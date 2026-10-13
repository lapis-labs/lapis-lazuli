"""The language of the questions: a run asks its owner in the owner's language.

A questions file for an owner whose request is in Korean, Japanese, or Chinese and which is plainly Latin text (the
English template copied as it stands) goes back to the run with a reason instead of waiting. The check only reads what
the CLI already holds of the request: the rows of the owner's brief files in the requirement record (`requirements.py`),
else the `[declared]` items of the brief record. A request with no clear Hangul, kana, or Han script, or one the CLI holds
no text of, is not checked, and neither is a questions file in any script other than Latin.
Code, links, paths, the kind line, and a pasted owner block (`waiting.question_text`) are no words of either side.

Stdlib only: the stop hook imports this through `next_step`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from lapis_design import waiting

REQUEST_SHARE = 0.5      # the share of a request's letters in Hangul, kana, or Han that makes its script clear
QUESTION_SHARE = 0.75    # the share of a questions file's letters in Latin that makes it "mostly Latin"
MIN_REQUEST = 10         # letters a request needs before its script is read
MIN_QUESTIONS = 20       # letters a questions file needs before its script is read

_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)
_ADDRESS = re.compile(r"https?://\S+|(?<![\w/])[\w.~-]+(?:/[\w.~-]+)+/?")   # a link or a path of two or more parts
_ITEM = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+(.*)$")
_KIND_LINE = re.compile(r"^[ \t]*lapis-questions:.*$", re.MULTILINE)
_DECLARED = re.compile(r"^[*_`]*\[declared\]", re.IGNORECASE)


def _bare(text: str) -> str:
    """`text` without code and addresses: what is left is written words."""
    return _ADDRESS.sub(" ", _CODE.sub(" ", text))


def _counts(text: str) -> dict[str, int]:
    """The letters of `text` by script: `hangul`, `kana`, `han`, `latin`; every other letter is not counted."""
    found = {"hangul": 0, "kana": 0, "han": 0, "latin": 0}
    for char in _bare(text):
        if not char.isalpha():
            continue
        code = ord(char)
        if 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F:
            found["hangul"] += 1
        elif 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF:
            found["kana"] += 1
        elif 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0xF900 <= code <= 0xFAFF:
            found["han"] += 1
        elif code < 0x250:
            found["latin"] += 1
    return found


def request_language(texts: list[str]) -> str | None:
    """The language of a request whose script is clearly Hangul, kana, or Han (`Korean`, `Japanese`, `Chinese`), or None
    when it is not clear: too few letters, or less than `REQUEST_SHARE` of them in those scripts."""
    found = _counts("\n".join(texts))
    cjk = found["hangul"] + found["kana"] + found["han"]
    total = cjk + found["latin"]
    if cjk < MIN_REQUEST or cjk < REQUEST_SHARE * total:
        return None
    if found["hangul"] >= found["kana"] and found["hangul"] >= found["han"]:
        return "Korean"
    return "Japanese" if found["kana"] else "Chinese"


def mostly_latin(text: str) -> bool:
    """Whether the questions in `text` are plainly Latin text: at least `MIN_QUESTIONS` letters, `QUESTION_SHARE` of them Latin."""
    found = _counts(waiting.question_text(_KIND_LINE.sub("", text)))
    total = sum(found.values())
    return total >= MIN_QUESTIONS and found["latin"] >= QUESTION_SHARE * total



def request_texts(root: Path, task: str) -> list[str]:
    """What the CLI holds of the owner's request: the rows of the owner's own brief files in the requirement record (code
    blocks apart), and when it holds none, the top-level `[declared]` items of the brief record. A run's own wording of a
    question, which a `[declared]` item carries beside the owner's answer, never outweighs the owner's files."""
    from lapis_design import requirements

    try:
        rows = json.loads(requirements.record_path(root, task).read_text(encoding="utf-8")).get("rows")
    except (OSError, ValueError, AttributeError):
        rows = None
    owner = [row["text"] for row in rows if isinstance(row, dict) and isinstance(row.get("text"), str)
             and row.get("kind") not in ("declared", "code")] if isinstance(rows, list) else []
    if owner:
        return owner
    try:
        record = waiting.answers_path(root, task).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [match.group(1) for line in record.splitlines() if (match := _ITEM.match(line)) and _DECLARED.match(match.group(1))]


def problem(root: Path, task: str) -> str | None:
    """Why the questions file of `task` under `root` is not in its owner's language, or None when it is, or when the
    CLI holds no request in a clear Hangul, kana, or Han script to compare it with."""
    try:
        questions = waiting.questions_path(root, task).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not mostly_latin(questions):
        return None
    language = request_language(request_texts(root, task))
    if language is None:
        return None
    return (f"the owner's request is in {language} and the questions are in Latin script. Write the questions, the "
            f"findings, and your reply in {language}: the template in the lps-brief skill's references/questions.md is a "
            "shape to fill, not text to copy")
