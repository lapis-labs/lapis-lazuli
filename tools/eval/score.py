#!/usr/bin/env python3
"""Score the runs of an eval folder and write one JSON per run plus an arm-comparison summary.

    uv run --no-sync python tools/eval/score.py OUT [--run ID ...] [--rescore] [--summary-only]

For each run under OUT/runs: serve the produced site on a loopback port, run `lapis-design render
check` at the default widths, `lapis-design behavior check` for tasks that name a stub, and
`lapis-design slop lint` over the plan (only when the agent wrote `.lapis/plans/<task>.yaml`), the
source tree, the render extract, and the behavior session. Per checker the score records blocking and
total findings; a checker that could not run is `not scored` with the reason, never a zero. Copy
findings are the open `copy.*` findings of the render layer, reported per 1,000 words of the page
(the word count is the one the copy detectors use: whitespace-separated tokens holding a letter or
digit, over the viewport with the most text, `code` and `data` runs excluded).

Outputs, next to each run's run.json: `score.json` and `score/` (render extract and screenshots,
behavior session, lint report, checker logs). In OUT: `summary.csv` and `summary.md`. A run is
scored whatever its status, so a folder from `run.py --dry-run` can be filled by hand and scored.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import evalkit as kit
from evalkit import ARMS, KitError

LAYERS = ("plan", "source", "render", "behavior")
SITE_FOLDERS = ("", "public", "dist", "build", "out", "docs")
TIMEOUTS = {"render": 300, "behavior": 900, "lint": 300}
NUMERIC = (*(f"{layer}_{kind}" for layer in (*LAYERS, "lint") for kind in ("blocking", "open", "total")),
           "copy_findings", "copy_words", "copy_per_1000", "tokens", "duration_s")
NA = "—"


# ------------------------------------------------------------------ site, plan, server

def find_site_root(project: Path) -> Path | None:
    """The folder to serve: the project root, or the first conventional output folder with an index.html."""
    for name in SITE_FOLDERS:
        root = project / name if name else project
        if (root / "index.html").is_file():
            return root
    return None


def find_plan(project: Path, task: str) -> tuple[Path | None, list[str]]:
    """The plan `.lapis/plans/<task>.yaml` when the agent wrote it, and the names of any other plan files."""
    plans = project / ".lapis" / "plans"
    wanted = plans / f"{task}.yaml"
    others = sorted(p.name for p in plans.glob("*.y*ml") if p != wanted) if plans.is_dir() else []
    return (wanted if wanted.is_file() else None), others


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # the checkers' own output is the record
        pass


@contextlib.contextmanager
def serve(root: Path):
    """Serve a folder on a free loopback port for the length of the block; yields its URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


# ------------------------------------------------------------------ running checkers

@dataclass
class Ran:
    exit: int | None
    seconds: float
    stdout: str
    stderr: str
    timed_out: bool = False
    error: str | None = None

    def reason(self) -> str:
        if self.timed_out:
            return "timed out"
        if self.error:
            return self.error
        return kit.first_line(self.stderr) or kit.first_line(self.stdout) or f"exit {self.exit}"


def run_checker(argv: list[str], *, cwd: Path, env: dict, timeout: int, log: Path) -> Ran:
    """Run one checker command, keep its output in `log`, and never raise."""
    started = time.monotonic()
    try:
        done = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        ran = Ran(done.returncode, 0.0, done.stdout, done.stderr)
    except subprocess.TimeoutExpired as exc:
        text = lambda v: v.decode("utf-8", "replace") if isinstance(v, bytes) else (v or "")
        ran = Ran(None, 0.0, text(exc.stdout), text(exc.stderr), timed_out=True)
    except OSError as exc:
        ran = Ran(None, 0.0, "", "", error=f"{type(exc).__name__}: {exc}")
    ran.seconds = round(time.monotonic() - started, 1)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"$ {' '.join(argv)}\nexit: {ran.exit}{' (timed out)' if ran.timed_out else ''}\n"
                   f"--- stdout\n{ran.stdout}\n--- stderr\n{ran.stderr}\n", encoding="utf-8")
    return ran


