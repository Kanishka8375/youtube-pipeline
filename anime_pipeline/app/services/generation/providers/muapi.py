"""MuAPI -- a unified endpoint in front of many image, video and audio models.

Raw HTTP, for the same reason as the OpenAI-compatible adapter: this is a
service with a small, stable REST surface, not a vendor whose SDK carries
behaviour worth inheriting.

The API is submit-then-poll:

    POST https://api.muapi.ai/api/v1/{model}      -> {"request_id": ...}
    GET  https://api.muapi.ai/api/v1/predictions/{request_id}/result
                                                  -> {"status", "outputs", "cost"}

with `x-api-key` on both.

The model *is* the path segment -- `openai-sora-2-text-to-video`,
`bytedance-seedream-v5.0-pro` and so on. That makes the model name part of a
URL, so it is validated against a strict charset before being interpolated; a
model string carrying `../` would otherwise reach an endpoint the caller never
named.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from app.services.generation.providers.media_base import (
    AUDIO,
    IMAGE,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    VIDEO,
    MediaGenerationFailedError,
    MediaProvider,
    MediaResult,
    MediaSubmission,
    ProviderCallError,
    ProviderNotConfiguredError,
    env_or_none,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.muapi.ai/api/v1"
REQUEST_TIMEOUT_SECONDS = 60.0

#: No default model. Which models exist is an account- and time-dependent fact
#: about the service; guessing one produces a 404 that reads like a bug here.
DEFAULT_MODEL = ""

#: Model names become a URL path segment, so they are restricted rather than
#: escaped -- an allowlist cannot be got wrong the way escaping can.
_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

#: The service's own status vocabulary, mapped onto ours. Several spellings
#: mean the same thing depending on the model behind the endpoint.
_STATUS_MAP = {
    "completed": STATUS_COMPLETED,
    "succeeded": STATUS_COMPLETED,
    "success": STATUS_COMPLETED,
    "failed": STATUS_FAILED,
    "error": STATUS_FAILED,
    "canceled": STATUS_FAILED,
    "cancelled": STATUS_FAILED,
    "processing": STATUS_PENDING,
    "pending": STATUS_PENDING,
    "queued": STATUS_PENDING,
    "starting": STATUS_PENDING,
    "in_progress": STATUS_PENDING,
}


class InvalidModelError(ProviderNotConfiguredError):
    """Raised when a model name could not be safely used as a path segment."""


def _network_errors() -> tuple:
    """Exception types that mean "the call did not get through".

    Deliberately narrow. A blanket `except Exception` here would catch a
    TypeError in this adapter and report it as an unreachable host -- which the
    job queue treats as *retryable*, so a programming error would quietly burn
    a retry budget three times instead of failing loudly once.
    """
    errors: List[type] = [OSError]
    try:
        import httpx

        errors.append(httpx.HTTPError)
        errors.append(httpx.InvalidURL)
    except ImportError:  # pragma: no cover -- httpx is a dependency
        pass
    return tuple(errors)


def _coerce_outputs(value: Any) -> List[str]:
    """Pull asset URLs out of whatever shape `outputs` arrived in.

    Observed shapes differ by model: a list of URL strings, a list of objects
    with a `url` key, or a bare string. Normalising here keeps every caller
    from having to know that.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        url = value.get("url") or value.get("uri")
        return [url] if isinstance(url, str) else []
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            out.extend(_coerce_outputs(item))
        return out
    return []


def _coerce_cost(payload: Dict[str, Any]) -> Optional[float]:
    """The call's price in USD, or None if the service did not say.

    None and 0.0 are different facts -- "not reported" versus "free" -- and
    flattening them would make a cost report quietly wrong.
    """
    cost = payload.get("cost")
    if not isinstance(cost, dict):
        return None
    amount = cost.get("amount_usd")
    if isinstance(amount, (int, float)):
        return float(amount)
    try:
        return float(amount)  # a string amount is still a number
    except (TypeError, ValueError):
        return None


