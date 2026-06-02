"""
SoI Studio — interactive Statement of Intent generator.

POST /studio/generate   — accepts a physical name, data type, and a business hint,
                          then returns 3 candidate Statements of Intent scored with
                          the TDK clarity formula and a quick jargon check.
                          Results are persisted to soi_studio_sessions.

GET  /studio/history    — returns paginated history of past sessions (JSON).

GET  /studio            — serves the single-page HTML UI (includes history browser).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from metadata_architect.agents.claude_client import CachedBlock, ClaudeClient
from metadata_architect.config import get_settings
from metadata_architect.database import get_db
from metadata_architect.models.soi_studio import SoiStudioSession
from metadata_architect.prompts.soi_drafter import BLOCK_ROLE, build_glossary_block
from metadata_architect.scoring.tdk_calculator import TdkCalculator, TdkInputs

log = logging.getLogger(__name__)
router = APIRouter(prefix="/studio", tags=["soi-studio"])

_calculator = TdkCalculator()

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    physical_name: str = Field(..., min_length=1, max_length=256,
                               description="Physical column or table name, e.g. cust_rev_ytd_usd")
    data_type: str = Field(..., min_length=1, max_length=64,
                           description="SQL / logical data type, e.g. NUMERIC(18,4), VARCHAR(128)")
    business_hint: str = Field("", max_length=500,
                               description="Optional free-text business context from the SME")
    glossary: dict[str, str] = Field(default_factory=dict,
                                     description="Optional glossary terms to whitelist")


class SoIOption(BaseModel):
    index: int                    # 1 | 2 | 3
    label: str                    # "Purpose-led" | "Consumer-led" | "Context-led"
    statement: str
    word_count: int
    reading_level: str
    reading_level_score: float
    tdk_clarity: float            # clarity score only (no ownership — SME hasn't acted yet)
    jargon_compliant: bool
    violations: list[str]
    confidence: float
    drafting_notes: str


class GenerateResponse(BaseModel):
    session_id: str
    physical_name: str
    data_type: str
    options: list[SoIOption]
    model_used: str
    cache_hit: bool


class SaveRequest(BaseModel):
    physical_name: str
    data_type: str
    business_hint: str | None = None
    model_used: str | None = None
    cache_hit: bool = False
    options: list[dict]


class SaveResponse(BaseModel):
    session_id: str


class HistorySession(BaseModel):
    session_id: str
    physical_name: str
    data_type: str
    business_hint: str | None
    model_used: str | None
    cache_hit: bool
    options: list[dict]
    created_at: str


class HistoryResponse(BaseModel):
    total: int
    page: int
    page_size: int
    sessions: list[HistorySession]


# ---------------------------------------------------------------------------
# System prompt (cached)
# ---------------------------------------------------------------------------

_STUDIO_SYSTEM = BLOCK_ROLE + """

## Special Task for This Session
Generate EXACTLY 3 distinct Statements of Intent for the same asset.
Each must answer the same three questions (what / why / who) but from a different angle:

Variant 1 — PURPOSE-LED: Lead with the business purpose. Start with "This [table/column] records/stores/tracks…"
Variant 2 — CONSUMER-LED: Lead with who uses the data. Start with "Finance teams / analysts / operations use this…"
Variant 3 — CONTEXT-LED: Lead with business context and what question the data answers.

All variants MUST obey the ISO 24495-1 Plain Language Rules above.

## Output Contract
Return a JSON array of exactly 3 objects. No prose outside the JSON.

[
  {
    "variant": 1,
    "label": "Purpose-led",
    "statement_of_intent": "<string: 20-100 words>",
    "reading_level": "<e.g. B1 / 9th Grade>",
    "reading_level_score": <float>,
    "confidence": <float 0.0-1.0>,
    "glossary_terms_used": ["<term>"],
    "drafting_notes": "<brief note on assumptions>"
  },
  { "variant": 2, ... },
  { "variant": 3, ... }
]
"""

_STUDIO_USER = """\
Generate 3 Statements of Intent for this asset.

Physical name : {physical_name}
Data type     : {data_type}
Business hint : {hint}

