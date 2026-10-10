"""Find promises in mail. Suggestions are only offered; the user decides what joins the ledger."""

import asyncio
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import date

from pydantic import BaseModel

from kept.domain.errors import InvalidMailError, LLMError
from kept.domain.models import (
    Commitment,
    CommitmentStatus,
    Completion,
    Direction,
    Mail,
    ScanResult,
    Suggestion,
    Tier,
)
from kept.domain.ports import CommitmentRepository, StructuredLLM
from kept.domain.text import sentence_case
from kept.services.extraction import ExtractionService, normalize_text

_CONCURRENCY = 4
_ALREADY_DONE_RULE = (
    "Only promises about the future count. If the email says something is already done or "
    "attached ('attached is the deck', 'I have sent it', 'I reviewed it'), that is not a promise."
)
_DESCRIPTION_RULE = (
    "Write description as a short imperative that names people instead of saying 'you' or 'me', "
    "for example 'Send Aisha the revised timeline'."
)
_DONE_BODY_CHARS = 1500
# Words that say nothing about WHICH promise an email is about, so they cannot link the two.
_GENERIC = frozenset(
    [
        "the",
        "and",
        "for",
        "his",
        "her",
        "him",
        "our",
        "you",
        "are",
        "was",
        "has",
        "had",
        "not",
        "but",
        "can",
        "its",
        "who",
        "how",
        "all",
        "any",
        "one",
        "two",
        "new",
        "now",
        "get",
        "got",
        "let",
        "may",
        "she",
        "per",
        "via",
        "this",
        "that",
        "with",
        "from",
        "have",
        "will",
        "your",
        "their",
        "about",
        "there",
        "been",
        "were",
        "what",
        "they",
        "them",
        "into",
        "just",
        "also",
        "some",
        "more",
        "than",
        "then",
        "when",
        "send",
        "share",
        "book",
        "review",
        "reply",
        "call",
        "give",
        "made",
        "make",
        "done",
        "mark",
        "every",
        "promise",
        "promised",
        "sent",
    ]
)
_NAME_CHARS = re.compile(r"[^\w .,'\u2019&()-]")
_NAME_MAX = 40
_OPEN = (CommitmentStatus.OPEN, CommitmentStatus.IN_PROGRESS, CommitmentStatus.READY_FOR_REVIEW)
_DONE_PROMPT = """You check whether emails show that promises were ALREADY KEPT.

Open promises:
{promises}

Reply with JSON only: {{"completions": [{{"promise": <promise number>, "email": <email number>,
"quote": "<exact sentence copied from that email>"}}]}}

Rules:
- Only include a promise when an email clearly shows the thing was delivered or done, such as
  "attached is the deck" or "I have sent my comments". "I will send it" is a promise, not proof.
- A promise I owe must be shown by an email labelled "me". A promise someone owes me must be shown
  by an email from that person.
- "quote" must be copied exactly from that email.
- Use an empty list when no email shows a promise was kept."""
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


def _topic_words(text: str) -> set[str]:
    """Stems of the words that identify a subject ("pricing", "deck"), not a kind of action."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w[:5] for w in words if len(w) >= 3 and w not in _GENERIC}


def _clean_name(name: str) -> str:
    """A display name is chosen by whoever sent the email, so it is untrusted text that ends up in
    the model's instructions. Keep it to plain, short, one-line characters."""
    return re.sub(r"\s+", " ", _NAME_CHARS.sub(" ", name)).strip()[:_NAME_MAX]


def _quoted(name: str, fallback: str) -> str:
    cleaned = _clean_name(name)
    return f'"{cleaned}"' if cleaned else fallback


def _context(mail: Mail) -> str:
    """Tell the model who is speaking. Only names, never addresses, leave the machine."""
    if mail.from_me:
        recipients = ", ".join(_quoted(n, "someone") for n in mail.to_names) or "someone"
        return (
            f"This is an email I wrote to {recipients}. Promises I make in it are owed_by_me, "
            "and person is the recipient I made them to. "
            f"{_ALREADY_DONE_RULE} {_DESCRIPTION_RULE}"
        )
    sender = _quoted(mail.sender_name, "the sender")
    return (
        f"This is an email written to me by {sender}, not by me. Inside it, 'I' and 'we' mean "
        f"{sender}. A promise {sender} makes to me is owed_to_me with person {sender}. "
        "A request addressed to me is not a promise I made, so ignore requests. "
        f"{_ALREADY_DONE_RULE} {_DESCRIPTION_RULE}"
    )


