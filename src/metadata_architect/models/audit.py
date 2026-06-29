"""ORM model for the ISO 27001 audit log."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from metadata_architect.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class AuditLogEntry(Base):
    """
    ISO 27001 A.12.4 audit trail entry.

    One row per event milestone. Multiple rows share the same request_id,
    allowing complete reconstruction of a single request's lifecycle.

    Immutable by design — entries are never updated or deleted.
    """
    __tablename__ = "audit_log"

    # ── Identity ──────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid
    )
    event_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False,
        comment="UUID v4 uniquely identifying this audit event"
    )
    request_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="Correlates all events for one HTTP request (X-Request-ID)"
    )
    sequence: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Monotonically increasing within a request_id"
    )

    # ── What happened ─────────────────────────────────────────────────
    event_code: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="ISO 27001 event code from the events catalogue"
    )
    event_description: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Human-readable event description from catalogue"
    )
    interface: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        comment="METADATA_DRAFTER | SECURITY_TRIAGE | INTERVIEW_BOT | SYSTEM"
    )

    # ── Who / What ────────────────────────────────────────────────────
    actor: Mapped[str] = mapped_column(
        String(256), nullable=False, default="system",
        comment="System, service account, or user that triggered the event"
    )
    asset_name: Mapped[str] = mapped_column(
        String(256), nullable=False, default="",
        comment="Data asset being acted on"
    )

    # ── Outcome & Risk ────────────────────────────────────────────────
    outcome: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="SUCCESS | FAILURE | PENDING | SKIPPED"
    )
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="INFO | WARNING | ERROR | CRITICAL"
    )
    risk_level: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="LOW | MEDIUM | HIGH | CRITICAL  (ISO 27001 risk scale)"
    )

    # ── Contextual payload ────────────────────────────────────────────
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="Event-specific structured data (column counts, signal types, etc.)"
    )
    duration_ms: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="Duration of this step in milliseconds (when measurable)"
    )

    # ── Timestamp ─────────────────────────────────────────────────────
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False, index=True,
        comment="UTC timestamp — ISO 8601 via .isoformat()"
    )

    # ── Composite indexes for common query patterns ───────────────────
    __table_args__ = (
        Index("ix_audit_log_request_seq",  "request_id", "sequence"),
        Index("ix_audit_log_asset_ts",     "asset_name", "timestamp"),
        Index("ix_audit_log_severity_ts",  "severity",   "timestamp"),
        Index("ix_audit_log_interface_ts", "interface",  "timestamp"),
    )

    def to_dict(self) -> dict:
        """Serialise to ISO 27001-structured dict for API responses."""
        return {
            "event_id":          self.event_id,
            "request_id":        self.request_id,
            "sequence":          self.sequence,
            "timestamp":         self.timestamp.isoformat(),
            "event_code":        self.event_code,
            "event_description": self.event_description,
            "interface":         self.interface,
            "actor":             self.actor,
            "asset_name":        self.asset_name,
            "outcome":           self.outcome,
            "severity":          self.severity,
            "risk_level":        self.risk_level,
            "details":           self.details,
            "duration_ms":       self.duration_ms,
        }
