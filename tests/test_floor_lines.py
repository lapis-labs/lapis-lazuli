"""A check that finds nothing says what no check judged: the printed result of every check ends with one line
when nothing blocks, and never when something does (cli/lapis_design/summary.py). `plan check` and `slop lint` then
add their dispute footer after it."""
from __future__ import annotations

from lapis_design.lint.cli import _summary_lines
from lapis_design.plan_check import _format_text
from lapis_design.summary import DISPUTE_FOOTER, floor_lines

FLOOR = "genre fit, information choice, the visitor's task at phone and desktop width"


def report(blocking: int, total: int, tool: str = "slop_lint") -> dict:
    return {"version": 0, "tool": {"name": tool, "version": "test"}, "target": {},
            "summary": {"blocking": blocking, "total": total}, "findings": []}


def test_nothing_found_says_no_defects_and_what_was_not_judged():
    assert floor_lines({"blocking": 0, "total": 0}) == [f"  no defects found; not judged: {FLOOR}"]


def test_findings_that_do_not_block_are_not_called_no_defects():
    assert floor_lines({"blocking": 0, "total": 4}) == [f"  no blocking findings; not judged: {FLOOR}"]


def test_a_blocking_report_carries_no_floor_line():
    assert floor_lines({"blocking": 1, "total": 1}) == []


def test_slop_lint_and_plan_check_end_their_printed_result_with_the_floor_line_and_the_dispute_footer():
    assert _summary_lines(report(0, 0), None)[-2:] == [f"  no defects found; not judged: {FLOOR}", DISPUTE_FOOTER]
    assert _format_text(report(0, 0, "plan_check"))[-2:] == [f"  no defects found; not judged: {FLOOR}", DISPUTE_FOOTER]
    assert not any("not judged: genre fit" in line for line in _summary_lines(report(2, 2), None))
