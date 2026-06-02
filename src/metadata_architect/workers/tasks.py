"""
Celery tasks for the Metadata Architect pipeline.

draft_asset_metadata         — end-to-end pipeline: parse → draft → scrub → score → persist
run_sla_monitor              — Celery Beat job: scans for SLA breaches, orphans assets
dispatch_orphan_notice       — sends Orphan Notice notifications
analyse_sme_edit             — offline edit categorisation for training data (Phase 6)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from celery import Task

from metadata_architect.workers.celery_app import celery_app

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task: draft_asset_metadata
# ---------------------------------------------------------------------------

@celery_app.task(
    name="metadata_architect.workers.tasks.draft_asset_metadata",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def draft_asset_metadata(self: Task, asset_id: str) -> dict:
    """
    Full drafting pipeline for a single asset.

    Steps:
      1. Load asset from DB (sync session via asyncio.run)
      2. Parse DDL → ParsedSchema
      3. Draft SoI (SoIDrafter — may escalate to Opus)
      4. Scrub for jargon violations (JargonScrubber)
      5. Validate reading level (ReadingLevelValidator)
      6. Compute initial TDK score (TdkCalculator)
      7. Persist SoIDraft + TdkScoreLog records
      8. Update SmeWorkflow with real draft_id + SLA deadline
      9. Return summary dict
    """
    try:
        return asyncio.run(_run_drafting_pipeline(uuid.UUID(asset_id)))
    except Exception as exc:
        log.exception("draft_asset_metadata.failed", extra={"asset_id": asset_id})
        raise self.retry(exc=exc)


async def _run_drafting_pipeline(asset_id: uuid.UUID) -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from metadata_architect.config import get_settings
    from metadata_architect.models.asset_registry import (
        Asset, AssetType, SoIDraft, SmeWorkflow, TdkScoreLog, TdkScoreEvent, WorkflowStatus,
    )
    from metadata_architect.parsers.schema_parser import SchemaParser, SchemaParseError
    from metadata_architect.agents.soi_drafter import SoIDrafter
    from metadata_architect.agents.jargon_scrubber import JargonScrubber
    from metadata_architect.agents.reading_level import ReadingLevelValidator
    from metadata_architect.scoring.tdk_calculator import TdkCalculator, TdkInputs

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        # 1. Load asset
        result = await db.execute(
            select(Asset)
            .where(Asset.id == asset_id)
            .options(
                selectinload(Asset.soi_drafts),
                selectinload(Asset.workflows),
                selectinload(Asset.tdk_scores),
            )
        )
        asset = result.scalar_one_or_none()
        if asset is None:
            raise ValueError(f"Asset {asset_id} not found.")

        if not asset.raw_ddl:
            raise ValueError(f"Asset {asset_id} has no DDL — cannot draft SoI.")

        # 2. Parse DDL
        dialect = _dialect_from_source(asset.source_system)
        try:
            parser = SchemaParser(dialect=dialect)
            schema = parser.parse(asset.raw_ddl)
        except SchemaParseError as exc:
            raise ValueError(f"DDL parse failed for asset {asset_id}: {exc}") from exc

        # 3. Draft SoI
        drafter = SoIDrafter(glossary=_load_glossary())
        draft_result = drafter.draft(
            schema,
            lineage_context=_extract_lineage(asset),
            asset_type=asset.asset_type.value,
        )

        # 4. Jargon scrub
        scrubber = JargonScrubber(glossary=_load_glossary())
        scrub_result = scrubber.scrub(draft_result.statement_of_intent)

        # 5. Reading level validation
        validator = ReadingLevelValidator()
        rl_result = validator.validate(draft_result.statement_of_intent)

        # 6. Compute initial TDK score
        context_authority = _get_context_authority(asset)
        calculator = TdkCalculator()
        tdk_inputs = TdkInputs(
            reading_level_score=rl_result.estimated_grade_level,
            jargon_violation_count=len(scrub_result.violations),
            statement_of_intent=draft_result.statement_of_intent,
            glossary_terms_used=len(draft_result.glossary_terms_used),
            total_columns=len(schema.columns),
            context_authority_assigned=bool(context_authority),
            sla_met=False,           # SLA not yet evaluated
            sme_approved=False,      # pending SME action
        )
        tdk_breakdown = calculator.compute(tdk_inputs, sla_breached=False)

        # 7. Determine next version number
        next_version = max((d.version for d in asset.soi_drafts), default=0) + 1

        # 8. Persist SoIDraft
        soi_draft = SoIDraft(
            asset_id=asset_id,
            version=next_version,
            statement_of_intent=draft_result.statement_of_intent,
            clarity_standard="ISO-24495-1-Compliant" if scrub_result.is_compliant else "ISO-24495-1-Violations-Present",
            reading_level=rl_result.reading_level_label,
            reading_level_score=rl_result.estimated_grade_level,
            jargon_violations={
                "violations": [v.__dict__ for v in scrub_result.violations],
                "is_compliant": scrub_result.is_compliant,
                "sentence_count": scrub_result.sentence_count,
                "longest_sentence_words": scrub_result.longest_sentence_words,
            },
            tdk_initial_score=tdk_breakdown.composite_score,
            model_used=draft_result.model_used,
            prompt_tokens=draft_result.input_tokens,
            completion_tokens=draft_result.output_tokens,
            cache_hit=draft_result.cache_hit,
        )
        db.add(soi_draft)
        await db.flush()

        # 9. Persist initial TDK score log
        tdk_log = TdkScoreLog(
            asset_id=asset_id,
            clarity_score=tdk_breakdown.clarity_score,
            ownership_score=tdk_breakdown.ownership_score,
            composite_score=tdk_breakdown.composite_score,
            score_reason=tdk_breakdown.score_reason,
            event_type=TdkScoreEvent.INITIAL_DRAFT,
        )
        db.add(tdk_log)

        # 10. Update sentinel SmeWorkflow with real draft_id + SLA deadline
        active_workflow = asset.active_workflow
        if active_workflow:
            active_workflow.draft_id = soi_draft.id
            active_workflow.sla_deadline_at = datetime.now(timezone.utc) + timedelta(
                hours=settings.sme_sla_hours
            )
        else:
            # Create workflow if none exists yet
            new_workflow = SmeWorkflow(
                asset_id=asset_id,
                draft_id=soi_draft.id,
                context_authority=context_authority or "unassigned",
                status=WorkflowStatus.AWAITING_SME_AUDIT,
                sla_deadline_at=datetime.now(timezone.utc) + timedelta(
                    hours=settings.sme_sla_hours
                ),
            )
            db.add(new_workflow)

        await db.commit()

    await engine.dispose()

    return {
        "asset_id": str(asset_id),
        "draft_id": str(soi_draft.id),
        "statement_of_intent": draft_result.statement_of_intent,
        "reading_level": rl_result.reading_level_label,
        "jargon_compliant": scrub_result.is_compliant,
        "violation_count": len(scrub_result.violations),
        "tdk_initial_score": tdk_breakdown.composite_score,
        "model_used": draft_result.model_used,
        "escalated": draft_result.escalate,
        "cache_hit": draft_result.cache_hit,
    }


# ---------------------------------------------------------------------------
# Task: run_sla_monitor (Celery Beat)
# ---------------------------------------------------------------------------

@celery_app.task(name="metadata_architect.workers.tasks.run_sla_monitor")
def run_sla_monitor() -> dict:
    """
    Scans for SmeWorkflow records where:
      status = AWAITING_SME_AUDIT AND sla_deadline_at < now()

    For each breach: transitions to ORPHANED, applies TDK penalty,
    enqueues an orphan notice.
    """
    return asyncio.run(_run_sla_monitor())


async def _run_sla_monitor() -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from metadata_architect.config import get_settings
    from metadata_architect.models.asset_registry import (
        SmeWorkflow, TdkScoreLog, TdkScoreEvent, WorkflowStatus,
    )
    from metadata_architect.scoring.tdk_calculator import TdkCalculator, TdkInputs

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)

    breached_ids: list[str] = []

    async with session_factory() as db:
        result = await db.execute(
            select(SmeWorkflow)
            .where(
                SmeWorkflow.status == WorkflowStatus.AWAITING_SME_AUDIT,
                SmeWorkflow.sla_deadline_at < now,
            )
            .options(selectinload(SmeWorkflow.asset).selectinload(
                # load tdk_scores for penalty calculation
                __import__(
                    "metadata_architect.models.asset_registry", fromlist=["Asset"]
                ).Asset.tdk_scores
            ))
        )
        workflows = result.scalars().all()

        for workflow in workflows:
            workflow.transition(WorkflowStatus.ORPHANED)
            workflow.sla_breach_count += 1

            # Apply TDK breach penalty: take last score and subtract penalty
            last_score = workflow.asset.tdk_scores[-1].composite_score if workflow.asset.tdk_scores else 0.5
            penalised = round(max(0.0, last_score - settings.tdk_sla_breach_penalty), 4)

            tdk_log = TdkScoreLog(
                asset_id=workflow.asset_id,
                clarity_score=0.0,
                ownership_score=0.0,
                composite_score=penalised,
                score_reason=f"SLA breach penalty -{settings.tdk_sla_breach_penalty} applied. Asset orphaned.",
                event_type=TdkScoreEvent.SLA_BREACH,
            )
            db.add(tdk_log)
            breached_ids.append(str(workflow.asset_id))

        await db.commit()

    await engine.dispose()

    # Enqueue orphan notices (fire-and-forget)
    for asset_id in breached_ids:
        dispatch_orphan_notice.delay(asset_id)

    log.info("sla_monitor.complete", extra={"breached_count": len(breached_ids)})
    return {"breached_count": len(breached_ids), "asset_ids": breached_ids}


# ---------------------------------------------------------------------------
# Task: dispatch_orphan_notice
# ---------------------------------------------------------------------------

@celery_app.task(
    name="metadata_architect.workers.tasks.dispatch_orphan_notice",
    max_retries=3,
    default_retry_delay=30,
)
def dispatch_orphan_notice(asset_id: str) -> dict:
    """
    Sends an Orphan Notice to the Context Authority for the given asset.
    Notification adapters (email/Slack) are wired in Phase 3.
    """
    log.warning("orphan_notice.dispatched", extra={"asset_id": asset_id})
    # Phase 3: replace with NotificationAdapter call
    return {"asset_id": asset_id, "status": "notice_queued"}


# ---------------------------------------------------------------------------
# Task: analyse_sme_edit (offline, Phase 6 training data pipeline)
# ---------------------------------------------------------------------------

@celery_app.task(
    name="metadata_architect.workers.tasks.analyse_sme_edit",
    queue="analysis",
)
def analyse_sme_edit(asset_id: str, draft_id: str, edit_diff: str) -> dict:
    """
    Categorise an SME edit diff using Claude.
    Stores the categorised diff in MinIO as a training data record.
    Stub — full implementation in Phase 6.
    """
    log.info("analyse_sme_edit.received", extra={"asset_id": asset_id, "draft_id": draft_id})
    return {"asset_id": asset_id, "draft_id": draft_id, "status": "analysis_queued"}


# ---------------------------------------------------------------------------
# Shared helpers (local imports to avoid circular deps at module level)
# ---------------------------------------------------------------------------

def _dialect_from_source(source_system: str | None) -> str:
    mapping = {
        "snowflake": "snowflake", "bigquery": "bigquery", "redshift": "redshift",
        "databricks": "databricks", "spark": "spark", "duckdb": "duckdb",
        "mysql": "mysql", "tsql": "tsql", "mssql": "tsql", "sqlserver": "tsql",
    }
    return mapping.get((source_system or "").lower(), "postgres")


def _load_glossary() -> dict[str, str]:
    """
    Load enterprise glossary terms.
    Phase 1: returns a minimal seed glossary.
    Phase 2+: will load from a database table or external catalog API.
    """
    return {
        "KPI": "Key Performance Indicator — a measurable value that shows how well an objective is being met.",
        "SLA": "Service Level Agreement — a commitment defining expected service standards and response times.",
        "TDK": "Trusted Data KPI — a composite score measuring the clarity and ownership quality of a data asset.",
        "SME": "Subject Matter Expert — a person with deep knowledge of a specific business domain.",
        "SoI": "Statement of Intent — a plain-language description of why a data asset exists.",
        "revenue": "Money earned from business activities before expenses are subtracted.",
        "aggregate": "A summary value calculated from multiple records, such as a sum or average.",
        "audit": "A formal review of records to verify accuracy and compliance.",
        "currency": "The type of money used in a transaction, identified by a three-letter ISO 4217 code.",
        "region": "A geographic area used to group business data, such as a country or sales territory.",
    }


def _extract_lineage(asset) -> list[str]:
    """Extract upstream asset names from stored lineage_refs JSONB."""
    if not asset.lineage_refs:
        return []
    refs = asset.lineage_refs
    if isinstance(refs, list):
        return [str(r) for r in refs]
    if isinstance(refs, dict):
        return [str(v) for v in refs.values()]
    return []


def _get_context_authority(asset) -> str | None:
    """Get the context authority from the active workflow."""
    workflow = asset.active_workflow
    if workflow and workflow.context_authority != "unassigned":
        return workflow.context_authority
    return None
