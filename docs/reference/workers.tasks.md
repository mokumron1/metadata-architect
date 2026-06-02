# `metadata_architect.workers.tasks`

**Package:** `metadata_architect`  
**Module:** `workers.tasks`  
**Source:** `src/metadata_architect/workers/tasks.py`  
**Generated:** 2026-06-02  

> Celery tasks: draft pipeline, SLA monitor, orphan notice, edit analysis.

## Overview

Celery tasks for the Metadata Architect pipeline.

draft_asset_metadata         — end-to-end pipeline: parse → draft → scrub → score → persist
run_sla_monitor              — Celery Beat job: scans for SLA breaches, orphans assets
dispatch_orphan_notice       — sends Orphan Notice notifications
analyse_sme_edit             — offline edit categorisation for training data (Phase 6)

## Functions

```
@celery_app.task(name='metadata_architect.workers.tasks.draft_asset_metadata', bind=True, max_retries=3, default_retry_delay=60)
```
```python
def draft_asset_metadata(asset_id: str) → dict
```

Full drafting pipeline for a single asset.

Steps:
  1. Load asset from DB (sync session via asyncio.run)
  2. Parse DDL → ParsedSchema
  3. Draft SoI (SoIDrafter — may escalate to Opus)
  4. Scrub for jargon violations (JargonScrubber)
  5. Validate reading level (ReadingLevelValidator)
  6. Compute initial TDK score (TdkCalculator)
  7. Persist SoIDraft + TdkScoreLog records
  8. Update SmeWorkflow with real draft_id + SLA deadline
  9. Return summary dict

**Parameters:**

- **`asset_id`** `str`

**Returns:** `dict`

```
@celery_app.task(name='metadata_architect.workers.tasks.run_sla_monitor')
```
```python
def run_sla_monitor() → dict
```

Scans for SmeWorkflow records where:
  status = AWAITING_SME_AUDIT AND sla_deadline_at < now()

For each breach: transitions to ORPHANED, applies TDK penalty,
enqueues an orphan notice.

**Returns:** `dict`

```
@celery_app.task(name='metadata_architect.workers.tasks.dispatch_orphan_notice', max_retries=3, default_retry_delay=30)
```
```python
def dispatch_orphan_notice(asset_id: str) → dict
```

Sends an Orphan Notice to the Context Authority for the given asset.

**Parameters:**

- **`asset_id`** `str`

**Returns:** `dict`

```
@celery_app.task(name='metadata_architect.workers.tasks.analyse_sme_edit', queue='analysis', max_retries=2, default_retry_delay=120)
```
```python
def analyse_sme_edit(asset_id: str, draft_id: str, edit_diff: str) → dict
```

Categorise an SME edit diff using Claude and store it in MinIO as a
labelled training record.

Categories (from prompt):
  FACTUAL_CORRECTION   — SME fixed an incorrect fact
  CLARITY_IMPROVEMENT  — SME improved readability without changing facts
  SCOPE_EXPANSION      — SME added context that was missing
  SCOPE_REDUCTION      — SME removed content that was out of scope
  TONE_ADJUSTMENT      — SME changed formality or style only
  JARGON_REPLACEMENT   — SME replaced undefined technical term

The record is written to MinIO bucket: sme-edits/
Key: edits/{asset_id}/{draft_id}/edit_analysis.json

**Parameters:**

- **`asset_id`** `str`
- **`draft_id`** `str`
- **`edit_diff`** `str`

**Returns:** `dict`
