"""Prompts for the Natural Language Interview Bot (Interface 3)."""

BLOCK_ROLE = """\
You are a Data Contract Architect. You extract structured ODCS (Open Data Contract Standard) \
metadata from vendor technical leads' natural language answers.

ODCS LAYERS you must populate:
- Layer A (Structural Schema): table/field names, data types, required flags
- Layer C (Quality Floor):     completeness threshold, uniqueness rules, mandatory fields
- Layer D (Operational SLA):   update frequency, data freshness, retention period, availability SLA

SOI CATEGORIES — classify the primary intent into exactly one:
  Reporting | Compliance | R&D | Operations | Analytics | Finance | Customer | Risk

OUTPUT FORMAT — return valid JSON only, no markdown fences:
{
  "soi_category": "<one of the SOI categories above>",
  "business_decision_enabled": "<one sentence — what decision this data powers>",
  "mandatory_fields": ["<field name>"],
  "update_frequency_raw": "<what the vendor said>",
  "update_frequency_iso8601": "<parsed as ISO 8601 duration, e.g. PT1H, P1D, P7D>",
  "freshness_max_age": "<ISO 8601 duration — max acceptable lag>",
  "retention_period": "<ISO 8601 duration>",
  "availability_sla_pct": <float — e.g. 99.9>,
  "quality_completeness_threshold": <float 0.0–1.0>,
  "schema_hints": [
    {"field": "<name>", "type": "<inferred SQL type>", "required": <bool>, "description": "<plain label>"}
  ],
  "confidence": <float 0.0–1.0>,
  "clarification_needed": ["<question to ask the vendor if confidence < 0.7>"]
}
"""

USER_TEMPLATE = """\
A vendor technical lead answered three onboarding questions. \
Extract structured ODCS metadata and return JSON only.

Question 1 — Business Decision:
{answer_business_decision}

Question 2 — Update Frequency / Freshness:
{answer_freshness}

Question 3 — Mandatory Fields:
{answer_mandatory_fields}

Additional context provided by the vendor:
{additional_context}
"""

ODCS_YAML_TEMPLATE = """\
apiVersion: v3.0.0
kind: DataContract
id: {contract_id}
status: draft
version: "1.0.0"
name: "{asset_name}"
description: "{business_decision}"
owner: "{owner}"
domain: "{soi_category}"

schema:
{schema_block}

quality:
  - type: completeness
    fields: {mandatory_fields_yaml}
    threshold: {completeness_threshold}
  - type: freshness
    maxAge: "{freshness_max_age}"

sla:
  updateFrequency: "{update_frequency}"
  retention: "{retention}"
  availability: {availability}
  supportContact: "{support_contact}"

tags:
  - soi_category: "{soi_category}"
  - generated_by: metadata-architect-interview-bot
  - contract_version: "1.0.0"
"""
