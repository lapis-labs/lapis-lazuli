"""The owner block and the owner summary: what `done` and every approval wait show the owner, written by the CLI from the
files.

`block(root, task, result)` reads the requirement record, the critic reports, the change log, the disputes, and the
draft record, and returns the full block as text with the 8-hex digest of its body. `write` also stores it atomically at
`.lapis/owner/<task>.md` and, once per digest, at `.lapis/owner/<task>.<sha8>.md`, which never changes. The text ends with
the line `lapis-owner-block <sha8>`.

The block is the record and is long. What the chat carries is the owner summary (`deliver`, `.lapis/owner/<task>.summary.md`):
one `Decision:` line, the decisions of the owner's last reply that changed something, every decision the owner has not made,
every defect of the build shown (open core findings, what is not reviewed, requirement rows that are missing or not
judged, a critic report that does not hold), every font role with its source and license, what was shown, and the path
and digest of the full block. The delivery contract is what `Delivery.problems` checks in the questions file of an approval
or direction wait: the summary carries the block's last line `lapis-owner-block <sha8>` and exactly one `Decision:` line,
and every line of `Delivery.required` (a core gap, a core defect, a font fact) is in it unchanged. Everything else of the
block is by link: the requirement outcome beyond the defects, the facts with their sources, integrity, disputes, the
documents of the shown pages. `done` tells the agent to paste the summary ahead of its own summary. The summary is never
shorter than the contract: a line it drops from `required` is a problem, not a saving.

The summary's fixed text is in the owner's language (`owner_text.py`: English and Korean; the full block is English), and
`Delivery.problems` compares against that text. Before anything has been shown or built (`_built`: not `done`, no critic
report, no page or record in the draft record, no slice budget fired), the summary has no `Defects of the build shown` section,
and requires none of its lines: there is no build to hold them against.

Sections of the full block, in order: requirement outcome (counts, and up to 15 `partly`, `missing`, or left-out rows), the
owner's own decisions, the decisions the owner has not made, the open core findings, the questions asked during the work,
the fonts and their rights, the facts shown with their sources, integrity (protected changes, reactive keeps,
requirement-record changes, anomalies, the critic's `narrows` verdicts, and what changed since the owner approved the
slice), disputes with the maker's reason and the critic's verdict, what was shown (URL, widths, document height at 1440,
the capture files of the shown widths, the supporting evidence declared for it, and, for a plain static page, the HTML
file that opens without a server: a link can be dead by the time the owner looks), what did not run or is stale, and the
release verdict line. The body holds no times and no absolute paths, so the same files give the same digest. Outcome and
integrity are never merged into one number. The block judges nothing: it copies what a record says and says where it came
from. A critic report on a delta packet is read as one report with the full report it follows (`critic_packet.effective`).

`result` is what the caller has: `verdict` (the release line `next` writes when the procedure is done), `integrity_error`
(what `integrity.observe` returned as `error`), and `kind` (`approval` or `direction`, for the summary's decision line); all
are optional.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

import yaml

from lapis_design import (attempts, brief, critic_packet, direction, diverge, draft, font_license, gaps, gate, integrity,
                          owner_text, requirements, slice_step, workers)

MARKER = "lapis-owner-block"
LIST_MAX = 15
STATES = ("met", "partly", "missing", "not-in-slice", "not-observable")
_MARKER_LINE = re.compile(r"^[ \t]*" + MARKER + r" ([0-9a-f]{8})[ \t]*$", re.MULTILINE)


def path(root: Path, task: str) -> Path:
    return root / ".lapis" / "owner" / f"{task}.md"


def carries(text: str, sha8: str) -> bool:
    """Whether `text` holds the line of the current block."""
    return any(found == sha8 for found in _MARKER_LINE.findall(text))


def artifact_path(root: Path, task: str, sha8: str) -> Path:
    """The full block with digest `sha8`, kept as it was when it was shown; the file of `path` is the latest one."""
    return root / ".lapis" / "owner" / f"{task}.{sha8}.md"


def summary_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "owner" / f"{task}.summary.md"


def _json(file: Path) -> Any:
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _report(root: Path, name: str) -> Any:
    """The critic report at `name` as a whole: a report on a delta packet is completed with the full report it follows."""
    return critic_packet.effective(root, root / name) or _json(root / name)


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
        report = _report(root, report_path)
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
    for d in direction.decisions(root, task):
        if d["kind"] == "pick":
            out.append(f"- picked rough {d['text']} ({d['by']}): {_cut(d['quote'], 200)}")
        else:
            out.append(f"- took the defaults of the direction conversation (turn {d['turn']}): {_cut(d['quote'], 200)}")
    from lapis_design import asks

    budget = asks._BUDGET.findall(answers)
    if budget:
        out.append(f"- agent-alone budget set by you: {budget[-1]} min")
    if said := slice_step.skipped(root, task):
        out.append(f"- slice skipped by you: {_cut(said, 200)}")
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
        for fact in (_report(root, report_path) or {}).get("facts") or ():
            if isinstance(fact, dict) and fact.get("text"):
                source = fact.get("source") if fact.get("source") not in (None, "", "none") else None
                entry = (str(fact["text"]), str(source) if source else "", fact.get("quote"))
                if entry not in found:
                    found.append(entry)
    if not found:
        return out + ["- none listed."]
    found.sort(key=lambda e: bool(e[1]))              # facts without a source first; the order of the report otherwise
    bare = [e for e in found if not e[1]]
    for text, source, quote in [*bare[:LIST_MAX], *[e for e in found if e[1]][:LIST_MAX]]:
        if source:
            out.append(f"- \"{_cut(text, 200)}\" — asserted by {source}" + (f": \"{_cut(quote, 160)}\"" if quote else ""))
        else:
            out.append(f"- \"{_cut(text, 200)}\" — no source found")
    if len(bare) > LIST_MAX:
        out.append(f"- and {len(bare) - LIST_MAX} more facts with no source found")
    if len(found) - len(bare) > LIST_MAX:
        out.append(f"- and {len(found) - len(bare) - LIST_MAX} more facts with a source")
    if bare:
        out.append("A fact with no source found may still come from your own answers to the fact questions: the critic "
                   "did not cite them, so compare it with what you said.")
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
        for change in (_report(root, report_path) or {}).get("changes") or ():
            if isinstance(change, dict) and change.get("verdict") == "narrows":
                lines.append(f"- the critic says change {change.get('seq')} narrows what you asked: "
                             f"{_cut(change.get('why', ''), 160)}")
    from lapis_design import order

    if order.tampered(root, task):
        out.append("- the order record `.lapis/order/" + task + ".json` was edited outside lapis-design: its page-write "
                   "counts are not trusted")
    out += workers.lines(root, task)
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
        for item in (_report(root, report_path) or {}).get("disputes") or ():
            if isinstance(item, dict) and isinstance(item.get("index"), int):
                verdicts.setdefault(item["index"], item)
    for index, d in enumerate(filed):
        seen = verdicts.get(index)
        ruling = f"critic: {seen.get('verdict')} — {_cut(seen.get('why', ''), 160)}" if seen else "critic: not judged"
        out.append(f"- {d.get('rule_id')}: {_cut(d.get('observed', ''), 120)}; maker: {_cut(d.get('reason', ''), 200)}; {ruling}")
    return out


def core_findings(root: Path, task: str) -> list[tuple[str, str]]:
    """The core findings of the critic reports of the pages shown that are still open, as (rule id, what the critic
    observed): the owner's decisions to make."""
    found: list[tuple[str, str]] = []
    for page in _pages(root, task):
        report = slice_step.critic_report(page)
        for finding in (_report(root, report) or {}).get("findings") or () if report else ():
            if isinstance(finding, dict) and "rule_id" in finding and "status" in finding and draft.is_core(finding):
                entry = (finding["rule_id"], _cut(finding.get("observed", ""), 200))
                if entry not in found:
                    found.append(entry)
    return found


