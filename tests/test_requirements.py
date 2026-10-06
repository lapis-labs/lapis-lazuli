"""The requirement record: the owner's own words, copied by the CLI into `.lapis/requirements/<task>.json`, and what
`next` and the keep evidence do with it."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import pytest
import yaml

from lapis_design import integrity, keep_evidence, next_step, requirements
from lapis_design.cli import main as cli_main
from procedure_support import BRIEF_RECORD, TASK, make_project, record, reply, update

BRIEF = """# Lapis site

The site explains the editor to a first-time visitor.
It must work on a phone.

## Home

- A hero with the product name and one sentence.
  - Main preview: a fader, switch, or animation that the visitor can touch.
  - A link to the docs.
- A three-step "how it starts" row

1. Install the package
2) Run the first command

## Pages

| Page | Purpose |
|------|---------|
| Docs | Link out to the manual |
| Changelog | Show the last five releases |

```sh
bun add lapis
```

Quiet tone
----------

Never claim a feature the editor does not have.
"""


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    record(tmp_path, "answers", BRIEF_RECORD, 50)
    (tmp_path / "brief.md").write_text(BRIEF, encoding="utf-8")
    return tmp_path


def seal(root: Path, *owner_files: str, code: int = 0) -> int:
    argv = ["requirements", "seal", "--task", TASK, "--root", str(root)]
    for name in owner_files:
        argv += ["--from", name]
    assert (result := cli_main(argv)) == code
    return result


def loaded(root: Path) -> dict:
    return json.loads((root / f".lapis/requirements/{TASK}.json").read_text(encoding="utf-8"))


def row_ids(doc: dict) -> dict[str, str]:
    return {row["text"]: row["id"] for row in doc["rows"]}


def expected_id(text: str) -> str:
    key = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    return "R" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:6]


# ---- 1. extraction

def test_extraction_gives_one_row_for_each_item_table_row_code_block_and_paragraph(project):
    rows = requirements.extract(project / "brief.md", "brief.md")
    found = [(row["kind"], row.get("section"), row["text"]) for row in rows]
    assert found == [
        ("paragraph", "Lapis site", "The site explains the editor to a first-time visitor.\nIt must work on a phone."),
        ("item", "Home", "A hero with the product name and one sentence."),
        ("item", "Home", "Main preview: a fader, switch, or animation that the visitor can touch."),
        ("item", "Home", "A link to the docs."),
        ("item", "Home", 'A three-step "how it starts" row'),
        ("item", "Home", "Install the package"),
        ("item", "Home", "Run the first command"),
        ("table-row", "Pages", "Docs | Link out to the manual"),
        ("table-row", "Pages", "Changelog | Show the last five releases"),
        ("code", "Pages", "bun add lapis"),
        ("paragraph", "Quiet tone", "Never claim a feature the editor does not have."),
    ]


def test_a_parent_item_excludes_its_children_and_the_fader_sub_bullet_is_a_row_of_its_own(project):
    rows = {row["text"]: row for row in requirements.extract(project / "brief.md", "brief.md")}
    parent = rows["A hero with the product name and one sentence."]
    assert "fader" not in parent["text"]
    fader = rows["Main preview: a fader, switch, or animation that the visitor can touch."]
    assert fader["at"] == [{"path": "brief.md", "lines": [9, 9]}]
    assert parent["at"] == [{"path": "brief.md", "lines": [8, 8]}]


def test_a_wrapped_item_is_one_row_and_lines_cover_the_whole_block(tmp_path):
    (tmp_path / "b.md").write_text("- first line of an item\n  wrapped onto a second line\n\n```\ncode\nmore\n```\n",
                                   encoding="utf-8")
    rows = requirements.extract(tmp_path / "b.md", "b.md")
    assert [(r["text"], r["at"][0]["lines"]) for r in rows] == [
        ("first line of an item\nwrapped onto a second line", [1, 2]), ("code\nmore", [4, 7])]


def test_sealing_a_brief_gives_rows_with_ids_and_a_record_the_schema_accepts(project):
    seal(project, "brief.md")
    doc = loaded(project)
    assert requirements.validate(doc) == []
    assert len(doc["rows"]) == 11 and doc["removed"] == [] and doc["owner_decisions"] == []
    assert [s["kind"] for s in doc["sources"]] == ["owner-file", "answers"]
    assert all(re.fullmatch(r"R[0-9a-f]{6}", row["id"]) for row in doc["rows"])
    assert row_ids(doc)["Install the package"] == expected_id("Install the package")
    shown = requirements.record(project, TASK)
    assert shown == doc and requirements.sha256(project, TASK) == hashlib.sha256(
        (project / f".lapis/requirements/{TASK}.json").read_bytes()).hexdigest()


def test_the_show_command_lists_every_row_with_its_id_and_needs_a_record(project, tmp_path_factory, capsys):
    seal(project, "brief.md")
    capsys.readouterr()
    assert cli_main(["requirements", "show", "--task", TASK, "--root", str(project)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("11 rows from brief.md, .lapis/answers/")
    assert f"{expected_id('Install the package')}  Install the package  (Home)" in out
    empty = tmp_path_factory.mktemp("empty")
    assert cli_main(["requirements", "show", "--task", TASK, "--root", str(empty)]) == 1
    assert "does not exist" in capsys.readouterr().err


# ---- 2. ids and changes

def test_the_same_text_keeps_its_id_across_a_reseal_whatever_its_case_or_spacing(project):
    seal(project, "brief.md")
    first = row_ids(loaded(project))
    (project / "brief.md").write_text(BRIEF.replace("Install the package", "  INSTALL   the\tPackage"), encoding="utf-8")
    seal(project)
    again = loaded(project)
    assert "INSTALL the Package" in {" ".join(text.split()) for text in row_ids(again)}      # as written, spacing apart
    assert {row["id"] for row in again["rows"]} == set(first.values()) and again["removed"] == []


def test_a_changed_text_is_a_new_row_the_old_one_is_removed_and_the_change_is_logged(project):
    seal(project, "brief.md")
    before = row_ids(loaded(project))
    (project / "brief.md").write_text(BRIEF.replace("Install the package", "Install the package with bun"),
                                      encoding="utf-8")
    seal(project)
    doc = loaded(project)
    assert doc["removed"] == [{"id": before["Install the package"], "text": "Install the package",
                               "at": [{"path": "brief.md", "lines": [13, 13]}]}]
    assert row_ids(doc)["Install the package with bun"] == expected_id("Install the package with bun")
    rows = [r for r in integrity.changes(project, TASK) if r["kind"] == "requirements"]
    assert [(r["pointer"], r["before"], r["after"]) for r in rows] == [
        (f"/requirements/{before['Install the package']}", "Install the package", None),
        (f"/requirements/{expected_id('Install the package with bun')}", None, "Install the package with bun")]


def test_text_that_goes_away_without_a_seal_is_found_by_the_next_call_that_reads_the_plan(project):
    seal(project, "brief.md")
    (project / "brief.md").write_text(BRIEF.replace("- A three-step \"how it starts\" row\n", ""), encoding="utf-8")
    changes = requirements.refresh(project, TASK)
    assert [(c["before"], c["after"]) for c in changes] == [('A three-step "how it starts" row', None)]
    assert requirements.refresh(project, TASK) == []                     # nothing left to find
    assert [row["text"] for row in loaded(project)["removed"]] == ['A three-step "how it starts" row']
    (project / "brief.md").write_text(BRIEF, encoding="utf-8")          # the owner put it back: same text, same id
    assert [c["after"] for c in requirements.refresh(project, TASK)] == ['A three-step "how it starts" row']
    assert loaded(project)["removed"] == []


def test_a_sealed_file_is_never_forgotten_and_a_missing_one_removes_its_rows(project):
    (project / "second.md").write_text("- A second file of the owner\n", encoding="utf-8")
    seal(project, "brief.md")
    seal(project, "second.md")
    assert [s["path"] for s in loaded(project)["sources"]] == ["brief.md", "second.md", f".lapis/answers/{TASK}.md"]
    seal(project)                                                        # sealing without --from keeps both
    assert len(loaded(project)["rows"]) == 12
    (project / "second.md").unlink()
    assert [c["before"] for c in requirements.refresh(project, TASK)] == ["A second file of the owner"]
    assert [s["path"] for s in loaded(project)["sources"]][:2] == ["brief.md", "second.md"]


def test_the_same_text_in_two_places_is_one_row_with_two_places(project):
    (project / "brief.md").write_text("# A\n\n- Keep the footer plain\n\n# B\n\n- keep the  footer PLAIN\n", encoding="utf-8")
    seal(project, "brief.md")
    (row,) = loaded(project)["rows"]
    assert row["text"] == "Keep the footer plain"
    assert [place["lines"] for place in row["at"]] == [[3, 3], [7, 7]]


def find_prefix_collision() -> tuple[str, str]:
    seen: dict[str, str] = {}
    for n in range(200_000):
        text = f"Requirement number {n}"
        prefix = expected_id(text)
        if prefix in seen:
            return seen[prefix], text
        seen[prefix] = text
    raise AssertionError("no collision found")


def test_two_texts_that_share_six_hex_digits_get_eight_each(project):
    one, two = find_prefix_collision()
    (project / "brief.md").write_text(f"- {one}\n- {two}\n- Something else entirely\n", encoding="utf-8")
    seal(project, "brief.md")
    ids = row_ids(loaded(project))
    assert ids[one] != ids[two] and ids[one][:7] == ids[two][:7] == expected_id(one)
    assert len(ids[one]) == len(ids[two]) == 9 and len(ids["Something else entirely"]) == 7
    assert requirements.validate(loaded(project)) == []


# ---- 3. the declared answers

ANSWERS = """## Found

