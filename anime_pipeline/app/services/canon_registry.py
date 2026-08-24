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
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import or_ as sa_or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    CanonicalEntity,
    Episode,
    EntityAlias,
    MemoryFact,
    TimelineCausalLink,
    TimelineEvent,
)
from app.services.normalisation import normalise_alias

#: A name must score at least this against a known alias before it is worth
#: showing a human. Tuned by the adversarial suite in app/services/evaluation.py:
#: low enough to catch "Kisargi" for "Kisaragi", high enough that "Kade" does
#: not suggest "Kane".
SUGGESTION_THRESHOLD = 0.82

#: Never auto-merge. A fuzzy match is a suggestion for a person, never a
#: resolution -- see `suggest`.
MAX_SUGGESTIONS = 5


class DuplicateEntityCodeError(ValueError):
    """Raised when an entity code already exists in the series."""


class AmbiguousEntityError(ValueError):
    """Raised when a name resolves to more than one registry entity.

    Silently picking one would attach a fact to the wrong entity, which is
    worse than refusing: the fact would then never contradict anything.
    """


class AliasConflictError(ValueError):
    """Raised when an alias is already claimed by a different entity.

    Refusing the write is the whole point of the alias table: the alternative
    is two entities that both answer to "Kisaragi", which makes every fact
    about either of them unresolvable.
    """


class UnknownEntityError(ValueError):
    """Raised when an operation names an entity that is not registered."""


class DuplicateEventCodeError(ValueError):
    """Raised when an event code already exists in the series."""


class TimelineOrderConflictError(ValueError):
    """Raised when an order_index is already taken in the series."""


@dataclass
class Suggestion:
    """A near-miss name match, for a human to confirm or dismiss."""

    entity_code: str
    display_name: str
    matched_alias: str
    score: float

    def as_dict(self) -> Dict:
        return {
            "entity_code": self.entity_code,
            "display_name": self.display_name,
            "matched_alias": self.matched_alias,
            "score": round(self.score, 3),
        }


