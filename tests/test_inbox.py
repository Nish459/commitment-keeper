from datetime import date
from email.message import EmailMessage
from pathlib import Path

import httpx
import pytest

from kept.adapters.mailfiles import parse_mail_files, strip_quoted
from kept.adapters.sqlite import Database, SqliteCommitmentRepository
from kept.config import Settings
from kept.demo import build_session_manager
from kept.domain.errors import InvalidMailError, LLMError
from kept.domain.models import Commitment, Direction, Mail, Suggestion
from kept.services.extraction import ExtractedCommitment, ExtractionResult, ExtractionService
from kept.services.inbox import InboxService, infer_owner
from kept.services.sample_inbox import sample_mails
from tests.fakes import FakeSearch, ScriptedLLM
from tests.helpers import demo_client

TODAY = date(2026, 10, 7)  # a Wednesday
QUOTE = "I'll send the signed NDA by Thursday"


def _eml(
    sender: str = "Priya Raman <priya@acme.example>",
    to: str = "You <you@kept.example>",
    subject: str = "Terms",
    body: str = f"Thanks. {QUOTE}.",
    sent: str = "Tue, 06 Oct 2026 09:30:00 +0000",
    html: str | None = None,
) -> bytes:
    message = EmailMessage()
    message["From"], message["To"], message["Subject"], message["Date"] = sender, to, subject, sent
    message.set_content(body)
    if html is not None:
        message.add_alternative(html, subtype="html")
    return message.as_bytes()


def _mail(**overrides: object) -> Mail:
    base: dict[str, object] = {
        "subject": "Terms",
        "sender_name": "Priya Raman",
        "sender_address": "priya@acme.example",
        "to_names": ("You",),
        "to_addresses": ("you@kept.example",),
        "sent": date(2026, 10, 6),
        "body": f"Thanks. {QUOTE}.",
    }
    return Mail(**{**base, **overrides})  # type: ignore[arg-type]


def _extraction(due_phrase: str | None = "by Thursday", person: str = "Priya") -> ExtractionResult:
    return ExtractionResult(
        commitments=[
            ExtractedCommitment(
                direction=Direction.OWED_TO_ME,
                person=person,
                description="send the signed NDA",
                due_phrase=due_phrase,
                source_quote=QUOTE,
            )
        ]
    )


def _service(
    llm: ScriptedLLM, repo: SqliteCommitmentRepository | None = None, **kw: object
) -> tuple[InboxService, SqliteCommitmentRepository]:
    repo = repo or SqliteCommitmentRepository(Database(":memory:"))
    return InboxService(ExtractionService(llm, repo), repo, **kw), repo  # type: ignore[arg-type]


# ---- reading mail files ----


def test_an_eml_file_becomes_a_mail_with_names_date_and_text() -> None:
    [mail] = parse_mail_files([("a.eml", _eml())])
    assert (mail.sender_name, mail.sender_address) == ("Priya Raman", "priya@acme.example")
    assert (mail.to_names, mail.to_addresses) == (("You",), ("you@kept.example",))
    assert mail.sent == date(2026, 10, 6)
    assert mail.subject == "Terms"
    assert QUOTE in mail.body


def test_a_missing_display_name_falls_back_to_a_readable_guess() -> None:
    [mail] = parse_mail_files([("a.eml", _eml(sender="priya.raman+news@acme.example"))])
    assert mail.sender_name == "Priya Raman"


def test_html_only_mail_is_reduced_to_text_without_scripts_or_styles() -> None:
    html = (
        "<html><style>p{color:red}</style><script>alert(1)</script>"
        f"<body><p>Hello</p><p>{QUOTE}.</p></body></html>"
    )
    message = EmailMessage()
    message["From"], message["Subject"] = "Sam <sam@vendor.example>", "Quote"
    message.set_content(html, subtype="html")
    [mail] = parse_mail_files([("a.eml", message.as_bytes())])
    assert QUOTE in mail.body
    assert "alert" not in mail.body and "color:red" not in mail.body and "<p>" not in mail.body


