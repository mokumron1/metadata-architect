"""
SME Workflow Router — the HITL Review Portal API.

Endpoints:
  GET  /workflows                      List workflows (filterable by status)
  GET  /workflows/{id}                 Single workflow with asset + draft detail
  POST /workflows/{id}/approve         SME approves the draft as-is
  POST /workflows/{id}/edit            SME submits a corrected SoI + approves
  POST /workflows/{id}/reject          SME rejects (orphaned / redundant data)

Each action endpoint:
  1. Validates the JWT review token from the email link (or falls back to API key)
  2. Drives the state machine transition
  3. Persists a TdkScoreLog event
  4. Emits a YAML policy file (on approve / edit-approve)
  5. Queues the analyse_sme_edit Celery task (on edit)
  6. Sends a confirmation notification
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from metadata_architect.auth.tokens import TokenError, TokenService
from metadata_architect.catalog.push_adapter import CatalogPayload, CatalogPushDispatcher
from metadata_architect.config import get_settings
from metadata_architect.database import get_db
from metadata_architect.models.asset_registry import (
    Asset,
    InvalidTransitionError,
    SmeWorkflow,
    TdkScoreLog,
    TdkScoreEvent,
    WorkflowStatus,
)
from metadata_architect.notifications.base import NotificationPayload, NotificationType
from metadata_architect.notifications.dispatcher import NotificationDispatcher
from metadata_architect.policy.emitter import PolicyEmitter
from metadata_architect.scoring.tdk_calculator import TdkCalculator, TdkInputs

router = APIRouter(prefix="/workflows", tags=["workflows"])
DbDep = Annotated[AsyncSession, Depends(get_db)]

_token_svc = TokenService()
_emitter = PolicyEmitter()
_calculator = TdkCalculator()
_dispatcher = NotificationDispatcher()
_catalog = CatalogPushDispatcher()

_LOAD_FULL = [
    selectinload(SmeWorkflow.asset).selectinload(Asset.soi_drafts),
    selectinload(SmeWorkflow.asset).selectinload(Asset.tdk_scores),
    selectinload(SmeWorkflow.draft),
]


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ApproveRequest(BaseModel):
    review_token: str = Field(..., description="JWT from the Verification Pulse email")


class EditRequest(BaseModel):
    review_token: str
    corrected_soi: str = Field(..., min_length=20, max_length=500,
                               description="The SME's corrected Statement of Intent")
    edit_reason: str | None = Field(None, description="Brief note on what was changed and why")


class RejectRequest(BaseModel):
    review_token: str
    rejection_reason: str = Field(..., min_length=5,
                                  description="Why the asset should be orphaned or removed")


class WorkflowActionResponse(BaseModel):
    workflow_id: str
    asset_id: str
    asset_name: str
    new_status: str
    tdk_score: float
    policy_yaml: str | None = None
    message: str


# ---------------------------------------------------------------------------
# List + Get
# ---------------------------------------------------------------------------

@router.get("", response_model=dict)
async def list_workflows(
    db: DbDep,
    status_filter: WorkflowStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    query = select(SmeWorkflow).options(*_LOAD_FULL)
    if status_filter:
        query = query.where(SmeWorkflow.status == status_filter)
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    workflows = result.scalars().all()
    return {
        "page": page,
        "page_size": page_size,
        "items": [_workflow_summary(w) for w in workflows],
    }


@router.get("/{workflow_id}", response_model=dict)
async def get_workflow(workflow_id: uuid.UUID, db: DbDep) -> dict:
    workflow = await _get_workflow_or_404(db, workflow_id)
    return _workflow_detail(workflow)


# ---------------------------------------------------------------------------
# SME Actions
# ---------------------------------------------------------------------------

@router.post("/{workflow_id}/approve", response_model=WorkflowActionResponse)
async def approve_workflow(
    workflow_id: uuid.UUID,
    body: ApproveRequest,
    db: DbDep,
) -> WorkflowActionResponse:
    """SME certifies the AI-drafted SoI without changes."""
    workflow = await _get_workflow_or_404(db, workflow_id)
    sme_email = _validate_token(body.review_token, workflow_id)

    _transition(workflow, WorkflowStatus.SME_APPROVED, actioned_by=sme_email)

    draft = workflow.draft
    tdk_score = await _record_tdk_score(db, workflow, TdkScoreEvent.SME_APPROVED, sla_met=True)

    policy = await _emit_and_store_policy(workflow, draft, WorkflowStatus.SME_APPROVED.value, tdk_score)
    await db.commit()

    await _send_notification(
        payload=NotificationPayload(
            notification_type=NotificationType.APPROVAL_NOTICE,
            recipient_email=sme_email,
            asset_id=str(workflow.asset_id),
            asset_name=workflow.asset.asset_name,
            workflow_id=str(workflow.id),
            tdk_score=tdk_score,
        )
    )
    await _push_to_catalogs(policy, workflow)

    return WorkflowActionResponse(
        workflow_id=str(workflow.id),
        asset_id=str(workflow.asset_id),
        asset_name=workflow.asset.asset_name,
        new_status=WorkflowStatus.SME_APPROVED.value,
        tdk_score=tdk_score,
        policy_yaml=policy.raw_yaml,
        message="Asset certified. YAML policy emitted.",
    )


@router.post("/{workflow_id}/edit", response_model=WorkflowActionResponse)
async def edit_and_approve_workflow(
    workflow_id: uuid.UUID,
    body: EditRequest,
    db: DbDep,
) -> WorkflowActionResponse:
    """
    SME submits a corrected SoI, which is immediately certified.

    The original draft + edit diff are stored as training data.
    Transitions: AWAITING_SME_AUDIT → SME_EDITED → SME_APPROVED (two steps).
    """
    workflow = await _get_workflow_or_404(db, workflow_id)
    sme_email = _validate_token(body.review_token, workflow_id)

    draft = workflow.draft
    original_soi = draft.statement_of_intent

    # Record the edit diff on the draft
    edit_diff = _build_diff(original_soi, body.corrected_soi, body.edit_reason)
    draft.statement_of_intent = body.corrected_soi
    draft.sme_edit_diff = edit_diff

    # Drive state machine: AWAITING → EDITED → APPROVED
    _transition(workflow, WorkflowStatus.SME_EDITED, actioned_by=sme_email)
    _transition(workflow, WorkflowStatus.SME_APPROVED, actioned_by=sme_email)

    tdk_score = await _record_tdk_score(db, workflow, TdkScoreEvent.SME_EDITED, sla_met=True)

    policy = await _emit_and_store_policy(workflow, draft, WorkflowStatus.SME_APPROVED.value, tdk_score)
    await db.commit()

    # Queue offline edit analysis (training data pipeline — Phase 6)
    _queue_edit_analysis(str(workflow.asset_id), str(draft.id), edit_diff)

    await _send_notification(
        payload=NotificationPayload(
            notification_type=NotificationType.APPROVAL_NOTICE,
            recipient_email=sme_email,
            asset_id=str(workflow.asset_id),
            asset_name=workflow.asset.asset_name,
            workflow_id=str(workflow.id),
            tdk_score=tdk_score,
        )
    )
    await _push_to_catalogs(policy, workflow)

    return WorkflowActionResponse(
        workflow_id=str(workflow.id),
        asset_id=str(workflow.asset_id),
        asset_name=workflow.asset.asset_name,
        new_status=WorkflowStatus.SME_APPROVED.value,
        tdk_score=tdk_score,
        policy_yaml=policy.raw_yaml,
        message="Edit recorded and asset certified. YAML policy emitted.",
    )


@router.post("/{workflow_id}/reject", response_model=WorkflowActionResponse)
async def reject_workflow(
    workflow_id: uuid.UUID,
    body: RejectRequest,
    db: DbDep,
) -> WorkflowActionResponse:
    """SME marks the asset as orphaned or redundant."""
    workflow = await _get_workflow_or_404(db, workflow_id)
    sme_email = _validate_token(body.review_token, workflow_id)

    _transition(workflow, WorkflowStatus.SME_REJECTED, actioned_by=sme_email)

    # Store rejection reason on the draft
    if workflow.draft:
        workflow.draft.sme_edit_diff = f"REJECTED: {body.rejection_reason}"

    tdk_score = await _record_tdk_score(db, workflow, TdkScoreEvent.ORPHANED, sla_met=True)
    await db.commit()

    await _send_notification(
        payload=NotificationPayload(
            notification_type=NotificationType.REJECTION_NOTICE,
            recipient_email=workflow.context_authority,
            asset_id=str(workflow.asset_id),
            asset_name=workflow.asset.asset_name,
            workflow_id=str(workflow.id),
            tdk_score=tdk_score,
        )
    )

    return WorkflowActionResponse(
        workflow_id=str(workflow.id),
        asset_id=str(workflow.asset_id),
        asset_name=workflow.asset.asset_name,
        new_status=WorkflowStatus.SME_REJECTED.value,
        tdk_score=tdk_score,
        policy_yaml=None,
        message="Asset rejected. Marked as orphaned. No policy emitted.",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _get_workflow_or_404(db: AsyncSession, workflow_id: uuid.UUID) -> SmeWorkflow:
    result = await db.execute(
        select(SmeWorkflow).where(SmeWorkflow.id == workflow_id).options(*_LOAD_FULL)
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")
    return workflow


def _validate_token(token: str, workflow_id: uuid.UUID) -> str:
    """Returns the SME email on success, raises 401 on failure."""
    try:
        payload = _token_svc.verify_review_token(token)
    except TokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if payload.workflow_id != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token is not valid for this workflow.",
        )
    return payload.sme_email


def _transition(workflow: SmeWorkflow, target: WorkflowStatus, actioned_by: str) -> None:
    try:
        workflow.transition(target, actioned_by=actioned_by)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


async def _record_tdk_score(
    db: AsyncSession,
    workflow: SmeWorkflow,
    event_type: TdkScoreEvent,
    sla_met: bool,
) -> float:
    """Compute and persist a TDK score log entry. Returns the composite score."""
    draft = workflow.draft
    asset = workflow.asset

    # Read jargon violations from the draft's stored scrub result
    violations = 0
    if draft and draft.jargon_violations:
        violations = len(draft.jargon_violations.get("violations", []))

    soi_text = draft.statement_of_intent if draft else ""
    rl_score = draft.reading_level_score or 10.0 if draft else 10.0
    total_cols = len(asset.column_metadata.get("columns", [])) if asset.column_metadata else 1

    inputs = TdkInputs(
        reading_level_score=rl_score,
        jargon_violation_count=violations,
        statement_of_intent=soi_text,
        glossary_terms_used=0,
        total_columns=total_cols,
        context_authority_assigned=bool(workflow.context_authority),
        sla_met=sla_met,
        sme_approved=event_type in {TdkScoreEvent.SME_APPROVED, TdkScoreEvent.SME_EDITED},
    )
    breakdown = _calculator.compute(inputs, sla_breached=False)

    log_entry = TdkScoreLog(
        asset_id=workflow.asset_id,
        clarity_score=breakdown.clarity_score,
        ownership_score=breakdown.ownership_score,
        composite_score=breakdown.composite_score,
        score_reason=breakdown.score_reason,
        event_type=event_type,
    )
    db.add(log_entry)
    return breakdown.composite_score


async def _emit_and_store_policy(
    workflow: SmeWorkflow,
    draft,
    verification_status: str,
    tdk_score: float,
) -> object:
    """Emit YAML policy and upload to MinIO. Upload failures are non-fatal."""
    doc = _emitter.emit(
        asset_id=workflow.asset_id,
        asset_name=workflow.asset.asset_name,
        statement_of_intent=draft.statement_of_intent if draft else "",
        clarity_standard=draft.clarity_standard if draft else "ISO-24495-1-Compliant",
        reading_level=draft.reading_level or "B1 / 9th Grade" if draft else "Unknown",
        context_authority=workflow.context_authority,
        tdk_score=tdk_score,
        verification_status=verification_status,
        workflow_id=workflow.id,
        draft_version=draft.version if draft else 1,
        jargon_compliant=(
            draft.jargon_violations.get("is_compliant", True)
            if draft and draft.jargon_violations else True
        ),
    )
    await _emitter.upload(doc, draft_version=draft.version if draft else 1)
    return doc


def _build_diff(original: str, corrected: str, reason: str | None) -> str:
    lines = [
        "--- original",
        "+++ corrected",
        f"-{original}",
        f"+{corrected}",
    ]
    if reason:
        lines.append(f"# Reason: {reason}")
    return "\n".join(lines)


def _queue_edit_analysis(asset_id: str, draft_id: str, edit_diff: str) -> None:
    try:
        from metadata_architect.workers.tasks import analyse_sme_edit
        analyse_sme_edit.delay(asset_id, draft_id, edit_diff)
    except Exception:
        pass  # Celery not running in test/dev — non-critical


async def _send_notification(payload: NotificationPayload) -> None:
    try:
        await _dispatcher.dispatch(payload)
    except Exception:
        pass  # Notification failure must never break the action endpoint


async def _push_to_catalogs(policy, workflow: SmeWorkflow) -> None:
    """Push approved metadata to DataHub / Collibra. Non-fatal."""
    try:
        catalog_payload = CatalogPayload(
            asset_name=policy.asset_name,
            asset_uuid=policy.asset_id,
            statement_of_intent=policy.statement_of_intent,
            tdk_score=policy.tdk_score,
            reading_level=policy.reading_level,
            context_authority=policy.context_authority,
            certified_at=policy.certified_at,
            verification_status=policy.verification_status,
        )
        await _catalog.dispatch(catalog_payload)
    except Exception:
        pass


def _workflow_summary(w: SmeWorkflow) -> dict:
    return {
        "workflow_id": str(w.id),
        "asset_id": str(w.asset_id),
        "asset_name": w.asset.asset_name if w.asset else None,
        "status": w.status.value,
        "context_authority": w.context_authority,
        "sla_deadline_at": w.sla_deadline_at.isoformat() if w.sla_deadline_at else None,
        "sla_breach_count": w.sla_breach_count,
        "created_at": w.created_at.isoformat(),
    }


def _workflow_detail(w: SmeWorkflow) -> dict:
    summary = _workflow_summary(w)
    if w.draft:
        summary["draft"] = {
            "draft_id": str(w.draft.id),
            "version": w.draft.version,
            "statement_of_intent": w.draft.statement_of_intent,
            "reading_level": w.draft.reading_level,
            "reading_level_score": w.draft.reading_level_score,
            "tdk_initial_score": w.draft.tdk_initial_score,
            "jargon_violations": w.draft.jargon_violations,
            "model_used": w.draft.model_used,
            "generated_at": w.draft.generated_at.isoformat(),
            "sme_edit_diff": w.draft.sme_edit_diff,
        }
    return summary
