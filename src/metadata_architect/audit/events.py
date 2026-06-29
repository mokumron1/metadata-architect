"""
ISO 27001 Audit Event Catalogue.

Every event code maps to:
  - A human-readable description
  - A severity (INFO / WARNING / ERROR / CRITICAL)
  - A risk level (LOW / MEDIUM / HIGH / CRITICAL) per ISO 27001 A.12.4
  - An interface tag (METADATA_DRAFTER / SECURITY_TRIAGE / INTERVIEW_BOT / SYSTEM)

Event code convention:  <INTERFACE>_<NOUN>_<VERB>
"""

from __future__ import annotations

from enum import Enum


class Severity(str, Enum):
    INFO     = "INFO"
    WARNING  = "WARNING"
    ERROR    = "ERROR"
    CRITICAL = "CRITICAL"


class RiskLevel(str, Enum):
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


class Outcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PENDING = "PENDING"
    SKIPPED = "SKIPPED"


class Interface(str, Enum):
    METADATA_DRAFTER = "METADATA_DRAFTER"
    SECURITY_TRIAGE  = "SECURITY_TRIAGE"
    INTERVIEW_BOT    = "INTERVIEW_BOT"
    SYSTEM           = "SYSTEM"


# ---------------------------------------------------------------------------
# Event definitions: (description, severity, risk_level, interface)
# ---------------------------------------------------------------------------

