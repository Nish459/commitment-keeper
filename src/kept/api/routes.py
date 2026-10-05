from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

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


@router.post("/drafts/{draft_id}/approve")
def approve(draft_id: int, c: Deps) -> Draft:
    return c.review.approve(draft_id)


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
    return sorted(c.settings.egress_allowlist)
