from datetime import date

import pytest

from kept.adapters.sqlite import (
    Database,
    SqliteAuditSink,
    SqliteCommitmentRepository,
    SqliteDraftRepository,
)
from kept.domain.models import (
    AuditEvent,
    Commitment,
    CommitmentStatus,
    Direction,
    Draft,
    DraftStatus,
)


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


def _commitment(person: str, due: date | None = None) -> Commitment:
    return Commitment(
        direction=Direction.OWED_BY_ME,
        person=person,
        description="Send the comparison",
        due=due,
        source_id="note-1",
        source_quote="I'll send it Friday",
    )


def test_add_get_roundtrip(db: Database) -> None:
    repo = SqliteCommitmentRepository(db)
    saved = repo.add(_commitment("Priya", date(2026, 10, 9)))
    assert saved.id is not None
    assert repo.get(saved.id) == saved


def test_get_missing_returns_none(db: Database) -> None:
    assert SqliteCommitmentRepository(db).get(999) is None


def test_list_orders_by_due_with_undated_last_and_filters_status(db: Database) -> None:
    repo = SqliteCommitmentRepository(db)
    repo.add(_commitment("undated"))
    late = repo.add(_commitment("late", date(2026, 11, 1)))
    repo.add(_commitment("soon", date(2026, 10, 7)))
    assert [c.person for c in repo.list()] == ["soon", "late", "undated"]

    assert late.id is not None
    repo.set_status(late.id, CommitmentStatus.DONE)
    assert [c.person for c in repo.list(CommitmentStatus.DONE)] == ["late"]


def test_audit_sink_persists_and_returns_newest_first(db: Database) -> None:
    sink = SqliteAuditSink(db)
    sink.record(AuditEvent(method="GET", host="a.test", path="/1", bytes_out=0, status_code=200))
    sink.record(AuditEvent(method="GET", host="evil.test", path="/2", bytes_out=0, blocked=True))
    events = sink.recent()
    assert [e.host for e in events] == ["evil.test", "a.test"]
    assert events[0].blocked is True
    assert events[1].status_code == 200


def test_draft_roundtrip_and_status(db: Database) -> None:
    commitments = SqliteCommitmentRepository(db)
    drafts = SqliteDraftRepository(db)
    commitment = commitments.add(_commitment("Priya"))
    assert commitment.id is not None

    saved = drafts.add(
        Draft(commitment_id=commitment.id, subject="Hi", body="Body", sources=["https://a.test"])
    )
    assert saved.id is not None
    assert drafts.get(saved.id) == saved
    assert drafts.for_commitment(commitment.id) == saved
    assert drafts.for_commitment(999) is None

    drafts.set_status(saved.id, DraftStatus.APPROVED)
    assert [d.id for d in drafts.list(DraftStatus.APPROVED)] == [saved.id]
    assert drafts.list(DraftStatus.PENDING) == []
