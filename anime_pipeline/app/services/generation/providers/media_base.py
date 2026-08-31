"""The contract every media provider satisfies.

Media generation differs from text in one way that shapes the whole interface:
it is **slow and asynchronous**. A text completion returns in seconds and can be
awaited inside a request. A video generation takes minutes, so the provider
exposes `submit` and `poll` as separate operations and lets the job queue drive
the wait. A blocking call would hold a worker for the duration and lose all
progress if the process restarted.

The second difference is that it costs real money per call, in amounts worth
recording. `MediaResult.cost_usd` exists because "what did this episode cost to
make" is a question someone will ask, and it is unanswerable unless each call
records its own price at the time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.generation.providers.base import (  # noqa: F401 -- re-exported
    ProviderCallError,
    ProviderError,
    ProviderNotConfiguredError,
    env_or_none,
)

#: The kinds of media a provider may support. A provider declares which it can
#: do; asking for one it cannot is a configuration error, not a call failure.
IMAGE = "image"
VIDEO = "video"
AUDIO = "audio"

#: Terminal states reported by a provider for a submitted job.
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


class MediaGenerationFailedError(ProviderError):
    """The provider accepted the job and then reported that it failed.

    Terminal, deliberately. A retry re-runs a *paid* generation, and a job that
    failed on the provider's side usually fails again for the same reason. The
    budget is better spent by a human reading the error and changing the
    prompt.
    """


@dataclass
class MediaSubmission:
    """A job the provider has accepted but not yet finished."""

    request_id: str
    provider: str
    model: str
    #: Whatever the submit call returned, kept whole rather than modelled.
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MediaResult:
    """A finished generation, normalised across providers."""

    request_id: str
    provider: str
    model: str
    status: str
    #: URLs of the generated assets. Empty while pending.
    outputs: List[str] = field(default_factory=list)
    #: What this call cost, as the provider reported it. None when unknown --
    #: which is different from zero and must not be flattened into it.
    cost_usd: Optional[float] = None
    error: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in (STATUS_COMPLETED, STATUS_FAILED)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "outputs": list(self.outputs),
            "cost_usd": self.cost_usd,
            "error": self.error,
        }


class MediaProvider(ABC):
    """Turns a prompt into an image, a video or a sound."""

    #: Stable identifier used in config profiles and stored on artifacts.
    provider_key: str = "base"
    #: Used when a caller does not name one.
    default_model: str = ""
    #: Which of IMAGE/VIDEO/AUDIO this provider can produce.
    supported_kinds: tuple[str, ...] = ()

    @abstractmethod
    def submit(
        self,
        *,
        prompt: str,
        kind: str = IMAGE,
        model: Optional[str] = None,
        **params: Any,
    ) -> MediaSubmission:
        """Start a generation. Returns as soon as the provider accepts it."""
        raise NotImplementedError

    @abstractmethod
    def poll(self, request_id: str) -> MediaResult:
        """Current state of a submitted job. Never blocks."""
        raise NotImplementedError

    def is_configured(self) -> bool:
        """Whether a real call would work right now.

        Checked before enqueueing so a misconfiguration surfaces on the request
        that caused it rather than as a job that fails its whole budget.
        """
        return True

    def supports(self, kind: str) -> bool:
        return kind in self.supported_kinds
