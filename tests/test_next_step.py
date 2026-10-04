"""`lapis-design next`: the step still to take, read from the files, and what never counts as done."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
import yaml

from lapis_design import attempts, next_step
from lapis_design.cli import main as cli_main
from procedure_support import TASK, ask, finish, make_interactive, make_project, reply, save, touch, update

PLAN = f"plans/{TASK}.yaml"


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("LAZULI_DB", "")
    monkeypatch.delenv("LAPIS_TASK", raising=False)
    return make_project(tmp_path)


def step_of(root: Path) -> str:
    result = next_step.evaluate(root, TASK)
    return result["step"]["id"] if result["step"] else "done"


def lint_without(root: Path, target: str, layer: str) -> None:
    def change(lint):
        lint["target"].pop(target, None)
        lint["scope"]["layers"].remove(layer)
    update(root, f"lint/{TASK}.json", change)
    touch(root, f"lint/{TASK}.json", 110)
    touch(root, f"critic/{TASK}.json", 111)                     # the critic read the new lint report


def vague_cta(plan):
    plan["content"]["key_copy"].append({"slot": "cta", "text": "Click here", "locale": "en"})


def invalid_lock(root):
    (root / ".lapis/fonts.lock.json").write_text('{"version": 0}', encoding="utf-8")


MISSING_INPUTS = [
    ("plan", lambda r: (r / ".lapis" / PLAN).unlink()),
    ("brief", lambda r: (r / f".lapis/answers/{TASK}.md").unlink()),
    ("plan-fix", lambda r: (r / ".lapis" / PLAN).write_text("brief: [oops\n", encoding="utf-8")),
    ("plan-fix", lambda r: update(r, PLAN, lambda d: d.pop("brief"))),
    ("plan-fix", lambda r: update(r, PLAN, vague_cta)),
    ("plan-explorations", lambda r: update(r, PLAN, lambda d: d.pop("explorations"))),
    ("fonts-lock", lambda r: (r / ".lapis/fonts.lock.json").unlink()),
    ("fonts-lock", invalid_lock),
    ("ledger", lambda r: (r / ".lapis/assets.ledger.json").unlink()),
    ("render", lambda r: (r / f".lapis/renders/{TASK}.json").unlink()),
    ("render", lambda r: update(r, f"renders/{TASK}.json", lambda d: d["viewports"].pop())),
    ("lint", lambda r: (r / f".lapis/lint/{TASK}.json").unlink()),
    ("lint", lambda r: lint_without(r, "source", "source")),
    ("lint", lambda r: touch(r, f"lint/{TASK}.json", 1)),
    ("critic", lambda r: (r / f".lapis/critic/{TASK}.json").unlink()),
    ("critic", lambda r: touch(r, f"critic/{TASK}.json", 1)),
]


def test_a_project_with_every_input_and_report_waits_only_for_the_release_gate(project):
    assert step_of(project) == "release"
    assert finish(project, "--static") == 0
    assert step_of(project) == "done"


@pytest.mark.parametrize("expected, mutate", MISSING_INPUTS,
                         ids=[f"{expected}-{i}" for i, (expected, _) in enumerate(MISSING_INPUTS)])
def test_a_missing_or_invalid_input_sends_the_agent_to_the_step_that_makes_it(project, expected, mutate):
    assert step_of(project) == "release"
    mutate(project)
    assert step_of(project) == expected


@pytest.mark.parametrize("expected, mutate", [
    ("stub", lambda r: (r / ".lapis/stub.yaml").unlink()),
    ("stub", lambda r: (r / ".lapis/stub.yaml").write_text("version: 99\n", encoding="utf-8")),
    ("behavior", lambda r: (r / f".lapis/behavior/{TASK}.json").unlink()),
    ("behavior", lambda r: touch(r, PLAN, 5000)),
])
def test_an_interactive_page_needs_its_stub_and_a_current_behavior_session(project, expected, mutate):
    make_interactive(project)
    assert step_of(project) == "release"
    mutate(project)
    assert step_of(project) == expected


def test_a_page_with_controls_and_no_flows_goes_back_to_the_plan(project):
    (project / "index.html").write_text("<!doctype html><main><button>Reserve</button></main>", encoding="utf-8")
    assert step_of(project) == "plan-flows"
    update(project, PLAN, lambda d: d.update(flows=[{"id": "reserve", "kind": "primary", "goal": "Reserve one piece",
                                                     "start": "/", "done": {"route": "/done"}}]))
    assert step_of(project) != "plan-flows"


def test_a_behavior_check_that_is_still_running_is_waited_for_not_started_again(project):
    make_interactive(project)
    (project / f".lapis/behavior/{TASK}.json").unlink()
    pidfile = project / f".lapis/logs/{TASK}.behavior.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text(f"{os.getpid()}\n", encoding="utf-8")
    assert step_of(project) == "behavior-wait"
    pidfile.write_text("2147483646\n", encoding="utf-8")         # a process that does not exist
    assert step_of(project) == "behavior"


def test_the_step_names_the_exact_command_for_the_page(project):
    (project / "index.html").write_text("<!doctype html><p>Static</p>", encoding="utf-8")
    (project / f".lapis/renders/{TASK}.json").unlink()
    step = next_step.evaluate(project, TASK)["step"]
    assert step["command"] == f"lapis-design render check index.html --task {TASK}"
    elsewhere = next_step.evaluate(project, TASK, page="http://127.0.0.1:5173/")["step"]
    assert elsewhere["command"] == f"lapis-design render check http://127.0.0.1:5173/ --task {TASK}"


def test_a_schema_step_names_the_contract_to_write_against(project):
    (project / ".lapis/assets.ledger.json").unlink()
    step = next_step.evaluate(project, TASK)["step"]
    assert Path(step["schema"]).name == "ledger.schema.yaml" and Path(step["schema"]).is_file()


def record_render_failure(root: Path, *, newer_than_plan: bool = True) -> None:
    (root / f".lapis/renders/{TASK}.json").unlink()
    attempts.record(root, TASK, "render", ["lapis-design", "render", "check", "index.html", "--task", TASK], 2,
                    "the browser is not installed; run playwright install and run the check again")
    touch(root, f"attempts/{TASK}/render.json", 200 if newer_than_plan else 1)


def test_an_environment_failure_record_completes_the_step_it_names(project):
    record_render_failure(project)
    # the lint report was made without the render, which is what the failed check leaves behind
    lint_without(project, "extract", "render")
    assert step_of(project) == "release"
    touch(project, f"attempts/{TASK}/render.json", 300)           # the release report must follow the record
    assert finish(project, "--static") == 1                       # the gate still says the render has no evidence
    result = next_step.evaluate(project, TASK)
    assert result["state"] == "done" and "0 defects, 3 without evidence" in result["reason"]
    assert "No defects found" not in result["reason"]         # a report that blocks is never called a pass


def test_a_failure_record_older_than_the_plan_no_longer_stands_in_for_the_step(project):
    record_render_failure(project, newer_than_plan=False)
    assert step_of(project) == "render"


@pytest.mark.parametrize("break_record", [
    lambda text: "not json",
    lambda text: json.dumps({**json.loads(text), "failure_kind": "findings"}),
    lambda text: json.dumps({**json.loads(text), "step": "behavior"}),
    lambda text: json.dumps({**json.loads(text), "task": "another-task"}),
], ids=["unreadable", "not-environment", "other-step", "other-task"])
def test_only_a_record_the_tools_would_write_for_this_task_and_step_counts(project, break_record):
    record_render_failure(project)
    path = project / f".lapis/attempts/{TASK}/render.json"
    path.write_text(break_record(path.read_text(encoding="utf-8")), encoding="utf-8")
    touch(project, f"attempts/{TASK}/render.json", 200)
    assert step_of(project) == "render"


@pytest.mark.parametrize("step, remove", [
    ("ledger", lambda r: (r / ".lapis/assets.ledger.json").unlink()),
    ("fonts-lock", lambda r: (r / ".lapis/fonts.lock.json").unlink()),
    ("lint", lambda r: (r / f".lapis/lint/{TASK}.json").unlink()),
])
def test_a_missing_input_or_report_is_never_excused_by_a_record(project, step, remove):
    remove(project)
    directory = project / ".lapis/attempts" / TASK
    directory.mkdir(parents=True)
    (directory / f"{step}.json").write_text(json.dumps({
        "version": 0, "task": TASK, "step": step, "failure_kind": "environment", "reason": "claimed",
        "command": ["lapis-design"], "exit": 2, "at": "2026-10-03T00:00:00Z"}), encoding="utf-8")
    touch(project, f"attempts/{TASK}/{step}.json", 400)
    assert step_of(project) == step


def test_a_critic_that_cannot_start_is_recorded_through_next_and_the_gate_still_reports_it(project, capsys):
    (project / f".lapis/critic/{TASK}.json").unlink()
    assert step_of(project) == "critic"
    assert cli_main(["next", "--task", TASK, "--root", str(project), "--unavailable", "critic",
                     "--reason", "this harness cannot start a separate context"]) == 0
    assert "next: release" in capsys.readouterr().out
    assert attempts.read(project, TASK, "critic")["reason"] == "this harness cannot start a separate context"
    assert finish(project, "--static") == 1                       # release.critic-missing is still blocking
    assert step_of(project) == "done"


def test_a_blocking_release_report_still_ends_the_procedure(project):
    update(project, f"lint/{TASK}.json", lambda d: d["findings"].append({
        "rule_id": "example.rule", "class": "requirement", "severity": {"create": "gate", "review": "P0"},
        "layer": "render", "observed": "a defect", "blocking": True, "status": "open",
        "evidence": {"type": "review", "refs": ["original"]}}))
    touch(project, f"lint/{TASK}.json", 110)
    touch(project, f"critic/{TASK}.json", 111)
    assert finish(project, "--static") == 1
    result = next_step.evaluate(project, TASK)
    assert result["state"] == "done" and result["step"] is None
    assert "1 blocking findings (1 defects, 0 without evidence)" in result["reason"]


def test_done_after_a_gate_with_no_blocking_finding_says_what_no_check_judged(project):
    assert finish(project, "--static") == 0
    reason = next_step.evaluate(project, TASK)["reason"]
    assert "No defects found; not judged by any check: genre fit, information choice, the visitor's task" in reason
    assert "says nothing about whether the page is good" in reason


def test_changing_the_plan_after_the_gate_brings_the_checks_back_in_order(project):
    assert finish(project, "--static") == 0
    assert step_of(project) == "done"
    time.sleep(0.01)
    update(project, PLAN, lambda d: d["brief"].update(one_job="Let visitors reserve a different piece"))
    assert step_of(project) == "lint"


def test_the_next_command_prints_one_step_as_text_or_json(project, capsys):
    (project / f".lapis/renders/{TASK}.json").unlink()
    assert cli_main(["next", "--task", TASK, "--root", str(project), "--json"]) == 0
    state = json.loads(capsys.readouterr().out)
    assert state["state"] == "needs-step" and state["step"]["id"] == "render"
    assert cli_main(["next", "--task", TASK, "--root", str(project)]) == 0
    text = capsys.readouterr().out
    assert text.startswith(f"next: render ({TASK})") and "  run: lapis-design render check" in text


def test_the_task_is_the_newest_plan_unless_one_is_named(project, monkeypatch):
    other = save(project, "plans/older-task.yaml", yaml.safe_load((project / ".lapis" / PLAN).read_text()))
    touch(project, "plans/older-task.yaml", 1)
    assert next_step.resolve_task(project) == TASK
    os.utime(other, None)
    assert next_step.resolve_task(project) == "older-task"
    monkeypatch.setenv("LAPIS_TASK", "named-by-env")
    assert next_step.resolve_task(project) == "named-by-env"
    assert next_step.resolve_task(project, "named-by-flag") == "named-by-flag"


def test_without_a_plan_or_a_task_the_command_asks_for_one(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("LAPIS_TASK", raising=False)
    with pytest.raises(SystemExit) as exc:
        cli_main(["next", "--root", str(tmp_path)])
    assert exc.value.code == 2 and "pass --task" in capsys.readouterr().err


QUESTIONS = "1. Who visits the kiln shop page?\n2. Is the monthly firing date fixed?\n"


def test_unanswered_questions_make_the_state_waiting_for_the_user_and_the_answers_bring_back_the_step(project):
    (project / ".lapis/assets.ledger.json").unlink()
    ask(project, QUESTIONS, 200)
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["step"]["id"], result["then"]["id"]) == ("waiting-for-user", "waiting-for-user", "ledger")
    assert result["waiting"]["questions"] == f".lapis/questions/{TASK}.md" and result["waiting"]["phase"] == "approval"
    assert result["step"]["command"] is None and f".lapis/answers/{TASK}.md" in result["step"]["why"]
    reply(project, "1. Buyers.\n2. Yes.\n", 300)
    assert (next_step.evaluate(project, TASK)["state"], step_of(project)) == ("needs-step", "ledger")
    ask(project, "3. Which glaze first?\n", 400)
    assert step_of(project) == "waiting-for-user"                       # the latest questions are newer than the answers


def test_a_run_with_no_plan_waits_in_the_plan_phase(project):
    (project / ".lapis" / PLAN).unlink()
    ask(project, QUESTIONS, 200)
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["waiting"]["phase"], result["then"]["id"]) == ("waiting-for-user", "plan", "plan")


def test_a_finished_procedure_is_done_whatever_the_questions_say(project):
    assert finish(project, "--static") == 0
    ask(project, QUESTIONS, 10**9)
    assert next_step.evaluate(project, TASK)["state"] == "done"


def test_waiting_ends_for_next_when_the_gate_has_let_as_many_sets_pass_as_the_run_may_ask(project):
    (project / ".lapis/assets.ledger.json").unlink()
    save(project, f"gate/{TASK}.json", {"version": 0, "task": TASK, "waits": {"approval": 1, "last": "old"}})
    ask(project, QUESTIONS, 200)
    assert step_of(project) == "ledger"


@pytest.mark.parametrize("text", ["", "Questions", "# Questions\n"])
def test_questions_without_words_do_not_make_the_run_wait(project, text):
    (project / ".lapis/assets.ledger.json").unlink()
    ask(project, text, 200)
    assert step_of(project) == "ledger"


def test_the_json_of_a_waiting_run_names_the_step_after_the_answers(project, capsys):
    (project / ".lapis/assets.ledger.json").unlink()
    ask(project, QUESTIONS, 200)
    assert cli_main(["next", "--task", TASK, "--root", str(project), "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["state"], printed["then"]["id"]) == ("waiting-for-user", "ledger")
    assert cli_main(["next", "--task", TASK, "--root", str(project)]) == 0
    assert capsys.readouterr().out.startswith(f"next: waiting-for-user ({TASK})")


def test_a_run_that_asked_before_it_wrote_a_plan_is_found_by_its_questions(tmp_path, monkeypatch):
    monkeypatch.delenv("LAPIS_TASK", raising=False)
    assert next_step.resolve_task(tmp_path) is None
    ask(tmp_path, "", 200, task="kiln-remake")
    assert next_step.resolve_task(tmp_path) is None                     # an empty file names no task
    ask(tmp_path, QUESTIONS, 210, task="kiln-remake")
    assert next_step.resolve_task(tmp_path) == "kiln-remake"
    save(tmp_path, "plans/older-plan.yaml", {})
    touch(tmp_path, "plans/older-plan.yaml", 100)
    assert next_step.resolve_task(tmp_path) == "kiln-remake"            # the newest of plans and questions
