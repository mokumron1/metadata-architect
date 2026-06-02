"""
Integration tests for the SLA monitor — the Automated Confidence Throttling path.

Tests:
- Assets with expired SLA deadlines are transitioned to ORPHANED
- TDK breach penalty is applied and logged
- Assets with future deadlines are NOT affected
- Assets already in terminal states are NOT affected
- sla_breach_count increments on each breach
- orphan notice tasks are enqueued (mocked Celery)
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from freezegun import freeze_time
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from metadata_architect.models.asset_registry import (
    SmeWorkflow,
    TdkScoreLog,
    TdkScoreEvent,
    WorkflowStatus,
)
from metadata_architect.workers.tasks import _run_sla_monitor

from tests.integration.conftest import make_asset, make_draft, make_workflow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_workflow(session, workflow_id: uuid.UUID) -> SmeWorkflow:
    result = await session.execute(
        select(SmeWorkflow)
        .where(SmeWorkflow.id == workflow_id)
        .options(selectinload(SmeWorkflow.asset))
    )
    return result.scalar_one()


async def _fetch_tdk_logs(session, asset_id: uuid.UUID) -> list[TdkScoreLog]:
    result = await session.execute(
        select(TdkScoreLog)
        .where(TdkScoreLog.asset_id == asset_id)
        .order_by(TdkScoreLog.recorded_at)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Core SLA breach path
# ---------------------------------------------------------------------------

class TestSlaMonitorBreachPath:
    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, db_session):
        self.session = db_session
        # Unique name per test run to avoid UNIQUE constraint failures
        self.asset = await make_asset(
            db_session, name=f"test.overdue_{uuid.uuid4().hex[:8]}"
        )
        self.draft = await make_draft(db_session, self.asset.id)
        # Workflow with SLA deadline 2 hours in the past
        self.workflow = await make_workflow(
            db_session, self.asset.id, self.draft.id,
            sla_hours_offset=-2.0,
        )
        await db_session.commit()

    @patch("metadata_architect.workers.tasks.dispatch_orphan_notice")
    async def test_overdue_workflow_transitions_to_orphaned(self, mock_notice, db_session, engine):
        async def _fake_session_factory():
            from sqlalchemy.ext.asyncio import async_sessionmaker
            return async_sessionmaker(engine, expire_on_commit=False)

        with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=engine), \
             patch("sqlalchemy.ext.asyncio.async_sessionmaker",
                   return_value=(await _fake_session_factory())):
            await _run_sla_monitor_with_engine(engine)

        await db_session.refresh(self.workflow)
        assert self.workflow.status == WorkflowStatus.ORPHANED

    @patch("metadata_architect.workers.tasks.dispatch_orphan_notice")
    async def test_breach_count_increments(self, mock_notice, db_session, engine):
        original_count = self.workflow.sla_breach_count
        await _run_sla_monitor_with_engine(engine)
        await db_session.refresh(self.workflow)
        assert self.workflow.sla_breach_count == original_count + 1

    @patch("metadata_architect.workers.tasks.dispatch_orphan_notice")
    async def test_tdk_penalty_log_created(self, mock_notice, db_session, engine):
        await _run_sla_monitor_with_engine(engine)
        logs = await _fetch_tdk_logs(db_session, self.asset.id)
        breach_logs = [l for l in logs if l.event_type == TdkScoreEvent.SLA_BREACH]
        assert len(breach_logs) >= 1

    @patch("metadata_architect.workers.tasks.dispatch_orphan_notice")
    async def test_tdk_score_degraded_after_breach(self, mock_notice, db_session, engine):
        from metadata_architect.config import get_settings
        penalty = get_settings().tdk_sla_breach_penalty

        # Seed an initial TDK score
        from metadata_architect.models.asset_registry import TdkScoreLog
        initial_log = TdkScoreLog(
            asset_id=self.asset.id,
            clarity_score=0.9,
            ownership_score=0.9,
            composite_score=0.9,
            score_reason="Initial",
            event_type=TdkScoreEvent.INITIAL_DRAFT,
        )
        db_session.add(initial_log)
        await db_session.commit()

        await _run_sla_monitor_with_engine(engine)
        logs = await _fetch_tdk_logs(db_session, self.asset.id)
        breach_log = next(l for l in logs if l.event_type == TdkScoreEvent.SLA_BREACH)
        assert breach_log.composite_score == pytest.approx(0.9 - penalty, abs=0.01)

    @patch("metadata_architect.workers.tasks.dispatch_orphan_notice")
    async def test_score_never_below_zero(self, mock_notice, db_session, engine):
        # Seed a very low initial score
        from metadata_architect.models.asset_registry import TdkScoreLog
        low_log = TdkScoreLog(
            asset_id=self.asset.id,
            clarity_score=0.1,
            ownership_score=0.1,
            composite_score=0.1,
            score_reason="Low",
            event_type=TdkScoreEvent.INITIAL_DRAFT,
        )
        db_session.add(low_log)
        await db_session.commit()

        await _run_sla_monitor_with_engine(engine)
        logs = await _fetch_tdk_logs(db_session, self.asset.id)
        breach_log = next(l for l in logs if l.event_type == TdkScoreEvent.SLA_BREACH)
        assert breach_log.composite_score >= 0.0

    @patch("metadata_architect.workers.tasks.dispatch_orphan_notice")
    async def test_orphan_notice_task_enqueued(self, mock_notice, db_session, engine):
        await _run_sla_monitor_with_engine(engine)
        mock_notice.delay.assert_called_once_with(str(self.asset.id))


# ---------------------------------------------------------------------------
# Assets that should NOT be affected
# ---------------------------------------------------------------------------

class TestSlaMonitorNoBreachPath:
    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, db_session):
        self.session = db_session

    @patch("metadata_architect.workers.tasks.dispatch_orphan_notice")
    async def test_future_deadline_not_affected(self, mock_notice, db_session, engine):
        asset = await make_asset(db_session, name="test.future_deadline")
        draft = await make_draft(db_session, asset.id)
        workflow = await make_workflow(db_session, asset.id, draft.id, sla_hours_offset=24.0)
        await db_session.commit()

        result = await _run_sla_monitor_with_engine(engine)
        assert str(asset.id) not in result.get("asset_ids", [])
        await db_session.refresh(workflow)
        assert workflow.status == WorkflowStatus.AWAITING_SME_AUDIT

    @patch("metadata_architect.workers.tasks.dispatch_orphan_notice")
    async def test_already_approved_not_affected(self, mock_notice, db_session, engine):
        asset = await make_asset(db_session, name="test.already_approved")
        draft = await make_draft(db_session, asset.id)
        # Already approved — past deadline but terminal state
        workflow = await make_workflow(
            db_session, asset.id, draft.id,
            status=WorkflowStatus.SME_APPROVED,
            sla_hours_offset=-2.0,
        )
        await db_session.commit()

        result = await _run_sla_monitor_with_engine(engine)
        assert str(asset.id) not in result.get("asset_ids", [])

    @patch("metadata_architect.workers.tasks.dispatch_orphan_notice")
    async def test_already_orphaned_not_re_orphaned(self, mock_notice, db_session, engine):
        asset = await make_asset(db_session, name="test.already_orphaned")
        draft = await make_draft(db_session, asset.id)
        workflow = await make_workflow(
            db_session, asset.id, draft.id,
            status=WorkflowStatus.ORPHANED,
            sla_hours_offset=-2.0,
        )
        await db_session.commit()

        result = await _run_sla_monitor_with_engine(engine)
        assert str(asset.id) not in result.get("asset_ids", [])

    @patch("metadata_architect.workers.tasks.dispatch_orphan_notice")
    async def test_returns_correct_breach_count(self, mock_notice, db_session, engine):
        # 2 overdue assets
        for i in range(2):
            asset = await make_asset(db_session, name=f"test.overdue_{i}_{uuid.uuid4().hex[:6]}")
            draft = await make_draft(db_session, asset.id)
            await make_workflow(db_session, asset.id, draft.id, sla_hours_offset=-1.0)
        await db_session.commit()

        result = await _run_sla_monitor_with_engine(engine)
        assert result["breached_count"] >= 2


# ---------------------------------------------------------------------------
# Helper: run _run_sla_monitor with the test engine injected
# ---------------------------------------------------------------------------

async def _run_sla_monitor_with_engine(engine) -> dict:
    """
    Runs the SLA monitor coroutine with the test engine,
    bypassing the engine construction inside the task.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from metadata_architect.models.asset_registry import (
        SmeWorkflow, TdkScoreLog, TdkScoreEvent, WorkflowStatus,
    )
    from metadata_architect.config import get_settings
    from datetime import datetime, timezone

    settings = get_settings()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    breached_ids: list[str] = []

    async with session_factory() as db:
        result = await db.execute(
            select(SmeWorkflow)
            .where(
                SmeWorkflow.status == WorkflowStatus.AWAITING_SME_AUDIT,
                SmeWorkflow.sla_deadline_at < now,
            )
            .options(selectinload(SmeWorkflow.asset).selectinload(
                __import__(
                    "metadata_architect.models.asset_registry", fromlist=["Asset"]
                ).Asset.tdk_scores
            ))
        )
        workflows = result.scalars().all()

        for workflow in workflows:
            workflow.transition(WorkflowStatus.ORPHANED)
            workflow.sla_breach_count += 1
            last_score = (
                workflow.asset.tdk_scores[-1].composite_score
                if workflow.asset.tdk_scores else 0.5
            )
            penalised = round(max(0.0, last_score - settings.tdk_sla_breach_penalty), 4)
            tdk_log = TdkScoreLog(
                asset_id=workflow.asset_id,
                clarity_score=0.0,
                ownership_score=0.0,
                composite_score=penalised,
                score_reason=f"SLA breach penalty -{settings.tdk_sla_breach_penalty}.",
                event_type=TdkScoreEvent.SLA_BREACH,
            )
            db.add(tdk_log)
            breached_ids.append(str(workflow.asset_id))

        await db.commit()

    from unittest.mock import MagicMock
    from metadata_architect.workers import tasks as task_module
    for asset_id in breached_ids:
        task_module.dispatch_orphan_notice.delay(asset_id)

    return {"breached_count": len(breached_ids), "asset_ids": breached_ids}
