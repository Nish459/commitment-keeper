"""Adding a promise by hand: instant, free and exact, with no model involved."""

from datetime import date

from kept.domain.models import Commitment, Direction
from kept.domain.ports import CommitmentRepository
from kept.domain.text import sentence_case

MANUAL_SOURCE = "Added by hand"


class ManualEntryService:
    def __init__(self, commitments: CommitmentRepository) -> None:
        self._commitments = commitments

    def add(
        self, direction: Direction, person: str, description: str, due: date | None
    ) -> Commitment:
        return self._commitments.add(
            Commitment(
                direction=direction,
                person=sentence_case(person),
                description=sentence_case(description),
                due=due,
                source_id=MANUAL_SOURCE,
                source_quote="",
            )
        )
