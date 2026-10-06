from datetime import UTC, date, datetime, timedelta

import httpx

from kept.adapters.sqlite import Database, SqliteCommitmentRepository, SqliteDraftRepository
from kept.domain.models import Commitment, CommitmentStatus, Direction, Draft
from kept.services.people import PeopleService
from tests.fakes import NOTE, FakeSearch, ScriptedLLM

TODAY = date(2026, 10, 7)
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


class Env:
    def __init__(self) -> None:
        db = Database(":memory:")
        self.commitments = SqliteCommitmentRepository(db)
        self.drafts = SqliteDraftRepository(db)
        self.service = PeopleService(self.commitments, self.drafts)

    def promise(
        self,
        person: str,
        description: str = "Do a thing",
        *,
        direction: Direction = Direction.OWED_BY_ME,
        status: CommitmentStatus = CommitmentStatus.OPEN,
        due: date | None = None,
    ) -> int:
        saved = self.commitments.add(
            Commitment(
                direction=direction,
                person=person,
                description=description,
                status=status,
                due=due,
                source_id="n",
                source_quote="q",
            )
        )
        return saved.id or 0

    def sent_email(self, commitment_id: int, subject: str, when: datetime) -> None:
        draft = self.drafts.add(Draft(commitment_id=commitment_id, subject=subject, body="b"))
        self.drafts.set_sent(draft.id or 0, "x@example.com", when)


def test_a_person_is_one_person_however_their_name_is_cased() -> None:
    env = Env()
    env.promise("priya")
    env.promise("Priya")
    (summary,) = env.service.all(TODAY)
    assert summary.name == "Priya"  # the most recently added spelling
    assert summary.open_by_me == 2


def test_counts_cover_kept_open_overdue_and_both_directions() -> None:
    env = Env()
    env.promise("Priya", status=CommitmentStatus.DONE)
    env.promise("Priya", due=date(2026, 10, 1))  # overdue
    env.promise("Priya", status=CommitmentStatus.DROPPED)  # not counted as made
    env.promise("Priya", direction=Direction.OWED_TO_ME, due=date(2026, 10, 9))
    env.promise("Priya", direction=Direction.OWED_TO_ME, status=CommitmentStatus.DONE)

    summary = env.service.for_person("PRIYA", TODAY)

    assert summary is not None
    assert (summary.promises_by_me, summary.kept_by_me) == (2, 1)
    assert (summary.open_by_me, summary.open_to_me, summary.overdue) == (1, 1, 1)


def test_only_sent_emails_count_and_the_latest_one_is_reported() -> None:
    env = Env()
    first = env.promise("Priya")
    second = env.promise("Priya")
    env.sent_email(first, "Old subject", NOW - timedelta(days=3))
    env.sent_email(second, "Newest subject", NOW)
    draft = env.drafts.add(Draft(commitment_id=first, subject="Never sent", body="b"))
    assert draft.sent_to is None

    summary = env.service.for_person("Priya", TODAY)

    assert summary is not None
    assert summary.emails_sent == 2
    assert (summary.last_subject, summary.last_emailed_at) == ("Newest subject", NOW)


def test_people_are_listed_alphabetically_and_unknown_names_are_none() -> None:
    env = Env()
    for name in ("Zoe", "Marcus", "Dana"):
        env.promise(name)
    assert [p.name for p in env.service.all(TODAY)] == ["Dana", "Marcus", "Zoe"]
    assert env.service.for_person("Nobody", TODAY) is None


def test_context_is_empty_when_there_is_nothing_to_remember() -> None:
    env = Env()
    only = env.promise("Priya")
    assert env.service.context_for("Priya", TODAY, exclude_id=only) == ""
    assert env.service.context_for("Stranger", TODAY) == ""


def test_context_describes_history_without_the_promise_being_drafted() -> None:
    env = Env()
    current = env.promise("Priya", "Send the comparison")
    kept = env.promise("Priya", "Review the pricing page", status=CommitmentStatus.DONE)
    env.promise("Priya", "Share the Q3 deck", direction=Direction.OWED_TO_ME, due=date(2026, 10, 9))
    env.promise("Marcus", "Unrelated")
    env.sent_email(kept, "Pricing review", NOW)

    text = env.service.context_for("Priya", TODAY, exclude_id=current)

    assert text.startswith("History with Priya:")
    assert "you have made Priya 1 promise(s) and kept 1" in text
    assert '"Pricing review" (6 Oct 2026)' in text
    assert 'Priya owes you "Share the Q3 deck", due 9 Oct' in text
    assert "Send the comparison" not in text  # the one being drafted is not history
    assert "Marcus" not in text and "Unrelated" not in text


def test_context_keeps_to_a_handful_of_recent_emails_and_open_items() -> None:
    env = Env()
    current = env.promise("Priya", "Current")
    for i in range(6):
        sent = env.promise("Priya", f"Done {i}", status=CommitmentStatus.DONE)
        env.sent_email(sent, f"Subject {i}", NOW + timedelta(days=i))
        env.promise("Priya", f"Open {i}")
    text = env.service.context_for("Priya", TODAY, exclude_id=current)
    assert text.count("Subject ") == 3 and "Subject 5" in text and "Subject 0" not in text
    assert text.count("Open ") == 4


async def test_the_people_endpoint_summarises_everyone_in_the_workspace(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    await client.post("/api/notes", json={"source_id": "n1", "text": NOTE})
    people = (await client.get("/api/people")).json()
    assert [(p["name"], p["open_by_me"], p["emails_sent"]) for p in people] == [("Priya", 1, 0)]
