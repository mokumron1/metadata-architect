"""
Third-Party Onboarding Suite — API router with ISO 27001 audit trail.

Every request is assigned an X-Request-ID that links all audit events
for that request. The AuditLogger writes to both the structured log
stream and the audit_log database table.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metadata_architect.audit.events import Interface, Outcome
from metadata_architect.audit.logger import AuditLogger
from metadata_architect.database import get_db
from metadata_architect.models.onboarding import (
    ColumnDefinition,
    DataContractRecord,
    SecurityPassportRecord,
)
from metadata_architect.onboarding.interview_bot import InterviewAnswers, InterviewBot
from metadata_architect.onboarding.metadata_drafter import ColumnContext, MetadataDrafter
from metadata_architect.onboarding.security_triage import SecurityTriageAgent, _regex_scan
from metadata_architect.schemas.onboarding_schemas import (
    ColumnApprovalRequest,
    ColumnApprovalResponse,
    ColumnContextRequest,
    ContractActivationRequest,
    ContractActivationResponse,
    DataContractResponse,
    InterviewRequest,
    MetadataDraftBatchRequest,
    MetadataDraftBatchResponse,
    MetadataDraftResponse,
    RiskSignalResponse,
    SchemaHintResponse,
    SecurityPassportResponse,
    SecurityReviewRequest,
    SecurityTriageRequest,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["third-party-onboarding"])

_now = lambda: datetime.now(timezone.utc)


def _request_id(request: Request) -> str:
    # Prefer the ID already computed (and bound to structlog) by RequestIDMiddleware.
    rid = getattr(request.state, "request_id", None)
    if rid:
        return rid
    return request.headers.get("x-request-id", str(uuid.uuid4()))


# ===========================================================================
# Interface 1 — AI Metadata Drafter
# ===========================================================================

@router.post(
    "/draft-metadata",
    response_model=MetadataDraftResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Interface 1 — Draft a plain-language definition for one column",
)
async def draft_metadata(
    body: ColumnContextRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MetadataDraftResponse:
    req_id = _request_id(request)
    audit = AuditLogger(
        db=db, request_id=req_id,
        interface=Interface.METADATA_DRAFTER,
        asset_name=body.asset_name or body.column_name,
    )

    # ── Milestone 1: request received ─────────────────────────────────
    await audit.event("MD_REQUEST_RECEIVED", details={
        "column_name": body.column_name,
        "data_type":   body.data_type,
        "asset_name":  body.asset_name,
        "source_system": body.source_system,
        "sample_count": len(body.sample_values),
    })

    drafter = MetadataDrafter()
    col = ColumnContext(
        column_name=body.column_name,
        data_type=body.data_type,
        sample_values=body.sample_values,
        table_context_hint=body.table_context_hint,
        source_system=body.source_system,
    )

    # ── Milestone 2: LLM call ─────────────────────────────────────────
    await audit.event("MD_LLM_CALL_STARTED", outcome=Outcome.PENDING, details={
        "model": drafter._model,
        "table_context_hint": body.table_context_hint,
    })

    t = audit.timer()
    try:
        with t:
            result = await asyncio.to_thread(drafter.draft, col)
    except Exception as exc:
        await audit.event("MD_LLM_CALL_FAILED", outcome=Outcome.FAILURE, details={
            "error": str(exc),
        })
        await db.commit()
        raise HTTPException(status_code=502, detail=f"LLM drafting failed: {exc}") from exc

    await audit.event("MD_LLM_CALL_COMPLETED", duration_ms=t.ms, details={
        "model_used":      result.model_used,
        "confidence":      result.confidence,
        "readability_grade": result.readability_grade,
        "input_tokens":    result.input_tokens,
        "output_tokens":   result.output_tokens,
        "cache_hit":       result.cache_hit,
    })

    # ── Milestone 3: linguistic audit ─────────────────────────────────
    await audit.event("MD_LINGUISTIC_AUDIT_STARTED")
    ling = result.linguistic_report
    if ling.is_compliant:
        await audit.event("MD_LINGUISTIC_AUDIT_PASSED", details={
            "sentence_count":        ling.sentence_count,
            "longest_sentence_words": ling.longest_sentence_words,
        })
    else:
        await audit.event(
            "MD_LINGUISTIC_AUDIT_FAILED",
            outcome=Outcome.FAILURE,
            details={
                "violation_count":  len(ling.violations),
                "passive_voice":    len(ling.passive_fragments_found),
                "non_b1_words":     ling.non_b1_words_found,
                "long_sentences":   ling.longest_sentence_words,
            },
        )

    # ── Milestone 4: auto-approval decision ───────────────────────────
    if result.is_auto_approvable:
        await audit.event("MD_AUTO_APPROVAL_GRANTED", details={
            "confidence":      result.confidence,
            "readability_grade": result.readability_grade,
        })
    else:
        await audit.event(
            "MD_AUTO_APPROVAL_DENIED",
            outcome=Outcome.SKIPPED,
            details={
                "reasons": [
                    *(["confidence_below_threshold"] if result.confidence < 0.80 else []),
                    *(["grade_above_9"] if result.readability_grade > 9.0 else []),
                    *(["linguistic_violations"] if not ling.is_compliant else []),
                ],
            },
        )

    # ── Milestone 5: persist draft ────────────────────────────────────
    record = ColumnDefinition(
        asset_name=body.asset_name or body.column_name,
        column_name=result.column_name,
        data_type=body.data_type,
        source_system=body.source_system or None,
        business_definition=result.business_definition,
        plain_name=result.plain_name,
        usage_examples=result.usage_examples,
        warnings=result.warnings,
        confidence=result.confidence,
        readability_grade=result.readability_grade,
        linguistic_compliant=ling.is_compliant,
        sme_status="pending",
        model_used=result.model_used,
    )
    db.add(record)
    await db.flush()

    await audit.event("MD_DRAFT_PERSISTED", details={
        "record_id":  str(record.id),
        "sme_status": record.sme_status,
    })

    await db.commit()
    await db.refresh(record)

    return MetadataDraftResponse(
        column_name=result.column_name,
        business_definition=result.business_definition,
        plain_name=result.plain_name,
        usage_examples=result.usage_examples,
        warnings=result.warnings,
        confidence=result.confidence,
        readability_grade=result.readability_grade,
        linguistic_compliant=ling.is_compliant,
        linguistic_violations=[
            {"rule": v.rule, "text": v.text, "suggestion": v.suggestion}
            for v in ling.violations
        ],
        is_auto_approvable=result.is_auto_approvable,
        model_used=result.model_used,
        record_id=record.id,
    )


@router.post(
    "/draft-metadata/batch",
    response_model=MetadataDraftBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Interface 1 — Batch draft definitions for up to 50 columns",
)
async def draft_metadata_batch(
    body: MetadataDraftBatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MetadataDraftBatchResponse:
    req_id = _request_id(request)
    audit = AuditLogger(
        db=db, request_id=req_id,
        interface=Interface.METADATA_DRAFTER,
        asset_name=body.asset_name,
    )

    await audit.event("MD_BATCH_STARTED", details={
        "asset_name":   body.asset_name,
        "column_count": len(body.columns),
    })

    drafter = MetadataDrafter()
    cols = [
        ColumnContext(
            column_name=c.column_name, data_type=c.data_type,
            sample_values=c.sample_values, table_context_hint=c.table_context_hint,
            source_system=c.source_system,
        )
        for c in body.columns
    ]

    await audit.event("MD_LLM_CALL_STARTED", outcome=Outcome.PENDING, details={
        "model": drafter._model, "batch_size": len(cols),
    })

    t = audit.timer()
    try:
        with t:
            results = await asyncio.to_thread(drafter.draft_batch, cols)
    except Exception as exc:
        await audit.event("MD_LLM_CALL_FAILED", outcome=Outcome.FAILURE,
                          details={"error": str(exc)})
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await audit.event("MD_LLM_CALL_COMPLETED", duration_ms=t.ms, details={
        "drafted_count": len(results),
    })

    if len(results) != len(body.columns):
        raise HTTPException(
            status_code=502,
            detail=f"Batch drafting returned {len(results)} results for {len(body.columns)} columns.",
        )

    drafts: list[MetadataDraftResponse] = []
    auto_count = 0
    for col_req, result in zip(body.columns, results):
        ling = result.linguistic_report
        record = ColumnDefinition(
            asset_name=body.asset_name, column_name=result.column_name,
            data_type=col_req.data_type, source_system=col_req.source_system or None,
            business_definition=result.business_definition, plain_name=result.plain_name,
            usage_examples=result.usage_examples, warnings=result.warnings,
            confidence=result.confidence, readability_grade=result.readability_grade,
            linguistic_compliant=ling.is_compliant, sme_status="pending",
            model_used=result.model_used,
        )
        db.add(record)

        if result.is_auto_approvable:
            auto_count += 1
        code = "MD_AUTO_APPROVAL_GRANTED" if result.is_auto_approvable else "MD_AUTO_APPROVAL_DENIED"
        await audit.event(code, details={
            "column_name": result.column_name,
            "confidence":  result.confidence,
            "record_id":   str(record.id),
        })

        drafts.append(MetadataDraftResponse(
            column_name=result.column_name,
            business_definition=result.business_definition,
            plain_name=result.plain_name,
            usage_examples=result.usage_examples,
            warnings=result.warnings,
            confidence=result.confidence,
            readability_grade=result.readability_grade,
            linguistic_compliant=ling.is_compliant,
            linguistic_violations=[
                {"rule": v.rule, "text": v.text, "suggestion": v.suggestion}
                for v in ling.violations
            ],
            is_auto_approvable=result.is_auto_approvable,
            model_used=result.model_used,
            record_id=record.id,
        ))

    await audit.event("MD_BATCH_COMPLETED", details={
        "total":         len(drafts),
        "auto_approvable": auto_count,
        "elapsed_ms":    audit.elapsed_ms(),
    })

    await db.commit()
    return MetadataDraftBatchResponse(
        asset_name=body.asset_name,
        drafts=drafts,
        auto_approvable_count=auto_count,
        total_columns=len(drafts),
    )


@router.patch(
    "/draft-metadata/{record_id}/review",
    response_model=ColumnApprovalResponse,
    summary="Interface 1 — SME One-Click Approve / Edit / Reject",
)
async def review_column_draft(
    record_id: uuid.UUID,
    body: ColumnApprovalRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ColumnApprovalResponse:
    req_id = _request_id(request)

    result = await db.execute(
        select(ColumnDefinition).where(ColumnDefinition.id == record_id)
    )
    record: ColumnDefinition | None = result.scalars().first()
    if not record:
        raise HTTPException(status_code=404, detail="Column definition record not found.")

    audit = AuditLogger(
        db=db, request_id=req_id,
        interface=Interface.METADATA_DRAFTER,
        asset_name=record.asset_name,
    )

    if body.action == "edited" and not body.edited_definition:
        raise HTTPException(status_code=422, detail="Provide 'edited_definition' when action='edited'.")

    # ── Milestone: SME review decision ────────────────────────────────
    event_code = {
        "approved": "MD_SME_APPROVED",
        "edited":   "MD_SME_EDITED",
        "rejected": "MD_SME_REJECTED",
    }[body.action]

    record.sme_status = body.action
    record.reviewed_at = _now()
    if body.action == "edited":
        record.sme_edited_definition = body.edited_definition

    await audit.event(event_code, details={
        "record_id":    str(record_id),
        "column_name":  record.column_name,
        "action":       body.action,
        "written_to_glossary": body.action in ("approved", "edited"),
        **({"edited_length": len(body.edited_definition)} if body.edited_definition else {}),
    })

    await db.commit()
    await db.refresh(record)

    final_def = record.sme_edited_definition or record.business_definition
    return ColumnApprovalResponse(
        record_id=record.id,
        column_name=record.column_name,
        sme_status=record.sme_status,
        final_definition=final_def,
        written_to_glossary=body.action in ("approved", "edited"),
    )


# ===========================================================================
# Interface 2 — Intelligent Security Triage
# ===========================================================================

@router.post(
    "/triage-security",
    response_model=SecurityPassportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Interface 2 — Classify security risk and generate Security Passport",
)
async def triage_security(
    body: SecurityTriageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SecurityPassportResponse:
    req_id = _request_id(request)
    audit = AuditLogger(
        db=db, request_id=req_id,
        interface=Interface.SECURITY_TRIAGE,
        asset_name=body.asset_name,
    )

    # ── Milestone 1: request received ─────────────────────────────────
    await audit.event("ST_REQUEST_RECEIVED", details={
        "asset_name":       body.asset_name,
        "payload_length":   len(body.payload_sample),
        "field_count":      len(body.field_metadata),
    })

    # ── Milestone 2: fingerprint ──────────────────────────────────────
    fingerprint = hashlib.sha256(body.payload_sample[:4096].encode()).hexdigest()
    await audit.event("ST_PAYLOAD_FINGERPRINTED", details={
        "fingerprint": fingerprint,
        "bytes_hashed": min(len(body.payload_sample), 4096),
    })

    # ── Milestone 3: regex scan ───────────────────────────────────────
    await audit.event("ST_REGEX_SCAN_STARTED")

    t = audit.timer()
    with t:
        regex_signals = _regex_scan(body.payload_sample)

    await audit.event("ST_REGEX_SCAN_COMPLETED", duration_ms=t.ms, details={
        "signal_count": len(regex_signals),
        "signal_types": list({s.signal_type for s in regex_signals}),
        "patterns_matched": [s.pattern_matched for s in regex_signals],
    })

    # ── Decision: critical fast-path vs. semantic analysis ────────────
    has_critical = any(s.severity == "critical" for s in regex_signals)
    if has_critical:
        await audit.event("ST_CRITICAL_SIGNAL_DETECTED", details={
            "critical_signals": [
                {"pattern": s.pattern_matched, "type": s.signal_type}
                for s in regex_signals if s.severity == "critical"
            ],
        })
    else:
        await audit.event("ST_SEMANTIC_ANALYSIS_STARTED", outcome=Outcome.PENDING, details={
            "pre_signal_count": len(regex_signals),
        })

    # ── Milestone 4: run triage agent (calls Claude if not fast-path) ─
    agent = SecurityTriageAgent()
    t2 = audit.timer()
    try:
        with t2:
            passport = await asyncio.to_thread(
                agent.triage,
                body.asset_name,
                body.payload_sample,
                body.field_metadata or None,
            )
    except Exception as exc:
        await audit.event("ST_SEMANTIC_ANALYSIS_FAILED", outcome=Outcome.FAILURE,
                          details={"error": str(exc)})
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not has_critical:
        await audit.event("ST_SEMANTIC_ANALYSIS_COMPLETED", duration_ms=t2.ms, details={
            "model_used":  passport.model_used,
            "cache_hit":   passport.cache_hit,
            "input_tokens": passport.input_tokens,
            "output_tokens": passport.output_tokens,
        })

    # ── Milestone 5: classification decided ──────────────────────────
    await audit.event("ST_CLASSIFICATION_DECIDED", details={
        "classification": passport.classification.value,
        "confidence":     passport.confidence,
        "total_signals":  len(passport.risk_signals),
        "regulatory_frameworks": passport.regulatory_frameworks,
    })

    # ── Decision: quarantine ──────────────────────────────────────────
    gate_status = "quarantined" if passport.quarantine_recommended else "pending_review"
    if passport.quarantine_recommended:
        await audit.event("ST_QUARANTINE_TRIGGERED", details={
            "reason": passport.quarantine_reason,
            "remediation_steps": passport.remediation_steps,
        })
        await audit.event("ST_GATE_BLOCKED", details={
            "asset_name":     body.asset_name,
            "classification": passport.classification.value,
        })

    # ── Milestone 6: persist passport ─────────────────────────────────
    record = SecurityPassportRecord(
        asset_name=passport.asset_name,
        classification=passport.classification.value,
        confidence=passport.confidence,
        risk_signals=[
            {"field": s.field, "signal_type": s.signal_type,
             "pattern_matched": s.pattern_matched, "sample_evidence": s.sample_evidence,
             "severity": s.severity}
            for s in passport.risk_signals
        ],
        quarantine_recommended=passport.quarantine_recommended,
        quarantine_reason=passport.quarantine_reason,
        remediation_steps=passport.remediation_steps,
        regulatory_frameworks=passport.regulatory_frameworks,
        payload_fingerprint=passport.payload_fingerprint,
        gate_status=gate_status,
        model_used=passport.model_used,
    )
    db.add(record)
    await db.flush()

    await audit.event("ST_PASSPORT_PERSISTED", details={
        "record_id":   str(record.id),
        "gate_status": gate_status,
    })

    await db.commit()
    await db.refresh(record)

    return SecurityPassportResponse(
        asset_name=passport.asset_name,
        classification=passport.classification.value,
        confidence=passport.confidence,
        risk_signals=[
            RiskSignalResponse(
                field=s.field, signal_type=s.signal_type,
                pattern_matched=s.pattern_matched, sample_evidence=s.sample_evidence,
                severity=s.severity,
            )
            for s in passport.risk_signals
        ],
        quarantine_recommended=passport.quarantine_recommended,
        quarantine_reason=passport.quarantine_reason,
        remediation_steps=passport.remediation_steps,
        regulatory_frameworks=passport.regulatory_frameworks,
        payload_fingerprint=passport.payload_fingerprint,
        gate_status=gate_status,
        record_id=record.id,
    )


@router.patch(
    "/triage-security/{record_id}/review",
    response_model=SecurityPassportResponse,
    summary="Interface 2 — Security team clears or confirms quarantine",
)
async def review_security_passport(
    record_id: uuid.UUID,
    body: SecurityReviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SecurityPassportResponse:
    req_id = _request_id(request)

    result = await db.execute(
        select(SecurityPassportRecord).where(SecurityPassportRecord.id == record_id)
    )
    record: SecurityPassportRecord | None = result.scalars().first()
    if not record:
        raise HTTPException(status_code=404, detail="Security passport record not found.")

    audit = AuditLogger(
        db=db, request_id=req_id,
        interface=Interface.SECURITY_TRIAGE,
        asset_name=record.asset_name,
    )

    event_code = "ST_GATE_CLEARED" if body.action == "cleared" else "ST_QUARANTINE_CONFIRMED"
    record.gate_status = body.action
    record.reviewed_at = _now()

    await audit.event(event_code, details={
        "record_id":     str(record_id),
        "action":        body.action,
        "reviewer_notes": body.reviewer_notes,
        "classification": record.classification,
    })

    await db.commit()
    await db.refresh(record)

    return SecurityPassportResponse(
        asset_name=record.asset_name,
        classification=record.classification,
        confidence=record.confidence,
        risk_signals=[RiskSignalResponse(**s) for s in record.risk_signals],
        quarantine_recommended=record.quarantine_recommended,
        quarantine_reason=record.quarantine_reason,
        remediation_steps=record.remediation_steps,
        regulatory_frameworks=record.regulatory_frameworks,
        payload_fingerprint=record.payload_fingerprint,
        gate_status=record.gate_status,
        record_id=record.id,
    )


# ===========================================================================
# Interface 3 — Interview Bot / Data Contract Generator
# ===========================================================================

@router.post(
    "/interview",
    response_model=DataContractResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Interface 3 — Convert NL vendor answers into an ODCS Data Contract",
)
async def run_interview(
    body: InterviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DataContractResponse:
    req_id = _request_id(request)
    audit = AuditLogger(
        db=db, request_id=req_id,
        interface=Interface.INTERVIEW_BOT,
        asset_name=body.asset_name,
    )

    # ── Milestone 1: request received ─────────────────────────────────
    await audit.event("IB_REQUEST_RECEIVED", details={
        "asset_name": body.asset_name,
        "owner":      body.owner,
        "answer_lengths": {
            "business_decision": len(body.answer_business_decision),
            "freshness":         len(body.answer_freshness),
            "mandatory_fields":  len(body.answer_mandatory_fields),
        },
    })

    # ── Milestone 2: LLM extraction ───────────────────────────────────
    bot = InterviewBot()
    answers = InterviewAnswers(
        asset_name=body.asset_name,
        answer_business_decision=body.answer_business_decision,
        answer_freshness=body.answer_freshness,
        answer_mandatory_fields=body.answer_mandatory_fields,
        owner=body.owner,
        support_contact=body.support_contact,
        additional_context=body.additional_context,
    )

    await audit.event("IB_LLM_EXTRACTION_STARTED", outcome=Outcome.PENDING, details={
        "model": bot._model,
    })

    t = audit.timer()
    try:
        with t:
            draft = await asyncio.to_thread(bot.generate_contract, answers)
    except Exception as exc:
        await audit.event("IB_LLM_EXTRACTION_FAILED", outcome=Outcome.FAILURE,
                          details={"error": str(exc)})
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await audit.event("IB_LLM_EXTRACTION_COMPLETED", duration_ms=t.ms, details={
        "model_used":    draft.model_used,
        "confidence":    draft.confidence,
        "input_tokens":  draft.input_tokens,
        "output_tokens": draft.output_tokens,
        "cache_hit":     draft.cache_hit,
    })

    # ── Milestone 3: SoI category mapped ─────────────────────────────
    await audit.event("IB_SOI_CATEGORY_MAPPED", details={
        "soi_category":       draft.soi_category,
        "mandatory_fields":   draft.mandatory_fields,
        "update_frequency":   draft.update_frequency,
        "freshness_max_age":  draft.freshness_max_age,
        "availability_sla":   draft.availability_sla,
    })

    # ── Milestone 4: YAML rendered & validated ────────────────────────
    await audit.event("IB_YAML_RENDERED", details={
        "yaml_length":    len(draft.contract_yaml),
        "schema_hints":   len(draft.schema_hints),
        "contract_id":    draft.contract_id,
    })

    # Check YAML validity
    try:
        from ruamel.yaml import YAML as _YAML
        import io
        _YAML().load(io.StringIO(draft.contract_yaml))
        await audit.event("IB_YAML_VALIDATION_PASSED")
    except Exception as exc:
        await audit.event("IB_YAML_VALIDATION_FAILED", outcome=Outcome.FAILURE,
                          details={"error": str(exc)})

    # ── Decision: clarification needed? ──────────────────────────────
    if draft.clarification_needed:
        await audit.event("IB_CLARIFICATION_NEEDED", outcome=Outcome.PENDING, details={
            "questions":  draft.clarification_needed,
            "confidence": draft.confidence,
        })

    # ── Milestone 5: gate readiness decision ─────────────────────────
    gate_code = "IB_GATE_READY" if draft.is_ready_for_gate else "IB_GATE_NOT_READY"
    await audit.event(gate_code, details={
        "confidence":          draft.confidence,
        "clarification_needed": draft.clarification_needed,
    })

    # ── Milestone 6: persist contract ─────────────────────────────────
    record = DataContractRecord(
        contract_id=draft.contract_id,
        asset_name=draft.asset_name,
        owner=body.owner,
        soi_category=draft.soi_category,
        business_decision=draft.business_decision,
        mandatory_fields=draft.mandatory_fields,
        update_frequency=draft.update_frequency,
        freshness_max_age=draft.freshness_max_age,
        retention_period=draft.retention_period,
        availability_sla=draft.availability_sla,
        quality_completeness=draft.quality_completeness,
        schema_hints=[
            {"field": h.field, "type": h.type, "required": h.required, "description": h.description}
            for h in draft.schema_hints
        ],
        contract_yaml=draft.contract_yaml,
        contract_json=draft.contract_json,
        confidence=draft.confidence,
        clarification_needed=draft.clarification_needed,
        linguistic_compliant=draft.linguistic_compliant,
        status="draft",
        model_used=draft.model_used,
    )
    db.add(record)
    await db.flush()

    await audit.event("IB_CONTRACT_PERSISTED", details={
        "record_id":   str(record.id),
        "contract_id": draft.contract_id,
        "status":      "draft",
        "version":     record.version,
        "elapsed_ms":  audit.elapsed_ms(),
    })

    await db.commit()
    await db.refresh(record)

    return DataContractResponse(
        contract_id=draft.contract_id,
        asset_name=draft.asset_name,
        soi_category=draft.soi_category,
        business_decision=draft.business_decision,
        mandatory_fields=draft.mandatory_fields,
        update_frequency=draft.update_frequency,
        freshness_max_age=draft.freshness_max_age,
        retention_period=draft.retention_period,
        availability_sla=draft.availability_sla,
        quality_completeness=draft.quality_completeness,
        schema_hints=[
            SchemaHintResponse(field=h.field, type=h.type, required=h.required, description=h.description)
            for h in draft.schema_hints
        ],
        confidence=draft.confidence,
        clarification_needed=draft.clarification_needed,
        is_ready_for_gate=draft.is_ready_for_gate,
        linguistic_compliant=draft.linguistic_compliant,
        contract_yaml=draft.contract_yaml,
        contract_json=draft.contract_json,
        model_used=draft.model_used,
        record_id=record.id,
    )


@router.patch(
    "/contracts/{record_id}/activate",
    response_model=ContractActivationResponse,
    summary="Interface 3 — Activate contract to unlock the Governance Entry Gate",
)
async def activate_contract(
    record_id: uuid.UUID,
    body: ContractActivationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ContractActivationResponse:
    req_id = _request_id(request)

    result = await db.execute(
        select(DataContractRecord).where(DataContractRecord.id == record_id)
    )
    record: DataContractRecord | None = result.scalars().first()
    if not record:
        raise HTTPException(status_code=404, detail="Data contract record not found.")

    audit = AuditLogger(
        db=db, request_id=req_id,
        interface=Interface.INTERVIEW_BOT,
        asset_name=record.asset_name,
    )

    event_map = {
        "activate":   "IB_CONTRACT_ACTIVATED",
        "supersede":  "IB_CONTRACT_SUPERSEDED",
        "terminate":  "IB_CONTRACT_TERMINATED",
    }
    _status_map = {
        "activate":  "active",
        "supersede": "superseded",
        "terminate": "terminated",
    }
    record.status = _status_map[body.action]
    if body.action == "activate":
        record.activated_at = _now()

    await audit.event(event_map[body.action], details={
        "record_id":   str(record_id),
        "contract_id": record.contract_id,
        "new_status":  record.status,
        "gate_unblocked": record.status == "active",
    })

    await db.commit()
    await db.refresh(record)

    return ContractActivationResponse(
        record_id=record.id,
        contract_id=record.contract_id,
        status=record.status,
        gate_unblocked=record.status == "active",
    )