class MuApiProvider(MediaProvider):
    provider_key = "muapi"
    default_model = DEFAULT_MODEL
    supported_kinds = (IMAGE, VIDEO, AUDIO)

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        transport: Any = None,
    ) -> None:
        self._api_key = api_key or env_or_none("MUAPI_API_KEY", "ANIME_MUAPI_API_KEY")
        self._base_url = (base_url or env_or_none("ANIME_MUAPI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.default_model = default_model or env_or_none("ANIME_MUAPI_MODEL") or DEFAULT_MODEL
        #: Injected in tests. Anything with .post/.get matching httpx's shape.
        self._transport = transport

    # -- plumbing ------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _client(self):
        if self._transport is not None:
            return self._transport
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover -- httpx is a dependency
            raise ProviderNotConfiguredError("httpx is required for this provider") from exc
        return httpx

    def _headers(self) -> Dict[str, str]:
        return {"x-api-key": self._api_key or "", "Content-Type": "application/json"}

    @staticmethod
    def _validate_model(model: str) -> str:
        if not model:
            raise InvalidModelError(
                "No MuAPI model given. The model is the endpoint path segment "
                "(e.g. 'bytedance-seedream-v5.0-pro'); set ANIME_MUAPI_MODEL "
                "or pass model=."
            )
        if not _MODEL_PATTERN.match(model):
            raise InvalidModelError(
                f"Model {model!r} is not a usable endpoint name. Expected "
                "letters, digits, dot, underscore or hyphen."
            )
        return model

    def _raise_for_status(self, status_code: int, body: str, where: str) -> None:
        if status_code in (401, 403):
            # No amount of retrying fixes a rejected key, so this is terminal.
            raise ProviderNotConfiguredError(
                f"MuAPI rejected the credentials on {where} ({status_code})."
            )
        if status_code == 404:
            raise InvalidModelError(
                f"MuAPI has no endpoint at {where} (404). Check the model name."
            )
        if status_code == 402:
            raise ProviderNotConfiguredError(
                f"MuAPI reports insufficient credit ({status_code}): {body[:300]}"
            )
        if status_code >= 400:
            # 429 and 5xx included: reachable, but the call did not work.
            raise ProviderCallError(f"MuAPI {where} returned {status_code}: {body[:400]}")

    @staticmethod
    def _decode(body: str, where: str) -> Dict[str, Any]:
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ProviderCallError(
                f"MuAPI {where} returned non-JSON: {body[:200]!r}"
            ) from exc
        if not isinstance(data, dict):
            raise ProviderCallError(f"MuAPI {where} returned {type(data).__name__}, expected an object")
        return data

    # -- the interface -------------------------------------------------------

    def submit(
        self,
        *,
        prompt: str,
        kind: str = IMAGE,
        model: Optional[str] = None,
        **params: Any,
    ) -> MediaSubmission:
        if not self.is_configured():
            raise ProviderNotConfiguredError(
                "No MuAPI key. Set MUAPI_API_KEY in the environment."
            )
        model_id = self._validate_model(model or self.default_model)

        # Model-specific arguments (resolution, aspect_ratio, duration, ...)
        # pass straight through. Enumerating them here would mean this adapter
        # needed editing every time the service added a model.
        body: Dict[str, Any] = {"prompt": prompt, **params}
        url = f"{self._base_url}/{model_id}"

        try:
            response = self._client().post(
                url, headers=self._headers(), json=body, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except _network_errors() as exc:
            raise ProviderCallError(f"Could not reach MuAPI at {url}: {exc}") from exc

        self._raise_for_status(response.status_code, response.text, f"POST /{model_id}")
        data = self._decode(response.text, f"POST /{model_id}")

        request_id = data.get("request_id") or data.get("id")
        if not isinstance(request_id, str) or not request_id:
            raise ProviderCallError(
                f"MuAPI accepted the job but returned no request_id: {list(data)}"
            )

        logger.info(
            "muapi.submit", extra={"muapi_model": model_id, "muapi_request_id": request_id}
        )
        return MediaSubmission(
            request_id=request_id, provider=self.provider_key, model=model_id, raw=data
        )

    def poll(self, request_id: str) -> MediaResult:
        if not self.is_configured():
            raise ProviderNotConfiguredError(
                "No MuAPI key. Set MUAPI_API_KEY in the environment."
            )
        url = f"{self._base_url}/predictions/{request_id}/result"

        try:
            response = self._client().get(
                url, headers=self._headers(), timeout=REQUEST_TIMEOUT_SECONDS
            )
        except _network_errors() as exc:
            raise ProviderCallError(f"Could not reach MuAPI at {url}: {exc}") from exc

        self._raise_for_status(response.status_code, response.text, "the result endpoint")
        data = self._decode(response.text, "the result endpoint")

        raw_status = str(data.get("status", "")).lower()
        # An unrecognised status is treated as pending rather than as success.
        # Guessing "done" from an unknown word would hand a caller an empty
        # output list as if it were a finished generation.
        status = _STATUS_MAP.get(raw_status, STATUS_PENDING)
        outputs = _coerce_outputs(data.get("outputs") or data.get("output"))

        if status == STATUS_COMPLETED and not outputs:
            raise ProviderCallError(
                f"MuAPI reported {raw_status!r} for {request_id} but returned no outputs"
            )

        return MediaResult(
            request_id=request_id,
            provider=self.provider_key,
            model=str(data.get("model") or self.default_model or ""),
            status=status,
            outputs=outputs,
            cost_usd=_coerce_cost(data),
            error=data.get("error") or data.get("message") if status == STATUS_FAILED else None,
            raw={"status": raw_status, "cost": data.get("cost")},
        )

    # -- convenience ---------------------------------------------------------

    def generate(
        self,
        *,
        prompt: str,
        kind: str = IMAGE,
        model: Optional[str] = None,
        poll_interval_seconds: float = 3.0,
        timeout_seconds: float = 600.0,
        sleep=time.sleep,
        **params: Any,
    ) -> MediaResult:
        """Submit and wait.

        For a script or a test. Real work goes through the job queue, which
        polls across separate transactions so a restart does not lose a
        generation that has already been paid for.

        The deadline is not optional: a provider job that never leaves
        `processing` would otherwise hang the caller forever.
        """
        submission = self.submit(prompt=prompt, kind=kind, model=model, **params)
        deadline = time.monotonic() + timeout_seconds

        while True:
            result = self.poll(submission.request_id)
            if result.status == STATUS_FAILED:
                raise MediaGenerationFailedError(
                    f"MuAPI job {submission.request_id} failed: {result.error or 'no reason given'}"
                )
            if result.status == STATUS_COMPLETED:
                return result
            if time.monotonic() >= deadline:
                raise ProviderCallError(
                    f"MuAPI job {submission.request_id} still {result.raw.get('status')!r} "
                    f"after {timeout_seconds:.0f}s. It may still finish -- poll it by id."
                )
            sleep(poll_interval_seconds)
