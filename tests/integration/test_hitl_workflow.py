"""
Integration tests for the HITL Workflow API endpoints.

Tests the full approve / edit / reject paths via the FastAPI
test client with an in-memory SQLite database.

Notifications and Celery tasks are mocked — these tests verify
API contract, state transitions, TDK score persistence, and
YAML policy generation without external dependencies.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from metadata_architect.auth.tokens import TokenService
from metadata_architect.models.asset_registry import WorkflowStatus

from tests.integration.conftest import make_asset, make_draft, make_workflow

_token_svc = TokenService()


def _make_token(workflow_id: uuid.UUID, sme_email: str = "sme@example.com") -> str:
    deadline = datetime.now(timezone.utc) + timedelta(hours=48)
    return _token_svc.create_review_token(workflow_id, sme_email, deadline)


# ---------------------------------------------------------------------------
# Approve path
# ---------------------------------------------------------------------------

class TestApproveWorkflow:
    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, db_session, async_client):
        self.client = async_client
        self.asset = await make_asset(db_session, name=f"test.approve_{uuid.uuid4().hex[:6]}")
        self.draft = await make_draft(db_session, self.asset.id)
        self.workflow = await make_workflow(
            db_session, self.asset.id, self.draft.id, sla_hours_offset=24.0
        )
        await db_session.commit()

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    async def test_approve_returns_200(self, mock_notify):
        token = _make_token(self.workflow.id)
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/approve",
            json={"review_token": token},
        )
        assert resp.status_code == 200

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    async def test_approve_status_in_response(self, mock_notify):
        token = _make_token(self.workflow.id)
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/approve",
            json={"review_token": token},
        )
        data = resp.json()
        assert data["new_status"] == "SME_APPROVED"

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    async def test_approve_returns_policy_yaml(self, mock_notify):
        token = _make_token(self.workflow.id)
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/approve",
            json={"review_token": token},
        )
        data = resp.json()
        assert data["policy_yaml"] is not None
        assert "asset_metadata" in data["policy_yaml"]

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    async def test_approve_returns_tdk_score(self, mock_notify):
        token = _make_token(self.workflow.id)
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/approve",
            json={"review_token": token},
        )
        data = resp.json()
        assert 0.0 <= data["tdk_score"] <= 1.0

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    async def test_approve_sends_notification(self, mock_notify):
        token = _make_token(self.workflow.id)
        await self.client.post(
            f"/workflows/{self.workflow.id}/approve",
            json={"review_token": token},
        )
        mock_notify.assert_called_once()

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    async def test_double_approve_returns_409(self, mock_notify):
        token = _make_token(self.workflow.id)
        await self.client.post(
            f"/workflows/{self.workflow.id}/approve",
            json={"review_token": token},
        )
        # Second approve on an already-approved workflow
        token2 = _make_token(self.workflow.id)
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/approve",
            json={"review_token": token2},
        )
        assert resp.status_code == 409

    async def test_invalid_token_returns_401(self):
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/approve",
            json={"review_token": "not.a.valid.token"},
        )
        assert resp.status_code == 401

    async def test_wrong_workflow_token_returns_403(self, db_session):
        other_workflow_id = uuid.uuid4()
        token = _make_token(other_workflow_id)  # token for a different workflow
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/approve",
            json={"review_token": token},
        )
        assert resp.status_code == 403

    async def test_nonexistent_workflow_returns_404(self):
        token = _make_token(uuid.uuid4())
        resp = await self.client.post(
            f"/workflows/{uuid.uuid4()}/approve",
            json={"review_token": token},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Edit + approve path
# ---------------------------------------------------------------------------

class TestEditWorkflow:
    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, db_session, async_client):
        self.client = async_client
        self.asset = await make_asset(db_session, name=f"test.edit_{uuid.uuid4().hex[:6]}")
        self.draft = await make_draft(db_session, self.asset.id)
        self.workflow = await make_workflow(
            db_session, self.asset.id, self.draft.id, sla_hours_offset=24.0
        )
        await db_session.commit()

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    @patch("metadata_architect.api.routers.workflows._queue_edit_analysis")
    async def test_edit_returns_200(self, mock_queue, mock_notify):
        token = _make_token(self.workflow.id)
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/edit",
            json={
                "review_token": token,
                "corrected_soi": (
                    "This table stores daily revenue totals by region and currency. "
                    "It supports finance audit reporting each quarter."
                ),
                "edit_reason": "Clarified downstream consumer.",
            },
        )
        assert resp.status_code == 200

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    @patch("metadata_architect.api.routers.workflows._queue_edit_analysis")
    async def test_edit_final_status_is_approved(self, mock_queue, mock_notify):
        token = _make_token(self.workflow.id)
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/edit",
            json={
                "review_token": token,
                "corrected_soi": (
                    "This table records monthly revenue by currency and region. "
                    "Finance teams use it for quarterly audit reports."
                ),
            },
        )
        assert resp.json()["new_status"] == "SME_APPROVED"

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    @patch("metadata_architect.api.routers.workflows._queue_edit_analysis")
    async def test_edit_queues_analysis_task(self, mock_queue, mock_notify):
        token = _make_token(self.workflow.id)
        await self.client.post(
            f"/workflows/{self.workflow.id}/edit",
            json={
                "review_token": token,
                "corrected_soi": (
                    "This table records monthly revenue by currency and region. "
                    "Finance teams use it for quarterly audit reports."
                ),
            },
        )
        mock_queue.assert_called_once()

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    @patch("metadata_architect.api.routers.workflows._queue_edit_analysis")
    async def test_edit_too_short_returns_422(self, mock_queue, mock_notify):
        token = _make_token(self.workflow.id)
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/edit",
            json={
                "review_token": token,
                "corrected_soi": "Too short.",
            },
        )
        assert resp.status_code == 422

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    @patch("metadata_architect.api.routers.workflows._queue_edit_analysis")
    async def test_edit_policy_yaml_contains_corrected_soi(self, mock_queue, mock_notify):
        token = _make_token(self.workflow.id)
        corrected = (
            "This table records monthly revenue by currency and region. "
            "Finance teams use it for quarterly audit reports."
        )
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/edit",
            json={"review_token": token, "corrected_soi": corrected},
        )
        yaml_text = resp.json()["policy_yaml"]
        # ruamel.yaml may line-wrap long strings — normalise whitespace before checking
        normalised = " ".join(yaml_text.split())
        assert "monthly revenue" in normalised
        assert "quarterly audit" in normalised


# ---------------------------------------------------------------------------
# Reject path
# ---------------------------------------------------------------------------

class TestRejectWorkflow:
    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, db_session, async_client):
        self.client = async_client
        self.asset = await make_asset(db_session, name=f"test.reject_{uuid.uuid4().hex[:6]}")
        self.draft = await make_draft(db_session, self.asset.id)
        self.workflow = await make_workflow(
            db_session, self.asset.id, self.draft.id, sla_hours_offset=24.0
        )
        await db_session.commit()

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    async def test_reject_returns_200(self, mock_notify):
        token = _make_token(self.workflow.id)
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/reject",
            json={
                "review_token": token,
                "rejection_reason": "This table is redundant — data already exists in revenue_master.",
            },
        )
        assert resp.status_code == 200

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    async def test_reject_status_is_rejected(self, mock_notify):
        token = _make_token(self.workflow.id)
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/reject",
            json={
                "review_token": token,
                "rejection_reason": "Redundant table — covered by revenue_master.",
            },
        )
        assert resp.json()["new_status"] == "SME_REJECTED"

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    async def test_reject_no_policy_yaml(self, mock_notify):
        token = _make_token(self.workflow.id)
        resp = await self.client.post(
            f"/workflows/{self.workflow.id}/reject",
            json={
                "review_token": token,
                "rejection_reason": "Redundant table.",
            },
        )
        assert resp.json()["policy_yaml"] is None

    @patch("metadata_architect.api.routers.workflows._send_notification", new_callable=AsyncMock)
    async def test_reject_sends_notification(self, mock_notify):
        token = _make_token(self.workflow.id)
        await self.client.post(
            f"/workflows/{self.workflow.id}/reject",
            json={
                "review_token": token,
                "rejection_reason": "Redundant table.",
            },
        )
        mock_notify.assert_called_once()


# ---------------------------------------------------------------------------
# List + Get endpoints
# ---------------------------------------------------------------------------

class TestWorkflowListGet:
    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, db_session, async_client):
        self.client = async_client
        self.asset = await make_asset(db_session, name=f"test.list_{uuid.uuid4().hex[:6]}")
        self.draft = await make_draft(db_session, self.asset.id)
        self.workflow = await make_workflow(
            db_session, self.asset.id, self.draft.id
        )
        await db_session.commit()

    async def test_list_returns_200(self):
        resp = await self.client.get("/workflows")
        assert resp.status_code == 200

    async def test_list_contains_items_key(self):
        resp = await self.client.get("/workflows")
        assert "items" in resp.json()

    async def test_get_workflow_returns_200(self):
        resp = await self.client.get(f"/workflows/{self.workflow.id}")
        assert resp.status_code == 200

    async def test_get_workflow_contains_draft(self):
        resp = await self.client.get(f"/workflows/{self.workflow.id}")
        data = resp.json()
        assert "draft" in data
        assert data["draft"]["statement_of_intent"] is not None

    async def test_get_nonexistent_returns_404(self):
        resp = await self.client.get(f"/workflows/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_list_filter_by_status(self):
        resp = await self.client.get("/workflows?status=AWAITING_SME_AUDIT")
        assert resp.status_code == 200
        items = resp.json()["items"]
        for item in items:
            assert item["status"] == "AWAITING_SME_AUDIT"
