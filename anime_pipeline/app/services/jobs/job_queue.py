"""A database-backed job queue.

Not a replacement for Celery/RQ/Arq -- it is the smallest thing that makes
deferred work durable and inspectable without adding a broker. What it does
provide, and what a naive `BackgroundTasks` call does not:

- **Survival.** A queued row outlives the process that queued it.
- **Bounded retries with backoff**, so a provider outage does not become a hot
  loop against a failing endpoint.
- **Claiming under a row lock**, so two workers cannot run the same job twice.
- **A terminal record** of what failed and why.

The one thing to know before scaling this out: `claim_next` relies on
`SELECT ... FOR UPDATE SKIP LOCKED`, which SQLite ignores. On SQLite the queue
is correct only with a single worker; on Postgres it is safe with many.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.request_context import current_correlation_id
from app.db.models import BackgroundJob

logger = logging.getLogger(__name__)

QUEUED = "queued"
RUNNING = "running"
RETRYING = "retrying"
COMPLETED = "completed"
FAILED = "failed"

#: Statuses a worker may pick up.
RUNNABLE = (QUEUED, RETRYING)
#: Statuses from which nothing further happens.
TERMINAL = (COMPLETED, FAILED)

#: Dialects where `FOR UPDATE SKIP LOCKED` actually locks. SQLite parses and
#: ignores it, which would let two workers claim one job.
_ROW_LOCK_DIALECTS = frozenset({"postgresql", "mysql", "mariadb", "oracle"})

#: Backoff in seconds, indexed by attempt number. Beyond the list, the last
#: value repeats. Capped rather than unbounded exponential: a job that has
#: failed four times needs a human, not a longer nap.
RETRY_BACKOFF_SECONDS = (30, 120, 600)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def backoff_for(attempt_count: int) -> timedelta:
    index = min(max(attempt_count - 1, 0), len(RETRY_BACKOFF_SECONDS) - 1)
    return timedelta(seconds=RETRY_BACKOFF_SECONDS[index])


class UnknownJobTypeError(ValueError):
    """Raised when a job's type has no registered handler.

    Treated as a permanent failure, not a retryable one: retrying a job whose
    handler does not exist burns the whole retry budget on the same import
    error and buries the real cause.
    """


@dataclass
class JobOutcome:
    job: BackgroundJob
    status: str
    result: Dict[str, Any]
    error: Optional[str]


class JobQueue:
    """Enqueue, claim, and run."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # -- producing -----------------------------------------------------------
    def enqueue(
        self,
        *,
        job_type: str,
        payload: Optional[Dict[str, Any]] = None,
        max_attempts: int = 3,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> BackgroundJob:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        job = BackgroundJob(
            job_type=job_type,
            status=QUEUED,
            attempt_count=0,
            max_attempts=max_attempts,
            payload_json=payload or {},
            result_json={},
            # Captured at enqueue time so the work can be traced back to the
            # request that asked for it, long after that request has finished.
            correlation_id=current_correlation_id(),
            workspace_id=workspace_id,
        )
        self.session.add(job)
        self.session.flush()
        return job

    # -- consuming -----------------------------------------------------------
    def runnable(self, *, limit: int = 50) -> Sequence[BackgroundJob]:
        return self.session.scalars(self._runnable_stmt().limit(limit)).all()

    def _runnable_stmt(self):
        now = _now()
        return (
            select(BackgroundJob)
            .where(
                BackgroundJob.status.in_(RUNNABLE),
                # NULL means "now"; a retry sets a future time.
                (BackgroundJob.scheduled_for.is_(None))
                | (BackgroundJob.scheduled_for <= now),
            )
            .order_by(BackgroundJob.created_at)
        )

    def claim_next(self) -> Optional[BackgroundJob]:
        """Take the oldest eligible job and mark it running.

        `SKIP LOCKED` is what lets several workers drain the queue in parallel
        without coordinating: each skips rows another has already claimed
        rather than blocking behind them.
        """
        stmt = self._runnable_stmt().limit(1)
        if self.session.bind.dialect.name in _ROW_LOCK_DIALECTS:
            stmt = stmt.with_for_update(skip_locked=True)

        job = self.session.scalar(stmt)
        if job is None:
            return None

        self._mark_running(job)
        return job

    def _mark_running(self, job: BackgroundJob) -> None:
        """Record the attempt, durably, before the handler runs.

        Committed rather than flushed, and this is the whole subtlety of the
        queue. A handler that fails leaves the session dirty, so `execute` must
        roll back before it can record the failure -- and a rollback would undo
        an uncommitted increment. The attempt count would then reset on every
        failure, the retry budget would never deplete, and a permanently broken
        job would retry forever.

        Committing here also makes the claim survive a worker crash: the row is
        already `running` with the attempt spent, so a restarted worker does not
        hand the same job a fresh budget.
        """
        job.status = RUNNING
        job.attempt_count += 1
        job.started_at = _now()
        self.session.commit()

    def run_one(self, handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]) -> Optional[JobOutcome]:
        """Claim and execute a single job. Returns None when the queue is idle."""
        job = self.claim_next()
        if job is None:
            return None
        return self.execute(job, handlers)

    def execute(
        self, job: BackgroundJob, handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]
    ) -> JobOutcome:
        """Run one job. Safe to call directly, not only via `run_one`.

        The attempt is recorded here when the caller has not already claimed the
        job, so the retry budget depletes no matter which entry point is used --
        two entry points where only one maintains the invariant is how a budget
        silently stops applying.
        """
        if job.status != RUNNING:
            self._mark_running(job)

        handler = handlers.get(job.job_type)
        if handler is None:
            return self._finish(
                job,
                status=FAILED,
                error=f"No handler registered for job_type {job.job_type!r}",
            )

        try:
            result = handler(dict(job.payload_json or {}))
        except Exception as exc:  # noqa: BLE001 -- any handler failure is a job failure
            # Rolled back first: a handler that failed mid-write leaves the
            # session dirty, and the status update below would otherwise flush
            # its partial work along with it.
            self.session.rollback()
            job = self.session.get(BackgroundJob, job.id)
            logger.warning(
                "job %s (%s) attempt %s/%s failed: %s",
                job.id, job.job_type, job.attempt_count, job.max_attempts, exc,
            )
            if job.attempt_count >= job.max_attempts:
                return self._finish(job, status=FAILED, error=f"{type(exc).__name__}: {exc}")

            job.status = RETRYING
            job.scheduled_for = _now() + backoff_for(job.attempt_count)
            job.error_message = f"{type(exc).__name__}: {exc}"
            self.session.flush()
            return JobOutcome(job=job, status=RETRYING, result={}, error=job.error_message)

        return self._finish(job, status=COMPLETED, result=result or {})

    def _finish(
        self,
        job: BackgroundJob,
        *,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> JobOutcome:
        job.status = status
        job.result_json = result or {}
        job.error_message = error
        job.completed_at = _now()
        job.scheduled_for = None
        self.session.flush()
        return JobOutcome(job=job, status=status, result=job.result_json, error=error)

    def drain(
        self,
        handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]],
        *,
        max_jobs: int = 100,
    ) -> list[JobOutcome]:
        """Run until the queue is empty or `max_jobs` is reached.

        The cap is not politeness: a handler that enqueues another job would
        otherwise let `drain` never return.
        """
        outcomes: list[JobOutcome] = []
        for _ in range(max_jobs):
            outcome = self.run_one(handlers)
            if outcome is None:
                break
            outcomes.append(outcome)
        return outcomes

    def by_id(self, job_id: uuid.UUID) -> Optional[BackgroundJob]:
        return self.session.get(BackgroundJob, job_id)

    def recent(self, *, limit: int = 50, workspace_id: Optional[uuid.UUID] = None) -> Sequence[BackgroundJob]:
        stmt = select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(limit)
        if workspace_id is not None:
            stmt = stmt.where(BackgroundJob.workspace_id == workspace_id)
        return self.session.scalars(stmt).all()
