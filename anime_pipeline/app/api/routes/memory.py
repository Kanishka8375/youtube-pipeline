"""Canon memory: bundles, documents, character profiles, style bibles, checks."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.api.routes.episodes import resolve_episode
from app.db.models import CharacterProfile, ContinuityCheck, MemoryDocument, Series, StyleBible
from app.services.consistency_guard import ConsistencyGuardService
from app.services.memory_service import (
    AutoWritebackService,
    InvalidMemoryScopeError,
    MemoryBundleService,
    MultipleActiveStyleBiblesError,
    record_continuity_check,
    validate_scope,
)

router = APIRouter()


# -- request models ---------------------------------------------------------
class MemoryDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_code: str
    memory_type: str
    title: str
    summary: Optional[str] = None
    content_json: Dict[str, Any] = Field(default_factory=dict)
    #: Exactly one of these, matching the memory_type's scope.
    series_code: Optional[str] = None
    episode_code: Optional[str] = None


class CharacterProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_code: str
    character_code: str
    display_name: str
    aliases: List[str] = Field(default_factory=list)
    age_range: Optional[str] = None
    role_type: Optional[str] = None
    personality_traits: List[str] = Field(default_factory=list)
    motivations: List[str] = Field(default_factory=list)
    fears: List[str] = Field(default_factory=list)
    speech_style: Dict[str, Any] = Field(default_factory=dict)
    relationship_map: Dict[str, Any] = Field(default_factory=dict)
    visual_design: Dict[str, Any] = Field(default_factory=dict)
    color_keys: List[str] = Field(default_factory=list)
    recurring_props: List[str] = Field(default_factory=list)
    do_not_change: List[str] = Field(default_factory=list)
    current_status: Dict[str, Any] = Field(default_factory=dict)
    canon_notes: Optional[str] = None


class StyleBibleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_code: str
    style_code: str
    title: str
    frame_rate: float = Field(default=24.0, gt=0)
    screenplay_rules: Dict[str, Any] = Field(default_factory=dict)
    dialogue_rules: Dict[str, Any] = Field(default_factory=dict)
    editing_rules: Dict[str, Any] = Field(default_factory=dict)
    cinematography_rules: Dict[str, Any] = Field(default_factory=dict)
    music_rules: Dict[str, Any] = Field(default_factory=dict)
    sfx_rules: Dict[str, Any] = Field(default_factory=dict)
    vfx_rules: Dict[str, Any] = Field(default_factory=dict)
    pacing_rules: Dict[str, Any] = Field(default_factory=dict)
    emotional_rules: Dict[str, Any] = Field(default_factory=dict)
    negative_rules: List[str] = Field(default_factory=list)
    is_active: bool = True


class ConsistencyCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_code: str
    script: Dict[str, Any]
    record: bool = Field(
        default=True, description="Persist the outcome as a continuity check."
    )


class WritebackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_code: str
    memory_code: str
    approved: Dict[str, Any]


# -- helpers ----------------------------------------------------------------
def _series(session: Session, series_code: str) -> Series:
    row = session.scalar(select(Series).where(Series.series_code == series_code))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown series {series_code!r}"
        )
    return row


# -- memory bundles ---------------------------------------------------------
@router.get("/bundles/agent/{agent_code}")
def get_memory_bundle(
    agent_code: str,
    episode_code: Optional[str] = Query(None),
    series_code: Optional[str] = Query(None),
    session: Session = Depends(db_session),
):
    """Everything `agent_code` must read before it produces anything.

    Pass `episode_code` for the full bundle. `series_code` alone yields series
    canon, characters and the style bible, for agents working above an episode.
    """
    if not episode_code and not series_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide episode_code or series_code",
        )
    service = MemoryBundleService(session)
    try:
        if episode_code:
            bundle = service.build(
                agent_code=agent_code, episode=resolve_episode(session, episode_code)
            )
        else:
            bundle = service.build(
                agent_code=agent_code, series=_series(session, series_code)
            )
    except MultipleActiveStyleBiblesError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return bundle.as_dict()


# -- memory documents -------------------------------------------------------
@router.post("/documents", status_code=status.HTTP_201_CREATED)
def create_memory_document(
    body: MemoryDocumentCreate, session: Session = Depends(db_session)
):
    if session.scalar(
        select(MemoryDocument).where(MemoryDocument.memory_code == body.memory_code)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Memory document {body.memory_code!r} already exists",
        )

    if body.episode_code:
        episode = resolve_episode(session, body.episode_code)
        scope_type, scope_id = (
            ("episode", episode.id)
            if body.memory_type == "episode_memory"
            else ("season", episode.season_id)
        )
    elif body.series_code:
        scope_type, scope_id = "series", _series(session, body.series_code).id
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide series_code or episode_code",
        )

    try:
        validate_scope(body.memory_type, scope_type)
    except InvalidMemoryScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    row = MemoryDocument(
        memory_code=body.memory_code,
        memory_type=body.memory_type,
        scope_type=scope_type,
        scope_id=scope_id,
        title=body.title,
        summary=body.summary,
        content_json=body.content_json,
    )
    session.add(row)
    session.commit()
    return {"memory_code": row.memory_code, "scope_type": scope_type, "version": row.version}


# -- character profiles -----------------------------------------------------
@router.post("/characters", status_code=status.HTTP_201_CREATED)
def create_character_profile(
    body: CharacterProfileCreate, session: Session = Depends(db_session)
):
    series = _series(session, body.series_code)
    existing = session.scalar(
        select(CharacterProfile).where(
            CharacterProfile.series_id == series.id,
            CharacterProfile.character_code == body.character_code,
        )
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Character {body.character_code!r} already exists in this series",
        )
    payload = body.model_dump(exclude={"series_code"})
    row = CharacterProfile(series_id=series.id, **payload)
    session.add(row)
    session.commit()
    return {"character_code": row.character_code, "version": row.version}


@router.get("/characters/{series_code}")
def list_character_profiles(series_code: str, session: Session = Depends(db_session)):
    series = _series(session, series_code)
    rows = MemoryBundleService(session).character_profiles(series.id)
    return [
        {
            "character_code": r.character_code,
            "display_name": r.display_name,
            "version": r.version,
            "current_status": r.current_status,
        }
        for r in rows
    ]


# -- style bibles -----------------------------------------------------------
@router.post("/style-bibles", status_code=status.HTTP_201_CREATED)
def create_style_bible(body: StyleBibleCreate, session: Session = Depends(db_session)):
    series = _series(session, body.series_code)
    if session.scalar(
        select(StyleBible).where(
            StyleBible.series_id == series.id, StyleBible.style_code == body.style_code
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Style bible {body.style_code!r} already exists in this series",
        )

    if body.is_active:
        # Exactly one active bible per series. Deactivate the incumbent rather
        # than rejecting, so activating a new version is a single call.
        for row in session.scalars(
            select(StyleBible).where(
                StyleBible.series_id == series.id, StyleBible.is_active.is_(True)
            )
        ).all():
            row.is_active = False

    payload = body.model_dump(exclude={"series_code"})
    row = StyleBible(series_id=series.id, **payload)
    session.add(row)
    session.commit()
    return {"style_code": row.style_code, "is_active": row.is_active, "version": row.version}


# -- consistency ------------------------------------------------------------
@router.post("/consistency-check")
def run_consistency_check(
    body: ConsistencyCheckRequest, session: Session = Depends(db_session)
):
    """Audit a draft script against canon.

    A pass means nothing mechanically checkable failed. It is not a full
    clearance: `not_mechanically_checked` carries the rules only the QC agent
    can judge.
    """
    episode = resolve_episode(session, body.episode_code)
    service = MemoryBundleService(session)
    try:
        bible = service.active_style_bible(episode.series_id)
    except MultipleActiveStyleBiblesError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    guard = ConsistencyGuardService(
        profiles=service.character_profiles(episode.series_id), style_bible=bible
    )
    result = guard.validate_script(body.script)

    if body.record:
        record_continuity_check(
            session, episode=episode, check_type="script_consistency", result=result
        )
        session.commit()
    return result.as_dict()


@router.get("/continuity-checks/{episode_code}")
def list_continuity_checks(episode_code: str, session: Session = Depends(db_session)):
    episode = resolve_episode(session, episode_code)
    rows = session.scalars(
        select(ContinuityCheck)
        .where(ContinuityCheck.episode_id == episode.id)
        .order_by(ContinuityCheck.created_at.desc())
    ).all()
    return [
        {
            "check_type": r.check_type,
            "status": r.status,
            "passed": r.passed,
            "issue_count": len(r.issues),
            "fixes_required": r.fixes_required,
            "not_mechanically_checked": r.not_mechanically_checked,
        }
        for r in rows
    ]


# -- writeback --------------------------------------------------------------
@router.post("/writeback")
def apply_writeback(body: WritebackRequest, session: Session = Depends(db_session)):
    """Fold an approved artifact's canon changes into memory."""
    episode = resolve_episode(session, body.episode_code)
    document = session.scalar(
        select(MemoryDocument).where(MemoryDocument.memory_code == body.memory_code)
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown memory document {body.memory_code!r}",
        )

    service = AutoWritebackService(session)
    result = service.apply(
        document=document, episode=episode, extracted=service.extract(body.approved)
    )
    return result.as_dict()
