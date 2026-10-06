from datetime import date
from pathlib import Path

import httpx
import pytest

from kept.api.app import create_app
from kept.config import Settings
from kept.demo import COOKIE_NAME, SessionManager, build_session_manager
from kept.domain.errors import DemoLimitError
from tests.fakes import NOTE, FakeSearch, ScriptedLLM
from tests.helpers import demo_client as _client

TODAY = date(2026, 10, 7)  # a Wednesday


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {"demo_mode": True, "web_dir": tmp_path}
    return Settings(_env_file=None, **{**base, **overrides})  # type: ignore[arg-type]


def _manager(settings: Settings, llm: ScriptedLLM | None = None, **kw: object) -> SessionManager:
    return build_session_manager(
        settings, llm=llm or ScriptedLLM(), search=FakeSearch(), today=lambda: TODAY, **kw
    )


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
            "access_code": False,
            "unlocked": False,
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


async def test_week_check_allowance_is_enforced(tmp_path: Path) -> None:
    settings = _settings(tmp_path, demo_max_checks=1)
    manager = _manager(settings)
    async with _client(settings, manager) as client:
        assert (await client.post("/api/week-check")).status_code == 200
        assert (await client.post("/api/week-check")).status_code == 429
    await manager.aclose()


CODE = "judge-2026"


async def _unlock(client: httpx.AsyncClient, code: str = CODE) -> httpx.Response:
    return await client.post("/api/demo/access", json={"code": code})


async def test_the_access_code_lifts_limits_for_that_visitor_only(tmp_path: Path) -> None:
    settings = _settings(tmp_path, demo_max_notes=1, demo_access_code=CODE)
    manager = _manager(settings)
    async with _client(settings, manager) as judge, _client(settings, manager) as stranger:
        assert (await judge.get("/api/capabilities")).json()["access_code"] is True

        await judge.post("/api/notes", json={"source_id": "a", "text": NOTE})
        blocked = await judge.post("/api/notes", json={"source_id": "b", "text": NOTE})
        assert blocked.status_code == 429

        assert (await _unlock(judge)).json() == {"unlocked": True}
        assert (await judge.get("/api/capabilities")).json()["unlocked"] is True
        for i in range(3):
            ok = await judge.post("/api/notes", json={"source_id": f"c{i}", "text": NOTE})
            assert ok.status_code == 200

        await stranger.post("/api/notes", json={"source_id": "a", "text": NOTE})
        again = await stranger.post("/api/notes", json={"source_id": "b", "text": NOTE})
        assert again.status_code == 429  # nobody else was unlocked
        assert (await stranger.get("/api/capabilities")).json()["unlocked"] is False
    await manager.aclose()


async def test_unlocking_also_lifts_the_note_size_cap(tmp_path: Path) -> None:
    settings = _settings(tmp_path, demo_max_note_chars=50, demo_access_code=CODE)
    manager = _manager(settings)
    async with _client(settings, manager) as client:
        big = {"source_id": "big", "text": "x" * 51}
        assert (await client.post("/api/notes", json=big)).status_code == 429
        await _unlock(client)
        assert (await client.post("/api/notes", json=big)).status_code == 200
    await manager.aclose()


async def test_wrong_codes_are_refused_and_guessing_is_capped(tmp_path: Path) -> None:
    settings = _settings(tmp_path, demo_access_code=CODE)
    manager = _manager(settings)
    async with _client(settings, manager) as client:
        for _ in range(5):
            assert (await _unlock(client, "nope")).status_code == 403
        assert (await _unlock(client, "nope")).status_code == 429
        assert (await _unlock(client, CODE)).status_code == 429  # even the right one, once capped
    await manager.aclose()


