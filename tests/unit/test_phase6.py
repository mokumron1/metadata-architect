"""
Unit tests for Phase 6 components.

- CatalogPushDispatcher: no-op when adapters unconfigured
- DataHubAdapter / CollibraAdapter: enabled only when env vars set
- edit analysis: _run_edit_analysis returns expected fields (Claude mocked)
"""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# CatalogPushDispatcher — no adapters configured
# ---------------------------------------------------------------------------

class TestCatalogPushDispatcherNoop:
    def _payload(self):
        from metadata_architect.catalog.push_adapter import CatalogPayload
        return CatalogPayload(
            asset_name="finance.test",
            asset_uuid=str(uuid.uuid4()),
            statement_of_intent="This table stores test data.",
            tdk_score=0.80,
            reading_level="B1 / 9th Grade",
            context_authority="sme@example.com",
            certified_at="2026-06-02T00:00:00+00:00",
            verification_status="SME_APPROVED",
        )

    @pytest.mark.asyncio
    async def test_dispatch_returns_empty_when_no_adapters_configured(self):
        from metadata_architect.catalog.push_adapter import CatalogPushDispatcher
        for k in ("DATAHUB_GMS_URL", "COLLIBRA_BASE_URL", "COLLIBRA_API_USER", "COLLIBRA_API_PASSWORD"):
            os.environ.pop(k, None)
        dispatcher = CatalogPushDispatcher()
        result = await dispatcher.dispatch(self._payload())
        assert result == {}

    def test_datahub_disabled_without_env_var(self):
        from metadata_architect.catalog.push_adapter import DataHubAdapter
        os.environ.pop("DATAHUB_GMS_URL", None)
        assert not DataHubAdapter().is_enabled()

    def test_collibra_disabled_without_env_vars(self):
        from metadata_architect.catalog.push_adapter import CollibraAdapter
        for k in ("COLLIBRA_BASE_URL", "COLLIBRA_API_USER", "COLLIBRA_API_PASSWORD"):
            os.environ.pop(k, None)
        assert not CollibraAdapter().is_enabled()

    def test_datahub_enabled_with_env_var(self):
        from metadata_architect.catalog.push_adapter import DataHubAdapter
        with patch.dict(os.environ, {"DATAHUB_GMS_URL": "http://datahub:8080"}):
            assert DataHubAdapter().is_enabled()

    def test_collibra_enabled_with_all_env_vars(self):
        from metadata_architect.catalog.push_adapter import CollibraAdapter
        with patch.dict(os.environ, {
            "COLLIBRA_BASE_URL": "https://tenant.collibra.com",
            "COLLIBRA_API_USER": "user@example.com",
            "COLLIBRA_API_PASSWORD": "secret",
        }):
            assert CollibraAdapter().is_enabled()


# ---------------------------------------------------------------------------
# DataHubAdapter push mechanics (httpx mocked)
# ---------------------------------------------------------------------------

class TestDataHubAdapterPush:
    def _payload(self):
        from metadata_architect.catalog.push_adapter import CatalogPayload
        return CatalogPayload(
            asset_name="finance.revenue",
            asset_uuid=str(uuid.uuid4()),
            statement_of_intent="Revenue table.",
            tdk_score=0.85,
            reading_level="B1 / 9th Grade",
            context_authority="sme@example.com",
            certified_at="2026-06-02T00:00:00+00:00",
            verification_status="SME_APPROVED",
        )

    @pytest.mark.asyncio
    async def test_push_returns_true_on_success(self):
        import httpx
        from metadata_architect.catalog.push_adapter import DataHubAdapter

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch.dict(os.environ, {"DATAHUB_GMS_URL": "http://datahub:8080"}):
            adapter = DataHubAdapter()
            with patch("httpx.AsyncClient") as MockClient:
                instance = MockClient.return_value.__aenter__.return_value
                instance.post = AsyncMock(return_value=mock_resp)
                result = await adapter.push(self._payload())

        assert result is True

    @pytest.mark.asyncio
    async def test_push_returns_false_on_network_error(self):
        import httpx
        from metadata_architect.catalog.push_adapter import DataHubAdapter

        with patch.dict(os.environ, {"DATAHUB_GMS_URL": "http://datahub:8080"}):
            adapter = DataHubAdapter()
            with patch("httpx.AsyncClient") as MockClient:
                instance = MockClient.return_value.__aenter__.return_value
                instance.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
                result = await adapter.push(self._payload())

        assert result is False


