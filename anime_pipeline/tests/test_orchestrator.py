"""Pipeline graph, dependency gating and the publish gate."""

from __future__ import annotations

import pytest

from app.models.enums import QCStage, TaskStatus
from app.services.orchestrator import (
    PIPELINE,
    STAGES_BY_NAME,
    Orchestrator,
    StageSpec,
    TaskState,
    WorkflowState,
    pipeline_mermaid,
    validate_pipeline,
)
from app.agents.registry import AGENTS_BY_CODE
from app.schemas.registry import SCHEMA_REGISTRY
from tests.conftest import qc_report


@pytest.fixture()
def orch():
    return Orchestrator()


@pytest.fixture()
def state():
    return WorkflowState(episode_id="EP01")


def advance(state: WorkflowState, stage: str, status: TaskStatus = TaskStatus.approved):
    task_id = f"tsk_{stage}"
    state.tasks[task_id] = TaskState(task_id=task_id, stage=stage, status=status)
    return task_id


def test_pipeline_is_a_valid_dag():
    validate_pipeline()


def test_every_stage_names_a_registered_agent_and_known_schema():
    for stage in PIPELINE:
        assert stage.agent_code in AGENTS_BY_CODE, stage.name
        assert stage.output_schema in SCHEMA_REGISTRY, stage.name


def test_cycles_are_rejected():
    stages = [
        StageSpec("a", "packaging_agent", "t", PIPELINE[0].task_category, "packaging_v1", ("b",)),
        StageSpec("b", "packaging_agent", "t", PIPELINE[0].task_category, "packaging_v1", ("a",)),
    ]
    with pytest.raises(ValueError, match="cycle"):
        validate_pipeline(stages)


def test_unknown_dependencies_are_rejected():
    stages = [
        StageSpec("a", "packaging_agent", "t", PIPELINE[0].task_category, "packaging_v1", ("ghost",))
    ]
    with pytest.raises(ValueError, match="unknown"):
        validate_pipeline(stages)


def test_only_the_first_stage_is_runnable_on_a_fresh_episode(orch, state):
    assert orch.runnable_stages(state) == ["showrunner_brief"]


def test_a_stage_waits_for_its_dependency(orch, state):
    advance(state, "showrunner_brief", TaskStatus.in_progress)
    gate = orch.can_start(state, "beat_sheet")
    assert not gate
    assert "dependency showrunner_brief is in_progress" in gate.reasons


def test_dependency_satisfied_by_approval_opens_the_next_stage(orch, state):
    advance(state, "showrunner_brief", TaskStatus.approved)
    assert orch.can_start(state, "beat_sheet")
    assert "beat_sheet" in orch.runnable_stages(state)


def test_asset_stages_run_in_parallel_after_the_scene_plan(orch, state):
    for stage in ("showrunner_brief", "beat_sheet", "script_draft"):
        advance(state, stage)
    state.qc_reports[QCStage.script] = qc_report(score=9, stage="script")
    advance(state, "continuity_review")
    advance(state, "scene_plan")
    state.qc_reports[QCStage.scene_plan] = qc_report(score=9, stage="scene_plan")

    runnable = orch.runnable_stages(state)
    assert "character_assets" in runnable
    assert "background_props" in runnable
    assert STAGES_BY_NAME["character_assets"].parallel_group == "assets"


def test_a_qc_gate_blocks_the_dependent_stage_until_a_report_exists(orch, state):
    advance(state, "showrunner_brief")
    advance(state, "beat_sheet")
    advance(state, "script_draft")

    gate = orch.can_start(state, "continuity_review")
    assert not gate
    assert "no script QC report yet" in gate.reasons


def test_a_qc_gate_stays_shut_while_mandatory_fixes_are_outstanding(orch, state):
    advance(state, "showrunner_brief")
    advance(state, "beat_sheet")
    advance(state, "script_draft")
    state.qc_reports[QCStage.script] = qc_report(
        score=9, stage="script", required_fixes_before_publish=["trim scene 3"]
    )

    gate = orch.can_start(state, "continuity_review")
    assert not gate
    assert any("unresolved mandatory fix" in reason for reason in gate.reasons)


