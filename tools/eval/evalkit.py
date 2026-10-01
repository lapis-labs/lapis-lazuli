"""Shared helpers of the skill-effectiveness kit: paths, the task file, run records, tree digests.

Nothing here starts a model or a browser. `run.py` prepares and executes runs, `score.py` scores them,
`review.py` builds the blind review sheet; all three read and write the run folders described in
README.md through these helpers.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
EVAL_DIR = Path(__file__).resolve().parent
TASKS_FILE = EVAL_DIR / "tasks.yaml"
ARMS = ("with", "without")
RECORD_VERSION = 1
FINISHED = ("completed", "failed", "timed_out")   # a resume repeats anything else, `interrupted` included
_IGNORED_NAMES = {".DS_Store"}
_IGNORED_DIRS = {"__pycache__"}


class KitError(Exception):
    """A problem the operator can fix: a bad task file, an unsafe folder, a missing input."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def first_line(text: str, limit: int = 240) -> str:
    """The first non-empty line of a message, clipped, for one-line reasons."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""


# ------------------------------------------------------------------ files

def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, doc: Any) -> None:
    """Write through a temporary file so an interrupted run never leaves half a record."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root: Path) -> str:
    """sha256 over the sorted relative paths and file hashes of a tree (names and bytes, not mtimes)."""
    root = Path(root)
    digest = hashlib.sha256()
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORED_DIRS)
        for name in filenames:
            if name in _IGNORED_NAMES or name.endswith(".pyc"):
                continue
            full = Path(dirpath, name)
            entries.append((full.relative_to(root).as_posix(), full))
    for rel, full in sorted(entries):
        digest.update(rel.encode("utf-8") + b"\0" + sha256_file(full).encode("ascii") + b"\n")
    return digest.hexdigest()


# ------------------------------------------------------------------ folders

def default_out_root() -> Path:
    """Where runs go unless --out says otherwise: the user cache, never a repository."""
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "lapis-eval"


def ensure_outside_repo(path: Path) -> Path:
    """Runs hold whole agent projects; they never belong inside this repository."""
    resolved = Path(path).expanduser().resolve()
    if resolved == REPO or REPO in resolved.parents:
        raise KitError(f"{path} is inside the repository; give an --out folder outside {REPO}")
    return resolved


def within(path: str | Path, base: str | Path) -> bool:
    """Whether `path`, with every link resolved, is `base` or lies below it."""
    real, root = os.path.realpath(path), os.path.realpath(base)
    return real == root or real.startswith(root.rstrip(os.sep) + os.sep)


def links_outside(root: Path, base: Path | None = None, skip=lambda name: False) -> list[str]:
    """Symlinks under `root` (paths relative to it) whose target resolves outside `base`, which is
    `root` unless given. `skip(name)` leaves out entries by name, directories with their contents;
    links are never followed while walking. When `root` itself resolves outside `base` the answer is
    `["."]`: everything under it is outside."""
    root = Path(root)
    if not within(root, base or root):
        return ["."]
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not skip(d))
        for name in (*dirnames, *sorted(filenames)):
            path = os.path.join(dirpath, name)
            if not skip(name) and os.path.islink(path) and not within(path, base or root):
                found.append(Path(path).relative_to(root).as_posix())
    return sorted(found)


def redact_home(text: str) -> str:
    """`text` with the user's home directory, as named and as resolved, replaced by `~`."""
    homes = {str(Path.home()), os.path.realpath(Path.home())} - {"", os.sep}
    for home in sorted(homes, key=len, reverse=True):
        text = text.replace(home, "~")
    return text


