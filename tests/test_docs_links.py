"""The public documents link only to files and headings that exist (the harness headings in
INSTALLATION.md come from install/harnesses.yaml, so renaming a harness moves its anchor)."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "README.ko.md", "CHANGELOG.md", "SECURITY.md", "INSTALLATION.md", "docs/eval/README.md"]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^```")


def prose(path: Path) -> list[str]:
    """The lines outside fenced code blocks."""
    lines, fenced = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            lines.append(line)
    return lines


def anchors(path: Path) -> set[str]:
    """GitHub's heading anchors for a Markdown file."""
    found = set()
    for line in prose(path):
        if m := re.match(r"#{1,6}\s+(.*?)\s*#*$", line):
            found.add(re.sub(r"[^\w\- ]", "", m.group(1).lower()).replace(" ", "-"))
    return found


@pytest.mark.parametrize("doc", DOCS)
def test_relative_links_resolve_to_a_file_and_heading(doc):
    source = ROOT / doc
    broken = []
    for line in prose(source):
        for target in LINK.findall(line):
            if re.match(r"[a-z][a-z0-9+.-]*:", target):
                continue                      # an absolute URL
            name, _, fragment = target.partition("#")
            path = source if not name else source.parent / name
            if not path.is_file() or (fragment and fragment not in anchors(path)):
                broken.append(target)
    assert broken == []
