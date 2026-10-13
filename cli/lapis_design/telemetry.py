"""Local measurement log of the checks: one JSON line per check invocation in `.lapis/telemetry/checks.jsonl`.

The log never leaves the machine and nothing reads it back to decide anything. A check that cannot write it still
runs: measurement must not change a result, so a failed write is dropped.

Fields of a line (all always present; a value that does not apply is `null`):

    command        the check as typed, e.g. "render check", "behavior check", "slop lint", "worker check"
    task           the task id, or null
    build_id       hash of what the browser loads (check_cache.build_id), or null when it cannot be established
    state_key      hash of the build and every request parameter, or null
    scope          "full" | "narrow" | "delta"
    cache          "hit" (a stored result was reused), "join" (waited for a concurrent identical run and shared its
                   result), "miss" (ran, and stored the result), "off" (ran; no identity, `--fresh`, or an unstable build)
    started, ended UTC ISO-8601 with milliseconds
    exit           the command's exit code
    output_chars   characters the command printed to stdout
    report_path    where the report was written (project-relative when under the project), or null

A line may carry more fields (`cache_reason`, `run_seconds`); readers ignore ones they do not know.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIELDS = ("command", "task", "build_id", "state_key", "scope", "cache", "started", "ended", "exit", "output_chars",
          "report_path")
SCOPES = ("full", "narrow", "delta")
CACHES = ("hit", "join", "miss", "off")


def log_path(root: Path) -> Path:
    return Path(root) / ".lapis" / "telemetry" / "checks.jsonl"


def stamp(moment: datetime | None = None) -> str:
    """A UTC ISO-8601 time with milliseconds, the form `started` and `ended` take."""
    return (moment or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="milliseconds")


def record(root: Path, **fields: Any) -> None:
    """Append one line for a check invocation. Unknown fields are kept; the listed ones are always written."""
    line = {name: fields.pop(name, None) for name in FIELDS}
    line.update(fields)
    if line["scope"] not in SCOPES and line["scope"] is not None:
        line["scope"] = None
    if line["cache"] not in CACHES and line["cache"] is not None:
        line["cache"] = None
    for name in ("report_path",):
        if isinstance(line[name], Path):
            line[name] = line[name].as_posix()
    path = log_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(line, ensure_ascii=False, default=str) + "\n").encode("utf-8")
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(descriptor, data)          # one write of one line: concurrent checks do not interleave
        finally:
            os.close(descriptor)
    except OSError:
        pass
