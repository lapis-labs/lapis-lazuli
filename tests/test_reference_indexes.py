"""A long skill reference opens with an index of its sections, so an agent reads the section a decision needs
instead of the whole file on every turn that follows."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[1] / "src" / "skills"
LONG = 120                                                  # lines: a reference this long needs an index
LONG_REFERENCES = sorted(path for path in SKILLS.glob("*/references/*.md")
                         if len(path.read_text(encoding="utf-8").splitlines()) >= LONG)


def headings(text: str) -> list[tuple[int, str]]:
    """(level, text) of each heading outside a fenced block."""
    found, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (match := re.match(r"(#{1,6}) (.+?)\s*$", line)):
            found.append((len(match[1]), match[2]))
    return found


def index_entries(text: str) -> list[str]:
    """The bullet lines of the `## Sections` block."""
    lines = text.splitlines()
    start = lines.index("## Sections") + 1
    block = []
    for line in lines[start:]:
        if line.startswith("#"):
            break
        block.append(line)
    return [line for line in block if line.startswith("- ")]


def test_every_long_reference_is_found():
    assert len(LONG_REFERENCES) >= 15


@pytest.mark.parametrize("path", LONG_REFERENCES, ids=lambda p: f"{p.parts[-3]}/{p.name}")
def test_a_long_reference_opens_with_an_index_that_names_each_of_its_sections(path):
    text = path.read_text(encoding="utf-8")
    found = headings(text)
    assert found[1] == (2, "Sections"), f"{path.name}: the second heading is the section index"
    sections = [name for level, name in found[2:] if level == 2]
    entries = index_entries(text)
    named = []
    for entry in entries:
        owner = [name for level, name in found[2:] if level in (2, 3) and entry.startswith(f"- {name}: ")]
        assert owner and entry.removeprefix(f"- {owner[0]}: ").strip(), f"{path.name}: no section for `{entry}`"
        named.append(owner[0])
    assert [name for name in named if name in sections] == sections, (
        f"{path.name}: the index names each `##` section once, in file order")
    assert len(set(named)) == len(named)
