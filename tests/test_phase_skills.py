"""A phase is not silently complete when its required sub-skill was never loaded."""
from pathlib import Path

from lapis_design import next_step, shared_dir
from lapis_design.cli import main as cli_main
from procedure_support import TASK, make_project


def test_the_release_phase_owes_its_review_skill_before_running_the_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    make_project(tmp_path)
    # make_project normally prepares loaded skills; this project deliberately lacks them.
    folder = tmp_path / ".lapis/skills" / TASK
    if folder.exists():
        for file in folder.glob("*.json"):
            file.unlink()
    result = next_step.evaluate(tmp_path, TASK)
    assert result["step"]["id"] == "skill-load"
    assert result["step"]["skill"] == "ultramarine"
    assert result["then"]["id"] == "release"


def test_loading_the_named_sections_unblocks_only_the_current_context(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    monkeypatch.setenv("LAPIS_CONTEXT", "critic-context")
    make_project(tmp_path)
    source = shared_dir().parent / "skills/ultramarine"
    args = ["skill", "loaded", "--root", str(tmp_path), "--task", TASK, "--skill", "ultramarine",
            "--context", "critic-context", "--read", str(source / "SKILL.md"),
            "--read", str(source / "references/pre-show-review.md") + "#Evidence"]
    assert cli_main(args) == 0
    assert next_step.evaluate(tmp_path, TASK)["step"]["id"] == "release"
    monkeypatch.setenv("LAPIS_CONTEXT", "another-context")
    assert next_step.evaluate(tmp_path, TASK)["step"]["id"] == "skill-load"


def test_a_skill_record_cannot_claim_a_section_that_does_not_exist(tmp_path):
    source = shared_dir().parent / "skills/lps-copy"
    assert cli_main(["skill", "loaded", "--root", str(tmp_path), "--task", TASK, "--skill", "lps-copy",
                     "--context", "copy-session", "--read", str(source / "SKILL.md") + "#No such section"]) == 2
    assert not (tmp_path / ".lapis/skills" / TASK / "lps-copy.json").exists()


def test_a_plan_phase_names_copy_then_system_as_missing_procedure_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    make_project(tmp_path)
    (tmp_path / f".lapis/plans/{TASK}.yaml").unlink()
    folder = tmp_path / ".lapis/skills" / TASK
    if folder.exists():
        for file in folder.glob("*.json"):
            file.unlink()
    result = next_step.evaluate(tmp_path, TASK)
    assert result["step"]["id"] == "skill-load"
    assert result["step"]["skill"] == "lps-copy"
    assert result["then"]["id"] == "plan"


def test_korean_locale_variants_require_the_role_and_register_section(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    make_project(tmp_path)  # the plan uses ko-KR, not only the bare ko tag
    source = shared_dir().parent / "skills/lps-copy"
    args = ["skill", "loaded", "--root", str(tmp_path), "--task", TASK, "--skill", "lps-copy",
            "--context", "korean-copy", "--read", str(source / "SKILL.md"),
            "--read", str(source / "references/interface-copy.md") + "#One owner for every string"]
    assert cli_main(args) == 2
    assert cli_main(args + ["--read", str(source / "references/interface-copy.md") + "#Korean"]) == 0


def test_a_later_phase_cannot_silently_skip_the_plans_copy_and_system_loads(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    make_project(tmp_path)
    for skill in ("lps-copy", "lps-system"):
        (tmp_path / ".lapis/skills" / TASK / f"{skill}.json").unlink()
    result = next_step.evaluate(tmp_path, TASK)
    assert result["step"]["id"] == "skill-load"
    assert result["step"]["skill"] == "lps-copy"
    assert result["then"]["id"] == "release"


def test_cold_brief_and_references_are_not_blocked_by_later_sub_skill_loads(tmp_path, monkeypatch):
    from procedure_support import BRIEF_RECORD, record

    monkeypatch.setenv("LAZULI_DB", "")
    assert next_step.evaluate(tmp_path, TASK)["step"]["id"] == "brief"
    record(tmp_path, "answers", BRIEF_RECORD, 50)
    assert next_step.evaluate(tmp_path, TASK)["step"]["id"] == "references"
    assert not (tmp_path / ".lapis/skills").exists()
