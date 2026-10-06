"""What Kept remembers about each person: the history that makes a follow-up a follow-up."""

from datetime import date, timedelta

from kept.domain.models import Commitment, CommitmentStatus, Direction, Draft, PersonSummary
from kept.domain.ports import CommitmentRepository, DraftRepository

_RECENT_EMAILS = 3
_REMIND_WITHIN_DAYS = 3
_OPEN_ITEMS = 4
_CLOSED = (CommitmentStatus.DONE, CommitmentStatus.DROPPED)


def _is_open(commitment: Commitment) -> bool:
    return commitment.status not in _CLOSED


def _key(name: str) -> str:
    return name.strip().casefold()


class PeopleService:
    def __init__(self, commitments: CommitmentRepository, drafts: DraftRepository) -> None:
        self._commitments = commitments
        self._drafts = drafts

    def _sent_by_person(self, commitments: list[Commitment]) -> dict[str, list[Draft]]:
        person_of = {c.id: _key(c.person) for c in commitments}
        sent: dict[str, list[Draft]] = {}
        for draft in self._drafts.list():
            if draft.sent_to and draft.sent_at and draft.commitment_id in person_of:
                sent.setdefault(person_of[draft.commitment_id], []).append(draft)
        for drafts in sent.values():
            drafts.sort(key=lambda d: d.sent_at or d.created_at, reverse=True)
        return sent

    def all(self, today: date) -> list[PersonSummary]:
        commitments = self._commitments.list()
        sent = self._sent_by_person(commitments)
        groups: dict[str, list[Commitment]] = {}
        for c in commitments:
            groups.setdefault(_key(c.person), []).append(c)
        return [
            self._summarise(items, sent.get(key, []), today)
            for key, items in sorted(groups.items())
        ]

    def for_person(self, name: str, today: date) -> PersonSummary | None:
        return next((s for s in self.all(today) if _key(s.name) == _key(name)), None)

    @staticmethod
    def _summarise(items: list[Commitment], sent: list[Draft], today: date) -> PersonSummary:
        mine = [c for c in items if c.direction is Direction.OWED_BY_ME]
        counted = [c for c in mine if c.status is not CommitmentStatus.DROPPED]
        open_ = [c for c in items if _is_open(c)]
        latest = sent[0] if sent else None
        return PersonSummary(
            name=items[-1].person,  # the most recently added spelling
            promises_by_me=len(counted),
            kept_by_me=sum(c.status is CommitmentStatus.DONE for c in counted),
            open_by_me=sum(c.direction is Direction.OWED_BY_ME for c in open_),
            open_to_me=sum(c.direction is Direction.OWED_TO_ME for c in open_),
            overdue=sum(c.due is not None and c.due < today for c in open_),
            emails_sent=len(sent),
            last_emailed_at=latest.sent_at if latest else None,
            last_subject=latest.subject if latest else None,
        )

    def context_for(self, name: str, today: date, exclude_id: int | None = None) -> str:
        """A few plain sentences for the drafting prompt. Empty when nothing is known."""
        commitments = self._commitments.list()
        key = _key(name)
        theirs = [c for c in commitments if _key(c.person) == key]
        sent = self._sent_by_person(commitments).get(key, [])
        lines: list[str] = []

        made = [c for c in theirs if c.direction is Direction.OWED_BY_ME and c.id != exclude_id]
        made = [c for c in made if c.status is not CommitmentStatus.DROPPED]
        if made:
            kept = sum(c.status is CommitmentStatus.DONE for c in made)
            lines.append(
                f"- Besides this one, you have made {name} {len(made)} promise(s) and kept {kept}."
            )
        if sent:
            recent = "; ".join(
                f'"{d.subject}" ({d.sent_at:%-d %b %Y})' for d in sent[:_RECENT_EMAILS] if d.sent_at
            )
            lines.append(f"- Emails you have already sent {name}: {recent}.")
        open_items = [c for c in theirs if c.id != exclude_id and _is_open(c)][:_OPEN_ITEMS]
        if open_items:
            described = "; ".join(self._open_item(c, name) for c in open_items)
            lines.append(f"- Still open between you: {described}.")
        return f"History with {name}:\n" + "\n".join(lines) if lines else ""

    def reminders_for(
        self, name: str, today: date, exclude_id: int | None = None
    ) -> list[Commitment]:
        """Open promises they owe me that are overdue or due within a few days, soonest first."""
        cutoff = today + timedelta(days=_REMIND_WITHIN_DAYS)
        due_soon = [
            c
            for c in self._commitments.list()
            if _key(c.person) == _key(name)
            and c.direction is Direction.OWED_TO_ME
            and c.id != exclude_id
            and _is_open(c)
            and c.due is not None
            and c.due <= cutoff
        ]
        return sorted(due_soon, key=lambda c: (c.due or cutoff, c.id or 0))

    @staticmethod
    def _open_item(c: Commitment, name: str) -> str:
        who = f"you owe {name}" if c.direction is Direction.OWED_BY_ME else f"{name} owes you"
        due = f", due {c.due:%-d %b}" if c.due else ""
        return f'{who} "{c.description}"{due}'
