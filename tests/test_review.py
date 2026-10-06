from datetime import UTC, datetime

import pytest

from kept.adapters.sqlite import (
    Database,
    SqliteCommitmentRepository,
    SqliteContactRepository,
    SqliteDraftRepository,
)
from kept.domain.errors import EmailError, EmailNotConfiguredError, RecipientNotAllowedError
from kept.domain.models import Commitment, CommitmentStatus, Direction, Draft, DraftStatus
from kept.services.review import DraftAlreadyReviewedError, DraftNotFoundError, ReviewService

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


class FakeSender:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            raise EmailError("Sending failed: refused")
        self.sent.append((to, subject, body))


class Env:
    def __init__(self, sender: FakeSender | None = None, allowed: tuple[str, ...] = ()) -> None:
        db = Database(":memory:")
        self.commitments = SqliteCommitmentRepository(db)
        self.drafts = SqliteDraftRepository(db)
        self.contacts = SqliteContactRepository(db)
        self.sender = sender
        self.service = ReviewService(
            self.commitments,
            self.drafts,
            self.contacts,
            sender=sender,
            sender_address="me@example.com",
            allowed_recipients=allowed,
            clock=lambda: NOW,
        )
        commitment = self.commitments.add(
            Commitment(
                direction=Direction.OWED_BY_ME,
                person="Priya",
                description="Send it",
                status=CommitmentStatus.READY_FOR_REVIEW,
                source_id="n",
                source_quote="q",
            )
        )
        draft = self.drafts.add(Draft(commitment_id=commitment.id or 0, subject="S", body="B"))
        self.commitment_id = commitment.id or 0
        self.draft_id = draft.id or 0

    def commitment_status(self) -> CommitmentStatus:
        stored = self.commitments.get(self.commitment_id)
        assert stored is not None
        return stored.status


async def test_approve_marks_draft_approved_and_commitment_done() -> None:
    env = Env()
    assert (await env.service.approve(env.draft_id)).status is DraftStatus.APPROVED
    assert env.commitment_status() is CommitmentStatus.DONE


def test_reject_reopens_commitment() -> None:
    env = Env()
    assert env.service.reject(env.draft_id).status is DraftStatus.REJECTED
    assert env.commitment_status() is CommitmentStatus.OPEN


async def test_cannot_review_twice_or_unknown() -> None:
    env = Env()
    await env.service.approve(env.draft_id)
    with pytest.raises(DraftAlreadyReviewedError):
        env.service.reject(env.draft_id)
    with pytest.raises(DraftNotFoundError):
        await env.service.approve(999)


async def test_approve_with_recipient_sends_records_and_remembers_contact() -> None:
    sender = FakeSender()
    env = Env(sender, allowed=("priya@acme.com",))
    draft = await env.service.approve(env.draft_id, "Priya@Acme.com")

    assert sender.sent == [("priya@acme.com", "S", "B")]
    assert (draft.sent_to, draft.sent_at) == ("priya@acme.com", NOW)
    assert env.commitment_status() is CommitmentStatus.DONE
    assert env.contacts.get("Priya") == "priya@acme.com"


async def test_recipient_not_on_allowlist_is_refused_and_nothing_changes() -> None:
    sender = FakeSender()
    env = Env(sender, allowed=("priya@acme.com",))
    with pytest.raises(RecipientNotAllowedError):
        await env.service.approve(env.draft_id, "someone@else.com")
    assert sender.sent == []
    assert env.drafts.get(env.draft_id) is not None
    assert env.commitment_status() is CommitmentStatus.READY_FOR_REVIEW


async def test_default_recipient_policy_allows_only_the_sender_address() -> None:
    sender = FakeSender()
    env = Env(sender)
    with pytest.raises(RecipientNotAllowedError):
        await env.service.approve(env.draft_id, "priya@acme.com")
    await env.service.approve(env.draft_id, "me@example.com")
    assert [to for to, _, _ in sender.sent] == ["me@example.com"]


async def test_failed_send_leaves_draft_pending_so_it_can_be_retried() -> None:
    env = Env(FakeSender(fail=True), allowed=("priya@acme.com",))
    with pytest.raises(EmailError):
        await env.service.approve(env.draft_id, "priya@acme.com")
    stored = env.drafts.get(env.draft_id)
    assert stored is not None
    assert (stored.status, stored.sent_to) == (DraftStatus.PENDING, None)
    assert env.commitment_status() is CommitmentStatus.READY_FOR_REVIEW
    assert env.contacts.get("Priya") is None


async def test_sending_without_email_configured_is_refused() -> None:
    env = Env()
    with pytest.raises(EmailNotConfiguredError):
        await env.service.approve(env.draft_id, "priya@acme.com")


async def test_edit_replaces_text_of_a_pending_draft_and_sends_the_edit() -> None:
    sender = FakeSender()
    env = Env(sender, allowed=("priya@acme.com",))
    edited = env.service.edit(env.draft_id, "New subject", "New body")
    assert (edited.subject, edited.body) == ("New subject", "New body")
    assert (env.drafts.get(env.draft_id) or edited).body == "New body"

    await env.service.approve(env.draft_id, "priya@acme.com")
    assert sender.sent == [("priya@acme.com", "New subject", "New body")]


async def test_edit_is_refused_once_reviewed_or_unknown() -> None:
    env = Env()
    await env.service.approve(env.draft_id)
    with pytest.raises(DraftAlreadyReviewedError):
        env.service.edit(env.draft_id, "s", "b")
    with pytest.raises(DraftNotFoundError):
        env.service.edit(999, "s", "b")
