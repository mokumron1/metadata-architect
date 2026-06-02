# `metadata_architect.notifications.slack_adapter`

**Package:** `metadata_architect`  
**Module:** `notifications.slack_adapter`  
**Source:** `src/metadata_architect/notifications/slack_adapter.py`  
**Generated:** 2026-06-02  

> Slack Block Kit adapter with TDK score bar visualisation.

## Overview

Slack adapter — posts to a governance channel via Incoming Webhooks.

Uses the Slack Block Kit format for rich, actionable messages.
Gracefully no-ops when SLACK_BOT_TOKEN is not configured.

## Constants

| Name | Value |
|---|---|
| `_SLACK_POST_URL` | `'https://slack.com/api/chat.postMessage'` |
| `_EMOJI` | `{NotificationType.VERIFICATION_PULSE: ':mag:', NotificationType.ORPHAN_NOTICE: ':warning:', NotificationType.REJECTIO...` |

## Classes

### `class SlackAdapter(NotificationAdapter)`

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