def _core_open(found: list[tuple[str, str]]) -> list[str]:
    """The section of the open core findings: no section when there is none."""
    if not found:
        return []
    out = ["## Open core findings: your decision",
           "The critic's report still holds these open. Say what to do about each: the slice is not sealed until a fresh "
           "critic report closes it or you decide it."]
    return out + [f"- {rule_id}: {observed}" for rule_id, observed in found[:LIST_MAX]]


# The channels whose license the owner has to confirm (release_check.UNCONFIRMED and `sandoll`), except an open-source file
# whose license was read from its own document (release_check.OPEN_CHANNELS): a subscription's synced files, files of
# unknown provenance, a purchase, a catalog that gives no license text. A commercial or Adobe candidate always is one.
_UNCONFIRMED_CHANNELS = {"adobe-sync", "user-installed", "foundry-purchase", "open-source-other", "noonnu", "sandoll"}
_OPEN_CHANNELS = {"open-source-other", "noonnu"}


def font_facts(root: Path, task: str, lang: str = "en") -> list[str]:
    """One line per type role of the plan: the family, where it comes from, and what the fonts lock records of its license
    (`no fonts lock entry yet` before `lazuli lock` ran). A role whose license nobody confirmed is marked `needs your word`.
    These are the rights facts the owner has to see. The fixed words are in `lang` (`owner_text.py`); the plan's and the
    lock's values are as they are."""
    plan = gaps._plan(root, task)
    roles = ((plan.get("tokens") or {}).get("type") or {}).get("roles") or ()
    lock = _json(root / ".lapis" / "fonts.lock.json")
    entries = [e for e in (lock.get("fonts") if isinstance(lock, dict) else None) or () if isinstance(e, dict)]
    candidates: dict[str, str] = {}
    for exploration in plan.get("explorations") or ():
        if isinstance(exploration, Mapping) and exploration.get("decision") == "type":
            for candidate in exploration.get("candidates") or ():
                if isinstance(candidate, Mapping) and candidate.get("name") and candidate.get("source"):
                    candidates.setdefault(str(candidate["name"]), str(candidate["source"]))
    out = []
    for role in roles:
        if not isinstance(role, Mapping) or not role.get("role") or not role.get("family"):
            continue
        family = str(role["family"])
        entry = (next((e for e in entries if e.get("family") == family and e.get("role") == role["role"]), None)
                 or next((e for e in entries if e.get("family") == family), None))
        source = candidates.get(family) or role.get("source") or owner_text.say(lang, "font.unsaid")
        scripts = f" ({', '.join(map(str, role['scripts']))})" if role.get("scripts") else ""
        if entry is None:
            lock_text, open_ = owner_text.say(lang, "font.no-lock"), True
        else:
            state = font_license.state(entry)
            kind = (entry.get("license") or {}).get("kind", "unknown")
            lock_text = owner_text.say(lang, "font.lock", channel=entry.get("source"), kind=kind, state=state)
            open_ = state in ("unknown", "unresearched") or (
                entry.get("source") in _UNCONFIRMED_CHANNELS and not (state == "researched" and entry.get("source") in _OPEN_CHANNELS))
        open_ = open_ or str(source).startswith(("adobe", "commercial"))
        out.append(owner_text.say(lang, "font.line", role=role["role"], scripts=scripts, family=family, source=source,
                                  lock=lock_text) + (owner_text.say(lang, "font.needs") if open_ else ""))
    return out


