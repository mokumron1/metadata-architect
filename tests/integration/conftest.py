"""
Integration test fixtures.

Uses SQLite + aiosqlite for a fully in-process async database
so integration tests run without Docker or a live Postgres instance.

The fixture creates a fresh schema per test session and provides
an AsyncSession and a TestClient wired to the same in-memory DB.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# SQLite compatibility: teach SQLite's type compiler to handle Postgres types
# ---------------------------------------------------------------------------
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler  # noqa: E402

def _visit_as_text(self, type_, **kw):
    return "TEXT"

SQLiteTypeCompiler.visit_JSONB = _visit_as_text       # type: ignore[attr-defined]
SQLiteTypeCompiler.visit_UUID = _visit_as_text        # type: ignore[attr-defined]
# ---------------------------------------------------------------------------

from metadata_architect.database import Base, get_db
from metadata_architect.api.main import app
from metadata_architect.models.asset_registry import (
    Asset,
    AssetType,
    SmeWorkflow,
    SoIDraft,
    TdkScoreLog,
    TdkScoreEvent,
    WorkflowStatus,
)

# SQLite in-memory URL for integration tests
_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = create_async_engine(_TEST_DB_URL, echo=False)
    async with eng.begin() as conn:
        # SQLite doesn't support all Postgres ENUMs — use native String for compatibility
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    """Fresh transaction per test — rolled back after each test."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def async_client(engine):
    """AsyncClient wired to the FastAPI app with the test DB session."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Shared factory helpers
# ---------------------------------------------------------------------------

async def make_asset(session: AsyncSession, name: str = "test.revenue_v1") -> Asset:
    asset = Asset(
        asset_name=name,
        asset_type=AssetType.table,
        source_system="postgres",
        raw_ddl="CREATE TABLE test (id SERIAL PRIMARY KEY, amount NUMERIC);",
        ddl_hash="abc123",
        column_metadata={"columns": [
            {"name": "id", "type": "INTEGER", "nullable": False, "is_primary_key": True,
             "is_foreign_key": False, "references": None, "default_value": None,
             "constraints": [], "comment": None},
            {"name": "amount", "type": "NUMERIC", "nullable": True, "is_primary_key": False,
             "is_foreign_key": False, "references": None, "default_value": None,
             "constraints": [], "comment": None},
        ], "primary_keys": ["id"], "foreign_keys": [], "table_options": {}},
    )
    session.add(asset)
    await session.flush()
    return asset


async def make_draft(session: AsyncSession, asset_id: uuid.UUID, version: int = 1) -> SoIDraft:
    draft = SoIDraft(
        asset_id=asset_id,
        version=version,
        statement_of_intent=(
            "This table stores daily revenue totals grouped by region. "
            "It supports the finance team in audit reporting."
        ),
        reading_level="B1 / 9th Grade",
        reading_level_score=7.5,
        jargon_violations={"violations": [], "is_compliant": True,
                           "sentence_count": 2, "longest_sentence_words": 12},
        tdk_initial_score=0.75,
        model_used="claude-sonnet-4-6",
    )
    session.add(draft)
    await session.flush()
    return draft


async def make_workflow(
    session: AsyncSession,
    asset_id: uuid.UUID,
    draft_id: uuid.UUID,
    status: WorkflowStatus = WorkflowStatus.AWAITING_SME_AUDIT,
    sla_hours_offset: float = 48.0,  # positive = future, negative = past
    context_authority: str = "sme@example.com",
) -> SmeWorkflow:
    deadline = datetime.now(timezone.utc) + timedelta(hours=sla_hours_offset)
    workflow = SmeWorkflow(
        asset_id=asset_id,
        draft_id=draft_id,
        context_authority=context_authority,
        status=status,
        sla_deadline_at=deadline,
        notification_sent_at=datetime.now(timezone.utc),
    )
    session.add(workflow)
    await session.flush()
    return workflow
