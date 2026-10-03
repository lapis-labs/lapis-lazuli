"""`approval` in the plan: a person's approval is recorded as `approved`; a run with nobody to ask records `assumed`
and why, and the release gate lists it for the user to confirm without counting it as approval."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from lapis_design import shared_dir
from procedure_support import TASK, finish, make_project, touch, update

SHARED = shared_dir()
SCHEMA = Draft202012Validator(yaml.safe_load((SHARED / "plan/schema.yaml").read_text(encoding="utf-8")))
EXAMPLE = yaml.safe_load((SHARED / "plan/example.plan.yaml").read_text(encoding="utf-8"))


def errors(approval) -> list[str]:
    plan = copy.deepcopy(EXAMPLE)
    plan["approval"] = approval
    return [e.message for e in SCHEMA.iter_errors(plan)]


def test_the_example_plan_records_the_users_approval_and_validates():
    assert EXAMPLE["approval"] == {"state": "approved"} and not list(SCHEMA.iter_errors(EXAMPLE))


@pytest.mark.parametrize("approval", [
    {"state": "approved"},
    {"state": "approved", "reason": "the user said go ahead in chat"},
    {"state": "assumed", "reason": "unattended run, nobody to ask"},
])
def test_an_approval_is_approved_or_assumed_with_its_reason(approval):
    assert errors(approval) == []


@pytest.mark.parametrize("approval", [
    {"state": "assumed"},
    {"state": "assumed", "reason": "no"},
    {"state": "granted"},
    {"reason": "unattended run, nobody to ask"},
    {"state": "approved", "by": "the agent"},
    "approved",
])
def test_an_assumed_approval_needs_a_reason_and_nothing_else_is_an_approval(approval):
    assert errors(approval)


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("LAZULI_DB", "")
    return make_project(tmp_path)


def findings(root: Path, *flags: str) -> tuple[int, list[dict]]:
    code = finish(root, "--static", *flags)
    return code, [f for f in json.loads((root / f".lapis/release/{TASK}.json").read_text())["findings"]
                  if f["rule_id"] == "release.approval-assumed"]


def test_the_gate_lists_an_assumed_approval_for_the_user_and_never_blocks_on_it(project):
    update(project, f"plans/{TASK}.yaml", lambda d: d.update(approval={"state": "assumed", "reason": "unattended run"}))
    touch(project, f"plans/{TASK}.yaml", 90)
    code, found = findings(project)
    assert code == 0 and len(found) == 1
    item = found[0]
    assert item["blocking"] is False and item["class"] == "quality" and item["layer"] == "plan"
    assert item["severity"] == {"create": "warn", "review": "P2"}
    assert item["observed"] == "no person approved this plan: unattended run"


@pytest.mark.parametrize("approval", [{"state": "approved"}, None])
def test_an_approved_plan_and_a_plan_that_says_nothing_get_no_finding(project, approval):
    update(project, f"plans/{TASK}.yaml", lambda d: d.update(approval=approval) if approval else d.pop("approval", None))
    touch(project, f"plans/{TASK}.yaml", 90)
    assert findings(project) == (0, [])
