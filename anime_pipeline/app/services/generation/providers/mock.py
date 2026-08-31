"""A provider that needs no credentials.

Not a stub in the pejorative sense -- it is what makes the whole generation
path testable and what keeps `pytest` runnable with no network. It returns
deterministic, structurally valid output so downstream parsing, canon
enforcement and QC all get exercised without a single API call.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from app.services.generation.providers.base import Completion, TextProvider


class MockTextProvider(TextProvider):
    provider_key = "mock"
    default_model = "mock-deterministic-v1"

    def generate(
        self,
        *,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 16000,
        **kwargs: Any,
    ) -> Completion:
        # Hashed so the same prompt always yields the same text: a benchmark
        # run against the mock provider is reproducible, which is the entire
        # reason the adversarial suite can use it.
        digest = hashlib.sha256(f"{system or ''}\n{prompt}".encode()).hexdigest()[:12]
        text = (
            "[HOOK]\n"
            "Something in the signal does not belong to anyone who is listening.\n\n"
            "[SETUP]\n"
            f"Deterministic mock output for prompt digest {digest}.\n\n"
            "[MIDPOINT SHIFT]\n"
            "The obvious explanation stops accounting for the evidence.\n\n"
            "[ESCALATION]\n"
            "Each answer costs another certainty.\n\n"
            "[PAYOFF]\n"
            "What looked isolated turns out to be a pattern.\n\n"
            "[OUTRO]\n"
            "And if it happened once, it has already happened again."
        )
        return Completion(
            text=text,
            provider=self.provider_key,
            model=model or self.default_model,
            usage={"prompt_chars": len(prompt), "completion_chars": len(text)},
            stop_reason="end_turn",
            raw={"digest": digest},
        )
