"""HTTP surface, exercised against a real (SQLite) database."""

from __future__ import annotations

from tests.conftest import qc_report

EPISODE = {
    "series_code": "NEON_VEIL",
    "season_code": "S01",
    "episode_code": "EP01",
    "episode_number": 1,
    "runtime_target_minutes": 8,
}


def create_episode(client, **overrides):
    return client.post("/episodes/", json={**EPISODE, **overrides})


def pass_continuity(client):
    """Record a passing continuity check, a precondition of the publish gate."""
    response = client.post(
        "/memory/consistency-check",
        json={"episode_code": "EP01", "script": {"scenes": []}},
    )
    assert response.status_code == 200 and response.json()["passed"] is True


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_agents_are_seeded_on_startup(client):
    assert len(client.get("/pipeline/agents").json()) == 13


def test_pipeline_stages_are_exposed(client):
    stages = client.get("/pipeline/stages").json()
    assert {s["name"] for s in stages} >= {"showrunner_brief", "final_cut", "packaging"}
    final_cut = next(s for s in stages if s["name"] == "final_cut")
    assert final_cut["qc_gate"] == "final_cut"


def test_create_and_fetch_an_episode(client):
    assert create_episode(client).status_code == 201
    body = client.get("/episodes/EP01").json()
    assert body["episode_code"] == "EP01"
    assert body["status"] == "idea"


def test_duplicate_episode_codes_are_rejected(client):
    create_episode(client)
    assert create_episode(client).status_code == 409


def test_unknown_episode_returns_404(client):
    assert client.get("/episodes/EP99").status_code == 404


def test_task_output_must_satisfy_its_declared_schema(client):
    create_episode(client)
    envelope = {
        "task_id": "tsk_EP01_STORY_001",
        "episode_id": "EP01",
        "task_type": "create_beat_sheet",
        "task_category": "story",
        "created_by": {"id": "executive_showrunner_agent"},
        "assigned_to": {"id": "episode_story_agent"},
        "instructions": {"goal": "Write the beat sheet."},
        "output_spec": {"schema_name": "beat_sheet_v1"},
    }
    assert client.post("/tasks/", json=envelope).status_code == 201

    bad = client.post("/tasks/tsk_EP01_STORY_001/complete", json={"beat_sheet_id": "b"})
    assert bad.status_code == 422
    # Rejected output must not be persisted.
    assert client.get("/tasks/tsk_EP01_STORY_001").json()["output"] is None

    good = client.post(
        "/tasks/tsk_EP01_STORY_001/complete",
        json={
            "beat_sheet_id": "beats_EP01_v1",
            "episode_id": "EP01",
            "logline": "A signal that should not exist.",
            "beats": [{"beat_no": 1, "name": "Cold Open", "purpose": "hook", "summary": "x"}],
        },
    )
    assert good.status_code == 200
    assert good.json()["status"] == "completed"


def test_task_for_an_unknown_agent_is_rejected(client):
    create_episode(client)
    response = client.post(
        "/tasks/",
        json={
            "task_id": "tsk_x",
            "episode_id": "EP01",
            "task_type": "t",
            "task_category": "story",
            "created_by": {"id": "a"},
            "assigned_to": {"id": "not_a_real_agent"},
            "instructions": {"goal": "g"},
            "output_spec": {"schema_name": "beat_sheet_v1"},
        },
    )
    assert response.status_code == 400


def test_publish_gate_without_a_report(client):
    create_episode(client)
    body = client.get("/qc-reports/episode/EP01/publish-gate").json()
    assert body["publish_ready"] is False
    # Both halves of the gate are unmet: no QC report, and no continuity check.
    assert body["reasons"] == [
        "no final_cut master QC report",
        "no passing continuity check",
    ]


def test_a_passing_report_opens_the_publish_gate(client):
    create_episode(client)
    pass_continuity(client)
    response = client.post("/qc-reports/", json=qc_report(score=9).model_dump(mode="json"))
    assert response.status_code == 201
    assert response.json()["overall_score"] == 90

    gate = client.get("/qc-reports/episode/EP01/publish-gate").json()
    assert gate["publish_ready"] is True
    assert gate["readiness"] == "Premium Ready"
    assert gate["reasons"] == []


def test_a_failing_report_keeps_the_gate_shut_and_names_the_weak_areas(client):
    create_episode(client)
    report = qc_report(
        score=9,
        sections={"music": {"score": 2}, "editing_rhythm": {"score": 3}},
        critical_issues=["Final reveal music enters too early"],
    )
    client.post("/qc-reports/", json=report.model_dump(mode="json"))

    gate = client.get("/qc-reports/episode/EP01/publish-gate").json()
    assert gate["publish_ready"] is False
    assert gate["weakest_categories"][0] == "music"
    assert any("critical issue" in reason for reason in gate["reasons"])


def test_the_latest_final_cut_report_wins(client):
    create_episode(client)
    pass_continuity(client)
    client.post(
        "/qc-reports/",
        json=qc_report(score=6, report_id="mqc_EP01_v1").model_dump(mode="json"),
    )
    client.post(
        "/qc-reports/",
        json=qc_report(score=9, report_id="mqc_EP01_v2").model_dump(mode="json"),
    )

    gate = client.get("/qc-reports/episode/EP01/publish-gate").json()
    assert gate["overall_score"] == 90
    assert gate["publish_ready"] is True
    assert len(client.get("/qc-reports/episode/EP01").json()) == 2


def test_duplicate_qc_report_ids_are_rejected(client):
    create_episode(client)
    payload = qc_report(score=9).model_dump(mode="json")
    assert client.post("/qc-reports/", json=payload).status_code == 201
    assert client.post("/qc-reports/", json=payload).status_code == 409


def test_a_qc_report_for_an_unknown_episode_is_rejected(client):
    payload = qc_report(score=9, episode_id="EP99").model_dump(mode="json")
    assert client.post("/qc-reports/", json=payload).status_code == 404


def test_orchestrator_events_drive_the_workflow_state(client):
    # The episode must exist first. Workflow state is now database-backed, so an
    # event naming an unknown episode is a 404 rather than silently conjuring
    # state for it -- see test_events_for_an_unknown_episode_return_404.
    create_episode(client)
    client.post("/webhooks/events", json={"event": "episode.created", "payload": {"episode_id": "EP01"}})
    state = client.get("/webhooks/state/EP01").json()
    assert state["runnable"] == ["showrunner_brief"]
    assert state["publish_ready"] is False

    client.post(
        "/webhooks/events",
        json={"event": "blocker.raised", "payload": {"episode_id": "EP01", "description": "missing BG"}},
    )
    assert client.get("/webhooks/state/EP01").json()["runnable"] == []


def test_events_without_an_episode_id_are_ignored(client):
    body = client.post("/webhooks/events", json={"event": "episode.created", "payload": {}}).json()
    assert body["status"] == "ignored"
