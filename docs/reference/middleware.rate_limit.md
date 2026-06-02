# `metadata_architect.middleware.rate_limit`

**Package:** `metadata_architect`  
**Module:** `middleware.rate_limit`  
**Source:** `src/metadata_architect/middleware/rate_limit.py`  
**Generated:** 2026-06-02  

> Sliding-window rate limiter (per API key) for the CI/CD gate endpoints.

## Overview

In-process sliding-window rate limiter for the CI/CD gate endpoints.

Uses a simple token-bucket per API key stored in a module-level dict.
Suitable for single-process deployments; for multi-worker deployments
replace with Redis-backed limits (e.g. slowapi + redis).

Default: 60 requests / 60 seconds per API key.
Override via env vars:
  GATE_RATE_LIMIT_REQUESTS=120
  GATE_RATE_LIMIT_WINDOW_SECONDS=60

## Constants

| Name | Value |
|---|---|
| `_LIMIT` | `int(os.getenv('GATE_RATE_LIMIT_REQUESTS', '60'))` |
| `_WINDOW` | `int(os.getenv('GATE_RATE_LIMIT_WINDOW_SECONDS', '60'))` |

## Functions

```python
def check_gate_rate_limit(request: Request) → None
```

FastAPI dependency — call as Depends(check_gate_rate_limit) on gate routes.

Identifies the caller by X-Gate-API-Key (already validated upstream).
Raises 429 if the caller has exceeded the sliding-window limit.

**Parameters:**

- **`request`** `Request`

**Returns:** `None`
