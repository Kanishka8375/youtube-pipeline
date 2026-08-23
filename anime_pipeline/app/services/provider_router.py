"""Provider-neutral interfaces for LLM and media generation.

No provider is wired in. `StubProvider` returns deterministic placeholders so
the orchestrator and its tests run end to end without network access or
credentials; swap in a real implementation by subclassing and registering it.
"""

from __future__ import annotations

from typing import Any, Dict, Protocol


class LLMProvider(Protocol):
    def generate(self, system_prompt: str, user_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Return the agent's structured response as a dict."""


class MediaProvider(Protocol):
    def generate_image(self, prompt: str, meta: Dict[str, Any]) -> Dict[str, Any]: ...
    def generate_video(self, prompt: str, meta: Dict[str, Any]) -> Dict[str, Any]: ...
    def generate_music(self, prompt: str, meta: Dict[str, Any]) -> Dict[str, Any]: ...


class ProviderNotConfiguredError(RuntimeError):
    """Raised when a call needs a provider that has not been configured."""


class StubLLMProvider:
    """Echoes a fixed response. Useful for wiring tests, useless in production."""

    name = "stub"

    def __init__(self, canned: Dict[str, Any] | None = None) -> None:
        self.canned = canned or {}
        self.calls: list[tuple[str, Dict[str, Any]]] = []

    def generate(self, system_prompt: str, user_payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append((system_prompt, user_payload))
        return dict(self.canned)


class StubMediaProvider:
    name = "stub"

    def _job(self, job_type: str) -> Dict[str, Any]:
        return {"provider": self.name, "job_type": job_type, "status": "queued"}

    def generate_image(self, prompt: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        return self._job("image")

    def generate_video(self, prompt: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        return self._job("video")

    def generate_music(self, prompt: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        return self._job("music")


class ProviderRouter:
    """Selects a provider per capability from config.

    Config shape mirrors the spec::

        {"providers": {"llm": {"active": "provider_a", "provider_a": {...}},
                       "image": {"active": None}}}
    """

    def __init__(
        self,
        llm: LLMProvider | None = None,
        media: MediaProvider | None = None,
        config: Dict[str, Any] | None = None,
    ) -> None:
        self.llm = llm
        self.media = media
        self.config = config or {}

    def call_llm(self, system_prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.llm is None:
            raise ProviderNotConfiguredError(
                "No LLM provider configured. Set one before running agents."
            )
        return self.llm.generate(system_prompt, payload)

    def generate_image(self, prompt: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        if self.media is None:
            raise ProviderNotConfiguredError("No media provider configured.")
        return self.media.generate_image(prompt, meta)

    def generate_video(self, prompt: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        if self.media is None:
            raise ProviderNotConfiguredError("No media provider configured.")
        return self.media.generate_video(prompt, meta)

    def generate_music(self, prompt: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        if self.media is None:
            raise ProviderNotConfiguredError("No media provider configured.")
        return self.media.generate_music(prompt, meta)
