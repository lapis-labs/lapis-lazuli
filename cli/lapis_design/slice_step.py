"""The slice: the owner approves a rendered first view and one core section before the rest is built.

In an attended create run (`LAPIS_UNATTENDED` unset) with no slice sealed in `.lapis/state/<task>.json`, `next` asks
for the step `slice` as soon as the plan steps pass. The step asks for the first view plus the one section the brief
puts first, captured at 390 and 1440, reviewed, and shown to the owner in the approval questions. Approval questions
that link no page, while no slice is sealed, return `slice` instead of waiting. Copy stays provisional until the owner
has seen it rendered.

A harness with a question tool may show 2-3 candidates that differ in composition or concept, not in order. Each is a
`direction: new` page of the draft record and all are linked in the questions; the owner picks one or gives feedback.
A pick is the maker's transcription of the owner's reply, `[declared] Slice: <address> - <their words>`, in the answers
file (`requirements.picks`). Feedback without a pick seals nothing. One linked page needs no pick.

`check` seals when all of these hold: the questions were asked and answered (the answers file is newer than the
questions file), `draft check` passes for what they link, one linked `direction: new` page is the chosen one, and the
plan says `approval: {state: approved}`. The seal is `state.slice` (`integrity.seal_slice`): the chosen address, every
candidate when there were several, and the digests of the draft record, the critic packet, the questions, the
answers, and the requirement record. Protected changes made afterwards are flagged `after_slice` in the change log and
listed in the owner block. Unattended runs skip the slice.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import yaml

from lapis_design import draft, gate, integrity, requirements, waiting

STEP = "slice"


def text(task: str) -> str:
    """What the `slice` step says while nothing has been shown and asked."""
    return (
        "Build the first view and the one section the brief puts first, not the whole page. Serve it with "
        f"`lapis-design preview start --task {task}` (a server that outlives this turn, so the owner's link is not "
        "dead when they open it) and capture both at 390 and "
        f"1440. Record them in `.lapis/drafts/{task}.yaml` with `direction: new`. Run the critic on `lapis-design "
        f"critic packet`. Run `lapis-design draft check --task {task}`, which writes the owner block to "
        f".lapis/owner/{task}.md, with the capture files the owner can open without a server. Then ask for approval in "
        f"`.lapis/questions/{task}.md`, linking the page and pasting "
        "the owner block unchanged, and stop. Copy is provisional until the owner has seen it rendered. If this "
        "harness has a question tool, show 2-3 candidates that differ in composition or concept (real alternatives, "
        "not reorderings), each its own `direction: new` page in the draft record and all of them linked in the "
        "questions, and ask the owner to pick one or give feedback; record a pick as `- [declared] Slice: <the "
        f"page's address exactly as linked> — <their words>` under a heading of its own in `.lapis/answers/{task}.md`. "
        "Without a question tool, show one slice. When the owner approves, record `approval: {state: approved}` in "
        f"the plan and run `lapis-design next --task {task}` again: it seals the slice.")


def step(task: str, why: str | None = None) -> dict:
    return {"id": STEP, "why": why or text(task), "command": f"lapis-design draft check --task {task}"}


def sealed(root: Path, task: str) -> dict | None:
    """`state.slice` of `task`, or None while no slice is sealed."""
    state = integrity.read_state(root, task)
    found = state.get("slice") if state else None
    return found if isinstance(found, dict) else None


def owed(root: Path, task: str, plan: Any, env: Mapping[str, str] = os.environ) -> bool:
    """Whether a slice is still to be approved: an attended create run with no sealed slice."""
    return (isinstance(plan, dict) and plan.get("mode") == "create" and not gate.is_unattended(env)
            and sealed(root, task) is None)


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


def check(root: Path, task: str, plan: Any, env: Mapping[str, str] = os.environ) -> str | None:
    """None when no slice is owed or the one asked for has just been sealed, else what the `slice` step says."""
    if not owed(root, task, plan, env):
        return None
    questions = waiting.questions_path(root, task)
    if not waiting.counts(questions) or waiting.pending(root, task, "approval") is not None:
        return text(task)                                  # nothing was asked yet, or the owner has not answered
    shown = draft.links(root, task)
    if not shown:
        return ("The owner answered, but the questions link no rendered page, so no slice was shown. " + text(task))
    errors, _ = draft.check(root, task, asked=shown)
    if errors:
        return "The slice cannot be sealed: " + "; ".join(errors[:3]) + ". Fix the draft record and ask again."
    candidates = [p for p in pages(root, task) if p["url"] in shown and p.get("direction") == "new"]
    if not candidates:
        return ("No page the questions link is a `direction: new` page of the draft record, so no slice was shown. "
                + text(task))
    chosen = candidates[0]
    if len(candidates) > 1:
        picked = [url for url in requirements.picks(root, task) if url in {p["url"] for p in candidates}]
        if not picked:
            return (f"The questions show {len(candidates)} candidates ({', '.join(p['url'] for p in candidates)}) and "
                    "the owner's answer names none of them. If they picked one, record it in the answers file as `- "
                    "[declared] Slice: <the page's address exactly as linked> — <their words>`. If they gave feedback, "
                    "revise the candidates (or the one you build on, as `direction: iteration`), show them, and ask "
                    "again.")
        chosen = next(p for p in candidates if p["url"] == picked[-1])
    if (plan.get("approval") or {}).get("state") != "approved":
        return ("The owner has answered the questions about the slice, but the plan does not say `approval: {state: "
                "approved}`. If they approved the slice, record that in the plan. If they asked for changes, revise "
                "the changed area as `direction: iteration`, show it, and ask again.")
    row = {"url": chosen["url"], **({"candidates": [p["url"] for p in candidates]} if len(candidates) > 1 else {}),
           "draft_sha256": _digest(draft.path(root, task)), "packet_sha256": _packet(root, chosen),
           "questions_sha256": _digest(questions), "answers_sha256": _digest(waiting.answers_path(root, task)),
           "requirements_sha256": requirements.sha256(root, task)}
    try:
        integrity.seal_slice(root, task, row)
    except Exception as exc:                               # the seal is recorded or the step stays; a run goes on
        return f"The slice could not be recorded: {type(exc).__name__}: {exc}. Run `lapis-design next --task {task}` again."
    return None
