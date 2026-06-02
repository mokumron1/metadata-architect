"""
Jargon Scrubber agent.

Evaluates a Statement of Intent for ISO 24495-1 plain language violations.
Runs as a second, focused Claude call after SoI drafting — or standalone
when called from the Gate 2 CI/CD endpoint on hand-authored metadata.
"""

import logging
from dataclasses import dataclass, field

from metadata_architect.agents.claude_client import CachedBlock, ClaudeClient, ClaudeResponse
from metadata_architect.config import get_settings
from metadata_architect.prompts.jargon_scrubber import BLOCK_ROLE, USER_TEMPLATE
from metadata_architect.prompts.soi_drafter import build_glossary_block

log = logging.getLogger(__name__)


@dataclass
class JargonViolation:
    term: str
    char_position: int
    rule_violated: str  # UNDEFINED_ACRONYM | SENTENCE_TOO_LONG | JARGON | PASSIVE_VOICE | READING_LEVEL
    suggestion: str


@dataclass
class JargonScrubResult:
    violations: list[JargonViolation] = field(default_factory=list)
    sentence_count: int = 0
    longest_sentence_words: int = 0
    is_compliant: bool = True
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit: bool = False


class JargonScrubber:
    """
    Evaluates a Statement of Intent for plain language violations.

    The scrubber rules and glossary are cached system prompt blocks.
    The SoI text is injected as the dynamic user turn.
    """

    def __init__(self, glossary: dict[str, str] | None = None) -> None:
        settings = get_settings()
        self._glossary = glossary or {}
        self._client = ClaudeClient(model=settings.soi_draft_model, max_tokens=1024)
        self._system_blocks = self._build_system_blocks()

    def scrub(self, soi_text: str) -> JargonScrubResult:
        """
        Analyse `soi_text` for ISO 24495-1 violations.
        Returns a JargonScrubResult with a list of zero or more violations.
        """
        user_message = USER_TEMPLATE.format(soi_text=soi_text)
        response = self._client.call(self._system_blocks, user_message)
        return _parse_response(response)

    def _build_system_blocks(self) -> list[dict]:
        glossary_text = build_glossary_block(self._glossary)
        return [
            CachedBlock.make(BLOCK_ROLE, cache=True),
            CachedBlock.make(glossary_text, cache=len(glossary_text) > 200),
        ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_response(response: ClaudeResponse) -> JargonScrubResult:
    data = response.parse_json()

    violations = [
        JargonViolation(
            term=v.get("term", ""),
            char_position=int(v.get("char_position", 0)),
            rule_violated=v.get("rule_violated", "JARGON"),
            suggestion=v.get("suggestion", ""),
        )
        for v in data.get("violations", [])
    ]

    return JargonScrubResult(
        violations=violations,
        sentence_count=int(data.get("sentence_count", 0)),
        longest_sentence_words=int(data.get("longest_sentence_words", 0)),
        is_compliant=bool(data.get("is_compliant", len(violations) == 0)),
        model_used=response.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cache_hit=response.cache_hit,
    )