def public_isolation(isolation: dict) -> dict:
    """`isolation` as it may be written to disk: counts, never the names or paths of the user's own
    skills (`outside_before` is a count, `disabled` becomes `disabled_count`), and no home directory
    in a reason. The full result stays in memory: the command needs the paths and the console names
    the skills that leaked. Applying it to its own result changes nothing, so it also cleans records
    written before it existed."""
    expected = set(isolation.get("expected", []))
    seen = list(isolation.get("visible", []))
    outside = isolation.get("outside_before")
    names = outside if isinstance(outside, list) else []
    record = {k: v for k, v in isolation.items() if k not in ("disabled", "visible", "outside_before", "reason")}
    record["visible"] = [n for n in seen if n in expected]
    record["visible_other"] = isolation.get("visible_other", 0) + len(seen) - len(record["visible"])
    record["outside_before"] = len(outside) if isinstance(outside, list) else outside
    record["disabled_count"] = (len(isolation["disabled"]) if "disabled" in isolation
                                else isolation.get("disabled_count", 0))
    reason = redact_home(isolation.get("reason") or "")
    for name in sorted({*names, *seen} - expected, key=len, reverse=True):
        reason = re.sub(r"(?<![\w.-])" + re.escape(name) + r"(?![\w.-])", "<skill>", reason)
    record["reason"] = reason or None
    return record


def run_id(task: str, replicate: int, arm: str) -> str:
    return f"{task}.r{replicate}.{arm}"


def runs_dir(out: Path) -> Path:
    return Path(out) / "runs"


def list_runs(out: Path) -> list[Path]:
    """Run folders under `out/runs` that hold a run.json, in the order they were planned."""
    folders = [p for p in runs_dir(out).glob("*") if (p / "run.json").is_file()]
    return sorted(folders, key=lambda p: (read_json(p / "run.json").get("order", 0), p.name))


def browsers_path() -> str:
    """Where Playwright's browsers are, read before HOME is replaced for an agent (see tests/conftest.py)."""
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured:
        return configured if configured == "0" or os.path.isabs(configured) else os.path.abspath(configured)
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    return str(base / "ms-playwright")


# ------------------------------------------------------------------ Adobe data stays out of evaluations

_ADOBE = re.compile(r"adobe", re.I)
_NOT_TOOL_ITEMS = {"agent_message", "reasoning", "command_execution", "file_change", "todo_list", "error"}
_TOOL_NAME_KEYS = {"server", "server_name", "tool", "tool_name", "name", "namespace", "connector",
                   "connector_name", "tool_title", "recipient_name"}
_PAYLOAD_KEYS = {"arguments", "result", "error", "output", "input", "content", "text", "aggregated_output"}


def _tool_names(node: Any, found: set[str]) -> None:
    """Collect the values of tool-identifying keys that name Adobe. What the agent said or ran in a shell,
    and what a tool was given or answered, is not looked at: only which tool was called."""
    if isinstance(node, dict):
        if node.get("type") in _NOT_TOOL_ITEMS:
            return
        for key, value in node.items():
            if key in _PAYLOAD_KEYS:
                continue
            if isinstance(value, str):
                if key in _TOOL_NAME_KEYS and _ADOBE.search(value):
                    found.add(value)
            else:
                _tool_names(value, found)
    elif isinstance(node, list):
        for item in node:
            _tool_names(item, found)