def _cli(python: str, *args: str) -> list[str]:
    return [python, "-m", "lapis_design.cli", *args]


def _not_scored(code: str, reason: str, **extra) -> dict:
    return {"status": "not scored", "code": code, "reason": reason, **extra}


def render_step(ctx: dict, url: str, plan: Path | None) -> dict:
    """`render check`; retried without the plan when the plan itself stops the capture."""
    out = ctx["score_dir"] / "render.json"
    ignored = None
    for use_plan in ([plan, None] if plan else [None]):
        argv = _cli(ctx["python"], "render", "check", url, "--task", ctx["task"], "--out", str(out))
        if use_plan:
            argv += ["--plan", str(use_plan)]
        ran = run_checker(argv, cwd=ctx["score_dir"], env=ctx["env"], timeout=ctx["timeouts"]["render"],
                          log=ctx["score_dir"] / "logs" / "render-check.txt")
        if ran.exit == 0 and out.is_file():
            extract = kit.read_json(out)
            result = {"status": "ok", "exit": 0, "seconds": ran.seconds, "extract": "score/render.json",
                      "viewports": len(extract.get("viewports") or [])}
            if ignored:
                result["plan_ignored"] = ignored
            return result
        ignored = ran.reason()
    return _not_scored("render check failed", ran.reason(), exit=ran.exit, seconds=ran.seconds)


def behavior_step(ctx: dict, url: str, plan: Path | None, extract: Path | None, stub: Path) -> dict:
    out = ctx["score_dir"] / "behavior.json"
    ignored = None
    for use_plan in ([plan, None] if plan else [None]):
        argv = _cli(ctx["python"], "behavior", "check", url, "--task", ctx["task"], "--stub", str(stub),
                    "--out", str(out))
        if use_plan:
            argv += ["--plan", str(use_plan)]
        if extract:
            argv += ["--extract", str(extract)]
        ran = run_checker(argv, cwd=ctx["score_dir"], env=ctx["env"], timeout=ctx["timeouts"]["behavior"],
                          log=ctx["score_dir"] / "logs" / "behavior-check.txt")
        if ran.exit == 0 and out.is_file():
            session = kit.read_json(out)
            result = {"status": "ok", "exit": 0, "seconds": ran.seconds, "session": "score/behavior.json",
                      "coverage": coverage_counts(session)}
            if ignored:
                result["plan_ignored"] = ignored
            return result
        ignored = ran.reason()
    return _not_scored("behavior check failed", ran.reason(), exit=ran.exit, seconds=ran.seconds)


def coverage_counts(session: dict) -> dict:
    """How many probes ran, ran partly, or were skipped, and the names of the skipped ones."""
    counts = Counter(entry.get("status") for entry in session.get("coverage") or [])
    return {"ran": counts.get("ran", 0), "partial": counts.get("partial", 0), "skipped": counts.get("skipped", 0),
            "skipped_probes": sorted(e["probe"] for e in session.get("coverage") or [] if e.get("status") == "skipped")}


def lint_step(ctx: dict, project: Path, plan: Path | None, extract: Path | None, session: Path | None) -> tuple[dict, dict | None]:
    """`slop lint` over every input available; retried without the plan when the plan is what it rejects.

    Returns the checker record and the report (None when lint could not run)."""
    out = ctx["score_dir"] / "lint.json"
    lock = project / ".lapis" / "fonts.lock.json"
    plan_problem = None
    for use_plan in ([plan, None] if plan else [None]):
        argv = _cli(ctx["python"], "slop", "lint", "--source", str(project), "-o", str(out))
        if use_plan:
            argv += ["--plan", str(use_plan)]
        if extract:
            argv += ["--extract", str(extract)]
        if session:
            argv += ["--session", str(session)]
        if lock.is_file():
            argv += ["--lock", str(lock)]
        ran = run_checker(argv, cwd=ctx["score_dir"], env=ctx["env"], timeout=ctx["timeouts"]["lint"],
                          log=ctx["score_dir"] / "logs" / "lint.txt")
        if ran.exit in (0, 1) and out.is_file():
            report = kit.read_json(out)
            record = {"status": "ok", "exit": ran.exit, "seconds": ran.seconds, "report": "score/lint.json",
                      "layers_ran": (report.get("scope") or {}).get("layers", [])}
            if plan_problem:
                record["plan_problem"] = plan_problem
            return record, report
        plan_problem = ran.reason()
    return _not_scored("lint failed", ran.reason(), exit=ran.exit, seconds=ran.seconds), None


