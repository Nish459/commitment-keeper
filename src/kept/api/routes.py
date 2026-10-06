from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field, StringConstraints

from kept.container import Container
from kept.domain.errors import EmailNotConfiguredError
from kept.domain.models import (
    Attachment,
    AuditEvent,
    Commitment,
    CommitmentStatus,
    Direction,
    Draft,
    DraftStatus,
    PersonSummary,
    utcnow,
)
from kept.services.attachments import MAX_FILE_BYTES
from kept.services.calendar import build_ics
from kept.services.keeper import CommitmentNotFoundError
from kept.services.planner import WeekCheck
from kept.services.sweep import SweepResult

router = APIRouter(prefix="/api")

# Trimmed, non-empty, no line breaks: safe to put in an email header or a one-line field.
OneLine = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^[^\r\n]+$")
]


def get_container(request: Request) -> Container:
    """This request's workspace: this visitor's own in demo mode, otherwise the single one."""
    workspace: Container | None = getattr(request.state, "workspace", None)
    if workspace is not None:
        return workspace
    container: Container = request.app.state.container
    return container


Deps = Annotated[Container, Depends(get_container)]


class NoteIn(BaseModel):
    source_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=50_000)


@router.post("/notes")
async def ingest_note(note: NoteIn, c: Deps) -> list[Commitment]:
    """Extract and store the commitments found in a note."""
    async with c.guarded("notes", len(note.text)):
        return await c.extraction.extract(note.source_id, note.text, c.today())


class PromiseIn(BaseModel):
    direction: Direction
    person: Annotated[OneLine, Field(max_length=100)]
    description: Annotated[OneLine, Field(max_length=300)]
    due: date | None = None


@router.post("/commitments", status_code=201)
async def add_promise(promise: PromiseIn, c: Deps) -> Commitment:
    """Add one promise by hand. No model is involved, so it is instant."""
    async with c.guarded("manual"):
        return c.manual.add(promise.direction, promise.person, promise.description, promise.due)


@router.get("/commitments")
def list_commitments(c: Deps, status: CommitmentStatus | None = None) -> list[Commitment]:
    return c.commitments.list(status)


@router.get("/commitments/{commitment_id}/calendar.ics")
def calendar(commitment_id: int, c: Deps) -> Response:
    """A calendar file for a promise's deadline, ready to import into any calendar app."""
    commitment = c.commitments.get(commitment_id)
    if commitment is None:
        raise CommitmentNotFoundError(f"Commitment {commitment_id} not found")
    return Response(
        build_ics(commitment, utcnow()),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="promise-{commitment_id}.ics"'},
    )


@router.post("/commitments/{commitment_id}/prepare")
async def prepare(commitment_id: int, c: Deps) -> Draft:
    """Research and draft the deliverable for a promise I made."""
    async with c.guarded("drafts"):
        return await c.keeper.prepare(commitment_id, c.today())


@router.post("/sweep")
async def sweep(c: Deps) -> SweepResult:
    """Draft everything that is overdue or due within three days and has no draft yet."""
    return await c.sweep.run(c.today())


@router.post("/week-check")
async def week_check(c: Deps) -> WeekCheck:
    """Nemotron Ultra reviews every open promise for conflicts, dependencies and risks."""
    async with c.guarded("checks"):
        return await c.planner.check_week(c.today())


@router.get("/drafts")
def list_drafts(c: Deps, status: DraftStatus | None = None) -> list[Draft]:
    return c.drafts.list(status)


class DraftEditIn(BaseModel):
    # A newline in the subject would corrupt the email header, so it is rejected up front.
    subject: Annotated[OneLine, Field(max_length=200)]
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


def _require_email(c: Container) -> None:
    if not c.settings.email_enabled:
        raise EmailNotConfiguredError(
            "Attachments are only used when sending email, which isn't set up here."
        )


@router.get("/drafts/{draft_id}/attachments")
def list_attachments(draft_id: int, c: Deps) -> list[Attachment]:
    return c.attachments.list(draft_id)


@router.post("/drafts/{draft_id}/attachments", status_code=201)
async def add_attachment(draft_id: int, file: UploadFile, c: Deps) -> Attachment:
    """Attach a file to a pending draft. It is only ever sent with that draft's email."""
    _require_email(c)
    data = await file.read(MAX_FILE_BYTES + 1)  # one byte over the limit is enough to refuse it
    return c.attachments.add(draft_id, file.filename or "attachment", file.content_type, data)


@router.delete("/drafts/{draft_id}/attachments/{attachment_id}", status_code=204)
def remove_attachment(draft_id: int, attachment_id: int, c: Deps) -> Response:
    if not c.attachments.remove(draft_id, attachment_id):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return Response(status_code=204)


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
    access_code: bool  # a code exists that lifts the demo's limits
    unlocked: bool  # this workspace already entered it


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
        access_code=s.demo_mode and bool(s.demo_access_code.get_secret_value()),
        unlocked=bool(c.guard and c.guard.unlocked),
    )


class AccessIn(BaseModel):
    code: Annotated[str, StringConstraints(min_length=1, max_length=200)]


@router.post("/demo/access")
def unlock_demo(body: AccessIn, c: Deps) -> dict[str, bool]:
    """Enter the access code to lift this demo workspace's limits."""
    if c.guard is None:
        raise HTTPException(status_code=404, detail="Not found")
    c.guard.try_unlock(body.code, c.settings.demo_access_code.get_secret_value())
    return {"unlocked": True}


@router.get("/people")
def people(c: Deps) -> list[PersonSummary]:
    """What Kept remembers about each person: promises kept, open items, emails sent."""
    return c.people.all(c.today())


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
