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
    AmbiguousEntityError,
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


# -- registry ---------------------------------------------------------------
@router.post("/entities", status_code=status.HTTP_201_CREATED)
def create_entity(body: EntityCreate, session: Session = Depends(db_session)):
    series = _series(session, body.series_code)
    try:
        entity = EntityRegistry(session).create(
            series.id, body.model_dump(exclude={"series_code"})
        )
    except DuplicateEntityCodeError as exc:
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