# ------------------------------------------------------------------ parsing reports

def rendered_words(extract: dict) -> tuple[int, int | None]:
    """Words on the page as the copy detectors count them, and the width of the viewport they came from."""
    viewports = extract.get("viewports") or []
    if not viewports:
        return 0, None
    sizes = [sum(len(run.get("text") or "") for run in vp.get("text") or []) for vp in viewports]
    index = max(range(len(viewports)), key=lambda i: (sizes[i], viewports[i].get("width") or 0))
    words = 0
    for run in viewports[index].get("text") or []:
        text = run.get("text")
        if text and run.get("type_role") not in ("code", "data"):
            words += sum(1 for token in text.split() if any(c.isalnum() for c in token))
    return words, viewports[index].get("width")


def layer_stats(report: dict) -> dict[str, dict]:
    """Blocking, total, open, and skipped findings per layer of a lint report."""
    stats = {layer: Counter() for layer in (*LAYERS, "review")}
    for finding in report.get("findings") or []:
        counter = stats.setdefault(finding.get("layer"), Counter())
        counter["total"] += 1
        counter["blocking"] += bool(finding.get("blocking"))
        counter[finding.get("status")] += 1
    return {layer: {"blocking": c["blocking"], "total": c["total"], "open": c["open"], "skipped": c["skipped"]}
            for layer, c in stats.items() if layer in LAYERS}


def copy_stats(report: dict | None, extract: dict | None) -> dict:
    """Open copy findings of the render layer per 1,000 rendered words."""
    if report is None or extract is None or "render" not in (report.get("scope") or {}).get("layers", []):
        return _not_scored("no render", "the render layer of the lint did not run")
    words, width = rendered_words(extract)
    if not words:
        return _not_scored("no copy", "the render extract holds no readable copy")
    hits = [f for f in report.get("findings") or []
            if f.get("layer") == "render" and str(f.get("rule_id", "")).startswith("copy.") and f.get("status") == "open"]
    plan_hits = sum(1 for f in report.get("findings") or []
                    if f.get("layer") == "plan" and str(f.get("rule_id", "")).startswith("copy.")
                    and f.get("status") == "open")
    return {"status": "ok", "words": words, "viewport": width, "findings": len(hits),
            "blocking": sum(1 for f in hits if f.get("blocking")),
            "per_1000_words": round(len(hits) * 1000 / words, 2),
            "rules": dict(sorted(Counter(f["rule_id"] for f in hits).items())), "plan_findings": plan_hits}


def layers_record(report: dict | None, lint: dict, *, plan: Path | None, behavior_applicable: bool,
                  behavior: dict | None, render: dict) -> dict:
    """Per-layer lint results, with the reason each layer that did not run was not scored."""
    reasons = {
        "plan": _not_scored("no plan", "the agent wrote no .lapis/plans/<task>.yaml") if plan is None else
                _not_scored("plan rejected", lint.get("plan_problem") or "lint could not use the plan"),
        "source": _not_scored("lint failed", lint.get("reason", "lint did not run")),
        "render": _not_scored("no render", render.get("reason", "render check did not run")),
        "behavior": _not_scored("n/a", "the task has no behavior check") if not behavior_applicable else
                    _not_scored("no behavior", (behavior or {}).get("reason", "behavior check did not run")),
    }
    if report is None:
        failed = _not_scored(lint["code"], lint["reason"])
        inherent = {"plan": plan is None, "behavior": not behavior_applicable}
        return {layer: reasons[layer] if inherent.get(layer) else failed for layer in LAYERS}
    stats = layer_stats(report)
    ran = set((report.get("scope") or {}).get("layers", []))
    return {layer: ({"status": "ok", **stats[layer]} if layer in ran else reasons[layer]) for layer in LAYERS}


