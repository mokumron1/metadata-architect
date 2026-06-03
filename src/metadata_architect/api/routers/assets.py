"""
Asset Registry CRUD — core Phase 1 API.

Endpoints:
  POST   /assets              Create a new asset record
  GET    /assets              List assets (paginated)
  GET    /assets/{id}         Get single asset with latest draft + TDK score
  PATCH  /assets/{id}         Update mutable fields
  DELETE /assets/{id}         Hard delete (admin only)
  POST   /assets/{id}/parse   Re-parse DDL and refresh column_metadata
  POST   /assets/{id}/workflow/transition   Advance SME workflow state
"""

import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from metadata_architect.config import get_settings
from metadata_architect.database import get_db
from metadata_architect.models.asset_registry import (
    Asset,
    AssetType,
    InvalidTransitionError,
    SmeWorkflow,
    WorkflowStatus,
)
from metadata_architect.parsers.schema_parser import SchemaParser, SchemaParseError
from metadata_architect.schemas.asset_schemas import (
    AssetCreate,
    AssetRead,
    AssetUpdate,
    SmeWorkflowRead,
    WorkflowTransitionRequest,
)


def _require_api_key(
    x_gate_api_key: Annotated[str | None, Header()] = None,
) -> str:
    """Require a valid X-Gate-API-Key header for write/destructive operations."""
    settings = get_settings()
    if not x_gate_api_key or x_gate_api_key != settings.gate_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Gate-API-Key header.",
        )
    return x_gate_api_key


ApiKeyDep = Annotated[str, Depends(_require_api_key)]

router = APIRouter(prefix="/assets", tags=["assets"])

DbDep = Annotated[AsyncSession, Depends(get_db)]

_LOAD_FULL = [
    selectinload(Asset.soi_drafts),
    selectinload(Asset.workflows),
    selectinload(Asset.tdk_scores),
]


async def _get_asset_or_404(db: AsyncSession, asset_id: uuid.UUID) -> Asset:
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id).options(*_LOAD_FULL)
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    return asset


@router.post("", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
async def create_asset(body: AssetCreate, db: DbDep) -> Asset:
    ddl_hash = hashlib.sha256(body.raw_ddl.encode()).hexdigest() if body.raw_ddl else None

    asset = Asset(
        asset_name=body.asset_name,
        asset_type=body.asset_type,
        source_system=body.source_system,
        raw_ddl=body.raw_ddl,
        ddl_hash=ddl_hash,
    )

    # Parse DDL immediately if provided
    if body.raw_ddl:
        try:
            dialect = _dialect_from_source(body.source_system)
            parser = SchemaParser(dialect=dialect)
            parsed = parser.parse(body.raw_ddl)
            asset.column_metadata = {
                "columns": [col.__dict__ for col in parsed.columns],
                "primary_keys": parsed.primary_keys,
                "foreign_keys": parsed.foreign_keys,
                "table_options": parsed.table_options,
            }
        except SchemaParseError:
            # Store asset even if DDL parse fails — SME can correct via /parse
            pass

    db.add(asset)
    await db.flush()

    # Create initial AWAITING_SME_AUDIT workflow stub so Gate 1 can detect the asset
    # A full SoI draft is created later by the Celery drafting pipeline (Phase 2).
    # We attach a sentinel workflow record to mark the asset as "registered."
    workflow = SmeWorkflow(
        asset_id=asset.id,
        draft_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),  # sentinel; replaced in Phase 2
        context_authority=body.context_authority,
        status=WorkflowStatus.AWAITING_SME_AUDIT,
    )
    db.add(workflow)
    await db.commit()
    await db.refresh(asset)

    # Reload with relationships
    return await _get_asset_or_404(db, asset.id)


@router.get("", response_model=dict)
async def list_assets(
    db: DbDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    asset_type: AssetType | None = None,
    source_system: str | None = None,
) -> dict:
    query = select(Asset)
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)
    if source_system:
        query = query.where(Asset.source_system == source_system)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar_one()

    query = query.offset((page - 1) * page_size).limit(page_size).options(*_LOAD_FULL)
    result = await db.execute(query)
    assets = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [AssetRead.model_validate(a) for a in assets],
    }


@router.get("/{asset_id}", response_model=AssetRead)
async def get_asset(asset_id: uuid.UUID, db: DbDep) -> Asset:
    return await _get_asset_or_404(db, asset_id)


@router.patch("/{asset_id}", response_model=AssetRead)
async def update_asset(asset_id: uuid.UUID, body: AssetUpdate, db: DbDep) -> Asset:
    asset = await _get_asset_or_404(db, asset_id)
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(asset, field, value)
    if "raw_ddl" in update_data and update_data["raw_ddl"]:
        asset.ddl_hash = hashlib.sha256(update_data["raw_ddl"].encode()).hexdigest()
    await db.commit()
    return await _get_asset_or_404(db, asset_id)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(asset_id: uuid.UUID, _: ApiKeyDep, db: DbDep) -> None:
    asset = await _get_asset_or_404(db, asset_id)
    await db.delete(asset)
    await db.commit()


@router.post("/{asset_id}/parse", response_model=AssetRead)
async def reparse_ddl(asset_id: uuid.UUID, db: DbDep) -> Asset:
    """Re-parse the stored DDL and refresh column_metadata."""
    asset = await _get_asset_or_404(db, asset_id)
    if not asset.raw_ddl:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No DDL stored.")
    try:
        dialect = _dialect_from_source(asset.source_system)
        parser = SchemaParser(dialect=dialect)
        parsed = parser.parse(asset.raw_ddl)
        asset.column_metadata = {
            "columns": [col.__dict__ for col in parsed.columns],
            "primary_keys": parsed.primary_keys,
            "foreign_keys": parsed.foreign_keys,
            "table_options": parsed.table_options,
        }
        asset.ddl_hash = parsed.ddl_hash
    except SchemaParseError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return await _get_asset_or_404(db, asset_id)


@router.post("/{asset_id}/workflow/transition", response_model=SmeWorkflowRead)
async def transition_workflow(
    asset_id: uuid.UUID, body: WorkflowTransitionRequest, db: DbDep
) -> SmeWorkflow:
    """Advance the active SME workflow state machine."""
    asset = await _get_asset_or_404(db, asset_id)
    workflow = asset.active_workflow
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active workflow found for this asset.",
        )
    try:
        workflow.transition(body.target_status, actioned_by=body.actioned_by)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    if body.sme_edit_diff and asset.latest_draft:
        asset.latest_draft.sme_edit_diff = body.sme_edit_diff

    await db.commit()
    await db.refresh(workflow)
    return workflow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOURCE_DIALECT_MAP = {
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "redshift": "redshift",
    "databricks": "databricks",
    "spark": "spark",
    "duckdb": "duckdb",
    "mysql": "mysql",
    "tsql": "tsql",
    "mssql": "tsql",
    "sqlserver": "tsql",
}


def _dialect_from_source(source_system: str | None) -> str:
    if source_system is None:
        return "postgres"
    return _SOURCE_DIALECT_MAP.get(source_system.lower(), "postgres")
