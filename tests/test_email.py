import smtplib
from email.message import EmailMessage
from types import TracebackType
from typing import Any, ClassVar, Self

import pytest

from kept.adapters.smtp import SmtpEmailSender
from kept.config import Settings
from kept.domain.errors import EmailError
from kept.domain.models import Attachment, AuditEvent
from kept.domain.recipients import is_recipient_allowed, normalize_address


class ListSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("Me@Example.com", "me@example.com"),
        ("a@b.co", "a@b.co"),
        ("not-an-email", None),
        ("a@b", None),
        ("a@b.com\nBcc: x@y.com", None),
        ("a@b.com, c@d.com", None),
        ("Name <a@b.com>", None),
        ("", None),
    ],
)
def test_normalize_address(address: str, expected: str | None) -> None:
    assert normalize_address(address) == expected


def test_only_the_sender_is_allowed_when_nothing_is_configured() -> None:
    assert is_recipient_allowed("me@example.com", [], "ME@example.com")
    assert not is_recipient_allowed("priya@acme.com", [], "me@example.com")


def test_allowed_addresses_and_domains() -> None:
    allowed = ["priya@acme.com", "@corp.com"]
    assert is_recipient_allowed("Priya@Acme.com", allowed, "me@example.com")
    assert is_recipient_allowed("anyone@corp.com", allowed, "me@example.com")
    assert not is_recipient_allowed("marcus@acme.com", allowed, "me@example.com")
    assert not is_recipient_allowed("a@sub.corp.com", allowed, "me@example.com")
    assert not is_recipient_allowed("bad address", allowed, "me@example.com")


def test_settings_enable_email_and_list_mail_host_as_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KEPT_EMAIL_ALLOWED_RECIPIENTS", "A@x.com, @y.com")
    off = Settings(_env_file=None)
    assert not off.email_enabled
    assert "smtp.example.com" not in off.allowed_hosts

    on = Settings(_env_file=None, smtp_host="smtp.example.com", email_from="me@example.com")
    assert on.email_enabled
    assert "smtp.example.com" in on.allowed_hosts
    assert off.email_allowed_recipients == ["a@x.com", "@y.com"]


class FakeSmtp:
    sent: ClassVar[list[EmailMessage]] = []
    fail = False
    logins: ClassVar[list[tuple[str, str]]] = []
    started_tls = False

    def __init__(self, host: str, port: int, **_: Any) -> None:
        self.host, self.port = host, port

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def starttls(self, **_: Any) -> None:
        FakeSmtp.started_tls = True

    def login(self, user: str, password: str) -> None:
        FakeSmtp.logins.append((user, password))

    def send_message(self, message: EmailMessage) -> None:
        if FakeSmtp.fail:
            raise smtplib.SMTPRecipientsRefused({})
        FakeSmtp.sent.append(message)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSmtp.sent, FakeSmtp.logins, FakeSmtp.fail, FakeSmtp.started_tls = [], [], False, False
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)


def _sender(sink: ListSink) -> SmtpEmailSender:
    return SmtpEmailSender(
        host="smtp.example.com",
        port=587,
        username="me@example.com",
        password="app-password",
        sender="me@example.com",
        sink=sink,
    )


async def test_send_delivers_message_and_audits_without_content() -> None:
    sink = ListSink()
    await _sender(sink).send("priya@acme.com", "Comparison", "Hi Priya,\nSecret body")

    (message,) = FakeSmtp.sent
    assert (message["To"], message["From"], message["Subject"]) == (
        "priya@acme.com",
        "me@example.com",
        "Comparison",
    )
    assert FakeSmtp.started_tls
    assert FakeSmtp.logins == [("me@example.com", "app-password")]
    (event,) = sink.events
    assert (event.method, event.host, event.status_code, event.blocked) == (
        "SMTP",
        "smtp.example.com",
        250,
        False,
    )
    assert event.bytes_out > 0
    assert "Secret body" not in event.model_dump_json()


async def test_send_failure_is_audited_and_raised() -> None:
    FakeSmtp.fail = True
    sink = ListSink()
    with pytest.raises(EmailError, match="Sending failed"):
        await _sender(sink).send("priya@acme.com", "s", "b")
    (event,) = sink.events
    assert event.status_code is None


async def test_attachments_become_real_mime_parts_with_the_right_name_and_type() -> None:
    sink = ListSink()
    files = [
        Attachment(
            draft_id=1, filename="roadmap.pdf", content_type="application/pdf", size=4, data=b"%PDF"
        ),
        Attachment(
            draft_id=1, filename="notes.txt", content_type="text/plain", size=5, data=b"hello"
        ),
        Attachment(draft_id=1, filename="blob", content_type="oddball", size=2, data=b"\x00\x01"),
    ]
    await _sender(sink).send("zoe@acme.com", "Q4 roadmap", "Attached.", files)

    (message,) = FakeSmtp.sent
    parts = list(message.iter_attachments())
    assert [(p.get_filename(), p.get_content_type()) for p in parts] == [
        ("roadmap.pdf", "application/pdf"),
        ("notes.txt", "text/plain"),
        ("blob", "application/octet-stream"),
    ]
    assert parts[0].get_payload(decode=True) == b"%PDF"
    assert parts[2].get_payload(decode=True) == b"\x00\x01"
    assert message.get_body().get_content().strip() == "Attached."  # type: ignore[union-attr]
    (event,) = sink.events
    assert event.bytes_out > 11  # the files count towards what left the machine
