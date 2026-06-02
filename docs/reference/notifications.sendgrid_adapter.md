# `metadata_architect.notifications.sendgrid_adapter`

**Package:** `metadata_architect`  
**Module:** `notifications.sendgrid_adapter`  
**Source:** `src/metadata_architect/notifications/sendgrid_adapter.py`  
**Generated:** 2026-06-02  

> SendGrid HTML email adapter for Verification Pulse and Orphan Notices.

## Overview

SendGrid email adapter for the Verification Pulse and Orphan Notice.

Sends HTML emails with action buttons linking to the SME Review Portal.
Gracefully no-ops when SENDGRID_API_KEY is not configured.

## Constants

| Name | Value |
|---|---|
| `_SENDGRID_SEND_URL` | `'https://api.sendgrid.com/v3/mail/send'` |
| `_FROM_EMAIL` | `'no-reply@metadata-architect.ai'` |
| `_FROM_NAME` | `'Metadata Architect'` |

## Classes

### `class SendGridAdapter(NotificationAdapter)`

#### Methods

```
@property
```
```python
def name() → str
```

**Returns:** `str`

```python
def is_configured() → bool
```

**Returns:** `bool`

```python
async def send(payload: NotificationPayload) → bool
```

**Parameters:**

- **`payload`** `NotificationPayload`

**Returns:** `bool`

---
