"""seed the 13 pipeline agents

Revision ID: 0002_seed_agents
Revises: 0001_initial
Create Date: 2026-08-23

Agent rows are seeded here rather than at application start so that a fresh
database is usable before the app boots, and so `tasks.agent_id` (a RESTRICT
foreign key) always has something to point at.

UUIDs are generated in Python rather than by `gen_random_uuid()`: the pgcrypto
function does not exist on SQLite, and this migration is expected to run
against both.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0002_seed_agents"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

AGENT_SEED = [
    ("executive_showrunner_agent", "Executive Showrunner",
     "Protects tone, identity and story cohesion; approves episode direction."),
    ("series_bible_agent", "Series Bible",
     "Maintains canon, world rules, character states and unresolved mysteries."),
    ("season_planner_agent", "Season Planner",
     "Structures the season arc and paces reveals across episodes."),
    ("episode_story_agent", "Episode Story",
     "Turns an episode slot into a beat sheet with hook and cliffhanger."),
    ("scriptwriting_agent", "Scriptwriting",
     "Writes concise, producible scene-by-scene scripts."),
    ("continuity_agent", "Continuity",
     "Audits scripts against canon, timeline and character logic."),
    ("character_asset_agent", "Character Asset",
     "Determines character visual needs and maximizes asset reuse."),
    ("background_props_agent", "Background & Props",
     "Determines environments, crops, variants and props."),
    ("storyboard_scene_planning_agent", "Storyboard / Scene Planning",
     "Converts the script into an editor-ready shot plan."),
    ("edit_motion_agent", "Edit & Motion",
     "Assembles the episode from approved assets, voice and scene plans."),
    ("packaging_agent", "Packaging",
     "Creates titles, thumbnails, descriptions and short hooks."),
    ("analytics_optimization_agent", "Analytics & Optimization",
     "Reviews performance and recommends next-episode changes."),
    ("master_anime_qc_agent", "Master Anime QC",
     "Final quality gate across story, edit, sound and anime-style polish."),
]

_agents = sa.table(
    "agents",
    sa.column("id", sa.Uuid),
    sa.column("agent_code", sa.String),
    sa.column("display_name", sa.String),
    sa.column("role_description", sa.Text),
    sa.column("system_prompt_version", sa.String),
    sa.column("allowed_tools", sa.JSON),
    sa.column("config", sa.JSON),
    sa.column("is_active", sa.Boolean),
)


def upgrade() -> None:
    op.bulk_insert(
        _agents,
        [
            {
                "id": uuid.uuid4(),
                "agent_code": code,
                "display_name": name,
                "role_description": role,
                "system_prompt_version": "v1",
                "allowed_tools": [],
                "config": {},
                "is_active": True,
            }
            for code, name, role in AGENT_SEED
        ],
    )


def downgrade() -> None:
    codes = [code for code, _, _ in AGENT_SEED]
    op.execute(
        sa.text("DELETE FROM agents WHERE agent_code IN :codes").bindparams(
            sa.bindparam("codes", value=tuple(codes), expanding=True)
        )
    )