def test_quoted_replies_are_dropped_so_old_promises_are_not_found_again() -> None:
    thread = (
        "Sounds good, thanks.\n\n"
        "On Mon, 5 Oct 2026, Priya Raman <priya@acme.example> wrote:\n"
        "> I'll send the old report by Friday.\n"
    )
    assert strip_quoted(thread) == "Sounds good, thanks."
    assert strip_quoted("Fine.\n> quoted line\nLast line") == "Fine.\nLast line"


def test_attachments_are_ignored_and_only_the_message_text_is_read() -> None:
    message = EmailMessage()
    message["From"], message["Subject"] = "Priya <priya@acme.example>", "Files"
    message.set_content("See the note.")
    message.add_attachment(b"%PDF-secret", maintype="application", subtype="pdf", filename="x.pdf")
    [mail] = parse_mail_files([("a.eml", message.as_bytes())])
    assert mail.body == "See the note."


def test_an_mbox_file_yields_every_message() -> None:
    first = _eml(subject="One").replace(b"\n", b"\r\n")
    second = _eml(subject="Two", body="Short note.").replace(b"\n", b"\r\n")
    mbox = b"From a@b Tue Oct  6 09:30:00 2026\n" + first + b"\nFrom a@b Tue Oct  6 10:30:00 2026\n"
    mbox += second + b"\n"
    mails = parse_mail_files([("inbox.mbox", mbox)])
    assert [m.subject for m in mails] == ["One", "Two"]


def test_only_eml_and_mbox_are_accepted() -> None:
    with pytest.raises(InvalidMailError, match=r"notes\.pdf: use \.eml or \.mbox"):
        parse_mail_files([("notes.pdf", b"x")])


def test_a_file_that_is_not_email_yields_nothing_rather_than_crashing() -> None:
    assert parse_mail_files([("junk.eml", b"just some words\n")]) == []


# ---- who owns the mailbox ----


def test_the_owner_is_the_address_that_appears_in_most_messages() -> None:
    mails = [
        _mail(sender_address="priya@acme.example"),
        _mail(sender_address="you@kept.example", to_addresses=("sam@vendor.example",)),
        _mail(sender_address="tom@northwind.example"),
    ]
    assert infer_owner(mails) == "you@kept.example"


def test_one_message_or_no_clear_owner_means_unknown() -> None:
    assert infer_owner([_mail()]) is None
    scattered = [
        _mail(sender_address="a@x.example", to_addresses=("b@x.example",)),
        _mail(sender_address="c@x.example", to_addresses=("d@x.example",)),
        _mail(sender_address="e@x.example", to_addresses=("f@x.example",)),
    ]
    assert infer_owner(scattered) is None


# ---- scanning ----


async def test_a_scan_suggests_promises_without_saving_any() -> None:
    llm = ScriptedLLM()
    llm.responses[ExtractionResult] = _extraction()
    service, repo = _service(llm)
    result = await service.scan([_mail()], TODAY, max_emails=10)
    assert result.emails_read == 1
    [suggestion] = result.suggestions
    assert (suggestion.person, suggestion.direction) == ("Priya", Direction.OWED_TO_ME)
    assert suggestion.source_id == "Email: Terms"
    assert suggestion.due == date(2026, 10, 8)
    assert repo.list() == []


async def test_a_deadline_is_worked_out_from_when_the_email_was_sent() -> None:
    llm = ScriptedLLM()
    llm.responses[ExtractionResult] = _extraction()
    service, _ = _service(llm)
    sent_last_week = _mail(sent=date(2026, 9, 28))  # a Monday: "by Thursday" was 1 Oct
    [suggestion] = (await service.scan([sent_last_week], TODAY, max_emails=10)).suggestions
    assert suggestion.due == date(2026, 10, 1)


async def test_the_model_is_told_who_is_speaking_and_never_sees_addresses() -> None:
    llm = ScriptedLLM()
    llm.responses[ExtractionResult] = ExtractionResult(commitments=[])
    service, _ = _service(llm, my_addresses=["you@kept.example"])
    received = _mail()
    sent = _mail(
        sender_name="You",
        sender_address="you@kept.example",
        to_names=("Aisha Khan",),
        to_addresses=("aisha@northwind.example",),
    )
    await service.scan([received, sent], TODAY, max_emails=10)
    prompts = "\n".join(llm.prompts)
    assert "written to me by Priya Raman" in prompts
    assert "I wrote to Aisha Khan" in prompts
    assert "@" not in prompts


