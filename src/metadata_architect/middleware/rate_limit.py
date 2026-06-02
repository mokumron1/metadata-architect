"""
In-process sliding-window rate limiter for the CI/CD gate endpoints.

Uses a simple token-bucket per API key stored in a module-level dict.
Suitable for single-process deployments; for multi-worker deployments
replace with Redis-backed limits (e.g. slowapi + redis).

Default: 60 requests / 60 seconds per API key.
Override via env vars:
  GATE_RATE_LIMIT_REQUESTS=120
  GATE_RATE_LIMIT_WINDOW_SECONDS=60
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status

_LIMIT = int(os.getenv("GATE_RATE_LIMIT_REQUESTS", "60"))
_WINDOW = int(os.getenv("GATE_RATE_LIMIT_WINDOW_SECONDS", "60"))

# {api_key: deque of request timestamps}
_buckets: dict[str, deque] = defaultdict(deque)
_lock = Lock()


def check_gate_rate_limit(request: Request) -> None:
    """
    FastAPI dependency — call as Depends(check_gate_rate_limit) on gate routes.

    Identifies the caller by X-Gate-API-Key (already validated upstream).
    Raises 429 if the caller has exceeded the sliding-window limit.
    """
    api_key = request.headers.get("x-gate-api-key", "anonymous")
    now = time.monotonic()
    cutoff = now - _WINDOW

    with _lock:
        bucket = _buckets[api_key]
        # Drop timestamps outside the window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= _LIMIT:
            retry_after = int(_WINDOW - (now - bucket[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Retry after {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )

        bucket.append(now)
