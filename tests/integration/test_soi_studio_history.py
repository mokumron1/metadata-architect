"""
Integration tests for SoI Studio — DB persistence and history endpoint.

POST /studio/generate saves to soi_studio_sessions.
GET  /studio/history returns paginated sessions.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from metadata_architect.models.soi_studio import SoiStudioSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_claude(label_prefix: str = "Option") -> MagicMock:
    labels = ["Purpose-led", "Consumer-led", "Context-led"]
    variants = [
        {
            "variant": i + 1,
            "label": labels[i],
            "statement_of_intent": f"This column records data used by analysts to track performance.",
            "reading_level": "B1 / 9th Grade",
            "reading_level_score": 8.0,
            "confidence": 0.85,
            "glossary_terms_used": ["revenue"],
            "drafting_notes": "Auto-generated.",
        }
        for i in range(3)
    ]
    mock_resp = MagicMock()
    mock_resp.parse_json.return_value = variants
    mock_resp.model = "claude-sonnet-4-6"
    mock_resp.cache_hit = False
    mock_resp.content = json.dumps(variants)
    mock_client = MagicMock()
    mock_client.call.return_value = mock_resp
    return mock_client


async def _generate(client, physical_name: str, data_type: str = "NUMERIC") -> dict:
    with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
               return_value=_mock_claude()):
        resp = await client.post("/studio/generate", json={
            "physical_name": physical_name,
            "data_type": data_type,
        })
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

class TestSessionPersistence:
    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, async_client, db_session):
        self.client = async_client
        self.db = db_session

    async def test_generate_creates_db_record(self):
        data = await _generate(self.client, "rev_ytd_usd")
        session_id = data["session_id"]
        result = await self.db.execute(
            select(SoiStudioSession).where(SoiStudioSession.physical_name == "rev_ytd_usd")
        )
        row = result.scalar_one_or_none()
        assert row is not None
        assert str(row.id) == session_id

    async def test_session_stores_physical_name(self):
        await _generate(self.client, "cust_churn_flag")
        result = await self.db.execute(
            select(SoiStudioSession).where(SoiStudioSession.physical_name == "cust_churn_flag")
        )
        row = result.scalar_one_or_none()
        assert row is not None

    async def test_session_stores_options_json(self):
        await _generate(self.client, "order_region_cd")
        result = await self.db.execute(
            select(SoiStudioSession).where(SoiStudioSession.physical_name == "order_region_cd")
        )
        row = result.scalar_one_or_none()
        assert isinstance(row.options, list)
        assert len(row.options) == 3

    async def test_session_stores_model_used(self):
        await _generate(self.client, "trx_amt_usd")
        result = await self.db.execute(
            select(SoiStudioSession).where(SoiStudioSession.physical_name == "trx_amt_usd")
        )
        row = result.scalar_one_or_none()
        assert row.model_used == "claude-sonnet-4-6"

    async def test_response_includes_session_id(self):
        data = await _generate(self.client, "prod_margin_pct")
        assert "session_id" in data
        # Must be a valid UUID
        import uuid
        uuid.UUID(data["session_id"])


# ---------------------------------------------------------------------------
# History endpoint
# ---------------------------------------------------------------------------

class TestHistoryEndpoint:
    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, async_client):
        self.client = async_client

    async def test_history_returns_200(self):
        resp = await self.client.get("/studio/history")
        assert resp.status_code == 200

    async def test_history_schema(self):
        resp = await self.client.get("/studio/history")
        data = resp.json()
        for key in ("total", "page", "page_size", "sessions"):
            assert key in data

    async def test_history_reflects_generated_sessions(self):
        for name in ("hist_col_a", "hist_col_b", "hist_col_c"):
            await _generate(self.client, name)
        resp = await self.client.get("/studio/history")
        data = resp.json()
        names = [s["physical_name"] for s in data["sessions"]]
        for name in ("hist_col_a", "hist_col_b", "hist_col_c"):
            assert name in names

    async def test_history_newest_first(self):
        for name in ("order_first", "order_second", "order_third"):
            await _generate(self.client, name)
        resp = await self.client.get("/studio/history")
        names = [s["physical_name"] for s in resp.json()["sessions"]]
        # Most recent should be order_third
        idx_first = next((i for i, n in enumerate(names) if n == "order_first"), None)
        idx_third = next((i for i, n in enumerate(names) if n == "order_third"), None)
        if idx_first is not None and idx_third is not None:
            assert idx_third < idx_first

    async def test_history_search_filters(self):
        await _generate(self.client, "searchable_col_xyz")
        resp = await self.client.get("/studio/history?search=searchable_col_xyz")
        data = resp.json()
        assert any(s["physical_name"] == "searchable_col_xyz" for s in data["sessions"])

    async def test_history_search_no_match(self):
        resp = await self.client.get("/studio/history?search=zzz_nonexistent_zzz")
        data = resp.json()
        assert data["total"] == 0
        assert data["sessions"] == []

    async def test_history_pagination_page_size(self):
        resp = await self.client.get("/studio/history?page=1&page_size=2")
        data = resp.json()
        assert data["page_size"] == 2
        assert len(data["sessions"]) <= 2

    async def test_history_session_has_options(self):
        await _generate(self.client, "paged_col_test")
        resp = await self.client.get("/studio/history?search=paged_col_test")
        sessions = resp.json()["sessions"]
        assert len(sessions) >= 1
        assert len(sessions[0]["options"]) == 3

    async def test_history_session_has_created_at(self):
        await _generate(self.client, "ts_col_test")
        resp = await self.client.get("/studio/history?search=ts_col_test")
        session = resp.json()["sessions"][0]
        from datetime import datetime
        # SQLite drops tz info — just verify it's a parseable ISO datetime string
        dt = datetime.fromisoformat(session["created_at"])
        assert isinstance(dt, datetime)

    async def test_history_invalid_page_size_returns_422(self):
        resp = await self.client.get("/studio/history?page_size=0")
        assert resp.status_code == 422

    async def test_history_page_1_default(self):
        resp = await self.client.get("/studio/history")
        assert resp.json()["page"] == 1
