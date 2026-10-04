"""User-given project taste; lexical overlap is a lead, never a verdict or gate."""
from __future__ import annotations

import re
from pathlib import Path

from lapis_design import brief, waiting

SECTIONS = ("likes", "dislikes", "references", "avoid", "feel", "fixed")
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+")
_STOP = frozenset("the and for with from that this not never avoid dislike dislikes like likes want please don't".split())


def path(root: Path) -> Path:
    return root / ".lapis/taste.md"


def parse(text: str) -> dict:
    sections = brief.sections(text)
    parsed = {name: brief.items(sections.get(name, "")) for name in SECTIONS}
    if not parsed["feel"]:
        parsed["feel"] = [line.strip() for line in sections.get("feel", "").splitlines() if line.strip()]
    given = re.search(r"^Given by:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    parsed["given_by"] = given.group(1).strip() if given else ""
    return parsed


def read(root: Path) -> dict:
    try:
        return parse(path(root).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return parse("")


def state(root: Path, task: str) -> str:
    user = read(root)
    if any(user[name] for name in SECTIONS):
        return "given"
    try:
        found = brief.sections(waiting.answers_path(root, task).read_text(encoding="utf-8", errors="replace")).get("found", "")
    except OSError:
        found = ""
    if any(line.strip().removeprefix("- ").casefold() == "taste: not given" for line in found.splitlines()):
        return "not-given"
    return "unrecorded"


def _tokens(text: str) -> set[str]:
    folded = text.casefold()
    words = {word for word in re.findall(r"\w+", _CJK.sub(" ", folded)) if len(word) >= 3 and word not in _STOP}
    # Character bigrams keep Hangul particles and CJK word boundaries from hiding a mention.
    for run in _CJK.findall(folded):
        words.update(run[i:i + 2] for i in range(len(run) - 1))
    return words


def touched(plan: dict, lines: list[str]) -> list[str]:
    direction = plan.get("direction") or {}
    texts = [direction.get("concept", ""), *(direction.get("levers") or []), (direction.get("read") or {}).get("text", "")]
    for exploration in plan.get("explorations") or []:
        texts.append(exploration.get("runner_up_lost", ""))
        for candidate in exploration.get("candidates") or []:
            if candidate.get("name") == exploration.get("chosen"):
                texts.extend((candidate.get("name", ""), candidate.get("note", "")))
    tokens = _tokens("\n".join(texts))
    return [line for line in lines if _tokens(line) & tokens]


def cited(plan: dict) -> bool:
    entry = (plan.get("direction") or {}).get("taste") or {}
    return entry.get("source") == ".lapis/taste.md" and bool(entry.get("follows"))


def done(root: Path, task: str, plan: dict) -> str:
    current = state(root, task)
    if current == "given":
        origin = read(root)["given_by"] or "origin not recorded"
        citation = "cited" if cited(plan) else "not cited"
        return f" Taste was given (.lapis/taste.md, Given by: {origin}); the direction {citation} it."
    if current == "not-given":
        return " Taste was not given; the direction is the agent's own reading."
    return " Taste is unrecorded."
