"""
Interface 3: Natural Language Interview Bot — SoI & SLA Generator

Converts a vendor technical lead's natural language answers into a
machine-executable ODCS (Open Data Contract Standard) YAML data contract.

Three structured "Nuchter" (pragmatic) questions extract:
  Q1: What business decision does this data enable?
  Q2: How often is this data updated (Freshness)?
  Q3: What are the mandatory fields for this intent?

The output is a versioned, machine-readable Data Contract (YAML + JSON)
ready for ingestion by the Governance Entry Gate.
"""

from __future__ import annotations

import json
import logging
import textwrap
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ruamel.yaml import YAML as _YAML

from metadata_architect.agents.claude_client import CachedBlock, ClaudeClient
from metadata_architect.config import get_settings
from metadata_architect.onboarding.linguistic_service import LinguisticValidationService
from metadata_architect.prompts.interview_bot import BLOCK_ROLE, ODCS_YAML_TEMPLATE, USER_TEMPLATE

log = logging.getLogger(__name__)

SOI_CATEGORIES = [
    "Reporting", "Compliance", "R&D", "Operations",
    "Analytics", "Finance", "Customer", "Risk",
]


@dataclass
class InterviewAnswers:
    """The three structured answers from the vendor technical lead."""
    answer_business_decision: str
    answer_freshness: str
    answer_mandatory_fields: str
    asset_name: str
    owner: str = ""
    support_contact: str = ""
    additional_context: str = ""


@dataclass
class SchemaHint:
    field: str
    type: str
    required: bool
    description: str


@dataclass
class DataContractDraft:
    """
    Versioned machine-readable Data Contract ready for registry storage.

    contract_yaml: ODCS v3.0.0 YAML string — persist to Data_Contract_Registry.
    contract_json: Equivalent JSON for programmatic consumption.
    soi_category: One of the SOI_CATEGORIES — persist to SoI_Repository.
    """
    contract_id: str
    asset_name: str
    soi_category: str
    business_decision: str
    mandatory_fields: list[str]
    update_frequency: str
    freshness_max_age: str
    retention_period: str
    availability_sla: float
    quality_completeness: float
    schema_hints: list[SchemaHint]
    confidence: float
    clarification_needed: list[str]
    contract_yaml: str
    contract_json: dict
    linguistic_compliant: bool
    model_used: str
    input_tokens: int
    output_tokens: int
    cache_hit: bool
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_ready_for_gate(self) -> bool:
        """Contract is ready to feed the Governance Entry Gate when high-confidence."""
        return self.confidence >= 0.75 and not self.clarification_needed


