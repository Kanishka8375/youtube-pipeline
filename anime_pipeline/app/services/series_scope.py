"""Which memory documents belong to a series.

`MemoryFact` has no `series_id`. It hangs off a `MemoryDocument`, whose
`scope_type`/`scope_id` pair points at a series, a season or an episode --
a deliberate trade made when the memory layer was designed, so one table
serves three scopes instead of three near-identical ones.

The cost of that trade is this module. Without it, every fact query is
global, and two shows that both have a character called MIRA contaminate
each other's continuity checks: a contradiction fires against a fact from a
series nobody involved has heard of. `canonical_entities` is scoped per
series precisely because two shows may share a name -- the fact lookups have
to honour the same boundary.
"""

from __future__ import annotations

import uuid
from typing import Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Episode, MemoryDocument, Season


def memory_document_ids_for_series(session: Session, series_id: uuid.UUID) -> Set[uuid.UUID]:
    """Every memory document scoped to this series, at any level."""
    season_ids = set(
        session.scalars(select(Season.id).where(Season.series_id == series_id)).all()
    )
    episode_ids = set(
        session.scalars(select(Episode.id).where(Episode.series_id == series_id)).all()
    )

    scope_ids = {series_id} | season_ids | episode_ids
    return set(
        session.scalars(
            select(MemoryDocument.id).where(MemoryDocument.scope_id.in_(scope_ids))
        ).all()
    )
