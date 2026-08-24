"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Iterator

from sqlalchemy.orm import Session

from app.core.database import get_session


def db_session() -> Iterator[Session]:
    yield from get_session()
