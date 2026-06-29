"""Add ISO 27001 audit_log table.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def _uuid():
    """Return dialect-appropriate UUID column type."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(36)


def _jsonb():
    """Return dialect-appropriate JSON column type."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.JSONB()
    return sa.Text()

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id",                _uuid(),        nullable=False),
        sa.Column("event_id",          sa.String(64),  nullable=False),
        sa.Column("request_id",        sa.String(64),  nullable=False),
        sa.Column("sequence",          sa.Integer,     nullable=False),
        sa.Column("event_code",        sa.String(64),  nullable=False),
        sa.Column("event_description", sa.Text,        nullable=False),
        sa.Column("interface",         sa.String(32),  nullable=False),
        sa.Column("actor",             sa.String(256), nullable=False, server_default="system"),
        sa.Column("asset_name",        sa.String(256), nullable=False, server_default=""),
        sa.Column("outcome",           sa.String(16),  nullable=False),
        sa.Column("severity",          sa.String(16),  nullable=False),
        sa.Column("risk_level",        sa.String(16),  nullable=False),
        sa.Column("details",           _jsonb(),       nullable=False, server_default="{}"),
        sa.Column("duration_ms",       sa.Float,       nullable=True),
        sa.Column("timestamp",         sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_audit_log_request_id",   "audit_log", ["request_id"])
    op.create_index("ix_audit_log_event_code",   "audit_log", ["event_code"])
    op.create_index("ix_audit_log_interface",    "audit_log", ["interface"])
    op.create_index("ix_audit_log_timestamp",    "audit_log", ["timestamp"])
    op.create_index("ix_audit_log_request_seq",  "audit_log", ["request_id", "sequence"])
    op.create_index("ix_audit_log_asset_ts",     "audit_log", ["asset_name", "timestamp"])
    op.create_index("ix_audit_log_severity_ts",  "audit_log", ["severity",   "timestamp"])
    op.create_index("ix_audit_log_interface_ts", "audit_log", ["interface",  "timestamp"])


def downgrade() -> None:
    op.drop_table("audit_log")
