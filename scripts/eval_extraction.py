"""Score commitment extraction against labeled cases, per model variant.

Run: .venv/bin/python scripts/eval_extraction.py
Uses the real Token Factory models (a few dozen small calls). Today is pinned to Tue 2026-10-06.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import date

from kept.adapters.egress import build_http_client
from kept.adapters.llm import LLMClient, LLMError
from kept.adapters.sqlite import Database, SqliteCommitmentRepository
from kept.config import get_settings
from kept.domain.models import AuditEvent, Direction, Tier
from kept.services.extraction import ExtractionService

TODAY = date(2026, 10, 6)
BY_ME, TO_ME = Direction.OWED_BY_ME, Direction.OWED_TO_ME


@dataclass(frozen=True)
class Case:
    text: str
    expected: list[tuple[Direction, str, date | None]]


CASES = [
    Case("I will send Priya the pricing deck by Friday.", [(BY_ME, "Priya", date(2026, 10, 9))]),
    Case(
        "Marcus will send me the revised budget sheet by tomorrow.",
        [(TO_ME, "Marcus", date(2026, 10, 7))],
    ),
    Case(
        "I said I would reply to the vendor about the contract renewal, no date set.",
        [(BY_ME, "vendor", None)],
    ),
    Case(
        "I promised Marcus I'd review his onboarding doc by next Monday.",
        [(BY_ME, "Marcus", date(2026, 10, 12))],
    ),
    Case(
        "I committed to booking the offsite venue with Dana by end of this week.",
        [(BY_ME, "Dana", date(2026, 10, 9))],
    ),
    Case(
        "Priya said she will share the Q3 deck by Wednesday.", [(TO_ME, "Priya", date(2026, 10, 7))]
    ),
    Case("We talked about lunch. Someone should maybe look at pricing someday.", []),
    Case(
        "Standup with Priya. I will send her the comparison by Friday. "
        "Priya said she will share the Q3 deck by Wednesday. "
        "Marcus will review my draft next week.",
        [
            (BY_ME, "Priya", date(2026, 10, 9)),
            (TO_ME, "Priya", date(2026, 10, 7)),
            (TO_ME, "Marcus", date(2026, 10, 16)),
        ],
    ),
]


class NullSink:
    def record(self, event: AuditEvent) -> None:
        pass


async def run_variant(llm: LLMClient, tier: Tier, thinking: bool | None) -> tuple[int, int, float]:
    correct = total = 0
    started = time.monotonic()
    for case in CASES:
        repo = SqliteCommitmentRepository(Database(":memory:"))
        service = ExtractionService(llm, repo, tier=tier, thinking=thinking)
        try:
            got = await service.extract("eval", case.text, TODAY)
        except LLMError as exc:
            print(f"    ERROR {exc}")
            got = []
        found = {(c.direction, c.person.lower(), c.due) for c in got}
        hits = 0
        for direction, person, due in case.expected:
            total += 1
            if (direction, person.lower(), due) in found:
                correct += 1
                hits += 1
            else:
                actual = sorted((d.value, p, str(x)) for d, p, x in found)
                print(f"    MISS  {case.text[:48]!r}")
                print(f"          expected {direction.value}/{person}/{due}, got {actual}")
        if (extras := len(found) - hits) > 0:
            total += extras
            print(f"    EXTRA {extras} unexpected in {case.text[:48]!r}")
    return correct, total, time.monotonic() - started


async def main() -> None:
    settings = get_settings()
    http = build_http_client(settings.egress_allowlist, NullSink())
    llm = LLMClient(settings, http)
    variants = [
        ("nano thinking off", Tier.NANO, False),
        ("nano thinking on", Tier.NANO, None),
        ("super thinking off", Tier.SUPER, False),
    ]
    for label, tier, thinking in variants:
        print(f"\n{label}")
        correct, total, seconds = await run_variant(llm, tier, thinking)
        print(f"  => {correct}/{total} correct, {seconds:.1f}s total")
    await http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
