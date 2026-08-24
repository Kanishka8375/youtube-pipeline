"""Entity aliases, near-miss suggestions, timeline rebalancing and causality."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import EntityAlias, MemoryFact, Series
from app.services.canon_registry import (
    AliasConflictError,
    CausalGraphService,
    EntityRegistry,
    TimelineService,
)
from tests.test_canon_enforcement import MIRA_ENTITY, add_entity, add_event
from tests.test_memory import SERIES
from tests.test_workflow_persistence import fresh_session, make_episode


def series_row(session):
    return session.scalar(select(Series).where(Series.series_code == SERIES))


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------
def test_registering_an_entity_indexes_every_spelling_it_answers_to(client):
    make_episode(client)
    add_entity(client)
    with fresh_session() as session:
        rows = session.scalars(select(EntityAlias)).all()
        assert sorted(r.alias_normalised for r in rows) == [
            "kisaragi",
            "mira",
            "mirakisaragi",
        ]
        assert sorted(r.source for r in rows) == [
            "display_name",
            "entity_code",
            "manual",
        ]


def test_a_code_and_display_name_that_normalise_alike_index_once(client):
    # "KADE" and "Kade" are one key. The alias table's unique constraint would
    # reject the second, so the registry has to recognise it as the same name
    # rather than trying to insert it twice.
    make_episode(client)
    add_entity(client, entity_code="KADE", display_name="Kade", aliases=[])
    with fresh_session() as session:
        rows = session.scalars(select(EntityAlias)).all()
        assert [r.alias_normalised for r in rows] == ["kade"]


def test_an_alias_can_be_added_after_registration(client):
    make_episode(client)
    add_entity(client)
    response = client.post(
        "/canon/aliases",
        json={"series_code": SERIES, "entity_code": "MIRA", "alias": "The Kisaragi Girl"},
    )
    assert response.status_code == 201, response.text
    resolved = client.get(
        f"/canon/entities/{SERIES}/resolve?name=the kisaragi girl"
    ).json()
    assert resolved["resolved"]["entity_code"] == "MIRA"
    # The display list is kept in step with the lookup index.
    listed = client.get(f"/canon/entities/{SERIES}").json()
    assert "The Kisaragi Girl" in listed[0]["aliases"]


def test_an_alias_already_claimed_by_another_entity_is_refused(client):
    make_episode(client)
    add_entity(client)
    add_entity(client, entity_code="KADE", display_name="Kade", aliases=[])
    clash = client.post(
        "/canon/aliases",
        json={"series_code": SERIES, "entity_code": "KADE", "alias": "kisaragi"},
    )
    assert clash.status_code == 409
    assert "already claimed by 'MIRA'" in clash.json()["detail"]


def test_an_alias_that_normalises_to_nothing_is_rejected(client):
    make_episode(client)
    add_entity(client)
    response = client.post(
        "/canon/aliases",
        json={"series_code": SERIES, "entity_code": "MIRA", "alias": "!!!"},
    )
    assert response.status_code == 400
    assert "normalises to nothing" in response.json()["detail"]


def test_alias_for_an_unknown_entity_is_a_404(client):
    make_episode(client)
    response = client.post(
        "/canon/aliases",
        json={"series_code": SERIES, "entity_code": "GHOST", "alias": "Spectre"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Suggestions -- the fuzzy half, deliberately kept out of resolution
# ---------------------------------------------------------------------------
def test_a_typo_is_suggested_but_never_resolved(client):
    make_episode(client)
    add_entity(client)
    # Resolution stays exact: a wrong fuzzy match attaches a fact to the wrong
    # character, and nothing afterwards reveals it.
    assert client.get(f"/canon/entities/{SERIES}/resolve?name=Kisargi").json()[
        "resolved"
    ] is None
    suggestions = client.get(
        f"/canon/entities/{SERIES}/suggest?name=Kisargi"
    ).json()["suggestions"]
    assert [s["entity_code"] for s in suggestions] == ["MIRA"]
    assert suggestions[0]["score"] < 1.0


def test_an_unrelated_name_suggests_nothing(client):
    make_episode(client)
    add_entity(client)
    assert (
        client.get(f"/canon/entities/{SERIES}/suggest?name=Tanaka").json()["suggestions"]
        == []
    )


def test_each_entity_is_suggested_once_at_its_best_matching_alias(client):
    make_episode(client)
    add_entity(client)
    with fresh_session() as session:
        registry = EntityRegistry(session)
        series = series_row(session)
        # Two aliases both near the query; the entity must appear once.
        result = registry.suggest(series.id, "Mirah")
        assert [s.entity_code for s in result] == ["MIRA"]


# ---------------------------------------------------------------------------
# Timeline rebalancing
# ---------------------------------------------------------------------------
def test_rebalance_respaces_without_reordering(client):
    make_episode(client)
    for code, order in [("E_A", 1), ("E_B", 2), ("E_C", 3)]:
        assert add_event(client, code, order).status_code == 201

    response = client.post("/canon/timeline/rebalance", json={"series_code": SERIES})
    assert response.status_code == 200, response.text
    assert response.json()["events_rebalanced"] == 3

    timeline = client.get(f"/canon/timeline/{SERIES}").json()
    assert [(e["event_code"], e["order_index"]) for e in timeline] == [
        ("E_A", 10),
        ("E_B", 20),
        ("E_C", 30),
    ]


def test_rebalance_reopens_room_for_an_insertion(client):
    make_episode(client)
    add_event(client, "E_A", 1)
    add_event(client, "E_B", 2)
    # Nothing fits between 1 and 2.
    assert add_event(client, "E_MID", 2).status_code == 409
    client.post("/canon/timeline/rebalance", json={"series_code": SERIES})
    assert add_event(client, "E_MID", 15).status_code == 201
    timeline = client.get(f"/canon/timeline/{SERIES}").json()
    assert [e["event_code"] for e in timeline] == ["E_A", "E_MID", "E_B"]


def test_rebalance_resyncs_the_positions_stored_on_facts(client):
    # The stored position is what the matcher orders by. If a rebalance leaves
    # it stale, the matcher compares a new position against an old one and
    # silently stops detecting retcons.
    make_episode(client)
    add_event(client, "E_EP01", 1, episode_code="EP01")
    with fresh_session() as session:
        from app.db.models import Episode, MemoryDocument

        series = series_row(session)
        episode = session.scalar(select(Episode).where(Episode.episode_code == "EP01"))
        doc = MemoryDocument(
            memory_code="MEM_REBAL",
            memory_type="series_canon",
            scope_type="series",
            scope_id=series.id,
            title="canon",
        )
        session.add(doc)
        session.flush()
        session.add(
            MemoryFact(
                memory_document_id=doc.id,
                fact_type="canon",
                entity_type="character",
                entity_key="MIRA",
                fact_key="location",
                fact_value="safehouse",
                mutability="stateful",
                valid_from_episode_id=episode.id,
                timeline_start_order=1,
            )
        )
        session.commit()

    client.post("/canon/timeline/rebalance", json={"series_code": SERIES, "gap": 100})

    with fresh_session() as session:
        fact = session.scalar(select(MemoryFact).where(MemoryFact.fact_key == "location"))
        assert fact.timeline_start_order == 100


def test_rebalance_of_an_empty_timeline_is_a_no_op(client):
    make_episode(client)
    body = client.post("/canon/timeline/rebalance", json={"series_code": SERIES}).json()
    assert body == {
        "series_code": SERIES,
        "gap": 10,
        "events_rebalanced": 0,
        "facts_resynced": 0,
    }


def test_a_gap_below_one_is_rejected(client):
    make_episode(client)
    assert (
        client.post(
            "/canon/timeline/rebalance", json={"series_code": SERIES, "gap": 0}
        ).status_code
        == 422
    )


# ---------------------------------------------------------------------------
# Causality
# ---------------------------------------------------------------------------
def link(client, cause, effect, link_type="causes"):
    return client.post(
        "/canon/causal-links",
        json={
            "series_code": SERIES,
            "cause_event_code": cause,
            "effect_event_code": effect,
            "link_type": link_type,
        },
    )


def test_a_correctly_ordered_chain_reports_nothing(client):
    make_episode(client)
    add_event(client, "RITUAL", 1)
    add_event(client, "GATE_SEALED", 2)
    assert link(client, "RITUAL", "GATE_SEALED").status_code == 201
    body = client.get(f"/canon/causal-check/{SERIES}").json()
    assert body == {"series_code": SERIES, "passed": True, "violations": []}


def test_an_effect_ordered_before_its_cause_is_reported(client):
    make_episode(client)
    add_event(client, "GATE_SEALED", 1)
    add_event(client, "RITUAL", 2)
    link(client, "RITUAL", "GATE_SEALED")
    body = client.get(f"/canon/causal-check/{SERIES}").json()
    assert body["passed"] is False
    assert [v["kind"] for v in body["violations"]] == ["effect_before_cause"]
    assert body["violations"][0]["events"] == ["RITUAL", "GATE_SEALED"]


def test_a_prevents_link_is_not_checked_for_ordering(client):
    # `prevents` asserts the effect does *not* follow, so the ordering rule for
    # `causes` would report every one of them as impossible.
    make_episode(client)
    add_event(client, "WARDING", 1)
    add_event(client, "BREACH", 2)
    link(client, "BREACH", "WARDING", link_type="prevents")
    assert client.get(f"/canon/causal-check/{SERIES}").json()["passed"] is True


def test_a_causal_cycle_is_reported_once(client):
    make_episode(client)
    for code, order in [("A", 1), ("B", 2), ("C", 3)]:
        add_event(client, code, order)
    link(client, "A", "B")
    link(client, "B", "C")
    link(client, "C", "A")
    violations = client.get(f"/canon/causal-check/{SERIES}").json()["violations"]
    cycles = [v for v in violations if v["kind"] == "causal_cycle"]
    assert len(cycles) == 1
    assert sorted(cycles[0]["events"]) == ["A", "B", "C"]


def test_an_event_cannot_cause_itself(client):
    make_episode(client)
    add_event(client, "A", 1)
    assert link(client, "A", "A").status_code == 400


def test_an_unknown_link_type_is_rejected(client):
    make_episode(client)
    add_event(client, "A", 1)
    add_event(client, "B", 2)
    response = client.post(
        "/canon/causal-links",
        json={
            "series_code": SERIES,
            "cause_event_code": "A",
            "effect_event_code": "B",
            "link_type": "vibes",
        },
    )
    assert response.status_code == 400


def test_a_link_to_an_unknown_event_is_a_404(client):
    make_episode(client)
    add_event(client, "A", 1)
    assert link(client, "A", "NOPE").status_code == 404


def test_a_causal_impossibility_in_this_episode_holds_its_release(client):
    from tests.conftest import qc_report

    make_episode(client)
    client.post("/qc-reports/", json=qc_report().model_dump(mode="json"))
    add_event(client, "GATE_SEALED", 1, episode_code="EP01")
    add_event(client, "RITUAL", 2, episode_code="EP01")
    link(client, "RITUAL", "GATE_SEALED")

    gate = client.get("/qc-reports/episode/EP01/publish-gate").json()
    assert gate["checks"]["causality_clear"] is False
    assert gate["publish_ready"] is False
    assert any("causal impossibility" in r for r in gate["reasons"])


def test_a_causal_impossibility_elsewhere_does_not_hold_this_episode(client):
    # Series-wide checking, episode-scoped gating. Holding every release for a
    # problem in one episode makes the check something people route around.
    from tests.conftest import qc_report

    make_episode(client)
    make_episode(client, episode_code="EP02", episode_number=2)
    client.post("/qc-reports/", json=qc_report().model_dump(mode="json"))
    add_event(client, "GATE_SEALED", 1, episode_code="EP02")
    add_event(client, "RITUAL", 2, episode_code="EP02")
    link(client, "RITUAL", "GATE_SEALED")

    assert client.get(f"/canon/causal-check/{SERIES}").json()["passed"] is False
    gate = client.get("/qc-reports/episode/EP01/publish-gate").json()
    assert gate["checks"]["causality_clear"] is True
