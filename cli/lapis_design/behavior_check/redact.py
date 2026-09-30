"""Remove sensitive path segments and fixture values before persisting observations."""
from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

_ID = re.compile(r"\d{4,}|[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}", re.I)
_LONG = re.compile(r"\b(?=[A-Za-z\d]{16,}\b)(?=[A-Za-z\d]*\d)[A-Za-z\d]+\b")
_URL = re.compile(r"https?://[^\s<>'\"]+")


def path(url_or_path: str, values: dict[str, str] | None = None) -> str:
    parsed = urlsplit(url_or_path)
    segments = []
    for segment in (parsed.path or "/").split("/"):
        if _ID.search(segment) or _LONG.search(segment):
            segments.append(":id")
            continue
        for fixture, replacement in _value_tokens(values):
            segment = _replace(_replace(segment, fixture, replacement), quote(fixture, safe=""), replacement)
        segments.append(segment)
    return "/".join(segments)


def _value_tokens(values: dict[str, str] | None) -> list[tuple[str, str]]:
    return [(fixture, "{" + key.split(":", 1)[0] + "}")
            for key, fixture in sorted((values or {}).items(), key=lambda item: -len(item[1])) if fixture]


def _replace(value: str, fixture: str, replacement: str) -> str:
    # Whole tokens only: an entered value is never glued to other letters or digits, and a short value
    # such as "0000" must not rewrite part of an unrelated number ("30000ms").
    return re.sub(rf"(?<![0-9A-Za-z]){re.escape(fixture)}(?![0-9A-Za-z])", lambda _: replacement, value)


def text(value: str, values: dict[str, str] | None = None) -> str:
    for fixture, replacement in _value_tokens(values):
        value = _replace(value, fixture, replacement)
    return value


def console(value: str, values: dict[str, str] | None = None) -> str:
    def replace(match):
        parsed = urlsplit(match.group(0))
        return (parsed.hostname or "") + path(parsed.path, values)
    return _LONG.sub("…", _URL.sub(replace, text(value, values)))
