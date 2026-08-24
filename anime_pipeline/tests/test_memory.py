"""Canon memory: bundles, the consistency guard, and auto-writeback."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import CharacterProfile, ContinuityCheck, MemoryDocument, MemoryFact
from app.services.consistency_guard import ConsistencyGuardService, SpeakerResolver
from app.services.memory_service import (
    InvalidMemoryScopeError,
    MemoryBundleService,
    MultipleActiveStyleBiblesError,
    validate_scope,
)
from tests.test_workflow_persistence import EPISODE, fresh_session, make_episode

SERIES = "NEON_VEIL"

MIRA = {
    "series_code": SERIES,
    "character_code": "MIRA",
    "display_name": "Mira Kisaragi",
    "aliases": ["Kisaragi"],
    "personality_traits": ["guarded", "observant"],
    "speech_style": {
        "tone": "short, precise, rarely overexplains",
        "forbidden_phrases": ["totally", "you got this"],
        "max_line_words": 12,
        "max_consecutive_lines": 2,
        "notes_for_reviewer": ["never becomes bubbly comic relief"],
    },
    "do_not_change": ["never becomes bubbly comic relief"],
}


def add_character(client, **overrides):
    response = client.post("/memory/characters", json={**MIRA, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def add_style_bible(client, **overrides):
    payload = {
        "series_code": SERIES,
        "style_code": "NEON_VEIL_STYLE_V1",
        "title": "Neon Veil Style Bible",
        "frame_rate": 24.0,
        "dialogue_rules": {"banned_terms": ["mana core"]},
        "negative_rules": ["no comedy smash cuts"],
    }
    response = client.post("/memory/style-bibles", json={**payload, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def script(*lines, scene_id="EP01_SC01", summary="", narration=None):
    return {
        "scenes": [
            {
                "scene_id": scene_id,
                "summary": summary,
                "narration": narration or [],
                "dialogue": [{"speaker": s, "line": t} for s, t in lines],
            }
        ]
    }


def guard_for(client, session):
    from app.api.routes.episodes import resolve_episode

    episode = resolve_episode(session, "EP01")
    service = MemoryBundleService(session)
    return ConsistencyGuardService(
        profiles=service.character_profiles(episode.series_id),
        style_bible=service.active_style_bible(episode.series_id),
    )


# ---------------------------------------------------------------------------
# Speaker resolution -- the spec's version keyed only on character_code, which
# resolves nothing, because scripts credit speakers by name.
# ---------------------------------------------------------------------------
class _Profile:
    def __init__(self, code, name, aliases=()):
        self.character_code = code
        self.display_name = name
        self.aliases = list(aliases)


@pytest.mark.parametrize("speaker", ["MIRA", "mira", "Mira Kisaragi", "Mira", "Kisaragi", " mira "])
def test_speaker_resolves_by_code_name_alias_and_first_name(speaker):
    resolver = SpeakerResolver([_Profile("MIRA", "Mira Kisaragi", ["Kisaragi"])])
    assert resolver.resolve(speaker).character_code == "MIRA"


def test_unknown_speaker_resolves_to_nothing():
    resolver = SpeakerResolver([_Profile("MIRA", "Mira Kisaragi")])
    assert resolver.resolve("Terminal Voice") is None
    assert resolver.resolve("") is None


# ---------------------------------------------------------------------------
# The consistency guard
# ---------------------------------------------------------------------------
def test_forbidden_phrase_is_caught(client):
    make_episode(client)
    add_character(client)
    with fresh_session() as session:
        result = guard_for(client, session).validate_script(
            script(("Mira", "That was totally the signal."))
        )
    assert result.passed is False
    assert result.issues[0].check == "forbidden_phrase"
    assert "totally" in result.issues[0].detail


def test_forbidden_phrase_matching_respects_word_boundaries(client):
    # A naive substring check would flag "totally" inside "totality".
    make_episode(client)
    add_character(client)
    with fresh_session() as session:
        result = guard_for(client, session).validate_script(
            script(("Mira", "The totality of it."))
        )
    assert result.passed is True


def test_prose_rules_do_not_masquerade_as_checks(client):
    # "never becomes bubbly comic relief" cannot be checked by substring match,
    # so it must be carried to the reviewer rather than silently passed.
    make_episode(client)
    add_character(client)
    with fresh_session() as session:
        result = guard_for(client, session).validate_script(
            script(("Mira", "Hehe, whatever you say!"))
        )
    assert result.passed is True, "no mechanical rule fires here"
    carried = result.not_mechanically_checked[0]
    assert carried["entity_key"] == "MIRA"
    assert "never becomes bubbly comic relief" in carried["reviewer_rules"]
    assert "tone" in carried["speech_style_keys_not_checked"]


def test_overlong_line_is_caught(client):
    make_episode(client)
    add_character(client)
    with fresh_session() as session:
        result = guard_for(client, session).validate_script(
            script(("Mira", " ".join(["word"] * 20)))
        )
    assert [i.check for i in result.issues] == ["line_too_long"]


def test_monologue_cap_fires_once_not_per_line(client):
    make_episode(client)
    add_character(client)
    with fresh_session() as session:
        result = guard_for(client, session).validate_script(
            script(*[("Mira", "Short line.")] * 5)
        )
    assert [i.check for i in result.issues] == ["monologue"]


def test_banned_series_terminology_is_caught(client):
    make_episode(client)
    add_character(client)
    add_style_bible(client)
    with fresh_session() as session:
        result = guard_for(client, session).validate_script(
            script(("Mira", "Check the mana core."))
        )
    assert any(i.check == "banned_term" for i in result.issues)


def test_unknown_speakers_are_reported_not_silently_skipped(client):
    make_episode(client)
    add_character(client)
    with fresh_session() as session:
        result = guard_for(client, session).validate_script(
            script(("Terminal Voice", "Mira... don't let them erase me."))
        )
    assert result.unknown_speakers == ["Terminal Voice"]


def test_guard_reads_the_line_field_used_by_the_script_schema(client):
    # The script contract calls this `line`; a guard reading `text` would check
    # an empty string and pass everything.
    make_episode(client)
    add_character(client)
    with fresh_session() as session:
        guard = guard_for(client, session)
        by_line = guard.validate_script(
            {"scenes": [{"scene_id": "S1", "dialogue": [{"speaker": "Mira", "line": "totally"}]}]}
        )
        by_text = guard.validate_script(
            {"scenes": [{"scene_id": "S1", "dialogue": [{"speaker": "Mira", "text": "totally"}]}]}
        )
    assert by_line.passed is False
    assert by_text.passed is False


# ---------------------------------------------------------------------------
# Memory bundles
# ---------------------------------------------------------------------------
def test_bundle_carries_canon_characters_and_style(client):
    make_episode(client)
    add_character(client)
    add_style_bible(client)
    client.post(
        "/memory/documents",
        json={
            "memory_code": "SERIES_CANON_V1",
            "memory_type": "series_canon",
            "series_code": SERIES,
            "title": "Series Canon",
            "content_json": {"world_rules": ["signal corruption erodes trust"]},
        },
    )

    bundle = client.get("/memory/bundles/agent/scriptwriting_agent?episode_code=EP01").json()
    assert bundle["agent_code"] == "scriptwriting_agent"
    assert bundle["series_memory"][0]["memory_code"] == "SERIES_CANON_V1"
    assert bundle["character_profiles"][0]["character_code"] == "MIRA"
    assert bundle["style_bible"]["frame_rate"] == 24.0


def test_bundle_records_provenance_of_every_document_it_used(client):
    make_episode(client)
    add_character(client)
    bundle = client.get("/memory/bundles/agent/continuity_agent?episode_code=EP01").json()
    assert {"character_code": "MIRA", "version": 1} in bundle["provenance"]


def test_bundle_by_series_alone_works_for_agents_above_an_episode(client):
    make_episode(client)
    add_character(client)
    bundle = client.get(
        f"/memory/bundles/agent/season_planner_agent?series_code={SERIES}"
    ).json()
    assert bundle["episode_code"] is None
    assert bundle["character_profiles"][0]["character_code"] == "MIRA"


def test_bundle_needs_a_scope(client):
    assert client.get("/memory/bundles/agent/x").status_code == 400


def test_activating_a_new_style_bible_retires_the_previous_one(client):
    # "The active style bible" must resolve to exactly one row, or two agents
    # silently work to different rules.
    make_episode(client)
    add_style_bible(client)
    add_style_bible(client, style_code="NEON_VEIL_STYLE_V2", title="v2")

    bundle = client.get("/memory/bundles/agent/edit_motion_agent?episode_code=EP01").json()
    assert bundle["style_bible"]["style_code"] == "NEON_VEIL_STYLE_V2"


def test_two_active_style_bibles_raise_rather_than_pick_one(client):
    make_episode(client)
    add_style_bible(client)
    add_style_bible(client, style_code="ROGUE", title="rogue", is_active=False)
    with fresh_session() as session:
        from app.db.models import StyleBible

        rogue = session.scalar(select(StyleBible).where(StyleBible.style_code == "ROGUE"))
        rogue.is_active = True
        session.commit()
        with pytest.raises(MultipleActiveStyleBiblesError):
            MemoryBundleService(session).active_style_bible(rogue.series_id)


# ---------------------------------------------------------------------------
# Scope validation
# ---------------------------------------------------------------------------
def test_memory_type_and_scope_must_agree():
    validate_scope("series_canon", "series")
    with pytest.raises(InvalidMemoryScopeError):
        validate_scope("series_canon", "episode")
    with pytest.raises(InvalidMemoryScopeError, match="Unknown memory_type"):
        validate_scope("made_up", "series")


def test_duplicate_memory_code_is_rejected(client):
    make_episode(client)
    payload = {
        "memory_code": "SERIES_CANON_V1",
        "memory_type": "series_canon",
        "series_code": SERIES,
        "title": "Series Canon",
    }
    assert client.post("/memory/documents", json=payload).status_code == 201
    assert client.post("/memory/documents", json=payload).status_code == 409


def test_duplicate_character_code_within_a_series_is_rejected(client):
    make_episode(client)
    add_character(client)
    assert client.post("/memory/characters", json=MIRA).status_code == 409


# ---------------------------------------------------------------------------
# Auto-writeback
# ---------------------------------------------------------------------------
def seed_episode_memory(client):
    response = client.post(
        "/memory/documents",
        json={
            "memory_code": "EP01_MEMORY",
            "memory_type": "episode_memory",
            "episode_code": "EP01",
            "title": "EP01 memory",
        },
    )
    assert response.status_code == 201, response.text


def test_writeback_stores_canon_facts_and_character_history(client):
    make_episode(client)
    add_character(client)
    seed_episode_memory(client)

    result = client.post(
        "/memory/writeback",
        json={
            "episode_code": "EP01",
            "memory_code": "EP01_MEMORY",
            "approved": {
                "canon_facts": [
                    {
                        "fact_type": "lore",
                        "entity_type": "signal_system",
                        "entity_key": "GHOST_SIGNAL",
                        "fact_key": "appears_on_public_terminals",
                        "fact_value": {"value": True},
                        "importance": "high",
                    }
                ],
                "character_state_changes": [
                    {"character_code": "MIRA", "current_status_patch": {"alert_level": "high"}}
                ],
                "unresolved_hooks": [
                    {"hook_code": "SUBWAY_TERMINAL_SECRET", "summary": "A terminal exposes Kade."}
                ],
            },
        },
    ).json()

    assert result["updated_characters"] == ["MIRA"]
    assert len(result["created_facts"]) == 3  # lore + character history + hook
    assert result["deferred"] == []

    with fresh_session() as session:
        profile = session.scalar(
            select(CharacterProfile).where(CharacterProfile.character_code == "MIRA")
        )
        assert profile.current_status == {"alert_level": "high"}
        assert profile.version == 2

        # The change is also a fact, so the prior state stays reconstructible.
        history = session.scalar(
            select(MemoryFact).where(MemoryFact.fact_type == "character_state")
        )
        assert history.fact_value["previous"] == {}
        assert history.fact_value["result"] == {"alert_level": "high"}


def test_writeback_supersedes_rather_than_deletes_a_replaced_fact(client):
    make_episode(client)
    seed_episode_memory(client)
    fact = {
        "fact_type": "lore",
        "entity_type": "signal_system",
        "entity_key": "GHOST_SIGNAL",
        "fact_key": "range_km",
        "fact_value": {"value": 5},
    }
    body = {"episode_code": "EP01", "memory_code": "EP01_MEMORY"}
    client.post("/memory/writeback", json={**body, "approved": {"canon_facts": [fact]}})
    second = client.post(
        "/memory/writeback",
        json={**body, "approved": {"canon_facts": [{**fact, "fact_value": {"value": 9}}]}},
    ).json()

    assert len(second["superseded_facts"]) == 1
    with fresh_session() as session:
        rows = session.scalars(
            select(MemoryFact).where(MemoryFact.fact_key == "range_km")
        ).all()
        assert len(rows) == 2, "the old fact is retained, not deleted"
        statuses = sorted(r.status for r in rows)
        assert statuses == ["active", "superseded"]


def test_writeback_defers_rather_than_guesses(client):
    make_episode(client)
    seed_episode_memory(client)
    result = client.post(
        "/memory/writeback",
        json={
            "episode_code": "EP01",
            "memory_code": "EP01_MEMORY",
            "approved": {
                "canon_facts": [{"fact_type": "lore", "entity_type": "x"}],
                "character_state_changes": [
                    {"character_code": "NOBODY", "current_status_patch": {"a": 1}}
                ],
                "unresolved_hooks": [{"summary": "no code"}],
            },
        },
    ).json()

    assert result["created_facts"] == []
    reasons = [d["reason"] for d in result["deferred"]]
    assert any("missing required keys" in r for r in reasons)
    assert any("no character profile" in r for r in reasons)
    assert any("missing hook_code" in r for r in reasons)


def test_writeback_to_an_unknown_document_is_404(client):
    make_episode(client)
    response = client.post(
        "/memory/writeback",
        json={"episode_code": "EP01", "memory_code": "NOPE", "approved": {}},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Continuity records and the publish gate
# ---------------------------------------------------------------------------
def test_consistency_check_endpoint_records_a_continuity_row(client):
    make_episode(client)
    add_character(client)
    body = client.post(
        "/memory/consistency-check",
        json={"episode_code": "EP01", "script": script(("Mira", "That was totally it."))},
    ).json()
    assert body["passed"] is False

    checks = client.get("/memory/continuity-checks/EP01").json()
    assert len(checks) == 1
    assert checks[0]["passed"] is False
    assert checks[0]["fixes_required"]


def test_consistency_check_can_run_without_recording(client):
    make_episode(client)
    add_character(client)
    client.post(
        "/memory/consistency-check",
        json={"episode_code": "EP01", "script": script(("Mira", "Fine.")), "record": False},
    )
    assert client.get("/memory/continuity-checks/EP01").json() == []


def test_publish_gate_requires_a_passing_continuity_check(client):
    from tests.conftest import qc_report

    make_episode(client)
    add_character(client)
    client.post("/qc-reports/", json=qc_report(score=9).model_dump(mode="json"))

    gate = client.get("/qc-reports/episode/EP01/publish-gate").json()
    assert gate["publish_ready"] is False
    assert gate["checks"]["qc_score_ok"] is True
    assert gate["checks"]["continuity_passed"] is False
    assert "no passing continuity check" in gate["reasons"]

    client.post(
        "/memory/consistency-check",
        json={"episode_code": "EP01", "script": script(("Mira", "Fine."))},
    )
    gate = client.get("/qc-reports/episode/EP01/publish-gate").json()
    assert gate["checks"]["continuity_passed"] is True
    assert gate["publish_ready"] is True
    assert gate["reasons"] == []


def test_publish_gate_reports_every_failing_check_not_just_the_first(client):
    from tests.conftest import qc_report

    make_episode(client)
    client.post(
        "/qc-reports/",
        json=qc_report(score=5, critical_issues=["music cue"]).model_dump(mode="json"),
    )
    gate = client.get("/qc-reports/episode/EP01/publish-gate").json()
    assert len(gate["reasons"]) >= 3
    assert gate["checks"] == {
        "qc_score_ok": False,
        "mandatory_fixes_closed": True,
        "no_critical_issues": False,
        "continuity_passed": False,
        # Clear by default: nothing has recorded a blocking finding yet.
        "enforcement_clear": True,
    }


# ---------------------------------------------------------------------------
# Schema generation -- /openapi.json shipped broken once; keep it covered.
# ---------------------------------------------------------------------------
def test_openapi_schema_generates(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/pipeline/diagram" in paths
    assert "/memory/bundles/agent/{agent_code}" in paths
