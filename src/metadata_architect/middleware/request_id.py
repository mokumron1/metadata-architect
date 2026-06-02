"""
Request-ID middleware.

Generates or propagates an X-Request-ID header and injects it into
the structlog context so every log line in the request lifecycle
carries the same correlation ID.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(_HEADER) or str(uuid.uuid4())

        try:
            import structlog
            structlog.contextvars.clear_contextvars()
            structlog.contextvars.bind_contextvars(request_id=request_id)
        except ImportError:
            pass

        response = await call_next(request)
        response.headers[_HEADER] = request_id
        return response
