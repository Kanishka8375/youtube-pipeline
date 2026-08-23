"""The canonical task envelope every agent handoff travels in."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ApprovalStatus, PriorityLevel, TaskCategory, TaskStatus
from app.models.message import ActorRef
from app.schemas.registry import get_schema


class ApprovalRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool = False
    status: ApprovalStatus = ApprovalStatus.pending
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class EscalationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_blocker: str = "notify_showrunner"
    on_timeout: str = "requeue_and_alert"
    on_schema_error: str = "reject_and_log"


class OutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str = "json"
    schema_name: str

    @field_validator("schema_name")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        # Fail when the task is built, not after an agent has already burned a
        # provider call producing output nothing can validate.
        get_schema(value)
        return value


class Instructions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str
    acceptance_criteria: List[str] = Field(default_factory=list)
    style_rules: List[str] = Field(default_factory=list)


class AuditInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    retry_count: int = 0
    source_event: Optional[str] = None


class TaskEnvelope(BaseModel):
    """One unit of agent work.

    `depends_on` and `blocks` reference other `task_id` values. The
    orchestrator, not the envelope, enforces them.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    episode_id: str
    season_id: Optional[str] = None
    series_id: Optional[str] = None
    workflow_id: Optional[str] = None
    task_type: str
    task_category: TaskCategory
    priority: PriorityLevel = PriorityLevel.normal
    status: TaskStatus = TaskStatus.queued
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    created_by: ActorRef
    assigned_to: ActorRef
    reviewer: Optional[ActorRef] = None
    depends_on: List[str] = Field(default_factory=list)
    blocks: List[str] = Field(default_factory=list)
    input_context: Dict[str, Any] = Field(default_factory=dict)
    instructions: Instructions
    payload: Dict[str, Any] = Field(default_factory=dict)
    output_spec: OutputSpec
    artifact_links: List[str] = Field(default_factory=list)
    approval: ApprovalRef = Field(default_factory=ApprovalRef)
    escalation: EscalationPolicy = Field(default_factory=EscalationPolicy)
    audit: AuditInfo = Field(default_factory=AuditInfo)

    @field_validator("depends_on", "blocks")
    @classmethod
    def _no_duplicates(cls, value: List[str]) -> List[str]:
        return list(dict.fromkeys(value))

    @field_validator("blocks")
    @classmethod
    def _no_self_reference(cls, value: List[str], info) -> List[str]:
        task_id = info.data.get("task_id")
        if task_id and task_id in value:
            raise ValueError(f"task {task_id} cannot block itself")
        return value
