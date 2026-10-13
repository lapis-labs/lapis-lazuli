"""The printed result of render, behavior, and lint checks, kept to a few KB: a path and a summary, not the report.

An agent reads everything a check prints again on every later turn, so the raw extract, session, and report stay in
their files (`--json` and `-o` still give them whole) and the screen gets, in a stable order:

  the verdict and the counts, the scope (full, or narrowed and how), what is new, changed, or gone since the report
  the same command wrote last, every blocker, what was skipped or only partly run, the limits, the build and state
  keys with the cache outcome, and the report path.

Nothing is dropped to make it shorter. A blocker stays listed by rule with its exact count and its finding ids when
there are too many to describe one by one, a skipped or partial probe stays named with its reason, and a check that
reused a stored result says so and says which.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from lapis_design.summary import clip, finding_lines, place

BLOCKER_BUDGET = 3000            # characters of blocker detail before rows give way to ids
DETAIL_ROWS = 2                  # rows kept per rule once the budget is spent
ID_CAP = 10                      # ids listed per rule once rows are dropped; the count stays exact
ROW_CAP = 130                    # characters of one row's text once the budget is spent
FIX_CAP = 160                    # characters of a rule's fix once the budget is spent
CHANGE_CAP = 12                  # new or changed findings described one by one
REASON_CAP = 200
SHORT_REASON_CAP = 100
REASON_BUDGET = 2500


@dataclass
class RunInfo:
    """How a check ran, for the state line and the telemetry."""
    command: str
    scope: str = "full"              # full | narrow
    scope_note: str | None = None    # what narrowed it, in words
    cache: str = "off"               # hit | join | miss | off
    reason: str | None = None
    build_id: str | None = None
    state_key: str | None = None
    run_seconds: float | None = None
    created: str | None = None
    wall_seconds: float | None = None
    waited: float = 0.0


def _seconds(value: float | None) -> str:
    return "?" if value is None else f"{value:.1f} s"


def state_line(info: RunInfo) -> str:
    """`  build … · state … · cache …`: which build the result describes and whether the browser or the lint ran."""
    keys = []
    if info.build_id:
        keys.append(f"build {info.build_id}")
    if info.state_key:
        keys.append(f"state {info.state_key[:12]}")
    took = f"; that run took {_seconds(info.run_seconds)}" if info.run_seconds is not None else ""
    if info.cache == "hit":
        cache = (f"cache hit: shown again from the stored result"
                 + (f" of {info.created}" if info.created else "")
                 + f" for these same inputs, not rerun (this call {_seconds(info.wall_seconds)}{took}); --fresh runs it again")
    elif info.cache == "join":
        cache = (f"cache join: waited {_seconds(info.waited)} for the identical run in progress and shared its result"
                 + (f" (that run took {_seconds(info.run_seconds)})" if info.run_seconds is not None else ""))
    elif info.cache == "miss":
        cache = f"cache miss: ran {_seconds(info.run_seconds)} and stored the result"
    else:
        cache = f"cache off: {info.reason or 'no build identity'}" + (
            f"; ran {_seconds(info.run_seconds)}" if info.run_seconds is not None else "")
    return "  " + " · ".join([*keys, cache])


def scope_line(info: RunInfo) -> str:
    if info.scope == "full":
        return "  scope: full"
    return f"  scope: NARROW — {info.scope_note or 'not every state'}; the release gate needs a full run on the final build"


# ---------------------------------------------------------------- findings

def _location(finding: dict) -> str:
    where = finding.get("location") or {}
    return json.dumps(where, sort_keys=True, ensure_ascii=False)


def finding_id(finding: dict) -> str:
    """A short stable id of a finding: the same rule, place, and observed text give the same id in any report."""
    text = json.dumps([finding.get("rule_id"), _location(finding), finding.get("observed")], ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _locus(finding: dict) -> tuple[str, str]:
    return str(finding.get("rule_id")), _location(finding)


def _state(finding: dict) -> tuple:
    return (finding.get("blocking"), finding.get("status"), (finding.get("severity") or {}).get("create"))


def _sort_key(finding: dict) -> tuple:
    return (str(finding.get("rule_id")), _location(finding), str(finding.get("observed")))


def delta(previous: list[dict] | None, current: list[dict]) -> dict | None:
    """What changed between two lists of findings, None without a previous list. A finding is `new` when neither its
    id nor its rule and place were there, `changed` when its place was but its text, severity, or status differ, and
    `gone` when its place no longer has a finding."""
    if previous is None:
        return None
    before_ids = {finding_id(f): f for f in previous}
    before_loci: dict[tuple, list[dict]] = {}
    for f in previous:
        before_loci.setdefault(_locus(f), []).append(f)
    now_loci = {_locus(f) for f in current}
    new, changed, same = [], [], 0
    for f in sorted(current, key=_sort_key):
        old = before_ids.get(finding_id(f))
        if old is not None:
            if _state(old) != _state(f):
                changed.append(f)
            else:
                same += 1
        elif _locus(f) in before_loci:
            changed.append(f)
        else:
            new.append(f)
    gone = [f for f in sorted(previous, key=_sort_key) if _locus(f) not in now_loci]
    return {"new": new, "changed": changed, "gone": gone, "unchanged": same}


def delta_lines(change: dict | None, previous_path: str | None) -> list[str]:
    if change is None:
        return ["  since the previous report: none at this path to compare"]
    new, changed, gone = change["new"], change["changed"], change["gone"]
    head = (f"  since the previous report ({previous_path}): {len(new)} new, {len(changed)} changed, "
            f"{len(gone)} gone, {change['unchanged']} unchanged")
    if not (new or changed or gone):
        return [head]
    lines = [head]
    rows = [("new", f) for f in new] + [("changed", f) for f in changed]
    for label, f in rows[:CHANGE_CAP]:
        mark = "BLOCK" if f.get("blocking") else str((f.get("severity") or {}).get("create", "open")).upper()
        where = place(f)
        lines.append(f"    {label} {finding_id(f)} [{mark}] {f['rule_id']}" + (f" {where}" if where else ""))
    if len(rows) > CHANGE_CAP:
        rest = rows[CHANGE_CAP:]
        lines.append(f"    …and {len(rest)} more new or changed; ids: " + " ".join(finding_id(f) for _, f in rest[:ID_CAP])
                     + (f" (+{len(rest) - ID_CAP} more in the report)" if len(rest) > ID_CAP else ""))
    if gone:
        lines.append("    gone: " + " ".join(f"{finding_id(f)}" for f in gone[:ID_CAP])
                     + (f" (+{len(gone) - ID_CAP} more)" if len(gone) > ID_CAP else ""))
    return lines


def _row(finding: dict, here: str | None) -> str:
    where = place(finding, here)
    text = clip(finding["observed"], ROW_CAP)
    return f"{finding_id(finding)} " + (text if not where or text.startswith(where) else f"{where} — {text}")


def severity_line(findings: Iterable[dict]) -> str | None:
    """`  judged by severity: BLOCK 2, WARN 5, INFO 1 (open 6, waived 2)`: the findings a check judged, not the skipped
    ones (those are not defects and have their own lines). None when every judged finding blocks: the verdict line
    already counts them."""
    items = [f for f in findings if f["status"] != "skipped"]
    marks = Counter("BLOCK" if f["blocking"] else str((f.get("severity") or {}).get("create", "open")).upper()
                    for f in items)
    states = Counter(f["status"] for f in items)
    if set(marks) <= {"BLOCK"}:
        return None
    return ("  judged by severity: " + ", ".join(f"{name} {marks[name]}" for name in sorted(marks, key=_mark_order))
            + " (" + ", ".join(f"{name} {states[name]}" for name in ("open", "waived", "fixed") if states[name]) + ")")


def _mark_order(name: str) -> int:
    return {"BLOCK": 0, "GATE": 1, "WARN": 2, "INFO": 3}.get(name, 4)


def blocker_lines(blocking: list[dict], here: str | None = None) -> list[str]:
    """Every blocking finding, grouped by rule: whole while they fit `BLOCKER_BUDGET`, then each rule keeps its exact
    count, its fix once, `DETAIL_ROWS` rows (one row when that is still too long), and the ids of the rest."""
    whole = finding_lines(blocking, here=here)
    if sum(len(line) + 1 for line in whole) <= BLOCKER_BUDGET:
        return whole
    groups: dict[str, list[dict]] = {}
    for f in sorted(blocking, key=_sort_key):
        groups.setdefault(f["rule_id"], []).append(f)
    lines: list[str] = []
    for rows_kept in (DETAIL_ROWS, 1):
        lines = []
        for rule, items in groups.items():
            rows = [_row(f, here) for f in items[:rows_kept]]
            lines.append(f"  [BLOCK] {rule} ×{len(items)}")
            fixes = {clip(f["fix"], FIX_CAP) for f in items if f.get("fix")}
            if len(fixes) == 1:
                lines.append(f"      fix: {next(iter(fixes))}")
            lines += [f"      {row}" for row in rows]
            rest = items[rows_kept:]
            if rest:
                lines.append(f"      {len(rest)} more, ids: " + " ".join(finding_id(f) for f in rest[:ID_CAP])
                             + (f" (+{len(rest) - ID_CAP} more in the report)" if len(rest) > ID_CAP else ""))
        if sum(len(line) + 1 for line in lines) <= 1.5 * BLOCKER_BUDGET:
            break
    return lines


# ---------------------------------------------------------------- render and behavior

def _viewport_key(viewport: dict) -> str:
    flags = [name for name, on in (("reduced", viewport.get("reduced_motion")), ("chrome", viewport.get("browser_chrome")))
             if on]
    return " ".join([str(viewport.get("width")), str(viewport.get("theme", "light")), *flags])


def render_lines(extract: dict, out: Path, info: RunInfo, previous: dict | None) -> list[str]:
    """The printed result of `render check`: what was captured, against the previous extract at the same path."""
    views = extract.get("viewports") or []
    boxes = sum(len(v.get("boxes") or []) for v in views)
    runs = sum(len(v.get("text") or []) for v in views)
    widths = sorted({v.get("width") for v in views})
    lines = [f"render check: captured {len(views)} viewports ({', '.join(map(str, widths))} px), {boxes} boxes, "
             f"{runs} runs -> {out}", scope_line(info), state_line(info)]
    if previous is None:
        lines.append("  since the previous extract: none to compare")
    else:
        before = {_viewport_key(v): v for v in previous.get("viewports") or []}
        notes = []
        for view in views:
            key = _viewport_key(view)
            old = before.get(key)
            if old is None:
                notes.append(f"{key}: new capture")
                continue
            old_ids = {b["id"] for b in old.get("boxes") or [] if "id" in b}
            new_ids = {b["id"] for b in view.get("boxes") or [] if "id" in b}
            old_runs, new_runs = len(old.get("text") or []), len(view.get("text") or [])
            old_boxes, new_boxes = len(old.get("boxes") or []), len(view.get("boxes") or [])
            if old_ids != new_ids or old_runs != new_runs or old_boxes != new_boxes:
                notes.append(f"{key}: boxes {old_boxes}→{new_boxes} (+{len(new_ids - old_ids)} −{len(old_ids - new_ids)} "
                             f"by id), runs {old_runs}→{new_runs}")
        missing = sorted(set(before) - {_viewport_key(v) for v in views})
        lines.append("  since the previous extract: " + ("no change in boxes or runs" if not notes else "; ".join(notes)))
        if missing and info.scope == "narrow":
            lines.append(f"  not captured this run (previous extract has them): {', '.join(missing)}")
    lines.append("  render check judges nothing: run `slop lint` on this extract for findings")
    return lines


def coverage_lines(coverage: list[dict]) -> list[str]:
    """What the probes did, so a run's partial and skipped probes are read without opening the session: the count per
    status, then a line for each status and reason with the probes it names. A probe that found nothing to exercise
    (`not-applicable`) is only counted. Reasons are clipped to `REASON_CAP`, or to `SHORT_REASON_CAP` when they would
    take more than `REASON_BUDGET` characters; every probe stays named."""
    counts = Counter(entry["status"] for entry in coverage)
    lines = ["  coverage: " + ", ".join(f"{counts[status]} {status}" for status in
                                         ("ran", "partial", "skipped", "not-applicable") if counts[status])]
    reasons: dict[tuple[str, str], list[str]] = {}
    for entry in coverage:
        if entry["status"] in ("partial", "skipped"):
            reasons.setdefault((entry["status"], " ".join((entry.get("reason") or "").split())), []).append(entry["probe"])
    cap = REASON_CAP if sum(min(len(reason), REASON_CAP) + 20 for _, reason in reasons) <= REASON_BUDGET else SHORT_REASON_CAP
    for (status, reason), probes in reasons.items():
        lines.append(f"  {status} {', '.join(dict.fromkeys(probes))}" + (f" — {clip(reason, cap)}" if reason else ""))
    return lines


def behavior_lines(session: dict, out: Path, info: RunInfo, previous: dict | None) -> list[str]:
    """The printed result of `behavior check`: contexts, nodes, probe coverage with every partial or skipped probe and its
    reason, and what changed in coverage since the previous session at the same path."""
    coverage = session.get("coverage") or []
    lines = [f"behavior check: {len(session['contexts'])} contexts, {len(session['nodes'])} nodes, {len(coverage)} "
             f"coverage entries -> {out}", scope_line(info), state_line(info), *coverage_lines(coverage)]
    if previous is None:
        lines.append("  since the previous session: none to compare")
    else:
        old = {e["probe"]: e["status"] for e in previous.get("coverage") or []}
        moved = [f"{e['probe']} {old[e['probe']]}→{e['status']}" for e in coverage
                 if e["probe"] in old and old[e["probe"]] != e["status"]]
        nodes = len(session["nodes"]) - len(previous.get("nodes") or [])
        lines.append("  since the previous session: " + ("coverage unchanged" if not moved else "; ".join(moved))
                     + (f"; nodes {nodes:+d}" if nodes else ""))
    return lines


# ---------------------------------------------------------------- printing and telemetry

def emit(lines: list[str]) -> int:
    """Print `lines`; the number of characters printed, for the telemetry line."""
    text = "\n".join(lines)
    print(text)
    return len(text) + 1


def project_path(path: Path | None) -> str | None:
    """`path` relative to the working directory when it lies under it, else as given."""
    if path is None:
        return None
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def record_run(info: RunInfo, *, task: str | None, started, exit_code: int, output_chars: int,
               report_path: Path | None) -> None:
    """One line in `.lapis/telemetry/checks.jsonl` for a check that ran."""
    from lapis_design import telemetry

    telemetry.record(Path.cwd(), command=info.command, task=task, build_id=info.build_id, state_key=info.state_key,
                     scope=info.scope, cache=info.cache, started=telemetry.stamp(started), ended=telemetry.stamp(),
                     exit=exit_code, output_chars=output_chars, report_path=project_path(report_path),
                     cache_reason=info.reason, run_seconds=info.run_seconds)
