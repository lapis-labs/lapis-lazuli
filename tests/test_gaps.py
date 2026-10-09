"""The gap list: which decisions the owner did not make, how the owner block shows them, and what the seal and the
approval of a redesign need before they count (`gaps.py`)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from lapis_design import draft, gaps, integrity, next_step, owner, waiting
from lapis_design.plan_check import run as plan_check_run
from procedure_support import (BRIEF_RECORD, SHARED, TASK, DEFAULTS_ACCEPTED, ask, clear_direction, make_project, record, reply, row_id, save,
                               unseal_slice, update, write_requirements)

DECIDED = '\n## Direction 1\n\n- [declared] O1 the firing log: a — "the ruled rows"\n'
URL = "http://127.0.0.1:4173/slice.html"


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    """A finished procedure with a plan that has type roles, no slice sealed, and no fonts lock."""
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    update(root, f"plans/{TASK}.yaml", lambda plan: plan["tokens"]["type"].update(roles=[
        {"role": "heading", "family": "Gowun Batang", "scripts": ["hang", "latn"], "source": "catalog"},
        {"role": "body", "family": "Pretendard", "scripts": ["hang", "latn"], "source": "inventory"}]))
    unseal_slice(root)
    (root / ".lapis/fonts.lock.json").unlink()
    return root


@pytest.fixture
def stated(project) -> Path:
    """`project` with no direction conversation: the cases state it themselves (`propose`, `direction`)."""
    clear_direction(project)
    return project


def ids(root: Path) -> list[str]:
    return [g["id"] for g in gaps.compute(root, TASK)]


def text_of(root: Path, gap: str) -> str:
    return next(g["text"] for g in gaps.compute(root, TASK) if g["id"] == gap)


def declare(root: Path, *lines: str, at: int = 60) -> None:
    """The brief record with `[declared]` items under a heading of their own."""
    record(root, "answers", f"{BRIEF_RECORD}\n## Replies\n\n" + "".join(f"- [declared] {line}\n" for line in lines), at)


PROPOSAL = {
    "version": 0, "task": TASK,
    "styles": [{"id": "S1", "name": "neo-brutalism", "rows": [], "default": "a",
                "options": [{"id": "a", "text": "expose the record: every plan is a bordered block", "source": "own"},
                            {"id": "b", "text": "collision of words and image", "source": "own"}],
                "kit": [{"id": "K1", "item": "ruled index rows", "seen_in": ["ref-1"], "default": "keep",
                         "why": "the skill lists are indexes"},
                        {"id": "K2", "item": "ticker band", "seen_in": ["ref-2"], "default": "drop", "why": "it moves"}]}],
    "objects": [{"id": "O1", "object": "the firing log", "kind": "record-document", "default": "all",
                 "options": [{"id": "a", "text": "a ruled sheet", "does": "read one row", "family": "ledger", "source": "own"},
                             {"id": "b", "text": "an annotated diff", "does": "compare", "family": "annotated-diff",
                              "source": "own"}]}],
    "signature": [{"id": "G1", "element": "firing log row", "default": "a",
                   "options": [{"id": "a", "text": "which piece and when"}]}],
}


def propose(root: Path) -> None:
    save(root, f"direction/{TASK}.yaml", PROPOSAL)


def direction(root: Path, *lines: str, at: int = 60) -> None:
    record(root, "answers", f"{BRIEF_RECORD}\n## Direction 1\n\n" + "".join(f"{line}\n" for line in lines), at)


# ---- 1. the areas, with and without answers

def test_color_layout_motion_and_type_are_gaps_with_what_the_plan_filled_in(stated):
    assert ids(stated) == ["signature", "color", "layout", "motion", "type:heading", "type:body", "copy:ko"]
    assert text_of(stated, "color") == ("color: field oklch(.97 .01 85) — canvas of every section outside the photographs, "
                                         "about 80% of the first view")
    assert text_of(stated, "layout") == "layout: list-detail; sections firing-log, works"
    assert text_of(stated, "motion").startswith("motion: dial 2 of 10")
    assert text_of(stated, "type:heading") == "type: heading (hang, latn) Gowun Batang"


def test_a_declared_item_for_an_area_decides_it(stated):
    declare(stated, "Color: the page stays white, the kiln blue only on the reserve button",
            "layout: a ruled sheet, no cards", "motion: nothing moves until I press", "signature: the firing log row",
            "type heading: Gowun Batang, as the firing sheets")
    assert ids(stated) == ["type:body", "copy:ko"]
    declare(stated, "Color: the page stays white", "layout: a ruled sheet", "motion: nothing moves", "signature: the row",
            "type heading: Gowun Batang", "type body: Pretendard", "copy ko headline: say the month and the count")
    assert ids(stated) == []


def test_a_gap_of_one_type_role_is_not_decided_by_another_role_or_by_an_item_that_names_none(stated):
    declare(stated, "type heading: Gowun Batang", "type: something serif")
    assert ids(stated) == ["signature", "color", "layout", "motion", "type:body", "copy:ko"]


def test_no_plan_and_a_plan_with_everything_decided_have_no_gaps(stated, tmp_path_factory):
    assert gaps.compute(tmp_path_factory.mktemp("bare"), TASK) == []
    declare(stated, "signature: x row", "color: white", "layout: ruled", "motion: still", "type heading: Gowun",
            "type body: Pretendard", "copy ko headline: the month")
    assert gaps.compute(stated, TASK) == []


def test_the_direction_areas_are_gaps_until_the_owner_decides_each_item(stated):
    propose(stated)
    assert ids(stated)[:5] == ["style:S1", "style:K1", "style:K2", "objects:O1", "signature"]
    assert text_of(stated, "style:K2") == "style: K2 ticker band → drop (default)"
    assert text_of(stated, "style:S1").endswith("→ a \"expose the record: every plan is a bordered block\" (default)")
    direction(stated, '- [declared] S1 neo-brutalism: b — "collision"', '- [declared] K1 ruled index rows: keep — "yes"',
              '- [declared] K2 ticker band: drop — "no"', '- [declared] G1 firing log row: a — "yes"',
              '- [declared] O1 the firing log: a — "the ruled sheet"')
    assert ids(stated)[:2] == ["color", "layout"] and "signature" not in ids(stated)


def test_an_assumed_answer_does_not_decide_and_defaults_accepted_stays_a_gap_marked_so(stated):
    propose(stated)
    direction(stated, '- [assumed] K1 ruled index rows: keep — Basis: nobody was there to ask.',
              '- Defaults accepted (direction 1): "fine, take yours"')
    assert text_of(stated, "style:K1").endswith("(defaults accepted)")
    assert "objects:O1" in ids(stated)


def test_a_narrowed_object_is_decided_by_the_owners_pick_and_shows_the_picked_representation(stated):
    propose(stated)
    save(stated, f"diverge/{TASK}/C2/card.yaml", {"version": 0, "id": "C2", "objects": [
        {"id": "O1", "option": "b", "family": "annotated-diff", "representation": "the plan file as a ruled sheet the cursor annotates"}]})
    direction(stated, '- [declared] O1 the firing log: a,b — "either"')
    assert text_of(stated, "objects:O1").endswith("→ default all")
    direction(stated, '- [declared] O1 the firing log: a,b — "either"', '- [declared] Pick: C2 — "the second"')
    assert "objects:O1" not in ids(stated)


def test_the_signature_is_a_gap_while_no_item_named_it_and_a_declared_signature_decides_it(stated):
    assert text_of(stated, "signature") == ('signature: layout.signature "firing log row"; lever "rhythm: the firing log '
                                             'sheet\'s ruled rows set the page grid, one row per piece"')
    declare(stated, "signature: the firing log row, and nothing else")
    assert "signature" not in ids(stated)


# ---- 2. fixed by the brief

def fixed(root: Path, decision: str, reason: str) -> None:
    update(root, f"plans/{TASK}.yaml", lambda plan: plan["explorations"].append(
        {"decision": decision, "fixed_by": "brief", "reason": reason}))


def test_a_fixed_by_brief_counts_only_with_a_live_row_id(stated):
    write_requirements(stated, ("The layout is a ruled sheet and nothing else",))
    live = row_id("The layout is a ruled sheet and nothing else")
    assert "layout" in ids(stated)
    fixed(stated, "layout", f"The brief fixes the layout: {live} says a ruled sheet, no cards")
    assert "layout" not in ids(stated)
    update(stated, f"plans/{TASK}.yaml", lambda plan: plan["explorations"].pop())
    fixed(stated, "layout", "The brief fixes the layout as a ruled sheet and nothing else")
    assert text_of(stated, "layout").endswith("(plan says fixed by the brief; no row quoted)")
    update(stated, f"plans/{TASK}.yaml", lambda plan: plan["explorations"].pop())
    fixed(stated, "layout", "The brief fixes it: Rabcdef says a ruled sheet")
    assert text_of(stated, "layout").endswith("(plan says fixed by the brief; no row quoted)")


def test_a_fixed_by_brief_with_a_live_id_decides_the_type_roles_it_covers_and_the_palette(stated):
    write_requirements(stated, ("Headings and body are Gowun Batang", "The palette is the log sheet's warm paper"))
    heading, palette = row_id("Headings and body are Gowun Batang"), row_id("The palette is the log sheet's warm paper")
    update(stated, f"plans/{TASK}.yaml", lambda plan: plan["explorations"].append(
        {"decision": "type", "covers": ["heading"], "fixed_by": "brief", "reason": f"{heading} names the face"}))
    fixed(stated, "palette", f"{palette} names the paper")
    assert ids(stated) == ["signature", "layout", "motion", "type:body", "copy:ko"]


# ---- 3. the section

def test_the_block_lists_the_gaps_in_its_own_section_deterministically(project):
    first, sha = owner.block(project, TASK)
    second, again = owner.block(project, TASK)
    assert (first, sha) == (second, again)
    head = "## Decisions you have not made\nThe agent filled these in. Approval needs your word on them"
    assert head in first
    section = first.split(head)[1].split("\n\n")[0]
    assert "- color: field oklch(.97 .01 85)" in section and "- type: body (hang, latn) Pretendard" in section
    assert first.index("## Your decisions") < first.index("## Decisions you have not made") < first.index("## Facts shown")


def test_the_section_shows_at_most_fifteen_lines_and_says_how_many_more(project):
    propose(project)
    update(project, f"direction/{TASK}.yaml", lambda doc: doc["styles"][0]["kit"].extend(
        {"id": f"K{n}", "item": f"item {n}", "seen_in": ["ref-1"], "default": "keep", "why": "x"} for n in range(3, 20)))
    text, _ = owner.block(project, TASK)
    section = text.split("## Decisions you have not made")[1].split("\n\n")[0]
    total = len(gaps.compute(project, TASK))
    assert total > 15 and section.count("\n- ") == 16 and f"- and {total - 15} more" in section


def test_an_unattended_block_at_done_says_the_decisions_were_made_without_the_owner(project, monkeypatch):
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    text, _ = owner.block(project, TASK, {"verdict": "the release gate's report has 0 blocking findings"})
    assert "## Decisions made without you\nThe run made these for you; nobody was there to ask.\n- objects:" in text
    assert "Decisions you have not made" not in text


def test_the_block_recorded_the_gaps_it_listed_under_its_digest(project):
    _, sha = owner.write(project, TASK)
    declare(project, "color: white")                                       # decided after the block was shown
    assert gaps.state_path(project, TASK).is_file()
    assert [g["id"] for g in gaps.unacknowledged(project, TASK, sha)] == ["objects:O1", "signature", "layout", "motion",
                                                                          "type:heading", "type:body", "copy:ko"]


# ---- 4. the seal

@pytest.fixture
def checked(monkeypatch):
    monkeypatch.setattr(draft, "check", lambda root, task, *, asked=None: ([], []))


def shown(root: Path) -> None:
    save(root, "critic/shown-0.json", {"version": 0, "tool": {"name": "critic", "version": "0.1.0"},
                                         "target": {"packet": {"path": ".lapis/critic/packet.json", "sha256": "1" * 64}},
                                         "findings": []})
    save(root, f"drafts/{TASK}.yaml", {"version": 0, "task": TASK, "pages": [
        {"url": URL, "render_task": "shown", "sources": ["index.html"], "direction": "new", "area": "first view",
         "widths": [390, 1440], "behavior_changed": False,
         "review": {"extracts": [], "critic": {"report": ".lapis/critic/shown-0.json"}}}]})
    update(root, f"plans/{TASK}.yaml", lambda plan: plan.update(approval={"state": "approved"}))


def asked_and_answered(root: Path, *answers: str, decided: bool = False) -> str:
    """The slice shown and asked, then answered; `decided` has the owner decide the one object in the direction section
    (the fixture's conversation took the defaults, which leaves it a gap)."""
    shown(root)
    ask(root, f"Approve this slice? {URL}", 200)
    carried = waiting.carried((root / f".lapis/questions/{TASK}.md").read_text(encoding="utf-8"))
    reply(root, "".join(f"- {line}\n" for line in answers), 210)
    if decided:
        file = root / f".lapis/answers/{TASK}.md"
        file.write_text(file.read_text(encoding="utf-8").replace(DEFAULTS_ACCEPTED, DECIDED), encoding="utf-8")
        os.utime(file, (210, 210))
    return carried


def sealed(root: Path) -> dict | None:
    return (integrity.read_state(root, TASK) or {}).get("slice")


def test_the_slice_is_not_sealed_without_the_acknowledgment_and_the_step_says_what_to_record(project, checked):
    carried = asked_and_answered(project, "[declared] The first view is right; keep it quiet.")
    result = next_step.evaluate(project, TASK)
    why = result["step"]["why"]
    assert result["step"]["id"] == "slice" and sealed(project) is None
    assert "lists 8 decisions the owner did not make" in why and "color: field oklch(.97 .01 85)" in why
    assert f"`- Gaps seen (lapis-owner-block {carried}): <their words>`" in why and "not approved while they are unacknowledged" in why


def test_a_gaps_seen_line_with_the_wrong_digest_does_not_acknowledge_and_the_right_one_does(project, checked):
    carried = asked_and_answered(project, '[declared] The first view is right.',
                                 "Gaps seen (lapis-owner-block 00000000): \"yes\"")
    assert next_step.evaluate(project, TASK)["step"]["id"] == "slice" and sealed(project) is None
    reply(project, f"- [declared] The first view is right.\n- Gaps seen (lapis-owner-block {carried}): \"seen, all fine\"\n", 220)
    assert next_step.evaluate(project, TASK)["step"]["id"] == "fonts-lock" and sealed(project)


def test_deciding_each_gap_also_lets_the_slice_seal(project, checked):
    asked_and_answered(project, "[declared] signature: the row",
                       "[declared] color: white stays", "[declared] layout: ruled sheet", "[declared] motion: still",
                       "[declared] type heading: Gowun Batang", "[declared] type body: Pretendard",
                       "[declared] copy ko headline: the month and the count", decided=True)
    assert next_step.evaluate(project, TASK)["step"]["id"] == "fonts-lock" and sealed(project)


def test_a_gap_decided_since_the_block_is_not_asked_again_and_one_still_open_is(project, checked):
    asked_and_answered(project, "[declared] signature: the row",
                       "[declared] color: white stays", "[declared] layout: ruled sheet", "[declared] motion: still",
                       "[declared] type heading: Gowun Batang", "[declared] copy ko headline: the month and the count",
                       decided=True)
    result = next_step.evaluate(project, TASK)
    assert result["step"]["id"] == "slice" and "lists 1 decisions" in result["step"]["why"]
    assert "type: body (hang, latn) Pretendard" in result["step"]["why"]


def test_an_unattended_run_needs_no_acknowledgment_and_has_no_slice(project, monkeypatch):
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    assert next_step.evaluate(project, TASK)["step"]["id"] == "fonts-lock"


# ---- 5. a redesign

def test_a_redesign_plan_approved_after_an_answered_approval_wait_needs_the_acknowledgment(project):
    seal = project / f".lapis/state/{TASK}.json"
    update(project, f"plans/{TASK}.yaml", lambda plan: plan.update(mode="redesign", approval={"state": "approved"}))
    assert next_step.evaluate(project, TASK)["step"]["id"] == "fonts-lock"          # no approval wait on record
    ask(project, "Approve this plan as it reads?", 200)
    carried = waiting.carried((project / f".lapis/questions/{TASK}.md").read_text(encoding="utf-8"))
    reply(project, "- Approved the plan: looks right", 210)
    result = next_step.evaluate(project, TASK)
    assert result["step"]["id"] == "approval-gaps" and seal.is_file()
    assert f"`- Gaps seen (lapis-owner-block {carried}): <their words>`" in result["step"]["why"]
    assert "The plan is not approved while they are unacknowledged" in result["step"]["why"]
    reply(project, f"- Approved the plan: looks right\n- Gaps seen (lapis-owner-block {carried}): \"seen\"\n", 220)
    assert next_step.evaluate(project, TASK)["step"]["id"] == "fonts-lock"


def test_an_unattended_redesign_needs_no_acknowledgment(project, monkeypatch):
    update(project, f"plans/{TASK}.yaml", lambda plan: plan.update(mode="redesign", approval={"state": "approved"}))
    ask(project, "Approve this plan as it reads?", 200)
    reply(project, "- Approved the plan: looks right", 210)
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    assert next_step.evaluate(project, TASK)["step"]["id"] == "fonts-lock"


# ---- 6. the color area

def plan_findings(root: Path) -> list[dict]:
    plan = yaml.safe_load((root / f".lapis/plans/{TASK}.yaml").read_text(encoding="utf-8"))
    report = plan_check_run(None, None, None, SHARED / "plan/schema.yaml", root, plan=plan, plan_label="plan.yaml")
    return [f for f in report["findings"] if f["rule_id"] == "plan.color-area-missing"]


def test_a_create_plan_whose_field_or_identity_color_has_no_area_is_blocked(project):
    assert plan_findings(project) == []
    update(project, f"plans/{TASK}.yaml", lambda plan: (
        plan["tokens"]["color"]["roles"][0].pop("area"),
        plan["tokens"]["color"]["roles"].append({"name": "stone", "role": "identity", "oklch": [0.45, 0.2, 265]})))
    found = plan_findings(project)
    assert [(f["blocking"], f["location"]["path"]) for f in found] == [(True, "tokens.color.roles[0]"),
                                                                     (True, "tokens.color.roles[3]")]
    assert "the field color 'paper' has no `area`" in found[0]["observed"]
    assert next_step.evaluate(project, TASK)["step"]["id"] == "plan-fix"


def test_the_color_area_is_not_asked_of_other_roles_or_of_a_repair(project):
    update(project, f"plans/{TASK}.yaml", lambda plan: plan["tokens"]["color"]["roles"][1].pop("area", None))
    assert plan_findings(project) == []
    update(project, f"plans/{TASK}.yaml", lambda plan: (plan["tokens"]["color"]["roles"][0].pop("area"),
                                                         plan.update(mode="repair")))
    assert plan_findings(project) == []


def test_the_area_must_say_something(project):
    update(project, f"plans/{TASK}.yaml", lambda plan: plan["tokens"]["color"]["roles"][0].update(area="whole"))
    report = plan_check_run(None, None, None, SHARED / "plan/schema.yaml", project,
                            plan=yaml.safe_load((project / f".lapis/plans/{TASK}.yaml").read_text(encoding="utf-8")),
                            plan_label="plan.yaml")
    assert any(f["rule_id"] == "schema.invalid" for f in report["findings"])
