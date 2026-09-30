"""Control a running stub server without importing a browser or extra HTTP clients."""
from __future__ import annotations

import http.client
import json
import socket
import ssl
from urllib.parse import quote, urlsplit
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from lapis_design.ours import SourcePin


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, port: int, *, timeout: int,
                 context: ssl.SSLContext | None = None):
        super().__init__(host, port, timeout=timeout, context=context)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class _RemoteClock:
    def __init__(self, remote: RemoteStub):
        self._remote = remote

    def now_ms(self) -> int:
        return self._remote._request("GET", "clock")["now_ms"]

    def advance(self, ms: int) -> None:
        self._remote._request("POST", "clock/advance", {"ms": ms})


class RemoteStub:
    def __init__(self, base_url: str, *, pin: SourcePin | None = None,
                 ssl_context: ssl.SSLContext | None = None):
        self.base_url = base_url.rstrip("/")
        self.pin = pin
        self.ssl_context = ssl_context
        if pin is None:
            handlers = [ProxyHandler({})]
            if ssl_context is not None:
                handlers.append(HTTPSHandler(context=ssl_context))
            self._opener = build_opener(*handlers)
        else:
            self._opener = None
        self.clock = _RemoteClock(self)

    def _request(self, method: str, endpoint: str, data: dict | None = None):
        payload = json.dumps(data).encode("utf-8") if data is not None else None
        url = f"{self.base_url}/__lapis/{endpoint}"
        if self.pin is not None:
            parsed = urlsplit(url)
            port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
            if parsed.scheme == "https":
                connection = _PinnedHTTPSConnection(self.pin.host, self.pin.address, port, timeout=15,
                                                    context=self.ssl_context)
            else:
                connection = http.client.HTTPConnection(self.pin.address, port, timeout=15)
            try:
                connection.request(method, parsed.path, body=payload,
                                   headers={"Host": parsed.netloc, "Content-Type": "application/json"})
                response = connection.getresponse()
                if response.status >= 400:
                    raise ValueError(f"stub control returned HTTP {response.status}")
                return json.load(response)
            finally:
                connection.close()
        request = Request(url, data=payload, method=method, headers={"Content-Type": "application/json"})
        with self._opener.open(request, timeout=15) as response:
            return json.load(response)

    def inject(self, mode: str, *, method: str | None = None, path: str | None = None, times: int = 1) -> None:
        self._request("POST", "inject", {"mode": mode, "method": method, "path": path, "times": times})

    def clear_injections(self) -> None:
        self._request("POST", "clear", {})

    def reset(self, *, variant: str | None = None) -> None:
        self._request("POST", "reset", {"variant": variant})

    @property
    def effects_total(self) -> int:
        return self._request("GET", "effects")["effects_total"]

    def value(self, value_id: str) -> str:
        return self._request("GET", f"values/{quote(value_id, safe='')}")["value"]

    def values_for(self, field_kind: str, value: str) -> str:
        return self._request("POST", "values/lookup", {"field_kind": field_kind, "value": value})["value_id"]

    def all_values(self) -> dict[str, str]:
        return self._request("GET", "values")

    def backed(self, kind: str, value: float | int, *, now_ms: int, resolution_s: float = 2) -> bool:
        return self._request("POST", "backed", {"kind": kind, "value": value, "now_ms": now_ms,
                                                   "resolution_s": resolution_s})["backed"]

    def account(self) -> dict:
        return self._request("GET", "account")
