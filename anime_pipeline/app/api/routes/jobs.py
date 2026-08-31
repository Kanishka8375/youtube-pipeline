"""The background job queue: enqueue, inspect, drain."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session
from app.db.models import User
from app.services.jobs.job_queue import JobQueue

router = APIRouter()


class JobEnqueue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type: str = Field(min_length=1, max_length=128)
    payload: Dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=10)


class DrainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_jobs: int = Field(default=25, ge=1, le=500)


def _job_payload(job) -> dict:
    return {
        "id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "payload": job.payload_json,
        "result": job.result_json,
        "error_message": job.error_message,
        "correlation_id": job.correlation_id,
        "scheduled_for": job.scheduled_for.isoformat() if job.scheduled_for else None,
        "created_at": job.created_at.isoformat(),
    }


def _handlers(session: Session) -> Dict[str, Any]:
    """The handler registry, assembled per request.

    Imported lazily so the jobs module does not depend on the generation stack
    at import time -- the queue is useful with no providers configured at all.
    """
    from app.services.generation.job_handlers import generation_handlers

    return generation_handlers(session)


@router.post("", status_code=status.HTTP_201_CREATED)
def enqueue_job(
    body: JobEnqueue,
    session: Session = Depends(db_session),
    user: User = Depends(current_user),
):
    known = _handlers(session)
    if body.job_type not in known:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown job_type {body.job_type!r}. "
                f"Known types: {sorted(known)}"
            ),
        )
    job = JobQueue(session).enqueue(
        job_type=body.job_type, payload=body.payload, max_attempts=body.max_attempts
    )
    session.commit()
    return _job_payload(job)


@router.get("")
def list_jobs(
    limit: int = 50,
    session: Session = Depends(db_session),
    user: User = Depends(current_user),
):
    return [_job_payload(j) for j in JobQueue(session).recent(limit=min(limit, 200))]


@router.get("/handlers")
def list_handlers(
    session: Session = Depends(db_session),
    user: User = Depends(current_user),
):
    """Which job types this deployment can actually run."""
    return {"job_types": sorted(_handlers(session))}


@router.get("/{job_id}")
def get_job(
    job_id: uuid.UUID,
    session: Session = Depends(db_session),
    user: User = Depends(current_user),
):
    job = JobQueue(session).by_id(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown job")
    return _job_payload(job)


@router.post("/drain")
def drain_queue(
    body: DrainRequest,
    session: Session = Depends(db_session),
    user: User = Depends(current_user),
):
    """Run queued work inline.

    An endpoint rather than only a worker process so a single-container
    deployment has a way to make progress. A real deployment runs
    `python -m app.worker` instead and leaves this for tests and local use.
    """
    outcomes = JobQueue(session).drain(_handlers(session), max_jobs=body.max_jobs)
    session.commit()
    return {
        "ran": len(outcomes),
        "outcomes": [
            {"job_id": str(o.job.id), "job_type": o.job.job_type, "status": o.status, "error": o.error}
            for o in outcomes
        ],
    }
