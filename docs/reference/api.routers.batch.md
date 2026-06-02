# `metadata_architect.api.routers.batch`

**Package:** `metadata_architect`  
**Module:** `api.routers.batch`  
**Source:** `src/metadata_architect/api/routers/batch.py`  
**Generated:** 2026-06-02  

> Batch ingestion endpoint — register up to 200 assets in one request.

## Overview

Batch ingestion router.

POST /batch/ingest   — Accept multiple DDL statements in one request,
                       register each as an Asset, and enqueue drafting tasks.

Designed for backfill scenarios where an entire Postgres schema (50–500 tables)
needs to be registered in one call without overwhelming the Celery queue.

## Constants

| Name | Value |
|---|---|
| `_DEFAULT_BATCH_LIMIT` | `200` |

## Classes

### `class BatchAssetInput(BaseModel)`

---

### `class BatchIngestRequest(BaseModel)`

---

### `class BatchAssetResult(BaseModel)`

---

### `class BatchIngestResponse(BaseModel)`

---

## Functions

```
@router.post('/ingest', response_model=BatchIngestResponse, status_code=status.HTTP_202_ACCEPTED, summary='Batch-register assets and enqueue AI drafting')
```
```python
async def batch_ingest(body: BatchIngestRequest, db: DbDep) → BatchIngestResponse
```

Register up to 200 assets and (optionally) queue AI metadata drafting for each.

Existing assets are skipped when `skip_existing=True` (default).
Parsing errors for individual DDLs are reported per-asset without aborting the batch.

**Parameters:**

- **`body`** `BatchIngestRequest`
- **`db`** `DbDep`

**Returns:** `BatchIngestResponse`
