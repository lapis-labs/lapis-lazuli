"""Threaded HTTP transport and compact JSON control surface for a StubEngine."""
from __future__ import annotations

import ipaddress
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from .engine import StubEngine, StubResponse


class StubServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host: str, port: int, engine: StubEngine):
        super().__init__((host, port), StubHandler)
        self.engine = engine


def _local_host(host: str) -> bool:
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    return bool(addresses) and all(
        (address := ipaddress.ip_address(item[4][0])).is_loopback or
        (address.is_private and not address.is_unspecified and not address.is_multicast)
        for item in addresses
    )


def make_server(engine: StubEngine, *, host: str = "127.0.0.1", port: int = 0) -> StubServer:
    if not _local_host(host):
        raise ValueError("stub server binds only loopback or private addresses")
    return StubServer(host, port, engine)


class StubHandler(BaseHTTPRequestHandler):
    server: StubServer

    def log_message(self, format: str, *args: object) -> None:
        # Never log URLs, query strings, headers, or bodies from the app.
        pass

    def _read(self) -> bytes:
        size = int(self.headers.get("Content-Length", "0"))
        if size < 0 or size > 1024 * 1024:
            raise ValueError("request too large")
        return self.rfile.read(size) if size else b""

    def _send(self, response: StubResponse) -> None:
        self.send_response(response.status)
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        try:
            self.wfile.write(response.body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, value: object) -> None:
        body = json.dumps(value).encode("utf-8")
        self._send(StubResponse(status, {"Content-Type": "application/json"}, body, 0, "none"))

    def do_GET(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def _dispatch(self) -> None:
        parsed = urlsplit(self.path)
        try:
            if not parsed.path.startswith("/__lapis/") and self.server.engine._reject_network(
                self.command, parsed.path, dict(self.headers)
            ):
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            body = self._read()
            if parsed.path.startswith("/__lapis/"):
                self._admin(parsed.path, body)
                return
            response = self.server.engine.handle(self.command, parsed.path, parsed.query,
                                                 dict(self.headers), body)
            if response is None:
                self._json(404, {"error": "not found"})
            elif response.injected == "fail-network":
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
            elif response.injected == "hang":
                # Close when the session clock passes the deadline (advanced through /__lapis/clock/advance).
                closed = threading.Event()
                self.server.engine.clock.at(self.server.engine.clock.now_ms() + response.hang_ms, closed.set)
                closed.wait()
                self.close_connection = True
            else:
                if response.delay_ms:
                    time.sleep(response.delay_ms / 1000)
                self._send(response)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})

    def _admin(self, path: str, body: bytes) -> None:
        engine = self.server.engine
        if self.command == "GET":
            if path == "/__lapis/clock":
                return self._json(200, {"now_ms": engine.clock.now_ms()})
            if path == "/__lapis/effects":
                return self._json(200, {"effects_total": engine.effects_total})
            if path == "/__lapis/values":
                return self._json(200, engine.all_values())
            if path.startswith("/__lapis/values/"):
                return self._json(200, {"value": engine.value(unquote(path.removeprefix("/__lapis/values/")))})
            if path == "/__lapis/account":
                return self._json(200, engine.account())
        if self.command == "POST":
            args = json.loads(body or b"{}")
            if path == "/__lapis/inject":
                engine.inject(args["mode"], method=args.get("method"), path=args.get("path"), times=args.get("times", 1))
                return self._json(200, {"ok": True})
            if path == "/__lapis/clear":
                engine.clear_injections()
                return self._json(200, {"ok": True})
            if path == "/__lapis/reset":
                engine.reset(variant=args.get("variant"))
                return self._json(200, {"ok": True})
            if path == "/__lapis/clock/advance":
                engine.clock.advance(args["ms"])
                return self._json(200, {"now_ms": engine.clock.now_ms()})
            if path == "/__lapis/values/lookup":
                return self._json(200, {"value_id": engine.values_for(args["field_kind"], args["value"])})
            if path == "/__lapis/backed":
                return self._json(200, {"backed": engine.backed(args["kind"], args["value"],
                                   now_ms=args["now_ms"], resolution_s=args.get("resolution_s", 2))})
        self._json(404, {"error": "not found"})
