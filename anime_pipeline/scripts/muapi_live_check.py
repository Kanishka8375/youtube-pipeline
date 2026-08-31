#!/usr/bin/env python
"""Live check against the real MuAPI service.

Deliberately not a pytest test. It needs a key, reaches the network, and
**spends money** -- a test suite that sometimes bills you is one people stop
running, and then it protects nothing. The behaviour of the adapter is pinned
in `tests/test_media_providers.py` against a fake transport; this script exists
to prove the adapter's idea of the wire matches the service's.

    export MUAPI_API_KEY=...          # never committed, never in a config row
    python scripts/muapi_live_check.py --prompt "a lighthouse at dusk"

Defaults to `flux-schnell-image` because it is the cheapest and fastest image
model on the service. Pass --model to use another; the model name is the
endpoint path segment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.generation.providers.media_base import (  # noqa: E402
    STATUS_COMPLETED,
    STATUS_FAILED,
    ProviderError,
)
from app.services.generation.providers.muapi import MuApiProvider  # noqa: E402

DEFAULT_MODEL = "flux-schnell-image"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", default="a lighthouse at dusk, anime key art")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--kind", default="image", choices=["image", "video", "audio"])
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument(
        "--submit-only",
        action="store_true",
        help="Submit and print the request id without waiting for the result.",
    )
    args = parser.parse_args()

    provider = MuApiProvider(default_model=args.model)
    if not provider.is_configured():
        print("MUAPI_API_KEY is not set. Export it and try again.", file=sys.stderr)
        return 2

    print(f"model   : {args.model}")
    print(f"prompt  : {args.prompt}")

    started = time.monotonic()
    try:
        submission = provider.submit(prompt=args.prompt, kind=args.kind)
    except ProviderError as exc:
        print(f"\nsubmit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"accepted: {submission.request_id}")
    if args.submit_only:
        return 0

    deadline = started + args.timeout
    last = None
    while True:
        try:
            result = provider.poll(submission.request_id)
        except ProviderError as exc:
            print(f"\npoll failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

        raw = result.raw.get("status")
        if raw != last:
            print(f"  [{time.monotonic() - started:6.1f}s] {raw}")
            last = raw

        if result.status == STATUS_FAILED:
            print(f"\nfailed  : {result.error}", file=sys.stderr)
            return 1
        if result.status == STATUS_COMPLETED:
            elapsed = time.monotonic() - started
            print(f"\ncompleted in {elapsed:.1f}s")
            print(f"cost    : {'unreported' if result.cost_usd is None else f'${result.cost_usd:.4f}'}")
            for url in result.outputs:
                print(f"output  : {url}")
            print("\nnormalised result:")
            print(json.dumps(result.as_dict(), indent=2))
            return 0
        if time.monotonic() >= deadline:
            print(
                f"\nstill {raw!r} after {args.timeout:.0f}s. It may yet finish -- "
                f"poll {submission.request_id} by id.",
                file=sys.stderr,
            )
            return 1
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    raise SystemExit(main())
