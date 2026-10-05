"""The user's decision on a prepared draft. Approval is the only way a promise becomes done."""

from kept.domain.models import CommitmentStatus, Draft, DraftStatus
from kept.domain.ports import CommitmentRepository, DraftRepository


class DraftNotFoundError(Exception):
    pass


class DraftAlreadyReviewedError(Exception):
    pass


class ReviewService:
    def __init__(self, commitments: CommitmentRepository, drafts: DraftRepository) -> None:
        self._commitments = commitments
        self._drafts = drafts

    def approve(self, draft_id: int) -> Draft:
        return self._decide(draft_id, DraftStatus.APPROVED, CommitmentStatus.DONE)

    def reject(self, draft_id: int) -> Draft:
        return self._decide(draft_id, DraftStatus.REJECTED, CommitmentStatus.OPEN)

    def _decide(
        self, draft_id: int, draft_status: DraftStatus, commitment_status: CommitmentStatus
    ) -> Draft:
        draft = self._drafts.get(draft_id)
        if draft is None:
            raise DraftNotFoundError(f"Draft {draft_id} not found")
        if draft.status is not DraftStatus.PENDING:
            raise DraftAlreadyReviewedError(f"Draft {draft_id} is already {draft.status.value}")
        self._drafts.set_status(draft_id, draft_status)
        self._commitments.set_status(draft.commitment_id, commitment_status)
        return draft.model_copy(update={"status": draft_status})
