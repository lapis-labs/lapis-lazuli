"""The brief: what a run learns about the subject before it plans, kept in one record.

`lapis-design next` names the step `brief` before `plan` while a create run has no brief record, and the exit
gate continues an unattended run with it. The record is `.lapis/answers/<task>.md`, the file `waiting.py` also
reads the user's replies from, so a relayed run's replies and a run's own answers land in one place, and the
plan cites it from `context.other`.

A record has two sections, `Found` (what the run read or looked up and where, or why nothing was) and
`Answers` (one list item per question). An item that starts with a status tag says where its answer comes
from: `[declared]` (the user said it), `[known]` (a source says it), `[assumed]` (the run's own choice) or
`[open]` (unresolved). An `[assumed]` item gives its `Basis:`, so a run with nobody to ask records what it
guessed and why rather than guessing silently. Nothing here judges whether the answers are good; it keeps
the record from being an empty file, an unsorted copy of replies, or a guess with no reason.

Stdlib only: the stop hook imports this at the end of every turn.
"""
from __future__ import annotations

import re
from pathlib import Path

from lapis_design import waiting

STEP = "brief"
SECTIONS = ("found", "answers")
STATUSES = ("declared", "known", "assumed", "open")
ROUNDS = waiting.CAP["plan"]             # rounds of questions before the plan: what the gate lets wait
PER_ROUND = 6                            # questions in one round

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ITEM = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+(.*)$")
_TAG = re.compile(r"^[*_`]*\[(declared|known|assumed|open)\]", re.IGNORECASE)
_BASIS = re.compile(r"\bbasis\b\s*:\s*(\S.*)", re.IGNORECASE | re.DOTALL)


def sections(text: str) -> dict[str, str]:
    """The body under each heading, keyed by the heading's first word in lower case: the lines up to the next
    heading of the same or a higher level, so a title above and subheadings below take nothing away. A repeated
    heading adds to its first."""
    lines = text.splitlines()
    heads = [(i, len(m.group(1)), m.group(2)) for i, line in enumerate(lines) if (m := _HEADING.match(line))]
    found: dict[str, list[str]] = {}
    for n, (start, level, title) in enumerate(heads):
        end = next((i for i, other, _ in heads[n + 1:] if other <= level), len(lines))
        words = re.findall(r"[^\W\d_]+", title.lower())
        found.setdefault(words[0] if words else "", []).extend(lines[start + 1:end])
    return {name: "\n".join(body) for name, body in found.items()}


def items(body: str) -> list[str]:
    """The list items of `body`; a line that is no item continues the item above it."""
    out: list[str] = []
    for line in body.splitlines():
        match = _ITEM.match(line)
        if match:
            out.append(match.group(1))
        elif out and line.strip() and not _HEADING.match(line):
            out[-1] += "\n" + line.strip()
    return out


def problem(text: str) -> str | None:
    """Why `text` is not a brief record, or None when it is."""
    body = sections(text)
    for name in SECTIONS:
        if waiting.words(body.get(name, "")) < waiting.MIN_WORDS:
            return f"it has no `## {name.capitalize()}` section with text in it"
    for item in items(body["answers"]):
        tag = _TAG.match(item)
        if tag and tag.group(1).lower() == "assumed":
            basis = _BASIS.search(item)
            if not basis or waiting.words(basis.group(1)) < waiting.MIN_WORDS:
                return f"an [assumed] answer gives no `Basis:` (\"{' '.join(item.split())[:60]}\")"
    return None


def record_problem(root: Path, task: str) -> str | None:
    """Why `.lapis/answers/<task>.md` under `root` is not a brief record, or None when it is."""
    path = waiting.answers_path(root, task)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"{path.relative_to(root).as_posix()} does not exist"
    return problem(text)


def why(task: str, reason: str, planned: bool) -> str:
    """What the `brief` step tells the run to do. `planned` says a plan already exists without the record."""
    record = waiting.answers_path(Path("."), task).as_posix()
    questions = waiting.questions_path(Path("."), task).as_posix()
    lead = (f"The plan at .lapis/plans/{task}.yaml is in create mode, and no brief record stands behind it ({reason}). "
            "Write the record from what the request, the project, and the plan already state, and change the plan "
            "wherever the record shows it guessed." if planned else
            f"Before the plan, gather what this design needs; there is no brief record yet ({reason}).")
    return (f"{lead} Follow the lps-brief skill: read the request and the project, look up what can be found about the "
            f"subject, and ask only what neither tells you: at most {PER_ROUND} questions a round and {ROUNDS} rounds, "
            "each with its reason and the default you will assume. Where a person can answer, ask in one message and "
            f"wait. Where an operator relays replies, write the questions to {questions} and stop. With nobody to ask, "
            "answer them yourself. Write the record to "
            f"{record}: a `## Found` section (what you read or looked up, with sources, or why nothing could be) and an "
            "`## Answers` section whose items start with [declared] (the user said it), [known] (a source says it), "
            "[assumed] (your own choice, followed by `Basis:` and the reason) or [open]. Then cite the record from the "
            "plan's `context.other` and carry what it settled into `brief`, `claims`, and `world_materials`; never put an "
            "[assumed] answer in `claims.known` or `claims.declared`. A repair of named findings needs no brief: write "
            "its plan with `mode: repair`.")
