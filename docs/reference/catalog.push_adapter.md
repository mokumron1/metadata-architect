# `metadata_architect.catalog.push_adapter`

**Package:** `metadata_architect`  
**Module:** `catalog.push_adapter`  
**Source:** `src/metadata_architect/catalog/push_adapter.py`  
**Generated:** 2026-06-02  

> DataHub GMS and Collibra REST adapters for post-approval metadata push.

## Overview

External catalog push adapter.

Pushes approved metadata (asset name, SoI, TDK score, certified_at)
to DataHub and/or Collibra after SME approval.

Adapters are opt-in: they activate only when the relevant env vars are set.
Both adapters are fire-and-forget — failures are logged but never block
the approval workflow.

Configuration (.env):
  DATAHUB_GMS_URL=http://datahub-gms:8080        # DataHub Graph Metadata Service
  COLLIBRA_BASE_URL=https://your-tenant.collibra.com
  COLLIBRA_API_USER=service-account@company.com
  COLLIBRA_API_PASSWORD=secret

## Classes

### `class CatalogPayload`

---

### `class DataHubAdapter`

Pushes metadata to DataHub via the GMS REST API (v3 entity upsert).

Uses the platform=metadata_architect, entity_type=dataset pattern
so the SoI appears as a "description" on the dataset entity.

#### Methods

```python
def __init__() → None
```

**Returns:** `None`

```python
def is_enabled() → bool
```

**Returns:** `bool`

```python
async def push(payload: CatalogPayload) → bool
```

**Parameters:**

- **`payload`** `CatalogPayload`

**Returns:** `bool`

---

### `class CollibraAdapter`

Upserts an asset description in Collibra via the REST API v2.

Looks up the asset by full name, then PATCHes the description attribute.

#### Methods

```python
def __init__() → None
```

**Returns:** `None`

```python
def is_enabled() → bool
```

**Returns:** `bool`

```python
async def push(payload: CatalogPayload) → bool
```

**Parameters:**

- **`payload`** `CatalogPayload`

**Returns:** `bool`

---

### `class CatalogPushDispatcher`

Dispatches an approved policy to all enabled catalog adapters concurrently.

#### Methods

```python
def __init__() → None
```

**Returns:** `None`

```python
async def dispatch(payload: CatalogPayload) → dict[str, bool]
```

**Parameters:**

- **`payload`** `CatalogPayload`

**Returns:** `dict[str, bool]`

---
