"""Turning stored canon into prompt variables.

This is the join between the two halves of the system. The continuity engine
spent five migrations learning what is true about a series; without this
module, generation would ignore all of it and invent freely, and the
enforcement gates would then reject what it produced.

The direction of travel matters: canon constrains generation *before* the call,
rather than the gates cleaning up afterwards. Rejecting a script after it is
written wastes the call and, worse, tempts a human to approve it anyway.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    CanonicalEntity,
    Episode,
    MemoryFact,
    Series,
    StyleBible,
)
from app.services.memory_service import MemoryBundleService
from app.services.generation.prompts.templates import get_template

#: Cap on facts rendered into a prompt. Beyond this the canon block crowds out
#: the actual brief; the most important facts are kept, so the cut is at the
#: bottom of a ranked list rather than arbitrary.
MAX_CANON_FACTS = 120

#: Ranking for the cut above.
_IMPORTANCE_RANK = {"critical": 0, "high": 1, "normal": 2, "low": 3}


class MissingSeriesError(ValueError):
    """Raised when an episode's series cannot be resolved."""


def _fact_line(fact: MemoryFact, entity_label: str) -> str:
    mutability = "fixed" if fact.mutability == "immutable" else "as of now"
    return f"- {entity_label}.{fact.fact_key} = {fact.fact_value!r} ({mutability})"


class CanonPromptBuilder:
    """Assembles the canon and style blocks a template needs."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.memory = MemoryBundleService(session)

    # -- canon ---------------------------------------------------------------
    def canon_constraints(self, series_id: uuid.UUID, *, limit: int = MAX_CANON_FACTS) -> str:
        """Every active canon fact, as lines a model can be held to.

        Ordered by importance then entity so the block is stable between calls
        -- an unstable prefix would defeat prompt caching on every request.
        """
        entities = {
            e.entity_code: e
            for e in self.session.scalars(
                select(CanonicalEntity).where(
                    CanonicalEntity.series_id == series_id,
                    CanonicalEntity.status == "active",
                )
            ).all()
        }

        facts = self.session.scalars(
            select(MemoryFact).where(MemoryFact.status == "active")
        ).all()

        rendered: List[tuple] = []
        for fact in facts:
            entity = entities.get(fact.entity_key)
            if entity is None:
                # Unregistered keys are included but marked: they are canon
                # too, they just have not been through the registry yet.
                label = f"{fact.entity_key} (unregistered)"
            else:
                label = entity.display_name
            rank = _IMPORTANCE_RANK.get((fact.importance or "normal").lower(), 2)
            rendered.append((rank, label, _fact_line(fact, label)))

        rendered.sort(key=lambda row: (row[0], row[1]))
        lines = [row[2] for row in rendered[:limit]]

        if not lines:
            return (
                "- No canon has been recorded for this series yet. Anything you "
                "establish here becomes binding on every later episode, so keep "
                "new world-facts few and deliberate."
            )
        if len(rendered) > limit:
            lines.append(
                f"- ({len(rendered) - limit} further lower-importance facts omitted.)"
            )
        return "\n".join(lines)

    # -- style ---------------------------------------------------------------
    def style_rules(self, series_id: uuid.UUID) -> str:
        """The active style bible, flattened.

        Reuses `MemoryBundleService.active_style_bible`, which raises when a
        series has two active bibles -- exactly the situation where a prompt
        would otherwise silently pick one and make the series drift.
        """
        bible: Optional[StyleBible] = self.memory.active_style_bible(series_id)
        if bible is None:
            return "- No style bible is set for this series. Keep choices conservative."

        sections = [
            ("Screenplay", bible.screenplay_rules),
            ("Dialogue", bible.dialogue_rules),
            ("Editing", bible.editing_rules),
            ("Cinematography", bible.cinematography_rules),
            ("Pacing", bible.pacing_rules),
            ("Emotional", bible.emotional_rules),
        ]
        lines = []
        for label, rules in sections:
            if not rules:
                continue
            for key, value in dict(rules).items():
                lines.append(f"- {label} / {key}: {value}")
        for rule in bible.negative_rules or []:
            lines.append(f"- NEVER: {rule}")
        return "\n".join(lines) if lines else "- Style bible is present but empty."

    # -- whole prompts -------------------------------------------------------
    def episode_script_variables(self, episode: Episode) -> Dict[str, Any]:
        series = self.session.get(Series, episode.series_id)
        if series is None:
            raise MissingSeriesError(f"Episode {episode.episode_code} has no series")

        return {
            "series_title": series.title,
            "series_premise": series.description or "(no series description recorded)",
            "episode_code": episode.episode_code,
            "episode_title": episode.working_title or episode.episode_code,
            "runtime_target_minutes": episode.runtime_target_minutes or 8,
            "canon_constraints": self.canon_constraints(series.id),
            "style_rules": self.style_rules(series.id),
        }

    def build(self, *, template_key: str, episode: Episode, extra: Optional[Dict[str, Any]] = None):
        """Render a template for an episode, returning (system, prompt)."""
        template = get_template(template_key)
        variables = self.episode_script_variables(episode)

        # Variables other templates need that the script template does not.
        variables.setdefault(
            "episode_premise",
            episode.main_hook or episode.core_conflict or "(no premise recorded)",
        )
        variables.setdefault("tone", "cinematic, restrained, serialized")
        variables.setdefault("emotion", "mystery")
        variables.setdefault("voice_notes", "measured, low-register, unhurried")
        variables.update(extra or {})

        return template.system, template.render(variables)
