"""The owner's words an action needs: `--basis` must be a statement the project's records hold as the owner's.

`lazuli adobe activate` adds a font to the owner's Creative Cloud library and `kit` publishes a web kit under
the owner's account, so neither runs on the agent's say-so. The basis is a quotation, and it must be found
verbatim (white space and wrapping quotation marks aside) in what the project records as the owner's own words:
the requirement record `.lapis/requirements/<task>.json` (a row, or a decision's quote), or a `[declared]` item of
the brief record `.lapis/answers/<task>.md` (the direction conversation's `## Direction <n>` items included). An
`[assumed]` item, a `## Found` line, and the run's own wording never count. The statement the quotation sits in
must also name what it approves: every font of the action (by its PostScript name or its family part, spaces
and case aside) and, for a kit, every domain. The check keeps the claim from being the agent's own text; it
cannot tell whether the words are consent, which is why the skills have the agent ask first and quote the answer.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

TASK = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
MIN_BASIS_CHARS = 8


def _key(text: str) -> str:
    """Letters and digits of any script, folded: how names are compared inside a sentence."""
    return "".join(ch for ch in unicodedata.normalize("NFKC", text).casefold() if ch.isalnum())


def font_keys(postscript_name: str) -> list[str]:
    """The ways a statement may name a font: the whole PostScript name, or its family part before the first hyphen
    when that is long enough to be a name (`FuturaPT-Book` is named by `Futura PT`)."""
    whole = _key(postscript_name)
    family = _key(postscript_name.split("-", 1)[0])
    return [whole] if len(family) < 3 else [whole, family]


def statements(root: Path, task: str) -> list[str]:
    """The owner's statements the project records: requirement rows, the quotes of decisions, and `[declared]`
    items of the brief record, each as one string."""
    from lapis_design import requirements, waiting

    found: list[str] = []
    doc = requirements.record(root, task)
    if doc:
        found += [row["text"] for row in doc["rows"]]
        found += [d["quote"] for d in doc.get("owner_decisions", []) if isinstance(d, dict) and isinstance(d.get("quote"), str)]
    try:
        text = waiting.answers_path(root, task).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    found += [quote for _, quote, _ in requirements._declared_items(text)]
    return found


def problem(basis: str | None, root: Path, task: str | None, fonts: list[str], domains: list[str] = ()) -> str | None:
    """Why `basis` cannot back an action on `fonts` (PostScript names) and `domains`, or None when it can."""
    from lapis_design import references

    if not basis or not basis.strip():
        return "--basis is required: quote, word for word, what the owner said that asks for this"
    if not task or not TASK.fullmatch(task):
        return "--task is required: the run whose records hold the owner's words (a lowercase slug)"
    line = references.clean_line(basis)
    if len(line) < MIN_BASIS_CHARS:
        return f"{line!r} is too short to be the owner's words; quote the whole statement"
    held = statements(root, task)
    if not held:
        return (f"the project records no owner statement for task {task!r}: no requirement record "
                f".lapis/requirements/{task}.json and no `[declared]` item in .lapis/answers/{task}.md. Ask the owner, "
                "record their answer as a `[declared]` item with their words, and quote it")
    squash = references._squash
    containing = [s for s in held if line in squash(s)]
    if not containing:
        return (f"{line!r} is not in the owner's words recorded for task {task!r}. Copy what the owner said, exactly, into "
                f"a `[declared]` item of .lapis/answers/{task}.md (or seal their file with `lapis-design requirements "
                "seal`), then quote it; an `[assumed]` item or your own wording is not the owner's statement")
    needs = [(name, font_keys(name)) for name in fonts] + [(d, [_key(d)]) for d in domains]
    for statement in containing:
        folded = _key(statement)
        if all(any(k and k in folded for k in keys) for _, keys in needs):
            return None
    missing = [name for name, keys in needs if not any(k and k in _key(containing[0]) for k in keys)]
    return (f"the statement holding {line!r} does not name {', '.join(missing)}, so it does not show the owner approved "
            "this. Record the owner's answer with the name of what they approved (the font's name, and for a kit its "
            "domains) in the `[declared]` item")
