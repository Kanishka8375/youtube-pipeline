"""The prompt template registry.

Templates are data, not f-strings scattered through services, for the same
reason `PIPELINE` is data: they need to be listable, previewable and diffable.
`GET /generation/templates` enumerates them and `POST .../preview` renders one
with sample variables, so a prompt change can be reviewed before it reaches a
paid API call.

Rendering is strict -- a missing variable raises rather than leaving a literal
`{episode_title}` in text sent to a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


class UnknownTemplateError(ValueError):
    """Raised when a template key is not registered."""


class MissingTemplateVariableError(ValueError):
    """Raised when rendering leaves a placeholder unfilled.

    Loud on purpose: a template rendered with a missing variable produces text
    containing a literal `{canon_constraints}`, which a model will cheerfully
    treat as part of the brief.
    """


@dataclass(frozen=True)
class PromptTemplate:
    key: str
    purpose: str
    #: What the caller must supply. Checked before rendering.
    variables: tuple
    body: str
    #: Sent as the system prompt when this template is used.
    system: str = ""

    def required_variables(self) -> List[str]:
        return sorted(set(_PLACEHOLDER.findall(self.body)))

    def render(self, variables: Mapping[str, Any]) -> str:
        missing = [name for name in self.required_variables() if name not in variables]
        if missing:
            raise MissingTemplateVariableError(
                f"Template {self.key!r} needs {missing}, which were not supplied"
            )
        return self.body.format(**variables)


CANON_DISCIPLINE = (
    "You write for a serialized anime channel with an enforced canon. "
    "Never state a fact about the world that is not in the canon block you were "
    "given. If something is unknown, write around it or say it is unknown -- "
    "an invented detail becomes canon the moment it is approved, and every later "
    "episode has to stay consistent with it."
)

TEMPLATES: Dict[str, PromptTemplate] = {
    t.key: t
    for t in [
        PromptTemplate(
            key="episode_script_v1",
            purpose="Full episode script from premise, series context and canon.",
            variables=("series_title", "series_premise", "episode_code", "episode_title",
                       "runtime_target_minutes", "canon_constraints", "style_rules"),
            system=CANON_DISCIPLINE,
            body="""Write the script for one episode.

SERIES: {series_title}
{series_premise}

EPISODE {episode_code}: {episode_title}
Target runtime: {runtime_target_minutes} minutes.

ESTABLISHED CANON — every one of these is already true and may not be contradicted:
{canon_constraints}

STYLE RULES:
{style_rules}

Structure the script with these exact section markers, in this order:
[HOOK] [SETUP] [MIDPOINT SHIFT] [ESCALATION] [PAYOFF] [OUTRO]

Return only the script.""",
        ),
        PromptTemplate(
            key="episode_outline_v1",
            purpose="Beat-level outline before committing to a full script.",
            variables=("series_title", "episode_title", "episode_premise", "canon_constraints"),
            system=CANON_DISCIPLINE,
            body="""Outline one episode as six beats.

SERIES: {series_title}
EPISODE: {episode_title}
PREMISE: {episode_premise}

ESTABLISHED CANON:
{canon_constraints}

Give one or two sentences for each of: hook, setup, midpoint shift,
escalation, payoff, outro. Name the emotional turn in each.""",
        ),
        PromptTemplate(
            key="hook_variations_v1",
            purpose="Several openings to test against each other.",
            variables=("episode_title", "episode_premise", "tone"),
            system=CANON_DISCIPLINE,
            body="""Write 5 alternative opening hooks.

EPISODE: {episode_title}
PREMISE: {episode_premise}
TONE: {tone}

Each hook: at most two sentences, opens a question the episode answers.
No rhetorical questions to camera, no "in this video". Number them 1-5.""",
        ),
        PromptTemplate(
            key="shot_prompt_v1",
            purpose="One cinematic image/video prompt for a single shot.",
            variables=("series_title", "shot_type", "emotion_target", "scene_context",
                       "style_rules"),
            system="You write image-generation prompts for a serialized anime series.",
            body="""Write one visual prompt for a single shot.

SERIES: {series_title}
SHOT TYPE: {shot_type}
EMOTIONAL TARGET: {emotion_target}

SCENE CONTEXT:
{scene_context}

STYLE RULES (binding — the series must look like itself across episodes):
{style_rules}

Return one paragraph. Describe framing, light, colour and motion. No dialogue,
no on-screen text, no camera brand names.""",
        ),
        PromptTemplate(
            key="thumbnail_prompt_v1",
            purpose="Thumbnail image prompt.",
            variables=("episode_title", "series_title", "emotion", "style_rules"),
            system="You write thumbnail prompts that read at 320px wide on a phone.",
            body="""Write one thumbnail image prompt.

EPISODE: {episode_title}
SERIES: {series_title}
EMOTION: {emotion}

STYLE RULES:
{style_rules}

Requirements: one focal subject, deep contrast, clear negative space on one
side for a 3-word overlay. Legible as a 320px-wide thumbnail. No text in the
image itself — the overlay is added later.""",
        ),
        PromptTemplate(
            key="narration_prompt_v1",
            purpose="Turn a script into narration-ready spoken text.",
            variables=("script_text", "voice_notes"),
            system="You prepare text for a voice actor or TTS engine.",
            body="""Rewrite this script as narration-ready spoken text.

VOICE NOTES: {voice_notes}

SCRIPT:
{script_text}

Keep the meaning exactly. Fix anything that reads well but speaks badly:
unpronounceable constructions, sentences too long for one breath, stage
directions that are not spoken. Mark deliberate pauses with [pause].
Return only the narration text.""",
        ),
        PromptTemplate(
            key="bgm_prompt_v1",
            purpose="Instrumental cue prompt for a music generator.",
            variables=("mood", "scene_type", "pacing", "duration_seconds"),
            system="You write prompts for instrumental music generation.",
            body="""Write one music generation prompt.

MOOD: {mood}
SCENE TYPE: {scene_type}
PACING: {pacing}
DURATION: about {duration_seconds} seconds

Instrumental only, no vocals. It sits under narration, so leave the midrange
open and avoid a lead line that competes with a speaking voice.""",
        ),
        PromptTemplate(
            key="continuity_review_v1",
            purpose="Ask a model to find continuity problems the mechanical checks cannot.",
            variables=("canon_constraints", "script_text"),
            system=(
                "You audit scripts against canon. Report only what the text actually "
                "says. A suspicion you cannot point at a line for is not a finding."
            ),
            body="""Review this script against established canon.

ESTABLISHED CANON:
{canon_constraints}

SCRIPT:
{script_text}

For each problem: quote the line, name which canon fact it contradicts, and say
whether it is a contradiction or merely unsupported. If there are none, say so
plainly. Do not invent problems to appear thorough.""",
        ),
    ]
}


def get_template(key: str) -> PromptTemplate:
    template = TEMPLATES.get(key)
    if template is None:
        raise UnknownTemplateError(
            f"Unknown template {key!r}. Known: {sorted(TEMPLATES)}"
        )
    return template


def list_templates() -> List[Dict[str, Any]]:
    return [
        {
            "key": t.key,
            "purpose": t.purpose,
            "variables": t.required_variables(),
            "has_system_prompt": bool(t.system),
        }
        for t in sorted(TEMPLATES.values(), key=lambda x: x.key)
    ]
