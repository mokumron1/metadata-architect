"""
Reading Level Validator.

Two-stage approach:
  Stage 1 (fast, free): textstat Flesch-Kincaid Grade Level.
              FK ≤ 8.5  → PASS immediately (no Claude call).
              FK > 10.5 → FAIL immediately (no Claude call).
  Stage 2 (Claude):     8.5 < FK ≤ 10.5 boundary zone —
              semantic ruling from Claude covers idioms, nominalisations,
              stacked clauses that mechanical scores miss.

This design minimises Claude API calls to only the ambiguous cases.
"""

import logging
from dataclasses import dataclass

import textstat

from metadata_architect.agents.claude_client import CachedBlock, ClaudeClient
from metadata_architect.config import get_settings
from metadata_architect.prompts.reading_level import BLOCK_ROLE, USER_TEMPLATE

log = logging.getLogger(__name__)

_FK_PASS_THRESHOLD = 8.5
_FK_FAIL_THRESHOLD = 10.5


@dataclass
class ReadingLevelResult:
    fk_score: float
    b1_compliant: bool
    estimated_grade_level: float
    ruling_reason: str
    problematic_phrases: list[str]
    method: str  # "textstat_pass" | "textstat_fail" | "claude_semantic"
    reading_level_label: str  # e.g. "B1 / 9th Grade"


class ReadingLevelValidator:
    """
    Validates that a Statement of Intent meets CEFR B1 / 9th Grade standard.
    Uses textstat for fast mechanical pre-filtering; Claude for boundary cases.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = ClaudeClient(model=settings.soi_draft_model, max_tokens=256)
        self._system_blocks = [CachedBlock.make(BLOCK_ROLE, cache=True)]

    def validate(self, text: str) -> ReadingLevelResult:
        fk_score = _compute_fk(text)

        if fk_score <= _FK_PASS_THRESHOLD:
            return ReadingLevelResult(
                fk_score=fk_score,
                b1_compliant=True,
                estimated_grade_level=fk_score,
                ruling_reason=f"Flesch-Kincaid score {fk_score:.1f} is below the 8.5 pass threshold.",
                problematic_phrases=[],
                method="textstat_pass",
                reading_level_label=_grade_label(fk_score),
            )

        if fk_score > _FK_FAIL_THRESHOLD:
            return ReadingLevelResult(
                fk_score=fk_score,
                b1_compliant=False,
                estimated_grade_level=fk_score,
                ruling_reason=f"Flesch-Kincaid score {fk_score:.1f} exceeds the 10.5 fail threshold.",
                problematic_phrases=[],
                method="textstat_fail",
                reading_level_label=_grade_label(fk_score),
            )

        # Boundary zone: delegate to Claude for semantic ruling
        log.info("reading_level.boundary_zone", extra={"fk_score": fk_score})
        return self._claude_ruling(text, fk_score)

    def _claude_ruling(self, text: str, fk_score: float) -> ReadingLevelResult:
        user_message = USER_TEMPLATE.format(fk_score=fk_score, text=text)
        response = self._client.call(self._system_blocks, user_message)
        data = response.parse_json()

        compliant = bool(data.get("b1_compliant", False))
        grade = float(data.get("estimated_grade_level", fk_score))
        return ReadingLevelResult(
            fk_score=fk_score,
            b1_compliant=compliant,
            estimated_grade_level=grade,
            ruling_reason=data.get("ruling_reason", ""),
            problematic_phrases=data.get("problematic_phrases", []),
            method="claude_semantic",
            reading_level_label=_grade_label(grade),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_fk(text: str) -> float:
    score = textstat.flesch_kincaid_grade(text)
    # textstat can return negative values for very short/simple text — clamp to 0
    return max(0.0, round(float(score), 2))


def _grade_label(fk_score: float) -> str:
    if fk_score <= 6.0:
        return "A2 / 6th Grade"
    if fk_score <= 8.5:
        return "B1 / 9th Grade"
    if fk_score <= 10.5:
        return "B2 / 10th Grade"
    if fk_score <= 12.0:
        return "C1 / 12th Grade"
    return "C2 / College+"
