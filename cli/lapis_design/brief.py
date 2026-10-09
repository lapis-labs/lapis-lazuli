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

The questions are capped, and the cap is counted where the files show it. A round is the list items under one
answers heading: `## Answers` is round 1, `## Answers (round 2)` round 2; more than `PER_ROUND` items under one,
or a round past `ROUNDS`, sends the run back to `brief`. The questions file `waiting.py` reads holds the round
being asked, and its numbered questions are counted the same way. The count is of list items, tagged or not.

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
_ROUND = re.compile(r"\bround\s*(\d+)", re.IGNORECASE)
_ROUND_LINE = re.compile(r"^\W*round\s+(\d+)\s+of\s+\d+", re.IGNORECASE | re.MULTILINE)   # "Round 2 of 2."
_NUMBERED = re.compile(r"^\s{0,3}\**Q?\d+[.):]\**\s+\S", re.IGNORECASE)                 # a numbered question


def _name(title: str) -> str:
    """A heading's first word in lower case ("" for a heading with no word)."""
    words = re.findall(r"[^\W\d_]+", title.lower())
    return words[0] if words else ""


def sections(text: str) -> dict[str, str]:
    """The body under each heading, keyed by the heading's first word in lower case: the lines up to the next
    heading of the same or a higher level, so a title above and subheadings below take nothing away. A repeated
    heading adds to its first."""
    lines = text.splitlines()
    heads = [(i, len(m.group(1)), m.group(2)) for i, line in enumerate(lines) if (m := _HEADING.match(line))]
    found: dict[str, list[str]] = {}
    for n, (start, level, title) in enumerate(heads):
        end = next((i for i, other, _ in heads[n + 1:] if other <= level), len(lines))
        found.setdefault(_name(title), []).extend(lines[start + 1:end])
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
    for item in (*items(body["answers"]), *items(body.get("asks", ""))):     # `## Asks` holds the asks the run answered
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


def _top_level(lines: list[str]) -> int:
    """The list items among `lines` that sit at the outermost indent, so a sub-list inside an answer adds nothing."""
    indents = [len(line) - len(line.lstrip()) for line in lines if _ITEM.match(line)]
    return indents.count(min(indents)) if indents else 0


def answer_rounds(text: str) -> dict[int, int]:
    """The list items in each round's answers, by round number. `## Answers` is round 1 and `## Answers (round 2)`
    round 2; a `Round N` subheading inside an answers section starts that round there."""
    lines = text.splitlines()
    heads = [(i, len(m.group(1)), m.group(2)) for i, line in enumerate(lines) if (m := _HEADING.match(line))]
    counts: dict[int, int] = {}
    covered = 0                                    # an answers heading inside another answers section is read there
    for n, (start, level, title) in enumerate(heads):
        if start < covered or _name(title) != "answers":
            continue
        end = next((i for i, other, _ in heads[n + 1:] if other <= level), len(lines))
        covered = end
        number = int(named.group(1)) if (named := _ROUND.search(title)) else 1
        chunk: list[str] = []
        for line in lines[start + 1:end]:
            sub = _HEADING.match(line)
            if sub and (named := _ROUND.search(sub.group(2))):
                counts[number] = counts.get(number, 0) + _top_level(chunk)
                number, chunk = int(named.group(1)), []
            else:
                chunk.append(line)
        counts[number] = counts.get(number, 0) + _top_level(chunk)
    return counts


def rounds_problem(text: str, where: str) -> str | None:
    """How the answers in `text` break the cap, or None when they keep it: at most `PER_ROUND` items in a round and no
    round past `ROUNDS`. A line such as `Round 2 of 2.` also names the round the record is in."""
    counts = answer_rounds(text)
    latest = max([*counts, *(int(number) for number in _ROUND_LINE.findall(text))], default=0)
    if latest > ROUNDS:
        return (f"{where} records a round {latest}, and the brief has at most {ROUNDS} rounds: after round {ROUNDS} go on, "
                "with what is still open as `[open]` or an `[assumed]` default with its `Basis:`")
    for number in sorted(counts):
        if counts[number] > PER_ROUND:
            return (f"{where} holds {counts[number]} answers in round {number}, and a round holds at most {PER_ROUND}: "
                    f"rank what is still open by how much the answer changes the page, keep the top {PER_ROUND}, and "
                    "leave out what the request or a lookup already answered (that is a `Found` line)")
    return None


def cap_problem(root: Path, task: str) -> str | None:
    """How `.lapis/answers/<task>.md` under `root` breaks the cap on questions, or None when it keeps it."""
    path = waiting.answers_path(root, task)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return rounds_problem(text, path.relative_to(root).as_posix())


def questions_problem(root: Path, task: str) -> str | None:
    """How `.lapis/questions/<task>.md` under `root` breaks the cap, or None when it keeps it. The file holds the
    round being asked: its numbered questions, those under a `Questions` heading when it has one."""
    path = waiting.questions_path(root, task)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    body = sections(text).get("questions", "")
    asked = sum(1 for line in (body if body.strip() else text).splitlines() if _NUMBERED.match(line))
    if asked > PER_ROUND:
        return (f"{path.relative_to(root).as_posix()} numbers {asked} questions, and a round asks at most {PER_ROUND}: "
                f"keep the top {PER_ROUND} by how much the answer changes the page, drop the rest, and write the file again")
    return None


def owed(root: Path, task: str, planned: bool) -> str | None:
    """What the `brief` step says while the brief is not in order, or None when it is: the record is missing or no
    record (`why`), or its rounds break the cap on questions (`over_why`)."""
    if reason := record_problem(root, task):
        return why(task, reason, planned)
    if over := cap_problem(root, task):
        return over_why(task, over)
    return None


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
            "[assumed] (your own choice, followed by `Basis:` and the reason) or [open]; a second round goes under its "
            "own `## Answers (round 2)` heading. Keep only user-given taste in .lapis/taste.md; otherwise write "
            "`Taste: not given` under Found and its answer as [open], never [assumed]. Then cite the record from the "
            "plan's `context.other` and carry what it settled into `brief`, `claims`, and `world_materials`; never put an "
            "[assumed] answer in `claims.known` or `claims.declared`. A repair of named findings needs no brief: write "
            "its plan with `mode: repair`.")


def over_why(task: str, reason: str) -> str:
    """What the `brief` step says when the questions or answers break the cap; `reason` is from `cap_problem` or
    `questions_problem`."""
    record = waiting.answers_path(Path("."), task).as_posix()
    questions = waiting.questions_path(Path("."), task).as_posix()
    return (f"The brief is over its question cap: {reason}. The cap is {PER_ROUND} questions a round and {ROUNDS} rounds. "
            f"A round is the list items under one answers heading of {record} (`## Answers` is round 1, "
            f"`## Answers (round 2)` round 2), or the numbered questions of the one message in {questions}. Fix the "
            f"file, then run `lapis-design next --task {task}` again.")
