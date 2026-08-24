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
from app.services.normalisation import values_agree
from app.services.retcon import RetconService

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
    #: 0-100. `severity` is the band a human reads; this is what a queue sorts
    #: by, so the worst item in a batch of forty surfaces first instead of
    #: whichever happened to be written first.
    severity_score: int = 0
    #: Set when an approved retcon covers this exact change.
    retcon_group_code: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "contradiction_type": self.kind,
            "entity_code": self.entity_code,
            "fact_key": self.fact_key,
            "proposed_fact": self.proposed,
            "existing_fact": self.existing,
            "severity": self.severity,
            "severity_score": self.severity_score,
            "explanation": self.explanation,
            "blocking": self.blocking,
            "retcon_group_code": self.retcon_group_code,
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
    #: Registered names close to an unregistered key, keyed by that key. A
    #: proposal for a human, never applied: a wrong fuzzy merge attaches a fact
    #: to the wrong character and is invisible afterwards.
    entity_suggestions: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    #: Changes that would have blocked but are covered by an approved retcon.
    permitted_retcons: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "contradictions_found": len(self.contradictions),
            "contradictions": [c.as_dict() for c in self.contradictions],
            "progressions": self.progressions,
            "skipped": self.skipped,
            "unregistered_entities": self.unregistered_entities,
            "entity_suggestions": self.entity_suggestions,
            "permitted_retcons": self.permitted_retcons,
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
        "confidence_score": fact.confidence_score,
        "source_priority": fact.source_priority,
        "timeline_start_order": fact.timeline_start_order,
        "is_retcon": fact.is_retcon,
    }


#: Where a fact came from, highest authority first. Used only to break ties in
#: severity: a draft disagreeing with human-approved canon is a bigger problem
#: than two agent guesses disagreeing with each other.
SOURCE_PRIORITY = {
    "human_approved": 200,
    "agent_output": 100,
    "inferred": 50,
}
DEFAULT_SOURCE_PRIORITY = SOURCE_PRIORITY["agent_output"]


def severity_band(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 55:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def score_severity(
    *,
    kind: str,
    existing: MemoryFact,
    proposed: Dict[str, Any],
    proposing_position: Optional[int],
) -> int:
    """How bad this contradiction is, 0-100.

    The inputs are the ones that actually change the answer:

    - **Kind.** Rewriting an immutable fact is worse than reordering a stateful
      one, because nothing downstream can absorb it.
    - **Importance.** A contradiction on a `critical` fact matters more than one
      on a background detail.
    - **Authority gap.** Contradicting human-approved canon with agent output is
      worse than two agent outputs disagreeing.
    - **Confidence.** A tentative claim contradicting a certain one is a smaller
      problem than two certain claims colliding.
    - **Timeline distance.** A retcon reaching four episodes back invalidates
      more than one reaching back a single scene.

    The weights are a deliberate, reviewable guess, not a measurement. What
    matters is the ordering they produce, which the adversarial suite pins.
    """
    score = 60 if kind == "immutable_fact_changed" else 45

    importance = (existing.importance or "normal").lower()
    score += {"critical": 20, "high": 10, "normal": 0, "low": -10}.get(importance, 0)

    existing_priority = existing.source_priority or DEFAULT_SOURCE_PRIORITY
    proposed_priority = proposed.get("source_priority") or DEFAULT_SOURCE_PRIORITY
    if existing_priority > proposed_priority:
        score += 10

    proposed_confidence = proposed.get("confidence_score")
    proposed_confidence = 1.0 if proposed_confidence is None else float(proposed_confidence)
    existing_confidence = (
        1.0 if existing.confidence_score is None else float(existing.confidence_score)
    )
    # Both sides certain is the worst case; either side hedging softens it.
    score -= int(round((1.0 - min(proposed_confidence, existing_confidence)) * 20))

    if (
        kind == "retcon"
        and proposing_position is not None
        and existing.timeline_start_order is not None
    ):
        reach = max(0, existing.timeline_start_order - proposing_position)
        score += min(reach, 15)

    return max(0, min(100, score))


class ContradictionMatcher:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.registry = EntityRegistry(session)
        self.timeline = TimelineService(session)
        self.retcons = RetconService(session)

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
                # Unregistered plus a near match is the signature of a typo
                # forking canon. Surfaced, never acted on.
                suggestions = self.registry.suggest(series_id, raw_key)
                if suggestions:
                    result.entity_suggestions[raw_key] = [s.as_dict() for s in suggestions]

            for existing in self._active_facts(series_id, canonical_key, proposed["fact_key"]):
                # Normalised, not raw: "Safehouse" and "safehouse" are one
                # place, and a matcher that disagrees fires on formatting.
                if values_agree(existing.fact_value, proposed["fact_value"]):
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

                approved = self.retcons.approved_change(
                    series_id, canonical_key, proposed["fact_key"], proposed["fact_value"]
                )
                if approved is not None:
                    # A human signed off on exactly this change. It is still
                    # recorded -- an unlogged rewrite of canon is the thing this
                    # module exists to prevent -- but it no longer blocks.
                    finding.blocking = False
                    finding.retcon_group_code = approved.retcon_group_code
                    finding.explanation += (
                        f" Permitted by approved retcon {approved.retcon_group_code} "
                        f"({approved.decided_by})."
                    )
                    result.permitted_retcons.append(
                        {
                            "entity_code": canonical_key,
                            "fact_key": proposed["fact_key"],
                            "retcon_group_code": approved.retcon_group_code,
                            "decided_by": approved.decided_by,
                        }
                    )

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
            immutable_score = score_severity(
                kind="immutable_fact_changed",
                existing=existing,
                proposed=proposed,
                proposing_position=proposing_position,
            )
            return Finding(
                kind="immutable_fact_changed",
                entity_code=canonical_key,
                fact_key=fact_key,
                proposed=proposed,
                existing=_fact_snapshot(existing),
                severity=severity_band(immutable_score),
                severity_score=immutable_score,
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
            retcon_score = score_severity(
                kind="retcon",
                existing=existing,
                proposed=proposed,
                proposing_position=proposing_position,
            )
            return Finding(
                kind="retcon",
                entity_code=canonical_key,
                fact_key=fact_key,
                proposed=proposed,
                existing=_fact_snapshot(existing),
                severity=severity_band(retcon_score),
                severity_score=retcon_score,
                explanation=(
                    f"{canonical_key}.{fact_key} was established at timeline "
                    f"position {established_at}; this draft sits at "
                    f"{proposing_position} and changes it, rewriting settled canon."
                ),
                blocking=True,
            )
        return None

    def _established_at(self, fact: MemoryFact) -> Optional[int]:
        """The timeline position the fact was established at.

        Prefers the denormalised column, which TimelineService keeps in step
        with the events; falls back to a query for facts written before the
        column existed or attached to an episode with no timeline event yet.
        """
        if fact.timeline_start_order is not None:
            return fact.timeline_start_order
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
                severity_score=finding.severity_score,
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
