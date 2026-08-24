"""Adversarial benchmarks for the continuity system, and the harness that runs them.

Why this exists
---------------
Every gate in this pipeline has two failure modes, and only one of them is
visible. A gate that blocks something it should have passed generates a
complaint. A gate that passes something it should have blocked generates
nothing at all -- it looks exactly like a gate with nothing to catch.

The second failure is the one that ships broken canon, and the only way to
notice it is to keep a standing set of things that *must* be caught and check
periodically that they still are.

Why the suite is balanced
-------------------------
Half these cases assert that nothing fires. That is not padding. A matcher
that blocks every fact change scores 100% on a suite made only of real
contradictions, and would be worse than useless in production -- writers would
turn it off in a week. `expects_block` is tracked per case and reported per
side so a run says "catches everything, blocks nothing spurious" rather than
one number that cannot distinguish the two.

The cases are adversarial in the specific sense that each one is a way the
system has actually been wrong or could plausibly be wrong: a spelling drift,
a value formatting difference, a retcon disguised as progression, an approved
rewrite that must be let through.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentEvalCaseResult, AgentEvalRun, Episode, Series

#: Every case belongs to one of these, so a failure report can say "all four
#: alias cases broke" instead of listing four unrelated-looking failures.
CATEGORIES = (
    "entity_resolution",
    "value_normalisation",
    "mutability",
    "timeline",
    "retcon",
    "causality",
)


@dataclass
class EvalCase:
    """One adversarial scenario.

    `run` returns the observed outcome as a dict; `expectation` is the subset of
    keys that must match. Comparing a subset rather than the whole dict is
    deliberate: a case asserting "this must block" should not start failing
    because an unrelated field gained a key.
    """

    case_code: str
    category: str
    description: str
    expects_block: bool
    run: Callable[["EvalContext"], Dict[str, Any]]
    expectation: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalContext:
    """Everything a case needs to build its own fixture.

    Each case gets a fresh series so cases cannot contaminate each other --
    a contradiction left behind by one case would otherwise change the verdict
    of the next, and the suite would only be reproducible in order.
    """

    session: Session
    make_series: Callable[[str], Series]
    make_episode: Callable[..., Episode]


@dataclass
class CaseOutcome:
    case: EvalCase
    observed: Dict[str, Any]
    passed: bool
    failure_reason: Optional[str]
    duration_ms: int


@dataclass
class SuiteReport:
    run_code: str
    suite_code: str
    target: str
    outcomes: List[CaseOutcome] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def passed(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return round(self.passed / self.total, 4) if self.total else 0.0

    def by_category(self) -> Dict[str, Dict[str, int]]:
        buckets: Dict[str, Dict[str, int]] = {}
        for outcome in self.outcomes:
            bucket = buckets.setdefault(
                outcome.case.category, {"total": 0, "passed": 0, "failed": 0}
            )
            bucket["total"] += 1
            bucket["passed" if outcome.passed else "failed"] += 1
        return buckets

    def by_polarity(self) -> Dict[str, Dict[str, int]]:
        """Results split by whether the case expected the system to fire.

        The two halves answer different questions -- "does it catch real
        problems" and "does it leave everything else alone" -- and a single
        pass rate hides a system that has stopped doing one of them.
        """
        buckets = {
            "must_block": {"total": 0, "passed": 0, "failed": 0},
            "must_pass": {"total": 0, "passed": 0, "failed": 0},
        }
        for outcome in self.outcomes:
            key = "must_block" if outcome.case.expects_block else "must_pass"
            buckets[key]["total"] += 1
            buckets[key]["passed" if outcome.passed else "failed"] += 1
        return buckets

    def failures(self) -> List[Dict[str, Any]]:
        return [
            {
                "case_code": o.case.case_code,
                "category": o.case.category,
                "description": o.case.description,
                "expects_block": o.case.expects_block,
                "expected": o.case.expectation,
                "observed": o.observed,
                "failure_reason": o.failure_reason,
            }
            for o in self.outcomes
            if not o.passed
        ]

    def summary(self) -> Dict[str, Any]:
        return {
            "suite_code": self.suite_code,
            "target": self.target,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "by_category": self.by_category(),
            "by_polarity": self.by_polarity(),
            "failures": self.failures(),
        }

    def failure_report(self) -> str:
        """A human-readable report, grouped so patterns are visible.

        Grouped by category on purpose: nine scattered failures read as nine
        problems, while "every entity_resolution case failed" reads as one
        regression in one place, which is almost always what it is.
        """
        lines = [
            f"# {self.suite_code} against {self.target}",
            "",
            f"{self.passed}/{self.total} passed ({self.pass_rate:.0%}).",
            "",
        ]
        polarity = self.by_polarity()
        lines.append(
            "Catches real problems: "
            f"{polarity['must_block']['passed']}/{polarity['must_block']['total']}. "
            "Leaves everything else alone: "
            f"{polarity['must_pass']['passed']}/{polarity['must_pass']['total']}."
        )
        lines.append("")

        if not self.failed:
            lines.append("No failures.")
            return "\n".join(lines)

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for failure in self.failures():
            grouped.setdefault(failure["category"], []).append(failure)

        for category in sorted(grouped):
            items = grouped[category]
            lines.append(f"## {category} ({len(items)} failing)")
            for item in items:
                lines.append(f"- **{item['case_code']}** — {item['description']}")
                lines.append(f"  - {item['failure_reason']}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


class EvaluationHarness:
    """Runs a suite of cases and persists the result."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(
        self,
        cases: Sequence[EvalCase],
        *,
        suite_code: str,
        target: str,
        context: EvalContext,
        persist: bool = True,
        run_code: Optional[str] = None,
    ) -> SuiteReport:
        report = SuiteReport(
            run_code=run_code or f"eval_{uuid.uuid4().hex[:12]}",
            suite_code=suite_code,
            target=target,
        )
        run_row: Optional[AgentEvalRun] = None
        if persist:
            run_row = AgentEvalRun(
                run_code=report.run_code,
                suite_code=suite_code,
                target=target,
                status="running",
                total_cases=len(cases),
            )
            self.session.add(run_row)
            self.session.flush()

        for case in cases:
            started = time.perf_counter()
            # Each case runs inside a savepoint that is always rolled back.
            # Two reasons, both load-bearing: the fixtures a case builds must
            # not reach the next case, and a case that fails with a database
            # error would otherwise poison the session for every case after it
            # -- turning one failure into a suite-wide outage that hides what
            # else was broken.
            savepoint = self.session.begin_nested()
            try:
                observed = case.run(context)
                failure = _mismatch(case.expectation, observed)
            except Exception as exc:  # noqa: BLE001 -- a raising case is a failing case
                observed = {"error": f"{type(exc).__name__}: {exc}"}
                failure = f"case raised {type(exc).__name__}: {exc}"
            finally:
                savepoint.rollback()
            duration_ms = int((time.perf_counter() - started) * 1000)

            outcome = CaseOutcome(
                case=case,
                observed=observed,
                passed=failure is None,
                failure_reason=failure,
                duration_ms=duration_ms,
            )
            report.outcomes.append(outcome)

            if persist and run_row is not None:
                self.session.add(
                    AgentEvalCaseResult(
                        run_id=run_row.id,
                        case_code=case.case_code,
                        category=case.category,
                        expects_block=case.expects_block,
                        expectation_json=case.expectation,
                        observed_json=observed,
                        passed=outcome.passed,
                        failure_reason=failure,
                        duration_ms=duration_ms,
                    )
                )

        if persist and run_row is not None:
            run_row.passed_cases = report.passed
            run_row.failed_cases = report.failed
            run_row.pass_rate = report.pass_rate
            run_row.status = "passed" if report.failed == 0 else "failed"
            run_row.summary_json = report.summary()
            run_row.finished_at = datetime.now(timezone.utc)
            self.session.flush()

        return report

    def by_run_code(self, run_code: str) -> Optional[AgentEvalRun]:
        return self.session.scalar(
            select(AgentEvalRun).where(AgentEvalRun.run_code == run_code)
        )


def _mismatch(expectation: Dict[str, Any], observed: Dict[str, Any]) -> Optional[str]:
    """The first expectation the observation fails, or None."""
    for key, want in expectation.items():
        if key not in observed:
            return f"expected key {key!r} missing from result"
        got = observed[key]
        if got != want:
            return f"{key}: expected {want!r}, got {got!r}"
    return None
