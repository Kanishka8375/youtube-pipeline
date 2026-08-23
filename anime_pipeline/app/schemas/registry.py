"""Maps `output_spec.schema_name` to the model that validates it."""

from __future__ import annotations

from typing import Dict, Type

from pydantic import BaseModel

from app.schemas.content import (
    AnalyticsReport,
    AssetRequest,
    BeatSheet,
    ContinuityReport,
    EpisodeBrief,
    PackagingSet,
    ScenePlan,
    ScriptDraft,
)
from app.schemas.master_qc_report import MasterQCReport, SceneEditorQCNote

SCHEMA_REGISTRY: Dict[str, Type[BaseModel]] = {
    "episode_brief_v1": EpisodeBrief,
    "beat_sheet_v1": BeatSheet,
    "script_draft_v1": ScriptDraft,
    "continuity_report_v1": ContinuityReport,
    "scene_plan_v1": ScenePlan,
    "asset_request_v1": AssetRequest,
    "packaging_v1": PackagingSet,
    "analytics_report_v1": AnalyticsReport,
    "master_qc_report_v1": MasterQCReport,
    "scene_editor_qc_note_v1": SceneEditorQCNote,
}


class UnknownSchemaError(ValueError):
    """Raised when a task names an output schema the registry does not carry.

    Deliberately a ValueError, not a KeyError: it is raised from Pydantic field
    validators, and Pydantic only folds ValueError/AssertionError into a
    ValidationError. A KeyError would escape as an unhandled 500 instead.
    """


def get_schema(schema_name: str) -> Type[BaseModel]:
    try:
        return SCHEMA_REGISTRY[schema_name]
    except KeyError as exc:
        raise UnknownSchemaError(
            f"Unknown output schema {schema_name!r}. "
            f"Known: {', '.join(sorted(SCHEMA_REGISTRY))}"
        ) from exc
