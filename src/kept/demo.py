"""Demo mode: one private, temporary workspace per visitor, with hard limits on costly actions."""

import asyncio
import re
import secrets
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from kept.adapters.sqlite import Database
from kept.config import Settings
from kept.domain.errors import DemoLimitError
from kept.domain.models import Commitment, Direction
from kept.services.dates import resolve_due

if TYPE_CHECKING:
    from kept.container import Container

COOKIE_NAME = "kept_session"
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
_SLOT_WAIT_SECONDS = 15


class DemoGuard:
    """Per-workspace allowance plus a server-wide cap on concurrent model work."""

    def __init__(
        self, slots: asyncio.Semaphore, *, notes: int, drafts: int, max_note_chars: int
    ) -> None:
        self._slots = slots
        self._left = {"notes": notes, "drafts": drafts}
        self._max_note_chars = max_note_chars

    @asynccontextmanager
    async def run(self, kind: str, size: int = 0) -> AsyncIterator[None]:
        if kind == "notes" and size > self._max_note_chars:
            raise DemoLimitError(
                f"Notes are limited to {self._max_note_chars} characters in the demo."
            )
        if self._left[kind] <= 0:
            raise DemoLimitError(
                f"You've used the demo's {kind} allowance. Run Kept yourself for unlimited use."
            )
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=_SLOT_WAIT_SECONDS)
        except TimeoutError as exc:
            raise DemoLimitError("The demo is busy right now. Try again in a moment.") from exc
        self._left[kind] -= 1
        try:
            yield
        except BaseException:
            self._left[kind] += 1  # a failed attempt should not cost the visitor their allowance
            raise
        finally:
            self._slots.release()


@dataclass
class _Entry:
    container: "Container"
    last_used: float


class SessionManager:
    def __init__(
        self,
        factory: Callable[[], "Container"],
        *,
        max_sessions: int,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._factory = factory
        self._max = max_sessions
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._to_close: list[Container] = []

    def __len__(self) -> int:
        return len(self._entries)

    def get_or_create(self, session_id: str | None) -> tuple[str, "Container", bool]:
        """Return (id, workspace, created). Unknown, expired or malformed ids get a fresh one."""
        now = self._clock()
        self._expire(now)
        if session_id and _SESSION_ID.match(session_id) and session_id in self._entries:
            entry = self._entries[session_id]
            entry.last_used = now
            return session_id, entry.container, False
        while len(self._entries) >= self._max:
            oldest = min(self._entries, key=lambda sid: self._entries[sid].last_used)
            self._to_close.append(self._entries.pop(oldest).container)
        new_id = secrets.token_urlsafe(24)
        container = self._factory()
        self._entries[new_id] = _Entry(container, now)
        return new_id, container, True

    def _expire(self, now: float) -> None:
        for sid in [s for s, e in self._entries.items() if now - e.last_used > self._ttl]:
            self._to_close.append(self._entries.pop(sid).container)

    async def reap(self) -> None:
        """Release the resources of workspaces that were evicted or expired."""
        closing, self._to_close = self._to_close, []
        for container in closing:
            await container.aclose()

    async def aclose(self) -> None:
        self._to_close.extend(entry.container for entry in self._entries.values())
        self._entries.clear()
        await self.reap()


_SAMPLES: list[tuple[Direction, str, str, str, str]] = [
    (
        Direction.OWED_BY_ME,
        "Priya",
        "Send competitor comparison of Tavily vs Exa vs Perplexity API for search",
        "by Friday",
        "I will send her a competitor comparison of Tavily vs Exa vs Perplexity API "
        "for search by Friday.",
    ),
    (
        Direction.OWED_TO_ME,
        "Priya",
        "Share the Q3 pricing deck",
        "by Wednesday",
        "Priya said she will share the Q3 pricing deck by Wednesday.",
    ),
    (
        Direction.OWED_BY_ME,
        "Marcus",
        "Review his onboarding doc",
        "by next Monday",
        "I also promised Marcus I would review his onboarding doc by next Monday.",
    ),
    (
        Direction.OWED_TO_ME,
        "Marcus",
        "Send revised budget sheet",
        "by tomorrow",
        "Marcus will send me the revised budget sheet by tomorrow.",
    ),
    (
        Direction.OWED_BY_ME,
        "Dana",
        "Book offsite venue",
        "by end of this week",
        "I committed to booking the offsite venue with Dana by end of this week.",
    ),
    (
        Direction.OWED_BY_ME,
        "Vendor",
        "Reply about contract renewal",
        "",
        "I said I would reply to the vendor about the contract renewal, no date set.",
    ),
]


def seed_sample_data(container: "Container") -> None:
    """Preload a believable week so a visitor sees a working product before spending anything."""
    today = container.today()
    for direction, person, description, phrase, quote in _SAMPLES:
        container.commitments.add(
            Commitment(
                direction=direction,
                person=person,
                description=description,
                due=resolve_due(phrase, today),
                source_id="Sample notes",
                source_quote=quote,
            )
        )


def build_demo_container(
    settings: Settings, slots: asyncio.Semaphore, **overrides: Any
) -> "Container":
    """A fresh in-memory workspace. Email is forced off no matter what the server has configured."""
    from kept.container import build_container

    demo_settings = settings.model_copy(update={"smtp_host": "", "email_from": ""})
    guard = DemoGuard(
        slots,
        notes=settings.demo_max_notes,
        drafts=settings.demo_max_drafts,
        max_note_chars=settings.demo_max_note_chars,
    )
    container = build_container(demo_settings, db=Database(":memory:"), guard=guard, **overrides)
    seed_sample_data(container)
    return container


def build_session_manager(settings: Settings, **overrides: Any) -> SessionManager:
    slots = asyncio.Semaphore(settings.demo_max_concurrent)
    return SessionManager(
        lambda: build_demo_container(settings, slots, **overrides),
        max_sessions=settings.demo_max_sessions,
        ttl_seconds=settings.demo_session_minutes * 60,
    )
