"""The order of the procedure: the brief, the references, the plan, and only then page code.

`next` asks for the records in that order, but nothing in a harness stops an agent from writing the page
first and the records afterwards to describe it, which leaves a plan that records the page instead of
steering it. This module makes the order visible and, where a harness can ask before a write, enforces it.

Detection (`violation`, read by `release check` and `next`): a create-mode plan whose page code came before the
brief, the references, or the plan. Two kinds of evidence, the first exact:

  - the first-write record `.lapis/order/<task>.json`, which `lapis-design hook pre-write` writes when it lets a
    page write through while the procedure still asked for the brief, the references, or the plan (a person's
    session, where the hook only gives notice; an unattended run past the refusal cap);
  - file times, for a harness with no pre-write event: every page file was last modified before the brief or
    the references record was. A plan is revised after the page legitimately, so its time says nothing.

The finding is lifted by a plan that cites the brief record in `context.other` and compares the existing code as
a candidate (`source: existing-code`) in a `direction` exploration, the code being kept only if it wins.

Prevention (`decide`, run by the versioned `lapis-design-hook` entry point for `PreToolUse` in Claude Code, Codex, and Antigravity,
and the tool_call event of Oh-My-Pi and pi): with `LAPIS_UNATTENDED=1`, a write of a page source file is refused
while `next` still names `brief`, `references`, `plan`, `plan-fix`, or `plan-explorations` for a create run.
Writes under `.lapis/` (except the folders below), to files that are not page code, and outside the project are never
refused. A person's session gets one line, once. A refusal repeats at most `CAP` times for one step: a plan blocker the
agent cannot lift must not keep it from writing anything, and a write let through after the cap is recorded as above.
The hook sees the harness's file-edit tools only; a page written through the shell is found afterwards.

Before that, in every session and whatever step `next` names, a write to a record only `lapis-design` writes
(`CLI_OWNED`: `.lapis/requirements/`, `.lapis/state/`, `.lapis/changes/`, `.lapis/owner/`) is refused, once per tool
call and with no cap. That stops the agent's tool, not a person. A write through the shell is not prevented; the change
log notices it (`integrity.py`: the log or the state no longer matches) and the owner sees the row.

Stdlib only until a page write must be judged: the hook starts for every file edit.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from lapis_design import attempts, gate

EXISTING = "existing-code"           # the `source` of the candidate that stands for code written before the plan
ORDER_STEPS = ("brief", "references", "plan")        # the records a page write can come before
BEFORE_CODE = (*ORDER_STEPS, "requirements", "plan-fix", "plan-explorations")    # steps after which page code may start
CAP = 3                              # refusals of one step; then the write goes through and is recorded
# the folders of `.lapis/` that only `lapis-design` writes (integrity.py, requirements.py, owner.py); a write to one
# is refused in every session, since the CLI computes what is in them and a hand edit would not be trusted
CLI_OWNED = (".lapis/requirements", ".lapis/state", ".lapis/changes", ".lapis/owner")

# the suffixes the source layer of the lint reads (lint/detectors/source.py), in the folders it walks
PAGE_SUFFIXES = {".css", ".scss", ".sass", ".less", ".styl", ".pcss", ".postcss", ".html", ".htm", ".vue",
                 ".svelte", ".astro", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}
SKIP_DIRS = {"node_modules", "bower_components", "jspm_packages", "vendor", "dist", "build", "out", "target", "obj",
             "Pods", "DerivedData", "coverage", "storybook-static", "__tests__", "__mocks__", "__pycache__", "venv"}
_NOT_PAGE = re.compile(r"\.(?:min|test|spec|stories|story|config)\.[^.]+$|\.d\.[cm]?ts$", re.I)
# a patch names its files in its text: Codex's apply_patch (`*** Update File: path`), and Oh-My-Pi's hashline edit (`[path#4F2A]`)
_PATCH_FILE = re.compile(r"^(?:\*\*\* (?:Add|Update|Delete) File: |\*\*\* Move to: )(.+?)\s*$|^\[([^\]\n#]+)#[0-9A-F]{4}\]\s*$",
                         re.M)
_PATH_KEYS = ("file_path", "path", "filePath")
_TEXT_KEYS = ("command", "input", "patch")

LABEL = {"brief": "brief record", "references": "references record", "plan": "plan"}
OWES = {"brief": "the brief record `.lapis/answers/{task}.md` (the lps-brief skill)",
        "requirements": "the requirement record `.lapis/requirements/{task}.json` (`lapis-design requirements seal`)",
        "references": "the references record `.lapis/references/{task}.md` (the lzl-research skill)",
        "plan": "the plan `.lapis/plans/{task}.yaml`, citing the records it rests on (a declined step has none)",
        "plan-fix": "a plan that `lapis-design plan check` reads and passes",
        "plan-explorations": "a plan that compares each open decision (`plan.uncompared-decision`)"}


def record_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "order" / f"{task}.json"


def load(root: Path, task: str) -> dict[str, Any]:
    """The order record of `task`: `{}` when there is none or it cannot be read."""
    try:
        state = json.loads(record_path(root, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _save(root: Path, task: str, state: dict[str, Any]) -> None:
    target = record_path(root, task)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"version": 0, "task": task, **state}, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    except OSError as exc:
        print(f"lapis-design order: {target} cannot be written: {exc}", file=sys.stderr)


def page_source(rel: str) -> bool:
    """Whether `rel`, a path relative to the project, is page code: a markup, style, or script file outside the
    hidden and generated folders and not a minified, test, story, declaration, or config file."""
    parts = Path(rel).parts
    if not parts or any(p.startswith(".") or p in SKIP_DIRS for p in parts[:-1]) or parts[-1].startswith("."):
        return False
    name = parts[-1]
    return Path(name).suffix.lower() in PAGE_SUFFIXES and not _NOT_PAGE.search(name)


def pages(root: Path) -> list[tuple[str, int]]:
    """The page source files under `root` with their modification times in nanoseconds."""
    found: list[tuple[str, int]] = []
    for folder, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS)
        for name in filenames:
            path = Path(folder) / name
            rel = path.relative_to(root).as_posix()
            if page_source(rel):
                try:
                    found.append((rel, path.stat().st_mtime_ns))
                except OSError:
                    continue
    return found


def named_paths(event: Mapping[str, Any], project: Path) -> list[str]:
    """Every file inside `project` that a file-edit event writes, relative to it, whatever the file is. The event is any
    harness's: `tool_input.file_path` (Claude Code), `path` (Oh-My-Pi and pi), and the text of a patch (Codex's
    `apply_patch` in `command`, Oh-My-Pi's hashline edit in `input`)."""
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, Mapping):
        return []
    named = [tool_input[k] for k in _PATH_KEYS if isinstance(tool_input.get(k), str)]
    for key in _TEXT_KEYS:
        if isinstance(tool_input.get(key), str):
            named += [a or b for a, b in _PATCH_FILE.findall(tool_input[key])]
    base = Path(event.get("cwd") or ".")
    found: list[str] = []
    for item in named:
        path = Path(os.path.realpath(item if os.path.isabs(item) else base / item))
        try:
            rel = path.relative_to(os.path.realpath(project)).as_posix()
        except ValueError:
            continue
        if rel not in found:
            found.append(rel)
    return found


