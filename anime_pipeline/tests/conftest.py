from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from app.schemas.master_qc_report import CATEGORY_WEIGHTS, MasterQCReport


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
