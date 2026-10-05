import pytest

from kept.adapters.sqlite import Database, SqliteCommitmentRepository, SqliteDraftRepository
from kept.domain.models import Commitment, CommitmentStatus, Direction, Draft, DraftStatus
from kept.services.review import DraftAlreadyReviewedError, DraftNotFoundError, ReviewService


def _setup() -> tuple[ReviewService, SqliteCommitmentRepository, int, int]:
    db = Database(":memory:")
    commitments = SqliteCommitmentRepository(db)
    drafts = SqliteDraftRepository(db)
    commitment = commitments.add(
        Commitment(
            direction=Direction.OWED_BY_ME,
            person="Priya",
            description="Send it",
            status=CommitmentStatus.READY_FOR_REVIEW,
            source_id="n",
            source_quote="q",
        )
    )
    assert commitment.id is not None
    draft = drafts.add(Draft(commitment_id=commitment.id, subject="s", body="b"))
    assert draft.id is not None
    return ReviewService(commitments, drafts), commitments, commitment.id, draft.id


def test_approve_marks_draft_approved_and_commitment_done() -> None:
    service, commitments, cid, did = _setup()
    assert service.approve(did).status is DraftStatus.APPROVED
    stored = commitments.get(cid)
    assert stored is not None
    assert stored.status is CommitmentStatus.DONE


def test_reject_reopens_commitment() -> None:
    service, commitments, cid, did = _setup()
    assert service.reject(did).status is DraftStatus.REJECTED
    stored = commitments.get(cid)
    assert stored is not None
    assert stored.status is CommitmentStatus.OPEN


def test_cannot_review_twice_or_unknown() -> None:
    service, _, _, did = _setup()
    service.approve(did)
    with pytest.raises(DraftAlreadyReviewedError):
        service.reject(did)
    with pytest.raises(DraftNotFoundError):
        service.approve(999)
