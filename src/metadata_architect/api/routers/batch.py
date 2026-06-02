"""
Batch ingestion router.

POST /batch/ingest   — Accept multiple DDL statements in one request,
                       register each as an Asset, and enqueue drafting tasks.

Designed for backfill scenarios where an entire Postgres schema (50–500 tables)
needs to be registered in one call without overwhelming the Celery queue.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metadata_architect.database import get_db
from metadata_architect.models.asset_registry import Asset, AssetType, SmeWorkflow, WorkflowStatus
from metadata_architect.parsers.schema_parser import SchemaParser, SchemaParseError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/batch", tags=["batch-ingestion"])
DbDep = Annotated[AsyncSession, Depends(get_db)]

_DEFAULT_BATCH_LIMIT = 200


class BatchAssetInput(BaseModel):
    asset_name: str = Field(..., description="Fully-qualified table name, e.g. finance.revenue_v1")
    asset_type: AssetType = AssetType.table
    source_system: str | None = None
    context_authority: str = Field(..., description="SME email address for this asset")
    raw_ddl: str = Field(..., min_length=10)
    lineage_refs: list[str] = Field(default_factory=list)


class BatchIngestRequest(BaseModel):
    assets: list[BatchAssetInput] = Field(
        ...,
        min_length=1,
        max_length=_DEFAULT_BATCH_LIMIT,
        description="Up to 200 assets per request.",
    )
    enqueue_drafting: bool = Field(
        True,
        description=(
            "When True, a draft_asset_metadata Celery task is queued for each "
            "newly registered asset. Set False to register only (dry-run mode)."
        ),
    )
    skip_existing: bool = Field(
        True,
        description="Silently skip assets that already exist instead of raising 409.",
    )


class BatchAssetResult(BaseModel):
    asset_name: str
    status: str           # "created" | "skipped" | "error"
    asset_id: str | None = None
    error: str | None = None
    drafting_queued: bool = False


class BatchIngestResponse(BaseModel):
    total_submitted: int
    created: int
    skipped: int
    errors: int
    results: list[BatchAssetResult]


@router.post(
    "/ingest",
    response_model=BatchIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Batch-register assets and enqueue AI drafting",
)
async def batch_ingest(body: BatchIngestRequest, db: DbDep) -> BatchIngestResponse:
    """
    Register up to 200 assets and (optionally) queue AI metadata drafting for each.

    Existing assets are skipped when `skip_existing=True` (default).
    Parsing errors for individual DDLs are reported per-asset without aborting the batch.
    """
    results: list[BatchAssetResult] = []
    created = skipped = errors = 0

    # Pre-fetch existing names to skip duplicate DB round-trips
    existing_names: set[str] = set()
    result = await db.execute(
        select(Asset.asset_name).where(
            Asset.asset_name.in_([a.asset_name for a in body.assets])
        )
    )
    for (name,) in result.all():
        existing_names.add(name)

    for item in body.assets:
        if item.asset_name in existing_names:
            if body.skip_existing:
                results.append(BatchAssetResult(asset_name=item.asset_name, status="skipped"))
                skipped += 1
                continue
            else:
                results.append(BatchAssetResult(
                    asset_name=item.asset_name,
                    status="error",
                    error="Asset already exists. Set skip_existing=true to skip.",
                ))
                errors += 1
                continue

        # Parse DDL — non-fatal per asset
        column_metadata = None
        try:
            dialect = _dialect_from_source(item.source_system)
            parsed = SchemaParser(dialect=dialect).parse(item.raw_ddl)
            column_metadata = {
                "columns": [col.__dict__ for col in parsed.columns],
                "primary_keys": parsed.primary_keys,
                "foreign_keys": parsed.foreign_keys,
                "table_options": parsed.table_options,
            }
        except SchemaParseError as exc:
            log.warning("batch_ingest.parse_error asset=%s err=%s", item.asset_name, exc)
            # Register the asset anyway — SME can trigger /parse later

        asset = Asset(
            asset_name=item.asset_name,
            asset_type=item.asset_type,
            source_system=item.source_system,
            raw_ddl=item.raw_ddl,
            ddl_hash=hashlib.sha256(item.raw_ddl.encode()).hexdigest(),
            column_metadata=column_metadata,
            lineage_refs={"refs": item.lineage_refs} if item.lineage_refs else None,
        )
        db.add(asset)
        await db.flush()

        workflow = SmeWorkflow(
            asset_id=asset.id,
            draft_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),  # sentinel
            context_authority=item.context_authority,
            status=WorkflowStatus.AWAITING_SME_AUDIT,
        )
        db.add(workflow)
        await db.flush()

        drafting_queued = False
        if body.enqueue_drafting:
            try:
                from metadata_architect.workers.tasks import draft_asset_metadata
                draft_asset_metadata.delay(str(asset.id))
                drafting_queued = True
            except Exception as exc:
                log.warning("batch_ingest.queue_error asset=%s err=%s", item.asset_name, exc)

        results.append(BatchAssetResult(
            asset_name=item.asset_name,
            status="created",
            asset_id=str(asset.id),
            drafting_queued=drafting_queued,
        ))
        created += 1

    await db.commit()

    log.info(
        "batch_ingest.complete created=%d skipped=%d errors=%d",
        created, skipped, errors,
    )
    return BatchIngestResponse(
        total_submitted=len(body.assets),
        created=created,
        skipped=skipped,
        errors=errors,
        results=results,
    )


def _dialect_from_source(source_system: str | None) -> str:
    mapping = {
        "snowflake": "snowflake", "bigquery": "bigquery", "redshift": "redshift",
        "databricks": "databricks", "spark": "spark", "duckdb": "duckdb",
        "mysql": "mysql", "tsql": "tsql", "mssql": "tsql", "sqlserver": "tsql",
    }
    return mapping.get((source_system or "").lower(), "postgres")
