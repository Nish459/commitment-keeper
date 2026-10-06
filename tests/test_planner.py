from datetime import date
from typing import Any

from pydantic import BaseModel

from kept.adapters.sqlite import Database, SqliteCommitmentRepository
from kept.domain.models import Commitment, CommitmentStatus, Direction, Tier
from kept.services.planner import MAX_PROMISES, Concern, OrderedItem, PlannerService, WeekCheck

TODAY = date(2026, 10, 6)  # a Tuesday


class FakeLLM:
    def __init__(self, answer: WeekCheck) -> None:
        self._answer = answer
        self.calls: list[dict[str, Any]] = []

    async def complete_json[T: BaseModel](
        self,
        tier: Tier,
        messages: list[dict[str, str]],
        schema: type[T],
        **kwargs: Any,
    ) -> T:
        self.calls.append({"tier": tier, "messages": messages, "kwargs": kwargs})
        return schema.model_validate(self._answer.model_dump())


def _setup(
    answer: WeekCheck | None = None,
) -> tuple[PlannerService, FakeLLM, SqliteCommitmentRepository]:
    llm = FakeLLM(answer or WeekCheck(summary="Fine."))
    repo = SqliteCommitmentRepository(Database(":memory:"))
    return PlannerService(llm, repo), llm, repo


def _add(
    repo: SqliteCommitmentRepository,
    description: str,
    due: date | None = date(2026, 10, 9),
    *,
    direction: Direction = Direction.OWED_BY_ME,
    status: CommitmentStatus = CommitmentStatus.OPEN,
    person: str = "Priya",
) -> int:
    saved = repo.add(
        Commitment(
            direction=direction,
            person=person,
            description=description,
            due=due,
            status=status,
            source_id="n",
            source_quote="q",
        )
    )
    return saved.id or 0


async def test_it_asks_ultra_with_reasoning_left_on_and_gives_it_real_dates() -> None:
    service, llm, repo = _setup()
    _add(repo, "Send comparison")
    _add(repo, "Share deck", date(2026, 10, 7), direction=Direction.OWED_TO_ME)
    _add(repo, "Late thing", date(2026, 10, 4))
    _add(repo, "Someday", None)

    await service.check_week(TODAY)

    (call,) = llm.calls
    assert call["tier"] is Tier.ULTRA
    assert "thinking" not in call["kwargs"]  # the whole point of Ultra here is to reason
    system, user = call["messages"][0]["content"], call["messages"][1]["content"]
    assert "Tuesday 2026-10-06" in system
    assert (
        "#1 | I owe Priya | Send comparison | due Fri 2026-10-09 (in 3 days) | status: open" in user
    )
    assert "#2 | Priya owes me | Share deck | due Wed 2026-10-07 (in 1 day)" in user
    assert "(2 days overdue)" in user
    assert "no due date" in user


async def test_with_fewer_than_two_open_promises_no_model_call_is_made() -> None:
    service, llm, repo = _setup()
    _add(repo, "Only one")
    _add(repo, "Done already", status=CommitmentStatus.DONE)
    result = await service.check_week(TODAY)
    assert llm.calls == []
    assert result.model_used is None
    assert result.concerns == [] and "nothing to compare" in result.summary


async def test_finished_and_dropped_promises_are_not_sent_to_the_model() -> None:
    service, llm, repo = _setup()
    _add(repo, "Open one")
    _add(repo, "Open two")
    _add(repo, "Finished", status=CommitmentStatus.DONE)
    _add(repo, "Dropped", status=CommitmentStatus.DROPPED)
    await service.check_week(TODAY)
    user = llm.calls[0]["messages"][1]["content"]
    assert "Open one" in user and "Open two" in user
    assert "Finished" not in user and "Dropped" not in user


async def test_the_model_cannot_cite_promises_that_do_not_exist() -> None:
    answer = WeekCheck(
        summary="  Busy Friday.  ",
        concerns=[
            Concern(commitment_ids=[1, 2, 99, 1], title="Crunch", explanation="Both land Friday."),
            Concern(commitment_ids=[99], title="Ghost", explanation="About nothing real."),
            Concern(commitment_ids=[1], title="Empty", explanation="   "),
        ],
        suggested_order=[
            OrderedItem(commitment_id=2, reason="Due first"),
            OrderedItem(commitment_id=3, reason="Owed to me, not mine to schedule"),
            OrderedItem(commitment_id=99, reason="Unknown"),
            OrderedItem(commitment_id=1, reason="Then this"),
            OrderedItem(commitment_id=2, reason="Duplicate"),
        ],
    )
    service, _, repo = _setup(answer)
    _add(repo, "First")
    _add(repo, "Second")
    _add(repo, "Theirs", direction=Direction.OWED_TO_ME)

    result = await service.check_week(TODAY)

    assert result.summary == "Busy Friday."
    assert [(c.title, c.commitment_ids) for c in result.concerns] == [("Crunch", [1, 2])]
    assert [(i.commitment_id, i.reason) for i in result.suggested_order] == [
        (2, "Due first"),
        (1, "Then this"),
    ]
    assert result.model_used == "Nemotron 3 Ultra"


async def test_a_very_long_list_is_capped_to_keep_the_prompt_bounded() -> None:
    service, llm, repo = _setup()
    for i in range(MAX_PROMISES + 10):
        _add(repo, f"Promise {i}")
    await service.check_week(TODAY)
    assert llm.calls[0]["messages"][1]["content"].count("\n") == MAX_PROMISES - 1
