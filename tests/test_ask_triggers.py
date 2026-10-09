"""The asks the CLI raises itself (`asks.detected`): a direction value that changed after the seal, a change on an area the
owner decided while a finding about it was open, and agent-alone time past the budget; and the order record that only
`lapis-design` writes."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from lapis_design import asks, integrity, next_step, order, owner
from procedure_support import (BRIEF_RECORD, DIRECTION_ANSWERS, TASK, make_project, record, reply, seal_slice, update)


@pytest.fixture(autouse=True)
def attended(monkeypatch):
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")


@pytest.fixture
def project(tmp_path) -> Path:
    """A finished procedure whose slice the owner approved, observed once so that the protected values are known."""
    root = make_project(tmp_path)
    integrity.observe_task(root, TASK, "test")
    state = integrity.read_state(root, TASK)
    integrity.seal_slice(root, TASK, {"url": "http://localhost/", "draft_sha256": None, "packet_sha256": None,
                                      "questions_sha256": None, "answers_sha256": None, "requirements_sha256": None})
    assert state is not None
    return root


def plan_of(root: Path) -> dict:
    import yaml

    return yaml.safe_load((root / f".lapis/plans/{TASK}.yaml").read_text(encoding="utf-8"))


def edit(root: Path, change) -> None:
    update(root, f"plans/{TASK}.yaml", change)
    integrity.observe_task(root, TASK, "test")


def step_of(root: Path) -> str:
    result = next_step.evaluate(root, TASK)
    return result["step"]["id"] if result["step"] else "done"


def answered(root: Path, *items: str) -> None:
    """`## Asks` items in the brief record, newer than anything before."""
    path = root / f".lapis/answers/{TASK}.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n## Asks\n\n" + "".join(f"- {i}\n" for i in items), encoding="utf-8")
    later = time.time() + 5
    os.utime(path, (later, later))


def test_a_direction_value_changed_after_the_seal_is_a_new_direction_ask_until_asked_or_put_back(project):
    original = plan_of(project)["direction"]["concept"]
    assert asks.detected(project, TASK, plan_of(project)) is None
    edit(project, lambda p: p["direction"].update(concept="The page becomes a ledger of firings, one row per piece."))
    found = asks.detected(project, TASK, plan_of(project))
    assert found["id"] == "ask" and found["triggers"] == ["new-direction"] and "/direction/concept" in found["why"]
    assert step_of(project) == "ask" and next_step.evaluate(project, TASK)["step"]["command"] is None
    edit(project, lambda p: p["direction"].update(concept=original))              # put back
    assert asks.detected(project, TASK, plan_of(project)) is None
    edit(project, lambda p: p["direction"].update(concept="Another relation entirely, drawn as a route."))
    assert asks.detected(project, TASK, plan_of(project)) is not None
    answered(project, "[declared] Ask new-direction: keep the route — they said so")      # asked after the row
    assert asks.detected(project, TASK, plan_of(project)) is None


def test_a_section_added_after_the_seal_is_a_new_direction_and_a_color_change_is_not(project):
    edit(project, lambda p: p["tokens"]["color"]["roles"][0].update(name=p["tokens"]["color"]["roles"][0]["name"] + "x"))
    assert asks.detected(project, TASK, plan_of(project)) is None or "new-direction" not in asks.detected(
        project, TASK, plan_of(project))["triggers"]
    edit(project, lambda p: p["layout"]["sections"].append({"id": "extra-act", "role": "act", "content": "More."}))
    found = asks.detected(project, TASK, plan_of(project))
    assert found and "new-direction" in found["triggers"] and "/layout/sections" in found["why"]


def test_nothing_is_raised_before_the_seal(tmp_path):
    root = make_project(tmp_path)
    integrity.observe_task(root, TASK, "test")
    state = root / f".lapis/state/{TASK}.json"
    doc = json.loads(state.read_text(encoding="utf-8"))
    doc.pop("slice", None)
    state.write_text(json.dumps(doc), encoding="utf-8")
    edit(root, lambda p: p["direction"].update(concept="A different relation before anyone saw a slice."))
    assert asks.detected(root, TASK, plan_of(root)) is None


def test_a_change_on_an_area_the_owner_decided_while_a_finding_was_open_is_a_finding_vs_decision_ask(project):
    reply(project, "- [declared] color: the page stays white, the kiln blue only on the button\n", 300)
    integrity.record_findings(project, TASK, [{"rule_id": "plan.uncompared-decision", "class": "quality", "layer": "plan",
                                               "observed": "a color role was not compared", "blocking": True,
                                               "evidence": {"type": "plan"}, "status": "open",
                                               "severity": {"create": "gate"}}], "plan_check")
    edit(project, lambda p: p["tokens"]["color"]["roles"][0].update(oklch=[0.5, 0.01, 85]))
    found = asks.detected(project, TASK, plan_of(project))
    assert found and "finding-vs-decision" in found["triggers"] and "/tokens/color/roles" in found["why"]
    answered(project, "[assumed] Ask finding-vs-decision: keep the blue — took the default. Basis: the critic's finding stands.")
    assert asks.detected(project, TASK, plan_of(project)) is None


def test_the_budget_asks_after_ninety_one_minutes_and_a_budget_line_moves_it(project):
    sealed_at = time.time()
    assert asks.detected(project, TASK, plan_of(project), now=sealed_at + 60 * 60) is None
    found = asks.detected(project, TASK, plan_of(project), now=sealed_at + 91 * 60)
    assert found and found["triggers"] == ["budget"] and "91" not in found["why"] and "90 minutes" in found["why"]
    record(project, "answers", BRIEF_RECORD + DIRECTION_ANSWERS + "\n- Budget: 180 min — \"let it run\"\n", 400)
    assert asks.budget_minutes(project, TASK) == 180
    assert asks.detected(project, TASK, plan_of(project), now=sealed_at + 91 * 60) is None
    assert asks.detected(project, TASK, plan_of(project), now=sealed_at + 181 * 60)["triggers"] == ["budget"]
    assert "agent-alone budget set by you: 180 min" in owner.block(project, TASK)[0]


def test_an_answered_ask_restarts_the_clock_and_an_unattended_run_has_no_budget(project, monkeypatch):
    start = time.time()
    path = project / f".lapis/state/{TASK}.asks.json"
    path.write_text(json.dumps({"version": 0, "task": TASK, "sets": [{"set": "s1", "kind": "ask", "trigger": "budget",
        "then": "ask", "asked": "x", "answered": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start + 100 * 60)),
        "cli": True}]}), encoding="utf-8")
    assert asks.detected(project, TASK, plan_of(project), now=start + 150 * 60) is None            # 50 minutes after the answer
    assert asks.detected(project, TASK, plan_of(project), now=start + 200 * 60)["triggers"] == ["budget"]
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    assert asks.detected(project, TASK, plan_of(project), now=start + 999 * 60) is None


def test_a_cli_raised_ask_is_exempt_from_one_ask_per_checkpoint(project):
    ask_text = ("lapis-questions: ask\n1. Keep the new relation or put the old one back?\n   a) keep  b) put back\n"
                "Trigger: new-direction — /direction/concept\nDefault: a — keep it until you see it.\n")
    record(project, "questions", ask_text, 200)
    record(project, "answers", BRIEF_RECORD + DIRECTION_ANSWERS + "\n## Asks\n\n- [declared] Ask finding-vs-decision: a — fine\n", 210)
    record(project, "questions", ask_text + "\n", 220)
    assert asks.checkpoint_problem(project, TASK, "ask", asks.CLI_TRIGGERS) is None


def test_the_order_record_is_cli_owned_and_any_other_write_to_it_is_found(project, monkeypatch):
    assert order.cli_owned(f".lapis/order/{TASK}.json")
    event = {"cwd": str(project), "tool_name": "Write", "tool_input": {"file_path": str(project / f".lapis/order/{TASK}.json")}}
    refusal = order.decide(event, {})
    assert refusal and "`.lapis/order/`" in refusal["hookSpecificOutput"]["permissionDecisionReason"]
    order._save(project, TASK, {"slice_writes": {"since": "2026-10-01T00:00:00Z", "count": 39}})
    assert not order.tampered(project, TASK) and order.load(project, TASK)["slice_writes"]["count"] == 39
    path = order.record_path(project, TASK)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["slice_writes"]["count"] = 0                                       # the agent resets its own counter by a shell write
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert order.tampered(project, TASK) and order.load(project, TASK) == {}
    assert "was edited outside lapis-design" in owner.block(project, TASK)[0]
