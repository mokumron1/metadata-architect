# `metadata_architect.auth.tokens`

**Package:** `metadata_architect`  
**Module:** `auth.tokens`  
**Source:** `src/metadata_architect/auth/tokens.py`  
**Generated:** 2026-06-02  

> JWT one-time review token creation and verification for SME email links.

## Overview

JWT one-time tokens for SME review portal links.

Each Verification Pulse email embeds a signed token containing:
  - workflow_id  — the specific workflow the SME must act on
  - sub          — the SME's email address
  - exp          — set to the SLA deadline so the link auto-expires

The token is validated on every workflow action endpoint so that:
  1. Only the designated SME can approve/edit/reject
  2. The link stops working after the SLA window closes
  3. No separate session store is needed

## Classes

### `class TokenError(Exception)`

---

### `class SMETokenPayload`

---

### `class TokenService`

#### Methods

```python
def __init__() → None
```

**Returns:** `None`

```python
def create_review_token(workflow_id: uuid.UUID, sme_email: str, sla_deadline: datetime) → str
```

Create a signed JWT for the SME review link.
Expires at the SLA deadline so the link self-destructs on breach.

**Parameters:**

- **`workflow_id`** `uuid.UUID`
- **`sme_email`** `str`
- **`sla_deadline`** `datetime`

**Returns:** `str`

```python
def verify_review_token(token: str) → SMETokenPayload
```

Decode and validate a review token.
Raises TokenError on expiry, tampering, or wrong type.

**Parameters:**

- **`token`** `str`

**Returns:** `SMETokenPayload`

```python
def create_api_key_header() → dict[str, str]
```

Returns the auth header dict for internal service-to-service calls.

**Returns:** `dict[str, str]`

---
