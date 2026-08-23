"""Agent output contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.content import ContinuityReport, ScenePlan, ScriptDraft
from app.schemas.registry import SCHEMA_REGISTRY, UnknownSchemaError, get_schema

SCENE = {
    "scene_id": "EP01_SC01",
    "scene_order": 1,
    "purpose": "hook",
    "location": "transit_station",
    "duration_estimate_sec": 35,
    "summary": "Terminal emits distorted memory fragments.",
    "emotion": "unease",
}


def test_registry_resolves_known_schemas():
    assert get_schema("script_draft_v1") is ScriptDraft
    assert len(SCHEMA_REGISTRY) == 10


def test_registry_rejects_unknown_schemas_with_a_listing():
    with pytest.raises(UnknownSchemaError, match="Known:"):
        get_schema("not_a_schema")


def test_registry_error_is_a_value_error():
    # Pydantic only folds ValueError into ValidationError; a KeyError here
    # would escape a field validator as an unhandled 500.
    assert issubclass(UnknownSchemaError, ValueError)


def test_script_runtime_drift_is_reported_against_the_target():
    script = ScriptDraft(
        script_id="s1",
        episode_id="EP01",
        runtime_target_minutes=8,
        scenes=[SCENE, {**SCENE, "scene_id": "EP01_SC02", "scene_order": 2, "duration_estimate_sec": 500}],
    )
    assert script.estimated_runtime_sec == 535
    assert script.runtime_drift_sec() == 55


def test_a_script_needs_at_least_one_scene():
    with pytest.raises(ValidationError):
        ScriptDraft(script_id="s1", episode_id="EP01", runtime_target_minutes=8, scenes=[])


def test_zero_length_scenes_are_rejected():
    with pytest.raises(ValidationError):
        ScriptDraft(
            script_id="s1", episode_id="EP01", runtime_target_minutes=8,
            scenes=[{**SCENE, "duration_estimate_sec": 0}],
        )


def test_unexpected_fields_are_rejected_rather_than_silently_dropped():
    with pytest.raises(ValidationError):
        ScriptDraft(
            script_id="s1", episode_id="EP01", runtime_target_minutes=8,
            scenes=[SCENE], surprise_field="nope",
        )


def test_scene_plan_shot_durations_can_be_checked_against_the_stated_total():
    plan = ScenePlan(
        scene_plan_id="p1",
        episode_id="EP01",
        runtime_total_sec=478,
        shots=[{
            "shot_id": "EP01_SH01", "scene_id": "EP01_SC01", "shot_order": 1,
            "framing": "close_up", "camera_motion": "slow_push_in",
            "background": "terminal_night", "transition_in": "hard_cut",
            "transition_out": "glitch_cut", "duration_sec": 8,
        }],
    )
    # The mismatch is exposed, not silently accepted: the scene-plan QC gate
    # is where a plan whose shots do not add up to its total gets caught.
    assert plan.shot_duration_sum() == 8
    assert plan.runtime_total_sec != plan.shot_duration_sum()


def test_continuity_status_drives_the_revision_loop():
    report = ContinuityReport(
        continuity_report_id="c1", episode_id="EP01", status="needs_revision",
        issues=[{
            "severity": "medium", "type": "world_rule_conflict", "scene_id": "EP01_SC03",
            "description": "Signal jump exceeds grid rules.", "suggested_fix": "Add relay node.",
        }],
    )
    assert report.needs_revision is True
    assert ContinuityReport(
        continuity_report_id="c2", episode_id="EP01", status="approved"
    ).needs_revision is False
