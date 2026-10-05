import json

import httpx
import pytest

from kept.adapters.egress import build_http_client
from kept.adapters.tavily import SearchError, TavilySearch
from kept.domain.models import AuditEvent


class NullSink:
    def record(self, event: AuditEvent) -> None:
        pass


def _search(handler: httpx.MockTransport, key: str = "k") -> TavilySearch:
    http = build_http_client(["api.tavily.com"], NullSink(), inner=handler)
    return TavilySearch(key, http)


async def test_search_maps_results_and_sends_bearer_auth() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {
            "results": [
                {"title": "A", "url": "https://a.test", "content": "alpha"},
                {"title": "no url", "content": "dropped"},
            ]
        }
        return httpx.Response(200, json=body)

    results = await _search(httpx.MockTransport(handler)).search("q", max_results=3)
    assert [(r.title, r.url, r.snippet) for r in results] == [("A", "https://a.test", "alpha")]
    assert seen[0].headers["authorization"] == "Bearer k"
    assert json.loads(seen[0].content)["max_results"] == 3


async def test_search_wraps_http_errors() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(500))
    with pytest.raises(SearchError):
        await _search(transport).search("q")


async def test_search_requires_key() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    with pytest.raises(SearchError, match="not set"):
        await _search(transport, key="").search("q")
