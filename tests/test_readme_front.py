"""The first screen of each README stays true to the files it quotes.

Text only: no script runs, so the docs-only CI workflow can run this file.
"""
import re
from pathlib import Path

import pytest
import yaml

from lapis_design import __version__

ROOT = Path(__file__).resolve().parents[1]
READMES = {"README.md": "## Install", "README.ko.md": "## 설치"}
FENCE = re.compile(r"^```(\w*)\s*$")


def fenced_blocks(path: Path, heading: str | None = None, lang: str | None = None) -> list[list[str]]:
    """The fenced blocks of a file, after `heading` when given and in `lang` when given."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if heading:
        lines = lines[lines.index(heading) + 1:]
    blocks, current, tag = [], None, ""
    for line in lines:
        m = FENCE.match(line)
        if m and current is None:
            current, tag = [], m.group(1)
        elif m:
            if lang is None or tag == lang:
                blocks.append(current)
            current = None
        elif current is not None:
            current.append(line)
    return blocks


def quick_install_line() -> str:
    """The macOS and Linux dry-run line INSTALLATION.md gives under Quick install."""
    guide = ROOT / "INSTALLATION.md"
    return fenced_blocks(guide, "## Quick install", "sh")[0][0]


@pytest.mark.parametrize("readme", READMES)
def test_install_lines_are_the_quick_install_line_and_its_real_run(readme):
    line = quick_install_line()
    assert line.endswith(" --dry-run")
    block = fenced_blocks(ROOT / readme, READMES[readme], "sh")[0]
    assert block == [line, line.removesuffix(" --dry-run"), "lazuli doctor"]


def console(readme: str) -> list[str]:
    """The plan-check output shown on the README's first screen."""
    return fenced_blocks(ROOT / readme, lang="console")[0]


@pytest.mark.parametrize("readme", READMES)
def test_console_output_names_the_current_version(readme):
    header = console(readme)[1]
    assert header.startswith(f"plan_check {__version__}: "), (
        f"{readme} shows `{header}`; run `lapis-design plan check` on the example plan on a machine "
        "without a lazuli database and paste its output")


def test_output_examples_in_the_outputs_guide_carry_the_current_version():
    text = (ROOT / "install" / "OUTPUTS.md").read_text(encoding="utf-8")
    assert set(re.findall(r'"version": "([^"]+)"', text)) == {__version__}


def test_both_readmes_show_the_same_findings_in_the_same_order():
    def findings(readme: str) -> list[str]:
        lines = console(readme)
        return [lines[1]] + [m.group(1) for line in lines if (m := re.match(r"\s+\[(?:BLOCK|WARN|INFO)\] (\S+)", line))]
    assert findings("README.md") == findings("README.ko.md")


def test_rule_ids_the_readmes_name_exist_in_the_rule_file():
    rules = yaml.safe_load((ROOT / "src" / "shared" / "slop" / "rules.yaml").read_text(encoding="utf-8"))["rules"]
    ids = {r["id"] for r in rules}
    domains = "|".join(sorted({r["domain"] for r in rules}))
    # plan_check findings such as font.no-lock are not rules; their domain is not a rule domain
    named = re.compile(rf"(?<![\w./-])(?:{domains})\.[a-z][a-z0-9.-]*[a-z0-9]")
    unknown = {m for readme in READMES for m in named.findall((ROOT / readme).read_text(encoding="utf-8")) if m not in ids}
    assert unknown == set()