def targets(event: Mapping[str, Any], project: Path) -> list[str]:
    """The page source files inside `project` that a file-edit event writes, relative to it."""
    return [rel for rel in named_paths(event, project) if not rel.startswith(".lapis/") and page_source(rel)]


def cli_owned(rel: str) -> bool:
    """Whether `rel`, a path relative to the project, is in a folder only `lapis-design` writes. Compared without case,
    since the folder may be on a case-insensitive file system."""
    folded = rel.casefold()
    return any(folded == folder or folded.startswith(folder + "/") for folder in CLI_OWNED)


def redone(plan: Mapping[str, Any], task: str) -> bool:
    """Whether the plan redid its direction after the code: it cites the brief record in `context.other` and a
    `direction` exploration lists the existing code as a candidate (`source: existing-code`)."""
    brief = f".lapis/answers/{task}.md"
    other = (plan.get("context") or {}).get("other") or []
    cites = any(isinstance(p, str) and posixpath.normpath(p.replace("\\", "/")).removeprefix("./").endswith(brief)
                for p in other)
    compared = any(isinstance(e, Mapping) and e.get("decision") == "direction"
                   and any(isinstance(c, Mapping) and c.get("source") == EXISTING for c in e.get("candidates") or ())
                   for e in plan.get("explorations") or ())
    return cites and compared


def _by_file_times(root: Path, task: str) -> dict[str, Any] | None:
    """The brief or references record that is newer than every page file, by modification time."""
    found = pages(root)
    if not found:
        return None
    newest = max(found, key=lambda item: item[1])
    for step, path in (("brief", root / ".lapis" / "answers" / f"{task}.md"),
                       ("references", root / ".lapis" / "references" / f"{task}.md")):
        try:
            if path.stat().st_mtime_ns > newest[1]:
                return {"step": step, "path": newest[0], "source": "file-times"}
        except OSError:
            continue
    return None


def violation(root: Path, task: str, plan: Mapping[str, Any]) -> dict[str, Any] | None:
    """The page write that came before the brief, the references, or the plan of a create plan, and was not
    answered by a redone direction: `{"step", "path", "source"}` (`source` is `hook` or `file-times`; a hook's
    record also has `at`), or None."""
    if plan.get("mode") != "create":
        return None
    first = load(root, task).get("first_page_write")
    found = ({**first, "source": "hook"} if isinstance(first, Mapping) and first.get("step") in ORDER_STEPS
             and isinstance(first.get("path"), str) else _by_file_times(root, task))
    return None if found is None or redone(plan, task) else found


