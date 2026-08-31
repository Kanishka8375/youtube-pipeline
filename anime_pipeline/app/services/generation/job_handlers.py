"""Job handlers for the generation queue.

A handler is a plain callable taking a payload dict and returning a result
dict. That shape is what lets `JobQueue` stay ignorant of generation entirely.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Episode, Workspace
from app.services.generation.dispatch import JOB_GENERATE_TEXT, GenerationDispatchService

logger = logging.getLogger(__name__)


def _generate_text(session: Session) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def handler(payload: Dict[str, Any]) -> Dict[str, Any]:
        episode_code = payload.get("episode_code")
        episode = session.scalar(select(Episode).where(Episode.episode_code == episode_code))
        if episode is None:
            # Raised, not returned: an episode deleted between enqueue and run
            # is a real failure, and the queue should record it as one.
            raise ValueError(f"Unknown episode {episode_code!r}")

        workspace = None
        if payload.get("workspace_slug"):
            workspace = session.scalar(
                select(Workspace).where(Workspace.slug == payload["workspace_slug"])
            )

        result = GenerationDispatchService(session).generate(
            template_key=payload["template_key"],
            episode=episode,
            provider_key=payload.get("provider_key"),
            model=payload.get("model"),
            workspace=workspace,
            extra=payload.get("extra") or {},
        )
        return result.as_dict()

    return handler


def generation_handlers(session: Session) -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
    """The handler registry for this session."""
    return {JOB_GENERATE_TEXT: _generate_text(session)}
