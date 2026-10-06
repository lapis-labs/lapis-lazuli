"""Antigravity's hook JSON, run as `lapis-design-hook --plugin-version VERSION --host antigravity <name>`.

Antigravity (`agy`) hands a hook its own event shape and reads a strict answer: the plugin's `hooks.json` command gets
`conversationId`, `workspacePaths`, and (PreToolUse) `toolCall.{name,args}` on stdin, and an answer with a field
Antigravity does not know, a `{}`, or text that is not JSON stops the PreToolUse tool call it was for, as does a command
that exits non-zero. A hook's working directory is the plugin's folder, not the project. This module turns that event into
the one the hook bodies in hooks.py read (`cwd`, `session_id`, `tool_name`, `tool_input`), runs the body, and turns what it
printed into the answer Antigravity reads:

pre-write      PreToolUse on the file-edit tools: `write_to_file`, `replace_file_content`, and
               `multi_replace_file_content` (`toolCall.args.TargetFile` is the file) and `notebook_edit`
               (`NotebookPath`). A refusal is `{"decision": "deny", "reason": ...}`; every other
               outcome prints nothing, which Antigravity reads as no opinion. It never prints `allow`, which would
               also skip the permission prompt for a path outside the workspace.
stop           Stop. A continuation is `{"decision": "continue", "reason": ...}`, asked only when the agent chose to
               stop (`terminationReason` NO_TOOL_CALL; a cancel, an error, or a limit is the end of the run), no
               background task is still running (`fullyIdle`), and the conversation is the person's own: Stop also
               fires when a subagent ends, with an event of the same shape, and a subagent's transcript opens with a
               system message from its parent where the person's conversation opens with their message (checked
               2026-10-06). Continuing a subagent, the critic included, with the procedure's next step would derail
               it, so a transcript that cannot be read is answered with nothing too.

There is no session-start hook: Antigravity has no such event, and the one place that could carry a summary, PreInvocation's
`injectSteps` `ephemeralMessage`, reaches the model for a few steps only (checked 2026-10-06: gone after three tool calls),
so the lazuli skill's by-hand command stands in for it.

Antigravity has no way to show a hook's message to the person: the notice a body prints as `systemMessage` (a person's
session, version skew, an unsupported hook) goes to stderr, which Antigravity writes to its CLI log. Stdlib only.
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

# the file-edit tools of agy 1.2.17 and the argument that names the file; `sed_file` is in its tool list but a custom agent
# that names it fails with "not found in registry" (2026-10-06), so it has no entry
WRITE_TOOLS = {"write_to_file": "TargetFile", "replace_file_content": "TargetFile",
               "multi_replace_file_content": "TargetFile", "notebook_edit": "NotebookPath"}
# Stop's `terminationReason` when the agent chose to stop. Antigravity's documentation names `model_stop`; agy 1.2.17
# sends `NO_TOOL_CALL` (checked 2026-10-06). Any other reason ends the run and is not continued.
CHOSEN_STOPS = frozenset({"NO_TOOL_CALL", "model_stop"})
HOOKS = ("pre-write", "stop")
Body = Callable[[TextIO, TextIO], int]


def _workspaces(raw: Mapping[str, Any]) -> list[str]:
    paths = raw.get("workspacePaths")
    return [p for p in paths if isinstance(p, str) and p] if isinstance(paths, list) else []


def _project(raw: Mapping[str, Any], target: str | None = None) -> str | None:
    """The workspace the event belongs to: the one that holds `target`, else the first that has a `.lapis` folder, else
    the first. None when the event names none, since a hook's own working directory is the plugin's folder."""
    paths = _workspaces(raw)
    if target:
        real = os.path.realpath(target)
        for path in paths:
            root = os.path.realpath(path)
            if real == root or real.startswith(root.rstrip(os.sep) + os.sep):
                return path
    return next((p for p in paths if (Path(p) / ".lapis").is_dir()), paths[0] if paths else None)


def _session(raw: Mapping[str, Any]) -> str:
    return str(raw.get("conversationId") or "")


def pre_write_event(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    call = raw.get("toolCall")
    if not isinstance(call, Mapping) or call.get("name") not in WRITE_TOOLS:
        return None
    args = call.get("args")
    target = args.get(WRITE_TOOLS[call["name"]]) if isinstance(args, Mapping) else None
    if not isinstance(target, str) or not target:
        return None
    cwd = _project(raw, target)
    if cwd is None:
        return None
    return {"hook_event_name": "PreToolUse", "cwd": cwd, "session_id": _session(raw), "tool_name": call["name"],
            "tool_input": {"file_path": target}}


def _person_started(raw: Mapping[str, Any]) -> bool:
    """Whether the conversation's first step is the person's own message (`source` USER_EXPLICIT); a subagent's is a
    system message from its parent."""
    try:
        with open(raw["transcriptPath"], encoding="utf-8") as f:
            first = json.loads(f.readline())
    except (KeyError, TypeError, OSError, ValueError):
        return False
    return isinstance(first, dict) and first.get("source") == "USER_EXPLICIT"


def stop_event(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    if raw.get("terminationReason") not in CHOSEN_STOPS or raw.get("fullyIdle") is False or not _person_started(raw):
        return None
    cwd = _project(raw)
    return None if cwd is None else {"hook_event_name": "Stop", "cwd": cwd, "session_id": _session(raw)}


EVENTS: dict[str, Callable[[Mapping[str, Any]], dict[str, Any] | None]] = {"pre-write": pre_write_event, "stop": stop_event}


def _answer(name: str, printed: str) -> tuple[dict[str, Any] | None, str | None]:
    """(what Antigravity reads, the notice for stderr) from what a hook body printed."""
    try:
        out = json.loads(printed) if printed.strip() else {}
    except ValueError:
        return None, None
    if not isinstance(out, dict):
        return None, None
    notice = out.get("systemMessage") if isinstance(out.get("systemMessage"), str) else None
    if name == "pre-write":
        decision = out.get("hookSpecificOutput")
        if isinstance(decision, dict) and decision.get("permissionDecision") == "deny":
            return {"decision": "deny", "reason": str(decision.get("permissionDecisionReason") or "")}, notice
    elif out.get("decision") == "block":
        return {"decision": "continue", "reason": str(out.get("reason") or "")}, notice
    return None, notice


def run(name: str, stdin: TextIO, stdout: TextIO, bodies: Mapping[str, Body]) -> int:
    """Run hook `name` (one of HOOKS) on Antigravity's event; `bodies` is hooks.HOOKS. Never fails: a hook command that
    exits non-zero stops Antigravity's tool call, so every failure of ours prints nothing."""
    try:
        raw = json.load(stdin)
        event = EVENTS[name](raw) if isinstance(raw, dict) else None
        if event is None:
            return 0
        printed = io.StringIO()
        bodies[name](io.StringIO(json.dumps(event)), printed)
        answer, notice = _answer(name, printed.getvalue())
        if notice:
            print(notice, file=sys.stderr)
        if answer:
            print(json.dumps(answer, ensure_ascii=False), file=stdout)
    except Exception as exc:        # a bug of ours never keeps an agent from working
        print(f"lapis-design hook {name} (antigravity): {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0
