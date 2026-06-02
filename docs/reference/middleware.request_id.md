# `metadata_architect.middleware.request_id`

**Package:** `metadata_architect`  
**Module:** `middleware.request_id`  
**Source:** `src/metadata_architect/middleware/request_id.py`  
**Generated:** 2026-06-02  

> X-Request-ID propagation middleware with structlog context binding.

## Overview

Request-ID middleware.

Generates or propagates an X-Request-ID header and injects it into
the structlog context so every log line in the request lifecycle
carries the same correlation ID.

## Constants

| Name | Value |
|---|---|
| `_HEADER` | `'X-Request-ID'` |

## Classes

### `class RequestIDMiddleware(BaseHTTPMiddleware)`

#### Methods

```python
async def dispatch(request: Request, call_next) → Response
```

**Parameters:**

- **`request`** `Request`
- **`call_next`**

**Returns:** `Response`

---
