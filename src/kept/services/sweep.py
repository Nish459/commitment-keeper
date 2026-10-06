"""Proactive keeping: draft everything that is due soon, so it is ready before the deadline."""

import logging
from collections.abc import Awaitable, Callable
from datetime import date, timedelta

from pydantic import BaseModel

from kept.domain.errors import DemoLimitError
from kept.domain.models import Commitment, CommitmentStatus, Direction, Draft, DraftStatus
from kept.domain.ports import CommitmentRepository, DraftRepository

logger = logging.getLogger("kept.sweep")

Prepare = Callable[[int, date], Awaitable[Draft]]


class SweepFailure(BaseModel):
    commitment_id: int
    description: str
    reason: str


class SweepResult(BaseModel):
    prepared: list[Draft] = []
    failed: list[SweepFailure] = []
    skipped: int = 0  # eligible but beyond this run's cap; the next run picks them up
    stopped: str | None = None


class SweepService:
    def __init__(
        self,
        commitments: CommitmentRepository,
        drafts: DraftRepository,
        prepare: Prepare,
        *,
        horizon_days: int = 3,
        max_per_run: int = 5,
    ) -> None:
        self._commitments = commitments
        self._drafts = drafts
        self._prepare = prepare
        self._horizon = horizon_days
        self._max = max_per_run

    def eligible(self, today: date) -> list[Commitment]:
        """Open promises I made that are overdue or due within the horizon, soonest first.

        A promise whose last draft was rejected is left alone: that was the user's decision.
        """
        cutoff = today + timedelta(days=self._horizon)
        due_soon = [
            c
            for c in self._commitments.list(CommitmentStatus.OPEN)
            if c.direction is Direction.OWED_BY_ME
            and c.due is not None
            and c.due <= cutoff
            and not self._was_rejected(c)
        ]
        return sorted(due_soon, key=lambda c: (c.due or cutoff, c.id or 0))

    def _was_rejected(self, commitment: Commitment) -> bool:
        latest = self._drafts.for_commitment(commitment.id or 0)
        return latest is not None and latest.status is DraftStatus.REJECTED

    async def run(self, today: date) -> SweepResult:
        candidates = self.eligible(today)
        result = SweepResult(skipped=max(0, len(candidates) - self._max))
        for commitment in candidates[: self._max]:
            try:
                result.prepared.append(await self._prepare(commitment.id or 0, today))
            except DemoLimitError as exc:
                result.stopped = str(exc)
                result.skipped += (
                    len(candidates[: self._max]) - len(result.prepared) - len(result.failed)
                )
                break
            except Exception as exc:
                logger.warning("sweep failed for %s: %s", commitment.id, exc)
                result.failed.append(
                    SweepFailure(
                        commitment_id=commitment.id or 0,
                        description=commitment.description,
                        reason=str(exc) or type(exc).__name__,
                    )
                )
        return result
