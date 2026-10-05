"""The single outbound HTTP path. Allowlist enforcement plus a metadata-only audit trail."""

import time
from collections.abc import Collection

import httpx

from kept.domain.models import AuditEvent
from kept.domain.ports import AuditSink


class EgressBlockedError(httpx.TransportError):
    """Raised when a request targets a host that is not on the allowlist."""


class AuditedTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        allowlist: Collection[str],
        sink: AuditSink,
    ) -> None:
        self._inner = inner
        self._allowlist = frozenset(host.lower() for host in allowlist)
        self._sink = sink

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host.lower()
        event = AuditEvent(
            method=request.method,
            host=host,
            path=request.url.path,
            bytes_out=int(request.headers.get("content-length", 0)),
        )
        if host not in self._allowlist:
            event.blocked = True
            self._sink.record(event)
            raise EgressBlockedError(f"Egress to {host} is not allowed", request=request)

        started = time.monotonic()
        try:
            response = await self._inner.handle_async_request(request)
        except httpx.HTTPError:
            event.duration_ms = int((time.monotonic() - started) * 1000)
            self._sink.record(event)
            raise
        event.status_code = response.status_code
        event.duration_ms = int((time.monotonic() - started) * 1000)
        self._sink.record(event)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


def build_http_client(
    allowlist: Collection[str],
    sink: AuditSink,
    *,
    inner: httpx.AsyncBaseTransport | None = None,
    timeout: float = 60.0,
) -> httpx.AsyncClient:
    """The only place an httpx client is constructed; everything else receives this one."""
    transport = AuditedTransport(inner or httpx.AsyncHTTPTransport(), allowlist, sink)
    return httpx.AsyncClient(transport=transport, timeout=timeout)
