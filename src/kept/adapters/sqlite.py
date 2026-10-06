"""SQLite persistence for commitments and the egress audit trail."""

import json
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

from kept.domain.models import (
    AuditEvent,
    Commitment,
    CommitmentStatus,
    Direction,
    Draft,
    DraftStatus,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS commitments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL,
    person TEXT NOT NULL,
    description TEXT NOT NULL,
    due TEXT,
    status TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_quote TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commitment_id INTEGER NOT NULL REFERENCES commitments(id),
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sources TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sent_to TEXT,
    sent_at TEXT
);
CREATE TABLE IF NOT EXISTS contacts (
    person TEXT PRIMARY KEY,
    email TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    method TEXT NOT NULL,
    host TEXT NOT NULL,
    path TEXT NOT NULL,
    bytes_out INTEGER NOT NULL,
    status_code INTEGER,
    blocked INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL
);
"""


# Columns added after the first release; older databases get them on open.
_ADDED_COLUMNS = (("drafts", "sent_to", "TEXT"), ("drafts", "sent_at", "TEXT"))


class Database:
    """One shared connection guarded by a lock; fine for a single-user local app."""

    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            for table, column, kind in _ADDED_COLUMNS:
                existing = {
                    row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")
                }
                if column not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            self._conn.commit()

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    def query(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _to_commitment(row: sqlite3.Row) -> Commitment:
    return Commitment(
        id=row["id"],
        direction=Direction(row["direction"]),
        person=row["person"],
        description=row["description"],
        due=date.fromisoformat(row["due"]) if row["due"] else None,
        status=CommitmentStatus(row["status"]),
        source_id=row["source_id"],
        source_quote=row["source_quote"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class SqliteCommitmentRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, commitment: Commitment) -> Commitment:
        cursor = self._db.execute(
            "INSERT INTO commitments (direction, person, description, due, status, source_id,"
            " source_quote, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                commitment.direction.value,
                commitment.person,
                commitment.description,
                commitment.due.isoformat() if commitment.due else None,
                commitment.status.value,
                commitment.source_id,
                commitment.source_quote,
                commitment.created_at.isoformat(),
            ),
        )
        return commitment.model_copy(update={"id": cursor.lastrowid})

    def get(self, commitment_id: int) -> Commitment | None:
        rows = self._db.query("SELECT * FROM commitments WHERE id = ?", (commitment_id,))
        return _to_commitment(rows[0]) if rows else None

    def list(self, status: CommitmentStatus | None = None) -> list[Commitment]:
        if status is None:
            rows = self._db.query("SELECT * FROM commitments ORDER BY due IS NULL, due, id")
        else:
            rows = self._db.query(
                "SELECT * FROM commitments WHERE status = ? ORDER BY due IS NULL, due, id",
                (status.value,),
            )
        return [_to_commitment(row) for row in rows]

    def set_status(self, commitment_id: int, status: CommitmentStatus) -> None:
        self._db.execute(
            "UPDATE commitments SET status = ? WHERE id = ?", (status.value, commitment_id)
        )


def _to_draft(row: sqlite3.Row) -> Draft:
    return Draft(
        id=row["id"],
        commitment_id=row["commitment_id"],
        subject=row["subject"],
        body=row["body"],
        sources=json.loads(row["sources"]),
        status=DraftStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        sent_to=row["sent_to"],
        sent_at=datetime.fromisoformat(row["sent_at"]) if row["sent_at"] else None,
    )


class SqliteDraftRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, draft: Draft) -> Draft:
        cursor = self._db.execute(
            "INSERT INTO drafts (commitment_id, subject, body, sources, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                draft.commitment_id,
                draft.subject,
                draft.body,
                json.dumps(draft.sources),
                draft.status.value,
                draft.created_at.isoformat(),
            ),
        )
        return draft.model_copy(update={"id": cursor.lastrowid})

    def get(self, draft_id: int) -> Draft | None:
        rows = self._db.query("SELECT * FROM drafts WHERE id = ?", (draft_id,))
        return _to_draft(rows[0]) if rows else None

    def list(self, status: DraftStatus | None = None) -> list[Draft]:
        if status is None:
            rows = self._db.query("SELECT * FROM drafts ORDER BY id DESC")
        else:
            rows = self._db.query(
                "SELECT * FROM drafts WHERE status = ? ORDER BY id DESC", (status.value,)
            )
        return [_to_draft(row) for row in rows]

    def for_commitment(self, commitment_id: int) -> Draft | None:
        rows = self._db.query(
            "SELECT * FROM drafts WHERE commitment_id = ? ORDER BY id DESC LIMIT 1",
            (commitment_id,),
        )
        return _to_draft(rows[0]) if rows else None

    def set_status(self, draft_id: int, status: DraftStatus) -> None:
        self._db.execute("UPDATE drafts SET status = ? WHERE id = ?", (status.value, draft_id))

    def update_content(self, draft_id: int, subject: str, body: str) -> None:
        self._db.execute(
            "UPDATE drafts SET subject = ?, body = ? WHERE id = ?", (subject, body, draft_id)
        )

    def set_sent(self, draft_id: int, to: str, at: datetime) -> None:
        self._db.execute(
            "UPDATE drafts SET sent_to = ?, sent_at = ? WHERE id = ?",
            (to, at.isoformat(), draft_id),
        )


class SqliteContactRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, person: str) -> str | None:
        rows = self._db.query("SELECT email FROM contacts WHERE person = ?", (person.lower(),))
        return str(rows[0]["email"]) if rows else None

    def set(self, person: str, email: str) -> None:
        self._db.execute(
            "INSERT INTO contacts (person, email) VALUES (?, ?)"
            " ON CONFLICT(person) DO UPDATE SET email = excluded.email",
            (person.lower(), email),
        )

    def all(self) -> dict[str, str]:
        return {str(r["person"]): str(r["email"]) for r in self._db.query("SELECT * FROM contacts")}


class SqliteProfileRepository:
    """The one person this installation belongs to."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get_name(self) -> str | None:
        rows = self._db.query("SELECT name FROM profile WHERE id = 1")
        return str(rows[0]["name"]) if rows else None

    def set_name(self, name: str) -> None:
        if not name:
            self._db.execute("DELETE FROM profile WHERE id = 1")
            return
        self._db.execute(
            "INSERT INTO profile (id, name) VALUES (1, ?)"
            " ON CONFLICT(id) DO UPDATE SET name = excluded.name",
            (name,),
        )


class SqliteAuditSink:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(self, event: AuditEvent) -> None:
        self._db.execute(
            "INSERT INTO audit_events (at, method, host, path, bytes_out, status_code, blocked,"
            " duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.at.isoformat(),
                event.method,
                event.host,
                event.path,
                event.bytes_out,
                event.status_code,
                int(event.blocked),
                event.duration_ms,
            ),
        )

    def recent(self, limit: int = 100) -> list[AuditEvent]:
        rows = self._db.query("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,))
        return [
            AuditEvent(
                at=datetime.fromisoformat(row["at"]),
                method=row["method"],
                host=row["host"],
                path=row["path"],
                bytes_out=row["bytes_out"],
                status_code=row["status_code"],
                blocked=bool(row["blocked"]),
                duration_ms=row["duration_ms"],
            )
            for row in rows
        ]
