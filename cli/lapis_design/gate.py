"""The exit gate: what `lapis-design hook stop` does when an agent is about to stop.

Every harness that has a stop event asks this module, so the rule is written once. The gate reads the
same state `lapis-design next` reads. When a step remains and `LAPIS_UNATTENDED=1`, it continues the
agent with that step; otherwise it says in one line that the procedure is not done, and never blocks:
a person at the keyboard decides when to stop.

Limits, kept in `.lapis/gate/<task>.json` because a hook is a new process each time: three continues in
a row for the same step, fifteen in a session. At either limit the gate lets the agent stop and records
the step that was left (`capped`), so the run ends and the reader can see where it stopped.

One stop passes without counting a continue: the run asked its user something. `next` then says
`waiting-for-user` (waiting.py: questions written and not yet answered) and the gate answers nothing, so
an operator can relay the answers. It counts each set of questions it let pass under `waits` in the same
file and lets at most two pass before a plan exists and one after; past that it continues the agent as
before.

A bug of ours or a state that cannot be read never stops an agent: the gate answers nothing then. A folder
with no plan is no project, with one exception: an unattended run (`LAPIS_UNATTENDED=1`, which only an
operator sets, for a design run) owes a plan, so its step is `brief` until a brief record exists and then
`plan`, under the same limits. The gate checks nothing, fixes nothing, and approves nothing for the user.

Stdlib only until a plan is in reach or the run is unattended: this runs at the end of every turn in
every session.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from lapis_design import waiting

ENV = "LAPIS_UNATTENDED"
CAP_STEP = 3
CAP_TOTAL = 15


def is_unattended(env: Mapping[str, str] = os.environ) -> bool:
    return env.get(ENV) == "1"


def folder_task(project: Path) -> str:
    """A plan task id from the project folder's name (lowercase letters, digits, hyphens; two characters
    at least), for a run that has written no plan and named no task."""
    slug = re.sub(r"[^a-z0-9]+", "-", project.name.lower()).strip("-")[:64].strip("-")
    return slug if len(slug) >= 2 else "design"


def find_project(start: Path, env: Mapping[str, str] = os.environ) -> Path | None:
    """The folder whose `.lapis/plans` holds a plan: `$CLAUDE_PROJECT_DIR`, else `start` or the nearest
    folder above it. With no plan yet, `start` itself when the task is named (`$LAPIS_TASK`) or the run is
    unattended, because only an operator sets `LAPIS_UNATTENDED` for a design run, and such a run owes a
    plan even if the agent wrote none; otherwise no project, and the gate says nothing."""
    candidates = [Path(env["CLAUDE_PROJECT_DIR"])] if env.get("CLAUDE_PROJECT_DIR") else []
    start = start.resolve()
    candidates += [start, *start.parents]
    for folder in candidates:
        try:
            if next((folder / ".lapis" / "plans").glob("*.yaml"), None):
                return folder
        except OSError:
            continue
    if not (env.get("LAPIS_TASK") or is_unattended(env)):
        return None
    return Path(env["CLAUDE_PROJECT_DIR"]).resolve() if env.get("CLAUDE_PROJECT_DIR") else start


def _path(project: Path, task: str) -> Path:
    return project / ".lapis" / "gate" / f"{task}.json"


def load(project: Path, task: str) -> dict[str, Any]:
    """The gate's recorded state for `task`: `{}` when there is none or it cannot be read."""
    try:
        state = json.loads(_path(project, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _save(project: Path, task: str, state: dict[str, Any]) -> None:
    target = _path(project, task)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"version": 0, "task": task, **state}, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    except OSError as exc:
        print(f"lapis-design gate: {target} cannot be written: {exc}", file=sys.stderr)


def continuation(result: dict[str, Any], first: bool, relayed: bool = False) -> str:
    """What the agent is told when the gate continues it: the step, and the rules that make it count."""
    step, task = result["step"], result["task"]
    parts = [f"LapisLazuli: the procedure for task {task} is not done. Next step: {step['id']}."]
    if step["command"]:
        parts.append(f"Run: {step['command']}")
    if step.get("schema"):
        parts.append(f"Schema: {step['schema']}")
    parts.append(step["why"])
    parts.append(f"A missing or invalid input and a plan blocker are not done: create or fix it, then run "
                 f"`lapis-design next --task {task}` again until it says done. Only a failure of the environment, "
                 "such as a browser that cannot start, counts, and the check records it itself. Never write or edit "
                 "a report, a lock, or a failure record by hand.")
    if relayed:
        if step["id"].startswith("plan"):
            parts.append("A person's answers are recorded: write `approval: {state: approved}` only if they approve "
                         "this plan, otherwise `assumed` with a reason.")
    elif step["id"] != "brief" and (first or step["id"].startswith("plan")):     # a brief comes before any plan to approve
        parts.append("No person is present to approve the plan: record `approval: {state: assumed, reason: ...}` in "
                     "it and continue; never write `approved`, which only the user's own approval earns.")
    return "\n".join(parts)


def notice(result: dict[str, Any]) -> str:
    step, task = result["step"], result["task"]
    if result["state"] == waiting.STEP:
        return f"LapisLazuli: task {task} waits for the user's answers to {result['waiting']['questions']}."
    return (f"LapisLazuli: the procedure for task {task} is not done; next step {step['id']} "
            f"(`lapis-design next --task {task}`).")


def stop_output(project: Path, session: str = "", *, unattended: bool = True,
                task: str | None = None) -> dict[str, Any] | None:
    """The JSON a stop hook prints, or None to let the agent stop.

    `{"decision": "block", "reason": ...}` continues an unattended agent (Claude Code's and Codex's
    Stop output, which the pi and Oh-My-Pi extensions translate); `{"systemMessage": ...}` is the
    one-line notice for a person; None says nothing."""
    from lapis_design import next_step

    task = next_step.resolve_task(project, task)
    if not task and unattended:
        task = folder_task(project)          # an unattended run with no plan still owes one: the step is `plan`
    if not task or not next_step.attempts.TASK.fullmatch(task):
        return None
    try:
        result = next_step.evaluate(project, task)
    except Exception as exc:        # a bug or an unreadable file here must not hold an agent in its turn
        print(f"lapis-design gate: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    stored = load(project, task)
    waits = stored.get("waits") if isinstance(stored.get("waits"), dict) else {}
    state = stored
    if session and state.get("session") not in (None, session):
        state = {}                                              # another session starts its own count

    def save(**fields: Any) -> None:                             # the waits belong to the task, not the session
        _save(project, task, {"session": session or state.get("session"), **fields,
                              **({"waits": waits} if waits else {})})

    step = result["step"]
    if step is None:
        if state.get("step") or state.get("capped"):
            save(step=None, same=0, total=state.get("total", 0))
        return None
    if not unattended:
        return {"systemMessage": notice(result)}
    if result["state"] == waiting.STEP:                         # the run asked its user: no continue, none counted
        found = result["waiting"]
        if not found["counted"]:
            waits = waiting.counted(waits, found)
            save(step=state.get("step"), same=state.get("same", 0), total=state.get("total", 0),
                 **({"capped": state["capped"]} if state.get("capped") else {}))
        return None
    same = state.get("same", 0) if state.get("step") == step["id"] else 0
    total = state.get("total", 0)
    if same >= CAP_STEP or total >= CAP_TOTAL:
        capped = {"reason": "same-step" if same >= CAP_STEP else "total", "step": step["id"],
                  "command": step["command"], "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        save(step=step["id"], same=same, total=total, capped=capped)
        return None
    save(step=step["id"], same=same + 1, total=total + 1)
    return {"decision": "block", "reason": continuation(result, first=total == 0, relayed=bool(waits))}


def decide(event: Mapping[str, Any], env: Mapping[str, str] = os.environ) -> dict[str, Any] | None:
    """`stop_output` for a stop hook's event JSON (`cwd`, `session_id`), or None when no plan is in reach."""
    project = find_project(Path(event.get("cwd") or "."), env)
    if project is None:
        return None
    return stop_output(project, str(event.get("session_id") or ""), unattended=is_unattended(env),
                       task=env.get("LAPIS_TASK"))
