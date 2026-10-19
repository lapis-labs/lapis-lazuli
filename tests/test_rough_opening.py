"""What a rough's opening is (`rough_opening.py`): `diverge check` runs the opening-composition rules on each rough's own
render, `diverge contract` refuses a brief whose opening carries all four of identity, claim, decisive-object, and
primary-action, and only the brief lifts either, by quoting the owner's `[declared]` line. Roughs, cards, and renders are the
files an agent and `render check` leave (`diverge_support.py`); the CLI reads them as it reads real ones."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from diverge_support import FACES, inventory, write_brief, write_rough
from lapis_design import diverge, owner_text, rough_opening
from procedure_support import (BRIEF_RECORD, DEFAULTS_ACCEPTED, DIRECTION_PROPOSAL, TASK, load_skills, record, save,
                               seal_requirements, write_references)

JOB = "say who the kiln is, show the one decisive object, and offer the booking"
SPLIT = "layout.split-hero"
FIRST_VIEW_ASK = "the first view is a two-column opening, the headline left and the kiln photo right"
BUILD_ORDER = "build the library window first, then the homepage"


@pytest.fixture(autouse=True)
def attended(monkeypatch, tmp_path_factory):
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", str(inventory(tmp_path_factory.mktemp("inventory") / "lazuli.db", *FACES.values())))


def conversation(root: Path, words: str = "") -> None:
    """The brief record with `words` as owner answers before the direction turn, and the first turn's defaults accepted."""
    record(root, "answers", BRIEF_RECORD + words + DEFAULTS_ACCEPTED, 50)


@pytest.fixture
def run(tmp_path) -> Path:
    """A create run with its references and the first turn answered with the defaults, no rough drawn yet."""
    record(tmp_path, "answers", BRIEF_RECORD, 50)
    seal_requirements(tmp_path)
    load_skills(tmp_path)
    write_references(tmp_path)
    shutil.rmtree(tmp_path / ".lapis/state/diverge")
    shutil.rmtree(tmp_path / ".lapis/diverge")
    save(tmp_path, f"direction/{TASK}.yaml", DIRECTION_PROPOSAL)
    conversation(tmp_path)
    diverge.start(tmp_path, TASK, 2, entropy="e1")
    return tmp_path


def opening(**extra) -> dict:
    return {"job": JOB, "carries": ["identity", "decisive-object", "primary-action"], **extra}


def make(root: Path, first: str | None, second: str | None) -> None:
    """The two roughs of the set, each opening as the layout given (`split`, `stacked`, or the fixture's plain boxes)."""
    for candidate, layout in (("C1", first), ("C2", second)):
        write_rough(root, TASK, candidate, opening=layout)


def problems(root: Path) -> str:
    return " | ".join(diverge.check(root, TASK)["problems"])


def contract(root: Path) -> str:
    return " | ".join(diverge.contract(root, TASK)["problems"])


# ---- the set

def test_two_roughs_that_open_as_a_split_hero_are_refused_naming_the_rule_and_the_roughs(run):
    make(run, "split", "split")
    found = problems(run)
    assert "every rough (C1, C2) opens as a split hero" in found and "(layout.split-hero;" in found
    assert not (run / f".lapis/state/diverge/{TASK}/distances.json").exists()
    assert "opening.keeps" in found and "asks for a two-column opening" in found          # what lifts it, named
    with pytest.raises(diverge.DivergeError, match="cannot be sealed: every rough \\(C1, C2\\) opens as a split hero"):
        diverge.seal(run, TASK)


def test_one_split_and_one_that_is_not_passes_and_the_owner_block_and_the_pick_question_say_which(run):
    make(run, "split", "stacked")
    assert problems(run) == ""
    diverge.seal(run, TASK)
    block = diverge.owner_lines(run, TASK)
    assert "- Rough C1 opens as a split hero, the heading and the action on one side and an image or a window on the other" in block
    assert not [line for line in block if line.startswith("- Rough C2 opens")]
    asked = diverge.summary_lines(run, TASK, "en")
    assert [line for line in asked if line.startswith("- Rough C1 opens as a split hero")] and not [
        line for line in asked if "Rough C2 opens" in line]
    assert any(line.startswith("- 러프 C1: 분할 히어로로 열려요") for line in diverge.summary_lines(run, TASK, "ko"))


def test_a_rough_that_trips_no_opening_rule_gets_no_line_and_the_fixture_renders_pass(run):
    make(run, None, None)                                    # the boxes of the other tests: nothing here is a hero
    assert problems(run) == "" and rough_opening.opens(run, TASK, "C1") == {}
    diverge.seal(run, TASK)
    assert not [line for line in diverge.owner_lines(run, TASK) if " opens " in line]


def test_a_declared_two_column_opening_lifts_the_refusal_through_the_brief_and_nothing_else_does(run):
    make(run, "split", "split")
    assert "every rough (C1, C2) opens as a split hero" in problems(run)
    conversation(run, f"- [declared] Q9 What is the first view? - {FIRST_VIEW_ASK}\n")
    write_brief(run, TASK, opening=opening(keeps=[{"rule": SPLIT, "by": FIRST_VIEW_ASK}]))
    assert diverge.contract(run, TASK)["problems"] == []
    for candidate in ("C1", "C2"):                           # the cards name the brief they were made from
        card = yaml.safe_load((diverge.folder(run, TASK) / candidate / "card.yaml").read_text(encoding="utf-8"))
        card["brief_sha256"] = diverge.brief_digest(run, TASK)
        (diverge.folder(run, TASK) / candidate / "card.yaml").write_text(yaml.safe_dump(card, sort_keys=False), encoding="utf-8")
    assert problems(run) == ""
    diverge.seal(run, TASK)
    assert not [line for line in diverge.owner_lines(run, TASK) if " opens " in line]    # the owner asked for it: no flag


