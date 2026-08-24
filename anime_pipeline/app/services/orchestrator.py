"""Episode workflow: the stage graph, dependency resolution and gates.

The pipeline is declared as data (`PIPELINE`) rather than hard-coded branches,
so the graph can be inspected, tested and rendered without executing anything.
The orchestrator holds no database dependency -- it operates on a `WorkflowState`
that a repository layer can load from and save back to Postgres.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set

from app.models.enums import (
    TERMINAL_OK_STATUSES,
    QCStage,
    TaskCategory,
    TaskStatus,
)
from app.schemas.master_qc_report import MasterQCReport


@dataclass(frozen=True)
class StageSpec:
    """One node in the episode pipeline."""

    name: str
    agent_code: str
    task_type: str
    task_category: TaskCategory
    output_schema: str
    depends_on: Sequence[str] = ()
    approval_required: bool = False
    #: QC stage this node must clear before its dependents may start.
    qc_gate: Optional[QCStage] = None
    #: Nodes with the same `parallel_group` may run concurrently.
    parallel_group: Optional[str] = None


PIPELINE: List[StageSpec] = [
    StageSpec(
        "showrunner_brief",
        "executive_showrunner_agent",
        "approve_episode_brief",
        TaskCategory.direction,
        "episode_brief_v1",
        approval_required=True,
    ),
    StageSpec(
        "season_placement",
        "season_planner_agent",
        "confirm_season_placement",
        TaskCategory.season_planning,
        "episode_brief_v1",
        depends_on=("showrunner_brief",),
    ),
    StageSpec(
        "beat_sheet",
        "episode_story_agent",
        "create_beat_sheet",
        TaskCategory.story,
        "beat_sheet_v1",
        depends_on=("showrunner_brief",),
    ),
    StageSpec(
        "script_draft",
        "scriptwriting_agent",
        "create_script_draft",
        TaskCategory.writing,
        "script_draft_v1",
        depends_on=("beat_sheet",),
        qc_gate=QCStage.script,
    ),
    StageSpec(
        "continuity_review",
        "continuity_agent",
        "review_script_continuity",
        TaskCategory.continuity,
        "continuity_report_v1",
        depends_on=("script_draft",),
        approval_required=True,
    ),
    StageSpec(
        "scene_plan",
        "storyboard_scene_planning_agent",
        "create_scene_plan",
        TaskCategory.scene_planning,
        "scene_plan_v1",
        depends_on=("continuity_review",),
        qc_gate=QCStage.scene_plan,
    ),
    StageSpec(
        "character_assets",
        "character_asset_agent",
        "plan_character_assets",
        TaskCategory.character_assets,
        "asset_request_v1",
        depends_on=("scene_plan",),
        parallel_group="assets",
    ),
    StageSpec(
        "background_props",
        "background_props_agent",
        "plan_background_props",
        TaskCategory.background_props,
        "asset_request_v1",
        depends_on=("scene_plan",),
        parallel_group="assets",
    ),
    StageSpec(
        "rough_cut",
        "edit_motion_agent",
        "assemble_rough_cut",
        TaskCategory.editing,
        "scene_plan_v1",
        depends_on=("character_assets", "background_props"),
        qc_gate=QCStage.rough_cut,
    ),
    StageSpec(
        "final_cut",
        "edit_motion_agent",
        "assemble_final_cut",
        TaskCategory.editing,
        "scene_plan_v1",
        depends_on=("rough_cut",),
        approval_required=True,
        qc_gate=QCStage.final_cut,
    ),
    StageSpec(
        "packaging",
        "packaging_agent",
        "create_packaging_set",
        TaskCategory.packaging,
        "packaging_v1",
        depends_on=("final_cut",),
        approval_required=True,
    ),
    StageSpec(
        "publish",
        "edit_motion_agent",
        "publish_episode",
        TaskCategory.publishing,
        "packaging_v1",
        depends_on=("packaging",),
        approval_required=True,
    ),
    StageSpec(
        "analytics_review",
        "analytics_optimization_agent",
        "review_episode_performance",
        TaskCategory.analytics,
        "analytics_report_v1",
        depends_on=("publish",),
    ),
    StageSpec(
        "canon_update",
        "series_bible_agent",
        "update_series_bible",
        TaskCategory.canon,
        "episode_brief_v1",
        depends_on=("analytics_review",),
        parallel_group="post_publish",
    ),
    StageSpec(
        "season_adjustment",
        "season_planner_agent",
        "adjust_season_plan",
        TaskCategory.season_planning,
        "episode_brief_v1",
        depends_on=("analytics_review",),
        parallel_group="post_publish",
    ),
]

STAGES_BY_NAME: Dict[str, StageSpec] = {stage.name: stage for stage in PIPELINE}

#: Stages that must be approved before an episode may be published, regardless
#: of QC score. Publication additionally requires a passing final-cut QC report.
PUBLISH_PREREQUISITE_STAGES = ("final_cut", "packaging")


def validate_pipeline(stages: Sequence[StageSpec] = tuple(PIPELINE)) -> None:
    """Raise if the graph references unknown stages or contains a cycle."""
    names = {stage.name for stage in stages}
    for stage in stages:
        unknown = set(stage.depends_on) - names
        if unknown:
            raise ValueError(f"stage {stage.name!r} depends on unknown {sorted(unknown)}")

    # Kahn's algorithm; anything left over is part of a cycle.
    pending = {stage.name: set(stage.depends_on) for stage in stages}
    resolved: Set[str] = set()
    progress = True
    while progress:
        progress = False
        for name, deps in list(pending.items()):
            if deps <= resolved:
                resolved.add(name)
                del pending[name]
                progress = True
    if pending:
        raise ValueError(f"cycle in pipeline involving {sorted(pending)}")


@dataclass
class TaskState:
    """The orchestrator's view of one task. Mirrors a row in `tasks`."""

    task_id: str
    stage: str
    status: TaskStatus = TaskStatus.queued
    retry_count: int = 0


