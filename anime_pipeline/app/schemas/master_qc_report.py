"""Master QC report contract and scoring.

The source spec carried three mutually inconsistent scoring rules:

1. A weighted table where each category had a different maximum (Emotional
   Impact 12, Audio Mix 5, ...), summing to 100.
2. Example reports that scored categories on a 0-10 scale regardless of that
   maximum -- `audio_mix: 9` against a stated maximum of 5.
3. An `overall_score` that matched neither the sum nor the weighted sum of its
   own sections.

This module resolves that: every category is scored **0-10**, and the weights
below convert those raw scores into a 0-100 total. `overall_score`,
`anime_style_score` and `publish_ready` are all *computed* from the sections
rather than accepted from the caller, so a report cannot claim a score its
own contents do not support. See docs/anime-pipeline/02-qc-framework.md.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import QCDecision, QCStage

#: Raw per-category score range. Uniform across categories by design.
SECTION_MIN_SCORE = 0
SECTION_MAX_SCORE = 10

#: Category weights, summing to 100. These express how much each area matters
#: to the finished episode; they are NOT per-category maximums.
CATEGORY_WEIGHTS: Dict[str, int] = {
    "story_logic": 10,
    "screenplay": 10,
    "emotion": 12,
    "character_consistency": 8,
    "scene_pacing": 10,
    "shot_design": 8,
    "animation_feel": 8,
    "editing_rhythm": 10,
    "sound_design": 7,
    "music": 7,
    "vfx": 5,
    "audio_mix": 5,
}

#: The subset that defines "does this feel like anime, or like a slideshow".
#: Scored separately so a story-strong / edit-weak episode is visibly flagged.
ANIME_STYLE_CATEGORIES = (
    "scene_pacing",
    "shot_design",
    "animation_feel",
    "editing_rhythm",
    "sound_design",
    "music",
    "vfx",
)

#: Minimum overall score for publication. One number, applied everywhere.
PUBLISH_SCORE_THRESHOLD = 85

#: Readiness bands, high to low. (inclusive lower bound, label)
READINESS_TIERS = (
    (90, "Premium Ready"),
    (PUBLISH_SCORE_THRESHOLD, "Publishable"),
    (70, "Revision Recommended"),
    (0, "Do Not Publish"),
)


class QCSection(BaseModel):
    """One review category. `score` is 0-10; weighting happens at roll-up."""

    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=SECTION_MIN_SCORE, le=SECTION_MAX_SCORE)
    issues: List[str] = Field(default_factory=list)
    required_fixes: List[str] = Field(default_factory=list)
    optional_polish: List[str] = Field(default_factory=list)


class MasterQCSections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_logic: QCSection
    screenplay: QCSection
    emotion: QCSection
    character_consistency: QCSection
    scene_pacing: QCSection
    shot_design: QCSection
    animation_feel: QCSection
    editing_rhythm: QCSection
    sound_design: QCSection
    music: QCSection
    vfx: QCSection
    audio_mix: QCSection

    def weighted_total(self) -> int:
        """0-100 weighted roll-up of the twelve raw category scores."""
        total = sum(
            getattr(self, name).score / SECTION_MAX_SCORE * weight
            for name, weight in CATEGORY_WEIGHTS.items()
        )
        return round(total)

    def anime_style_total(self) -> int:
        """0-100 roll-up over the edit-feel categories only."""
        weight_sum = sum(CATEGORY_WEIGHTS[name] for name in ANIME_STYLE_CATEGORIES)
        total = sum(
            getattr(self, name).score / SECTION_MAX_SCORE * CATEGORY_WEIGHTS[name]
            for name in ANIME_STYLE_CATEGORIES
        )
        return round(total / weight_sum * 100)

    def all_required_fixes(self) -> List[str]:
        fixes: List[str] = []
        for name in CATEGORY_WEIGHTS:
            fixes.extend(getattr(self, name).required_fixes)
        return fixes

    def weakest_categories(self, limit: int = 3) -> List[str]:
        """Category names with the lowest scores, worst first."""
        ranked = sorted(CATEGORY_WEIGHTS, key=lambda n: getattr(self, n).score)
        return ranked[:limit]


def readiness_tier(overall_score: int) -> str:
    for floor, label in READINESS_TIERS:
        if overall_score >= floor:
            return label
    return READINESS_TIERS[-1][1]


class MasterQCReport(BaseModel):
    """A QC verdict on one episode at one stage.

    `episode_id` is the human episode *code* (``EP01``), matching the rest of
    the JSON contracts. The database stores a UUID foreign key and resolves
    between the two -- see `app.db.models.MasterQCReport`.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    master_qc_report_id: str
    episode_id: str
    qc_stage: QCStage
    qc_type: str = "master_qc"
    status: str = "pending"
    sections: MasterQCSections
    critical_issues: List[str] = Field(default_factory=list)
    required_fixes_before_publish: List[str] = Field(default_factory=list)
    optional_polish_suggestions: List[str] = Field(default_factory=list)
    final_notes: List[str] = Field(default_factory=list)

    # Derived. Any value supplied by the caller is overwritten on validation.
    overall_score: int = 0
    anime_style_score: int = 0
    publish_ready: bool = False
    readiness: str = ""
    final_decision: Optional[QCDecision] = None

    @model_validator(mode="after")
    def _derive(self) -> "MasterQCReport":
        # Recompute rather than trust: an agent that reports a flattering
        # total alongside poor sections must not be able to open the gate.
        object.__setattr__(self, "overall_score", self.sections.weighted_total())
        object.__setattr__(self, "anime_style_score", self.sections.anime_style_total())

        # Section-level required_fixes are mandatory too; fold them in so a fix
        # recorded only inside a category still blocks publication.
        merged = list(
            dict.fromkeys(
                [*self.required_fixes_before_publish, *self.sections.all_required_fixes()]
            )
        )
        object.__setattr__(self, "required_fixes_before_publish", merged)

        ready = (
            self.overall_score >= PUBLISH_SCORE_THRESHOLD
            and not merged
            and not self.critical_issues
            and self.qc_stage is QCStage.final_cut
        )
        object.__setattr__(self, "publish_ready", ready)
        object.__setattr__(self, "readiness", readiness_tier(self.overall_score))

        if self.final_decision is None:
            if ready:
                decision = QCDecision.pass_
            elif self.overall_score >= 70:
                decision = QCDecision.pass_with_revisions
            else:
                decision = QCDecision.reject
            object.__setattr__(self, "final_decision", decision)
        return self


