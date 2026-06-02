"""Add soi_studio_sessions table

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soi_studio_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("physical_name", sa.String(256), nullable=False),
        sa.Column("data_type", sa.String(64), nullable=False),
        sa.Column("business_hint", sa.Text, nullable=True),
        sa.Column("model_used", sa.String(128), nullable=True),
        sa.Column("cache_hit", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("options", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_soi_studio_sessions_created_at",
        "soi_studio_sessions",
        ["created_at"],
    )
    op.create_index(
        "ix_soi_studio_sessions_physical_name",
        "soi_studio_sessions",
        ["physical_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_soi_studio_sessions_physical_name")
    op.drop_index("ix_soi_studio_sessions_created_at")
    op.drop_table("soi_studio_sessions")
