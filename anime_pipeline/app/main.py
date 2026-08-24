"""FastAPI application for the anime episode agent pipeline."""

from __future__ import annotations

from contextlib import asynccontextmanager

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.agents.registry import AGENTS
from app.api.routes import (
    auth,
    canon,
    episodes,
    evaluation,
    generation,
    jobs,
    memory,
    pipeline,
    qc_reports,
    system,
    tasks,
    webhooks,
    workspaces,
)
from app.api.middleware.correlation import CorrelationIdMiddleware
from app.core.config import get_settings, require_production_secret
from app.core.logging import configure_logging
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
    configure_logging()
    # Refuses to start a production deployment still signing tokens with the
    # shipped development key. A startup crash is the only failure mode loud
    # enough to stop that reaching real users.
    require_production_secret(get_settings())
    get_engine()
    seed_agents()
    yield


app = FastAPI(title="Anime Channel Agent Backend", version="0.1.0", lifespan=lifespan)

# Outermost: every log line and every queued job carries the request's id.
app.add_middleware(CorrelationIdMiddleware)

# The admin UI is a separate origin. Origins come from the environment because
# a wildcard with credentials is rejected by browsers anyway, and hardcoding
# localhost would leave production without a way to set its own.
_cors_origins = [o.strip() for o in os.getenv("ANIME_CORS_ORIGINS", "http://localhost:3001").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )

app.include_router(episodes.router, prefix="/episodes", tags=["episodes"])
app.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
app.include_router(qc_reports.router, prefix="/qc-reports", tags=["qc"])
app.include_router(pipeline.router, prefix="/pipeline", tags=["pipeline"])
app.include_router(memory.router, prefix="/memory", tags=["memory"])
app.include_router(canon.router, prefix="/canon", tags=["canon"])
app.include_router(evaluation.router, prefix="/evaluation", tags=["evaluation"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(generation.router, prefix="/generation", tags=["generation"])
app.include_router(system.router, prefix="/system", tags=["system"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])


@app.get("/health")
def health():
    return {"status": "ok"}
