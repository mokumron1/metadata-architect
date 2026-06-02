"""
Trusted Data KPI (TDK) Score Calculator.

Implements the formula from the governance framework specification:

  clarity_score  = reading_level_ok*0.30 + no_jargon*0.30
                 + soi_length_ok*0.20 + glossary_coverage*0.20

  ownership_score = authority_assigned*0.50 + sla_met*0.30
                  + approved_not_rejected*0.20

  composite = clarity*0.6 + ownership*0.4

  # SLA breach penalty:
  composite = max(0.0, composite - SLA_BREACH_PENALTY)

All scores are in [0.0, 1.0].
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from metadata_architect.config import get_settings

log = logging.getLogger(__name__)

_SOI_MIN_WORDS = 20
_SOI_MAX_WORDS = 100
_FK_GRADE_PASS = 9.0  # Flesch-Kincaid grade threshold for "reading_level_ok"


@dataclass
class TdkInputs:
    """All inputs needed to compute a TDK score at a given lifecycle event."""

    # Clarity inputs
    reading_level_score: float          # Flesch-Kincaid grade; ≤ 9 = ok
    jargon_violation_count: int         # from JargonScrubResult
    statement_of_intent: str            # the SoI text (for word-count check)
    glossary_terms_used: int            # count of glossary terms matched
    total_columns: int                  # total columns in schema (denominator for coverage)

    # Ownership inputs
    context_authority_assigned: bool    # SME / Context Authority email is set
    sla_met: bool                       # True if SME acted before the deadline
    sme_approved: bool                  # True if SME approved or edited (not rejected)


@dataclass
class TdkScoreBreakdown:
    clarity_score: float
    ownership_score: float
    composite_score: float
    sla_breach_applied: bool
    score_reason: str

    # Sub-component scores for observability
    reading_level_ok: float
    no_jargon: float
    soi_length_ok: float
    glossary_coverage: float
    authority_assigned: float
    sla_met_score: float
    approved_not_rejected: float


class TdkCalculator:
    """
    Stateless calculator — call compute() with TdkInputs to get a breakdown.
    Instantiate once and reuse; reads SLA breach penalty from settings.
    """

    def __init__(self) -> None:
        self._breach_penalty = get_settings().tdk_sla_breach_penalty

    def compute(
        self,
        inputs: TdkInputs,
        *,
        sla_breached: bool = False,
    ) -> TdkScoreBreakdown:
        """
        Compute TDK scores.

        sla_breached: set True when the SLA monitor triggers Automated
                      Confidence Throttling (48-hour window elapsed).
        """
        # ---- Clarity sub-components ----
        reading_level_ok = 1.0 if inputs.reading_level_score <= _FK_GRADE_PASS else 0.0
        no_jargon = 1.0 if inputs.jargon_violation_count == 0 else max(
            0.0, 1.0 - (inputs.jargon_violation_count * 0.25)
        )
        soi_length_ok = _soi_length_score(inputs.statement_of_intent)
        glossary_coverage = _glossary_coverage_score(
            inputs.glossary_terms_used, inputs.total_columns
        )

        clarity = (
            reading_level_ok * 0.30
            + no_jargon * 0.30
            + soi_length_ok * 0.20
            + glossary_coverage * 0.20
        )
        clarity = round(min(1.0, max(0.0, clarity)), 4)

        # ---- Ownership sub-components ----
        authority_assigned = 1.0 if inputs.context_authority_assigned else 0.0
        sla_met_score = 1.0 if inputs.sla_met else 0.0
        approved_not_rejected = 1.0 if inputs.sme_approved else 0.0

        ownership = (
            authority_assigned * 0.50
            + sla_met_score * 0.30
            + approved_not_rejected * 0.20
        )
        ownership = round(min(1.0, max(0.0, ownership)), 4)

        # ---- Composite ----
        composite = round(clarity * 0.6 + ownership * 0.4, 4)

        # ---- SLA breach penalty ----
        if sla_breached:
            composite = round(max(0.0, composite - self._breach_penalty), 4)
            log.info(
                "tdk.sla_breach_penalty_applied",
                extra={"penalty": self._breach_penalty, "composite_after": composite},
            )

        reason = _build_reason(
            reading_level_ok, no_jargon, soi_length_ok, glossary_coverage,
            authority_assigned, sla_met_score, approved_not_rejected,
            sla_breached, self._breach_penalty,
        )

        return TdkScoreBreakdown(
            clarity_score=clarity,
            ownership_score=ownership,
            composite_score=composite,
            sla_breach_applied=sla_breached,
            score_reason=reason,
            reading_level_ok=reading_level_ok,
            no_jargon=no_jargon,
            soi_length_ok=soi_length_ok,
            glossary_coverage=glossary_coverage,
            authority_assigned=authority_assigned,
            sla_met_score=sla_met_score,
            approved_not_rejected=approved_not_rejected,
        )


# ---------------------------------------------------------------------------
# Sub-component helpers
# ---------------------------------------------------------------------------

def _word_count(text: str) -> int:
    return len(text.split())


def _soi_length_score(soi: str) -> float:
    wc = _word_count(soi)
    if _SOI_MIN_WORDS <= wc <= _SOI_MAX_WORDS:
        return 1.0
    if wc < _SOI_MIN_WORDS:
        # Proportional penalty — 0 words → 0.0, 20 words → 1.0
        return round(wc / _SOI_MIN_WORDS, 4)
    # Over 100 words — mild penalty, max 0.5 deduction
    excess = wc - _SOI_MAX_WORDS
    return round(max(0.5, 1.0 - (excess / 100)), 4)


def _glossary_coverage_score(terms_used: int, total_columns: int) -> float:
    """
    Ratio of glossary-matched terms to total columns.
    Columns without a matching glossary term indicate unmapped domain concepts.
    Capped at 1.0.
    """
    if total_columns == 0:
        return 0.0
    return round(min(1.0, terms_used / max(1, total_columns)), 4)


def _build_reason(
    rl_ok: float, no_jargon: float, soi_len: float, gl_cov: float,
    auth: float, sla: float, approved: float,
    sla_breached: bool, penalty: float,
) -> str:
    parts = []
    if rl_ok < 1.0:
        parts.append("reading level exceeds 9th Grade")
    if no_jargon < 1.0:
        parts.append("jargon violations detected")
    if soi_len < 1.0:
        parts.append("SoI length outside 20-100 word range")
    if gl_cov < 0.5:
        parts.append("low glossary term coverage")
    if auth < 1.0:
        parts.append("no context authority assigned")
    if sla < 1.0:
        parts.append("SLA not met")
    if approved < 1.0:
        parts.append("asset rejected or pending SME action")
    if sla_breached:
        parts.append(f"SLA breach penalty -{penalty} applied")
    return "; ".join(parts) if parts else "All clarity and ownership criteria met."
