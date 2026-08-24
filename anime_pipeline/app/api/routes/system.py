"""Liveness and readiness."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.core.config import get_settings

router = APIRouter()


@router.get("/health")
def health():
    """Liveness: is the process up. Never touches the database.

    Kept dependency-free on purpose -- a liveness probe that fails when the
    database blips gets the container killed and restarted, which does not fix
    a database problem and does lose in-flight work.
    """
    settings = get_settings()
    return {"status": "ok", "environment": settings.environment}


@router.get("/readiness")
def readiness(session: Session = Depends(db_session)):
    """Readiness: can this process serve traffic. Requires the database."""
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 -- any failure means not ready
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unavailable: {type(exc).__name__}",
        ) from exc
    settings = get_settings()
    return {
        "status": "ready",
        "database": "ok",
        "environment": settings.environment,
        "llm_provider": settings.providers["llm"]["active"] or "unconfigured",
    }