async def test_there_is_nothing_to_unlock_when_no_code_is_configured(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    manager = _manager(settings)
    async with _client(settings, manager) as client:
        assert (await client.get("/api/capabilities")).json()["access_code"] is False
        assert (await _unlock(client, "")).status_code == 422
        assert (await _unlock(client, "anything")).status_code == 403
    await manager.aclose()


async def test_the_unlock_endpoint_does_not_exist_outside_the_demo(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    assert (await _unlock(client)).status_code == 404
    caps = (await client.get("/api/capabilities")).json()
    assert (caps["access_code"], caps["unlocked"]) == (False, False)


async def test_error_responses_still_carry_the_session_cookie(tmp_path: Path) -> None:
    settings = _settings(tmp_path, demo_access_code=CODE)
    manager = _manager(settings)
    async with _client(settings, manager) as client:
        refused = await _unlock(client, "nope")
        assert refused.status_code == 403
        assert COOKIE_NAME in refused.headers["set-cookie"]
        assert len(manager) == 1  # the failed request created one workspace, not zero
        await _unlock(client, "nope again")
        assert len(manager) == 1  # and the next request reused it
    await manager.aclose()


async def test_static_files_never_create_workspaces(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Kept</h1>")
    settings = _settings(tmp_path)
    manager = _manager(settings)
    async with _client(settings, manager) as client:
        page = await client.get("/")
        assert "<h1>Kept</h1>" in page.text
        assert "set-cookie" not in page.headers
        assert (await client.get("/health")).status_code == 200
        assert len(manager) == 0
    await manager.aclose()


def _limited_manager(tmp_path: Path, clock: list[float], **limits: int) -> SessionManager:
    settings = _settings(tmp_path)
    factory = build_session_manager(settings, llm=ScriptedLLM(), search=FakeSearch())._factory
    return SessionManager(
        factory, max_sessions=100, ttl_seconds=3600, clock=lambda: clock[0], **limits
    )


def test_one_client_cannot_flood_the_server_with_new_workspaces(tmp_path: Path) -> None:
    now = [0.0]
    manager = _limited_manager(tmp_path, now, new_per_minute_per_client=2, new_per_minute_total=100)
    manager.get_or_create(None, client="1.1.1.1")
    manager.get_or_create(None, client="1.1.1.1")
    with pytest.raises(DemoLimitError, match="busy"):
        manager.get_or_create(None, client="1.1.1.1")
    manager.get_or_create(None, client="2.2.2.2")  # someone else is unaffected
    assert len(manager) == 3


def test_there_is_also_a_server_wide_creation_cap(tmp_path: Path) -> None:
    now = [0.0]
    manager = _limited_manager(tmp_path, now, new_per_minute_per_client=10, new_per_minute_total=3)
    for client in ("a", "b", "c"):
        manager.get_or_create(None, client=client)
    with pytest.raises(DemoLimitError):
        manager.get_or_create(None, client="d")


def test_the_creation_window_slides_and_existing_visitors_are_never_blocked(
    tmp_path: Path,
) -> None:
    now = [0.0]
    manager = _limited_manager(tmp_path, now, new_per_minute_per_client=1, new_per_minute_total=100)
    sid, container, _ = manager.get_or_create(None, client="1.1.1.1")
    with pytest.raises(DemoLimitError):
        manager.get_or_create(None, client="1.1.1.1")

    assert manager.get_or_create(sid, client="1.1.1.1") == (sid, container, False)

    now[0] = 61
    manager.get_or_create(None, client="1.1.1.1")
    assert len(manager) == 2


async def test_a_flood_of_cookieless_requests_gets_a_429_not_a_workspace(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    factory = build_session_manager(settings, llm=ScriptedLLM(), search=FakeSearch())._factory
    manager = SessionManager(
        factory, max_sessions=10, ttl_seconds=3600, new_per_minute_per_client=1
    )
    async with _client(settings, manager) as visitor, _client(settings, manager) as bot:
        assert (await visitor.get("/api/commitments")).status_code == 200
        blocked = await bot.get("/api/commitments")  # same address (the test client), no cookie
        assert blocked.status_code == 429
        assert "busy" in blocked.json()["detail"]
        assert (await visitor.get("/api/commitments")).status_code == 200  # has a cookie: fine
        assert len(manager) == 1
    await manager.aclose()
