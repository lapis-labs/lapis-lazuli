"""One scoped router, request journal, and off-origin navigation guard."""
from __future__ import annotations

import json
from time import monotonic, sleep
from urllib.parse import urlsplit

from lapis_design import ours
from lapis_design.behavior_check.redact import path

_ALLOWED_ASSETS = {"script", "stylesheet", "font", "image"}
NAVIGATION_GUARD = """(() => {
  const source=__SOURCE_HOST__;
  function stop(event, address) {
    if(!address) return;
    const url=new URL(address,location.href);
    if(url.hostname===source || !['http:','https:'].includes(url.protocol)) return;
    event.preventDefault();
    window.__lapisExternalNavigation={url:url.href,method:event.type==='submit'?
       (event.target.method||'GET').toUpperCase():'GET'};
  }
  document.addEventListener('click', event => {
    const link=event.target.closest?.('a[href]');
    if(link && link.target!=='_blank') stop(event,link.href);
  },true);
  document.addEventListener('submit', event => stop(event,event.target.action),true);
})();"""


def navigation_guard(host: str) -> str:
    return NAVIGATION_GUARD.replace("__SOURCE_HOST__", json.dumps(host))


class Network:
    def __init__(self, driver):
        self.driver = driver
        self.source = urlsplit(driver.session.source["url"]).hostname
        self.entries: list[dict] = []
        self.pending: set = set()
        self.external = False
        self.external_path = None
        self._open: dict = {}

    def attach(self, context, page):
        page.on("request", self._on_request)
        page.on("requestfinished", self._finished)
        page.on("requestfailed", self._finished)
        context.route("**/*", self._route)

    def record_external(self, url: str, *, method: str = "GET") -> None:
        parsed = urlsplit(url)
        self.external = True
        self.external_path = path(url, self.driver.session.fixture_values)
        host = parsed.hostname or ""
        self.entries.append({"method": method, "host": host + (f":{parsed.port}" if parsed.port else ""),
                             "path": self.external_path, "kind": "document", "blocked": True,
                             "status": 0, "idempotency_key": False, "effects": 0,
                             "t_ms": self.driver.t_ms(), "duration_ms": 0})

    def _on_request(self, request):
        parsed = urlsplit(request.url)
        if request in self._open:
            return
        hostname = parsed.hostname or ""
        safe_host = "localhost" if hostname == "::1" else hostname
        safe_host += f":{parsed.port}" if parsed.port is not None else ""
        entry = {"method": request.method, "host": safe_host.lower(),
                 "path": path(request.url, self.driver.session.fixture_values),
                 "kind": {"document": "document", "fetch": "fetch", "xhr": "xhr",
                          "ping": "beacon", "websocket": "websocket"}.get(request.resource_type, "other"),
                 "idempotency_key": "idempotency-key" in {k.lower() for k in request.headers},
                 "t_ms": self.driver.t_ms()}
        self.entries.append(entry)
        self._open[request] = (entry, monotonic())
        self.pending.add(request)

    def _finished(self, request):
        self.pending.discard(request)
        if request not in self._open:
            return
        entry, started = self._open.pop(request)
        entry["duration_ms"] = round((monotonic() - started) * 1000, 2)
        if "status" not in entry:
            try:
                response = request.response()
                entry["status"] = response.status if response else 0
            except Exception:
                entry["status"] = 0

    def _route(self, route, request):
        from lapis_design.stub.playwright import respond
        parsed = urlsplit(request.url)
        entry = next((entry for req, (entry, _) in self._open.items() if req == request), None)
        if entry is None:
            self._on_request(request)
            entry = self._open[request][0]
        host = parsed.hostname or ""
        if request.is_navigation_request() and request.frame.parent_frame is None and host != self.source:
            self.external = True
            self.external_path = path(request.url, self.driver.session.fixture_values)
            entry.update(blocked=True, status=0)
            route.abort("blockedbyclient")
            return
        if self.driver.ctx["network"] == "offline" and self.driver._loaded:
            entry.update(status=0)
            route.abort("internetdisconnected")
            return
        engine = self.driver.session.engine
        if self.driver.ctx["network"] == "slow" and engine is not None and hasattr(engine, "handle"):
            sleep(0.4)
        if engine is not None and hasattr(engine, "handle") and host == self.source:
            result = respond(route, request, engine, now_ms=engine.clock.now_ms())
            if result is not None:
                entry.update(status=result.status, effects=result.effects, injected=result.injected,
                             idempotency_key=result.idempotency_key, duration_ms=result.duration_ms)
                return
        if engine is not None and hasattr(engine, "standin") and host != self.source:
            standin = engine.standin(host, request.method, parsed.path)
            if standin is not None:
                if standin.delay_ms:
                    sleep(standin.delay_ms / 1000)
                entry.update(status=standin.status, effects=standin.effects, injected=standin.injected)
                if standin.status == 0:
                    route.abort("connectionrefused")
                else:
                    route.fulfill(status=standin.status, headers=standin.headers, body=standin.body)
                return
        stub_pin = getattr(engine, "pin", None)
        addresses = (self.driver.session.source.get("addresses") if host == self.source else
                     list(stub_pin.addresses) if stub_pin is not None and host == stub_pin.host else None)
        if ours.source_is_ours(host, addresses):
            route.continue_()
        elif request.method == "GET" and request.resource_type in _ALLOWED_ASSETS:
            route.continue_()
        else:
            entry.update(blocked=True, status=0)
            route.abort("blockedbyclient")
