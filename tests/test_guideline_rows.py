"""Guideline rows: the behavior checklist items of the guidelines a plan names, kept in the requirement record from a lapis source
(never the owner's words) and judged by the critic through the packet."""
from __future__ import annotations

import json

import pytest
import yaml

from lapis_design import critic_packet, guidelines, requirements
from lapis_design.cli import main as cli_main
from procedure_support import TASK, row_id, update
from test_critic_packet import PLAN, REPORT, ROWS, edit, judged, packet, problems, project  # noqa: F401  (the project fixture)

ROUTE = {"kind": "official-docs", "ref": "https://example.org/docs"}


def entry(gid: str, platforms: list[str], **more) -> dict:
    return {"id": gid, "platforms": platforms, "basis": "suggested", "route": ROUTE, **more}


def name(project, *entries: dict) -> None:
    update(project, PLAN, lambda p: p["brief"].update(guidelines=list(entries)))
    requirements.refresh(project, TASK)


def doc(project) -> dict:
    return json.loads(requirements.record_path(project, TASK).read_text(encoding="utf-8"))


def ids(rows: list[dict]) -> list[str]:
    return [r["id"] for r in rows]


# ---------------------------------------------------------------- the record

def test_the_checklist_items_of_each_named_guideline_become_rows_from_a_lapis_source_and_the_owners_rows_are_untouched(project):
    owners = requirements.rows(project, TASK)
    name(project, entry("apple-hig", ["ios"]), entry("wcag-2.2", ["web"]))
    record = doc(project)
    expected = [row["id"] for row in guidelines.rows(yaml.safe_load((project / ".lapis" / "plans" / f"{TASK}.yaml").read_text()))]
    assert ids(record["guideline_rows"]) == expected and len(expected) == 19 + 20
    assert requirements.rows(project, TASK) == owners and ids(owners) == [row_id(t) for t in ROWS]   # not reworded, not added to
    assert all(r["id"].startswith("G:") and r["guideline"]["id"] in ("apple-hig", "wcag-2.2") for r in record["guideline_rows"])
    assert not any(r["id"].startswith("G:") for r in record["rows"]) and not any("at" in r for r in record["guideline_rows"])
    assert requirements.validate(record) == []
    assert requirements.guideline_rows(project, TASK) == record["guideline_rows"]
    assert ids(requirements.all_rows(project, TASK)) == [*ids(owners), *expected]


def test_a_row_says_what_it_asks_where_it_comes_from_and_what_measures_it(project):
    name(project, entry("apple-hig", ["ios"]), entry("wcag-2.2", ["web"]))
    by_id = {r["id"]: r for r in doc(project)["guideline_rows"]}
    size = by_id["G:apple-hig/target-size"]
    assert size["text"].startswith("A button or other tappable control has a hit region of at least 44 by 44 pt")
    assert size["section"] == "Buttons > Best practices" and size["guideline"]["url"] == "https://developer.apple.com/design/human-interface-guidelines/buttons"
    assert size["guideline"]["measure"] == "render" and size["guideline"]["check"] == "target-size" and size["guideline"]["platforms"] == ["ios"]
    assert size["guideline"]["threshold"]["unit"] == "pt" and size["guideline"]["threshold"]["value"] == 44     # kept in the guideline's own unit
    assert by_id["G:wcag-2.2/reflow"]["guideline"]["rules"] == ["layout.compact-overflow"]
    assert by_id["G:wcag-2.2/target-size-min"]["guideline"]["threshold"]["unit"] == "css-px"
    assert by_id["G:apple-hig/modality-purpose"]["guideline"]["measure"] == "judge"


