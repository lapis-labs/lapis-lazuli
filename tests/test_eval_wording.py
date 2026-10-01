"""README and CHANGELOG never state an evaluation or benchmark result as a figure or as an improvement.

docs/eval/README.md gives the rule. Text only: no script runs, so the docs-only CI workflow can run
this file.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "README.ko.md", "CHANGELOG.md"]
EVAL_ITEM = re.compile(r"\beval|\bbench|평가 도구|평가 결과|벤치", re.I)
CLAIM = re.compile(r"%|×|better|improv|더 나은|개선|향상", re.I)
STARTS_ITEM = re.compile(r"\s*(?:[-*+]|\d+\.)\s|\s*\||#")


def items(path: Path) -> list[str]:
    """Paragraphs, list items, table rows, and headings outside code blocks, each as one string."""
    out, current, fenced = [], [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if not line.strip() or STARTS_ITEM.match(line):
            if current:
                out.append(" ".join(current))
            current = [line.strip()] if line.strip() else []
        else:
            current.append(line.strip())
    return out + [" ".join(current)] if current else out


def test_a_wrapped_item_is_read_as_one_and_code_blocks_are_skipped(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("- The evaluation kit\n  makes results better.\n- Other item\n\n```\neval 50%\n```\n\n"
                   "Bench run | 3×\n", encoding="utf-8")
    assert items(doc) == ["- The evaluation kit makes results better.", "- Other item", "Bench run | 3×"]


@pytest.mark.parametrize("doc", DOCS)
def test_evaluation_and_benchmark_text_makes_no_figure_or_improvement_claim(doc):
    hits = [item for item in items(ROOT / doc) if EVAL_ITEM.search(item) and CLAIM.search(item)]
    assert hits == []
