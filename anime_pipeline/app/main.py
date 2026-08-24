"""FastAPI application for the anime episode agent pipeline."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.agents.registry import AGENTS
from app.api.routes import episodes, memory, pipeline, qc_reports, tasks, webhooks
from app.core.database import get_engine, get_session
from app.db.models import Agent


def seed_agents() -> int:
    """Insert any registered agent that is not yet in the database."""
    added = 0
    for session in get_session():
        for spec in AGENTS:
            exists = session.scalar(select(Agent).where(Agent.agent_code == spec.agent_code))
            if exists:
                continue
            session.add(
                Agent(
                    agent_code=spec.agent_code,
                    display_name=spec.display_name,
                    role_description=spec.role_description,
                    system_prompt_version="v1",
                )
            )
            added += 1
        session.commit()
    return added


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_engine()
    seed_agents()
    yield


app = FastAPI(title="Anime Channel Agent Backend", version="0.1.0", lifespan=lifespan)

app.include_router(episodes.router, prefix="/episodes", tags=["episodes"])
app.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
app.include_router(qc_reports.router, prefix="/qc-reports", tags=["qc"])
app.include_router(pipeline.router, prefix="/pipeline", tags=["pipeline"])
app.include_router(memory.router, prefix="/memory", tags=["memory"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])


@app.get("/health")
def health():
    return {"status": "ok"}
