"""Synthetic, stateful API fixtures shared by the browser and HTTP adapters."""
from __future__ import annotations

import copy
import json
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml
from jsonschema import Draft202012Validator

from lapis_design import shared_dir


class SessionClock:
    def __init__(self, start_ms: int):
        self.start_ms = start_ms
        self._now = start_ms
        self._lock = threading.Lock()
        self._deadlines: list[tuple[int, object]] = []

    def now_ms(self) -> int:
        with self._lock:
            return self._now

    def at(self, deadline_ms: int, callback) -> None:
        """Run callback once the controlled time reaches deadline_ms (immediately if it already has)."""
        with self._lock:
            if deadline_ms > self._now:
                self._deadlines.append((deadline_ms, callback))
                return
        callback()

    def advance(self, ms: int) -> None:
        if ms < 0:
            raise ValueError("clock cannot go backwards")
        with self._lock:
            self._now += ms
            due = [callback for deadline, callback in self._deadlines if deadline <= self._now]
            self._deadlines = [(deadline, callback) for deadline, callback in self._deadlines if deadline > self._now]
        for callback in due:
            callback()


@dataclass
class StubResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    effects: int
    injected: str
    delay_ms: int = 0
    hang_ms: int = 0


def _epoch_ms(utc: str) -> int:
    return int(datetime.fromisoformat(utc.replace("Z", "+00:00")).timestamp() * 1000)


def _route_pattern(template: str) -> re.Pattern[str]:
    return re.compile("^" + "/".join(
        f"(?P<{segment[1:]}>[^/]+)" if segment.startswith(":") else re.escape(segment)
        for segment in template.split("/")
    ) + "$")


def _json_response(status: int, value: object, effects: int = 0, *, headers: dict[str, str] | None = None) -> StubResponse:
    return StubResponse(status, {"Content-Type": "application/json", **(headers or {})},
                        json.dumps(value, ensure_ascii=False).encode("utf-8"), effects, "none")


