"""Selecting a media provider.

Same resolution order as the text registry -- explicit argument, workspace
config profile, environment, then the mock -- so a deployment with nothing
configured still runs end to end and produces obviously-fake asset URLs rather
than failing at import.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, Optional, Type

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ConfigProfile
from app.services.generation.providers.media_base import (
    AUDIO,
    IMAGE,
    STATUS_COMPLETED,
    VIDEO,
    MediaProvider,
    MediaResult,
    MediaSubmission,
    ProviderNotConfiguredError,
)
from app.services.generation.providers.muapi import MuApiProvider

#: The config profile key a workspace uses to choose its media provider.
MEDIA_PROFILE_KEY = "media.default"


class MockMediaProvider(MediaProvider):
    """Deterministic placeholders. Costs nothing, reaches nothing.

    Returns a completed result immediately: there is no useful "pending" state
    to simulate, and a mock that made callers poll would mostly be testing the
    mock.
    """

    provider_key = "mock"
    default_model = "mock-media-v1"
    supported_kinds = (IMAGE, VIDEO, AUDIO)

    _EXTENSIONS = {IMAGE: "png", VIDEO: "mp4", AUDIO: "mp3"}

    def __init__(self, **_: Any) -> None:
        self._jobs: Dict[str, MediaResult] = {}

    def submit(
        self, *, prompt: str, kind: str = IMAGE, model: Optional[str] = None, **params: Any
    ) -> MediaSubmission:
        model_id = model or self.default_model
        digest = hashlib.sha256(f"{kind}:{model_id}:{prompt}".encode()).hexdigest()[:16]
        request_id = f"mock-{digest}"
        extension = self._EXTENSIONS.get(kind, "bin")
        self._jobs[request_id] = MediaResult(
            request_id=request_id,
            provider=self.provider_key,
            model=model_id,
            status=STATUS_COMPLETED,
            outputs=[f"https://example.invalid/mock/{request_id}.{extension}"],
            cost_usd=0.0,
        )
        return MediaSubmission(
            request_id=request_id, provider=self.provider_key, model=model_id, raw={}
        )

    def poll(self, request_id: str) -> MediaResult:
        result = self._jobs.get(request_id)
        if result is None:
            raise KeyError(f"Unknown mock job {request_id!r}")
        return result


PROVIDERS: Dict[str, Type[MediaProvider]] = {
    MockMediaProvider.provider_key: MockMediaProvider,
    MuApiProvider.provider_key: MuApiProvider,
}


class UnknownMediaProviderError(ValueError):
    """Raised when a media provider key has no implementation."""


def available_media_providers() -> Dict[str, Dict[str, object]]:
    """Every media provider, with whether it could actually run right now."""
    out: Dict[str, Dict[str, object]] = {}
    for key, cls in PROVIDERS.items():
        instance = cls()
        out[key] = {
            "provider_key": key,
            "default_model": instance.default_model or None,
            "kinds": list(instance.supported_kinds),
            "configured": instance.is_configured(),
        }
    return out


def build_media_provider(provider_key: str, **kwargs: Any) -> MediaProvider:
    cls = PROVIDERS.get(provider_key)
    if cls is None:
        raise UnknownMediaProviderError(
            f"Unknown media provider {provider_key!r}. Known: {sorted(PROVIDERS)}"
        )
    return cls(**kwargs)


class MediaProviderResolver:
    """Works out which media provider and model a request should use."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self.session = session

    def profile_for_workspace(self, workspace_id: Optional[uuid.UUID]) -> Dict[str, object]:
        if self.session is None or workspace_id is None:
            return {}
        row = self.session.scalar(
            select(ConfigProfile).where(
                ConfigProfile.workspace_id == workspace_id,
                ConfigProfile.profile_key == MEDIA_PROFILE_KEY,
            )
        )
        return dict(row.profile_json) if row else {}

    def resolve(
        self,
        *,
        provider_key: Optional[str] = None,
        model: Optional[str] = None,
        kind: str = IMAGE,
        workspace_id: Optional[uuid.UUID] = None,
        require_configured: bool = True,
    ) -> tuple[MediaProvider, Optional[str]]:
        profile = self.profile_for_workspace(workspace_id)
        settings = get_settings()

        chosen = (
            provider_key
            or profile.get("provider_key")
            or settings.providers.get(kind, {}).get("active")
            or MockMediaProvider.provider_key
        )
        provider = build_media_provider(str(chosen))

        if not provider.supports(kind):
            raise UnknownMediaProviderError(
                f"Provider {chosen!r} does not generate {kind}. It supports: "
                f"{sorted(provider.supported_kinds)}"
            )

        if require_configured and not provider.is_configured():
            # Before anything is queued, so a missing key surfaces on the
            # request that caused it -- and, for media, before a paid call.
            raise ProviderNotConfiguredError(
                f"Media provider {chosen!r} has no usable credentials. Configured: "
                f"{sorted(k for k, v in available_media_providers().items() if v['configured'])}"
            )

        resolved_model = model or profile.get("model") or provider.default_model or None
        return provider, resolved_model
