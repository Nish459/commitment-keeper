"""Tavily web search. Uses the shared audited HTTP client."""

import httpx

from kept.domain.errors import SearchError
from kept.domain.models import SearchResult

_SEARCH_URL = "https://api.tavily.com/search"


class TavilySearch:
    def __init__(self, api_key: str, http_client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._http = http_client

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self._api_key:
            raise SearchError("KEPT_TAVILY_API_KEY is not set")
        try:
            response = await self._http.post(
                _SEARCH_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"query": query, "max_results": max_results, "search_depth": "basic"},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchError(f"Tavily search failed: {exc}") from exc
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item["url"],
                snippet=item.get("content", ""),
            )
            for item in payload.get("results", [])
            if item.get("url")
        ]
