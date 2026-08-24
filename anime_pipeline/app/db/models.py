"""Persistence models.

Naming note: the `artifacts` table has a `metadata` column in the SQL spec, but
`metadata` is reserved on SQLAlchemy declarative classes -- declaring an
attribute by that name raises at class-definition time. Every such column is
mapped to a Python attribute named `meta` while keeping `metadata` as the
column name in the database, so the SQL schema is unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

import sqlalchemy as sa
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONColumn
from app.models.enums import (
    ApprovalStatus,
    ArtifactStatus,
    PriorityLevel,
    ProviderJobStatus,
    QCDecision,
    QCStage,
    TaskStatus,
)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _created() -> Mapped[datetime]:
    # Both defaults on purpose. The Python default gives microsecond
    # resolution, which is what makes "the latest report wins" deterministic:
    # server-side now() resolves to the second on SQLite and to the
    # transaction on Postgres, so sibling rows written together tie. The
    # server default remains for rows inserted by raw SQL or migrations.
    return mapped_column(
        sa.DateTime(timezone=True),
        default=_now,
        server_default=sa.func.now(),
        nullable=False,
    )


def _updated() -> Mapped[datetime]:
    return mapped_column(
        sa.DateTime(timezone=True),
        default=_now,
        server_default=sa.func.now(),
        onupdate=_now,
        nullable=False,
    )


class Series(Base):
    __tablename__ = "series"

    id: Mapped[uuid.UUID] = _uuid_pk()
    series_code: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    seasons: Mapped[List["Season"]] = relationship(
        back_populates="series", cascade="all, delete-orphan"
    )
    episodes: Mapped[List["Episode"]] = relationship(
        back_populates="series", cascade="all, delete-orphan"
    )


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (
        sa.UniqueConstraint("series_id", "season_number"),
        sa.UniqueConstraint("series_id", "season_code"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    series_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False
    )
    season_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    season_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(sa.String(255))
    status: Mapped[str] = mapped_column(sa.String(50), default="active", nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    series: Mapped[Series] = relationship(back_populates="seasons")
    episodes: Mapped[List["Episode"]] = relationship(
        back_populates="season", cascade="all, delete-orphan"
    )


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (sa.UniqueConstraint("season_id", "episode_number"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    series_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False
    )
    season_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False
    )
    #: Human-facing identifier ("EP01"). Every JSON contract's `episode_id`
    #: field carries this value, not the UUID primary key.
    episode_code: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    episode_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    working_title: Mapped[Optional[str]] = mapped_column(sa.String(255))
    final_title: Mapped[Optional[str]] = mapped_column(sa.String(255))
    status: Mapped[str] = mapped_column(sa.String(50), default="idea", nullable=False)
    current_stage: Mapped[str] = mapped_column(
        sa.String(50), default="direction", nullable=False
    )
    runtime_target_minutes: Mapped[Optional[int]] = mapped_column(sa.Integer)
    publish_target_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    published_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    priority: Mapped[PriorityLevel] = mapped_column(
        SAEnum(PriorityLevel, name="priority_level"),
        default=PriorityLevel.normal,
        nullable=False,
    )
    main_hook: Mapped[Optional[str]] = mapped_column(sa.Text)
    core_conflict: Mapped[Optional[str]] = mapped_column(sa.Text)
    emotional_arc: Mapped[Optional[str]] = mapped_column(sa.Text)
    ending_beat: Mapped[Optional[str]] = mapped_column(sa.Text)
    meta: Mapped[dict] = mapped_column("metadata", JSONColumn, default=dict, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    series: Mapped[Series] = relationship(back_populates="episodes")
    season: Mapped[Season] = relationship(back_populates="episodes")
    tasks: Mapped[List["Task"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
    artifacts: Mapped[List["Artifact"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
    asset_requests: Mapped[List["AssetRequest"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
    master_qc_reports: Mapped[List["MasterQCReport"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
    scene_editor_qc_notes: Mapped[List["SceneEditorQCNote"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
    blockers: Mapped[List["EpisodeBlocker"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    agent_code: Mapped[str] = mapped_column(sa.String(128), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    role_description: Mapped[Optional[str]] = mapped_column(sa.Text)
    system_prompt_version: Mapped[Optional[str]] = mapped_column(sa.String(64))
    allowed_tools: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    config: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    tasks: Mapped[List["Task"]] = relationship(
        back_populates="agent", foreign_keys="Task.agent_id"
    )
    master_qc_reports: Mapped[List["MasterQCReport"]] = relationship(
        back_populates="reviewer_agent"
    )
    scene_editor_qc_notes: Mapped[List["SceneEditorQCNote"]] = relationship(
        back_populates="created_by_agent"
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    episode_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    workflow_name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    workflow_version: Mapped[Optional[str]] = mapped_column(sa.String(64))
    status: Mapped[str] = mapped_column(sa.String(50), default="running", nullable=False)
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    context: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)

    tasks: Mapped[List["Task"]] = relationship(back_populates="workflow_run")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    workflow_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("workflow_runs.id", ondelete="SET NULL")
    )
    episode_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    task_code: Mapped[str] = mapped_column(sa.String(128), unique=True, nullable=False)
    task_type: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    task_category: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    #: Pipeline stage this task fulfils (`PIPELINE[*].name`). Nullable because a
    #: task may be ad hoc rather than part of the declared graph; the
    #: orchestrator only sees tasks that name a stage.
    stage: Mapped[Optional[str]] = mapped_column(sa.String(64), index=True)
    title: Mapped[Optional[str]] = mapped_column(sa.String(255))
    description: Mapped[Optional[str]] = mapped_column(sa.Text)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status"), default=TaskStatus.queued, nullable=False
    )
    priority: Mapped[PriorityLevel] = mapped_column(
        SAEnum(PriorityLevel, name="priority_level"),
        default=PriorityLevel.normal,
        nullable=False,
    )
    input_context: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    instructions: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    output_json: Mapped[Optional[dict]] = mapped_column(JSONColumn)
    output_schema_name: Mapped[Optional[str]] = mapped_column(sa.String(128))
    due_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(sa.Integer, default=2, nullable=False)
    reviewer_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("agents.id", ondelete="SET NULL")
    )
    approval_required: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    created_by_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("agents.id", ondelete="SET NULL")
    )
    meta: Mapped[dict] = mapped_column("metadata", JSONColumn, default=dict, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    episode: Mapped[Episode] = relationship(back_populates="tasks")
    workflow_run: Mapped[Optional[WorkflowRun]] = relationship(back_populates="tasks")
    agent: Mapped[Agent] = relationship(back_populates="tasks", foreign_keys=[agent_id])
    artifacts: Mapped[List["Artifact"]] = relationship(back_populates="source_task")
    master_qc_reports: Mapped[List["MasterQCReport"]] = relationship(
        back_populates="source_task"
    )
    dependencies: Mapped[List["TaskDependency"]] = relationship(
        back_populates="task",
        foreign_keys="TaskDependency.task_id",
        cascade="all, delete-orphan",
    )


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (sa.UniqueConstraint("task_id", "depends_on_task_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    task_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = _created()

    task: Mapped[Task] = relationship(back_populates="dependencies", foreign_keys=[task_id])
    depends_on: Mapped[Task] = relationship(foreign_keys=[depends_on_task_id])


class EpisodeBlocker(Base):
    """An unresolved obstacle that freezes every stage on an episode.

    Stored rather than held in memory because it outlives the request that
    raised it: a missing background asset still blocks the episode after a
    redeploy, and every worker must see the same freeze.

    Resolution is a timestamp rather than a delete, so the record of what
    stalled an episode survives for the post-mortem.
    """

    __tablename__ = "episode_blockers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    episode_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    blocker_type: Mapped[Optional[str]] = mapped_column(sa.String(64))
    severity: Mapped[str] = mapped_column(sa.String(32), default="medium", nullable=False)
    raised_by_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("agents.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    episode: Mapped["Episode"] = relationship(back_populates="blockers")

    @property
    def is_active(self) -> bool:
        return self.resolved_at is None


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    episode_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    source_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="SET NULL")
    )
    artifact_type: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    artifact_code: Mapped[str] = mapped_column(sa.String(128), unique=True, nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    status: Mapped[ArtifactStatus] = mapped_column(
        SAEnum(ArtifactStatus, name="artifact_status"),
        default=ArtifactStatus.draft,
        nullable=False,
    )
    title: Mapped[Optional[str]] = mapped_column(sa.String(255))
    uri: Mapped[Optional[str]] = mapped_column(sa.Text)
    mime_type: Mapped[Optional[str]] = mapped_column(sa.String(128))
    file_size_bytes: Mapped[Optional[int]] = mapped_column(sa.BigInteger)
    content_json: Mapped[Optional[dict]] = mapped_column(JSONColumn)
    meta: Mapped[dict] = mapped_column("metadata", JSONColumn, default=dict, nullable=False)
    created_by_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("agents.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    episode: Mapped[Episode] = relationship(back_populates="artifacts")
    source_task: Mapped[Optional[Task]] = relationship(back_populates="artifacts")
    approvals: Mapped[List["Approval"]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan"
    )


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="SET NULL")
    )
    reviewer_agent_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus, name="approval_status"),
        default=ApprovalStatus.pending,
        nullable=False,
    )
    notes: Mapped[Optional[str]] = mapped_column(sa.Text)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    artifact: Mapped[Artifact] = relationship(back_populates="approvals")


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="CASCADE")
    )
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("agents.id", ondelete="SET NULL")
    )
    level: Mapped[str] = mapped_column(sa.String(32), default="info", nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    created_at: Mapped[datetime] = _created()


class ProviderJob(Base):
    __tablename__ = "provider_jobs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="CASCADE")
    )
    provider_name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    job_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    external_job_id: Mapped[Optional[str]] = mapped_column(sa.String(255))
    status: Mapped[ProviderJobStatus] = mapped_column(
        SAEnum(ProviderJobStatus, name="provider_job_status"),
        default=ProviderJobStatus.queued,
        nullable=False,
    )
    request_payload: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    response_payload: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    callback_payload: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    error_message: Mapped[Optional[str]] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AssetRequest(Base):
    __tablename__ = "asset_requests"

    id: Mapped[uuid.UUID] = _uuid_pk()
    episode_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    source_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="SET NULL")
    )
    asset_request_code: Mapped[str] = mapped_column(
        sa.String(128), unique=True, nullable=False
    )
    asset_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    asset_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    scene_refs: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    priority: Mapped[PriorityLevel] = mapped_column(
        SAEnum(PriorityLevel, name="priority_level"),
        default=PriorityLevel.normal,
        nullable=False,
    )
    reusable: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(50), default="needed", nullable=False)
    spec: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    output_artifact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("artifacts.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    episode: Mapped[Episode] = relationship(back_populates="asset_requests")


class MasterQCReport(Base):
    __tablename__ = "master_qc_reports"
    __table_args__ = (
        sa.CheckConstraint(
            "overall_score >= 0 AND overall_score <= 100", name="ck_qc_overall_score"
        ),
        sa.CheckConstraint(
            "anime_style_score >= 0 AND anime_style_score <= 100",
            name="ck_qc_anime_style_score",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    master_qc_report_id: Mapped[str] = mapped_column(
        sa.String(128), unique=True, nullable=False
    )
    episode_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    source_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="SET NULL")
    )
    source_artifact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("artifacts.id", ondelete="SET NULL")
    )
    reviewer_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("agents.id", ondelete="SET NULL")
    )
    qc_stage: Mapped[QCStage] = mapped_column(
        SAEnum(QCStage, name="qc_stage_enum"), nullable=False
    )
    qc_type: Mapped[str] = mapped_column(
        sa.String(64), default="master_qc", nullable=False
    )
    status: Mapped[str] = mapped_column(sa.String(64), default="pending", nullable=False)
    overall_score: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    anime_style_score: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    publish_ready: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    critical_issues: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    required_fixes_before_publish: Mapped[list] = mapped_column(
        JSONColumn, default=list, nullable=False
    )
    optional_polish_suggestions: Mapped[list] = mapped_column(
        JSONColumn, default=list, nullable=False
    )
    final_notes: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    sections: Mapped[dict] = mapped_column(JSONColumn, nullable=False)
    final_decision: Mapped[Optional[QCDecision]] = mapped_column(
        SAEnum(QCDecision, name="qc_decision_enum")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    episode: Mapped[Episode] = relationship(back_populates="master_qc_reports")
    source_task: Mapped[Optional[Task]] = relationship(back_populates="master_qc_reports")
    reviewer_agent: Mapped[Optional[Agent]] = relationship(back_populates="master_qc_reports")
    scene_qc_notes: Mapped[List["SceneEditorQCNote"]] = relationship(
        back_populates="qc_report", cascade="all, delete-orphan"
    )


class SceneEditorQCNote(Base):
    __tablename__ = "scene_editor_qc_notes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    qc_report_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("master_qc_reports.id", ondelete="CASCADE")
    )
    episode_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    shot_id: Mapped[Optional[str]] = mapped_column(sa.String(128))
    timecode: Mapped[Optional[str]] = mapped_column(sa.String(32))
    #: Required so that a note quoted in frames is unambiguous. Without it,
    #: "extend by 8 frames" means different durations at 24 vs 30 fps.
    frame_rate: Mapped[float] = mapped_column(
        sa.Float, default=24.0, nullable=False, server_default=sa.text("24.0")
    )
    issue_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    severity: Mapped[str] = mapped_column(sa.String(32), default="medium", nullable=False)
    issue: Mapped[str] = mapped_column(sa.Text, nullable=False)
    why_it_hurts: Mapped[Optional[str]] = mapped_column(sa.Text)
    current_duration_frames: Mapped[Optional[int]] = mapped_column(sa.Integer)
    recommended_duration_frames: Mapped[Optional[int]] = mapped_column(sa.Integer)
    fix_note: Mapped[Optional[str]] = mapped_column(sa.Text)
    mandatory_fix: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    resolved: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    assigned_to: Mapped[Optional[str]] = mapped_column(sa.String(255))
    category: Mapped[Optional[str]] = mapped_column(sa.String(64))
    created_by_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("agents.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    qc_report: Mapped[Optional[MasterQCReport]] = relationship(back_populates="scene_qc_notes")
    episode: Mapped[Episode] = relationship(back_populates="scene_editor_qc_notes")
    created_by_agent: Mapped[Optional[Agent]] = relationship(
        back_populates="scene_editor_qc_notes"
    )
