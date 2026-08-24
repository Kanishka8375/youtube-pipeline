"""Media provider behaviour, pinned against a fake transport.

Nothing here reaches the network. The live check against the real service is
`scripts/muapi_live_check.py`, which is deliberately not a test: it costs money
and needs a key, and a test suite that sometimes spends money is a test suite
people stop running.
"""

from __future__ import annotations

import json

import pytest

from app.services.generation.providers.media_base import (
    IMAGE,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    VIDEO,
    MediaGenerationFailedError,
    ProviderCallError,
    ProviderNotConfiguredError,
)
from app.services.generation.providers.media_registry import (
    MockMediaProvider,
    MediaProviderResolver,
    UnknownMediaProviderError,
    available_media_providers,
    build_media_provider,
)
from app.services.generation.providers.muapi import InvalidModelError, MuApiProvider


class FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self.text = payload if isinstance(payload, str) else json.dumps(payload)


class FakeTransport:
    """Records requests and replays queued responses."""

    def __init__(self, post=None, get=None) -> None:
        self._post = list(post or [])
        self._get = list(get or [])
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    def post(self, url, *, headers=None, json=None, timeout=None):  # noqa: A002
        self.posts.append({"url": url, "headers": headers, "json": json})
        if not self._post:
            raise AssertionError(f"unexpected POST {url}")
        response = self._post.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, *, headers=None, timeout=None):
        self.gets.append({"url": url, "headers": headers})
        if not self._get:
            raise AssertionError(f"unexpected GET {url}")
        response = self._get.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def provider(transport, **kwargs) -> MuApiProvider:
    kwargs.setdefault("api_key", "test-key")
    kwargs.setdefault("default_model", "some-image-model")
    return MuApiProvider(transport=transport, **kwargs)


# -- submit ------------------------------------------------------------------


def test_submit_posts_the_model_as_the_path_and_returns_the_request_id():
    transport = FakeTransport(post=[FakeResponse(200, {"request_id": "req-1"})])
    submission = provider(transport).submit(prompt="a lighthouse", kind=IMAGE)

    assert submission.request_id == "req-1"
    assert transport.posts[0]["url"] == "https://api.muapi.ai/api/v1/some-image-model"
    assert transport.posts[0]["headers"]["x-api-key"] == "test-key"


def test_extra_params_pass_straight_through():
    """Model-specific arguments must not need this adapter to know about them."""
    transport = FakeTransport(post=[FakeResponse(200, {"request_id": "req-2"})])
    provider(transport).submit(
        prompt="a chase", kind=VIDEO, model="some-video-model",
        resolution="720p", aspect_ratio="16:9",
    )

    body = transport.posts[0]["json"]
    assert body == {"prompt": "a chase", "resolution": "720p", "aspect_ratio": "16:9"}


def test_a_model_name_cannot_escape_its_path_segment():
    """The model is interpolated into a URL, so traversal must be refused."""
    transport = FakeTransport()
    for hostile in ["../admin", "a/b", "model?x=1", "model#frag", "mo del", "-lead"]:
        with pytest.raises(InvalidModelError):
            provider(transport).submit(prompt="x", model=hostile)
    assert transport.posts == []


def test_no_model_anywhere_says_so_rather_than_calling_a_guessed_endpoint():
    """Which models exist is an account-dependent fact; guessing gives a 404."""
    bare = MuApiProvider(api_key="k", default_model="", transport=FakeTransport())
    with pytest.raises(InvalidModelError, match="No MuAPI model"):
        bare.submit(prompt="x")


def test_a_transport_bug_is_not_reported_as_an_unreachable_host():
    """A programming error must fail loudly, not burn the queue retry budget."""

    class BrokenTransport:
        def post(self, *a, **k):
            raise TypeError("wrong arguments")

    with pytest.raises(TypeError):
        provider(BrokenTransport()).submit(prompt="x")


def test_a_genuine_connection_failure_is_retryable():
    class DeadTransport:
        def post(self, *a, **k):
            raise OSError("connection refused")

    with pytest.raises(ProviderCallError, match="Could not reach"):
        provider(DeadTransport()).submit(prompt="x")


def test_submit_without_a_key_is_terminal_not_retryable():
    with pytest.raises(ProviderNotConfiguredError):
        MuApiProvider(api_key=None, default_model="m", transport=FakeTransport()).submit(
            prompt="x"
        )


