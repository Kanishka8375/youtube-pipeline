"""The canonical entity registry and the series timeline.

Together these give the contradiction matcher the two things it needs:

- **Normalisation.** Facts key off `entity_key`, free text written by agents.
  Without resolving it through a registry, "MIRA" and "Mira" are different
  entities that can never contradict each other, and canon quietly forks.
- **Order.** Whether a fact change is progression or a retcon depends on which
  event came first, which needs a chronology to consult.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CanonicalEntity, Episode, TimelineEvent


class DuplicateEntityCodeError(ValueError):
    """Raised when an entity code already exists in the series."""


class AmbiguousEntityError(ValueError):
    """Raised when a name resolves to more than one registry entity.

    Silently picking one would attach a fact to the wrong entity, which is
    worse than refusing: the fact would then never contradict anything.
    """


class DuplicateEventCodeError(ValueError):
    """Raised when an event code already exists in the series."""


class TimelineOrderConflictError(ValueError):
    """Raised when an order_index is already taken in the series."""


class EntityRegistry:
    """Resolves free-text names to registry entities."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def entities_for_series(self, series_id: uuid.UUID) -> Sequence[CanonicalEntity]:
        return self.session.scalars(
            select(CanonicalEntity)
            .where(CanonicalEntity.series_id == series_id, CanonicalEntity.status == "active")
            .order_by(CanonicalEntity.entity_code)
        ).all()

    def create(self, series_id: uuid.UUID, payload: Dict) -> CanonicalEntity:
        code = payload["entity_code"]
        if self.by_code(series_id, code) is not None:
            raise DuplicateEntityCodeError(
                f"Entity {code!r} already exists in this series"
            )
        entity = CanonicalEntity(series_id=series_id, **payload)
        self.session.add(entity)
        self.session.flush()
        return entity

    def by_code(self, series_id: uuid.UUID, entity_code: str) -> Optional[CanonicalEntity]:
        return self.session.scalar(
            select(CanonicalEntity).where(
                CanonicalEntity.series_id == series_id,
                CanonicalEntity.entity_code == entity_code,
            )
        )

    def resolve(self, series_id: uuid.UUID, name: str) -> Optional[CanonicalEntity]:
        """Map any spelling of a name to its registry entity.

        Matches code, display name and aliases, case-insensitively. Raises
        rather than guessing when a name matches two entities.
        """
        if not name or not name.strip():
            return None
        needle = name.strip().casefold()

        hits: List[CanonicalEntity] = []
        for entity in self.entities_for_series(series_id):
            candidates = {entity.entity_code, entity.display_name, *(entity.aliases or [])}
            if any(c and c.strip().casefold() == needle for c in candidates):
                hits.append(entity)

        if len(hits) > 1:
            raise AmbiguousEntityError(
                f"{name!r} matches {len(hits)} registry entities: "
                f"{', '.join(e.entity_code for e in hits)}. Disambiguate the aliases."
            )
        return hits[0] if hits else None

    def normalise_key(self, series_id: uuid.UUID, entity_key: str) -> str:
        """Return the canonical code for a key, or the key unchanged.

        An unregistered key passes through rather than failing: canon can be
        recorded about something not yet in the registry, it just will not
        benefit from cross-spelling matching until it is registered.
        """
        entity = self.resolve(series_id, entity_key)
        return entity.entity_code if entity else entity_key

    def unregistered_keys(
        self, series_id: uuid.UUID, keys: Iterable[str]
    ) -> List[str]:
        """Keys with no registry entry -- candidates for canon drift."""
        missing = []
        for key in keys:
            if key and self.resolve(series_id, key) is None and key not in missing:
                missing.append(key)
        return missing


@dataclass
class TimelinePosition:
    """Where an episode sits in series chronology."""

    episode_code: str
    order_index: Optional[int]


class TimelineService:
    """Ordered chronology across a series."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_event(self, payload: Dict) -> TimelineEvent:
        series_id = payload["series_id"]
        order_index = payload["order_index"]
        existing = self.session.scalar(
            select(TimelineEvent).where(
                TimelineEvent.series_id == series_id,
                TimelineEvent.event_code == payload["event_code"],
            )
        )
        if existing is not None:
            raise DuplicateEventCodeError(
                f"Event {payload['event_code']!r} already exists in this series"
            )
        clash = self.session.scalar(
            select(TimelineEvent).where(
                TimelineEvent.series_id == series_id,
                TimelineEvent.order_index == order_index,
            )
        )
        if clash is not None:
            raise TimelineOrderConflictError(
                f"order_index {order_index} is already taken in this series by "
                f"{clash.event_code!r}. Timeline order must be unambiguous."
            )
        event = TimelineEvent(**payload)
        self.session.add(event)
        self.session.flush()
        return event

    def for_series(self, series_id: uuid.UUID) -> Sequence[TimelineEvent]:
        return self.session.scalars(
            select(TimelineEvent)
            .where(TimelineEvent.series_id == series_id, TimelineEvent.status == "active")
            .order_by(TimelineEvent.order_index)
        ).all()

    def for_season(self, season_id: uuid.UUID) -> Sequence[TimelineEvent]:
        return self.session.scalars(
            select(TimelineEvent)
            .where(TimelineEvent.season_id == season_id, TimelineEvent.status == "active")
            .order_by(TimelineEvent.order_index)
        ).all()

    def for_episode(self, episode_id: uuid.UUID) -> Sequence[TimelineEvent]:
        return self.session.scalars(
            select(TimelineEvent)
            .where(TimelineEvent.episode_id == episode_id, TimelineEvent.status == "active")
            .order_by(TimelineEvent.order_index)
        ).all()

    def earliest_order_index(self, episode_id: uuid.UUID) -> Optional[int]:
        """The episode's first position on the series timeline.

        Used to decide whether a fact change moves canon forward or rewrites
        something already established later.
        """
        return self.session.scalar(
            select(TimelineEvent.order_index)
            .where(
                TimelineEvent.episode_id == episode_id,
                TimelineEvent.status == "active",
            )
            .order_by(TimelineEvent.order_index)
            .limit(1)
        )

    def position_of(self, episode: Episode) -> TimelinePosition:
        return TimelinePosition(
            episode_code=episode.episode_code,
            order_index=self.earliest_order_index(episode.id),
        )
