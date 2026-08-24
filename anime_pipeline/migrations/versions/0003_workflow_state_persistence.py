"""persist workflow state: task stage and episode blockers

Revision ID: 0003_workflow_state
Revises: 0002_seed_agents
Create Date: 2026-08-24

Moves the orchestrator's `WorkflowState` out of process memory:

- `tasks.stage` records which pipeline stage a task fulfils. Backfilled from
  `task_type`, which is distinct per stage in the declared graph.
- `episode_blockers` holds the freezes that were previously a list in RAM.

Backward compatible: both are additive, and `tasks.stage` is nullable, so rows
created before this revision keep working (they are simply invisible to the
orchestrator until backfilled).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_workflow_state"
down_revision = "0002_seed_agents"
branch_labels = None
depends_on = None

#: task_type -> stage for the pipeline as it stands at this revision. Inlined
#: rather than imported: a migration must keep describing the schema change it
#: made even after the application's PIPELINE moves on.
STAGE_BY_TASK_TYPE = {
    "approve_episode_brief": "showrunner_brief",
    "confirm_season_placement": "season_placement",
    "create_beat_sheet": "beat_sheet",
    "create_script_draft": "script_draft",
    "review_script_continuity": "continuity_review",
    "create_scene_plan": "scene_plan",
    "plan_character_assets": "character_assets",
    "plan_background_props": "background_props",
    "assemble_rough_cut": "rough_cut",
    "assemble_final_cut": "final_cut",
    "create_packaging_set": "packaging",
    "publish_episode": "publish",
    "review_episode_performance": "analytics_review",
    "update_series_bible": "canon_update",
    "adjust_season_plan": "season_adjustment",
}


def upgrade() -> None:
    op.add_column("tasks", sa.Column("stage", sa.String(length=64), nullable=True))
    op.create_index("ix_tasks_stage", "tasks", ["stage"], unique=False)

    tasks = sa.table("tasks", sa.column("stage", sa.String), sa.column("task_type", sa.String))
    for task_type, stage in STAGE_BY_TASK_TYPE.items():
        op.execute(
            tasks.update().where(tasks.c.task_type == task_type).values(stage=stage)
        )

    op.create_table(
        "episode_blockers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("blocker_type", sa.String(length=64), nullable=True),
        sa.Column("severity", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column("raised_by_agent_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raised_by_agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_episode_blockers_episode_id", "episode_blockers", ["episode_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_episode_blockers_episode_id", table_name="episode_blockers")
    op.drop_table("episode_blockers")
    op.drop_index("ix_tasks_stage", table_name="tasks")
    op.drop_column("tasks", "stage")
