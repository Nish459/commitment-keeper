import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from kept.adapters.sqlite import (
    Database,
    SqliteAuditSink,
    SqliteCommitmentRepository,
    SqliteContactRepository,
    SqliteDraftRepository,
    SqliteProfileRepository,
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


def test_sent_details_roundtrip(db: Database) -> None:
    commitments = SqliteCommitmentRepository(db)
    drafts = SqliteDraftRepository(db)
    commitment = commitments.add(_commitment("Priya"))
    assert commitment.id is not None
    saved = drafts.add(Draft(commitment_id=commitment.id, subject="s", body="b"))
    assert saved.id is not None
    assert saved.sent_to is None

    sent_at = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    drafts.set_sent(saved.id, "priya@acme.com", sent_at)
    stored = drafts.get(saved.id)
    assert stored is not None
    assert (stored.sent_to, stored.sent_at) == ("priya@acme.com", sent_at)


def test_contacts_are_case_insensitive_and_upsert(db: Database) -> None:
    contacts = SqliteContactRepository(db)
    assert contacts.get("Priya") is None
    contacts.set("Priya", "old@acme.com")
    contacts.set("priya", "new@acme.com")
    assert contacts.get("PRIYA") == "new@acme.com"
    assert contacts.all() == {"priya": "new@acme.com"}


def test_opening_a_legacy_database_adds_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE drafts (id INTEGER PRIMARY KEY AUTOINCREMENT, commitment_id INTEGER NOT NULL,"
        " subject TEXT NOT NULL, body TEXT NOT NULL, sources TEXT NOT NULL, status TEXT NOT NULL,"
        " created_at TEXT NOT NULL)"
    )
    legacy.commit()
    legacy.close()

    db = Database(path)
    columns = {row["name"] for row in db.query("PRAGMA table_info(drafts)")}
    assert {"sent_to", "sent_at"} <= columns
    db.close()


def test_update_content_changes_only_subject_and_body(db: Database) -> None:
    commitments = SqliteCommitmentRepository(db)
    drafts = SqliteDraftRepository(db)
    commitment = commitments.add(_commitment("Priya"))
    assert commitment.id is not None
    saved = drafts.add(
        Draft(
            commitment_id=commitment.id, subject="Old", body="Old body", sources=["https://a.test"]
        )
    )
    assert saved.id is not None

    drafts.update_content(saved.id, "New", "New body")
    stored = drafts.get(saved.id)
    assert stored is not None
    assert (stored.subject, stored.body) == ("New", "New body")
    assert (stored.sources, stored.status) == (["https://a.test"], DraftStatus.PENDING)


def test_profile_name_roundtrip_overwrite_and_clear(db: Database) -> None:
    profile = SqliteProfileRepository(db)
    assert profile.get_name() is None
    profile.set_name("Ada Lovelace")
    profile.set_name("Grace Hopper")
    assert profile.get_name() == "Grace Hopper"
    profile.set_name("")
    assert profile.get_name() is None


def test_needs_attachment_is_stored_and_legacy_databases_default_to_false(
    db: Database, tmp_path: Path
) -> None:
    commitments = SqliteCommitmentRepository(db)
    drafts = SqliteDraftRepository(db)
    commitment = commitments.add(_commitment("Zoe"))
    saved = drafts.add(
        Draft(commitment_id=commitment.id or 0, subject="s", body="b", needs_attachment=True)
    )
    assert drafts.get(saved.id or 0) == saved
    assert saved.needs_attachment is True

    legacy = sqlite3.connect(tmp_path / "old.db")
    legacy.execute(
        "CREATE TABLE drafts (id INTEGER PRIMARY KEY AUTOINCREMENT, commitment_id INTEGER NOT NULL,"
        " subject TEXT NOT NULL, body TEXT NOT NULL, sources TEXT NOT NULL, status TEXT NOT NULL,"
        " created_at TEXT NOT NULL)"
    )
    legacy.execute(
        "INSERT INTO drafts (commitment_id, subject, body, sources, status, created_at)"
        " VALUES (1, 's', 'b', '[]', 'pending', '2026-10-06T00:00:00+00:00')"
    )
    legacy.commit()
    legacy.close()
    old = Database(tmp_path / "old.db")
    assert SqliteDraftRepository(old).get(1).needs_attachment is False  # type: ignore[union-attr]
    old.close()
