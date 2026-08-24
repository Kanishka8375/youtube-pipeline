"""canon registry, timeline and continuity enforcement

Adds the layer that makes contradictions detectable:

- canonical_entities   one source of truth per named thing, so facts written
                       under different spellings still meet
- timeline_events      series chronology, so a fact change can be judged as
                       progression or as a retcon
- contradiction_matches, continuity_enforcement_runs, continuity_issues
                       the audit trail the publish gate reads

Also adds memory_facts.mutability. Existing rows default to `immutable`,
the conservative choice: a fact whose mutability nobody has classified is
flagged when it changes rather than passed silently.

Revision ID: ceaf9845ff9b
Revises: 0004_canon_memory
Create Date: 2026-08-24 09:38:48.686339
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0005_canon_registry'
down_revision = '0004_canon_memory'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('canonical_entities',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('series_id', sa.Uuid(), nullable=False),
    sa.Column('entity_code', sa.String(length=128), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('aliases', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('tags', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('metadata_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('is_canonical', sa.Boolean(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['series_id'], ['series.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('series_id', 'entity_code')
    )
    op.create_index(op.f('ix_canonical_entities_entity_type'), 'canonical_entities', ['entity_type'], unique=False)
    op.create_index(op.f('ix_canonical_entities_series_id'), 'canonical_entities', ['series_id'], unique=False)
    op.create_table('timeline_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('event_code', sa.String(length=128), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('series_id', sa.Uuid(), nullable=False),
    sa.Column('season_id', sa.Uuid(), nullable=True),
    sa.Column('episode_id', sa.Uuid(), nullable=True),
    sa.Column('order_index', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('involved_entity_codes', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('fact_refs', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('metadata_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('is_canonical', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['season_id'], ['seasons.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['series_id'], ['series.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('series_id', 'event_code'),
    sa.UniqueConstraint('series_id', 'order_index')
    )
    op.create_index(op.f('ix_timeline_events_episode_id'), 'timeline_events', ['episode_id'], unique=False)
    op.create_index(op.f('ix_timeline_events_series_id'), 'timeline_events', ['series_id'], unique=False)
    op.create_table('continuity_enforcement_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('episode_id', sa.Uuid(), nullable=True),
    sa.Column('task_id', sa.Uuid(), nullable=True),
    sa.Column('agent_id', sa.Uuid(), nullable=True),
    sa.Column('run_type', sa.String(length=64), nullable=False),
    sa.Column('source_type', sa.String(length=64), nullable=False),
    sa.Column('source_ref', sa.String(length=255), nullable=True),
    sa.Column('input_payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('memory_provenance', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('passed', sa.Boolean(), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_continuity_enforcement_runs_episode_id'), 'continuity_enforcement_runs', ['episode_id'], unique=False)
    op.create_index(op.f('ix_continuity_enforcement_runs_run_type'), 'continuity_enforcement_runs', ['run_type'], unique=False)
    op.create_table('continuity_issues',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('issue_type', sa.String(length=64), nullable=False),
    sa.Column('severity', sa.String(length=32), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=True),
    sa.Column('entity_key', sa.String(length=128), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('recommendation', sa.Text(), nullable=True),
    sa.Column('evidence_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('blocking', sa.Boolean(), nullable=False),
    sa.Column('resolved', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['continuity_enforcement_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_continuity_issues_run_id'), 'continuity_issues', ['run_id'], unique=False)
    op.create_table('contradiction_matches',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('episode_id', sa.Uuid(), nullable=True),
    sa.Column('source_run_id', sa.Uuid(), nullable=True),
    sa.Column('entity_code', sa.String(length=128), nullable=True),
    sa.Column('fact_key', sa.String(length=128), nullable=True),
    sa.Column('proposed_fact_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('existing_fact_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('contradiction_type', sa.String(length=64), nullable=False),
    sa.Column('severity', sa.String(length=32), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('blocking', sa.Boolean(), nullable=False),
    sa.Column('resolved', sa.Boolean(), nullable=False),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_run_id'], ['continuity_enforcement_runs.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_contradiction_matches_entity_code'), 'contradiction_matches', ['entity_code'], unique=False)
    op.create_index(op.f('ix_contradiction_matches_episode_id'), 'contradiction_matches', ['episode_id'], unique=False)
    op.add_column('memory_facts', sa.Column('mutability', sa.String(length=16), server_default='immutable', nullable=False))


def downgrade() -> None:
    op.drop_column('memory_facts', 'mutability')
    op.drop_index(op.f('ix_contradiction_matches_episode_id'), table_name='contradiction_matches')
    op.drop_index(op.f('ix_contradiction_matches_entity_code'), table_name='contradiction_matches')
    op.drop_table('contradiction_matches')
    op.drop_index(op.f('ix_continuity_issues_run_id'), table_name='continuity_issues')
    op.drop_table('continuity_issues')
    op.drop_index(op.f('ix_continuity_enforcement_runs_run_type'), table_name='continuity_enforcement_runs')
    op.drop_index(op.f('ix_continuity_enforcement_runs_episode_id'), table_name='continuity_enforcement_runs')
    op.drop_table('continuity_enforcement_runs')
    op.drop_index(op.f('ix_timeline_events_series_id'), table_name='timeline_events')
    op.drop_index(op.f('ix_timeline_events_episode_id'), table_name='timeline_events')
    op.drop_table('timeline_events')
    op.drop_index(op.f('ix_canonical_entities_series_id'), table_name='canonical_entities')
    op.drop_index(op.f('ix_canonical_entities_entity_type'), table_name='canonical_entities')
    op.drop_table('canonical_entities')
