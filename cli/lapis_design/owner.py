"""The owner block: what `done` and every approval wait show the owner, written by the CLI from the files.

`block(root, task, result)` reads the requirement record, the critic reports, the change log, the disputes, and the
draft record, and returns the block as text with the 8-hex digest of its body. `write` also stores it atomically at
`.lapis/owner/<task>.md`. The text ends with the line `lapis-owner-block <sha8>`; an approval question has to carry
that line (`carries`), and `done` tells the agent to paste the block unchanged ahead of its own summary.

Sections, in order: requirement outcome (counts, and up to 15 `partly`, `missing`, or left-out rows), the owner's own
decisions, the facts shown with their sources, integrity (protected changes, reactive keeps, requirement-record
changes, anomalies, the critic's `narrows` verdicts, and what changed since the owner approved the slice), disputes
with the maker's reason and the critic's verdict, what was shown (URL, widths, document height at 1440, the capture
files of the shown widths, and, for a plain static page, the HTML file that opens without a server: a link can be
dead by the time the owner looks), what did not run or is stale, and the release verdict line. The body holds no
times and no absolute paths, so the same files give the same digest. Outcome and integrity are never merged into one
number. The block judges nothing: it copies what a record says and says where it came from.

`result` is what the caller has: `verdict` (the release line `next` writes when the procedure is done) and
`integrity_error` (what `integrity.observe` returned as `error`); both are optional.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

import yaml

from lapis_design import attempts, brief, critic_packet, draft, gaps, gate, integrity, requirements, slice_step

MARKER = "lapis-owner-block"
LIST_MAX = 15
STATES = ("met", "partly", "missing", "not-in-slice", "not-observable")
_MARKER_LINE = re.compile(r"^[ \t]*" + MARKER + r" ([0-9a-f]{8})[ \t]*$", re.MULTILINE)


def path(root: Path, task: str) -> Path:
    return root / ".lapis" / "owner" / f"{task}.md"


def carries(text: str, sha8: str) -> bool:
    """Whether `text` holds the line of the current block."""
    return any(found == sha8 for found in _MARKER_LINE.findall(text))


def _json(file: Path) -> Any:
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _cut(text: Any, limit: int = 100) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _pages(root: Path, task: str) -> list[dict]:
    return slice_step.pages(root, task)


def _sources(root: Path, task: str, done: bool) -> list[tuple[str, str]]:
    """The critic reports the block speaks for, as (what it judged, path): the release report when the procedure is
    done, else the reports of the pages shown in the draft record, else the release report if there is one."""
    release = f".lapis/critic/{task}.json"
    if not done:
        shown = [(f"the page {p['url']}", report) for p in _pages(root, task) if (report := slice_step.critic_report(p))]
        if shown:
            return list(dict.fromkeys(shown))
    return [("the whole page", release)] if (root / release).is_file() else []


def _outcome(root: Path, task: str, record: dict | None, sources: list[tuple[str, str]],
             decisions: list[dict]) -> list[str]:
    out = ["## Requirements: what was shown against what you asked"]
    if record is None:
        return out + ["- There is no requirement record for this task (a repair, or a task from before the record), so "
                      "no row of yours was judged."]
    dropped = {d["row"] for d in decisions if d["decision"] == "drop"}
    narrowed = {d["row"] for d in decisions if d["decision"] == "narrow"}
    rows = [r for r in record["rows"] if r["id"] not in dropped]
    note = attempts.read(root, task, "critic")
    if not rows:
        return out + ["- The record holds no row of yours" + (f" besides {len(dropped)} you dropped." if dropped else ".")]
    if not sources:
        why = f"requirements not judged: {note['reason']}" if note else "requirements not judged: no critic report yet"
        return out + [f"- {len(rows)} rows. {why}."]
    for label, report_path in sources:
        report = _json(root / report_path)
        if not isinstance(report, dict):
            out.append(f"- {label}: the critic report {report_path} cannot be read; {len(rows)} rows not judged.")
            continue
        judged = {r["id"]: r for r in report.get("requirements") or () if isinstance(r, dict) and "id" in r}
        counts = {state: sum(judged.get(r["id"], {}).get("state") == state for r in rows) for state in STATES}
        open_ids = [r["id"] for r in rows if r["id"] not in judged]
        parts = [f"{state} {n}" for state, n in counts.items() if n] + ([f"not judged {len(open_ids)}"] if open_ids else [])
        out.append(f"- {label}, critic report {report_path}: {len(rows)} rows: {', '.join(parts) or 'none judged'}.")
        if open_ids and note:
            out.append(f"  requirements not judged: {note['reason']}.")
        listed = []
        for row in rows:
            entry = judged.get(row["id"])
            if entry and (entry.get("state") in ("partly", "missing") or entry.get("left_by")):
                mark = " (you narrowed it)" if row["id"] in narrowed else ""
                left = f"; left out by {', '.join(map(str, entry['left_by']))}" if entry.get("left_by") else ""
                why = f" — {_cut(entry['note'], 160)}" if entry.get("note") else ""
                listed.append(f"  - {entry.get('state')} {row['id']}{mark} \"{_cut(row['text'])}\"{why}{left}")
        listed += [f"  - not judged {i} \"{_cut(next(r['text'] for r in rows if r['id'] == i))}\"" for i in open_ids]
        out += listed[:LIST_MAX]
        if len(listed) > LIST_MAX:
            out.append(f"  - and {len(listed) - LIST_MAX} more in {report_path}")
    return out


def _decisions(root: Path, task: str, decisions: list[dict], record: dict | None) -> list[str]:
    out = ["## Your decisions"]
    known = {r["id"] for r in (record or {}).get("rows", [])}
    for d in decisions:
        extra = "" if d["row"] in known else " (no row has this id)"
        out.append(f"- {d['decision']} {d['row']}{extra}: {_cut(d['quote'], 200)} ({d['at']['path']} line {d['at']['line']})")
    try:
        answers = (root / ".lapis" / "answers" / f"{task}.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        answers = ""
    out += [f"- gaps seen (lapis-owner-block {m.group(1)}): {_cut(m.group(2), 200)}" for m in gaps.SEEN.finditer(answers)]
    return out if len(out) > 1 else out + ["- none recorded."]


def _gaps(found: list[dict], done: bool) -> list[str]:
    """The decisions the owner did not make, with what the agent filled in (`gaps.py`). An unattended run's block at
    `done` says they were made without the owner."""
    if done and gate.is_unattended():
        out = ["## Decisions made without you", "The run made these for you; nobody was there to ask."]
    else:
        out = ["## Decisions you have not made",
               "The agent filled these in. Approval needs your word on them: say they are seen, or change any of them."]
    if not found:
        return out + ["- none."]
    out += [f"- {g['text']}" for g in found[:LIST_MAX]]
    return out + ([f"- and {len(found) - LIST_MAX} more"] if len(found) > LIST_MAX else [])


_ASK_ITEM = re.compile(r"^\s*Ask\s+([a-z][a-z-]*)\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL)
_BASIS = re.compile(r"\bbasis\b\s*:\s*(\S.*)", re.IGNORECASE | re.DOTALL)


def _asks(root: Path, task: str, record: dict | None) -> list[str]:
    """Each item under `## Asks` of the brief record: its trigger and, for what the owner answered, its row id and their
    words; for what the run answered itself, the default it took and why. When the run answered every one itself (an
    unattended run), the title says so."""
    try:
        text = (root / ".lapis" / "answers" / f"{task}.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    rows = {requirements.norm(r["text"]): r["id"] for r in (record or {}).get("rows", [])}
    lines: list[str] = []
    owner_answered = False
    for item in brief.items(brief.sections(text).get("asks", "")):
        tag = brief._TAG.match(item)
        body = requirements._LEAD.sub("", item[tag.end():]) if tag else item
        found = _ASK_ITEM.match(body)
        trigger, said = (found.group(1).lower(), found.group(2)) if found else ("unnamed", body)
        if tag and tag.group(1).lower() == "assumed":
            basis = _BASIS.search(said)
            lines.append(f"- {trigger}: default taken, not asked: "
                         f"{_cut(basis.group(1), 200) if basis else _cut(said, 200)}")
        else:
            owner_answered = True
            row = rows.get(requirements.norm(body))
            lines.append(f"- {trigger}{f' ({row})' if row else ''}: {_cut(said, 200)}")
    title = "## Questions during the work" if owner_answered or not lines else "## Questions the run answered itself"
    return [title] + (lines or ["- none."])


def _facts(root: Path, sources: list[tuple[str, str]]) -> list[str]:
    out = ["## Facts shown, with their sources"]
    found: list[tuple[str, str, str | None]] = []
    for _, report_path in sources:
        for fact in (_json(root / report_path) or {}).get("facts") or ():
            if isinstance(fact, dict) and fact.get("text"):
                source = fact.get("source") if fact.get("source") not in (None, "", "none") else None
                entry = (str(fact["text"]), str(source) if source else "", fact.get("quote"))
                if entry not in found:
                    found.append(entry)
    if not found:
        return out + ["- none listed."]
    found.sort(key=lambda e: bool(e[1]))              # facts without a source first; the order of the report otherwise
    for text, source, quote in found:
        if source:
            out.append(f"- \"{_cut(text, 200)}\" — asserted by {source}" + (f": \"{_cut(quote, 160)}\"" if quote else ""))
        else:
            out.append(f"- \"{_cut(text, 200)}\" — no source found")
    return out + ["These are asserted by their source and not independently checked."]


def _integrity(root: Path, task: str, sources: list[tuple[str, str]], error: str | None) -> list[str]:
    out = ["## Integrity: what changed behind the page"]
    if error:
        out.append(f"- integrity not recorded: {error}")
    rows = integrity.changes(root, task)
    protected = [r for r in rows if r.get("kind") == "protected"]
    since = [r for r in protected if r.get("after_slice")]
    flagged = [r for r in protected if r.get("reactive") or r.get("related_open")]
    lines: list[str] = []
    for r in flagged:
        reactive = " — a keep added while its finding was open" if r.get("reactive") else ""
        related = f" (findings open: {', '.join(r['related_open'])})" if r.get("related_open") else ""
        lines.append(f"- protected {r['pointer']} changed{related}{reactive}")
    for r in rows:
        if r.get("kind") == "requirements":
            lines.append(f"- requirement record: {r['pointer'].removeprefix('/requirements/')} "
                         f"{_cut(r.get('before') or '', 60)!r} -> {_cut(r.get('after') or '', 60)!r}")
        elif r.get("kind") == "answers-headings":
            lines.append("- the headings of the answers file changed")
        elif r.get("kind") == "integrity":
            lines.append(f"- anomaly: {_cut(r.get('after'), 200)}")
    for _, report_path in sources:
        for change in (_json(root / report_path) or {}).get("changes") or ():
            if isinstance(change, dict) and change.get("verdict") == "narrows":
                lines.append(f"- the critic says change {change.get('seq')} narrows what you asked: "
                             f"{_cut(change.get('why', ''), 160)}")
    out.append(f"- {len(protected)} protected changes observed, {len(flagged)} listed here, {len(since)} since the slice.")
    out += lines
    if since:
        out.append("Changed since you approved the slice:")
        out += [f"- {r['pointer']}" for r in since]
    return out


def _disputes(root: Path, task: str, sources: list[tuple[str, str]]) -> list[str]:
    out = ["## Disputes: findings the maker says are wrong"]
    try:
        doc = yaml.safe_load((root / ".lapis" / "disputes" / f"{task}.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        doc = None
    filed = [d for d in (doc or {}).get("disputes") or () if isinstance(d, dict)] if isinstance(doc, dict) else []
    if not filed:
        return out + ["- none filed."]
    verdicts: dict[int, dict] = {}
    for _, report_path in sources:
        for item in (_json(root / report_path) or {}).get("disputes") or ():
            if isinstance(item, dict) and isinstance(item.get("index"), int):
                verdicts.setdefault(item["index"], item)
    for index, d in enumerate(filed):
        seen = verdicts.get(index)
        ruling = f"critic: {seen.get('verdict')} — {_cut(seen.get('why', ''), 160)}" if seen else "critic: not judged"
        out.append(f"- {d.get('rule_id')}: {_cut(d.get('observed', ''), 120)}; maker: {_cut(d.get('reason', ''), 200)}; {ruling}")
    return out


def _core_open(root: Path, task: str) -> list[str]:
    """The core findings of the critic reports of the pages shown that are still open: the owner's decisions to make,
    each with the rule id and what the critic observed. Empty when there is none, and then the block has no section."""
    found: list[tuple[str, str]] = []
    for page in _pages(root, task):
        report = slice_step.critic_report(page)
        for finding in (_json(root / report) or {}).get("findings") or () if report else ():
            if isinstance(finding, dict) and "rule_id" in finding and "status" in finding and draft.is_core(finding):
                entry = (finding["rule_id"], _cut(finding.get("observed", ""), 200))
                if entry not in found:
                    found.append(entry)
    if not found:
        return []
    out = ["## Open core findings: your decision",
           "The critic's report still holds these open. Say what to do about each: the slice is not sealed until a fresh "
           "critic report closes it or you decide it."]
    return out + [f"- {rule_id}: {observed}" for rule_id, observed in found[:LIST_MAX]]


def _captures(root: Path, page: Mapping[str, Any]) -> list[str]:
    """The screenshots of the widths shown that the page's extracts name, project-relative and ordered by width: one
    per extract and width, the light, full-motion, unframed capture when an extract holds several."""
    base = Path(root).resolve()
    review = page.get("review") if isinstance(page.get("review"), dict) else {}
    shown = set(page.get("widths") or ())
    out: list[str] = []
    for name in review.get("extracts") or ():
        extract = base / name
        best: dict[int, tuple[tuple[bool, bool, bool], Path]] = {}
        for view in (_json(extract) or {}).get("viewports") or ():
            if not isinstance(view, dict) or view.get("width") not in shown or not isinstance(view.get("screenshot"), str):
                continue
            shot = (extract.parent / view["screenshot"]).resolve()
            score = (view.get("theme") == "light", not view.get("reduced_motion"), not view.get("browser_chrome"))
            if shot.is_file() and shot.is_relative_to(base) and (view["width"] not in best or score > best[view["width"]][0]):
                best[view["width"]] = (score, shot)
        out += [best[width][1].relative_to(base).as_posix() for width in sorted(best)]
    return list(dict.fromkeys(out))


# What a page needs a server for: an address from the site root, a module script or import, a request of its own, a worker.
_ABSOLUTE = re.compile(r"""\b(?:src|href|poster|action|data)\s*=\s*["']\s*/(?!/)|\burl\(\s*["']?\s*/(?!/)""", re.I)
_REQUESTS = re.compile(r"""<script[^>]*\btype\s*=\s*["']?module|\bfetch\s*\(|\bXMLHttpRequest\b|"""
                       r"""\bnew\s+(?:Worker|SharedWorker|EventSource|WebSocket)\b|\bserviceWorker\b|"""
                       r"""\bimport\s*\(|^\s*import\b\s*[\w{*"']""", re.M)


def _static(root: Path, page: Mapping[str, Any]) -> str | None:
    """The page's own HTML file, project-relative, when a person can open it from disk without a server: the address
    names an HTML file of the project, and neither it nor the HTML, styles, and scripts it lists reach for the site
    root, a module, or a request of their own. Anything less sure gives None; the captures show the page as checked."""
    base = Path(root).resolve()
    parts = urlsplit(page["url"])
    if parts.scheme not in ("http", "https") or parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        return None
    name = unquote(parts.path).lstrip("/")
    entry = (base / (name if name and not name.endswith("/") else name + "index.html")).resolve()
    if entry.suffix.lower() not in (".html", ".htm") or not entry.is_file() or not entry.is_relative_to(base):
        return None
    files = {entry}
    for listed in page.get("sources") or ():
        file = (base / str(listed)).resolve()
        if file.is_file() and file.is_relative_to(base) and file.suffix.lower() in (".html", ".htm", ".css", ".js", ".mjs"):
            files.add(file)
    for file in sorted(files):
        try:
            text = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
        if _ABSOLUTE.search(text) or (file.suffix.lower() != ".css" and _REQUESTS.search(text)):
            return None
    return entry.relative_to(base).as_posix()


def _shown(root: Path, task: str) -> list[str]:
    out = ["## What was shown"]
    pages = _pages(root, task)
    for page in pages:
        widths = ", ".join(str(w) for w in page.get("widths") or ()) or "unknown widths"
        height = slice_step.height(root, page)
        tall = f"{height:,} px" if height is not None else "not measured"
        out.append(f"- {page['url']} at {widths}; document height at 1440: {tall}")
        if captures := _captures(root, page):
            out.append(f"  - captures, which open without a server: {', '.join(captures)}")
        if static := _static(root, page):
            out.append(f"  - the page as a file, which opens without a server: {static}")
    if not pages:
        out.append("- no rendered page is recorded for this task.")
    if sealed := slice_step.sealed(root, task):
        out.append(f"- Slice sealed: {sealed['url']}")
    state = integrity.read_state(root, task) or {}
    if (state.get("slice_rounds") or 1) > 1:                   # the first showing is the page above; the clock alone changes no block
        out.append(f"- Slice rounds: {state['slice_rounds']}")
        out += [f"  - round {n}: document height at 1440: {h:,} px"
                for n, h in sorted((state.get("slice_heights") or {}).items(), key=lambda item: int(item[0]))]
    if said := slice_step.skipped(root, task):
        out.append(f"- Slice skipped by you: {_cut(said, 200)}")
    return out


def _not_run(root: Path, task: str, record: dict | None, sources: list[tuple[str, str]], done: bool) -> list[str]:
    out = ["## Not run, or stale"]
    lines: list[str] = []
    for step in ("render", "behavior", "critic", "release", "references"):
        if skipped := attempts.read(root, task, step):
            lines.append(f"- {step}: {skipped.get('reason') or skipped.get('brief_line') or skipped.get('kind', 'not run')}")
    if record is not None and record["rows"] and not sources:
        lines.append("- critic: no report, so no requirement was judged")
    for label, report_path in sources if record is not None else ():
        # a report counts only for its packet: say where it does not (critic_packet.check, as the gate reads it)
        found = critic_packet.verify(root, root / report_path)
        lines += [f"- {label}, critic report {report_path}: {_cut(problem, 300)}" for problem in found[:3]]
        if len(found) > 3:
            lines.append(f"- {label}, critic report {report_path}: and {len(found) - 3} more gaps")
    release = _json(root / ".lapis" / "release" / f"{task}.json")
    if done:
        if not isinstance(release, dict):
            lines.append("- release gate: no report")
        else:
            from lapis_design.release_check import NO_EVIDENCE

            summary = release.get("summary") or {}
            causes = [f"{summary['not_run'][key]} {name}" for key, name in NO_EVIDENCE.values()
                      if key in (summary.get("not_run") or {})]
            if causes:
                lines.append(f"- the release gate had no evidence for: {', '.join(causes)}")
    elif not isinstance(release, dict):
        lines.append("- release gate: not run yet")
    return out + (lines or ["- nothing recorded as skipped."])


def _build(root: Path, task: str, result: Mapping[str, Any] | None) -> tuple[str, str, list[str]]:
    result = result or {}
    root = Path(root)
    record = requirements.record(root, task)
    decisions = list((record or {}).get("owner_decisions") or [])
    done = bool(result.get("verdict"))
    sources = _sources(root, task, done)
    found = gaps.compute(root, task)
    sections = [
        [f"# Owner block: {task}"],
        _outcome(root, task, record, sources, decisions),
        _decisions(root, task, decisions, record),
        _gaps(found, done),
        _core_open(root, task),
        _asks(root, task, record),
        _facts(root, sources),
        _integrity(root, task, sources, result.get("integrity_error")),
        _disputes(root, task, sources),
        _shown(root, task),
        _not_run(root, task, record, sources, done),
    ]
    sections = [lines for lines in sections if lines]
    if done:
        sections.append(["## Release", f"- {result['verdict']}"])
    body = "\n\n".join("\n".join(lines) for lines in sections) + "\n\n"
    sha8 = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    return f"{body}{MARKER} {sha8}\n", sha8, [g["id"] for g in found]


def block(root: Path, task: str, result: Mapping[str, Any] | None = None) -> tuple[str, str]:
    """The owner block for `task` and the first 8 hex digits of the SHA-256 of its body."""
    text, sha8, _ = _build(root, task, result)
    return text, sha8


def write(root: Path, task: str, result: Mapping[str, Any] | None = None) -> tuple[str, str]:
    """`block`, also written to `.lapis/owner/<task>.md`, with the gaps it lists recorded under its digest. A folder that
    cannot be written is told on stderr; the block comes back either way."""
    text, sha8, listed = _build(root, task, result)
    try:
        requirements.write_atomic(path(Path(root), task), text)
    except OSError as exc:
        print(f"lapis-design owner: {path(Path(root), task)} cannot be written: {exc}", file=sys.stderr)
    gaps.record(Path(root), task, sha8, listed)
    return text, sha8
