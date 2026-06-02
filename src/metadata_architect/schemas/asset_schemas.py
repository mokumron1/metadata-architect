import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from metadata_architect.models.asset_registry import AssetType, WorkflowStatus, TdkScoreEvent


class AssetCreate(BaseModel):
    asset_name: str = Field(..., min_length=1, max_length=512)
    asset_type: AssetType
    source_system: str | None = None
    raw_ddl: str | None = None
    context_authority: str = Field(..., description="SME email or team identifier")


class AssetUpdate(BaseModel):
    asset_type: AssetType | None = None
    source_system: str | None = None
    raw_ddl: str | None = None
    context_authority: str | None = None


class SoIDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    version: int
    statement_of_intent: str
    clarity_standard: str
    reading_level: str | None
    reading_level_score: float | None
    jargon_violations: list | None
    tdk_initial_score: float | None
    model_used: str | None
    generated_at: datetime


class SmeWorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    draft_id: uuid.UUID
    context_authority: str
    status: WorkflowStatus
    notification_sent_at: datetime | None
    sla_deadline_at: datetime | None
    actioned_at: datetime | None
    action_by: str | None
    sla_breach_count: int
    created_at: datetime


class TdkScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    clarity_score: float
    ownership_score: float
    composite_score: float
    score_reason: str | None
    event_type: TdkScoreEvent
    recorded_at: datetime


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_name: str
    asset_type: AssetType
    source_system: str | None
    ddl_hash: str | None
    column_metadata: dict | None
    lineage_refs: dict | None
    glossary_terms: dict | None
    created_at: datetime
    updated_at: datetime
    current_tdk_score: float | None
    latest_draft: SoIDraftRead | None


class WorkflowTransitionRequest(BaseModel):
    target_status: WorkflowStatus
    actioned_by: str
    sme_edit_diff: str | None = None  # provided when target_status == SME_EDITED
