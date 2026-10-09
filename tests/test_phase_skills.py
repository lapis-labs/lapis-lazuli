"""A phase is not silently complete when its required sub-skill was never loaded, and the skill text keeps the
steps and prohibitions the spec lock-in and the checks against gaming depend on."""
import re
from pathlib import Path

import pytest

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


def test_cold_brief_requirements_and_references_are_not_blocked_by_later_sub_skill_loads(tmp_path, monkeypatch):
    from procedure_support import BRIEF_RECORD, record, seal_requirements

    monkeypatch.setenv("LAZULI_DB", "")
    assert next_step.evaluate(tmp_path, TASK)["step"]["id"] == "brief"
    record(tmp_path, "answers", BRIEF_RECORD, 50)
    assert next_step.evaluate(tmp_path, TASK)["step"]["id"] == "requirements"
    seal_requirements(tmp_path)
    assert next_step.evaluate(tmp_path, TASK)["step"]["id"] == "references"
    assert not (tmp_path / ".lapis/skills").exists()


# --- The skill text that drives the spec lock-in and the checks against gaming -----------------------------------
# These read the sources the build copies into every plugin: a skill that stops naming a step, a record, or a
# prohibition changes what the maker does, even when the CLI still enforces it.
SOURCES = shared_dir().parent                     # src/ in a checkout


def source(skill: str, part: str = "SKILL.md") -> str:
    """A skill's source file with its line breaks folded, so a wrapped sentence still matches."""
    return " ".join((SOURCES / "skills" / skill / part).read_text(encoding="utf-8").split())


OWED = [
    # the requirement record: sealed after the brief, before the references
    ("lps-brief seals the owner's words after its record", "lps-brief", "SKILL.md",
     r"lapis-design requirements seal --task <task> --from <the owner's brief file>"),
    ("lapis orders requirements between brief and references", "lapis", "SKILL.md",
     r"order is brief, requirements, references, direction, plan, then code"),
    ("lapis names the seal", "lapis", "SKILL.md", r"`requirements seal`"),
    ("the record says what the seal reads", "lps-brief", "references/record.md", r"At most five `--from` files"),
    ("a drop is the owner's quoted reply", "lps-brief", "references/record.md",
     r"\[declared\] R3f2a1c: drop — <the owner's words>"),
    ("a narrowing is the owner's quoted reply", "lps-brief", "references/record.md",
     r"\[declared\] R9b40de: narrow — <the owner's words>"),
    # approval on a rendered slice, with candidates only where the harness can ask
    ("lapis names the slice step", "lapis", "SKILL.md", r"`next` names `slice`"),
    ("approval is asked on the rendered slice, not the summary", "lapis", "SKILL.md",
     r"do not ask them to approve the plan on that text: build the slice and ask on the rendered page"),
    ("a slice is the first view and one section at both widths", "lapis", "SKILL.md",
     r"the first view and the one section the brief puts first, not the whole page, and capture both at 390 and 1440"),
    ("candidates need a question tool", "lapis", "SKILL.md",
     r"When this harness has a question tool, you may show two or three candidates that differ in composition or concept"),
    ("a reordering is not a candidate", "lapis", "SKILL.md", r"a reordering or the same layout in another palette is not one"),
    ("without a question tool one slice is shown", "lapis", "SKILL.md", r"Without a question tool, show one slice"),
    ("the pick is recorded for the seal", "lapis", "SKILL.md", r"\[declared\] Slice: <the chosen page's URL as linked>"),
    ("the pick among roughs is in the record guide", "lps-brief", "references/record.md", r"\[declared\] Pick: C2 — <the owner's words>"),
    # the direction conversation between the references and the plan
    ("lapis names the direction conversation and its step", "lapis", "SKILL.md",
     r"hold the direction conversation \(`references/direction-conversation.md`\): `next` names `owner-direction`"),
    ("a named style is decoded with the owner, not alone", "lapis", "SKILL.md", r"it is decoded with the owner, not alone"),
    ("the direction guide says what the three questions are", "lapis", "references/direction-conversation.md",
     r"what a named style does.*how each core object is represented.*what a signature element carries"),
    ("the direction guide has its answer grammar", "lapis", "references/direction-conversation.md",
     r"- \[declared\] K2 ticker band: drop — \"<owner words>\""),
    ("lapis names the diverge step and says the CLI draws", "lapis", "SKILL.md",
     r"make the rough first views \(`references/diverge.md`\): `next` names `diverge` until .*The CLI draws each rough's reference direction"),
    ("the roughs differ in representation and color allocation, never decoration", "lapis", "references/diverge.md",
     r"differ in three ways|differ in how the open core objects are represented, how color is allocated"),
    ("the draws are the CLI's and a resample is recorded", "lapis", "references/diverge.md",
     r"The draws are the CLI's: you cannot choose them"),
    ("an owner-requested variant is drawn with reason owner", "lapis", "references/diverge.md", r"drawn with `reason: owner`"),
    ("the slice shows one page built from the pick", "lapis", "references/diverge.md",
     r"The slice shows one page, built from the pick"),
    ("the brief leaves the visual direction to the conversation in lapis", "lps-brief", "references/research.md",
     r"Do not ask in the brief; the direction conversation in `lapis` asks what a style does"),
    ("a plain approval is untagged, not a requirement row", "lapis", "SKILL.md",
     r"A plain approval \(\"looks right, go on\"\) is an untagged item \(`- Approved the slice: <their words>`\), because every `\[declared\]` item becomes a requirement row"),
    ("the record guide keeps approval out of the rows", "lps-brief", "references/record.md",
     r"Record an owner's plain approval \(\"looks right, go on\"\) as an untagged item"),
    ("a stale owner block is pasted again", "lapis", "SKILL.md",
     r"a new critic report or draft record makes its marker stale: run `lapis-design draft check` again and paste the block again"),
    # the owner block
    ("lapis pastes the owner block unchanged", "lapis", "SKILL.md",
     r"`lapis-owner-block <sha8>` line\. Paste it unchanged ahead of your own summary at `done`, and into the questions file"),
    ("lapis never writes the block or the CLI records", "lapis", "SKILL.md",
     r"`lapis-design` alone writes `\.lapis/requirements/`, `state/`, `changes/`, and `owner/`"),
    ("ultramarine pastes the owner block unchanged", "ultramarine", "SKILL.md", r"paste it unchanged ahead of the report"),
    # the critic and the disputes
    ("lapis builds the critic's input with the packet", "lapis", "SKILL.md", r"`lapis-design critic packet --task <task>`"),
    ("ultramarine runs the critic on the packet", "ultramarine", "SKILL.md",
     r"reading only the critic packet\. `lapis-design critic packet --task <task>` writes"),
    ("a report counts only for its packet", "ultramarine", "SKILL.md", r"names its packet in `target\.packet` and counts only for that one"),
    ("a keep is judged by case_when without the reason", "ultramarine", "SKILL.md", r"packet carries as `case_when`.*?not given the maker's reason"),
    ("the checker's source is not read to argue", "lapis", "SKILL.md", r"Do not open the `lapis_design` source to argue with a finding"),
    ("a wrong finding goes to the disputes file", "lapis", "SKILL.md", r"`\.lapis/disputes/<task>\.yaml`"),
    ("a dispute does not clear the finding", "lapis", "SKILL.md", r"A dispute does not clear the finding"),
    ("the critic re-judges a dispute without the reason", "ultramarine", "SKILL.md",
     r"`\.lapis/disputes/<task>\.yaml`.*?re-judges it on the captures without your reason"),
    # no pattern kills
    ("lapis forbids pattern kills", "lapis", "SKILL.md",
     r"Never stop a process by pattern \(`pkill`, `killall`, or a `pgrep` piped to `kill`\).*?Stop only a process id a command recorded"),
    ("ultramarine forbids pattern kills", "ultramarine", "SKILL.md",
     r"Never stop a process by pattern \(`pkill`, `killall`, or a `pgrep` piped to `kill`\).*?Stop only a process id a command recorded"),
    # copy stays provisional until it has been seen rendered, and a source's claims go to the owner
    ("lapis: copy is provisional", "lapis", "SKILL.md", r"Copy is provisional until the owner has seen it rendered"),
    ("lps-copy: key copy is provisional", "lps-copy", "SKILL.md",
     r"Key copy is provisional until the owner has seen it rendered"),
    ("no final spec for a delegate", "lapis", "SKILL.md",
     r"Never call it final in a spec, an assignment to another agent, or a handoff"),
    ("a delegate gets one section by ids or a packet", "lapis", "SKILL.md",
     r"one section, or one handoff scope, per worker, as a handoff packet or as text that cites the requirement ids"),
    ("a source's claim about history goes to the owner", "lps-copy", "SKILL.md",
     r"history, origin, naming, or third parties is a claim for the owner to confirm, not a fact"),
    ("keeping certainty is not verifying", "lps-copy", "SKILL.md", r"Keeping a source's certainty is not verifying it"),
]


