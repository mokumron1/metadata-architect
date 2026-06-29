"""Add Third-Party Onboarding Suite tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # column_definitions — Interface 1: Enterprise Glossary drafts
    # -----------------------------------------------------------------------
    op.create_table(
        "column_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_name", sa.String(256), nullable=False),
        sa.Column("column_name", sa.String(256), nullable=False),
        sa.Column("data_type", sa.String(64), nullable=False),
        sa.Column("source_system", sa.String(128), nullable=True),
        sa.Column("business_definition", sa.Text, nullable=False),
        sa.Column("plain_name", sa.String(256), nullable=False),
        sa.Column("usage_examples", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("warnings", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("readability_grade", sa.Float, nullable=False),
        sa.Column("linguistic_compliant", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sme_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("sme_edited_definition", sa.Text, nullable=True),
        sa.Column("model_used", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_column_definitions_asset_name", "column_definitions", ["asset_name"])

    # -----------------------------------------------------------------------
    # security_passports — Interface 2: Security Passport records
    # -----------------------------------------------------------------------
    op.create_table(
        "security_passports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_name", sa.String(256), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("risk_signals", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("quarantine_recommended", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("quarantine_reason", sa.Text, nullable=False, server_default=""),
        sa.Column("remediation_steps", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("regulatory_frameworks", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("payload_fingerprint", sa.String(64), nullable=False),
        sa.Column("gate_status", sa.String(32), nullable=False, server_default="pending_review"),
        sa.Column("model_used", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_security_passports_asset_name", "security_passports", ["asset_name"])

    # -----------------------------------------------------------------------
    # data_contracts — Interface 3: ODCS Data Contract Registry
    # -----------------------------------------------------------------------
    op.create_table(
        "data_contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", sa.String(64), nullable=False),
        sa.Column("asset_name", sa.String(256), nullable=False),
        sa.Column("owner", sa.String(256), nullable=False, server_default=""),
        sa.Column("soi_category", sa.String(64), nullable=False),
        sa.Column("business_decision", sa.Text, nullable=False),
        sa.Column("mandatory_fields", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("update_frequency", sa.String(64), nullable=False),
        sa.Column("freshness_max_age", sa.String(64), nullable=False),
        sa.Column("retention_period", sa.String(64), nullable=False),
        sa.Column("availability_sla", sa.Float, nullable=False, server_default="99.9"),
        sa.Column("quality_completeness", sa.Float, nullable=False, server_default="0.95"),
        sa.Column("schema_hints", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("contract_yaml", sa.Text, nullable=False),
        sa.Column("contract_json", postgresql.JSONB, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("clarification_needed", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("linguistic_compliant", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("model_used", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_id"),
    )
    op.create_index("ix_data_contracts_asset_name", "data_contracts", ["asset_name"])


def downgrade() -> None:
    op.drop_index("ix_data_contracts_asset_name", table_name="data_contracts")
    op.drop_table("data_contracts")
    op.drop_index("ix_security_passports_asset_name", table_name="security_passports")
    op.drop_table("security_passports")
    op.drop_index("ix_column_definitions_asset_name", table_name="column_definitions")
    op.drop_table("column_definitions")
