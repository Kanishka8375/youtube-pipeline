"""The retcon approval workflow, and the severity scoring that ranks the queue."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import (
    ContradictionMatch,
    Episode,
    MemoryDocument,
    MemoryFact,
    RetconProposal,
    Series,
)
from app.services.contradiction import ContradictionMatcher, score_severity, severity_band
from app.services.retcon import RetconService, RetconStateError
from tests.test_canon_enforcement import add_entity, add_event
from tests.test_memory import SERIES
from tests.test_workflow_persistence import fresh_session, make_episode

def two_episodes(client):
    make_episode(client)
    make_episode(client, episode_code="EP02", episode_number=2)
    add_event(client, "E_EP01", 1, episode_code="EP01")
    add_event(client, "E_EP02", 2, episode_code="EP02")


def seed_fact(session, *, fact_key="location", value="safehouse", episode_code="EP02",
              mutability="stateful", importance="normal"):
    series = session.scalar(select(Series).where(Series.series_code == SERIES))
    episode = session.scalar(select(Episode).where(Episode.episode_code == episode_code))
    doc = session.scalar(
        select(MemoryDocument).where(MemoryDocument.memory_code == "MEM_RETCON")
    )
    if doc is None:
        doc = MemoryDocument(
            memory_code="MEM_RETCON",
            memory_type="series_canon",
            scope_type="series",
            scope_id=series.id,
            title="canon",
        )
        session.add(doc)
        session.flush()
    fact = MemoryFact(
        memory_document_id=doc.id,
        fact_type="canon",
        entity_type="character",
        entity_key="MIRA",
        fact_key=fact_key,
        fact_value=value,
        mutability=mutability,
        importance=importance,
        valid_from_episode_id=episode.id,
        timeline_start_order=2 if episode_code == "EP02" else 1,
    )
    session.add(fact)
    session.commit()
    return fact


def propose(client, **overrides):
    payload = {
        "series_code": SERIES,
        "entity_key": "MIRA",
        "fact_key": "location",
        "proposed_value": "alley",
        "rationale": "EP01 flashback relocates the scene.",
        "episode_code": "EP01",
    }
    return client.post("/canon/retcons", json={**payload, **overrides})


# ---------------------------------------------------------------------------
# The workflow
# ---------------------------------------------------------------------------
def test_filing_a_proposal_does_not_unblock_anything(client):
    two_episodes(client)
    with fresh_session() as session:
        seed_fact(session)

    body = propose(client).json()
    assert body["status"] == "pending"

    # Still blocked: filing is a request, not a decision.
    check = client.post(
        "/canon/contradiction-check",
        json={
            "series_code": SERIES,
            "episode_code": "EP01",
            "proposed_facts": [
                {
                    "entity_type": "character",
                    "entity_key": "MIRA",
                    "fact_key": "location",
                    "fact_value": "alley",
                    "mutability": "stateful",
                }
            ],
        },
    ).json()
    assert check["passed"] is False
    assert check["contradictions"][0]["contradiction_type"] == "retcon"


def test_approval_records_who_decided_and_rewrites_canon(client):
    two_episodes(client)
    with fresh_session() as session:
        original = seed_fact(session)
        original_id = original.id

    group = propose(client).json()["retcon_group_code"]
    outcome = client.post(
        f"/canon/retcons/{group}/approve",
        json={"decided_by": "showrunner", "decision_note": "Agreed in the EP01 pass."},
    )
    assert outcome.status_code == 200, outcome.text
    body = outcome.json()
    assert body["status"] == "approved"
    assert body["decided_by"] == "showrunner"

    with fresh_session() as session:
        old = session.get(MemoryFact, original_id)
        assert old.status == "superseded"
        assert old.fact_value == "safehouse"  # kept, not erased
        new = session.scalar(
            select(MemoryFact).where(MemoryFact.supersedes_fact_id == original_id)
        )
        assert new.fact_value == "alley"
        assert new.is_retcon is True
        assert new.retcon_group_code == group
        # An approved retcon outranks ordinary agent writeback, so the next
        # draft cannot win the same argument back on source priority.
        assert new.source_priority > old.source_priority


def test_an_approval_covers_the_change_however_it_is_spelled(client):
    two_episodes(client)
    with fresh_session() as session:
        seed_fact(session)
    group = propose(client, proposed_value="the Alley").json()["retcon_group_code"]
    client.post(f"/canon/retcons/{group}/approve", json={"decided_by": "showrunner"})

    with fresh_session() as session:
        series = session.scalar(select(Series).where(Series.series_code == SERIES))
        service = RetconService(session)
        # Same change, different spelling: an approval that needed re-granting
        # for every capitalisation would not be usable.
        assert service.approved_change(series.id, "MIRA", "location", "  THE ALLEY ")
        assert service.approved_change(series.id, "MIRA", "location", "rooftop") is None


def test_a_proposal_filed_under_an_alias_covers_the_canonical_code(client):
    two_episodes(client)
    add_entity(client)
    with fresh_session() as session:
        seed_fact(session)
    body = propose(client, entity_key="Kisaragi").json()
    assert body["entity_code"] == "MIRA"


def test_rejection_leaves_canon_untouched(client):
    two_episodes(client)
    with fresh_session() as session:
        fact = seed_fact(session)
        fact_id = fact.id
    group = propose(client).json()["retcon_group_code"]
    body = client.post(
        f"/canon/retcons/{group}/reject", json={"decided_by": "showrunner"}
    ).json()
    assert body["status"] == "rejected"
    assert body["new_fact_id"] is None
    with fresh_session() as session:
        assert session.get(MemoryFact, fact_id).status == "active"


def test_a_decided_proposal_cannot_be_decided_again(client):
    two_episodes(client)
    with fresh_session() as session:
        seed_fact(session)
    group = propose(client).json()["retcon_group_code"]
    client.post(f"/canon/retcons/{group}/approve", json={"decided_by": "showrunner"})
    again = client.post(
        f"/canon/retcons/{group}/reject", json={"decided_by": "someone else"}
    )
    assert again.status_code == 409
    assert "already approved" in again.json()["detail"]


def test_a_decision_must_name_who_made_it(client):
    two_episodes(client)
    with fresh_session() as session:
        seed_fact(session)
    group = propose(client).json()["retcon_group_code"]
    # An unattributed approval is the thing this workflow exists to prevent.
    assert (
        client.post(f"/canon/retcons/{group}/approve", json={"decided_by": ""}).status_code
        == 422
    )


def test_approving_resolves_the_contradiction_it_was_filed_against(client):
    two_episodes(client)
    with fresh_session() as session:
        seed_fact(session)
    # Persist a contradiction first, the way an enforcement run would.
    client.post(
        "/canon/contradiction-check",
        json={
            "series_code": SERIES,
            "episode_code": "EP01",
            "proposed_facts": [
                {
                    "entity_type": "character",
                    "entity_key": "MIRA",
                    "fact_key": "location",
                    "fact_value": "alley",
                    "mutability": "stateful",
                }
            ],
        },
    )
    group = propose(client).json()["retcon_group_code"]
    body = client.post(
        f"/canon/retcons/{group}/approve", json={"decided_by": "showrunner"}
    ).json()
    assert body["contradictions_cleared"] == 1

    with fresh_session() as session:
        match = session.scalar(select(ContradictionMatch))
        assert match.resolved is True
        assert match.blocking is False
        assert "showrunner" in match.resolution_note


def test_unknown_proposal_is_a_404(client):
    two_episodes(client)
    assert (
        client.post("/canon/retcons/rtc_nope/approve", json={"decided_by": "x"}).status_code
        == 404
    )


def test_proposals_can_be_listed_and_filtered(client):
    two_episodes(client)
    with fresh_session() as session:
        seed_fact(session)
    first = propose(client).json()["retcon_group_code"]
    propose(client, fact_key="allegiance", proposed_value="crown")
    client.post(f"/canon/retcons/{first}/approve", json={"decided_by": "showrunner"})

    assert len(client.get(f"/canon/retcons/{SERIES}").json()) == 2
    pending = client.get(f"/canon/retcons/{SERIES}?retcon_status=pending").json()
    assert [p["fact_key"] for p in pending] == ["allegiance"]
    assert client.get(f"/canon/retcons/{SERIES}?retcon_status=maybe").status_code == 400


# ---------------------------------------------------------------------------
# Severity scoring
# ---------------------------------------------------------------------------
class _Fact:
    """A stand-in carrying only what the scorer reads."""

    def __init__(self, **kwargs):
        self.importance = kwargs.get("importance", "normal")
        self.confidence_score = kwargs.get("confidence_score", 1.0)
        self.source_priority = kwargs.get("source_priority", 100)
        self.timeline_start_order = kwargs.get("timeline_start_order")


def test_rewriting_immutable_canon_outranks_a_retcon():
    immutable = score_severity(
        kind="immutable_fact_changed",
        existing=_Fact(),
        proposed={},
        proposing_position=None,
    )
    retcon = score_severity(
        kind="retcon", existing=_Fact(), proposed={}, proposing_position=None
    )
    assert immutable > retcon


def test_a_contradiction_on_critical_canon_outranks_one_on_a_detail():
    critical = score_severity(
        kind="retcon",
        existing=_Fact(importance="critical"),
        proposed={},
        proposing_position=None,
    )
    minor = score_severity(
        kind="retcon", existing=_Fact(importance="low"), proposed={}, proposing_position=None
    )
    assert critical > minor


def test_a_hedged_claim_softens_the_score():
    confident = score_severity(
        kind="retcon", existing=_Fact(), proposed={"confidence_score": 1.0},
        proposing_position=None,
    )
    tentative = score_severity(
        kind="retcon", existing=_Fact(), proposed={"confidence_score": 0.3},
        proposing_position=None,
    )
    assert tentative < confident


def test_a_retcon_reaching_further_back_scores_higher():
    near = score_severity(
        kind="retcon",
        existing=_Fact(timeline_start_order=3),
        proposed={},
        proposing_position=2,
    )
    far = score_severity(
        kind="retcon",
        existing=_Fact(timeline_start_order=30),
        proposed={},
        proposing_position=2,
    )
    assert far > near


@pytest.mark.parametrize(
    "score,band",
    [(95, "critical"), (80, "critical"), (60, "high"), (40, "medium"), (10, "low")],
)
def test_bands_partition_the_scale(score, band):
    assert severity_band(score) == band


def test_the_score_is_persisted_with_the_contradiction(client):
    two_episodes(client)
    with fresh_session() as session:
        seed_fact(session, fact_key="species", value="human", mutability="immutable",
                  importance="critical", episode_code="EP01")
    body = client.post(
        "/canon/contradiction-check",
        json={
            "series_code": SERIES,
            "episode_code": "EP02",
            "proposed_facts": [
                {
                    "entity_type": "character",
                    "entity_key": "MIRA",
                    "fact_key": "species",
                    "fact_value": "oni",
                    "mutability": "immutable",
                }
            ],
        },
    ).json()
    finding = body["contradictions"][0]
    assert finding["severity_score"] > 0
    assert finding["severity"] == severity_band(finding["severity_score"])
    with fresh_session() as session:
        match = session.scalar(select(ContradictionMatch))
        assert match.severity_score == finding["severity_score"]
