"""
Unit tests for Phase 5 hardening components.

- RequestIDMiddleware: X-Request-ID header propagation
- Rate limiter: sliding window enforcement
- Tracing: no-op tracer when OTel SDK absent
- Alembic migration 0002 exists and chains from 0001
"""

import importlib
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# RequestIDMiddleware
# ---------------------------------------------------------------------------

class TestRequestIDMiddleware:
    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, async_client):
        self.client = async_client

    async def test_response_has_request_id_header(self):
        resp = await self.client.get("/health")
        assert "x-request-id" in resp.headers

    async def test_propagated_request_id_is_echoed(self):
        sent_id = str(uuid.uuid4())
        resp = await self.client.get("/health", headers={"X-Request-ID": sent_id})
        assert resp.headers["x-request-id"] == sent_id

    async def test_generated_id_is_valid_uuid(self):
        resp = await self.client.get("/health")
        request_id = resp.headers["x-request-id"]
        uuid.UUID(request_id)  # raises ValueError if not a valid UUID

    async def test_different_requests_get_different_ids(self):
        r1 = await self.client.get("/health")
        r2 = await self.client.get("/health")
        assert r1.headers["x-request-id"] != r2.headers["x-request-id"]


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class TestGateRateLimiter:
    def setup_method(self):
        # Reset the in-process bucket state between tests
        from metadata_architect.middleware import rate_limit
        rate_limit._buckets.clear()

    def _make_request(self, api_key: str = "test-key") -> MagicMock:
        req = MagicMock()
        req.headers = {"x-gate-api-key": api_key}
        return req

    def test_first_request_passes(self):
        from metadata_architect.middleware.rate_limit import check_gate_rate_limit
        # Should not raise
        check_gate_rate_limit(self._make_request())

    def test_within_limit_passes(self):
        from metadata_architect.middleware.rate_limit import check_gate_rate_limit
        for _ in range(5):
            check_gate_rate_limit(self._make_request("key-a"))

    def test_exceeds_limit_raises_429(self):
        from fastapi import HTTPException
        from metadata_architect.middleware import rate_limit

        # Temporarily tighten the limit to 3 requests for this test
        original_limit = rate_limit._LIMIT
        rate_limit._LIMIT = 3
        try:
            for _ in range(3):
                rate_limit.check_gate_rate_limit(self._make_request("burst-key"))
            with pytest.raises(HTTPException) as exc_info:
                rate_limit.check_gate_rate_limit(self._make_request("burst-key"))
            assert exc_info.value.status_code == 429
        finally:
            rate_limit._LIMIT = original_limit

    def test_different_keys_have_independent_buckets(self):
        from metadata_architect.middleware import rate_limit

        original_limit = rate_limit._LIMIT
        rate_limit._LIMIT = 2
        try:
            # Key A exhausted
            for _ in range(2):
                rate_limit.check_gate_rate_limit(self._make_request("key-a"))
            # Key B unaffected
            rate_limit.check_gate_rate_limit(self._make_request("key-b"))
        finally:
            rate_limit._LIMIT = original_limit

    def test_retry_after_header_present(self):
        from fastapi import HTTPException
        from metadata_architect.middleware import rate_limit

        original_limit = rate_limit._LIMIT
        rate_limit._LIMIT = 1
        try:
            rate_limit.check_gate_rate_limit(self._make_request("hdr-key"))
            with pytest.raises(HTTPException) as exc_info:
                rate_limit.check_gate_rate_limit(self._make_request("hdr-key"))
            assert "Retry-After" in exc_info.value.headers
        finally:
            rate_limit._LIMIT = original_limit


# ---------------------------------------------------------------------------
# Tracing no-op
# ---------------------------------------------------------------------------

class TestTracingNoop:
    def test_noop_tracer_start_span_does_not_raise(self):
        from metadata_architect.observability.tracing import _NoopTracer
        tracer = _NoopTracer()
        with tracer.start_as_current_span("test.span") as span:
            span.set_attribute("key", "value")
            span.record_exception(Exception("test"))
            span.set_status("OK")

    def test_get_tracer_returns_something(self):
        from metadata_architect.observability.tracing import get_tracer
        tracer = get_tracer()
        assert tracer is not None

    def test_setup_tracing_without_sdk_uses_noop(self):
        from metadata_architect.observability import tracing as tracing_mod
        original = tracing_mod._tracer
        try:
            tracing_mod._tracer = None
            with patch.dict("sys.modules", {"opentelemetry": None}):
                tracing_mod.setup_tracing()
            # Should have fallen back to noop
            assert tracing_mod._tracer is not None
        finally:
            tracing_mod._tracer = original


# ---------------------------------------------------------------------------
# Alembic migration chain
# ---------------------------------------------------------------------------

class TestAlembicMigrations:
    def test_0002_revises_0001(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config("alembic.ini")
        scripts = ScriptDirectory.from_config(cfg)
        rev = scripts.get_revision("0002")
        assert rev is not None
        assert rev.down_revision == "0001"

    def test_0002_has_upgrade_and_downgrade(self):
        import importlib.util, pathlib
        path = pathlib.Path("alembic/versions/0002_perf_indexes.py")
        spec = importlib.util.spec_from_file_location("rev_0002", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)

    def test_0001_is_base_revision(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config("alembic.ini")
        scripts = ScriptDirectory.from_config(cfg)
        rev = scripts.get_revision("0001")
        assert rev.down_revision is None