class EntityRegistry:
    """Resolves free-text names to registry entities."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # -- reads ---------------------------------------------------------------

    def entities_for_series(self, series_id: uuid.UUID) -> Sequence[CanonicalEntity]:
        return self.session.scalars(
            select(CanonicalEntity)
            .where(CanonicalEntity.series_id == series_id, CanonicalEntity.status == "active")
            .order_by(CanonicalEntity.entity_code)
        ).all()

    def by_code(self, series_id: uuid.UUID, entity_code: str) -> Optional[CanonicalEntity]:
        return self.session.scalar(
            select(CanonicalEntity).where(
                CanonicalEntity.series_id == series_id,
                CanonicalEntity.entity_code == entity_code,
            )
        )

    def aliases_for(self, entity: CanonicalEntity) -> Sequence[EntityAlias]:
        return self.session.scalars(
            select(EntityAlias)
            .where(EntityAlias.entity_id == entity.id)
            .order_by(EntityAlias.alias)
        ).all()

    # -- writes --------------------------------------------------------------

    def create(self, series_id: uuid.UUID, payload: Dict) -> CanonicalEntity:
        code = payload["entity_code"]
        if self.by_code(series_id, code) is not None:
            raise DuplicateEntityCodeError(
                f"Entity {code!r} already exists in this series"
            )
        payload = dict(payload)
        aliases = list(payload.pop("aliases", None) or [])
        entity = CanonicalEntity(series_id=series_id, aliases=aliases, **payload)
        self.session.add(entity)
        self.session.flush()
        # The code and display name are aliases too: an agent writing "Mira"
        # when the code is "MIRA" must resolve, and the same uniqueness rule
        # has to cover both or a second entity could take one as its alias.
        self._index_alias(entity, entity.entity_code, source="entity_code")
        self._index_alias(entity, entity.display_name, source="display_name")
        for alias in aliases:
            self._index_alias(entity, alias, source="manual")
        self.session.flush()
        return entity

    def add_alias(
        self,
        entity: CanonicalEntity,
        alias: str,
        *,
        source: str = "manual",
        confidence: float = 1.0,
    ) -> Optional[EntityAlias]:
        row = self._index_alias(entity, alias, source=source, confidence=confidence)
        if row is not None and alias not in (entity.aliases or []):
            # Rebound rather than mutated: JSON columns do not track in-place
            # list mutation, so an append alone would never be persisted.
            entity.aliases = [*(entity.aliases or []), alias]
        self.session.flush()
        return row

    def _index_alias(
        self,
        entity: CanonicalEntity,
        alias: str,
        *,
        source: str,
        confidence: float = 1.0,
    ) -> Optional[EntityAlias]:
        normalised = normalise_alias(alias)
        if not normalised:
            return None
        existing = self.session.scalar(
            select(EntityAlias).where(
                EntityAlias.series_id == entity.series_id,
                EntityAlias.alias_normalised == normalised,
            )
        )
        if existing is not None:
            if existing.entity_id != entity.id:
                owner = self.session.get(CanonicalEntity, existing.entity_id)
                raise AliasConflictError(
                    f"Alias {alias!r} is already claimed by "
                    f"{owner.entity_code if owner else existing.entity_id!r}. "
                    "One spelling cannot mean two entities."
                )
            return existing
        row = EntityAlias(
            series_id=entity.series_id,
            entity_id=entity.id,
            alias=alias,
            alias_normalised=normalised,
            source=source,
            confidence=confidence,
        )
        self.session.add(row)
        # Flushed immediately, not batched. The session runs with autoflush
        # off, so the lookup above cannot see a row that is only pending --
        # and `create()` indexes the code, the display name and every alias in
        # one call, where "KADE" and "Kade" normalise to the same key. Without
        # this the duplicate reaches the database as a unique-constraint error
        # instead of being recognised as the same name written twice.
        self.session.flush()
        return row

    # -- resolution ----------------------------------------------------------

    def resolve(self, series_id: uuid.UUID, name: str) -> Optional[CanonicalEntity]:
        """Map a spelling of a name to its registry entity, or None.

        Exact match on the normalised form only. Fuzzy matching deliberately
        does not happen here: a 0.9 similarity that is wrong attaches a fact to
        the wrong character and corrupts canon silently, which is strictly
        worse than not resolving. Near misses go through `suggest`.

        `AmbiguousEntityError` is still raised if two rows somehow share a
        normalised alias -- the unique constraint should make that impossible,
        but a resolver that guesses when its invariant is violated is how the
        violation stays hidden.
        """
        needle = normalise_alias(name or "")
        if not needle:
            return None
        rows = self.session.scalars(
            select(EntityAlias).where(
                EntityAlias.series_id == series_id,
                EntityAlias.alias_normalised == needle,
            )
        ).all()
        entity_ids = {row.entity_id for row in rows}
        if len(entity_ids) > 1:
            raise AmbiguousEntityError(
                f"{name!r} matches {len(entity_ids)} registry entities. "
                "Disambiguate the aliases."
            )
        if not rows:
            return None
        entity = self.session.get(CanonicalEntity, rows[0].entity_id)
        return entity if entity is not None and entity.status == "active" else None

    def suggest(self, series_id: uuid.UUID, name: str) -> List[Suggestion]:
        """Registered names close to `name`, best first.

        This is the fuzzy half, kept separate on purpose. It answers "did you
        mean" for a human or a review queue; nothing in the pipeline acts on it
        without a decision.
        """
        needle = normalise_alias(name or "")
        if not needle:
            return []
        rows = self.session.scalars(
            select(EntityAlias).where(EntityAlias.series_id == series_id)
        ).all()

        best: Dict[uuid.UUID, Tuple[float, str]] = {}
        for row in rows:
            if row.alias_normalised == needle:
                continue
            score = SequenceMatcher(None, needle, row.alias_normalised).ratio()
            if score < SUGGESTION_THRESHOLD:
                continue
            current = best.get(row.entity_id)
            if current is None or score > current[0]:
                best[row.entity_id] = (score, row.alias)

        suggestions: List[Suggestion] = []
        for entity_id, (score, matched) in best.items():
            entity = self.session.get(CanonicalEntity, entity_id)
            if entity is None or entity.status != "active":
                continue
            suggestions.append(
                Suggestion(
                    entity_code=entity.entity_code,
                    display_name=entity.display_name,
                    matched_alias=matched,
                    score=score,
                )
            )
        suggestions.sort(key=lambda s: (-s.score, s.entity_code))
        return suggestions[:MAX_SUGGESTIONS]

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
        # A new event can change where an episode sits, and facts carry that
        # position denormalised. Resyncing here is what keeps the two from
        # drifting apart between rebalances.
        self.resync_fact_orders(series_id)
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

    # -- maintenance ---------------------------------------------------------

    def rebalance(self, series_id: uuid.UUID, *, gap: int = 10) -> Dict[str, int]:
        """Respace order_index to `gap`, 2*gap, ... preserving relative order.

        Timelines get dense: insert three events between 4 and 5 and the next
        insertion has nowhere to go. Rebalancing reopens the gaps without
        changing which event comes first.

        Two passes, not one. `(series_id, order_index)` is unique, so writing
        the new values directly collides with rows that still hold them -- the
        first pass parks every row at a negative index no real row can occupy.
        """
        if gap < 1:
            raise ValueError("gap must be at least 1")

        events = self.session.scalars(
            select(TimelineEvent)
            .where(TimelineEvent.series_id == series_id)
            .order_by(TimelineEvent.order_index, TimelineEvent.event_code)
        ).all()
        if not events:
            return {"events_rebalanced": 0, "facts_resynced": 0}

        for offset, event in enumerate(events, start=1):
            event.order_index = -offset
        self.session.flush()

        for position, event in enumerate(events, start=1):
            event.order_index = position * gap
        self.session.flush()

        resynced = self.resync_fact_orders(series_id)
        return {"events_rebalanced": len(events), "facts_resynced": resynced}

    def resync_fact_orders(self, series_id: uuid.UUID) -> int:
        """Recompute the denormalised timeline orders on memory facts.

        `MemoryFact.timeline_start_order` exists so the matcher can order facts
        without a query each; the cost of that is exactly this function. Any
        operation that moves an episode on the timeline must call it, or the
        matcher orders facts by a chronology that no longer exists.
        """
        positions: Dict[uuid.UUID, int] = {}
        rows = self.session.execute(
            select(TimelineEvent.episode_id, TimelineEvent.order_index).where(
                TimelineEvent.series_id == series_id,
                TimelineEvent.status == "active",
                TimelineEvent.episode_id.is_not(None),
            )
        ).all()
        for episode_id, order_index in rows:
            current = positions.get(episode_id)
            if current is None or order_index < current:
                positions[episode_id] = order_index

        if not positions:
            return 0

        episode_ids = list(positions)
        facts = self.session.scalars(
            select(MemoryFact).where(
                sa_or_(
                    MemoryFact.valid_from_episode_id.in_(episode_ids),
                    MemoryFact.valid_to_episode_id.in_(episode_ids),
                )
            )
        ).all()
        changed = 0
        for fact in facts:
            start = positions.get(fact.valid_from_episode_id)
            end = positions.get(fact.valid_to_episode_id)
            if fact.timeline_start_order != start or fact.timeline_end_order != end:
                fact.timeline_start_order = start
                fact.timeline_end_order = end
                changed += 1
        self.session.flush()
        return changed


@dataclass
class CausalViolation:
    kind: str
    detail: str
    events: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {"kind": self.kind, "detail": self.detail, "events": self.events}


class CausalGraphService:
    """Cause/effect edges over the timeline, and the impossibilities they expose.

    Ordering alone says which event is earlier. It cannot say that an effect
    was written before its cause -- for that, someone has to state the causal
    link, and then the contradiction is arithmetic.
    """

    #: A `prevents` edge asserts the effect does *not* follow, so ordering it
    #: after the cause is the expected shape, not a violation.
    ORDERED_LINK_TYPES = frozenset({"causes", "enables"})
    VALID_LINK_TYPES = frozenset({"causes", "enables", "prevents"})

    def __init__(self, session: Session) -> None:
        self.session = session

    def link(
        self,
        *,
        series_id: uuid.UUID,
        cause: TimelineEvent,
        effect: TimelineEvent,
        link_type: str = "causes",
        strength: float = 1.0,
        note: Optional[str] = None,
    ) -> TimelineCausalLink:
        if link_type not in self.VALID_LINK_TYPES:
            raise ValueError(
                f"link_type must be one of {sorted(self.VALID_LINK_TYPES)}, got {link_type!r}"
            )
        if cause.id == effect.id:
            raise ValueError("An event cannot cause itself")
        row = TimelineCausalLink(
            series_id=series_id,
            cause_event_id=cause.id,
            effect_event_id=effect.id,
            link_type=link_type,
            strength=strength,
            note=note,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def links_for_series(self, series_id: uuid.UUID) -> Sequence[TimelineCausalLink]:
        return self.session.scalars(
            select(TimelineCausalLink).where(TimelineCausalLink.series_id == series_id)
        ).all()

    def check(self, series_id: uuid.UUID) -> List[CausalViolation]:
        """Every causal impossibility currently in the series."""
        events = {
            event.id: event
            for event in self.session.scalars(
                select(TimelineEvent).where(TimelineEvent.series_id == series_id)
            ).all()
        }
        links = self.links_for_series(series_id)
        violations: List[CausalViolation] = []

        for link in links:
            cause = events.get(link.cause_event_id)
            effect = events.get(link.effect_event_id)
            if cause is None or effect is None:
                continue
            if link.link_type not in self.ORDERED_LINK_TYPES:
                continue
            if effect.order_index <= cause.order_index:
                violations.append(
                    CausalViolation(
                        kind="effect_before_cause",
                        detail=(
                            f"{effect.event_code!r} (position {effect.order_index}) is "
                            f"{link.link_type} by {cause.event_code!r} (position "
                            f"{cause.order_index}), but sits at or before it."
                        ),
                        events=[cause.event_code, effect.event_code],
                    )
                )

        violations.extend(self._cycles(events, links))
        return violations

    def _cycles(
        self, events: Dict[uuid.UUID, TimelineEvent], links: Sequence[TimelineCausalLink]
    ) -> List[CausalViolation]:
        """Cycles in the cause graph, reported once each.

        A cycle means a set of events that each ultimately cause themselves --
        no ordering of the timeline can satisfy it, so it is unfixable by
        renumbering and has to be reported as its own kind of problem.
        """
        adjacency: Dict[uuid.UUID, List[uuid.UUID]] = {}
        for link in links:
            if link.link_type not in self.ORDERED_LINK_TYPES:
                continue
            adjacency.setdefault(link.cause_event_id, []).append(link.effect_event_id)

        WHITE, GREY, BLACK = 0, 1, 2
        colour: Dict[uuid.UUID, int] = {}
        found: List[CausalViolation] = []
        seen_signatures = set()

        def walk(node: uuid.UUID, path: List[uuid.UUID]) -> None:
            colour[node] = GREY
            path.append(node)
            for nxt in adjacency.get(node, ()):
                state = colour.get(nxt, WHITE)
                if state == GREY:
                    cycle = path[path.index(nxt):]
                    codes = [events[n].event_code for n in cycle if n in events]
                    signature = frozenset(codes)
                    if codes and signature not in seen_signatures:
                        seen_signatures.add(signature)
                        found.append(
                            CausalViolation(
                                kind="causal_cycle",
                                detail=(
                                    "These events form a causal loop: "
                                    + " -> ".join(codes + [codes[0]])
                                ),
                                events=codes,
                            )
                        )
                elif state == WHITE:
                    walk(nxt, path)
            path.pop()
            colour[node] = BLACK

        for node in list(adjacency):
            if colour.get(node, WHITE) == WHITE:
                walk(node, [])
        return found
