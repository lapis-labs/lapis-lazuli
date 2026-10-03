"""Waiting for the user: a run that stopped to ask questions, recorded in two files.

Some runs must stop and ask: grilling before the plan, or the plan's approval, in a harness where an
operator relays a person's answers. The agent writes its open questions to `.lapis/questions/<task>.md`
and stops; the answers go to `.lapis/answers/<task>.md`, where the plan's `context.other` and
`claims.declared` can cite them. `lapis-design next` says `waiting-for-user` while the latest questions
are unanswered, that is, the questions file is the newer of the two, and the exit gate lets that stop pass
without counting a continue.

Two guards keep a question from becoming a way to stop. A questions file with fewer than two words (a
heading line is not text) does not count. And the gate lets a run wait for at most `CAP["plan"]` sets of
questions before a plan exists and `CAP["approval"]` after one; a set the gate has let pass is counted in
`.lapis/gate/<task>.json` under `waits`. A set is one text as written once: rewriting the file, even to the
same words, is a new set. Past the cap `next` goes back to the step it would name, and the gate continues
the agent with it.

Stdlib only: the stop hook imports this at the end of every turn.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

STEP = "waiting-for-user"
CAP = {"plan": 2, "approval": 1}      # sets of questions the gate lets pass, by whether a plan exists
MIN_WORDS = 2
_LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_WORD = re.compile(r"[^\W_]+")        # a run of letters or digits of any script


def questions_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "questions" / f"{task}.md"


def answers_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "answers" / f"{task}.md"


def words(text: str) -> int:
    """Words in `text`, not counting a markdown heading line or a list marker."""
    return sum(len(_WORD.findall(_LIST_MARK.sub("", line))) for line in text.splitlines()
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


def pending(root: Path, task: str, phase: str, waits: Any = None) -> dict[str, Any] | None:
    """The set of questions the run waits on, or None.

    `phase` is `plan` while no plan exists, else `approval`; `waits` is what the gate recorded
    (`{"plan": n, "approval": n, "last": id}`). The set is `{"phase", "questions", "answers", "id",
    "counted"}`; `counted` says whether the gate has already let this very set pass."""
    waits = waits if isinstance(waits, dict) else {}
    asked = _read(questions_path(root, task))
    if asked is None or words(asked[0]) < MIN_WORDS:
        return None
    replied = _read(answers_path(root, task))
    if replied is not None and words(replied[0]) >= 1 and replied[1] >= asked[1]:
        return None
    set_id = f"{hashlib.sha256(asked[0].encode('utf-8')).hexdigest()[:12]}-{asked[1]}"
    counted = waits.get("last") == set_id
    if not counted and _count(waits, phase) >= CAP[phase]:
        return None
    return {"phase": phase, "questions": questions_path(root, task).relative_to(root).as_posix(),
            "answers": answers_path(root, task).relative_to(root).as_posix(), "id": set_id, "counted": counted}


def counted(waits: Any, found: Mapping[str, Any]) -> dict[str, Any]:
    """`waits` with the set `found` added, once."""
    waits = dict(waits) if isinstance(waits, dict) else {}
    if waits.get("last") != found["id"]:
        waits[found["phase"]] = _count(waits, found["phase"]) + 1
        waits["last"] = found["id"]
    return waits


def why(task: str, found: Mapping[str, Any], then: str) -> str:
    return (f"The questions in {found['questions']} have no answer yet, so the run waits for the user: stop with "
            f"them as your last message. When the answers come, record them in {found['answers']}, cite them from "
            f"the plan (`context.other`, `claims.declared`), and run `lapis-design next --task {task}` again; the "
            f"step after the answers is {then}. A run may wait for {CAP['plan']} sets of questions before a plan "
            f"exists and {CAP['approval']} after; past that the exit gate continues it.")
