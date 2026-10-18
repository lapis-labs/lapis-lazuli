"""The records a run writes by hand have a skeleton the CLI prints: the schema's shape with nothing decided, which fails the
record's own check until it is filled."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from lapis_design import direction, draft, owner, requirements, shared_dir, skeleton, slice_step
from lapis_design.cli import main as cli_main
from procedure_support import BRIEF_RECORD, DIRECTION_PROPOSAL, TASK, ask, make_project, record, save
from test_draft_review import CRITIC, EXTRACT, LINT, URL, critic, finding, reviewed  # noqa: F401
from test_draft_review import project  # noqa: F401


def schema(name: str) -> dict:
    return yaml.safe_load((shared_dir() / name).read_text(encoding="utf-8"))


def errors(document, name: str) -> list[str]:
    return [e.message for e in Draft202012Validator(schema(name)).iter_errors(document)]


def leaves(node):
    """Every scalar of a loaded skeleton, with its path."""
    if isinstance(node, dict):
        for key, value in node.items():
            for path, leaf in leaves(value):
                yield (key, *path), leaf
    elif isinstance(node, list):
        for index, value in enumerate(node):
            for path, leaf in leaves(value):
                yield (index, *path), leaf
    else:
        yield (), node


def only_nulls_or_ids(text: str, allowed: set[tuple]) -> None:
    """No leaf of the skeleton holds a value, apart from the ones the files fix (`allowed`, by path)."""
    for path, leaf in leaves(yaml.safe_load(text)):
        assert leaf is None or path in allowed, (path, leaf)


# ---------------------------------------------------------------- the plan

def test_the_plan_skeleton_has_the_schemas_required_shape_and_fails_until_filled():
    text = skeleton.plan("kiln-shop")
    document = yaml.safe_load(text)
    assert set(document) == set(schema("plan/schema.yaml")["required"])
    assert document["version"] == 0 and document["task"] == {"id": "kiln-shop", "title": None}
    only_nulls_or_ids(text, {("version",), ("task", "id")})
    assert errors(document, "plan/schema.yaml")
    assert "also required: world_materials, sources, direction, layout" in text    # what `mode: create` adds is named
    filled = copy.deepcopy(document)
    filled["mode"] = "repair"
    filled["task"]["title"] = "Kiln shop"
    filled["brief"] = {"subject": "a kiln shop", "one_job": "reserve a piece", "platform": ["web"], "locales": ["en"],
                       "product_frame": "e-commerce"}
    filled["defaults"] = [{"id": "type.system-default", "decision": "keep", "basis": "brief", "reason": "the brief says so"}]
    assert errors(filled, "plan/schema.yaml") == []


def test_the_plan_skeleton_of_a_mode_adds_the_keys_that_mode_requires_and_still_fails():
    text = skeleton.plan("kiln-shop", mode="create")
    document = yaml.safe_load(text)
    assert set(document) == set(schema("plan/schema.yaml")["required"]) | {"world_materials", "sources", "direction", "layout"}
    assert document["mode"] == "create" and "also required" not in text
    assert errors(document, "plan/schema.yaml")
    filled = copy.deepcopy(document)
    filled["task"]["title"] = "Kiln shop"
    filled["brief"] = {"subject": "a kiln shop", "one_job": "reserve a piece", "platform": ["web"], "locales": ["en"],
                       "product_frame": "e-commerce"}
    filled["defaults"] = [{"id": "type.system-default", "decision": "keep", "basis": "brief", "reason": "the brief says so"}]
    filled["world_materials"] = ["kiln shelf"]
    filled["sources"] = [{"ref": "PRODUCT.md"}]
    assert errors(filled, "plan/schema.yaml") == []


def test_a_plan_section_skeleton_shows_every_key_the_section_names_and_nothing_else():
    document = yaml.safe_load(skeleton.plan("kiln-shop", "brief"))
    assert list(document) == ["brief"]
    assert set(document["brief"]) == set(schema("plan/schema.yaml")["properties"]["brief"]["properties"])
    shown = {key: value for key, value in document["brief"].items() if key != "guidelines"}
    assert all(value is None or value == [None] or value == [] for value in shown.values())
    assert [sorted(item) for item in document["brief"]["guidelines"]] == [["basis", "id", "platforms", "route"]]     # a list shows one item to repeat
    with pytest.raises(KeyError):
        skeleton.plan(None, "no-such-section")


def test_the_skeleton_commands_print_the_skeleton(capsys):
    assert cli_main(["plan", "skeleton", "--task", "kiln-shop"]) == 0
    assert capsys.readouterr().out == skeleton.plan("kiln-shop")
    assert cli_main(["plan", "skeleton", "--section", "nope"]) == 2
    assert "the plan has no section nope" in capsys.readouterr().err


# ---------------------------------------------------------------- the draft record

def test_the_draft_skeleton_has_a_page_per_shown_link_the_shape_of_a_review_and_fails_until_filled(project):
    text = skeleton.draft(project, TASK)
    document = yaml.safe_load(text)
    assert document["version"] == 1 and document["task"] == TASK
    assert [page["url"] for page in document["pages"]] == [URL]
    only_nulls_or_ids(text, {("version",), ("task",), ("pages", 0, "url")})
    valid = reviewed(project)["pages"][0]
    page = document["pages"][0]
    assert set(valid) <= set(page) and set(page) - set(valid) == set()
    assert set(valid["review"]) <= set(page["review"]) <= set(valid["review"]) | {"behavior"}
    assert set(page["review"]["handled"][0]) == {"report", "finding", "disposition", "reason", "refs"}
    assert errors(document, "release/draft.schema.yaml")
    save(project, f"drafts/{TASK}.yaml", document)
    assert any("review record" in e or "does not match" in e or "null" in e or "type" in e for e in draft.check(project, TASK)[0])


def test_the_draft_skeleton_repeats_the_page_for_every_shown_link(project):
    ask(project, f"Approve these? {URL} and http://127.0.0.1:4173/other.html", 300)
    document = yaml.safe_load(skeleton.draft(project, TASK))
    assert [p["url"] for p in document["pages"]] == [URL, "http://127.0.0.1:4173/other.html"]
    assert all(p["render_task"] is None and p["direction"] is None for p in document["pages"])


# ---------------------------------------------------------------- the critic dispositions

def with_findings(project):
    """The shown page reviewed, its critic report holding five findings of four statuses: the record and the findings."""
    record_ = reviewed(project)
    findings = [finding("review.one"), finding("review.two", status="fixed"), finding("review.three"),
                finding("review.four", status="skipped"), finding("review.five")]
    critic(project, findings=findings)
    return record_, findings


def test_the_disposition_skeleton_lists_exactly_the_open_findings_of_the_report_and_fills_nothing(project):
    _, findings = with_findings(project)
    text = skeleton.dispositions(project / CRITIC, CRITIC)
    entries = yaml.safe_load(text)
    assert [e["finding"] for e in entries] == [i for i, f in enumerate(findings) if f["status"] == "open"] == [0, 2, 4]
    assert all(e["report"] == CRITIC for e in entries)
    for entry in entries:
        assert entry["disposition"] is None and entry["reason"] is None and entry["refs"] == []
        assert set(entry) == {"report", "finding", "disposition", "reason", "refs"}
    for number in (1, 3):                                            # a finding that is not open is named, and needs no entry
        assert f"# finding {number} (" in text and "needs no entry" in text
    for word in ("fixed", "justified-keep", "unresolved"):
        assert word in text.split("\n", 2)[1]                       # the allowed values are listed; none is chosen
    assert [line for line in text.splitlines() if line.strip().startswith("disposition:")] == ["  disposition: null"] * 3
    assert "waived" not in text


def test_the_disposition_skeleton_submitted_unfilled_fails_the_draft_check_and_passes_once_filled(project):
    record_, _ = with_findings(project)
    entries = yaml.safe_load(skeleton.dispositions(project / CRITIC, CRITIC))
    critic(project, findings=[finding("review.one"), finding("review.three"), finding("review.five")])
    entries = [{**e, "finding": i} for i, e in enumerate(entries)]       # the report as rewritten holds the three, numbered 0 to 2
    record_["pages"][0]["review"]["handled"] = copy.deepcopy(entries)
    save(project, f"drafts/{TASK}.yaml", record_)
    found, _ = draft.check(project, TASK)
    assert found and "does not match" in found[0] or any("disposition" in e for e in found)
    filled = copy.deepcopy(record_)
    for entry in filled["pages"][0]["review"]["handled"]:
        entry.update(disposition="justified-keep", reason="The page shows the product's own settings", refs=["shown-390.png"])
    save(project, f"drafts/{TASK}.yaml", filled)
    assert draft.check(project, TASK)[0] == []


def test_the_missing_disposition_error_names_the_skeleton_command(project):
    record_, _ = with_findings(project)
    critic(project, findings=[finding("review.one")])
    save(project, f"drafts/{TASK}.yaml", record_)
    found, _ = draft.check(project, TASK)
    assert f"lapis-design critic dispositions --skeleton --report {CRITIC}" in found[0]


def test_the_disposition_command_reads_a_report_and_refuses_a_file_that_is_none(project, capsys):
    with_findings(project)
    assert cli_main(["critic", "dispositions", "--skeleton", "--report", CRITIC, "--root", str(project)]) == 0
    assert [e["finding"] for e in yaml.safe_load(capsys.readouterr().out)] == [0, 2, 4]
    (project / "notes.json").write_text(json.dumps({"hello": 1}))
    assert cli_main(["critic", "dispositions", "--skeleton", "--report", "notes.json", "--root", str(project)]) == 2
    assert "not a critic or lint report" in capsys.readouterr().err
    with pytest.raises(SystemExit):                                  # a disposition is never printed filled: the flag is the form
        cli_main(["critic", "dispositions", "--report", CRITIC, "--root", str(project)])


# ---------------------------------------------------------------- the answer rows

@pytest.fixture
def conversation(tmp_path):
    root = make_project(tmp_path)
    save(root, f"direction/{TASK}.yaml", DIRECTION_PROPOSAL)
    record(root, "answers", BRIEF_RECORD, 50)                       # the owner has answered the brief and nothing of the direction
    return root


def test_the_answer_skeleton_names_the_open_items_with_their_choices_and_answers_none(conversation):
    text = skeleton.answers(conversation, TASK)
    assert "## Direction 1" in text and "- [TAG] O1 the monthly firing log: \n" in text
    assert "O1: a | b | all | default | other" in text and "Pick" not in text      # the pick comes after turn one
    assert "[declared]" not in text.replace("`[declared]`", "") and "[assumed]" not in text.replace("`[assumed]`", "")
    rows_before = requirements.rows(conversation, TASK)
    record(conversation, "answers", BRIEF_RECORD + "\n" + text[text.index("## Direction 1"):], 100)
    assert [i["state"] for i in direction.items(conversation, TASK)] == ["open"]          # no choice, no tag: still open
    assert direction.owed(conversation, TASK, 1)
    assert requirements.rows(conversation, TASK) == rows_before                            # and no row for the requirement record


def test_a_filled_answer_row_counts_and_an_unfilled_one_does_not(conversation):
    text = skeleton.answers(conversation, TASK)
    row = "- [declared] O1 the monthly firing log: a,b — \"both, please\""
    record(conversation, "answers", BRIEF_RECORD + "\n" + text[text.index("## Direction 1"):].replace(
        "- [TAG] O1 the monthly firing log: ", row), 100)
    [item] = direction.items(conversation, TASK)
    assert item["state"] == "narrowed" and item["choice"] == ["a", "b"] and item["by"] == "owner"
    after = skeleton.answers(conversation, TASK)                     # the items stand; the pick of the sealed roughs is what is open
    assert "O1" not in after and "## Direction 2\n\n- [TAG] Pick: \n" in after and "Pick: C1 | C2 | C3" in after


def test_the_answer_skeleton_lists_an_open_core_finding_with_no_decision(project):
    reviewed(project)
    critic(project, findings=[finding("review.world-materials", approval_impact="core-product-explanation")])
    text = skeleton.answers(project, TASK)
    assert "- [TAG] Ask finding-vs-decision: review.world-materials — \n" in text
    record(project, "answers", "## Open core findings\n\n- [TAG] Ask finding-vs-decision: review.world-materials — \n", 100)
    assert not slice_step._decided(project, TASK, "review.world-materials")
    record(project, "answers", "## Open core findings\n\n- [declared] Ask finding-vs-decision: review.world-materials — \"keep\"\n", 101)
    assert slice_step._decided(project, TASK, "review.world-materials")
    assert owner.core_findings(project, TASK)


def test_next_names_the_skeleton_commands_at_the_steps_that_have_the_run_write_the_records(tmp_path, project):
    from lapis_design import next_step

    result = next_step.evaluate(project, TASK)
    assert result["step"]["id"] == "draft-review"
    commands = [e["command"] for e in result["step"]["format"]]
    assert f"lapis-design draft skeleton --task {TASK}" in commands
    assert any(c.startswith("lapis-design critic dispositions --skeleton --report") for c in commands)
    assert "skeleton: run `lapis-design draft skeleton" in next_step._text(result)
    assert any(e.get("command") == f"lapis-design answers skeleton --task {TASK}" for e in direction.formats(TASK))
    bare = make_project(tmp_path / "bare")
    (bare / ".lapis" / "plans" / f"{TASK}.yaml").unlink()
    plan_step = next_step.evaluate(bare, TASK)["step"]
    assert plan_step["id"] in ("plan", "brief") and (plan_step["id"] != "plan" or plan_step["format"][0]["command"].startswith(
        f"lapis-design plan skeleton --task {TASK}"))
