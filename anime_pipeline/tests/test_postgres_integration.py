"""Properties that only a real Postgres can check.

Everything here is covered logically by the SQLite suite. What it cannot cover
is whether Postgres agrees: whether the migration chain builds the schema the
models expect, whether the constraints are actually enforced, whether JSONB
round-trips, and whether row locking does what the workflow repository assumes.

These skip cleanly when no Postgres is available -- see `postgres_url` in
conftest for how to give them one.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from app.db.models import (
    CanonicalEntity,
    Episode,
    EntityAlias,
    MemoryDocument,
    MemoryFact,
    Season,
    Series,
    TimelineEvent,
)
from app.services.canon_registry import (
    AliasConflictError,
    EntityRegistry,
    TimelineService,
)
from app.services.contradiction import ContradictionMatcher
from app.services.normalisation import normalise_fact_value
from app.services.retcon import RetconService

pytestmark = pytest.mark.postgres


def seed_series(session, code="PG_SERIES"):
    series = Series(series_code=code, title="Postgres fixture")
    session.add(series)
    session.flush()
    season = Season(series_id=series.id, season_code=f"{code}_S1", season_number=1)
    session.add(season)
    session.flush()
    return series, season


def seed_episode(session, series, season, code, number):
    episode = Episode(
        series_id=series.id,
        season_id=season.id,
        episode_code=code,
        episode_number=number,
    )
    session.add(episode)
    session.flush()
    return episode


def seed_document(session, series):
    doc = MemoryDocument(
        memory_code=f"pg_{uuid.uuid4().hex[:8]}",
        memory_type="series_canon",
        scope_type="series",
        scope_id=series.id,
        title="canon",
    )
    session.add(doc)
    session.flush()
    return doc


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
def test_the_migration_chain_builds_the_schema_the_models_expect(postgres_engine):
    from app.db.models import Base

    inspector = sa.inspect(postgres_engine)
    built = set(inspector.get_table_names())
    expected = set(Base.metadata.tables) | {"alembic_version"}
    assert expected - built == set()


def test_json_columns_are_jsonb_on_postgres(postgres_engine):
    inspector = sa.inspect(postgres_engine)
    types = {c["name"]: str(c["type"]) for c in inspector.get_columns("memory_facts")}
    assert types["fact_value"] == "JSONB"


def test_uuid_columns_are_native(postgres_engine):
    inspector = sa.inspect(postgres_engine)
    types = {c["name"]: str(c["type"]) for c in inspector.get_columns("memory_facts")}
    assert types["id"] == "UUID"


# ---------------------------------------------------------------------------
# Constraints Postgres actually enforces
# ---------------------------------------------------------------------------
def test_one_spelling_cannot_mean_two_entities(postgres_session):
    series, _ = seed_series(postgres_session)
    registry = EntityRegistry(postgres_session)
    registry.create(
        series.id,
        {
            "entity_code": "MIRA",
            "entity_type": "character",
            "display_name": "Mira Kisaragi",
            "aliases": ["Kisaragi"],
        },
    )
    with pytest.raises(AliasConflictError):
        registry.create(
            series.id,
            {
                "entity_code": "KADE",
                "entity_type": "character",
                "display_name": "Kade",
                "aliases": ["kisaragi"],
            },
        )


def test_the_alias_uniqueness_is_enforced_by_the_database_not_only_the_service(
    postgres_session,
):
    # The service refuses first, which is the good path. This checks the floor
    # underneath it: a writer that bypasses the service still cannot create the
    # ambiguity.
    series, _ = seed_series(postgres_session)
    registry = EntityRegistry(postgres_session)
    entity = registry.create(
        series.id,
        {
            "entity_code": "MIRA",
            "entity_type": "character",
            "display_name": "Mira",
            "aliases": [],
        },
    )
    other = registry.create(
        series.id,
        {
            "entity_code": "KADE",
            "entity_type": "character",
            "display_name": "Kade",
            "aliases": [],
        },
    )
    postgres_session.add(
        EntityAlias(
            series_id=series.id,
            entity_id=other.id,
            alias="Mira",
            alias_normalised="mira",
            source="manual",
        )
    )
    with pytest.raises(sa.exc.IntegrityError):
        postgres_session.flush()
    postgres_session.rollback()
    assert entity.entity_code == "MIRA"


def test_two_series_can_each_have_their_own_mira(postgres_session):
    first, _ = seed_series(postgres_session, "PG_ONE")
    second, _ = seed_series(postgres_session, "PG_TWO")
    registry = EntityRegistry(postgres_session)
    payload = {
        "entity_code": "MIRA",
        "entity_type": "character",
        "display_name": "Mira",
        "aliases": [],
    }
    registry.create(first.id, dict(payload))
    registry.create(second.id, dict(payload))
    postgres_session.flush()
    assert registry.resolve(first.id, "Mira").series_id == first.id
    assert registry.resolve(second.id, "Mira").series_id == second.id


def test_timeline_order_is_unique_per_series(postgres_session):
    series, season = seed_series(postgres_session)
    postgres_session.add_all(
        [
            TimelineEvent(
                event_code="A",
                event_type="plot",
                series_id=series.id,
                order_index=1,
                title="A",
                summary="A",
            ),
            TimelineEvent(
                event_code="B",
                event_type="plot",
                series_id=series.id,
                order_index=1,
                title="B",
                summary="B",
            ),
        ]
    )
    with pytest.raises(sa.exc.IntegrityError):
        postgres_session.flush()
    postgres_session.rollback()


# ---------------------------------------------------------------------------
# Behaviour under a real dialect
# ---------------------------------------------------------------------------
def test_rebalancing_does_not_collide_with_the_unique_constraint(postgres_session):
    # Writing the new indexes directly would collide with rows still holding
    # them. SQLite is forgiving about constraint timing; Postgres is not, which
    # is exactly why this belongs here.
    series, season = seed_series(postgres_session)
    timeline = TimelineService(postgres_session)
    for index, code in enumerate(["A", "B", "C", "D"], start=1):
        timeline.create_event(
            {
                "event_code": code,
                "event_type": "plot",
                "series_id": series.id,
                "order_index": index,
                "title": code,
                "summary": code,
            }
        )
    result = timeline.rebalance(series.id, gap=10)
    assert result["events_rebalanced"] == 4
    assert [(e.event_code, e.order_index) for e in timeline.for_series(series.id)] == [
        ("A", 10),
        ("B", 20),
        ("C", 30),
        ("D", 40),
    ]


def test_a_retcon_round_trips_through_jsonb(postgres_session):
    series, season = seed_series(postgres_session)
    ep1 = seed_episode(postgres_session, series, season, "PG_EP01", 1)
    ep2 = seed_episode(postgres_session, series, season, "PG_EP02", 2)
    timeline = TimelineService(postgres_session)
    for episode, index, code in [(ep1, 1, "PG_A"), (ep2, 2, "PG_B")]:
        timeline.create_event(
            {
                "event_code": code,
                "event_type": "plot",
                "series_id": series.id,
                "episode_id": episode.id,
                "order_index": index,
                "title": code,
                "summary": code,
            }
        )
    doc = seed_document(postgres_session, series)
    structured = {"place": "safehouse", "floor": 2}
    postgres_session.add(
        MemoryFact(
            memory_document_id=doc.id,
            fact_type="canon",
            entity_type="character",
            entity_key="MIRA",
            fact_key="location",
            fact_value=structured,
            normalised_value=normalise_fact_value(structured),
            mutability="stateful",
            valid_from_episode_id=ep2.id,
            timeline_start_order=2,
        )
    )
    postgres_session.flush()

    service = RetconService(postgres_session)
    proposal = service.propose(
        series=series,
        entity_key="MIRA",
        fact_key="location",
        proposed_value={"place": "alley", "floor": 0},
        rationale="Flashback relocates the scene.",
        episode=ep1,
    )
    outcome = service.approve(proposal, decided_by="showrunner")
    written = postgres_session.get(MemoryFact, outcome.new_fact_id)
    assert written.fact_value == {"place": "alley", "floor": 0}
    assert written.is_retcon is True

    # And the approval is what unblocks the same change on a fresh check.
    result = ContradictionMatcher(postgres_session).check(
        series_id=series.id,
        proposed_facts=[
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "location",
                "fact_value": {"floor": 0, "place": "alley"},
                "mutability": "stateful",
            }
        ],
        episode=ep1,
        persist=False,
    )
    assert result.passed is True


def test_row_locking_is_available_on_this_dialect(postgres_session):
    # The workflow repository takes a per-episode row lock; SQLite silently
    # ignores FOR UPDATE, so this is the only place the clause is really run.
    series, season = seed_series(postgres_session)
    episode = seed_episode(postgres_session, series, season, "PG_LOCK", 1)
    postgres_session.commit()
    locked = postgres_session.scalar(
        select(Episode).where(Episode.id == episode.id).with_for_update()
    )
    assert locked.episode_code == "PG_LOCK"
    postgres_session.rollback()
