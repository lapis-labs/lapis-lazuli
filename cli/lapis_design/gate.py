"""The exit gate: what `lapis-design hook stop` does when an agent is about to stop.

Every harness that has a stop event asks this module, so the rule is written once. The gate reads the
same state `lapis-design next` reads. When a step remains and `LAPIS_UNATTENDED=1`, it continues the
agent with that step; otherwise it says in one line that the procedure is not done, and never blocks:
a person at the keyboard decides when to stop.

Limits, kept in `.lapis/gate/<task>.json` because a hook is a new process each time: three continues in
a row for the same step, fifteen in a session. At either limit the gate lets the agent stop and records
the step that was left (`capped`), so the run ends and the reader can see where it stopped.

A bug of ours, a state that cannot be read, or a project without a plan never stops an agent: the gate
answers nothing then. It checks nothing, fixes nothing, and approves nothing for the user.

Stdlib only until a plan exists: this runs at the end of every turn in every session.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ENV = "LAPIS_UNATTENDED"
CAP_STEP = 3
CAP_TOTAL = 15


def is_unattended(env: Mapping[str, str] = os.environ) -> bool:
    return env.get(ENV) == "1"


def find_project(start: Path, env: Mapping[str, str] = os.environ) -> Path | None:
    """The folder whose `.lapis/plans` holds a plan: `$CLAUDE_PROJECT_DIR`, else `start` or the nearest
    folder above it. With `$LAPIS_TASK` set and no plan yet, `start` itself, since the task is named."""
    candidates = [Path(env["CLAUDE_PROJECT_DIR"])] if env.get("CLAUDE_PROJECT_DIR") else []
    start = start.resolve()
    candidates += [start, *start.parents]
    for folder in candidates:
        try:
            if next((folder / ".lapis" / "plans").glob("*.yaml"), None):
                return folder
        except OSError:
            continue
    return start if env.get("LAPIS_TASK") else None


def _path(project: Path, task: str) -> Path:
    return project / ".lapis" / "gate" / f"{task}.json"


def _load(project: Path, task: str) -> dict[str, Any]:
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


def continuation(result: dict[str, Any], first: bool) -> str:
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
    if first or step["id"].startswith("plan"):
        parts.append("No person is present to approve the plan: record `approval: {state: assumed, reason: ...}` in "
                     "it and continue; never write `approved`, which only the user's own approval earns.")
    return "\n".join(parts)


def notice(result: dict[str, Any]) -> str:
    step, task = result["step"], result["task"]
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
    if not task or not next_step.attempts.TASK.fullmatch(task):
        return None
    try:
        result = next_step.evaluate(project, task)
    except Exception as exc:        # a bug or an unreadable file here must not hold an agent in its turn
        print(f"lapis-design gate: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    state = _load(project, task)
    if session and state.get("session") not in (None, session):
        state = {}                                              # another session starts its own count
    step = result["step"]
    if step is None:
        if state.get("step") or state.get("capped"):
            _save(project, task, {"session": session or state.get("session"), "step": None, "same": 0,
                                  "total": state.get("total", 0)})
        return None
    if not unattended:
        return {"systemMessage": notice(result)}
    same = state.get("same", 0) if state.get("step") == step["id"] else 0
    total = state.get("total", 0)
    if same >= CAP_STEP or total >= CAP_TOTAL:
        capped = {"reason": "same-step" if same >= CAP_STEP else "total", "step": step["id"],
                  "command": step["command"], "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        _save(project, task, {"session": session or state.get("session"), "step": step["id"], "same": same,
                              "total": total, "capped": capped})
        return None
    _save(project, task, {"session": session or state.get("session"), "step": step["id"], "same": same + 1,
                          "total": total + 1})
    return {"decision": "block", "reason": continuation(result, first=total == 0)}


def decide(event: Mapping[str, Any], env: Mapping[str, str] = os.environ) -> dict[str, Any] | None:
    """`stop_output` for a stop hook's event JSON (`cwd`, `session_id`), or None when no plan is in reach."""
    project = find_project(Path(event.get("cwd") or "."), env)
    if project is None:
        return None
    return stop_output(project, str(event.get("session_id") or ""), unattended=is_unattended(env),
                       task=env.get("LAPIS_TASK"))