EVENTS: dict[str, tuple[str, Severity, RiskLevel, Interface]] = {

    # ── Interface 1: Metadata Drafter ─────────────────────────────────
    "MD_REQUEST_RECEIVED": (
        "Metadata draft request accepted and validated",
        Severity.INFO, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),
    "MD_LLM_CALL_STARTED": (
        "LLM drafting engine invoked",
        Severity.INFO, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),
    "MD_LLM_CALL_COMPLETED": (
        "LLM returned a definition draft",
        Severity.INFO, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),
    "MD_LLM_CALL_FAILED": (
        "LLM call failed — draft could not be generated",
        Severity.ERROR, RiskLevel.MEDIUM, Interface.METADATA_DRAFTER,
    ),
    "MD_LINGUISTIC_AUDIT_STARTED": (
        "ISO 24495-1 / CEFR B1 linguistic validation started",
        Severity.INFO, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),
    "MD_LINGUISTIC_AUDIT_PASSED": (
        "Definition passed all linguistic constraints",
        Severity.INFO, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),
    "MD_LINGUISTIC_AUDIT_FAILED": (
        "Definition has linguistic violations — flagged for SME review",
        Severity.WARNING, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),
    "MD_AUTO_APPROVAL_GRANTED": (
        "Definition meets auto-approval criteria (confidence ≥ 80%, grade ≤ 9, linguistic pass)",
        Severity.INFO, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),
    "MD_AUTO_APPROVAL_DENIED": (
        "Definition does not meet auto-approval criteria — routed to SME queue",
        Severity.WARNING, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),
    "MD_DRAFT_PERSISTED": (
        "Draft definition written to column_definitions table",
        Severity.INFO, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),
    "MD_BATCH_STARTED": (
        "Batch metadata draft job started",
        Severity.INFO, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),
    "MD_BATCH_COMPLETED": (
        "Batch metadata draft job completed",
        Severity.INFO, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),
    "MD_SME_APPROVED": (
        "SME approved the AI-generated definition — written to Enterprise Glossary",
        Severity.INFO, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),
    "MD_SME_EDITED": (
        "SME submitted an edited definition — written to Enterprise Glossary",
        Severity.INFO, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),
    "MD_SME_REJECTED": (
        "SME rejected the AI-generated definition — not written to Enterprise Glossary",
        Severity.WARNING, RiskLevel.LOW, Interface.METADATA_DRAFTER,
    ),

    # ── Interface 2: Security Triage ──────────────────────────────────
    "ST_REQUEST_RECEIVED": (
        "Security triage request accepted",
        Severity.INFO, RiskLevel.LOW, Interface.SECURITY_TRIAGE,
    ),
    "ST_PAYLOAD_FINGERPRINTED": (
        "SHA-256 fingerprint computed for audit trail",
        Severity.INFO, RiskLevel.LOW, Interface.SECURITY_TRIAGE,
    ),
    "ST_REGEX_SCAN_STARTED": (
        "Phase 1 — parallel regex PII/PHI/PCI pattern scan started",
        Severity.INFO, RiskLevel.LOW, Interface.SECURITY_TRIAGE,
    ),
    "ST_REGEX_SCAN_COMPLETED": (
        "Phase 1 regex scan completed",
        Severity.INFO, RiskLevel.LOW, Interface.SECURITY_TRIAGE,
    ),
    "ST_CRITICAL_SIGNAL_DETECTED": (
        "Critical risk signal found — skipping semantic phase and fast-pathing to classification",
        Severity.CRITICAL, RiskLevel.CRITICAL, Interface.SECURITY_TRIAGE,
    ),
    "ST_SEMANTIC_ANALYSIS_STARTED": (
        "Phase 2 — Claude semantic classification started",
        Severity.INFO, RiskLevel.LOW, Interface.SECURITY_TRIAGE,
    ),
    "ST_SEMANTIC_ANALYSIS_COMPLETED": (
        "Phase 2 semantic classification completed",
        Severity.INFO, RiskLevel.LOW, Interface.SECURITY_TRIAGE,
    ),
    "ST_SEMANTIC_ANALYSIS_FAILED": (
        "Phase 2 Claude semantic call failed",
        Severity.ERROR, RiskLevel.HIGH, Interface.SECURITY_TRIAGE,
    ),
    "ST_CLASSIFICATION_DECIDED": (
        "Security Passport classification badge assigned",
        Severity.INFO, RiskLevel.LOW, Interface.SECURITY_TRIAGE,
    ),
    "ST_QUARANTINE_TRIGGERED": (
        "High-risk data detected — asset routed to Observation Table",
        Severity.CRITICAL, RiskLevel.CRITICAL, Interface.SECURITY_TRIAGE,
    ),
    "ST_PASSPORT_PERSISTED": (
        "Security Passport written to security_passports table",
        Severity.INFO, RiskLevel.LOW, Interface.SECURITY_TRIAGE,
    ),
    "ST_GATE_BLOCKED": (
        "Governance Entry Gate blocked — asset quarantined pending review",
        Severity.CRITICAL, RiskLevel.HIGH, Interface.SECURITY_TRIAGE,
    ),
    "ST_GATE_CLEARED": (
        "Security team cleared asset from quarantine — ingestion permitted",
        Severity.INFO, RiskLevel.MEDIUM, Interface.SECURITY_TRIAGE,
    ),
    "ST_QUARANTINE_CONFIRMED": (
        "Security team confirmed quarantine — asset remains blocked",
        Severity.WARNING, RiskLevel.HIGH, Interface.SECURITY_TRIAGE,
    ),

    # ── Interface 3: Interview Bot ────────────────────────────────────
    "IB_REQUEST_RECEIVED": (
        "Interview request accepted — NL answers submitted for extraction",
        Severity.INFO, RiskLevel.LOW, Interface.INTERVIEW_BOT,
    ),
    "IB_LLM_EXTRACTION_STARTED": (
        "LLM ODCS metadata extraction started",
        Severity.INFO, RiskLevel.LOW, Interface.INTERVIEW_BOT,
    ),
    "IB_LLM_EXTRACTION_COMPLETED": (
        "LLM returned structured ODCS metadata",
        Severity.INFO, RiskLevel.LOW, Interface.INTERVIEW_BOT,
    ),
    "IB_LLM_EXTRACTION_FAILED": (
        "LLM extraction failed — contract could not be generated",
        Severity.ERROR, RiskLevel.MEDIUM, Interface.INTERVIEW_BOT,
    ),
    "IB_SOI_CATEGORY_MAPPED": (
        "Statement of Intent category classified",
        Severity.INFO, RiskLevel.LOW, Interface.INTERVIEW_BOT,
    ),
    "IB_YAML_RENDERED": (
        "ODCS v3.0.0 YAML contract rendered",
        Severity.INFO, RiskLevel.LOW, Interface.INTERVIEW_BOT,
    ),
    "IB_YAML_VALIDATION_PASSED": (
        "YAML contract is syntactically valid",
        Severity.INFO, RiskLevel.LOW, Interface.INTERVIEW_BOT,
    ),
    "IB_YAML_VALIDATION_FAILED": (
        "YAML contract failed validation — flagged for review",
        Severity.WARNING, RiskLevel.MEDIUM, Interface.INTERVIEW_BOT,
    ),
    "IB_CLARIFICATION_NEEDED": (
        "Low-confidence extraction — clarification questions generated",
        Severity.WARNING, RiskLevel.LOW, Interface.INTERVIEW_BOT,
    ),
    "IB_CONTRACT_PERSISTED": (
        "Data contract draft written to data_contracts table",
        Severity.INFO, RiskLevel.LOW, Interface.INTERVIEW_BOT,
    ),
    "IB_GATE_READY": (
        "Contract confidence ≥ 75% — ready to feed Governance Entry Gate",
        Severity.INFO, RiskLevel.LOW, Interface.INTERVIEW_BOT,
    ),
    "IB_GATE_NOT_READY": (
        "Contract confidence < 75% or clarifications needed — gate remains closed",
        Severity.WARNING, RiskLevel.MEDIUM, Interface.INTERVIEW_BOT,
    ),
    "IB_CONTRACT_ACTIVATED": (
        "Contract activated — Governance Entry Gate unlocked for this asset",
        Severity.INFO, RiskLevel.LOW, Interface.INTERVIEW_BOT,
    ),
    "IB_CONTRACT_SUPERSEDED": (
        "Contract superseded by a newer version",
        Severity.INFO, RiskLevel.LOW, Interface.INTERVIEW_BOT,
    ),
    "IB_CONTRACT_TERMINATED": (
        "Contract terminated — access revoked",
        Severity.WARNING, RiskLevel.HIGH, Interface.INTERVIEW_BOT,
    ),
}


def lookup(code: str) -> tuple[str, Severity, RiskLevel, Interface]:
    if code not in EVENTS:
        return (
            f"Unknown event: {code}",
            Severity.WARNING,
            RiskLevel.MEDIUM,
            Interface.SYSTEM,
        )
    return EVENTS[code]