# ------------------------------------------------------------------ scoring one run

def score_run(run_dir: Path, tasks: dict, *, python: str = sys.executable, timeouts: dict | None = None,
              sig_key: Path | None = None) -> dict:
    """Run every checker the task names against one run's project; write and return score.json."""
    run = kit.read_json(run_dir / "run.json")
    task = tasks[run["task"]]
    project = run_dir / run["project"]
    score_dir = run_dir / "score"
    if score_dir.exists():
        shutil.rmtree(score_dir)
    score_dir.mkdir(parents=True)
    env = dict(os.environ)
    env["LAPIS_SIG_KEY_FILE"] = str(sig_key or run_dir.parent.parent / ".sig.key")
    ctx = {"python": python, "env": env, "score_dir": score_dir, "task": run["task"],
           "timeouts": {**TIMEOUTS, **(timeouts or {})}}
    plan, other_plans = find_plan(project, run["task"])
    root = find_site_root(project)
    result: dict = {
        "version": kit.RECORD_VERSION, "run": run["id"], "task": run["task"], "arm": run["arm"],
        "replicate": run["replicate"], "scored_at": kit.utc_now(), "run_status": run.get("status"),
        "plan": {"status": "found" if plan else "no plan", "path": ".lapis/plans/" + plan.name if plan else None,
                 "other_plans": other_plans},
        "site": {"root": root.relative_to(run_dir).as_posix() if root else None},
        "checkers": {},
    }
    with contextlib.ExitStack() as stack:
        url = stack.enter_context(serve(root)) if root else None
        if task["checks"]["render"]:
            render = render_step(ctx, url, plan) if url else _not_scored("no site", "the project has no index.html")
        else:
            render = _not_scored("n/a", "the task has no render check")
        behavior_stub = kit.stub_path(task)
        if behavior_stub:
            behavior = behavior_step(ctx, url, plan, score_dir / "render.json" if render["status"] == "ok" else None,
                                     behavior_stub) if url else _not_scored("no site", "the project has no index.html")
        else:
            behavior = _not_scored("n/a", "the task has no behavior check")
    result["checkers"]["render_check"] = render
    result["checkers"]["behavior_check"] = behavior
    report = None
    if not task["checks"]["lint"]:
        lint = _not_scored("n/a", "the task has no lint")
    elif root is None:      # an empty project would read as zero findings, which is not a result
        lint = _not_scored("no site", "the project has no index.html, so nothing was built to lint")
    else:
        lint, report = lint_step(ctx, project, plan, score_dir / "render.json" if render["status"] == "ok" else None,
                                 score_dir / "behavior.json" if behavior["status"] == "ok" else None)
    lint["layers"] = layers_record(report, lint, plan=plan, behavior_applicable=behavior_stub is not None,
                                   behavior=behavior, render=render)
    if report is not None:
        lint["summary"] = {"blocking": (report.get("summary") or {}).get("blocking", 0),
                           "total": (report.get("summary") or {}).get("total", 0)}
        if report.get("analyzers"):
            lint["analyzers"] = report["analyzers"]
    result["checkers"]["lint"] = lint
    extract = kit.read_json(score_dir / "render.json") if render["status"] == "ok" else None
    result["copy"] = copy_stats(report, extract)
    kit.write_json(run_dir / "score.json", result)
    return result


# ------------------------------------------------------------------ rows, aggregation, tables