# ---------------------------------------------------------------------------
# analyse_sme_edit — _run_edit_analysis (Claude mocked at agents level)
# ---------------------------------------------------------------------------

def _mock_claude(category: str, confidence: float):
    """Return a mock ClaudeClient that returns the given category/confidence."""
    mock_resp = MagicMock()
    mock_resp.parse_json.return_value = {
        "category": category,
        "confidence": confidence,
        "rationale": "Test rationale.",
    }
    mock_resp.model = "claude-sonnet-4-6"
    mock_client = MagicMock()
    mock_client.call.return_value = mock_resp
    return mock_client


class TestAnalyseSmeEditTask:
    @pytest.mark.asyncio
    async def test_returns_category_and_confidence(self):
        from metadata_architect.workers.tasks import _run_edit_analysis

        with patch("metadata_architect.agents.claude_client.ClaudeClient",
                   return_value=_mock_claude("CLARITY_IMPROVEMENT", 0.92)), \
             patch("metadata_architect.workers.tasks._store_edit_record", new_callable=AsyncMock):
            result = await _run_edit_analysis("asset-1", "draft-1", "--- orig\n+++ new")

        assert result["category"] == "CLARITY_IMPROVEMENT"
        assert result["confidence"] == pytest.approx(0.92)
        assert result["asset_id"] == "asset-1"
        assert result["draft_id"] == "draft-1"

    @pytest.mark.asyncio
    async def test_analysed_at_is_tz_aware_iso_string(self):
        from datetime import datetime
        from metadata_architect.workers.tasks import _run_edit_analysis

        with patch("metadata_architect.agents.claude_client.ClaudeClient",
                   return_value=_mock_claude("FACTUAL_CORRECTION", 0.88)), \
             patch("metadata_architect.workers.tasks._store_edit_record", new_callable=AsyncMock):
            result = await _run_edit_analysis("a", "b", "diff")

        dt = datetime.fromisoformat(result["analysed_at"])
        assert dt.tzinfo is not None

    @pytest.mark.asyncio
    async def test_store_called_with_record(self):
        from metadata_architect.workers.tasks import _run_edit_analysis

        mock_store = AsyncMock()
        with patch("metadata_architect.agents.claude_client.ClaudeClient",
                   return_value=_mock_claude("SCOPE_EXPANSION", 0.75)), \
             patch("metadata_architect.workers.tasks._store_edit_record", mock_store):
            await _run_edit_analysis("asset-x", "draft-y", "diff text")

        mock_store.assert_called_once()
        call_args = mock_store.call_args[0]
        assert call_args[0] == "asset-x"
        assert call_args[1] == "draft-y"
        assert call_args[2]["category"] == "SCOPE_EXPANSION"

    @pytest.mark.asyncio
    async def test_all_six_categories_accepted(self):
        from metadata_architect.workers.tasks import _run_edit_analysis

        categories = [
            "FACTUAL_CORRECTION", "CLARITY_IMPROVEMENT", "SCOPE_EXPANSION",
            "SCOPE_REDUCTION", "TONE_ADJUSTMENT", "JARGON_REPLACEMENT",
        ]
        for cat in categories:
            with patch("metadata_architect.agents.claude_client.ClaudeClient",
                       return_value=_mock_claude(cat, 0.9)), \
                 patch("metadata_architect.workers.tasks._store_edit_record", new_callable=AsyncMock):
                result = await _run_edit_analysis("a", "b", "diff")
            assert result["category"] == cat
