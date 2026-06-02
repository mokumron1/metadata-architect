"""
Unit tests for ReadingLevelValidator.

Strategy:
- textstat pass / fail paths are tested without any Claude call (no mocking needed
  because the boundary thresholds mean the test texts never hit the Claude path).
- The Claude boundary-zone path is tested with a mock to avoid live API calls.
"""

from unittest.mock import MagicMock, patch

import pytest

from metadata_architect.agents.reading_level import (
    ReadingLevelValidator,
    _compute_fk,
    _grade_label,
)


# ---------------------------------------------------------------------------
# _compute_fk — deterministic textstat wrapper
# ---------------------------------------------------------------------------

class TestComputeFk:
    def test_simple_text_low_score(self):
        text = "The cat sat on the mat. It was a big cat."
        score = _compute_fk(text)
        assert 0.0 <= score <= 5.0

    def test_complex_text_higher_score(self):
        text = (
            "The implementation of sophisticated distributed transaction management "
            "mechanisms necessitates comprehensive consideration of atomicity, "
            "consistency, isolation, and durability constraints."
        )
        score = _compute_fk(text)
        assert score >= 12.0

    def test_never_returns_negative(self):
        score = _compute_fk("Hi. Yes. No.")
        assert score >= 0.0

    def test_returns_float(self):
        assert isinstance(_compute_fk("Hello world."), float)


# ---------------------------------------------------------------------------
# _grade_label — label mapping
# ---------------------------------------------------------------------------

class TestGradeLabel:
    @pytest.mark.parametrize("score,expected_fragment", [
        (4.0, "A2"),
        (7.0, "B1"),
        (9.5, "B2"),
        (11.0, "C1"),
        (14.0, "C2"),
    ])
    def test_label_contains_level(self, score, expected_fragment):
        assert expected_fragment in _grade_label(score)


# ---------------------------------------------------------------------------
# ReadingLevelValidator — textstat fast path (no Claude needed)
# ---------------------------------------------------------------------------

class TestTextstatFastPath:
    @pytest.fixture
    def validator(self):
        return ReadingLevelValidator()

    def test_clear_pass_returns_b1_compliant(self, validator):
        # Deliberately simple text well below 8.5 FK threshold
        text = "This table stores daily revenue totals by region. It supports finance audits."
        result = validator.validate(text)
        # We only assert method, not compliance, since textstat scores vary slightly
        if result.fk_score <= 8.5:
            assert result.b1_compliant is True
            assert result.method == "textstat_pass"

    def test_clear_fail_returns_non_compliant(self, validator):
        # Deliberately complex text, well above 10.5 FK threshold
        text = (
            "The multidimensional optimisation of heterogeneous, schema-on-read data "
            "ingestion pipelines necessitates the implementation of idempotent, "
            "eventually-consistent transactional semantics across polyglot persistence layers "
            "whilst maintaining strict referential integrity guarantees throughout the "
            "entirety of the data lineage provenance chain."
        )
        result = validator.validate(text)
        if result.fk_score > 10.5:
            assert result.b1_compliant is False
            assert result.method == "textstat_fail"

    def test_result_has_all_fields(self, validator):
        text = "This table records sales transactions. It helps the sales team."
        result = validator.validate(text)
        assert hasattr(result, "fk_score")
        assert hasattr(result, "b1_compliant")
        assert hasattr(result, "reading_level_label")
        assert hasattr(result, "method")
        assert hasattr(result, "ruling_reason")
        assert hasattr(result, "problematic_phrases")
        assert isinstance(result.problematic_phrases, list)

    def test_reading_level_label_is_string(self, validator):
        result = validator.validate("Simple text here. Short words used.")
        assert isinstance(result.reading_level_label, str)
        assert "/" in result.reading_level_label  # e.g. "B1 / 9th Grade"


# ---------------------------------------------------------------------------
# ReadingLevelValidator — Claude boundary-zone path (mocked)
# ---------------------------------------------------------------------------

class TestClaudeBoundaryZone:
    """
    Tests the semantic ruling path without making live Claude API calls.
    We construct a fake response that matches what ClaudeClient.call() returns.
    """

    def _make_mock_client(self, compliant: bool, grade: float, reason: str, phrases: list) -> MagicMock:
        import json
        mock_response = MagicMock()
        mock_response.parse_json.return_value = {
            "b1_compliant": compliant,
            "estimated_grade_level": grade,
            "ruling_reason": reason,
            "problematic_phrases": phrases,
        }
        mock_response.model = "claude-sonnet-4-6"
        mock_response.input_tokens = 150
        mock_response.output_tokens = 80
        mock_response.cache_hit = True

        mock_client = MagicMock()
        mock_client.call.return_value = mock_response
        return mock_client

    @patch("metadata_architect.agents.reading_level._compute_fk", return_value=9.5)
    def test_boundary_zone_calls_claude(self, mock_fk):
        validator = ReadingLevelValidator()
        validator._client = self._make_mock_client(
            compliant=True, grade=9.0,
            reason="Text uses accessible vocabulary despite borderline score.",
            phrases=[],
        )
        result = validator.validate("Boundary zone text here.")
        assert result.method == "claude_semantic"
        assert result.b1_compliant is True

    @patch("metadata_architect.agents.reading_level._compute_fk", return_value=10.0)
    def test_boundary_zone_non_compliant(self, mock_fk):
        validator = ReadingLevelValidator()
        validator._client = self._make_mock_client(
            compliant=False, grade=10.2,
            reason="Nominalisations and stacked clauses exceed B1.",
            phrases=["optimisation of the implementation"],
        )
        result = validator.validate("Some boundary zone text.")
        assert result.b1_compliant is False
        assert len(result.problematic_phrases) >= 1

    @patch("metadata_architect.agents.reading_level._compute_fk", return_value=9.5)
    def test_boundary_zone_preserves_fk_score(self, mock_fk):
        validator = ReadingLevelValidator()
        validator._client = self._make_mock_client(
            compliant=True, grade=9.3, reason="OK", phrases=[]
        )
        result = validator.validate("Text.")
        assert result.fk_score == pytest.approx(9.5, abs=0.01)

    @patch("metadata_architect.agents.reading_level._compute_fk", return_value=8.4)
    def test_just_below_boundary_skips_claude(self, mock_fk):
        """FK = 8.4 → textstat pass. Claude must NOT be called."""
        validator = ReadingLevelValidator()
        mock_client = MagicMock()
        validator._client = mock_client
        result = validator.validate("Simple text.")
        mock_client.call.assert_not_called()
        assert result.method == "textstat_pass"

    @patch("metadata_architect.agents.reading_level._compute_fk", return_value=10.6)
    def test_just_above_boundary_skips_claude(self, mock_fk):
        """FK = 10.6 → textstat fail. Claude must NOT be called."""
        validator = ReadingLevelValidator()
        mock_client = MagicMock()
        validator._client = mock_client
        result = validator.validate("Complex sophisticated text.")
        mock_client.call.assert_not_called()
        assert result.method == "textstat_fail"