def test_intermediate_qc_gates_do_not_require_publish_readiness(orch, state):
    # A script-stage report can never be publish_ready, so gating on that
    # would deadlock the pipeline before it ever reached the final cut.
    advance(state, "showrunner_brief")
    advance(state, "beat_sheet")
    advance(state, "script_draft")
    report = qc_report(score=9, stage="script")
    assert report.publish_ready is False
    state.qc_reports[QCStage.script] = report

    assert orch.can_start(state, "continuity_review")


def test_a_blocker_freezes_every_stage(orch, state):
    advance(state, "showrunner_brief")
    assert orch.runnable_stages(state)

    orch.on_event(state, "blocker.raised", {"description": "missing surveillance BG"})
    assert orch.runnable_stages(state) == []

    orch.on_event(state, "blocker.resolved", {"description": "missing surveillance BG"})
    assert orch.runnable_stages(state)


def test_publish_gate_requires_approvals_and_a_passing_final_cut_report(orch, state):
    advance(state, "final_cut")
    advance(state, "packaging")
    gate = orch.can_publish(state)
    assert not gate
    assert "no final_cut master QC report" in gate.reasons

    state.qc_reports[QCStage.final_cut] = qc_report(score=9)
    assert orch.can_publish(state)


def test_publish_gate_refuses_a_passing_score_with_an_outstanding_fix(orch, state):
    advance(state, "final_cut")
    advance(state, "packaging")
    state.qc_reports[QCStage.final_cut] = qc_report(
        score=10, required_fixes_before_publish=["retime reveal pause"]
    )
    gate = orch.can_publish(state)
    assert not gate
    assert any("mandatory fix" in reason for reason in gate.reasons)


def test_publish_gate_refuses_an_unapproved_packaging_stage(orch, state):
    advance(state, "final_cut")
    advance(state, "packaging", TaskStatus.needs_revision)
    state.qc_reports[QCStage.final_cut] = qc_report(score=10)
    gate = orch.can_publish(state)
    assert not gate
    assert any("packaging is needs_revision" in reason for reason in gate.reasons)


def test_task_completion_routes_to_review_when_approval_is_required(orch, state):
    task_id = advance(state, "showrunner_brief", TaskStatus.in_progress)
    result = orch.on_event(state, "task.completed", {"task_id": task_id})
    assert result["task_status"] == TaskStatus.waiting_for_review.value

    task_id = advance(state, "beat_sheet", TaskStatus.in_progress)
    result = orch.on_event(state, "task.completed", {"task_id": task_id})
    assert result["task_status"] == TaskStatus.completed.value


def test_failure_retries_up_to_the_limit_then_escalates(orch, state):
    task_id = advance(state, "showrunner_brief", TaskStatus.in_progress)
    for _ in range(2):
        result = orch.on_event(state, "task.failed", {"task_id": task_id, "max_retries": 2})
        assert result["next_action"] == "retry"
    result = orch.on_event(state, "task.failed", {"task_id": task_id, "max_retries": 2})
    assert result["next_action"] == "escalate"
    assert state.tasks[task_id].status is TaskStatus.failed


def test_rejection_sends_a_task_back_for_revision(orch, state):
    task_id = advance(state, "script_draft", TaskStatus.waiting_for_review)
    result = orch.on_event(state, "approval.rejected", {"task_id": task_id})
    assert result["next_action"] == "revision_loop"
    assert state.tasks[task_id].status is TaskStatus.needs_revision


def test_qc_event_stores_the_report_and_reports_the_gate(orch, state):
    result = orch.on_event(
        state, "qc.reported", {"report": qc_report(score=9, stage="script")}
    )
    assert result["gate_open"] is True
    assert result["overall_score"] == 90
    assert QCStage.script in state.qc_reports


def test_unknown_events_are_ignored_rather_than_raising(orch, state):
    assert orch.on_event(state, "nonsense.event", {})["status"] == "ignored"


def test_mermaid_diagram_covers_every_stage_and_edge():
    diagram = pipeline_mermaid()
    assert diagram.startswith("flowchart TD")
    for stage in PIPELINE:
        assert stage.name in diagram
        for dep in stage.depends_on:
            assert f"{dep} --> {stage.name}" in diagram
