"""Helpers shared by test modules."""

import httpx

from kept.api.app import create_app
from kept.config import Settings
from kept.demo import SessionManager


def demo_client(settings: Settings, manager: SessionManager) -> httpx.AsyncClient:
    """An independent "browser" (its own cookie jar) talking to a demo-mode app."""
    app = create_app(sessions=manager, settings=settings)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
