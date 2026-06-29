"""
Audit Log Query API — ISO 27001 A.12.4 audit trail retrieval.

Allows querying audit events by request_id, interface, asset_name,
severity, outcome, and date range.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from metadata_architect.database import get_db
from metadata_architect.models.audit import AuditLogEntry

router = APIRouter(prefix="/audit", tags=["audit-log"])


@router.get("/", summary="Query the ISO 27001 audit log")
async def query_audit_log(
    request_id: Optional[str] = Query(None, description="Filter by X-Request-ID"),
    interface: Optional[str] = Query(None, description="METADATA_DRAFTER | SECURITY_TRIAGE | INTERVIEW_BOT | SYSTEM"),
    asset_name: Optional[str] = Query(None, description="Partial match on asset name"),
    severity: Optional[str] = Query(None, description="INFO | WARNING | ERROR | CRITICAL"),
    outcome: Optional[str] = Query(None, description="SUCCESS | FAILURE | PENDING | SKIPPED"),
    event_code: Optional[str] = Query(None, description="Exact event code, e.g. MD_REQUEST_RECEIVED"),
    from_ts: Optional[datetime] = Query(None, description="ISO 8601 start timestamp (UTC)"),
    to_ts: Optional[datetime] = Query(None, description="ISO 8601 end timestamp (UTC)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Return audit log entries matching the supplied filters, ordered by
    request_id + sequence so a single request's events are contiguous.
    """
    filters = []
    if request_id:
        filters.append(AuditLogEntry.request_id == request_id)
    if interface:
        filters.append(AuditLogEntry.interface == interface.upper())
    if asset_name:
        filters.append(AuditLogEntry.asset_name.ilike(f"%{asset_name}%"))
    if severity:
        filters.append(AuditLogEntry.severity == severity.upper())
    if outcome:
        filters.append(AuditLogEntry.outcome == outcome.upper())
    if event_code:
        filters.append(AuditLogEntry.event_code == event_code.upper())
    if from_ts:
        filters.append(AuditLogEntry.timestamp >= from_ts)
    if to_ts:
        filters.append(AuditLogEntry.timestamp <= to_ts)

    stmt = (
        select(AuditLogEntry)
        .where(and_(*filters) if filters else True)
        .order_by(AuditLogEntry.request_id, AuditLogEntry.sequence)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    entries = result.scalars().all()

    return {
        "count":   len(entries),
        "limit":   limit,
        "offset":  offset,
        "entries": [e.to_dict() for e in entries],
    }


@router.get("/{request_id}", summary="Get all audit events for a single request")
async def get_request_audit_trail(
    request_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Return the complete ordered audit trail for one X-Request-ID.
    This is the primary "trace a single request" view.
    """
    result = await db.execute(
        select(AuditLogEntry)
        .where(AuditLogEntry.request_id == request_id)
        .order_by(AuditLogEntry.sequence)
    )
    entries = result.scalars().all()

    return {
        "request_id": request_id,
        "event_count": len(entries),
        "entries": [e.to_dict() for e in entries],
    }
