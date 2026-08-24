"""Claude, via the official Anthropic SDK.

Uses the SDK rather than raw HTTP against `/v1/messages`. The SDK carries the
retry policy, the typed error hierarchy this module maps onto its own, and the
streaming helper that keeps large `max_tokens` from hitting request timeouts --
all of which would otherwise be reimplemented here, worse.

Two API details that a version written from memory tends to get wrong:

- **`budget_tokens` is gone.** Current models take
  `thinking={"type": "adaptive"}` and control depth with `output_config.effort`.
  Sending `budget_tokens` to Opus 5 is a 400, not a deprecation warning.
- **Streaming is required for large `max_tokens`.** Above ~16k the SDK asks for
  `.stream()`; `generate` switches automatically rather than failing.
"""

from __future__ import annotations

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

#: Default model. Opus 5 unless a caller names another -- never downgrade for
#: cost on the caller's behalf; that is their decision to make.
DEFAULT_MODEL = "claude-opus-5"

#: Above this, use the streaming API. The SDK enforces roughly this boundary
#: itself; crossing it on a non-streaming call raises rather than truncating.
STREAMING_THRESHOLD_TOKENS = 16_000

#: Effort replaces the old thinking budget. `high` is the default; `xhigh` and
#: `max` cost more for work where correctness beats latency.
VALID_EFFORT = frozenset({"low", "medium", "high", "xhigh", "max"})


class AnthropicProvider(TextProvider):
    provider_key = "anthropic"
    default_model = DEFAULT_MODEL

    def __init__(self, *, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or env_or_none("ANTHROPIC_API_KEY")
        self._client = None

    def is_configured(self) -> bool:
        # An unset ANTHROPIC_API_KEY does not always mean no credentials -- the
        # SDK also resolves ANTHROPIC_AUTH_TOKEN and an `ant auth login`
        # profile on disk. Report configured if any of those could apply, and
        # let the first real call produce the authoritative answer.
        if self._api_key or env_or_none("ANTHROPIC_AUTH_TOKEN"):
            return True
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        from pathlib import Path

        return (Path.home() / ".config" / "anthropic").exists()

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderNotConfiguredError(
                "The anthropic package is not installed. `pip install anthropic`."
            ) from exc

        # Zero-arg construction when no explicit key: the SDK then resolves
        # ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or a stored auth profile in
        # that order. Passing api_key=None explicitly would defeat that.
        self._client = (
            anthropic.Anthropic(api_key=self._api_key) if self._api_key else anthropic.Anthropic()
        )
        return self._client

    def generate(
        self,
        *,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 16000,
        effort: str = "high",
        thinking: bool = True,
        **kwargs: Any,
    ) -> Completion:
        if effort not in VALID_EFFORT:
            raise ValueError(f"effort must be one of {sorted(VALID_EFFORT)}, got {effort!r}")

        client = self._get_client()
        model_id = model or self.default_model

        request: Dict[str, Any] = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": effort},
        }
        if system:
            request["system"] = system
        if thinking:
            # Adaptive, not a token budget: the model decides how much to think.
            request["thinking"] = {"type": "adaptive"}

        try:
            if max_tokens > STREAMING_THRESHOLD_TOKENS:
                with client.messages.stream(**request) as stream:
                    message = stream.get_final_message()
            else:
                message = client.messages.create(**request)
        except Exception as exc:  # noqa: BLE001 -- mapped onto this module's hierarchy below
            raise self._translate(exc) from exc

        # stop_reason must be checked before reading content: a safety decline
        # returns HTTP 200 with a refusal, not an exception.
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None)
            raise ProviderCallError(
                f"Claude declined this request (category={category!r}). "
                "The prompt likely needs rewording."
            )

        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
        usage = message.usage
        return Completion(
            text=text,
            provider=self.provider_key,
            model=message.model,
            usage={
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            },
            stop_reason=message.stop_reason,
            raw={"id": getattr(message, "id", None)},
        )

    def _translate(self, exc: Exception) -> Exception:
        """Map SDK exceptions onto this module's hierarchy.

        The split that matters is retryable vs not: the job queue burns a retry
        on `ProviderCallError` and gives up immediately on
        `ProviderNotConfiguredError`, because no key will appear by waiting.
        """
        try:
            import anthropic
        except ImportError:
            return ProviderCallError(str(exc))

        if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return ProviderNotConfiguredError(f"Anthropic rejected the credentials: {exc}")
        if isinstance(exc, anthropic.NotFoundError):
            return ProviderCallError(f"Unknown model or endpoint: {exc}")
        if isinstance(exc, anthropic.RateLimitError):
            return ProviderCallError(f"Rate limited by Anthropic: {exc}")
        if isinstance(exc, anthropic.APIConnectionError):
            return ProviderCallError(f"Could not reach Anthropic: {exc}")
        if isinstance(exc, anthropic.APIStatusError):
            return ProviderCallError(f"Anthropic returned {exc.status_code}: {exc}")
        return ProviderCallError(f"{type(exc).__name__}: {exc}")
