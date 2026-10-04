"""The exit gate: continues an unattended agent with the next step, within limits, and never blocks a person."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from lapis_design import gate
from lapis_design.cli import main as cli_main
from procedure_support import (BRIEF_RECORD, TASK, ask, finish, make_project, record, reply, save, touch,
                               write_references)

STATE = f".lapis/gate/{TASK}.json"


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    (root / ".lapis/assets.ledger.json").unlink()        # the ledger step remains
    return root


def state(root: Path) -> dict:
    return json.loads((root / STATE).read_text(encoding="utf-8"))


def test_an_unattended_gate_continues_the_agent_with_the_step_that_remains(project):
    answer = gate.stop_output(project, "s1")
    assert answer["decision"] == "block"
    reason = answer["reason"]
    assert "Next step: ledger." in reason and "ledger.schema.yaml" in reason
    assert f"lapis-design next --task {TASK}" in reason
    assert "approval: {state: assumed" in reason          # the first continue says what to do with the approval
    assert (state(project)["same"], state(project)["total"], state(project)["session"]) == (1, 1, "s1")


def test_the_gate_lets_the_agent_stop_after_three_continues_for_one_step_and_records_the_step(project):
    answers = [gate.stop_output(project, "s1") for _ in range(5)]
    assert [bool(a) for a in answers] == [True, True, True, False, False]
    capped = state(project)["capped"]
    assert capped["reason"] == "same-step" and capped["step"] == "ledger" and capped["command"] is None
    assert state(project)["same"] == 3 and state(project)["total"] == 3


def alternate(root: Path, index: int) -> None:
    """Make the step differ on every stop: the fonts lock is missing on even stops, the ledger on odd ones."""
    lock, ledger = root / ".lapis/fonts.lock.json", root / ".lapis/assets.ledger.json"
    if index % 2 == 0:
        ledger.write_text('{"version": 0, "updated_at": "2026-09-27T00:00:00Z", "assets": []}', encoding="utf-8")
        lock.unlink(missing_ok=True)
    else:
        lock.write_text('{"version": 0, "locked_at": "2026-09-27T00:00:00Z", "fonts": []}', encoding="utf-8")
        ledger.unlink(missing_ok=True)


def test_the_gate_lets_the_agent_stop_after_fifteen_continues_in_all_whatever_the_steps(project):
    steps = []
    for index in range(17):
        alternate(project, index)
        answer = gate.stop_output(project, "s1")
        steps.append(answer["reason"].split("Next step: ")[1].split(".")[0] if answer else None)
    assert steps[:15] == ["fonts-lock", "ledger"] * 7 + ["fonts-lock"]      # never three in a row for one step
    assert steps[15:] == [None, None]
    assert state(project)["total"] == 15 and state(project)["capped"]["reason"] == "total"


def test_a_step_that_changes_starts_its_count_again_and_total_keeps_running(project):
    assert gate.stop_output(project, "s1") and gate.stop_output(project, "s1")
    save(project, "assets.ledger.json", {"version": 0, "updated_at": "2026-09-27T00:00:00Z", "assets": []})
    touch(project, "assets.ledger.json", 103)             # the lint report was made after this ledger
    answer = gate.stop_output(project, "s1")
    assert "Next step: release." in answer["reason"] and "approval:" not in answer["reason"]
    assert (state(project)["step"], state(project)["same"], state(project)["total"]) == ("release", 1, 3)


def test_a_procedure_that_is_done_lets_the_agent_stop_and_forgets_the_step(project):
    assert gate.stop_output(project, "s1")
    save(project, "assets.ledger.json", {"version": 0, "updated_at": "2026-09-27T00:00:00Z", "assets": []})
    touch(project, "assets.ledger.json", 103)
    assert finish(project, "--static") == 0
    assert gate.stop_output(project, "s1") is None
    assert state(project)["step"] is None and state(project)["same"] == 0 and state(project)["total"] == 1


def test_a_person_at_the_keyboard_gets_one_line_and_is_never_blocked(project):
    answers = [gate.stop_output(project, "s1", unattended=False) for _ in range(30)]
    assert all(set(a) == {"systemMessage"} for a in answers)
    assert "step ledger" in answers[0]["systemMessage"] and "\n" not in answers[0]["systemMessage"]
    assert not (project / STATE).exists()


def test_the_unattended_switch_is_exactly_one(monkeypatch):
    for value, expected in (("1", True), ("0", False), ("true", False), ("", False)):
        assert gate.is_unattended({"LAPIS_UNATTENDED": value}) is expected
    assert gate.is_unattended({}) is False


def test_another_session_counts_for_itself(project):
    assert [bool(gate.stop_output(project, "s1")) for _ in range(4)] == [True, True, True, False]
    assert gate.stop_output(project, "s2")["decision"] == "block"
    assert (state(project)["session"], state(project)["total"], "capped" in state(project)) == ("s2", 1, False)


def test_a_folder_without_a_plan_is_no_project_for_a_person_or_an_unrelated_session(tmp_path, monkeypatch):
    monkeypatch.delenv("LAPIS_TASK", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    assert gate.decide({"cwd": str(tmp_path)}, {}) is None
    assert gate.decide({"cwd": str(tmp_path)}, {"LAPIS_UNATTENDED": "0"}) is None
    answer = gate.decide({"cwd": str(tmp_path)}, {"LAPIS_TASK": TASK})
    assert answer == {"systemMessage": gate.notice(next_state_without_plan(tmp_path))}   # a named task starts at the plan


def next_state_without_plan(root: Path, task: str = TASK) -> dict:
    from lapis_design import next_step
    return next_step.evaluate(root, task)


@pytest.mark.parametrize("records, step", [(0, "brief"), (1, "references"), (2, "plan")])
def test_an_unattended_run_that_wrote_no_plan_is_continued_to_write_one_and_is_capped_like_any_step(
        tmp_path, monkeypatch, records, step):
    """The failure this guards: the agent wrote a free-form PLAN.md and never the schema plan."""
    monkeypatch.delenv("LAPIS_TASK", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    folder = tmp_path / "Kiln Shop_Landing"
    folder.mkdir()
    (folder / "PLAN.md").write_text("# Plan\nA free-form plan.\n", encoding="utf-8")
    if records:
        record(folder, "answers", BRIEF_RECORD, 100, task="kiln-shop-landing")
    if records > 1:
        write_references(folder, 110, task="kiln-shop-landing")
    env = {"LAPIS_UNATTENDED": "1"}
    event = {"cwd": str(folder), "session_id": "s1"}
    answers = [gate.decide(event, env) for _ in range(5)]
    assert [bool(a) for a in answers] == [True, True, True, False, False]
    assert f"task kiln-shop-landing is not done. Next step: {step}." in answers[0]["reason"]
    assert ("approval: {state: assumed" in answers[0]["reason"]) == (step == "plan")     # there is no plan to approve yet
    saved = json.loads((folder / ".lapis/gate/kiln-shop-landing.json").read_text(encoding="utf-8"))
    assert saved["capped"]["reason"] == "same-step" and saved["capped"]["step"] == step


def test_a_run_that_recorded_its_brief_under_a_task_id_of_its_own_is_continued_under_that_id(tmp_path, monkeypatch):
    monkeypatch.delenv("LAPIS_TASK", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    folder = tmp_path / "Kiln Shop"
    folder.mkdir()
    record(folder, "answers", BRIEF_RECORD, 100, task="pottery-landing")
    answer = gate.decide({"cwd": str(folder), "session_id": "s1"}, {"LAPIS_UNATTENDED": "1"})
    assert "task pottery-landing is not done. Next step: references." in answer["reason"]
    write_references(folder, 110, task="pottery-landing")
    answer = gate.decide({"cwd": str(folder), "session_id": "s1"}, {"LAPIS_UNATTENDED": "1"})
    assert "task pottery-landing is not done. Next step: plan." in answer["reason"]


def test_an_unattended_run_that_answers_its_own_questions_must_mark_what_it_assumed_and_why(tmp_path, monkeypatch):
    monkeypatch.delenv("LAPIS_TASK", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    folder = tmp_path / "Kiln Shop"
    folder.mkdir()
    env, event = {"LAPIS_UNATTENDED": "1"}, {"cwd": str(folder), "session_id": "s1"}
    assert "Next step: brief." in gate.decide(event, env)["reason"]
    record(folder, "answers", "## Found\nThe request only; nothing else to read.\n## Answers\n"
           "- [assumed] Q1 Who buys? Small teams.\n", 100, task="kiln-shop")
    hollow = gate.decide(event, env)["reason"]                          # an assumption with no basis is no record
    assert "Next step: brief." in hollow and "Basis" in hollow
    record(folder, "answers", "## Found\nThe request only; nothing else to read.\n## Answers\n"
           "- [assumed] Q1 Who buys? Small teams. Basis: the usual buyer of this kind of product; nobody to ask.\n",
           110, task="kiln-shop")
    looking = gate.decide(event, env)["reason"]
    assert "Next step: references." in looking and "approval: {state: assumed" not in looking
    write_references(folder, 120, task="kiln-shop")
    done = gate.decide(event, env)["reason"]
    assert "Next step: plan." in done and "approval: {state: assumed" in done
    saved = json.loads((folder / ".lapis/gate/kiln-shop.json").read_text(encoding="utf-8"))
    assert (saved["step"], saved["same"], saved["total"]) == ("plan", 1, 4)


@pytest.mark.parametrize("name, task", [("Kiln Shop_Landing", "kiln-shop-landing"), ("x", "design"), ("---", "design"),
                                        ("a" * 80, "a" * 64), ("Café 한글 2", "caf-2")])
def test_the_task_of_a_run_with_no_plan_comes_from_its_folder_name(tmp_path, name, task):
    assert gate.folder_task(tmp_path / name) == task
    assert next_step_fullmatch(task)


def next_step_fullmatch(task: str) -> bool:
    from lapis_design import attempts
    return attempts.TASK.fullmatch(task) is not None


def test_the_project_is_found_from_a_folder_below_it(project):
    nested = project / "src" / "app"
    nested.mkdir(parents=True)
    answer = gate.decide({"cwd": str(nested), "session_id": "s1"}, {"LAPIS_UNATTENDED": "1"})
    assert answer["decision"] == "block"
    assert gate.decide({"cwd": str(nested), "session_id": "s1"}, {}) == {
        "systemMessage": gate.notice(next_state(project))}


def next_state(root: Path) -> dict:
    from lapis_design import next_step
    return next_step.evaluate(root, TASK)


def test_a_state_the_gate_cannot_read_never_holds_the_agent(project, monkeypatch, tmp_path, capsys):
    broken = tmp_path / "not-a-database.db"
    broken.write_text("this is not sqlite", encoding="utf-8")
    monkeypatch.setenv("LAZULI_DB", str(broken))
    assert gate.stop_output(project, "s1") is None
    assert "lapis-design gate:" in capsys.readouterr().err
    assert not (project / STATE).exists()


def hook(monkeypatch, capsys, stdin: str, **env: str) -> str:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    assert cli_main(["hook", "stop"]) == 0
    return capsys.readouterr().out


def test_the_stop_hook_reads_the_event_on_stdin_and_prints_claude_codes_stop_json(project, monkeypatch, capsys):
    event = json.dumps({"hook_event_name": "Stop", "cwd": str(project), "session_id": "s1", "stop_hook_active": False})
    out = json.loads(hook(monkeypatch, capsys, event, LAPIS_UNATTENDED="1"))
    assert set(out) == {"decision", "reason"} and out["decision"] == "block"
    attended = json.loads(hook(monkeypatch, capsys, event, LAPIS_UNATTENDED="0"))
    assert set(attended) == {"systemMessage"}


@pytest.mark.parametrize("stdin", ["", "not json", "[]", '{"cwd": 5}'])
def test_the_stop_hook_says_nothing_to_an_event_it_cannot_read_when_nobody_runs_it_unattended(
        monkeypatch, capsys, tmp_path, stdin):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LAPIS_TASK", raising=False)
    assert hook(monkeypatch, capsys, stdin, LAPIS_UNATTENDED="0") == ""


QUESTIONS = "1. Who visits the kiln shop page?\n2. Is the monthly firing date fixed?\n"
ANSWERS = "1. Buyers of the monthly firing.\n2. Yes, the first Saturday.\n"


def next_question(index: int) -> str:
    return f"{index}. Which of the {index + 2} glaze colors goes first?\n"


def test_a_run_that_asked_its_user_may_stop_and_no_continue_is_counted(project):
    assert gate.stop_output(project, "s1")["decision"] == "block"            # one continue before the question
    ask(project, QUESTIONS, 200)
    assert [gate.stop_output(project, "s1") for _ in range(4)] == [None] * 4   # the same set is one wait, not four
    saved = state(project)
    assert (saved["step"], saved["same"], saved["total"]) == ("ledger", 1, 1)
    assert saved["waits"]["approval"] == 1 and "plan" not in saved["waits"] and "capped" not in saved


def test_answers_resume_the_run_with_the_step_that_comes_next(project):
    ask(project, QUESTIONS, 200)
    assert gate.stop_output(project, "s1") is None
    reply(project, ANSWERS, 300)
    answer = gate.stop_output(project, "s1")
    assert answer["decision"] == "block" and "Next step: ledger." in answer["reason"]
    assert (state(project)["same"], state(project)["total"], state(project)["waits"]["approval"]) == (1, 1, 1)


def test_questions_asked_again_after_an_answer_are_waited_on_while_the_cap_allows(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    folder = tmp_path / "Kiln Shop"
    folder.mkdir()
    outcomes = []
    for index in range(3):
        ask(folder, next_question(index), 200 + 20 * index, task="kiln-shop")
        outcomes.append(gate.stop_output(folder, "s1", task="kiln-shop"))
        reply(folder, ANSWERS, 210 + 20 * index, task="kiln-shop")
    assert outcomes[:2] == [None, None]                                   # two sets before a plan exist
    assert outcomes[2]["decision"] == "block" and "Next step: references." in outcomes[2]["reason"]
    saved = json.loads((folder / ".lapis/gate/kiln-shop.json").read_text(encoding="utf-8"))
    assert saved["waits"]["plan"] == 2 and (saved["step"], saved["same"], saved["total"]) == ("references", 1, 1)


def test_one_set_after_the_plan_and_the_two_before_it_are_counted_apart(project):
    save(project, f"gate/{TASK}.json", {"version": 0, "task": TASK, "waits": {"plan": 2, "last": "0-0"}})
    ask(project, next_question(1), 200)
    assert gate.stop_output(project, "s1") is None                         # the approval question
    reply(project, ANSWERS, 210)
    ask(project, next_question(2), 220)
    answer = gate.stop_output(project, "s1")
    assert answer["decision"] == "block" and "Next step: ledger." in answer["reason"]
    assert state(project)["waits"]["plan"] == 2 and state(project)["waits"]["approval"] == 1


@pytest.mark.parametrize("text", ["", "  \n\n", "Questions", "# Questions for the user\n", "1.\n", "?\n"])
def test_a_questions_file_without_words_of_its_own_does_not_hold_the_run(project, text):
    ask(project, text, 200)
    answer = gate.stop_output(project, "s1")
    assert answer["decision"] == "block" and "Next step: ledger." in answer["reason"]
    assert "waits" not in state(project)


def test_writing_the_same_questions_again_after_the_answer_is_a_new_set_and_hits_the_cap(project):
    ask(project, QUESTIONS, 200)
    assert gate.stop_output(project, "s1") is None
    reply(project, ANSWERS, 210)
    ask(project, QUESTIONS, 220)
    assert gate.stop_output(project, "s1")["decision"] == "block"


def test_the_waits_belong_to_the_task_and_not_to_the_session(project):
    ask(project, QUESTIONS, 200)
    assert gate.stop_output(project, "s1") is None
    assert gate.stop_output(project, "s2") is None                         # the same set is not counted again
    reply(project, ANSWERS, 210)
    ask(project, next_question(1), 220)
    assert gate.stop_output(project, "s2")["decision"] == "block"          # the one after-plan set was used in s1
    assert state(project)["waits"]["approval"] == 1 and state(project)["session"] == "s2"


def test_a_person_at_the_keyboard_is_told_what_the_run_waits_for_and_nothing_is_recorded(project):
    ask(project, QUESTIONS, 200)
    answer = gate.stop_output(project, "s1", unattended=False)
    assert set(answer) == {"systemMessage"} and f".lapis/questions/{TASK}.md" in answer["systemMessage"]
    assert not (project / STATE).exists()


def test_a_run_whose_questions_were_answered_is_not_told_that_nobody_is_present(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    folder = tmp_path / "Kiln Shop"
    folder.mkdir()
    cold = gate.stop_output(folder, "s1", task="kiln-shop")["reason"]
    assert "Next step: brief." in cold and "approve the plan" not in cold      # no plan yet, so nothing to approve
    ask(folder, QUESTIONS, 200, task="kiln-shop")
    assert gate.stop_output(folder, "s1", task="kiln-shop") is None
    reply(folder, ANSWERS, 210, task="kiln-shop")
    looking = gate.stop_output(folder, "s1", task="kiln-shop")["reason"]
    assert "Next step: references." in looking and "approve the plan" not in looking and "approval" not in looking
    write_references(folder, 220, task="kiln-shop")
    warm = gate.stop_output(folder, "s1", task="kiln-shop")["reason"]
    assert "Next step: plan." in warm and "No person is present" not in warm
    assert "A person's answers are recorded: write `approval: {state: approved}` only if they approve" in warm


def test_questions_before_the_brief_are_waited_on_twice_and_a_third_set_sends_the_run_back_to_the_brief(
        tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    folder = tmp_path / "Kiln Shop"
    folder.mkdir()
    outcomes = []
    for index in range(3):
        ask(folder, next_question(index), 200 + 20 * index, task="kiln-shop")
        outcomes.append(gate.stop_output(folder, "s1", task="kiln-shop"))
        record(folder, "answers", ANSWERS, 210 + 20 * index, task="kiln-shop")      # replies, not yet a record
    assert outcomes[:2] == [None, None]                                   # the two rounds the brief may take
    assert outcomes[2]["decision"] == "block" and "Next step: brief." in outcomes[2]["reason"]
    saved = json.loads((folder / ".lapis/gate/kiln-shop.json").read_text(encoding="utf-8"))
    assert saved["waits"]["plan"] == 2 and (saved["step"], saved["same"], saved["total"]) == ("brief", 1, 1)


def test_the_stop_hook_prints_nothing_while_the_run_waits_for_its_user(project, monkeypatch, capsys):
    ask(project, QUESTIONS, 200)
    event = json.dumps({"hook_event_name": "Stop", "cwd": str(project), "session_id": "s1", "stop_hook_active": False})
    assert hook(monkeypatch, capsys, event, LAPIS_UNATTENDED="1") == ""
    reply(project, ANSWERS, 210)
    assert json.loads(hook(monkeypatch, capsys, event, LAPIS_UNATTENDED="1"))["decision"] == "block"
