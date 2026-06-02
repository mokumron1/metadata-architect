"""
CI/CD Gate endpoints.

Gate 1 — Context-First: rejects pipeline assets that have no registered
          Statement of Intent.  Blocks deployment until metadata is
          authored and approved.

Gate 2 — Jargon Scrubber: runs the JargonScrubber agent against a
          supplied SoI text.  Returns the violation list so CI/CD
          pipelines can fail on non-compliant prose.

Both endpoints require the X-Gate-API-Key header to authenticate the
calling CI/CD system.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from metadata_architect.config import get_settings
from metadata_architect.database import get_db
from metadata_architect.middleware.rate_limit import check_gate_rate_limit
from metadata_architect.models.asset_registry import Asset, WorkflowStatus
from metadata_architect.observability.tracing import get_tracer

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/gates",
    tags=["ci-cd-gates"],
    dependencies=[Depends(check_gate_rate_limit)],
)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def _require_gate_key(
    x_gate_api_key: Annotated[str | None, Header()] = None,
) -> str:
    settings = get_settings()
    if not x_gate_api_key or x_gate_api_key != settings.gate_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Gate-API-Key header.",
        )
    return x_gate_api_key


GateAuth = Annotated[str, Depends(_require_gate_key)]


# ---------------------------------------------------------------------------
# Gate 1 — Context-First
# ---------------------------------------------------------------------------

class ContextFirstRequest(BaseModel):
    asset_name: str = Field(..., description="Fully-qualified asset name, e.g. finance.global_revenue_v1")
    source_system: str | None = Field(None, description="Source system identifier, e.g. 'postgres'")


class ContextFirstResponse(BaseModel):
    asset_name: str
    passed: bool
    status: str  # "APPROVED" | "PENDING_REVIEW" | "NOT_REGISTERED" | "REJECTED"
    workflow_status: str | None = None
    tdk_score: float | None = None
    message: str


@router.post(
    "/context-first",
    response_model=ContextFirstResponse,
    summary="Gate 1 — Context-First: verify asset has an approved SoI",
)
async def context_first_gate(
    body: ContextFirstRequest,
    _: GateAuth,
    db: AsyncSession = Depends(get_db),
) -> ContextFirstResponse:
    """
    Blocks CI/CD pipelines that attempt to deploy an asset with no
    registered or approved Statement of Intent.

    Returns 200 with `passed=True` only when the asset has at least one
    workflow in SME_APPROVED state.  All other states (including absent
    records) return 200 with `passed=False` so the CI/CD runner can
    distinguish a gate failure from an API error.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span("gate.context_first") as span:
        span.set_attribute("gate.asset_name", body.asset_name)
        span.set_attribute("gate.source_system", body.source_system or "")

    query = (
        select(Asset)
        .where(Asset.asset_name == body.asset_name)
        .options(
            selectinload(Asset.workflows),
            selectinload(Asset.tdk_scores),
        )
    )
    if body.source_system:
        query = query.where(Asset.source_system == body.source_system)

    result = await db.execute(query)
    asset: Asset | None = result.scalars().first()

    if asset is None:
        return ContextFirstResponse(
            asset_name=body.asset_name,
            passed=False,
            status="NOT_REGISTERED",
            message=(
                f"Asset '{body.asset_name}' has no record in the Metadata Architect registry. "
                "Register the asset and obtain SME approval before deploying."
            ),
        )

    approved = [w for w in asset.workflows if w.status == WorkflowStatus.SME_APPROVED]
    if approved:
        return ContextFirstResponse(
            asset_name=body.asset_name,
            passed=True,
            status="APPROVED",
            workflow_status=WorkflowStatus.SME_APPROVED.value,
            tdk_score=asset.current_tdk_score,
            message="Asset has an approved Statement of Intent. Gate passed.",
        )

    # Has a record but no approval — determine most descriptive status
    pending = [w for w in asset.workflows if w.status == WorkflowStatus.AWAITING_SME_AUDIT]
    rejected = [w for w in asset.workflows if w.status == WorkflowStatus.SME_REJECTED]
    orphaned = [w for w in asset.workflows if w.status == WorkflowStatus.ORPHANED]

    if pending:
        gate_status = "PENDING_REVIEW"
        msg = (
            "Asset is awaiting SME review. Gate blocked until the SME approves "
            "the Statement of Intent."
        )
        wf_status = WorkflowStatus.AWAITING_SME_AUDIT.value
    elif rejected:
        gate_status = "REJECTED"
        msg = "Asset Statement of Intent was rejected by an SME. Revise and resubmit."
        wf_status = WorkflowStatus.SME_REJECTED.value
    elif orphaned:
        gate_status = "ORPHANED"
        msg = "Asset SLA expired without SME review. Recertification is required."
        wf_status = WorkflowStatus.ORPHANED.value
    else:
        gate_status = "NOT_REGISTERED"
        msg = "Asset exists but has no active workflow. Trigger metadata drafting first."
        wf_status = None

    return ContextFirstResponse(
        asset_name=body.asset_name,
        passed=False,
        status=gate_status,
        workflow_status=wf_status,
        tdk_score=asset.current_tdk_score,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Gate 2 — Jargon Scrubber
# ---------------------------------------------------------------------------

class JargonScrubRequest(BaseModel):
    soi_text: str = Field(
        ...,
        min_length=20,
        description="The Statement of Intent prose to evaluate.",
    )
    glossary: dict[str, str] = Field(
        default_factory=dict,
        description="Optional project-level glossary {term: definition} to whitelist known terms.",
    )
    fail_on_violation: bool = Field(
        True,
        description="When True, any violation causes `passed=False`. "
                    "Set False to surface warnings without blocking.",
    )


class ViolationItem(BaseModel):
    term: str
    char_position: int
    rule_violated: str
    suggestion: str


class JargonScrubResponse(BaseModel):
    passed: bool
    is_compliant: bool
    violation_count: int
    violations: list[ViolationItem]
    sentence_count: int
    longest_sentence_words: int
    model_used: str
    message: str


@router.post(
    "/jargon-scrub",
    response_model=JargonScrubResponse,
    summary="Gate 2 — Jargon Scrubber: validate SoI against ISO 24495-1",
)
async def jargon_scrub_gate(
    body: JargonScrubRequest,
    _: GateAuth,
) -> JargonScrubResponse:
    """
    Runs the JargonScrubber agent against the supplied Statement of Intent.

    Returns a violation list.  When `fail_on_violation=True` (default),
    any violation sets `passed=False` so the CI/CD pipeline can fail the
    build.
    """
    from metadata_architect.agents.jargon_scrubber import JargonScrubber

    tracer = get_tracer()
    with tracer.start_as_current_span("gate.jargon_scrub") as span:
        span.set_attribute("gate.soi_length", len(body.soi_text))
        span.set_attribute("gate.fail_on_violation", body.fail_on_violation)

    scrubber = JargonScrubber(glossary=body.glossary)
    result = scrubber.scrub(body.soi_text)

    passed = result.is_compliant if body.fail_on_violation else True

    if result.is_compliant:
        msg = "Statement of Intent is ISO 24495-1 compliant. Gate passed."
    else:
        count = len(result.violations)
        msg = (
            f"Statement of Intent has {count} violation(s). "
            "Review and resolve before merging."
        )

    return JargonScrubResponse(
        passed=passed,
        is_compliant=result.is_compliant,
        violation_count=len(result.violations),
        violations=[
            ViolationItem(
                term=v.term,
                char_position=v.char_position,
                rule_violated=v.rule_violated,
                suggestion=v.suggestion,
            )
            for v in result.violations
        ],
        sentence_count=result.sentence_count,
        longest_sentence_words=result.longest_sentence_words,
        model_used=result.model_used,
        message=msg,
    )
