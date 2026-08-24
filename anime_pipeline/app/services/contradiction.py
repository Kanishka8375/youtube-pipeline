"""Compares proposed facts against established canon.

Why a naive matcher does not work
---------------------------------
The obvious rule -- *same entity, same fact key, different value => contradiction*
-- flags every normal story development. Mira's trust in Kade going from
``intact`` to ``damaged`` is the plot, not an error. A gate built that way
blocks on ordinary progression and gets switched off within a week, at which
point it protects nothing.

The distinction that makes it work is on the fact itself:

``immutable``
    Cannot change without rewriting the past: a birth name, a species, what
    happened in EP03. A changed value here is a genuine contradiction.

``stateful``
    Changes as the story runs: trust, location, injuries, what a character
    knows. A changed value is progression -- reported, never blocking.

One case does make a stateful change a contradiction: establishing it from an
episode that sits *earlier* on the timeline than the episode that established
the current value. That is a retcon -- writing new past over settled future --
and the timeline is what makes it detectable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ContradictionMatch, Episode, MemoryFact
from app.services.canon_registry import AmbiguousEntityError, EntityRegistry, TimelineService

IMMUTABLE = "immutable"
STATEFUL = "stateful"
VALID_MUTABILITY = frozenset({IMMUTABLE, STATEFUL})

#: A proposed fact must carry these before it can be compared to anything.
REQUIRED_KEYS = ("entity_type", "entity_key", "fact_key", "fact_value")


class InvalidMutabilityError(ValueError):
    """Raised when a fact declares a mutability the matcher does not know."""


@dataclass
class Finding:
    kind: str
    entity_code: Optional[str]
    fact_key: Optional[str]
    proposed: Dict[str, Any]
    existing: Dict[str, Any]
    severity: str
    explanation: str
    blocking: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "contradiction_type": self.kind,
            "entity_code": self.entity_code,
            "fact_key": self.fact_key,
            "proposed_fact": self.proposed,
            "existing_fact": self.existing,
            "severity": self.severity,
            "explanation": self.explanation,
            "blocking": self.blocking,
        }


@dataclass
class ContradictionResult:
    passed: bool = True
    contradictions: List[Finding] = field(default_factory=list)
    #: Stateful changes: recorded so the reviewer sees canon moving, but not
    #: treated as errors.
    progressions: List[Dict[str, Any]] = field(default_factory=list)
    #: Facts too incomplete to compare against anything.
    skipped: List[Dict[str, Any]] = field(default_factory=list)
    #: entity_keys with no registry entry. Not an error, but the usual first
    #: sign of canon forking across spellings.
    unregistered_entities: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "contradictions_found": len(self.contradictions),
            "contradictions": [c.as_dict() for c in self.contradictions],
            "progressions": self.progressions,
            "skipped": self.skipped,
            "unregistered_entities": self.unregistered_entities,
        }


def _fact_snapshot(fact: MemoryFact) -> Dict[str, Any]:
    return {
        "fact_type": fact.fact_type,
        "entity_type": fact.entity_type,
        "entity_key": fact.entity_key,
        "fact_key": fact.fact_key,
        "fact_value": fact.fact_value,
        "mutability": fact.mutability,
        "status": fact.status,
    }


class ContradictionMatcher:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.registry = EntityRegistry(session)
        self.timeline = TimelineService(session)

    def check(
        self,
        *,
        series_id: uuid.UUID,
        proposed_facts: Sequence[Dict[str, Any]],
        episode: Optional[Episode] = None,
        persist: bool = True,
        source_run_id: Optional[uuid.UUID] = None,
    ) -> ContradictionResult:
        result = ContradictionResult()
        proposing_position = (
            self.timeline.earliest_order_index(episode.id) if episode else None
        )

        for proposed in proposed_facts:
            missing = [k for k in REQUIRED_KEYS if not proposed.get(k)]
            if missing:
                result.skipped.append(
                    {
                        "reason": f"missing required keys: {', '.join(missing)}",
                        "payload": proposed,
                    }
                )
                continue

            mutability = proposed.get("mutability", IMMUTABLE)
            if mutability not in VALID_MUTABILITY:
                raise InvalidMutabilityError(
                    f"mutability must be one of {sorted(VALID_MUTABILITY)}, "
                    f"got {mutability!r}"
                )

            raw_key = proposed["entity_key"]
            try:
                entity = self.registry.resolve(series_id, raw_key)
            except AmbiguousEntityError:
                result.skipped.append(
                    {
                        "reason": f"{raw_key!r} matches more than one registry entity",
                        "payload": proposed,
                    }
                )
                continue

            canonical_key = entity.entity_code if entity else raw_key
            if entity is None and raw_key not in result.unregistered_entities:
                result.unregistered_entities.append(raw_key)

            for existing in self._active_facts(series_id, canonical_key, proposed["fact_key"]):
                if existing.fact_value == proposed["fact_value"]:
                    continue
                finding = self._classify(
                    proposed=proposed,
                    existing=existing,
                    canonical_key=canonical_key,
                    mutability=mutability,
                    proposing_position=proposing_position,
                )
                if finding is None:
                    result.progressions.append(
                        {
                            "entity_code": canonical_key,
                            "fact_key": proposed["fact_key"],
                            "from": existing.fact_value,
                            "to": proposed["fact_value"],
                        }
                    )
                    continue
                result.contradictions.append(finding)
                if persist:
                    self._persist(finding, episode=episode, source_run_id=source_run_id)

        result.passed = not any(c.blocking for c in result.contradictions)
        if persist:
            self.session.flush()
        return result

    def _active_facts(
        self, series_id: uuid.UUID, entity_key: str, fact_key: str
    ) -> Sequence[MemoryFact]:
        """Active facts for this entity and key, matched across spellings.

        Existing facts may have been written under a different spelling before
        the entity was registered, so every candidate is normalised too.
        """
        rows = self.session.scalars(
            select(MemoryFact).where(
                MemoryFact.fact_key == fact_key, MemoryFact.status == "active"
            )
        ).all()
        matched = []
        for row in rows:
            try:
                if self.registry.normalise_key(series_id, row.entity_key) == entity_key:
                    matched.append(row)
            except AmbiguousEntityError:
                continue
        return matched

    def _classify(
        self,
        *,
        proposed: Dict[str, Any],
        existing: MemoryFact,
        canonical_key: str,
        mutability: str,
        proposing_position: Optional[int],
    ) -> Optional[Finding]:
        """Contradiction, retcon, or ordinary progression."""
        fact_key = proposed["fact_key"]

        # An immutable fact changing rewrites something settled.
        if mutability == IMMUTABLE or existing.mutability == IMMUTABLE:
            return Finding(
                kind="immutable_fact_changed",
                entity_code=canonical_key,
                fact_key=fact_key,
                proposed=proposed,
                existing=_fact_snapshot(existing),
                severity="high",
                explanation=(
                    f"{canonical_key}.{fact_key} is immutable canon "
                    f"({existing.fact_value!r}); the draft sets it to "
                    f"{proposed['fact_value']!r}."
                ),
                blocking=True,
            )

        # Both stateful: progression unless the proposing episode sits earlier
        # on the timeline than the one that established the current value.
        established_at = self._established_at(existing)
        if (
            proposing_position is not None
            and established_at is not None
            and proposing_position < established_at
        ):
            return Finding(
                kind="retcon",
                entity_code=canonical_key,
                fact_key=fact_key,
                proposed=proposed,
                existing=_fact_snapshot(existing),
                severity="high",
                explanation=(
                    f"{canonical_key}.{fact_key} was established at timeline "
                    f"position {established_at}; this draft sits at "
                    f"{proposing_position} and changes it, rewriting settled canon."
                ),
                blocking=True,
            )
        return None

    def _established_at(self, fact: MemoryFact) -> Optional[int]:
        if fact.valid_from_episode_id is None:
            return None
        return self.timeline.earliest_order_index(fact.valid_from_episode_id)

    def _persist(
        self,
        finding: Finding,
        *,
        episode: Optional[Episode],
        source_run_id: Optional[uuid.UUID],
    ) -> None:
        self.session.add(
            ContradictionMatch(
                episode_id=episode.id if episode else None,
                source_run_id=source_run_id,
                entity_code=finding.entity_code,
                fact_key=finding.fact_key,
                proposed_fact_json=finding.proposed,
                existing_fact_json=finding.existing,
                contradiction_type=finding.kind,
                severity=finding.severity,
                explanation=finding.explanation,
                blocking=finding.blocking,
            )
        )

    def open_blocking_for_episode(self, episode_id: uuid.UUID) -> Sequence[ContradictionMatch]:
        return self.session.scalars(
            select(ContradictionMatch).where(
                ContradictionMatch.episode_id == episode_id,
                ContradictionMatch.blocking.is_(True),
                ContradictionMatch.resolved.is_(False),
            )
        ).all()
