"""The critic's task walkthroughs (slop/finding.schema.yaml `walkthroughs`): an optional list that the findings
schema accepts when each entry names a task, a captured width, the first look, and an outcome, and refuses
anything else. No check or gate reads it."""
from __future__ import annotations

import copy

from lapis_design.lint.cli import problems

WALK = {"task": "find today's hours and book", "viewport": 390, "first_look": "the hero picture, then the date row",
        "read_or_scrolled_past": "two screens of picture before the hours", "stuck": "no hours on the first screen",
        "completed": "partly", "refs": ["renders/demo.shots/390.png"]}
REPORT = {"version": 0, "tool": {"name": "critic", "version": "test"}, "target": {"task": "demo"},
          "summary": {"blocking": 0, "total": 0}, "findings": [], "walkthroughs": [WALK]}


def test_a_critic_report_may_carry_walkthroughs():
    assert problems(REPORT, "report") == []


def test_a_report_without_walkthroughs_is_still_valid():
    bare = {k: v for k, v in REPORT.items() if k != "walkthroughs"}
    assert problems(bare, "report") == []


def test_a_walk_names_the_task_the_width_the_first_look_and_the_outcome():
    for missing in ("task", "viewport", "first_look", "completed"):
        broken = copy.deepcopy(REPORT)
        del broken["walkthroughs"][0][missing]
        assert problems(broken, "report"), missing


def test_the_outcome_and_the_width_come_from_a_closed_set():
    for field, value in (("completed", "maybe"), ("viewport", 500)):
        broken = copy.deepcopy(REPORT)
        broken["walkthroughs"][0][field] = value
        assert problems(broken, "report"), field


def test_a_walk_that_got_nowhere_needs_no_stuck_note_and_unknown_keys_are_refused():
    ok = copy.deepcopy(REPORT)
    del ok["walkthroughs"][0]["stuck"]
    ok["walkthroughs"][0]["completed"] = "yes"
    assert problems(ok, "report") == []
    ok["walkthroughs"][0]["score"] = 7
    assert problems(ok, "report")
