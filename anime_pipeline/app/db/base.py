"""Declarative base and portable column types.

Production runs on Postgres; the test suite runs on SQLite. `JSONColumn`
renders JSONB on Postgres and JSON elsewhere so one model set serves both,
and `sa.Uuid` renders a native UUID on Postgres and CHAR(32) elsewhere.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

#: Use for every JSON column. Do not import JSONB directly into models.
JSONColumn = sa.JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass
