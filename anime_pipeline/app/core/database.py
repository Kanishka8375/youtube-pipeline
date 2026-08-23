"""Engine, session factory and the FastAPI session dependency."""

from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.base import Base

# Imported for its side effect: model classes must be registered on
# Base.metadata before create_all(), or a fresh database gets zero tables.
from app.db import models  # noqa: F401

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def init_engine(settings: Settings | None = None, create_all: bool = True) -> Engine:
    global _engine, _SessionLocal
    settings = settings or get_settings()
    kwargs = {"echo": settings.echo_sql, "future": True}
    if settings.database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(settings.database_url, **kwargs)

    if _engine.dialect.name == "sqlite":
        # SQLite ignores foreign keys unless asked; without this the ondelete
        # rules in the models are silently inert and tests pass on data
        # Postgres would reject.
        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_conn, _record):  # pragma: no cover - trivial
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    if create_all:
        Base.metadata.create_all(_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_session() -> Iterator[Session]:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
