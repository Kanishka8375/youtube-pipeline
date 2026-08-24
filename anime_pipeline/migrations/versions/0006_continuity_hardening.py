"""continuity hardening: entity aliases, fact versioning, retcons, causality

Revision ID: 0006_continuity_hardening
Revises: 0005_canon_registry
Create Date: 2026-08-24

Backfill note
-------------
`entity_aliases` is populated from the existing `canonical_entities.aliases`
JSON so resolution keeps working the moment this runs -- without it, every
registered entity would become unresolvable until someone re-registered it.

The normalisation function is copied into this file rather than imported from
`app.services.normalisation`. A migration must keep producing the same rows
forever; importing live application code means a later change to normalisation
silently changes what this historical migration did.
"""
from __future__ import annotations

import re
import unicodedata
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0006_continuity_hardening'
down_revision = '0005_canon_registry'
branch_labels = None
depends_on = None

JSONColumn = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')

#: Frozen copy of normalise_alias as of this revision. See the module docstring.
_NAME_PUNCTUATION = re.compile(r"[.'’`\-_/\\]+")
_NON_ALNUM_SPACE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def _normalise(name: str) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _NAME_PUNCTUATION.sub(" ", text)
    text = _NON_ALNUM_SPACE.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text.casefold()


#: Foreign keys added to tables that already exist. SQLite has no
#: `ALTER TABLE ... ADD CONSTRAINT`, so these go through batch mode there,
#: which rebuilds the table with the constraint in place. Skipping them on
#: SQLite instead would leave the migrated schema disagreeing with the models,
#: which `alembic check` reports as drift on every subsequent run.
_ADDED_FOREIGN_KEYS = (
    (
        "fk_memory_facts_supersedes_fact_id",
        "memory_facts",
        "memory_facts",
        ["supersedes_fact_id"],
        ["id"],
    ),
    (
        "fk_contradiction_matches_retcon_proposal_id",
        "contradiction_matches",
        "retcon_proposals",
        ["retcon_proposal_id"],
        ["id"],
    ),
)


def _add_foreign_keys() -> None:
    for name, source, target, local_cols, remote_cols in _ADDED_FOREIGN_KEYS:
        with op.batch_alter_table(source) as batch:
            batch.create_foreign_key(
                name, target, local_cols, remote_cols, ondelete="SET NULL"
            )


def _drop_foreign_keys() -> None:
    for name, source, *_ in reversed(_ADDED_FOREIGN_KEYS):
        with op.batch_alter_table(source) as batch:
            batch.drop_constraint(name, type_="foreignkey")


