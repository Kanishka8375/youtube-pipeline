"""Durable `WorkflowState`: load it from the database, write mutations back.

The orchestrator stays free of any database dependency -- that is what keeps its
gating logic unit-testable. This module is the seam between it and Postgres:

    with repo.locked(episode_code) as state:      # BEGIN; SELECT ... FOR UPDATE
        result = orchestrator.on_event(state, event, payload)
    #                                             # flush mutations; COMMIT

Holding the episode row for the whole block is what makes this safe across
workers. Two events for the same episode land in the same critical section, so
they serialise; events for different episodes do not contend at all. Without it,
two workers could each read `retry_count = 1`, each write `2`, and lose a retry.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Iterator, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Episode, EpisodeBlocker, MasterQCReport as MasterQCReportRow, Task
from app.models.enums import QCStage
from app.schemas.master_qc_report import MasterQCReport
from app.services.orchestrator import TaskState, WorkflowState

#: Dialects whose `SELECT ... FOR UPDATE` we can rely on. SQLite has no row
#: locks, but it serialises writers with a database-level lock, which gives the
#: same mutual exclusion for a single-file test or dev database.
_ROW_LOCK_DIALECTS = frozenset({"postgresql", "mysql", "mariadb", "oracle"})


class UnknownEpisodeError(LookupError):
    """Raised when an event names an episode that does not exist."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowStateRepository:
    """Reads and writes the orchestrator's view of an episode."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # -- loading --------------------------------------------------------
    def _episode(self, episode_code: str, *, for_update: bool = False) -> Episode:
        stmt = select(Episode).where(Episode.episode_code == episode_code)
        if for_update and self.session.bind.dialect.name in _ROW_LOCK_DIALECTS:
            stmt = stmt.with_for_update()
        episode = self.session.scalar(stmt)
        if episode is None:
            raise UnknownEpisodeError(f"Unknown episode {episode_code!r}")
        return episode

    def load(self, episode_code: str, *, for_update: bool = False) -> WorkflowState:
        episode = self._episode(episode_code, for_update=for_update)
        return WorkflowState(
            episode_id=episode.episode_code,
            tasks=self._load_tasks(episode.id),
            qc_reports=self._load_qc_reports(episode.id),
            blockers=self._load_blockers(episode.id),
        )

    def _load_tasks(self, episode_uuid: uuid.UUID) -> Dict[str, TaskState]:
        rows = self.session.scalars(
            select(Task).where(Task.episode_id == episode_uuid, Task.stage.is_not(None))
        ).all()
        return {
            row.task_code: TaskState(
                task_id=row.task_code,
                stage=row.stage,
                status=row.status,
                retry_count=row.retry_count,
            )
            for row in rows
        }

    def _load_qc_reports(self, episode_uuid: uuid.UUID) -> Dict[QCStage, MasterQCReport]:
        # Newest first, so the first row seen for a stage is the one that gates
        # it and later (older) rows are skipped.
        rows = self.session.scalars(
            select(MasterQCReportRow)
            .where(MasterQCReportRow.episode_id == episode_uuid)
            .order_by(MasterQCReportRow.created_at.desc())
        ).all()
        latest: Dict[QCStage, MasterQCReport] = {}
        for row in rows:
            if row.qc_stage in latest:
                continue
            latest[row.qc_stage] = qc_row_to_schema(row)
        return latest

    def _load_blockers(self, episode_uuid: uuid.UUID) -> List[str]:
        rows = self.session.scalars(
            select(EpisodeBlocker)
            .where(
                EpisodeBlocker.episode_id == episode_uuid,
                EpisodeBlocker.resolved_at.is_(None),
            )
            .order_by(EpisodeBlocker.created_at)
        ).all()
        return [row.description for row in rows]

    # -- persistence ----------------------------------------------------
    def save(self, state: WorkflowState) -> None:
        """Write back the fields the orchestrator is allowed to change.

        Deliberately narrow: task status and retry count, and the set of active
        blockers. Everything else on those rows belongs to whoever created them.
        """
        episode = self._episode(state.episode_id)
        self._save_tasks(episode.id, state)
        self._save_blockers(episode.id, state)

    def _save_tasks(self, episode_uuid: uuid.UUID, state: WorkflowState) -> None:
        if not state.tasks:
            return
        rows = self.session.scalars(
            select(Task).where(
                Task.episode_id == episode_uuid,
                Task.task_code.in_(state.tasks.keys()),
            )
        ).all()
        for row in rows:
            task = state.tasks[row.task_code]
            if row.status != task.status:
                row.status = task.status
                if task.status.value == "in_progress" and row.started_at is None:
                    row.started_at = _now()
                elif task.status.value in {"completed", "approved"}:
                    row.completed_at = _now()
            row.retry_count = task.retry_count

    def _save_blockers(self, episode_uuid: uuid.UUID, state: WorkflowState) -> None:
        rows = self.session.scalars(
            select(EpisodeBlocker).where(
                EpisodeBlocker.episode_id == episode_uuid,
                EpisodeBlocker.resolved_at.is_(None),
            )
        ).all()
        existing = {row.description: row for row in rows}
        wanted = set(state.blockers)

        for description, row in existing.items():
            if description not in wanted:
                row.resolved_at = _now()

        for description in state.blockers:
            if description not in existing:
                self.session.add(
                    EpisodeBlocker(episode_id=episode_uuid, description=description)
                )

    # -- the critical section -------------------------------------------
    @contextmanager
    def locked(self, episode_code: str) -> Iterator[WorkflowState]:
        """Load, yield for mutation, persist, commit -- under one episode lock.

        The lock is released by the commit, so the block should stay short:
        orchestrator decisions only, no provider calls.
        """
        state = self.load(episode_code, for_update=True)
        try:
            yield state
            self.save(state)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    # -- QC report resolution -------------------------------------------
    def qc_report_by_code(self, master_qc_report_id: str) -> Optional[MasterQCReport]:
        row = self.session.scalar(
            select(MasterQCReportRow).where(
                MasterQCReportRow.master_qc_report_id == master_qc_report_id
            )
        )
        return qc_row_to_schema(row) if row is not None else None


def qc_row_to_schema(row: MasterQCReportRow) -> MasterQCReport:
    """Rebuild the report from its sections.

    Re-validating on read recomputes `overall_score`, `anime_style_score` and
    `publish_ready`, so a row whose stored totals were edited by hand cannot
    open a gate its own section scores do not support.
    """
    return MasterQCReport.model_validate(
        {
            "master_qc_report_id": row.master_qc_report_id,
            "episode_id": row.episode.episode_code,
            "qc_stage": row.qc_stage,
            "qc_type": row.qc_type,
            "status": row.status,
            "sections": row.sections,
            "critical_issues": row.critical_issues,
            "required_fixes_before_publish": row.required_fixes_before_publish,
            "optional_polish_suggestions": row.optional_polish_suggestions,
            "final_notes": row.final_notes,
        }
    )
