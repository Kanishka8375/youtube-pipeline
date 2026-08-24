"""The adversarial suite, and the harness that runs it.

Two levels here. The first is that the suite passes -- if it does not, some
gate has stopped gating. The second is that the harness itself behaves: a
harness that reports green when a case crashed, or that lets one case's
fixtures leak into the next, is worse than no harness, because it converts a
real regression into a passing build.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import AgentEvalCaseResult, AgentEvalRun, Series
from app.services.benchmarks import ADVERSARIAL_CASES, SUITE_CODE
from app.services.evaluation import CATEGORIES, EvalCase, EvaluationHarness, SuiteReport
from tests.test_workflow_persistence import fresh_session


def run_suite(client, **overrides):
    response = client.post("/evaluation/runs", json={"target": "continuity_system", **overrides})
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# The suite itself
# ---------------------------------------------------------------------------
def test_every_adversarial_case_passes(client):
    body = run_suite(client)
    failures = [(f["case_code"], f["failure_reason"]) for f in body["failures"]]
    assert failures == [], failures
    assert body["pass_rate"] == 1.0


def test_the_suite_checks_both_directions(client):
    # A matcher that blocks everything scores 100% on a suite made only of real
    # contradictions. The must-pass half is what makes the number mean anything.
    body = run_suite(client)
    polarity = body["by_polarity"]
    assert polarity["must_block"]["total"] >= 5
    assert polarity["must_pass"]["total"] >= 5


def test_every_case_declares_a_known_category():
    unknown = {c.category for c in ADVERSARIAL_CASES} - set(CATEGORIES)
    assert unknown == set()


def test_case_codes_are_unique():
    codes = [c.case_code for c in ADVERSARIAL_CASES]
    assert len(codes) == len(set(codes))


def test_every_case_asserts_something():
    # A case with no expectation passes unconditionally and is worse than
    # absent: it inflates the pass rate while checking nothing.
    empty = [c.case_code for c in ADVERSARIAL_CASES if not c.expectation]
    assert empty == []


def test_the_suite_can_be_described_without_running_it(client):
    body = client.get("/evaluation/suite").json()
    assert body["suite_code"] == SUITE_CODE
    assert body["case_count"] == len(ADVERSARIAL_CASES)
    assert all(case["description"] for case in body["cases"])


# ---------------------------------------------------------------------------
# The harness
# ---------------------------------------------------------------------------
def test_a_run_and_its_case_results_are_persisted(client):
    body = run_suite(client)
    with fresh_session() as session:
        run = session.scalar(
            select(AgentEvalRun).where(AgentEvalRun.run_code == body["run_code"])
        )
        assert run.status == "passed"
        assert run.total_cases == len(ADVERSARIAL_CASES)
        assert run.finished_at is not None
        results = session.scalars(
            select(AgentEvalCaseResult).where(AgentEvalCaseResult.run_id == run.id)
        ).all()
        assert len(results) == len(ADVERSARIAL_CASES)


def test_the_fixtures_a_case_builds_do_not_survive_it(client):
    # Cases that share state contaminate each other: a contradiction left
    # behind by one changes the verdict of the next, and the suite is then only
    # reproducible in order.
    run_suite(client)
    with fresh_session() as session:
        benchmark_series = [
            s.series_code
            for s in session.scalars(select(Series)).all()
            if s.series_code.startswith("BM_")
        ]
    assert benchmark_series == []


def test_a_dry_run_leaves_nothing_behind(client):
    body = run_suite(client, persist=False)
    assert body["persisted"] is False
    with fresh_session() as session:
        assert session.scalars(select(AgentEvalRun)).all() == []


def test_a_run_can_be_read_back(client):
    body = run_suite(client)
    fetched = client.get(f"/evaluation/runs/{body['run_code']}").json()
    assert fetched["pass_rate"] == 1.0
    assert len(fetched["cases"]) == len(ADVERSARIAL_CASES)
    assert client.get("/evaluation/runs/nope").status_code == 404


def test_the_report_is_grouped_and_says_nothing_when_all_is_well(client):
    body = run_suite(client)
    markdown = client.get(f"/evaluation/runs/{body['run_code']}/report").json()["markdown"]
    assert "No failures." in markdown
    assert "Catches real problems:" in markdown


def test_a_case_that_raises_is_a_failing_case_not_a_broken_run(client):
    # Stopping the suite on the first exception would hide every case after it.
    def explode(_ctx):
        raise RuntimeError("boom")

    cases = [
        EvalCase(
            case_code="explodes",
            category="mutability",
            description="raises",
            expects_block=True,
            run=explode,
            expectation={"passed": False},
        ),
        EvalCase(
            case_code="after_the_explosion",
            category="mutability",
            description="still runs",
            expects_block=False,
            run=lambda _ctx: {"passed": True},
            expectation={"passed": True},
        ),
    ]
    from app.api.routes.evaluation import _sandbox_context

    with fresh_session() as session:
        report = EvaluationHarness(session).run(
            cases,
            suite_code="harness_selftest",
            target="harness",
            context=_sandbox_context(session),
            persist=False,
        )
    assert [o.case.case_code for o in report.outcomes if not o.passed] == ["explodes"]
    assert "RuntimeError: boom" in report.outcomes[0].failure_reason
    assert report.outcomes[1].passed is True


def test_a_missing_key_is_a_failure_not_a_pass(client):
    from app.api.routes.evaluation import _sandbox_context

    case = EvalCase(
        case_code="missing_key",
        category="timeline",
        description="observation omits the asserted key",
        expects_block=True,
        run=lambda _ctx: {"something_else": True},
        expectation={"passed": False},
    )
    with fresh_session() as session:
        report = EvaluationHarness(session).run(
            [case],
            suite_code="harness_selftest",
            target="harness",
            context=_sandbox_context(session),
            persist=False,
        )
    assert report.failed == 1
    assert "missing from result" in report.outcomes[0].failure_reason


def test_the_report_groups_failures_by_category():
    report = SuiteReport(run_code="r", suite_code="s", target="t")
    from app.services.evaluation import CaseOutcome

    for code, category in [("a", "timeline"), ("b", "timeline"), ("c", "retcon")]:
        report.outcomes.append(
            CaseOutcome(
                case=EvalCase(
                    case_code=code,
                    category=category,
                    description=f"case {code}",
                    expects_block=True,
                    run=lambda _ctx: {},
                    expectation={},
                ),
                observed={},
                passed=False,
                failure_reason="nope",
                duration_ms=0,
            )
        )
    markdown = report.failure_report()
    # Grouped so a pattern reads as one regression, not three problems.
    assert "## retcon (1 failing)" in markdown
    assert "## timeline (2 failing)" in markdown
    assert report.by_category()["timeline"]["failed"] == 2
