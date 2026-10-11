"""The visitor's own calendar date. A server in UTC is a day ahead of a US evening."""

from datetime import date

HEADER = "x-kept-today"


def reported_date(value: str | None, server_today: date) -> date | None:
    """The date the browser reports, if it is plausible. Time zones span about a day either way,
    so anything further off (or garbled) is ignored."""
    try:
        reported = date.fromisoformat(value or "")
    except ValueError:
        return None
    return reported if abs((reported - server_today).days) <= 1 else None


def client_today(value: str | None, server_today: date) -> date:
    """Today for this visitor: their own date when plausible, otherwise the server's."""
    return reported_date(value, server_today) or server_today
