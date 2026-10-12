"""The rules a delegated task carries, and what the CLI can check of them (`shared/review/worker-rules.md`).

`rules()` is the text a delegation puts in front of a worker. `pre_bash` refuses a shell command that stops a process by
pattern (`pkill`, `killall`, a process finder piped or substituted into `kill`), as the pre-write hook's answer for a `Bash`
call. `scan` reads a transcript (JSON lines of tool calls, as Claude Code writes a subagent's) and finds the same commands
and the tool calls that touched a check's source (`lapis_design/lint`, `render`, `behavior_check`); `record` keeps what it
found in `.lapis/state/<task>.workers.json` (a folder only `lapis-design` writes), and `lines` is what the owner block
shows. `lapis-design worker check` runs a transcript through it; the `subagent-stop` hook does so for Claude Code's
subagents. A transcript the CLI is not given, or in a shape `scan` does not read, is not checked: the limits are named in
the shared file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from lapis_design import shared_dir

_START = r"(?:^|[;&|(`]|\$\()\s*(?:(?:sudo|command|exec|nohup|time)\s+|env\s+(?:\S+=\S+\s+)*)*"
_PATTERN_KILL = [
    re.compile(_START + r"(?:pkill|killall)\b"),                                     # the pattern killers themselves
    re.compile(r"\b(?:pgrep|pidof|lsof|ps)\b[^;&\n]*\|\s*(?:xargs\s+(?:-\S+\s+)*)?kill\b"),   # a finder piped into kill
    re.compile(r"\bkill\b[^;&|\n]*(?:\$\(|`)\s*(?:pgrep|pidof|lsof|ps)\b"),                  # kill $(finder ...)
]
CHECKER_SOURCE = re.compile(r"lapis_design/(?:lint|render|behavior_check)(?:/|\b)")
TASK = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
_BASH = {"bash", "shell", "local_shell", "exec_command"}


def rules() -> str:
    """The lines under **The rules** of `shared/review/worker-rules.md`, as a delegated task carries them."""
    text = (shared_dir() / "review" / "worker-rules.md").read_text(encoding="utf-8")
    block = text.split("## The rules", 1)[1].split("\n## ", 1)[0]
    return "\n".join(line for line in block.strip().splitlines() if line.startswith("- "))


def pattern_kill(command: object) -> str | None:
    """The part of the shell `command` that stops a process by pattern, or None."""
    if not isinstance(command, str):
        return None
    for found in _PATTERN_KILL:
        if match := found.search(command):
            return " ".join(command[match.start():].split())[:200]
    return None


def pre_bash(event: Mapping[str, Any]) -> dict | None:
    """The PreToolUse refusal for a `Bash` call that stops a process by pattern in a project that has a plan, else None."""
    from lapis_design import gate

    tool_input = event.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if (found := pattern_kill(command)) is None or gate.find_project(Path(event.get("cwd") or ".")) is None:
        return None
    reason = ("LapisLazuli refuses this command: it stops a process by pattern (" + found + "). Other work shares the machine, "
              "and a pattern reaches it. Stop only a process id a command recorded, such as the one in "
              ".lapis/logs/<task>.<step>.pid (`kill <pid>`); if you have none, leave the process and say so.")
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def _calls(value: Any) -> Iterator[tuple[str, Any]]:
    """Every tool call in a parsed transcript line: `(tool name, its input)`, whatever depth it sits at."""
    if isinstance(value, dict):
        name = value.get("name") if isinstance(value.get("name"), str) else value.get("toolName")
        args = next((value[k] for k in ("input", "arguments", "args") if k in value), None)
        if isinstance(name, str) and isinstance(args, (dict, str)) and (value.get("type") in (None, "tool_use", "toolCall")):
            yield name, args
        for item in value.values():
            yield from _calls(item)
    elif isinstance(value, list):
        for item in value:
            yield from _calls(item)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def scan(path: Path) -> list[dict[str, str]]:
    """The findings in the transcript at `path` (JSON lines): `{"kind": "pattern-kill" | "checker-source", "tool",
    "evidence"}` for each tool call that stopped a process by pattern or touched a check's source. Unreadable lines and
    calls in a shape this does not know are skipped: that is a limit, not a pass."""
    found: list[dict[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return found
    for line in lines:
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        for name, args in _calls(parsed):
            if name.lower() in _BASH or (isinstance(args, dict) and isinstance(args.get("command"), str)):
                command = args.get("command") if isinstance(args, dict) else args
                if (hit := pattern_kill(command)) is not None:
                    found.append({"kind": "pattern-kill", "tool": name, "evidence": hit})
            for text in _strings(args):
                if (match := CHECKER_SOURCE.search(text)):
                    found.append({"kind": "checker-source", "tool": name, "evidence": text[max(0, match.start() - 40):][:200]})
                    break
    return found


def state_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "state" / f"{task}.workers.json"


def load(root: Path, task: str) -> dict:
    try:
        found = json.loads(state_path(root, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        found = None
    items = found.get("findings") if isinstance(found, dict) else None
    return {"version": 0, "task": task, "findings": [f for f in items or () if isinstance(f, dict)]}


def record(root: Path, task: str, agent: str, transcript: str, found: list[dict[str, str]]) -> list[dict]:
    """Add `found` of `agent`'s `transcript` to `.lapis/state/<task>.workers.json` (a finding already there is not added
    twice); returns the findings that were new."""
    log = load(root, task)
    have = {(f.get("transcript"), f.get("kind"), f.get("evidence")) for f in log["findings"]}
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new = [{"at": at, "agent": agent, "transcript": transcript, **item} for item in found
           if (transcript, item["kind"], item["evidence"]) not in have]
    if new:
        log["findings"] += new
        path = state_path(root, task)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return new


def lines(root: Path, task: str) -> list[str]:
    """What the owner block says of delegated work that broke a rule: one line per kind and agent, none when nothing was found."""
    out: dict[tuple[str, str], int] = {}
    for item in load(root, task)["findings"]:
        key = (str(item.get("agent") or "a delegated worker"), str(item.get("kind")))
        out[key] = out.get(key, 0) + 1
    said = {"pattern-kill": "stopped a process by pattern (`pkill`, `killall`, or a kill from a process finder)",
            "checker-source": "opened or listed the source of a check (`lapis_design/lint`, `render`, or `behavior_check`)"}
    return [f"- delegated work: {agent} {said.get(kind, kind)}, {count} time{'s' if count != 1 else ''}; "
            f"`.lapis/state/{task}.workers.json` has the commands" for (agent, kind), count in sorted(out.items())]


def subagent_stop(event: Mapping[str, Any], env: Mapping[str, str] = os.environ) -> dict | None:
    """The `SubagentStop` answer: reads the subagent's own transcript (`agent_transcript_path`), records what broke a rule,
    and says so in one line. Never blocks; None when there is nothing to say or no project to say it in."""
    from lapis_design import gate, next_step

    name = event.get("agent_transcript_path")
    project = gate.find_project(Path(event.get("cwd") or "."), env)
    if not isinstance(name, str) or project is None:
        return None
    task = next_step.resolve_task(project, env.get("LAPIS_TASK")) or gate.folder_task(project)
    transcript = Path(name).expanduser()
    if not TASK.fullmatch(task) or not (found := scan(transcript)):
        return None
    new = record(project, task, str(event.get("agent_type") or event.get("agent_id") or "a subagent"), transcript.name, found)
    if not new:
        return None
    return {"systemMessage": f"LapisLazuli: a subagent broke a delegated-work rule ({len(new)} finding"
            f"{'s' if len(new) != 1 else ''}; the owner block lists it): see .lapis/state/{task}.workers.json"}


def main(argv: list[str] | None = None, prog: str = "lapis-design worker check") -> int:
    ap = argparse.ArgumentParser(prog=prog, allow_abbrev=False,
                                 description="Read a delegated agent's transcript for the rules delegated work carries.")
    ap.add_argument("--task", required=True)
    ap.add_argument("--transcript", type=Path, required=True, help="the agent's transcript (JSON lines of tool calls)")
    ap.add_argument("--agent", default="a delegated worker", help="who made it, as the owner block names it")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    if not TASK.fullmatch(args.task):
        ap.error("--task must be a plan task id (lowercase letters, digits, and hyphens)")
    if not args.transcript.is_file():
        print(f"worker check: {args.transcript} is not a file", file=sys.stderr)
        return 2
    found = scan(args.transcript)
    new = record(args.root.resolve(), args.task, args.agent, args.transcript.name, found) if found else []
    for item in found:
        print(f"worker check: {item['kind']}: {item['evidence']}", file=sys.stderr)
    print(f"worker check: {len(found)} finding{'s' if len(found) != 1 else ''} in {args.transcript.name}"
          f" ({len(new)} new, recorded in {state_path(Path('.'), args.task).as_posix()})" if found
          else f"worker check: nothing in {args.transcript.name} stops a process by pattern or touches check source "
               "(only what the scanner reads: see shared/review/worker-rules.md)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
