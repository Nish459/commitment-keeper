"""Command line entry point. `kept sweep` is what the nightly Nebius Serverless Job runs."""

import argparse
import asyncio
import logging
from collections.abc import Sequence

from kept.config import Settings, get_settings
from kept.container import build_container
from kept.services.sweep import SweepResult


def format_result(result: SweepResult) -> str:
    lines = [f"Prepared {len(result.prepared)} draft(s) for review."]
    lines += [f"  draft {d.id} for promise {d.commitment_id}: {d.subject}" for d in result.prepared]
    if result.failed:
        lines.append(f"{len(result.failed)} failed:")
        lines += [
            f"  promise {f.commitment_id} ({f.description}): {f.reason}" for f in result.failed
        ]
    if result.skipped:
        lines.append(f"{result.skipped} more are due soon and will be picked up on the next run.")
    if result.stopped:
        lines.append(f"Stopped early: {result.stopped}")
    return "\n".join(lines)


def exit_code(result: SweepResult) -> int:
    """Non-zero only if there was work and none of it succeeded, so a failed Job shows as failed."""
    return 1 if result.failed and not result.prepared else 0


async def run_sweep(settings: Settings) -> SweepResult:
    container = build_container(settings)
    try:
        return await container.sweep.run(container.today())
    finally:
        await container.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kept", description="Kept: keeps your promises.")
    commands = parser.add_subparsers(dest="command", required=True)
    sweep = commands.add_parser("sweep", help="draft every promise that is due soon")
    sweep.add_argument("--horizon", type=int, help="days ahead to look (default from settings)")
    sweep.add_argument("--max", type=int, dest="max_per_run", help="drafts per run (default 5)")
    sweep.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    overrides = {
        key: value
        for key, value in {
            "sweep_horizon_days": args.horizon,
            "sweep_max_per_run": args.max_per_run,
        }.items()
        if value is not None
    }
    result = asyncio.run(run_sweep(get_settings().model_copy(update=overrides)))
    print(result.model_dump_json(indent=2) if args.json else format_result(result))
    return exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