def cell_number(value) -> float | int | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def row_from(run: dict, score: dict | None) -> dict:
    """One flat row per run: identity, session facts, and the numbers or reasons of each checker."""
    usage = run.get("usage") or {}
    row: dict = {"id": run["id"], "task": run["task"], "arm": run["arm"], "replicate": run["replicate"],
                 "run_status": run.get("status"), "exit_code": run.get("exit_code"),
                 "duration_s": run.get("duration_s"),
                 "tokens": (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)) if usage else None,
                 "skills_read": ",".join((run.get("session") or {}).get("skills_read") or []),
                 "scored": score is not None}
    for layer in LAYERS:
        row.update({f"{layer}_status": NA, f"{layer}_blocking": None, f"{layer}_open": None, f"{layer}_total": None})
    row.update(render_check=NA, behavior_check=NA, lint_blocking=None, lint_open=None, lint_total=None,
               copy_status=NA, copy_words=None, copy_findings=None, copy_per_1000=None)
    if score is None:
        return row
    checkers = score["checkers"]
    row["render_check"] = "ok" if checkers["render_check"]["status"] == "ok" else checkers["render_check"]["code"]
    row["behavior_check"] = "ok" if checkers["behavior_check"]["status"] == "ok" else checkers["behavior_check"]["code"]
    layers = checkers["lint"].get("layers") or {}
    scored = [layers[layer] for layer in LAYERS if layers.get(layer, {}).get("status") == "ok"]
    for layer in LAYERS:
        entry = layers.get(layer) or {}
        if entry.get("status") == "ok":
            row.update({f"{layer}_status": "ok", f"{layer}_blocking": entry["blocking"],
                        f"{layer}_open": entry["open"], f"{layer}_total": entry["total"]})
        else:
            row[f"{layer}_status"] = entry.get("code", NA)
    if scored:
        for kind in ("blocking", "open", "total"):
            row[f"lint_{kind}"] = sum(e[kind] for e in scored)
    copy = score["copy"]
    row["copy_status"] = "ok" if copy["status"] == "ok" else copy["code"]
    if copy["status"] == "ok":
        row.update(copy_words=copy["words"], copy_findings=copy["findings"], copy_per_1000=copy["per_1000_words"])
    return row


def mean(values: list) -> float | None:
    values = [v for v in (cell_number(x) for x in values) if v is not None]
    return round(sum(values) / len(values), 2) if values else None


