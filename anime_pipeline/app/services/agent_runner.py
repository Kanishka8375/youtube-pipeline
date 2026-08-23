"""Runs one agent against one task and validates what comes back."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pydantic import BaseModel, ValidationError

from app.agents.registry import AgentRegistry
from app.models.task import TaskEnvelope
from app.schemas.registry import get_schema
from app.services.provider_router import ProviderRouter


@dataclass
class AgentRunResult:
    task_id: str
    agent_code: str
    ok: bool
    output: Optional[BaseModel] = None
    raw_output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    attempts: int = 1


class AgentRunner:
    """Executes an agent, validates its output, and retries once on a schema error.

    The single repair retry matches the spec's Rule 3: a schema failure is
    retried once with the validation error fed back to the agent, and a second
    failure escalates rather than looping.
    """

    def __init__(
        self,
        provider_router: ProviderRouter,
        registry: Optional[AgentRegistry] = None,
        max_schema_repairs: int = 1,
    ) -> None:
        self.provider_router = provider_router
        self.registry = registry or AgentRegistry()
        self.max_schema_repairs = max_schema_repairs

    def run(self, task: TaskEnvelope) -> AgentRunResult:
        agent_code = task.assigned_to.id
        system_prompt = self.registry.system_prompt(agent_code)
        schema = get_schema(task.output_spec.schema_name)

        payload = {
            "task": task.model_dump(mode="json"),
            "input_context": task.input_context,
            "instructions": task.instructions.model_dump(),
            "expected_schema": task.output_spec.schema_name,
        }

        last_error: Optional[str] = None
        raw: Dict[str, Any] = {}
        for attempt in range(1, self.max_schema_repairs + 2):
            if last_error is not None:
                payload = {
                    **payload,
                    "repair_request": {
                        "previous_output": raw,
                        "validation_error": last_error,
                        "instruction": (
                            "Your previous response failed schema validation. "
                            "Return corrected JSON matching the expected schema exactly."
                        ),
                    },
                }
            raw = self.provider_router.call_llm(system_prompt, payload)
            try:
                validated = schema.model_validate(raw)
            except ValidationError as exc:
                last_error = str(exc)
                continue
            return AgentRunResult(
                task_id=task.task_id,
                agent_code=agent_code,
                ok=True,
                output=validated,
                raw_output=raw,
                attempts=attempt,
            )

        return AgentRunResult(
            task_id=task.task_id,
            agent_code=agent_code,
            ok=False,
            raw_output=raw,
            error=last_error,
            attempts=self.max_schema_repairs + 1,
        )
