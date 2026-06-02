# `metadata_architect.api.routers.workflows`

**Package:** `metadata_architect`  
**Module:** `api.routers.workflows`  
**Source:** `src/metadata_architect/api/routers/workflows.py`  
**Generated:** 2026-06-02  

> SME HITL review portal — approve, edit, reject, list, and get workflows.

## Overview

SME Workflow Router — the HITL Review Portal API.

Endpoints:
  GET  /workflows                      List workflows (filterable by status)
  GET  /workflows/{id}                 Single workflow with asset + draft detail
  POST /workflows/{id}/approve         SME approves the draft as-is
  POST /workflows/{id}/edit            SME submits a corrected SoI + approves
  POST /workflows/{id}/reject          SME rejects (orphaned / redundant data)

Each action endpoint:
  1. Validates the JWT review token from the email link (or falls back to API key)
  2. Drives the state machine transition
  3. Persists a TdkScoreLog event
  4. Emits a YAML policy file (on approve / edit-approve)
  5. Queues the analyse_sme_edit Celery task (on edit)
  6. Sends a confirmation notification

## Constants

| Name | Value |
|---|---|
| `_LOAD_FULL` | `[selectinload(SmeWorkflow.asset).selectinload(Asset.soi_drafts), selectinload(SmeWorkflow.asset).selectinload(Asset.t...` |

## Classes

### `class ApproveRequest(BaseModel)`

---

### `class EditRequest(BaseModel)`

---

### `class RejectRequest(BaseModel)`

---

### `class WorkflowActionResponse(BaseModel)`

---

## Functions

```
@router.get('', response_model=dict)
```
```python
async def list_workflows(db: DbDep, status_filter: WorkflowStatus | None = Query(None, alias='status'), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)) → dict
```

**Parameters:**

- **`db`** `DbDep`
- **`status_filter`** `WorkflowStatus | None` *(default: `Query(None, alias='status')`)*
- **`page`** `int` *(default: `Query(1, ge=1)`)*
- **`page_size`** `int` *(default: `Query(20, ge=1, le=100)`)*

**Returns:** `dict`

```
@router.get('/{workflow_id}', response_model=dict)
```
```python
async def get_workflow(workflow_id: uuid.UUID, db: DbDep) → dict
```

**Parameters:**

- **`workflow_id`** `uuid.UUID`
- **`db`** `DbDep`

**Returns:** `dict`

```
@router.post('/{workflow_id}/approve', response_model=WorkflowActionResponse)
```
```python
async def approve_workflow(workflow_id: uuid.UUID, body: ApproveRequest, db: DbDep) → WorkflowActionResponse
```

SME certifies the AI-drafted SoI without changes.

**Parameters:**

- **`workflow_id`** `uuid.UUID`
- **`body`** `ApproveRequest`
- **`db`** `DbDep`

**Returns:** `WorkflowActionResponse`

```
@router.post('/{workflow_id}/edit', response_model=WorkflowActionResponse)
```
```python
async def edit_and_approve_workflow(workflow_id: uuid.UUID, body: EditRequest, db: DbDep) → WorkflowActionResponse
```

SME submits a corrected SoI, which is immediately certified.

The original draft + edit diff are stored as training data.
Transitions: AWAITING_SME_AUDIT → SME_EDITED → SME_APPROVED (two steps).

**Parameters:**

- **`workflow_id`** `uuid.UUID`
- **`body`** `EditRequest`
- **`db`** `DbDep`

**Returns:** `WorkflowActionResponse`

```
@router.post('/{workflow_id}/reject', response_model=WorkflowActionResponse)
```
```python
async def reject_workflow(workflow_id: uuid.UUID, body: RejectRequest, db: DbDep) → WorkflowActionResponse
```

SME marks the asset as orphaned or redundant.

**Parameters:**

- **`workflow_id`** `uuid.UUID`
- **`body`** `RejectRequest`
- **`db`** `DbDep`

**Returns:** `WorkflowActionResponse`
