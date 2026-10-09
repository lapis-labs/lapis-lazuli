"""Waiting for the user: a run that stopped to ask questions, recorded in two files.

Some runs must stop and ask: the brief before the plan (`brief.py`), the direction conversation (`direction.py`), one
doubt during the work (`asks.py`), or the approval of the slice. In a harness where an operator relays a person's
answers, the agent writes its open questions to `.lapis/questions/<task>.md` and stops; the answers go to
`.lapis/answers/<task>.md`, the file that is also the brief record, where the plan's `context.other` and
`claims.declared` can cite them. `lapis-design next` says `waiting-for-user` while the latest questions are
unanswered, that is, the questions file is the newer of the two, and the exit gate lets that stop pass without
counting a continue.

A questions file declares its kind on its first non-blank line, `lapis-questions: brief|direction|approval|ask`
(`kind`). The line is a machine line like the owner block's marker: it is no word of the questions. A file without
it does not wait (`unmarked` says which); `next` names the step it would name and tells the run to mark the kind. The
kind decides what the file must hold (`next_step.py`), and which guards below apply: `direction` and `ask` files wait
only in an attended run, since an unattended run answers them itself (`[assumed]` items, never a stop).

Two guards keep a question from becoming a way to stop. A questions file with fewer than two words (a
heading line is not text) does not count. And the gate lets a run wait for at most `CAP["plan"]` sets of
`brief` or `approval` questions before a plan exists and `CAP["approval"]` after one; a set the gate has let pass is
counted in `.lapis/gate/<task>.json` under `waits`. A set is one text as written once: rewriting the file, even to the
same words, is a new set. Past the cap `next` goes back to the step it would name, and the gate continues the agent
with it. `direction` and `ask` sets have their own limits (`direction.py`, `asks.py`) and are never counted here.

Stdlib only: the stop hook imports this at the end of every turn.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Mapping

STEP = "waiting-for-user"
CAP = {"plan": 2, "approval": 1}      # sets of questions the gate lets pass, by whether a plan exists
KINDS = ("brief", "direction", "approval", "ask")
CAPPED = ("brief", "approval")        # the kinds the gate counts against CAP
ATTENDED_ONLY = ("direction", "ask")  # an unattended run answers these itself and never waits on them
MIN_WORDS = 2
ENV = "LAPIS_UNATTENDED"              # the variable `gate.is_unattended` reads; this module imports nothing of ours
_LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_WORD = re.compile(r"[^\W_]+")        # a run of letters or digits of any script
_BLOCK = re.compile(r"^# Owner block: .*?^lapis-owner-block [0-9a-f]{8}[ \t]*$", re.MULTILINE | re.DOTALL)
_KIND = re.compile(r"^[ \t]*lapis-questions:[ \t]*(\S*)[ \t]*$", re.MULTILINE)
_MARKER = re.compile(r"^lapis-owner-block ([0-9a-f]{8})[ \t]*$", re.MULTILINE)


def questions_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "questions" / f"{task}.md"


def answers_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "answers" / f"{task}.md"


def question_text(text: str) -> str:
    """`text` without a pasted owner block (`owner.py`): the block is the CLI's, not the run's question, so its words
    and the addresses it names are neither words nor links of the questions."""
    return _BLOCK.sub("", text)


def carried(text: str) -> str | None:
    """The digest on the last `lapis-owner-block <sha8>` line of `text`: the owner block a questions file carries."""
    found = _MARKER.findall(text)
    return found[-1] if found else None


def declared(text: str) -> str | None:
    """The word after `lapis-questions:` on the first non-blank line of `text`, as written, or None when that line is
    not a kind line."""
    first = next((line for line in text.splitlines() if line.strip()), "")
    found = _KIND.fullmatch(first)
    return found.group(1) if found else None


def kind(text: str) -> str | None:
    """The kind the questions in `text` declare (`brief`, `direction`, `approval`, or `ask`), or None when the first
    non-blank line is no kind line or names another word."""
    found = declared(text)
    return found if found in KINDS else None


def words(text: str) -> int:
    """Words in `text`, not counting a markdown heading line, a list marker, the kind line, or a pasted owner block: a
    questions file that holds only the block asks nothing."""
    return sum(len(_WORD.findall(_LIST_MARK.sub("", line))) for line in _KIND.sub("", question_text(text)).splitlines()
               if not line.lstrip().startswith("#"))


def _read(path: Path) -> tuple[str, int] | None:
    """The text and modification time (ns) of `path`, or None when it cannot be read."""
    try:
        stamp = path.stat().st_mtime_ns
        return path.read_text(encoding="utf-8", errors="replace"), stamp
    except OSError:
        return None


def _count(waits: Mapping[str, Any], phase: str) -> int:
    value = waits.get(phase)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def counts(path: Path) -> bool:
    """Whether the questions file at `path` has enough text to count as questions."""
    asked = _read(path)
    return asked is not None and words(asked[0]) >= MIN_WORDS


def current(root: Path, task: str) -> dict[str, Any] | None:
    """The questions file as it stands, answered or not, or None when there is none that counts: `{"text", "kind"
    (None when unmarked), "id", "asked_ns", "answered", "answered_ns" (None until answered)}`. The id names this text
    as written once: a hash and the file's modification time."""
    asked = _read(questions_path(root, task))
    if asked is None or words(asked[0]) < MIN_WORDS:
        return None
    replied = _read(answers_path(root, task))
    answered = replied is not None and words(replied[0]) >= 1 and replied[1] >= asked[1]
    return {"text": asked[0], "kind": kind(asked[0]), "asked_ns": asked[1], "answered": answered,
            "answered_ns": replied[1] if answered else None,
            "id": f"{hashlib.sha256(asked[0].encode('utf-8')).hexdigest()[:12]}-{asked[1]}"}


