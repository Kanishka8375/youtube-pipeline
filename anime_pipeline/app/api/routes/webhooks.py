"""Event intake for the orchestrator.

The in-process `WorkflowState` cache below is deliberate scaffolding: it keeps
the event surface exercisable before a repository layer exists. It is not
production-safe -- it is per-process and lost on restart. Replace
`_load_state`/`_save_state` with database-backed equivalents before deploying
more than one worker.
"""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter

from app.models.api import EventIn
from app.services.orchestrator import Orchestrator, WorkflowState

router = APIRouter()

_orchestrator = Orchestrator()
_states: Dict[str, WorkflowState] = {}


def _load_state(episode_id: str) -> WorkflowState:
    return _states.setdefault(episode_id, WorkflowState(episode_id=episode_id))


@router.post("/events")
def receive_event(body: EventIn):
    episode_id = body.payload.get("episode_id")
    if not episode_id:
        return {"status": "ignored", "reason": "payload has no episode_id"}
    state = _load_state(episode_id)
    result = _orchestrator.on_event(state, body.event, body.payload)
    return {"event": body.event, "episode_id": episode_id, **result}


@router.get("/state/{episode_id}")
def get_state(episode_id: str):
    state = _load_state(episode_id)
    gate = _orchestrator.can_publish(state)
    return {
        "episode_id": episode_id,
        "tasks": {
            task_id: {"stage": task.stage, "status": task.status.value}
            for task_id, task in state.tasks.items()
        },
        "qc_reports": {
            stage.value: report.overall_score for stage, report in state.qc_reports.items()
        },
        "blockers": state.blockers,
        "runnable": _orchestrator.runnable_stages(state),
        "publish_ready": gate.ok,
        "publish_blockers": gate.reasons,
    }