def upgrade() -> None:
    op.create_table(
        'entity_aliases',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('series_id', sa.Uuid(), nullable=False),
        sa.Column('entity_id', sa.Uuid(), nullable=False),
        sa.Column('alias', sa.String(length=255), nullable=False),
        sa.Column('alias_normalised', sa.String(length=255), nullable=False),
        sa.Column('source', sa.String(length=32), server_default='manual', nullable=False),
        sa.Column('confidence', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['entity_id'], ['canonical_entities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['series_id'], ['series.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('series_id', 'alias_normalised'),
    )
    op.create_index(op.f('ix_entity_aliases_entity_id'), 'entity_aliases', ['entity_id'], unique=False)
    op.create_index('ix_entity_aliases_lookup', 'entity_aliases', ['series_id', 'alias_normalised'], unique=False)
    op.create_index(op.f('ix_entity_aliases_series_id'), 'entity_aliases', ['series_id'], unique=False)

    op.create_table(
        'timeline_causal_links',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('series_id', sa.Uuid(), nullable=False),
        sa.Column('cause_event_id', sa.Uuid(), nullable=False),
        sa.Column('effect_event_id', sa.Uuid(), nullable=False),
        sa.Column('link_type', sa.String(length=32), server_default='causes', nullable=False),
        sa.Column('strength', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['cause_event_id'], ['timeline_events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['effect_event_id'], ['timeline_events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['series_id'], ['series.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('series_id', 'cause_event_id', 'effect_event_id'),
    )
    op.create_index(op.f('ix_timeline_causal_links_cause_event_id'), 'timeline_causal_links', ['cause_event_id'], unique=False)
    op.create_index(op.f('ix_timeline_causal_links_effect_event_id'), 'timeline_causal_links', ['effect_event_id'], unique=False)
    op.create_index(op.f('ix_timeline_causal_links_series_id'), 'timeline_causal_links', ['series_id'], unique=False)

    op.create_table(
        'retcon_proposals',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('series_id', sa.Uuid(), nullable=False),
        sa.Column('episode_id', sa.Uuid(), nullable=True),
        sa.Column('entity_code', sa.String(length=128), nullable=False),
        sa.Column('fact_key', sa.String(length=128), nullable=False),
        sa.Column('proposed_value', JSONColumn, nullable=False),
        sa.Column('proposed_normalised_value', sa.String(length=512), nullable=True),
        sa.Column('existing_fact_id', sa.Uuid(), nullable=True),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='pending', nullable=False),
        sa.Column('retcon_group_code', sa.String(length=128), nullable=False),
        sa.Column('decided_by', sa.String(length=128), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['existing_fact_id'], ['memory_facts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['series_id'], ['series.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('retcon_group_code'),
    )
    op.create_index(op.f('ix_retcon_proposals_entity_code'), 'retcon_proposals', ['entity_code'], unique=False)
    op.create_index(op.f('ix_retcon_proposals_episode_id'), 'retcon_proposals', ['episode_id'], unique=False)
    op.create_index('ix_retcon_proposals_open', 'retcon_proposals', ['series_id', 'status'], unique=False)
    op.create_index(op.f('ix_retcon_proposals_proposed_normalised_value'), 'retcon_proposals', ['proposed_normalised_value'], unique=False)
    op.create_index(op.f('ix_retcon_proposals_series_id'), 'retcon_proposals', ['series_id'], unique=False)

    op.add_column('memory_facts', sa.Column('normalised_value', sa.String(length=512), nullable=True))
    op.add_column('memory_facts', sa.Column('timeline_start_order', sa.Integer(), nullable=True))
    op.add_column('memory_facts', sa.Column('timeline_end_order', sa.Integer(), nullable=True))
    op.add_column('memory_facts', sa.Column('supersedes_fact_id', sa.Uuid(), nullable=True))
    op.add_column('memory_facts', sa.Column('is_retcon', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('memory_facts', sa.Column('retcon_group_code', sa.String(length=128), nullable=True))
    op.add_column('memory_facts', sa.Column('confidence_score', sa.Float(), server_default='1.0', nullable=False))
    op.add_column('memory_facts', sa.Column('source_priority', sa.Integer(), server_default='100', nullable=False))
    op.create_index(op.f('ix_memory_facts_normalised_value'), 'memory_facts', ['normalised_value'], unique=False)
    op.create_index(op.f('ix_memory_facts_retcon_group_code'), 'memory_facts', ['retcon_group_code'], unique=False)
    op.create_index(op.f('ix_memory_facts_timeline_start_order'), 'memory_facts', ['timeline_start_order'], unique=False)

    op.add_column('contradiction_matches', sa.Column('severity_score', sa.Integer(), server_default='0', nullable=False))
    op.add_column('contradiction_matches', sa.Column('retcon_proposal_id', sa.Uuid(), nullable=True))

    _add_foreign_keys()
    _backfill_aliases()


def _backfill_aliases() -> None:
    """Seed entity_aliases from the entity code, display name and alias list.

    Done through Core table objects rather than raw SQL so the UUID and JSON
    columns go through their dialect bind processors: Postgres stores native
    uuid, SQLite stores 32-char hex, and raw text SQL would have to pick one.

    Skips a spelling already claimed in the same series rather than failing the
    migration. A pre-existing clash means two entities already answered to one
    name, which the resolver could not have handled either; recording the first
    and leaving the second unregistered is the state an operator can see and
    fix, where a failed migration on a production database is not.
    """
    meta = sa.MetaData()
    entities = sa.Table(
        'canonical_entities', meta,
        sa.Column('id', sa.Uuid()),
        sa.Column('series_id', sa.Uuid()),
        sa.Column('entity_code', sa.String(128)),
        sa.Column('display_name', sa.String(255)),
        sa.Column('aliases', JSONColumn),
    )
    aliases = sa.Table(
        'entity_aliases', meta,
        sa.Column('id', sa.Uuid()),
        sa.Column('series_id', sa.Uuid()),
        sa.Column('entity_id', sa.Uuid()),
        sa.Column('alias', sa.String(255)),
        sa.Column('alias_normalised', sa.String(255)),
        sa.Column('source', sa.String(32)),
        sa.Column('confidence', sa.Float()),
    )

    bind = op.get_bind()
    rows = bind.execute(sa.select(entities)).mappings().all()
    if not rows:
        return

    payload = []
    claimed: set = set()
    for row in rows:
        candidates = [
            (row['entity_code'], 'entity_code'),
            (row['display_name'], 'display_name'),
        ]
        for alias in row['aliases'] or []:
            candidates.append((alias, 'manual'))

        for alias, source in candidates:
            normalised = _normalise(alias or '')
            if not normalised:
                continue
            key = (str(row['series_id']), normalised)
            if key in claimed:
                continue
            claimed.add(key)
            payload.append(
                {
                    'id': uuid.uuid4(),
                    'series_id': row['series_id'],
                    'entity_id': row['id'],
                    'alias': alias,
                    'alias_normalised': normalised,
                    'source': source,
                    'confidence': 1.0,
                }
            )

    if payload:
        bind.execute(sa.insert(aliases), payload)


def downgrade() -> None:
    _drop_foreign_keys()

    op.drop_column('contradiction_matches', 'retcon_proposal_id')
    op.drop_column('contradiction_matches', 'severity_score')

    op.drop_index(op.f('ix_memory_facts_timeline_start_order'), table_name='memory_facts')
    op.drop_index(op.f('ix_memory_facts_retcon_group_code'), table_name='memory_facts')
    op.drop_index(op.f('ix_memory_facts_normalised_value'), table_name='memory_facts')
    op.drop_column('memory_facts', 'source_priority')
    op.drop_column('memory_facts', 'confidence_score')
    op.drop_column('memory_facts', 'retcon_group_code')
    op.drop_column('memory_facts', 'is_retcon')
    op.drop_column('memory_facts', 'supersedes_fact_id')
    op.drop_column('memory_facts', 'timeline_end_order')
    op.drop_column('memory_facts', 'timeline_start_order')
    op.drop_column('memory_facts', 'normalised_value')

    op.drop_index(op.f('ix_retcon_proposals_series_id'), table_name='retcon_proposals')
    op.drop_index(op.f('ix_retcon_proposals_proposed_normalised_value'), table_name='retcon_proposals')
    op.drop_index('ix_retcon_proposals_open', table_name='retcon_proposals')
    op.drop_index(op.f('ix_retcon_proposals_episode_id'), table_name='retcon_proposals')
    op.drop_index(op.f('ix_retcon_proposals_entity_code'), table_name='retcon_proposals')
    op.drop_table('retcon_proposals')

    op.drop_index(op.f('ix_timeline_causal_links_series_id'), table_name='timeline_causal_links')
    op.drop_index(op.f('ix_timeline_causal_links_effect_event_id'), table_name='timeline_causal_links')
    op.drop_index(op.f('ix_timeline_causal_links_cause_event_id'), table_name='timeline_causal_links')
    op.drop_table('timeline_causal_links')

    op.drop_index(op.f('ix_entity_aliases_series_id'), table_name='entity_aliases')
    op.drop_index('ix_entity_aliases_lookup', table_name='entity_aliases')
    op.drop_index(op.f('ix_entity_aliases_entity_id'), table_name='entity_aliases')
    op.drop_table('entity_aliases')
