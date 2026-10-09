"""Read .eml and .mbox files into plain `Mail` records. Pure parsing: no network, nothing stored."""

import mailbox
import re
import tempfile
from collections.abc import Iterator, Sequence
from datetime import date
from email import message_from_bytes, policy
from email.headerregistry import Address
from email.message import EmailMessage, Message
from html.parser import HTMLParser
from pathlib import Path

from kept.domain.errors import InvalidMailError
from kept.domain.models import Mail

MAX_BODY_CHARS = 6000

_REPLY_MARKER = re.compile(
    r"^\s*(on .{5,200} wrote:|-{2,}\s*original message\s*-{2,}|from:\s.+\ssent:\s)",
    re.IGNORECASE,
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class _TextOnly(HTMLParser):
    """Turns an HTML email into plain text: tags dropped, script and style ignored."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in {"br", "p", "div", "li", "tr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip = max(0, self._skip - 1)
        elif tag in {"p", "div", "li", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _html_to_text(html: str) -> str:
    parser = _TextOnly()
    parser.feed(html)
    parser.close()
    return parser.text()


def strip_quoted(text: str) -> str:
    """Keep only what the sender newly wrote: drop "> quoted" lines and everything after a
    reply marker, so an old promise in the thread is not found again."""
    kept: list[str] = []
    for line in text.splitlines():
        if _REPLY_MARKER.match(line):
            break
        if not line.lstrip().startswith(">"):
            kept.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def _body(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, ValueError):  # an unknown charset or a broken part
        return ""
    text = _html_to_text(content) if part.get_content_type() == "text/html" else content
    return _CONTROL.sub("", strip_quoted(text))[:MAX_BODY_CHARS]


def _addresses(message: EmailMessage, header: str) -> list[Address]:
    try:
        value = message[header]
        return list(value.addresses) if value is not None else []
    except (AttributeError, IndexError, ValueError):  # a malformed address header
        return []


def _name(address: Address) -> str:
    """The display name, or a readable guess from the address itself."""
    if address.display_name:
        return address.display_name.strip()
    local = address.username.split("+")[0]
    return re.sub(r"[._-]+", " ", local).strip().title()


def _sent(message: EmailMessage) -> date | None:
    try:
        value = message["date"]
        return value.datetime.date() if value is not None else None
    except (AttributeError, ValueError, TypeError):
        return None


def _to_mail(message: EmailMessage) -> Mail:
    senders = _addresses(message, "from")
    sender = senders[0] if senders else None
    recipients = _addresses(message, "to")
    return Mail(
        subject=_CONTROL.sub("", str(message["subject"] or "(no subject)")).strip()[:200],
        sender_name=_name(sender) if sender else "",
        sender_address=sender.addr_spec.lower() if sender else "",
        to_names=tuple(_name(a) for a in recipients),
        to_addresses=tuple(a.addr_spec.lower() for a in recipients),
        sent=_sent(message),
        body=_body(message),
    )


def _parse_eml(data: bytes) -> Iterator[Mail]:
    message = message_from_bytes(data, policy=policy.default)
    if isinstance(message, EmailMessage) and message["from"] is not None:
        yield _to_mail(message)


def _parse_mbox(data: bytes) -> Iterator[Mail]:
    # `mailbox.mbox` reads from a path, so the bytes pass through a temporary file that is
    # removed straight away.
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "mail.mbox"
        path.write_bytes(data)
        box = mailbox.mbox(str(path))
        try:
            for key in box.iterkeys():
                message: Message = message_from_bytes(box.get_bytes(key), policy=policy.default)
                if isinstance(message, EmailMessage):
                    yield _to_mail(message)
        finally:
            box.close()


def parse_mail_files(files: Sequence[tuple[str, bytes]]) -> list[Mail]:
    """Parse uploaded `(filename, bytes)` pairs. `.mbox` holds many messages, `.eml` holds one."""
    mails: list[Mail] = []
    for name, data in files:
        lowered = name.lower()
        if lowered.endswith(".mbox"):
            parser = _parse_mbox
        elif lowered.endswith(".eml"):
            parser = _parse_eml
        else:
            raise InvalidMailError(f"{name}: use .eml or .mbox files.")
        try:
            mails.extend(parser(data))
        except (OSError, UnicodeError, ValueError, mailbox.Error) as exc:
            raise InvalidMailError(f"{name} could not be read as email.") from exc
    return mails
