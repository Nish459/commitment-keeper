"""Outbound email over SMTP. Records an audit event just like the HTTP egress client does."""

import asyncio
import smtplib
import ssl
import time
from collections.abc import Sequence
from email.message import EmailMessage

from kept.domain.errors import EmailError
from kept.domain.models import Attachment, AuditEvent
from kept.domain.ports import AuditSink


class SmtpEmailSender:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        sink: AuditSink,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._sink = sink

    async def send(
        self, to: str, subject: str, body: str, attachments: Sequence[Attachment] = ()
    ) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        for attachment in attachments:
            kind = attachment.content_type if "/" in attachment.content_type else ""
            maintype, _, subtype = (kind or "application/octet-stream").partition("/")
            message.add_attachment(
                attachment.data, maintype=maintype, subtype=subtype, filename=attachment.filename
            )

        event = AuditEvent(
            method="SMTP", host=self._host.lower(), path="/send", bytes_out=len(message.as_bytes())
        )
        started = time.monotonic()
        try:
            await asyncio.to_thread(self._deliver, message)
        except (smtplib.SMTPException, OSError) as exc:
            event.duration_ms = int((time.monotonic() - started) * 1000)
            self._sink.record(event)
            raise EmailError(f"Sending failed: {exc}") from exc
        event.status_code = 250
        event.duration_ms = int((time.monotonic() - started) * 1000)
        self._sink.record(event)

    def _deliver(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        if self._port == 465:
            with smtplib.SMTP_SSL(self._host, self._port, timeout=20, context=context) as smtp:
                self._login_and_send(smtp, message)
        else:
            with smtplib.SMTP(self._host, self._port, timeout=20) as smtp:
                smtp.starttls(context=context)
                self._login_and_send(smtp, message)

    def _login_and_send(self, smtp: smtplib.SMTP, message: EmailMessage) -> None:
        if self._username:
            smtp.login(self._username, self._password)
        smtp.send_message(message)
