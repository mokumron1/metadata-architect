"""
Interface 1: AI Metadata Drafter — "The Context Generator"

Converts cryptic technical column descriptors into plain-language business
definitions that meet the 9th Grade Standard (ISO 24495-1 / CEFR B1).

Vendor SMEs receive a "Nutritional Label" output they can One-Click Approve
or edit — shifting them from Authors to Editors.

Success metric: 75–80% reduction in manual metadata authorship time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from metadata_architect.agents.claude_client import CachedBlock, ClaudeClient
from metadata_architect.config import get_settings
from metadata_architect.onboarding.linguistic_service import (
    LinguisticReport,
    LinguisticValidationService,
)
from metadata_architect.prompts.metadata_drafter import BLOCK_ROLE, USER_TEMPLATE

log = logging.getLogger(__name__)


@dataclass
class ColumnContext:
    """Input payload for a single column to be drafted."""
    column_name: str
    data_type: str
    sample_values: list[str] = field(default_factory=list)
    table_context_hint: str = ""
    source_system: str = ""


@dataclass
class MetadataDraftResult:
    """
    "Nutritional Label" output for one column definition.

    The SME sees business_definition, plain_name, and usage_examples.
    They can One-Click Approve (status → 'approved') or refine inline.
    """
    column_name: str
    business_definition: str
    plain_name: str
    usage_examples: list[str]
    warnings: list[str]
    confidence: float
    readability_grade: float
    linguistic_report: LinguisticReport
    model_used: str
    input_tokens: int
    output_tokens: int
    cache_hit: bool

    @property
    def is_auto_approvable(self) -> bool:
        """True when linguistic checks pass and Claude confidence is high."""
        return (
            self.linguistic_report.is_compliant
            and self.confidence >= 0.80
            and self.readability_grade <= 9.0
        )


class MetadataDrafter:
    """
    Drafts plain-language business definitions for technical column descriptors.

    Usage::

        drafter = MetadataDrafter()
        result = drafter.draft(ColumnContext(
            column_name="AMT_D_01",
            data_type="DECIMAL(18,2)",
            sample_values=["1200.00", "500.50", "0.00"],
            table_context_hint="daily transaction settlement table",
        ))
        if result.is_auto_approvable:
            # write to Enterprise_Glossary directly
            ...
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._model = settings.soi_draft_model
        self._client = ClaudeClient(model=self._model, max_tokens=512)
        self._validator = LinguisticValidationService()

    def draft(self, col: ColumnContext) -> MetadataDraftResult:
        context = {
            "column_name": col.column_name,
            "data_type": col.data_type,
            "sample_values": col.sample_values[:10],
            "table_context_hint": col.table_context_hint,
            "source_system": col.source_system,
        }

        import json
        user_message = USER_TEMPLATE.format(context_json=json.dumps(context, indent=2))
        system_blocks = [CachedBlock.make(BLOCK_ROLE, cache=True)]

        response = self._client.call(system_blocks, user_message)
        data = response.parse_json()

        business_def = data.get("business_definition", "")
        cleaned = self._validator.clean_suggestion(business_def)
        linguistic_report = self._validator.validate(cleaned)

        log.info(
            "metadata_drafter.drafted",
            extra={
                "column": col.column_name,
                "confidence": data.get("confidence", 0),
                "compliant": linguistic_report.is_compliant,
            },
        )

        return MetadataDraftResult(
            column_name=col.column_name,
            business_definition=cleaned,
            plain_name=data.get("plain_name", col.column_name),
            usage_examples=data.get("usage_examples", []),
            warnings=data.get("warnings", []),
            confidence=float(data.get("confidence", 0.5)),
            readability_grade=float(data.get("readability_grade", 10.0)),
            linguistic_report=linguistic_report,
            model_used=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cache_hit=response.cache_hit,
        )

    def draft_batch(self, columns: list[ColumnContext]) -> list[MetadataDraftResult]:
        """Draft definitions for multiple columns sequentially."""
        return [self.draft(col) for col in columns]
