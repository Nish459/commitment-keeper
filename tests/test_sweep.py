from datetime import date

import pytest

from kept.adapters.sqlite import Database, SqliteCommitmentRepository, SqliteDraftRepository
from kept.domain.errors import DemoLimitError
from kept.domain.models import Commitment, CommitmentStatus, Direction, Draft, DraftStatus
from kept.services.sweep import SweepService

TODAY = date(2026, 10, 6)  # a Tuesday


class Env:
    def __init__(self, *, max_per_run: int = 5, fail_ids: set[int] | None = None) -> None:
        db = Database(":memory:")
        self.commitments = SqliteCommitmentRepository(db)
        self.drafts = SqliteDraftRepository(db)
        self.prepared: list[int] = []
        self.fail_ids = fail_ids or set()
        self.limit_after: int | None = None
        self.service = SweepService(
            self.commitments, self.drafts, self._prepare, horizon_days=3, max_per_run=max_per_run
        )

    async def _prepare(self, commitment_id: int, today: date) -> Draft:
        if commitment_id in self.fail_ids:
            raise RuntimeError("search is down")
        if self.limit_after is not None and len(self.prepared) >= self.limit_after:
            raise DemoLimitError("You've used the demo's drafts allowance.")
        self.prepared.append(commitment_id)
        self.commitments.set_status(commitment_id, CommitmentStatus.READY_FOR_REVIEW)
        return self.drafts.add(Draft(commitment_id=commitment_id, subject="s", body="b"))

    def add(
        self,
        due: str | None,
        *,
        direction: Direction = Direction.OWED_BY_ME,
        status: CommitmentStatus = CommitmentStatus.OPEN,
        person: str = "Priya",
    ) -> int:
        saved = self.commitments.add(
            Commitment(
                direction=direction,
                person=person,
                description=f"Promise due {due}",
                due=date.fromisoformat(due) if due else None,
                status=status,
                source_id="n",
                source_quote="q",
            )
        )
        return saved.id or 0


async def test_only_open_promises_i_made_that_are_due_soon_are_drafted() -> None:
    env = Env()
    overdue = env.add("2026-10-04")
    today = env.add("2026-10-06")
    edge = env.add("2026-10-09")  # exactly three days out
    env.add("2026-10-10")  # beyond the horizon
    env.add(None)  # no deadline
    env.add("2026-10-07", direction=Direction.OWED_TO_ME)
    env.add("2026-10-07", status=CommitmentStatus.READY_FOR_REVIEW)
    env.add("2026-10-07", status=CommitmentStatus.DONE)

    result = await env.service.run(TODAY)

    assert env.prepared == [overdue, today, edge]  # soonest first
    assert [d.commitment_id for d in result.prepared] == [overdue, today, edge]
    assert (result.failed, result.skipped, result.stopped) == ([], 0, None)


async def test_a_second_run_finds_nothing_left_to_do() -> None:
    env = Env()
    env.add("2026-10-07")
    assert len((await env.service.run(TODAY)).prepared) == 1
    assert (await env.service.run(TODAY)).prepared == []


async def test_a_rejected_draft_is_never_redrafted_automatically() -> None:
    env = Env()
    rejected = env.add("2026-10-07")
    draft = env.drafts.add(Draft(commitment_id=rejected, subject="s", body="b"))
    env.drafts.set_status(draft.id or 0, DraftStatus.REJECTED)
    kept = env.add("2026-10-08")

    await env.service.run(TODAY)
    assert env.prepared == [kept]


async def test_the_per_run_cap_defers_the_rest_and_says_so() -> None:
    env = Env(max_per_run=2)
    ids = [env.add(f"2026-10-0{day}") for day in (6, 7, 8, 9)]
    first = await env.service.run(TODAY)
    assert env.prepared == ids[:2]
    assert first.skipped == 2

    second = await env.service.run(TODAY)
    assert env.prepared == ids
    assert second.skipped == 0


async def test_one_failing_promise_does_not_stop_the_others() -> None:
    env = Env()
    bad = env.add("2026-10-06")
    good = env.add("2026-10-07")
    env.fail_ids = {bad}

    result = await env.service.run(TODAY)
    assert [d.commitment_id for d in result.prepared] == [good]
    assert [(f.commitment_id, f.reason) for f in result.failed] == [(bad, "search is down")]
    stored = env.commitments.get(bad)
    assert stored is not None
    assert stored.status is CommitmentStatus.OPEN  # still eligible for the next run


async def test_hitting_the_demo_allowance_stops_the_sweep_and_counts_what_was_left() -> None:
    env = Env()
    env.limit_after = 1
    for day in (6, 7, 8):
        env.add(f"2026-10-0{day}")

    result = await env.service.run(TODAY)
    assert len(result.prepared) == 1
    assert result.stopped is not None
    assert result.skipped == 2


@pytest.mark.parametrize("horizon", [0, 1])
def test_horizon_is_configurable(horizon: int) -> None:
    env = Env()
    env.service = SweepService(env.commitments, env.drafts, env._prepare, horizon_days=horizon)
    env.add("2026-10-06")
    env.add("2026-10-07")
    assert len(env.service.eligible(TODAY)) == horizon + 1
