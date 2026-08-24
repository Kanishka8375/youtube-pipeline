"""Selecting a provider.

Resolution order, most specific first: an explicit argument, then the
workspace's `llm.default` config profile, then `ANIME_LLM_PROVIDER`, then the
mock. The mock last means a deployment with nothing configured still runs --
it just produces obviously-fake text rather than failing at import.
"""

from __future__ import annotations

import uuid
from typing import Dict, Optional, Type

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ConfigProfile
from app.services.generation.providers.anthropic_provider import AnthropicProvider
from app.services.generation.providers.base import (
    ProviderNotConfiguredError,
    TextProvider,
)
from app.services.generation.providers.mock import MockTextProvider
from app.services.generation.providers.openai_compatible import OpenAICompatibleProvider

#: The config profile key a workspace uses to choose its provider.
LLM_PROFILE_KEY = "llm.default"

PROVIDERS: Dict[str, Type[TextProvider]] = {
    MockTextProvider.provider_key: MockTextProvider,
    AnthropicProvider.provider_key: AnthropicProvider,
    OpenAICompatibleProvider.provider_key: OpenAICompatibleProvider,
}


class UnknownProviderError(ValueError):
    """Raised when a provider key has no implementation."""


def available_providers() -> Dict[str, Dict[str, object]]:
    """Every provider, with whether it could actually run right now."""
    out: Dict[str, Dict[str, object]] = {}
    for key, cls in PROVIDERS.items():
        instance = cls()
        out[key] = {
            "provider_key": key,
            "default_model": instance.default_model or None,
            "configured": instance.is_configured(),
        }
    return out


def build_provider(provider_key: str, **kwargs) -> TextProvider:
    cls = PROVIDERS.get(provider_key)
    if cls is None:
        raise UnknownProviderError(
            f"Unknown provider {provider_key!r}. Known: {sorted(PROVIDERS)}"
        )
    return cls(**kwargs)


class ProviderResolver:
    """Works out which provider and model a request should use."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self.session = session

    def profile_for_workspace(self, workspace_id: Optional[uuid.UUID]) -> Dict[str, object]:
        if self.session is None or workspace_id is None:
            return {}
        row = self.session.scalar(
            select(ConfigProfile).where(
                ConfigProfile.workspace_id == workspace_id,
                ConfigProfile.profile_key == LLM_PROFILE_KEY,
            )
        )
        return dict(row.profile_json) if row else {}

    def resolve(
        self,
        *,
        provider_key: Optional[str] = None,
        model: Optional[str] = None,
        workspace_id: Optional[uuid.UUID] = None,
        require_configured: bool = True,
    ) -> tuple[TextProvider, Optional[str]]:
        profile = self.profile_for_workspace(workspace_id)
        settings = get_settings()

        chosen = (
            provider_key
            or profile.get("provider_key")
            or settings.providers["llm"]["active"]
            or MockTextProvider.provider_key
        )
        provider = build_provider(str(chosen))

        if require_configured and not provider.is_configured():
            # Checked here, before any work is queued, so a missing key shows
            # up on the request that caused it instead of as a job that fails
            # its whole retry budget overnight.
            raise ProviderNotConfiguredError(
                f"Provider {chosen!r} has no usable credentials. "
                f"Configured providers: "
                f"{sorted(k for k, v in available_providers().items() if v['configured'])}"
            )

        resolved_model = model or profile.get("model") or provider.default_model or None
        return provider, resolved_model
