"""initial pipeline schema

Creates every table for the episode agent pipeline, including the master QC
tables. Portable: sa.Uuid renders native UUID on Postgres and CHAR(32)
elsewhere, and the JSON columns render JSONB on Postgres.

Revision ID: 3b054df6ccbf
Revises: 
Create Date: 2026-08-23 20:11:51.523081
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('agents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('agent_code', sa.String(length=128), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('role_description', sa.Text(), nullable=True),
    sa.Column('system_prompt_version', sa.String(length=64), nullable=True),
    sa.Column('allowed_tools', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('config', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('agent_code')
    )
    op.create_table('series',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('series_code', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('series_code')
    )
    op.create_table('seasons',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('series_id', sa.Uuid(), nullable=False),
    sa.Column('season_code', sa.String(length=64), nullable=False),
    sa.Column('season_number', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['series_id'], ['series.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('series_id', 'season_code'),
    sa.UniqueConstraint('series_id', 'season_number')
    )
    op.create_table('episodes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('series_id', sa.Uuid(), nullable=False),
    sa.Column('season_id', sa.Uuid(), nullable=False),
    sa.Column('episode_code', sa.String(length=64), nullable=False),
    sa.Column('episode_number', sa.Integer(), nullable=False),
    sa.Column('working_title', sa.String(length=255), nullable=True),
    sa.Column('final_title', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('current_stage', sa.String(length=50), nullable=False),
    sa.Column('runtime_target_minutes', sa.Integer(), nullable=True),
    sa.Column('publish_target_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('priority', sa.Enum('low', 'normal', 'high', 'urgent', name='priority_level'), nullable=False),
    sa.Column('main_hook', sa.Text(), nullable=True),
    sa.Column('core_conflict', sa.Text(), nullable=True),
    sa.Column('emotional_arc', sa.Text(), nullable=True),
    sa.Column('ending_beat', sa.Text(), nullable=True),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['season_id'], ['seasons.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['series_id'], ['series.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('episode_code'),
    sa.UniqueConstraint('season_id', 'episode_number')
    )
    op.create_table('workflow_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('episode_id', sa.Uuid(), nullable=False),
    sa.Column('workflow_name', sa.String(length=128), nullable=False),
    sa.Column('workflow_version', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('context', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('tasks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workflow_run_id', sa.Uuid(), nullable=True),
    sa.Column('episode_id', sa.Uuid(), nullable=False),
    sa.Column('agent_id', sa.Uuid(), nullable=False),
    sa.Column('task_code', sa.String(length=128), nullable=False),
    sa.Column('task_type', sa.String(length=128), nullable=False),
    sa.Column('task_category', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('queued', 'in_progress', 'waiting_on_dependency', 'waiting_for_review', 'approved', 'needs_revision', 'completed', 'blocked', 'failed', 'cancelled', name='task_status'), nullable=False),
    sa.Column('priority', sa.Enum('low', 'normal', 'high', 'urgent', name='priority_level'), nullable=False),
    sa.Column('input_context', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('instructions', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('output_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('output_schema_name', sa.String(length=128), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('max_retries', sa.Integer(), nullable=False),
    sa.Column('reviewer_agent_id', sa.Uuid(), nullable=True),
    sa.Column('approval_required', sa.Boolean(), nullable=False),
    sa.Column('created_by_agent_id', sa.Uuid(), nullable=True),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by_agent_id'], ['agents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewer_agent_id'], ['agents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workflow_run_id'], ['workflow_runs.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_code')
    )
    op.create_table('agent_logs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=True),
    sa.Column('agent_id', sa.Uuid(), nullable=True),
    sa.Column('level', sa.String(length=32), nullable=False),
    sa.Column('event_type', sa.String(length=128), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('artifacts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('episode_id', sa.Uuid(), nullable=False),
    sa.Column('source_task_id', sa.Uuid(), nullable=True),
    sa.Column('artifact_type', sa.String(length=128), nullable=False),
    sa.Column('artifact_code', sa.String(length=128), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('draft', 'submitted', 'approved', 'rejected', 'archived', name='artifact_status'), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('uri', sa.Text(), nullable=True),
    sa.Column('mime_type', sa.String(length=128), nullable=True),
    sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('content_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_by_agent_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_agent_id'], ['agents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_task_id'], ['tasks.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('artifact_code')
    )
    op.create_table('provider_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=True),
    sa.Column('provider_name', sa.String(length=128), nullable=False),
    sa.Column('job_type', sa.String(length=64), nullable=False),
    sa.Column('external_job_id', sa.String(length=255), nullable=True),
    sa.Column('status', sa.Enum('queued', 'submitted', 'processing', 'completed', 'failed', 'cancelled', name='provider_job_status'), nullable=False),
    sa.Column('request_payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('response_payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('callback_payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('task_dependencies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('depends_on_task_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['depends_on_task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_id', 'depends_on_task_id')
    )
    op.create_table('approvals',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('artifact_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=True),
    sa.Column('reviewer_agent_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'approved', 'needs_revision', 'rejected', name='approval_status'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['artifact_id'], ['artifacts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewer_agent_id'], ['agents.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('asset_requests',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('episode_id', sa.Uuid(), nullable=False),
    sa.Column('source_task_id', sa.Uuid(), nullable=True),
    sa.Column('asset_request_code', sa.String(length=128), nullable=False),
    sa.Column('asset_type', sa.String(length=64), nullable=False),
    sa.Column('asset_name', sa.String(length=255), nullable=False),
    sa.Column('scene_refs', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('priority', sa.Enum('low', 'normal', 'high', 'urgent', name='priority_level'), nullable=False),
    sa.Column('reusable', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('spec', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('output_artifact_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['output_artifact_id'], ['artifacts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_task_id'], ['tasks.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('asset_request_code')
    )
    op.create_table('master_qc_reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('master_qc_report_id', sa.String(length=128), nullable=False),
    sa.Column('episode_id', sa.Uuid(), nullable=False),
    sa.Column('source_task_id', sa.Uuid(), nullable=True),
    sa.Column('source_artifact_id', sa.Uuid(), nullable=True),
    sa.Column('reviewer_agent_id', sa.Uuid(), nullable=True),
    sa.Column('qc_stage', sa.Enum('script', 'scene_plan', 'rough_cut', 'final_cut', name='qc_stage_enum'), nullable=False),
    sa.Column('qc_type', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=64), nullable=False),
    sa.Column('overall_score', sa.Integer(), nullable=False),
    sa.Column('anime_style_score', sa.Integer(), nullable=False),
    sa.Column('publish_ready', sa.Boolean(), nullable=False),
    sa.Column('critical_issues', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('required_fixes_before_publish', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('optional_polish_suggestions', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('final_notes', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('sections', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('final_decision', sa.Enum('pass_', 'pass_with_revisions', 'reject', name='qc_decision_enum'), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('anime_style_score >= 0 AND anime_style_score <= 100', name='ck_qc_anime_style_score'),
    sa.CheckConstraint('overall_score >= 0 AND overall_score <= 100', name='ck_qc_overall_score'),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewer_agent_id'], ['agents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_artifact_id'], ['artifacts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_task_id'], ['tasks.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('master_qc_report_id')
    )
    op.create_table('scene_editor_qc_notes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('qc_report_id', sa.Uuid(), nullable=True),
    sa.Column('episode_id', sa.Uuid(), nullable=False),
    sa.Column('scene_id', sa.String(length=128), nullable=False),
    sa.Column('shot_id', sa.String(length=128), nullable=True),
    sa.Column('timecode', sa.String(length=32), nullable=True),
    sa.Column('frame_rate', sa.Float(), server_default=sa.text('(24.0)'), nullable=False),
    sa.Column('issue_type', sa.String(length=64), nullable=False),
    sa.Column('severity', sa.String(length=32), nullable=False),
    sa.Column('issue', sa.Text(), nullable=False),
    sa.Column('why_it_hurts', sa.Text(), nullable=True),
    sa.Column('current_duration_frames', sa.Integer(), nullable=True),
    sa.Column('recommended_duration_frames', sa.Integer(), nullable=True),
    sa.Column('fix_note', sa.Text(), nullable=True),
    sa.Column('mandatory_fix', sa.Boolean(), nullable=False),
    sa.Column('resolved', sa.Boolean(), nullable=False),
    sa.Column('assigned_to', sa.String(length=255), nullable=True),
    sa.Column('category', sa.String(length=64), nullable=True),
    sa.Column('created_by_agent_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_agent_id'], ['agents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['qc_report_id'], ['master_qc_reports.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('scene_editor_qc_notes')
    op.drop_table('master_qc_reports')
    op.drop_table('asset_requests')
    op.drop_table('approvals')
    op.drop_table('task_dependencies')
    op.drop_table('provider_jobs')
    op.drop_table('artifacts')
    op.drop_table('agent_logs')
    op.drop_table('tasks')
    op.drop_table('workflow_runs')
    op.drop_table('episodes')
    op.drop_table('seasons')
    op.drop_table('series')
    op.drop_table('agents')
