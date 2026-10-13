"""The long checks of a task: which run now, which were not run for the build the owner is shown, and the one wait that
reports each background run's end once, with one bounded summary.

  lapis-design checks status [--task T]            what runs now, and what has no result for the build shown
  lapis-design checks wait [--task T] [--timeout S]  wait for the checks that run now; print each one's end once

A render or behavior check that runs for minutes is one run per build and request (`check_cache`): the same check asked
again while it runs joins it and shares its result, so a second launch, or a second wait, never starts a second browser.
What runs now is read from the locks those runs hold (the check's own process, whoever started it) and from the process id
a background launch recorded in `.lapis/logs/<task>.<step>.pid`. The owner summary and `next` read it too, and say that
a running check is not finished; they never call it done. `wait` returns when the checks end or after `--timeout`
seconds, exit 0 when nothing runs and 3 when something still does, and prints the summary of a finished background run
once: a later `wait` names the report and does not print it again.

Stdlib and `check_cache` only until a command is asked for: the stop hook imports `next_step`, which imports this.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lapis_design import check_cache

JOB_MAX_AGE_S = 2 * 3600                           # a background run older than this is not assumed alive
LOG_CHARS = 3000                                   # the summary of a finished run, at most
KINDS = ("render", "behavior")
STILL_RUNNING = 3                                  # the exit code of `wait` that timed out with a check still running


def _pidfile(root: Path, task: str, step: str) -> Path:
    return root / ".lapis" / "logs" / f"{task}.{step}.pid"


def log_path(root: Path, task: str, step: str) -> Path:
    return root / ".lapis" / "logs" / f"{task}.{step}.log"


def _reported(root: Path, task: str, step: str) -> Path:
    return root / ".lapis" / "logs" / f"{task}.{step}.reported"


def _output(root: Path, task: str, step: str) -> Path:
    """The report the background run of `step` writes: its end is that report, or the failure record, newer than the pid."""
    return root / ".lapis" / ("behavior" if step == "behavior" else "renders") / f"{task}.json"


def job_running(root: Path, task: str, step: str = "behavior") -> bool:
    """Whether the background run of `step` that the step's command started is still going.

    The command writes `.lapis/logs/<task>.<step>.pid`. The run is over when its report or its failure
    record is newer than that file, when the process is gone or a zombie, or when the file is older than
    two hours, since a process id can be reused."""
    from lapis_design import attempts

    pidfile = _pidfile(root, task, step)
    try:
        started = pidfile.stat().st_mtime
        pid = int(pidfile.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if os.name == "nt" or pid <= 0 or time.time() - started > JOB_MAX_AGE_S:
        return False
    outputs = [_output(root, task, step), attempts.path(root, task, step)]
    if any(p.is_file() and p.stat().st_mtime >= started for p in outputs):
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    try:
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True,
                               timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return True
    return not state.startswith("Z")


# ---------------------------------------------------------------- what runs now

def _stems(root: Path, task: str) -> set[str]:
    """The report names that belong to `task`: its own, and the render task of each page of its draft record."""
    from lapis_design import slice_step

    return {task, *(p["render_task"] for p in slice_step.pages(root, task) if isinstance(p.get("render_task"), str))}


def _belongs(out: str, stems: set[str]) -> bool:
    return any(Path(out).name.startswith(f"{stem}.") for stem in stems)


def running(root: Path, task: str) -> list[dict[str, Any]]:
    """The render and behavior checks that run now for `task`, oldest first: `{kind, out, started, pid, build_id,
    source}`. A run holds a lock (`source: lock`); a background launch that holds none (the page is not one the cache
    identifies) is listed from its process id (`source: pidfile`)."""
    stems = _stems(root, task)
    found = [{**row, "source": "lock"} for row in check_cache.running(root)
             if row["kind"] in KINDS and _belongs(row["out"], stems)]
    for step in KINDS:
        if not any(row["kind"] == step for row in found) and job_running(root, task, step):
            pidfile = _pidfile(root, task, step)
            found.append({"kind": step, "out": _output(root, task, step).relative_to(root).as_posix(),
                          "started": pidfile.stat().st_mtime, "pid": int(pidfile.read_text(encoding="utf-8").strip()),
                          "build_id": None, "state_key": None, "source": "pidfile"})
    return sorted(found, key=lambda row: row["started"] or 0)


def running_report(root: Path, task: str, kind: str) -> dict[str, Any] | None:
    """The check of `kind` that writes the full report the gate reads (`.lapis/renders|behavior/<task>.json`), if it runs."""
    want = _output(root, task, kind).relative_to(root).as_posix()
    return next((row for row in running(root, task) if row["kind"] == kind and row["out"] == want), None)


def clock(epoch: float | None) -> str:
    return time.strftime("%H:%M:%S", time.localtime(epoch)) if epoch else "an unknown time"


def _minutes(epoch: float | None) -> str:
    seconds = max(0, int(time.time() - epoch)) if epoch else 0
    return f"{seconds // 60} min" if seconds >= 60 else f"{seconds} s"


# ---------------------------------------------------------------- the build shown

def unfinished(root: Path, task: str) -> dict[str, list[dict[str, Any]]]:
    """What a checkpoint must not call done: `running` (the checks that run now) and `not_run` (for each page of the draft
    record that this CLI serves, the render check of its widths, and the behavior check when its behavior changed or one ran
    for another build, that has no stored result for the build as it is now). A page the CLI does not serve has no identity, so
    nothing is said of its build. Both are empty when nothing is shown."""
    from lapis_design import slice_step

    ran = running(root, task)
    missing: list[dict[str, Any]] = []
    for page in slice_step.pages(root, task):
        try:
            served = check_cache.served(page["url"], root)
        except OSError:
            served = None
        if served is None:
            continue
        build = served.build_id
        widths = {w for w in page.get("widths") or () if isinstance(w, int)}
        extracts = {Path(e).name for e in ((page.get("review") or {}).get("extracts") or ()) if isinstance(e, str)} \
            if isinstance(page.get("review"), dict) else set()
        for kind in KINDS:
            if kind == "behavior" and not page.get("behavior_changed") and not _stored(root, kind, None):
                continue
            if not _stored(root, kind, build, extracts if kind == "render" else set(), widths if kind == "render" else set()):
                if not any(row["kind"] == kind and row["build_id"] in (None, build) for row in ran):
                    missing.append({"kind": kind, "url": page["url"], "build_id": build, "widths": sorted(widths)})
    return {"running": ran, "not_run": missing}


def _stored(root: Path, kind: str, build: str | None, names: set[str] = frozenset(), widths: set[int] = frozenset()) -> bool:
    """Whether the cache holds a result of `kind` for `build` (for any build when `build` is None) that covers `widths` and
    wrote one of the reports `names`, when those are given."""
    folder = root / check_cache.CACHE_DIR
    for entry in folder.glob(f"{kind}-*"):
        meta = check_cache._load_meta(entry)
        if not meta or (build is not None and meta.get("build_id") != build):
            continue
        if names and meta.get("out_name") not in names:
            continue
        if widths and not widths <= set((meta.get("selection") or {}).get("widths") or ()):
            continue
        return True
    return False


# ---------------------------------------------------------------- the commands

def _finished_unreported(root: Path, task: str) -> list[str]:
    """The background runs of `task` that ended since their pid was recorded and have not been reported by `wait`."""
    out = []
    for step in KINDS:
        pidfile = _pidfile(root, task, step)
        try:
            started = pidfile.stat().st_mtime
        except OSError:
            continue
        if time.time() - started > JOB_MAX_AGE_S or job_running(root, task, step):
            continue
        try:
            seen = _reported(root, task, step).read_text(encoding="utf-8").strip()
        except OSError:
            seen = ""
        if seen != repr(started):
            out.append(step)
    return out


def _report_finished(root: Path, task: str, step: str) -> list[str]:
    """One bounded summary of a finished background run: how long it took and what it printed, cut at `LOG_CHARS`, then
    marked reported so a second `wait` does not print it again."""
    pidfile = _pidfile(root, task, step)
    started = pidfile.stat().st_mtime
    report = _output(root, task, step)
    ended = report.stat().st_mtime if report.is_file() and report.stat().st_mtime >= started else None
    lines = [f"{step} check finished" + (f" after {_minutes_between(started, ended)}" if ended else
                                         ", and wrote no report (it failed or was stopped)")
             + f"; report {report.relative_to(root).as_posix()}"]
    try:
        text = log_path(root, task, step).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        text = ""
    if text:
        lines.append(text if len(text) <= LOG_CHARS else text[:LOG_CHARS].rstrip() +
                     f"\n... the log goes on in {log_path(root, task, step).relative_to(root).as_posix()}")
    try:
        _reported(root, task, step).write_text(repr(started), encoding="utf-8")
    except OSError:
        pass
    return lines


def _minutes_between(start: float, end: float) -> str:
    seconds = max(0, int(end - start))
    return f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s"


def _task(root: Path, task: str | None) -> str | None:
    from lapis_design.next_step import resolve_task

    return resolve_task(root, task)


def main(argv: list[str] | None = None, prog: str = "lapis-design checks wait") -> int:
    verb = prog.split()[-1]
    ap = argparse.ArgumentParser(prog=prog, allow_abbrev=False, description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--task", help="the plan's task id (default: $LAPIS_TASK, else the newest plan under --root)")
    ap.add_argument("--root", type=Path, default=Path("."), help="the project folder (default: .)")
    if verb == "wait":
        ap.add_argument("--timeout", type=float, default=55.0,
                        help="seconds to wait at most (default 55, under a tool call's usual limit); exit 3 when a check still runs")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    task = _task(root, args.task)
    if task is None:
        print(f"{prog}: no task: give --task, or run it where a plan is under .lapis/plans/", file=sys.stderr)
        return 2
    started = time.time()
    out: list[str] = []
    code = 0
    if verb == "status":
        state = unfinished(root, task)
        out += status_lines(state)
    else:
        deadline = time.monotonic() + max(args.timeout, 0.0)
        seen = running(root, task)
        while seen and time.monotonic() < deadline:
            time.sleep(min(1.0, max(deadline - time.monotonic(), 0.0)))
            seen = running(root, task)
        if seen:
            out += [f"not finished: {_describe(row)}" for row in seen]
            out.append(f"waited {int(time.time() - started)} s. Run `lapis-design checks wait --task {task}` again to keep waiting: "
                       "asking for the same check while it runs joins it, so launch nothing else.")
            code = STILL_RUNNING
        else:
            done = _finished_unreported(root, task)
            for step in done:
                out += _report_finished(root, task, step)
            if not done:
                out.append(f"no check runs for {task}" + (f" (waited {int(time.time() - started)} s)" if time.time() - started >= 1 else "")
                           + f"; `lapis-design next --task {task}` says what comes next.")
    text = "\n".join(out) + "\n"
    sys.stdout.write(text)
    try:
        from lapis_design import telemetry

        telemetry.record(root, command=prog.removeprefix("lapis-design "), task=task, scope=None, cache=None,
                         started=telemetry.stamp(datetime.fromtimestamp(started, timezone.utc)),
                         ended=telemetry.stamp(), exit=code, output_chars=len(text), report_path=None,
                         waited_seconds=round(time.time() - started, 1))
    except Exception:         # measurement never changes a result
        pass
    return code


def _describe(row: dict[str, Any]) -> str:
    return f"{row['kind']} check, started {clock(row['started'])} ({_minutes(row['started'])} ago), pid {row['pid']}, report {row['out']}"


def disclosure_lines(state: dict[str, list[dict[str, Any]]]) -> list[str]:
    """The checks that have not finished, one line each, and none when every check has: a run that goes on, and a check
    with no result for the build shown."""
    lines = [f"{_describe(row)}: running, not finished" for row in state["running"]]
    lines += [f"{row['kind']} check of {row['url']} (build {row['build_id']}"
              + (f", widths {', '.join(map(str, row['widths']))}" if row["widths"] else "")
              + "): no result for this build, not run" for row in state["not_run"]]
    return lines


def status_lines(state: dict[str, list[dict[str, Any]]]) -> list[str]:
    return disclosure_lines(state) or ["no check runs, and none lacks a result for the build shown."]


if __name__ == "__main__":
    sys.exit(main())