def test_a_rejected_key_is_terminal():
    transport = FakeTransport(post=[FakeResponse(401, {"error": "bad key"})])
    with pytest.raises(ProviderNotConfiguredError):
        provider(transport).submit(prompt="x")


def test_insufficient_credit_is_terminal():
    """Retrying does not conjure credit; it just burns the budget."""
    transport = FakeTransport(post=[FakeResponse(402, {"error": "no credit"})])
    with pytest.raises(ProviderNotConfiguredError):
        provider(transport).submit(prompt="x")


def test_a_server_error_is_retryable():
    transport = FakeTransport(post=[FakeResponse(503, "upstream busy")])
    with pytest.raises(ProviderCallError):
        provider(transport).submit(prompt="x")


def test_rate_limiting_is_retryable():
    transport = FakeTransport(post=[FakeResponse(429, {"error": "slow down"})])
    with pytest.raises(ProviderCallError):
        provider(transport).submit(prompt="x")


def test_an_unknown_endpoint_names_the_model_rather_than_looking_like_a_bug():
    transport = FakeTransport(post=[FakeResponse(404, "not found")])
    with pytest.raises(InvalidModelError, match="model name"):
        provider(transport).submit(prompt="x")


def test_accepting_the_job_without_a_request_id_is_a_call_error():
    transport = FakeTransport(post=[FakeResponse(200, {"ok": True})])
    with pytest.raises(ProviderCallError, match="no request_id"):
        provider(transport).submit(prompt="x")


def test_a_non_json_body_is_reported_as_such():
    transport = FakeTransport(post=[FakeResponse(200, "<html>gateway</html>")])
    with pytest.raises(ProviderCallError, match="non-JSON"):
        provider(transport).submit(prompt="x")


# -- poll --------------------------------------------------------------------


def test_poll_maps_processing_to_pending():
    transport = FakeTransport(get=[FakeResponse(200, {"status": "processing"})])
    result = provider(transport).poll("req-1")

    assert result.status == STATUS_PENDING
    assert result.outputs == []
    assert not result.is_terminal
    assert transport.gets[0]["url"].endswith("/predictions/req-1/result")


@pytest.mark.parametrize("spelling", ["completed", "succeeded", "SUCCESS"])
def test_every_success_spelling_means_completed(spelling):
    transport = FakeTransport(
        get=[FakeResponse(200, {"status": spelling, "outputs": ["https://cdn/x.png"]})]
    )
    assert provider(transport).poll("req-1").status == STATUS_COMPLETED


def test_an_unknown_status_is_pending_not_success():
    """Guessing 'done' from an unrecognised word hands back an empty result."""
    transport = FakeTransport(get=[FakeResponse(200, {"status": "recalibrating"})])
    assert provider(transport).poll("req-1").status == STATUS_PENDING


def test_completed_with_no_outputs_is_an_error_not_an_empty_success():
    transport = FakeTransport(get=[FakeResponse(200, {"status": "completed", "outputs": []})])
    with pytest.raises(ProviderCallError, match="no outputs"):
        provider(transport).poll("req-1")


@pytest.mark.parametrize(
    "outputs,expected",
    [
        (["https://cdn/a.png"], ["https://cdn/a.png"]),
        ("https://cdn/a.png", ["https://cdn/a.png"]),
        ([{"url": "https://cdn/a.png"}], ["https://cdn/a.png"]),
        ([{"uri": "https://cdn/a.mp4"}], ["https://cdn/a.mp4"]),
    ],
)
def test_output_shapes_are_normalised(outputs, expected):
    """Shapes differ per model; callers must not have to know that."""
    transport = FakeTransport(get=[FakeResponse(200, {"status": "completed", "outputs": outputs})])
    assert provider(transport).poll("req-1").outputs == expected


def test_cost_is_captured():
    transport = FakeTransport(
        get=[
            FakeResponse(
                200,
                {
                    "status": "completed",
                    "outputs": ["https://cdn/a.png"],
                    "cost": {"amount_usd": 0.042, "amount_credits": 42},
                },
            )
        ]
    )
    assert provider(transport).poll("req-1").cost_usd == pytest.approx(0.042)


