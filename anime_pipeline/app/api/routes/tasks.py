"""Task envelope intake and completion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.api.routes.episodes import resolve_episode
from app.db.models import Agent, Task
from app.models.enums import TaskStatus
from app.models.task import TaskEnvelope
from app.schemas.registry import get_schema
from app.services.orchestrator import PIPELINE

router = APIRouter()

#: task_type -> pipeline stage. Each stage declares a distinct task_type, so the
#: mapping is unambiguous; a task_type outside the graph simply has no stage and
#: is invisible to the orchestrator.
_STAGE_BY_TASK_TYPE = {stage.task_type: stage.name for stage in PIPELINE}


def _stage_for(task_type: str):
    return _STAGE_BY_TASK_TYPE.get(task_type)


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_task(envelope: TaskEnvelope, session: Session = Depends(db_session)):
    episode = resolve_episode(session, envelope.episode_id)
    agent = session.scalar(
        select(Agent).where(Agent.agent_code == envelope.assigned_to.id)
    )
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown agent {envelope.assigned_to.id!r}; seed the agent registry first",
        )
    if session.scalar(select(Task).where(Task.task_code == envelope.task_id)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {envelope.task_id!r} already exists",
        )

    task = Task(
        episode_id=episode.id,
        agent_id=agent.id,
        task_code=envelope.task_id,
        task_type=envelope.task_type,
        stage=_stage_for(envelope.task_type),
        task_category=envelope.task_category.value,
        status=envelope.status,
        priority=envelope.priority,
        input_context=envelope.input_context,
        instructions=envelope.instructions.model_dump(),
        payload=envelope.payload,
        output_schema_name=envelope.output_spec.schema_name,
        due_at=envelope.due_at,
        approval_required=envelope.approval.required,
    )
    session.add(task)
    session.commit()
    return {"task_id": envelope.task_id, "status": task.status.value}


@router.post("/{task_code}/complete")
def complete_task(task_code: str, output: dict, session: Session = Depends(db_session)):
    """Store an agent's output, but only after it validates against its schema."""
    task = session.scalar(select(Task).where(Task.task_code == task_code))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if task.output_schema_name:
        schema = get_schema(task.output_schema_name)
        try:
            schema.model_validate(output)
        except Exception as exc:
            # Rejected output is not stored: a downstream agent must never read
            # a payload that failed its own contract.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"schema": task.output_schema_name, "error": str(exc)},
            ) from exc

    task.output_json = output
    task.status = (
        TaskStatus.waiting_for_review if task.approval_required else TaskStatus.completed
    )
    session.commit()
    return {"task_id": task_code, "status": task.status.value}


@router.get("/{task_code}")
def get_task(task_code: str, session: Session = Depends(db_session)):
    task = session.scalar(select(Task).where(Task.task_code == task_code))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return {
        "task_id": task.task_code,
        "task_type": task.task_type,
        "status": task.status.value,
        "output_schema": task.output_schema_name,
        "output": task.output_json,
    }
