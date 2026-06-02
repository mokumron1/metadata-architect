"""
Unit tests for the CI/CD Gate endpoints.

Both gates are tested against the in-memory SQLite DB via the
integration conftest (engine + async_client) to keep the test
fixtures consistent with the rest of the suite.

Gate-1 (Context-First) tests exercise the full DB query path.
Gate-2 (Jargon-Scrub) mocks the JargonScrubber to avoid live
Claude calls — it tests the endpoint contract, not the LLM.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from metadata_architect.config import get_settings
from metadata_architect.models.asset_registry import WorkflowStatus

from tests.integration.conftest import make_asset, make_draft, make_workflow

_GATE_KEY = get_settings().gate_api_key
_HEADERS = {"x-gate-api-key": _GATE_KEY}


# ---------------------------------------------------------------------------
# Gate 1 — Context-First
# ---------------------------------------------------------------------------

class TestContextFirstGate:
    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, db_session, async_client):
        self.client = async_client
        self.db = db_session

    async def test_approved_asset_passes(self):
        asset = await make_asset(self.db, name=f"finance.gate_approved_{uuid.uuid4().hex[:6]}")
        draft = await make_draft(self.db, asset.id)
        await make_workflow(
            self.db, asset.id, draft.id,
            status=WorkflowStatus.SME_APPROVED,
        )
        await self.db.commit()

        resp = await self.client.post(
            "/gates/context-first",
            json={"asset_name": asset.asset_name},
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is True
        assert data["status"] == "APPROVED"

    async def test_unregistered_asset_fails(self):
        resp = await self.client.post(
            "/gates/context-first",
            json={"asset_name": "nonexistent.table_xyz"},
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is False
        assert data["status"] == "NOT_REGISTERED"

    async def test_awaiting_review_fails(self):
        asset = await make_asset(self.db, name=f"finance.pending_{uuid.uuid4().hex[:6]}")
        draft = await make_draft(self.db, asset.id)
        await make_workflow(
            self.db, asset.id, draft.id,
            status=WorkflowStatus.AWAITING_SME_AUDIT,
        )
        await self.db.commit()

        resp = await self.client.post(
            "/gates/context-first",
            json={"asset_name": asset.asset_name},
            headers=_HEADERS,
        )
        data = resp.json()
        assert data["passed"] is False
        assert data["status"] == "PENDING_REVIEW"

    async def test_rejected_asset_fails(self):
        asset = await make_asset(self.db, name=f"finance.rejected_{uuid.uuid4().hex[:6]}")
        draft = await make_draft(self.db, asset.id)
        await make_workflow(
            self.db, asset.id, draft.id,
            status=WorkflowStatus.SME_REJECTED,
        )
        await self.db.commit()

        resp = await self.client.post(
            "/gates/context-first",
            json={"asset_name": asset.asset_name},
            headers=_HEADERS,
        )
        data = resp.json()
        assert data["passed"] is False
        assert data["status"] == "REJECTED"

    async def test_orphaned_asset_fails(self):
        asset = await make_asset(self.db, name=f"finance.orphaned_{uuid.uuid4().hex[:6]}")
        draft = await make_draft(self.db, asset.id)
        await make_workflow(
            self.db, asset.id, draft.id,
            status=WorkflowStatus.ORPHANED,
            sla_hours_offset=-2.0,
        )
        await self.db.commit()

        resp = await self.client.post(
            "/gates/context-first",
            json={"asset_name": asset.asset_name},
            headers=_HEADERS,
        )
        data = resp.json()
        assert data["passed"] is False
        assert data["status"] == "ORPHANED"

    async def test_approved_asset_returns_tdk_score(self):
        from metadata_architect.models.asset_registry import TdkScoreLog, TdkScoreEvent
        asset = await make_asset(self.db, name=f"finance.scored_{uuid.uuid4().hex[:6]}")
        draft = await make_draft(self.db, asset.id)
        await make_workflow(self.db, asset.id, draft.id, status=WorkflowStatus.SME_APPROVED)
        self.db.add(TdkScoreLog(
            asset_id=asset.id,
            clarity_score=0.8,
            ownership_score=0.8,
            composite_score=0.8,
            event_type=TdkScoreEvent.SME_APPROVED,
        ))
        await self.db.commit()

        resp = await self.client.post(
            "/gates/context-first",
            json={"asset_name": asset.asset_name},
            headers=_HEADERS,
        )
        data = resp.json()
        assert data["tdk_score"] == pytest.approx(0.8, abs=0.01)

    async def test_missing_api_key_returns_401(self):
        resp = await self.client.post(
            "/gates/context-first",
            json={"asset_name": "any.table"},
        )
        assert resp.status_code == 401

    async def test_wrong_api_key_returns_401(self):
        resp = await self.client.post(
            "/gates/context-first",
            json={"asset_name": "any.table"},
            headers={"x-gate-api-key": "totally-wrong"},
        )
        assert resp.status_code == 401

    async def test_response_contains_message(self):
        resp = await self.client.post(
            "/gates/context-first",
            json={"asset_name": "no.such.asset"},
            headers=_HEADERS,
        )
        assert "message" in resp.json()


# ---------------------------------------------------------------------------
# Gate 2 — Jargon Scrubber
# ---------------------------------------------------------------------------

def _mock_scrub_result(violations=None, is_compliant=True):
    from metadata_architect.agents.jargon_scrubber import JargonScrubResult, JargonViolation
    result = JargonScrubResult(
        violations=violations or [],
        sentence_count=2,
        longest_sentence_words=14,
        is_compliant=is_compliant,
        model_used="claude-sonnet-4-6",
        input_tokens=80,
        output_tokens=40,
        cache_hit=True,
    )
    return result


class TestJargonScrubGate:
    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, async_client):
        self.client = async_client

    @patch("metadata_architect.agents.jargon_scrubber.JargonScrubber")
    async def test_compliant_soi_passes(self, MockScrubber):
        MockScrubber.return_value.scrub.return_value = _mock_scrub_result()
        resp = await self.client.post(
            "/gates/jargon-scrub",
            json={"soi_text": "This table stores daily revenue totals grouped by region for audit reporting."},
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is True
        assert data["is_compliant"] is True
        assert data["violation_count"] == 0

    @patch("metadata_architect.agents.jargon_scrubber.JargonScrubber")
    async def test_violation_fails_when_fail_on_violation_true(self, MockScrubber):
        from metadata_architect.agents.jargon_scrubber import JargonViolation
        violations = [
            JargonViolation(
                term="KPI",
                char_position=12,
                rule_violated="UNDEFINED_ACRONYM",
                suggestion="Key Performance Indicator (KPI)",
            )
        ]
        MockScrubber.return_value.scrub.return_value = _mock_scrub_result(
            violations=violations, is_compliant=False
        )
        resp = await self.client.post(
            "/gates/jargon-scrub",
            json={
                "soi_text": "This table tracks KPI scores for the finance team each quarter.",
                "fail_on_violation": True,
            },
            headers=_HEADERS,
        )
        data = resp.json()
        assert data["passed"] is False
        assert data["violation_count"] == 1
        assert data["violations"][0]["rule_violated"] == "UNDEFINED_ACRONYM"

    @patch("metadata_architect.agents.jargon_scrubber.JargonScrubber")
    async def test_violation_passes_when_fail_on_violation_false(self, MockScrubber):
        from metadata_architect.agents.jargon_scrubber import JargonViolation
        violations = [
            JargonViolation(term="ETL", char_position=5, rule_violated="UNDEFINED_ACRONYM", suggestion="Extract, Transform, Load (ETL)")
        ]
        MockScrubber.return_value.scrub.return_value = _mock_scrub_result(
            violations=violations, is_compliant=False
        )
        resp = await self.client.post(
            "/gates/jargon-scrub",
            json={
                "soi_text": "The ETL pipeline loads daily revenue data into the warehouse for reporting.",
                "fail_on_violation": False,
            },
            headers=_HEADERS,
        )
        data = resp.json()
        assert data["passed"] is True   # warning mode — violations surface but don't block
        assert data["is_compliant"] is False
        assert data["violation_count"] == 1

    @patch("metadata_architect.agents.jargon_scrubber.JargonScrubber")
    async def test_response_includes_all_fields(self, MockScrubber):
        MockScrubber.return_value.scrub.return_value = _mock_scrub_result()
        resp = await self.client.post(
            "/gates/jargon-scrub",
            json={"soi_text": "This table stores daily revenue totals grouped by region for audit reporting."},
            headers=_HEADERS,
        )
        data = resp.json()
        for field in ("passed", "is_compliant", "violation_count", "violations",
                      "sentence_count", "longest_sentence_words", "model_used", "message"):
            assert field in data, f"Missing field: {field}"

    @patch("metadata_architect.agents.jargon_scrubber.JargonScrubber")
    async def test_glossary_forwarded_to_scrubber(self, MockScrubber):
        MockScrubber.return_value.scrub.return_value = _mock_scrub_result()
        glossary = {"KPI": "Key Performance Indicator"}
        await self.client.post(
            "/gates/jargon-scrub",
            json={
                "soi_text": "This table tracks KPI scores for the finance team each quarter.",
                "glossary": glossary,
            },
            headers=_HEADERS,
        )
        MockScrubber.assert_called_once_with(glossary=glossary)

    async def test_too_short_soi_returns_422(self):
        resp = await self.client.post(
            "/gates/jargon-scrub",
            json={"soi_text": "Too short."},
            headers=_HEADERS,
        )
        assert resp.status_code == 422

    async def test_missing_api_key_returns_401(self):
        resp = await self.client.post(
            "/gates/jargon-scrub",
            json={"soi_text": "This table stores daily revenue totals grouped by region for reporting."},
        )
        assert resp.status_code == 401
