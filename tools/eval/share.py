#!/usr/bin/env python3
"""Export what is safe to share from an eval folder: numbers, settings, and hashes, nothing a user or an agent wrote.

    uv run --no-sync python tools/eval/share.py OUT DEST

Run records never go into the repository or a bundle: a run folder holds the agent's whole conversation
(`events.jsonl`), its project, and paths that name the user. This command is the one way results leave it.
It writes to DEST (a new or empty folder, outside the repository and outside OUT) only `manifest.json`,
`summary.md`, `summary.csv`, and per run `run.json`, `score.json`, `isolation.json`, `command.txt`, and
`prompt.txt`.

None of these files is copied or cleaned. Each is built again from an allow-list: the fields it may hold,
and for each field a type (a count or a number, a flag, one word of a short list, a hash, a timestamp, a short
token such as a model name, or the name of one of the kit's own skills). A field that is not on the list, or
whose value is not of its type, is left out wherever it sits, keys included, so a field a later version adds,
a note, or text an agent wrote never leaves by being overlooked. What the records say in words becomes a
`code` from `score.CODES` (or an isolation code), and lists of names (errors, other plan files, refused links,
skipped folders, the shared Codex files) become counts. The Codex executable, `thread_id`, and `pid` are not
exported. `command.txt` keeps only the lines `run.py` writes (the executable shown as `codex`). `prompt.txt`
becomes `Task id: <id>` when it is the kit's prompt for that task (compared by hash) and is left out
otherwise. The names of skills that are not the kit's own become `<other-skill>`. The two summaries are
built again from the exported records.

Nothing is written when a run's event log shows a call to an Adobe tool, when a `score.json` has no
`font_db` record (it was made with the operator's own font database; score it again with `--font-db`), or
when a token such as the model name holds the name of the account that ran the evaluation (exit 2).
"""
from __future__ import annotations

import argparse
import getpass
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import evalkit as kit
import score
from evalkit import KitError

SUMMARY_FILES = ("summary.md", "summary.csv")
LEFT_OUT = ("project trees, scratch homes, transcripts (events.jsonl), stderr logs, last messages, "
            "score/ reports, the review folder and its key, and every field and word the allow-list does not name")
OTHER_SKILL = "<other-skill>"
GENERIC_ACCOUNTS = frozenset({"root", "runner", "admin", "user", "ubuntu", "vscode", "node"})
_MIN_NAME = 3        # shorter account names are not looked for in tokens; as words they would match ordinary text

_TASK_ID = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_RUN_ID = re.compile(_TASK_ID + r"\.r[0-9]+\.(?:with|without)")
_TOKEN = r"[A-Za-z0-9][A-Za-z0-9._+:-]{0,63}"                 # a model name or an effort level
_VERSION = r"[A-Za-z0-9][A-Za-z0-9._+: -]{0,63}"              # "codex-cli 0.159.3"
_STAMP = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"
STATUSES = ("prepared", "running", "completed", "failed", "timed_out", "interrupted")
SITE_ROOTS = ("project", *(f"project/{name}" for name in score.SITE_FOLDERS if name))
# The sub-commands of the kit's two tools that `tools_run` counts. A command not listed here (a new one, or
# anything an agent typed after the tool's name) is counted under `other` until it is added.
COMMANDS = {
    "lapis-design": frozenset({"plan", "rights", "render", "behavior", "stub", "slop", "release", "hook", "mcp"}),
    "lazuli": frozenset({"local", "catalog", "doctor", "class", "lock", "search", "sources", "color", "read",
                         "ref", "setup"}),
}
_COMMAND = re.compile(r"(lapis-design|lazuli) ([a-z]+)(?: [a-z]+)?")
_ISOLATION_CODES = (
    (re.compile(r"probe failed"), "probe failed"),
    (re.compile(r"probe with overrides failed"), "probe with overrides failed"),
    (re.compile(r"\d+ skill entries in the prompt could not be read"), "skill entries unreadable"),
    (re.compile(r"skills not discovered in the project"), "skills not discovered"),
    (re.compile(r"skills still visible after switching off"), "outside skills visible"),
)
_COMMAND_HEADER = (
    re.compile(r"# run from the run folder; paths are relative to it"),
    re.compile(r"# environment: PATH, LANG, LC_\*, TERM from the operator; HOME=home TMPDIR=home/tmp "
               r"LAZULI_FONT_ROOTS=user=home/fonts CODEX_HOME=\(the operator's own, not recorded\)"
               r"(?: PATH=(?:\.\./)+bin:\$PATH)?"),
)
_COMMAND_LINES = tuple(re.compile(p) for p in (
    r"exec", r"--ignore-user-config", r"--ignore-rules", r"--skip-git-repo-check", r"--ephemeral", r"--json",
    r"--color never", r"--sandbox (?:workspace-write|danger-full-access)", r"-C project", rf"-m {_TOKEN}",
    r"-o last-message\.txt", r"-c features\.apps=false", rf"""-c 'model_reasoning_effort="{_TOKEN}"'""",
    r"-c sandbox_workspace_write\.network_access=true",
    r"-c 'skills\.config=\[\.\.\. \d+ paths switched off \.\.\.\]'", r"--add-dir home", r"-", r"< prompt\.txt"))