@dataclass
class WorkflowState:
    """Everything the orchestrator needs to decide what happens next."""

    episode_id: str
    tasks: Dict[str, TaskState] = field(default_factory=dict)
    #: Latest QC report per stage. Only the newest matters for gating.
    qc_reports: Dict[QCStage, MasterQCReport] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)

    def task_for_stage(self, stage: str) -> Optional[TaskState]:
        for task in self.tasks.values():
            if task.stage == stage:
                return task
        return None

    def stage_status(self, stage: str) -> Optional[TaskStatus]:
        task = self.task_for_stage(stage)
        return task.status if task else None


class GateResult:
    """Why a stage may or may not start. Truthy when the stage may start."""

    __slots__ = ("ok", "reasons")

    def __init__(self, ok: bool, reasons: Optional[List[str]] = None) -> None:
        self.ok = ok
        self.reasons = reasons or []

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:
        return f"GateResult(ok={self.ok}, reasons={self.reasons})"


class Orchestrator:
    """Decides which stages are runnable and whether an episode may publish."""

    def __init__(self, stages: Sequence[StageSpec] = tuple(PIPELINE)) -> None:
        validate_pipeline(stages)
        self.stages = list(stages)
        self.by_name = {stage.name: stage for stage in self.stages}

    # -- gating ---------------------------------------------------------
    def can_start(self, state: WorkflowState, stage_name: str) -> GateResult:
        stage = self.by_name[stage_name]
        reasons: List[str] = []

        if state.blockers:
            reasons.append(f"episode blocked: {', '.join(state.blockers)}")

        for dep_name in stage.depends_on:
            dep_status = state.stage_status(dep_name)
            if dep_status is None:
                reasons.append(f"dependency {dep_name} has no task yet")
            elif dep_status not in TERMINAL_OK_STATUSES:
                reasons.append(f"dependency {dep_name} is {dep_status.value}")

            dep_stage = self.by_name[dep_name]
            if dep_stage.qc_gate is not None:
                gate = self.qc_gate_result(state, dep_stage.qc_gate)
                if not gate:
                    reasons.extend(gate.reasons)

        return GateResult(not reasons, reasons)

    def qc_gate_result(self, state: WorkflowState, qc_stage: QCStage) -> GateResult:
        """A QC gate passes when the latest report for that stage clears review.

        Intermediate gates (script, scene plan, rough cut) pass on decision, not
        on `publish_ready` -- only a final-cut report can ever be publish-ready,
        so requiring it earlier would deadlock the pipeline.
        """
        report = state.qc_reports.get(qc_stage)
        if report is None:
            return GateResult(False, [f"no {qc_stage.value} QC report yet"])
        if report.critical_issues:
            return GateResult(
                False,
                [f"{qc_stage.value} QC has {len(report.critical_issues)} critical issue(s)"],
            )
        if report.required_fixes_before_publish:
            return GateResult(
                False,
                [
                    f"{qc_stage.value} QC has "
                    f"{len(report.required_fixes_before_publish)} unresolved mandatory fix(es)"
                ],
            )
        return GateResult(True)

    def runnable_stages(self, state: WorkflowState) -> List[str]:
        """Stages with no task yet, or a queued task, whose gates are open."""
        runnable = []
        for stage in self.stages:
            status = state.stage_status(stage.name)
            if status is not None and status not in {TaskStatus.queued, TaskStatus.waiting_on_dependency}:
                continue
            if self.can_start(state, stage.name):
                runnable.append(stage.name)
        return runnable

    def can_publish(self, state: WorkflowState) -> GateResult:
        """The publish gate: approvals AND a passing final-cut QC report."""
        reasons: List[str] = []
        for stage_name in PUBLISH_PREREQUISITE_STAGES:
            status = state.stage_status(stage_name)
            if status not in TERMINAL_OK_STATUSES:
                reasons.append(
                    f"{stage_name} is {status.value if status else 'not started'}, "
                    "must be approved or completed"
                )

        report = state.qc_reports.get(QCStage.final_cut)
        if report is None:
            reasons.append("no final_cut master QC report")
        elif not report.publish_ready:
            reasons.append(
                f"final_cut QC not publish-ready "
                f"(score {report.overall_score}, "
                f"{len(report.required_fixes_before_publish)} mandatory fix(es), "
                f"{len(report.critical_issues)} critical issue(s))"
            )
        return GateResult(not reasons, reasons)

    # -- events ---------------------------------------------------------
    def on_event(self, state: WorkflowState, event: str, payload: Dict) -> Dict:
        """Handle one orchestration event and report what should happen next."""
        handler = {
            "episode.created": self._on_episode_created,
            "task.completed": self._on_task_completed,
            "task.failed": self._on_task_failed,
            "approval.granted": self._on_approval_granted,
            "approval.rejected": self._on_approval_rejected,
            "qc.reported": self._on_qc_reported,
            "blocker.raised": self._on_blocker_raised,
            "blocker.resolved": self._on_blocker_resolved,
        }.get(event)
        if handler is None:
            return {"status": "ignored", "event": event}
        return handler(state, payload)

    def _next(self, state: WorkflowState, **extra) -> Dict:
        return {"status": "ok", "runnable": self.runnable_stages(state), **extra}

    def _on_episode_created(self, state: WorkflowState, payload: Dict) -> Dict:
        return self._next(state, next_action="create_showrunner_task")

    def _on_task_completed(self, state: WorkflowState, payload: Dict) -> Dict:
        task = state.tasks.get(payload["task_id"])
        if task is None:
            return {"status": "unknown_task", "task_id": payload["task_id"]}
        stage = self.by_name[task.stage]
        task.status = (
            TaskStatus.waiting_for_review if stage.approval_required else TaskStatus.completed
        )
        return self._next(state, task_id=task.task_id, task_status=task.status.value)

    def _on_task_failed(self, state: WorkflowState, payload: Dict) -> Dict:
        task = state.tasks.get(payload["task_id"])
        if task is None:
            return {"status": "unknown_task", "task_id": payload["task_id"]}
        max_retries = payload.get("max_retries", 2)
        if task.retry_count < max_retries:
            task.retry_count += 1
            task.status = TaskStatus.queued
            return self._next(state, task_id=task.task_id, next_action="retry")
        task.status = TaskStatus.failed
        return self._next(state, task_id=task.task_id, next_action="escalate")

    def _on_approval_granted(self, state: WorkflowState, payload: Dict) -> Dict:
        task = state.tasks.get(payload["task_id"])
        if task is None:
            return {"status": "unknown_task", "task_id": payload["task_id"]}
        task.status = TaskStatus.approved
        return self._next(state, task_id=task.task_id)

    def _on_approval_rejected(self, state: WorkflowState, payload: Dict) -> Dict:
        task = state.tasks.get(payload["task_id"])
        if task is None:
            return {"status": "unknown_task", "task_id": payload["task_id"]}
        task.status = TaskStatus.needs_revision
        return self._next(state, task_id=task.task_id, next_action="revision_loop")

    def _on_qc_reported(self, state: WorkflowState, payload: Dict) -> Dict:
        report = payload["report"]
        if not isinstance(report, MasterQCReport):
            report = MasterQCReport.model_validate(report)
        state.qc_reports[report.qc_stage] = report
        gate = self.qc_gate_result(state, report.qc_stage)
        return self._next(
            state,
            qc_stage=report.qc_stage.value,
            overall_score=report.overall_score,
            gate_open=gate.ok,
            gate_reasons=gate.reasons,
        )

    def _on_blocker_raised(self, state: WorkflowState, payload: Dict) -> Dict:
        description = payload["description"]
        if description not in state.blockers:
            state.blockers.append(description)
        return self._next(state, next_action="notify_showrunner")

    def _on_blocker_resolved(self, state: WorkflowState, payload: Dict) -> Dict:
        description = payload["description"]
        if description in state.blockers:
            state.blockers.remove(description)
        return self._next(state)


def pipeline_mermaid(stages: Iterable[StageSpec] = tuple(PIPELINE)) -> str:
    """Render the pipeline as a mermaid flowchart, for docs and dashboards."""
    lines = ["flowchart TD"]
    for stage in stages:
        label = stage.name.replace("_", " ")
        if stage.qc_gate is not None:
            label += f"<br/>QC: {stage.qc_gate.value}"
        lines.append(f'    {stage.name}["{label}"]')
    for stage in stages:
        for dep in stage.depends_on:
            lines.append(f"    {dep} --> {stage.name}")
    return "\n".join(lines)
