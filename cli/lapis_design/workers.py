"""The rules a delegated task carries, and what the CLI can check of them (`shared/review/worker-rules.md`).

`rules()` is the text a delegation puts in front of a worker. `pre_bash` refuses a shell command that stops a process by
pattern (`pkill`, `killall`, a process finder piped or substituted into `kill`), as the pre-write hook's answer for a `Bash`
call. `scan` reads a transcript (JSON lines of tool calls, as Claude Code or Antigravity writes them) and finds the same
commands and the tool calls that read the source of `lapis-design` (any module of `lapis_design`): a path under it, a
listing of its package folder, an import of it, or `inspect.getsource` of it, each with the module and how; `record` keeps
what it found in `.lapis/state/<task>.workers.json` (a folder only `lapis-design` writes), and `lines` is what the owner
block shows. `lapis-design worker check` runs a transcript through it; the `subagent-stop` hook does so for Claude Code's
subagents, and Antigravity's `stop` hook does so for its sessions and subagents (`scan_session`, which also records that a
transcript could not be read). A transcript the CLI is not given, or in a shape `scan` does not read, is not checked: the
limits are named in the shared file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from lapis_design import shared_dir, telemetry
from lapis_design.summary import clip

_START = r"(?:^|[;&|(`\n]|\$\()\s*(?:(?:sudo|command|exec|nohup|time)\s+|env\s+(?:\S+=\S+\s+)*)*"
_PATTERN_KILL = [
    re.compile(_START + r"(?:pkill|killall)\b"),                                     # the pattern killers themselves
    re.compile(r"\b(?:pgrep|pidof|lsof|ps)\b[^;&\n]*\|\s*(?:xargs\s+(?:-\S+\s+)*)?kill\b"),   # a finder piped into kill
    re.compile(r"\bkill\b[^;&|\n]*(?:\$\(|`)\s*(?:pgrep|pidof|lsof|ps)\b"),                  # kill $(finder ...)
]
PACKAGE = "lapis_design"
# What reads the source of `lapis-design`, as a pattern each; the CLI itself (`lapis-design ...`, `lazuli ...`, `--help`, the
# skill guides, `python -m lapis_design...`) is not in them. Each yields the module it names (the package when none).
_ENTRY = re.compile(r"-m\s+lapis_design[\w.]*")                                    # blanked out: running the CLI is not reading it
_FROM = re.compile(r"\bfrom\s+lapis_design((?:\.\w+)*)\s+import\s+([^\n;]*)")        # from lapis_design[.m] import a, b
_IMPORT = re.compile(r"\bimport\s+(?:[\w.]+(?:\s+as\s+\w+)?\s*,\s*)*lapis_design((?:\.\w+)*)")   # import lapis_design[.m]
_ATTR = re.compile(r"(?<![\w./-])lapis_design\.(\w+)")                                # lapis_design.m used in code
_LOAD = re.compile(r"(?:import_module|__import__|find_spec)\(\s*[\"']lapis_design(?:\.(\w+))?")
_PATH = re.compile(r"(?<![\w.-])lapis_design/(\w*)")                                   # .../lapis_design/m.py, .../lapis_design/
_DIR = re.compile(r"/lapis_design(?![\w./-])")                                         # the package folder, no trailing slash
_SOURCE = re.compile(r"\binspect\.(?:getsource\w*|getfile|getmodule)\b|\bgetsource\w*\(|\.__file__\b")
TASK = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
_BASH = {"bash", "shell", "local_shell", "exec_command", "run_command"}
_COMMAND_KEYS = ("command", "CommandLine")        # Claude Code and Codex; Antigravity's `run_command`
_PROSE = {"toolAction", "toolSummary"}            # Antigravity's own one-line description of a call, not the call
SHOWN = 5                    # findings `worker check` prints one by one; the count and the file hold every one


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
        for key, item in value.items():
            if key not in _PROSE:
                yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _command(name: str, args: Any) -> str | None:
    """The shell command of a tool call: the argument of a shell tool, or the command field of any call."""
    if isinstance(args, str):
        return args if name.lower() in _BASH else None
    return next((args[key] for key in _COMMAND_KEYS if isinstance(args.get(key), str)), None)


def source_reads(text: str) -> list[dict[str, Any]]:
    """What in `text` reads the source of `lapis-design`, as `{"at", "module", "how"}` by position, once per module and way.
    `how` is `path` (a path under `lapis_design/` naming a module), `package-dir` (the package folder itself), `import` (an
    import of it, or `lapis_design.<module>` used in code), or `getsource` (the same call also reads source or a file path
    off the module: `inspect.getsource`, `getfile`, `__file__`). `module` is the module named, or `lapis_design` for the
    package. `lapis-design ...`, `lazuli ...`, `--help`, and `python -m lapis_design...` read nothing."""
    text = _ENTRY.sub(lambda match: " " * len(match.group()), text)
    code = "getsource" if _SOURCE.search(text) else "import"
    hits: list[tuple[int, str, str]] = []
    for match in _FROM.finditer(text):
        sub = match.group(1).split(".")[1] if match.group(1) else None
        if sub:
            hits.append((match.start(), sub, code))
            continue
        names = [m.group() for part in match.group(2).split(",") if (m := re.match(r"[A-Za-z_]\w*", part.strip(" ()\\\"'")))]
        hits += [(match.start(), PACKAGE if name.startswith("__") else name, code) for name in names or [PACKAGE]]
    for found in (_IMPORT, _ATTR, _LOAD):
        for match in found.finditer(text):
            sub = (match.group(1).split(".")[1] if found is _IMPORT and match.group(1) else
                   None if found is _IMPORT else match.group(1))
            hits.append((match.start(), PACKAGE if not sub or sub.startswith("__") else sub, code))
    for match in _PATH.finditer(text):
        hits.append((match.start(), match.group(1) or PACKAGE, "path" if match.group(1) else "package-dir"))
    hits += [(match.start(), PACKAGE, "package-dir") for match in _DIR.finditer(text)]
    seen: set[tuple[str, str]] = set()
    out = []
    for at, module, how in sorted(hits):
        if (module, how) not in seen:
            seen.add((module, how))
            out.append({"at": at, "module": module, "how": how})
    return out


def scan_rows(rows: Iterable[Any]) -> list[dict[str, str]]:
    """The findings in parsed transcript rows: `{"kind": "pattern-kill" | "checker-source", "tool", "evidence"}` for each
    tool call that stopped a process by pattern, and `{"kind": "checker-source", "tool", "module", "how", "evidence"}` for each
    module of `lapis_design` and way a tool call read its source (`source_reads`). Calls in a shape this does not know are
    skipped: that is a limit, not a pass."""
    found: list[dict[str, str]] = []
    for parsed in rows:
        for name, args in _calls(parsed):
            if (hit := pattern_kill(_command(name, args))) is not None:
                found.append({"kind": "pattern-kill", "tool": name, "evidence": hit})
            for text in _strings(args):
                for read in source_reads(text):
                    found.append({"kind": "checker-source", "tool": name, "module": read["module"], "how": read["how"],
                                  "evidence": text[max(0, read["at"] - 40):][:200]})
    return found


def rows(path: Path) -> list[Any]:
    """The JSON lines of the transcript at `path` that parse; raises OSError when the file cannot be read."""
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def scan(path: Path) -> list[dict[str, str]]:
    """The findings in the transcript at `path` (JSON lines; see `scan_rows`). An unreadable file or line is skipped: that is
    a limit, not a pass."""
    try:
        return scan_rows(rows(path))
    except OSError:
        return []


def state_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "state" / f"{task}.workers.json"


def load(root: Path, task: str) -> dict:
    try:
        found = json.loads(state_path(root, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        found = None
    found = found if isinstance(found, dict) else {}
    return {"version": 0, "task": task,
            **{key: [f for f in found.get(key) or () if isinstance(f, dict)] for key in ("findings", "limits")}}


def _save(root: Path, task: str, log: dict) -> None:
    path = state_path(root, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not log["limits"]:
        del log["limits"]
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(root: Path, task: str, agent: str, transcript: str, found: list[dict[str, str]]) -> list[dict]:
    """Add `found` of `agent`'s `transcript` to `.lapis/state/<task>.workers.json` (a finding already there is not added
    twice); returns the findings that were new."""
    log = load(root, task)
    key = lambda f: (f.get("transcript"), f.get("kind"), f.get("module"), f.get("how"), f.get("evidence"))  # noqa: E731
    have = {key(f) for f in log["findings"]}
    at = _now()
    new = [{"at": at, "agent": agent, "transcript": transcript, **item} for item in found
           if key({"transcript": transcript, **item}) not in have]
    if new:
        log["findings"] += new
        _save(root, task, log)
    return new


def record_limit(root: Path, task: str, agent: str, transcript: str, reason: str) -> bool:
    """Note in `.lapis/state/<task>.workers.json` that `agent`'s `transcript` was not checked, and why (once per reason);
    whether it was new."""
    log = load(root, task)
    if any((f.get("transcript"), f.get("reason")) == (transcript, reason) for f in log["limits"]):
        return False
    log["limits"].append({"at": _now(), "agent": agent, "transcript": transcript, "reason": reason})
    _save(root, task, log)
    return True


_SAID = {"pattern-kill": "stopped a process by pattern (`pkill`, `killall`, or a kill from a process finder)",
         "checker-source": "read the source of `lapis-design` (a path under `lapis_design/`, a listing of it, an import of "
                           "it, or `inspect.getsource`)"}
SHOWN_MODULES = 6


def lines(root: Path, task: str) -> list[str]:
    """What the owner block says of agents that broke a worker rule or whose transcript could not be checked: one line per
    kind and agent (the modules and ways of a source read are named), none when nothing was found."""
    log = load(root, task)
    out: dict[tuple[str, str], list[dict]] = {}
    for item in log["findings"]:
        out.setdefault((str(item.get("agent") or "a delegated worker"), str(item.get("kind"))), []).append(item)
    got = []
    for (agent, kind), items in sorted(out.items()):
        detail = ""
        if kind == "checker-source":
            modules = Counter(str(i["module"]) for i in items if i.get("module"))
            ways = Counter(str(i["how"]) for i in items if i.get("how"))
            if modules:
                shown = ", ".join(sorted(modules)[:SHOWN_MODULES]) + (", …" if len(modules) > SHOWN_MODULES else "")
                detail = f" (module {shown}; {', '.join(f'{how} ×{n}' for how, n in sorted(ways.items()))})"
        got.append(f"- worker rules: {agent} {_SAID.get(kind, kind)}{detail}, {len(items)} time{'s' if len(items) != 1 else ''}; "
                   f"`.lapis/state/{task}.workers.json` has the commands")
    limits = Counter((str(i.get("agent") or "a delegated worker"), str(i.get("reason"))) for i in log["limits"])
    got += [f"- worker rules: not checked for {agent}: {reason}; `.lapis/state/{task}.workers.json` names it"
            for (agent, reason), _ in sorted(limits.items())]
    return got


def scan_session(root: Path, task: str, agent: str, session: str, path: object) -> str | None:
    """Scan the transcript a harness's hook named (`path`) for `agent`, a main session or a subagent of conversation
    `session`, and record the findings in `.lapis/state/<task>.workers.json`; a path that is missing, unreadable, or holds no
    JSON row is recorded as a limit, never a failure. Returns the one line to tell the person when something new was
    recorded, else None. Never blocks."""
    name = f"{session}/{Path(path).name}" if session and isinstance(path, str) and path else session or "transcript"
    reason = None
    parsed: list[Any] = []
    if not isinstance(path, str) or not path:
        reason = "the hook event named no transcript"
    else:
        try:
            parsed = rows(Path(path).expanduser())
        except OSError:
            reason = "the transcript file could not be read"
        else:
            reason = None if parsed else "the transcript holds no JSON row"
    if reason is not None:
        return (f"LapisLazuli: {agent}: {reason}; see .lapis/state/{task}.workers.json"
                if record_limit(root, task, agent, name, reason) else None)
    new = record(root, task, agent, name, found) if (found := scan_rows(parsed)) else []
    return (f"LapisLazuli: {agent} broke a worker rule ({len(new)} finding{'s' if len(new) != 1 else ''}; the owner block "
            f"lists it): see .lapis/state/{task}.workers.json" if new else None)


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
    started, clock = datetime.now(timezone.utc), time.monotonic()
    found = scan(args.transcript)
    root = args.root.resolve()
    new = record(root, args.task, args.agent, args.transcript.name, found) if found else []
    kinds = ", ".join(f"{kind} ×{count}" for kind, count in Counter(item["kind"] for item in found).items())
    for item in found[:SHOWN]:
        how = f" ({item['how']}, {item['module']})" if item.get("module") else ""
        print(f"worker check: {item['kind']}{how}: {clip(item['evidence'], 160)}", file=sys.stderr)
    if len(found) > SHOWN:
        print(f"worker check: …and {len(found) - SHOWN} more of the {len(found)}; every command is in "
              f"{state_path(Path('.'), args.task).as_posix()}", file=sys.stderr)
    summary = (f"worker check: {len(found)} finding{'s' if len(found) != 1 else ''} in {args.transcript.name} ({kinds}; "
               f"{len(new)} new, recorded in {state_path(Path('.'), args.task).as_posix()})" if found
               else f"worker check: nothing in {args.transcript.name} stops a process by pattern or reads lapis-design source "
                    "(only what the scanner reads: see shared/review/worker-rules.md)")
    print(summary)
    telemetry.record(root, command=prog.removeprefix("lapis-design "), task=args.task, build_id=None, state_key=None,
                     scope="full", cache="off", started=telemetry.stamp(started), ended=telemetry.stamp(),
                     exit=1 if found else 0, output_chars=len(summary) + 1,
                     report_path=state_path(Path("."), args.task).as_posix() if found else None,
                     cache_reason="a transcript is read once per call; nothing to reuse", run_seconds=time.monotonic() - clock)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
