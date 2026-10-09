"""Find promises in mail. Suggestions are only offered; the user decides what joins the ledger."""

import asyncio
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import date

from kept.domain.errors import InvalidMailError, LLMError
from kept.domain.models import Commitment, Mail, ScanResult, Suggestion
from kept.domain.ports import CommitmentRepository
from kept.domain.text import sentence_case
from kept.services.extraction import ExtractionService

_CONCURRENCY = 4
_DESCRIPTION_RULE = (
    "Write description as a short imperative that names people instead of saying 'you' or 'me', "
    "for example 'Send Aisha the revised timeline'."
)
_AUTOMATED_SENDER = re.compile(r"no-?reply|do-?not-?reply|newsletter|notifications?@|mailer-daemon")


def infer_owner(mails: Sequence[Mail]) -> str | None:
    """The mailbox owner's address: the one that shows up in the most messages. A mailbox export
    is full of the owner's own address, either as sender or recipient. Needs at least two
    messages to be a guess worth making."""
    if len(mails) < 2:
        return None
    counts: Counter[str] = Counter()
    for mail in mails:
        counts.update({mail.sender_address, *mail.to_addresses} - {""})
    if not counts:
        return None
    address, seen = counts.most_common(1)[0]
    return address if seen >= max(2, len(mails) // 2) else None


def _context(mail: Mail) -> str:
    """Tell the model who is speaking. Only names, never addresses, leave the machine."""
    if mail.from_me:
        recipients = ", ".join(mail.to_names) or "someone"
        return (
            f"This is an email I wrote to {recipients}. Promises I make in it are owed_by_me, "
            "and person is the recipient I made them to. "
            f"{_DESCRIPTION_RULE}"
        )
    sender = mail.sender_name or "the sender"
    return (
        f"This is an email written to me by {sender}, not by me. Inside it, 'I' and 'we' mean "
        f"{sender}. A promise {sender} makes to me is owed_to_me with person '{sender}'. "
        "A request addressed to me is not a promise I made, so ignore requests. "
        f"{_DESCRIPTION_RULE}"
    )


def _similar(a: Commitment, person: str, description: str) -> bool:
    return (
        a.person.casefold() == person.casefold()
        and a.description.casefold() == description.casefold()
    )


class InboxService:
    def __init__(
        self,
        extraction: ExtractionService,
        commitments: CommitmentRepository,
        *,
        my_addresses: Iterable[str] = (),
    ) -> None:
        self._extraction = extraction
        self._commitments = commitments
        self._mine = {a.strip().lower() for a in my_addresses if a.strip()}

    def _mark_mine(self, mails: Sequence[Mail], owner: str | None) -> list[Mail]:
        owners = self._mine or ({owner} if owner else set())
        return [
            replace(mail, from_me=mail.sender_address in owners) if mail.from_me is None else mail
            for mail in mails
        ]

    async def scan(
        self,
        mails: Sequence[Mail],
        today: date,
        *,
        max_emails: int,
        mailbox_owner: str | None = None,
    ) -> ScanResult:
        """Read the newest `max_emails` messages and suggest the promises in them."""
        if not mails:
            raise InvalidMailError("No emails were found in those files.")
        owner = mailbox_owner or infer_owner(mails)
        newest = sorted(mails, key=lambda m: m.sent or date.min, reverse=True)[:max_emails]
        marked = self._mark_mine(newest, owner)
        readable = [
            m for m in marked if m.body.strip() and not _AUTOMATED_SENDER.search(m.sender_address)
        ]

        gate = asyncio.Semaphore(_CONCURRENCY)

        async def read(mail: Mail) -> list[Commitment] | None:
            async with gate:
                try:
                    return await self._extraction.propose(
                        f"Email: {mail.subject}",
                        mail.body,
                        min(mail.sent or today, today),
                        context=_context(mail),
                    )
                except LLMError:
                    return None

        outcomes = await asyncio.gather(*(read(m) for m in readable))
        if readable and all(outcome is None for outcome in outcomes):
            raise LLMError("Kept couldn't read your mail right now. Try again in a moment.")

        existing = self._commitments.list()
        suggestions: list[Suggestion] = []
        for found in outcomes:
            for item in found or []:
                if any(_similar(c, item.person, item.description) for c in existing):
                    continue
                suggestions.append(
                    Suggestion(
                        direction=item.direction,
                        person=item.person,
                        description=item.description,
                        due=item.due,
                        source_id=item.source_id,
                        source_quote=item.source_quote,
                    )
                )
        return ScanResult(
            emails_read=len(readable),
            emails_skipped=len(mails) - len(readable),
            suggestions=suggestions,
        )

    def accept(self, suggestions: Sequence[Suggestion]) -> list[Commitment]:
        """Add the suggestions the user picked, skipping any already in the ledger."""
        existing = {(c.source_id, c.source_quote.casefold()) for c in self._commitments.list()}
        saved: list[Commitment] = []
        for item in suggestions:
            key = (item.source_id, item.source_quote.casefold())
            if key in existing:
                continue
            existing.add(key)
            saved.append(
                self._commitments.add(
                    Commitment(
                        direction=item.direction,
                        person=sentence_case(item.person),
                        description=sentence_case(item.description),
                        due=item.due,
                        source_id=item.source_id,
                        source_quote=item.source_quote.strip(),
                    )
                )
            )
        return saved
