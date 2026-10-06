"""A critic's report and a maker's dispute hold the page's own words: a name that is two characters long in Korean,
Japanese, or Chinese ("드릴", a drill) is a whole fact, a whole first look, a whole observation. JSON Schema counts
characters, not words, so the floor of these fields is one; an empty string is still no fact."""
from __future__ import annotations

import copy

import pytest
import yaml

from lapis_design import shared_dir
from lapis_design.lint.cli import problems

FINDING = {"rule_id": "copy.generic-label", "class": "quality", "severity": {"create": "warn", "review": "P2"},
           "layer": "render", "observed": "확인", "blocking": False, "evidence": {"type": "review"}, "status": "open"}
REPORT = {
    "version": 0, "tool": {"name": "critic", "version": "test"}, "target": {"task": "demo"},
    "findings": [FINDING],
    "walkthroughs": [{"task": "예약", "viewport": 390, "first_look": "드릴", "completed": "yes"}],
    "facts": [{"text": "드릴", "refs": ["b0123456789ab"], "source": "none", "quote": ""}]}


def test_a_report_may_name_a_tool_with_two_characters():
    assert problems(REPORT, "report") == []


@pytest.mark.parametrize("where", [("facts", 0, "text"), ("walkthroughs", 0, "task"), ("walkthroughs", 0, "first_look"),
                                   ("findings", 0, "observed")])
def test_an_empty_string_is_still_no_fact_no_task_no_first_look_and_no_observation(where):
    broken = copy.deepcopy(REPORT)
    section, index, key = where
    broken[section][index][key] = ""
    assert problems(broken, "report")


def test_a_dispute_may_quote_a_finding_as_short_as_the_findings_own():
    schema = yaml.safe_load((shared_dir() / "review/disputes.schema.yaml").read_text(encoding="utf-8"))
    from jsonschema import Draft202012Validator

    dispute = {"report": ".lapis/lint/demo.json", "rule_id": "copy.generic-label", "observed": "확인",
               "reason": "The label is the name of the tool", "refs": ["b0123456789ab"]}
    document = {"version": 0, "task": "demo", "disputes": [dispute]}
    assert list(Draft202012Validator(schema).iter_errors(document)) == []
    document["disputes"][0]["observed"] = ""
    assert list(Draft202012Validator(schema).iter_errors(document))