def test_the_checklist_files_are_a_source_of_the_record_with_their_hash(project):
    name(project, entry("apple-hig", ["ios"]), entry("wcag-2.2", ["web"]))
    sources = {s["path"]: s for s in doc(project)["sources"]}
    for gid in ("apple-hig", "wcag-2.2"):
        assert sources[f"guideline:{gid}"] == {"path": f"guideline:{gid}", "sha256": guidelines.sha256(gid), "kind": "guideline"}
    assert {s["kind"] for s in sources.values()} >= {"owner-file", "answers", "guideline"}
    name(project)                                                       # no guideline named: the rows and the sources go with it
    assert "guideline_rows" not in doc(project) and not any(s["kind"] == "guideline" for s in doc(project)["sources"])


def test_only_the_platforms_an_entry_covers_give_rows_and_a_guideline_named_twice_gives_each_row_once(project):
    name(project, entry("apple-hig", ["web"]))
    assert "guideline_rows" not in doc(project)
    name(project, entry("material-3", ["android"]), entry("material-3", ["web"]))
    rows = {r["id"]: r for r in doc(project)["guideline_rows"]}
    assert len(rows) == len(guidelines.load("material-3")["items"])
    assert rows["G:material-3/target-size"]["guideline"]["platforms"] == ["android", "web"]
    assert rows["G:material-3/predictive-back"]["guideline"]["platforms"] == ["android"]       # an Android-only item
    assert rows["G:material-3/text-resizing"]["guideline"]["needs_review"] is True


def test_a_consult_only_or_unlisted_guideline_gives_no_row(project):
    name(project, entry("toss-tds", ["web"]), entry("daangn-seed", ["web"]), entry("other", ["web"], name="Acme", url="https://acme.example/"))
    assert "guideline_rows" not in doc(project)


def test_the_record_is_rebuilt_from_the_plan_and_has_the_same_bytes_for_the_same_inputs(project):
    name(project, entry("wcag-2.2", ["web"]))
    first = requirements.record_path(project, TASK).read_bytes()
    requirements.refresh(project, TASK)
    assert requirements.record_path(project, TASK).read_bytes() == first
    update(project, PLAN, lambda p: p["brief"]["guidelines"].append(entry("apple-hig", ["ios"])))       # any call that reads the plan notices
    requirements.refresh(project, TASK)
    assert len(doc(project)["guideline_rows"]) == 20 + 19


def test_an_owner_cannot_drop_a_guideline_row_by_quoting_it(project):
    name(project, entry("wcag-2.2", ["web"]))
    answers = project / ".lapis" / "answers" / f"{TASK}.md"
    answers.write_text(answers.read_text(encoding="utf-8") + "- [declared] G:wcag-2.2/reflow: drop — not for us\n", encoding="utf-8")
    requirements.refresh(project, TASK)
    record = doc(project)
    assert record["owner_decisions"] == [] and "G:wcag-2.2/reflow" in ids(record["guideline_rows"])       # a decision quotes an R id only


