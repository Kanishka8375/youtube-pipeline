"""Read-only views of the pipeline graph itself."""

from __future__ import annotations

from fastapi import APIRouter

from app.agents.registry import AGENTS
from app.schemas.master_qc_report import CATEGORY_WEIGHTS, PUBLISH_SCORE_THRESHOLD
from app.services.orchestrator import PIPELINE, pipeline_mermaid

router = APIRouter()


@router.get("/stages")
def list_stages():
    return [
        {
            "name": stage.name,
            "agent": stage.agent_code,
            "task_type": stage.task_type,
            "category": stage.task_category.value,
            "output_schema": stage.output_schema,
            "depends_on": list(stage.depends_on),
            "approval_required": stage.approval_required,
            "qc_gate": stage.qc_gate.value if stage.qc_gate else None,
            "parallel_group": stage.parallel_group,
        }
        for stage in PIPELINE
    ]


@router.get("/agents")
def list_agents():
    return [
        {
            "agent_code": spec.agent_code,
            "display_name": spec.display_name,
            "role": spec.role_description,
        }
        for spec in AGENTS
    ]


@router.get("/qc-model")
def qc_model():
    return {
        "category_weights": CATEGORY_WEIGHTS,
        "section_score_range": [0, 10],
        "publish_score_threshold": PUBLISH_SCORE_THRESHOLD,
    }


@router.get("/diagram")
def diagram():
    return {"format": "mermaid", "source": pipeline_mermaid()}
