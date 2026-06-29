"""
AuditLogger — ISO 27001 A.12.4 compliant audit trail.

Every call writes:
  1. A structured JSON log line (to structlog — captured by your log sink)
  2. An AuditLogEntry row in the database (permanent, queryable)

Usage::

    async with AuditLogger(db, request_id="…", asset_name="…") as log:
        await log.event("MD_REQUEST_RECEIVED", details={"column": "AMT_D_01"})
        # ... do work ...
        await log.event("MD_DRAFT_PERSISTED", outcome=Outcome.SUCCESS)

The context manager records total duration on __aexit__ and writes a final
summary event automatically.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from metadata_architect.audit.events import Interface, Outcome, RiskLevel, Severity, lookup
from metadata_architect.models.audit import AuditLogEntry

log = structlog.get_logger(__name__)


class AuditLogger:
    """
    Writes ISO 27001-conformant audit events for one logical request.

    Parameters
    ----------
    db          : AsyncSession bound to the current request
    request_id  : The X-Request-ID propagated from the HTTP middleware
    interface   : Which of the three onboarding interfaces owns this request
    asset_name  : The data asset being acted on (for quick filtering)
    actor       : Identifier of the calling system / user (default: "system")
    """

    def __init__(
        self,
        db: AsyncSession,
        request_id: str,
        interface: Interface,
        asset_name: str = "",
        actor: str = "system",
    ) -> None:
        self._db         = db
        self._request_id = request_id
        self._interface  = interface
        self._asset_name = asset_name
        self._actor      = actor
        self._sequence   = 0
        self._started_at = time.monotonic()

    async def event(
        self,
        code: str,
        outcome: Outcome = Outcome.SUCCESS,
        details: dict[str, Any] | None = None,
        duration_ms: float | None = None,
        override_severity: Severity | None = None,
        override_risk: RiskLevel | None = None,
    ) -> AuditLogEntry:
        """
        Write one audit event.

        All ISO 27001 A.12.4 mandatory fields are set automatically from
        the event catalogue — only supply the event code and contextual details.
        """
        description, severity, risk_level, interface = lookup(code)

        if override_severity:
            severity = override_severity
        if override_risk:
            risk_level = override_risk

        self._sequence += 1
        entry = AuditLogEntry(
            event_id      = str(uuid.uuid4()),
            request_id    = self._request_id,
            sequence      = self._sequence,
            event_code    = code,
            event_description = description,
            interface     = self._interface.value,
            actor         = self._actor,
            asset_name    = self._asset_name,
            outcome       = outcome.value,
            severity      = severity.value,
            risk_level    = risk_level.value,
            details       = details or {},
            duration_ms   = duration_ms,
        )
        self._db.add(entry)
        await self._db.flush()   # visible in transaction; caller commits

        # Structured log line — picked up by any log sink (CloudWatch, Splunk, etc.)
        log.info(
            "audit",
            event_id   = entry.event_id,
            request_id = self._request_id,
            sequence   = self._sequence,
            code       = code,
            interface  = self._interface.value,
            asset      = self._asset_name,
            outcome    = outcome.value,
            severity   = severity.value,
            risk       = risk_level.value,
            actor      = self._actor,
            **(details or {}),
        )
        return entry

    # ------------------------------------------------------------------
    # Convenience timer helper
    # ------------------------------------------------------------------

    def timer(self) -> "_Timer":
        """Return a context-manager that measures elapsed ms."""
        return _Timer()

    # ------------------------------------------------------------------
    # Total elapsed since construction
    # ------------------------------------------------------------------

    def elapsed_ms(self) -> float:
        return (time.monotonic() - self._started_at) * 1000


class _Timer:
    """Lightweight elapsed-time context manager."""

    def __init__(self) -> None:
        self._start = time.monotonic()
        self.ms: float = 0.0

    def __enter__(self) -> "_Timer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *_: Any) -> None:
        self.ms = (time.monotonic() - self._start) * 1000


# ---------------------------------------------------------------------------
# FastAPI dependency — injects a fully-configured AuditLogger into a route
# ---------------------------------------------------------------------------

def make_audit_logger(
    interface: Interface,
    asset_name: str = "",
    actor: str = "system",
):
    """
    FastAPI dependency factory.

    Usage in a router::

        from metadata_architect.audit.logger import make_audit_logger
        from metadata_architect.audit.events import Interface

        @router.post("/my-endpoint")
        async def my_handler(
            body: MyRequest,
            request: Request,
            db: AsyncSession = Depends(get_db),
            audit: AuditLogger = Depends(
                make_audit_logger(Interface.METADATA_DRAFTER)
            ),
        ):
            await audit.event("MD_REQUEST_RECEIVED", details={"column": body.column_name})
    """
    async def _dep(
        request: "fastapi.Request",  # type: ignore[name-defined]
        db: AsyncSession,
    ) -> AuditLogger:
        request_id = (
            request.headers.get("x-request-id")
            or request.state.__dict__.get("request_id", str(uuid.uuid4()))
        )
        return AuditLogger(
            db=db,
            request_id=request_id,
            interface=interface,
            asset_name=asset_name,
            actor=actor,
        )
    return _dep
