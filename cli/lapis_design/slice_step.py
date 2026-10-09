"""The slice: the owner approves a rendered first view and one core section before the rest is built.

In an attended create run (`LAPIS_UNATTENDED` unset) with no slice sealed in `.lapis/state/<task>.json`, `next` asks for
the step `slice` as soon as the plan steps pass. The step asks for the first view plus the one section the brief puts
first, captured at 390 and 1440, reviewed, and shown to the owner in questions of kind `approval`. Such questions that
link no page, while no slice is sealed, return `slice` instead of waiting, and so does a shown page taller than
`MAX_HEIGHT` px at 1440. Copy stays provisional until the owner has seen it rendered. The slice is one page: the choice
among several roughs is made earlier, at the second direction turn.

From the first time `next` names `slice` until the slice is sealed or skipped, the agent is held (`hold`, enforced by
the pre-write hook in `order.py`): it may write only the files its slice page declares in `.lapis/drafts/<task>.yaml`
(`direction: new`, with its `url` and `sources`, at most `MAX_FILES`). The slice must also reach the owner as a waiting
`approval` question that links the page and carries the current owner block: it is overdue after `MINUTES` minutes or
`WRITES` page writes since the clock started (`overdue`), and from then on every page write is refused until that
question exists. The clock starts when `next` first names `slice` (`state.slice_since`), at every owner reply that asks
for a revision, and at every answered set of questions of any kind (the log of `asks.py`). An untagged
`- Slice skipped: "<owner words>"` line in the answers file lifts the hold and the step.

`check` seals when all of these hold: the questions were asked and answered (the answers file is newer than the
questions file), `draft check` passes for what they link, one linked `direction: new` page is the slice, the plan says
`approval: {state: approved}`, the owner acknowledged the gaps the questions' owner block listed (`gaps.py`), and every
core finding the critic left open is closed by a fresh critic report or decided by the owner
(`- [declared] Ask finding-vs-decision: <rule id> — <their words>`). An answered but unapproved slice starts the next
round (`state.slice_rounds`): the hold and the clock go on. The seal is `state.slice` (`integrity.seal_slice`): the
address, the digests of the draft record, the critic packet, the questions, the answers, and the requirement record, and
the protected values. Protected changes made afterwards are flagged `after_slice` in the change log and listed in the
owner block. Unattended runs skip the slice.
"""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from lapis_design import asks, draft, gaps, gate, integrity, order, requirements, waiting

STEP = "slice"
MAX_FILES = 12                 # files a slice page may declare [provisional: the next HITL measures it]
MAX_HEIGHT = 3600              # px at 1440: four 900 px screens
MINUTES = 60                   # from the start of the clock to a waiting question
WRITES = 40                    # page writes from the start of the clock to a waiting question
_SKIPPED = re.compile(r"^[ \t]*[-*+][ \t]+Slice skipped[ \t]*:[ \t]*(\S.*)$", re.IGNORECASE | re.MULTILINE)
_STAMP = "%Y-%m-%dT%H:%M:%SZ"


def text(task: str) -> str:
    """What the `slice` step says while nothing has been shown and asked."""
    return (
        "Build the first view and the one section the brief puts first, not the whole page, and show it to the owner "
        "before building more. First declare the slice page in "
        f".lapis/drafts/{task}.yaml with `direction: new`, its `url`, and its `sources` (at most {MAX_FILES} files): "
        "until the owner has seen the slice you may write only those files, and a write to any other page file is "
        f"refused. Serve it with `lapis-design preview start --task {task}` (a server that outlives this turn, so the "
        "owner's link is not dead when they open it) and capture it at 390 and "
        f"1440, at most {MAX_HEIGHT:,} px tall at 1440. Run the critic on `lapis-design "
        f"critic packet`. Run `lapis-design draft check --task {task}`, which writes the owner block to "
        f".lapis/owner/{task}.md, with the capture files the owner can open without a server. Then ask for approval in "
        f".lapis/questions/{task}.md, whose first line is `lapis-questions: approval`, linking the page and pasting "
        f"the owner block unchanged, and stop, within {MINUTES} minutes or {WRITES} page writes: past either, every page "
        "write is refused until that question exists. Copy is provisional until the owner has seen it rendered. The "
        "block lists the open core findings and the decisions the owner did not make: put each core finding to them as "
        "a decision. When the owner approves, record `approval: {state: approved}` in "
        f"the plan and their acknowledgment of the gaps in the answers file, and run `lapis-design next --task {task}` "
        "again: it seals the slice. When they ask for changes, `next` names the next round.")