- The studio fires once a month. Source: PRODUCT.md.

## Answers

- [declared] Q1 Who buys? Craft lovers in their 30s and 40s.
- [known] Q2 What is the one job? Reserve a piece. Source: PRODUCT.md.
- [assumed] Q3 Which tone? Warm. Basis: nobody to ask; the request names none.
- [open] Q4 Which regions ship? No default fits.
- **[declared]** Q5 Is the date fixed? Yes: the first Saturday.
  - a sub-list inside an answer is part of it, not another row
"""


def test_declared_answers_become_rows_and_the_other_tags_do_not(project):
    record(project, "answers", ANSWERS, 60)
    seal(project)
    doc = loaded(project)
    assert [(r["kind"], r["section"], r["text"]) for r in doc["rows"]] == [
        ("declared", "Answers", "Q1 Who buys? Craft lovers in their 30s and 40s."),
        ("declared", "Answers", "Q5 Is the date fixed? Yes: the first Saturday.\n- a sub-list inside an answer is part of it, "
                                "not another row")]
    assert doc["rows"][0]["at"] == [{"path": f".lapis/answers/{TASK}.md", "lines": [7, 7]}]


def test_an_answer_the_owner_pasted_from_their_brief_is_one_row(project):
    record(project, "answers", ANSWERS + "- [declared] Install the package\n", 60)
    seal(project, "brief.md")
    row = next(r for r in loaded(project)["rows"] if r["text"] == "Install the package")
    assert row["kind"] == "item" and [p["path"] for p in row["at"]] == ["brief.md", f".lapis/answers/{TASK}.md"]


def test_a_brief_record_is_needed_before_anything_is_sealed(tmp_path, capsys):
    (tmp_path / "brief.md").write_text(BRIEF, encoding="utf-8")
    assert cli_main(["requirements", "seal", "--task", TASK, "--root", str(tmp_path), "--from", "brief.md"]) == 1
    assert "brief record is not in order" in capsys.readouterr().err
    assert not (tmp_path / ".lapis/requirements").exists()


# ---- 4. what --from refuses

@pytest.mark.parametrize("name, part", [
    (".lapis/answers/kiln-shop-landing.md", "is under .lapis/"),
    ("../outside.md", "is outside the project folder"),
    ("missing.md", "is not a file"),
    ("folder", "is not a regular file"),
    ("binary.md", "is not UTF-8 text"),
    ("big.md", "is larger than 200 KB"),
])
def test_from_refuses_a_path_that_is_not_the_owners_utf8_file_and_writes_nothing(project, capsys, name, part):
    (project.parent / "outside.md").write_text("- outside\n", encoding="utf-8")
    (project / "folder").mkdir()
    (project / "binary.md").write_bytes(b"- caf\xe9 not utf-8\n")
    (project / "big.md").write_text("- word\n" * 40_000, encoding="utf-8")
    seal(project, name, code=1)
    assert part in capsys.readouterr().err
    assert not (project / f".lapis/requirements/{TASK}.json").exists()


def test_from_refuses_an_absolute_path_outside_the_project(project, tmp_path_factory, capsys):
    other = tmp_path_factory.mktemp("elsewhere") / "brief.md"
    other.write_text("- outside\n", encoding="utf-8")
    seal(project, str(other), code=1)
    assert "is outside the project folder" in capsys.readouterr().err


def test_from_accepts_an_absolute_path_inside_the_project(project):
    seal(project, str(project / "brief.md"))
    assert loaded(project)["sources"][0]["path"] == "brief.md"


def test_more_than_five_files_are_refused(project, capsys):
    names = []
    for n in range(6):
        (project / f"f{n}.md").write_text(f"- file {n}\n", encoding="utf-8")
        names.append(f"f{n}.md")
    seal(project, *names, code=1)
    assert "6 files are more than the 5" in capsys.readouterr().err


def test_more_than_three_hundred_rows_are_refused_with_the_product_docs_message(project, capsys):
    (project / "README.md").write_text("".join(f"- Feature {n} of the product\n" for n in range(301)), encoding="utf-8")
    seal(project, "README.md", code=1)
    err = capsys.readouterr().err
    assert "301 rows are more than the 300" in err and "product docs belong in `context.product`/`context.other`" in err
    assert not (project / f".lapis/requirements/{TASK}.json").exists()
    (project / "README.md").write_text("".join(f"- Feature {n} of the product\n" for n in range(300)), encoding="utf-8")
    seal(project, "README.md")
    assert len(loaded(project)["rows"]) == 300


# ---- 5. the step

def test_next_gives_requirements_after_the_brief_and_references_after_the_seal(project):
    assert next_step.evaluate(project, TASK)["step"]["id"] == "requirements"
    result = next_step.evaluate(project, TASK)
    assert result["step"]["command"] == f"lapis-design requirements seal --task {TASK}"
    assert f".lapis/requirements/{TASK}.json does not exist" in result["step"]["why"]
    seal(project, "brief.md")
    assert next_step.evaluate(project, TASK)["step"]["id"] == "references"


def test_a_create_plan_gets_requirements_too_and_a_repair_plan_never_does(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    assert next_step.evaluate(root, TASK)["step"]["id"] == "release"
    (root / f".lapis/requirements/{TASK}.json").unlink()
    assert next_step.evaluate(root, TASK)["step"]["id"] == "requirements"
    (root / f".lapis/requirements/{TASK}.json").write_text("{\"version\": 1}", encoding="utf-8")
    result = next_step.evaluate(root, TASK)
    assert result["step"]["id"] == "requirements" and "not a requirement record" in result["step"]["why"]
    for mode in ("redesign", "repair"):
        update(root, f"plans/{TASK}.yaml", lambda plan, mode=mode: plan.update(mode=mode))
        assert next_step.evaluate(root, TASK)["step"]["id"] != "requirements", mode


def test_page_code_waits_for_the_requirement_record_in_an_unattended_run(project, monkeypatch):
    from lapis_design import order

    assert "requirements" in order.BEFORE_CODE
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    event = {"cwd": str(project), "tool_input": {"file_path": str(project / "index.html")}}
    refusal = order.decide(event, {"LAPIS_UNATTENDED": "1", "LAPIS_TASK": TASK})
    reason = refusal["hookSpecificOutput"]["permissionDecisionReason"]
    assert "requirement record `.lapis/requirements/kiln-shop-landing.json`" in reason and "requirements, references" in reason


# ---- 6. the owner's decisions

def test_an_owner_decision_lands_in_owner_decisions_with_the_line_verbatim_and_is_no_row(project):
    seal(project, "brief.md")
    fader = row_ids(loaded(project))["Main preview: a fader, switch, or animation that the visitor can touch."]
    line = f"- [declared] {fader}: drop — no fader in the first version, the owner said"
    reply(project, line + "\n- [declared] Slice: http://localhost:4173/slice-b.html — this one\n", 60)
    changes = requirements.refresh(project, TASK)
    doc = loaded(project)
    assert doc["owner_decisions"] == [{"row": fader, "decision": "drop", "quote": line.removeprefix("- "),
                                       "at": {"path": f".lapis/answers/{TASK}.md", "line": 14}}]
    assert len(doc["rows"]) == 11                                         # neither the decision nor the pick is a row
    assert [(c["pointer"], c["before"]) for c in changes] == [
        (f"/requirements/owner_decisions/{fader}", None)]
    assert changes[0]["after"] == f"drop — [declared] {fader}: drop — no fader in the first version, the owner said"
    assert requirements.validate(doc) == []


def test_a_narrow_decision_needs_the_owners_words_and_a_dropped_row_stays_in_the_record(project):
    seal(project, "brief.md")
    rid = row_ids(loaded(project))["Install the package"]
    reply(project, f"- [declared] {rid}: narrow\n- [declared] {rid}: dropping — not a decision\n"
                   f"- [assumed] {rid}: drop — the agent's guess\n- [declared] {rid.upper()}: narrow - only bun\n", 60)
    requirements.refresh(project, TASK)
    doc = loaded(project)
    assert [(d["decision"], d["row"]) for d in doc["owner_decisions"]] == [("narrow", rid)]
    assert "Install the package" in row_ids(doc)


def test_removing_a_decision_line_is_a_change_too(project):
    seal(project, "brief.md")
    rid = row_ids(loaded(project))["Install the package"]
    reply(project, f"- [declared] {rid}: drop — not needed\n", 60)
    requirements.refresh(project, TASK)
    reply(project, "", 70)
    assert [(c["before"] is not None, c["after"]) for c in requirements.refresh(project, TASK)] == [(True, None)]
    assert loaded(project)["owner_decisions"] == []


def test_uncovered_names_the_rows_a_critic_report_does_not_judge(project):
    seal(project, "brief.md")
    ids = [row["id"] for row in loaded(project)["rows"]]
    report = {"requirements": [{"id": i, "state": "met"} for i in ids[:-2]]}
    assert requirements.uncovered(project, TASK, report) == ids[-2:]
    assert requirements.uncovered(project, TASK, {}) == ids
    assert requirements.uncovered(project, "other-task", {}) == []


# ---- 7. the keep evidence

CASE = {"id": "a-case", "when": "a condition the test states", "evidence": ["brief"]}


def gap(root: Path, quote: str, **plan) -> str | None:
    plan = {"task": {"id": TASK}, "brief": {"subject": "The studio explains the editor",
                                           "constraints": ["Keep dates in the studio's own format"]}, **plan}
    return keep_evidence.gap(CASE, {"evidence": {"brief": quote}}, keep_evidence.Sources(plan, root=root))


def test_with_a_record_the_keep_must_quote_a_row_and_the_plans_paraphrase_no_longer_holds(project):
    seal(project, "brief.md")
    assert gap(project, "Keep dates in the studio's own format") is not None         # the plan's own constraint
    assert gap(project, "never claim a feature the EDITOR does not have") is None    # a row, normalised
    assert gap(project, "a link to the docs") is None
    found = gap(project, "The studio explains the editor")
    assert found is not None and "evidence.brief is not a row of the requirement record" in found


def test_without_a_record_the_keep_is_read_against_the_plan_as_before(project):
    assert gap(project, "keep dates in the studio's own format") is None
    found = gap(project, "Never claim a feature the editor does not have")
    assert found is not None and "evidence.brief is not a line of brief" in found
    assert gap(project, "keep dates in the studio's own format", task="oops") is None     # no task id: the plan only


# ---- the contract

def test_the_example_record_passes_the_schema_and_the_schema_refuses_a_row_the_cli_would_not_write():
    from lapis_design import shared_dir

    example = json.loads((shared_dir() / "requirements/example.requirements.json").read_text(encoding="utf-8"))
    assert requirements.validate(example) == []
    example["rows"][0]["id"] = "R12"                                      # an id is six or eight hex digits
    example["rows"][1]["kind"] = "bullet"
    example["owner_decisions"][0]["decision"] = "delete"
    example["sources"][0]["sha256"] = "abc"
    assert len(requirements.validate(example)) == 4