class SceneEditorQCNote(BaseModel):
    """A frame-accurate note against one scene or shot.

    `frame_rate` is required. The source checklist quoted fixes in frames
    ("extend by 8 frames") without ever stating a rate, which makes every one
    of them ambiguous -- 8 frames is 333ms at 24fps and 267ms at 30fps.
    """

    model_config = ConfigDict(extra="forbid")

    qc_note_id: str
    episode_id: str
    scene_id: str
    shot_id: Optional[str] = None
    timecode: Optional[str] = None
    frame_rate: float = Field(gt=0, description="Project fps; anime edits are usually 24.")
    issue_type: str
    severity: str = "medium"
    issue: str
    why_it_hurts: Optional[str] = None
    current_duration_frames: Optional[int] = Field(default=None, ge=0)
    recommended_duration_frames: Optional[int] = Field(default=None, ge=0)
    fix_note: Optional[str] = None
    mandatory_fix: bool = False
    resolved: bool = False
    assigned_to: Optional[str] = None
    category: Optional[str] = None

    @property
    def frame_delta(self) -> Optional[int]:
        """Frames to add (positive) or remove (negative)."""
        if self.current_duration_frames is None or self.recommended_duration_frames is None:
            return None
        return self.recommended_duration_frames - self.current_duration_frames

    @property
    def delta_milliseconds(self) -> Optional[float]:
        """The same correction in wall-clock time, which is rate-independent."""
        delta = self.frame_delta
        if delta is None:
            return None
        return round(delta / self.frame_rate * 1000, 1)
