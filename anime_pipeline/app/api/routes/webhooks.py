"""Event intake for the orchestrator.

Workflow state lives in the database, not in this process. Each event is handled
inside a per-episode lock (`WorkflowStateRepository.locked`), so the route is
safe to run behind any number of workers and survives a restart with the
episode's progress intact.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.models.api import EventIn
from app.services.orchestrator import Orchestrator
from app.services.workflow_repository import UnknownEpisodeError, WorkflowStateRepository

router = APIRouter()

_orchestrator = Orchestrator()

#: Events whose payload the route enriches before the orchestrator sees it.
_QC_EVENT = "qc.reported"


def _resolve_qc_report(repo: WorkflowStateRepository, payload: dict) -> dict:
    """Turn a QC event into the report object the orchestrator expects.

    Preferred form is `{"master_qc_report_id": "..."}`, resolved from the
    database. An inline `report` is also accepted, but it must already have been
    stored via `POST /qc-reports/` -- a report that exists only in an event
    payload would vanish on the next load, which is the exact failure this
    module removes.
    """
    report_id = payload.get("master_qc_report_id")
    if report_id:
        report = repo.qc_report_by_code(report_id)
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown QC report {report_id!r}; submit it to /qc-reports/ first",
            )
        return {**payload, "report": report}

    if "report" not in payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "qc.reported needs master_qc_report_id (preferred) or an inline "
                "report; the report must already exist via POST /qc-reports/"
            ),
        )
    return payload


@router.post("/events")
def receive_event(body: EventIn, session: Session = Depends(db_session)):
    episode_code = body.payload.get("episode_id")
    if not episode_code:
        return {"status": "ignored", "reason": "payload has no episode_id"}

    repo = WorkflowStateRepository(session)
    payload = body.payload
    if body.event == _QC_EVENT:
        payload = _resolve_qc_report(repo, payload)

    try:
        with repo.locked(episode_code) as state:
            result = _orchestrator.on_event(state, body.event, payload)
    except UnknownEpisodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    return {"event": body.event, "episode_id": episode_code, **result}


@router.get("/state/{episode_code}")
def get_state(episode_code: str, session: Session = Depends(db_session)):
    repo = WorkflowStateRepository(session)
    try:
        state = repo.load(episode_code)
    except UnknownEpisodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    gate = _orchestrator.can_publish(state)
    return {
        "episode_id": episode_code,
        "tasks": {
            task_id: {
                "stage": task.stage,
                "status": task.status.value,
                "retry_count": task.retry_count,
            }
            for task_id, task in state.tasks.items()
        },
        "qc_reports": {
            stage.value: {
                "report_id": report.master_qc_report_id,
                "overall_score": report.overall_score,
                "publish_ready": report.publish_ready,
            }
            for stage, report in state.qc_reports.items()
        },
        "blockers": state.blockers,
        "runnable": _orchestrator.runnable_stages(state),
        "publish_ready": gate.ok,
        "publish_blockers": gate.reasons,
    }
