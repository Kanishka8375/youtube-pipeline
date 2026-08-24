"""Canon registry, timeline, contradiction matching and continuity enforcement."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import ContradictionMatch, MemoryFact
from app.services.canon_registry import (
    AmbiguousEntityError,
    EntityRegistry,
    TimelineOrderConflictError,
    TimelineService,
)
from app.services.contradiction import ContradictionMatcher, InvalidMutabilityError
from app.services.enforcement import ApprovedOutputParser, required_components_for
from tests.conftest import qc_report
from tests.test_memory import MIRA, SERIES, add_character, add_style_bible
from tests.test_workflow_persistence import fresh_session, make_episode

MIRA_ENTITY = {
    "series_code": SERIES,
    "entity_code": "MIRA",
    "entity_type": "character",
    "display_name": "Mira Kisaragi",
    "aliases": ["Kisaragi"],
}


def add_entity(client, **overrides):
    response = client.post("/canon/entities", json={**MIRA_ENTITY, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def add_event(client, code, order, episode_code=None, **overrides):
    payload = {
        "series_code": SERIES,
        "event_code": code,
        "event_type": "plot",
        "order_index": order,
        "title": code,
        "summary": f"{code} summary",
    }
    if episode_code:
        payload["episode_code"] = episode_code
    response = client.post("/canon/timeline", json={**payload, **overrides})
    return response


def seed_memory_doc(client, code="EP01_MEMORY", episode_code="EP01"):
    response = client.post(
        "/memory/documents",
        json={
            "memory_code": code,
            "memory_type": "episode_memory",
            "episode_code": episode_code,
            "title": code,
        },
    )
    assert response.status_code == 201, response.text


def write_fact(client, *, fact_key, value, mutability, episode_code="EP01", memory_code="EP01_MEMORY"):
    response = client.post(
        "/memory/writeback",
        json={
            "episode_code": episode_code,
            "memory_code": memory_code,
            "approved": {
                "canon_facts": [
                    {
                        "fact_type": "lore",
                        "entity_type": "character",
                        "entity_key": "MIRA",
                        "fact_key": fact_key,
                        "fact_value": value,
                        "mutability": mutability,
                    }
                ]
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def check(client, facts, episode_code="EP01", persist=True):
    response = client.post(
        "/canon/contradiction-check",
        json={
            "series_code": SERIES,
            "episode_code": episode_code,
            "proposed_facts": facts,
            "persist": persist,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Entity registry and normalisation
# ---------------------------------------------------------------------------
def test_entity_resolves_across_spellings(client):
    make_episode(client)
    add_entity(client)
    for name in ["MIRA", "mira", "Mira Kisaragi", "Kisaragi"]:
        body = client.get(f"/canon/entities/{SERIES}/resolve?name={name}").json()
        assert body["resolved"]["entity_code"] == "MIRA", name


def test_unregistered_name_resolves_to_nothing(client):
    make_episode(client)
    add_entity(client)
    assert client.get(f"/canon/entities/{SERIES}/resolve?name=Kade").json()["resolved"] is None


def test_ambiguous_alias_raises_rather_than_picking_one(client):
    # Silently choosing would attach facts to the wrong entity, after which
    # they would never contradict anything.
    make_episode(client)
    add_entity(client)
    add_entity(client, entity_code="KADE", display_name="Kade", aliases=["Kisaragi"])
    assert client.get(f"/canon/entities/{SERIES}/resolve?name=Kisaragi").status_code == 409


def test_duplicate_entity_code_in_a_series_is_rejected(client):
    make_episode(client)
    add_entity(client)
    assert client.post("/canon/entities", json=MIRA_ENTITY).status_code == 409


def test_registry_normalises_keys_and_leaves_unknown_ones_alone(client):
    make_episode(client)
    add_entity(client)
    with fresh_session() as session:
        from app.db.models import Series

        series = session.scalar(select(Series).where(Series.series_code == SERIES))
        registry = EntityRegistry(session)
        assert registry.normalise_key(series.id, "Mira Kisaragi") == "MIRA"
        assert registry.normalise_key(series.id, "GHOST_SIGNAL") == "GHOST_SIGNAL"
        assert registry.unregistered_keys(series.id, ["Mira", "Kade"]) == ["Kade"]


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
def test_timeline_returns_events_in_order(client):
    make_episode(client)
    add_event(client, "EVT_002", 2)
    add_event(client, "EVT_001", 1)
    codes = [e["event_code"] for e in client.get(f"/canon/timeline/{SERIES}").json()]
    assert codes == ["EVT_001", "EVT_002"]


def test_duplicate_order_index_is_rejected(client):
    # Without this, "ordered" is not a well-defined word: two tied events
    # return in arbitrary order and the timeline differs between reads.
    make_episode(client)
    assert add_event(client, "EVT_001", 1).status_code == 201
    response = add_event(client, "EVT_002", 1)
    assert response.status_code == 409
    assert "already taken" in response.json()["detail"]


def test_duplicate_event_code_is_rejected(client):
    make_episode(client)
    add_event(client, "EVT_001", 1)
    assert add_event(client, "EVT_001", 2).status_code == 409


def test_episode_scoped_event_must_belong_to_the_series(client):
    make_episode(client)
    make_episode(client, series_code="OTHER", season_code="S01", episode_code="EP99")
    response = add_event(client, "EVT_X", 1, episode_code="EP99")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Contradiction matching -- the case a naive matcher gets wrong
# ---------------------------------------------------------------------------
def test_a_stateful_fact_changing_is_progression_not_a_contradiction(client):
    # Mira's trust in Kade going from intact to damaged IS the plot. A matcher
    # that flags this blocks on every normal story beat and gets switched off.
    make_episode(client)
    add_entity(client)
    seed_memory_doc(client)
    write_fact(client, fact_key="trust_in_kade", value={"v": "intact"}, mutability="stateful")

    body = check(
        client,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "trust_in_kade",
                "fact_value": {"v": "damaged"},
                "mutability": "stateful",
            }
        ],
    )
    assert body["passed"] is True
    assert body["contradictions_found"] == 0
    assert body["progressions"][0]["from"] == {"v": "intact"}
    assert body["progressions"][0]["to"] == {"v": "damaged"}


def test_an_immutable_fact_changing_is_a_blocking_contradiction(client):
    make_episode(client)
    add_entity(client)
    seed_memory_doc(client)
    write_fact(client, fact_key="birth_name", value={"v": "Mira"}, mutability="immutable")

    body = check(
        client,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "birth_name",
                "fact_value": {"v": "Mirai"},
                "mutability": "immutable",
            }
        ],
    )
    assert body["passed"] is False
    assert body["contradictions"][0]["contradiction_type"] == "immutable_fact_changed"
    assert body["contradictions"][0]["blocking"] is True


def test_an_existing_immutable_fact_governs_even_if_the_draft_claims_stateful(client):
    # Otherwise any agent could relabel canon as mutable to get past the gate.
    make_episode(client)
    add_entity(client)
    seed_memory_doc(client)
    write_fact(client, fact_key="species", value={"v": "human"}, mutability="immutable")

    body = check(
        client,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "species",
                "fact_value": {"v": "synthetic"},
                "mutability": "stateful",
            }
        ],
    )
    assert body["passed"] is False
    assert body["contradictions"][0]["contradiction_type"] == "immutable_fact_changed"


def test_facts_match_across_spellings_once_the_entity_is_registered(client):
    # The registry's whole purpose: "Mira" and "MIRA" must meet, or canon forks.
    make_episode(client)
    add_entity(client)
    seed_memory_doc(client)
    write_fact(client, fact_key="birth_name", value={"v": "Mira"}, mutability="immutable")

    body = check(
        client,
        [
            {
                "entity_type": "character",
                "entity_key": "Mira Kisaragi",
                "fact_key": "birth_name",
                "fact_value": {"v": "Mirai"},
                "mutability": "immutable",
            }
        ],
    )
    assert body["contradictions_found"] == 1
    assert body["contradictions"][0]["entity_code"] == "MIRA"


def test_unregistered_entities_are_reported(client):
    make_episode(client)
    seed_memory_doc(client)
    body = check(
        client,
        [
            {
                "entity_type": "character",
                "entity_key": "Kade",
                "fact_key": "alive",
                "fact_value": {"v": True},
            }
        ],
    )
    assert body["unregistered_entities"] == ["Kade"]


def test_identical_values_are_not_contradictions(client):
    make_episode(client)
    add_entity(client)
    seed_memory_doc(client)
    write_fact(client, fact_key="birth_name", value={"v": "Mira"}, mutability="immutable")
    body = check(
        client,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "birth_name",
                "fact_value": {"v": "Mira"},
                "mutability": "immutable",
            }
        ],
    )
    assert body["passed"] is True
    assert body["progressions"] == []


def test_incomplete_facts_are_skipped_with_a_reason(client):
    make_episode(client)
    body = check(client, [{"entity_type": "character", "fact_key": "alive"}])
    assert body["skipped"][0]["reason"].startswith("missing required keys")


def test_unknown_mutability_is_rejected(client):
    make_episode(client)
    response = client.post(
        "/canon/contradiction-check",
        json={
            "series_code": SERIES,
            "proposed_facts": [
                {
                    "entity_type": "character",
                    "entity_key": "MIRA",
                    "fact_key": "x",
                    "fact_value": {"v": 1},
                    "mutability": "sometimes",
                }
            ],
        },
    )
    assert response.status_code == 400


def test_contradictions_are_persisted_for_the_episode(client):
    make_episode(client)
    add_entity(client)
    seed_memory_doc(client)
    write_fact(client, fact_key="birth_name", value={"v": "Mira"}, mutability="immutable")
    check(
        client,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "birth_name",
                "fact_value": {"v": "Mirai"},
                "mutability": "immutable",
            }
        ],
    )
    stored = client.get("/canon/contradictions/EP01").json()
    assert len(stored) == 1
    assert stored[0]["blocking"] is True


def test_persist_false_leaves_no_record(client):
    make_episode(client)
    add_entity(client)
    seed_memory_doc(client)
    write_fact(client, fact_key="birth_name", value={"v": "Mira"}, mutability="immutable")
    check(
        client,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "birth_name",
                "fact_value": {"v": "Mirai"},
                "mutability": "immutable",
            }
        ],
        persist=False,
    )
    assert client.get("/canon/contradictions/EP01").json() == []


def test_facts_default_to_immutable(client):
    # The conservative default: an unclassified fact is flagged when it
    # changes rather than passed silently.
    make_episode(client)
    add_entity(client)
    seed_memory_doc(client)
    client.post(
        "/memory/writeback",
        json={
            "episode_code": "EP01",
            "memory_code": "EP01_MEMORY",
            "approved": {
                "canon_facts": [
                    {
                        "fact_type": "lore",
                        "entity_type": "character",
                        "entity_key": "MIRA",
                        "fact_key": "origin",
                        "fact_value": {"v": "district 7"},
                    }
                ]
            },
        },
    )
    with fresh_session() as session:
        fact = session.scalar(select(MemoryFact).where(MemoryFact.fact_key == "origin"))
        assert fact.mutability == "immutable"


# ---------------------------------------------------------------------------
# Retcon detection -- needs the timeline
# ---------------------------------------------------------------------------
def test_a_stateful_change_from_an_earlier_episode_is_a_retcon(client):
    # EP02 establishes a state; EP01 (earlier on the timeline) then changes it.
    # That is writing new past over settled future.
    make_episode(client)
    make_episode(client, episode_code="EP02", episode_number=2)
    add_entity(client)
    add_event(client, "EVT_EP01", 1, episode_code="EP01")
    add_event(client, "EVT_EP02", 2, episode_code="EP02")
    seed_memory_doc(client, code="EP02_MEMORY", episode_code="EP02")

    write_fact(
        client,
        fact_key="location",
        value={"v": "safehouse"},
        mutability="stateful",
        episode_code="EP02",
        memory_code="EP02_MEMORY",
    )

    body = check(
        client,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "location",
                "fact_value": {"v": "transit station"},
                "mutability": "stateful",
            }
        ],
        episode_code="EP01",
    )
    assert body["passed"] is False
    assert body["contradictions"][0]["contradiction_type"] == "retcon"


def test_a_stateful_change_from_a_later_episode_is_progression(client):
    make_episode(client)
    make_episode(client, episode_code="EP02", episode_number=2)
    add_entity(client)
    add_event(client, "EVT_EP01", 1, episode_code="EP01")
    add_event(client, "EVT_EP02", 2, episode_code="EP02")
    seed_memory_doc(client)

    write_fact(client, fact_key="location", value={"v": "transit station"}, mutability="stateful")

    body = check(
        client,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "location",
                "fact_value": {"v": "safehouse"},
                "mutability": "stateful",
            }
        ],
        episode_code="EP02",
    )
    assert body["passed"] is True
    assert len(body["progressions"]) == 1


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
def test_preflight_blocks_when_required_canon_is_missing(client):
    make_episode(client)
    body = client.post(
        "/canon/preflight",
        json={"agent_code": "scriptwriting_agent", "episode_code": "EP01"},
    ).json()

    assert body["passed"] is False
    missing = {i["entity_key"] for i in body["issues"]}
    assert missing == {"character_profiles", "style_bible"}
    assert all(i["blocking"] for i in body["issues"])


def test_preflight_passes_once_canon_exists(client):
    make_episode(client)
    add_character(client)
    add_style_bible(client)
    body = client.post(
        "/canon/preflight",
        json={"agent_code": "scriptwriting_agent", "episode_code": "EP01"},
    ).json()
    assert body["passed"] is True
    assert body["issues"] == []


def test_preflight_records_which_canon_versions_it_read(client):
    make_episode(client)
    add_character(client)
    add_style_bible(client)
    body = client.post(
        "/canon/preflight",
        json={"agent_code": "scriptwriting_agent", "episode_code": "EP01"},
    ).json()
    assert {"character_code": "MIRA", "version": 1} in body["memory_provenance"]


def test_preflight_requirements_can_be_overridden(client):
    make_episode(client)
    body = client.post(
        "/canon/preflight",
        json={
            "agent_code": "scriptwriting_agent",
            "episode_code": "EP01",
            "required_components": [],
        },
    ).json()
    assert body["passed"] is True


def test_unknown_required_component_is_rejected(client):
    make_episode(client)
    response = client.post(
        "/canon/preflight",
        json={
            "agent_code": "scriptwriting_agent",
            "episode_code": "EP01",
            "required_components": ["vibes"],
        },
    )
    assert response.status_code == 400


def test_every_declared_requirement_has_a_check():
    from app.services.enforcement import COMPONENT_CHECKS, REQUIRED_COMPONENTS

    for agent, components in REQUIRED_COMPONENTS.items():
        for component in components:
            assert component in COMPONENT_CHECKS, f"{agent} requires uncheckable {component}"


def test_every_pipeline_agent_has_declared_requirements():
    from app.agents.registry import AGENTS
    from app.services.enforcement import REQUIRED_COMPONENTS

    # series_bible_agent writes canon rather than consuming it, so it is the
    # one agent with no prerequisites.
    expected = {s.agent_code for s in AGENTS} - {"series_bible_agent"}
    assert expected == set(REQUIRED_COMPONENTS)


# ---------------------------------------------------------------------------
# Draft validation
# ---------------------------------------------------------------------------
def test_draft_validation_combines_guard_and_contradiction_findings(client):
    make_episode(client)
    add_character(client)
    add_style_bible(client)
    add_entity(client)
    seed_memory_doc(client)
    write_fact(client, fact_key="birth_name", value={"v": "Mira"}, mutability="immutable")

    body = client.post(
        "/canon/validate-draft",
        json={
            "agent_code": "scriptwriting_agent",
            "episode_code": "EP01",
            "payload": {
                "scenes": [
                    {
                        "scene_id": "EP01_SC01",
                        "dialogue": [{"speaker": "Mira", "line": "That was totally it."}],
                    }
                ],
                "proposed_facts": [
                    {
                        "entity_type": "character",
                        "entity_key": "MIRA",
                        "fact_key": "birth_name",
                        "fact_value": {"v": "Mirai"},
                        "mutability": "immutable",
                    }
                ],
            },
        },
    ).json()

    assert body["passed"] is False
    kinds = {i["issue_type"] for i in body["issues"]}
    assert "forbidden_phrase" in kinds
    assert "immutable_fact_changed" in kinds


def test_draft_validation_carries_what_it_could_not_check(client):
    make_episode(client)
    add_character(client)
    add_style_bible(client)
    body = client.post(
        "/canon/validate-draft",
        json={
            "agent_code": "scriptwriting_agent",
            "episode_code": "EP01",
            "payload": {
                "scenes": [
                    {
                        "scene_id": "EP01_SC01",
                        "dialogue": [{"speaker": "Terminal Voice", "line": "Mira..."}],
                    }
                ]
            },
        },
    ).json()

    assert body["passed"] is True
    assert body["unknown_speakers"] == ["Terminal Voice"]
    assert body["not_mechanically_checked"], "a pass must not read as full clearance"


def test_enforcement_runs_are_listed_for_the_episode(client):
    make_episode(client)
    add_character(client)
    add_style_bible(client)
    client.post(
        "/canon/preflight",
        json={"agent_code": "scriptwriting_agent", "episode_code": "EP01"},
    )
    runs = client.get("/canon/enforcement-runs/EP01").json()
    assert [r["run_type"] for r in runs] == ["preflight"]


# ---------------------------------------------------------------------------
# Approved-output parser
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("output_type", ApprovedOutputParser.SUPPORTED)
def test_every_supported_output_type_parses(output_type):
    assert ApprovedOutputParser().parse(output_type, {}).unsupported == []


def test_unsupported_output_type_is_reported_not_silently_empty(client):
    make_episode(client)
    seed_memory_doc(client)
    response = client.post(
        "/canon/writeback",
        json={
            "episode_code": "EP01",
            "memory_code": "EP01_MEMORY",
            "output_type": "interpretive_dance",
            "payload": {},
        },
    )
    assert response.status_code == 400


def test_qc_report_yields_style_candidates_not_canon_facts():
    # A repeated edit complaint is evidence a rule may be missing. It is not a
    # fact about the world, and must not become one automatically.
    parsed = ApprovedOutputParser().parse(
        "qc_report",
        {"recurring_issues": [{"domain": "editing", "rule_candidate": "vary cut rhythm"}]},
    )
    assert parsed.canon_facts == []
    assert parsed.style_candidates[0]["domain"] == "editing"


def test_final_cut_metadata_yields_motifs_and_facts():
    parsed = ApprovedOutputParser().parse(
        "final_cut_metadata",
        {
            "music_motifs_introduced": ["mira_theme_low_strings"],
            "visual_motifs_introduced": ["blue screen glow"],
            "canon_facts": [{"entity_key": "X"}],
        },
    )
    assert len(parsed.style_candidates) == 2
    assert len(parsed.canon_facts) == 1


def test_style_candidates_are_never_applied_automatically(client):
    make_episode(client)
    add_style_bible(client)
    seed_memory_doc(client)
    body = client.post(
        "/canon/writeback",
        json={
            "episode_code": "EP01",
            "memory_code": "EP01_MEMORY",
            "output_type": "final_cut_metadata",
            "payload": {"music_motifs_introduced": ["mira_theme"]},
        },
    ).json()

    assert body["style_candidates_awaiting_approval"] == [
        {"domain": "music", "rule_candidate": "mira_theme"}
    ]
    # The style bible is untouched: style is a showrunner decision.
    bundle = client.get("/memory/bundles/agent/edit_motion_agent?episode_code=EP01").json()
    assert bundle["style_bible"]["version"] == 1


# ---------------------------------------------------------------------------
# Publish gate
# ---------------------------------------------------------------------------
def test_unresolved_contradiction_blocks_publication(client):
    from tests.test_api import pass_continuity

    make_episode(client)
    add_entity(client)
    seed_memory_doc(client)
    pass_continuity(client)
    client.post("/qc-reports/", json=qc_report(score=9).model_dump(mode="json"))

    gate = client.get("/qc-reports/episode/EP01/publish-gate").json()
    assert gate["publish_ready"] is True, "baseline should be clear"

    write_fact(client, fact_key="birth_name", value={"v": "Mira"}, mutability="immutable")
    check(
        client,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "birth_name",
                "fact_value": {"v": "Mirai"},
                "mutability": "immutable",
            }
        ],
    )

    gate = client.get("/qc-reports/episode/EP01/publish-gate").json()
    assert gate["publish_ready"] is False
    assert gate["checks"]["enforcement_clear"] is False
    assert any("contradiction" in r for r in gate["reasons"])


def test_blocking_enforcement_issue_blocks_publication(client):
    from tests.test_api import pass_continuity

    make_episode(client)
    pass_continuity(client)
    client.post("/qc-reports/", json=qc_report(score=9).model_dump(mode="json"))
    # Preflight fails -> blocking issues recorded against the episode.
    client.post(
        "/canon/preflight",
        json={"agent_code": "scriptwriting_agent", "episode_code": "EP01"},
    )

    gate = client.get("/qc-reports/episode/EP01/publish-gate").json()
    assert gate["publish_ready"] is False
    assert gate["checks"]["enforcement_clear"] is False
    assert any("continuity issue" in r for r in gate["reasons"])