class StubEngine:
    """Fixture state belongs to this engine, not to individual browser contexts."""

    def __init__(self, fixture: dict, *, variant: str | None = None, clock: SessionClock | None = None):
        self.fixture = fixture
        self.clock = clock or SessionClock(_epoch_ms(fixture["clock"]["start"]))
        self._lock = threading.RLock()
        self._routes = [(r, _route_pattern(r["path"])) for r in fixture["routes"]]
        self._outside = [(r, _route_pattern(r["path"])) for r in fixture.get("outside", [])]
        for route in fixture["routes"]:
            if "collection" in route and route["collection"] not in fixture["collections"]:
                raise ValueError(f"unknown collection: {route['collection']}")
        for name, overrides in fixture["variants"].items():
            if set(overrides) - set(fixture["collections"]):
                raise ValueError(f"variant {name} names unknown collections")
        if fixture.get("auth"):
            identity = fixture["auth"]["sign_in"]
            if not any(r["method"] == identity["method"] and r["path"] == identity["path"] for r in fixture["routes"]):
                raise ValueError("auth.sign_in must name a route")
        for record in fixture.get("accounts", {}).values():
            if record not in fixture["values"]:
                raise ValueError(f"account references unknown value: {record}")
        self.reset(variant=variant)

    @classmethod
    def load(cls, path: Path, *, variant: str | None = None, clock: SessionClock | None = None) -> StubEngine:
        fixture = yaml.safe_load(path.read_text(encoding="utf-8"))
        schema = yaml.safe_load((shared_dir() / "behavior" / "stub.schema.yaml").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(fixture)
        return cls(fixture, variant=variant, clock=clock)

    def reset(self, *, variant: str | None = None) -> None:
        with self._lock:
            if variant is not None and variant not in self.fixture["variants"]:
                raise ValueError(f"unknown variant: {variant}")
            self._variant = variant
            self._collections = copy.deepcopy(self.fixture["collections"])
            if variant:
                self._collections.update(copy.deepcopy(self.fixture["variants"][variant]))
            for records in self._collections.values():
                ids = [r["id"] for r in records]
                if len(ids) != len(set(ids)):
                    raise ValueError("collection contains duplicate ids")
            self._serial = 0
            self._effects_total = 0
            self._injections: list[dict] = []
            self._replays: dict[str, StubResponse] = {}
            self._sessions: set[str] = set()

    @property
    def effects_total(self) -> int:
        with self._lock:
            return self._effects_total

    def inject(self, mode: str, *, method: str | None = None, path: str | None = None, times: int = 1) -> None:
        if mode not in {"delay", "fail-5xx", "fail-network", "hang", "forbidden", "not-found"}:
            raise ValueError(f"unknown injection: {mode}")
        if times < 1:
            raise ValueError("times must be positive")
        with self._lock:
            self._injections.append({"mode": mode, "method": method.upper() if method else None,
                                     "path": path, "times": times})

    def clear_injections(self) -> None:
        with self._lock:
            self._injections.clear()

    def _matching_injection(self, method: str, template: str, path: str) -> dict | None:
        for injection in self._injections:
            matcher = injection["path"]
            if (injection["method"] is None or injection["method"] == method) and (
                matcher is None or matcher == template or matcher == path or _route_pattern(matcher).fullmatch(path)
            ):
                return injection
        return None

    def _take_injection(self, method: str, template: str, path: str) -> str:
        injection = self._matching_injection(method, template, path)
        if injection is None:
            return "none"
        injection["times"] -= 1
        if not injection["times"]:
            self._injections.remove(injection)
        return injection["mode"]

    def _authorized(self, route: dict, headers: dict[str, str]) -> bool:
        if not route.get("require_session"):
            return True
        auth = self.fixture.get("auth")
        cookie = next((v for k, v in headers.items() if k.lower() == "cookie"), "")
        return bool(auth and any(
            part.strip() == f"{auth['cookie']}={token}"
            for part in cookie.split(";") for token in self._sessions
        ))

    def _reject_network(self, method: str, path: str, headers: dict[str, str]) -> bool:
        """Consume a matching network failure without reading a request body."""
        method = method.upper()
        path = unquote(urlsplit(path).path)
        with self._lock:
            for route, matcher in self._routes:
                if method != route["method"] or not matcher.fullmatch(path):
                    continue
                key = next((v for k, v in headers.items() if k.lower() == "idempotency-key"), None)
                if key and key in self._replays:
                    return self._replays[key].injected == "fail-network"
                if not self._authorized(route, headers):
                    return False
                injection = self._matching_injection(method, route["path"], path)
                if injection is None or injection["mode"] != "fail-network":
                    return False
                self._take_injection(method, route["path"], path)
                if key:
                    self._replays[key] = StubResponse(0, {}, b"", 0, "fail-network")
                return True
        return False

    def handle(self, method: str, path: str, query: str, headers: dict[str, str], body: bytes | None) -> StubResponse | None:
        method = method.upper()
        path = unquote(urlsplit(path).path)
        with self._lock:
            for route, matcher in self._routes:
                match = matcher.fullmatch(path) if method == route["method"] else None
                if match is None:
                    continue
                key = next((v for k, v in headers.items() if k.lower() == "idempotency-key"), None)
                if key and key in self._replays:
                    previous = self._replays[key]
                    return StubResponse(previous.status, dict(previous.headers), previous.body, 0, previous.injected,
                                        previous.delay_ms, 0)
                if not self._authorized(route, headers):
                    return _json_response(401, {"error": "session required"})
                mode = self._take_injection(method, route["path"], path)
                if mode in {"fail-5xx", "forbidden", "not-found", "fail-network"}:
                    response = (StubResponse(0, {}, b"", 0, mode) if mode == "fail-network" else
                                _json_response({"fail-5xx": 503, "forbidden": 403, "not-found": 404}[mode],
                                               {"error": mode}))
                    response.injected = mode
                else:
                    response = self._execute(route, match.groupdict(), body)
                    if mode == "delay":
                        response.injected, response.delay_ms = mode, 400
                    elif mode == "hang":
                        response.injected, response.hang_ms = mode, 10_000
                    self._effects_total += response.effects
                if key:
                    # A lost hang response is recoverable: replay the committed result, not another hang.
                    replay = copy.deepcopy(response)
                    if mode == "hang":
                        replay.injected, replay.hang_ms = "none", 0
                    self._replays[key] = replay
                return response
        return None

    def _execute(self, route: dict, params: dict[str, str], body: bytes | None) -> StubResponse:
        if "response" in route:
            value = route["response"]
            result = _json_response(value["status"], value["json"], route.get("effects", 0))
        else:
            records = self._collections[route["collection"]]
            operation = route["operation"]
            record = next((r for r in records if r["id"] == params.get("id")), None)
            if operation == "list":
                result = _json_response(200, records, route.get("effects", 0))
            elif operation == "get":
                result = _json_response(200, record, route.get("effects", 0)) if record else _json_response(404, {"error": "not found"})
            elif operation in {"update", "delete"} and record is None:
                result = _json_response(404, {"error": "not found"})
            elif operation == "delete":
                records.remove(record)
                result = _json_response(200, record, route.get("effects", 1))
            else:
                try:
                    data = json.loads(body or b"{}")
                    if not isinstance(data, dict):
                        raise ValueError("expected JSON object")
                except (ValueError, UnicodeError):
                    return _json_response(400, {"error": "invalid JSON object"})
                if operation == "create":
                    self._serial += 1
                    used = {r["id"] for r in records}
                    new_id = f"r-{self._serial}"
                    while new_id in used:
                        self._serial += 1
                        new_id = f"r-{self._serial}"
                    record = {**data, "id": new_id}
                    records.append(record)
                    result = _json_response(201, record, route.get("effects", 1))
                else:
                    record.update({k: v for k, v in data.items() if k != "id"})
                    result = _json_response(200, record, route.get("effects", 1))
        auth = self.fixture.get("auth")
        if auth and route["method"] == auth["sign_in"]["method"] and route["path"] == auth["sign_in"]["path"]:
            try:
                credentials = json.loads(body or b"{}")
            except (ValueError, UnicodeError):
                credentials = None
            account = self.fixture.get("accounts", {})
            if not isinstance(credentials, dict) or any(
                credentials.get(k) != self.value(account[k]) for k in ("username", "password")
            ):
                return _json_response(401, {"error": "invalid sign-in"})
            token = secrets.token_urlsafe(18)
            self._sessions.add(token)
            result.headers["Set-Cookie"] = f"{auth['cookie']}={token}; HttpOnly; SameSite=Lax; Path=/"
        return result

    def standin(self, host: str, method: str, path: str) -> StubResponse | None:
        with self._lock:
            for entry, matcher in self._outside:
                if entry["host"].lower() == host.lower() and entry["method"] == method.upper() and matcher.fullmatch(path):
                    return _json_response(entry["response"]["status"], entry["response"]["json"])
        return None

    def value(self, value_id: str) -> str:
        base, _, variant = value_id.partition(":")
        spec = self.fixture["values"][base]
        if variant == "empty":
            return ""
        if variant not in {"", "valid", "invalid", "alternate"}:
            raise KeyError(value_id)
        return spec[variant or "valid"]

    def values_for(self, field_kind: str, value: str) -> str:
        if value not in {"valid", "invalid", "empty", "alternate"}:
            raise ValueError(f"unknown value variant: {value}")
        for key, spec in self.fixture["values"].items():
            if spec["kind"] == field_kind:
                return key if value == "valid" else f"{key}:{value}"
        raise KeyError(field_kind)

    def all_values(self) -> dict[str, str]:
        return {key if variant == "valid" else f"{key}:{variant}": text
                for key, spec in self.fixture["values"].items()
                for variant in ("valid", "invalid", "alternate")
                if (text := spec[variant])}

    def backed(self, kind: str, value: float | int, *, now_ms: int, resolution_s: float = 2) -> bool:
        urgency = self.fixture.get("urgency", {})
        if kind in {"countdown", "deadline", "hold"}:
            target = urgency.get(kind)
            if not target:
                return False
            expiry = (_epoch_ms(target["at"]) if "at" in target else
                      self.clock.start_ms + target["hold_s"] * 1000)
            return abs(float(value) - max(0, (expiry - now_ms) / 1000)) <= max(2, resolution_s)
        if kind in {"stock", "demand"}:
            return value in urgency.get(kind, {}).values()
        if kind == "activity":
            return any(event["count"] == value for event in urgency.get("activity", []))
        return False

    def account(self) -> dict:
        return dict(self.fixture.get("accounts", {}))
