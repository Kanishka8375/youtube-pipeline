"""Request/response models for the HTTP surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ApprovalStatus, ArtifactStatus, PriorityLevel


class EpisodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_code: str
    season_code: str
    episode_code: str
    episode_number: int = Field(ge=1)
    working_title: Optional[str] = None
    runtime_target_minutes: Optional[int] = Field(default=None, gt=0)
    priority: PriorityLevel = PriorityLevel.normal
    publish_target_at: Optional[datetime] = None


class EpisodeResponse(BaseModel):
    id: str
    series_code: str
    season_code: str
    episode_code: str
    episode_number: int
    working_title: Optional[str] = None
    final_title: Optional[str] = None
    status: str
    current_stage: str
    runtime_target_minutes: Optional[int] = None


class ArtifactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_id: str
    source_task_id: Optional[str] = None
    artifact_type: str
    artifact_code: str
    version: int = Field(default=1, ge=1)
    status: ArtifactStatus = ArtifactStatus.draft
    title: Optional[str] = None
    uri: Optional[str] = None
    mime_type: Optional[str] = None
    content_json: Optional[Dict[str, Any]] = None
    # Named `meta` rather than `metadata`: `metadata` is reserved on
    # SQLAlchemy declarative classes, and keeping one name across both layers
    # avoids a silent mismatch at the ORM boundary.
    meta: Dict[str, Any] = Field(default_factory=dict)
    created_by_agent: Optional[str] = None


class ArtifactResponse(ArtifactCreate):
    id: str


class ApprovalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    task_id: Optional[str] = None
    reviewer_agent: str
    status: ApprovalStatus = ApprovalStatus.pending
    notes: Optional[str] = None


class ApprovalResponse(ApprovalCreate):
    id: str


class AssetRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_id: str
    source_task_id: Optional[str] = None
    asset_request_code: str
    asset_type: str
    asset_name: str
    scene_refs: List[str] = Field(default_factory=list)
    priority: PriorityLevel = PriorityLevel.normal
    reusable: bool = True
    status: str = "needed"
    spec: Dict[str, Any] = Field(default_factory=dict)


class AssetRequestResponse(AssetRequestCreate):
    id: str


class WorkflowRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_id: str
    workflow_name: str
    workflow_version: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class WorkflowRunResponse(WorkflowRunCreate):
    id: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class EventIn(BaseModel):
    """A webhook or manual event fed to the orchestrator."""

    model_config = ConfigDict(extra="forbid")

    event: str
    payload: Dict[str, Any] = Field(default_factory=dict)
