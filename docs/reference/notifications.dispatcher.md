# `metadata_architect.notifications.dispatcher`

**Package:** `metadata_architect`  
**Module:** `notifications.dispatcher`  
**Source:** `src/metadata_architect/notifications/dispatcher.py`  
**Generated:** 2026-06-02  

> Concurrent notification dispatcher — sends to all enabled adapters.

## Overview

Notification dispatcher.

Routes a NotificationPayload to all configured adapters concurrently.
Failures in one adapter never block others.

## Classes

### `class NotificationDispatcher`

Instantiate once per task / request context and call dispatch().
Builds the adapter list from settings on construction.

#### Methods

```python
def __init__(adapters: list[NotificationAdapter] | None = None) → None
```

**Parameters:**

- **`adapters`** `list[NotificationAdapter] | None` *(default: `None`)*

**Returns:** `None`

```python
async def dispatch(payload: NotificationPayload) → dict[str, bool]
```

Send payload to all configured adapters concurrently.
Returns {adapter_name: success} for observability.

**Parameters:**

- **`payload`** `NotificationPayload`

**Returns:** `dict[str, bool]`

---