def adobe_tool_calls(run_dir: Path) -> list[str]:
    """The names of Adobe tools (connector apps) that the run's event log (`events.jsonl`) shows as
    called; empty when the log is missing or none was. Lines that are not JSON are skipped."""
    log = Path(run_dir) / "events.jsonl"
    if not log.is_file():
        return []
    found: set[str] = set()
    with open(log, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            _tool_names(event, found)
    return sorted(found)


def refuse_adobe_calls(run_dirs: Iterable[Path], action: str) -> None:
    """Raise when any of the runs called an Adobe tool: what such a call returns is Adobe data, which
    never goes into an evaluation (a session that used it is neither scored nor summarized)."""
    called = {Path(d).name: names for d in run_dirs if (names := adobe_tool_calls(d))}
    if called:
        listing = "; ".join(f"{run}: {', '.join(names)}" for run, names in sorted(called.items()))
        raise KitError(f"cannot {action}: the event log of {len(called)} run(s) shows a call to an Adobe tool "
                       f"({listing}). Data from Adobe Fonts is never used in an evaluation; move those run "
                       "folders out of the out folder, then try again")


def evaluation_font_db(path: Path) -> dict:
    """The evaluation font database `score.py` pins as `LAZULI_DB`: its resolved path, sha256, and the
    number of faces and families it holds. It is built from OFL fonts only (README.md, "The evaluation
    font database"), so it is refused when it is missing, outside a lazuli schema, empty, holds an
    Adobe Fonts face (origin `adobe-sync`, or a `coretext:` path), or has writes that are not in the
    file yet (the hash would not describe what the checkers read)."""
    path = Path(path).expanduser().resolve()
    if path == REPO or REPO in path.parents:
        raise KitError(f"{path} is inside the repository; keep the evaluation font database outside {REPO}")
    if not path.is_file():
        raise KitError(f"{path} is not a file; build the evaluation font database first "
                       "(tools/eval/README.md, \"The evaluation font database\")")
    pending = path.with_name(path.name + "-wal")
    if pending.is_file() and pending.stat().st_size:
        raise KitError(f"{path} has writes in {pending.name} that are not in the file; "
                       "run `PRAGMA wal_checkpoint(TRUNCATE)` on it, then score")
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            faces, families, adobe = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT family_norm), "
                "COALESCE(SUM(origin = 'adobe-sync' OR path LIKE 'coretext:%'), 0) FROM local_font").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise KitError(f"{path} cannot be read as a lazuli database: {exc}") from exc
    if adobe:
        raise KitError(f"{path} holds {adobe} Adobe Fonts faces; an evaluation database is built from OFL "
                       "fonts only, with LAZULI_FONT_ROOTS set (tools/eval/README.md)")
    if not faces:
        raise KitError(f"{path} holds no fonts; build it from the OFL folder (tools/eval/README.md)")
    return {"path": path, "sha256": sha256_file(path), "faces": faces, "families": families}


# ------------------------------------------------------------------ tasks

def load_tasks(path: Path = TASKS_FILE) -> dict[str, dict]:
    """The tasks by id, checked for the fields run.py, score.py, and review.py rely on."""
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("version") != RECORD_VERSION:
        raise KitError(f"{path}: expected a mapping with version: {RECORD_VERSION}")
    tasks = doc.get("tasks")
    if not isinstance(tasks, dict) or not tasks:
        raise KitError(f"{path}: `tasks` must be a non-empty mapping")
    for task_id, task in tasks.items():
        where = f"{path}: task {task_id}"
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(task_id)):
            raise KitError(f"{where}: the id must be lowercase words joined by hyphens")
        if not isinstance(task, dict):
            raise KitError(f"{where}: must be a mapping")
        if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
            raise KitError(f"{where}: `prompt` must be a non-empty string")
        if f"Task id: {task_id}" not in task["prompt"]:
            raise KitError(f"{where}: the prompt must name its task id (`Task id: {task_id}`)")
        skills = task.get("skills")
        if not isinstance(skills, list) or not skills or not all(isinstance(s, str) for s in skills):
            raise KitError(f"{where}: `skills` must be a non-empty list of skill names")
        acceptance = task.get("acceptance")
        if not isinstance(acceptance, list) or not all(isinstance(a, str) for a in acceptance):
            raise KitError(f"{where}: `acceptance` must be a list of strings")
        checks = task.get("checks")
        if not isinstance(checks, dict) or not isinstance(checks.get("render"), bool) \
                or not isinstance(checks.get("lint"), bool):
            raise KitError(f"{where}: `checks` needs boolean `render` and `lint`")
        behavior = checks.get("behavior")
        if behavior is not None and not (isinstance(behavior, dict) and isinstance(behavior.get("stub"), str)):
            raise KitError(f"{where}: `checks.behavior` is null or a mapping with a `stub` path")
    return tasks


def stub_path(task: dict) -> Path | None:
    """The task's behavior-check stub, or None when the behavior check does not apply."""
    behavior = task["checks"].get("behavior")
    return EVAL_DIR / behavior["stub"] if behavior else None
