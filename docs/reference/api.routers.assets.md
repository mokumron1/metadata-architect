# `metadata_architect.api.routers.assets`

**Package:** `metadata_architect`  
**Module:** `api.routers.assets`  
**Source:** `src/metadata_architect/api/routers/assets.py`  
**Generated:** 2026-06-02  

> Asset Registry CRUD endpoints (create, read, update, delete, parse, transition).

## Overview

Asset Registry CRUD — core Phase 1 API.

Endpoints:
  POST   /assets              Create a new asset record
  GET    /assets              List assets (paginated)
  GET    /assets/{id}         Get single asset with latest draft + TDK score
  PATCH  /assets/{id}         Update mutable fields
  DELETE /assets/{id}         Hard delete (admin only)
  POST   /assets/{id}/parse   Re-parse DDL and refresh column_metadata
  POST   /assets/{id}/workflow/transition   Advance SME workflow state

## Constants

| Name | Value |
|---|---|
| `_LOAD_FULL` | `[selectinload(Asset.soi_drafts), selectinload(Asset.workflows), selectinload(Asset.tdk_scores)]` |
| `_SOURCE_DIALECT_MAP` | `{'snowflake': 'snowflake', 'bigquery': 'bigquery', 'redshift': 'redshift', 'databricks': 'databricks', 'spark': 'spar...` |

## Functions

```
@router.post('', response_model=AssetRead, status_code=status.HTTP_201_CREATED)
```
```python
async def create_asset(body: AssetCreate, db: DbDep) → Asset
```

**Parameters:**

- **`body`** `AssetCreate`
- **`db`** `DbDep`

**Returns:** `Asset`

```
@router.get('', response_model=dict)
```
```python
async def list_assets(db: DbDep, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), asset_type: AssetType | None = None, source_system: str | None = None) → dict
```

**Parameters:**

- **`db`** `DbDep`
- **`page`** `int` *(default: `Query(1, ge=1)`)*
- **`page_size`** `int` *(default: `Query(20, ge=1, le=100)`)*
- **`asset_type`** `AssetType | None` *(default: `None`)*
- **`source_system`** `str | None` *(default: `None`)*

**Returns:** `dict`

```
@router.get('/{asset_id}', response_model=AssetRead)
```
```python
async def get_asset(asset_id: uuid.UUID, db: DbDep) → Asset
```

**Parameters:**

- **`asset_id`** `uuid.UUID`
- **`db`** `DbDep`

**Returns:** `Asset`

```
@router.patch('/{asset_id}', response_model=AssetRead)
```
```python
async def update_asset(asset_id: uuid.UUID, body: AssetUpdate, db: DbDep) → Asset
```

**Parameters:**

- **`asset_id`** `uuid.UUID`
- **`body`** `AssetUpdate`
- **`db`** `DbDep`

**Returns:** `Asset`

```
@router.delete('/{asset_id}', status_code=status.HTTP_204_NO_CONTENT)
```
```python
async def delete_asset(asset_id: uuid.UUID, db: DbDep) → None
```

**Parameters:**

- **`asset_id`** `uuid.UUID`
- **`db`** `DbDep`

**Returns:** `None`

```
@router.post('/{asset_id}/parse', response_model=AssetRead)
```
```python
async def reparse_ddl(asset_id: uuid.UUID, db: DbDep) → Asset
```

Re-parse the stored DDL and refresh column_metadata.

**Parameters:**

- **`asset_id`** `uuid.UUID`
- **`db`** `DbDep`

**Returns:** `Asset`

```
@router.post('/{asset_id}/workflow/transition', response_model=SmeWorkflowRead)
```
```python
async def transition_workflow(asset_id: uuid.UUID, body: WorkflowTransitionRequest, db: DbDep) → SmeWorkflow
```

Advance the active SME workflow state machine.

**Parameters:**

- **`asset_id`** `uuid.UUID`
- **`body`** `WorkflowTransitionRequest`
- **`db`** `DbDep`

**Returns:** `SmeWorkflow`
