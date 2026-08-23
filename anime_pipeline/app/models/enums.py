"""Shared enumerations for the agent pipeline.

Every value here is part of the wire contract: the same strings appear in the
JSON task envelope, the Postgres enum types, and the Notion/Airtable select
options. Changing a value is a breaking change on all three.
"""

from enum import Enum


class TaskStatus(str, Enum):
    queued = "queued"
    in_progress = "in_progress"
    waiting_on_dependency = "waiting_on_dependency"
    waiting_for_review = "waiting_for_review"
    approved = "approved"
    needs_revision = "needs_revision"
    completed = "completed"
    blocked = "blocked"
    failed = "failed"
    cancelled = "cancelled"


#: Statuses that satisfy a downstream dependency. A task waiting on a
#: dependency may only start once every parent is in this set.
TERMINAL_OK_STATUSES = frozenset({TaskStatus.approved, TaskStatus.completed})

#: Statuses from which no further transition is possible.
TERMINAL_STATUSES = frozenset(
    {TaskStatus.completed, TaskStatus.approved, TaskStatus.cancelled, TaskStatus.failed}
)


class PriorityLevel(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class ApprovalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    needs_revision = "needs_revision"
    rejected = "rejected"


class ArtifactStatus(str, Enum):
    draft = "draft"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"
    archived = "archived"


class ProviderJobStatus(str, Enum):
    queued = "queued"
    submitted = "submitted"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TaskCategory(str, Enum):
    direction = "direction"
    canon = "canon"
    season_planning = "season_planning"
    story = "story"
    writing = "writing"
    continuity = "continuity"
    character_assets = "character_assets"
    background_props = "background_props"
    scene_planning = "scene_planning"
    editing = "editing"
    packaging = "packaging"
    analytics = "analytics"
    publishing = "publishing"
    integration = "integration"
    quality_control = "quality_control"


class QCStage(str, Enum):
    script = "script"
    scene_plan = "scene_plan"
    rough_cut = "rough_cut"
    final_cut = "final_cut"


class QCDecision(str, Enum):
    # `pass` is a Python keyword, so the member name is suffixed. The *value*
    # is what crosses the wire and what Postgres stores.
    pass_ = "pass"
    pass_with_revisions = "pass_with_revisions"
    reject = "reject"


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"