def unmarked(root: Path, task: str) -> str | None:
    """The questions file's path, relative to `root`, while it holds unanswered questions of no declared kind: such a
    file does not wait. None when there is none, or it has a kind, or it is answered."""
    found = current(root, task)
    if found is None or found["kind"] is not None or found["answered"]:
        return None
    return questions_path(root, task).relative_to(root).as_posix()


def pending(root: Path, task: str, phase: str, waits: Any = None, env: Mapping[str, str] = os.environ
            ) -> dict[str, Any] | None:
    """The set of questions the run waits on, or None.

    `phase` is `plan` while no plan exists, else `approval`; `waits` is what the gate recorded
    (`{"plan": n, "approval": n, "last": id}`). The set is `{"phase", "kind", "questions", "answers", "id",
    "counted"}`; `counted` says whether the gate has already let this very set pass. A file of no declared kind does
    not wait, nor does a `direction` or `ask` file in an unattended run, nor a `brief` or `approval` set past `CAP`."""
    waits = waits if isinstance(waits, dict) else {}
    found = current(root, task)
    if found is None or found["answered"] or found["kind"] is None:
        return None
    if found["kind"] in ATTENDED_ONLY and env.get(ENV) == "1":
        return None
    counted = waits.get("last") == found["id"]
    if found["kind"] in CAPPED and not counted and _count(waits, phase) >= CAP[phase]:
        return None
    return {"phase": phase, "kind": found["kind"], "questions": questions_path(root, task).relative_to(root).as_posix(),
            "answers": answers_path(root, task).relative_to(root).as_posix(), "id": found["id"], "counted": counted}


def counted(waits: Any, found: Mapping[str, Any]) -> dict[str, Any]:
    """`waits` with the set `found` added, once. Only `brief` and `approval` sets count against `CAP`."""
    waits = dict(waits) if isinstance(waits, dict) else {}
    if waits.get("last") != found["id"]:
        if found.get("kind") in CAPPED:
            waits[found["phase"]] = _count(waits, found["phase"]) + 1
        waits["last"] = found["id"]
    return waits


def why(task: str, found: Mapping[str, Any], then: str) -> str:
    """What the `waiting-for-user` step says: stop with the questions, and what to record when the answers come."""
    asked = found.get("kind")
    if asked == "brief":
        after = (f"record them in {found['answers']} as the brief record (a `## Found` and an `## Answers` section, "
                 f"as the lps-brief skill describes), and run `lapis-design next --task {task}` again; it names the "
                 "step after the brief.")
    elif asked == "direction":
        after = (f"record each answer in {found['answers']} under `## Direction <n>` as `- [declared] <item id> <name>: "
                 "<choice> — \"<their words>\"`, or as one untagged `- Defaults accepted (direction <n>): \"<their "
                 f"words>\"` line, keeping what the file holds, and run `lapis-design next --task {task}` again; the "
                 f"step after the answers is {then}.")
    elif asked == "ask":
        after = (f"record the decision in {found['answers']} under `## Asks` as `- [declared] Ask <trigger>: <the "
                 "decision, in their words>`, or as `- [declared] Ask <trigger>: default — \"<their words>\"` when they "
                 f"take your default, and run `lapis-design next --task {task}` again; the step after the answer is "
                 f"{then}.")
    else:
        after = (f"add them to {found['answers']} under a heading of their own, keeping what the file holds, cite "
                 f"them from the plan (`context.other`, `claims.declared`), and run `lapis-design next --task "
                 f"{task}` again; the step after the answers is {then}.")
    limit = (f" A run may wait for {CAP['plan']} sets of questions before a plan exists and {CAP['approval']} after; "
             "past that the exit gate continues it." if asked in CAPPED else "")
    return (f"The questions in {found['questions']} have no answer yet, so the run waits for the user: stop with "
            f"them as your last message. When the answers come, {after}{limit}")
