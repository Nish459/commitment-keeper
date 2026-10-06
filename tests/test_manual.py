from datetime import date
from pathlib import Path

import httpx
import pytest

from kept.adapters.sqlite import Database, SqliteCommitmentRepository
from kept.config import Settings
from kept.demo import build_session_manager
from kept.domain.models import Direction
from kept.domain.text import sentence_case
from kept.services.manual import MANUAL_SOURCE, ManualEntryService
from tests.fakes import FakeSearch, ScriptedLLM
from tests.helpers import demo_client


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("send the deck", "Send the deck"),
        ("  trim me ", "Trim me"),
        ("Q3 deck", "Q3 deck"),
        ("already Capitalized", "Already Capitalized"),
        ("éclair order", "Éclair order"),
        ("", ""),
    ],
)
def test_sentence_case(raw: str, expected: str) -> None:
    assert sentence_case(raw) == expected


def test_a_hand_added_promise_is_tidied_and_marked_as_added_by_hand() -> None:
    repo = SqliteCommitmentRepository(Database(":memory:"))
    saved = ManualEntryService(repo).add(
        Direction.OWED_BY_ME, " priya ", "send the q3 deck", date(2026, 10, 9)
    )
    assert saved.id is not None
    assert (saved.person, saved.description, saved.due) == (
        "Priya",
        "Send the q3 deck",
        date(2026, 10, 9),
    )
    assert (saved.source_id, saved.source_quote) == (MANUAL_SOURCE, "")
    assert repo.get(saved.id) == saved


async def test_the_endpoint_creates_a_promise_that_works_like_any_other(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    response = await client.post(
        "/api/commitments",
        json={
            "direction": "owed_by_me",
            "person": "dana",
            "description": "book the venue",
            "due": "2026-10-09",
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert (created["person"], created["description"], created["status"]) == (
        "Dana",
        "Book the venue",
        "open",
    )
    assert created["source_id"] == "Added by hand"

    listed = (await client.get("/api/commitments")).json()
    assert [c["id"] for c in listed] == [created["id"]]

    calendar = await client.get(f"/api/commitments/{created['id']}/calendar.ics")
    assert calendar.status_code == 200 and "DTSTART;VALUE=DATE:20261009" in calendar.text
    draft = await client.post(f"/api/commitments/{created['id']}/prepare")
    assert draft.status_code == 200


async def test_the_due_date_is_optional_and_direction_can_be_inbound(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    created = (
        await client.post(
            "/api/commitments",
            json={"direction": "owed_to_me", "person": "Marcus", "description": "send the budget"},
        )
    ).json()
    assert (created["direction"], created["due"]) == ("owed_to_me", None)


@pytest.mark.parametrize(
    "payload",
    [
        {"direction": "owed_by_me", "person": "", "description": "x"},
        {"direction": "owed_by_me", "person": "   ", "description": "x"},
        {"direction": "owed_by_me", "person": "Priya", "description": ""},
        {"direction": "owed_by_me", "person": "Pri\nya", "description": "x"},
        {"direction": "owed_by_me", "person": "Priya", "description": "a\nBcc: x@y.com"},
        {"direction": "owed_by_me", "person": "P" * 101, "description": "x"},
        {"direction": "owed_by_me", "person": "Priya", "description": "d" * 301},
        {"direction": "sideways", "person": "Priya", "description": "x"},
        {"direction": "owed_by_me", "person": "Priya", "description": "x", "due": "soon"},
        {"direction": "owed_by_me", "person": "Priya", "description": "x", "due": "2026-02-31"},
        {"person": "Priya", "description": "x"},
    ],
)
async def test_invalid_promises_are_rejected(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch], payload: dict[str, str]
) -> None:
    client, _, _ = env
    assert (await client.post("/api/commitments", json=payload)).status_code == 422
    assert (await client.get("/api/commitments")).json() == []


async def test_manual_entry_has_its_own_demo_allowance(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, demo_mode=True, web_dir=tmp_path, demo_max_manual=2)
    manager = build_session_manager(settings, llm=ScriptedLLM(), search=FakeSearch())
    body = {"direction": "owed_by_me", "person": "Priya", "description": "do a thing"}
    async with demo_client(settings, manager) as client:
        assert (await client.post("/api/commitments", json=body)).status_code == 201
        assert (await client.post("/api/commitments", json=body)).status_code == 201
        over = await client.post("/api/commitments", json=body)
        assert over.status_code == 429
        assert "allowance" in over.json()["detail"]
    await manager.aclose()
