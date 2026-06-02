# `metadata_architect.notifications.base`

**Package:** `metadata_architect`  
**Module:** `notifications.base`  
**Source:** `src/metadata_architect/notifications/base.py`  
**Generated:** 2026-06-02  

> Abstract notification adapter interface, payload schema, and type enum.

## Overview

Abstract notification adapter interface.

All adapters (SendGrid, Slack) implement NotificationAdapter.
The dispatcher selects active adapters from settings and calls
send() on each concurrently.

## Classes

### `class NotificationType(str, Enum)`

---

### `class NotificationPayload`

---

### `class NotificationAdapter(ABC)`

Base class for all notification channel adapters.

#### Methods

```
@property
```
```
@abstractmethod
```
```python
def name() → str
```

Channel identifier for logging.

**Returns:** `str`

```
@abstractmethod
```
```python
def is_configured() → bool
```

Return True if required credentials are present in settings.

**Returns:** `bool`

```
@abstractmethod
```
```python
async def send(payload: NotificationPayload) → bool
```

Send the notification. Returns True on success, False on failure.
Must never raise — log and return False instead.

**Parameters:**

- **`payload`** `NotificationPayload`

**Returns:** `bool`

---
