"""Canon memory: assemble it for an agent, write approved changes back.

Two directions:

- `MemoryBundleService` reads. It gathers everything an agent must know before
  it writes a word — series canon, season and episode memory, character
  profiles, the active style bible.
- `AutoWritebackService` writes. It turns an *approved* artifact into durable
  canon, and refuses to guess about anything it cannot attribute.

The asymmetry is deliberate. Reads are permissive; writes are narrow, because
a wrong fact written into canon propagates into every later episode.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    CharacterProfile,
    ContinuityCheck,
    Episode,
    MemoryDocument,
    MemoryFact,
    Series,
    StyleBible,
)

#: Which memory_type belongs to which scope. Enforced on write so a document
#: cannot claim a scope its type does not support.
SCOPE_FOR_MEMORY_TYPE = {
    "series_canon": "series",
    "style_memory": "series",
    "season_memory": "season",
    "episode_memory": "episode",
}


class InvalidMemoryScopeError(ValueError):
    """Raised when a memory document's type and scope disagree."""


class MultipleActiveStyleBiblesError(RuntimeError):
    """Raised when a series has more than one active style bible.

    "The active style bible" must name exactly one row. Two would mean
    different agents silently working to different rules.
    """


def _now() -> datetime:
    return datetime.now(timezone.utc)


def validate_scope(memory_type: str, scope_type: str) -> None:
    expected = SCOPE_FOR_MEMORY_TYPE.get(memory_type)
    if expected is None:
        raise InvalidMemoryScopeError(
            f"Unknown memory_type {memory_type!r}. "
            f"Known: {', '.join(sorted(SCOPE_FOR_MEMORY_TYPE))}"
        )
    if scope_type != expected:
        raise InvalidMemoryScopeError(
            f"memory_type {memory_type!r} belongs to scope {expected!r}, got {scope_type!r}"
        )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
@dataclass
class MemoryBundle:
    """Everything an agent should read before producing anything."""

    agent_code: str
    series_code: str
    season_code: Optional[str] = None
    episode_code: Optional[str] = None
    series_memory: List[Dict[str, Any]] = field(default_factory=list)
    season_memory: List[Dict[str, Any]] = field(default_factory=list)
    episode_memory: List[Dict[str, Any]] = field(default_factory=list)
    character_profiles: List[Dict[str, Any]] = field(default_factory=list)
    style_bible: Optional[Dict[str, Any]] = None
    #: Document ids and versions actually used, so a task can record exactly
    #: which canon it was working from.
    provenance: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "agent_code": self.agent_code,
            "series_code": self.series_code,
            "season_code": self.season_code,
            "episode_code": self.episode_code,
            "series_memory": self.series_memory,
            "season_memory": self.season_memory,
            "episode_memory": self.episode_memory,
            "character_profiles": self.character_profiles,
            "style_bible": self.style_bible,
            "provenance": self.provenance,
        }


def _document_payload(doc: MemoryDocument) -> Dict[str, Any]:
    return {
        "memory_code": doc.memory_code,
        "memory_type": doc.memory_type,
        "title": doc.title,
        "summary": doc.summary,
        "content_json": doc.content_json,
        "version": doc.version,
    }


def _profile_payload(profile: CharacterProfile) -> Dict[str, Any]:
    return {
        "character_code": profile.character_code,
        "display_name": profile.display_name,
        "aliases": profile.aliases,
        "role_type": profile.role_type,
        "personality_traits": profile.personality_traits,
        "motivations": profile.motivations,
        "fears": profile.fears,
        "speech_style": profile.speech_style,
        "relationship_map": profile.relationship_map,
        "visual_design": profile.visual_design,
        "recurring_props": profile.recurring_props,
        "do_not_change": profile.do_not_change,
        "current_status": profile.current_status,
        "version": profile.version,
    }


def _style_payload(bible: StyleBible) -> Dict[str, Any]:
    return {
        "style_code": bible.style_code,
        "title": bible.title,
        "frame_rate": bible.frame_rate,
        "screenplay_rules": bible.screenplay_rules,
        "dialogue_rules": bible.dialogue_rules,
        "editing_rules": bible.editing_rules,
        "cinematography_rules": bible.cinematography_rules,
        "music_rules": bible.music_rules,
        "sfx_rules": bible.sfx_rules,
        "vfx_rules": bible.vfx_rules,
        "pacing_rules": bible.pacing_rules,
        "emotional_rules": bible.emotional_rules,
        "negative_rules": bible.negative_rules,
        "version": bible.version,
    }


