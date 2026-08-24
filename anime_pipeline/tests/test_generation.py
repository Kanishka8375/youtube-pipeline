"""Prompt templates, provider selection, and canon-bound generation."""

from __future__ import annotations

import pytest

from app.services.generation.prompts.templates import (
    TEMPLATES,
    MissingTemplateVariableError,
    UnknownTemplateError,
    get_template,
    list_templates,
)
from app.services.generation.providers.anthropic_provider import (
    DEFAULT_MODEL,
    AnthropicProvider,
)
from app.services.generation.providers.base import ProviderNotConfiguredError
from app.services.generation.providers.mock import MockTextProvider
from app.services.generation.providers.registry import (
    ProviderResolver,
    UnknownProviderError,
    available_providers,
    build_provider,
)
from tests.test_auth_and_workspaces import signed_in
from tests.test_canon_enforcement import add_entity
from tests.test_memory import SERIES, add_style_bible
from tests.test_workflow_persistence import make_episode


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
def test_every_template_declares_the_variables_it_uses():
    # A template whose body references a variable it never declares renders to
    # text containing a literal `{canon_constraints}`, which a model reads as
    # part of the brief.
    for key, template in TEMPLATES.items():
        assert template.required_variables(), f"{key} has no variables"
        assert template.purpose, f"{key} has no stated purpose"


def test_rendering_without_a_variable_raises_rather_than_leaking_a_placeholder():
    with pytest.raises(MissingTemplateVariableError, match="episode_title"):
        get_template("episode_script_v1").render({"series_title": "X"})


def test_an_unknown_template_names_the_ones_that_exist():
    with pytest.raises(UnknownTemplateError, match="episode_script_v1"):
        get_template("no_such_template")


def test_the_canon_discipline_system_prompt_is_attached_to_writing_templates():
    # The instruction not to invent world-facts is the whole reason generation
    # and the continuity engine can coexist.
    for key in ("episode_script_v1", "episode_outline_v1"):
        assert "canon" in get_template(key).system.lower()


def test_templates_are_listable_for_review():
    listed = {t["key"] for t in list_templates()}
    assert listed == set(TEMPLATES)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
def test_the_mock_provider_needs_no_credentials_and_is_deterministic():
    provider = MockTextProvider()
    assert provider.is_configured()
    first = provider.generate(prompt="Write EP01")
    second = provider.generate(prompt="Write EP01")
    # Determinism is what lets the adversarial suite use it as a fixture.
    assert first.text == second.text
    assert provider.generate(prompt="Different").text != first.text


def test_the_anthropic_provider_defaults_to_the_current_model():
    # Pinned: a stale model id from training data (claude-3-5-sonnet-latest and
    # friends) is the single most likely thing to be wrong here.
    assert DEFAULT_MODEL == "claude-opus-5"
    assert AnthropicProvider().default_model == DEFAULT_MODEL


