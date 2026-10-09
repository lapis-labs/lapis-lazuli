"""Asks during the work: one short question when the work hits a conflict or a doubt, not a report.

A questions file of kind `ask` (`waiting.kind`) holds one numbered question, a `Trigger:` line naming why it is asked,
a `Default:` line, at most two "unless you object" lines, and at most `MAX_WORDS` words. It carries no owner block and
no draft review: a file that links a rendered page for approval is kind `approval`. `shape_problem` reads that shape;
a file that does not keep it does not wait, and `next` names the step it would name and says what is wrong.

The CLI keeps `.lapis/state/<task>.asks.json`, which the agent never writes (`order.CLI_OWNED`): every set of
questions the run waited on, as `{set, kind, trigger, then, asked, answered, cli}`. `then` is the step `next` named
while the set waited, which is the checkpoint the ask belongs to; `asked` and `answered` are the modification times of
the questions file and of the answers file that answered it, so the log does not depend on when `next` ran. A second
ask the agent raises at a checkpoint that already has an answered ask does not wait (`checkpoint_problem`): the run
takes its default and records it under `## Asks`. An ask the CLI itself raised (`cli`) is exempt.

Stdlib and `waiting`/`brief` only: the stop hook imports `next` at the end of every turn.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection

from lapis_design import brief, requirements, waiting

TRIGGERS = ("requirement-unmeetable", "requirement-conflict", "finding-vs-decision", "new-direction",
            "reference-vs-brief", "budget")
MAX_WORDS = 150
MAX_UNLESS = 2

_TRIGGER = re.compile(r"^[ \t]*trigger[ \t]*:[ \t]*([^\s—–]+)", re.IGNORECASE | re.MULTILINE)
_DEFAULT = re.compile(r"^[ \t]*default[ \t]*:[ \t]*\S", re.IGNORECASE | re.MULTILINE)
_UNLESS = re.compile(r"unless you object", re.IGNORECASE)


def log_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "state" / f"{task}.asks.json"


def load(root: Path, task: str) -> dict[str, Any]:
    """The log of `task`: `{"version": 0, "task", "sets": [...]}`, empty when there is none or it cannot be read."""
    try:
        doc = json.loads(log_path(root, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = None
    sets = doc.get("sets") if isinstance(doc, dict) else None
    return {"version": 0, "task": task,
            "sets": [s for s in sets or () if isinstance(s, dict) and isinstance(s.get("set"), str)]}


def trigger(text: str) -> str | None:
    """The word after `Trigger:` in the questions `text`, as written, or None when it has no such line."""
    found = _TRIGGER.search(waiting.question_text(text))
    return found.group(1).strip("`*_.,;:").lower() if found else None


def shape_problem(text: str) -> str | None:
    """Why the questions in `text` are not an ask, or None when they are: exactly one numbered question, a `Trigger:`
    line with one of the six ids, a `Default:` line, at most two "unless you object" lines, at most `MAX_WORDS` words."""
    body = waiting.question_text(text)
    numbered = sum(1 for line in body.splitlines() if brief._NUMBERED.match(line))
    if numbered != 1:
        return (f"an ask is one question, and it numbers {numbered}: keep the one the answer changes most, and take "
                "your default on the rest")
    named = trigger(text)
    if named is None:
        return f"it has no `Trigger:` line; name one of {', '.join(TRIGGERS)}"
    if named not in TRIGGERS:
        return f"`Trigger: {named}` is no trigger; the ones that exist are {', '.join(TRIGGERS)}"
    if not _DEFAULT.search(body):
        return "it has no `Default:` line saying what you will do if the owner takes it"
    unless = len(_UNLESS.findall(body))
    if unless > MAX_UNLESS:
        return f"it has {unless} \"unless you object\" lines, and an ask carries at most {MAX_UNLESS}"
    counted = waiting.words(text)
    if counted > MAX_WORDS:
        return f"it is {counted} words, and an ask is at most {MAX_WORDS}: ask the question, not a report of the work"
    return None


def _iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def observe(root: Path, task: str, then: str, found: dict[str, Any] | None, exempt: Collection[str] = ()) -> None:
    """Record in the log the set `found` that the run waits on (as asked, at checkpoint `then`) and mark the set the
    answers file now answers as answered. `exempt` holds the triggers the CLI itself raises: an ask with one of them
    is recorded as `cli`. A log that cannot be written is left as it was."""
    current = waiting.current(root, task)
    log = load(root, task)
    sets = log["sets"]
    changed = False
    if found is not None and current is not None and not any(s["set"] == found["id"] for s in sets):
        named = trigger(current["text"]) if found["kind"] == "ask" else None
        sets.append({"set": found["id"], "kind": found["kind"], "trigger": named, "then": then,
                     "asked": _iso(current["asked_ns"]), "answered": None, "cli": named in exempt if named else False})
        changed = True
    if current is not None and current["answered"]:
        for entry in sets:
            if entry["set"] == current["id"] and not entry.get("answered"):
                entry["answered"] = _iso(current["answered_ns"])
                changed = True
    if changed:
        try:
            requirements.write_atomic(log_path(root, task), json.dumps(log, ensure_ascii=False, indent=2) + "\n")
        except OSError:
            pass


def checkpoint_problem(root: Path, task: str, then: str, exempt: Collection[str] = ()) -> str | None:
    """Why the ask now in the questions file does not wait, or None: an earlier ask the agent raised at the same
    checkpoint `then` was answered already, and this one is not one the CLI raises (`exempt`)."""
    current = waiting.current(root, task)
    if current is None or current["kind"] != "ask":
        return None
    named = trigger(current["text"])
    if named in exempt:
        return None
    for entry in load(root, task)["sets"]:
        if (entry.get("kind") == "ask" and entry.get("then") == then and entry.get("answered") and not entry.get("cli")
                and entry["set"] != current["id"]):
            return ("one ask per checkpoint, and this checkpoint's ask was answered already. Take your default, record "
                    "`- [assumed] Ask <trigger>: <the question> — took <default>. Basis: <why>` under `## Asks` in the "
                    "brief record, and go on; the owner sees it at the next checkpoint (the next approval wait, the next "
                    "ask, or `done`)")
    return None
