"""canon memory layer

Adds the persistent consistency store every agent reads before working and
writes back to after approval: memory documents and facts, character profiles,
style bibles, and continuity check records.

Purely additive -- no existing table or column is touched.

Revision ID: 76b917715760
Revises: 0003_workflow_state
Create Date: 2026-08-24 07:48:25.503465
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004_canon_memory'
down_revision = '0003_workflow_state'
branch_labels = None
depends_on = None


ACTIVE_STYLE_BIBLE_INDEX = "uq_style_bibles_one_active_per_series"


def _create_active_style_bible_guard() -> None:
    """Enforce at most one active style bible per series, where supported."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite and MySQL lack partial indexes. MemoryBundleService raises
        # MultipleActiveStyleBiblesError if a second one ever appears, so the
        # invariant is still checked, just at read time rather than on write.
        return
    op.create_index(
        ACTIVE_STYLE_BIBLE_INDEX,
        "style_bibles",
        ["series_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def _drop_active_style_bible_guard() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_index(ACTIVE_STYLE_BIBLE_INDEX, table_name="style_bibles")


def upgrade() -> None:
    op.create_table('character_profiles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('series_id', sa.Uuid(), nullable=False),
    sa.Column('character_code', sa.String(length=128), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('aliases', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('age_range', sa.String(length=64), nullable=True),
    sa.Column('role_type', sa.String(length=64), nullable=True),
    sa.Column('personality_traits', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('motivations', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('fears', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('speech_style', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('relationship_map', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('visual_design', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('color_keys', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('recurring_props', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('do_not_change', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('current_status', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('canon_notes', sa.Text(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['series_id'], ['series.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('series_id', 'character_code')
    )
    op.create_index(op.f('ix_character_profiles_series_id'), 'character_profiles', ['series_id'], unique=False)
    op.create_table('style_bibles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('series_id', sa.Uuid(), nullable=False),
    sa.Column('style_code', sa.String(length=128), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('screenplay_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('dialogue_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('editing_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('cinematography_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('music_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('sfx_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('vfx_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('pacing_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('emotional_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('negative_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('frame_rate', sa.Float(), server_default=sa.text('(24.0)'), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['series_id'], ['series.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('series_id', 'style_code')
    )
    op.create_index(op.f('ix_style_bibles_series_id'), 'style_bibles', ['series_id'], unique=False)
    op.create_table('continuity_checks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('episode_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=True),
    sa.Column('check_type', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('issues', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('fixes_required', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('not_mechanically_checked', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('passed', sa.Boolean(), nullable=False),
    sa.Column('checked_by_agent_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['checked_by_agent_id'], ['agents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_continuity_checks_episode_id'), 'continuity_checks', ['episode_id'], unique=False)
    op.create_table('memory_documents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('memory_code', sa.String(length=128), nullable=False),
    sa.Column('memory_type', sa.String(length=64), nullable=False),
    sa.Column('scope_type', sa.String(length=32), nullable=False),
    sa.Column('scope_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('content_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('source_artifact_id', sa.Uuid(), nullable=True),
    sa.Column('source_task_id', sa.Uuid(), nullable=True),
    sa.Column('created_by_agent_id', sa.Uuid(), nullable=True),
    sa.Column('approved_by_agent_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['approved_by_agent_id'], ['agents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by_agent_id'], ['agents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_artifact_id'], ['artifacts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_task_id'], ['tasks.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('memory_code')
    )
    op.create_index(op.f('ix_memory_documents_memory_type'), 'memory_documents', ['memory_type'], unique=False)
    op.create_index('ix_memory_documents_scope', 'memory_documents', ['scope_type', 'scope_id'], unique=False)
    op.create_table('memory_facts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('memory_document_id', sa.Uuid(), nullable=False),
    sa.Column('fact_type', sa.String(length=64), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=False),
    sa.Column('entity_key', sa.String(length=128), nullable=False),
    sa.Column('fact_key', sa.String(length=128), nullable=False),
    sa.Column('fact_value', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('importance', sa.String(length=32), nullable=False),
    sa.Column('valid_from_episode_id', sa.Uuid(), nullable=True),
    sa.Column('valid_to_episode_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['memory_document_id'], ['memory_documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['valid_from_episode_id'], ['episodes.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['valid_to_episode_id'], ['episodes.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_memory_facts_entity', 'memory_facts', ['entity_type', 'entity_key', 'status'], unique=False)


    _create_active_style_bible_guard()
def downgrade() -> None:
    _drop_active_style_bible_guard()
    op.drop_index('ix_memory_facts_entity', table_name='memory_facts')
    op.drop_table('memory_facts')
    op.drop_index('ix_memory_documents_scope', table_name='memory_documents')
    op.drop_index(op.f('ix_memory_documents_memory_type'), table_name='memory_documents')
    op.drop_table('memory_documents')
    op.drop_index(op.f('ix_continuity_checks_episode_id'), table_name='continuity_checks')
    op.drop_table('continuity_checks')
    op.drop_index(op.f('ix_style_bibles_series_id'), table_name='style_bibles')
    op.drop_table('style_bibles')
    op.drop_index(op.f('ix_character_profiles_series_id'), table_name='character_profiles')
    op.drop_table('character_profiles')