def test_the_show_command_lists_them_apart_from_the_owners_rows(project, capsys):
    name(project, entry("wcag-2.2", ["web"]))
    capsys.readouterr()
    assert cli_main(["requirements", "show", "--task", TASK, "--root", str(project)]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "2 rows from owner-brief.md, .lapis/answers/kiln-shop-landing.md"
    assert "20 guideline rows from the plan's guidelines (not the owner's words):" in out
    assert "G:wcag-2.2/target-size-min  [render]  A pointer target is at least 24 by 24 CSS px" in out


def test_a_record_with_a_malformed_guideline_row_is_not_a_record(project):
    name(project, entry("wcag-2.2", ["web"]))
    path = requirements.record_path(project, TASK)
    document = json.loads(path.read_text())
    document["guideline_rows"] = [{"id": "G:x/y"}]
    path.write_text(json.dumps(document), encoding="utf-8")
    assert requirements.record(project, TASK) is None and "guideline_rows" in requirements.owed(project, TASK)


# ---------------------------------------------------------------- the critic packet

def test_the_packet_lists_the_guideline_rows_after_the_owners_with_what_measures_each(project):
    name(project, entry("apple-hig", ["ios"]), entry("wcag-2.2", ["web"]))
    rows = packet(project)["requirements"]["rows"]
    assert [r["id"] for r in rows[:2]] == [row_id(t) for t in ROWS] and not any("guideline" in r for r in rows[:2])
    by_id = {r["id"]: r for r in rows}
    hig = by_id["G:apple-hig/target-size"]
    assert hig["text"].startswith("A button or other tappable control") and hig["section"] == "Buttons > Best practices"
    assert hig["guideline"]["check"] == "target-size" and hig["guideline"]["threshold"]["unit"] == "pt"
    assert hig["guideline"]["limits"].startswith("The render extract holds each element's box")
    assert by_id["G:wcag-2.2/focus-visible"]["guideline"]["rules"] == ["code.focus-outline-removed"]
    assert len(rows) == 2 + 19 + 20


def test_a_report_that_leaves_a_guideline_row_unjudged_does_not_hold_and_one_that_judges_it_does(project):
    name(project, entry("apple-hig", ["ios"]), entry("wcag-2.2", ["web"]))
    judged(project)
    assert problems(project) == []
    edit(project, lambda d: d["requirements"].pop(-1))
    assert "`requirements` has no entry for G:wcag-2.2/status-messages" in problems(project)
    edit(project, lambda d: d["requirements"].append({"id": "G:wcag-2.2/status-messages", "state": "not-observable", "refs": [],
                                                      "note": "no capture of a status message"}))
    assert problems(project) == []
    edit(project, lambda d: d["requirements"].append({"id": "G:wcag-2.2/not-an-item", "state": "met", "refs": []}))
    assert "which the packet does not list" in " ".join(problems(project))


def test_the_critic_is_not_done_until_every_guideline_row_is_judged(project):
    name(project, entry("wcag-2.2", ["web"]))
    judged(project)
    report = json.loads((project / REPORT).read_text())
    assert requirements.uncovered(project, TASK, report) == []
    report["requirements"] = [r for r in report["requirements"] if r["id"] != "G:wcag-2.2/reflow"]
    assert requirements.uncovered(project, TASK, report) == ["G:wcag-2.2/reflow"]
    report["requirements"] = [r for r in report["requirements"] if not r["id"].startswith("G:")]
    assert len(requirements.uncovered(project, TASK, report)) == 20


def test_a_changed_guideline_or_a_changed_checklist_makes_the_report_stale(project):
    name(project, entry("wcag-2.2", ["web"]))
    judged(project)
    assert problems(project) == []
    name(project, entry("wcag-2.2", ["web"]), entry("apple-hig", ["ios"]))
    assert any("another packet" in p for p in problems(project))


def test_a_packet_without_guidelines_is_what_it_was(project):
    name(project)
    base = packet(project)
    assert not any(r["id"].startswith("G:") for r in base["requirements"]["rows"])
    assert "guideline_rows" not in doc(project)
    name(project, entry("wcag-2.2", ["web"]))
    name(project)                                          # named and then taken away again
    assert packet(project)["requirements"] == base["requirements"]


def test_the_packet_command_counts_them_apart(project, capsys):
    name(project, entry("wcag-2.2", ["web"]))
    capsys.readouterr()
    assert cli_main(["critic", "packet", "--task", TASK, "--root", str(project)]) == 0
    assert "2 requirement rows and 20 guideline rows, 0 changes" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["G:wcag-2.2/", "G:/reflow", "g:wcag-2.2/reflow", "G:wcag-2.2/Reflow"])
def test_a_report_cannot_judge_an_id_that_is_no_row_id(project, bad):
    from lapis_design import shared_dir
    from jsonschema import Draft202012Validator

    schema = yaml.safe_load((shared_dir() / "slop" / "finding.schema.yaml").read_text(encoding="utf-8"))
    row = schema["properties"]["requirements"]["items"]["properties"]["id"]
    assert list(Draft202012Validator(row).iter_errors(bad))
    assert not list(Draft202012Validator(row).iter_errors("G:wcag-2.2/reflow"))
