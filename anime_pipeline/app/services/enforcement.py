"""Continuity enforcement: before a task, on a draft, and after approval.

Three gates, each recorded as a `ContinuityEnforcementRun`:

- **Preflight** refuses to start a task whose required canon is missing. An
  agent with no style bible does not fail loudly, it invents one.
- **Draft validation** runs the consistency guard and the contradiction matcher
  over a draft and records what it finds.
- **Writeback** parses an approved artifact into canon.

The consistency guard is reused, not reimplemented. A second copy would drift
from the first, and the first is the one with the tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ContinuityEnforcementRun,
    ContinuityIssue,
    Episode,
    MemoryDocument,
)
from app.services.canon_registry import EntityRegistry
from app.services.consistency_guard import ConsistencyGuardService
from app.services.contradiction import ContradictionMatcher
from app.services.memory_service import AutoWritebackService, MemoryBundleService

#: What each agent needs in place before it can work. Preflight refuses to
#: start a task whose components are missing rather than letting the agent
#: improvise the canon it cannot see.
REQUIRED_COMPONENTS: Dict[str, tuple] = {
    "executive_showrunner_agent": ("series_memory", "style_bible"),
    "season_planner_agent": ("series_memory",),
    "episode_story_agent": ("series_memory", "character_profiles"),
    "scriptwriting_agent": ("character_profiles", "style_bible"),
    "continuity_agent": ("series_memory", "character_profiles"),
    "character_asset_agent": ("character_profiles",),
    "background_props_agent": ("style_bible",),
    "storyboard_scene_planning_agent": ("style_bible",),
    "edit_motion_agent": ("style_bible",),
    "packaging_agent": ("style_bible",),
    # Reviews performance after publication; reads analytics, not canon.
    "analytics_optimization_agent": (),
    "master_anime_qc_agent": ("series_memory", "character_profiles", "style_bible"),
}

COMPONENT_CHECKS = {
    "series_memory": lambda b: bool(b.series_memory),
    "season_memory": lambda b: bool(b.season_memory),
    "episode_memory": lambda b: bool(b.episode_memory),
    "character_profiles": lambda b: bool(b.character_profiles),
    "style_bible": lambda b: b.style_bible is not None,
}


class UnknownComponentError(ValueError):
    """Raised when a required component name has no check defined."""


def required_components_for(agent_code: str) -> tuple:
    """What this agent must have. Unknown agents require nothing."""
    return REQUIRED_COMPONENTS.get(agent_code, ())


# ---------------------------------------------------------------------------
# Approved-output parsing
# ---------------------------------------------------------------------------
@dataclass
class ParsedOutput:
    canon_facts: List[Dict[str, Any]] = field(default_factory=list)
    character_state_changes: List[Dict[str, Any]] = field(default_factory=list)
    unresolved_hooks: List[Dict[str, Any]] = field(default_factory=list)
    #: Proposed additions to the style bible. Never auto-applied: style is a
    #: showrunner decision, and a rule inferred from one episode's QC notes is
    #: a hypothesis, not canon.
    style_candidates: List[Dict[str, Any]] = field(default_factory=list)
    unsupported: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "canon_facts": self.canon_facts,
            "character_state_changes": self.character_state_changes,
            "unresolved_hooks": self.unresolved_hooks,
            "style_candidates": self.style_candidates,
            "unsupported": self.unsupported,
        }


class ApprovedOutputParser:
    """Extracts canon changes from an approved artifact of any supported type."""

    SUPPORTED = ("script", "qc_report", "final_cut_metadata", "packaging")

    def parse(self, output_type: str, payload: Dict[str, Any]) -> ParsedOutput:
        handler = {
            "script": self._script,
            "qc_report": self._qc_report,
            "final_cut_metadata": self._final_cut,
            "packaging": self._packaging,
        }.get(output_type)

        if handler is None:
            return ParsedOutput(
                unsupported=[
                    {
                        "reason": f"unsupported approved output type {output_type!r}",
                        "supported": list(self.SUPPORTED),
                    }
                ]
            )
        return handler(payload)

    @staticmethod
    def _common(payload: Dict[str, Any]) -> ParsedOutput:
        return ParsedOutput(
            canon_facts=list(payload.get("canon_facts", []) or []),
            character_state_changes=list(payload.get("character_state_changes", []) or []),
            unresolved_hooks=list(payload.get("unresolved_hooks", []) or []),
        )

    def _script(self, payload: Dict[str, Any]) -> ParsedOutput:
        parsed = self._common(payload)
        parsed.style_candidates = list(payload.get("style_candidates", []) or [])
        return parsed

    def _qc_report(self, payload: Dict[str, Any]) -> ParsedOutput:
        """A QC report contributes style hypotheses, never canon facts.

        A repeated edit complaint is evidence a rule might be missing from the
        style bible; it is not itself a fact about the world.
        """
        parsed = ParsedOutput()
        for issue in payload.get("recurring_issues", []) or []:
            parsed.style_candidates.append(
                {
                    "domain": issue.get("domain", "editing"),
                    "rule_candidate": issue.get("rule_candidate") or issue.get("summary"),
                    "evidence": issue,
                }
            )
        return parsed

    def _final_cut(self, payload: Dict[str, Any]) -> ParsedOutput:
        parsed = self._common(payload)
        for motif in payload.get("music_motifs_introduced", []) or []:
            parsed.style_candidates.append({"domain": "music", "rule_candidate": motif})
        for motif in payload.get("visual_motifs_introduced", []) or []:
            parsed.style_candidates.append({"domain": "visual", "rule_candidate": motif})
        return parsed

    def _packaging(self, payload: Dict[str, Any]) -> ParsedOutput:
        parsed = ParsedOutput()
        for candidate in payload.get("packaging_style_candidates", []) or []:
            parsed.style_candidates.append({"domain": "packaging", "rule_candidate": candidate})
        return parsed


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------
class ContinuityEnforcementService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.bundles = MemoryBundleService(session)
        self.registry = EntityRegistry(session)
        self.matcher = ContradictionMatcher(session)
        self.parser = ApprovedOutputParser()

    # -- preflight ------------------------------------------------------
    def preflight(
        self,
        *,
        agent_code: str,
        episode: Episode,
        required: Optional[Sequence[str]] = None,
        task_id: Optional[uuid.UUID] = None,
    ) -> ContinuityEnforcementRun:
        components = tuple(required) if required is not None else required_components_for(agent_code)
        unknown = [c for c in components if c not in COMPONENT_CHECKS]
        if unknown:
            raise UnknownComponentError(
                f"Unknown required component(s): {', '.join(unknown)}. "
                f"Known: {', '.join(sorted(COMPONENT_CHECKS))}"
            )

        bundle = self.bundles.build(agent_code=agent_code, episode=episode)
        missing = [c for c in components if not COMPONENT_CHECKS[c](bundle)]

        run = ContinuityEnforcementRun(
            episode_id=episode.id,
            task_id=task_id,
            run_type="preflight",
            source_type="agent_task",
            source_ref=agent_code,
            input_payload={"required_components": list(components)},
            memory_provenance=bundle.provenance,
            passed=not missing,
            summary=(
                "Preflight passed"
                if not missing
                else f"Missing required canon: {', '.join(missing)}"
            ),
        )
        self.session.add(run)
        self.session.flush()

        for component in missing:
            self.session.add(
                ContinuityIssue(
                    run_id=run.id,
                    issue_type="missing_required_memory",
                    severity="high",
                    entity_type="memory_component",
                    entity_key=component,
                    title=f"Missing required component: {component}",
                    description=(
                        f"{agent_code} requires {component} and none exists for this "
                        "series or episode. An agent that cannot see canon invents it."
                    ),
                    recommendation=f"Create the {component} before starting this task.",
                    evidence_json={"missing_component": component},
                    blocking=True,
                )
            )
        self.session.flush()
        return run

    # -- draft validation ------------------------------------------------
    def validate_draft(
        self,
        *,
        agent_code: str,
        episode: Episode,
        payload: Dict[str, Any],
        source_type: str = "script",
        source_ref: Optional[str] = None,
        task_id: Optional[uuid.UUID] = None,
    ) -> ContinuityEnforcementRun:
        bundle = self.bundles.build(agent_code=agent_code, episode=episode)
        style_bible = self.bundles.active_style_bible(episode.series_id)
        guard = ConsistencyGuardService(
            profiles=self.bundles.character_profiles(episode.series_id),
            style_bible=style_bible,
        )
        guard_result = guard.validate_script(payload)

        run = ContinuityEnforcementRun(
            episode_id=episode.id,
            task_id=task_id,
            run_type="draft_validation",
            source_type=source_type,
            source_ref=source_ref,
            input_payload=payload,
            memory_provenance=bundle.provenance,
            passed=False,  # set below
        )
        self.session.add(run)
        self.session.flush()

        contradictions = self.matcher.check(
            series_id=episode.series_id,
            proposed_facts=payload.get("proposed_facts", []) or [],
            episode=episode,
            source_run_id=run.id,
        )

        blocking_count = 0

        for issue in guard_result.issues:
            if issue.severity == "high":
                blocking_count += 1
            self.session.add(
                ContinuityIssue(
                    run_id=run.id,
                    issue_type=issue.check,
                    severity=issue.severity,
                    entity_type="character" if issue.speaker else "scene",
                    entity_key=issue.speaker or issue.scene_id,
                    title=f"{issue.check.replace('_', ' ').capitalize()} in {issue.scene_id}",
                    description=issue.detail,
                    recommendation=issue.suggested_fix,
                    evidence_json={"scene_id": issue.scene_id, "speaker": issue.speaker},
                    blocking=issue.severity == "high",
                )
            )

        for finding in contradictions.contradictions:
            if finding.blocking:
                blocking_count += 1
            self.session.add(
                ContinuityIssue(
                    run_id=run.id,
                    issue_type=finding.kind,
                    severity=finding.severity,
                    entity_type="canon_fact",
                    entity_key=finding.entity_code,
                    title=f"{finding.kind.replace('_', ' ').capitalize()}: {finding.entity_code}",
                    description=finding.explanation,
                    recommendation=(
                        "Reconcile with established canon, or have the showrunner "
                        "approve the change and supersede the existing fact."
                    ),
                    evidence_json=finding.as_dict(),
                    blocking=finding.blocking,
                )
            )

        # Counted as issues are built rather than re-queried: the session runs
        # with autoflush off, so a query here would not see the pending rows
        # and every run would report as passing.
        run.passed = blocking_count == 0
        run.summary = (
            "Draft validation passed"
            if run.passed
            else f"{blocking_count} blocking issue(s)"
        )
        # A guard pass is not a full clearance; carry that forward so a green
        # run is not mistaken for one.
        run.input_payload = {
            **payload,
            "_not_mechanically_checked": guard_result.not_mechanically_checked,
            "_unknown_speakers": guard_result.unknown_speakers,
            "_unregistered_entities": contradictions.unregistered_entities,
            "_progressions": contradictions.progressions,
        }
        self.session.flush()
        return run

    # -- writeback -------------------------------------------------------
    def writeback(
        self,
        *,
        episode: Episode,
        document: MemoryDocument,
        output_type: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        parsed = self.parser.parse(output_type, payload)
        writer = AutoWritebackService(self.session)
        result = writer.apply(
            document=document,
            episode=episode,
            extracted={
                "canon_facts": parsed.canon_facts,
                "character_updates": parsed.character_state_changes,
                "unresolved_hooks": parsed.unresolved_hooks,
            },
        )
        return {
            "parsed": parsed.as_dict(),
            "writeback": result.as_dict(),
            # Style candidates are never applied automatically.
            "style_candidates_awaiting_approval": parsed.style_candidates,
        }

    # -- publish gate input ----------------------------------------------
    def open_blocking_issues(self, episode_id: uuid.UUID) -> Sequence[ContinuityIssue]:
        return self.session.scalars(
            select(ContinuityIssue)
            .join(ContinuityEnforcementRun)
            .where(
                ContinuityEnforcementRun.episode_id == episode_id,
                ContinuityIssue.blocking.is_(True),
                ContinuityIssue.resolved.is_(False),
            )
        ).all()
