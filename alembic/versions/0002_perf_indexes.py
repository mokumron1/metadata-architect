"""Performance indexes for context-first gate and SLA monitor queries

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-02
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Gate 1 hot path: asset_name + source_system lookup
    op.create_index(
        "ix_assets_name_source",
        "assets",
        ["asset_name", "source_system"],
        unique=False,
    )

    # SLA monitor query: status = AWAITING_SME_AUDIT AND sla_deadline_at < now()
    op.create_index(
        "ix_sme_workflows_status_sla",
        "sme_workflows",
        ["status", "sla_deadline_at"],
        unique=False,
    )

    # TDK score history lookup: most-recent score per asset
    op.create_index(
        "ix_tdk_scores_asset_recorded",
        "tdk_scores",
        ["asset_id", "recorded_at"],
        unique=False,
    )

    # Workflow list + filter by status (used by GET /workflows?status=)
    op.create_index(
        "ix_sme_workflows_asset_status",
        "sme_workflows",
        ["asset_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sme_workflows_asset_status", table_name="sme_workflows")
    op.drop_index("ix_tdk_scores_asset_recorded", table_name="tdk_scores")
    op.drop_index("ix_sme_workflows_status_sla", table_name="sme_workflows")
    op.drop_index("ix_assets_name_source", table_name="assets")
