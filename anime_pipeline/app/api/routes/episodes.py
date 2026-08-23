"""Episode CRUD. `episode_code` is the identifier every JSON contract uses."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.db.models import Episode, Season, Series
from app.models.api import EpisodeCreate, EpisodeResponse

router = APIRouter()


def _to_response(episode: Episode) -> EpisodeResponse:
    return EpisodeResponse(
        id=str(episode.id),
        series_code=episode.series.series_code,
        season_code=episode.season.season_code,
        episode_code=episode.episode_code,
        episode_number=episode.episode_number,
        working_title=episode.working_title,
        final_title=episode.final_title,
        status=episode.status,
        current_stage=episode.current_stage,
        runtime_target_minutes=episode.runtime_target_minutes,
    )


def resolve_episode(session: Session, episode_code: str) -> Episode:
    """Translate the human episode code used in JSON contracts to a row."""
    episode = session.scalar(select(Episode).where(Episode.episode_code == episode_code))
    if episode is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown episode {episode_code!r}"
        )
    return episode


@router.post("/", response_model=EpisodeResponse, status_code=status.HTTP_201_CREATED)
def create_episode(body: EpisodeCreate, session: Session = Depends(db_session)):
    series = session.scalar(select(Series).where(Series.series_code == body.series_code))
    if series is None:
        series = Series(series_code=body.series_code, title=body.series_code)
        session.add(series)
        session.flush()

    season = session.scalar(
        select(Season).where(
            Season.series_id == series.id, Season.season_code == body.season_code
        )
    )
    if season is None:
        season = Season(
            series_id=series.id, season_code=body.season_code, season_number=1
        )
        session.add(season)
        session.flush()

    if session.scalar(select(Episode).where(Episode.episode_code == body.episode_code)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Episode {body.episode_code!r} already exists",
        )

    episode = Episode(
        series_id=series.id,
        season_id=season.id,
        episode_code=body.episode_code,
        episode_number=body.episode_number,
        working_title=body.working_title,
        runtime_target_minutes=body.runtime_target_minutes,
        priority=body.priority,
        publish_target_at=body.publish_target_at,
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)
    return _to_response(episode)


@router.get("/", response_model=List[EpisodeResponse])
def list_episodes(session: Session = Depends(db_session)):
    return [_to_response(e) for e in session.scalars(select(Episode)).all()]


@router.get("/{episode_code}", response_model=EpisodeResponse)
def get_episode(episode_code: str, session: Session = Depends(db_session)):
    return _to_response(resolve_episode(session, episode_code))
