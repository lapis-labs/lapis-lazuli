"""Three recorded genre hints, and the independent references that must accompany them."""
from __future__ import annotations

import hashlib
import json
from datetime import date as calendar_date
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from lapis_design import attempts, shared_dir

COUNT = 3


@cache
def load() -> dict:
    return yaml.safe_load((shared_dir() / "sources/hints.yaml").read_text(encoding="utf-8"))


def offer(task: str, field: str, date: str, n: int = COUNT) -> list[dict]:
    """Stable across data-file order; changing task or date rotates the starting points."""
    if field == "none":
        return []
    entries = load()["fields"][field]["entries"]
    return sorted(entries, key=lambda entry: (
        hashlib.sha256(f"{task}\n{date}\n{field}\n{entry['url']}".encode()).digest(), entry["url"]))[:n]


def path(root: Path, task: str) -> Path:
    return root / ".lapis/references" / f"{task}.hints.json"


def read(root: Path, task: str) -> dict | None:
    """A complete recorded offer, not an arbitrary count that could erase the independent minimum."""
    try:
        record = json.loads(path(root, task).read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("task") != task:
            return None
        field, date = record["field"], record["date"]
        if not isinstance(field, str) or not isinstance(date, str) or calendar_date.fromisoformat(date).isoformat() != date:
            return None
        expected = [entry["url"] for entry in offer(task, field, date)]
        return record if record.get("offered") == expected else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def draw(root: Path, task: str, field: str, date: str) -> list[dict]:
    if not attempts.TASK.fullmatch(task):
        raise ValueError("task must be lowercase letters, digits, and hyphens")
    if calendar_date.fromisoformat(date).isoformat() != date:
        raise ValueError("date must be YYYY-MM-DD")
    if (record := read(root, task)) and record["field"] == field:
        return offer(task, field, record["date"])
    entries = offer(task, field, date)
    destination = path(root, task)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"task": task, "field": field, "date": date,
                                       "offered": [entry["url"] for entry in entries]}, indent=2) + "\n", encoding="utf-8")
    return entries


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


def agent_found(references: list) -> int:
    listed = [entry["url"] for field in load()["fields"].values() for entry in field["entries"]]
    return sum(1 for ref in references if isinstance(ref, dict) and (
        isinstance(ref.get("url"), str) and bool(ref["url"].strip()) and not any(matches(ref["url"], hint) for hint in listed)
        or not ref.get("url") and isinstance(ref.get("source"), str) and bool(ref["source"].strip())))
