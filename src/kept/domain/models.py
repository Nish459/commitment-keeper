from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class Tier(StrEnum):
    """Model tier requested by callers; concrete model IDs live in settings."""

    NANO = "nano"
    SUPER = "super"
    ULTRA = "ultra"


class Direction(StrEnum):
    """Who owes whom: I promised them, or they promised me."""

    OWED_BY_ME = "owed_by_me"
    OWED_TO_ME = "owed_to_me"


class CommitmentStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    READY_FOR_REVIEW = "ready_for_review"
    DONE = "done"
    DROPPED = "dropped"


class Commitment(BaseModel):
    id: int | None = None
    direction: Direction
    person: str
    description: str
    due: date | None = None
    status: CommitmentStatus = CommitmentStatus.OPEN
    source_id: str
    source_quote: str
    created_at: datetime = Field(default_factory=utcnow)


class Suggestion(BaseModel):
    """A promise found in mail, offered to the user. Nothing is saved until they accept it."""

    direction: Direction
    person: str
    description: str
    due: date | None = None
    source_id: str
    source_quote: str


class ScanResult(BaseModel):
    emails_read: int
    emails_skipped: int
    suggestions: list[Suggestion]


@dataclass(frozen=True)
class Mail:
    """One email reduced to what Kept needs: who, when, and the text the sender wrote."""

    subject: str
    sender_name: str
    sender_address: str
    to_names: tuple[str, ...]
    to_addresses: tuple[str, ...]
    sent: date | None
    body: str
    from_me: bool | None = None  # None until the mailbox owner is known


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class DraftStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Draft(BaseModel):
    """A prepared deliverable awaiting the user's approval. Never sent automatically."""

    id: int | None = None
    commitment_id: int
    subject: str
    body: str
    sources: list[str] = Field(default_factory=list)
    status: DraftStatus = DraftStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    sent_to: str | None = None
    sent_at: datetime | None = None
    # The email says a file is attached; the user must add it before sending.
    needs_attachment: bool = False


class Attachment(BaseModel):
    """A file the user adds to a draft. The bytes never leave the server in API responses."""

    id: int | None = None
    draft_id: int
    filename: str
    content_type: str
    size: int
    data: bytes = Field(default=b"", exclude=True, repr=False)


class PersonSummary(BaseModel):
    """What Kept remembers about one person, computed from promises and sent emails."""

    name: str
    promises_by_me: int  # promises I made to them, not counting dropped ones
    kept_by_me: int
    open_by_me: int
    open_to_me: int  # promises they made to me that are still open
    overdue: int  # open promises, either direction, past their due date
    emails_sent: int
    last_emailed_at: datetime | None = None
    last_subject: str | None = None


class AuditEvent(BaseModel):
    """One outbound request attempt. Never contains bodies, queries or credentials."""

    at: datetime = Field(default_factory=utcnow)
    method: str
    host: str
    path: str
    bytes_out: int
    status_code: int | None = None
    blocked: bool = False
    duration_ms: int = 0