def _fonts(lines: list[str]) -> list[str]:
    return ["## Fonts and rights", *([f"- {line}" for line in lines] or ["- the plan names no type roles."])]


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
        height = slice_step.height(root, task, page)
        tall = f"{height:,} px" if height is not None else "not measured"
        out.append(f"- {page['url']} at {widths}; document height at 1440: {tall}")
        if captures := _captures(root, page):
            out.append(f"  - captures, which open without a server: {', '.join(captures)}")
        if static := _static(root, page):
            out.append(f"  - the page as a file, which opens without a server: {static}")
    if not pages:
        out.append("- no rendered page is recorded for this task.")
    for entry in draft.supporting(root, task):
        out.append(f"- supporting evidence ({entry['kind']}) {entry['path']}, sha256 {entry['sha256'][:12]}: "
                   f"{_cut(entry['claim'], 160)}")
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


def _unreviewed(found: tuple[str, list[str]] | None, lang: str = "en") -> list[str]:
    """The slice shown before its review was current, because its budget ran out: why, and what the draft check says is
    not current (`slice_step.unreviewed`). No section while the review is current or the budget has not fired."""
    if found is None:
        return []
    why, errors = found
    return ["## Not fully reviewed",
            owner_text.say(lang, "unreviewed.line", why=why),
            *[owner_text.say(lang, "unreviewed.error", error=_cut(error, 300)) for error in errors[:5]],
            *([owner_text.say(lang, "unreviewed.more", n=len(errors) - 5)] if len(errors) > 5 else [])]


