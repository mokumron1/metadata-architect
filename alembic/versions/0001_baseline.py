"""Baseline: assets, soi_drafts, sme_workflows, tdk_scores

Revision ID: 0001
Revises:
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- assets ---
    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_name", sa.String(512), nullable=False),
        sa.Column(
            "asset_type",
            sa.Enum("table", "view", "stream", "model", name="assettype"),
            nullable=False,
        ),
        sa.Column("source_system", sa.String(256), nullable=True),
        sa.Column("ddl_hash", sa.String(64), nullable=True),
        sa.Column("raw_ddl", sa.Text, nullable=True),
        sa.Column("column_metadata", postgresql.JSONB, nullable=True),
        sa.Column("lineage_refs", postgresql.JSONB, nullable=True),
        sa.Column("glossary_terms", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_name", "source_system", name="uq_asset_name_source"),
    )
    op.create_index("ix_assets_asset_name", "assets", ["asset_name"])
    op.create_index("ix_assets_source_system", "assets", ["source_system"])

    # --- soi_drafts ---
    op.create_table(
        "soi_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("statement_of_intent", sa.Text, nullable=False),
        sa.Column(
            "clarity_standard",
            sa.String(64),
            nullable=False,
            server_default="ISO-24495-1-Compliant",
        ),
        sa.Column("reading_level", sa.String(32), nullable=True),
        sa.Column("reading_level_score", sa.Float, nullable=True),
        sa.Column("jargon_violations", postgresql.JSONB, nullable=True),
        sa.Column("tdk_initial_score", sa.Float, nullable=True),
        sa.Column("model_used", sa.String(64), nullable=True),
        sa.Column("prompt_tokens", sa.Integer, nullable=True),
        sa.Column("completion_tokens", sa.Integer, nullable=True),
        sa.Column("cache_hit", sa.Boolean, nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sme_edit_diff", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_soi_drafts_asset_id", "soi_drafts", ["asset_id"])

    # --- sme_workflows ---
    op.create_table(
        "sme_workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_authority", sa.String(256), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "AWAITING_SME_AUDIT",
                "SME_APPROVED",
                "SME_EDITED",
                "SME_REJECTED",
                "ORPHANED",
                "RECERTIFYING",
                name="workflowstatus",
            ),
            nullable=False,
            server_default="AWAITING_SME_AUDIT",
        ),
        sa.Column("notification_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("action_by", sa.String(256), nullable=True),
        sa.Column("sla_breach_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sme_workflows_asset_id", "sme_workflows", ["asset_id"])
    op.create_index("ix_sme_workflows_status", "sme_workflows", ["status"])
    op.create_index("ix_sme_workflows_sla_deadline", "sme_workflows", ["sla_deadline_at"])

    # --- tdk_scores ---
    op.create_table(
        "tdk_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clarity_score", sa.Float, nullable=False),
        sa.Column("ownership_score", sa.Float, nullable=False),
        sa.Column("composite_score", sa.Float, nullable=False),
        sa.Column("score_reason", sa.Text, nullable=True),
        sa.Column(
            "event_type",
            sa.Enum(
                "INITIAL_DRAFT",
                "SME_APPROVED",
                "SME_EDITED",
                "SLA_BREACH",
                "RECERTIFIED",
                "ORPHANED",
                name="tdkscoreevent",
            ),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tdk_scores_asset_id", "tdk_scores", ["asset_id"])
    op.create_index("ix_tdk_scores_recorded_at", "tdk_scores", ["recorded_at"])


def downgrade() -> None:
    op.drop_table("tdk_scores")
    op.drop_table("sme_workflows")
    op.drop_table("soi_drafts")
    op.drop_table("assets")
    op.execute("DROP TYPE IF EXISTS assettype")
    op.execute("DROP TYPE IF EXISTS workflowstatus")
    op.execute("DROP TYPE IF EXISTS tdkscoreevent")