class MemoryBundleService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def active_style_bible(self, series_id: uuid.UUID) -> Optional[StyleBible]:
        rows = self.session.scalars(
            select(StyleBible).where(
                StyleBible.series_id == series_id, StyleBible.is_active.is_(True)
            )
        ).all()
        if len(rows) > 1:
            raise MultipleActiveStyleBiblesError(
                f"Series {series_id} has {len(rows)} active style bibles: "
                f"{', '.join(r.style_code for r in rows)}. Exactly one must be active."
            )
        return rows[0] if rows else None

    def character_profiles(self, series_id: uuid.UUID) -> Sequence[CharacterProfile]:
        return self.session.scalars(
            select(CharacterProfile)
            .where(CharacterProfile.series_id == series_id)
            .order_by(CharacterProfile.character_code)
        ).all()

    def _documents(
        self, memory_type: str, scope_id: uuid.UUID
    ) -> Sequence[MemoryDocument]:
        return self.session.scalars(
            select(MemoryDocument)
            .where(
                MemoryDocument.memory_type == memory_type,
                MemoryDocument.scope_id == scope_id,
                MemoryDocument.status == "active",
            )
            .order_by(MemoryDocument.updated_at.desc())
        ).all()

    def build(
        self,
        *,
        agent_code: str,
        episode: Optional[Episode] = None,
        series: Optional[Series] = None,
    ) -> MemoryBundle:
        """Assemble a bundle from an episode (preferred) or a bare series."""
        if episode is None and series is None:
            raise ValueError("build() needs an episode or a series")

        resolved_series = series if episode is None else episode.series
        bundle = MemoryBundle(
            agent_code=agent_code,
            series_code=resolved_series.series_code,
            season_code=episode.season.season_code if episode else None,
            episode_code=episode.episode_code if episode else None,
        )

        series_docs = list(self._documents("series_canon", resolved_series.id))
        series_docs += list(self._documents("style_memory", resolved_series.id))
        bundle.series_memory = [_document_payload(d) for d in series_docs]

        season_docs: List[MemoryDocument] = []
        episode_docs: List[MemoryDocument] = []
        if episode is not None:
            season_docs = list(self._documents("season_memory", episode.season_id))
            episode_docs = list(self._documents("episode_memory", episode.id))
            bundle.season_memory = [_document_payload(d) for d in season_docs]
            bundle.episode_memory = [_document_payload(d) for d in episode_docs]

        profiles = self.character_profiles(resolved_series.id)
        bundle.character_profiles = [_profile_payload(p) for p in profiles]

        bible = self.active_style_bible(resolved_series.id)
        bundle.style_bible = _style_payload(bible) if bible else None

        bundle.provenance = [
            {"memory_code": d.memory_code, "version": d.version}
            for d in [*series_docs, *season_docs, *episode_docs]
        ]
        bundle.provenance += [
            {"character_code": p.character_code, "version": p.version} for p in profiles
        ]
        if bible is not None:
            bundle.provenance.append(
                {"style_code": bible.style_code, "version": bible.version}
            )
        return bundle

    def facts_for_entity(
        self, entity_type: str, entity_key: str, *, status: str = "active"
    ) -> Sequence[MemoryFact]:
        return self.session.scalars(
            select(MemoryFact).where(
                MemoryFact.entity_type == entity_type,
                MemoryFact.entity_key == entity_key,
                MemoryFact.status == status,
            )
        ).all()


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
@dataclass
class WritebackResult:
    created_facts: List[str] = field(default_factory=list)
    updated_characters: List[str] = field(default_factory=list)
    superseded_facts: List[str] = field(default_factory=list)
    #: Changes the parser would not apply, and why. These need a human or the
    #: showrunner agent to resolve.
    deferred: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "created_facts": self.created_facts,
            "updated_characters": self.updated_characters,
            "superseded_facts": self.superseded_facts,
            "deferred": self.deferred,
        }


