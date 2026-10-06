from datetime import date
from pathlib import Path

import httpx
import pytest

from kept.api.app import create_app
from kept.config import Settings
from kept.demo import COOKIE_NAME, SessionManager, build_session_manager
from tests.fakes import NOTE, FakeSearch, ScriptedLLM

TODAY = date(2026, 10, 7)  # a Wednesday


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {"demo_mode": True, "web_dir": tmp_path}
    return Settings(_env_file=None, **{**base, **overrides})  # type: ignore[arg-type]


def _manager(settings: Settings, llm: ScriptedLLM | None = None, **kw: object) -> SessionManager:
    return build_session_manager(
        settings, llm=llm or ScriptedLLM(), search=FakeSearch(), today=lambda: TODAY, **kw
    )


def _client(settings: Settings, manager: SessionManager) -> httpx.AsyncClient:
    app = create_app(sessions=manager, settings=settings)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return _settings(tmp_path)


async def _count(client: httpx.AsyncClient) -> int:
    return len((await client.get("/api/commitments")).json())


async def test_each_visitor_gets_a_private_seeded_workspace(settings: Settings) -> None:
    manager = _manager(settings)
    async with _client(settings, manager) as alice, _client(settings, manager) as bob:
        assert await _count(alice) == 6
        assert await _count(bob) == 6

        await alice.post("/api/notes", json={"source_id": "mine", "text": NOTE})
        assert await _count(alice) == 7
        assert await _count(bob) == 6
        assert len(manager) == 2
    await manager.aclose()


async def test_the_session_cookie_is_private_and_keeps_the_workspace(settings: Settings) -> None:
    manager = _manager(settings)
    async with _client(settings, manager) as client:
        first = await client.get("/api/commitments")
        cookie = first.headers["set-cookie"].lower()
        assert COOKIE_NAME in cookie
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        await client.post("/api/notes", json={"source_id": "mine", "text": NOTE})
        assert await _count(client) == 7
        assert len(manager) == 1
    await manager.aclose()


async def test_email_is_forced_off_even_if_the_server_has_it_configured(tmp_path: Path) -> None:
    settings = _settings(tmp_path, smtp_host="smtp.example.com", email_from="me@example.com")
    manager = _manager(settings)
    async with _client(settings, manager) as client:
        caps = (await client.get("/api/capabilities")).json()
        assert caps == {
            "email": {"enabled": False, "sender": "", "recipients": []},
            "demo": True,
        }
        hosts = (await client.get("/api/allowlist")).json()
        assert "smtp.example.com" not in hosts
    await manager.aclose()


async def test_sample_promises_land_on_sensible_dates(settings: Settings) -> None:
    manager = _manager(settings)
    async with _client(settings, manager) as client:
        listed = (await client.get("/api/commitments")).json()
    due = {(c["person"], c["description"].split()[0]): c["due"] for c in listed}
    assert due[("Priya", "Send")] == "2026-10-09"
    assert due[("Priya", "Share")] == "2026-10-07"
    assert due[("Marcus", "Review")] == "2026-10-12"
    assert due[("Marcus", "Send")] == "2026-10-08"
    assert due[("Dana", "Book")] == "2026-10-09"
    assert due[("Vendor", "Reply")] is None
    await manager.aclose()


async def test_note_allowance_runs_out_with_a_clear_message(tmp_path: Path) -> None:
    settings = _settings(tmp_path, demo_max_notes=2)
    manager = _manager(settings)
    async with _client(settings, manager) as client:
        for i in range(2):
            ok = await client.post("/api/notes", json={"source_id": f"n{i}", "text": NOTE})
            assert ok.status_code == 200
        over = await client.post("/api/notes", json={"source_id": "n3", "text": NOTE})
        assert over.status_code == 429
        assert "allowance" in over.json()["detail"]
    await manager.aclose()


