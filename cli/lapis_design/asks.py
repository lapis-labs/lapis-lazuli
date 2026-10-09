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

Three triggers are the CLI's own (`detected`, `CLI_TRIGGERS`), read from the change log and the clocks after the slice
is sealed: `new-direction` (a direction pointer of `DIRECTION_POINTERS` holds another value than at the seal),
`finding-vs-decision` (a change on an area the owner decided while a finding about it was open), and `budget` (more than
`BUDGET_MINUTES`, or the owner's `- Budget: <n> min` line, since the later of the last answered set and the seal; attended
runs only). `detected` gives the step `ask` while a trigger is pending; an answer to it, or the value put back, lifts it.

Stdlib and `waiting`/`brief` only until `detected` reads the change log: the stop hook imports `next` at the end of every turn.
"""
from __future__ import annotations

import json
import re
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection

from lapis_design import brief, requirements, waiting

TRIGGERS = ("requirement-unmeetable", "requirement-conflict", "finding-vs-decision", "new-direction",
            "reference-vs-brief", "budget")
CLI_TRIGGERS = ("new-direction", "finding-vs-decision", "budget")   # raised by `detected`: exempt from one ask per checkpoint
BUDGET_MINUTES = 90                    # provisional: agent-alone time after the seal before the budget ask
DIRECTION_POINTERS = ("/direction/concept", "/direction/levers", "/layout/signature", "/layout/sections",
                      "/tokens/type/roles", "/tokens/motion/principles")
AREA_POINTERS = {"color": ("/tokens/color/roles",), "type": ("/tokens/type/roles",), "layout": ("/layout/",),
                 "motion": ("/tokens/motion",), "signature": ("/layout/signature", "/direction/levers")}
MAX_WORDS = 150
MAX_UNLESS = 2

_TRIGGER = re.compile(r"^[ \t]*trigger[ \t]*:[ \t]*([^\s—–]+)", re.IGNORECASE | re.MULTILINE)
_DEFAULT = re.compile(r"^[ \t]*default[ \t]*:[ \t]*\S", re.IGNORECASE | re.MULTILINE)
_UNLESS = re.compile(r"unless you object", re.IGNORECASE)
_BUDGET = re.compile(r"^[ \t]*[-*+][ \t]+Budget[ \t]*:[ \t]*(\d+)[ \t]*min(?:ute)?s?\b", re.IGNORECASE | re.MULTILINE)
_ROLE = re.compile(r"role=([^,\]]+)")


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


_ASK_ITEM = re.compile(r"^[\s*_`:\-–—]*Ask\s+([a-z][a-z-]*)\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL)
_BASIS_TAIL = re.compile(r"\s*\bbasis\b\s*:.*$", re.IGNORECASE | re.DOTALL)


def recorded(root: Path, task: str) -> list[dict[str, str]]:
    """The items under `## Asks` of the brief record, in file order, as `{"trigger", "by", "said"}`: `by` is `owner` for a
    `[declared]` item and `run` for an `[assumed]` one, and `said` is the decision (or the question and the default the run
    took) in the words written, without a `Basis:` (the run's own reason is not the critic's to read)."""
    try:
        text = waiting.answers_path(root, task).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for item in brief.items(brief.sections(text).get("asks", "")):
        tag = brief._TAG.match(item)
        match = _ASK_ITEM.match(item[tag.end():] if tag else item)
        trigger, said = (match.group(1).lower(), match.group(2)) if match else ("unnamed", item)
        found.append({"trigger": trigger, "by": "run" if tag and tag.group(1).lower() == "assumed" else "owner",
                      "said": " ".join(_BASIS_TAIL.sub("", said).split())})
    return found


# ---------------------------------------------------------------- the triggers the CLI raises

def budget_minutes(root: Path, task: str) -> int:
    """The minutes of agent-alone time before the budget ask: the owner's last untagged `- Budget: <n> min` line of the
    answers file, else `BUDGET_MINUTES`."""
    try:
        text = waiting.answers_path(root, task).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return BUDGET_MINUTES
    found = _BUDGET.findall(text)
    return int(found[-1]) if found and int(found[-1]) > 0 else BUDGET_MINUTES


def _epoch(stamp: Any) -> float | None:
    try:
        return datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _asked_since(root: Path, task: str, named: str, since: float) -> bool:
    """Whether the answers file holds an item `Ask <named>: ...` (the owner's, or the run's own with its `Basis:`) and is
    newer than `since`: the trigger was asked after the change."""
    path = waiting.answers_path(root, task)
    try:
        text, mtime = path.read_text(encoding="utf-8", errors="replace"), path.stat().st_mtime
    except OSError:
        return False
    if mtime < since:
        return False
    for item in brief.items(brief.sections(text).get("asks", "")):
        tag = brief._TAG.match(item)
        body = item[tag.end():] if tag else item
        if re.match(rf"^[\s*_`:\-–—]*Ask\s+{re.escape(named)}\b", body, re.IGNORECASE):
            return True
    return False


def _area_of(pointer: str) -> tuple[str, str | None] | None:
    """The area a protected pointer belongs to (`AREA_POINTERS`) and, for a type role, the role."""
    for area, heads in AREA_POINTERS.items():
        if any(pointer.startswith(head) for head in heads):
            role = _ROLE.search(pointer)
            return area, role.group(1) if area == "type" and role else None
    return None


def detected(root: Path, task: str, plan: Any, env: Any = os.environ, now: float | None = None) -> dict[str, Any] | None:
    """The step `ask` while a trigger the CLI raises is pending, else None: `{"id": "ask", "why", "command": None,
    "triggers": [...]}` with every pending row batched into one question. See the module text for the three triggers."""
    from lapis_design import gate, integrity, slice_step

    if not isinstance(plan, dict):
        return None
    sealed = slice_step.sealed(root, task)
    rows = [r for r in integrity.changes(root, task) if r.get("kind") == "protected" and isinstance(r.get("pointer"), str)]
    pending: dict[str, list[str]] = {}
    state_values = (integrity.read_state(root, task) or {}).get("values") or {}
    # new-direction: the value now is not the sealed one, and no ask about it was answered since its change
    if sealed and isinstance(sealed.get("values"), dict):
        latest: dict[str, dict] = {}
        for row in rows:
            if row.get("after_slice") and any(row["pointer"].startswith(head) for head in DIRECTION_POINTERS):
                latest[row["pointer"]] = row
        for pointer, row in latest.items():
            if state_values.get(pointer) != sealed["values"].get(pointer):
                when = _epoch(row.get("at")) or 0.0
                if not _asked_since(root, task, "new-direction", when):
                    pending.setdefault("new-direction", []).append(pointer)
    # finding-vs-decision: a finding was open on an area the owner decided when it changed
    from lapis_design import gaps

    undecided = {(g["area"], g["id"].partition(":")[2] or None) for g in gaps.compute(root, task, env)}
    for row in rows:
        found = _area_of(row["pointer"])
        if not found or not row.get("related_open"):
            continue
        area, role = found
        if area == "type" and role:
            decided = ("type", role) not in undecided
        else:
            decided = not any(a == area for a, _ in undecided)
        if decided and not _asked_since(root, task, "finding-vs-decision", _epoch(row.get("at")) or 0.0):
            pending.setdefault("finding-vs-decision", []).append(f"{row['pointer']} (findings open: {', '.join(row['related_open'])})")
    # budget: agent-alone time after the seal, attended runs only
    if sealed and not gate.is_unattended(env):
        stamps = [_epoch(sealed.get("at"))] + [_epoch(s.get("answered")) for s in load(root, task)["sets"] if s.get("answered")]
        since = max((t for t in stamps if t is not None), default=None)
        minutes = budget_minutes(root, task)
        if since is not None and ((time.time() if now is None else now) - since) / 60 > minutes:
            pending["budget"] = [f"more than {minutes} minutes since the owner last answered or saw the slice"]
    if not pending:
        return None
    lines = [f"{named}: {'; '.join(items[:4])}" for named, items in pending.items()]
    why = ("A trigger the CLI raises is pending: " + " | ".join(lines) + ". Ask the owner one short question about it "
           "(`.lapis/questions/<task>.md`, first line `lapis-questions: ask`, a `Trigger:` line naming the first trigger, one "
           "question, a `Default:` line, at most 150 words; it batches every row above), or put the changed values back. "
           "Record the answer under `## Asks` as `- [declared] Ask <trigger>: <their decision>`, or, with nobody to ask, as "
           "`- [assumed] Ask <trigger>: <the question> — took <default>. Basis: <why>`, and run `lapis-design next` again. "
           "The owner sees every ask in the owner block.")
    return {"id": "ask", "why": why, "command": None, "triggers": list(pending)}
