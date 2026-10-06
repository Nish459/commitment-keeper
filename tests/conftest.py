from collections.abc import AsyncIterator
from datetime import date

import httpx
import pytest

from kept.adapters.sqlite import Database
from kept.api.app import create_app
from kept.config import Settings
from kept.container import build_container
from tests.fakes import FakeSearch, FakeSender, ScriptedLLM


@pytest.fixture
async def env() -> AsyncIterator[tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch]]:
    llm, search = ScriptedLLM(), FakeSearch()
    container = build_container(
        Settings(_env_file=None),
        llm=llm,
        search=search,
        db=Database(":memory:"),
        today=lambda: date(2026, 10, 7),
    )
    app = create_app(container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, llm, search
    await container.aclose()


@pytest.fixture
async def email_env() -> AsyncIterator[tuple[httpx.AsyncClient, FakeSender]]:
    sender = FakeSender()
    container = build_container(
        Settings(
            _env_file=None,
            smtp_host="smtp.example.com",
            email_from="me@example.com",
            email_allowed_recipients=["priya@acme.com"],
        ),
        llm=ScriptedLLM(),
        search=FakeSearch(),
        db=Database(":memory:"),
        email=sender,
        today=lambda: date(2026, 10, 7),
    )
    transport = httpx.ASGITransport(app=create_app(container))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, sender
    await container.aclose()