Return the JSON array only.
"""


# ---------------------------------------------------------------------------
# Endpoint: generate
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=GenerateResponse)
async def generate_soi_options(body: GenerateRequest) -> GenerateResponse:
    """
    Calls Claude to produce 3 candidate SoI variants, then scores each
    with the TDK clarity formula and a lightweight jargon check.
    Results are NOT saved automatically — call POST /studio/save to persist.
    """
    settings = get_settings()
    client = ClaudeClient(model=settings.soi_draft_model, max_tokens=2048)

    glossary_block = build_glossary_block(body.glossary or _default_glossary())
    system_blocks = [
        CachedBlock.make(_STUDIO_SYSTEM, cache=True),
        CachedBlock.make(glossary_block, cache=len(glossary_block) > 200),
    ]

    user_msg = _STUDIO_USER.format(
        physical_name=body.physical_name,
        data_type=body.data_type,
        hint=body.business_hint or "(none provided)",
    )

    try:
        response = client.call(system_blocks, user_msg)
    except Exception as exc:
        log.exception("soi_studio.generate_failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Claude API error: {exc}",
        )

    try:
        raw = response.parse_json()
        if not isinstance(raw, list):
            raise ValueError("Expected JSON array")
        variants = raw[:3]
    except Exception as exc:
        log.error("soi_studio.parse_failed content=%s", response.content[:300])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to parse Claude response as 3-variant JSON array.",
        )

    _labels = {1: "Purpose-led", 2: "Consumer-led", 3: "Context-led"}
    options: list[SoIOption] = []

    for i, v in enumerate(variants, start=1):
        soi_text = v.get("statement_of_intent", "")
        rl_score = float(v.get("reading_level_score", 10.0))
        terms_used = len(v.get("glossary_terms_used", []))
        word_count = len(soi_text.split())

        # Quick jargon scan (local heuristic — no extra Claude call in UI mode)
        violations, jargon_ok = _quick_jargon_check(soi_text, body.glossary or _default_glossary())

        tdk_inputs = TdkInputs(
            reading_level_score=rl_score,
            jargon_violation_count=len(violations),
            statement_of_intent=soi_text,
            glossary_terms_used=terms_used,
            total_columns=max(1, len(body.physical_name.split("_"))),
            context_authority_assigned=True,   # SME is present in this session
            sla_met=True,
            sme_approved=False,                # not yet actioned
        )
        breakdown = _calculator.compute(tdk_inputs)

        options.append(SoIOption(
            index=i,
            label=v.get("label", _labels.get(i, f"Option {i}")),
            statement=soi_text,
            word_count=word_count,
            reading_level=v.get("reading_level", "Unknown"),
            reading_level_score=rl_score,
            tdk_clarity=breakdown.clarity_score,
            jargon_compliant=jargon_ok,
            violations=violations,
            confidence=float(v.get("confidence", 0.5)),
            drafting_notes=v.get("drafting_notes", ""),
        ))

    return GenerateResponse(
        session_id="",  # not yet saved — call POST /studio/save to persist
        physical_name=body.physical_name,
        data_type=body.data_type,
        options=options,
        model_used=response.model,
        cache_hit=response.cache_hit,
    )


# ---------------------------------------------------------------------------
# Endpoint: save session
# ---------------------------------------------------------------------------

@router.post("/save", response_model=SaveResponse, status_code=201)
async def save_session(
    body: SaveRequest,
    db: AsyncSession = Depends(get_db),
) -> SaveResponse:
    """Persist a generated session to history. Called explicitly by the SME."""
    session_id = uuid.uuid4()
    record = SoiStudioSession(
        id=session_id,
        physical_name=body.physical_name,
        data_type=body.data_type,
        business_hint=body.business_hint or None,
        model_used=body.model_used,
        cache_hit=body.cache_hit,
        options=body.options,
    )
    try:
        db.add(record)
        await db.commit()
    except Exception as exc:
        log.warning("soi_studio.save_session_failed reason=%s", exc)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save session to history.",
        )
    return SaveResponse(session_id=str(session_id))


# ---------------------------------------------------------------------------
# Endpoint: history
# ---------------------------------------------------------------------------

@router.get("/history", response_model=HistoryResponse)
async def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query("", description="Filter by physical name (partial match)"),
    db: AsyncSession = Depends(get_db),
) -> HistoryResponse:
    """Return paginated history of past SoI Studio sessions, newest first."""
    base_q = select(SoiStudioSession)
    count_q = select(func.count()).select_from(SoiStudioSession)

    if search:
        like = f"%{search}%"
        base_q = base_q.where(SoiStudioSession.physical_name.ilike(like))
        count_q = count_q.where(SoiStudioSession.physical_name.ilike(like))

    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    rows_result = await db.execute(
        base_q.order_by(SoiStudioSession.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = rows_result.scalars().all()

    sessions = [
        HistorySession(
            session_id=str(r.id),
            physical_name=r.physical_name,
            data_type=r.data_type,
            business_hint=r.business_hint,
            model_used=r.model_used,
            cache_hit=r.cache_hit,
            options=r.options,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]

    return HistoryResponse(total=total, page=page, page_size=page_size, sessions=sessions)


# ---------------------------------------------------------------------------
# Endpoint: serve UI
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def studio_ui() -> HTMLResponse:
    return HTMLResponse(_UI_HTML)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JARGON_TERMS = {
    "DDL", "ETL", "CDC", "ODS", "SCD", "ELT", "DAG", "DWH", "OLAP", "OLTP",
    "PK", "FK", "UUID", "JSON", "JSONB", "VARCHAR", "NUMERIC", "BIGINT",
    "TIMESTAMPTZ", "BOOLEAN", "SERIAL",
}


def _quick_jargon_check(text: str, glossary: dict[str, str]) -> tuple[list[str], bool]:
    """Return (list_of_violations, is_compliant)."""
    approved = {k.upper() for k in glossary}
    words = text.upper().split()
    found = []
    for term in _JARGON_TERMS:
        if term in words and term not in approved:
            found.append(term)
    return found, len(found) == 0


def _default_glossary() -> dict[str, str]:
    return {
        "KPI": "Key Performance Indicator",
        "SLA": "Service Level Agreement",
        "TDK": "Trusted Data KPI",
        "SME": "Subject Matter Expert",
        "SoI": "Statement of Intent",
        "revenue": "Money earned from business activities before expenses are subtracted.",
        "aggregate": "A summary value calculated from multiple records.",
        "audit": "A formal review of records to verify accuracy and compliance.",
        "currency": "The type of money in a transaction, identified by an ISO 4217 code.",
        "region": "A geographic area used to group business data.",
    }


# ---------------------------------------------------------------------------
# Inline HTML UI  (generator + history browser)
# ---------------------------------------------------------------------------

_UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SoI Studio — Metadata Architect</title>
<style>
:root {
  --bg: #0b0d16;
  --surface: #13162b;
  --surface2: #1c2040;
  --surface3: #242850;
  --border: #2a2f5e;
  --accent: #7c6af7;
  --accent2: #56c2e6;
  --accent3: #a78bfa;
  --text: #e4e6f4;
  --muted: #7880a8;
  --green: #34d399;
  --yellow: #fbbf24;
  --red: #f87171;
  --glow: rgba(124,106,247,0.18);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 14px;
  line-height: 1.6;
  min-height: 100vh;
}

/* ── Header ── */
header {
  background: linear-gradient(135deg, #0f1228 0%, #1a1040 100%);
  border-bottom: 1px solid var(--border);
  padding: 0 32px;
  height: 60px;
  display: flex;
  align-items: center;
  gap: 14px;
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(12px);
}
.logo-icon {
  width: 34px; height: 34px;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px;
  box-shadow: 0 0 16px var(--glow);
  flex-shrink: 0;
}
header h1 { font-size: 16px; font-weight: 700; color: var(--text); }
header span { font-size: 12px; color: var(--muted); }
.header-badge {
  margin-left: auto;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 3px 12px;
  font-size: 11px;
  color: var(--accent2);
}

/* ── Layout ── */
.workspace {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 0;
  min-height: calc(100vh - 60px);
}

/* ── Left panel ── */
.left-panel {
  background: var(--surface);
  border-right: 1px solid var(--border);
  padding: 28px 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow-y: auto;
}
.panel-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--muted);
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.field { display: flex; flex-direction: column; gap: 6px; }
label {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 6px;
}
.label-tag {
  font-size: 10px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 5px;
  color: var(--accent2);
}
input, textarea, select {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  padding: 10px 14px;
  transition: border-color 0.2s, box-shadow 0.2s;
  outline: none;
  width: 100%;
}
input:focus, textarea:focus, select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--glow);
}
textarea { resize: vertical; min-height: 90px; line-height: 1.6; }
input::placeholder, textarea::placeholder { color: var(--muted); opacity: 0.6; }

.hint-text { font-size: 11px; color: var(--muted); margin-top: -2px; }

.data-type-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.dt-chip {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 7px 10px;
  font-size: 12px;
  color: var(--muted);
  cursor: pointer;
  text-align: center;
  transition: all 0.15s;
}
.dt-chip:hover { border-color: var(--accent); color: var(--accent); }
.dt-chip.active { border-color: var(--accent); background: rgba(124,106,247,0.12); color: var(--accent3); }

/* Generate button */
.btn-generate {
  background: linear-gradient(135deg, var(--accent) 0%, #5b4de8 100%);
  border: none;
  border-radius: 10px;
  color: white;
  font-size: 14px;
  font-weight: 600;
  padding: 13px 20px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: opacity 0.2s, transform 0.1s;
  box-shadow: 0 4px 20px var(--glow);
  width: 100%;
}
.btn-generate:hover { opacity: 0.92; }
.btn-generate:active { transform: scale(0.98); }
.btn-generate:disabled { opacity: 0.5; cursor: not-allowed; }

.spinner {
  width: 16px; height: 16px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  display: none;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Framework info */
.framework-box {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
}
.framework-box h4 { font-size: 11px; color: var(--accent2); margin-bottom: 8px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; }
.rule-list { list-style: none; display: flex; flex-direction: column; gap: 4px; }
.rule-list li { font-size: 11px; color: var(--muted); display: flex; gap: 6px; }
.rule-list li::before { content: "▸"; color: var(--accent); flex-shrink: 0; }

/* ── Right panel ── */
.right-panel {
  padding: 28px 32px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.right-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.right-panel-header h2 { font-size: 16px; font-weight: 600; color: var(--text); }
.result-meta { font-size: 11px; color: var(--muted); }

/* Empty state */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  color: var(--muted);
  text-align: center;
  padding: 60px 40px;
}
.empty-icon { font-size: 48px; opacity: 0.4; }
.empty-state h3 { font-size: 16px; color: var(--muted); font-weight: 500; }
.empty-state p { font-size: 13px; max-width: 320px; line-height: 1.6; }

/* SoI Card */
.soi-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  transition: border-color 0.2s;
}
.soi-card:hover { border-color: var(--accent); }
.soi-card.selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--glow);
}

.card-header {
  background: var(--surface2);
  padding: 12px 18px;
  display: flex;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid var(--border);
}
.option-badge {
  width: 26px; height: 26px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}
.badge-1 { background: rgba(124,106,247,0.2); color: var(--accent3); border: 1px solid var(--accent); }
.badge-2 { background: rgba(86,194,230,0.15); color: var(--accent2); border: 1px solid var(--accent2); }
.badge-3 { background: rgba(52,211,153,0.15); color: var(--green); border: 1px solid var(--green); }

.card-label { font-size: 13px; font-weight: 600; color: var(--text); }
.card-actions { margin-left: auto; display: flex; gap: 6px; }

.btn-sm {
  background: var(--surface3);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--muted);
  font-size: 11px;
  padding: 4px 10px;
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}
.btn-sm:hover { border-color: var(--accent2); color: var(--accent2); }
.btn-sm.btn-use {
  background: rgba(124,106,247,0.15);
  border-color: var(--accent);
  color: var(--accent3);
  font-weight: 600;
}
.btn-sm.btn-use:hover { background: rgba(124,106,247,0.25); }
.btn-sm.copied { border-color: var(--green); color: var(--green); }

.card-body { padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; }

.soi-text {
  font-size: 14px;
  line-height: 1.75;
  color: var(--text);
  background: var(--surface2);
  border-radius: 8px;
  padding: 14px 16px;
  border-left: 3px solid var(--accent);
}
.soi-text.editable { outline: none; cursor: text; }
.soi-text.editable:focus {
  border-left-color: var(--accent2);
  box-shadow: 0 0 0 2px var(--glow);
}

/* Metrics row */
.metrics-row { display: flex; gap: 10px; flex-wrap: wrap; }
.metric-chip {
  display: flex;
  align-items: center;
  gap: 5px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--muted);
}
.metric-chip .val { font-weight: 700; font-family: monospace; }
.val-good { color: var(--green); }
.val-warn { color: var(--yellow); }
.val-bad { color: var(--red); }

/* TDK bar */
.tdk-bar-wrap { display: flex; flex-direction: column; gap: 5px; }
.tdk-bar-label { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); }
.tdk-bar-track {
  height: 6px;
  background: var(--surface3);
  border-radius: 3px;
  overflow: hidden;
}
.tdk-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.6s cubic-bezier(0.4,0,0.2,1);
}

/* Jargon violations */
.violations { display: flex; gap: 5px; flex-wrap: wrap; }
.violation-tag {
  background: rgba(248,113,113,0.12);
  border: 1px solid rgba(248,113,113,0.3);
  color: var(--red);
  border-radius: 4px;
  padding: 2px 7px;
  font-size: 11px;
  font-family: monospace;
}
.compliant-badge {
  background: rgba(52,211,153,0.1);
  border: 1px solid rgba(52,211,153,0.3);
  color: var(--green);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
}

/* Drafting notes */
.drafting-notes {
  font-size: 12px;
  color: var(--muted);
  font-style: italic;
  display: flex;
  gap: 6px;
  align-items: flex-start;
}
.drafting-notes::before { content: "💡"; font-style: normal; flex-shrink: 0; }

/* Error banner */
.error-banner {
  background: rgba(248,113,113,0.1);
  border: 1px solid rgba(248,113,113,0.3);
  border-radius: 8px;
  padding: 14px 18px;
  color: var(--red);
  font-size: 13px;
  display: none;
}

/* Toast */
.toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 18px;
  font-size: 13px;
  color: var(--text);
  opacity: 0;
  transform: translateY(8px);
  transition: all 0.25s;
  pointer-events: none;
  z-index: 1000;
}
.toast.show { opacity: 1; transform: translateY(0); }

/* Confidence ring */
.conf-ring {
  width: 36px; height: 36px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px;
  font-weight: 700;
  border: 2px solid;
  flex-shrink: 0;
}

/* Model info */
.model-info {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: var(--muted);
}
.model-info span { display: flex; align-items: center; gap: 5px; }
.cache-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--green);
}

/* ── Tabs ── */
.tab-bar {
  display: flex;
  gap: 2px;
  padding: 0 32px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
.tab-btn {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--muted);
  cursor: pointer;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  padding: 12px 18px;
  transition: color 0.15s, border-color 0.15s;
}
.tab-btn:hover { color: var(--text); }
.tab-btn.active { color: var(--accent3); border-bottom-color: var(--accent); }

/* ── History panel ── */
.history-panel {
  padding: 28px 32px;
  display: none;
  flex-direction: column;
  gap: 16px;
}
.history-panel.visible { display: flex; }

.history-toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
}
.history-toolbar input {
  max-width: 280px;
}
.history-count { font-size: 12px; color: var(--muted); margin-left: auto; }

/* History table */
.hist-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.hist-table th {
  background: var(--surface2);
  border-bottom: 1px solid var(--border);
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 9px 14px;
  text-align: left;
  text-transform: uppercase;
}
.hist-table td {
  border-bottom: 1px solid var(--border);
  padding: 10px 14px;
  vertical-align: top;
}
.hist-table tr:hover td { background: var(--surface2); cursor: pointer; }
.hist-table tr.expanded td { background: var(--surface2); }

.hist-name { color: var(--accent2); font-family: monospace; font-size: 12px; }
.hist-type { background: var(--surface3); border-radius: 4px; color: var(--muted); font-size: 11px; padding: 2px 7px; white-space: nowrap; }
.hist-date { color: var(--muted); font-size: 11px; white-space: nowrap; }
.hist-tdk { font-family: monospace; font-size: 12px; }

/* Expanded session detail */
.hist-detail {
  display: none;
}
.hist-detail.open {
  display: table-row;
}
.hist-detail td {
  padding: 0 !important;
  border-bottom: 1px solid var(--border);
}
.detail-inner {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.detail-hint {
  font-size: 12px;
  color: var(--muted);
  font-style: italic;
  padding: 6px 10px;
  background: var(--surface3);
  border-radius: 6px;
}
.detail-option {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 6px;
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.6;
}
.detail-option-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.detail-label { font-size: 11px; font-weight: 700; color: var(--accent3); text-transform: uppercase; }
.detail-tdk { font-size: 11px; color: var(--muted); margin-left: auto; }

/* Pagination */
.pagination {
  display: flex;
  gap: 6px;
  align-items: center;
  justify-content: center;
  margin-top: 4px;
}
.page-btn {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--muted);
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
  padding: 5px 12px;
  transition: all 0.15s;
}
.page-btn:hover { border-color: var(--accent); color: var(--accent); }
.page-btn.active { background: rgba(124,106,247,0.15); border-color: var(--accent); color: var(--accent3); font-weight: 700; }
.page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.page-info { font-size: 12px; color: var(--muted); }

.hist-empty {
  text-align: center;
  padding: 60px 20px;
  color: var(--muted);
  font-size: 13px;
}

/* Save to History button */
.btn-save-history {
  background: linear-gradient(135deg, #1a3a2a 0%, #1e4a35 100%);
  border: 1px solid var(--green);
  border-radius: 8px;
  color: var(--green);
  cursor: pointer;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  padding: 9px 20px;
  transition: all 0.2s;
}
.btn-save-history:hover { background: rgba(52,211,153,0.15); box-shadow: 0 0 12px rgba(52,211,153,0.2); }
.btn-save-history:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-save-history.saved { border-color: var(--muted); color: var(--muted); background: var(--surface2); }

@media (max-width: 860px) {
  .workspace { grid-template-columns: 1fr; }
  .left-panel { border-right: none; border-bottom: 1px solid var(--border); }
}
</style>
</head>
<body>

<header>
  <div class="logo-icon">🏛</div>
  <div>
    <h1>SoI Studio</h1>
    <span>Statement of Intent Generator</span>
  </div>
  <div class="header-badge">Metadata Architect · Speed of Trust Framework</div>
</header>

<div class="tab-bar">
  <button class="tab-btn active" onclick="switchTab('generate', this)">Generate</button>
  <button class="tab-btn" onclick="switchTab('history', this)">History</button>
</div>

<div class="workspace" id="tabGenerate">

  <!-- LEFT: Input panel -->
  <div class="left-panel">
    <div class="panel-title">Asset Input</div>

    <div class="field">
      <label>Physical Name <span class="label-tag">required</span></label>
      <input id="physicalName" type="text"
             placeholder="e.g. cust_rev_ytd_usd, global_revenue_agg_v1"
             autocomplete="off" spellcheck="false">
      <span class="hint-text">Column or table name as it appears in the database</span>
    </div>

    <div class="field">
      <label>Data Type <span class="label-tag">required</span></label>
      <input id="dataType" type="text"
             placeholder="e.g. NUMERIC(18,4), VARCHAR(128), DATE"
             autocomplete="off" spellcheck="false">
      <div class="data-type-grid" style="margin-top:6px">
        <div class="dt-chip" onclick="setType('NUMERIC(18,4)')">NUMERIC</div>
        <div class="dt-chip" onclick="setType('VARCHAR(256)')">VARCHAR</div>
        <div class="dt-chip" onclick="setType('TIMESTAMPTZ')">TIMESTAMP</div>
        <div class="dt-chip" onclick="setType('BOOLEAN')">BOOLEAN</div>
        <div class="dt-chip" onclick="setType('INTEGER')">INTEGER</div>
        <div class="dt-chip" onclick="setType('DATE')">DATE</div>
      </div>
    </div>

    <div class="field">
      <label>Business Context Hint <span class="label-tag">optional</span></label>
      <textarea id="businessHint"
                placeholder="Describe what this data means in business terms. Who uses it? What decision does it support? Any domain context helps…"></textarea>
      <span class="hint-text">The more context you provide, the more accurate the generated descriptions</span>
    </div>

    <button class="btn-generate" id="generateBtn" onclick="generate()">
      <div class="spinner" id="spinner"></div>
      <span id="btnText">✦ Generate 3 Descriptions</span>
    </button>

    <div class="error-banner" id="errorBanner"></div>

    <div class="framework-box">
      <h4>ISO 24495-1 Rules Applied</h4>
      <ul class="rule-list">
        <li>≤ 25 words per sentence</li>
        <li>CEFR B1 / 9th Grade reading level</li>
        <li>Active voice only</li>
        <li>No undefined acronyms or jargon</li>
        <li>Present tense throughout</li>
        <li>20–100 word target length</li>
      </ul>
    </div>

    <div class="framework-box">
      <h4>TDK Clarity Score</h4>
      <ul class="rule-list">
        <li>30% Reading level (FK ≤ 9.0)</li>
        <li>30% No jargon violations</li>
        <li>20% SoI length (20–100 words)</li>
        <li>20% Glossary term coverage</li>
      </ul>
    </div>
  </div>

  <!-- RIGHT: Results panel -->
  <div class="right-panel" id="rightPanel">
    <div class="empty-state" id="emptyState">
      <div class="empty-icon">📝</div>
      <h3>Ready to generate</h3>
      <p>Enter a physical name and data type on the left, add any business context, then click Generate.</p>
      <p style="margin-top:8px; font-size:11px; color:var(--muted)">
        The agent will produce 3 ISO 24495-1 compliant descriptions:<br>
        Purpose-led · Consumer-led · Context-led
      </p>
    </div>
    <div id="resultsArea" style="display:none; display:flex; flex-direction:column; gap:20px;"></div>
  </div>

</div>

<!-- History tab -->
<div class="history-panel" id="tabHistory">
  <div class="history-toolbar">
    <input type="text" id="histSearch" placeholder="Search by physical name…"
           oninput="debounceSearch()" autocomplete="off" spellcheck="false">
    <button class="page-btn" onclick="loadHistory(1)">Refresh</button>
    <span class="history-count" id="histCount"></span>
  </div>
  <div id="histTableWrap"></div>
  <div class="pagination" id="histPagination"></div>
</div>

<div class="toast" id="toast"></div>

<script>
const API = '/studio/generate';
const SAVE_API = '/studio/save';
const HISTORY_API = '/studio/history';

let _lastGenerated = null;  // holds the last GenerateResponse for manual save

let _histPage = 1;
let _histSearch = '';
let _searchTimer = null;

// ── Save to History ──
async function saveToHistory() {
  if (!_lastGenerated) return;
  const btn = document.getElementById('saveHistoryBtn');
  btn.disabled = true;
  btn.textContent = 'Saving…';
  try {
    const resp = await fetch(SAVE_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        physical_name: _lastGenerated.physical_name,
        data_type: _lastGenerated.data_type,
        business_hint: document.getElementById('businessHint').value.trim() || null,
        model_used: _lastGenerated.model_used,
        cache_hit: _lastGenerated.cache_hit,
        options: _lastGenerated.options,
      }),
    });
    if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || resp.statusText);
    btn.textContent = '✓ Saved to History';
    btn.classList.add('saved');
    showToast('Session saved to History');
  } catch (e) {
    btn.disabled = false;
    btn.textContent = '💾 Save to History';
    showToast(`Save failed: ${e.message}`);
  }
}

// ── Tab switching ──
function switchTab(tab, btn) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tabGenerate').style.display = tab === 'generate' ? 'grid' : 'none';
  const hp = document.getElementById('tabHistory');
  if (tab === 'history') {
    hp.classList.add('visible');
    loadHistory(1);
  } else {
    hp.classList.remove('visible');
  }
}

// ── History ──
function debounceSearch() {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(() => {
    _histSearch = document.getElementById('histSearch').value.trim();
    loadHistory(1);
  }, 350);
}

async function loadHistory(page) {
  _histPage = page;
  const params = new URLSearchParams({ page, page_size: 15 });
  if (_histSearch) params.set('search', _histSearch);

  const wrap = document.getElementById('histTableWrap');
  wrap.innerHTML = '<div class="hist-empty">Loading…</div>';

  try {
    const resp = await fetch(`${HISTORY_API}?${params}`);
    if (!resp.ok) throw new Error(resp.statusText);
    const data = await resp.json();
    renderHistory(data);
  } catch (e) {
    wrap.innerHTML = `<div class="hist-empty" style="color:var(--red)">Error: ${e.message}</div>`;
  }
}

function tdkColor(v) {
  if (v >= 0.75) return 'var(--green)';
  if (v >= 0.5)  return 'var(--yellow)';
  return 'var(--red)';
}

function renderHistory(data) {
  document.getElementById('histCount').textContent =
    `${data.total} session${data.total !== 1 ? 's' : ''}`;

  const wrap = document.getElementById('histTableWrap');
  if (!data.sessions.length) {
    wrap.innerHTML = '<div class="hist-empty">No sessions found. Generate some descriptions first!</div>';
    document.getElementById('histPagination').innerHTML = '';
    return;
  }

  const rows = data.sessions.map((s, idx) => {
    const bestTdk = Math.max(...s.options.map(o => o.tdk_clarity));
    const dt = new Date(s.created_at);
    const dateStr = dt.toLocaleDateString() + ' ' + dt.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
    const rowId = `hrow-${idx}`;
    const detailId = `hdetail-${idx}`;

    const optRows = s.options.map(o => `
      <div class="detail-option">
        <div class="detail-option-header">
          <span class="detail-label">${o.label}</span>
          <span class="detail-tdk" style="color:${tdkColor(o.tdk_clarity)}">
            TDK ${(o.tdk_clarity*100).toFixed(0)}/100 · ${o.word_count}w · ${o.reading_level}
          </span>
          <button class="btn-sm" style="margin-left:8px"
            onclick="navigator.clipboard.writeText(${JSON.stringify(o.statement)});showToast('Copied!')">Copy</button>
        </div>
        ${o.statement}
      </div>`).join('');

    const hintHtml = s.business_hint
      ? `<div class="detail-hint">Hint: ${s.business_hint}</div>` : '';

    return `
      <tr id="${rowId}" onclick="toggleDetail('${detailId}', '${rowId}')">
        <td><span class="hist-name">${s.physical_name}</span></td>
        <td><span class="hist-type">${s.data_type}</span></td>
        <td class="hist-tdk" style="color:${tdkColor(bestTdk)}">${(bestTdk*100).toFixed(0)}</td>
        <td class="hist-date">${dateStr}</td>
      </tr>
      <tr class="hist-detail" id="${detailId}">
        <td colspan="4">
          <div class="detail-inner">
            ${hintHtml}
            ${optRows}
          </div>
        </td>
      </tr>`;
  }).join('');

  wrap.innerHTML = `
    <table class="hist-table">
      <thead>
        <tr>
          <th>Physical Name</th>
          <th>Data Type</th>
          <th>Best TDK</th>
          <th>Generated</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;

  // Pagination
  const totalPages = Math.ceil(data.total / data.page_size);
  const pg = document.getElementById('histPagination');
  if (totalPages <= 1) { pg.innerHTML = ''; return; }

  let btns = `<button class="page-btn" onclick="loadHistory(${data.page-1})"
    ${data.page <= 1 ? 'disabled' : ''}>← Prev</button>`;
  const start = Math.max(1, data.page - 2);
  const end = Math.min(totalPages, data.page + 2);
  for (let p = start; p <= end; p++) {
    btns += `<button class="page-btn ${p === data.page ? 'active' : ''}"
      onclick="loadHistory(${p})">${p}</button>`;
  }
  btns += `<button class="page-btn" onclick="loadHistory(${data.page+1})"
    ${data.page >= totalPages ? 'disabled' : ''}>Next →</button>`;
  btns += `<span class="page-info">Page ${data.page} of ${totalPages}</span>`;
  pg.innerHTML = btns;
}

function toggleDetail(detailId, rowId) {
  const detail = document.getElementById(detailId);
  const row = document.getElementById(rowId);
  const isOpen = detail.classList.contains('open');
  // Close all others
  document.querySelectorAll('.hist-detail.open').forEach(d => d.classList.remove('open'));
  document.querySelectorAll('.hist-table tr.expanded').forEach(r => r.classList.remove('expanded'));
  if (!isOpen) {
    detail.classList.add('open');
    row.classList.add('expanded');
  }
}

function setType(t) {
  document.getElementById('dataType').value = t;
  document.querySelectorAll('.dt-chip').forEach(c => {
    c.classList.toggle('active', c.textContent.trim() === t.split('(')[0]);
  });
}

function showToast(msg, duration = 2000) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), duration);
}

function scoreColor(v) {
  if (v >= 0.75) return 'var(--green)';
  if (v >= 0.5)  return 'var(--yellow)';
  return 'var(--red)';
}

function scoreClass(v) {
  if (v >= 0.75) return 'val-good';
  if (v >= 0.5)  return 'val-warn';
  return 'val-bad';
}

function rlClass(v) {
  if (v <= 8.5) return 'val-good';
  if (v <= 10.5) return 'val-warn';
  return 'val-bad';
}

function copyText(id, btn) {
  const el = document.getElementById(id);
  navigator.clipboard.writeText(el.textContent.trim()).then(() => {
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 1800);
  });
}

function useOption(id) {
  const el = document.getElementById(id);
  const text = el.textContent.trim();
  navigator.clipboard.writeText(text);
  document.querySelectorAll('.soi-card').forEach(c => c.classList.remove('selected'));
  el.closest('.soi-card').classList.add('selected');
  showToast('Description copied to clipboard and marked as selected');
}

function renderCard(opt, index) {
  const id = `soi-text-${index}`;
  const tdk = opt.tdk_clarity;
  const rl = opt.reading_level_score;
  const conf = Math.round(opt.confidence * 100);
  const wc = opt.word_count;
  const wcClass = (wc >= 20 && wc <= 100) ? 'val-good' : 'val-warn';
  const confColor = conf >= 75 ? 'var(--green)' : conf >= 50 ? 'var(--yellow)' : 'var(--red)';
  const badgeClass = ['', 'badge-1', 'badge-2', 'badge-3'][index];

  const violHtml = opt.violations.length
    ? opt.violations.map(v => `<span class="violation-tag">${v}</span>`).join('')
    : '<span class="compliant-badge">✓ ISO compliant</span>';

  const notesHtml = opt.drafting_notes
    ? `<div class="drafting-notes">${opt.drafting_notes}</div>`
    : '';

  return `
<div class="soi-card" id="card-${index}">
  <div class="card-header">
    <div class="option-badge ${badgeClass}">${index}</div>
    <div class="card-label">${opt.label}</div>
    <div class="conf-ring" style="border-color:${confColor};color:${confColor}" title="AI confidence">
      ${conf}%
    </div>
    <div class="card-actions">
      <button class="btn-sm" onclick="copyText('${id}', this)">Copy</button>
      <button class="btn-sm btn-use" onclick="useOption('${id}')">Use this ↗</button>
    </div>
  </div>
  <div class="card-body">
    <div class="soi-text" id="${id}" contenteditable="true" spellcheck="true"
         title="Click to edit">${opt.statement}</div>

    <div class="tdk-bar-wrap">
      <div class="tdk-bar-label">
        <span>TDK Clarity Score</span>
        <span class="${scoreClass(tdk)}" style="font-weight:700">${(tdk*100).toFixed(0)}/100</span>
      </div>
      <div class="tdk-bar-track">
        <div class="tdk-bar-fill"
             style="width:${tdk*100}%;background:${scoreColor(tdk)}"></div>
      </div>
    </div>

    <div class="metrics-row">
      <div class="metric-chip">
        <span>Words:</span>
        <span class="val ${wcClass}">${wc}</span>
      </div>
      <div class="metric-chip">
        <span>Grade:</span>
        <span class="val ${rlClass(rl)}">${rl.toFixed(1)}</span>
      </div>
      <div class="metric-chip">
        <span>Level:</span>
        <span class="val" style="color:var(--accent2)">${opt.reading_level}</span>
      </div>
    </div>

    <div class="violations">${violHtml}</div>
    ${notesHtml}
  </div>
</div>`;
}

async function generate() {
  const physical = document.getElementById('physicalName').value.trim();
  const dtype = document.getElementById('dataType').value.trim();
  const hint = document.getElementById('businessHint').value.trim();

  if (!physical) {
    document.getElementById('physicalName').focus();
    showToast('Please enter a physical name');
    return;
  }
  if (!dtype) {
    document.getElementById('dataType').focus();
    showToast('Please enter a data type');
    return;
  }

  const btn = document.getElementById('generateBtn');
  const spinner = document.getElementById('spinner');
  const btnText = document.getElementById('btnText');
  const errBanner = document.getElementById('errorBanner');
  const emptyState = document.getElementById('emptyState');
  const resultsArea = document.getElementById('resultsArea');

  _lastGenerated = null;
  btn.disabled = true;
  spinner.style.display = 'block';
  btnText.textContent = 'Generating…';
  errBanner.style.display = 'none';
  emptyState.style.display = 'none';
  resultsArea.style.display = 'flex';
  resultsArea.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px">
      ${[1,2,3].map(() => `
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;
                    height:180px;display:flex;align-items:center;justify-content:center;
                    color:var(--muted);font-size:13px">
          <div style="display:flex;gap:10px;align-items:center">
            <div style="width:20px;height:20px;border:2px solid var(--accent);border-top-color:transparent;
                        border-radius:50%;animation:spin 0.7s linear infinite"></div>
            Drafting variant…
          </div>
        </div>`).join('')}
    </div>`;

  try {
    const resp = await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        physical_name: physical,
        data_type: dtype,
        business_hint: hint,
      }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }

    const data = await resp.json();
    _lastGenerated = data;  // store for manual save
    const cacheLabel = data.cache_hit ? '⚡ Cache hit' : '🔮 Fresh generation';

    resultsArea.innerHTML = `
      <div class="right-panel-header">
        <h2>Generated Descriptions for <code style="color:var(--accent2);font-size:13px">${physical}</code></h2>
        <span class="result-meta">${cacheLabel} · ${data.model_used}</span>
      </div>
      <div class="model-info">
        <span>${data.cache_hit ? '<div class="cache-dot"></div>' : ''}
          Model: <strong style="color:var(--text)">${data.model_used}</strong></span>
        <span>Data type: <strong style="color:var(--accent2)">${data.data_type}</strong></span>
        <span style="margin-left:auto;color:var(--muted)">Click any description to edit · Use this ↗ to select</span>
      </div>
      ${data.options.map((opt, i) => renderCard(opt, i + 1)).join('')}
      <div style="display:flex;justify-content:flex-end;padding-top:4px">
        <button class="btn-save-history" id="saveHistoryBtn" onclick="saveToHistory()">
          💾 Save to History
        </button>
      </div>
    `;
  } catch (e) {
    errBanner.style.display = 'block';
    errBanner.textContent = `Error: ${e.message}`;
    resultsArea.innerHTML = '';
    emptyState.style.display = 'flex';
  } finally {
    btn.disabled = false;
    spinner.style.display = 'none';
    btnText.textContent = '✦ Generate 3 Descriptions';
  }
}

// Enter key on inputs triggers generate
['physicalName','dataType'].forEach(id => {
  document.getElementById(id).addEventListener('keydown', e => {
    if (e.key === 'Enter') generate();
  });
});
</script>
</body>
</html>
"""
