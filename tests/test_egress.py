import httpx
import pytest

from kept.adapters.egress import EgressBlockedError, build_http_client
from kept.domain.models import AuditEvent


class ListSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def _ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


async def test_allowed_host_passes_and_is_audited() -> None:
    sink = ListSink()
    client = build_http_client(["api.ok.test"], sink, inner=httpx.MockTransport(_ok))
    response = await client.post("https://api.ok.test/v1/x?secret=abc", json={"a": 1})
    assert response.status_code == 200
    (event,) = sink.events
    assert (event.host, event.path, event.blocked, event.status_code) == (
        "api.ok.test",
        "/v1/x",
        False,
        200,
    )
    assert event.bytes_out > 0
    assert "secret" not in event.model_dump_json()


async def test_blocked_host_raises_and_is_audited() -> None:
    sink = ListSink()
    client = build_http_client(["api.ok.test"], sink, inner=httpx.MockTransport(_ok))
    with pytest.raises(EgressBlockedError):
        await client.get("https://evil.test/leak")
    (event,) = sink.events
    assert event.blocked is True
    assert event.host == "evil.test"
    assert event.status_code is None


async def test_allowlist_is_exact_not_suffix() -> None:
    sink = ListSink()
    client = build_http_client(["ok.test"], sink, inner=httpx.MockTransport(_ok))
    with pytest.raises(EgressBlockedError):
        await client.get("https://sub.ok.test/")
