"""The printed result of a check: a verdict line, every finding that blocks, and counts for the rest.

An agent re-reads everything a check prints on each later turn, so a check prints this summary and keeps
the full report in its file (or on stdout with `--json`). The summary leaves out no finding that blocks and
no notice that something was skipped or only partly run; it shortens only the length of one finding's text,
and the report path says where the rest is.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

OBSERVED_CAP = 200                      # characters of one finding's observed text (the report has all of it)
FIX_CAP = 240                           # the fix of all but three rules fits whole
REASON_CAP = 200
NOTICE_CAP = 110                        # the reason shared by findings that were not judged


def clip(text: object, limit: int) -> str:
    """One line of at most `limit` characters; a cut text ends in an ellipsis."""
    one = " ".join(str(text).split())
    return one if len(one) <= limit else one[:limit - 1].rstrip() + "…"


def skipped_note(summary: dict) -> str:
    """`, 21 skipped: not judged` for a summary with skipped findings, else nothing: a skipped finding
    was not judged and is never a defect."""
    return f", {summary['skipped']} skipped: not judged" if summary.get("skipped") else ""


def place(finding: dict, here: str | None = None) -> str:
    """Where a finding is, as the words a narrowed rerun needs: `320 px box b2e4777952afd`. `here` is the file the
    whole report is about (the plan), which a finding in it need not repeat."""
    where = finding.get("location") or {}
    parts = []
    if "viewport" in where:
        parts.append(f"{where['viewport']} px")
    if "context" in where:
        parts.append(f"context {where['context']}")
    if "flow" in where:
        parts.append(f"flow {where['flow']}" + (f" step {where['step']}" if "step" in where else ""))
    if "box" in where:
        parts.append(f"box {where['box']}")
    for key in ("asset", "file", "path"):
        if key in where and where[key] != here:
            parts.append(str(where[key]))
    return " ".join(parts)


def _item(finding: dict, here: str | None) -> str:
    where = place(finding, here)
    text = clip(finding["observed"], OBSERVED_CAP)
    return text if not where or text.startswith(where) else f"{where} — {text}"


def finding_lines(findings: Iterable[dict], mark: str = "BLOCK", here: str | None = None, *,
                  fixes: bool = True) -> list[str]:
    """Each finding once, grouped by rule: the rule id, where, the observed text, and the fix. A rule with several
    findings names its fix once when they share it; identical lines count as `×n`."""
    groups: dict[str, list[dict]] = {}
    for finding in findings:
        groups.setdefault(finding["rule_id"], []).append(finding)
    lines: list[str] = []
    for rule, items in groups.items():
        fixed = [clip(f["fix"], FIX_CAP) for f in items if fixes and f.get("fix")]
        shared = fixed[0] if fixed and len(fixed) == len(items) and len(set(fixed)) == 1 else None
        rows = Counter(_item(f, here) + (f"  fix: {clip(f['fix'], FIX_CAP)}" if fixes and f.get("fix") and shared is None
                                         else "") for f in items)
        if len(items) == 1:
            lines.append(f"  [{mark}] {rule} {next(iter(rows))}")
        else:
            lines.append(f"  [{mark}] {rule} ×{len(items)}")
        if shared:
            lines.append(f"      fix: {shared}")
        if len(items) > 1:
            lines += [f"      {text}" + (f"  (×{n})" if n > 1 else "") for text, n in rows.items()]
    return lines


def _mark(finding: dict) -> str:
    """`WARN` or `INFO` for an open finding that does not block: the severity it has when creating."""
    return str((finding.get("severity") or {}).get("create", "open")).upper()


def _tally(names: Iterable[str]) -> str:
    return ", ".join(f"{name} ×{n}" if n > 1 else name for name, n in Counter(names).items())


def rest_lines(findings: Iterable[dict], here: str | None = None, *, detail_open: bool = False) -> list[str]:
    """What did not block: findings that stay open, findings a plan keep waived, and findings that were not judged.
    Open findings are named by rule id, or with `detail_open` one by one with their text (a plan holds few). Waived
    ones are named by rule id. Findings not judged come one line per cause and reason (a missing input names the
    check to run, a reviewer's call goes to the critic), so no skipped rule is left out."""
    open_, waived, skipped = [], [], {}
    for f in findings:
        if f["blocking"]:
            continue
        if f["status"] == "skipped":
            skipped.setdefault((f.get("skip_cause"), clip(f["observed"], NOTICE_CAP)), []).append(f["rule_id"])
        elif f["status"] == "waived":
            waived.append(f["rule_id"])
        else:
            open_.append(f)
    lines = []
    if open_ and detail_open:
        for mark in dict.fromkeys(map(_mark, open_)):
            lines += finding_lines((f for f in open_ if _mark(f) == mark), mark, here, fixes=False)
    elif open_:
        lines.append(f"  open, not blocking: {_tally(f['rule_id'] for f in open_)}")
    if waived:
        lines.append(f"  waived by the plan: {_tally(waived)}")
    for (cause, reason), rules in skipped.items():
        lines.append(f"  not judged{f' ({cause})' if cause else ''}: {reason} — {_tally(rules)}")
    return lines
