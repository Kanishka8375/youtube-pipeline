"""The 13 agents and their system prompts.

Twelve production agents plus the Master Anime QC agent, which reviews the
other twelve rather than producing episode content of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

PROMPT_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class AgentSpec:
    agent_code: str
    display_name: str
    prompt_file: str
    role_description: str


AGENTS: List[AgentSpec] = [
    AgentSpec(
        "executive_showrunner_agent",
        "Executive Showrunner",
        "executive_showrunner.txt",
        "Protects tone, identity and story cohesion; approves episode direction.",
    ),
    AgentSpec(
        "series_bible_agent",
        "Series Bible",
        "series_bible.txt",
        "Maintains canon, world rules, character states and unresolved mysteries.",
    ),
    AgentSpec(
        "season_planner_agent",
        "Season Planner",
        "season_planner.txt",
        "Structures the season arc and paces reveals across episodes.",
    ),
    AgentSpec(
        "episode_story_agent",
        "Episode Story",
        "episode_story.txt",
        "Turns an episode slot into a beat sheet with hook and cliffhanger.",
    ),
    AgentSpec(
        "scriptwriting_agent",
        "Scriptwriting",
        "scriptwriting.txt",
        "Writes concise, producible scene-by-scene scripts.",
    ),
    AgentSpec(
        "continuity_agent",
        "Continuity",
        "continuity.txt",
        "Audits scripts against canon, timeline and character logic.",
    ),
    AgentSpec(
        "character_asset_agent",
        "Character Asset",
        "character_asset.txt",
        "Determines character visual needs and maximizes asset reuse.",
    ),
    AgentSpec(
        "background_props_agent",
        "Background & Props",
        "background_props.txt",
        "Determines environments, crops, variants and props.",
    ),
    AgentSpec(
        "storyboard_scene_planning_agent",
        "Storyboard / Scene Planning",
        "storyboard_scene_planning.txt",
        "Converts the script into an editor-ready shot plan.",
    ),
    AgentSpec(
        "edit_motion_agent",
        "Edit & Motion",
        "edit_motion.txt",
        "Assembles the episode from approved assets, voice and scene plans.",
    ),
    AgentSpec(
        "packaging_agent",
        "Packaging",
        "packaging.txt",
        "Creates titles, thumbnails, descriptions and short hooks.",
    ),
    AgentSpec(
        "analytics_optimization_agent",
        "Analytics & Optimization",
        "analytics_optimization.txt",
        "Reviews performance and recommends next-episode changes.",
    ),
    AgentSpec(
        "master_anime_qc_agent",
        "Master Anime QC",
        "master_anime_qc.txt",
        "Final quality gate across story, edit, sound and anime-style polish.",
    ),
]

AGENTS_BY_CODE: Dict[str, AgentSpec] = {spec.agent_code: spec for spec in AGENTS}


class UnknownAgentError(ValueError):
    """Raised when a task is assigned to an agent that is not registered."""


class AgentRegistry:
    """Looks up agent specs and loads their prompts from disk."""

    def __init__(self, prompt_dir: Path | None = None) -> None:
        self.prompt_dir = prompt_dir or PROMPT_DIR

    def get(self, agent_code: str) -> AgentSpec:
        try:
            return AGENTS_BY_CODE[agent_code]
        except KeyError as exc:
            raise UnknownAgentError(
                f"Unknown agent {agent_code!r}. Known: {', '.join(sorted(AGENTS_BY_CODE))}"
            ) from exc

    def system_prompt(self, agent_code: str) -> str:
        spec = self.get(agent_code)
        return self._read(self.prompt_dir / spec.prompt_file)

    @staticmethod
    @lru_cache(maxsize=32)
    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8")