def _roughs(root: Path, task: str) -> list[str]:
    """The rough first views the owner picked among, sealed, and what changed in them after the seal (`diverge.py`); no
    section when the run made none."""
    lines = diverge.owner_lines(root, task)
    return ["## Rough first views", *lines] if lines else []


def _faults(root: Path, record: dict | None, sources: list[tuple[str, str]]) -> dict[str, list[str]]:
    """Where a critic report does not hold against its packet (`critic_packet.check`, as the pre-show review reads it: a
    report on a delta packet counts), by report path."""
    return {report_path: critic_packet.verify(root, root / report_path, allow_delta=True)
            for _, report_path in sources if record is not None}


def _fault_lines(sources: list[tuple[str, str]], faults: dict[str, list[str]], lang: str = "en") -> list[str]:
    lines: list[str] = []
    for label, report_path in sources:
        label = _label(label, lang)
        found = faults.get(report_path, [])
        lines += [owner_text.say(lang, "fault.line", label=label, path=report_path, problem=_cut(problem, 300))
                  for problem in found[:3]]
        if len(found) > 3:
            lines.append(owner_text.say(lang, "fault.more", label=label, path=report_path, n=len(found) - 3))
    return lines


def _not_run(root: Path, task: str, record: dict | None, sources: list[tuple[str, str]], done: bool,
             faults: dict[str, list[str]]) -> list[str]:
    out = ["## Not run, or stale"]
    lines: list[str] = []
    for step in ("render", "behavior", "critic", "release", "references"):
        if skipped := attempts.read(root, task, step):
            lines.append(f"- {step}: {skipped.get('reason') or skipped.get('brief_line') or skipped.get('kind', 'not run')}")
    if record is not None and record["rows"] and not sources:
        lines.append("- critic: no report, so no requirement was judged")
    lines += _fault_lines(sources, faults)
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


@dataclass(frozen=True)
class Delivery:
    """What an owner wait delivers: the full block and its digest, the summary the chat carries, the project-relative path
    of the full block kept under its digest, and `required`, the lines of the summary the delivery contract needs in the
    questions as they are (what they are, the line): a core gap, a core defect, a font fact, the release verdict."""
    task: str
    block: str
    sha8: str
    summary: str
    required: tuple[tuple[str, str], ...]
    artifact: str
    gap_ids: tuple[str, ...]
    language: str = "en"

    @property
    def marker(self) -> str:
        return f"{MARKER} {self.sha8}"

    @property
    def heading(self) -> str:
        """The summary's first line, in the owner's language."""
        return f"# {owner_text.say(self.language, 'title')}: {self.task}"

    @property
    def decision_label(self) -> str:
        """The word the summary's one decision line starts with (`Decision`), in the owner's language."""
        return owner_text.say(self.language, "decision.label")

    def pointer(self) -> dict:
        """Where the full block is, for a command's JSON: its path under the digest, the marker line, and its size in
        characters, which the chat does not carry."""
        return {"path": self.artifact, "marker": self.marker, "chars": len(self.block),
                "summary": f".lapis/owner/{self.task}.summary.md"}

    def problems(self, text: str) -> list[str]:
        """What the questions in `text` lack of the delivery contract (empty when it is met): the current summary with its
        last line `lapis-owner-block <sha8>`, exactly one `Decision:` line, the path of the full block, and every line of
        `required` unchanged, all in the language the summary was written in. Nothing else of the full block is required
        in chat."""
        if not carries(text, self.sha8):
            return [f"the questions do not carry the current owner summary: its last line `{self.marker}` is missing or out "
                    "of date"]
        lines = text.splitlines()
        end = max(i for i, line in enumerate(lines) if line.strip() == self.marker)
        heading = self.heading
        starts = [i for i in range(end) if lines[i].strip() == heading]
        if not starts:
            return [f"the questions carry `{self.marker}` but not the owner summary above it (`{heading}`): paste "
                    f".lapis/owner/{self.task}.summary.md unchanged"]
        inside = lines[starts[-1]:end + 1]
        region = " ".join(" ".join(inside).split())
        found: list[str] = []
        label = f"{self.decision_label}:"
        if (asks := sum(line.startswith(label) for line in inside)) != 1:
            found.append(f"the owner summary carries exactly one `{label}` line, and this one has {asks}")
        if self.artifact not in region:
            found.append(f"the owner summary names the full block ({self.artifact}) and its digest; this one does not")
        if missing := [(what, line) for what, line in self.required if " ".join(line.split()) not in region]:
            shown = "; ".join(f"{what}: {_cut(line, 90)}" for what, line in missing[:3])
            found.append(f"the owner summary drops {len(missing)} line{'s' if len(missing) != 1 else ''} the owner must "
                         f"see ({shown}{'; and more' if len(missing) > 3 else ''}): paste it unchanged")
        return found


