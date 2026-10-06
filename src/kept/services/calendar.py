"""Calendar export. Builds an RFC 5545 all-day event so any calendar app can import a promise."""

from datetime import datetime, timedelta

from kept.domain.errors import NoDueDateError
from kept.domain.models import Commitment, Direction

_MAX_LINE_OCTETS = 75


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> list[str]:
    """Split a content line at 75 octets without breaking a multi-byte character."""
    pieces: list[str] = []
    current = ""
    limit = _MAX_LINE_OCTETS
    for char in line:
        if len((current + char).encode()) > limit:
            pieces.append(current)
            current, limit = char, _MAX_LINE_OCTETS - 1  # continuation lines start with a space
        else:
            current += char
    pieces.append(current)
    return [pieces[0], *(" " + piece for piece in pieces[1:])]


def build_ics(commitment: Commitment, now: datetime) -> str:
    if commitment.due is None:
        raise NoDueDateError("This promise has no due date, so it can't go on a calendar.")

    mine = commitment.direction is Direction.OWED_BY_ME
    summary = (
        f"{commitment.description} (for {commitment.person})"
        if mine
        else f"{commitment.person} owes you: {commitment.description}"
    )
    day = commitment.due
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Kept//Promise reminders//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:kept-promise-{commitment.id}@kept.local",
        f"DTSTAMP:{now:%Y%m%dT%H%M%SZ}",
        f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
        f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
        f"SUMMARY:{_escape(summary)}",
        f"DESCRIPTION:{_escape(f'From {commitment.source_id}: {commitment.source_quote}')}",
        "TRANSP:TRANSPARENT",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_escape(summary)}",
        "TRIGGER:-PT15H",  # 9:00 the day before an all-day event
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "".join(f"{part}\r\n" for line in lines for part in _fold(line))