async def test_a_failed_attempt_does_not_use_up_the_allowance(tmp_path: Path) -> None:
    from kept.adapters.llm import LLMOutputError

    settings = _settings(tmp_path, demo_max_notes=1)
    llm = ScriptedLLM()
    manager = _manager(settings, llm)
    async with _client(settings, manager) as client:
        llm.error = LLMOutputError("bad json")
        failed = await client.post("/api/notes", json={"source_id": "a", "text": NOTE})
        assert failed.status_code == 502

        llm.error = None
        retry = await client.post("/api/notes", json={"source_id": "a", "text": NOTE})
        assert retry.status_code == 200
    await manager.aclose()


async def test_oversized_notes_are_refused_in_the_demo(tmp_path: Path) -> None:
    settings = _settings(tmp_path, demo_max_note_chars=50)
    manager = _manager(settings)
    async with _client(settings, manager) as client:
        response = await client.post("/api/notes", json={"source_id": "big", "text": "x" * 51})
        assert response.status_code == 429
        assert "50 characters" in response.json()["detail"]
    await manager.aclose()


async def test_draft_allowance_is_enforced(tmp_path: Path) -> None:
    settings = _settings(tmp_path, demo_max_drafts=1)
    manager = _manager(settings)
    async with _client(settings, manager) as client:
        ids = [
            c["id"]
            for c in (await client.get("/api/commitments")).json()
            if c["direction"] == "owed_by_me"
        ]
        first = await client.post(f"/api/commitments/{ids[0]}/prepare")
        assert first.status_code == 200
        second = await client.post(f"/api/commitments/{ids[1]}/prepare")
        assert second.status_code == 429
    await manager.aclose()


async def test_oldest_workspace_is_evicted_when_the_server_is_full(tmp_path: Path) -> None:
    settings = _settings(tmp_path, demo_max_sessions=2)
    manager = _manager(settings)
    async with (
        _client(settings, manager) as first,
        _client(settings, manager) as second,
        _client(settings, manager) as third,
    ):
        await first.post("/api/notes", json={"source_id": "mine", "text": NOTE})
        assert await _count(first) == 7
        await second.get("/api/commitments")
        await third.get("/api/commitments")
        assert len(manager) == 2
        assert await _count(first) == 6  # evicted, so it starts over with a fresh workspace
    await manager.aclose()


def test_idle_workspaces_expire_and_bad_cookies_get_a_new_one(tmp_path: Path) -> None:
    settings = _settings(tmp_path, demo_session_minutes=1)
    now = [0.0]
    slots_manager = build_session_manager(settings, llm=ScriptedLLM(), search=FakeSearch())
    manager = SessionManager(
        slots_manager._factory, max_sessions=10, ttl_seconds=60, clock=lambda: now[0]
    )
    sid, container, created = manager.get_or_create(None)
    assert created

    now[0] = 30
    assert manager.get_or_create(sid) == (sid, container, False)

    now[0] = 30 + 61
    new_sid, new_container, created = manager.get_or_create(sid)
    assert created and new_sid != sid and new_container is not container

    other, _, created = manager.get_or_create("../../etc/passwd")
    assert created and other != "../../etc/passwd"


async def test_released_workspaces_are_closed(tmp_path: Path) -> None:
    settings = _settings(tmp_path, demo_max_sessions=1)
    manager = _manager(settings)
    _, first, _ = manager.get_or_create(None)
    closed: list[bool] = []
    original = first.aclose

    async def spy() -> None:
        closed.append(True)
        await original()

    first.aclose = spy  # type: ignore[method-assign]
    manager.get_or_create(None)  # evicts the first
    assert closed == []
    await manager.reap()
    assert closed == [True]
    await manager.aclose()


async def test_normal_mode_is_unchanged_and_not_a_demo(tmp_path: Path) -> None:
    from kept.adapters.sqlite import Database
    from kept.container import build_container

    settings = Settings(_env_file=None, web_dir=tmp_path)
    container = build_container(
        settings, llm=ScriptedLLM(), search=FakeSearch(), db=Database(":memory:")
    )
    app = create_app(container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/commitments")
        assert response.json() == []
        assert "set-cookie" not in response.headers
        assert (await client.get("/api/capabilities")).json()["demo"] is False
    await container.aclose()
