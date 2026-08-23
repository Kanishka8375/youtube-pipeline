"""Agent output contracts.

Each model is the `output_spec.schema_name` an agent must satisfy. The
orchestrator validates every agent response against one of these before the
artifact is stored, so a malformed response never reaches a downstream agent.

`episode_id` throughout is the human episode code (``EP01``), not the database
UUID. The persistence layer resolves between them.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Showrunner -> episode brief
# --------------------------------------------------------------------------
class EpisodeBrief(_Strict):
    brief_id: str
    episode_id: str
    objective: str
    emotional_focus: str
    character_focus: List[str]
    core_conflict: str
    ending_trigger: str
    style_guardrails: List[str] = Field(default_factory=list)
    approved: bool = False


# --------------------------------------------------------------------------
# Episode story -> beat sheet
# --------------------------------------------------------------------------
class Beat(_Strict):
    beat_no: int = Field(ge=1)
    name: str
    purpose: str
    summary: str


class BeatSheet(_Strict):
    beat_sheet_id: str
    episode_id: str
    logline: str
    beats: List[Beat] = Field(min_length=1)
    short_candidates: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Scriptwriting -> script draft
# --------------------------------------------------------------------------
class DialogueLine(_Strict):
    speaker: str
    line: str


class Scene(_Strict):
    scene_id: str
    scene_order: int = Field(ge=1)
    purpose: str
    location: str
    duration_estimate_sec: int = Field(gt=0)
    summary: str
    dialogue: List[DialogueLine] = Field(default_factory=list)
    narration: List[str] = Field(default_factory=list)
    emotion: str
    asset_notes: List[str] = Field(default_factory=list)
    short_candidate: bool = False


class ScriptDraft(_Strict):
    script_id: str
    episode_id: str
    runtime_target_minutes: int = Field(gt=0)
    scenes: List[Scene] = Field(min_length=1)
    hook_strength_notes: str = ""
    revision_notes: List[str] = Field(default_factory=list)

    @property
    def estimated_runtime_sec(self) -> int:
        return sum(scene.duration_estimate_sec for scene in self.scenes)

    def runtime_drift_sec(self) -> int:
        """Estimated runtime minus target. Positive means over-length."""
        return self.estimated_runtime_sec - self.runtime_target_minutes * 60


# --------------------------------------------------------------------------
# Continuity -> continuity report
# --------------------------------------------------------------------------
class ContinuityIssue(_Strict):
    severity: str
    type: str
    scene_id: str
    description: str
    suggested_fix: str


class ContinuityReport(_Strict):
    continuity_report_id: str
    episode_id: str
    status: str
    issues: List[ContinuityIssue] = Field(default_factory=list)
    callback_opportunities: List[str] = Field(default_factory=list)
    approved_with_conditions: bool = False

    @property
    def needs_revision(self) -> bool:
        return self.status == "needs_revision"


# --------------------------------------------------------------------------
# Storyboard / scene planning -> scene plan
# --------------------------------------------------------------------------
class ShotCharacter(_Strict):
    name: str
    pose: str
    expression: str


class Shot(_Strict):
    shot_id: str
    scene_id: str
    shot_order: int = Field(ge=1)
    framing: str
    camera_motion: str
    background: str
    characters: List[ShotCharacter] = Field(default_factory=list)
    fx: List[str] = Field(default_factory=list)
    transition_in: str
    transition_out: str
    duration_sec: int = Field(gt=0)


class ScenePlan(_Strict):
    scene_plan_id: str
    episode_id: str
    shots: List[Shot] = Field(min_length=1)
    runtime_total_sec: int = Field(gt=0)

    def shot_duration_sum(self) -> int:
        return sum(shot.duration_sec for shot in self.shots)


# --------------------------------------------------------------------------
# Character / background agents -> asset request
# --------------------------------------------------------------------------
class AssetRequest(_Strict):
    asset_request_id: str
    episode_id: str
    requested_by: str
    asset_type: str
    asset_name: str
    scene_refs: List[str] = Field(default_factory=list)
    priority: str = "normal"
    reusable: bool = True
    status: str = "needed"
    spec: dict = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Packaging -> packaging set
# --------------------------------------------------------------------------
class ThumbnailConcept(_Strict):
    concept_id: str
    visual: str
    emotion: str
    text_overlay: str = ""


class PackagingSet(_Strict):
    packaging_id: str
    episode_id: str
    title_options: List[str] = Field(min_length=1)
    thumbnail_concepts: List[ThumbnailConcept] = Field(min_length=1)
    recommended_title: str
    description: str
    short_hooks: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Analytics -> analytics report
# --------------------------------------------------------------------------
class MetricSet(_Strict):
    ctr: float = Field(ge=0, le=100)
    retention_30s: float = Field(ge=0, le=100)
    avg_view_duration_sec: int = Field(ge=0)
    returning_viewers: int = Field(ge=0)
    subs_gained: int


class Moment(_Strict):
    timestamp: str
    reason: str


class AnalyticsReport(_Strict):
    analytics_report_id: str
    episode_id: str
    window: str
    metrics: MetricSet
    top_moment: Optional[Moment] = None
    dropoff_moment: Optional[Moment] = None
    recommendations: List[str] = Field(default_factory=list)
