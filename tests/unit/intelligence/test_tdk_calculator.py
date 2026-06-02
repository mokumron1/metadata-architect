"""
Unit tests for TdkCalculator.

Covers:
- All formula branches and weight combinations
- SLA breach penalty application
- Edge cases: 0 columns, empty SoI, all zeros
- Score clamping to [0.0, 1.0]
- Score reason generation
"""

import pytest

from metadata_architect.scoring.tdk_calculator import (
    TdkCalculator,
    TdkInputs,
    TdkScoreBreakdown,
    _soi_length_score,
    _glossary_coverage_score,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def calc() -> TdkCalculator:
    return TdkCalculator()


def _perfect_inputs() -> TdkInputs:
    return TdkInputs(
        reading_level_score=7.5,
        jargon_violation_count=0,
        statement_of_intent=(
            "This table stores the daily revenue totals grouped by region and currency. "
            "It supports the finance team in producing accurate audit reports each quarter."
        ),
        glossary_terms_used=4,
        total_columns=8,
        context_authority_assigned=True,
        sla_met=True,
        sme_approved=True,
    )


def _minimal_inputs() -> TdkInputs:
    return TdkInputs(
        reading_level_score=12.0,
        jargon_violation_count=5,
        statement_of_intent="X",
        glossary_terms_used=0,
        total_columns=10,
        context_authority_assigned=False,
        sla_met=False,
        sme_approved=False,
    )


# ---------------------------------------------------------------------------
# Score range invariants
# ---------------------------------------------------------------------------

class TestScoreRangeInvariants:
    def test_perfect_inputs_high_score(self, calc):
        result = calc.compute(_perfect_inputs())
        assert result.composite_score >= 0.80

    def test_minimal_inputs_low_score(self, calc):
        result = calc.compute(_minimal_inputs())
        assert result.composite_score <= 0.40

    def test_composite_never_above_1(self, calc):
        result = calc.compute(_perfect_inputs())
        assert result.composite_score <= 1.0

    def test_composite_never_below_0(self, calc):
        result = calc.compute(_minimal_inputs(), sla_breached=True)
        assert result.composite_score >= 0.0

    def test_clarity_in_range(self, calc):
        result = calc.compute(_perfect_inputs())
        assert 0.0 <= result.clarity_score <= 1.0

    def test_ownership_in_range(self, calc):
        result = calc.compute(_perfect_inputs())
        assert 0.0 <= result.ownership_score <= 1.0


# ---------------------------------------------------------------------------
# Clarity sub-components
# ---------------------------------------------------------------------------

class TestClarityComponents:
    def test_reading_level_ok_passes_at_9(self, calc):
        inputs = _perfect_inputs()
        inputs.reading_level_score = 9.0
        result = calc.compute(inputs)
        assert result.reading_level_ok == 1.0

    def test_reading_level_fails_above_9(self, calc):
        inputs = _perfect_inputs()
        inputs.reading_level_score = 9.1
        result = calc.compute(inputs)
        assert result.reading_level_ok == 0.0

    def test_no_jargon_perfect_with_zero_violations(self, calc):
        inputs = _perfect_inputs()
        inputs.jargon_violation_count = 0
        result = calc.compute(inputs)
        assert result.no_jargon == 1.0

    def test_jargon_score_degrades_with_violations(self, calc):
        inputs = _perfect_inputs()
        inputs.jargon_violation_count = 2
        result = calc.compute(inputs)
        assert result.no_jargon == pytest.approx(0.5, abs=0.01)

    def test_jargon_score_clamps_to_zero(self, calc):
        inputs = _perfect_inputs()
        inputs.jargon_violation_count = 10
        result = calc.compute(inputs)
        assert result.no_jargon == 0.0

    def test_soi_length_ok_within_range(self, calc):
        inputs = _perfect_inputs()
        result = calc.compute(inputs)
        assert result.soi_length_ok == 1.0

    def test_soi_length_penalised_when_too_short(self, calc):
        inputs = _perfect_inputs()
        inputs.statement_of_intent = "Too short."
        result = calc.compute(inputs)
        assert result.soi_length_ok < 1.0

    def test_glossary_coverage_full(self, calc):
        inputs = _perfect_inputs()
        inputs.glossary_terms_used = 8
        inputs.total_columns = 8
        result = calc.compute(inputs)
        assert result.glossary_coverage == 1.0

    def test_glossary_coverage_zero_when_no_columns(self, calc):
        inputs = _perfect_inputs()
        inputs.total_columns = 0
        result = calc.compute(inputs)
        assert result.glossary_coverage == 0.0

    def test_glossary_coverage_capped_at_1(self, calc):
        inputs = _perfect_inputs()
        inputs.glossary_terms_used = 100
        inputs.total_columns = 5
        result = calc.compute(inputs)
        assert result.glossary_coverage == 1.0


# ---------------------------------------------------------------------------
# Ownership sub-components
# ---------------------------------------------------------------------------

class TestOwnershipComponents:
    def test_full_ownership_requires_all_three(self, calc):
        result = calc.compute(_perfect_inputs())
        assert result.ownership_score == pytest.approx(1.0, abs=0.001)

    def test_no_authority_halves_ownership(self, calc):
        inputs = _perfect_inputs()
        inputs.context_authority_assigned = False
        result = calc.compute(inputs)
        assert result.ownership_score == pytest.approx(0.5, abs=0.01)

    def test_sla_miss_reduces_ownership(self, calc):
        inputs = _perfect_inputs()
        inputs.sla_met = False
        result = calc.compute(inputs)
        assert result.ownership_score == pytest.approx(0.70, abs=0.01)

    def test_rejection_reduces_ownership(self, calc):
        inputs = _perfect_inputs()
        inputs.sme_approved = False
        result = calc.compute(inputs)
        assert result.ownership_score == pytest.approx(0.80, abs=0.01)

    def test_zero_ownership_when_all_fail(self, calc):
        inputs = _perfect_inputs()
        inputs.context_authority_assigned = False
        inputs.sla_met = False
        inputs.sme_approved = False
        result = calc.compute(inputs)
        assert result.ownership_score == pytest.approx(0.0, abs=0.001)


# ---------------------------------------------------------------------------
# Composite formula weights
# ---------------------------------------------------------------------------

class TestCompositeFormula:
    def test_composite_weights_60_40(self, calc):
        """Composite = clarity*0.6 + ownership*0.4"""
        inputs = _perfect_inputs()
        result = calc.compute(inputs)
        expected = result.clarity_score * 0.6 + result.ownership_score * 0.4
        assert result.composite_score == pytest.approx(expected, abs=0.001)

    def test_clarity_dominant_when_ownership_zero(self, calc):
        inputs = _perfect_inputs()
        inputs.context_authority_assigned = False
        inputs.sla_met = False
        inputs.sme_approved = False
        result = calc.compute(inputs)
        # ownership = 0, so composite = clarity * 0.6
        assert result.composite_score == pytest.approx(result.clarity_score * 0.6, abs=0.001)


# ---------------------------------------------------------------------------
# SLA breach penalty
# ---------------------------------------------------------------------------

class TestSlaBreachPenalty:
    def test_penalty_applied_when_breached(self, calc):
        result_no_breach = calc.compute(_perfect_inputs(), sla_breached=False)
        result_breach = calc.compute(_perfect_inputs(), sla_breached=True)
        assert result_breach.composite_score < result_no_breach.composite_score

    def test_penalty_amount_matches_config(self, calc):
        from metadata_architect.config import get_settings
        penalty = get_settings().tdk_sla_breach_penalty
        result_no_breach = calc.compute(_perfect_inputs(), sla_breached=False)
        result_breach = calc.compute(_perfect_inputs(), sla_breached=True)
        assert result_no_breach.composite_score - result_breach.composite_score == pytest.approx(
            penalty, abs=0.001
        )

    def test_penalty_does_not_go_below_zero(self, calc):
        result = calc.compute(_minimal_inputs(), sla_breached=True)
        assert result.composite_score >= 0.0

    def test_sla_breach_flag_recorded(self, calc):
        result = calc.compute(_perfect_inputs(), sla_breached=True)
        assert result.sla_breach_applied is True

    def test_no_breach_flag_when_not_breached(self, calc):
        result = calc.compute(_perfect_inputs(), sla_breached=False)
        assert result.sla_breach_applied is False


# ---------------------------------------------------------------------------
# Score reason
# ---------------------------------------------------------------------------

class TestScoreReason:
    def test_perfect_score_positive_reason(self, calc):
        result = calc.compute(_perfect_inputs())
        assert "met" in result.score_reason.lower()

    def test_reason_mentions_jargon_when_violations_present(self, calc):
        inputs = _perfect_inputs()
        inputs.jargon_violation_count = 3
        result = calc.compute(inputs)
        assert "jargon" in result.score_reason.lower()

    def test_reason_mentions_sla_breach(self, calc):
        result = calc.compute(_perfect_inputs(), sla_breached=True)
        assert "breach" in result.score_reason.lower()

    def test_reason_is_string(self, calc):
        result = calc.compute(_perfect_inputs())
        assert isinstance(result.score_reason, str)


# ---------------------------------------------------------------------------
# Sub-function unit tests
# ---------------------------------------------------------------------------

class TestSoiLengthScore:
    @pytest.mark.parametrize("text,expected", [
        ("word " * 20, 1.0),   # exactly 20 words — pass
        ("word " * 50, 1.0),   # 50 words — pass
        ("word " * 100, 1.0),  # exactly 100 — pass
        ("short", 0.05),        # 1 word — ~0.05
        ("word " * 150, 0.50), # 50 over — penalty floor at 0.5
    ])
    def test_length_scoring(self, text, expected):
        score = _soi_length_score(text.strip())
        assert score == pytest.approx(expected, abs=0.1)


class TestGlossaryCoverageScore:
    def test_perfect_coverage(self):
        assert _glossary_coverage_score(5, 5) == 1.0

    def test_no_coverage(self):
        assert _glossary_coverage_score(0, 10) == 0.0

    def test_zero_columns(self):
        assert _glossary_coverage_score(3, 0) == 0.0

    def test_overcoverage_capped(self):
        assert _glossary_coverage_score(20, 5) == 1.0

    def test_partial_coverage(self):
        assert _glossary_coverage_score(3, 10) == pytest.approx(0.3, abs=0.01)
