"""Harness hooks, run as `lapis-design hook <name>` (install/OUTPUTS.md, Hooks).

exit-plan    Claude Code PermissionRequest on ExitPlanMode, inline in the lapis plugin's Claude Code
             manifest. Validates the plan's lapis-plan block before the plan leaves plan mode:
               - no lapis-plan block in the plan            -> no output, normal approval flow
               - block present, no blocking findings        -> no output, normal approval flow
               - block present with blocking findings       -> deny with the findings, so the model
                                                               fixes the plan before the user is asked
               - block present but cannot be checked        -> deny with the error
             It never approves on the user's behalf. Verify the decision JSON against the current
             Claude Code hooks documentation before shipping.
session-start  SessionStart in the lazuli plugin's hooks/hooks.json (Claude Code, Codex) and the
             session_start extension (pi, Oh-My-Pi). Prints the local font inventory summary as
             context (`lazuli local fonts --summary`, without scanning or measuring), or one line
             that says how to create the inventory. A failure prints nothing: the session must start.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable, TextIO


def _deny(message: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                   "decision": {"behavior": "deny", "message": message}}}


def _uncheckable(exc: Exception) -> dict:
    first_line = str(exc).splitlines()[0] if str(exc) else ""
    return _deny(f"lapis-plan block could not be checked: {type(exc).__name__}: {first_line}")


def _exit_plan_block(event: dict) -> str | None:
    from lapis_design import plan_check

    plan_md = (event.get("tool_input") or {}).get("plan") or ""
    return plan_check.extract_lapis_block(plan_md)


def exit_plan_decision(event: dict, project: Path, shared: Path) -> dict | None:
    try:
        block = _exit_plan_block(event)
        if block is None:
            return None
        return _checked_exit_plan_decision(block, project, shared)
    except Exception as exc:
        return _uncheckable(exc)


def _checked_exit_plan_decision(block: str, project: Path, shared: Path) -> dict | None:
    from lapis_design import plan_check

    rules = shared / "slop" / "rules.yaml"
    if not rules.exists():
        rules = shared / "slop" / "rules.example.yaml"
    lock = project / ".lapis" / "fonts.lock.json"
    parsed = plan_check.parse_plan(block)
    lazuli_db, _ = plan_check.default_lazuli_db(None)
    try:
        report = plan_check.run(None, rules, lock, shared / "plan" / "schema.yaml", project,
                                plan=parsed, plan_label="ExitPlanMode#lapis-plan", lazuli_db=lazuli_db)
    except plan_check.LazuliDBOpenError as exc:
        print(f"warning: {exc}; this run checks without font measurements", file=sys.stderr)
        report = plan_check.run(None, rules, lock, shared / "plan" / "schema.yaml", project,
                                plan=parsed, plan_label="ExitPlanMode#lapis-plan", lazuli_db=None)
    blocking = [f for f in report["findings"] if f["blocking"]]
    if not blocking:
        return None
    lines = [f"- {f['rule_id']}: {f['observed']}" + (f" (fix: {f['fix']})" if f.get("fix") else "")
             for f in blocking]
    return _deny("LapisLazuli plan_check found blocking issues in the lapis-plan block:\n" +
                 "\n".join(lines))


def exit_plan(stdin: TextIO, stdout: TextIO) -> int:
    try:
        event = json.load(stdin)
        block = _exit_plan_block(event)
        if block is None:
            return 0
        from lapis_design import shared_dir

        project = Path(os.environ.get("CLAUDE_PROJECT_DIR", event.get("cwd", ".")))
        # the full contracts packaged with the CLI, not the plugin's skill views (which lack the rules)
        out = _checked_exit_plan_decision(block, project, shared_dir())
    except Exception as exc:
        out = _uncheckable(exc)
    if out:
        print(json.dumps(out, ensure_ascii=False), file=stdout)
    return 0


def session_start(stdin: TextIO, stdout: TextIO) -> int:
    # stdin is left unread: the pi and Oh-My-Pi extension may start the command without an event
    try:
        from lazuli.local import session_summary

        text = session_summary()
    except Exception:
        return 0
    if text:
        print(text, file=stdout)
    return 0


HOOKS: dict[str, Callable[[TextIO, TextIO], int]] = {
    "exit-plan": exit_plan,
    "session-start": session_start,
}
