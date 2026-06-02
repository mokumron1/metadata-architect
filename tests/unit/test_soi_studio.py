"""
Unit tests for the SoI Studio router.

POST /studio/generate   — Claude mocked, validates response shape and scoring
GET  /studio            — HTML UI served
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_claude_response(variants: list[dict]) -> MagicMock:
    """Build a fake ClaudeClient whose .call() returns a mock response."""
    mock_resp = MagicMock()
    mock_resp.parse_json.return_value = variants
    mock_resp.model = "claude-sonnet-4-6"
    mock_resp.cache_hit = False
    mock_resp.content = json.dumps(variants)

    mock_client = MagicMock()
    mock_client.call.return_value = mock_resp
    return mock_client


def _three_variants(
    statement: str = "This table stores test financial data used by analysts.",
    rl_score: float = 8.5,
    confidence: float = 0.88,
) -> list[dict]:
    labels = ["Purpose-led", "Consumer-led", "Context-led"]
    return [
        {
            "variant": i + 1,
            "label": labels[i],
            "statement_of_intent": statement,
            "reading_level": "B1 / 9th Grade",
            "reading_level_score": rl_score,
            "confidence": confidence,
            "glossary_terms_used": ["revenue"],
            "drafting_notes": f"Variant {i + 1} notes.",
        }
        for i in range(3)
    ]


# ---------------------------------------------------------------------------
# GET /studio — UI
# ---------------------------------------------------------------------------

class TestStudioUI:
    @pytest.mark.asyncio
    async def test_get_studio_returns_200(self, async_client):
        resp = await async_client.get("/studio")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_studio_returns_html(self, async_client):
        resp = await async_client.get("/studio")
        assert "text/html" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_get_studio_contains_key_elements(self, async_client):
        resp = await async_client.get("/studio")
        html = resp.text
        assert "SoI Studio" in html
        assert "Generate 3 Descriptions" in html
        assert "studio/generate" in html


# ---------------------------------------------------------------------------
# POST /studio/generate — happy path
# ---------------------------------------------------------------------------

class TestGenerateEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200(self, async_client):
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=_mock_claude_response(_three_variants())):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "cust_rev_ytd_usd",
                "data_type": "NUMERIC(18,4)",
                "business_hint": "Year-to-date revenue per customer in USD.",
            })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_three_options(self, async_client):
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=_mock_claude_response(_three_variants())):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "cust_rev_ytd_usd",
                "data_type": "NUMERIC(18,4)",
            })
        data = resp.json()
        assert len(data["options"]) == 3

    @pytest.mark.asyncio
    async def test_option_fields_present(self, async_client):
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=_mock_claude_response(_three_variants())):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "trx_amt",
                "data_type": "NUMERIC(18,4)",
            })
        opt = resp.json()["options"][0]
        for field in ("index", "label", "statement", "word_count", "reading_level",
                      "tdk_clarity", "jargon_compliant", "violations", "confidence",
                      "drafting_notes"):
            assert field in opt, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_option_indexes_are_1_2_3(self, async_client):
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=_mock_claude_response(_three_variants())):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "trx_amt",
                "data_type": "INTEGER",
            })
        indexes = [o["index"] for o in resp.json()["options"]]
        assert indexes == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_labels_match_expected(self, async_client):
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=_mock_claude_response(_three_variants())):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "trx_amt",
                "data_type": "INTEGER",
            })
        labels = [o["label"] for o in resp.json()["options"]]
        assert labels == ["Purpose-led", "Consumer-led", "Context-led"]

    @pytest.mark.asyncio
    async def test_model_used_in_response(self, async_client):
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=_mock_claude_response(_three_variants())):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "trx_amt",
                "data_type": "INTEGER",
            })
        assert resp.json()["model_used"] == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_physical_name_echoed(self, async_client):
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=_mock_claude_response(_three_variants())):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "order_region_cd",
                "data_type": "VARCHAR(64)",
            })
        assert resp.json()["physical_name"] == "order_region_cd"

    @pytest.mark.asyncio
    async def test_tdk_clarity_between_0_and_1(self, async_client):
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=_mock_claude_response(_three_variants())):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "revenue_usd",
                "data_type": "NUMERIC(18,4)",
            })
        for opt in resp.json()["options"]:
            assert 0.0 <= opt["tdk_clarity"] <= 1.0

    @pytest.mark.asyncio
    async def test_confidence_between_0_and_1(self, async_client):
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=_mock_claude_response(_three_variants(confidence=0.92))):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "revenue_usd",
                "data_type": "NUMERIC(18,4)",
            })
        for opt in resp.json()["options"]:
            assert 0.0 <= opt["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# Jargon detection
# ---------------------------------------------------------------------------

class TestJargonCheck:
    @pytest.mark.asyncio
    async def test_clean_statement_is_compliant(self, async_client):
        variants = _three_variants(
            statement="This column records the customer revenue in US dollars for the year."
        )
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=_mock_claude_response(variants)):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "cust_rev",
                "data_type": "NUMERIC",
            })
        opt = resp.json()["options"][0]
        assert opt["jargon_compliant"] is True
        assert opt["violations"] == []

    @pytest.mark.asyncio
    async def test_statement_with_jargon_flagged(self, async_client):
        variants = _three_variants(
            statement="This ETL pipeline populates the OLAP DDL structure."
        )
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=_mock_claude_response(variants)):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "pipeline_col",
                "data_type": "VARCHAR",
            })
        opt = resp.json()["options"][0]
        assert opt["jargon_compliant"] is False
        assert len(opt["violations"]) > 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    @pytest.mark.asyncio
    async def test_missing_physical_name_returns_422(self, async_client):
        resp = await async_client.post("/studio/generate", json={
            "data_type": "INTEGER",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_data_type_returns_422(self, async_client):
        resp = await async_client.post("/studio/generate", json={
            "physical_name": "some_col",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_physical_name_returns_422(self, async_client):
        resp = await async_client.post("/studio/generate", json={
            "physical_name": "",
            "data_type": "INTEGER",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_business_hint_optional(self, async_client):
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=_mock_claude_response(_three_variants())):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "some_col",
                "data_type": "INTEGER",
            })
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_claude_error_returns_503(self, async_client):
        mock_client = MagicMock()
        mock_client.call.side_effect = RuntimeError("Claude unavailable")
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=mock_client):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "some_col",
                "data_type": "INTEGER",
            })
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_bad_json_from_claude_returns_502(self, async_client):
        mock_resp = MagicMock()
        mock_resp.parse_json.side_effect = ValueError("not json")
        mock_resp.content = "not a json array"
        mock_client = MagicMock()
        mock_client.call.return_value = mock_resp
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=mock_client):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "some_col",
                "data_type": "INTEGER",
            })
        assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_non_list_response_returns_502(self, async_client):
        mock_resp = MagicMock()
        mock_resp.parse_json.return_value = {"error": "not an array"}
        mock_resp.content = '{"error": "not an array"}'
        mock_client = MagicMock()
        mock_client.call.return_value = mock_resp
        with patch("metadata_architect.api.routers.soi_studio.ClaudeClient",
                   return_value=mock_client):
            resp = await async_client.post("/studio/generate", json={
                "physical_name": "some_col",
                "data_type": "INTEGER",
            })
        assert resp.status_code == 502
