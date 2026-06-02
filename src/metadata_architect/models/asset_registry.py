import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from metadata_architect.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class AssetType(str, enum.Enum):
    table = "table"
    view = "view"
    stream = "stream"
    model = "model"


class WorkflowStatus(str, enum.Enum):
    AWAITING_SME_AUDIT = "AWAITING_SME_AUDIT"
    SME_APPROVED = "SME_APPROVED"
    SME_EDITED = "SME_EDITED"
    SME_REJECTED = "SME_REJECTED"
    ORPHANED = "ORPHANED"
    RECERTIFYING = "RECERTIFYING"


class TdkScoreEvent(str, enum.Enum):
    INITIAL_DRAFT = "INITIAL_DRAFT"
    SME_APPROVED = "SME_APPROVED"
    SME_EDITED = "SME_EDITED"
    SLA_BREACH = "SLA_BREACH"
    RECERTIFIED = "RECERTIFIED"
    ORPHANED = "ORPHANED"


# ---------------------------------------------------------------------------
# Asset — the canonical record for a data asset
# ---------------------------------------------------------------------------

class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    asset_name: Mapped[str] = mapped_column(String(512), nullable=False)
    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType), nullable=False)
    source_system: Mapped[str | None] = mapped_column(String(256))
    ddl_hash: Mapped[str | None] = mapped_column(String(64))  # SHA-256 of raw DDL
    raw_ddl: Mapped[str | None] = mapped_column(Text)
    column_metadata: Mapped[dict | None] = mapped_column(JSONB)  # list[ColumnMetadata]
    lineage_refs: Mapped[dict | None] = mapped_column(JSONB)     # list of upstream asset IDs
    glossary_terms: Mapped[dict | None] = mapped_column(JSONB)   # matched enterprise terms
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (UniqueConstraint("asset_name", "source_system", name="uq_asset_name_source"),)

    soi_drafts: Mapped[list["SoIDraft"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", order_by="SoIDraft.version"
    )
    workflows: Mapped[list["SmeWorkflow"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    tdk_scores: Mapped[list["TdkScoreLog"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", order_by="TdkScoreLog.recorded_at"
    )

    @property
    def latest_draft(self) -> "SoIDraft | None":
        return self.soi_drafts[-1] if self.soi_drafts else None

    @property
    def active_workflow(self) -> "SmeWorkflow | None":
        open_statuses = {WorkflowStatus.AWAITING_SME_AUDIT, WorkflowStatus.RECERTIFYING}
        return next((w for w in self.workflows if w.status in open_statuses), None)

    @property
    def current_tdk_score(self) -> float | None:
        return self.tdk_scores[-1].composite_score if self.tdk_scores else None


# ---------------------------------------------------------------------------
# SoIDraft — versioned Statement of Intent drafts
# ---------------------------------------------------------------------------

class SoIDraft(Base):
    __tablename__ = "soi_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    statement_of_intent: Mapped[str] = mapped_column(Text, nullable=False)
    clarity_standard: Mapped[str] = mapped_column(
        String(64), nullable=False, default="ISO-24495-1-Compliant"
    )
    reading_level: Mapped[str | None] = mapped_column(String(32))   # e.g. "B1 / 9th Grade"
    reading_level_score: Mapped[float | None] = mapped_column(Float)  # Flesch-Kincaid numeric
    jargon_violations: Mapped[dict | None] = mapped_column(JSONB)    # list of violation dicts
    tdk_initial_score: Mapped[float | None] = mapped_column(Float)
    model_used: Mapped[str | None] = mapped_column(String(64))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_hit: Mapped[bool | None] = mapped_column(Boolean)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    sme_edit_diff: Mapped[str | None] = mapped_column(Text)  # null if approved without edit

    asset: Mapped["Asset"] = relationship(back_populates="soi_drafts")
    workflows: Mapped[list["SmeWorkflow"]] = relationship(back_populates="draft")


# ---------------------------------------------------------------------------
# SmeWorkflow — per-asset HITL state machine
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[WorkflowStatus, set[WorkflowStatus]] = {
    WorkflowStatus.AWAITING_SME_AUDIT: {
        WorkflowStatus.SME_APPROVED,
        WorkflowStatus.SME_EDITED,
        WorkflowStatus.SME_REJECTED,
        WorkflowStatus.ORPHANED,
    },
    WorkflowStatus.SME_EDITED: {WorkflowStatus.SME_APPROVED},
    WorkflowStatus.SME_REJECTED: {WorkflowStatus.AWAITING_SME_AUDIT},
    WorkflowStatus.ORPHANED: {WorkflowStatus.RECERTIFYING},
    WorkflowStatus.RECERTIFYING: {WorkflowStatus.AWAITING_SME_AUDIT},
    WorkflowStatus.SME_APPROVED: set(),  # terminal — new workflow record for re-certification
}


class InvalidTransitionError(Exception):
    def __init__(self, current: WorkflowStatus, target: WorkflowStatus) -> None:
        super().__init__(f"Invalid transition: {current.value} → {target.value}")


class SmeWorkflow(Base):
    __tablename__ = "sme_workflows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("soi_drafts.id"), nullable=False)
    context_authority: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus), nullable=False, default=WorkflowStatus.AWAITING_SME_AUDIT
    )
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    action_by: Mapped[str | None] = mapped_column(String(256))
    sla_breach_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    asset: Mapped["Asset"] = relationship(back_populates="workflows")
    draft: Mapped["SoIDraft"] = relationship(back_populates="workflows")

    def transition(self, target: WorkflowStatus, actioned_by: str | None = None) -> None:
        allowed = VALID_TRANSITIONS.get(self.status, set())
        if target not in allowed:
            raise InvalidTransitionError(self.status, target)
        self.status = target
        if target not in {WorkflowStatus.ORPHANED, WorkflowStatus.RECERTIFYING}:
            self.actioned_at = _now()
            self.action_by = actioned_by

    @property
    def is_sla_breached(self) -> bool:
        if self.sla_deadline_at is None:
            return False
        return _now() > self.sla_deadline_at and self.status == WorkflowStatus.AWAITING_SME_AUDIT


# ---------------------------------------------------------------------------
# TdkScoreLog — append-only score history
# ---------------------------------------------------------------------------

class TdkScoreLog(Base):
    __tablename__ = "tdk_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    clarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    ownership_score: Mapped[float] = mapped_column(Float, nullable=False)
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    score_reason: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[TdkScoreEvent] = mapped_column(Enum(TdkScoreEvent), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    asset: Mapped["Asset"] = relationship(back_populates="tdk_scores")
