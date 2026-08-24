"""Shared fixtures.

The default suite runs on SQLite, which is fast and needs nothing installed.
A handful of properties cannot be checked there -- JSONB behaviour, real
constraint enforcement, `SELECT ... FOR UPDATE` -- so `postgres_engine` opens a
real Postgres when one is available and skips cleanly when it is not. See its
docstring for how to give it one.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.schemas.master_qc_report import CATEGORY_WEIGHTS, MasterQCReport

#: Point this at a throwaway Postgres to run the dialect-specific tests, e.g.
#: ANIME_TEST_POSTGRES_URL=postgresql+psycopg://postgres:postgres@localhost:5432/anime_test
POSTGRES_URL_ENV = "ANIME_TEST_POSTGRES_URL"

#: Postgres image used when testcontainers spins one up.
POSTGRES_IMAGE = "postgres:16-alpine"


@pytest.fixture()
def client():
    """A TestClient backed by a throwaway SQLite database."""
    tmpdir = tempfile.mkdtemp()
    db_path = Path(tmpdir) / "test.db"
    os.environ["ANIME_DATABASE_URL"] = f"sqlite:///{db_path}"

    from app.core import database

    database.init_engine(create_all=True)

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def qc_report(
    score: int = 9,
    stage: str = "final_cut",
    report_id: str = "mqc_EP01_v1",
    episode_id: str = "EP01",
    **overrides,
) -> MasterQCReport:
    """A QC report with every category at `score`, plus any overrides."""
    payload = {
        "master_qc_report_id": report_id,
        "episode_id": episode_id,
        "qc_stage": stage,
        "sections": {name: {"score": score} for name in CATEGORY_WEIGHTS},
    }
    sections = overrides.pop("sections", None)
    if sections:
        payload["sections"].update(sections)
    payload.update(overrides)
    return MasterQCReport.model_validate(payload)


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------
def _testcontainers_url():
    """A disposable Postgres from testcontainers, or None.

    Returns None rather than raising for every reason it might be unavailable:
    the package is not installed, no Docker daemon is reachable, or the image
    cannot be pulled. A Postgres-only test that cannot get a Postgres should
    skip, not fail -- the SQLite suite still covers the logic, and turning an
    absent daemon into a red build teaches everyone to ignore red builds.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        return None
    try:
        container = PostgresContainer(POSTGRES_IMAGE, driver="psycopg")
        container.start()
    except Exception:  # noqa: BLE001 -- any startup failure means "not available"
        return None
    return container


@pytest.fixture(scope="session")
def postgres_url():
    """A Postgres URL, or a skip.

    Prefers an explicitly provided database so CI can supply its own service
    container; falls back to testcontainers when Docker is available locally.
    """
    explicit = os.environ.get(POSTGRES_URL_ENV)
    if explicit:
        yield explicit
        return

    container = _testcontainers_url()
    if container is None:
        pytest.skip(
            "No Postgres available. Set "
            f"{POSTGRES_URL_ENV} to a throwaway database, or install "
            "testcontainers with a running Docker daemon."
        )
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture()
def postgres_engine(postgres_url):
    """An engine on a schema built from the migrations, dropped afterwards.

    Built by running Alembic rather than `create_all`, because half the point
    of testing against Postgres is to check that the migration chain produces
    the schema the models expect -- `create_all` would bypass exactly that.
    """
    from alembic import command
    from alembic.config import Config

    engine = sa.create_engine(postgres_url)
    with engine.begin() as connection:
        connection.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(sa.text("CREATE SCHEMA public"))

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(config, "head")

    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def postgres_session(postgres_engine):
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=postgres_engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