@pytest.mark.parametrize(("behavior", "skill", "part", "pattern"), OWED, ids=[row[0] for row in OWED])
def test_the_skill_text_says_what_the_maker_must_do(behavior, skill, part, pattern):
    assert re.search(pattern, source(skill, part)), f"{skill}/{part} no longer says: {behavior}"


FINAL_COPY = re.compile(r"\bcopy\s+(?:is|are|stays|remains)\s+(?:final|frozen|locked)\b|\bfinal copy\b", re.IGNORECASE)


def test_no_instruction_calls_copy_final_before_it_has_been_seen_rendered():
    texts = {path: path.read_text(encoding="utf-8")
             for folder in ("skills", "agents", "shared") for path in (SOURCES / folder).rglob("*.md")}
    assert len(texts) > 50                                   # the sources were found
    assert {path.relative_to(SOURCES).as_posix() for path, text in texts.items() if FINAL_COPY.search(text)} == set()


def critic_inputs() -> str:
    text = (SOURCES / "agents" / "critic.md").read_text(encoding="utf-8")
    return re.search(r"^## Inputs\n(.*?)(?=^## )", text, re.MULTILINE | re.DOTALL).group(1)


MAKER_FILES = (".lapis/plans/", ".lapis/answers/", ".lapis/drafts/", ".lapis/questions/", ".lapis/disputes/")


def test_the_critic_reads_the_packet_and_only_the_files_it_lists():
    inputs = critic_inputs()
    assert " ".join(inputs.split()).startswith("Read the packet and only the files it lists.")
    assert "`lapis-design critic packet --task <task>`" in inputs and "`.lapis/critic/<task>.packet.json`" in inputs
    # the maker's files may be named only to forbid them, never offered as an input
    folded = " ".join(inputs.split())
    for path in MAKER_FILES:
        for hit in re.finditer(re.escape(path), folded):
            assert re.split(r"(?<=\.)\s", folded[:hit.start()])[-1].startswith("Do not open"), path
    assert not [line for line in inputs.splitlines() if line.startswith("- ") and any(p in line for p in MAKER_FILES)]
