"""The correlation id for the request currently being served.

A `ContextVar` rather than a global: FastAPI runs sync endpoints in a thread
pool and async ones on the loop, and a plain module-level variable would leak
one request's id into another's logs under either.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def current_correlation_id() -> Optional[str]:
    return correlation_id_var.get()