class InterviewBot:
    """
    One-shot NL interview → ODCS Data Contract.

    The vendor answers the three questions; this class calls Claude to
    extract structured ODCS metadata, validates the intent description
    against CEFR B1 standards, and renders the final YAML contract.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._model = settings.soi_draft_model
        self._client = ClaudeClient(model=self._model, max_tokens=1024)
        self._validator = LinguisticValidationService()

    def generate_contract(self, answers: InterviewAnswers) -> DataContractDraft:
        user_message = USER_TEMPLATE.format(
            answer_business_decision=answers.answer_business_decision,
            answer_freshness=answers.answer_freshness,
            answer_mandatory_fields=answers.answer_mandatory_fields,
            additional_context=answers.additional_context or "(none provided)",
        )
        system_blocks = [CachedBlock.make(BLOCK_ROLE, cache=True)]

        response = self._client.call(system_blocks, user_message)
        data = response.parse_json()

        contract_id = str(uuid.uuid4())
        schema_hints = [
            SchemaHint(
                field=h.get("field", ""),
                type=h.get("type", "TEXT"),
                required=bool(h.get("required", False)),
                description=h.get("description", ""),
            )
            for h in data.get("schema_hints", [])
        ]

        business_decision = data.get("business_decision_enabled", answers.answer_business_decision)
        linguistic_report = self._validator.validate(business_decision)

        contract_yaml = self._render_yaml(
            contract_id=contract_id,
            data=data,
            answers=answers,
            schema_hints=schema_hints,
            business_decision=business_decision,
        )

        contract_json: dict = {
            "apiVersion": "v3.0.0",
            "kind": "DataContract",
            "id": contract_id,
            "status": "draft",
            "version": "1.0.0",
            "name": answers.asset_name,
            "description": business_decision,
            "owner": answers.owner,
            "domain": data.get("soi_category", ""),
            "schema": [
                {
                    "name": answers.asset_name,
                    "fields": [
                        {
                            "name": h.field,
                            "type": h.type,
                            "required": h.required,
                            "description": h.description,
                        }
                        for h in schema_hints
                    ],
                }
            ],
            "quality": [
                {
                    "type": "completeness",
                    "fields": data.get("mandatory_fields", []),
                    "threshold": data.get("quality_completeness_threshold", 0.95),
                },
                {
                    "type": "freshness",
                    "maxAge": data.get("freshness_max_age", "P1D"),
                },
            ],
            "sla": {
                "updateFrequency": data.get("update_frequency_iso8601", "P1D"),
                "retention": data.get("retention_period", "P7Y"),
                "availability": data.get("availability_sla_pct", 99.9),
                "supportContact": answers.support_contact,
            },
            "tags": {
                "soi_category": data.get("soi_category", ""),
                "generated_by": "metadata-architect-interview-bot",
            },
        }

        log.info(
            "interview_bot.contract_generated",
            extra={
                "asset": answers.asset_name,
                "soi_category": data.get("soi_category"),
                "confidence": data.get("confidence"),
                "ready_for_gate": data.get("confidence", 0) >= 0.75,
            },
        )

        return DataContractDraft(
            contract_id=contract_id,
            asset_name=answers.asset_name,
            soi_category=data.get("soi_category", ""),
            business_decision=business_decision,
            mandatory_fields=data.get("mandatory_fields", []),
            update_frequency=data.get("update_frequency_iso8601", "P1D"),
            freshness_max_age=data.get("freshness_max_age", "P1D"),
            retention_period=data.get("retention_period", "P7Y"),
            availability_sla=float(data.get("availability_sla_pct", 99.9)),
            quality_completeness=float(data.get("quality_completeness_threshold", 0.95)),
            schema_hints=schema_hints,
            confidence=float(data.get("confidence", 0.5)),
            clarification_needed=data.get("clarification_needed", []),
            contract_yaml=contract_yaml,
            contract_json=contract_json,
            linguistic_compliant=linguistic_report.is_compliant,
            model_used=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cache_hit=response.cache_hit,
        )

    # ---------------------------------------------------------------------------
    # Private helpers
    # ---------------------------------------------------------------------------

    def _render_yaml(
        self,
        contract_id: str,
        data: dict,
        answers: InterviewAnswers,
        schema_hints: list[SchemaHint],
        business_decision: str,
    ) -> str:
        """Build ODCS YAML programmatically to prevent injection via user/LLM strings."""
        import io
        from ruamel.yaml.comments import CommentedMap, CommentedSeq

        doc = CommentedMap()
        doc["apiVersion"] = "v3.0.0"
        doc["kind"] = "DataContract"
        doc["id"] = contract_id
        doc["status"] = "draft"
        doc["version"] = "1.0.0"
        doc["name"] = answers.asset_name
        doc["description"] = business_decision
        doc["owner"] = answers.owner or "unknown"
        doc["domain"] = data.get("soi_category", "")

        # schema
        schema_entry = CommentedMap()
        schema_entry["name"] = answers.asset_name
        fields_seq = CommentedSeq()
        for h in schema_hints:
            f = CommentedMap()
            f["name"] = h.field
            f["type"] = h.type
            f["required"] = h.required
            f["description"] = h.description
            fields_seq.append(f)
        schema_entry["fields"] = fields_seq
        doc["schema"] = [schema_entry]

        # quality
        completeness = CommentedMap()
        completeness["type"] = "completeness"
        completeness["fields"] = data.get("mandatory_fields", [])
        completeness["threshold"] = float(data.get("quality_completeness_threshold", 0.95))
        freshness = CommentedMap()
        freshness["type"] = "freshness"
        freshness["maxAge"] = str(data.get("freshness_max_age", "P1D"))
        doc["quality"] = [completeness, freshness]

        # sla
        sla = CommentedMap()
        sla["updateFrequency"] = str(data.get("update_frequency_iso8601", "P1D"))
        sla["retention"] = str(data.get("retention_period", "P7Y"))
        sla["availability"] = float(data.get("availability_sla_pct", 99.9))
        sla["supportContact"] = answers.support_contact or ""
        doc["sla"] = sla

        # tags
        doc["tags"] = [
            {"soi_category": data.get("soi_category", "")},
            {"generated_by": "metadata-architect-interview-bot"},
            {"contract_version": "1.0.0"},
        ]

        buf = io.StringIO()
        yaml = _YAML()
        yaml.default_flow_style = False
        yaml.dump(doc, buf)
        rendered = buf.getvalue()

        # Validate — any remaining parse failure is a hard error, not a silent warning
        try:
            _YAML().load(io.StringIO(rendered))
        except Exception as exc:
            raise ValueError(f"ODCS YAML generation produced invalid output: {exc}") from exc

        return rendered
