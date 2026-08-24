"""Master QC reports and the publish gate they guard."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.api.routes.episodes import resolve_episode
from app.db.models import (
    Agent,
    ContinuityCheck,
    MasterQCReport as MasterQCReportRow,
)
from app.models.enums import QCStage
from app.schemas.master_qc_report import PUBLISH_SCORE_THRESHOLD, MasterQCReport

router = APIRouter()


def _to_schema(row: MasterQCReportRow) -> MasterQCReport:
    # Re-validating on read recomputes the derived fields, so a report whose
    # stored score was tampered with in the database is corrected on the way
    # out rather than silently trusted.
    return MasterQCReport.model_validate(
        {
            "master_qc_report_id": row.master_qc_report_id,
            "episode_id": row.episode.episode_code,
            "qc_stage": row.qc_stage,
            "qc_type": row.qc_type,
            "status": row.status,
            "sections": row.sections,
            "critical_issues": row.critical_issues,
            "required_fixes_before_publish": row.required_fixes_before_publish,
            "optional_polish_suggestions": row.optional_polish_suggestions,
            "final_notes": row.final_notes,
        }
    )


@router.post("/", response_model=MasterQCReport, status_code=status.HTTP_201_CREATED)
def create_qc_report(report: MasterQCReport, session: Session = Depends(db_session)):
    episode = resolve_episode(session, report.episode_id)

    existing = session.scalar(
        select(MasterQCReportRow).where(
            MasterQCReportRow.master_qc_report_id == report.master_qc_report_id
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"QC report {report.master_qc_report_id!r} already exists",
        )

    reviewer = session.scalar(
        select(Agent).where(Agent.agent_code == "master_anime_qc_agent")
    )
    row = MasterQCReportRow(
        master_qc_report_id=report.master_qc_report_id,
        episode_id=episode.id,
        reviewer_agent_id=reviewer.id if reviewer else None,
        qc_stage=report.qc_stage,
        qc_type=report.qc_type,
        status=report.status,
        overall_score=report.overall_score,
        anime_style_score=report.anime_style_score,
        publish_ready=report.publish_ready,
        critical_issues=report.critical_issues,
        required_fixes_before_publish=report.required_fixes_before_publish,
        optional_polish_suggestions=report.optional_polish_suggestions,
        final_notes=report.final_notes,
        sections=report.sections.model_dump(),
        final_decision=report.final_decision,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return report


@router.get("/episode/{episode_code}", response_model=List[MasterQCReport])
def list_episode_qc_reports(episode_code: str, session: Session = Depends(db_session)):
    episode = resolve_episode(session, episode_code)
    rows = session.scalars(
        select(MasterQCReportRow)
        .where(MasterQCReportRow.episode_id == episode.id)
        .order_by(MasterQCReportRow.created_at)
    ).all()
    return [_to_schema(row) for row in rows]


@router.get("/episode/{episode_code}/publish-gate")
def publish_gate(episode_code: str, session: Session = Depends(db_session)):
    """Whether the latest final-cut QC report clears the episode for release."""
    episode = resolve_episode(session, episode_code)
    row = session.scalars(
        select(MasterQCReportRow)
        .where(
            MasterQCReportRow.episode_id == episode.id,
            MasterQCReportRow.qc_stage == QCStage.final_cut,
        )
        .order_by(MasterQCReportRow.created_at.desc())
    ).first()

    # A passing continuity check is required alongside the QC score: an episode
    # can be beautifully made and still contradict canon.
    continuity_passed = session.scalar(
        select(ContinuityCheck)
        .where(
            ContinuityCheck.episode_id == episode.id,
            ContinuityCheck.passed.is_(True),
        )
        .order_by(ContinuityCheck.created_at.desc())
    ) is not None

    if row is None:
        reasons = ["no final_cut master QC report"]
        if not continuity_passed:
            reasons.append("no passing continuity check")
        return {
            "episode_id": episode_code,
            "publish_ready": False,
            "checks": {
                "qc_score_ok": False,
                "mandatory_fixes_closed": False,
                "no_critical_issues": False,
                "continuity_passed": continuity_passed,
            },
            "reasons": reasons,
        }

    report = _to_schema(row)
    reasons: List[str] = []
    score_ok = report.overall_score >= PUBLISH_SCORE_THRESHOLD
    if not score_ok:
        reasons.append(
            f"overall score {report.overall_score} is below the threshold of "
            f"{PUBLISH_SCORE_THRESHOLD}"
        )
    if report.required_fixes_before_publish:
        reasons.append(
            f"{len(report.required_fixes_before_publish)} mandatory fix(es) outstanding"
        )
    if report.critical_issues:
        reasons.append(f"{len(report.critical_issues)} critical issue(s) outstanding")
    if not continuity_passed:
        reasons.append("no passing continuity check")

    return {
        "episode_id": episode_code,
        # report.publish_ready is recomputed from the sections, never read from
        # the stored column; continuity is the one gate it does not cover.
        "publish_ready": report.publish_ready and continuity_passed,
        "overall_score": report.overall_score,
        "anime_style_score": report.anime_style_score,
        "readiness": report.readiness,
        "final_decision": report.final_decision.value if report.final_decision else None,
        "weakest_categories": report.sections.weakest_categories(),
        "checks": {
            "qc_score_ok": score_ok,
            "mandatory_fixes_closed": not report.required_fixes_before_publish,
            "no_critical_issues": not report.critical_issues,
            "continuity_passed": continuity_passed,
        },
        "reasons": reasons,
    }


@router.get("/{master_qc_report_id}", response_model=MasterQCReport)
def get_qc_report(master_qc_report_id: str, session: Session = Depends(db_session)):
    row = session.scalar(
        select(MasterQCReportRow).where(
            MasterQCReportRow.master_qc_report_id == master_qc_report_id
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="QC report not found")
    return _to_schema(row)
