"""Pydantic request/response schemas for the Third-Party Onboarding Suite."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Interface 1 — AI Metadata Drafter
# ---------------------------------------------------------------------------

class ColumnContextRequest(BaseModel):
    column_name: str = Field(..., description="Technical column name, e.g. 'AMT_D_01'")
    data_type: str = Field(..., description="SQL data type, e.g. 'DECIMAL(18,2)'")
    sample_values: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Up to 10 representative sample values",
    )
    table_context_hint: str = Field(
        default="",
        description="Brief hint about the parent table's business purpose",
    )
    source_system: str = Field(default="", description="Source system identifier")
    asset_name: str = Field(default="", description="Parent asset / table name")


class LinguisticViolationResponse(BaseModel):
    rule: str
    text: str
    suggestion: str


class MetadataDraftResponse(BaseModel):
    column_name: str
    business_definition: str
    plain_name: str
    usage_examples: list[str]
    warnings: list[str]
    confidence: float
    readability_grade: float
    linguistic_compliant: bool
    linguistic_violations: list[LinguisticViolationResponse]
    is_auto_approvable: bool
    model_used: str
    record_id: uuid.UUID | None = None


class MetadataDraftBatchRequest(BaseModel):
    columns: list[ColumnContextRequest] = Field(..., max_length=50)
    asset_name: str


class MetadataDraftBatchResponse(BaseModel):
    asset_name: str
    drafts: list[MetadataDraftResponse]
    auto_approvable_count: int
    total_columns: int


class ColumnApprovalRequest(BaseModel):
    record_id: uuid.UUID
    action: str = Field(..., pattern="^(approved|edited|rejected)$")
    edited_definition: str | None = Field(
        None, description="Provide when action='edited'"
    )


class ColumnApprovalResponse(BaseModel):
    record_id: uuid.UUID
    column_name: str
    sme_status: str
    final_definition: str
    written_to_glossary: bool


# ---------------------------------------------------------------------------
# Interface 2 — Intelligent Security Triage
# ---------------------------------------------------------------------------

class SecurityTriageRequest(BaseModel):
    asset_name: str = Field(..., description="Name of the data asset being triaged")
    payload_sample: str = Field(
        ...,
        max_length=8000,
        description="Raw data sample — first 4096 chars used for fingerprint",
    )
    field_metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Optional {field_name: data_type} map for richer context",
    )


class RiskSignalResponse(BaseModel):
    field: str
    signal_type: str
    pattern_matched: str
    sample_evidence: str
    severity: str


class SecurityPassportResponse(BaseModel):
    asset_name: str
    classification: str
    confidence: float
    risk_signals: list[RiskSignalResponse]
    quarantine_recommended: bool
    quarantine_reason: str
    remediation_steps: list[str]
    regulatory_frameworks: list[str]
    payload_fingerprint: str
    gate_status: str
    record_id: uuid.UUID | None = None


class SecurityReviewRequest(BaseModel):
    record_id: uuid.UUID
    action: str = Field(..., pattern="^(cleared|quarantined)$")
    reviewer_notes: str = ""


# ---------------------------------------------------------------------------
# Interface 3 — Interview Bot / Data Contract Generator
# ---------------------------------------------------------------------------

class InterviewRequest(BaseModel):
    asset_name: str = Field(..., description="Fully-qualified asset name")
    answer_business_decision: str = Field(
        ...,
        description="Vendor answer to: 'What business decision will this data enable?'",
    )
    answer_freshness: str = Field(
        ...,
        description="Vendor answer to: 'How often is this data updated?'",
    )
    answer_mandatory_fields: str = Field(
        ...,
        description="Vendor answer to: 'What are the mandatory fields for this intent?'",
    )
    owner: str = ""
    support_contact: str = ""
    additional_context: str = ""


class SchemaHintResponse(BaseModel):
    field: str
    type: str
    required: bool
    description: str


class DataContractResponse(BaseModel):
    contract_id: str
    asset_name: str
    soi_category: str
    business_decision: str
    mandatory_fields: list[str]
    update_frequency: str
    freshness_max_age: str
    retention_period: str
    availability_sla: float
    quality_completeness: float
    schema_hints: list[SchemaHintResponse]
    confidence: float
    clarification_needed: list[str]
    is_ready_for_gate: bool
    linguistic_compliant: bool
    contract_yaml: str
    contract_json: dict[str, Any]
    model_used: str
    record_id: uuid.UUID | None = None


class ContractActivationRequest(BaseModel):
    record_id: uuid.UUID
    action: str = Field(..., pattern="^(activate|supersede|terminate)$")


class ContractActivationResponse(BaseModel):
    record_id: uuid.UUID
    contract_id: str
    status: str
    gate_unblocked: bool