def test_an_unreported_cost_is_none_not_zero():
    """'Not reported' and 'free' are different facts about a paid call."""
    transport = FakeTransport(
        get=[FakeResponse(200, {"status": "completed", "outputs": ["https://cdn/a.png"]})]
    )
    assert provider(transport).poll("req-1").cost_usd is None


def test_a_failed_job_carries_its_reason():
    transport = FakeTransport(
        get=[FakeResponse(200, {"status": "failed", "error": "content policy"})]
    )
    result = provider(transport).poll("req-1")

    assert result.status == STATUS_FAILED
    assert result.is_terminal
    assert result.error == "content policy"


# -- generate (submit + wait) ------------------------------------------------


def test_generate_polls_until_completion():
    transport = FakeTransport(
        post=[FakeResponse(200, {"request_id": "req-1"})],
        get=[
            FakeResponse(200, {"status": "processing"}),
            FakeResponse(200, {"status": "processing"}),
            FakeResponse(200, {"status": "completed", "outputs": ["https://cdn/a.png"]}),
        ],
    )
    slept: list[float] = []
    result = provider(transport).generate(
        prompt="a lighthouse", poll_interval_seconds=0.5, sleep=slept.append
    )

    assert result.outputs == ["https://cdn/a.png"]
    assert len(transport.gets) == 3
    assert slept == [0.5, 0.5]


def test_generate_raises_terminally_when_the_provider_reports_failure():
    """A retry re-runs a paid generation, so this must not look retryable."""
    transport = FakeTransport(
        post=[FakeResponse(200, {"request_id": "req-1"})],
        get=[FakeResponse(200, {"status": "failed", "error": "content policy"})],
    )
    with pytest.raises(MediaGenerationFailedError, match="content policy"):
        provider(transport).generate(prompt="x", sleep=lambda _: None)


def test_generate_gives_up_rather_than_hanging_forever():
    transport = FakeTransport(
        post=[FakeResponse(200, {"request_id": "req-1"})],
        get=[FakeResponse(200, {"status": "processing"})] * 50,
    )
    with pytest.raises(ProviderCallError, match="poll it by id"):
        provider(transport).generate(
            prompt="x", timeout_seconds=0.0, poll_interval_seconds=0, sleep=lambda _: None
        )


# -- registry ----------------------------------------------------------------


def test_the_mock_provider_needs_nothing_and_completes_immediately():
    mock = MockMediaProvider()
    submission = mock.submit(prompt="a lighthouse", kind=IMAGE)
    result = mock.poll(submission.request_id)

    assert mock.is_configured()
    assert result.status == STATUS_COMPLETED
    assert result.outputs[0].endswith(".png")


def test_the_mock_is_deterministic():
    a = MockMediaProvider().submit(prompt="same", kind=IMAGE)
    b = MockMediaProvider().submit(prompt="same", kind=IMAGE)
    assert a.request_id == b.request_id


def test_muapi_is_listed_and_reports_whether_it_is_configured(monkeypatch):
    monkeypatch.delenv("MUAPI_API_KEY", raising=False)
    monkeypatch.delenv("ANIME_MUAPI_API_KEY", raising=False)
    listed = available_media_providers()

    assert listed["muapi"]["configured"] is False
    assert listed["mock"]["configured"] is True
    assert set(listed["muapi"]["kinds"]) == {"image", "video", "audio"}

    monkeypatch.setenv("MUAPI_API_KEY", "k")
    assert available_media_providers()["muapi"]["configured"] is True


def test_an_unknown_provider_key_names_the_known_ones():
    with pytest.raises(UnknownMediaProviderError, match="mock"):
        build_media_provider("nope")


def test_resolution_falls_back_to_the_mock_so_a_bare_deployment_still_runs():
    resolver = MediaProviderResolver(session=None)
    chosen, model = resolver.resolve(kind=IMAGE)

    assert chosen.provider_key == "mock"
    assert model == "mock-media-v1"


def test_resolving_an_unconfigured_provider_fails_before_anything_is_queued(monkeypatch):
    monkeypatch.delenv("MUAPI_API_KEY", raising=False)
    monkeypatch.delenv("ANIME_MUAPI_API_KEY", raising=False)
    with pytest.raises(ProviderNotConfiguredError):
        MediaProviderResolver().resolve(provider_key="muapi", kind=IMAGE)
