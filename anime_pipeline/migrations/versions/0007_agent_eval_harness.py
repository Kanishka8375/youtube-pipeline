"""agent evaluation harness: benchmark runs and case results

Revision ID: 0007_agent_eval_harness
Revises: 0006_continuity_hardening
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0007_agent_eval_harness'
down_revision = '0006_continuity_hardening'
branch_labels = None
depends_on = None

JSONColumn = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table(
        'agent_eval_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('run_code', sa.String(length=128), nullable=False),
        sa.Column('suite_code', sa.String(length=128), nullable=False),
        sa.Column('target', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='running', nullable=False),
        sa.Column('total_cases', sa.Integer(), nullable=False),
        sa.Column('passed_cases', sa.Integer(), nullable=False),
        sa.Column('failed_cases', sa.Integer(), nullable=False),
        sa.Column('pass_rate', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('summary_json', JSONColumn, nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_code'),
    )
    op.create_index(op.f('ix_agent_eval_runs_suite_code'), 'agent_eval_runs', ['suite_code'], unique=False)

    op.create_table(
        'agent_eval_case_results',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=False),
        sa.Column('case_code', sa.String(length=128), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('expects_block', sa.Boolean(), nullable=False),
        sa.Column('expectation_json', JSONColumn, nullable=False),
        sa.Column('observed_json', JSONColumn, nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=False),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['agent_eval_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_id', 'case_code'),
    )
    op.create_index(op.f('ix_agent_eval_case_results_category'), 'agent_eval_case_results', ['category'], unique=False)
    op.create_index(op.f('ix_agent_eval_case_results_run_id'), 'agent_eval_case_results', ['run_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_agent_eval_case_results_run_id'), table_name='agent_eval_case_results')
    op.drop_index(op.f('ix_agent_eval_case_results_category'), table_name='agent_eval_case_results')
    op.drop_table('agent_eval_case_results')
    op.drop_index(op.f('ix_agent_eval_runs_suite_code'), table_name='agent_eval_runs')
    op.drop_table('agent_eval_runs')
