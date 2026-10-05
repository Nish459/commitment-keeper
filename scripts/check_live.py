"""Live smoke test against Token Factory (all tiers) with the real egress policy.

Run: .venv/bin/python scripts/check_live.py
Reads keys from .env. Costs a handful of tokens.
"""

import asyncio
import time

from kept.adapters.egress import build_http_client
from kept.adapters.llm import LLMClient, LLMError
from kept.config import get_settings
from kept.domain.models import AuditEvent, Tier


class PrintSink:
    def record(self, event: AuditEvent) -> None:
        state = "BLOCKED" if event.blocked else event.status_code
        print(f"  [egress] {event.method} {event.host}{event.path} -> {state}")


async def main() -> None:
    settings = get_settings()
    if not settings.nebius_api_key.get_secret_value():
        raise SystemExit("KEPT_NEBIUS_API_KEY is not set (see .env.example)")

    http = build_http_client(settings.egress_allowlist, PrintSink())
    llm = LLMClient(settings, http)

    print("Available models containing 'nemotron':")
    for model_id in await llm.list_model_ids():
        if "nemotron" in model_id.lower():
            print(f"  {model_id}")

    for tier in Tier:
        model = settings.model_for(tier)
        print(f"\n{tier.value}: {model or '(not configured)'}")
        started = time.monotonic()
        try:
            reply = await llm.complete(
                tier,
                [{"role": "user", "content": "Reply with exactly: ready"}],
                max_tokens=256,
            )
        except LLMError as exc:
            print(f"  FAILED: {exc}")
            continue
        print(f"  {reply!r} in {time.monotonic() - started:.1f}s")

    await http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