def _similar(a: Commitment, person: str, description: str) -> bool:
    return (
        a.person.casefold() == person.casefold()
        and a.description.casefold() == description.casefold()
    )


class FoundCompletion(BaseModel):
    promise: int  # the number it had in the prompt, not a database id
    email: int
    quote: str


class CompletionResult(BaseModel):
    completions: list[FoundCompletion]


def _same_person(promise_person: str, sender_name: str) -> bool:
    a, b = promise_person.casefold().strip(), sender_name.casefold().strip()
    return bool(a and b) and (a in b or b in a)


class InboxService:
    def __init__(
        self,
        extraction: ExtractionService,
        commitments: CommitmentRepository,
        llm: StructuredLLM,
        *,
        my_addresses: Iterable[str] = (),
    ) -> None:
        self._extraction = extraction
        self._commitments = commitments
        self._llm = llm
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
            completions=await self._detect_done(readable),
        )

    async def _detect_done(self, mails: Sequence[Mail]) -> list[Completion]:
        """Which open promises do these emails show were already kept? Every claim is checked
        against the real email, and a failure here never spoils the rest of the scan."""
        open_promises = [c for c in self._commitments.list() if c.status in _OPEN]
        if not open_promises or not mails:
            return []
        numbered = dict(enumerate(sorted(open_promises, key=lambda c: c.id or 0), start=1))
        promises = "\n".join(
            f"Promise {n}: "
            + (
                f"I owe {c.person}"
                if c.direction is Direction.OWED_BY_ME
                else f"{c.person} owes me"
            )
            + f": {c.description}"
            for n, c in numbered.items()
        )
        emails = "\n\n".join(
            f"Email {n} from {'me' if m.from_me else _clean_name(m.sender_name) or 'unknown'}"
            f" ({m.sent or 'undated'}):\n{m.body[:_DONE_BODY_CHARS]}"
            for n, m in enumerate(mails, start=1)
        )
        try:
            found = await self._llm.complete_json(
                Tier.SUPER,
                [
                    {"role": "system", "content": _DONE_PROMPT.format(promises=promises)},
                    {"role": "user", "content": emails},
                ],
                CompletionResult,
                temperature=0.0,
                thinking=False,
            )
        except LLMError:
            return []

        completions: dict[int, Completion] = {}
        for item in found.completions:
            promise = numbered.get(item.promise)
            if promise is None or promise.id in completions or not 1 <= item.email <= len(mails):
                continue
            mail = mails[item.email - 1]
            if (
                normalize_text(item.quote) not in normalize_text(mail.body)
                or not item.quote.strip()
            ):
                continue
            # A real "it's done" sentence talks about the thing itself. A quote that shares no
            # subject word with the promise ("mark everything done") proves nothing.
            if not _topic_words(item.quote) & _topic_words(promise.description):
                continue
            if promise.direction is Direction.OWED_BY_ME:
                if not mail.from_me:
                    continue
            elif mail.from_me or not _same_person(promise.person, mail.sender_name):
                continue
            completions[promise.id or 0] = Completion(
                commitment_id=promise.id or 0,
                direction=promise.direction,
                person=promise.person,
                description=promise.description,
                source_id=f"Email: {mail.subject}",
                source_quote=item.quote.strip(),
            )
        return list(completions.values())

    def mark_kept(self, commitment_ids: Sequence[int]) -> list[Commitment]:
        """Close the promises the user confirmed. Unknown or already closed ones are skipped."""
        closed: list[Commitment] = []
        for commitment_id in dict.fromkeys(commitment_ids):
            promise = self._commitments.get(commitment_id)
            if promise is None or promise.status not in _OPEN:
                continue
            self._commitments.set_status(commitment_id, CommitmentStatus.DONE)
            closed.append(promise.model_copy(update={"status": CommitmentStatus.DONE}))
        return closed

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