def describe(found: Mapping[str, Any]) -> str:
    """The one line the release finding and `next` give for a violation."""
    label = LABEL[found["step"]]
    if found["source"] == "hook":
        return f"{found['path']} was written before the {label} was done ({found.get('at', 'time not recorded')})"
    return f"every page file is older than the {label} (the newest, {found['path']}), so the page was written first"


# ---------------------------------------------------------------- the pre-write hook

def _pending(project: Path, task: str) -> str | None:
    """The step of the procedure `next` asks for, or the step it waits to ask for; None when it is done."""
    from lapis_design import next_step

    result = next_step.evaluate(project, task)
    step = (result.get("then") or result["step"]) if result["step"] else None
    return step["id"] if step else None


def _create(project: Path, task: str) -> bool:
    """Whether the run is making a new surface. A folder with no plan and no page code is; a folder that holds
    page code and no plan says nothing about it (a small edit, a redesign, a repair), so it is not. A plan that cannot be
    read counts as create unless its text says another mode."""
    plan = project / ".lapis" / "plans" / f"{task}.yaml"
    if not plan.is_file():
        return not pages(project)
    try:
        text = plan.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    mode = re.search(r"^mode:\s*['\"]?([a-z]+)", text, re.M)
    return mode is None or mode.group(1) == "create"


def _refusal(page: str, task: str, step: str) -> dict[str, Any]:
    reason = (f"LapisLazuli refuses this write: {page} is page code, and task {task} is in create mode with "
              f"{OWES[step].format(task=task)} still owed. The order is brief, requirements, references, plan, then code. "
              f"Write that first (files under .lapis/ are never refused), run `lapis-design next --task {task}` "
              "for the step and its command, and write page files once it names a later step.")
    if step == "references":
        reason += (" If the user's words forbid lookups during the work and nobody can be asked, the step is declined "
                   "with their line, not researched and not left open (the step's text gives the command).")
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def _lapis_folder(start: Path, env: Mapping[str, str]) -> Path | None:
    """The nearest folder (`$CLAUDE_PROJECT_DIR`, else `start` or one above it) that has a `.lapis` folder, with or
    without a plan: the records `lapis-design` keeps exist before the plan does."""
    candidates = [Path(env["CLAUDE_PROJECT_DIR"])] if env.get("CLAUDE_PROJECT_DIR") else []
    start = start.resolve()
    return next((folder for folder in (*candidates, start, *start.parents) if (folder / ".lapis").is_dir()), None)


def _owned_refusal(rel: str) -> dict[str, Any]:
    reason = (f"LapisLazuli refuses this write: {rel} is a record only `lapis-design` writes (`.lapis/requirements/`, "
              "`.lapis/state/`, `.lapis/changes/`, `.lapis/owner/`). A write to it by any other route is found "
              "afterwards and shown to the owner as an integrity change. Run the command that makes the record "
              "(`lapis-design requirements seal`, `lapis-design next`), and tell the owner when it holds something wrong.")
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def decide(event: Mapping[str, Any], env: Mapping[str, str] = os.environ) -> dict[str, Any] | None:
    """The JSON a pre-write hook prints for a file-edit event: Claude Code's and Codex's `PreToolUse` refusal
    (the extensions translate it), `{"systemMessage": ...}` as the one line for a person, or None to let the
    write go on. A write to a folder only `lapis-design` writes (`CLI_OWNED`) is refused in every session."""
    unattended = gate.is_unattended(env)
    base = Path(event.get("cwd") or ".")
    project = gate.find_project(base, env)
    guarded = project or _lapis_folder(base, env)
    if guarded is not None and (owned := [rel for rel in named_paths(event, guarded) if cli_owned(rel)]):
        return _owned_refusal(owned[0])
    if project is None:
        return None
    written = targets(event, project)
    if not written:
        return None
    from lapis_design import next_step

    task = next_step.resolve_task(project, env.get("LAPIS_TASK")) or (gate.folder_task(project) if unattended else None)
    if not task or not attempts.TASK.fullmatch(task):
        return None
    try:
        step = _pending(project, task)
    except Exception as exc:        # a bug or an unreadable file here must not keep an agent from writing
        print(f"lapis-design hook pre-write: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    if step not in BEFORE_CODE or not _create(project, task):
        return None
    state = load(project, task)
    if unattended:
        denied = state.get("denied") if isinstance(state.get("denied"), dict) else {}
        count = denied.get("count", 0) if denied.get("step") == step else 0
        if count < CAP:
            _save(project, task, {**state, "denied": {"step": step, "count": count + 1}})
            return _refusal(written[0], task, step)
    if step in ORDER_STEPS and "first_page_write" not in state:
        _save(project, task, {**state, "first_page_write": {
            "path": written[0], "step": step, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}})
        if not unattended:
            return {"systemMessage": f"LapisLazuli: {written[0]} is page code written before the {LABEL[step]}; the "
                    f"procedure is brief, references, plan, then code (`lapis-design next --task {task}`). Nothing is "
                    "blocked here; `lapis-design release check` lists it."}
    return None
