"""Canon registry, timeline, contradiction checks and continuity enforcement."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.api.routes.episodes import resolve_episode
from app.db.models import (
    ContinuityEnforcementRun,
    ContradictionMatch,
    MemoryDocument,
    Series,
)
from app.services.canon_registry import (
    AliasConflictError,
    AmbiguousEntityError,
    CausalGraphService,
    DuplicateEntityCodeError,
    DuplicateEventCodeError,
    EntityRegistry,
    TimelineOrderConflictError,
    TimelineService,
)
from app.services.contradiction import ContradictionMatcher, InvalidMutabilityError
from app.services.enforcement import (
    ApprovedOutputParser,
    ContinuityEnforcementService,
    UnknownComponentError,
)
from app.services.retcon import (
    RetconService,
    RetconStateError,
    UnknownProposalError,
)

router = APIRouter()


def _series(session: Session, series_code: str) -> Series:
    row = session.scalar(select(Series).where(Series.series_code == series_code))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown series {series_code!r}"
        )
    return row


# -- request models ---------------------------------------------------------
class EntityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_code: str
    entity_code: str
    entity_type: str
    display_name: str
    aliases: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class TimelineEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_code: str
    event_code: str
    event_type: str
    order_index: int = Field(ge=0)
    title: str
    summary: str
    episode_code: Optional[str] = None
    involved_entity_codes: List[str] = Field(default_factory=list)
    fact_refs: List[str] = Field(default_factory=list)
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class ContradictionCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_code: str
    episode_code: Optional[str] = None
    proposed_facts: List[Dict[str, Any]]
    persist: bool = True


class PreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_code: str
    episode_code: str
    #: Omit to use the agent's declared requirements.
    required_components: Optional[List[str]] = None


class DraftValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_code: str
    episode_code: str
    payload: Dict[str, Any]
    source_type: str = "script"
    source_ref: Optional[str] = None


class WritebackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_code: str
    memory_code: str
    output_type: str
    payload: Dict[str, Any]


class AliasCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_code: str
    entity_code: str
    alias: str
    source: str = "manual"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class RebalanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_code: str
    gap: int = Field(default=10, ge=1, le=1000)


class CausalLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_code: str
    cause_event_code: str
    effect_event_code: str
    link_type: str = "causes"
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    note: Optional[str] = None


class RetconProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_code: str
    entity_key: str
    fact_key: str
    proposed_value: Any
    rationale: str = Field(min_length=1)
    episode_code: Optional[str] = None


class RetconDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decided_by: str = Field(min_length=1)
    decision_note: Optional[str] = None


# -- registry ---------------------------------------------------------------
@router.post("/entities", status_code=status.HTTP_201_CREATED)
def create_entity(body: EntityCreate, session: Session = Depends(db_session)):
    series = _series(session, body.series_code)
    try:
        entity = EntityRegistry(session).create(
            series.id, body.model_dump(exclude={"series_code"})
        )
    except (DuplicateEntityCodeError, AliasConflictError) as exc:
        # 409 for both: an alias already claimed by another entity is the same
        # kind of collision as a duplicate code, and refusing it here is what
        # stops the ambiguity from ever reaching a resolver.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    return {"entity_code": entity.entity_code, "entity_type": entity.entity_type}


@router.get("/entities/{series_code}")
def list_entities(
    series_code: str,
    entity_type: Optional[str] = None,
    session: Session = Depends(db_session),
):
    series = _series(session, series_code)
    rows = EntityRegistry(session).entities_for_series(series.id)
    return [
        {
            "entity_code": r.entity_code,
            "entity_type": r.entity_type,
            "display_name": r.display_name,
            "aliases": r.aliases,
        }
        for r in rows
        if entity_type is None or r.entity_type == entity_type
    ]


@router.get("/entities/{series_code}/resolve")
def resolve_entity(series_code: str, name: str, session: Session = Depends(db_session)):
    """Which registry entity does this spelling refer to?"""
    series = _series(session, series_code)
    try:
        entity = EntityRegistry(session).resolve(series.id, name)
    except AmbiguousEntityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if entity is None:
        return {"query": name, "resolved": None}
    return {
        "query": name,
        "resolved": {"entity_code": entity.entity_code, "display_name": entity.display_name},
    }


# -- timeline ---------------------------------------------------------------
@router.post("/timeline", status_code=status.HTTP_201_CREATED)
def create_timeline_event(
    body: TimelineEventCreate, session: Session = Depends(db_session)
):
    series = _series(session, body.series_code)
    payload = body.model_dump(exclude={"series_code", "episode_code"})
    payload["series_id"] = series.id
    if body.episode_code:
        episode = resolve_episode(session, body.episode_code)
        if episode.series_id != series.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Episode {body.episode_code!r} is not in series {body.series_code!r}",
            )
        payload["episode_id"] = episode.id
        payload["season_id"] = episode.season_id

    try:
        event = TimelineService(session).create_event(payload)
    except (TimelineOrderConflictError, DuplicateEventCodeError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    return {"event_code": event.event_code, "order_index": event.order_index}


@router.get("/timeline/{series_code}")
def series_timeline(series_code: str, session: Session = Depends(db_session)):
    series = _series(session, series_code)
    return [
        {
            "event_code": e.event_code,
            "event_type": e.event_type,
            "order_index": e.order_index,
            "title": e.title,
            "summary": e.summary,
            "involved_entity_codes": e.involved_entity_codes,
        }
        for e in TimelineService(session).for_series(series.id)
    ]


# -- contradictions ---------------------------------------------------------
@router.post("/contradiction-check")
def contradiction_check(
    body: ContradictionCheckRequest, session: Session = Depends(db_session)
):
    """Compare proposed facts against established canon.

    A stateful fact changing is progression, not a contradiction — it is
    reported under `progressions`. Only immutable changes and retcons block.
    """
    series = _series(session, body.series_code)
    episode = resolve_episode(session, body.episode_code) if body.episode_code else None
    try:
        result = ContradictionMatcher(session).check(
            series_id=series.id,
            proposed_facts=body.proposed_facts,
            episode=episode,
            persist=body.persist,
        )
    except InvalidMutabilityError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if body.persist:
        session.commit()
    return result.as_dict()


@router.get("/contradictions/{episode_code}")
def list_contradictions(episode_code: str, session: Session = Depends(db_session)):
    episode = resolve_episode(session, episode_code)
    rows = session.scalars(
        select(ContradictionMatch)
        .where(ContradictionMatch.episode_id == episode.id)
        .order_by(ContradictionMatch.created_at.desc())
    ).all()
    return [
        {
            "entity_code": r.entity_code,
            "fact_key": r.fact_key,
            "contradiction_type": r.contradiction_type,
            "severity": r.severity,
            "explanation": r.explanation,
            "blocking": r.blocking,
            "resolved": r.resolved,
        }
        for r in rows
    ]


# -- enforcement ------------------------------------------------------------
def _run_payload(session: Session, run: ContinuityEnforcementRun) -> Dict[str, Any]:
    return {
        "run_type": run.run_type,
        "source_type": run.source_type,
        "source_ref": run.source_ref,
        "passed": run.passed,
        "summary": run.summary,
        "memory_provenance": run.memory_provenance,
        "issues": [
            {
                "issue_type": i.issue_type,
                "severity": i.severity,
                "entity_key": i.entity_key,
                "title": i.title,
                "description": i.description,
                "recommendation": i.recommendation,
                "blocking": i.blocking,
            }
            for i in run.issues
        ],
        "not_mechanically_checked": run.input_payload.get("_not_mechanically_checked", []),
        "unknown_speakers": run.input_payload.get("_unknown_speakers", []),
        "unregistered_entities": run.input_payload.get("_unregistered_entities", []),
        "progressions": run.input_payload.get("_progressions", []),
    }


@router.post("/preflight")
def preflight(body: PreflightRequest, session: Session = Depends(db_session)):
    """Refuse to start a task whose required canon is missing."""
    episode = resolve_episode(session, body.episode_code)
    service = ContinuityEnforcementService(session)
    try:
        run = service.preflight(
            agent_code=body.agent_code,
            episode=episode,
            required=body.required_components,
        )
    except UnknownComponentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    session.commit()
    return _run_payload(session, run)


@router.post("/validate-draft")
def validate_draft(body: DraftValidationRequest, session: Session = Depends(db_session)):
    episode = resolve_episode(session, body.episode_code)
    service = ContinuityEnforcementService(session)
    try:
        run = service.validate_draft(
            agent_code=body.agent_code,
            episode=episode,
            payload=body.payload,
            source_type=body.source_type,
            source_ref=body.source_ref,
        )
    except InvalidMutabilityError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    session.commit()
    return _run_payload(session, run)


@router.post("/writeback")
def writeback(body: WritebackRequest, session: Session = Depends(db_session)):
    episode = resolve_episode(session, body.episode_code)
    document = session.scalar(
        select(MemoryDocument).where(MemoryDocument.memory_code == body.memory_code)
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown memory document {body.memory_code!r}",
        )
    if body.output_type not in ApprovedOutputParser.SUPPORTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported output_type {body.output_type!r}. "
                f"Supported: {', '.join(ApprovedOutputParser.SUPPORTED)}"
            ),
        )
    return ContinuityEnforcementService(session).writeback(
        episode=episode,
        document=document,
        output_type=body.output_type,
        payload=body.payload,
    )


@router.get("/enforcement-runs/{episode_code}")
def list_runs(episode_code: str, session: Session = Depends(db_session)):
    episode = resolve_episode(session, episode_code)
    rows = session.scalars(
        select(ContinuityEnforcementRun)
        .where(ContinuityEnforcementRun.episode_id == episode.id)
        .order_by(ContinuityEnforcementRun.created_at.desc())
    ).all()
    return [_run_payload(session, r) for r in rows]


# -- aliases ----------------------------------------------------------------
@router.post("/aliases", status_code=status.HTTP_201_CREATED)
def add_alias(body: AliasCreate, session: Session = Depends(db_session)):
    """Teach the registry another spelling of a known entity."""
    series = _series(session, body.series_code)
    registry = EntityRegistry(session)
    entity = registry.by_code(series.id, body.entity_code)
    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown entity {body.entity_code!r} in series {body.series_code!r}",
        )
    try:
        row = registry.add_alias(
            entity, body.alias, source=body.source, confidence=body.confidence
        )
    except AliasConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{body.alias!r} normalises to nothing and cannot be used as a name",
        )
    session.commit()
    return {"entity_code": entity.entity_code, "alias": row.alias}


@router.get("/entities/{series_code}/suggest")
def suggest_entities(series_code: str, name: str, session: Session = Depends(db_session)):
    """Registered names close to `name`.

    Suggestions only. Nothing in the pipeline acts on these -- a fuzzy match
    that is wrong attaches a fact to the wrong entity and is invisible
    afterwards, so the decision stays with a person.
    """
    series = _series(session, series_code)
    return {
        "query": name,
        "suggestions": [s.as_dict() for s in EntityRegistry(session).suggest(series.id, name)],
    }


# -- timeline maintenance ---------------------------------------------------
@router.post("/timeline/rebalance")
def rebalance_timeline(body: RebalanceRequest, session: Session = Depends(db_session)):
    """Respace order_index without changing the order, reopening insertion gaps."""
    series = _series(session, body.series_code)
    result = TimelineService(session).rebalance(series.id, gap=body.gap)
    session.commit()
    return {"series_code": body.series_code, "gap": body.gap, **result}


# -- causality --------------------------------------------------------------
def _event(session: Session, series: Series, event_code: str):
    from app.db.models import TimelineEvent

    row = session.scalar(
        select(TimelineEvent).where(
            TimelineEvent.series_id == series.id, TimelineEvent.event_code == event_code
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown timeline event {event_code!r}",
        )
    return row


@router.post("/causal-links", status_code=status.HTTP_201_CREATED)
def create_causal_link(body: CausalLinkCreate, session: Session = Depends(db_session)):
    series = _series(session, body.series_code)
    cause = _event(session, series, body.cause_event_code)
    effect = _event(session, series, body.effect_event_code)
    try:
        CausalGraphService(session).link(
            series_id=series.id,
            cause=cause,
            effect=effect,
            link_type=body.link_type,
            strength=body.strength,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    session.commit()
    return {
        "cause_event_code": cause.event_code,
        "effect_event_code": effect.event_code,
        "link_type": body.link_type,
    }


@router.get("/causal-check/{series_code}")
def causal_check(series_code: str, session: Session = Depends(db_session)):
    """Causal impossibilities currently in the series."""
    series = _series(session, series_code)
    violations = CausalGraphService(session).check(series.id)
    return {
        "series_code": series_code,
        "passed": not violations,
        "violations": [v.as_dict() for v in violations],
    }


# -- retcons ----------------------------------------------------------------
def _proposal_payload(proposal) -> Dict[str, Any]:
    return {
        "retcon_group_code": proposal.retcon_group_code,
        "series_id": str(proposal.series_id),
        "entity_code": proposal.entity_code,
        "fact_key": proposal.fact_key,
        "proposed_value": proposal.proposed_value,
        "rationale": proposal.rationale,
        "status": proposal.status,
        "decided_by": proposal.decided_by,
        "decision_note": proposal.decision_note,
    }


@router.post("/retcons", status_code=status.HTTP_201_CREATED)
def propose_retcon(body: RetconProposeRequest, session: Session = Depends(db_session)):
    """File a request to overwrite settled canon.

    Filing does not unblock anything. Only an approval does, and only for the
    exact change proposed.
    """
    series = _series(session, body.series_code)
    episode = resolve_episode(session, body.episode_code) if body.episode_code else None
    if episode is not None and episode.series_id != series.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Episode {body.episode_code!r} is not in series {body.series_code!r}",
        )
    proposal = RetconService(session).propose(
        series=series,
        entity_key=body.entity_key,
        fact_key=body.fact_key,
        proposed_value=body.proposed_value,
        rationale=body.rationale,
        episode=episode,
    )
    session.commit()
    return _proposal_payload(proposal)


@router.get("/retcons/{series_code}")
def list_retcons(
    series_code: str,
    retcon_status: Optional[str] = None,
    session: Session = Depends(db_session),
):
    series = _series(session, series_code)
    try:
        rows = RetconService(session).for_series(series.id, status=retcon_status)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return [_proposal_payload(r) for r in rows]


def _decide(session: Session, group_code: str, body: RetconDecisionRequest, approve: bool):
    service = RetconService(session)
    try:
        proposal = service.by_group_code(group_code)
    except UnknownProposalError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    try:
        action = service.approve if approve else service.reject
        outcome = action(
            proposal, decided_by=body.decided_by, decision_note=body.decision_note
        )
    except RetconStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    return outcome.as_dict()


@router.post("/retcons/{group_code}/approve")
def approve_retcon(
    group_code: str, body: RetconDecisionRequest, session: Session = Depends(db_session)
):
    """Accept a rewrite: supersede the old fact and record who decided."""
    return _decide(session, group_code, body, approve=True)


@router.post("/retcons/{group_code}/reject")
def reject_retcon(
    group_code: str, body: RetconDecisionRequest, session: Session = Depends(db_session)
):
    return _decide(session, group_code, body, approve=False)
