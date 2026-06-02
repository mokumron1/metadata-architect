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

GET  /studio            — serves the single-page HTML UI.

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

## Functions

```
@router.post('/generate', response_model=GenerateResponse)
```
```python
async def generate_soi_options(body: GenerateRequest) → GenerateResponse
```

Calls Claude to produce 3 candidate SoI variants, then scores each
with the TDK clarity formula and a lightweight jargon check.

**Parameters:**

- **`body`** `GenerateRequest`

**Returns:** `GenerateResponse`

```
@router.get('', response_class=HTMLResponse, include_in_schema=False)
```
```python
async def studio_ui() → HTMLResponse
```

**Returns:** `HTMLResponse`
