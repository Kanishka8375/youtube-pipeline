"""The QC scoring contract, including the inconsistencies it was written to fix."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.enums import QCDecision, QCStage
from app.schemas.master_qc_report import (
    ANIME_STYLE_CATEGORIES,
    CATEGORY_WEIGHTS,
    PUBLISH_SCORE_THRESHOLD,
    MasterQCReport,
    SceneEditorQCNote,
    readiness_tier,
)
from tests.conftest import qc_report


def test_weights_sum_to_one_hundred():
    assert sum(CATEGORY_WEIGHTS.values()) == 100


def test_anime_style_categories_are_all_real_categories():
    assert set(ANIME_STYLE_CATEGORIES) <= set(CATEGORY_WEIGHTS)


@pytest.mark.parametrize("score,expected", [(0, 0), (5, 50), (10, 100)])
def test_uniform_scores_roll_up_linearly(score, expected):
    report = qc_report(score=score)
    assert report.overall_score == expected
    assert report.anime_style_score == expected


def test_overall_score_is_recomputed_not_trusted():
    # An agent claiming a passing total alongside failing sections must not
    # be able to open the gate.
    report = qc_report(score=3, overall_score=99, anime_style_score=99, publish_ready=True)
    assert report.overall_score == 30
    assert report.anime_style_score == 30
    assert report.publish_ready is False


def test_section_scores_are_capped_at_ten():
    with pytest.raises(ValidationError):
        qc_report(sections={"audio_mix": {"score": 11}})


def test_weighted_total_reflects_category_weight():
    # Emotion carries weight 12; dropping it to 0 from a perfect board costs
    # exactly 12 points, which is what "weighted" has to mean.
    perfect = qc_report(score=10)
    without_emotion = qc_report(score=10, sections={"emotion": {"score": 0}})
    assert perfect.overall_score - without_emotion.overall_score == CATEGORY_WEIGHTS["emotion"]


def test_anime_style_score_ignores_story_categories():
    # Story logic is not an edit-feel category, so tanking it must not move
    # the anime style score at all.
    baseline = qc_report(score=8)
    story_tanked = qc_report(score=8, sections={"story_logic": {"score": 0}})
    assert story_tanked.anime_style_score == baseline.anime_style_score
    assert story_tanked.overall_score < baseline.overall_score


def test_section_required_fixes_are_folded_into_the_publish_blocker_list():
    # A mandatory fix recorded only inside a category still has to block.
    report = qc_report(
        score=10, sections={"music": {"score": 10, "required_fixes": ["Delay cue by 1.2s"]}}
    )
    assert "Delay cue by 1.2s" in report.required_fixes_before_publish
    assert report.publish_ready is False


def test_publish_ready_requires_score_fixes_and_final_cut_stage():
    assert qc_report(score=9).publish_ready is True

    below = qc_report(score=8)
    assert below.overall_score == 80 < PUBLISH_SCORE_THRESHOLD
    assert below.publish_ready is False

    assert qc_report(score=10, critical_issues=["music cue"]).publish_ready is False
    assert qc_report(score=10, required_fixes_before_publish=["retime"]).publish_ready is False
    # Only a final-cut review can clear an episode for release.
    assert qc_report(score=10, stage="rough_cut").publish_ready is False


def test_final_decision_derives_from_score():
    assert qc_report(score=10).final_decision is QCDecision.pass_
    assert qc_report(score=8).final_decision is QCDecision.pass_with_revisions
    assert qc_report(score=5).final_decision is QCDecision.reject


def test_explicit_final_decision_is_preserved():
    report = qc_report(score=10, final_decision="reject")
    assert report.final_decision is QCDecision.reject


@pytest.mark.parametrize(
    "score,tier",
    [(95, "Premium Ready"), (85, "Publishable"), (70, "Revision Recommended"), (10, "Do Not Publish")],
)
def test_readiness_tiers(score, tier):
    assert readiness_tier(score) == tier


def test_weakest_categories_are_reported_worst_first():
    report = qc_report(
        score=9, sections={"music": {"score": 2}, "editing_rhythm": {"score": 4}}
    )
    weakest = report.sections.weakest_categories(limit=2)
    assert weakest[0] == "music"
    assert weakest[1] == "editing_rhythm"


def test_report_rejects_unknown_categories():
    with pytest.raises(ValidationError):
        MasterQCReport.model_validate(
            {
                "master_qc_report_id": "x",
                "episode_id": "EP01",
                "qc_stage": QCStage.final_cut,
                "sections": {
                    **{name: {"score": 5} for name in CATEGORY_WEIGHTS},
                    "vibes": {"score": 5},
                },
            }
        )


def test_frame_notes_convert_to_rate_independent_milliseconds():
    # The source checklist quoted fixes in frames with no stated frame rate,
    # which makes the same note mean different durations per project.
    at24 = SceneEditorQCNote(
        qc_note_id="n1", episode_id="EP01", scene_id="EP01_SC03", frame_rate=24,
        issue_type="reaction_timing", issue="cut away too early",
        current_duration_frames=5, recommended_duration_frames=14,
    )
    at30 = at24.model_copy(update={"frame_rate": 30})

    assert at24.frame_delta == at30.frame_delta == 9
    assert at24.delta_milliseconds == 375.0
    assert at30.delta_milliseconds == 300.0


def test_frame_rate_must_be_positive():
    with pytest.raises(ValidationError):
        SceneEditorQCNote(
            qc_note_id="n1", episode_id="EP01", scene_id="s", frame_rate=0,
            issue_type="pacing", issue="x",
        )
