"""Failure records: `.lapis/attempts/<task>/<step>.json`, written by the checks themselves.

A check that cannot run because of its environment (Chromium that is missing or cannot start, a sandbox
that denies a file) says so in one record: the reason, the command, its exit status, and the time.
`lapis-design next` counts a fresh record as that step done, since the check was tried and the
environment is what stopped it. Nothing else counts: a missing input, an invalid input, a timeout, a
finding, or a plan blocker is never recorded here and never excuses a step. The record belongs to the
tool; an agent that writes one by hand writes a claim, which the release gate still shows as a check
that did not run.

One more record is no failure: `lapis-design next --declined references --brief-line "<quote>"` writes
`.lapis/attempts/<task>/references.json` with `kind: declined-by-brief`, the user's own line, and the time, for a
run whose user's words could forbid the lookups the step needs and who cannot be asked. `read` never returns it
(the environment did not stop anything); `read_declined` does, and whoever counts it checks the line again.

The module is imported by `render check`, `behavior check`, `release check`, and `next`, so it stays
light: no jsonschema, no YAML.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# render, behavior, and release record themselves; a critic that cannot start, or references that cannot be
# looked at for want of a network, are recorded through `lapis-design next --unavailable <step>`, since no
# command of ours runs them
STEPS = ("render", "behavior", "release", "critic", "references")
DECLINABLE = ("references",)         # the steps a run can decline with the user's own line
TASK = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
KIND = "environment"
DECLINED = "declined-by-brief"


def path(root: Path, task: str, step: str) -> Path:
    return root / ".lapis" / "attempts" / task / f"{step}.json"


def environment_reason(exc: BaseException) -> str | None:
    """One line for a failure that comes from the environment, else None: a browser that is not
    installed or cannot start, or a path the sandbox denies."""
    from lapis_design.chromium import BrowserUnavailable

    if isinstance(exc, BrowserUnavailable):
        return str(exc).splitlines()[0]
    if isinstance(exc, PermissionError):
        return (str(exc).splitlines() or ["permission denied"])[0]
    return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(target: Path, document: dict[str, Any]) -> Path | None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return None
    return target


def record(root: Path, task: str, step: str, command: list[str], exit_code: int | None, reason: str) -> Path | None:
    """Write the record for `step`; returns its path, or None when it cannot be written (a record is
    best effort: the check's own error is what the caller reports)."""
    if step not in STEPS or not TASK.fullmatch(task):
        return None
    return _write(path(root, task, step), {
        "version": 0, "task": task, "step": step, "failure_kind": KIND, "reason": reason, "command": command,
        "exit": exit_code, "at": _now()})


def record_declined(root: Path, task: str, step: str, command: list[str], brief_line: str) -> Path | None:
    """Write the record that `step` was declined with `brief_line`, the user's own words; None when the step
    cannot be declined or the record cannot be written. Whether the line is in the brief is the caller's check."""
    if step not in DECLINABLE or not TASK.fullmatch(task):
        return None
    return _write(path(root, task, step), {
        "version": 0, "task": task, "step": step, "kind": DECLINED, "brief_line": brief_line, "command": command,
        "at": _now()})


def record_failure(exc: BaseException, *, task: str | None, step: str, command: list[str], exit_code: int,
                   full_run: bool, root: Path = Path(".")) -> Path | None:
    """Record `exc` for a check's step when it is an environment failure of a full run.

    A run narrowed by a flag, or one that writes somewhere else, is not the step the gate reads, so
    it leaves no record, as it leaves no full report."""
    reason = environment_reason(exc)
    if not (reason and task and full_run):
        return None
    return record(root, task, step, command, exit_code, reason)


def command_line(prog: str, argv: list[str] | None) -> list[str]:
    """The command a check was started with, as its record names it."""
    return [*prog.split(), *(sys.argv[1:] if argv is None else argv)]


def clear(task: str | None, step: str, root: Path = Path(".")) -> None:
    """Remove the record for `step` after the check ran and wrote its report, so an old failure never
    stands in for a report that is later deleted."""
    if task and step in STEPS and TASK.fullmatch(task):
        try:
            path(root, task, step).unlink(missing_ok=True)
        except OSError:
            pass


def read(root: Path, task: str, step: str) -> dict[str, Any] | None:
    """The record for `step` when it is one of ours for this task and step, else None."""
    try:
        document = json.loads(path(root, task, step).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (isinstance(document, dict) and document.get("version") == 0 and document.get("failure_kind") == KIND
            and document.get("task") == task and document.get("step") == step
            and isinstance(document.get("reason"), str) and document["reason"]
            and isinstance(document.get("command"), list) and isinstance(document.get("at"), str)):
        return document
    return None


def read_declined(root: Path, task: str, step: str) -> dict[str, Any] | None:
    """The declined record for `step` when it is one of ours for this task and step, else None."""
    try:
        document = json.loads(path(root, task, step).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (isinstance(document, dict) and document.get("version") == 0 and document.get("kind") == DECLINED
            and step in DECLINABLE and document.get("task") == task and document.get("step") == step
            and isinstance(document.get("brief_line"), str) and document["brief_line"].strip()
            and isinstance(document.get("command"), list) and isinstance(document.get("at"), str)):
        return document
    return None
