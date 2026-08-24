"""Inter-agent messages that are not task envelopes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Severity


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ActorRef(BaseModel):
    """Who created or owns something: an agent, or a human operator."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["agent", "human", "system"] = "agent"
    id: str


class HandoffMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_type: Literal["handoff"] = "handoff"
    from_agent: str
    to_agent: str
    episode_id: str
    task_id: str
    summary: str
    artifacts: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_now)


class ReviewRequestMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_type: Literal["review_request"] = "review_request"
    from_agent: str
    to_agent: str
    episode_id: str
    artifact_id: str
    review_scope: List[str] = Field(default_factory=list)
    deadline: Optional[datetime] = None
    timestamp: datetime = Field(default_factory=_now)


class BlockerAlertMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_type: Literal["blocker_alert"] = "blocker_alert"
    from_agent: str
    to_agent: str
    episode_id: str
    severity: Severity = Severity.medium
    blocker_type: str
    description: str
    suggested_options: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_now)


class ApprovalMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_type: Literal["approval"] = "approval"
    from_agent: str
    to_agent: str
    episode_id: str
    artifact_id: str
    status: str
    notes: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_now)
