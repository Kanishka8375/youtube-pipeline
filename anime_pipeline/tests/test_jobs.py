"""The background job queue: claiming, retries, and giving up."""

from __future__ import annotations

import pytest

from app.db.models import BackgroundJob
from app.services.jobs.job_queue import (
    COMPLETED,
    FAILED,
    QUEUED,
    RETRYING,
    RUNNING,
    JobQueue,
    backoff_for,
)
from tests.test_auth_and_workspaces import signed_in
from tests.test_workflow_persistence import fresh_session


def queue(session):
    return JobQueue(session)


def run_until_terminal(session, job_id, handlers, *, rounds=6):
    """Execute a job repeatedly, skipping the backoff wait each time."""
    q = queue(session)
    for _ in range(rounds):
        row = session.get(BackgroundJob, job_id)
        if row.status in (COMPLETED, FAILED):
            return row
        row.scheduled_for = None
        session.commit()
        q.execute(row, handlers)
    return session.get(BackgroundJob, job_id)


# ---------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------
def test_a_transient_failure_is_retried_then_succeeds(client):
    calls = {"n": 0}

    def flaky(_payload):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("upstream 503")
        return {"attempts": calls["n"]}

    with fresh_session() as session:
        job = queue(session).enqueue(job_type="flaky", max_attempts=3)
        session.commit()
        final = run_until_terminal(session, job.id, {"flaky": flaky})

    assert final.status == COMPLETED
    assert final.attempt_count == 3
    assert final.result_json == {"attempts": 3}


def test_the_retry_budget_actually_depletes(client):
    # The bug this pins: `execute` rolls back on failure to discard the
    # handler's partial writes, and an uncommitted attempt increment would be
    # rolled back with it -- so the count resets, the budget never depletes,
    # and a permanently broken job retries forever.
    def always_fails(_payload):
        raise ValueError("permanently broken")

    with fresh_session() as session:
        job = queue(session).enqueue(job_type="broken", max_attempts=2)
        session.commit()
        final = run_until_terminal(session, job.id, {"broken": always_fails})

    assert final.status == FAILED
    assert final.attempt_count == 2
    assert "permanently broken" in final.error_message


def test_a_handlers_partial_writes_are_discarded_on_failure(client):
    from app.db.models import AuditLog

    def writes_then_fails(_payload):
        session.add(AuditLog(action="should.not.persist", entity_type="test"))
        session.flush()
        raise RuntimeError("failed after writing")

    with fresh_session() as session:
        job = queue(session).enqueue(job_type="dirty", max_attempts=1)
        session.commit()
        run_until_terminal(session, job.id, {"dirty": writes_then_fails})
        leaked = [a for a in session.query(AuditLog).all() if a.action == "should.not.persist"]

    assert leaked == [], "a failed handler must not leave half-written rows behind"


def test_an_unknown_job_type_fails_without_burning_the_budget(client):
    # Retrying a job whose handler does not exist spends the whole budget on
    # the same missing import and buries the real cause.
    with fresh_session() as session:
        job = queue(session).enqueue(job_type="nonexistent", max_attempts=5)
        session.commit()
        outcome = queue(session).execute(session.get(BackgroundJob, job.id), {})

    assert outcome.status == FAILED
    assert outcome.job.attempt_count == 1
    assert "No handler registered" in outcome.error


def test_backoff_grows_then_plateaus():
    ladder = [backoff_for(n).total_seconds() for n in range(1, 6)]
    assert ladder[0] < ladder[1] < ladder[2]
    # Capped rather than unbounded: a job that has failed four times needs a
    # human, not a longer nap.
    assert ladder[2] == ladder[3] == ladder[4]


def test_a_retrying_job_is_not_runnable_until_its_backoff_elapses(client):
    def fails(_payload):
        raise RuntimeError("nope")

    with fresh_session() as session:
        q = queue(session)
        job = q.enqueue(job_type="waits", max_attempts=3)
        session.commit()
        q.execute(session.get(BackgroundJob, job.id), {"waits": fails})

        row = session.get(BackgroundJob, job.id)
        assert row.status == RETRYING
        assert row.scheduled_for is not None
        # Nothing eligible: the backoff has not elapsed.
        assert [j.id for j in q.runnable()] == []


# ---------------------------------------------------------------------------
# Claiming
# ---------------------------------------------------------------------------
def test_claiming_marks_the_job_running_and_spends_an_attempt(client):
    with fresh_session() as session:
        q = queue(session)
        q.enqueue(job_type="a")
        session.commit()

        claimed = q.claim_next()
        assert claimed.status == RUNNING
        assert claimed.attempt_count == 1
        # The claim is committed, so a crashed worker does not hand the job a
        # fresh budget on restart.
        assert session.get(BackgroundJob, claimed.id).attempt_count == 1


def test_claiming_an_empty_queue_returns_nothing(client):
    with fresh_session() as session:
        assert queue(session).claim_next() is None


def test_jobs_are_claimed_oldest_first(client):
    with fresh_session() as session:
        q = queue(session)
        for name in ("first", "second", "third"):
            q.enqueue(job_type=name)
            session.commit()
        assert [q.claim_next().job_type for _ in range(3)] == ["first", "second", "third"]


def test_drain_stops_when_the_queue_empties(client):
    with fresh_session() as session:
        q = queue(session)
        for _ in range(3):
            q.enqueue(job_type="noop")
        session.commit()
        outcomes = q.drain({"noop": lambda payload: {"ok": True}})
    assert len(outcomes) == 3
    assert all(o.status == COMPLETED for o in outcomes)


def test_drain_is_bounded(client):
    # A handler that enqueues another job would otherwise make drain never
    # return.
    with fresh_session() as session:
        q = queue(session)
        q.enqueue(job_type="spawns")
        session.commit()

        def spawns(_payload):
            q.enqueue(job_type="spawns")
            return {"spawned": True}

        outcomes = q.drain({"spawns": spawns}, max_jobs=4)
    assert len(outcomes) == 4


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def test_the_queue_endpoints_require_a_token(client):
    assert client.get("/jobs").status_code == 401
    assert client.post("/jobs", json={"job_type": "x"}).status_code == 401


def test_enqueueing_an_unknown_job_type_is_rejected_up_front(client):
    headers = signed_in(client, "jobs@studio.example")
    response = client.post("/jobs", json={"job_type": "not.a.real.handler"}, headers=headers)
    assert response.status_code == 400
    assert "Known types" in response.json()["detail"]


def test_the_handler_registry_is_introspectable(client):
    headers = signed_in(client, "jobs2@studio.example")
    body = client.get("/jobs/handlers", headers=headers).json()
    assert "generation.text" in body["job_types"]
