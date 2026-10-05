"""The user's decision on a prepared draft. Approval is the only way a promise becomes done."""

from collections.abc import Callable, Collection
from datetime import datetime

from kept.domain.errors import EmailNotConfiguredError, RecipientNotAllowedError
from kept.domain.models import CommitmentStatus, Draft, DraftStatus, utcnow
from kept.domain.ports import CommitmentRepository, ContactRepository, DraftRepository, EmailSender
from kept.domain.recipients import is_recipient_allowed, normalize_address


class DraftNotFoundError(Exception):
    pass


class DraftAlreadyReviewedError(Exception):
    pass


class ReviewService:
    def __init__(
        self,
        commitments: CommitmentRepository,
        drafts: DraftRepository,
        contacts: ContactRepository,
        *,
        sender: EmailSender | None = None,
        sender_address: str = "",
        allowed_recipients: Collection[str] = (),
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._commitments = commitments
        self._drafts = drafts
        self._contacts = contacts
        self._sender = sender
        self._sender_address = sender_address
        self._allowed = tuple(allowed_recipients)
        self._clock = clock

    async def approve(self, draft_id: int, to: str | None = None) -> Draft:
        """Approve a draft. With `to`, email it first; a failed send leaves it pending."""
        draft = self._pending(draft_id)
        if to is not None:
            await self._send(draft, to)
            draft = self._drafts.get(draft_id) or draft
        self._drafts.set_status(draft_id, DraftStatus.APPROVED)
        self._commitments.set_status(draft.commitment_id, CommitmentStatus.DONE)
        return draft.model_copy(update={"status": DraftStatus.APPROVED})

    def reject(self, draft_id: int) -> Draft:
        draft = self._pending(draft_id)
        self._drafts.set_status(draft_id, DraftStatus.REJECTED)
        self._commitments.set_status(draft.commitment_id, CommitmentStatus.OPEN)
        return draft.model_copy(update={"status": DraftStatus.REJECTED})

    def _pending(self, draft_id: int) -> Draft:
        draft = self._drafts.get(draft_id)
        if draft is None:
            raise DraftNotFoundError(f"Draft {draft_id} not found")
        if draft.status is not DraftStatus.PENDING:
            raise DraftAlreadyReviewedError(f"Draft {draft_id} is already {draft.status.value}")
        return draft

    async def _send(self, draft: Draft, to: str) -> None:
        if self._sender is None:
            raise EmailNotConfiguredError(
                "Email isn't set up. Approve without sending, or copy it."
            )
        address = normalize_address(to)
        if address is None or not is_recipient_allowed(
            address, self._allowed, self._sender_address
        ):
            raise RecipientNotAllowedError(
                f"Kept isn't allowed to email {to}. Add it to KEPT_EMAIL_ALLOWED_RECIPIENTS first."
            )
        await self._sender.send(address, draft.subject, draft.body)
        assert draft.id is not None
        self._drafts.set_sent(draft.id, address, self._clock())
        commitment = self._commitments.get(draft.commitment_id)
        if commitment is not None:
            self._contacts.set(commitment.person, address)
