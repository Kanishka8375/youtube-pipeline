"""Prompt templates, provider selection, and running a generation."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session
from app.api.routes.episodes import resolve_episode
from app.db.models import User, Workspace
from app.services.generation.dispatch import GenerationDispatchService
from app.services.generation.prompts.templates import (
    MissingTemplateVariableError,
    UnknownTemplateError,
    list_templates,
)
from app.services.generation.providers.base import (
    ProviderCallError,
    ProviderNotConfiguredError,
)
from app.services.generation.providers.registry import (
    UnknownProviderError,
    available_providers,
)

router = APIRouter()


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_key: str
    episode_code: str
    extra: Dict[str, Any] = Field(default_factory=dict)


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_key: str
    episode_code: str
    provider_key: Optional[str] = None
    model: Optional[str] = None
    workspace_slug: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)
    #: Queue it rather than blocking the request. The right default for any
    #: real provider -- a script generation takes tens of seconds.
    background: bool = True
    max_tokens: int = Field(default=16000, ge=256, le=128000)


def _workspace(session: Session, slug: Optional[str]) -> Optional[Workspace]:
    if not slug:
        return None
    workspace = session.scalar(select(Workspace).where(Workspace.slug == slug))
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown workspace {slug!r}"
        )
    return workspace


@router.get("/templates")
def get_templates():
    """Every prompt template, with the variables each needs."""
    return {"templates": list_templates()}


@router.get("/providers")
def get_providers():
    """Every provider and whether it has usable credentials right now."""
    return {"providers": available_providers()}


@router.post("/preview")
def preview(
    body: PreviewRequest,
    session: Session = Depends(db_session),
    user: User = Depends(current_user),
):
    """Render a prompt against real canon without calling a provider."""
    episode = resolve_episode(session, body.episode_code)
    try:
        return GenerationDispatchService(session).preview_prompt(
            template_key=body.template_key, episode=episode, extra=body.extra
        )
    except UnknownTemplateError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MissingTemplateVariableError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/run")
def run_generation(
    body: GenerateRequest,
    session: Session = Depends(db_session),
    user: User = Depends(current_user),
):
    episode = resolve_episode(session, body.episode_code)
    workspace = _workspace(session, body.workspace_slug)
    service = GenerationDispatchService(session)

    try:
        if body.background:
            job = service.enqueue(
                template_key=body.template_key,
                episode=episode,
                provider_key=body.provider_key,
                model=body.model,
                workspace=workspace,
                extra=body.extra,
            )
            session.commit()
            return {
                "mode": "queued",
                "job_id": str(job.id),
                "job_type": job.job_type,
                "status": job.status,
            }

        result = service.generate(
            template_key=body.template_key,
            episode=episode,
            provider_key=body.provider_key,
            model=body.model,
            workspace=workspace,
            actor=user,
            extra=body.extra,
            max_tokens=body.max_tokens,
        )
        session.commit()
        return {"mode": "inline", **result.as_dict()}

    except UnknownTemplateError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (UnknownProviderError, MissingTemplateVariableError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProviderNotConfiguredError as exc:
        # 400, not 500: the deployment is missing configuration, which is the
        # caller's problem to fix, and retrying will not help.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProviderCallError as exc:
        # 502: this service is fine, the upstream one is not.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
