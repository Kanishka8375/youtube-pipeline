"""Editorial approval for rewriting settled canon.

The contradiction matcher blocks a draft that changes a fact established
later on the timeline. That is correct and it is also not the whole story:
shows revise their own past deliberately, and a gate with no legitimate way
through is a gate people route around.

This module is the way through. It does not weaken the check -- the
contradiction still blocks -- it adds a record of a human deciding to allow
this specific change, so the rewrite is deliberate, attributed, and revertible
as a unit.

The invariant that makes it worth having: an agent cannot approve its own
retcon. `RetconProposal.status` moves to `approved` only through `approve()`,
which requires a `decided_by`, and `MemoryFact.is_retcon` is set nowhere else.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ContradictionMatch,
    Episode,
    MemoryFact,
    RetconProposal,
    Series,
)
from app.services.canon_registry import EntityRegistry, TimelineService
from app.services.normalisation import normalise_fact_value, values_agree

#: Approved retcons outrank ordinary agent writeback: a human decided this
#: one, so the next draft cannot win the same argument back on priority alone.
SOURCE_PRIORITY_APPROVED_RETCON = 200

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
VALID_STATUSES = frozenset({PENDING, APPROVED, REJECTED})


class RetconStateError(ValueError):
    """Raised when a proposal is decided twice, or decided into a bad state."""


class UnknownProposalError(ValueError):
    """Raised when a proposal code or id does not exist."""


@dataclass
class RetconOutcome:
    proposal: RetconProposal
    superseded_fact_id: Optional[uuid.UUID]
    new_fact_id: Optional[uuid.UUID]
    contradictions_cleared: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "retcon_group_code": self.proposal.retcon_group_code,
            "status": self.proposal.status,
            "entity_code": self.proposal.entity_code,
            "fact_key": self.proposal.fact_key,
            "decided_by": self.proposal.decided_by,
            "superseded_fact_id": str(self.superseded_fact_id)
            if self.superseded_fact_id
            else None,
            "new_fact_id": str(self.new_fact_id) if self.new_fact_id else None,
            "contradictions_cleared": self.contradictions_cleared,
        }


class RetconService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.registry = EntityRegistry(session)
        self.timeline = TimelineService(session)

    # -- proposing -----------------------------------------------------------

    def propose(
        self,
        *,
        series: Series,
        entity_key: str,
        fact_key: str,
        proposed_value: Any,
        rationale: str,
        episode: Optional[Episode] = None,
        contradiction_id: Optional[uuid.UUID] = None,
    ) -> RetconProposal:
        """File a request to change a fact that canon already settled.

        The entity key is normalised through the registry first: a proposal
        filed under one spelling has to cover the draft that arrives under
        another, or approving it changes nothing.
        """
        entity_code = self.registry.normalise_key(series.id, entity_key)
        group_code = f"rtc_{uuid.uuid4().hex[:12]}"
        existing = self._established_fact(series.id, entity_code, fact_key)

        proposal = RetconProposal(
            series_id=series.id,
            episode_id=episode.id if episode else None,
            entity_code=entity_code,
            fact_key=fact_key,
            proposed_value=proposed_value,
            proposed_normalised_value=normalise_fact_value(proposed_value),
            existing_fact_id=existing.id if existing else None,
            rationale=rationale,
            status=PENDING,
            retcon_group_code=group_code,
        )
        self.session.add(proposal)
        self.session.flush()

        if contradiction_id is not None:
            match = self.session.get(ContradictionMatch, contradiction_id)
            if match is not None:
                match.retcon_proposal_id = proposal.id
                self.session.flush()
        return proposal

    # -- deciding ------------------------------------------------------------

    def approve(
        self,
        proposal: RetconProposal,
        *,
        decided_by: str,
        decision_note: Optional[str] = None,
    ) -> RetconOutcome:
        """Accept the rewrite: supersede the old fact, write the new one.

        The old fact is never deleted. It is closed off -- status `superseded`,
        `valid_to` set to the retconning episode -- so "what was true before the
        rewrite" stays answerable, which is the whole reason to record a retcon
        rather than just letting the draft through.
        """
        self._require_pending(proposal)
        if not decided_by or not decided_by.strip():
            raise RetconStateError("An approval must record who approved it")

        superseded = (
            self.session.get(MemoryFact, proposal.existing_fact_id)
            if proposal.existing_fact_id
            else self._established_fact(
                proposal.series_id, proposal.entity_code, proposal.fact_key
            )
        )

        episode = (
            self.session.get(Episode, proposal.episode_id) if proposal.episode_id else None
        )
        new_fact: Optional[MemoryFact] = None
        if superseded is not None:
            superseded.status = "superseded"
            if episode is not None:
                superseded.valid_to_episode_id = episode.id
                superseded.timeline_end_order = self.timeline.earliest_order_index(episode.id)

            new_fact = MemoryFact(
                memory_document_id=superseded.memory_document_id,
                fact_type=superseded.fact_type,
                entity_type=superseded.entity_type,
                entity_key=proposal.entity_code,
                fact_key=proposal.fact_key,
                fact_value=proposal.proposed_value,
                normalised_value=proposal.proposed_normalised_value,
                mutability=superseded.mutability,
                importance=superseded.importance,
                valid_from_episode_id=episode.id if episode else None,
                timeline_start_order=(
                    self.timeline.earliest_order_index(episode.id) if episode else None
                ),
                supersedes_fact_id=superseded.id,
                is_retcon=True,
                retcon_group_code=proposal.retcon_group_code,
                # An approved retcon is human-decided canon, so it outranks the
                # agent output it replaced -- otherwise the next draft could
                # win the same argument again on source priority alone.
                confidence_score=1.0,
                source_priority=SOURCE_PRIORITY_APPROVED_RETCON,
                status="active",
            )
            self.session.add(new_fact)

        proposal.status = APPROVED
        proposal.decided_by = decided_by.strip()
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.decision_note = decision_note
        self.session.flush()

        cleared = self._clear_contradictions(proposal)
        self.session.flush()
        return RetconOutcome(
            proposal=proposal,
            superseded_fact_id=superseded.id if superseded else None,
            new_fact_id=new_fact.id if new_fact else None,
            contradictions_cleared=cleared,
        )

    def reject(
        self,
        proposal: RetconProposal,
        *,
        decided_by: str,
        decision_note: Optional[str] = None,
    ) -> RetconOutcome:
        self._require_pending(proposal)
        if not decided_by or not decided_by.strip():
            raise RetconStateError("A rejection must record who rejected it")
        proposal.status = REJECTED
        proposal.decided_by = decided_by.strip()
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.decision_note = decision_note
        self.session.flush()
        return RetconOutcome(
            proposal=proposal,
            superseded_fact_id=None,
            new_fact_id=None,
            contradictions_cleared=0,
        )

    # -- lookups -------------------------------------------------------------

    def by_group_code(self, group_code: str) -> RetconProposal:
        proposal = self.session.scalar(
            select(RetconProposal).where(RetconProposal.retcon_group_code == group_code)
        )
        if proposal is None:
            raise UnknownProposalError(f"No retcon proposal {group_code!r}")
        return proposal

    def for_series(
        self, series_id: uuid.UUID, *, status: Optional[str] = None
    ) -> Sequence[RetconProposal]:
        stmt = select(RetconProposal).where(RetconProposal.series_id == series_id)
        if status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
            stmt = stmt.where(RetconProposal.status == status)
        return self.session.scalars(stmt.order_by(RetconProposal.created_at)).all()

    def approved_change(
        self, series_id: uuid.UUID, entity_code: str, fact_key: str, value: Any
    ) -> Optional[RetconProposal]:
        """The approved proposal covering this exact change, if any.

        Value comparison goes through normalisation so an approval granted for
        ``"the alley"`` still covers a draft that writes ``"The Alley"``. Without
        that, every re-spelling would need its own approval and the workflow
        would be unusable.
        """
        candidates = self.session.scalars(
            select(RetconProposal).where(
                RetconProposal.series_id == series_id,
                RetconProposal.entity_code == entity_code,
                RetconProposal.fact_key == fact_key,
                RetconProposal.status == APPROVED,
            )
        ).all()
        for candidate in candidates:
            if values_agree(candidate.proposed_value, value):
                return candidate
        return None

    # -- internals -----------------------------------------------------------

    def _require_pending(self, proposal: RetconProposal) -> None:
        if proposal.status != PENDING:
            raise RetconStateError(
                f"Proposal {proposal.retcon_group_code} is already {proposal.status}; "
                "a decided retcon cannot be decided again."
            )

    def _established_fact(
        self, series_id: uuid.UUID, entity_code: str, fact_key: str
    ) -> Optional[MemoryFact]:
        """The active fact this proposal would overwrite.

        Facts are not series-scoped directly -- they hang off a memory document
        -- so the entity code is matched through the registry, which is what
        makes a proposal filed under an alias find the right row.
        """
        rows = self.session.scalars(
            select(MemoryFact).where(
                MemoryFact.fact_key == fact_key, MemoryFact.status == "active"
            )
        ).all()
        for row in rows:
            if self.registry.normalise_key(series_id, row.entity_key) == entity_code:
                return row
        return None

    def _clear_contradictions(self, proposal: RetconProposal) -> int:
        matches = self.session.scalars(
            select(ContradictionMatch).where(
                ContradictionMatch.entity_code == proposal.entity_code,
                ContradictionMatch.fact_key == proposal.fact_key,
                ContradictionMatch.resolved.is_(False),
            )
        ).all()
        cleared = 0
        for match in matches:
            proposed = (match.proposed_fact_json or {}).get("fact_value")
            if not values_agree(proposed, proposal.proposed_value):
                continue
            match.resolved = True
            match.blocking = False
            match.retcon_proposal_id = proposal.id
            match.resolution_note = (
                f"Approved retcon {proposal.retcon_group_code} by "
                f"{proposal.decided_by}: {proposal.rationale}"
            )
            cleared += 1
        return cleared
