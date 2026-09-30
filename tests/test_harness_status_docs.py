"""The harness table in each README shows the status install/harnesses.yaml gives every harness.

Text only: no script runs, so the docs-only CI workflow can run this file.
"""
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "build"))

import installers  # noqa: E402


def kind_en(cell: str) -> str:
    for prefix, kind in (("Experimental", "experimental"), ("Listing verified", "listing"), ("Verified", "verified")):
        if cell.startswith(prefix):
            return kind
    return cell


def kind_ko(cell: str) -> str:
    if cell.startswith("실험적"):
        return "experimental"
    if "목록" in cell:
        return "listing"
    if "확인함" in cell:
        return "verified"
    return cell


READMES = {"README.md": ("## Supported harnesses", kind_en), "README.ko.md": ("## 지원하는 하네스", kind_ko)}
ROW = re.compile(r"\| \[[^\]]+\]\(INSTALLATION\.md#([^)]+)\)[^|]*\|\s*([^|]+?)\s*\|")


def harness_rows(path: Path, heading: str) -> dict[str, str]:
    """Anchor in INSTALLATION.md -> the status cell of that table row."""
    lines = path.read_text(encoding="utf-8").splitlines()
    rows = {}
    for line in lines[lines.index(heading) + 1:]:
        if line.startswith("## "):
            break
        if m := ROW.match(line):
            rows[m.group(1)] = m.group(2)
    return rows


def listing_only(h: dict) -> bool:
    """Every confirmed fact of the harness is about what a listing showed, none about an install."""
    return all(re.search(r"\blists\b", v) and not re.search(r"\binstalls\b", v) for v in h["verified"])


def expected_kind(h: dict) -> str:
    if h.get("status") == "experimental":
        return "experimental"
    if not h.get("verified"):
        return "nothing confirmed"
    return "listing" if listing_only(h) else "verified"


@pytest.mark.parametrize("readme", READMES)
def test_readme_harness_table_shows_the_status_of_harnesses_yaml(readme):
    doc = yaml.safe_load((ROOT / "install/harnesses.yaml").read_text(encoding="utf-8"))
    heading, kind = READMES[readme]
    shown = {anchor: kind(cell) for anchor, cell in harness_rows(ROOT / readme, heading).items()}
    assert shown == {installers._slug(h["name"]): expected_kind(h) for h in doc["harnesses"]}
