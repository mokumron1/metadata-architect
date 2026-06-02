"""
Thin wrapper around the Anthropic Python SDK.

Responsibilities:
- Prompt caching via cache_control blocks on stable system prompt sections
- Exponential-backoff retry on transient errors (overload, rate-limit)
- Structured token usage logging for observability
- JSON response extraction with fallback error
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)


@dataclass
class ClaudeResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_tokens > 0

    def parse_json(self) -> dict[str, Any]:
        """Parse content as JSON, raising ValueError on failure."""
        text = self.content.strip()
        # Strip markdown fences if model wraps despite instructions
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                line for line in lines if not line.startswith("```")
            ).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Claude returned non-JSON response: {self.content[:200]!r}"
            ) from exc


class CachedBlock:
    """Helper to build a cacheable system prompt text block."""

    @staticmethod
    def make(text: str, cache: bool = True) -> dict[str, Any]:
        block: dict[str, Any] = {"type": "text", "text": text}
        if cache:
            block["cache_control"] = {"type": "ephemeral"}
        return block


class ClaudeClient:
    """
    Reusable Claude API client with caching and retry.

    Each agent instantiates one ClaudeClient with its chosen model.
    System prompt blocks that are large and stable should pass cache=True
    to CachedBlock.make() — this activates prompt caching and reduces
    per-call token cost for those blocks by ~90% on cache hits.
    """

    def __init__(self, model: str, max_tokens: int = 1024) -> None:
        from metadata_architect.config import get_settings
        settings = get_settings()
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = model
        self.max_tokens = max_tokens

    @retry(
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def call(
        self,
        system_blocks: list[dict[str, Any]],
        user_message: str,
    ) -> ClaudeResponse:
        """
        Send a request to the Claude API and return a structured response.

        system_blocks: list of content block dicts (use CachedBlock.make()).
        user_message:  the dynamic per-call user turn.
        """
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": user_message}],
        )

        usage = response.usage
        cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0

        result = ClaudeResponse(
            content=response.content[0].text,
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
        )

        log.info(
            "claude_call",
            extra={
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cache_creation_tokens": cache_creation,
                "cache_read_tokens": cache_read,
                "cache_hit": result.cache_hit,
            },
        )
        return result
