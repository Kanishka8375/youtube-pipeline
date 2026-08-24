"""The contract every text provider satisfies.

`ProviderRouter` has raised `ProviderNotConfiguredError` since the first
commit; this is what finally sits behind it. The interface is deliberately
narrow -- one method, one return shape -- because everything upstream
(prompt building, canon enforcement, QC) is provider-agnostic and must stay
that way.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class ProviderError(RuntimeError):
    """Base for every provider failure."""


class ProviderNotConfiguredError(ProviderError):
    """Raised when a provider is selected but its credentials are absent.

    Distinct from a transient failure: no amount of retrying fixes a missing
    API key, so the job queue treats this as terminal.
    """


class ProviderCallError(ProviderError):
    """Raised when the provider was reachable but the call failed."""


@dataclass
class Completion:
    """One provider response, normalised.

    `raw` is kept so a caller can reach provider-specific fields without this
    dataclass having to grow a union of every provider's response shape.
    """

    text: str
    provider: str
    model: str
    #: Whatever the provider reports. Shapes differ; treated as opaque.
    usage: Dict[str, Any] = field(default_factory=dict)
    stop_reason: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "usage": self.usage,
            "stop_reason": self.stop_reason,
        }


class TextProvider(ABC):
    """Turns a prompt into text."""

    #: Stable identifier used in config profiles and stored on artifacts.
    provider_key: str = "base"
    #: Used when a caller does not name one.
    default_model: str = ""

    @abstractmethod
    def generate(
        self,
        *,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 16000,
        **kwargs: Any,
    ) -> Completion:
        raise NotImplementedError

    def is_configured(self) -> bool:
        """Whether a real call would work right now.

        Checked before enqueueing so a misconfiguration surfaces at the request
        that caused it, rather than as a job that fails three times overnight.
        """
        return True


def env_or_none(*names: str) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None
