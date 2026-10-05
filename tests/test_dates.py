from datetime import date

import pytest

from kept.services.dates import resolve_due

TUE = date(2026, 10, 6)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("by Friday", date(2026, 10, 9)),
        ("by Wednesday", date(2026, 10, 7)),
        ("by Tuesday", date(2026, 10, 6)),
        ("next Monday", date(2026, 10, 12)),
        ("monday", date(2026, 10, 12)),
        ("next Friday", date(2026, 10, 16)),
        ("this Friday", date(2026, 10, 9)),
        ("tomorrow", date(2026, 10, 7)),
        ("today", date(2026, 10, 6)),
        ("EOD", date(2026, 10, 6)),
        ("Friday EOD", date(2026, 10, 9)),
        ("end of this week", date(2026, 10, 9)),
        ("by the end of the week", date(2026, 10, 9)),
        ("next week", date(2026, 10, 16)),
        ("in 3 days", date(2026, 10, 9)),
        ("in 2 weeks", date(2026, 10, 20)),
        ("end of the month", date(2026, 10, 31)),
        ("Oct 9", date(2026, 10, 9)),
        ("9th October", date(2026, 10, 9)),
        ("October 3", date(2027, 10, 3)),
        ("2026-11-02", date(2026, 11, 2)),
        ("someday", None),
        ("no date set", None),
        ("", None),
        (None, None),
    ],
)
def test_resolve_due(phrase: str | None, expected: date | None) -> None:
    assert resolve_due(phrase, TUE) == expected


def test_end_of_week_on_weekend_rolls_to_next_friday() -> None:
    assert resolve_due("end of week", date(2026, 10, 10)) == date(2026, 10, 16)


def test_invalid_calendar_date_is_none() -> None:
    assert resolve_due("Feb 31", TUE) is None
