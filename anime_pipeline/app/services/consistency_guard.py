"""Mechanical consistency checks for a draft script against canon.

What this can and cannot do
---------------------------
This guard checks what a machine can actually check: literal forbidden
phrases, line-length limits, monologue caps, unknown speakers, and banned
terminology. It reports those as issues.

It deliberately does **not** try to judge things like "never becomes bubbly
comic relief". A substring search for that description against dialogue can
never match a real line, so a guard built that way passes everything and
reports success — worse than no guard, because it manufactures confidence.
Those rules are carried through to `not_mechanically_checked` and handed to
the Master QC agent, whose job is judgement.

`speech_style` keys
-------------------
Mechanically checked:

    forbidden_phrases     list[str]  literal substrings the character never says
    max_line_words        int        longest single line, in words
    max_consecutive_lines int        longest unbroken run of their lines

Reviewer-only (surfaced, never auto-passed):

    tone, patterns, notes_for_reviewer, and anything else
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

#: speech_style keys this module knows how to evaluate.
MECHANICAL_KEYS = frozenset({"forbidden_phrases", "max_line_words", "max_consecutive_lines"})


def _words(text: str) -> int:
    return len(text.split())


def _contains_phrase(haystack: str, needle: str) -> bool:
    """Word-boundary-aware, case-insensitive containment.

    Plain `in` would flag "cooperate" for a forbidden "cool"; a boundary match
    keeps the check to whole words and phrases.
    """
    pattern = r"(?<!\w)" + re.escape(needle.strip()) + r"(?!\w)"
    return re.search(pattern, haystack, flags=re.IGNORECASE) is not None


@dataclass
class ConsistencyIssue:
    check: str
    severity: str
    scene_id: Optional[str]
    speaker: Optional[str]
    detail: str
    suggested_fix: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "scene_id": self.scene_id,
            "speaker": self.speaker,
            "detail": self.detail,
            "suggested_fix": self.suggested_fix,
        }


@dataclass
class ConsistencyResult:
    passed: bool
    issues: List[ConsistencyIssue] = field(default_factory=list)
    #: Rules that exist in canon but no mechanism here can evaluate.
    not_mechanically_checked: List[Dict[str, Any]] = field(default_factory=list)
    #: Speakers in the script that resolved to no character profile.
    unknown_speakers: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": [issue.as_dict() for issue in self.issues],
            "not_mechanically_checked": self.not_mechanically_checked,
            "unknown_speakers": self.unknown_speakers,
        }


class SpeakerResolver:
    """Maps a script's `speaker` string to a character profile.

    Scripts name speakers the way a reader would ("Mira", "Mira Kisaragi"),
    while canon keys them by code ("MIRA"). Matching on code alone resolves
    almost nothing, so display names and aliases are indexed too.
    """

    def __init__(self, profiles: Iterable[Any]) -> None:
        self._index: Dict[str, Any] = {}
        for profile in profiles:
            for key in self._keys_for(profile):
                self._index.setdefault(key, profile)

    @staticmethod
    def _keys_for(profile: Any) -> List[str]:
        keys = [profile.character_code, profile.display_name]
        keys.extend(profile.aliases or [])
        # A display name's first token: scripts usually credit "Mira", not
        # "Mira Kisaragi".
        if profile.display_name:
            keys.append(profile.display_name.split()[0])
        return [k.strip().casefold() for k in keys if k and k.strip()]

    def resolve(self, speaker: str) -> Optional[Any]:
        if not speaker:
            return None
        return self._index.get(speaker.strip().casefold())


class ConsistencyGuardService:
    """Audits a script draft against character profiles and the style bible."""

    def __init__(self, profiles: Sequence[Any], style_bible: Any | None = None) -> None:
        self.profiles = list(profiles)
        self.resolver = SpeakerResolver(self.profiles)
        self.style_bible = style_bible

    # -- public ---------------------------------------------------------
    def validate_script(self, script: Dict[str, Any]) -> ConsistencyResult:
        issues: List[ConsistencyIssue] = []
        unknown: List[str] = []

        for scene in script.get("scenes", []):
            scene_id = scene.get("scene_id")
            run_speaker: Optional[str] = None
            run_length = 0

            for entry in scene.get("dialogue", []):
                speaker = entry.get("speaker", "")
                # The script schema calls this field `line`; accept `text` too
                # so a payload written against the older draft still validates
                # rather than silently checking an empty string.
                text = entry.get("line") or entry.get("text") or ""

                profile = self.resolver.resolve(speaker)
                if profile is None:
                    if speaker and speaker not in unknown:
                        unknown.append(speaker)
                    run_speaker, run_length = None, 0
                    continue

                issues.extend(self._check_line(profile, scene_id, speaker, text))

                if speaker == run_speaker:
                    run_length += 1
                else:
                    run_speaker, run_length = speaker, 1
                issues.extend(
                    self._check_run(profile, scene_id, speaker, run_length)
                )

        issues.extend(self._check_banned_terms(script))

        result = ConsistencyResult(
            passed=not issues,
            issues=issues,
            not_mechanically_checked=self._uncheckable_rules(),
            unknown_speakers=unknown,
        )
        return result

    # -- individual checks ----------------------------------------------
    def _check_line(
        self, profile: Any, scene_id: Optional[str], speaker: str, text: str
    ) -> List[ConsistencyIssue]:
        found: List[ConsistencyIssue] = []
        style = profile.speech_style or {}

        for phrase in style.get("forbidden_phrases", []) or []:
            if _contains_phrase(text, phrase):
                found.append(
                    ConsistencyIssue(
                        check="forbidden_phrase",
                        severity="high",
                        scene_id=scene_id,
                        speaker=speaker,
                        detail=f"{profile.character_code} says {phrase!r}, which canon forbids.",
                        suggested_fix=f"Rewrite the line without {phrase!r}.",
                    )
                )

        max_words = style.get("max_line_words")
        if isinstance(max_words, int) and max_words > 0:
            count = _words(text)
            if count > max_words:
                found.append(
                    ConsistencyIssue(
                        check="line_too_long",
                        severity="medium",
                        scene_id=scene_id,
                        speaker=speaker,
                        detail=(
                            f"{profile.character_code} speaks {count} words; canon caps "
                            f"a line at {max_words}."
                        ),
                        suggested_fix=f"Cut to {max_words} words or split across a reaction beat.",
                    )
                )
        return found

    def _check_run(
        self, profile: Any, scene_id: Optional[str], speaker: str, run_length: int
    ) -> List[ConsistencyIssue]:
        max_run = (profile.speech_style or {}).get("max_consecutive_lines")
        if not isinstance(max_run, int) or max_run <= 0 or run_length != max_run + 1:
            # Fire once, on the line that first breaks the cap, not on every
            # line after it.
            return []
        return [
            ConsistencyIssue(
                check="monologue",
                severity="medium",
                scene_id=scene_id,
                speaker=speaker,
                detail=(
                    f"{profile.character_code} has {run_length} consecutive lines; "
                    f"canon caps the run at {max_run}."
                ),
                suggested_fix="Break the run with a reaction, an action beat or another speaker.",
            )
        ]

    def _check_banned_terms(self, script: Dict[str, Any]) -> List[ConsistencyIssue]:
        """Series-wide banned terminology from the style bible."""
        if self.style_bible is None:
            return []
        banned = (self.style_bible.dialogue_rules or {}).get("banned_terms", []) or []
        if not banned:
            return []

        found: List[ConsistencyIssue] = []
        for scene in script.get("scenes", []):
            scene_id = scene.get("scene_id")
            haystacks = [scene.get("summary", "") or ""]
            haystacks += [
                (e.get("line") or e.get("text") or "") for e in scene.get("dialogue", [])
            ]
            haystacks += list(scene.get("narration", []) or [])
            blob = "\n".join(haystacks)
            for term in banned:
                if _contains_phrase(blob, term):
                    found.append(
                        ConsistencyIssue(
                            check="banned_term",
                            severity="high",
                            scene_id=scene_id,
                            speaker=None,
                            detail=f"Scene uses banned series terminology {term!r}.",
                            suggested_fix=f"Replace {term!r} with the canonical term.",
                        )
                    )
        return found

    def _uncheckable_rules(self) -> List[Dict[str, Any]]:
        """Canon rules no mechanism here evaluates, for the QC agent to judge."""
        carried: List[Dict[str, Any]] = []
        for profile in self.profiles:
            prose = [
                key
                for key in (profile.speech_style or {})
                if key not in MECHANICAL_KEYS
            ]
            if prose or profile.do_not_change:
                carried.append(
                    {
                        "entity_type": "character",
                        "entity_key": profile.character_code,
                        "reviewer_rules": list(profile.do_not_change or []),
                        "speech_style_keys_not_checked": sorted(prose),
                    }
                )
        if self.style_bible is not None and self.style_bible.negative_rules:
            carried.append(
                {
                    "entity_type": "style_bible",
                    "entity_key": self.style_bible.style_code,
                    "reviewer_rules": list(self.style_bible.negative_rules),
                    "speech_style_keys_not_checked": [],
                }
            )
        return carried