def _label(label: str, lang: str) -> str:
    """The label `_sources` gives a critic report (what it judged), in `lang`."""
    if label == "the whole page":
        return owner_text.say(lang, "label.whole")
    if label.startswith("the page "):
        return owner_text.say(lang, "label.page", url=label.removeprefix("the page "))
    return label


def _states(root: Path, record: dict | None, sources: list[tuple[str, str]], decisions: list[dict],
            why: str, lang: str = "en") -> list[str]:
    """The requirement outcome as the summary carries it: per critic report the counts, each row `missing` or not judged
    with its words, and the rows `partly` by id. A report that cannot be read, or no report, says the rows are not judged."""
    if record is None:
        return []
    dropped = {d["row"] for d in decisions if d["decision"] == "drop"}
    rows = [r for r in record["rows"] if r["id"] not in dropped]
    if not rows:
        return []
    say = owner_text.say
    if not sources:
        return [say(lang, "req.no-report", n=len(rows), why=why)]
    out: list[str] = []
    for label, report_path in sources:
        label = _label(label, lang)
        report = _report(root, report_path)
        if not isinstance(report, dict):
            out.append(say(lang, "req.unreadable", label=label, path=report_path, n=len(rows)))
            continue
        judged = {r["id"]: r for r in report.get("requirements") or () if isinstance(r, dict) and "id" in r}
        by_state = {state: [r for r in rows if judged.get(r["id"], {}).get("state") == state] for state in STATES}
        open_rows = [r for r in rows if r["id"] not in judged]
        parts = [f"{say(lang, 'state.' + state)} {len(found)}" for state, found in by_state.items() if found] + (
            [f"{say(lang, 'state.not-judged')} {len(open_rows)}"] if open_rows else [])
        out.append(say(lang, "req.counts", label=label, parts=", ".join(parts) or say(lang, "req.none-judged-counts"),
                       total=len(rows)))
        out += [say(lang, "req.row", state=say(lang, "state.missing"), id=r["id"], text=_cut(r["text"]))
                for r in by_state["missing"]]
        out += [say(lang, "req.row", state=say(lang, "state.not-judged"), id=r["id"], text=_cut(r["text"]))
                for r in open_rows]
        if by_state["partly"]:
            out.append(say(lang, "req.partly", ids=", ".join(r["id"] for r in by_state["partly"])))
    return out


_OWN_WORDS = re.compile(r"\b(?:drop|narrow)\b\s*(?:—|–|--|-)\s*(\S.*)$", re.DOTALL)


def _row_text(record: dict | None, row_id: str) -> str:
    """The words of requirement row `row_id`, from the record's rows or, for a row that left it, its history."""
    for entry in [*((record or {}).get("rows") or ()), *((record or {}).get("removed") or ())]:
        if entry.get("id") == row_id:
            return _cut(entry["text"])
    return row_id