_DROP = object()        # what a type answers for a value that is not of it


# ------------------------------------------------------------------ types: value in, clean value or _DROP out

def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _DROP
    return _DROP if isinstance(value, float) and not math.isfinite(value) else value


def _integer(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else _DROP


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else _DROP


def _flag(value):
    return value if isinstance(value, bool) else _DROP


def _present(value):
    """Text that said something (a reason, an error) becomes `true`: that it was there is the figure."""
    return True if value else _DROP


def _length(value):
    return len(value) if isinstance(value, (list, dict)) else _DROP


def _text(regex: str):
    pattern = re.compile(regex)
    return lambda value: value if isinstance(value, str) and pattern.fullmatch(value) else _DROP


def _enum(*allowed: str, other=_DROP):
    words = frozenset(allowed)

    def check(value):
        if not isinstance(value, str):
            return _DROP
        return value if value in words else other
    return check


def _maybe(spec):
    return lambda value: None if value is None else spec(value)


def _list(item, limit: int = 1000):
    def check(value):
        if not isinstance(value, list):
            return _DROP
        return [got for got in map(item, value[:limit]) if got is not _DROP]
    return check


def _mapping(key, item, limit: int = 500):
    def check(value):
        if not isinstance(value, dict):
            return _DROP
        kept = {}
        for name, entry in list(value.items())[:limit]:
            clean_name, clean = key(name), item(entry)
            if clean_name is not _DROP and clean is not _DROP:
                kept[clean_name] = clean
        return dict(sorted(kept.items()))
    return check


def _record(fields: dict):
    """An object with these fields and no others. A field is `key: type`, or `key: (new key, type)` when the
    exported field has another name or meaning than the one in the run folder."""
    def check(value):
        if not isinstance(value, dict):
            return _DROP
        kept = {}
        for key, spec in fields.items():
            if key not in value:
                continue
            name, type_ = spec if isinstance(spec, tuple) else (key, spec)
            clean = type_(value[key])
            if clean is not _DROP:
                kept[name] = clean
        return kept
    return check


def _key(regex: str):
    pattern = re.compile(regex)
    return lambda name: name if isinstance(name, str) and pattern.fullmatch(name) else _DROP


def _tools_run(value):
    """`{"lapis-design plan check": 3, ...}` as counts per command of the kit (`lapis-design plan`); any other
    key, whatever it says, is added to `other`."""
    if not isinstance(value, dict):
        return _DROP
    totals: Counter = Counter()
    for name, times in value.items():
        times = _count(times)
        if times is _DROP:
            continue
        match = _COMMAND.fullmatch(name) if isinstance(name, str) else None
        known = match is not None and match.group(2) in COMMANDS[match.group(1)]
        totals[f"{match.group(1)} {match.group(2)}" if known else "other"] += times
    return dict(sorted(totals.items()))


def _isolation_code(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return _DROP
    return next((code for pattern, code in _ISOLATION_CODES if pattern.match(value)), "other")


def _name_guard(names: set[str]):
    words = [re.compile(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])", re.I) for n in sorted(names)]

    def check(text: str) -> str:
        if any(word.search(text) for word in words):
            raise KitError("a value holds the name of the account that ran the evaluation")
        return text
    return check


def _guarded(spec, guard):
    def check(value):
        clean = spec(value)
        if isinstance(clean, str):
            guard(clean)
        return clean
    return check


def _account_names() -> set[str]:
    names = {Path.home().name}
    try:
        names.add(getpass.getuser())
    except (OSError, KeyError, ImportError):
        pass
    return {n.casefold() for n in names if len(n) >= _MIN_NAME and n.casefold() not in GENERIC_ACCOUNTS}


# ------------------------------------------------------------------ what each exported file may hold

def _schemas(skills: frozenset[str], guard) -> dict:
    token = _guarded(_text(_TOKEN), guard)
    version = _guarded(_text(_VERSION), guard)
    sha256 = _text(r"[0-9a-f]{64}")
    stamp = _text(_STAMP)
    arm = _enum(*kit.ARMS)
    status = _enum(*STATUSES, other="other")
    sandbox = _enum("workspace-write", "danger-full-access", other="other")
    skill = lambda value: (value if value in skills else OTHER_SKILL) if isinstance(value, str) else _DROP
    skill_list = _list(skill)
    skill_name = lambda name: name if name in skills else _DROP
    task_id, run_id = _text(_TASK_ID), _text(_RUN_ID.pattern)
    code = _enum(*score.CODES, other="other")
    scored = _enum("ok", "not scored", other="other")
    checker = {"status": scored, "code": code, "exit": _maybe(_integer), "seconds": _num}
    layer = _record({"status": scored, "code": code, "blocking": _count, "total": _count, "open": _count,
                     "skipped": _count})
    isolation_fields = _record({
        "verified": _flag, "reason": ("code", _isolation_code), "expected": skill_list, "visible": skill_list,
        "visible_other": _count, "outside_before": _count, "disabled_count": _count, "agents_md_injected": _flag})

    def isolation(value):
        try:
            return isolation_fields(kit.public_isolation(value)) if isinstance(value, dict) else _DROP
        except (TypeError, ValueError, AttributeError):
            return _DROP

    return {
        "manifest.json": _record({
            "version": _count, "created_at": stamp, "dry_run": _flag, "seed": _integer, "model": token,
            "effort": _maybe(token), "sandbox": sandbox, "network": _flag, "timeout_s": _num,
            "codex": _record({"version": version}), "shared_codex_files": ("shared_codex_file_count", _length),
            "repo": _record({"commit": _text(r"[0-9a-f]{40}"), "dirty_sources": _flag}),
            "lapis_design": _maybe(version),
            "tasks": _mapping(_key(_TASK_ID), _record({"prompt_sha256": sha256, "skills": skill_list})),
            "tasks_file_sha256": sha256, "skill_digests": _mapping(skill_name, sha256),
            "order": _list(_record({"task": task_id, "replicate": _count, "arm": arm, "order": _count,
                                    "id": run_id})),
            "finished_at": _maybe(stamp), "resumed_at": stamp}),
        "run.json": _record({
            "version": _count, "id": run_id, "task": task_id, "arm": arm, "replicate": _count, "order": _count,
            "status": status, "skills": skill_list, "skill_digest": _maybe(sha256),
            "skill_digests": _mapping(skill_name, sha256), "prompt_sha256": sha256, "model": token,
            "effort": _maybe(token), "sandbox": sandbox, "network": _flag,
            "harness": _record({"name": _enum("codex"), "version": version}), "isolation": isolation,
            "started_at": _maybe(stamp), "ended_at": _maybe(stamp), "duration_s": _maybe(_num),
            "exit_code": _maybe(_integer), "timed_out": _flag,
            "usage": _maybe(_mapping(_key(r"[a-z][a-z0-9_]{0,39}"), _num)),
            "session": _record({"turns": _count, "commands": _count, "skills_read": skill_list,
                                "skills_not_read": skill_list, "tools_run": _tools_run,
                                "errors": ("error_count", _length)}),
            "output": _record({"files": _count, "bytes": _count, "has_index": _flag}),
            "last_message_chars": _count}),
        "score.json": _record({
            "version": _count, "run": run_id, "task": task_id, "arm": arm, "replicate": _count,
            "scored_at": stamp, "run_status": _maybe(status),
            "plan": _record({"status": _enum("found", "no plan", "outside", other="other"),
                             "other_plans": ("other_plan_count", _length)}),
            "lock": _record({"status": _enum("found", "no lock", "outside", other="other")}),
            "site": _record({"root": _maybe(_enum(*SITE_ROOTS)), "refused_links": ("refused_link_count", _length),
                             "skipped_roots": ("skipped_root_count", _length)}),
            "font_db": _record({"sha256": sha256, "faces": _count, "families": _count}),
            "checkers": _record({
                "render_check": _record({**checker, "viewports": _count, "plan_ignored": _present}),
                "behavior_check": _record({**checker, "plan_ignored": _present, "coverage": _record({
                    "ran": _count, "partial": _count, "skipped": _count,
                    "skipped_probes": _list(_text(r"[a-z][a-z0-9_-]{0,39}"))})}),
                "lint": _record({**checker, "layers_ran": _list(_enum(*score.LAYERS, "review")),
                                 "plan_problem": _present,
                                 "unread_links": _record({"source": _length, "corpus": _length}),
                                 "layers": _record({name: layer for name in score.LAYERS}),
                                 "summary": _record({"blocking": _count, "total": _count}),
                                 "analyzers": _mapping(_enum("ko", "ja", "zh"), version)})}),
            "copy": _record({
                "status": scored, "code": code, "words": _count, "viewport": _maybe(_count), "findings": _count,
                "blocking": _count, "per_1000_words": _num, "plan_findings": _count,
                "rules": _mapping(_key(r"[a-z][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+"), _count)})}),
        "isolation.json": isolation,
    }


def _kit_skills() -> frozenset[str]:
    """The skills this kit ships and tests: the ones a record may name."""
    names = {skill for task in kit.load_tasks().values() for skill in task["skills"]}
    dist = kit.REPO / "dist" / "skills"
    if dist.is_dir():
        names.update(p.name for p in dist.iterdir() if p.is_dir())
    return frozenset(names)


def _command_text(text: str, guard) -> str | None:
    """The lines of `command.txt` that `run.py` writes, and no other; the executable is shown as `codex`."""
    header, command = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if any(pattern.fullmatch(line) for pattern in _COMMAND_HEADER):
                header.append(line)
            continue
        line = line.removesuffix(" \\")
        if not command:
            command.append("codex")             # the first line is the executable, wherever it lives
        elif any(pattern.fullmatch(line) for pattern in _COMMAND_LINES):
            command.append(line)
    if len(command) < 2:
        return None
    return guard("\n".join(header) + ("\n" if header else "") + " \\\n  ".join(command) + "\n")


def _prompt_text(path: Path, task_id: str | None, tasks: dict) -> str | None:
    """`Task id: <id>` when `prompt.txt` is exactly the kit's prompt for that task, else None."""
    task = tasks.get(task_id)
    if task is None or kit.sha256_file(path) != kit.sha256_bytes(task["prompt"].encode("utf-8")):
        return None
    return f"Task id: {task_id}\n"


def _load(path: Path, relative: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KitError(f"{relative} cannot be read ({type(exc).__name__})") from exc


def _dump(document) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def export(out: Path, dest: Path, notes: list[str] | None = None) -> list[str]:
    """Write the shareable records of `out` to `dest`; returns the files written, relative to `dest`. `notes`
    collects what was left out of a run that is otherwise exported."""
    out = Path(out).expanduser().resolve()
    dest = kit.ensure_outside_repo(dest)
    if not (out / "manifest.json").is_file():
        raise KitError(f"{out} has no manifest.json; give the folder run.py wrote")
    if dest == out or out in dest.parents or dest in out.parents:
        raise KitError(f"{dest} and {out} must be separate folders")
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise KitError(f"{dest} is not empty; give a new folder")
    runs = kit.list_runs(out)
    kit.refuse_adobe_calls(runs, "export")
    kit.refuse_unpinned_scores(runs, "export")
    for run_dir in runs:
        if not _RUN_ID.fullmatch(run_dir.name):
            raise KitError(f"runs/{run_dir.name} is not a run folder this kit writes; nothing was exported")
    guard = _name_guard(_account_names())
    schemas = _schemas(_kit_skills(), guard)
    tasks = kit.load_tasks()
    written: dict[Path, str] = {}
    cleaned: dict[Path, object] = {}

    def build(relative: Path, source: Path, schema) -> dict:
        document = _load(source, relative)
        try:
            clean = schema(document)
        except KitError as exc:
            raise KitError(f"{relative}: {exc}") from exc
        if clean is _DROP:
            raise KitError(f"{relative} is not a JSON object")
        cleaned[relative] = clean
        written[relative] = _dump(clean)
        return clean

    try:
        build(Path("manifest.json"), out / "manifest.json", schemas["manifest.json"])
        for run_dir in runs:
            folder = Path("runs") / run_dir.name
            run = build(folder / "run.json", run_dir / "run.json", schemas["run.json"])
            for name in ("score.json", "isolation.json"):
                if (run_dir / name).is_file():
                    build(folder / name, run_dir / name, schemas[name])
            if (run_dir / "command.txt").is_file():
                text = (run_dir / "command.txt").read_text(encoding="utf-8", errors="replace")
                try:
                    command = _command_text(text, guard)
                except KitError as exc:
                    raise KitError(f"{folder / 'command.txt'}: {exc}") from exc
                if command:
                    written[folder / "command.txt"] = command
            if (run_dir / "prompt.txt").is_file():
                prompt = _prompt_text(run_dir / "prompt.txt", run.get("task"), tasks)
                if prompt:
                    written[folder / "prompt.txt"] = prompt
                elif notes is not None:
                    notes.append(f"{run_dir.name}: prompt.txt is not the kit's prompt for its task, so it is left out")
    except KitError as exc:
        raise KitError(f"{exc}; nothing was exported") from exc
    for relative, text in _summaries(out, runs, cleaned).items():
        written[relative] = text
    for relative, text in written.items():
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return sorted(p.as_posix() for p in written)


def _summaries(out: Path, runs: list[Path], cleaned: dict[Path, object]) -> dict[Path, str]:
    """The summaries that `out` holds, built again from the exported manifest, run, and score records."""
    wanted = [name for name in SUMMARY_FILES if (out / name).is_file()]
    if not wanted:
        return {}
    try:
        rows = [score.row_from(cleaned[Path("runs") / run_dir.name / "run.json"],
                               cleaned.get(Path("runs") / run_dir.name / "score.json")) for run_dir in runs]
        files = score.summary_files(cleaned.get(Path("manifest.json")), rows)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise KitError(f"the summaries cannot be built from the run records ({type(exc).__name__}: {exc}); "
                       "nothing was exported") from exc
    return {Path(name): files[name] for name in wanted}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="share.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("out", type=Path, help="the folder run.py wrote")
    ap.add_argument("dest", type=Path, help="a new or empty folder outside the repository and OUT")
    args = ap.parse_args(argv)
    notes: list[str] = []
    try:
        files = export(args.out, args.dest, notes)
    except KitError as exc:
        print(f"share.py: {exc}", file=sys.stderr)
        return 2
    print(f"{len(files)} files -> {args.dest.expanduser().resolve()}\nleft out: {LEFT_OUT}")
    for note in notes:
        print(f"note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
