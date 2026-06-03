"""
Integration tests for the batch ingestion endpoint.

POST /batch/ingest with SQLite in-memory DB.
Celery tasks are not tested here — drafting is disabled via enqueue_drafting=false.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from metadata_architect.config import get_settings
from metadata_architect.models.asset_registry import Asset, SmeWorkflow, WorkflowStatus

_GATE_KEY = get_settings().gate_api_key
_HEADERS = {"x-gate-api-key": _GATE_KEY}

_DDL = (
    "CREATE TABLE finance.test_{tag} ("
    "  id SERIAL PRIMARY KEY, "
    "  amount NUMERIC(18,4) NOT NULL, "
    "  region VARCHAR(64), "
    "  created_at TIMESTAMPTZ DEFAULT now()"
    ");"
)


def _make_asset(tag: str, authority: str = "sme@example.com") -> dict:
    return {
        "asset_name": f"finance.test_{tag}",
        "asset_type": "table",
        "source_system": "postgres",
        "context_authority": authority,
        "raw_ddl": _DDL.format(tag=tag),
    }


class TestBatchIngest:
    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, async_client):
        self.client = async_client

    async def test_single_asset_returns_202(self):
        resp = await self.client.post(
            "/batch/ingest",
            json={"assets": [_make_asset(uuid.uuid4().hex[:8])], "enqueue_drafting": False},
            headers=_HEADERS,
        )
        assert resp.status_code == 202

    async def test_response_counts_created(self):
        assets = [_make_asset(uuid.uuid4().hex[:8]) for _ in range(3)]
        resp = await self.client.post(
            "/batch/ingest",
            json={"assets": assets, "enqueue_drafting": False},
            headers=_HEADERS,
        )
        data = resp.json()
        assert data["created"] == 3
        assert data["skipped"] == 0
        assert data["errors"] == 0

    async def test_results_list_length_matches_submitted(self):
        assets = [_make_asset(uuid.uuid4().hex[:8]) for _ in range(4)]
        resp = await self.client.post(
            "/batch/ingest",
            json={"assets": assets, "enqueue_drafting": False},
            headers=_HEADERS,
        )
        data = resp.json()
        assert len(data["results"]) == 4

    async def test_created_result_has_asset_id(self):
        tag = uuid.uuid4().hex[:8]
        resp = await self.client.post(
            "/batch/ingest",
            json={"assets": [_make_asset(tag)], "enqueue_drafting": False},
            headers=_HEADERS,
        )
        result = resp.json()["results"][0]
        assert result["status"] == "created"
        assert result["asset_id"] is not None
        uuid.UUID(result["asset_id"])  # valid UUID

    async def test_duplicate_skipped_by_default(self, db_session):
        tag = uuid.uuid4().hex[:8]
        # First ingest
        await self.client.post(
            "/batch/ingest",
            json={"assets": [_make_asset(tag)], "enqueue_drafting": False},
            headers=_HEADERS,
        )
        # Second ingest — same name
        resp = await self.client.post(
            "/batch/ingest",
            json={"assets": [_make_asset(tag)], "enqueue_drafting": False},
            headers=_HEADERS,
        )
        data = resp.json()
        assert data["skipped"] == 1
        assert data["created"] == 0

    async def test_duplicate_fails_when_skip_false(self):
        tag = uuid.uuid4().hex[:8]
        await self.client.post(
            "/batch/ingest",
            json={"assets": [_make_asset(tag)], "enqueue_drafting": False},
            headers=_HEADERS,
        )
        resp = await self.client.post(
            "/batch/ingest",
            json={
                "assets": [_make_asset(tag)],
                "enqueue_drafting": False,
                "skip_existing": False,
            },
            headers=_HEADERS,
        )
        data = resp.json()
        assert data["errors"] == 1
        assert data["results"][0]["status"] == "error"

    async def test_workflow_created_for_each_asset(self, db_session):
        tags = [uuid.uuid4().hex[:8] for _ in range(2)]
        resp = await self.client.post(
            "/batch/ingest",
            json={"assets": [_make_asset(t) for t in tags], "enqueue_drafting": False},
            headers=_HEADERS,
        )
        asset_ids = [r["asset_id"] for r in resp.json()["results"]]
        for aid in asset_ids:
            result = await db_session.execute(
                select(SmeWorkflow).where(SmeWorkflow.asset_id == uuid.UUID(aid))
            )
            wf = result.scalar_one_or_none()
            assert wf is not None
            assert wf.status == WorkflowStatus.AWAITING_SME_AUDIT

    async def test_enqueue_drafting_calls_celery(self):
        tag = uuid.uuid4().hex[:8]
        with patch(
            "metadata_architect.workers.tasks.draft_asset_metadata"
        ) as mock_task:
            mock_task.delay = MagicMock()
            resp = await self.client.post(
                "/batch/ingest",
                json={"assets": [_make_asset(tag)], "enqueue_drafting": True},
                headers=_HEADERS,
            )
        assert resp.status_code == 202
        assert resp.json()["results"][0]["drafting_queued"] is True

    async def test_empty_assets_returns_422(self):
        resp = await self.client.post(
            "/batch/ingest",
            json={"assets": [], "enqueue_drafting": False},
            headers=_HEADERS,
        )
        assert resp.status_code == 422

    async def test_invalid_ddl_still_registers_asset(self):
        tag = uuid.uuid4().hex[:8]
        resp = await self.client.post(
            "/batch/ingest",
            json={
                "assets": [{
                    "asset_name": f"finance.bad_ddl_{tag}",
                    "asset_type": "table",
                    "source_system": "postgres",
                    "context_authority": "sme@example.com",
                    "raw_ddl": "NOT VALID SQL AT ALL",
                }],
                "enqueue_drafting": False,
            },
            headers=_HEADERS,
        )
        # Asset is registered even when DDL parse fails (column_metadata will be null)
        assert resp.json()["created"] == 1

    async def test_mixed_valid_and_duplicate(self):
        tag_existing = uuid.uuid4().hex[:8]
        tag_new = uuid.uuid4().hex[:8]
        # Register existing
        await self.client.post(
            "/batch/ingest",
            json={"assets": [_make_asset(tag_existing)], "enqueue_drafting": False},
            headers=_HEADERS,
        )
        # Mix
        resp = await self.client.post(
            "/batch/ingest",
            json={
                "assets": [_make_asset(tag_existing), _make_asset(tag_new)],
                "enqueue_drafting": False,
            },
            headers=_HEADERS,
        )
        data = resp.json()
        assert data["created"] == 1
        assert data["skipped"] == 1