def _changed(root: Path, task: str, decisions: list[dict], record: dict | None, lang: str = "en") -> list[str]:
    """What changed since the owner's last word, in their terms: the decisions their last reply made (the answers file's
    last section) by the row's words and theirs, the requirement rows that were added or left the record by their text
    (no line when more than three changed: the full block lists them), and the protected values changed since they
    approved the slice."""
    say = owner_text.say
    try:
        answers = (root / ".lapis" / "answers" / f"{task}.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        answers = ""
    heads = [i + 1 for i, line in enumerate(answers.splitlines()) if line.lstrip().startswith("#")]
    start = heads[-1] if heads else 1
    out = []
    for d in decisions:
        if d["at"]["path"].endswith(f"{task}.md") and d["at"]["line"] >= start:
            said = _OWN_WORDS.search(d["quote"])
            words = _cut((said.group(1) if said else d["quote"]).strip().strip("\"“”").strip(), 160)
            out.append(say(lang, f"changed.{d['decision']}", row=_row_text(record, d["row"]), words=words))
    rows = integrity.changes(root, task)
    changed_rows = [r for r in rows if r.get("kind") == "requirements"
                    and not str(r.get("pointer", "")).startswith("/requirements/owner_decisions/")]
    if len(changed_rows) <= 3:
        out += [say(lang, "changed.added", text=_cut(r["after"], 100)) if r.get("after")
                else say(lang, "changed.removed", text=_cut(r.get("before") or "", 100)) for r in changed_rows]
    out += [say(lang, "changed.slice", pointer=r["pointer"])
            for r in rows if r.get("kind") == "protected" and r.get("after_slice")]
    return out[:8] + ([say(lang, "changed.more", n=len(out) - 8)] if len(out) > 8 else [])


def _shown_lines(root: Path, task: str, lang: str = "en") -> list[str]:
    say = owner_text.say
    out = []
    for page in _pages(root, task):
        widths = ", ".join(str(w) for w in page.get("widths") or ())
        line = say(lang, "shown.page", url=page["url"], widths=widths) if widths else say(lang, "shown.page-unknown", url=page["url"])
        if captures := _captures(root, page):
            line += say(lang, "shown.captures", captures=", ".join(captures))
        if static := _static(root, page):
            line += say(lang, "shown.file", file=static)
        out.append(line)
    out += [say(lang, "shown.support", kind=e["kind"], path=e["path"], sha=e["sha256"][:12], claim=_cut(e["claim"], 160))
            for e in draft.supporting(root, task)]
    return out


def _decision(kind: str | None, done: bool, gaps_open: int, core_open: int, lang: str = "en") -> str:
    """The one thing the summary asks the owner for."""
    say = owner_text.say
    if done:
        return say(lang, "decision.done")
    settles = [say(lang, key, n=n) for n, key in ((gaps_open, "settles.gaps"), (core_open, "settles.core")) if n]
    ask = "decision.direction" if kind == "direction" else "decision.approval"
    return say(lang, ask + ".settles", what=say(lang, "settles.join").join(settles)) if settles else say(lang, ask)


def _built(root: Path, task: str, done: bool, sources: list[tuple[str, str]], unreviewed: Any) -> bool:
    """Whether anything has been shown or built, as the CLI's own records say (never the agent's word): the procedure is
    done, a critic report is named, the draft record holds a page or exists at all, or the slice budget ran out with the
    review not current. Before that (direction turns, the roughs before the pick) the summary has no build to hold defects
    against."""
    return bool(done or sources or unreviewed is not None or draft.path(root, task).is_file() or _pages(root, task))


def _build(root: Path, task: str, result: Mapping[str, Any] | None) -> Delivery:
    result = result or {}
    root = Path(root)
    record = requirements.record(root, task)
    decisions = list((record or {}).get("owner_decisions") or [])
    done = bool(result.get("verdict"))
    sources = _sources(root, task, done)
    found = gaps.compute(root, task)
    core = core_findings(root, task)
    unreviewed = slice_step.unreviewed(root, task)
    faults = _faults(root, record, sources)
    fonts = font_facts(root, task)
    sections = [
        [f"# Owner block: {task}"],
        _outcome(root, task, record, sources, decisions),
        _unreviewed(unreviewed),
        _decisions(root, task, decisions, record),
        _gaps(found, done),
        _core_open(core),
        _asks(root, task, record),
        _fonts(fonts),
        _facts(root, sources),
        _integrity(root, task, sources, result.get("integrity_error")),
        _disputes(root, task, sources),
        _shown(root, task),
        _roughs(root, task),
        _not_run(root, task, record, sources, done, faults),
    ]
    sections = [lines for lines in sections if lines]
    if done:
        sections.append(["## Release", f"- {result['verdict']}"])
    body = "\n\n".join("\n".join(lines) for lines in sections) + "\n\n"
    sha8 = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    text = f"{body}{MARKER} {sha8}\n"
    artifact = artifact_path(Path("."), task, sha8).as_posix()
    required: list[tuple[str, str]] = []

    def need(what: str, lines: list[str]) -> list[str]:
        required.extend((what, line) for line in lines)
        return lines

    lang = owner_text.language(root, task)
    say = owner_text.say
    attention = need("core gap", [f"- {g['text']}" for g in found])
    built = _built(root, task, done, sources, unreviewed)
    defects: list[str] = []
    if built:
        why = (say(lang, "why.note", reason=note["reason"]) if (note := attempts.read(root, task, "critic"))
               else say(lang, "why.none"))
        defects = need("core defect", [f"- {rule_id}: {observed}" for rule_id, observed in core])
        defects += need("core defect", [line.strip() for line in _unreviewed(unreviewed, lang)[1:]] if unreviewed else [])
        defects += need("core defect", _fault_lines(sources, faults, lang))
        defects += need("core defect", _states(root, record, sources, decisions, why, lang))
    changed = _changed(root, task, decisions, record, lang)
    shown = _shown_lines(root, task, lang)
    unattended = done and gate.is_unattended()
    summary = [
        [f"# {say(lang, 'title')}: {task}"],
        [f"{say(lang, 'decision.label')}: {_decision(result.get('kind'), done, len(found), len(core), lang)}"],
        [f"## {say(lang, 'heading.changed')}", *changed] if changed else [],
        [f"## {say(lang, 'heading.gaps.unattended' if unattended else 'heading.gaps')}", *attention] if attention else [],
        [f"## {say(lang, 'heading.defects')}", *(defects or [say(lang, 'none.open')])] if built else [],
        [f"## {say(lang, 'heading.release')}", *need("release", [f"- {result['verdict']}"])] if done else [],
        [f"## {say(lang, 'heading.fonts')}", *need("font fact", [f"- {line}" for line in font_facts(root, task, lang)])]
        if fonts else [],
        [f"## {say(lang, 'heading.shown')}", *shown] if shown else [],
        [say(lang, "full.block", artifact=artifact, chars=len(text)), f"{MARKER} {sha8}"]]
    return Delivery(task=task, block=text, sha8=sha8, summary="\n\n".join("\n".join(lines) for lines in summary if lines) + "\n",
                    required=tuple(required), artifact=artifact, gap_ids=tuple(g["id"] for g in found), language=lang)


def block(root: Path, task: str, result: Mapping[str, Any] | None = None) -> tuple[str, str]:
    """The owner block for `task` and the first 8 hex digits of the SHA-256 of its body."""
    delivery = _build(root, task, result)
    return delivery.block, delivery.sha8


def delivery(root: Path, task: str, result: Mapping[str, Any] | None = None) -> Delivery:
    """The delivery for `task` as the files give it now, written nowhere: what `Delivery.problems` holds a questions file to."""
    return _build(root, task, result)


def deliver(root: Path, task: str, result: Mapping[str, Any] | None = None) -> Delivery:
    """`_build`, stored: the full block at `.lapis/owner/<task>.md` and, kept as it was shown, at `<task>.<sha8>.md`; the
    summary at `<task>.summary.md`; the gaps the block lists recorded under its digest. A folder that cannot be written is
    told on stderr; the delivery comes back either way."""
    root = Path(root)
    delivery = _build(root, task, result)
    try:
        requirements.write_atomic(path(root, task), delivery.block)
        if not artifact_path(root, task, delivery.sha8).exists():
            requirements.write_atomic(artifact_path(root, task, delivery.sha8), delivery.block)
        requirements.write_atomic(summary_path(root, task), delivery.summary)
    except OSError as exc:
        print(f"lapis-design owner: {path(root, task)} cannot be written: {exc}", file=sys.stderr)
    gaps.record(root, task, delivery.sha8, list(delivery.gap_ids))
    return delivery


def write(root: Path, task: str, result: Mapping[str, Any] | None = None) -> tuple[str, str]:
    """`deliver`, as the full block and its digest."""
    delivery = deliver(root, task, result)
    return delivery.block, delivery.sha8
