"""Any endpoint speaking the OpenAI chat-completions shape.

Raw HTTP rather than the `openai` package: this targets a wire format, not one
vendor. The same adapter reaches OpenAI, a self-hosted vLLM or llama.cpp
server, or a gateway -- all of which implement `/chat/completions` and none of
which need a dependency added to this project.

(The Anthropic adapter uses its SDK precisely because it is *not* a wire-format
adapter -- it targets one vendor, whose SDK carries retries, typed errors and
streaming that would otherwise be rewritten here.)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from app.services.generation.providers.base import (
    Completion,
    ProviderCallError,
    ProviderNotConfiguredError,
    TextProvider,
    env_or_none,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
#: No default model. Which model exists depends entirely on the endpoint --
#: guessing one produces a 404 that reads like a bug in this code.
DEFAULT_MODEL = ""
REQUEST_TIMEOUT_SECONDS = 120.0


class OpenAICompatibleProvider(TextProvider):
    provider_key = "openai_compatible"
    default_model = DEFAULT_MODEL

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or env_or_none("OPENAI_API_KEY", "OPENAI_COMPAT_API_KEY")
        self._base_url = (
            base_url or env_or_none("OPENAI_COMPAT_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.default_model = default_model or env_or_none("OPENAI_COMPAT_MODEL") or DEFAULT_MODEL

    def is_configured(self) -> bool:
        # A local endpoint on localhost typically needs no key at all, so a
        # missing key is only disqualifying when talking to a remote host.
        if self._api_key:
            return True
        return "localhost" in self._base_url or "127.0.0.1" in self._base_url

    def generate(
        self,
        *,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 16000,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> Completion:
        model_id = model or self.default_model
        if not model_id:
            raise ProviderNotConfiguredError(
                "No model specified. Set OPENAI_COMPAT_MODEL or pass model= "
                "-- which models exist depends on the endpoint."
            )
        if not self.is_configured():
            raise ProviderNotConfiguredError(
                f"No API key for {self._base_url}. Set OPENAI_API_KEY."
            )

        try:
            import httpx
        except ImportError as exc:
            raise ProviderNotConfiguredError("httpx is required for this provider") from exc

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json={
                    "model": model_id,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 -- network layer
            raise ProviderCallError(f"Could not reach {self._base_url}: {exc}") from exc

        if response.status_code in (401, 403):
            raise ProviderNotConfiguredError(
                f"{self._base_url} rejected the credentials ({response.status_code})"
            )
        if response.status_code >= 400:
            raise ProviderCallError(
                f"{self._base_url} returned {response.status_code}: {response.text[:400]}"
            )

        try:
            data = response.json()
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            # An endpoint that answered 200 with a shape this adapter does not
            # understand is a compatibility failure, not a transport one.
            raise ProviderCallError(
                f"{self._base_url} returned an unrecognised response shape: {exc}"
            ) from exc

        return Completion(
            text=text,
            provider=self.provider_key,
            model=data.get("model", model_id),
            usage=data.get("usage", {}),
            stop_reason=choice.get("finish_reason"),
            raw={"id": data.get("id")},
        )
