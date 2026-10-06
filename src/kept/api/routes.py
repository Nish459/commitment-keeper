from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, StringConstraints

from kept.container import Container
from kept.demo import COOKIE_NAME, SessionManager
from kept.domain.models import AuditEvent, Commitment, CommitmentStatus, Draft, DraftStatus

router = APIRouter(prefix="/api")


async def get_container(request: Request, response: Response) -> Container:
    """The workspace for this request: the single one, or this visitor's own in demo mode."""
    sessions: SessionManager | None = request.app.state.sessions
    if sessions is None:
        container: Container = request.app.state.container
        return container
    await sessions.reap()
    session_id, workspace, _ = sessions.get_or_create(request.cookies.get(COOKIE_NAME))
    response.set_cookie(
        COOKIE_NAME,
        session_id,
        max_age=workspace.settings.demo_session_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return workspace


Deps = Annotated[Container, Depends(get_container)]


class NoteIn(BaseModel):
    source_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=50_000)


@router.post("/notes")
async def ingest_note(note: NoteIn, c: Deps) -> list[Commitment]:
    """Extract and store the commitments found in a note."""
    async with c.guarded("notes", len(note.text)):
        return await c.extraction.extract(note.source_id, note.text, c.today())


@router.get("/commitments")
def list_commitments(c: Deps, status: CommitmentStatus | None = None) -> list[Commitment]:
    return c.commitments.list(status)


@router.post("/commitments/{commitment_id}/prepare")
async def prepare(commitment_id: int, c: Deps) -> Draft:
    """Research and draft the deliverable for a promise I made."""
    async with c.guarded("drafts"):
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
    demo: bool


@router.get("/capabilities")
def capabilities(c: Deps) -> Capabilities:
    s = c.settings
    return Capabilities(
        email=EmailCapability(
            enabled=s.email_enabled,
            sender=s.email_from if s.email_enabled else "",
            recipients=(s.email_allowed_recipients or [s.email_from]) if s.email_enabled else [],
        ),
        demo=s.demo_mode,
    )


@router.get("/contacts")
def contacts(c: Deps) -> dict[str, str]:
    """Email addresses Kept has used before, by lowercase person name."""
    return c.contacts.all()


class Profile(BaseModel):
    # Empty clears the saved name. No line breaks: the name goes into the email signature.
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=100, pattern=r"^[^\r\n]*$")
    ]


@router.get("/profile")
def get_profile(c: Deps) -> Profile:
    """Who Kept signs emails as: the saved name, else KEPT_USER_NAME, else nobody."""
    return Profile(name=c.profile.get_name() or c.settings.user_name)


@router.put("/profile")
def save_profile(profile: Profile, c: Deps) -> Profile:
    c.profile.set_name(profile.name)
    return Profile(name=c.profile.get_name() or c.settings.user_name)
