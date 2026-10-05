"""Deterministic due-date resolution. Models copy phrases; this computes the dates."""

import calendar
import re
from datetime import date, timedelta

_WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}
_WEEKDAYS |= {name.lower(): i for i, name in enumerate(calendar.day_abbr)}
_WEEKDAYS |= {"tues": 1, "wednes": 2, "thur": 3, "thurs": 3}
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS |= {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
_MONTHS["sept"] = 9

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_IN_N = re.compile(r"\bin (\d+) (day|week)s?\b")
_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)? (?:of )?([a-z]+)\b")
_MONTH_DAY = re.compile(r"\b([a-z]+) (\d{1,2})(?:st|nd|rd|th)?\b")
_WEEKDAY = re.compile(
    r"\b(?:(next|this|coming) )?(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b"
)


def _friday_of_week(day: date) -> date:
    return day - timedelta(days=day.weekday()) + timedelta(days=4)


def _month_day(month_name: str, day: int, today: date) -> date | None:
    month = _MONTHS.get(month_name)
    if month is None:
        return None
    try:
        result = date(today.year, month, day)
        return result if result >= today else date(today.year + 1, month, day)
    except ValueError:
        return None


def resolve_due(phrase: str | None, today: date) -> date | None:
    """Resolve phrases like "by Friday" or "end of next week" to a date, or None if unclear."""
    if not phrase:
        return None
    text = re.sub(r"[^a-z0-9\- ]", " ", phrase.lower())
    text = re.sub(r"\s+", " ", text).strip()

    if iso := _ISO.search(text):
        try:
            return date(int(iso[1]), int(iso[2]), int(iso[3]))
        except ValueError:
            return None
    if "tomorrow" in text:
        return today + timedelta(days=1)
    if match := _IN_N.search(text):
        return today + timedelta(days=int(match[1]) * (7 if match[2] == "week" else 1))
    if re.search(r"\bend of (?:the |this )?month\b|\beom\b", text):
        return date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    if re.search(r"\bend of (?:the |this )?week\b|\beow\b", text):
        friday = _friday_of_week(today)
        return friday if friday >= today else friday + timedelta(days=7)
    if re.search(r"\bnext week\b", text):
        return _friday_of_week(today) + timedelta(days=7)
    if match := _WEEKDAY.search(text):
        target = _WEEKDAYS[match[2]]
        ahead = (target - today.weekday()) % 7
        if match[1] == "next":
            ahead = ahead or 7
            if today.weekday() + ahead < 7:  # still inside this Mon-Sun week
                ahead += 7
        return today + timedelta(days=ahead)
    if (match := _DAY_MONTH.search(text)) and (
        result := _month_day(match[2], int(match[1]), today)
    ):
        return result
    if (match := _MONTH_DAY.search(text)) and (
        result := _month_day(match[1], int(match[2]), today)
    ):
        return result
    if re.search(r"\btoday\b|\btonight\b|\beod\b|\bend of (?:the )?day\b|\bcob\b", text):
        return today
    return None
