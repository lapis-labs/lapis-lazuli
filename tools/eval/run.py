#!/usr/bin/env python3
"""Run paired skill-evaluation sessions: the same task, model, and prompt with and without skills.

    uv run --no-sync python tools/eval/run.py --model MODEL [--effort LEVEL] [--replicates 2] \\
        [--tasks all|ID,ID] [--out DIR] [--seed N] [--timeout SECONDS] [--dry-run] [--resume]

Every run gets its own empty project folder (a git repository, so Codex takes it as the project
root), a scratch HOME, and a Codex command that ignores the user's config and rules. The with-skill
arm receives copies of the task's `dist/skills/<skill>/` trees in `.agents/skills/`; the without arm
receives none. The skills Codex would otherwise load from the user's own folders are switched off
for both arms (`skills.config`), and each run's skill list is read back from
`codex debug prompt-input` to confirm the arm sees exactly its own skills. Arm order is randomized
per task and replicate from a recorded seed.

`--dry-run` builds the folders and prints every command but never starts a model: it runs only the
model-free `codex debug prompt-input` probe. Runs go under `--out` (default: a timestamped folder in
`~/.cache/lapis-eval/`), never inside the repository. Score them with `score.py`.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import evalkit as kit
from evalkit import ARMS, KitError

CODEX_TIMEOUT_DEFAULT = 2400
SANDBOXES = ("workspace-write", "danger-full-access")
_SKILLS_BLOCK = re.compile(r"<skills_instructions>(.*?)</skills_instructions>", re.S)
_ROOT_LINE = re.compile(r"^- `(r\d+)` = `([^`]+)`\s*$", re.M)
_SKILL_LINE = re.compile(r"^- (\S+?): .*\(file: ([^)\n]+)\)\s*$", re.M)
_SKILL_PATH = re.compile(r"\.agents/skills/([A-Za-z0-9_.\-]+)/")
_CHECK_CALL = re.compile(r"\b(lapis-design|lazuli)\s+([a-z]+)(?:\s+([a-z]+))?")


# ------------------------------------------------------------------ planning

def plan_runs(task_ids: list[str], replicates: int, seed: int) -> list[dict]:
    """The run order: per replicate the tasks shuffled, and per task the two arms shuffled."""
    rng = random.Random(seed)
    order = []
    for replicate in range(1, replicates + 1):
        tasks = list(task_ids)
        rng.shuffle(tasks)
        for task in tasks:
            arms = list(ARMS)
            rng.shuffle(arms)
            order.extend({"task": task, "replicate": replicate, "arm": arm} for arm in arms)
    for position, run in enumerate(order, 1):
        run["order"] = position
        run["id"] = kit.run_id(run["task"], run["replicate"], run["arm"])
    return order


# ------------------------------------------------------------------ the Codex command

def toml_skill_config(paths: list[str]) -> str:
    """`skills.config` value that switches each path off (JSON string escapes are valid TOML)."""
    return "[" + ",".join("{path=%s,enabled=false}" % json.dumps(p) for p in paths) + "]"


def codex_command(codex: str, project: Path, last_message: Path, *, model: str, effort: str | None,
                  sandbox: str, network: bool, add_dirs: list[Path], disabled: list[str]) -> list[str]:
    """`codex exec` for one run; the prompt comes from stdin (`-`)."""
    cmd = [codex, "exec", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "--ephemeral",
           "--color", "never", "--json", "--sandbox", sandbox, "-C", str(project), "-m", model,
           "-o", str(last_message)]
    if effort:
        cmd += ["-c", f"model_reasoning_effort={json.dumps(effort)}"]
    if sandbox == "workspace-write":
        if network:
            cmd += ["-c", "sandbox_workspace_write.network_access=true"]
        for folder in add_dirs:
            cmd += ["--add-dir", str(folder)]
    if disabled:
        cmd += ["-c", "skills.config=" + toml_skill_config(disabled)]
    cmd.append("-")
    return cmd


_VALUE_OPTIONS = {"-c", "-C", "-m", "-o", "--sandbox", "--color", "--add-dir"}


def format_command(cmd: list[str], *, elide: bool = False) -> str:
    """A shell command with each option and its value on one line; `elide` shortens the long
    `skills.config` value for printing (command.txt keeps the whole command)."""
    lines, index = [], 0
    while index < len(cmd):
        parts = [cmd[index]]
        if cmd[index] in _VALUE_OPTIONS and index + 1 < len(cmd):
            index += 1
            value = cmd[index]
            if elide and value.startswith("skills.config=") and len(value) > 200:
                value = f"skills.config=[... {value.count('enabled=false')} paths switched off ...]"
            parts.append(value)
        lines.append(" ".join(shlex.quote(p) for p in parts))
        index += 1
    return " \\\n  ".join(lines)


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def make_shims(out: Path) -> Path | None:
    """A bin folder with the repository's `lapis-design` and `lazuli`, so the agent finds them on PATH.

    The skills tell agents to run those commands; on a machine where they are only in the project's
    venv the agent would otherwise find neither. Both arms get the same PATH."""
    folder = out / "bin"
    made = False
    for name in ("lapis-design", "lazuli"):
        source = Path(sys.executable).parent / name
        if not source.exists():
            found = shutil.which(name)
            source = Path(found) if found else None
        if source is None:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        link = folder / name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(source)
        made = True
    return folder if made else None


def agent_env(run_dir: Path, shims: Path | None) -> dict[str, str]:
    """The environment of one agent: a scratch HOME (no user skills, fonts, or caches), the real
    CODEX_HOME (auth stays the user's login), and lazuli pointed at an empty font folder."""
    env = dict(os.environ)
    home = run_dir / "home"
    env["HOME"] = str(home)
    env["CODEX_HOME"] = str(codex_home())
    env["LAZULI_FONT_ROOTS"] = f"user={home / 'fonts'}"
    env["PLAYWRIGHT_BROWSERS_PATH"] = kit.browsers_path()
    for name in ("LAZULI_DB", "LAPIS_SIG_KEY_FILE"):
        env.pop(name, None)
    if shims is not None:
        env["PATH"] = os.pathsep.join([str(shims), env.get("PATH", "")])
    return env


# ------------------------------------------------------------------ isolation probe

def parse_prompt_input(items: list) -> dict:
    """Skills and instruction injection out of `codex debug prompt-input` JSON.

    Returns {"skills": [{"name", "path"}], "unparsed": int, "agents_md": bool}; `path` is the SKILL.md
    file, and `unparsed` counts list entries that did not match the expected line shape."""
    texts = []
    for item in items if isinstance(items, list) else []:
        content = item.get("content") if isinstance(item, dict) else None
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
    skills, unparsed = [], 0
    for text in texts:
        block = _SKILLS_BLOCK.search(text)
        if not block:
            continue
        roots = dict(_ROOT_LINE.findall(block.group(1)))
        matched = _SKILL_LINE.findall(block.group(1))
        unparsed += len(re.findall(r"^- ", block.group(1).partition("### Available skills")[2], re.M)) - len(matched)
        for name, ref in matched:
            head, _, rest = ref.partition("/")
            path = f"{roots[head]}/{rest}" if head in roots else ref
            skills.append({"name": name, "path": os.path.realpath(path)})
    return {"skills": skills, "unparsed": unparsed,
            "agents_md": any("# AGENTS.md instructions" in text for text in texts)}


def probe_prompt_input(codex: str, project: Path, env: dict, disabled: list[str] | None = None) -> dict:
    """Render what the model would see for a project, without a model: the skills and AGENTS.md."""
    cmd = [codex, "debug", "prompt-input"]
    if disabled:
        cmd += ["-c", "skills.config=" + toml_skill_config(disabled)]
    cmd.append("probe")
    try:
        done = subprocess.run(cmd, cwd=project, env=env, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    if done.returncode:
        return {"error": kit.first_line(done.stderr) or f"exit {done.returncode}"}
    try:
        return parse_prompt_input(json.loads(done.stdout))
    except json.JSONDecodeError as exc:
        return {"error": f"prompt-input output is not JSON: {exc}"}


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def isolate_skills(codex: str, project: Path, env: dict, expected: list[str], *, disable_outside: bool) -> dict:
    """Find the skills Codex would load from outside the project, switch them off, and read the list back.

    `verified` means the run will see exactly the expected project skills (or, with disable_outside
    False, at least those). The SKILL.md path and its folder are both listed because which one Codex
    matches differs between versions (0.158.0: the file)."""
    keep_root = os.path.realpath(project / ".agents" / "skills")
    before = probe_prompt_input(codex, project, env)
    if "error" in before:
        return {"verified": False, "reason": "probe failed: " + before["error"], "expected": expected,
                "disabled": [], "visible": []}
    inside = sorted({s["name"] for s in before["skills"] if _under(s["path"], keep_root)})
    outside = [s for s in before["skills"] if not _under(s["path"], keep_root)]
    disabled = sorted({p for s in outside for p in (s["path"], os.path.dirname(s["path"]))}) if disable_outside else []
    after = probe_prompt_input(codex, project, env, disabled) if disabled else before
    if "error" in after:
        return {"verified": False, "reason": "probe with overrides failed: " + after["error"],
                "expected": expected, "disabled": disabled, "visible": []}
    visible = sorted(s["name"] for s in after["skills"])
    missing = sorted(set(expected) - set(inside))
    reason = None
    if before["unparsed"] or after["unparsed"]:
        reason = f"{max(before['unparsed'], after['unparsed'])} skill entries in the prompt could not be read"
    elif missing:
        reason = "skills not discovered in the project: " + ", ".join(missing)
    elif disable_outside and visible != sorted(expected):
        reason = "skills still visible after switching off the outside ones: " + \
                 ", ".join(sorted(set(visible) - set(expected)))
    return {"verified": reason is None, "reason": reason, "expected": sorted(expected), "visible": visible,
            "outside_before": sorted({s["name"] for s in outside}), "disabled": disabled,
            "agents_md_injected": after["agents_md"]}


# ------------------------------------------------------------------ reading a finished session

def parse_events(lines: list[str], expected_skills: list[str] | None = None) -> dict:
    """Token usage, turns, commands, skills read, and checks run, from `codex exec --json` lines.

    Tolerant by design: unknown events and missing fields are skipped, so a Codex version that adds
    events cannot break scoring. Usage sums the `turn.completed` events."""
    usage: Counter = Counter()
    turns = commands = 0
    skills: list[str] = []
    checks: Counter = Counter()
    errors: list[str] = []
    thread = None
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "thread.started":
            thread = event.get("thread_id")
        elif kind == "turn.completed":
            turns += 1
            for key, value in (event.get("usage") or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    usage[key] += value
        elif kind in ("turn.failed", "error"):
            detail = event.get("error") or event.get("message") or event
            errors.append(kit.first_line(detail.get("message", "") if isinstance(detail, dict) else str(detail)))
        item = event.get("item")
        if isinstance(item, dict) and str(kind).startswith("item."):
            for name in _SKILL_PATH.findall(json.dumps(item, ensure_ascii=False)):
                if name not in skills:
                    skills.append(name)
            if kind == "item.completed" and item.get("type") == "command_execution":
                commands += 1
                for tool, noun, verb in _CHECK_CALL.findall(str(item.get("command", ""))):
                    checks[f"{tool} {noun} {verb}".strip()] += 1
    result = {"thread_id": thread, "turns": turns, "commands": commands,
              "usage": dict(usage) or None, "skills_read": skills, "tools_run": dict(sorted(checks.items())),
              "errors": [e for e in errors if e]}
    if expected_skills is not None:
        result["skills_not_read"] = [s for s in expected_skills if s not in skills]
    return result


# ------------------------------------------------------------------ preparing a run

def prepare_run(spec: dict, task: dict, ctx: dict) -> tuple[dict, list[str], dict]:
    """Create one run folder; return its run.json (status `prepared`), the exact command, and its env."""
    run_dir = ctx["out"] / "runs" / spec["id"]
    project, home = run_dir / "project", run_dir / "home"
    project.mkdir(parents=True)
    (home / "fonts").mkdir(parents=True)
    if ctx["git"]:
        subprocess.run([ctx["git"], "init", "-q", str(project)], check=False, capture_output=True)
    skills = task["skills"] if spec["arm"] == "with" else []
    digests: dict[str, str] = {}
    for name in skills:
        target = project / ".agents" / "skills" / name
        shutil.copytree(ctx["skills_dir"] / name, target, ignore=shutil.ignore_patterns(".DS_Store", "__pycache__"))
        digests[name] = kit.tree_digest(target)
        if digests[name] != kit.tree_digest(ctx["skills_dir"] / name):
            raise KitError(f"the copy of skill {name} differs from {ctx['skills_dir'] / name}")
    skills_root = project / ".agents" / "skills"
    (run_dir / "prompt.txt").write_text(task["prompt"], encoding="utf-8")
    env = agent_env(run_dir, ctx["shims"])
    isolation = isolate_skills(ctx["codex"], project, env, skills, disable_outside=not ctx["keep_outside"])
    cmd = codex_command(ctx["codex"], project, run_dir / "last-message.txt", model=ctx["model"],
                        effort=ctx["effort"], sandbox=ctx["sandbox"], network=ctx["network"],
                        add_dirs=[home], disabled=isolation.get("disabled", []))
    shell = format_command(cmd) + " \\\n  < prompt.txt"
    (run_dir / "command.txt").write_text(
        f"# run from {run_dir}\n# environment: HOME={home} CODEX_HOME={env['CODEX_HOME']} "
        f"LAZULI_FONT_ROOTS={env['LAZULI_FONT_ROOTS']} PATH={ctx['shims']}:$PATH\n{shell}\n", encoding="utf-8")
    kit.write_json(run_dir / "isolation.json", isolation)
    isolation_summary = {k: v for k, v in isolation.items() if k != "disabled"}
    isolation_summary["disabled_count"] = len(isolation.get("disabled", []))
    record = {
        "version": kit.RECORD_VERSION, "id": spec["id"], "task": spec["task"], "arm": spec["arm"],
        "replicate": spec["replicate"], "order": spec["order"], "status": "prepared",
        "project": "project", "skills": skills,
        "skill_digest": kit.tree_digest(skills_root) if skills else None, "skill_digests": digests,
        "prompt_sha256": kit.sha256_bytes(task["prompt"].encode("utf-8")),
        "model": ctx["model"], "effort": ctx["effort"], "sandbox": ctx["sandbox"], "network": ctx["network"],
        "harness": {"name": "codex", "version": ctx["codex_version"]},
        "isolation": isolation_summary,
        "started_at": None, "ended_at": None, "duration_s": None, "exit_code": None, "timed_out": False,
        "usage": None,
    }
    kit.write_json(run_dir / "run.json", record)
    return record, cmd, env


# ------------------------------------------------------------------ executing a run

def _stop(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def _project_output(project: Path) -> dict:
    files = size = 0
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames if d not in (".git", ".agents")]
        for name in filenames:
            files += 1
            size += (Path(dirpath) / name).stat().st_size
    return {"files": files, "bytes": size, "has_index": (project / "index.html").is_file()}


def execute_run(run_dir: Path, cmd: list[str], env: dict, timeout: int) -> dict:
    """Start Codex for a prepared run, wait, and record the outcome in run.json."""
    record = kit.read_json(run_dir / "run.json")
    project = run_dir / record["project"]
    record.update(status="running", started_at=kit.utc_now())
    kit.write_json(run_dir / "run.json", record)
    started = time.monotonic()
    timed_out = interrupted = False
    with open(run_dir / "prompt.txt", "rb") as stdin, open(run_dir / "events.jsonl", "wb") as events, \
            open(run_dir / "stderr.log", "wb") as stderr:
        proc = subprocess.Popen(cmd, stdin=stdin, stdout=events, stderr=stderr, cwd=project, env=env,
                                start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop(proc)
            code = proc.returncode
        except KeyboardInterrupt:
            interrupted = True
            _stop(proc)
            code = proc.returncode
    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()
    parsed = parse_events(lines, record["skills"] if record["arm"] == "with" else None)
    last = run_dir / "last-message.txt"
    record.update(
        status="interrupted" if interrupted else "timed_out" if timed_out else "completed" if code == 0 else "failed",
        ended_at=kit.utc_now(), duration_s=round(time.monotonic() - started, 1), exit_code=code,
        timed_out=timed_out, usage=parsed["usage"], session={k: v for k, v in parsed.items() if k != "usage"},
        output=_project_output(project),
        last_message_chars=len(last.read_text(encoding="utf-8")) if last.is_file() else 0)
    kit.write_json(run_dir / "run.json", record)
    if interrupted:
        raise KeyboardInterrupt
    return record


# ------------------------------------------------------------------ orchestration

def _git(*args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", str(kit.REPO), *args], capture_output=True, text=True, timeout=30)
        return done.stdout.strip() if done.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _command_output(cmd: list[str], env: dict | None = None) -> str | None:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (done.stdout or done.stderr).strip() if done.returncode == 0 else None


def preflight(codex: str, dry_run: bool) -> dict:
    """What the sessions will run on: the Codex version and login, instruction files that both arms share."""
    version = _command_output([codex, "--version"])
    if version is None:
        raise KitError(f"`{codex} --version` failed; install Codex or pass --codex PATH")
    logged_in = _command_output([codex, "login", "status"]) is not None
    if not logged_in and not dry_run:
        raise KitError("Codex is not logged in (`codex login status` failed); run `codex login` yourself first")
    notes = {}
    for name in ("AGENTS.md", "AGENTS.override.md", "hooks.json"):
        path = codex_home() / name
        if path.is_file():
            notes[name] = kit.sha256_file(path)[:16]
    return {"version": version, "logged_in": logged_in, "shared_files": notes}


def build_context(args: argparse.Namespace, out: Path, settings: dict) -> dict:
    shims = make_shims(out)
    return {"out": out, "codex": args.codex, "skills_dir": Path(args.skills_dir).resolve(), "shims": shims,
            "git": shutil.which("git"), "keep_outside": args.keep_outside_skills, **settings}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", help="Codex model, the same for every run (required unless --resume)")
    ap.add_argument("--effort", help="model_reasoning_effort for every run (default: the model's own)")
    ap.add_argument("--tasks", default="all", help="comma-separated task ids, or all (default)")
    ap.add_argument("--replicates", type=int, default=2, help="runs per task and arm (default 2)")
    ap.add_argument("--out", type=Path, help="run folder (default: a timestamped folder in ~/.cache/lapis-eval/)")
    ap.add_argument("--seed", type=int, help="seed for the run order (default: random, recorded)")
    ap.add_argument("--timeout", type=int, default=CODEX_TIMEOUT_DEFAULT, help="seconds per run (default 2400)")
    ap.add_argument("--sandbox", choices=SANDBOXES, default="workspace-write",
                    help="Codex sandbox; Chromium cannot start inside workspace-write on macOS, so agents "
                         "there cannot run render or behavior checks (see README.md)")
    ap.add_argument("--network", action="store_true", help="allow network in workspace-write")
    ap.add_argument("--codex", default="codex", help="Codex executable")
    ap.add_argument("--skills-dir", type=Path, default=kit.REPO / "dist" / "skills")
    ap.add_argument("--keep-outside-skills", action="store_true",
                    help="do not switch off skills Codex loads from the user's own folders")
    ap.add_argument("--dry-run", action="store_true", help="prepare folders and print commands; start no model")
    ap.add_argument("--resume", action="store_true", help="continue --out: skip finished runs")
    args = ap.parse_args(argv)
    if os.name == "nt":
        ap.error("the eval kit supports macOS and Linux only")
    try:
        return _main(args, ap)
    except KitError as exc:
        print(f"run.py: {exc}", file=sys.stderr)
        return 2


def _choose_runs(args: argparse.Namespace, ap: argparse.ArgumentParser, tasks: dict) -> tuple[list[str], list[dict]]:
    """The task ids and run order for a fresh out folder; records the seed on args."""
    if not args.model:
        ap.error("--model is required")
    task_ids = list(tasks) if args.tasks == "all" else list(dict.fromkeys(t for t in args.tasks.split(",") if t))
    unknown = [t for t in task_ids if t not in tasks]
    if unknown:
        raise KitError(f"unknown task: {', '.join(unknown)} (known: {', '.join(tasks)})")
    if args.replicates < 1:
        ap.error("--replicates must be at least 1")
    args.seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1 << 31)
    return task_ids, plan_runs(task_ids, args.replicates, args.seed)


def _manifest(args: argparse.Namespace, pre: dict, tasks: dict, task_ids: list[str], order: list[dict],
              skills_dir: Path, lapis: str | None) -> dict:
    skills = sorted({s for t in task_ids for s in tasks[t]["skills"]})
    return {
        "version": kit.RECORD_VERSION, "created_at": kit.utc_now(), "dry_run": args.dry_run, "seed": args.seed,
        "model": args.model, "effort": args.effort, "sandbox": args.sandbox, "network": args.network,
        "timeout_s": args.timeout, "codex": {"bin": args.codex, "version": pre["version"]},
        "shared_codex_files": pre["shared_files"],
        "repo": {"commit": _git("rev-parse", "HEAD"),
                 "dirty_sources": bool(_git("status", "--porcelain", "--", "src", "dist"))},
        "lapis_design": lapis,
        "tasks": {t: {"prompt_sha256": kit.sha256_bytes(tasks[t]["prompt"].encode("utf-8")),
                      "skills": tasks[t]["skills"]} for t in task_ids},
        "tasks_file_sha256": kit.sha256_file(kit.TASKS_FILE),
        "skill_digests": {s: kit.tree_digest(skills_dir / s) for s in skills},
        "order": order, "finished_at": None,
    }


def _main(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    tasks = kit.load_tasks()
    if args.resume and not args.out:
        ap.error("--resume needs --out")
    out = kit.ensure_outside_repo(args.out or kit.default_out_root() / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    manifest_path = out / "manifest.json"
    previous = None
    if args.resume:
        if not manifest_path.is_file():
            raise KitError(f"{out} has no manifest.json to resume")
        previous = kit.read_json(manifest_path)
        for key in ("model", "effort", "sandbox", "network", "seed"):
            setattr(args, key, previous[key])
        task_ids, order = list(previous["tasks"]), previous["order"]
    else:
        if manifest_path.exists():
            raise KitError(f"{out} already holds a manifest; pick a new --out or pass --resume")
        task_ids, order = _choose_runs(args, ap, tasks)
    skills_dir = Path(args.skills_dir).resolve()
    for task_id in task_ids:
        for name in tasks[task_id]["skills"]:
            if not (skills_dir / name / "SKILL.md").is_file():
                raise KitError(f"task {task_id}: {skills_dir / name}/SKILL.md is missing; run tools/build/build.py")

    pre = preflight(args.codex, args.dry_run)
    out.mkdir(parents=True, exist_ok=True)
    ctx = build_context(args, out, {"model": args.model, "effort": args.effort, "sandbox": args.sandbox,
                                    "network": args.network, "codex_version": pre["version"]})
    lapis = _command_output([str(ctx["shims"] / "lapis-design"), "--version"]) if ctx["shims"] else None
    if lapis is None:
        print("warning: lapis-design is not on the agents' PATH; agents given the skills cannot run its checks",
              file=sys.stderr)
    manifest = _manifest(args, pre, tasks, task_ids, order, skills_dir, lapis) if previous is None else {
        **previous, "resumed_at": kit.utc_now(), "dry_run": args.dry_run, "timeout_s": args.timeout,
        "finished_at": None}
    kit.write_json(manifest_path, manifest)
    if pre["shared_files"]:
        print("note: Codex loads these files from CODEX_HOME in every run, both arms: "
              + ", ".join(pre["shared_files"]), file=sys.stderr)

    prepared = []
    for spec in order:
        run_dir = out / "runs" / spec["id"]
        if previous is not None and run_dir.exists():
            status = kit.read_json(run_dir / "run.json").get("status") if (run_dir / "run.json").is_file() else None
            if status in kit.FINISHED:
                continue
            shutil.rmtree(run_dir)
        record, cmd, env = prepare_run(spec, tasks[spec["task"]], ctx)
        iso = record["isolation"]
        flag = "ok" if iso["verified"] else f"NOT VERIFIED: {iso['reason']}"
        print(f"prepared {spec['order']:>2}/{len(order)} {spec['id']:<34} skills visible: "
              f"{', '.join(iso['visible']) or '-'} ({iso['disabled_count']} outside switched off) [{flag}]")
        prepared.append((spec, run_dir, record, cmd, env))
    unverified = [spec["id"] for spec, _, record, _, _ in prepared if not record["isolation"]["verified"]]
    if unverified and not args.dry_run:
        raise KitError("skill isolation not verified for: " + ", ".join(unverified) +
                       " (inspect with --dry-run; --keep-outside-skills relaxes the check)")

    if args.dry_run:
        for spec, run_dir, _, cmd, _ in prepared:
            header = "\n".join((run_dir / "command.txt").read_text(encoding="utf-8").splitlines()[:2])
            print(f"\n# {spec['id']}\n{header}\n{format_command(cmd, elide=True)} \\\n  < prompt.txt")
        print(f"\ndry run: {len(prepared)} run folders under {out}/runs; no model was started")
        return 0

    incomplete = []
    for spec, run_dir, _, cmd, env in prepared:
        print(f"running  {spec['order']:>2}/{len(order)} {spec['id']} ...", flush=True)
        try:
            done = execute_run(run_dir, cmd, env, args.timeout)
        except KeyboardInterrupt:
            print("interrupted; continue later with --resume", file=sys.stderr)
            return 130
        tokens = sum((done["usage"] or {}).get(k, 0) for k in ("input_tokens", "output_tokens"))
        print(f"  {done['status']} exit {done['exit_code']} in {done['duration_s']} s, "
              f"{tokens or 'no'} tokens, index.html: {done['output']['has_index']}")
        if done["status"] != "completed":
            incomplete.append(spec["id"])
    manifest["finished_at"] = kit.utc_now()
    kit.write_json(manifest_path, manifest)
    print(f"\nall runs finished under {out}\n"
          f"score them: uv run --no-sync python tools/eval/score.py {shlex.quote(str(out))}")
    if incomplete:
        print("not completed (still scorable, but read their run.json first): " + ", ".join(incomplete),
              file=sys.stderr)
    return 1 if incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