def test_an_unconfigured_provider_reports_itself_as_such(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    assert AnthropicProvider().is_configured() is False


def test_every_registered_provider_reports_configuration_status():
    for key, info in available_providers().items():
        assert info["provider_key"] == key
        assert isinstance(info["configured"], bool)


def test_an_unknown_provider_key_names_the_known_ones():
    with pytest.raises(UnknownProviderError, match="mock"):
        build_provider("telepathy")


def test_resolution_falls_back_to_the_mock_when_nothing_is_configured():
    # A deployment with no keys still runs. It produces obviously-fake text
    # rather than failing at import, which is what keeps tests runnable.
    provider, model = ProviderResolver().resolve()
    assert provider.provider_key == "mock"
    assert model == MockTextProvider.default_model


def test_resolution_refuses_a_provider_with_no_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    with pytest.raises(ProviderNotConfiguredError, match="anthropic"):
        ProviderResolver().resolve(provider_key="anthropic")


# ---------------------------------------------------------------------------
# Canon binding -- the point of the whole layer
# ---------------------------------------------------------------------------
def seed_canon(client):
    make_episode(client)
    add_entity(client)
    add_style_bible(client)
    client.post(
        "/memory/documents",
        json={
            "memory_code": "GEN_CANON",
            "memory_type": "episode_memory",
            "episode_code": "EP01",
            "title": "canon",
        },
    )
    client.post(
        "/canon/writeback",
        json={
            "episode_code": "EP01",
            "memory_code": "GEN_CANON",
            "output_type": "script",
            "payload": {
                "canon_facts": [
                    {
                        "fact_type": "canon",
                        "entity_type": "character",
                        "entity_key": "MIRA",
                        "fact_key": "species",
                        "fact_value": "human",
                        "mutability": "immutable",
                        "importance": "critical",
                    }
                ]
            },
        },
    )


def test_established_canon_reaches_the_prompt(client):
    # Without this the generator invents freely and the enforcement gates then
    # reject what it produced -- wasting the call and tempting a human to
    # approve it anyway.
    headers = signed_in(client, "gen@studio.example")
    seed_canon(client)
    body = client.post(
        "/generation/preview",
        json={"template_key": "episode_script_v1", "episode_code": "EP01"},
        headers=headers,
    ).json()

    assert "Mira Kisaragi.species" in body["prompt"]
    assert "human" in body["prompt"]
    assert "(fixed)" in body["prompt"], "immutability must be visible to the model"


def test_the_style_bible_reaches_the_prompt(client):
    headers = signed_in(client, "gen2@studio.example")
    seed_canon(client)
    body = client.post(
        "/generation/preview",
        json={"template_key": "episode_script_v1", "episode_code": "EP01"},
        headers=headers,
    ).json()
    assert "NEVER: no comedy smash cuts" in body["prompt"]


def test_a_series_with_no_canon_says_so_rather_than_rendering_an_empty_block(client):
    headers = signed_in(client, "gen3@studio.example")
    make_episode(client)
    body = client.post(
        "/generation/preview",
        json={"template_key": "episode_script_v1", "episode_code": "EP01"},
        headers=headers,
    ).json()
    assert "No canon has been recorded" in body["prompt"]
    assert "becomes binding on every later episode" in body["prompt"]


def test_preview_calls_no_provider(client):
    # The cheapest way to review a prompt change: no tokens, no latency, and
    # the canon block is the real one.
    headers = signed_in(client, "gen4@studio.example")
    seed_canon(client)
    body = client.post(
        "/generation/preview",
        json={"template_key": "episode_script_v1", "episode_code": "EP01"},
        headers=headers,
    ).json()
    assert set(body) == {"template_key", "system", "prompt", "prompt_chars"}


def test_the_providers_endpoint_lists_text_and_media_separately(client):
    # They are chosen separately -- a deployment can run a real LLM behind a
    # mock image generator -- so one merged list would hide the difference.
    headers = signed_in(client, "gen5@studio.example")
    body = client.get("/generation/providers", headers=headers).json()

    assert set(body) == {"providers", "media_providers"}
    assert "anthropic" in body["providers"]
    assert "muapi" in body["media_providers"]
    assert body["media_providers"]["mock"]["configured"] is True
    assert set(body["media_providers"]["muapi"]["kinds"]) == {"image", "video", "audio"}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def test_an_inline_generation_persists_an_artifact_with_its_provenance(client):
    headers = signed_in(client, "gen5@studio.example")
    seed_canon(client)
    body = client.post(
        "/generation/run",
        json={
            "template_key": "episode_script_v1",
            "episode_code": "EP01",
            "provider_key": "mock",
            "background": False,
        },
        headers=headers,
    ).json()

    assert body["mode"] == "inline"
    assert body["provider"] == "mock"
    # Provenance: when an episode turns out to contradict canon later, the
    # first question is which model and prompt wrote it.
    assert body["artifact_id"]
    assert body["template_key"] == "episode_script_v1"


def test_regenerating_creates_a_new_artifact_rather_than_overwriting(client):
    headers = signed_in(client, "gen6@studio.example")
    seed_canon(client)
    payload = {
        "template_key": "episode_script_v1",
        "episode_code": "EP01",
        "provider_key": "mock",
        "background": False,
    }
    first = client.post("/generation/run", json=payload, headers=headers).json()
    second = client.post("/generation/run", json=payload, headers=headers).json()
    # The previous version stays reviewable.
    assert first["artifact_id"] != second["artifact_id"]


def test_a_missing_api_key_fails_on_the_request_not_as_a_job(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    headers = signed_in(client, "gen7@studio.example")
    seed_canon(client)
    response = client.post(
        "/generation/run",
        json={
            "template_key": "episode_script_v1",
            "episode_code": "EP01",
            "provider_key": "anthropic",
            "background": True,
        },
        headers=headers,
    )
    # 400, not a queued job that fails its whole retry budget overnight.
    assert response.status_code == 400
    assert "credentials" in response.json()["detail"]


def test_a_queued_generation_runs_and_records_its_result(client):
    headers = signed_in(client, "gen8@studio.example")
    seed_canon(client)
    queued = client.post(
        "/generation/run",
        json={
            "template_key": "episode_outline_v1",
            "episode_code": "EP01",
            "provider_key": "mock",
            "background": True,
        },
        headers=headers,
    ).json()
    assert queued["mode"] == "queued"

    drained = client.post("/jobs/drain", json={"max_jobs": 5}, headers=headers).json()
    assert drained["ran"] == 1
    assert drained["outcomes"][0]["status"] == "completed"

    job = client.get(f"/jobs/{queued['job_id']}", headers=headers).json()
    assert job["status"] == "completed"
    assert job["result"]["provider"] == "mock"


def test_generation_endpoints_require_a_token(client):
    assert client.post("/generation/run", json={"template_key": "x", "episode_code": "EP01"}).status_code == 401
    assert client.post("/generation/preview", json={"template_key": "x", "episode_code": "EP01"}).status_code == 401
    # Listing what exists is not sensitive; running it is.
    assert client.get("/generation/templates").status_code == 200
