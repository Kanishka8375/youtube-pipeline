"""Logging that carries the correlation id.

The id is what makes a background job traceable back to the request that
queued it: `BackgroundJob.correlation_id` stores the same value the log lines
carry, so one grep spans the HTTP request and the work it deferred.
"""

from __future__ import annotations

import logging
import os

from app.core.request_context import current_correlation_id

LOG_FORMAT = "%(asctime)s %(levelname)-7s [corr=%(correlation_id)s] %(name)s: %(message)s"


class CorrelationIdFilter(logging.Filter):
    """Attaches `correlation_id` to every record, so the format string is safe.

    A filter rather than an adapter: the format string references the field
    unconditionally, and a record from a library that knows nothing about
    correlation ids would raise on formatting without this.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = current_correlation_id() or "-"
        return True


def configure_logging(level: str | None = None) -> None:
    """Idempotent. Safe to call from both app startup and a worker entrypoint."""
    root = logging.getLogger()
    if any(getattr(h, "_anime_pipeline_configured", False) for h in root.handlers):
        return

    handler = logging.StreamHandler()
    handler.addFilter(CorrelationIdFilter())
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler._anime_pipeline_configured = True  # type: ignore[attr-defined]

    root.addHandler(handler)
    root.setLevel(getattr(logging, (level or os.getenv("ANIME_LOG_LEVEL", "INFO")).upper(), logging.INFO))