def test_a_keeps_quote_has_to_be_a_declared_line_about_the_opening_that_asks_for_what_the_rule_flags(run):
    conversation(run, f"- [declared] Q9 First view? - {FIRST_VIEW_ASK}\n- [declared] Q8 Work order? - {BUILD_ORDER}\n"
                      "- [declared] Q7 Opening? - a quiet opening, one calm line\n"
                      "- [assumed] Q6 First view? - two columns, an assumed layout on a wide first screen\n")
    cases = [(FIRST_VIEW_ASK[:30] + " and more", "is in no `[declared]` line"),
             (BUILD_ORDER, "does not speak of the opening"),
             ("a quiet opening, one calm line", "asks for none of what the rule flags"),
             ("two columns, an assumed layout", "is in no `[declared]` line")]
    for quote, why in cases:
        write_brief(run, TASK, opening=opening(keeps=[{"rule": SPLIT, "by": quote}]))
        assert f"opening.keeps {SPLIT} quotes" in contract(run) and why in contract(run), (quote, contract(run))
    write_brief(run, TASK, opening=opening(keeps=[{"rule": SPLIT, "by": FIRST_VIEW_ASK}]))
    assert contract(run) == ""
    write_brief(run, TASK, opening=opening(keeps=[{"rule": "layout.nested-cards", "by": FIRST_VIEW_ASK}]))
    assert "diverge/brief.schema.yaml" in contract(run)                                   # only the opening rules can be kept


def test_a_kept_rule_has_to_be_the_rule_the_owner_line_asks_for(run):
    make(run, "split", "split")
    conversation(run, f"- [declared] Q9 First view? - {FIRST_VIEW_ASK}\n")
    write_brief(run, TASK, opening=opening(keeps=[{"rule": "component.fake-app-window", "by": FIRST_VIEW_ASK}]))
    assert "asks for none of what the rule flags" in contract(run)                        # a two-column ask is no window ask
    write_brief(run, TASK, opening=opening(keeps=[{"rule": SPLIT, "by": FIRST_VIEW_ASK}]))
    assert contract(run) == ""
    assert rough_opening.lifted(run, TASK) == {SPLIT}


# ---- the brief

def test_a_brief_whose_opening_carries_all_four_is_refused_at_the_contract_unless_the_owner_asked_for_it(run):
    four = ["identity", "claim", "decisive-object", "primary-action"]
    write_brief(run, TASK, opening=opening(carries=four))
    found = contract(run)
    assert "the opening carries identity, claim, decisive-object, and primary-action" in found
    assert "The first view's job is three things" in found and "opening.carries_by" in found
    assert not diverge.contract_passed(run, TASK)
    write_brief(run, TASK, opening=opening(carries=["identity", "claim", "primary-action"]))
    assert contract(run) == ""                                                             # three of the four are fine


def test_an_answer_about_the_order_of_work_is_no_owner_line_that_asks_for_all_four(run):
    four = ["identity", "claim", "decisive-object", "primary-action"]
    conversation(run, f"- [declared] Q2 Build order? - {BUILD_ORDER}\n"
                      "- [declared] Q3 The opening? - the first view holds the headline, the claim, the kiln, and the booking button\n")
    write_brief(run, TASK, opening=opening(carries=four, carries_by=BUILD_ORDER))
    assert "opening.carries_by quotes" in contract(run) and "does not speak of the opening" in contract(run)
    write_brief(run, TASK, opening=opening(carries=four, carries_by="a quote that is nowhere in the record"))
    assert "is in no `[declared]` line" in contract(run)
    write_brief(run, TASK, opening=opening(carries=four, carries_by="the first view holds the headline, the claim, the kiln"))
    assert contract(run) == "" and diverge.contract_passed(run, TASK)


# ---- migration and the shipped lists

def test_a_set_sealed_before_the_opening_checks_comes_back_to_be_checked_again(run):
    make(run, "stacked", None)
    diverge.seal(run, TASK)
    assert diverge.owed(run, TASK) is None
    seal = diverge.state_dir(run, TASK) / "seal.json"
    old = {k: v for k, v in json.loads(seal.read_text(encoding="utf-8")).items() if k != "contract"}
    seal.write_text(json.dumps(old), encoding="utf-8")
    receipt = diverge.contract_path(run, TASK)                                   # the contract was checked before, as version 2
    receipt.write_text(json.dumps({**json.loads(receipt.read_text(encoding="utf-8")), "version": 2}), encoding="utf-8")
    assert "were sealed before the opening checks" in diverge.owed(run, TASK)
    assert diverge.step(run, TASK, "")["command"] == f"lapis-design diverge contract --task {TASK}"
    assert diverge.contract(run, TASK)["problems"] == [] and problems(run) == ""
    diverge.seal(run, TASK)
    assert diverge.owed(run, TASK) is None


def test_the_opening_rules_the_pools_name_are_rules_the_brief_schema_and_both_owner_catalogs_know():
    named = diverge.pools()["rough_opening"]
    schema = diverge.shared_yaml("diverge/brief.schema.yaml")
    kept = schema["properties"]["opening"]["properties"]["keeps"]["items"]["properties"]["rule"]["enum"]
    assert list(named["rules"]) == kept and set(named["asks"]) == set(kept)
    slop = {r["id"]: r for r in diverge.shared_yaml("slop/rules.yaml")["rules"]}
    assert all(rule in slop and "render" in slop[rule]["detect"] for rule in kept)
    for lang in ("en", "ko"):
        assert all(owner_text.say(lang, f"rough.opens.{rule}") for rule in kept)
