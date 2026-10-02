"""README, CHANGELOG, and docs/eval/README.md never state an evaluation or benchmark result as a figure or as an
improvement.

docs/eval/README.md gives the rule. Text only: no script runs, so the docs-only CI workflow can run
this file.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "README.ko.md", "CHANGELOG.md", "docs/eval/README.md"]

# An item is about an evaluation when it names one or the conditions of one: an evaluation or benchmark, the
# skills, or "with ... without". An evaluator (the critic subagent, 평가자) is not an evaluation.
EVAL_ITEM = re.compile(
    r"\beval(?!uator)|\bbench|평가(?!자)|벤치|\bskills?\b|스킬|\bwith\b.*\bwithout\b|\bwithout\b.*\bwith\b", re.I)

# A claim is a figure (a percent sign, a factor, a number beside a run, task, finding, or token, a number alone
# in a table cell, `N of M`) or a comparison (better, improved, faster, fewer, higher, lower, outperforms,
# beats; 줄, 높, 빠르 and their forms).
_NUMBER = r"(?<![\d.])\d+(?:,\d{3})*(?:\.\d+)?(?!\.?\d)"           # not a part of 127.0.0.1 or 0.1.4
_COUNTED = r"(?:runs?|tasks?|findings?|tokens?|실행|과제|발견|토큰)"
CLAIM = re.compile("|".join([
    r"%|×|\d\s*x\b(?!\s*\d)",
    rf"\|\s*{_NUMBER}\s*(?=\|)",
    r"(?<![가-힣])배(?:가|는|를|로|나|의|만큼)?(?![가-힣])",
    rf"{_NUMBER}[가-힣]{{0,2}}\W+(?:\w+\W+){{0,2}}{_COUNTED}",
    rf"{_COUNTED}\W+(?:\w+\W+){{0,2}}{_NUMBER}",
    r"\d+\s+of\s+\d+",
    r"better|improv|\bfaster\b|\bfewer\b|\boutperform|\bbeat(?:s|en|ing)?\b|\bhigher\b|\blower\b",
    r"더 나은|개선|향상|줄(?:었|어|이|임|고|여|인)|높(?:았|아|은|이)|빠르|빨(?:랐|라)|낮(?:았|아|은)",
]), re.I)

STARTS_ITEM = re.compile(r"\s*(?:[-*+]|\d+\.)\s|#")
TABLE_ROW = re.compile(r"\s*\|")
TABLE_RULE = re.compile(r"\s*\|[\s:|-]+$")


def items(path: Path) -> list[str]:
    """Paragraphs, list items, headings, code blocks (read like the text around them), and table rows (each
    with the header row of its table, since the header may be what makes the row about an evaluation), each
    as one string."""
    out, current, header = [], [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```") or not line.strip() or TABLE_ROW.match(line) or STARTS_ITEM.match(line):
            if current:
                out.append(" ".join(current))
            current = []
        if line.startswith("```") or not line.strip():
            header = None
        elif TABLE_ROW.match(line):
            if not TABLE_RULE.match(line):
                out.append(line.strip() if header is None else f"{header} {line.strip()}")
                header = header or line.strip()
        else:
            header = None
            current.append(line.strip())
    return out + [" ".join(current)] if current else out


def claims(path: Path) -> list[str]:
    return [item for item in items(path) if EVAL_ITEM.search(item) and CLAIM.search(item)]


def test_a_wrapped_item_is_read_as_one_a_table_row_with_its_header_and_code_blocks_like_text(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("- The evaluation kit\n  makes results better.\n- Other item\n\n```\neval 50%\n```\n\n"
                   "| Eval | with | without |\n|---|---|---|\n| blocking | 11 | 102 |\n\nBench run | 3×\n", encoding="utf-8")
    assert items(doc) == ["- The evaluation kit makes results better.", "- Other item", "eval 50%",
                          "| Eval | with | without |", "| Eval | with | without | | blocking | 11 | 102 |",
                          "Bench run | 3×"]


# Sentences that state a result. Each must be caught wherever it stands: in a list, a table, or a code block.
RESULTS = [
    "- Eval: agents with the skills were 40% better.",
    "- In the eval, runs with the skills finished faster and with fewer blocking findings.",
    "- The eval shows LapisLazuli outperforms the baseline and beats plain Codex.",
    "- Eval: 9 of 12 tasks passed with the skills, 4 of 12 without.",
    "- Benchmark: 102 blocking findings before, 11 after.",
    "- Eval: 2x fewer findings; findings cut in half; twice as many passes.",
    "- 평가 결과 차단 발견이 두 배 줄었어요.",
    "- 벤치에서 점수가 더 높았어요.",
    "- 평가에서 차단 발견이 40% 줄었어요.",
    "- With the skills, agents produced 40% fewer blocking findings (12 tasks).",
    "- In paired runs the skills improved results by 40%.",
    "- Skill-effectiveness study: with minus without = -91 blocking findings.",
    "| Eval | with | without |\n|---|---|---|\n| blocking | 11 | 102 |",
    "```\neval: 40% better\n```",
    "- 스킬을 쓰면 실행 3회 가운데 2회에서 발견이 줄었어요.",
]

# Honest sentences that mention the same words or numbers.
PLAIN = [
    "- `behavior check` runs the controls probe faster with the same observations.",
    "- The eval server listens on 127.0.0.1 for the run, and the kit is version 0.1.4.",
    "- The evaluator subagent (평가자) checks the 모션 줄이기 setting.",
    "- The kit runs paired sessions with and without the skills; see docs/eval/ for the method.",
    "- Its results are case studies, not measurements of quality.",
    "| Skills | Version |\n|---|---|\n| lapis | 0.1.4 |",
]


@pytest.mark.parametrize("text", RESULTS)
def test_a_sentence_that_states_a_result_is_caught(tmp_path, text):
    doc = tmp_path / "doc.md"
    doc.write_text(text + "\n", encoding="utf-8")
    assert claims(doc) != []


@pytest.mark.parametrize("text", PLAIN)
def test_a_sentence_that_only_mentions_the_words_is_not_caught(tmp_path, text):
    doc = tmp_path / "doc.md"
    doc.write_text(text + "\n", encoding="utf-8")
    assert claims(doc) == []


@pytest.mark.parametrize("doc", DOCS)
def test_evaluation_and_benchmark_text_makes_no_figure_or_improvement_claim(doc):
    assert claims(ROOT / doc) == []
