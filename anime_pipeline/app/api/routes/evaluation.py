"""Run the adversarial continuity suite and read its results.

Exposed as an endpoint, not just a test, because the question "does the gate
still gate" has to be answerable against a running deployment -- against its
real database and its real code -- not only in CI.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.db.models import AgentEvalCaseResult, AgentEvalRun, Episode, Season, Series
from app.services.benchmarks import ADVERSARIAL_CASES, SUITE_CODE
from app.services.evaluation import EvalContext, EvaluationHarness

router = APIRouter()


class EvalRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(default="continuity_system", min_length=1)
    #: Persisting is the default; a dry run is for checking a change without
    #: leaving a row behind.
    persist: bool = True


def _sandbox_context(session: Session) -> EvalContext:
    """Fixtures for one suite run, namespaced so they cannot collide.

    Every case builds a fresh series under a unique prefix. Cases that share a
    series contaminate each other -- a contradiction left by one changes the
    verdict of the next -- and the suite would only be reproducible in order.
    """
    namespace = uuid.uuid4().hex[:8]

    def make_series(code: str) -> Series:
        series = Series(
            series_code=f"{code}_{namespace}",
            title=f"Benchmark {code}",
            description="Fixture built by the adversarial continuity suite.",
        )
        session.add(series)
        session.flush()
        return series

    def make_episode(series: Series, code: str, **overrides) -> Episode:
        season = session.scalar(select(Season).where(Season.series_id == series.id))
        if season is None:
            season = Season(
                series_id=series.id,
                season_code=f"{series.series_code}_S1",
                season_number=1,
                title="Benchmark season",
            )
            session.add(season)
            session.flush()
        # Episode numbers must be unique within a season, and cases build
        # several episodes each; derive it from how many already exist rather
        # than making every case pass one.
        used = session.scalars(
            select(Episode.episode_number).where(Episode.season_id == season.id)
        ).all()
        episode = Episode(
            series_id=series.id,
            season_id=season.id,
            episode_code=f"{series.series_code}_{code}",
            episode_number=int(overrides.pop("episode_number", max(used, default=0) + 1)),
            working_title=code,
            **overrides,
        )
        session.add(episode)
        session.flush()
        return episode

    return EvalContext(session=session, make_series=make_series, make_episode=make_episode)


def _run_payload(run: AgentEvalRun, session: Session) -> Dict[str, Any]:
    cases = session.scalars(
        select(AgentEvalCaseResult)
        .where(AgentEvalCaseResult.run_id == run.id)
        .order_by(AgentEvalCaseResult.category, AgentEvalCaseResult.case_code)
    ).all()
    return {
        "run_code": run.run_code,
        "suite_code": run.suite_code,
        "target": run.target,
        "status": run.status,
        "total_cases": run.total_cases,
        "passed_cases": run.passed_cases,
        "failed_cases": run.failed_cases,
        "pass_rate": run.pass_rate,
        "summary": run.summary_json,
        "cases": [
            {
                "case_code": c.case_code,
                "category": c.category,
                "expects_block": c.expects_block,
                "passed": c.passed,
                "failure_reason": c.failure_reason,
                "duration_ms": c.duration_ms,
            }
            for c in cases
        ],
    }


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def run_suite(body: EvalRunRequest, session: Session = Depends(db_session)):
    """Run the adversarial suite against this deployment."""
    report = EvaluationHarness(session).run(
        ADVERSARIAL_CASES,
        suite_code=SUITE_CODE,
        target=body.target,
        context=_sandbox_context(session),
        persist=body.persist,
    )
    if body.persist:
        session.commit()
    else:
        # A dry run must leave nothing behind, including the fixtures the cases
        # built to exercise the checks.
        session.rollback()
    return {
        "run_code": report.run_code,
        "suite_code": report.suite_code,
        "target": report.target,
        "persisted": body.persist,
        **report.summary(),
    }


@router.get("/runs/{run_code}")
def get_run(run_code: str, session: Session = Depends(db_session)):
    run = _require_run(session, run_code)
    return _run_payload(run, session)


@router.get("/runs/{run_code}/report")
def failure_report(run_code: str, session: Session = Depends(db_session)):
    """The stored summary rendered as a grouped, human-readable report."""
    run = _require_run(session, run_code)
    summary = run.summary_json or {}
    return {
        "run_code": run.run_code,
        "markdown": _render_markdown(run, summary),
    }


@router.get("/suite")
def describe_suite() -> Dict[str, Any]:
    """What the suite checks, without running it."""
    return {
        "suite_code": SUITE_CODE,
        "case_count": len(ADVERSARIAL_CASES),
        "cases": [
            {
                "case_code": case.case_code,
                "category": case.category,
                "description": case.description,
                "expects_block": case.expects_block,
            }
            for case in ADVERSARIAL_CASES
        ],
    }


def _require_run(session: Session, run_code: str) -> AgentEvalRun:
    run = session.scalar(select(AgentEvalRun).where(AgentEvalRun.run_code == run_code))
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown eval run {run_code!r}"
        )
    return run


def _render_markdown(run: AgentEvalRun, summary: Dict[str, Any]) -> str:
    polarity = summary.get("by_polarity", {})
    blocked: Optional[Dict[str, Any]] = polarity.get("must_block")
    quiet: Optional[Dict[str, Any]] = polarity.get("must_pass")
    lines = [
        f"# {run.suite_code} against {run.target}",
        "",
        f"{run.passed_cases}/{run.total_cases} passed ({run.pass_rate:.0%}).",
        "",
    ]
    if blocked and quiet:
        lines.append(
            f"Catches real problems: {blocked['passed']}/{blocked['total']}. "
            f"Leaves everything else alone: {quiet['passed']}/{quiet['total']}."
        )
        lines.append("")

    failures = summary.get("failures", [])
    if not failures:
        lines.append("No failures.")
        return "\n".join(lines) + "\n"

    grouped: Dict[str, list] = {}
    for failure in failures:
        grouped.setdefault(failure.get("category", "uncategorised"), []).append(failure)
    for category in sorted(grouped):
        items = grouped[category]
        lines.append(f"## {category} ({len(items)} failing)")
        for item in items:
            lines.append(f"- **{item['case_code']}** — {item.get('description', '')}")
            lines.append(f"  - {item.get('failure_reason')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