class AutoWritebackService:
    """Turns an approved artifact into durable canon.

    Every write is attributable: facts carry `valid_from_episode_id`, and a
    character state change also lands as a fact, so the profile's history is
    reconstructible rather than overwritten silently.

    The parser refuses rather than guesses. An update naming an unknown
    character, or a fact missing required keys, goes to `deferred` instead of
    being dropped or approximated.
    """

    REQUIRED_FACT_KEYS = ("fact_type", "entity_type", "entity_key", "fact_key", "fact_value")

    def __init__(self, session: Session) -> None:
        self.session = session

    def extract(self, approved: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Split an approved payload into the three things memory accepts."""
        return {
            "canon_facts": list(approved.get("canon_facts", []) or []),
            "character_updates": list(approved.get("character_state_changes", []) or []),
            "unresolved_hooks": list(approved.get("unresolved_hooks", []) or []),
        }

    def apply(
        self,
        *,
        document: MemoryDocument,
        episode: Episode,
        extracted: Dict[str, List[Dict[str, Any]]],
    ) -> WritebackResult:
        result = WritebackResult()

        for fact in extracted.get("canon_facts", []):
            missing = [k for k in self.REQUIRED_FACT_KEYS if k not in fact]
            if missing:
                result.deferred.append(
                    {
                        "kind": "canon_fact",
                        "reason": f"missing required keys: {', '.join(missing)}",
                        "payload": fact,
                    }
                )
                continue
            result.superseded_facts.extend(
                self._supersede(
                    entity_type=fact["entity_type"],
                    entity_key=fact["entity_key"],
                    fact_key=fact["fact_key"],
                    episode=episode,
                )
            )
            row = MemoryFact(
                memory_document_id=document.id,
                fact_type=fact["fact_type"],
                entity_type=fact["entity_type"],
                entity_key=fact["entity_key"],
                fact_key=fact["fact_key"],
                fact_value=fact["fact_value"],
                importance=fact.get("importance", "normal"),
                valid_from_episode_id=episode.id,
            )
            self.session.add(row)
            self.session.flush()
            result.created_facts.append(str(row.id))

        for update in extracted.get("character_updates", []):
            code = update.get("character_code")
            profile = self.session.scalar(
                select(CharacterProfile).where(
                    CharacterProfile.series_id == episode.series_id,
                    CharacterProfile.character_code == code,
                )
            )
            if profile is None:
                # Creating a profile from a state patch would invent canon.
                result.deferred.append(
                    {
                        "kind": "character_update",
                        "reason": f"no character profile {code!r} in this series",
                        "payload": update,
                    }
                )
                continue

            patch = update.get("current_status_patch") or {}
            if not patch:
                result.deferred.append(
                    {
                        "kind": "character_update",
                        "reason": "empty current_status_patch",
                        "payload": update,
                    }
                )
                continue

            previous = dict(profile.current_status or {})
            merged = {**previous, **patch}
            if merged == previous:
                continue

            profile.current_status = merged
            profile.version += 1
            result.updated_characters.append(profile.character_code)

            # The profile holds only the present. The fact holds the change, so
            # "what did this character know at EP04" stays answerable.
            history = MemoryFact(
                memory_document_id=document.id,
                fact_type="character_state",
                entity_type="character",
                entity_key=profile.character_code,
                fact_key="current_status",
                fact_value={"previous": previous, "patch": patch, "result": merged},
                importance=update.get("importance", "normal"),
                valid_from_episode_id=episode.id,
            )
            self.session.add(history)
            self.session.flush()
            result.created_facts.append(str(history.id))

        for hook in extracted.get("unresolved_hooks", []):
            code = hook.get("hook_code")
            if not code:
                result.deferred.append(
                    {"kind": "unresolved_hook", "reason": "missing hook_code", "payload": hook}
                )
                continue
            row = MemoryFact(
                memory_document_id=document.id,
                fact_type="unresolved_hook",
                entity_type="hook",
                entity_key=code,
                fact_key="summary",
                fact_value={"summary": hook.get("summary", "")},
                importance=hook.get("importance", "high"),
                valid_from_episode_id=episode.id,
            )
            self.session.add(row)
            self.session.flush()
            result.created_facts.append(str(row.id))

        self.session.commit()
        return result

    def _supersede(
        self, *, entity_type: str, entity_key: str, fact_key: str, episode: Episode
    ) -> List[str]:
        """Close out the active fact this one replaces, rather than deleting it."""
        rows = self.session.scalars(
            select(MemoryFact).where(
                MemoryFact.entity_type == entity_type,
                MemoryFact.entity_key == entity_key,
                MemoryFact.fact_key == fact_key,
                MemoryFact.status == "active",
            )
        ).all()
        closed: List[str] = []
        for row in rows:
            row.status = "superseded"
            row.valid_to_episode_id = episode.id
            closed.append(str(row.id))
        return closed


def record_continuity_check(
    session: Session,
    *,
    episode: Episode,
    check_type: str,
    result: Any,
    task_id: Optional[uuid.UUID] = None,
) -> ContinuityCheck:
    """Persist a guard result as the episode's continuity record."""
    payload = result.as_dict() if hasattr(result, "as_dict") else dict(result)
    row = ContinuityCheck(
        episode_id=episode.id,
        task_id=task_id,
        check_type=check_type,
        status="passed" if payload.get("passed") else "needs_revision",
        issues=payload.get("issues", []),
        fixes_required=[
            issue["suggested_fix"]
            for issue in payload.get("issues", [])
            if issue.get("suggested_fix")
        ],
        not_mechanically_checked=payload.get("not_mechanically_checked", []),
        passed=bool(payload.get("passed")),
    )
    session.add(row)
    session.flush()
    return row
