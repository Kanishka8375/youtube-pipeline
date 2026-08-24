"""Workflow state must outlive the process that produced it.

These tests exist because the previous implementation kept `WorkflowState` in a
module-level dict: correct within one worker, silently wrong across a restart or
a second process. Everything here goes through the database.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import Episode, EpisodeBlocker, Task
from app.models.enums import QCStage, TaskStatus
from app.services.orchestrator import Orchestrator, TaskState
from app.services.workflow_repository import (
    UnknownEpisodeError,
    WorkflowStateRepository,
)
from tests.conftest import qc_report

EPISODE = {
    "series_code": "NEON_VEIL",
    "season_code": "S01",
    "episode_code": "EP01",
    "episode_number": 1,
    "runtime_target_minutes": 8,
}


def make_episode(client, **overrides):
    response = client.post("/episodes/", json={**EPISODE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def make_task(client, task_id, task_type, agent, category, schema="beat_sheet_v1"):
    response = client.post(
        "/tasks/",
        json={
            "task_id": task_id,
            "episode_id": "EP01",
            "task_type": task_type,
            "task_category": category,
            "created_by": {"id": "executive_showrunner_agent"},
            "assigned_to": {"id": agent},
            "instructions": {"goal": "g"},
            "output_spec": {"schema_name": schema},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def fresh_session():
    """A session from a new connection -- stands in for a second worker."""
    from app.core import database

    return next(database.get_session())


# ---------------------------------------------------------------------------
# The core property: nothing depends on process memory
# ---------------------------------------------------------------------------
def test_blocker_survives_a_new_session(client):
    make_episode(client)
    client.post(
        "/webhooks/events",
        json={
            "event": "blocker.raised",
            "payload": {"episode_id": "EP01", "description": "missing surveillance BG"},
        },
    )

    # A different session, as a different worker would have.
    with fresh_session() as session:
        state = WorkflowStateRepository(session).load("EP01")
        assert state.blockers == ["missing surveillance BG"]


def test_task_status_survives_a_new_session(client):
    make_episode(client)
    make_task(client, "tsk_brief", "approve_episode_brief", "executive_showrunner_agent", "direction")

    client.post(
        "/webhooks/events",
        json={"event": "task.completed", "payload": {"episode_id": "EP01", "task_id": "tsk_brief"}},
    )

    with fresh_session() as session:
        state = WorkflowStateRepository(session).load("EP01")
        assert state.tasks["tsk_brief"].status is TaskStatus.waiting_for_review


def test_retry_count_accumulates_across_sessions(client):
    # The lost-update case: each failure must build on the persisted count,
    # not on a counter that resets with the process.
    make_episode(client)
    make_task(client, "tsk_brief", "approve_episode_brief", "executive_showrunner_agent", "direction")

    for _ in range(2):
        client.post(
            "/webhooks/events",
            json={
                "event": "task.failed",
                "payload": {"episode_id": "EP01", "task_id": "tsk_brief", "max_retries": 2},
            },
        )

    with fresh_session() as session:
        assert session.scalar(select(Task).where(Task.task_code == "tsk_brief")).retry_count == 2

    final = client.post(
        "/webhooks/events",
        json={
            "event": "task.failed",
            "payload": {"episode_id": "EP01", "task_id": "tsk_brief", "max_retries": 2},
        },
    ).json()
    assert final["next_action"] == "escalate"

    with fresh_session() as session:
        row = session.scalar(select(Task).where(Task.task_code == "tsk_brief"))
        assert row.status is TaskStatus.failed


def test_qc_report_gating_survives_a_new_session(client):
    make_episode(client)
    client.post("/qc-reports/", json=qc_report(score=9, stage="script").model_dump(mode="json"))
    client.post(
        "/webhooks/events",
        json={
            "event": "qc.reported",
            "payload": {"episode_id": "EP01", "master_qc_report_id": "mqc_EP01_v1"},
        },
    )

    with fresh_session() as session:
        state = WorkflowStateRepository(session).load("EP01")
        assert QCStage.script in state.qc_reports
        assert state.qc_reports[QCStage.script].overall_score == 90


# ---------------------------------------------------------------------------
# Blocker lifecycle
# ---------------------------------------------------------------------------
def test_resolving_a_blocker_marks_it_resolved_rather_than_deleting_it(client):
    episode = make_episode(client)
    payload = {"episode_id": "EP01", "description": "missing surveillance BG"}
    client.post("/webhooks/events", json={"event": "blocker.raised", "payload": payload})
    client.post("/webhooks/events", json={"event": "blocker.resolved", "payload": payload})

    with fresh_session() as session:
        rows = session.scalars(select(EpisodeBlocker)).all()
        assert len(rows) == 1, "the record of what stalled the episode should survive"
        assert rows[0].resolved_at is not None
        assert rows[0].is_active is False

    assert client.get("/webhooks/state/EP01").json()["blockers"] == []


def test_raising_the_same_blocker_twice_does_not_duplicate_it(client):
    make_episode(client)
    payload = {"episode_id": "EP01", "description": "missing surveillance BG"}
    client.post("/webhooks/events", json={"event": "blocker.raised", "payload": payload})
    client.post("/webhooks/events", json={"event": "blocker.raised", "payload": payload})

    with fresh_session() as session:
        active = session.scalars(
            select(EpisodeBlocker).where(EpisodeBlocker.resolved_at.is_(None))
        ).all()
        assert len(active) == 1


def test_a_blocker_freezes_the_runnable_set_and_resolving_thaws_it(client):
    make_episode(client)
    make_task(client, "tsk_brief", "approve_episode_brief", "executive_showrunner_agent", "direction")

    assert client.get("/webhooks/state/EP01").json()["runnable"] == ["showrunner_brief"]

    payload = {"episode_id": "EP01", "description": "missing surveillance BG"}
    client.post("/webhooks/events", json={"event": "blocker.raised", "payload": payload})
    assert client.get("/webhooks/state/EP01").json()["runnable"] == []

    client.post("/webhooks/events", json={"event": "blocker.resolved", "payload": payload})
    assert client.get("/webhooks/state/EP01").json()["runnable"] == ["showrunner_brief"]


# ---------------------------------------------------------------------------
# Stage mapping
# ---------------------------------------------------------------------------
def test_creating_a_task_records_its_pipeline_stage(client):
    make_episode(client)
    make_task(client, "tsk_brief", "approve_episode_brief", "executive_showrunner_agent", "direction")

    with fresh_session() as session:
        assert session.scalar(select(Task).where(Task.task_code == "tsk_brief")).stage == (
            "showrunner_brief"
        )


def test_a_task_outside_the_graph_has_no_stage_and_is_invisible_to_the_orchestrator(client):
    make_episode(client)
    make_task(client, "tsk_adhoc", "some_ad_hoc_job", "packaging_agent", "integration")

    with fresh_session() as session:
        assert session.scalar(select(Task).where(Task.task_code == "tsk_adhoc")).stage is None
        state = WorkflowStateRepository(session).load("EP01")
        assert state.tasks == {}


# ---------------------------------------------------------------------------
# Locking and error handling
# ---------------------------------------------------------------------------
def test_locked_block_commits_on_success(client):
    make_episode(client)
    make_task(client, "tsk_brief", "approve_episode_brief", "executive_showrunner_agent", "direction")

    with fresh_session() as session:
        repo = WorkflowStateRepository(session)
        with repo.locked("EP01") as state:
            state.tasks["tsk_brief"].status = TaskStatus.approved

    with fresh_session() as session:
        state = WorkflowStateRepository(session).load("EP01")
        assert state.tasks["tsk_brief"].status is TaskStatus.approved


def test_locked_block_rolls_back_when_the_body_raises(client):
    make_episode(client)
    make_task(client, "tsk_brief", "approve_episode_brief", "executive_showrunner_agent", "direction")

    with fresh_session() as session:
        repo = WorkflowStateRepository(session)
        with pytest.raises(RuntimeError):
            with repo.locked("EP01") as state:
                state.tasks["tsk_brief"].status = TaskStatus.approved
                raise RuntimeError("boom")

    with fresh_session() as session:
        state = WorkflowStateRepository(session).load("EP01")
        assert state.tasks["tsk_brief"].status is TaskStatus.queued


def test_events_for_an_unknown_episode_return_404(client):
    response = client.post(
        "/webhooks/events",
        json={"event": "blocker.raised", "payload": {"episode_id": "EP99", "description": "x"}},
    )
    assert response.status_code == 404

    assert client.get("/webhooks/state/EP99").status_code == 404


def test_repository_raises_on_an_unknown_episode(client):
    with fresh_session() as session:
        with pytest.raises(UnknownEpisodeError):
            WorkflowStateRepository(session).load("EP99")


# ---------------------------------------------------------------------------
# QC event contract
# ---------------------------------------------------------------------------
def test_qc_event_requires_a_stored_report(client):
    make_episode(client)
    response = client.post(
        "/webhooks/events",
        json={
            "event": "qc.reported",
            "payload": {"episode_id": "EP01", "master_qc_report_id": "mqc_nope"},
        },
    )
    assert response.status_code == 404
    assert "qc-reports" in response.json()["detail"]


def test_qc_event_without_a_report_reference_is_rejected(client):
    make_episode(client)
    response = client.post(
        "/webhooks/events", json={"event": "qc.reported", "payload": {"episode_id": "EP01"}}
    )
    assert response.status_code == 400


def test_state_endpoint_reports_the_latest_report_per_stage(client):
    make_episode(client)
    client.post(
        "/qc-reports/",
        json=qc_report(score=6, stage="script", report_id="mqc_EP01_v1").model_dump(mode="json"),
    )
    client.post(
        "/qc-reports/",
        json=qc_report(score=9, stage="script", report_id="mqc_EP01_v2").model_dump(mode="json"),
    )

    body = client.get("/webhooks/state/EP01").json()
    assert body["qc_reports"]["script"]["report_id"] == "mqc_EP01_v2"
    assert body["qc_reports"]["script"]["overall_score"] == 90


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------
def test_a_full_gated_run_reaches_the_publish_gate(client):
    make_episode(client)
    stages = [
        ("tsk_brief", "approve_episode_brief", "executive_showrunner_agent", "direction"),
        ("tsk_beats", "create_beat_sheet", "episode_story_agent", "story"),
        ("tsk_script", "create_script_draft", "scriptwriting_agent", "writing"),
        ("tsk_cont", "review_script_continuity", "continuity_agent", "continuity"),
        ("tsk_plan", "create_scene_plan", "storyboard_scene_planning_agent", "scene_planning"),
        ("tsk_chars", "plan_character_assets", "character_asset_agent", "character_assets"),
        ("tsk_bg", "plan_background_props", "background_props_agent", "background_props"),
        ("tsk_rough", "assemble_rough_cut", "edit_motion_agent", "editing"),
        ("tsk_final", "assemble_final_cut", "edit_motion_agent", "editing"),
        ("tsk_pkg", "create_packaging_set", "packaging_agent", "packaging"),
    ]
    for task_id, task_type, agent, category in stages:
        make_task(client, task_id, task_type, agent, category)
        client.post(
            "/webhooks/events",
            json={"event": "task.completed", "payload": {"episode_id": "EP01", "task_id": task_id}},
        )
        client.post(
            "/webhooks/events",
            json={"event": "approval.granted", "payload": {"episode_id": "EP01", "task_id": task_id}},
        )

    for index, stage in enumerate(["script", "scene_plan", "rough_cut", "final_cut"], start=1):
        report = qc_report(score=9, stage=stage, report_id=f"mqc_EP01_{stage}_v{index}")
        client.post("/qc-reports/", json=report.model_dump(mode="json"))
        client.post(
            "/webhooks/events",
            json={
                "event": "qc.reported",
                "payload": {
                    "episode_id": "EP01",
                    "master_qc_report_id": report.master_qc_report_id,
                },
            },
        )

    # A brand-new session sees the same finished state.
    with fresh_session() as session:
        state = WorkflowStateRepository(session).load("EP01")
        gate = Orchestrator().can_publish(state)
        assert gate.ok, gate.reasons

    body = client.get("/webhooks/state/EP01").json()
    assert body["publish_ready"] is True
    assert body["publish_blockers"] == []
