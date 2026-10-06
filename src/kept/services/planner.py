"""The week check: Ultra reads every open promise and flags conflicts, dependencies and risks."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from kept.domain.models import Commitment, Direction, Tier
from kept.domain.ports import CommitmentRepository, StructuredLLM

MAX_PROMISES = 40

_PROMPT = """You are a careful planner reviewing a person's open promises. Today is {today}.
The person is "me". Each promise has an id, who owes whom, a due date and the days until it is due.

Find real problems only. Do not invent facts or dependencies the descriptions do not support.
Reply with JSON only:
{{"summary": "...",
 "concerns": [{{"commitment_ids": [1, 2], "title": "...", "explanation": "...",
               "severity": "high" | "medium" | "low"}}],
 "suggested_order": [{{"commitment_id": 1, "reason": "..."}}]}}

- concerns: genuine conflicts (too much due on the same day), dependencies (something I promised
  needs something someone owes me that arrives late or not at all), or promises likely to slip.
  Use only ids from the list. Return an empty list when nothing is wrong.
- suggested_order: only promises marked "I owe", most urgent first, one short reason each.
- summary: one or two plain sentences about the week as a whole."""


class Concern(BaseModel):
    commitment_ids: list[int] = Field(default_factory=list)
    title: str
    explanation: str
    severity: Literal["high", "medium", "low"] = "medium"


class OrderedItem(BaseModel):
    commitment_id: int
    reason: str


class WeekCheck(BaseModel):
    summary: str
    concerns: list[Concern] = Field(default_factory=list)
    suggested_order: list[OrderedItem] = Field(default_factory=list)
    model_used: str | None = None  # None when no model call was needed


def _describe(commitment: Commitment, today: date) -> str:
    who = (
        f"I owe {commitment.person}"
        if commitment.direction is Direction.OWED_BY_ME
        else f"{commitment.person} owes me"
    )
    if commitment.due is None:
        due = "no due date"
    else:
        days = (commitment.due - today).days
        unit = "day" if abs(days) == 1 else "days"
        when = (
            "today" if days == 0 else f"in {days} {unit}" if days > 0 else f"{-days} {unit} overdue"
        )
        due = f"due {commitment.due:%a %Y-%m-%d} ({when})"
    return (
        f"#{commitment.id} | {who} | {commitment.description} | {due} | status: {commitment.status}"
    )


class PlannerService:
    def __init__(self, llm: StructuredLLM, commitments: CommitmentRepository) -> None:
        self._llm = llm
        self._commitments = commitments

    async def check_week(self, today: date) -> WeekCheck:
        open_promises = [
            c for c in self._commitments.list() if c.status.value not in {"done", "dropped"}
        ][:MAX_PROMISES]
        if len(open_promises) < 2:
            return WeekCheck(summary="There's nothing to compare yet. Add more promises first.")

        raw = await self._llm.complete_json(
            Tier.ULTRA,
            [
                {"role": "system", "content": _PROMPT.format(today=f"{today:%A %Y-%m-%d}")},
                {"role": "user", "content": "\n".join(_describe(c, today) for c in open_promises)},
            ],
            WeekCheck,
            temperature=0.2,
            max_tokens=4096,
        )
        return self._validated(raw, open_promises)

    @staticmethod
    def _validated(raw: WeekCheck, open_promises: list[Commitment]) -> WeekCheck:
        """The model may only refer to promises that exist; anything else is dropped."""
        known = {c.id for c in open_promises}
        mine = {c.id for c in open_promises if c.direction is Direction.OWED_BY_ME}

        concerns = []
        for concern in raw.concerns:
            ids = [i for i in dict.fromkeys(concern.commitment_ids) if i in known]
            if ids and concern.explanation.strip():
                concerns.append(concern.model_copy(update={"commitment_ids": ids}))

        order: list[OrderedItem] = []
        seen: set[int] = set()
        for item in raw.suggested_order:
            if item.commitment_id in mine and item.commitment_id not in seen:
                seen.add(item.commitment_id)
                order.append(item)

        return WeekCheck(
            summary=raw.summary.strip(),
            concerns=concerns,
            suggested_order=order,
            model_used="Nemotron 3 Ultra",
        )