async def test_the_owner_is_guessed_from_the_mailbox_when_not_configured() -> None:
    llm = ScriptedLLM()
    llm.responses[ExtractionResult] = ExtractionResult(commitments=[])
    service, _ = _service(llm)
    mails = [
        _mail(),
        _mail(
            sender_address="you@kept.example",
            sender_name="You",
            to_names=("Tom",),
            to_addresses=("tom@northwind.example",),
        ),
        _mail(sender_address="sam@vendor.example", sender_name="Sam"),
    ]
    await service.scan(mails, TODAY, max_emails=10)
    assert any("I wrote to Tom" in p for p in llm.prompts)


async def test_automated_and_empty_mail_is_skipped_and_counted() -> None:
    llm = ScriptedLLM()
    llm.responses[ExtractionResult] = ExtractionResult(commitments=[])
    service, _ = _service(llm)
    mails = [
        _mail(),
        _mail(sender_address="newsletter@news.example"),
        _mail(sender_address="noreply@bank.example"),
        _mail(body="   "),
    ]
    result = await service.scan(mails, TODAY, max_emails=10)
    assert (result.emails_read, result.emails_skipped) == (1, 3)
    assert len(llm.prompts) == 1


async def test_only_the_newest_emails_are_read() -> None:
    llm = ScriptedLLM()
    llm.responses[ExtractionResult] = ExtractionResult(commitments=[])
    service, _ = _service(llm)
    mails = [_mail(sent=date(2026, 9, d), subject=f"m{d}") for d in range(1, 8)]
    result = await service.scan(mails, TODAY, max_emails=3)
    assert result.emails_read == 3 and result.emails_skipped == 4


async def test_a_promise_already_in_the_ledger_is_not_suggested_again() -> None:
    llm = ScriptedLLM()
    llm.responses[ExtractionResult] = _extraction()
    service, repo = _service(llm)
    repo.add(
        Commitment(
            direction=Direction.OWED_TO_ME,
            person="priya",
            description="Send the signed NDA",
            source_id="Added by hand",
            source_quote="",
        )
    )
    assert (await service.scan([_mail()], TODAY, max_emails=10)).suggestions == []


async def test_one_failed_email_does_not_sink_the_rest_but_total_failure_is_reported() -> None:
    llm = ScriptedLLM()
    llm.responses[ExtractionResult] = _extraction()
    llm.fail_after = 1
    service, _ = _service(llm)
    mails = [_mail(subject="a", sent=date(2026, 10, 6)), _mail(subject="b", sent=date(2026, 10, 5))]
    partial = await service.scan(mails, TODAY, max_emails=10)
    assert len(partial.suggestions) == 1

    broken = ScriptedLLM()
    broken.error = LLMError("down")
    failing, _ = _service(broken)
    with pytest.raises(LLMError):
        await failing.scan(mails, TODAY, max_emails=10)


async def test_scanning_nothing_is_an_error_not_an_empty_success() -> None:
    service, _ = _service(ScriptedLLM())
    with pytest.raises(InvalidMailError):
        await service.scan([], TODAY, max_emails=10)


def test_accepting_saves_tidy_promises_and_skips_ones_already_saved() -> None:
    service, repo = _service(ScriptedLLM())
    item = Suggestion(
        direction=Direction.OWED_TO_ME,
        person="priya",
        description="send the signed NDA",
        due=date(2026, 10, 8),
        source_id="Email: Terms",
        source_quote=QUOTE,
    )
    [saved] = service.accept([item, item])
    assert (saved.person, saved.description, saved.due) == (
        "Priya",
        "Send the signed NDA",
        date(2026, 10, 8),
    )
    assert service.accept([item]) == []
    assert len(repo.list()) == 1


def test_the_sample_inbox_is_synthetic_and_covers_both_directions() -> None:
    mails = sample_mails(TODAY)
    assert all(m.sender_address.endswith(".example") for m in mails)
    assert any(m.from_me for m in mails) and any(not m.from_me for m in mails)
    assert all(m.sent is not None and m.sent < TODAY for m in mails)


# ---- the API ----


