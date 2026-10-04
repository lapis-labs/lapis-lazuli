"""The brief step: what `lapis-design next` asks for before the plan, and what counts as the brief record."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from lapis_design import brief, next_step
from lapis_design.cli import main as cli_main
from procedure_support import BRIEF_RECORD, TASK, ask, make_project, record, reply, save, update

QUESTIONS = "1. Who visits the kiln shop page?\n2. Is the monthly firing date fixed?\n"
ANSWERS = "1. Buyers.\n2. Yes, the first Saturday.\n"


@pytest.fixture
def bare(tmp_path, monkeypatch) -> Path:
    """A project folder with nothing in it: no plan, no questions, no record."""
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    return tmp_path


def evaluated(root: Path) -> dict:
    return next_step.evaluate(root, TASK)


def step_of(root: Path) -> str:
    result = evaluated(root)
    return result["step"]["id"] if result["step"] else "done"


def test_a_run_with_no_plan_and_no_record_is_sent_to_the_brief_before_the_plan(bare):
    result = evaluated(bare)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "brief")
    assert result["step"]["command"] is None and f".lapis/answers/{TASK}.md" in result["step"]["why"]


def test_a_brief_record_hands_the_run_on_to_the_plan(bare):
    record(bare, "answers", BRIEF_RECORD, 100)
    assert step_of(bare) == "plan"


def test_a_create_plan_without_a_record_goes_back_to_the_brief_and_the_other_modes_do_not(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    assert step_of(root) == "release"
    (root / f".lapis/answers/{TASK}.md").unlink()
    assert step_of(root) == "brief"
    for mode in ("redesign", "repair"):
        update(root, f"plans/{TASK}.yaml", lambda plan, mode=mode: plan.update(mode=mode))
        assert step_of(root) != "brief", mode


def test_a_plan_that_cannot_be_read_is_fixed_before_anything_asks_for_a_record(bare):
    save(bare, f"plans/{TASK}.yaml", {"mode": "create"})
    (bare / f".lapis/plans/{TASK}.yaml").write_text("brief: [oops\n", encoding="utf-8")
    assert step_of(bare) == "plan-fix"


def test_the_json_and_the_text_of_the_command_name_the_brief(bare, capsys):
    assert cli_main(["next", "--task", TASK, "--root", str(bare), "--json"]) == 0
    assert '"id": "brief"' in capsys.readouterr().out
    assert cli_main(["next", "--task", TASK, "--root", str(bare)]) == 0
    assert capsys.readouterr().out.startswith(f"next: brief ({TASK})")


NOT_A_RECORD = [
    ("", "no file text at all", "## Found"),
    ("# Brief\n", "a heading only", "## Found"),
    ("## Answers\n- [known] Q1 Who buys? Buyers. Basis: PRODUCT.md.\n", "no Found section", "## Found"),
    ("## Found\n\n## Answers\n- [known] Q1 Who buys? Buyers. Basis: PRODUCT.md.\n", "Found has no text", "## Found"),
    ("## Found\nPRODUCT.md read: the studio fires monthly.\n", "no Answers section", "## Answers"),
    ("## Found\nPRODUCT.md read.\n## Answers\n", "Answers has no text", "## Answers"),
    ("## Found\nPRODUCT.md read.\n## Answers\n- [assumed] Q1 Who buys? Small teams.\n",
     "an assumed answer without a basis", "Basis:"),
    ("## Found\nPRODUCT.md read.\n## Answers\n- [assumed] Q1 Who buys? Small teams. Basis:\n",
     "an empty basis", "Basis:"),
    ("## Found\nPRODUCT.md read.\n## Answers\n- [known] Q1 Who buys? Buyers. Basis: PRODUCT.md.\n"
     "- [assumed] Q2 The job? Reserve a piece.\n", "one of two assumed answers without a basis", "Q2 The job"),
    ("1. Buyers.\n2. Yes, the first Saturday.\n", "answers copied as they came, in no record", "## Found"),
]


@pytest.mark.parametrize("text, case, part", NOT_A_RECORD, ids=[case for _, case, _ in NOT_A_RECORD])
def test_a_file_that_is_not_a_brief_record_leaves_the_run_at_the_brief_and_says_what_is_missing(bare, text, case, part):
    record(bare, "answers", text, 100)
    assert evaluated(bare)["step"]["id"] == "brief", case
    assert part in brief.problem(text), case


ACCEPTED = [
    ("the template", BRIEF_RECORD),
    ("deeper headings and other capitals", "### FOUND\nRead the folder: empty.\n### answers (round 1)\n"
     "- [declared] Q1 The look? Modern and professional. Basis: the request.\n"),
    ("numbered, bold-tagged items", "## Found\nNothing found: the folder is empty and no lookup was possible.\n"
     "## Answers\n1. **[assumed]** Q1 Who buys? IT leads. Basis: the category's usual buyer.\n"),
    ("a basis on a following line", "## Found\nThe request only.\n## Answers\n"
     "- [assumed] Q1 Who buys? IT leads at small companies.\n  Basis: the category's usual buyer; nobody to ask.\n"),
    ("answers that need no tags", "## Found\nPRODUCT.md holds audience, offer, and limits.\n"
     "## Answers\nNo questions needed: every fact was found in the project.\n"),
    ("an open answer without a basis", "## Found\nThe request only.\n## Answers\n"
     "- [open] Q1 Which regions ship? No default fits; the page says nothing about shipping.\n"),
]


@pytest.mark.parametrize("case, text", ACCEPTED, ids=[case for case, _ in ACCEPTED])
def test_the_shapes_a_record_may_take_are_accepted(bare, case, text):
    record(bare, "answers", text, 100)
    assert step_of(bare) == "plan", case


def test_questions_before_the_brief_wait_in_the_plan_phase_and_only_a_record_ends_the_wait(bare):
    ask(bare, QUESTIONS, 200)
    result = evaluated(bare)
    assert (result["state"], result["waiting"]["phase"], result["then"]["id"]) == ("waiting-for-user", "plan", "brief")
    record(bare, "answers", ANSWERS, 300)                              # the replies as they came: not yet a record
    result = evaluated(bare)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "brief")
    reply(bare, ANSWERS, 400)
    assert step_of(bare) == "plan"
    ask(bare, "3. Which glaze goes first?\n", 500)                     # a second round, newer than the record
    result = evaluated(bare)
    assert (result["state"], result["then"]["id"]) == ("waiting-for-user", "plan")


def test_the_task_of_a_run_that_only_recorded_its_brief_is_found_by_the_record(bare):
    assert next_step.resolve_task(bare) is None
    record(bare, "answers", "", 100, task="kiln-remake")
    assert next_step.resolve_task(bare) is None                        # an empty file names no task
    record(bare, "answers", BRIEF_RECORD, 110, task="kiln-remake")
    assert next_step.resolve_task(bare) == "kiln-remake"
    save(bare, "plans/older-plan.yaml", {})
    os.utime(bare / ".lapis/plans/older-plan.yaml", (100, 100))
    assert next_step.resolve_task(bare) == "kiln-remake"               # the newest of plans, questions, and records