def aggregate(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """Per task and arm: run count and, per numeric column, the mean over the runs that scored it."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["task"], row["arm"])].append(row)
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for (task, arm), members in groups.items():
        entry = {"runs": len(members), "render_ok": sum(1 for m in members if m["render_check"] == "ok"),
                 "mean": {}, "n": {}}
        for column in NUMERIC:
            values = [m[column] for m in members if cell_number(m[column]) is not None]
            entry["mean"][column] = mean(values)
            entry["n"][column] = len(values)
        out[task][arm] = entry
    return out


def delta(agg_task: dict[str, dict]) -> dict[str, float | None]:
    """with minus without, per numeric column, where both arms have a mean."""
    if not all(arm in agg_task for arm in ARMS):
        return {}
    out = {}
    for column in NUMERIC:
        a, b = agg_task["with"]["mean"][column], agg_task["without"]["mean"][column]
        out[column] = round(a - b, 2) if a is not None and b is not None else None
    return out


def fmt(value) -> str:
    if value is None:
        return NA
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def pair(row: dict, layer: str) -> str:
    """`blocking/total (open)` of a layer, or why it was not scored."""
    if row[f"{layer}_status"] == "ok":
        return f"{row[f'{layer}_blocking']}/{row[f'{layer}_total']} ({row[f'{layer}_open']} open)"
    return row[f"{layer}_status"]


def mean_cell(entry: dict, layer: str) -> str:
    """Mean `blocking/total (open)` of a layer over the runs that scored it, and how many did."""
    mean_of = entry["mean"]
    if mean_of[f"{layer}_blocking"] is None:
        return NA
    return (f"{fmt(mean_of[f'{layer}_blocking'])}/{fmt(mean_of[f'{layer}_total'])} "
            f"({fmt(mean_of[f'{layer}_open'])} open), n={entry['n'][f'{layer}_blocking']}")


def delta_cell(change: dict, layer: str) -> str:
    if change[f"{layer}_blocking"] is None:
        return NA
    return (f"{fmt(change[f'{layer}_blocking'])}/{fmt(change[f'{layer}_total'])} "
            f"({fmt(change[f'{layer}_open'])} open)")


def copy_cell(row: dict) -> str:
    if row["copy_status"] != "ok":
        return row["copy_status"]
    return f"{fmt(row['copy_per_1000'])} ({row['copy_findings']} in {row['copy_words']} w)"


def markdown(manifest: dict | None, rows: list[dict], agg: dict) -> str:
    lines = ["# Skill evaluation summary", ""]
    if manifest:
        lines += [f"- Model: `{manifest.get('model')}`, effort: `{manifest.get('effort') or 'model default'}`, "
                  f"sandbox: `{manifest.get('sandbox')}`",
                  f"- Harness: {manifest.get('codex', {}).get('version')}; repository commit "
                  f"`{(manifest.get('repo') or {}).get('commit', '')[:10]}`"
                  f"{' (sources changed since)' if (manifest.get('repo') or {}).get('dirty_sources') else ''}; "
                  f"{manifest.get('lapis_design')}",
                  f"- Seed {manifest.get('seed')}, created {manifest.get('created_at')}"
                  f"{'; **dry run: no model was started**' if manifest.get('dry_run') else ''}"]
    lines += ["- Layer cells read `blocking/total (open)` lint findings: `total` also counts findings a rule could not "
              "judge (skipped), `open` only the judged ones. `—` is not applicable; other words say why a checker "
              "did not score (`no plan`, `n/a`, `render check failed`, ...). Means use scored runs only.", ""]
    for task in sorted({r["task"] for r in rows}):
        lines += [f"## {task}", "",
                  "| run | arm | status | render | plan | source | render layer | behavior | copy /1,000 w | all layers | tokens | skills read |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for row in sorted((r for r in rows if r["task"] == task), key=lambda r: (r["replicate"], r["arm"])):
            lint = (f"{row['lint_blocking']}/{row['lint_total']} ({row['lint_open']} open)"
                    if row["lint_total"] is not None else NA)
            behavior = pair(row, "behavior")
            lines.append(f"| {row['id']} | {row['arm']} | {row['run_status']} | {row['render_check']} | "
                         f"{pair(row, 'plan')} | {pair(row, 'source')} | {pair(row, 'render')} | {behavior} | "
                         f"{copy_cell(row)} | {lint} | {fmt(row['tokens'])} | {row['skills_read'] or NA} |")
        lines += ["", f"Arm means for {task} (n = runs that scored the layer):", "",
                  "| arm | runs | render ok | plan | source | render layer | behavior | all layers | copy /1,000 w | words | tokens |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for arm in ARMS:
            entry = agg.get(task, {}).get(arm)
            if not entry:
                continue
            cells = [mean_cell(entry, layer) for layer in (*LAYERS, "lint")]
            cells += [f"{fmt(entry['mean'][c])} (n={entry['n'][c]})" for c in ("copy_per_1000", "copy_words", "tokens")]
            lines.append(f"| {arm} | {entry['runs']} | {entry['render_ok']} | " + " | ".join(cells) + " |")
        change = delta(agg.get(task, {}))
        if change:
            lines.append("| with − without | | | " + " | ".join(
                [delta_cell(change, layer) for layer in (*LAYERS, "lint")]
                + [fmt(change[c]) for c in ("copy_per_1000", "copy_words", "tokens")]) + " |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


CSV_COLUMNS = ["scope", "task", "arm", "run", "replicate", "run_status", "exit_code", "render_check",
               "plan_status", "source_status", "render_layer_status", "behavior_check", "behavior_layer_status",
               "copy_status", *NUMERIC, "skills_read"]


def csv_rows(rows: list[dict], agg: dict) -> list[dict]:
    out = []
    for row in sorted(rows, key=lambda r: (r["task"], r["replicate"], r["arm"])):
        out.append({"scope": "run", "task": row["task"], "arm": row["arm"], "run": row["id"],
                    "replicate": row["replicate"], "run_status": row["run_status"], "exit_code": row["exit_code"],
                    "render_check": row["render_check"], "plan_status": row["plan_status"],
                    "source_status": row["source_status"], "render_layer_status": row["render_status"],
                    "behavior_check": row["behavior_check"], "behavior_layer_status": row["behavior_status"],
                    "copy_status": row["copy_status"], "skills_read": row["skills_read"],
                    **{c: row[c] for c in NUMERIC}})
    for task in sorted(agg):
        for arm in ARMS:
            if arm in agg[task]:
                entry = agg[task][arm]
                out.append({"scope": "mean", "task": task, "arm": arm, "run": f"mean of {entry['runs']}",
                            **entry["mean"]})
        change = delta(agg[task])
        if change:
            out.append({"scope": "delta", "task": task, "arm": "with-without", "run": "with minus without", **change})
    return out


def write_summary(out: Path, rows: list[dict]) -> None:
    agg = aggregate(rows)
    manifest = kit.read_json(out / "manifest.json") if (out / "manifest.json").is_file() else None
    (out / "summary.md").write_text(markdown(manifest, rows, agg), encoding="utf-8")
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore", restval="")
        writer.writeheader()
        for row in csv_rows(rows, agg):
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


def collect_rows(out: Path) -> list[dict]:
    rows = []
    for run_dir in kit.list_runs(out):
        run = kit.read_json(run_dir / "run.json")
        score = kit.read_json(run_dir / "score.json") if (run_dir / "score.json").is_file() else None
        rows.append(row_from(run, score))
    return rows


# ------------------------------------------------------------------ command line

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="score.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("out", type=Path, help="the folder run.py wrote (holds manifest.json and runs/)")
    ap.add_argument("--run", action="append", default=[], help="score only this run id (repeatable)")
    ap.add_argument("--rescore", action="store_true", help="score runs that already have a score.json")
    ap.add_argument("--summary-only", action="store_true", help="rebuild summary.csv and summary.md, run no checker")
    for name, seconds in TIMEOUTS.items():
        ap.add_argument(f"--{name}-timeout", type=int, default=seconds, help=f"seconds for the {name} step")
    args = ap.parse_args(argv)
    try:
        tasks = kit.load_tasks()
        out = args.out.expanduser().resolve()
        runs = kit.list_runs(out)
        if not runs:
            raise KitError(f"no runs under {out}/runs")
        wanted = set(args.run)
        unknown = wanted - {p.name for p in runs}
        if unknown:
            raise KitError(f"unknown run: {', '.join(sorted(unknown))}")
        if not args.summary_only:
            timeouts = {name: getattr(args, f"{name}_timeout") for name in TIMEOUTS}
            for run_dir in runs:
                if wanted and run_dir.name not in wanted:
                    continue
                if (run_dir / "score.json").is_file() and not args.rescore:
                    print(f"skip   {run_dir.name} (scored; --rescore to redo)")
                    continue
                print(f"score  {run_dir.name} ...", flush=True)
                result = score_run(run_dir, tasks, timeouts=timeouts, sig_key=out / ".sig.key")
                checkers = result["checkers"]
                print("  render {} | behavior {} | lint {} | copy {}".format(
                    checkers["render_check"]["status"], checkers["behavior_check"]["status"],
                    checkers["lint"]["status"], result["copy"].get("per_1000_words", result["copy"]["status"])))
        rows = collect_rows(out)
        write_summary(out, rows)
    except KitError as exc:
        print(f"score.py: {exc}", file=sys.stderr)
        return 2
    print(f"summary: {out / 'summary.md'}\n         {out / 'summary.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
