"""The kinds of questions file (`lapis-questions: brief|direction|approval|ask`), the ask's shape and checkpoint rule, and
what unattended runs do with asks."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from lapis_design import asks, brief, gate, next_step, owner, waiting
from procedure_support import DIRECTION_ANSWERS, TASK, ask, make_project, record, reply, save, unseal_slice

QUESTIONS = "1. Who visits the kiln shop page?\n2. Is the monthly firing date fixed?\n"
ASK = ("1. Give each plate its own composition, or keep the repeated plate?\n   a) one composition per plate  "
       "b) keep the repetition\nTrigger: finding-vs-decision — critic review.taste-conflict on the plates\n"
       "Default: a — I build two plates differently and keep the rest until you see them.\n"
       "Unless you object: the install strip moves under the hero.\n")


@pytest.fixture(autouse=True)
def attended(monkeypatch):
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")


@pytest.fixture
def project(tmp_path) -> Path:
    """A finished procedure with a sealed slice and no fonts lock, so that `fonts-lock` is the step the questions wait on."""
    root = make_project(tmp_path)
    (root / ".lapis/fonts.lock.json").unlink()
    return root


def open_item(root: Path) -> str:
    """The direction proposal gains a signature item no owner answer settles, so that a `direction` file has an item to
    ask about; returns a question that names it."""
    doc = yaml.safe_load((root / f".lapis/direction/{TASK}.yaml").read_text(encoding="utf-8"))
    answers = root / f".lapis/answers/{TASK}.md"
    stamp = answers.stat().st_mtime_ns
    answers.write_text(answers.read_text(encoding="utf-8").replace(
        DIRECTION_ANSWERS, '\n## Direction 1\n\n- [declared] O1 the log: all — "try them all"\n'), encoding="utf-8")
    os.utime(answers, ns=(stamp, stamp))                     # the owner answered the object and has not taken the defaults
    doc["signature"] = [{"id": "G1", "element": "procedure animation", "default": "a",
                         "options": [{"id": "a", "text": "which step is current"}, {"id": "b", "text": "only the order"}]}]
    save(root, f"direction/{TASK}.yaml", doc)
    return "G1: what should the procedure animation carry?\n"


def numbered(count: int) -> str:
    return "".join(f"{n}. Question number {n} about the page?\n" for n in range(1, count + 1))


def step_of(root: Path) -> str:
    result = next_step.evaluate(root, TASK)
    return result["step"]["id"] if result["step"] else "done"


# ---- 1. kinds

def test_a_questions_file_without_a_kind_does_not_wait_and_the_step_says_to_mark_it(tmp_path):
    record(tmp_path, "questions", QUESTIONS, 200)
    result = next_step.evaluate(tmp_path, TASK)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "brief")
    assert "declares no kind, so they do not wait" in result["step"]["why"] and "lapis-questions: brief|direction" in result["step"]["why"]
    record(tmp_path, "questions", "lapis-questions: urgent\n" + QUESTIONS, 210)
    assert "names `urgent`, which is no kind" in next_step.evaluate(tmp_path, TASK)["step"]["why"]


def test_the_kind_line_is_no_word_of_the_questions(tmp_path):
    assert waiting.words("lapis-questions: ask\n") == 0 and waiting.kind("\n\nlapis-questions: ask\n1. Why?") == "ask"
    assert waiting.kind("1. Why?\nlapis-questions: ask") is None            # only the first non-blank line declares it
    record(tmp_path, "questions", "lapis-questions: brief\n", 200)
    assert next_step.evaluate(tmp_path, TASK)["state"] == "needs-step"


def test_a_brief_with_seven_numbered_questions_returns_brief_and_six_wait(tmp_path):
    ask(tmp_path, numbered(7), 200)
    result = next_step.evaluate(tmp_path, TASK)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "brief") and "numbers 7 questions" in result["step"]["why"]
    ask(tmp_path, numbered(6), 210)
    assert next_step.evaluate(tmp_path, TASK)["state"] == "waiting-for-user"


def test_the_cap_on_questions_is_the_briefs_alone(project):
    ask(project, numbered(15) + open_item(project), 200, kind="direction")
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["waiting"]["kind"]) == ("waiting-for-user", "direction")
    ask(project, numbered(7), 210, kind="brief")
    assert next_step.evaluate(project, TASK)["step"]["id"] == "brief"


def test_an_approval_file_with_no_draft_before_the_seal_returns_slice_and_the_other_kinds_wait(project):
    unseal_slice(project)
    ask(project, "Do you approve this plan as it reads?", 200)
    assert step_of(project) == "slice"
    ask(project, "Which of these two looks is closer: a or b? " + open_item(project), 210, kind="direction")
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["then"]["id"]) == ("waiting-for-user", "slice")
    ask(project, ASK, 220, kind="ask")
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["waiting"]["kind"], result["then"]["id"]) == ("waiting-for-user", "ask", "slice")


def test_a_wait_names_its_kind_and_what_to_record_for_it(project):
    ask(project, ASK, 200, kind="ask")
    why = next_step.evaluate(project, TASK)["step"]["why"]
    assert "under `## Asks`" in why and "[declared] Ask <trigger>:" in why and "may wait for" not in why
    ask(project, "Which of the options? " + open_item(project), 210, kind="direction")
    assert "under `## Direction <n>`" in next_step.evaluate(project, TASK)["step"]["why"]
    ask(project, QUESTIONS, 220, kind="approval")
    assert "may wait for 2 sets of questions before a plan exists and 1 after" in next_step.evaluate(project, TASK)["step"]["why"]


def test_direction_and_ask_sets_are_not_counted_against_the_briefs_cap(project):
    ask(project, ASK, 200, kind="ask")
    assert gate.stop_output(project, "s1", unattended=True, task=TASK) is None
    saved = json.loads((project / f".lapis/gate/{TASK}.json").read_text(encoding="utf-8"))
    assert "plan" not in saved["waits"] and "approval" not in saved["waits"] and saved["waits"]["last"]
    reply(project, "- [declared] Ask finding-vs-decision: a — one each", 210)
    ask(project, "Which look is closer? " + open_item(project), 220, kind="direction")
    for _ in range(3):
        assert gate.stop_output(project, "s1", unattended=True, task=TASK) is None
    ask(project, QUESTIONS, 230, kind="approval")
    assert gate.stop_output(project, "s1", unattended=True, task=TASK) is None
    assert json.loads((project / f".lapis/gate/{TASK}.json").read_text(encoding="utf-8"))["waits"]["approval"] == 1


# ---- 2. the shape of an ask

def test_an_ask_with_one_question_a_known_trigger_a_default_and_at_most_150_words_waits(project):
    assert asks.shape_problem(ASK) is None
    ask(project, ASK, 200, kind="ask")
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"


def padded(words: int) -> str:
    """The ask with its default line padded so that the whole file has exactly `words` words."""
    extra = words - waiting.words(ASK)
    return ASK.replace("Default: a —", "Default: a — " + " ".join(["more"] * extra) + " —")


@pytest.mark.parametrize("text, said", [
    (ASK + "2. And the other plate?\n", "an ask is one question, and it numbers 2"),
    (ASK.replace("1. Give", "Give"), "numbers 0"),
    (ASK.replace("Default: a — I build two plates differently and keep the rest until you see them.\n", ""), "no `Default:` line"),
    (ASK.replace("Trigger: finding-vs-decision", "Trigger: taste"), "`Trigger: taste` is no trigger"),
    (ASK.replace("Trigger: finding-vs-decision — critic review.taste-conflict on the plates\n", ""), "no `Trigger:` line"),
    (ASK + "Unless you object: a.\nUnless you object: b.\n", "3 \"unless you object\" lines"),
    (padded(151), "151 words"),
])
def test_an_ask_that_breaks_its_shape_does_not_wait_and_the_step_says_which_rule(project, text, said):
    ask(project, text, 200, kind="ask")
    result = next_step.evaluate(project, TASK)
    assert result["state"] == "needs-step" and said in result["step"]["why"] and "do not wait" in result["step"]["why"]


def test_an_ask_of_150_words_waits(project):
    assert waiting.words(padded(150)) == 150 and asks.shape_problem(padded(150)) is None
    ask(project, padded(150), 200, kind="ask")
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"


def test_an_ask_needs_no_owner_block_and_no_draft_review(project):
    ask(project, ASK + "See http://127.0.0.1:4173/slice.html\n", 200, kind="ask")
    result = next_step.evaluate(project, TASK)
    assert result["state"] == "waiting-for-user" and "owner_block" not in result and "draft_review" not in result


# ---- 3. one ask per checkpoint

def answered_ask(project: Path, at: int = 200) -> None:
    ask(project, ASK, at, kind="ask")
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"
    reply(project, "- [declared] Ask finding-vs-decision: a — one composition each", at + 10)
    assert step_of(project) == "fonts-lock"


def test_the_log_records_the_set_where_it_waited_and_when_it_was_answered(project):
    answered_ask(project)
    (entry,) = asks.load(project, TASK)["sets"]
    assert (entry["kind"], entry["trigger"], entry["then"], entry["cli"]) == ("ask", "finding-vs-decision", "fonts-lock", False)
    assert entry["asked"] == "1970-01-01T00:03:20Z" and entry["answered"] == "1970-01-01T00:03:30Z"


def test_a_second_ask_at_a_checkpoint_with_an_answered_ask_does_not_wait(project):
    answered_ask(project)
    ask(project, ASK + "\n", 300, kind="ask")
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "fonts-lock")
    assert "one ask per checkpoint" in result["step"]["why"] and "`- [assumed] Ask <trigger>:" in result["step"]["why"]
    assert next_step.evaluate(project, TASK)["state"] == "needs-step"       # said again, still not waiting


def test_an_ask_at_the_next_checkpoint_waits(project):
    answered_ask(project)
    (project / ".lapis/assets.ledger.json").unlink()                         # another step is now the checkpoint
    (project / ".lapis/fonts.lock.json").write_text('{"version": 0, "locked_at": "2026-09-27T00:00:00Z", "fonts": []}')
    os.utime(project / ".lapis/fonts.lock.json", (100, 100))
    ask(project, ASK + "\n", 300, kind="ask")
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["then"]["id"]) == ("waiting-for-user", "ledger")


def test_a_brief_or_direction_answer_at_the_checkpoint_is_not_an_answered_ask(project):
    ask(project, QUESTIONS, 200, kind="approval")
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"
    reply(project, "- [declared] 1. Buyers. 2. Yes.", 210)
    assert step_of(project) == "fonts-lock"
    ask(project, ASK, 300, kind="ask")
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"


# ---- 4. unattended

def test_direction_and_ask_files_never_wait_in_an_unattended_run(project, monkeypatch):
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    for at, kind in ((200, "direction"), (210, "ask")):
        ask(project, ASK, at, kind=kind)
        result = next_step.evaluate(project, TASK)
        assert (result["state"], result["step"]["id"]) == ("needs-step", "fonts-lock")
    ask(project, QUESTIONS, 220, kind="approval")
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"       # approval and brief still wait


def test_an_assumed_ask_without_a_basis_sends_the_run_back_to_the_brief_and_with_one_it_goes_on(tmp_path):
    answers = ("## Found\n- The request only.\n\n## Answers\n- [assumed] Q1 Who buys? Small teams. "
               "Basis: the usual buyer; nobody to ask.\n\n## Asks\n")
    record(tmp_path, "answers", answers + "- [assumed] Ask budget: keep going? — took the default.\n", 100)
    assert brief.record_problem(tmp_path, TASK).startswith("an [assumed] answer gives no `Basis:`")
    record(tmp_path, "answers", answers + "- [assumed] Ask budget: keep going? — took the default. "
           "Basis: nobody to ask; the run is within its time.\n", 110)
    assert brief.record_problem(tmp_path, TASK) is None
    assert step_of(tmp_path) == "requirements"


def test_an_assumed_ask_shows_in_the_block_at_done(project, monkeypatch):
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    answers = (project / f".lapis/answers/{TASK}.md").read_text(encoding="utf-8")
    record(project, "answers", answers + "\n## Asks\n\n- [assumed] Ask finding-vs-decision: one composition per plate, or "
           "keep the repeated plate? — took a. Basis: nobody to ask; a is the cheaper change to undo.\n", 60)
    text, _ = owner.block(project, TASK, {"verdict": "the release gate's report has 0 blocking findings"})
    assert "## Questions the run answered itself" in text
    assert "- finding-vs-decision: default taken, not asked: nobody to ask; a is the cheaper change to undo." in text
