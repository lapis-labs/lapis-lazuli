"""Recorded starting points for a task's reference search, on three axes, and the independent references that must
accompany them.

`sources/hints.yaml` (v1) lists works and pages per axis: `genre` fields (pages of the subject's own kind),
`expression` modes (work that does what the owner's words ask for: motion, experimental type, ...), and `beyond-web`
media (posters, exhibitions, record covers, ...). An offer is three genre hints, two per chosen expression mode, and
two per chosen medium (at most two modes and two media), sorted by one hash of task, date, name, and URL, and recorded
in `.lapis/references/<task>.hints.json` (version 1). Hints are leads, not a canon.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date as calendar_date
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from lapis_design import attempts, shared_dir

COUNT = 3                       # genre hints
PER_NAME = 2                    # hints per expression mode or beyond-web medium
MAX_NAMES = 2                   # modes, and media, per offer
AXES = ("genre", "expression", "beyond-web")
VERSION = 1


@cache
def load() -> dict:
    return yaml.safe_load((shared_dir() / "sources/hints.yaml").read_text(encoding="utf-8"))


def names(axis: str) -> list[str]:
    return list(load()["axes"][axis])


def entries_of(axis: str, name: str) -> list[dict]:
    return load()["axes"][axis][name]["entries"]


def listed() -> list[str]:
    """Every hint URL on every axis."""
    return [entry["url"] for axis in load()["axes"].values() for data in axis.values() for entry in data["entries"]]


def _rotate(task: str, date: str, key: str, entries: list[dict], n: int) -> list[dict]:
    """Stable across data-file order; changing task or date rotates the starting points."""
    return sorted(entries, key=lambda entry: (
        hashlib.sha256(f"{task}\n{date}\n{key}\n{entry['url']}".encode()).digest(), entry["url"]))[:n]


def offer(task: str, field: str, date: str, n: int = COUNT) -> list[dict]:
    """The genre offer for `field` (`none` offers nothing)."""
    if field == "none":
        return []
    return _rotate(task, date, field, entries_of("genre", field), n)


def offer_axis(task: str, axis: str, name: str, date: str, n: int = PER_NAME) -> list[dict]:
    """The offer for one expression mode or beyond-web medium; the key carries the axis so names never collide."""
    return _rotate(task, date, f"{axis}/{name}", entries_of(axis, name), n)


def offered_urls(task: str, date: str, genre: str, expression: list[str], beyond_web: list[str]) -> list[str]:
    urls = [entry["url"] for entry in offer(task, genre, date)]
    for axis, chosen in (("expression", expression), ("beyond-web", beyond_web)):
        for name in chosen:
            urls += [entry["url"] for entry in offer_axis(task, axis, name, date)]
    return urls


def path(root: Path, task: str) -> Path:
    return root / ".lapis/references" / f"{task}.hints.json"


def _names(value: object, axis: str) -> list[str] | None:
    if (not isinstance(value, list) or len(value) > MAX_NAMES or len(set(value)) != len(value)
            or any(not isinstance(name, str) or name not in load()["axes"][axis] for name in value)):
        return None
    return value


def stale(root: Path, task: str) -> str | None:
    """Why a recorded offer that exists is out of date (a version 0 file lists one genre field only), or None."""
    try:
        record = json.loads(path(root, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(record, dict) and record.get("version") != VERSION:
        return (f"{path(root, task).relative_to(root).as_posix()} is an old version 0 offer (one genre field only); "
                "record it again with `lazuli hints --task <task> --genre <field|none> --expression <mode> "
                "--beyond-web <medium>`")
    return None


def read(root: Path, task: str) -> dict | None:
    """A complete recorded version 1 offer: its genre, modes, media, and URLs are known and match the draw they
    claim, so a trimmed list cannot erase the independent minimum."""
    try:
        record = json.loads(path(root, task).read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("task") != task or record.get("version") != VERSION:
            return None
        genre, date = record["genre"], record["date"]
        if not isinstance(genre, str) or not isinstance(date, str) or calendar_date.fromisoformat(date).isoformat() != date:
            return None
        if genre != "none" and genre not in load()["axes"]["genre"]:
            return None
        expression, beyond = _names(record["expression"], "expression"), _names(record["beyond_web"], "beyond-web")
        if expression is None or beyond is None:
            return None
        return record if record.get("offered") == offered_urls(task, date, genre, expression, beyond) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def draw(root: Path, task: str, genre: str, date: str, expression: list[str] | tuple[str, ...] = (),
         beyond_web: list[str] | tuple[str, ...] = ()) -> list[dict]:
    """Record the offer (or reprint the recorded one for the same choice, whatever the date) and return its entries
    in order: genre first, then each mode, then each medium."""
    if not attempts.TASK.fullmatch(task):
        raise ValueError("task must be lowercase letters, digits, and hyphens")
    if calendar_date.fromisoformat(date).isoformat() != date:
        raise ValueError("date must be YYYY-MM-DD")
    expression, beyond_web = list(expression), list(beyond_web)
    if genre != "none" and genre not in load()["axes"]["genre"]:
        raise ValueError(f"unknown genre field {genre!r}")
    if _names(expression, "expression") is None:
        raise ValueError(f"--expression takes at most {MAX_NAMES} of: {', '.join(names('expression'))}")
    if _names(beyond_web, "beyond-web") is None:
        raise ValueError(f"--beyond-web takes at most {MAX_NAMES} of: {', '.join(names('beyond-web'))}")
    if (record := read(root, task)) and (record["genre"], record["expression"], record["beyond_web"]) == (
            genre, expression, beyond_web):
        date = record["date"]
    else:
        destination = path(root, task)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({
            "version": VERSION, "task": task, "date": date, "genre": genre, "expression": expression,
            "beyond_web": beyond_web, "offered": offered_urls(task, date, genre, expression, beyond_web)},
            indent=2) + "\n", encoding="utf-8")
    return [*offer(task, genre, date),
            *(entry for name in expression for entry in offer_axis(task, "expression", name, date)),
            *(entry for name in beyond_web for entry in offer_axis(task, "beyond-web", name, date))]


def matches(url: str, hint: str) -> bool:
    """Same host without www., with the hint path as a whole-segment prefix; queries do not create a new find."""
    try:
        reference, source = urlsplit(url), urlsplit(hint)
        host = (reference.hostname or "").casefold().removeprefix("www.")
        own = (source.hostname or "").casefold().removeprefix("www.")
        prefix = source.path.rstrip("/")
        return bool(host and host == own and (not prefix or reference.path == prefix or reference.path.startswith(prefix + "/")))
    except ValueError:
        return False


def is_agent_found(ref: object) -> bool:
    """A reference that is not on the whole hints list (any axis), or has no address and names its own source."""
    if not isinstance(ref, dict):
        return False
    if isinstance(ref.get("url"), str) and ref["url"].strip():
        return not any(matches(ref["url"], hint) for hint in listed())
    return isinstance(ref.get("source"), str) and bool(ref["source"].strip())


def agent_found(references: list, axis: str | None = None) -> int:
    """Agent-found references in all, or on one axis."""
    return sum(1 for ref in references if is_agent_found(ref) and (axis is None or ref.get("axis") == axis))


def suggest(text: str) -> dict[str, list[str]]:
    """Expression modes whose owner words occur in `text`, each with the words found: a lexical lead, not a verdict."""
    low = text.casefold()
    found = {mode: [word for word in data["words"] if word.casefold() in low]
             for mode, data in load()["axes"]["expression"].items()}
    return {mode: words for mode, words in found.items() if words}
