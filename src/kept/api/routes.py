from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, StringConstraints

from kept.container import Container
from kept.domain.models import AuditEvent, Commitment, CommitmentStatus, Draft, DraftStatus

router = APIRouter(prefix="/api")


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


Deps = Annotated[Container, Depends(get_container)]


class NoteIn(BaseModel):
    source_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=50_000)


@router.post("/notes")
async def ingest_note(note: NoteIn, c: Deps) -> list[Commitment]:
    """Extract and store the commitments found in a note."""
    return await c.extraction.extract(note.source_id, note.text, c.today())


@router.get("/commitments")
def list_commitments(c: Deps, status: CommitmentStatus | None = None) -> list[Commitment]:
    return c.commitments.list(status)


@router.post("/commitments/{commitment_id}/prepare")
async def prepare(commitment_id: int, c: Deps) -> Draft:
    """Research and draft the deliverable for a promise I made."""
    return await c.keeper.prepare(commitment_id, c.today())


@router.get("/drafts")
def list_drafts(c: Deps, status: DraftStatus | None = None) -> list[Draft]:
    return c.drafts.list(status)


class DraftEditIn(BaseModel):
    # A newline in the subject would corrupt the email header, so it is rejected up front.
    subject: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[^\r\n]+$"
        ),
    ]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]


@router.put("/drafts/{draft_id}")
def edit_draft(draft_id: int, edit: DraftEditIn, c: Deps) -> Draft:
    """Edit the text of a draft that is still waiting for review."""
    return c.review.edit(draft_id, edit.subject, edit.body)


class ApproveIn(BaseModel):
    to: str = Field(min_length=3, max_length=254)


@router.post("/drafts/{draft_id}/approve")
async def approve(draft_id: int, c: Deps, body: ApproveIn | None = None) -> Draft:
    """Approve a draft. With a recipient, the email is sent first."""
    return await c.review.approve(draft_id, body.to if body else None)


@router.post("/drafts/{draft_id}/reject")
def reject(draft_id: int, c: Deps) -> Draft:
    return c.review.reject(draft_id)


@router.get("/audit")
def audit(c: Deps, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[AuditEvent]:
    """Every outbound request attempt: what left this machine, and what was blocked."""
    return c.audit.recent(limit)


@router.get("/allowlist")
def allowlist(c: Deps) -> list[str]:
    """The only hosts this app may contact."""
    return c.settings.allowed_hosts


class EmailCapability(BaseModel):
    enabled: bool
    sender: str
    recipients: list[str]


class Capabilities(BaseModel):
    email: EmailCapability


@router.get("/capabilities")
def capabilities(c: Deps) -> Capabilities:
    s = c.settings
    return Capabilities(
        email=EmailCapability(
            enabled=s.email_enabled,
            sender=s.email_from if s.email_enabled else "",
            recipients=(s.email_allowed_recipients or [s.email_from]) if s.email_enabled else [],
        )
    )


@router.get("/contacts")
def contacts(c: Deps) -> dict[str, str]:
    """Email addresses Kept has used before, by lowercase person name."""
    return c.contacts.all()
