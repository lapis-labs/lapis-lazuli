"""Fulfill in-browser API requests from the same engine used by the HTTP server."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from .engine import StubEngine


@dataclass
class RouteResult:
    status: int
    injected: str
    effects: int
    idempotency_key: bool
    duration_ms: float


def respond(route, request, engine: StubEngine, *, now_ms: int) -> RouteResult | None:
    """Return None for an unmatched URL; caller continues the request normally.

    The sync Playwright API is owned by its creating thread. A hanging response is aborted
    on Playwright's underlying asyncio loop once the session clock passes its deadline.
    """
    started = time.monotonic()
    url = urlsplit(request.url)
    headers = dict(request.headers)
    keyed = any(name.lower() == "idempotency-key" for name in headers)
    if engine._reject_network(request.method, url.path, headers):
        route.abort("connectionrefused")
        return RouteResult(0, "fail-network", 0, keyed, (time.monotonic() - started) * 1000)
    response = engine.handle(request.method, url.path, url.query, headers, request.post_data_buffer)
    if response is None:
        return None
    if response.injected == "fail-network":
        route.abort("connectionrefused")
    elif response.injected == "hang":
        loop = route._loop
        async_route = route._impl_obj

        async def abort_later() -> None:
            try:
                await async_route.abort("connectionrefused")
            except Exception:
                # A closed page/browser has already ended the pending request.
                pass

        def close() -> None:
            if not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(lambda: loop.create_task(abort_later()))
                except RuntimeError:
                    pass  # the loop closed between the check and scheduling

        engine.clock.at(engine.clock.now_ms() + response.hang_ms, close)
    else:
        if response.delay_ms:
            time.sleep(response.delay_ms / 1000)
        route.fulfill(status=response.status, headers=response.headers, body=response.body)
    return RouteResult(0 if response.injected == "hang" else response.status, response.injected, response.effects, keyed,
                       (time.monotonic() - started) * 1000 + (response.hang_ms if response.injected == "hang" else 0))
