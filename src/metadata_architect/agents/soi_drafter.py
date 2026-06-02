"""
Statement of Intent Drafter.

Takes a ParsedSchema + optional lineage and glossary context,
calls Claude with cached system prompt blocks, and returns a
structured SoIDraftResult ready to be persisted as a SoIDraft record.
"""

import json
import logging
from dataclasses import dataclass, field

from metadata_architect.agents.claude_client import CachedBlock, ClaudeClient, ClaudeResponse
from metadata_architect.config import get_settings
from metadata_architect.parsers.schema_parser import ParsedSchema
from metadata_architect.prompts.soi_drafter import (
    BLOCK_ROLE,
    USER_TEMPLATE,
    build_glossary_block,
)

log = logging.getLogger(__name__)

# Minimum context tokens to justify caching a glossary block.
# Below this size, caching costs more than it saves.
_MIN_CACHE_TOKENS = 200


@dataclass
class SoIDraftResult:
    statement_of_intent: str
    reading_level: str
    reading_level_score: float
    confidence: float
    glossary_terms_used: list[str]
    drafting_notes: str
    model_used: str
    input_tokens: int
    output_tokens: int
    cache_hit: bool
    escalate: bool = False  # True when confidence < threshold

    @property
    def tdk_initial_score(self) -> float:
        """
        Provisional TDK score from the draft alone (before SME review).
        The full score is computed by TdkScoreCalculator after SME action.
        """
        rl_ok = 1.0 if self.reading_level_score <= 9.0 else 0.0
        return round(min(1.0, self.confidence * 0.5 + rl_ok * 0.3 + 0.2), 4)


class SoIDrafter:
    """
    Drafts a Statement of Intent for a data asset.

    The enterprise glossary and ISO-24495-1 rules are injected as cached
    system prompt blocks, amortising their token cost across all drafting calls.
    """

    def __init__(self, glossary: dict[str, str] | None = None) -> None:
        settings = get_settings()
        self._model = settings.soi_draft_model
        self._escalation_model = settings.soi_escalation_model
        self._escalation_threshold = settings.tdk_confidence_escalation_threshold
        self._glossary = glossary or {}
        self._client = ClaudeClient(model=self._model, max_tokens=512)
        self._escalation_client = ClaudeClient(model=self._escalation_model, max_tokens=768)

    def draft(
        self,
        schema: ParsedSchema,
        lineage_context: list[str] | None = None,
        asset_type: str = "table",
    ) -> SoIDraftResult:
        """
        Generate a SoI draft for the given schema.

        If Claude's confidence is below the escalation threshold,
        the draft is automatically retried with the Opus escalation model.
        """
        context_packet = _build_context_packet(schema, lineage_context, asset_type)
        system_blocks = self._build_system_blocks()
        user_message = USER_TEMPLATE.format(context_json=json.dumps(context_packet, indent=2))

        response = self._client.call(system_blocks, user_message)
        result = _parse_response(response, self._model)

        if result.confidence < self._escalation_threshold:
            log.info(
                "soi_drafter.escalating",
                extra={"confidence": result.confidence, "asset": schema.asset_name},
            )
            escalation_blocks = self._build_system_blocks(escalating=True)
            escalation_response = self._escalation_client.call(escalation_blocks, user_message)
            result = _parse_response(escalation_response, self._escalation_model)
            result.escalate = True

        return result

    def _build_system_blocks(self, *, escalating: bool = False) -> list[dict]:
        glossary_text = build_glossary_block(self._glossary)
        # Cache glossary only if it's large enough to justify it
        should_cache_glossary = len(glossary_text) > _MIN_CACHE_TOKENS

        blocks = [
            CachedBlock.make(BLOCK_ROLE, cache=True),
            CachedBlock.make(glossary_text, cache=should_cache_glossary),
        ]
        if escalating:
            blocks.append(
                CachedBlock.make(
                    "NOTE: This is an escalated draft. The previous attempt had low confidence. "
                    "Make conservative assumptions explicit in drafting_notes. "
                    "Prefer a narrow, accurate scope over a broad, speculative one.",
                    cache=False,
                )
            )
        return blocks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_context_packet(
    schema: ParsedSchema,
    lineage_context: list[str] | None,
    asset_type: str,
) -> dict:
    columns = []
    for col in schema.columns:
        entry: dict = {
            "name": col.name,
            "type": col.data_type,
            "nullable": col.nullable,
        }
        if col.is_primary_key:
            entry["primary_key"] = True
        if col.is_foreign_key:
            entry["foreign_key_references"] = col.references
        if col.default_value:
            entry["default"] = col.default_value
        if col.comment:
            entry["comment"] = col.comment
        if col.constraints:
            entry["constraints"] = col.constraints
        columns.append(entry)

    packet: dict = {
        "asset_name": schema.asset_name,
        "asset_type": asset_type,
        "dialect": schema.dialect,
        "columns": columns,
        "primary_keys": schema.primary_keys,
    }
    if schema.foreign_keys:
        packet["foreign_keys"] = schema.foreign_keys
    if lineage_context:
        packet["lineage"] = lineage_context
    return packet


def _parse_response(response: ClaudeResponse, model: str) -> SoIDraftResult:
    data = response.parse_json()

    soi = data.get("statement_of_intent", "")
    if not soi:
        raise ValueError("Claude response missing 'statement_of_intent' field.")

    return SoIDraftResult(
        statement_of_intent=soi,
        reading_level=data.get("reading_level", "Unknown"),
        reading_level_score=float(data.get("reading_level_score", 0.0)),
        confidence=float(data.get("confidence", 0.5)),
        glossary_terms_used=data.get("glossary_terms_used", []),
        drafting_notes=data.get("drafting_notes", ""),
        model_used=model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cache_hit=response.cache_hit,
    )