def step(task: str, why: str | None = None) -> dict:
    return {"id": STEP, "why": why or text(task), "command": f"lapis-design draft check --task {task}"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(_STAMP)


def _parse(stamp: Any) -> datetime | None:
    try:
        return datetime.strptime(stamp, _STAMP).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def sealed(root: Path, task: str) -> dict | None:
    """`state.slice` of `task`, or None while no slice is sealed."""
    state = integrity.read_state(root, task)
    found = state.get("slice") if state else None
    return found if isinstance(found, dict) else None


def skipped(root: Path, task: str) -> str | None:
    """The owner's words of the last `- Slice skipped: "<words>"` line of the answers file, or None."""
    found = _SKIPPED.findall(_read(waiting.answers_path(root, task)))
    return " ".join(found[-1].split()) if found else None


def owed(root: Path, task: str, plan: Any, env: Mapping[str, str] = os.environ) -> bool:
    """Whether a slice is still to be approved: an attended create run with no sealed slice that the owner did not skip."""
    return (isinstance(plan, dict) and plan.get("mode") == "create" and not gate.is_unattended(env)
            and sealed(root, task) is None and skipped(root, task) is None)


def _digest(file: Path) -> str | None:
    try:
        return hashlib.sha256(file.read_bytes()).hexdigest()
    except OSError:
        return None


def pages(root: Path, task: str) -> list[dict]:
    """The pages of the draft record as written, without judging them (`draft.check` does)."""
    try:
        doc = yaml.safe_load(draft.path(root, task).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    found = doc.get("pages") if isinstance(doc, dict) else None
    return [p for p in found or () if isinstance(p, dict) and isinstance(p.get("url"), str)]


def critic_report(page: Mapping[str, Any]) -> str | None:
    """The path of the critic report a draft page names, if it names one."""
    critic = (page.get("review") or {}).get("critic") if isinstance(page.get("review"), dict) else None
    report = critic.get("report") if isinstance(critic, dict) else None
    return report if isinstance(report, str) else None


def _packet(root: Path, page: Mapping[str, Any]) -> str | None:
    """The packet digest the chosen page's critic report names (`target.packet.sha256`), if it names one."""
    try:
        report = json.loads((root / critic_report(page)).read_text(encoding="utf-8"))
        found = report["target"]["packet"]["sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return found if isinstance(found, str) else None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def height(root: Path, page: Mapping[str, Any]) -> int | None:
    """The document height at 1440: the largest `rect.y + rect.h` among the boxes of the page's extracts."""
    review = page.get("review") if isinstance(page.get("review"), dict) else {}
    bottoms = []
    for name in review.get("extracts") or ():
        for view in (_json(root / name) or {}).get("viewports") or ():
            if isinstance(view, dict) and view.get("width") == 1440:
                for box in view.get("boxes") or ():
                    rect = box.get("rect") if isinstance(box, dict) else None
                    if isinstance(rect, dict) and all(isinstance(rect.get(k), (int, float)) for k in ("y", "h")):
                        bottoms.append(rect["y"] + rect["h"])
    return round(max(bottoms)) if bottoms else None


def tall(root: Path, task: str, shown: list[str]) -> str | None:
    """What `slice` says when a shown `direction: new` page is taller than `MAX_HEIGHT` px at 1440, else None: the slice is
    the first view and the one section the brief puts first, not the page."""
    for page in pages(root, task):
        found = height(root, page) if page["url"] in shown and page.get("direction") == "new" else None
        if found is not None and found > MAX_HEIGHT:
            return (f"The page {page['url']} is {found:,} px tall at 1440, and a slice is at most {MAX_HEIGHT:,}: cut it to "
                    "the first view and the one section the brief puts first, capture it again, review it, and ask again. "
                    "The rest is built after the owner has seen the slice.")
    return None


# ---------------------------------------------------------------- the hold and the clock

def begin(root: Path, task: str) -> None:
    """Start the clock the first time `next` names `slice`: `state.slice_since` and `state.slice_rounds` (1). A state that
    cannot be written is left as it was."""
    state = integrity.read_state(root, task)
    if state is not None and state.get("slice_since"):
        return
    try:
        integrity.mark_slice(root, task, slice_since=_stamp(now()), slice_rounds=1)
    except Exception:                                      # the run goes on; the hold starts at the next call
        return


def clock_start(root: Path, task: str) -> datetime | None:
    """When the clock started: the later of `state.slice_since` and the last time any set of questions was answered
    (`asks.json`), since an answered ask or direction turn touched the owner. None before `next` named `slice`."""
    state = integrity.read_state(root, task) or {}
    started = _parse(state.get("slice_since"))
    if started is None:
        return None
    answered = [moment for entry in asks.load(root, task)["sets"] if (moment := _parse(entry.get("answered")))]
    return max([started, *answered])


def overdue(root: Path, task: str) -> str | None:
    """Why the slice is overdue (`MINUTES` minutes or `WRITES` page writes since the clock started), or None."""
    start = clock_start(root, task)
    if start is None:
        return None
    minutes = (now() - start).total_seconds() / 60
    writes = order.slice_writes(root, task, _stamp(start))
    if minutes > MINUTES:
        return f"{int(minutes)} minutes since {_stamp(start)}"
    if writes >= WRITES:
        return f"{writes} page writes since {_stamp(start)}"
    return None


def waiting_for_owner(root: Path, task: str) -> bool:
    """Whether the slice has reached the owner as a waiting question: questions of kind `approval`, not yet answered,
    that link a `direction: new` page of the draft record and carry the current owner block."""
    from lapis_design import owner

    current = waiting.current(root, task)
    if current is None or current["kind"] != "approval" or current["answered"]:
        return False
    shown = set(draft.links(root, task))
    if not any(p["url"] in shown and p.get("direction") == "new" for p in pages(root, task)):
        return False
    return waiting.carried(current["text"]) == owner.block(root, task)[1]


def hold(root: Path, task: str, plan: Any, env: Mapping[str, str] = os.environ) -> dict | None:
    """The hold on page writes, or None when there is none: `{"pages", "sources", "overdue"}`, the urls and the files of the
    `direction: new` pages of the draft record, and why the slice is overdue (None when it is not, or when the owner
    already has the question). It holds from the first time `next` named `slice` until the slice is sealed or skipped."""
    if not owed(root, task, plan, env) or (integrity.read_state(root, task) or {}).get("slice_since") is None:
        return None
    new = [p for p in pages(root, task) if p.get("direction") == "new"]
    sources = sorted({posixpath.normpath(s.replace("\\", "/")).removeprefix("./")
                      for p in new for s in p.get("sources") or () if isinstance(s, str)})
    late = overdue(root, task)
    return {"pages": [p["url"] for p in new], "sources": sources, "since": _stamp(clock_start(root, task)),
            "overdue": None if late is None or waiting_for_owner(root, task) else late}


# ---------------------------------------------------------------- the seal

def _reply_rows(root: Path, task: str) -> list[str]:
    """The ids of the rows the owner's last reply made: the requirement rows of the answers file's last section."""
    lines = _read(waiting.answers_path(root, task)).splitlines()
    heads = [i + 1 for i, line in enumerate(lines) if line.lstrip().startswith("#")]
    start = heads[-1] if heads else 1
    return [row["id"] for row in requirements.rows(root, task) or ()
            for found in row.get("at") or () if isinstance(found, dict) and found.get("path", "").endswith(f"{task}.md")
            and (found.get("lines") or [0])[0] >= start]


def _round(root: Path, task: str, answered: Mapping[str, Any], page: Mapping[str, Any]) -> int:
    """The number of the round the owner's answered, unapproved set opens: it counts once per set, restarts the clock,
    and records the height of the page the owner just saw."""
    state = integrity.read_state(root, task) or {}
    rounds = state.get("slice_rounds") or 1
    if state.get("slice_set") == answered["id"]:
        return rounds
    heights = dict(state.get("slice_heights") or {})
    if (seen := height(root, page)) is not None:
        heights[str(rounds)] = seen
    rounds += 1
    try:
        integrity.mark_slice(root, task, slice_rounds=rounds, slice_set=answered["id"], slice_since=_stamp(now()),
                             slice_heights=heights)
    except Exception:
        pass
    return rounds


def _decided(root: Path, task: str, rule_id: str) -> bool:
    """Whether the owner decided the finding `rule_id`: a `[declared] Ask finding-vs-decision: <rule id>` item."""
    found = re.compile(rf"^ask\s+finding-vs-decision\s*:\s*{re.escape(rule_id)}(?![\w.-])", re.IGNORECASE)
    try:
        answers = (root / ".lapis" / "answers" / f"{task}.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return any(found.match(body) for _, _, body in requirements._declared_items(answers))


def check(root: Path, task: str, plan: Any, env: Mapping[str, str] = os.environ) -> str | None:
    """None when no slice is owed or the one asked for has just been sealed, else what the `slice` step says."""
    if not owed(root, task, plan, env):
        return None
    begin(root, task)
    questions = waiting.questions_path(root, task)
    current = waiting.current(root, task)
    if current is None or current["kind"] != "approval" or not current["answered"]:
        late = None if waiting_for_owner(root, task) else overdue(root, task)
        return (f"The slice is overdue ({late}): every page write is refused until the owner has the question. Ask now "
                "with what is built, as the questions file of kind `approval` that links the page and pastes the owner "
                "block, and stop. " if late else "") + text(task)       # nothing was asked yet, or the owner has not answered
    shown = draft.links(root, task)
    if not shown:
        return ("The owner answered, but the questions link no rendered page, so no slice was shown. " + text(task))
    candidates = [p for p in pages(root, task) if p["url"] in shown and p.get("direction") == "new"]
    unapproved = (plan.get("approval") or {}).get("state") != "approved"
    rounds = _round(root, task, current, candidates[0]) if unapproved and len(candidates) == 1 else None   # before any return below
    errors, summaries = draft.check(root, task, asked=shown)
    if errors:
        return "The slice cannot be sealed: " + "; ".join(errors[:3]) + ". Fix the draft record and ask again."
    if not candidates:
        return ("No page the questions link is a `direction: new` page of the draft record, so no slice was shown. "
                + text(task))
    if len(candidates) > 1:
        return (f"The slice is one page, and the questions link {len(candidates)} `direction: new` pages "
                f"({', '.join(p['url'] for p in candidates)}). Show the one page: the choice among roughs was the owner's "
                "at the second direction turn.")
    chosen = candidates[0]
    if unapproved:
        rows = _reply_rows(root, task)
        return (f"Slice round {rounds}: the owner answered and did not approve" + (f" (rows {', '.join(rows)})" if rows else "")
                + ". Revise for their reply, within the slice files you declared, show it, and ask again; the hold and the "
                "clock go on. A reply that rejects the composition or the core-object representation is a direction reply "
                "(go back to the second direction turn); a reply that changes a value, copy, or a component is this "
                "revision. If they approved, record `approval: {state: approved}` in the plan.")
    carried = waiting.carried(_read(questions))
    if missing := gaps.unacknowledged(root, task, carried, env):
        return gaps.problem(missing, carried, approval="The slice")
    open_core = [c for s in summaries if s["url"] == chosen["url"] for c in s.get("core_open", ())]
    if undecided := [c for c in open_core if not _decided(root, task, c["rule_id"])]:
        shown_ids = "; ".join(f"{c['rule_id']}: {c['observed']}" for c in undecided[:3])
        return ("The slice cannot be sealed: the critic's report still has "
                f"{len(undecided)} core finding{'s' if len(undecided) != 1 else ''} open ({shown_ids}). A fresh critic report "
                "that no longer lists one closes it; otherwise it is the owner's decision. Put it to them, and record their "
                "answer as `- [declared] Ask finding-vs-decision: <rule id> — <their words>`, then run `next`.")
    seen = height(root, chosen)
    if seen is not None:
        state = integrity.read_state(root, task) or {}
        try:
            integrity.mark_slice(root, task, slice_heights={**(state.get("slice_heights") or {}),
                                                            str(state.get("slice_rounds") or 1): seen})
        except Exception:
            pass
    row = {"url": chosen["url"], "draft_sha256": _digest(draft.path(root, task)), "packet_sha256": _packet(root, chosen),
           "questions_sha256": _digest(questions), "answers_sha256": _digest(waiting.answers_path(root, task)),
           "requirements_sha256": requirements.sha256(root, task)}
    try:
        integrity.seal_slice(root, task, row)
    except Exception as exc:                               # the seal is recorded or the step stays; a run goes on
        return f"The slice could not be recorded: {type(exc).__name__}: {exc}. Run `lapis-design next --task {task}` again."
    return None
