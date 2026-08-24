"""Agent execution, schema enforcement and the single repair retry."""

from __future__ import annotations

import pytest

from app.agents.registry import AGENTS, AgentRegistry, UnknownAgentError
from app.models.task import TaskEnvelope
from app.services.agent_runner import AgentRunner
from app.services.provider_router import (
    ProviderNotConfiguredError,
    ProviderRouter,
    StubLLMProvider,
)

VALID_BEAT_SHEET = {
    "beat_sheet_id": "beats_EP01_v1",
    "episode_id": "EP01",
    "logline": "A rogue listener detects a dead child's memory signal.",
    "beats": [{"beat_no": 1, "name": "Cold Open", "purpose": "hook", "summary": "A voice."}],
    "short_candidates": ["distorted voice"],
}


def make_task(schema_name: str = "beat_sheet_v1") -> TaskEnvelope:
    return TaskEnvelope(
        task_id="tsk_EP01_STORY_001",
        episode_id="EP01",
        task_type="create_beat_sheet",
        task_category="story",
        created_by={"id": "executive_showrunner_agent"},
        assigned_to={"id": "episode_story_agent"},
        instructions={"goal": "Write the beat sheet."},
        output_spec={"schema_name": schema_name},
    )


class SequenceProvider:
    """Returns each queued response in turn."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    def generate(self, system_prompt, user_payload):
        self.payloads.append(user_payload)
        return self.responses.pop(0)


def test_all_thirteen_agents_have_a_prompt_file():
    registry = AgentRegistry()
    assert len(AGENTS) == 13
    for spec in AGENTS:
        assert registry.system_prompt(spec.agent_code).strip()


def test_unknown_agent_raises_a_useful_error():
    with pytest.raises(UnknownAgentError, match="Unknown agent"):
        AgentRegistry().get("nonexistent_agent")


def test_valid_output_is_returned_as_a_validated_model():
    router = ProviderRouter(llm=StubLLMProvider(VALID_BEAT_SHEET))
    result = AgentRunner(router).run(make_task())

    assert result.ok is True
    assert result.attempts == 1
    assert result.output.logline.startswith("A rogue listener")


def test_the_prompt_sent_to_the_provider_is_the_assigned_agents_prompt():
    provider = StubLLMProvider(VALID_BEAT_SHEET)
    AgentRunner(ProviderRouter(llm=provider)).run(make_task())

    system_prompt, payload = provider.calls[0]
    assert "You are the Episode Story Agent." in system_prompt
    assert payload["expected_schema"] == "beat_sheet_v1"


def test_a_schema_failure_is_retried_once_with_the_error_fed_back():
    provider = SequenceProvider([{"beat_sheet_id": "b"}, VALID_BEAT_SHEET])
    result = AgentRunner(ProviderRouter(llm=provider)).run(make_task())

    assert result.ok is True
    assert result.attempts == 2
    repair = provider.payloads[1]["repair_request"]
    assert "validation_error" in repair
    assert repair["previous_output"] == {"beat_sheet_id": "b"}


def test_a_second_schema_failure_gives_up_instead_of_looping():
    provider = SequenceProvider([{"bad": 1}, {"still_bad": 2}])
    result = AgentRunner(ProviderRouter(llm=provider)).run(make_task())

    assert result.ok is False
    assert result.attempts == 2
    assert result.error
    assert not provider.responses  # exactly two calls, no third


def test_an_unconfigured_provider_fails_loudly():
    with pytest.raises(ProviderNotConfiguredError):
        AgentRunner(ProviderRouter()).run(make_task())


def test_a_task_cannot_name_an_unknown_output_schema():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_task(schema_name="does_not_exist_v1")
