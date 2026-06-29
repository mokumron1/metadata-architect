"""
Interface 2: Intelligent Security Triage — "The Proactive Shield"

Performs real-time pattern discovery on third-party data feeds to:
  1. Detect PII / PHI / PCI signals via parallel regex + semantic classifiers.
  2. Suggest a Security Passport classification badge.
  3. Route non-compliant records to an Observation Table (quarantine).

The Security Passport output feeds the Governance Entry Gate — non-classified
assets are blocked from ingestion ("No Contract, No Access").
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum

from metadata_architect.agents.claude_client import CachedBlock, ClaudeClient
from metadata_architect.config import get_settings
from metadata_architect.prompts.security_triage import BLOCK_ROLE, USER_TEMPLATE

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex-based fast detectors (run before calling Claude)
# ---------------------------------------------------------------------------

_PATTERNS: dict[str, re.Pattern] = {
    # PII
    "ssn":            re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "email":          re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    "us_phone":       re.compile(r"\b(\+1[\s\-]?)?(\(?\d{3}\)?[\s\-]?)?\d{3}[\s\-]\d{4}\b"),
    "dob_slash":      re.compile(r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/\d{4}\b"),
    # PHI
    "icd10":          re.compile(r"\b[A-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?\b"),
    "npi":            re.compile(r"\bNPI[:\s]?\d{10}\b", re.IGNORECASE),
    "mrn":            re.compile(r"\bMRN[:\s]?\d{6,12}\b", re.IGNORECASE),
    # PCI
    "visa":           re.compile(r"\b4[0-9]{12}(?:[0-9]{3})?\b"),
    "mastercard":     re.compile(r"\b5[1-5][0-9]{14}\b"),
    "amex":           re.compile(r"\b3[47][0-9]{13}\b"),
    "cvv":            re.compile(r"\b(?:cvv|cvc|cvv2)[:\s]?\d{3,4}\b", re.IGNORECASE),
}

_SIGNAL_TYPE_MAP: dict[str, str] = {
    "ssn": "pii", "email": "pii", "us_phone": "pii", "dob_slash": "pii",
    "icd10": "phi", "npi": "phi", "mrn": "phi",
    "visa": "pci", "mastercard": "pci", "amex": "pci", "cvv": "pci",
}

_SEVERITY_MAP: dict[str, str] = {
    "ssn": "critical", "icd10": "critical", "npi": "critical", "mrn": "critical",
    "visa": "critical", "mastercard": "critical", "amex": "critical", "cvv": "critical",
    "email": "high", "us_phone": "high", "dob_slash": "high",
}

_CLASSIFICATION_HIERARCHY = ["Public", "Internal", "Confidential", "Restricted"]

_SIGNAL_TO_CLASSIFICATION: dict[str, str] = {
    "pii": "Confidential",
    "phi": "Restricted",
    "pci": "Restricted",
    "none": "Internal",
}


class SecurityClassification(str, Enum):
    PUBLIC = "Public"
    INTERNAL = "Internal"
    CONFIDENTIAL = "Confidential"
    RESTRICTED = "Restricted"


@dataclass
class RiskSignal:
    field: str
    signal_type: str
    pattern_matched: str
    sample_evidence: str
    severity: str


@dataclass
class SecurityPassport:
    """
    Machine-readable Security Passport attached to a data asset's metadata.

    Feed into the Governance Entry Gate to block non-compliant ingestion.
    """
    asset_name: str
    classification: SecurityClassification
    confidence: float
    risk_signals: list[RiskSignal]
    quarantine_recommended: bool
    quarantine_reason: str
    remediation_steps: list[str]
    regulatory_frameworks: list[str]
    payload_fingerprint: str   # SHA-256 of the first 4096 bytes — for audit trail
    model_used: str
    input_tokens: int
    output_tokens: int
    cache_hit: bool

    def as_tag(self) -> dict:
        """Return a minimal machine-readable tag for attaching to metadata records."""
        return {
            "security_classification": self.classification.value,
            "quarantine": self.quarantine_recommended,
            "regulatory_frameworks": self.regulatory_frameworks,
            "payload_fingerprint": self.payload_fingerprint,
        }


def _anonymise(text: str) -> str:
    """Replace digit runs and common name patterns before logging as evidence."""
    text = re.sub(r"\d+", lambda m: "X" * len(m.group()), text)
    text = re.sub(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", "[NAME]", text)
    return text


def _normalize_classification(raw: str) -> str:
    """Map Claude's classification string to a known hierarchy value.

    Returns 'Internal' for any unrecognised value so _upgrade_classification
    and SecurityClassification() never raise on unexpected LLM output.
    """
    canonical = {c.lower(): c for c in _CLASSIFICATION_HIERARCHY}
    return canonical.get(raw.strip().lower(), "Internal")


def _regex_scan(text: str) -> list[RiskSignal]:
    signals: list[RiskSignal] = []
    for pattern_name, pattern in _PATTERNS.items():
        match = pattern.search(text)
        if match:
            signals.append(
                RiskSignal(
                    field="free_text",
                    signal_type=_SIGNAL_TYPE_MAP[pattern_name],
                    pattern_matched=pattern_name,
                    sample_evidence=_anonymise(match.group()),
                    severity=_SEVERITY_MAP.get(pattern_name, "medium"),
                )
            )
    return signals


def _upgrade_classification(current: str, new: str) -> str:
    ci = _CLASSIFICATION_HIERARCHY.index(current)
    ni = _CLASSIFICATION_HIERARCHY.index(new)
    return _CLASSIFICATION_HIERARCHY[max(ci, ni)]


class SecurityTriageAgent:
    """
    Runs two-phase triage: fast regex scan first, then semantic Claude analysis.

    If the regex scan already produces high/critical signals, the classification
    is set without calling Claude (to avoid sending sensitive data over the wire
    unless necessary). Claude is used for semantic classification when signal
    types are ambiguous or a higher-confidence result is needed.
    """

    _SKIP_SEMANTIC_THRESHOLD = "critical"

    def __init__(self) -> None:
        settings = get_settings()
        self._model = settings.soi_draft_model
        self._client = ClaudeClient(model=self._model, max_tokens=768)

    def triage(
        self,
        asset_name: str,
        payload_text: str,
        field_metadata: dict[str, str] | None = None,
    ) -> SecurityPassport:
        """
        Classify the security risk of a data payload.

        payload_text: raw text sample (first 4096 chars used for fingerprint)
        field_metadata: optional dict of {field_name: data_type} for richer context
        """
        fingerprint = hashlib.sha256(payload_text[:4096].encode()).hexdigest()
        regex_signals = _regex_scan(payload_text)

        has_critical = any(s.severity == "critical" for s in regex_signals)

        if has_critical:
            # Derive classification from regex signals alone — don't call Claude
            classification = "Public"
            for sig in regex_signals:
                classification = _upgrade_classification(
                    classification, _SIGNAL_TO_CLASSIFICATION[sig.signal_type]
                )
            # Always quarantine when a critical signal is present regardless of
            # classification level — SSN maps to "Confidential" but must still
            # be quarantined (it satisfies the hard stop for critical PII/PCI/PHI).
            quarantine = True
            return SecurityPassport(
                asset_name=asset_name,
                classification=SecurityClassification(classification),
                confidence=0.95,
                risk_signals=regex_signals,
                quarantine_recommended=quarantine,
                quarantine_reason=(
                    "Critical regex signals detected (PCI/PHI). "
                    "Route to Observation Table pending security review."
                ) if quarantine else "",
                remediation_steps=[
                    "Mask or tokenise all critical fields before ingestion.",
                    "Obtain DPO sign-off before promoting from Observation Table.",
                ],
                regulatory_frameworks=list({
                    "PCI-DSS" if s.signal_type == "pci" else
                    "HIPAA" if s.signal_type == "phi" else "GDPR"
                    for s in regex_signals
                }),
                payload_fingerprint=fingerprint,
                model_used="regex-only",
                input_tokens=0,
                output_tokens=0,
                cache_hit=False,
            )

        # Semantic phase — send truncated, de-identified sample to Claude
        sample = payload_text[:2000]
        metadata_json = json.dumps({
            "asset_name": asset_name,
            "field_metadata": field_metadata or {},
            "regex_pre_signals": [
                {"pattern": s.pattern_matched, "signal_type": s.signal_type}
                for s in regex_signals
            ],
        }, indent=2)

        system_blocks = [CachedBlock.make(BLOCK_ROLE, cache=True)]
        user_message = USER_TEMPLATE.format(
            metadata_json=metadata_json,
            sample_text=sample,
        )

        response = self._client.call(system_blocks, user_message)
        data = response.parse_json()

        classification = _normalize_classification(data.get("classification", "Internal"))
        for sig in regex_signals:
            classification = _upgrade_classification(
                classification, _SIGNAL_TO_CLASSIFICATION[sig.signal_type]
            )

        semantic_signals = [
            RiskSignal(
                field=s.get("field", ""),
                signal_type=s.get("signal_type", "none"),
                pattern_matched=s.get("pattern_matched", "semantic"),
                sample_evidence=s.get("sample_evidence", ""),
                severity=s.get("severity", "low"),
            )
            for s in data.get("risk_signals", [])
        ]
        all_signals = regex_signals + semantic_signals
        # Upgrade classification using semantic signals too (not just regex signals)
        for sig in semantic_signals:
            stype = sig.signal_type if sig.signal_type in _SIGNAL_TO_CLASSIFICATION else "none"
            classification = _upgrade_classification(
                classification, _SIGNAL_TO_CLASSIFICATION[stype]
            )
        quarantine = data.get("quarantine_recommended", False) or any(
            s.severity in ("high", "critical") for s in all_signals
        )

        log.info(
            "security_triage.classified",
            extra={
                "asset": asset_name,
                "classification": classification,
                "quarantine": quarantine,
                "signal_count": len(all_signals),
            },
        )

        return SecurityPassport(
            asset_name=asset_name,
            classification=SecurityClassification(classification),
            confidence=float(data.get("confidence", 0.75)),
            risk_signals=all_signals,
            quarantine_recommended=quarantine,
            quarantine_reason=data.get("quarantine_reason", ""),
            remediation_steps=data.get("remediation_steps", []),
            regulatory_frameworks=data.get("regulatory_frameworks", []),
            payload_fingerprint=fingerprint,
            model_used=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cache_hit=response.cache_hit,
        )
