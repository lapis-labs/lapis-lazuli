"""The brief step: what `lapis-design next` asks for before the plan, and what counts as the brief record."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from lapis_design import brief, gate, next_step
from lapis_design.cli import main as cli_main
from procedure_support import (BRIEF_RECORD, TASK, ask, make_project, record, reply, save, seal_requirements,
                               update)

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


def test_a_brief_record_hands_the_run_on_to_the_requirements_and_then_the_references(bare):
    record(bare, "answers", BRIEF_RECORD, 100)
    assert step_of(bare) == "requirements"
    seal_requirements(bare)
    assert step_of(bare) == "references"


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
    assert step_of(bare) == "requirements", case


def test_questions_before_the_brief_wait_in_the_plan_phase_and_only_a_record_ends_the_wait(bare):
    ask(bare, QUESTIONS, 200)
    result = evaluated(bare)
    assert (result["state"], result["waiting"]["phase"], result["then"]["id"]) == ("waiting-for-user", "plan", "brief")
    record(bare, "answers", ANSWERS, 300)                              # the replies as they came: not yet a record
    result = evaluated(bare)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "brief")
    reply(bare, ANSWERS, 400)
    assert step_of(bare) == "requirements"
    ask(bare, "3. Which glaze goes first?\n", 500)                     # a second round, newer than the record
    result = evaluated(bare)
    assert (result["state"], result["then"]["id"]) == ("waiting-for-user", "requirements")


def test_the_task_of_a_run_that_only_recorded_its_brief_is_found_by_the_record(bare):
    assert next_step.resolve_task(bare) is None
    record(bare, "answers", "", 100, task="kiln-remake")
    assert next_step.resolve_task(bare) is None                        # an empty file names no task
    record(bare, "answers", BRIEF_RECORD, 110, task="kiln-remake")
    assert next_step.resolve_task(bare) == "kiln-remake"
    save(bare, "plans/older-plan.yaml", {})
    os.utime(bare / ".lapis/plans/older-plan.yaml", (100, 100))
    assert next_step.resolve_task(bare) == "kiln-remake"               # the newest of plans, questions, and records


def answered(first: int, count: int) -> str:
    """`count` assumed answers numbered from `first`."""
    return "".join(f"- [assumed] Q{n} Which glaze goes first? The celadon. Basis: the kiln's own price list.\n"
                   for n in range(first, first + count))


def rounds_of(*counts: int, header: str = "Round 1 of 2.") -> str:
    """A brief record with one answers heading per round, each holding that many answers."""
    text = f"# Brief: kiln shop\n\n{header}\n\n## Found\nThe studio fires once a month: PRODUCT.md.\n\n"
    first = 1
    for number, count in enumerate(counts, start=1):
        text += f"## Answers{'' if number == 1 else f' (round {number})'}\n\n{answered(first, count)}\n"
        first += count
    return text


WITHIN_THE_CAP = [
    ("six answers in one round", rounds_of(6)),
    ("two rounds of six", rounds_of(6, 6)),
    ("a second round under a subheading of Answers",
     "## Found\nPRODUCT.md read.\n## Answers\n### Round 1\n" + answered(1, 6) + "### Round 2\n" + answered(7, 6)),
    ("a sub-list inside an answer is no further answer",
     "## Found\nPRODUCT.md read.\n## Answers\n" + "".join(
         f"- [assumed] Q{n} Who buys? Buyers. Basis: the price list.\n  - the studio's own newsletter list\n"
         for n in range(1, 7))),
]


@pytest.mark.parametrize("case, text", WITHIN_THE_CAP, ids=[case for case, _ in WITHIN_THE_CAP])
def test_a_record_within_six_answers_a_round_and_two_rounds_goes_on_to_the_requirements(bare, case, text):
    record(bare, "answers", text, 100)
    assert step_of(bare) == "requirements", case


OVER_THE_CAP = [
    ("seven answers in the first round", rounds_of(7), "holds 7 answers in round 1"),
    ("eleven answers under one heading", rounds_of(11), "holds 11 answers in round 1"),
    ("seven answers in the second round", rounds_of(3, 7), "holds 7 answers in round 2"),
    ("a third round", rounds_of(2, 2, 2), "records a round 3"),
    ("a header that says round 3", rounds_of(4, header="Round 3 of 3."), "records a round 3"),
]


@pytest.mark.parametrize("case, text, part", OVER_THE_CAP, ids=[case for case, _, _ in OVER_THE_CAP])
def test_a_record_with_a_round_past_six_answers_or_a_third_round_goes_back_to_the_brief_and_says_which(
        bare, case, text, part):
    record(bare, "answers", text, 100)
    result = evaluated(bare)
    assert result["step"]["id"] == "brief", case
    assert part in result["step"]["why"] and f".lapis/answers/{TASK}.md" in result["step"]["why"], case
    assert brief.problem(text) is None, case                           # a record in shape, over its cap


def test_a_create_plan_whose_record_is_over_the_cap_goes_back_to_the_brief(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    assert step_of(root) == "release"
    record(root, "answers", rounds_of(7), 50)
    assert step_of(root) == "brief"


def numbered(count: int) -> str:
    return "".join(f"{n}. Question {n}?\n   Why: it changes the opening.\n   If you skip it, I assume: the usual.\n"
                   for n in range(1, count + 1))


def test_questions_over_the_cap_are_cut_before_the_run_waits_on_them(bare):
    ask(bare, numbered(7), 200)
    result = evaluated(bare)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "brief")
    assert "numbers 7 questions" in result["step"]["why"] and f".lapis/questions/{TASK}.md" in result["step"]["why"]
    ask(bare, numbered(6), 300)                                        # written again, cut to six
    assert evaluated(bare)["state"] == "waiting-for-user"
    ask(bare, "## Found\n- The studio fires monthly (PRODUCT.md)\n- Nothing on prices\n- No logo found\n\n## Questions\n"
        + numbered(6), 400)
    assert evaluated(bare)["state"] == "waiting-for-user"              # the findings are no questions


def test_a_second_round_of_questions_over_the_cap_is_cut_too(bare):
    record(bare, "answers", BRIEF_RECORD, 100)
    ask(bare, numbered(7), 200)
    result = evaluated(bare)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "brief")


def test_the_questions_of_the_plans_approval_are_not_the_briefs_to_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    ask(root, numbered(7), 200)
    assert evaluated(root)["state"] == "waiting-for-user"


def test_the_exit_gate_continues_an_unattended_run_that_asked_more_than_it_may(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    folder = tmp_path / "Kiln Shop"
    folder.mkdir()
    ask(folder, numbered(7), 200, task="kiln-shop")
    stop = gate.stop_output(folder, "s1", task="kiln-shop")
    assert stop["decision"] == "block" and "Next step: brief." in stop["reason"] and "numbers 7 questions" in stop["reason"]
    ask(folder, numbered(6), 300, task="kiln-shop")
    assert gate.stop_output(folder, "s1", task="kiln-shop") is None
