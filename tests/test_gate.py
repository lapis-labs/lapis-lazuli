"""The exit gate: continues an unattended agent with the next step, within limits, and never blocks a person."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from lapis_design import gate
from lapis_design.cli import main as cli_main
from procedure_support import TASK, finish, make_project, save, touch

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


def test_a_folder_without_a_plan_is_not_a_lapis_project_and_gets_no_answer(tmp_path, monkeypatch):
    monkeypatch.delenv("LAPIS_TASK", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    assert gate.decide({"cwd": str(tmp_path)}, {"LAPIS_UNATTENDED": "1"}) is None
    answer = gate.decide({"cwd": str(tmp_path)}, {"LAPIS_UNATTENDED": "1", "LAPIS_TASK": TASK})
    assert "Next step: plan." in answer["reason"]          # a named task with no plan yet starts at the plan


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
def test_the_stop_hook_says_nothing_to_an_event_it_cannot_read(monkeypatch, capsys, tmp_path, stdin):
    monkeypatch.chdir(tmp_path)
    assert hook(monkeypatch, capsys, stdin, LAPIS_UNATTENDED="1") == ""
