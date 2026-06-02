# `metadata_architect.models.asset_registry`

**Package:** `metadata_architect`  
**Module:** `models.asset_registry`  
**Source:** `src/metadata_architect/models/asset_registry.py`  
**Generated:** 2026-06-02  

> SQLAlchemy ORM models: Asset, SoIDraft, SmeWorkflow, TdkScoreLog and state machine.

## Classes

### `class AssetType(str, enum.Enum)`

---

### `class WorkflowStatus(str, enum.Enum)`

---

### `class TdkScoreEvent(str, enum.Enum)`

---

### `class Asset(Base)`

#### Methods

```
@property
```
```python
def latest_draft() → 'SoIDraft | None'
```

**Returns:** `'SoIDraft | None'`

```
@property
```
```python
def active_workflow() → 'SmeWorkflow | None'
```

**Returns:** `'SmeWorkflow | None'`

```
@property
```
```python
def current_tdk_score() → float | None
```

**Returns:** `float | None`

---

### `class SoIDraft(Base)`

---

### `class InvalidTransitionError(Exception)`

#### Methods

```python
def __init__(current: WorkflowStatus, target: WorkflowStatus) → None
```

**Parameters:**

- **`current`** `WorkflowStatus`
- **`target`** `WorkflowStatus`

**Returns:** `None`

---

### `class SmeWorkflow(Base)`

#### Methods

```python
def transition(target: WorkflowStatus, actioned_by: str | None = None) → None
```

**Parameters:**

- **`target`** `WorkflowStatus`
- **`actioned_by`** `str | None` *(default: `None`)*

**Returns:** `None`

```
@property
```
```python
def is_sla_breached() → bool
```

**Returns:** `bool`

---

### `class TdkScoreLog(Base)`

---
