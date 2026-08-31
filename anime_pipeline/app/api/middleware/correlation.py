"""Assigns every request a correlation id and echoes it back."""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from app.core.request_context import correlation_id_var

HEADER = "X-Correlation-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Honours an inbound `X-Correlation-ID`, or mints one.

    Honouring the caller's id is what lets a trace span services. The token is
    reset in a `finally` so a failed request cannot leak its id into whatever
    the worker thread handles next.
    """

    async def dispatch(self, request, call_next):
        correlation_id = request.headers.get(HEADER) or uuid.uuid4().hex
        token = correlation_id_var.set(correlation_id)
        try:
            response = await call_next(request)
            response.headers[HEADER] = correlation_id
            return response
        finally:
            correlation_id_var.reset(token)
