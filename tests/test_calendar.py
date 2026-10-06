from datetime import UTC, date, datetime

import httpx
import pytest

from kept.domain.errors import NoDueDateError
from kept.domain.models import Commitment, Direction
from kept.services.calendar import build_ics
from tests.fakes import NOTE, FakeSearch, ScriptedLLM

NOW = datetime(2026, 10, 6, 12, 30, 5, tzinfo=UTC)


def _promise(**overrides: object) -> Commitment:
    fields: dict[str, object] = {
        "id": 7,
        "direction": Direction.OWED_BY_ME,
        "person": "Priya",
        "description": "Send the comparison",
        "due": date(2026, 10, 9),
        "source_id": "Standup",
        "source_quote": "I will send it by Friday.",
    }
    return Commitment(**{**fields, **overrides})


def _lines(ics: str) -> list[str]:
    return ics.split("\r\n")[:-1]


def test_builds_a_valid_all_day_event_with_crlf_line_endings() -> None:
    ics = build_ics(_promise(), NOW)
    assert ics.endswith("\r\n") and "\n" not in ics.replace("\r\n", "")
    lines = _lines(ics)
    assert lines[0] == "BEGIN:VCALENDAR"
    assert lines[-1] == "END:VCALENDAR"
    assert "VERSION:2.0" in lines
    assert (
        "UID:kept-promise-7@kept.local" in lines
    )  # stable, so re-importing updates not duplicates
    assert "DTSTAMP:20261006T123005Z" in lines
    assert "DTSTART;VALUE=DATE:20261009" in lines
    assert "DTEND;VALUE=DATE:20261010" in lines  # all-day events end the next day
    assert "SUMMARY:Send the comparison (for Priya)" in lines
    assert "TRIGGER:-PT15H" in lines


def test_inbound_promises_say_who_owes_you() -> None:
    ics = build_ics(_promise(direction=Direction.OWED_TO_ME, description="Share the deck"), NOW)
    assert "SUMMARY:Priya owes you: Share the deck" in _lines(ics)


def test_end_date_rolls_over_months_and_years() -> None:
    assert "DTEND;VALUE=DATE:20261101" in _lines(build_ics(_promise(due=date(2026, 10, 31)), NOW))
    assert "DTEND;VALUE=DATE:20270101" in _lines(build_ics(_promise(due=date(2026, 12, 31)), NOW))


def test_special_characters_are_escaped_so_they_cannot_break_the_format() -> None:
    ics = build_ics(
        _promise(description="Send a, b; c\\d\nBEGIN:VEVENT", source_quote="line one\r\nline two"),
        NOW,
    )
    lines = _lines(ics)
    assert r"SUMMARY:Send a\, b\; c\\d\nBEGIN:VEVENT (for Priya)" in lines
    assert lines.count("BEGIN:VEVENT") == 1  # an injected BEGIN:VEVENT stayed plain text
    assert any("line one\\nline two" in line for line in lines)


def test_long_lines_fold_at_75_octets_without_splitting_characters() -> None:
    ics = build_ics(_promise(source_quote="Ünïcödé ✓ " * 40), NOW)
    lines = _lines(ics)
    assert all(len(line.encode()) <= 75 for line in lines)
    assert any(line.startswith(" ") for line in lines)
    unfolded = ics.replace("\r\n ", "")
    assert "Ünïcödé ✓ " * 3 in unfolded


def test_a_promise_without_a_due_date_cannot_be_exported() -> None:
    with pytest.raises(NoDueDateError):
        build_ics(_promise(due=None), NOW)


async def test_the_endpoint_serves_a_downloadable_calendar_file(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    created = (await client.post("/api/notes", json={"source_id": "n1", "text": NOTE})).json()
    response = await client.get(f"/api/commitments/{created[0]['id']}/calendar.ics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert "attachment" in response.headers["content-disposition"]
    assert response.text.startswith("BEGIN:VCALENDAR\r\n")
    assert "DTSTART;VALUE=DATE:20261009" in response.text


async def test_the_endpoint_reports_missing_and_undated_promises(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, llm, _ = env
    assert (await client.get("/api/commitments/999/calendar.ics")).status_code == 404

    from kept.services.extraction import ExtractionResult

    extracted = llm.responses[ExtractionResult]
    assert isinstance(extracted, ExtractionResult)
    undated = extracted.commitments[0].model_copy(update={"due_phrase": None})
    llm.responses[ExtractionResult] = ExtractionResult(commitments=[undated])
    created = (await client.post("/api/notes", json={"source_id": "n2", "text": NOTE})).json()
    assert (
        await client.get(f"/api/commitments/{created[0]['id']}/calendar.ics")
    ).status_code == 409