async def test_scanning_the_sample_inbox_over_the_api(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, llm, _ = env
    llm.responses[ExtractionResult] = ExtractionResult(
        commitments=[
            ExtractedCommitment(
                direction=Direction.OWED_TO_ME,
                person="Priya",
                description="send the signed NDA",
                due_phrase="by Thursday",
                source_quote="I'll send over the signed NDA by Thursday",
            )
        ]
    )
    response = await client.post("/api/inbox/scan", data={"sample": "true"})
    assert response.status_code == 200
    body = response.json()
    assert body["emails_read"] >= 5 and body["emails_skipped"] >= 1
    assert [s["person"] for s in body["suggestions"]] == ["Priya"]
    assert (await client.get("/api/commitments")).json() == []  # nothing saved by scanning


async def test_uploading_an_eml_file_then_accepting_its_promises(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, llm, _ = env
    llm.responses[ExtractionResult] = _extraction()
    scan = await client.post(
        "/api/inbox/scan", files=[("files", ("terms.eml", _eml(), "message/rfc822"))]
    )
    assert scan.status_code == 200
    suggestions = scan.json()["suggestions"]
    assert suggestions[0]["due"] == "2026-10-08"

    accepted = await client.post("/api/inbox/accept", json={"suggestions": suggestions})
    assert accepted.status_code == 201
    [saved] = (await client.get("/api/commitments")).json()
    assert (saved["person"], saved["source_id"]) == ("Priya", "Email: Terms")
    assert saved["source_quote"] == QUOTE


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "Choose .eml or .mbox files"),
        ({"files": [("files", ("a.txt", b"x", "text/plain"))]}, "use .eml or .mbox"),
        ({"files": [("files", ("a.eml", b"no headers here", "message/rfc822"))]}, "No emails"),
    ],
)
async def test_bad_scan_requests_get_a_clear_422(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch], kwargs: dict[str, object], message: str
) -> None:
    client, _, _ = env
    response = await client.post("/api/inbox/scan", **kwargs)  # type: ignore[arg-type]
    assert response.status_code == 422
    assert message in response.json()["detail"]


async def test_oversized_uploads_are_refused(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    big = b"x" * (10 * 1024 * 1024 + 1)
    response = await client.post(
        "/api/inbox/scan", files=[("files", ("big.mbox", big, "application/mbox"))]
    )
    assert response.status_code == 422
    assert "too large" in response.json()["detail"]


@pytest.mark.parametrize(
    "bad",
    [
        {"person": "A\nB"},
        {"description": ""},
        {"source_quote": "   "},
        {"source_id": "x" * 300},
    ],
)
async def test_accept_validates_what_the_browser_sends_back(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch], bad: dict[str, str]
) -> None:
    client, _, _ = env
    item = {
        "direction": "owed_to_me",
        "person": "Priya",
        "description": "Send it",
        "due": None,
        "source_id": "Email: Terms",
        "source_quote": QUOTE,
        **bad,
    }
    assert (await client.post("/api/inbox/accept", json={"suggestions": [item]})).status_code == 422
    assert (await client.post("/api/inbox/accept", json={"suggestions": []})).status_code == 422


async def test_the_demo_limits_how_often_and_how_much_mail_is_scanned(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        demo_mode=True,
        web_dir=tmp_path,
        demo_max_inbox=1,
        demo_max_inbox_emails=2,
        demo_access_code="open-sesame",
    )
    llm = ScriptedLLM()
    llm.responses[ExtractionResult] = ExtractionResult(commitments=[])
    manager = build_session_manager(settings, llm=llm, search=FakeSearch(), today=lambda: TODAY)
    async with demo_client(settings, manager) as client:
        first = await client.post("/api/inbox/scan", data={"sample": "true"})
        assert first.status_code == 200
        assert first.json()["emails_read"] + first.json()["emails_skipped"] == 7
        assert first.json()["emails_read"] <= 2

        second = await client.post("/api/inbox/scan", data={"sample": "true"})
        assert second.status_code == 429
        assert "allowance" in second.json()["detail"]

        await client.post("/api/demo/access", json={"code": "open-sesame"})
        assert (await client.post("/api/inbox/scan", data={"sample": "true"})).status_code == 200
    await manager.aclose()
