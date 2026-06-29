"""
Unit tests for the Third-Party Onboarding Suite.

LLM calls are mocked so the suite runs offline. Tests cover:
  - LinguisticValidationService rule enforcement
  - MetadataDrafter draft logic and auto-approvable flag
  - SecurityTriageAgent regex fast-path and semantic path
  - InterviewBot contract generation and YAML validity
  - API endpoints (draft-metadata, triage-security, interview)
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from metadata_architect.onboarding.linguistic_service import LinguisticValidationService
from metadata_architect.onboarding.metadata_drafter import ColumnContext, MetadataDrafter
from metadata_architect.onboarding.security_triage import SecurityTriageAgent
from metadata_architect.onboarding.interview_bot import InterviewAnswers, InterviewBot


# ===========================================================================
# LinguisticValidationService
# ===========================================================================

class TestLinguisticValidationService:
    def setup_method(self):
        self.svc = LinguisticValidationService()

    def test_compliant_text_passes(self):
        text = "The system stores the daily revenue amount. Users query this field in reports."
        report = self.svc.validate(text)
        assert report.is_compliant
        assert report.violations == []

    def test_long_sentence_flagged(self):
        # 30-word sentence — exceeds max 25
        long = " ".join(["word"] * 30) + "."
        report = self.svc.validate(long)
        violations = [v for v in report.violations if v.rule == "long_sentence"]
        assert len(violations) >= 1

    def test_passive_voice_flagged(self):
        text = "The amount is stored by the database."
        report = self.svc.validate(text)
        violations = [v for v in report.violations if v.rule == "passive_voice"]
        assert len(violations) >= 1

    def test_non_b1_vocab_flagged(self):
        text = "The system will utilize the concatenated value."
        report = self.svc.validate(text)
        violations = [v for v in report.violations if v.rule == "non_b1_vocab"]
        assert len(violations) >= 2  # "utilize" and "concatenated"

    def test_clean_suggestion_substitutes(self):
        text = "The system will utilize this field."
        cleaned = self.svc.clean_suggestion(text)
        assert "utilize" not in cleaned.lower()
        assert "use" in cleaned.lower()

    def test_sentence_count(self):
        text = "First sentence. Second sentence. Third sentence."
        report = self.svc.validate(text)
        assert report.sentence_count == 3

    def test_longest_sentence_tracked(self):
        text = "Short. " + " ".join(["word"] * 20) + ". Also short."
        report = self.svc.validate(text)
        assert report.longest_sentence_words == 20


# ===========================================================================
# MetadataDrafter
# ===========================================================================

_DRAFT_RESPONSE = json.dumps({
    "business_definition": "The system stores the daily settlement amount for each account.",
    "plain_name": "Daily Settlement Amount",
    "usage_examples": ["Used in the nightly reconciliation report."],
    "warnings": [],
    "confidence": 0.88,
    "readability_grade": 7.5,
    "active_voice_violations": [],
    "long_sentence_violations": [],
})


class TestMetadataDrafter:
    def _make_drafter(self):
        drafter = MetadataDrafter.__new__(MetadataDrafter)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = _DRAFT_RESPONSE
        mock_response.model = "claude-sonnet-4-6"
        mock_response.input_tokens = 100
        mock_response.output_tokens = 80
        mock_response.cache_hit = False
        mock_response.parse_json.return_value = json.loads(_DRAFT_RESPONSE)
        mock_client.call.return_value = mock_response
        drafter._client = mock_client
        from metadata_architect.onboarding.linguistic_service import LinguisticValidationService
        drafter._validator = LinguisticValidationService()
        drafter._model = "claude-sonnet-4-6"
        return drafter

    def test_draft_returns_result(self):
        drafter = self._make_drafter()
        col = ColumnContext(
            column_name="AMT_D_01",
            data_type="DECIMAL(18,2)",
            sample_values=["1200.00", "500.00"],
            table_context_hint="daily transaction settlement table",
        )
        result = drafter.draft(col)
        assert result.column_name == "AMT_D_01"
        assert "settlement" in result.business_definition.lower()
        assert result.plain_name == "Daily Settlement Amount"

    def test_auto_approvable_when_high_confidence_compliant(self):
        drafter = self._make_drafter()
        col = ColumnContext(column_name="AMT_D_01", data_type="DECIMAL(18,2)")
        result = drafter.draft(col)
        assert result.confidence >= 0.80
        assert result.linguistic_report.is_compliant
        assert result.readability_grade <= 9.0
        assert result.is_auto_approvable

    def test_batch_returns_list(self):
        drafter = self._make_drafter()
        cols = [
            ColumnContext(column_name=f"COL_{i}", data_type="VARCHAR(64)")
            for i in range(3)
        ]
        results = drafter.draft_batch(cols)
        assert len(results) == 3


# ===========================================================================
# SecurityTriageAgent
# ===========================================================================

class TestSecurityTriageAgent:
    def test_ssn_triggers_critical_regex_path(self):
        agent = SecurityTriageAgent()
        text = "Customer SSN: 123-45-6789 was submitted on 2024-01-01."
        passport = agent.triage("test_asset", text)
        assert passport.classification.value == "Confidential"
        assert any(s.pattern_matched == "ssn" for s in passport.risk_signals)
        assert passport.model_used == "regex-only"

    def test_credit_card_triggers_restricted(self):
        agent = SecurityTriageAgent()
        # Visa test number (passes Luhn)
        text = "Payment card: 4111111111111111 processed."
        passport = agent.triage("payment_feed", text)
        assert passport.classification.value == "Restricted"
        assert passport.quarantine_recommended

    def test_clean_text_goes_to_semantic_path(self):
        agent = SecurityTriageAgent.__new__(SecurityTriageAgent)
        mock_client = MagicMock()
        mock_response = MagicMock()
        semantic_result = {
            "classification": "Internal",
            "confidence": 0.90,
            "risk_signals": [],
            "quarantine_recommended": False,
            "quarantine_reason": "",
            "remediation_steps": [],
            "regulatory_frameworks": [],
        }
        mock_response.parse_json.return_value = semantic_result
        mock_response.model = "claude-sonnet-4-6"
        mock_response.input_tokens = 200
        mock_response.output_tokens = 100
        mock_response.cache_hit = False
        mock_client.call.return_value = mock_response
        agent._client = mock_client
        agent._model = "claude-sonnet-4-6"

        passport = agent.triage("internal_report", "Revenue for Q3 was $5M.")
        assert passport.classification.value == "Internal"
        assert not passport.quarantine_recommended

    def test_passport_as_tag(self):
        agent = SecurityTriageAgent()
        text = "No PII here. Just aggregate counts."
        # mock the client for semantic path
        with patch.object(agent, "_client") as mock_client:
            mock_response = MagicMock()
            mock_response.parse_json.return_value = {
                "classification": "Public",
                "confidence": 0.95,
                "risk_signals": [],
                "quarantine_recommended": False,
                "quarantine_reason": "",
                "remediation_steps": [],
                "regulatory_frameworks": [],
            }
            mock_response.model = "claude-sonnet-4-6"
            mock_response.input_tokens = 50
            mock_response.output_tokens = 30
            mock_response.cache_hit = False
            mock_client.call.return_value = mock_response
            passport = agent.triage("public_agg", text)

        tag = passport.as_tag()
        assert "security_classification" in tag
        assert "payload_fingerprint" in tag

    def test_payload_fingerprint_is_sha256(self):
        agent = SecurityTriageAgent()
        text = "123-45-6789"
        passport = agent.triage("fp_test", text)
        assert len(passport.payload_fingerprint) == 64


# ===========================================================================
# InterviewBot
# ===========================================================================

_INTERVIEW_RESPONSE = json.dumps({
    "soi_category": "Reporting",
    "business_decision_enabled": "Finance leaders use this data to approve monthly budget variances.",
    "mandatory_fields": ["transaction_id", "amount", "account_id"],
    "update_frequency_raw": "every hour",
    "update_frequency_iso8601": "PT1H",
    "freshness_max_age": "PT2H",
    "retention_period": "P7Y",
    "availability_sla_pct": 99.9,
    "quality_completeness_threshold": 0.98,
    "schema_hints": [
        {"field": "transaction_id", "type": "VARCHAR(64)", "required": True, "description": "Unique transaction key"},
        {"field": "amount", "type": "DECIMAL(18,2)", "required": True, "description": "Settlement amount"},
        {"field": "account_id", "type": "VARCHAR(32)", "required": True, "description": "Account identifier"},
    ],
    "confidence": 0.91,
    "clarification_needed": [],
})


class TestInterviewBot:
    def _make_bot(self):
        bot = InterviewBot.__new__(InterviewBot)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = _INTERVIEW_RESPONSE
        mock_response.model = "claude-sonnet-4-6"
        mock_response.input_tokens = 300
        mock_response.output_tokens = 200
        mock_response.cache_hit = False
        mock_response.parse_json.return_value = json.loads(_INTERVIEW_RESPONSE)
        mock_client.call.return_value = mock_response
        bot._client = mock_client
        bot._model = "claude-sonnet-4-6"
        from metadata_architect.onboarding.linguistic_service import LinguisticValidationService
        bot._validator = LinguisticValidationService()
        return bot

    def test_generate_contract_returns_draft(self):
        bot = self._make_bot()
        answers = InterviewAnswers(
            asset_name="finance.daily_settlements",
            answer_business_decision="Finance leaders approve monthly budget variances.",
            answer_freshness="Updated every hour.",
            answer_mandatory_fields="transaction_id, amount, account_id",
            owner="finance-team@example.com",
        )
        draft = bot.generate_contract(answers)
        assert draft.soi_category == "Reporting"
        assert draft.update_frequency == "PT1H"
        assert "transaction_id" in draft.mandatory_fields
        assert draft.confidence >= 0.75

    def test_is_ready_for_gate_when_high_confidence(self):
        bot = self._make_bot()
        answers = InterviewAnswers(
            asset_name="finance.daily_settlements",
            answer_business_decision="Finance leaders approve monthly budget variances.",
            answer_freshness="Hourly.",
            answer_mandatory_fields="transaction_id, amount",
        )
        draft = bot.generate_contract(answers)
        assert draft.is_ready_for_gate

    def test_contract_yaml_is_valid(self):
        from ruamel.yaml import YAML
        import io
        bot = self._make_bot()
        answers = InterviewAnswers(
            asset_name="test.asset",
            answer_business_decision="Teams use this to track KPIs.",
            answer_freshness="Daily.",
            answer_mandatory_fields="id, value",
        )
        draft = bot.generate_contract(answers)
        parsed = YAML().load(io.StringIO(draft.contract_yaml))
        assert parsed["kind"] == "DataContract"
        assert parsed["id"] == draft.contract_id

    def test_contract_json_has_odcs_structure(self):
        bot = self._make_bot()
        answers = InterviewAnswers(
            asset_name="test.asset",
            answer_business_decision="Teams use this to track KPIs.",
            answer_freshness="Daily.",
            answer_mandatory_fields="id, value",
        )
        draft = bot.generate_contract(answers)
        cj = draft.contract_json
        assert cj["apiVersion"] == "v3.0.0"
        assert "schema" in cj
        assert "quality" in cj
        assert "sla" in cj

    def test_schema_hints_populated(self):
        bot = self._make_bot()
        answers = InterviewAnswers(
            asset_name="finance.settlements",
            answer_business_decision="Used for variance reporting.",
            answer_freshness="Hourly.",
            answer_mandatory_fields="transaction_id",
        )
        draft = bot.generate_contract(answers)
        assert len(draft.schema_hints) == 3
        assert draft.schema_hints[0].field == "transaction_id"


# ===========================================================================
# API endpoint smoke tests
# ===========================================================================

class TestOnboardingAPI:
    """Smoke tests against the FastAPI test client with mocked LLM calls."""

    @pytest.mark.asyncio
    async def test_draft_metadata_endpoint(self, async_client):
        mock_response = MagicMock()
        mock_response.parse_json.return_value = json.loads(_DRAFT_RESPONSE)
        mock_response.model = "claude-sonnet-4-6"
        mock_response.input_tokens = 100
        mock_response.output_tokens = 80
        mock_response.cache_hit = False

        with patch(
            "metadata_architect.onboarding.metadata_drafter.ClaudeClient.call",
            return_value=mock_response,
        ):
            resp = await async_client.post(
                "/onboarding/draft-metadata",
                json={
                    "column_name": "AMT_D_01",
                    "data_type": "DECIMAL(18,2)",
                    "sample_values": ["1200.00"],
                    "table_context_hint": "settlement table",
                    "asset_name": "finance.settlements",
                },
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["column_name"] == "AMT_D_01"
        assert body["record_id"] is not None

    @pytest.mark.asyncio
    async def test_triage_security_ssn_endpoint(self, async_client):
        resp = await async_client.post(
            "/onboarding/triage-security",
            json={
                "asset_name": "vendor.customer_feed",
                "payload_sample": "Customer SSN: 123-45-6789, name: John Smith",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["classification"] == "Confidential"
        assert body["record_id"] is not None

    @pytest.mark.asyncio
    async def test_interview_endpoint(self, async_client):
        mock_response = MagicMock()
        mock_response.parse_json.return_value = json.loads(_INTERVIEW_RESPONSE)
        mock_response.model = "claude-sonnet-4-6"
        mock_response.input_tokens = 300
        mock_response.output_tokens = 200
        mock_response.cache_hit = False

        with patch(
            "metadata_architect.onboarding.interview_bot.ClaudeClient.call",
            return_value=mock_response,
        ):
            resp = await async_client.post(
                "/onboarding/interview",
                json={
                    "asset_name": "finance.daily_settlements",
                    "answer_business_decision": "Finance leaders approve variances.",
                    "answer_freshness": "Every hour.",
                    "answer_mandatory_fields": "transaction_id, amount, account_id",
                    "owner": "finance@example.com",
                },
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["soi_category"] == "Reporting"
        assert body["contract_id"] is not None
        assert body["is_ready_for_gate"] is True

    @pytest.mark.asyncio
    async def test_contract_activation_endpoint(self, async_client):
        mock_response = MagicMock()
        mock_response.parse_json.return_value = json.loads(_INTERVIEW_RESPONSE)
        mock_response.model = "claude-sonnet-4-6"
        mock_response.input_tokens = 300
        mock_response.output_tokens = 200
        mock_response.cache_hit = False

        with patch(
            "metadata_architect.onboarding.interview_bot.ClaudeClient.call",
            return_value=mock_response,
        ):
            create_resp = await async_client.post(
                "/onboarding/interview",
                json={
                    "asset_name": "finance.daily_settlements_v2",
                    "answer_business_decision": "Used for quarterly reporting.",
                    "answer_freshness": "Daily.",
                    "answer_mandatory_fields": "id, amount",
                },
            )
        record_id = create_resp.json()["record_id"]

        activate_resp = await async_client.patch(
            f"/onboarding/contracts/{record_id}/activate",
            json={"record_id": record_id, "action": "activate"},
        )
        assert activate_resp.status_code == 200
        assert activate_resp.json()["status"] == "active"
        assert activate_resp.json()["gate_unblocked"] is True

    @pytest.mark.asyncio
    async def test_column_approval_endpoint(self, async_client):
        mock_response = MagicMock()
        mock_response.parse_json.return_value = json.loads(_DRAFT_RESPONSE)
        mock_response.model = "claude-sonnet-4-6"
        mock_response.input_tokens = 100
        mock_response.output_tokens = 80
        mock_response.cache_hit = False

        with patch(
            "metadata_architect.onboarding.metadata_drafter.ClaudeClient.call",
            return_value=mock_response,
        ):
            create_resp = await async_client.post(
                "/onboarding/draft-metadata",
                json={
                    "column_name": "REV_AMT",
                    "data_type": "DECIMAL(18,2)",
                    "asset_name": "finance.revenue",
                },
            )
        record_id = create_resp.json()["record_id"]

        approve_resp = await async_client.patch(
            f"/onboarding/draft-metadata/{record_id}/review",
            json={"record_id": record_id, "action": "approved"},
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["sme_status"] == "approved"
        assert approve_resp.json()["written_to_glossary"] is True


# ===========================================================================
# Audit log tests
# ===========================================================================

class TestAuditLog:
    """Verify that audit events are written for every interface."""

    @pytest.mark.asyncio
    async def test_audit_events_written_on_draft(self, async_client):
        """Metadata Drafter writes multiple audit events; /audit/{req_id} returns them."""
        import json
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.parse_json.return_value = json.loads(_DRAFT_RESPONSE)
        mock_response.model = "claude-sonnet-4-6"
        mock_response.input_tokens = 100
        mock_response.output_tokens = 80
        mock_response.cache_hit = False

        req_id = str(__import__("uuid").uuid4())
        with patch(
            "metadata_architect.onboarding.metadata_drafter.ClaudeClient.call",
            return_value=mock_response,
        ):
            resp = await async_client.post(
                "/onboarding/draft-metadata",
                json={
                    "column_name": "AUDIT_TEST_COL",
                    "data_type": "VARCHAR(255)",
                    "asset_name": "audit.test_asset",
                },
                headers={"X-Request-ID": req_id},
            )
        assert resp.status_code == 201

        audit_resp = await async_client.get(f"/audit/{req_id}")
        assert audit_resp.status_code == 200
        data = audit_resp.json()
        assert data["request_id"] == req_id
        assert data["event_count"] >= 4  # received, llm_started, llm_done, persisted
        codes = [e["event_code"] for e in data["entries"]]
        assert "MD_REQUEST_RECEIVED" in codes
        assert "MD_DRAFT_PERSISTED" in codes

    @pytest.mark.asyncio
    async def test_audit_events_written_on_triage(self, async_client):
        """Security Triage writes audit events including regex scan and classification."""
        req_id = str(__import__("uuid").uuid4())
        resp = await async_client.post(
            "/onboarding/triage-security",
            json={
                "asset_name": "audit.triage_asset",
                "payload_sample": "SSN: 123-45-6789",
            },
            headers={"X-Request-ID": req_id},
        )
        assert resp.status_code == 201

        audit_resp = await async_client.get(f"/audit/{req_id}")
        assert audit_resp.status_code == 200
        data = audit_resp.json()
        codes = [e["event_code"] for e in data["entries"]]
        assert "ST_REQUEST_RECEIVED" in codes
        assert "ST_REGEX_SCAN_COMPLETED" in codes
        assert "ST_CLASSIFICATION_DECIDED" in codes
        assert "ST_PASSPORT_PERSISTED" in codes

    @pytest.mark.asyncio
    async def test_audit_query_filter_by_interface(self, async_client):
        """/audit/?interface=SECURITY_TRIAGE returns only triage events."""
        req_id = str(__import__("uuid").uuid4())
        await async_client.post(
            "/onboarding/triage-security",
            json={"asset_name": "audit.filter_test", "payload_sample": "SSN: 222-33-4444"},
            headers={"X-Request-ID": req_id},
        )

        query_resp = await async_client.get(
            "/audit/",
            params={"request_id": req_id, "interface": "SECURITY_TRIAGE"},
        )
        assert query_resp.status_code == 200
        data = query_resp.json()
        assert data["count"] > 0
        assert all(e["interface"] == "SECURITY_TRIAGE" for e in data["entries"])

    @pytest.mark.asyncio
    async def test_audit_sequence_is_monotonic(self, async_client):
        """Sequence numbers within a request increase monotonically."""
        req_id = str(__import__("uuid").uuid4())
        await async_client.post(
            "/onboarding/triage-security",
            json={"asset_name": "audit.seq_test", "payload_sample": "plain text no PII"},
            headers={"X-Request-ID": req_id},
        )

        audit_resp = await async_client.get(f"/audit/{req_id}")
        seqs = [e["sequence"] for e in audit_resp.json()["entries"]]
        assert seqs == sorted(seqs)
        assert seqs == list(range(1, len(seqs) + 1))
