"""A step that has the run write a record prints the record's format: the guide section, and a skeleton or the schema."""
from __future__ import annotations

import json
import re
from pathlib import Path

from lapis_design import brief, direction, next_step, references
from lapis_design.cli import main as cli_main
from procedure_support import TASK, ask, record
from test_owner_language import ENGLISH_QUESTIONS, KOREAN_REQUEST, attended, evaluated, owner_file, refused  # noqa: F401


def fill(skeleton: str) -> str:
    """The skeleton with a word in place of every `<...>` part."""
    return re.sub(r"<[^<>\n]*>", "filled in", skeleton)


def test_next_at_the_brief_step_prints_the_formats_of_the_record_and_the_questions(tmp_path, capsys):
    result = evaluated(tmp_path)
    formats = {Path(entry["file"]).parent.name: entry for entry in result["step"]["format"]}
    assert set(formats) == {"answers", "questions"}
    assert 'references/record.md, section "Shape"' in formats["answers"]["guide"]
    assert "references/questions.md" in formats["questions"]["guide"] and "owner's language" in formats["questions"]["guide"]
    assert cli_main(["next", "--task", TASK, "--root", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["step"]["format"] == result["step"]["format"]
    assert cli_main(["next", "--task", TASK, "--root", str(tmp_path)]) == 0
    text = capsys.readouterr().out
    assert f"format of .lapis/answers/{TASK}.md:" in text and "## Answers" in text and "lapis-questions: brief" in text


def test_the_record_skeleton_is_a_brief_record_as_it_stands_and_once_filled_in(tmp_path):
    skeleton = next(e["skeleton"] for e in evaluated(tmp_path)["step"]["format"] if e["file"].endswith("answers/" + TASK + ".md"))
    for text in (skeleton, fill(skeleton)):
        assert brief.problem(text) is None and brief.rounds_problem(text, "the record") is None
        record(tmp_path, "answers", text, 100)
        assert brief.owed(tmp_path, TASK, planned=False) is None
    assert next_step.evaluate(tmp_path, TASK)["step"]["id"] == "requirements"


def test_the_questions_skeleton_waits_once_marked_and_is_no_text_to_copy_for_a_korean_owner(tmp_path):
    skeleton = next(e["skeleton"] for e in evaluated(tmp_path)["step"]["format"] if e["file"].endswith("questions/" + TASK + ".md"))
    assert skeleton.startswith("lapis-questions: brief\n")
    ask(tmp_path, fill(skeleton).removeprefix("lapis-questions: brief\n"), 200)
    assert evaluated(tmp_path)["state"] == "waiting-for-user"
    owner_file(tmp_path, KOREAN_REQUEST)
    assert refused(evaluated(tmp_path), "Korean")


def test_the_wait_on_brief_questions_names_the_record_format(tmp_path):
    ask(tmp_path, ENGLISH_QUESTIONS, 200)
    result = evaluated(tmp_path)
    assert result["state"] == "waiting-for-user"
    assert [Path(e["file"]).parent.name for e in result["step"]["format"]] == ["answers"]


def test_the_direction_and_references_steps_name_their_guide_sections():
    answers = direction.formats(TASK)
    assert answers[0]["schema"].endswith("direction/schema.yaml") and 'section "The proposal"' in answers[0]["guide"]
    assert 'section "Recording answers"' in answers[1]["guide"] and answers[1]["skeleton"].startswith("## Direction 1")
    assert direction.step(TASK, "why")["format"] == answers
    assert 'section "4. Write the record"' in references.formats(TASK)[0]["guide"]
