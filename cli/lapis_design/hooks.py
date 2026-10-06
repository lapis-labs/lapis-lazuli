"""Harness hooks, run as `lapis-design-hook --plugin-version VERSION <name>` (install/OUTPUTS.md, Hooks).

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
stop         Stop in the lapis plugin's hooks/hooks.json (Claude Code, Codex), and the session_stop (Oh-My-Pi)
             and agent_before_settle (pi) handlers of the lapis plugin's exit-gate extension. The event JSON
             (`cwd`, `session_id`) names a project; with a plan under it and `LAPIS_UNATTENDED=1`, the gate
             (gate.py) continues the agent with the step `lapis-design next` still asks for, up to three
             times in a row for one step and fifteen in a session. An unattended run with no plan owes one:
             its step is `plan`. A run waiting for its user's answers (`.lapis/questions/<task>.md`, see
             waiting.py) is let stop, two sets of questions before a plan and one after. Without that
             variable it prints a one-line `systemMessage` and never blocks. Output is Claude Code's and
             Codex's Stop JSON; the extensions translate it. With no plan and no unattended run, or on any
             failure of ours, it prints nothing.
pre-write    PreToolUse on the file-edit tools in the lapis plugin's hooks/hooks.json (Claude Code: Write, Edit,
             MultiEdit; Codex: apply_patch), and the tool_call handler of the lapis write-guard extension (Oh-My-Pi,
             pi). The event JSON (`cwd`, `tool_input`) names the files a write touches. With `LAPIS_UNATTENDED=1`,
             a create run whose brief, references, or plan is still owed has its writes of page source files
             refused (order.py), as `hookSpecificOutput.permissionDecision: deny` with the next step named;
             writes under `.lapis/` (except the next sentence), to other files, and outside the project pass. A
             person's session gets one `systemMessage` the first time and is never blocked. In every session, a
             write to `.lapis/requirements/`, `.lapis/state/`, `.lapis/changes/`, or `.lapis/owner/` (records only
             `lapis-design` writes) is refused the same way, with no cap: it stops the agent's tool, not a person.
             On any failure of ours it prints nothing.
"""
from __future__ import annotations

import json
import argparse
import hashlib
import os
import sys
from pathlib import Path
from typing import Callable, TextIO

from lapis_design import __version__


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


def stop(stdin: TextIO, stdout: TextIO) -> int:
    try:
        event = json.load(stdin)
    except ValueError:
        event = {}
    try:
        from lapis_design import gate

        out = gate.decide(event if isinstance(event, dict) else {})
    except Exception as exc:        # the gate never holds an agent in its turn because of a bug of ours
        print(f"lapis-design hook stop: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    if out:
        print(json.dumps(out, ensure_ascii=False), file=stdout)
    return 0


def pre_write(stdin: TextIO, stdout: TextIO) -> int:
    try:
        event = json.load(stdin)
    except ValueError:
        event = {}
    try:
        from lapis_design import order

        out = order.decide(event if isinstance(event, dict) else {})
    except Exception as exc:        # a bug of ours never keeps an agent from writing
        print(f"lapis-design hook pre-write: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    if out:
        print(json.dumps(out, ensure_ascii=False), file=stdout)
    return 0


HOOKS: dict[str, Callable[[TextIO, TextIO], int]] = {
    "exit-plan": exit_plan,
    "session-start": session_start,
    "stop": stop,
    "pre-write": pre_write,
}


class _HookParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # Exit 2 means block/continue to the harness, not "unsupported command".
        raise ValueError(message)


def _notice(message: str, plugin_version: str | None = None) -> int:
    try:
        event = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except (ValueError, OSError):
        event = {}
    if not isinstance(event, dict):
        event = {}
    # All hooks in a session share this atomic claim, including the two plugins.
    # Without a session id, report once per project and version pair instead.
    key = json.dumps([event.get("session_id"), plugin_version, __version__, message])
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    try:
        folder = Path(event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".") / ".lapis" / "hooks"
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / f"{digest}.notice").open("x", encoding="utf-8"):
            pass
    except FileExistsError:
        return 0
    except (OSError, TypeError, ValueError):
        # A read-only project can lose deduplication, never fail-open behavior.
        pass
    print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    """The hook-only entry point: unsupported interfaces never exit with 2."""
    ap = _HookParser(prog="lapis-design-hook", description="Run a harness hook; version skew fails open.")
    ap.add_argument("--plugin-version", help="the version embedded in the calling plugin")
    ap.add_argument("name", help="one of " + ", ".join(HOOKS))
    try:
        args = ap.parse_args(argv)
    except ValueError as exc:
        return _notice(f"LapisLazuli hook skipped: {exc}; update the CLI and plugins together.")
    if args.plugin_version and args.plugin_version != __version__:
        return _notice(
            f"LapisLazuli hooks skipped: plugin {args.plugin_version}, CLI {__version__}; "
            "update the CLI and plugins together.", args.plugin_version)
    if args.name not in HOOKS:
        return _notice(
            f"LapisLazuli hook skipped: CLI {__version__} does not support {args.name!r}; "
            "update the CLI and plugins together.", args.plugin_version)
    return HOOKS[args.name](sys.stdin, sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
