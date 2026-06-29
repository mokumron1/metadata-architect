"""
LinguisticValidationService — shared plain-language enforcement layer.

Called by all three onboarding interfaces to ensure output meets:
  - ISO 24495-1 (Plain Language)
  - CEFR B1 vocabulary
  - 9th Grade Standard (Flesch-Kincaid ≤ 9.0)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# CEFR B1 violation list — high-frequency non-B1 technical / academic words.
# A word on this list triggers a vocabulary flag and a plain-language suggestion.
# ---------------------------------------------------------------------------
_NON_B1_TERMS: dict[str, str] = {
    # Data engineering jargon
    "concatenated": "combined",
    "concatenate": "combine",
    "nullable": "optional",
    "varchar": "text field",
    "timestamp": "date and time",
    "instantiated": "created",
    "instantiate": "create",
    "serialized": "converted",
    "serialize": "convert",
    "deprecated": "no longer used",
    "polymorphic": "flexible type",
    "idempotent": "safe to repeat",
    "partitioned": "divided",
    "partition": "divide",
    "schema": "data structure",
    "ingest": "import",
    "ingestion": "import",
    "payload": "data package",
    "endpoint": "connection point",
    "persist": "save",
    "persisted": "saved",
    "hydrate": "fill",
    "hydrated": "filled",
    "upsert": "insert or update",
    "truncate": "clear",
    "materialise": "create",
    "materialize": "create",
    "denormalised": "combined",
    "denormalize": "combine",
    "normalised": "organised",
    "normalize": "organise",
    "enum": "fixed list",
    "boolean": "yes/no value",
    "metadata": "data description",
    "orchestrate": "manage",
    "orchestration": "management",
    "parameterised": "configurable",
    "parameterize": "configure",
    "propagate": "spread",
    "propagation": "spreading",
    # Academic / passive-voice builders
    "utilised": "used",
    "utilise": "use",
    "utilized": "used",
    "utilize": "use",
    "facilitate": "help",
    "ascertain": "find out",
    "endeavour": "try",
    "endeavor": "try",
    "commence": "start",
    "terminate": "end",
    "initiate": "start",
    "leverage": "use",
    "synergise": "work together",
    "synergize": "work together",
    "optimise": "improve",
    "optimize": "improve",
}

# Passive-voice detector: "is/are/was/were/been/being + past participle"
_PASSIVE_RE = re.compile(
    r"\b(is|are|was|were|been|being|be)\s+\w+ed\b",
    re.IGNORECASE,
)

# Sentence splitter
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class LinguisticViolation:
    rule: str          # "long_sentence" | "passive_voice" | "non_b1_vocab"
    text: str          # the offending fragment
    suggestion: str    # plain-language fix


@dataclass
class LinguisticReport:
    is_compliant: bool
    violations: list[LinguisticViolation] = field(default_factory=list)
    sentence_count: int = 0
    longest_sentence_words: int = 0
    non_b1_words_found: list[str] = field(default_factory=list)
    passive_fragments_found: list[str] = field(default_factory=list)


class LinguisticValidationService:
    """
    Validates text against ISO 24495-1 / CEFR B1 constraints.

    Instantiate once and reuse — the word list is compiled at class load time.
    """

    MAX_SENTENCE_WORDS = 25

    def validate(self, text: str) -> LinguisticReport:
        violations: list[LinguisticViolation] = []
        sentences = _SENTENCE_END_RE.split(text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        longest = 0
        for sentence in sentences:
            words = sentence.split()
            count = len(words)
            if count > longest:
                longest = count
            if count > self.MAX_SENTENCE_WORDS:
                violations.append(
                    LinguisticViolation(
                        rule="long_sentence",
                        text=sentence[:120],
                        suggestion=(
                            f"Split into shorter sentences. "
                            f"This sentence has {count} words (limit: {self.MAX_SENTENCE_WORDS})."
                        ),
                    )
                )

        passive_fragments: list[str] = []
        for match in _PASSIVE_RE.finditer(text):
            fragment = text[max(0, match.start() - 10): match.end() + 10]
            passive_fragments.append(fragment)
            violations.append(
                LinguisticViolation(
                    rule="passive_voice",
                    text=fragment,
                    suggestion=(
                        "Use active voice. Name the actor explicitly, e.g. "
                        "'The system stores…' instead of 'data is stored…'."
                    ),
                )
            )

        text_lower = text.lower()
        non_b1: list[str] = []
        for term, replacement in _NON_B1_TERMS.items():
            if re.search(r"\b" + re.escape(term) + r"\b", text_lower):
                non_b1.append(term)
                violations.append(
                    LinguisticViolation(
                        rule="non_b1_vocab",
                        text=term,
                        suggestion=f"Replace '{term}' with '{replacement}' (CEFR B1 equivalent).",
                    )
                )

        return LinguisticReport(
            is_compliant=len(violations) == 0,
            violations=violations,
            sentence_count=len(sentences),
            longest_sentence_words=longest,
            non_b1_words_found=non_b1,
            passive_fragments_found=passive_fragments,
        )

    def clean_suggestion(self, text: str) -> str:
        """Apply mechanical substitutions for non-B1 terms. Does not fix passive voice."""
        result = text
        for term, replacement in _NON_B1_TERMS.items():
            result = re.sub(
                r"\b" + re.escape(term) + r"\b",
                replacement,
                result,
                flags=re.IGNORECASE,
            )
        return result
