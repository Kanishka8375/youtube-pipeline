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


class User(Base):
    """A person who can sign in.

    Everything before this commit was single-tenant and unauthenticated: any
    caller could approve a retcon or publish an episode, and nothing recorded
    who did. `RetconProposal.decided_by` was a free-text string precisely
    because there was no user to point at.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    #: Stored lower-cased by AuthService; the unique index is what makes
    #: "one account per address" true rather than merely intended.
    email: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    #: PBKDF2-SHA256, salt and digest hex-encoded. Never the password.
    password_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, default=True, server_default=sa.true(), nullable=False
    )
    is_superuser: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false(), nullable=False
    )
    created_at: Mapped[datetime] = _created()

    memberships: Mapped[List["WorkspaceMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Workspace(Base):
    """A tenant boundary: one team's channels, series and episodes."""

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False, index=True)
    settings_json: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    created_at: Mapped[datetime] = _created()

    memberships: Mapped[List["WorkspaceMembership"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMembership(Base):
    """One person's role in one workspace.

    The unique constraint is the point: without it the same user can hold two
    roles in one workspace, and "what may they do here" stops having an answer.
    """

    __tablename__ = "workspace_memberships"
    __table_args__ = (sa.UniqueConstraint("workspace_id", "user_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: owner | editor | member | viewer -- see app/services/auth/roles.py
    role: Mapped[str] = mapped_column(
        sa.String(64), default="member", server_default="member", nullable=False
    )
    created_at: Mapped[datetime] = _created()

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class BackgroundJob(Base):
    """A unit of deferred work, with its own retry budget.

    Generation calls take tens of seconds and fail for reasons no caller can
    fix by waiting. Running them inside the request means a timeout loses the
    work entirely and leaves nothing to inspect; a row survives both.
    """

    __tablename__ = "background_jobs"
    __table_args__ = (sa.Index("ix_background_jobs_runnable", "status", "scheduled_for"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_type: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    #: queued | running | retrying | completed | failed
    status: Mapped[str] = mapped_column(
        sa.String(64), default="queued", server_default="queued", nullable=False, index=True
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer, default=0, server_default="0", nullable=False
    )
    max_attempts: Mapped[int] = mapped_column(
        sa.Integer, default=3, server_default="3", nullable=False
    )
    payload_json: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(sa.Text)
    #: Ties a job back to the request that queued it; see app/core/logging.py.
    correlation_id: Mapped[Optional[str]] = mapped_column(sa.String(128), index=True)
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    #: When a retry becomes eligible. NULL means "now".
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class AuditLog(Base):
    """Who did what, appended and never updated.

    Retcon approval and publishing are the two irreversible acts in this
    system. `RetconProposal.decided_by` records a name on the proposal; this
    records the act itself, so the history survives even if the proposal is
    later deleted.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (sa.Index("ix_audit_logs_entity", "entity_type", "entity_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(sa.String(128))
    metadata_json: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    correlation_id: Mapped[Optional[str]] = mapped_column(sa.String(128), index=True)
    message: Mapped[Optional[str]] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created()


class ConfigProfile(Base):
    """Named settings, global or per-workspace.

    Which LLM answers for a series is an operational choice, not a deployment
    one. A NULL workspace_id is the global default; a workspace row overrides
    it. Secrets never land here -- only provider and model selection.
    """

    __tablename__ = "config_profiles"
    __table_args__ = (sa.UniqueConstraint("workspace_id", "profile_key"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    profile_key: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    profile_json: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


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


class MemoryDocument(Base):
    """A durable block of canon, style or episode memory.

    `scope_type` / `scope_id` are a deliberate polymorphic pair: a document
    attaches to a series, a season or an episode, and no single foreign key can
    express that. The trade is enforcement -- `scope_id` is validated by the
    service layer, not the database -- in exchange for one table instead of
    three near-identical ones.
    """

    __tablename__ = "memory_documents"
    __table_args__ = (sa.Index("ix_memory_documents_scope", "scope_type", "scope_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    memory_code: Mapped[str] = mapped_column(sa.String(128), unique=True, nullable=False)
    #: series_canon | season_memory | episode_memory | style_memory
    memory_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    scope_id: Mapped[Optional[uuid.UUID]] = mapped_column(sa.Uuid)
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(sa.Text)
    content_json: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(32), default="active", nullable=False)
    source_artifact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("artifacts.id", ondelete="SET NULL")
    )
    source_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="SET NULL")
    )
    created_by_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("agents.id", ondelete="SET NULL")
    )
    approved_by_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("agents.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    facts: Mapped[List["MemoryFact"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class MemoryFact(Base):
    """One atomic, retrievable canon fact.

    Facts are the queryable half of memory: a document holds prose an agent
    reads, a fact holds something the system can look up and compare. The
    `valid_from` / `valid_to` episode pair is what lets a fact be superseded
    without being erased, so "what was true at EP04" stays answerable.
    """

    __tablename__ = "memory_facts"
    __table_args__ = (
        sa.Index("ix_memory_facts_entity", "entity_type", "entity_key", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    memory_document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("memory_documents.id", ondelete="CASCADE"), nullable=False
    )
    fact_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    entity_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    fact_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    fact_value: Mapped[dict] = mapped_column(JSONColumn, nullable=False)
    #: immutable | stateful. An immutable fact that changes is a contradiction;
    #: a stateful one that changes is the story progressing. Without this
    #: distinction a contradiction matcher fires on every character development
    #: and gets switched off within a week. See app/services/contradiction.py.
    mutability: Mapped[str] = mapped_column(
        sa.String(16), default="immutable", server_default="immutable", nullable=False
    )
    importance: Mapped[str] = mapped_column(sa.String(32), default="normal", nullable=False)
    #: Canonical comparison form of `fact_value`, maintained by the service
    #: layer. NULL means the value has no flat form and must be compared raw;
    #: see app/services/normalisation.py.
    normalised_value: Mapped[Optional[str]] = mapped_column(sa.String(512), index=True)
    valid_from_episode_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="SET NULL")
    )
    valid_to_episode_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="SET NULL")
    )
    #: Timeline positions of `valid_from` / `valid_to`, denormalised so the
    #: matcher can order facts without a per-fact timeline query. Derived, never
    #: caller-set: TimelineService owns them and resyncs on every rebalance.
    timeline_start_order: Mapped[Optional[int]] = mapped_column(sa.Integer, index=True)
    timeline_end_order: Mapped[Optional[int]] = mapped_column(sa.Integer)
    #: Set when this fact was written to replace an earlier one. Together with
    #: `is_retcon` it makes a rewritten past auditable instead of invisible.
    supersedes_fact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("memory_facts.id", ondelete="SET NULL")
    )
    #: True only when an approved RetconProposal created this fact. Agents
    #: cannot set it: a self-declared retcon would let any draft opt out of the
    #: check it is supposed to face.
    is_retcon: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false(), nullable=False
    )
    #: Shared by every fact written under one approved retcon, so a rewrite
    #: spanning several facts can be reviewed and reverted as one unit.
    retcon_group_code: Mapped[Optional[str]] = mapped_column(sa.String(128), index=True)
    #: 0.0-1.0. How sure the writer is. Feeds contradiction severity: a
    #: high-confidence fact contradicted by a low-confidence one is a smaller
    #: problem than two confident facts disagreeing.
    confidence_score: Mapped[float] = mapped_column(
        sa.Float, default=1.0, server_default="1.0", nullable=False
    )
    #: Higher wins. Human-approved canon outranks agent output, which outranks
    #: inference. See app/services/contradiction.py:SOURCE_PRIORITY.
    source_priority: Mapped[int] = mapped_column(
        sa.Integer, default=100, server_default="100", nullable=False
    )
    status: Mapped[str] = mapped_column(sa.String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = _created()

    document: Mapped[MemoryDocument] = relationship(back_populates="facts")


class CharacterProfile(Base):
    """The consistency anchor for one character.

    `character_code` is unique *per series*, not globally: two shows may both
    have a MIRA, and a global constraint would make the second one unnameable.
    """

    __tablename__ = "character_profiles"
    __table_args__ = (sa.UniqueConstraint("series_id", "character_code"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    series_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True
    )
    character_code: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    aliases: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    age_range: Mapped[Optional[str]] = mapped_column(sa.String(64))
    role_type: Mapped[Optional[str]] = mapped_column(sa.String(64))
    personality_traits: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    motivations: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    fears: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    #: See app/services/consistency_guard.py for which keys are mechanically
    #: checkable and which are reviewer-only prose.
    speech_style: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    relationship_map: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    visual_design: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    color_keys: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    recurring_props: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    do_not_change: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    current_status: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    canon_notes: Mapped[Optional[str]] = mapped_column(sa.Text)
    version: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class StyleBible(Base):
    """Editing, music and visual rules that define the show's identity."""

    __tablename__ = "style_bibles"
    __table_args__ = (
        sa.UniqueConstraint("series_id", "style_code"),
        # At most one active bible per series: "the active style bible" has to
        # name exactly one row, or every agent reading it may get a different
        # answer. Partial indexes are Postgres-only; SQLite ignores the WHERE
        # and would reject a second inactive row, so it is applied per dialect
        # in the migration rather than declared here.
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    series_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True
    )
    style_code: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    screenplay_rules: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    dialogue_rules: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    editing_rules: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    cinematography_rules: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    music_rules: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    sfx_rules: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    vfx_rules: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    pacing_rules: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    emotional_rules: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    negative_rules: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    #: Project frame rate. Every timing rule below is meaningless without it --
    #: see docs/anime-pipeline/03-anime-edit-checklist.md.
    frame_rate: Mapped[float] = mapped_column(
        sa.Float, default=24.0, nullable=False, server_default=sa.text("24.0")
    )
    version: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ContinuityCheck(Base):
    """The recorded outcome of one continuity or consistency audit."""

    __tablename__ = "continuity_checks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    episode_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="SET NULL")
    )
    check_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    issues: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    fixes_required: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    #: What the guard could NOT check mechanically. Carried so a pass is never
    #: mistaken for a full clearance.
    not_mechanically_checked: Mapped[list] = mapped_column(
        JSONColumn, default=list, nullable=False
    )
    passed: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    checked_by_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("agents.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class CanonicalEntity(Base):
    """One source-of-truth record for a named thing in the series.

    Exists so that "MIRA", "Mira" and "Mira Kisaragi" resolve to the same
    entity. Facts key off `entity_code`; without a registry to normalise
    through, two agents spelling a name differently create two parallel canons
    that never contradict each other because they never meet.

    Scoped per series: two shows may both have a MIRA, and a global unique
    constraint would make the second one unnameable.
    """

    __tablename__ = "canonical_entities"
    __table_args__ = (sa.UniqueConstraint("series_id", "entity_code"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    series_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_code: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    #: character | location | object | faction | creature | technology | concept
    entity_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    aliases: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    tags: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(sa.Text)
    metadata_json: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(32), default="active", nullable=False)
    is_canonical: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    alias_rows: Mapped[List["EntityAlias"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )


class EntityAlias(Base):
    """One spelling that resolves to a canonical entity.

    Why a table and not the `aliases` JSON column alone: the unique constraint.
    With aliases in JSON, two entities can both claim "Kisaragi" and nothing
    stops it -- the clash is only discovered later, at read time, by a resolver
    that then has to refuse. Here the second write fails, at the moment someone
    can still fix it, and resolution is a single indexed lookup instead of a
    scan over every entity in the series.

    `CanonicalEntity.aliases` remains as the display list; `EntityRegistry` is
    the only writer of either and keeps them in step.
    """

    __tablename__ = "entity_aliases"
    __table_args__ = (
        sa.UniqueConstraint("series_id", "alias_normalised"),
        sa.Index("ix_entity_aliases_lookup", "series_id", "alias_normalised"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    series_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("canonical_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: As written, for display and for explaining a match to a human.
    alias: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    #: normalise_alias(alias) -- the column actually matched against.
    alias_normalised: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    #: entity_code | display_name | manual | inferred
    source: Mapped[str] = mapped_column(
        sa.String(32), default="manual", server_default="manual", nullable=False
    )
    confidence: Mapped[float] = mapped_column(
        sa.Float, default=1.0, server_default="1.0", nullable=False
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped["CanonicalEntity"] = relationship(back_populates="alias_rows")


class TimelineEvent(Base):
    """One ordered event in series chronology.

    `series_id` is always set, even for episode-scoped events, so a single
    ordered read spans the whole show. `order_index` is unique per series,
    which is what makes "ordered" a well-defined word here: without the
    constraint two events can tie and the timeline silently differs between
    reads.
    """

    __tablename__ = "timeline_events"
    __table_args__ = (
        sa.UniqueConstraint("series_id", "event_code"),
        sa.UniqueConstraint("series_id", "order_index"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    event_code: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    series_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True
    )
    season_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("seasons.id", ondelete="CASCADE")
    )
    episode_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    summary: Mapped[str] = mapped_column(sa.Text, nullable=False)
    involved_entity_codes: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    fact_refs: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    is_canonical: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class TimelineCausalLink(Base):
    """A directed cause -> effect edge between two timeline events.

    Chronology alone cannot catch "the ritual that sealed the gate happens
    after the gate is already sealed". Ordering says both events exist and one
    precedes the other; only a stated causal edge makes the impossibility
    checkable -- an effect ordered at or before its cause, or a cycle of causes
    with no first link.
    """

    __tablename__ = "timeline_causal_links"
    __table_args__ = (
        sa.UniqueConstraint("series_id", "cause_event_id", "effect_event_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    series_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cause_event_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("timeline_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    effect_event_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("timeline_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: causes | enables | prevents. `prevents` is the one edge whose effect is
    #: expected *not* to occur, so it is checked in the opposite direction.
    link_type: Mapped[str] = mapped_column(
        sa.String(32), default="causes", server_default="causes", nullable=False
    )
    strength: Mapped[float] = mapped_column(
        sa.Float, default=1.0, server_default="1.0", nullable=False
    )
    note: Mapped[Optional[str]] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created()


class RetconProposal(Base):
    """A request to overwrite settled canon, and its editorial decision.

    Retcons are legitimate -- shows revise their own past on purpose. What is
    not legitimate is a draft doing it silently. This table is the difference:
    the contradiction still blocks, and an editor unblocks it by approving a
    proposal that records who decided, when, and why.
    """

    __tablename__ = "retcon_proposals"
    __table_args__ = (
        sa.Index("ix_retcon_proposals_open", "series_id", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    series_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True
    )
    episode_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="SET NULL"), index=True
    )
    #: Canonical entity code, already normalised through the registry.
    entity_code: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    fact_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    proposed_value: Mapped[dict] = mapped_column(JSONColumn, nullable=False)
    #: normalise_fact_value(proposed_value); NULL when the value has no flat
    #: form. Matched against a draft's proposed fact so an approval covers the
    #: same change however it is spelled next time.
    proposed_normalised_value: Mapped[Optional[str]] = mapped_column(sa.String(512), index=True)
    existing_fact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("memory_facts.id", ondelete="SET NULL")
    )
    rationale: Mapped[str] = mapped_column(sa.Text, nullable=False)
    #: pending | approved | rejected
    status: Mapped[str] = mapped_column(
        sa.String(32), default="pending", server_default="pending", nullable=False
    )
    #: Shared by the proposal and every fact its approval writes.
    retcon_group_code: Mapped[str] = mapped_column(sa.String(128), nullable=False, unique=True)
    decided_by: Mapped[Optional[str]] = mapped_column(sa.String(128))
    decided_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    decision_note: Mapped[Optional[str]] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ContinuityEnforcementRun(Base):
    """One recorded enforcement pass: preflight, draft validation or writeback."""

    __tablename__ = "continuity_enforcement_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    episode_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="SET NULL")
    )
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("agents.id", ondelete="SET NULL")
    )
    run_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    source_ref: Mapped[Optional[str]] = mapped_column(sa.String(255))
    input_payload: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    #: Memory codes and versions the run read, not the bundle itself. The whole
    #: bundle carries every character profile and the style bible; storing it
    #: per run would balloon the table while answering the same question.
    memory_provenance: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    passed: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(sa.String(500))
    created_at: Mapped[datetime] = _created()

    issues: Mapped[List["ContinuityIssue"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ContinuityIssue(Base):
    """One finding from an enforcement run."""

    __tablename__ = "continuity_issues"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("continuity_enforcement_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issue_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    severity: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(sa.String(64))
    entity_key: Mapped[Optional[str]] = mapped_column(sa.String(128))
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    recommendation: Mapped[Optional[str]] = mapped_column(sa.Text)
    evidence_json: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    blocking: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    resolved: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = _created()

    run: Mapped[ContinuityEnforcementRun] = relationship(back_populates="issues")


class ContradictionMatch(Base):
    """A proposed fact that conflicts with established canon."""

    __tablename__ = "contradiction_matches"

    id: Mapped[uuid.UUID] = _uuid_pk()
    episode_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("episodes.id", ondelete="CASCADE"), index=True
    )
    source_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("continuity_enforcement_runs.id", ondelete="SET NULL")
    )
    entity_code: Mapped[Optional[str]] = mapped_column(sa.String(128), index=True)
    fact_key: Mapped[Optional[str]] = mapped_column(sa.String(128))
    proposed_fact_json: Mapped[dict] = mapped_column(JSONColumn, nullable=False)
    existing_fact_json: Mapped[dict] = mapped_column(JSONColumn, nullable=False)
    #: immutable_fact_changed | retcon | duplicate_entity
    contradiction_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    severity: Mapped[str] = mapped_column(sa.String(32), default="high", nullable=False)
    #: 0-100. The band in `severity` is what a human reads; this is what a
    #: queue sorts by, so the worst contradiction in a batch of forty is the
    #: one on top rather than whichever happened to be written first.
    severity_score: Mapped[int] = mapped_column(
        sa.Integer, default=0, server_default="0", nullable=False
    )
    explanation: Mapped[str] = mapped_column(sa.Text, nullable=False)
    blocking: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    resolved: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    resolution_note: Mapped[Optional[str]] = mapped_column(sa.Text)
    #: Set when an editor filed a retcon proposal for this contradiction.
    #: An approved proposal is what turns "you rewrote canon" into "canon was
    #: rewritten on purpose, here is who signed off".
    retcon_proposal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("retcon_proposals.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class AgentEvalRun(Base):
    """One execution of a benchmark suite against the continuity system.

    The point is regression, not a grade. A suite of adversarial cases that
    passes today and fails after a refactor is the only thing that tells you a
    gate stopped gating -- and a gate that silently stops gating is
    indistinguishable, from the outside, from a gate with nothing to catch.
    """

    __tablename__ = "agent_eval_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_code: Mapped[str] = mapped_column(sa.String(128), unique=True, nullable=False)
    suite_code: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    #: What was evaluated: a service name, an agent code, a model identifier.
    target: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    #: running | passed | failed
    status: Mapped[str] = mapped_column(
        sa.String(32), default="running", server_default="running", nullable=False
    )
    total_cases: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    passed_cases: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    failed_cases: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    pass_rate: Mapped[float] = mapped_column(
        sa.Float, default=0.0, server_default="0.0", nullable=False
    )
    #: Failures grouped by category, so a report says "every alias case broke"
    #: rather than listing nine unrelated-looking failures.
    summary_json: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))

    case_results: Mapped[List["AgentEvalCaseResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AgentEvalCaseResult(Base):
    """The outcome of one benchmark case."""

    __tablename__ = "agent_eval_case_results"
    __table_args__ = (sa.UniqueConstraint("run_id", "case_code"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("agent_eval_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_code: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    category: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    #: False for a case whose whole point is that the system must *not* fire.
    #: Tracked separately because a system that blocks everything scores 100%
    #: on a suite made only of things that should block.
    expects_block: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    expectation_json: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    observed_json: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    passed: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    failure_reason: Mapped[Optional[str]] = mapped_column(sa.Text)
    duration_ms: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = _created()

    run: Mapped[AgentEvalRun] = relationship(back_populates="case_results")


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
