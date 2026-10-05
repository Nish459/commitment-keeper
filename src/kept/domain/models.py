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
