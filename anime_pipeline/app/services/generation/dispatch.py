"""Running a generation, and recording what produced what.

Every completed generation writes an `Artifact` carrying the provider, the
model and the template key. That provenance is not bookkeeping: when an
episode turns out to contradict canon three episodes later, the first question
is which model and which prompt version wrote it, and an artifact with no
provenance cannot answer.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.models import Artifact, Episode, User, Workspace
from app.services.audit.audit_service import ACTION_GENERATION_DISPATCHED, AuditService
from app.services.generation.prompts.builders import CanonPromptBuilder
from app.services.generation.prompts.templates import get_template
from app.services.generation.providers.base import Completion, ProviderNotConfiguredError
from app.services.generation.providers.registry import ProviderResolver
from app.services.jobs.job_queue import JobQueue

logger = logging.getLogger(__name__)

JOB_GENERATE_TEXT = "generation.text"


@dataclass
class GenerationResult:
    completion: Completion
    artifact_id: Optional[uuid.UUID]
    template_key: str
    prompt_chars: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": str(self.artifact_id) if self.artifact_id else None,
            "template_key": self.template_key,
            "prompt_chars": self.prompt_chars,
            **self.completion.as_dict(),
        }


class GenerationDispatchService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.builder = CanonPromptBuilder(session)
        self.resolver = ProviderResolver(session)

    def preview_prompt(
        self, *, template_key: str, episode: Episode, extra: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Render without calling anything.

        The cheapest possible way to review a prompt change: no tokens, no
        latency, and the canon block is the real one.
        """
        system, prompt = self.builder.build(
            template_key=template_key, episode=episode, extra=extra
        )
        return {
            "template_key": template_key,
            "system": system,
            "prompt": prompt,
            "prompt_chars": len(prompt),
        }

    def generate(
        self,
        *,
        template_key: str,
        episode: Episode,
        provider_key: Optional[str] = None,
        model: Optional[str] = None,
        workspace: Optional[Workspace] = None,
        actor: Optional[User] = None,
        extra: Optional[Dict[str, Any]] = None,
        persist_artifact: bool = True,
        **provider_kwargs: Any,
    ) -> GenerationResult:
        get_template(template_key)  # fail fast on an unknown key
        system, prompt = self.builder.build(
            template_key=template_key, episode=episode, extra=extra
        )

        provider, resolved_model = self.resolver.resolve(
            provider_key=provider_key,
            model=model,
            workspace_id=workspace.id if workspace else None,
        )
        completion = provider.generate(
            prompt=prompt, model=resolved_model, system=system, **provider_kwargs
        )

        artifact_id = None
        if persist_artifact:
            artifact = Artifact(
                episode_id=episode.id,
                artifact_type=template_key,
                # Unique per artifact and readable in a listing. The random
                # suffix is what lets the same template run twice for one
                # episode -- a regeneration is a new artifact, not an
                # overwrite, so the previous version stays reviewable.
                artifact_code=f"{episode.episode_code}_{template_key}_{uuid.uuid4().hex[:8]}",
                title=f"{template_key} for {episode.episode_code}",
                mime_type="text/plain",
                content_json={"text": completion.text},
                meta={
                    "provider": completion.provider,
                    "model": completion.model,
                    "template_key": template_key,
                    "usage": completion.usage,
                    "stop_reason": completion.stop_reason,
                },
            )
            self.session.add(artifact)
            self.session.flush()
            artifact_id = artifact.id

        AuditService(self.session).record(
            action=ACTION_GENERATION_DISPATCHED,
            entity_type="artifact",
            entity_id=str(artifact_id) if artifact_id else None,
            actor=actor,
            workspace=workspace,
            message=f"{template_key} for {episode.episode_code} via {completion.provider}",
            metadata={
                "provider": completion.provider,
                "model": completion.model,
                "template_key": template_key,
            },
        )

        return GenerationResult(
            completion=completion,
            artifact_id=artifact_id,
            template_key=template_key,
            prompt_chars=len(prompt),
        )

    def enqueue(
        self,
        *,
        template_key: str,
        episode: Episode,
        provider_key: Optional[str] = None,
        model: Optional[str] = None,
        workspace: Optional[Workspace] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        """Queue a generation instead of running it inline.

        The provider is resolved *now*, before queueing, so a missing API key
        is a 400 on this request rather than a job that fails three times
        overnight and reports it at breakfast.
        """
        get_template(template_key)
        self.resolver.resolve(
            provider_key=provider_key,
            model=model,
            workspace_id=workspace.id if workspace else None,
        )
        return JobQueue(self.session).enqueue(
            job_type=JOB_GENERATE_TEXT,
            payload={
                "template_key": template_key,
                "episode_code": episode.episode_code,
                "provider_key": provider_key,
                "model": model,
                "workspace_slug": workspace.slug if workspace else None,
                "extra": extra or {},
            },
            workspace_id=workspace.id if workspace else None,
        )
