# `metadata_architect.api.routers.soi_studio`

**Package:** `metadata_architect`  
**Module:** `api.routers.soi_studio`  
**Source:** `src/metadata_architect/api/routers/soi_studio.py`  
**Generated:** 2026-06-02  

## Overview

SoI Studio — interactive Statement of Intent generator.

POST /studio/generate   — accepts a physical name, data type, and a business hint,
                          then returns 3 candidate Statements of Intent scored with
                          the TDK clarity formula and a quick jargon check.
                          Results are persisted to soi_studio_sessions.

GET  /studio/history    — returns paginated history of past sessions (JSON).

GET  /studio            — serves the single-page HTML UI (includes history browser).

## Constants

| Name | Value |
|---|---|
| `_STUDIO_SYSTEM` | `BLOCK_ROLE + '\n\n## Special Task for This Session\nGenerate EXACTLY 3 distinct Statements of Intent for the same ass...` |
| `_STUDIO_USER` | `'Generate 3 Statements of Intent for this asset.\n\nPhysical name : {physical_name}\nData type     : {data_type}\nBus...` |
| `_JARGON_TERMS` | `{'DDL', 'ETL', 'CDC', 'ODS', 'SCD', 'ELT', 'DAG', 'DWH', 'OLAP', 'OLTP', 'PK', 'FK', 'UUID', 'JSON', 'JSONB', 'VARCHA...` |
| `_UI_HTML` | `'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width...` |

## Classes

### `class GenerateRequest(BaseModel)`

---

### `class SoIOption(BaseModel)`

---

### `class GenerateResponse(BaseModel)`

---

### `class HistorySession(BaseModel)`

---

### `class HistoryResponse(BaseModel)`

---

## Functions

```
@router.post('/generate', response_model=GenerateResponse)
```
```python
async def generate_soi_options(body: GenerateRequest, db: AsyncSession = Depends(get_db)) → GenerateResponse
```

Calls Claude to produce 3 candidate SoI variants, then scores each
with the TDK clarity formula and a lightweight jargon check.
Results are saved to soi_studio_sessions for history browsing.

**Parameters:**

- **`body`** `GenerateRequest`
- **`db`** `AsyncSession` *(default: `Depends(get_db)`)*

**Returns:** `GenerateResponse`

```
@router.get('/history', response_model=HistoryResponse)
```
```python
async def get_history(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), search: str = Query('', description='Filter by physical name (partial match)'), db: AsyncSession = Depends(get_db)) → HistoryResponse
```

Return paginated history of past SoI Studio sessions, newest first.

**Parameters:**

- **`page`** `int` *(default: `Query(1, ge=1)`)*
- **`page_size`** `int` *(default: `Query(20, ge=1, le=100)`)*
- **`search`** `str` *(default: `Query('', description='Filter by physical name (partial match)')`)*
- **`db`** `AsyncSession` *(default: `Depends(get_db)`)*

**Returns:** `HistoryResponse`

```
@router.get('', response_class=HTMLResponse, include_in_schema=False)
```
```python
async def studio_ui() → HTMLResponse
```

**Returns:** `HTMLResponse`
