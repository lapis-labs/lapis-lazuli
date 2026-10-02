"""layout.unanchored-lever: a form lever that shares no word with the plan's world materials or
signature blocks the plan in create mode (plan-anchored-text), and the plan summary shows the concept
and levers the user is asked to approve."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from lapis_design import plan_check
from lapis_design.lint.detectors import load
from lapis_design.lint.types import DETECTORS, Context

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "src" / "shared"
SCHEMA = SHARED / "plan/schema.yaml"
LOCK = SHARED / "fonts/example.fonts.lock.json"
RULES = yaml.safe_load((SHARED / "slop/rules.yaml").read_text(encoding="utf-8"))
RULE = next(r for r in RULES["rules"] if r["id"] == "layout.unanchored-lever")
RULE_ID = "layout.unanchored-lever"

# The materials of the two prototype subjects: a backup service and a clinic (kit outline, section 3).
MATERIALS_EN = ["restore log", "snapshot timeline", "retention schedule", "file version list", "checksum"]
MATERIALS_KO = ["접수표", "진료 시간표", "대기 순번", "처방전"]
PERSUADE = {"surface_mode": ["persuade"], "style_frame": "subject-derived"}

# (sentence that hits, sentence that passes, materials)
OUTLINE_SENTENCES = [
    ("clean", "rhythm: one row per backup day, taken from the snapshot timeline", MATERIALS_EN),
    ("modern and professional",
     "density: the file version list keeps ledger density while the opening stays sparse", MATERIALS_EN),
    ("bold typography", "motif: the checksum's fixed-width blocks recur as the divider between sections",
     MATERIALS_EN),
    ("scale contrast",
     "type as form: restore-log timestamps in tabular figures are the largest thing in the opening",
     MATERIALS_EN),
    ("깔끔하고 신뢰감 있는 화면", "리듬: 진료 시간표의 요일과 시간 칸을 날짜 선택 격자로 그대로 쓴다", MATERIALS_KO),
    ("여백을 넉넉하게", "스케일: 대기 순번 숫자를 화면에서 가장 크게 둔다", MATERIALS_KO),
    ("모던한 카드 레이아웃", "밀도: 처방전의 약 이름과 용량은 표 밀도로, 주의 문구는 넓게 둔다", MATERIALS_KO),
]


def lever_plan(levers, materials=MATERIALS_EN, *, mode="create", read=PERSUADE, signature=None):
    plan = {"version": 0, "mode": mode, "task": {"id": "demo", "title": "Demo"},
            "world_materials": list(materials), "direction": {"read": dict(read), "levers": list(levers)}}
    if signature:
        plan["layout"] = {"signature": signature}
    return plan


def anchored(plan):
    load("plan")
    ctx = Context(rules=RULES, plan=plan, plan_path="plan.yaml")
    return DETECTORS["plan-anchored-text"].fn(ctx, RULE["detect"]["plan"], RULE, "plan")


@pytest.mark.parametrize("row", OUTLINE_SENTENCES, ids=[row[0] for row in OUTLINE_SENTENCES])
def test_adjective_levers_name_no_material(row):
    adjective, _, materials = row
    result = anchored(lever_plan([adjective], materials))
    assert [h.location["path"] for h in result.hits] == ["direction.levers[0]"]


@pytest.mark.parametrize("row", OUTLINE_SENTENCES, ids=[row[1].split(":")[0] for row in OUTLINE_SENTENCES])
def test_levers_that_name_a_material_pass(row):
    _, lever, materials = row
    assert anchored(lever_plan([lever], materials)).hits == []


def test_only_the_unanchored_lever_is_reported_with_its_place():
    plan = lever_plan([OUTLINE_SENTENCES[0][1], OUTLINE_SENTENCES[0][0], OUTLINE_SENTENCES[1][1]])
    assert [h.location["path"] for h in anchored(plan).hits] == ["direction.levers[1]"]


def test_a_word_of_the_signature_anchors_a_lever():
    plan = lever_plan(["scale: the verification badge is the largest mark in the opening"], MATERIALS_EN,
                      signature="verification badge")
    assert anchored(plan).hits == []
    assert len(anchored(lever_plan(["scale: the badge is the largest mark"], MATERIALS_EN)).hits) == 1


def test_function_words_do_not_anchor_a_lever():
    plan = lever_plan(["the one for all and with them"], ["The Archive", "for the record"])
    assert len(anchored(plan).hits) == 1


def test_english_words_match_by_their_first_five_letters():
    assert anchored(lever_plan(["rhythm: scheduling sets the grid"], ["retention schedule"])).hits == []
    assert len(anchored(lever_plan(["rhythm: sche sets the grid"], ["retention schedule"])).hits) == 1


# ---------------------------------------------------------------- scope

@pytest.mark.parametrize("read,hits", [
    ({"surface_mode": ["persuade"], "style_frame": "subject-derived"}, 1),
    ({"surface_mode": ["operate"], "style_frame": "subject-derived"}, 0),
    ({"surface_mode": ["operate", "read"], "style_frame": "subject-derived"}, 1),
    ({"surface_mode": ["persuade", "operate"], "style_frame": "named", "style_name": "clean"}, 1),
])
def test_no_lever_hits_unless_the_surface_is_operate_alone(read, hits):
    assert len(anchored(lever_plan([], read=read)).hits) == hits


def test_blank_levers_count_as_no_lever():
    assert len(anchored(lever_plan(["  "])).hits) == 1
    assert anchored(lever_plan(["  "], read={"surface_mode": ["operate"], "style_frame": "undecided"})).hits == []


@pytest.mark.parametrize("mode", ["redesign", "repair"])
def test_only_create_mode_is_checked(mode):
    assert anchored(lever_plan(["clean"], mode=mode)).hits == []
    assert anchored(lever_plan([], mode=mode)).hits == []


def test_an_inherited_style_frame_is_left_alone():
    read = {"surface_mode": ["persuade"], "style_frame": "inherit"}
    assert anchored(lever_plan(["clean"], read=read)).hits == []
    assert anchored(lever_plan([], read=read)).hits == []


# ---------------------------------------------------------------- the plan gate

def write_plan(tmp_path, plan):
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    return path


def base_plan():
    return yaml.safe_load((SHARED / "plan/example.plan.yaml").read_text(encoding="utf-8"))


def run_real(tmp_path, plan):
    return plan_check.run(write_plan(tmp_path, plan), SHARED / "slop/rules.yaml", LOCK, SCHEMA, tmp_path)


def blocking(report):
    return {f["rule_id"] for f in report["findings"] if f["blocking"]}


def pilot_shaped_plan():
    """What the first internal pilot wrote: two adjectives as materials, a role word as the signature,
    adjective levers, one system font for every role with its keep line, and generic section names."""
    plan = base_plan()
    plan["world_materials"] = ["trust", "modern feel"]
    plan["layout"]["signature"] = "hero section"
    plan["direction"]["levers"] = ["clean spacing", "bold typography", "subtle motion", "card-based layout"]
    plan["tokens"]["type"]["roles"] = [
        {"role": role, "family": "system-ui", "weights": [400, 600], "scripts": ["latn"], "source": "inventory"}
        for role in ("display", "heading", "body", "ui")]
    plan["explorations"] = [e for e in plan["explorations"] if e["decision"] != "type"] + [
        {"decision": "type", "covers": ["display", "heading", "body", "ui"],
         "candidates": [{"name": "system-ui", "source": "generic"}, {"name": "Pretendard", "source": "local"}],
         "compared_on": ["specimen"], "chosen": "system-ui",
         "runner_up_lost": "Pretendard read the same on the phone and needs a file to ship"}]
    plan["layout"]["sections"] = [
        {"id": name, "archetype": name, "answers": "What do I need to know here"}
        for name in ("opening", "features", "plans", "questions", "closing")]
    return plan


def test_pilot_shaped_plan_is_blocked_by_its_adjective_levers(tmp_path):
    report = run_real(tmp_path, pilot_shaped_plan())
    assert blocking(report) == {RULE_ID}
    found = next(f for f in report["findings"] if f["rule_id"] == RULE_ID)
    assert found["observed"].count("shares no word") == 4 and "clean spacing" in found["observed"]
    assert found["location"]["path"] == "direction.levers[*]" and "defaults entry" in found["fix"]


def test_a_lever_that_names_its_material_unblocks_the_pilot_shaped_plan(tmp_path):
    plan = pilot_shaped_plan()
    plan["direction"]["levers"] = ["scale: the modern feel of the opening is one large trust statement"]
    assert RULE_ID not in {f["rule_id"] for f in run_real(tmp_path, plan)["findings"]}


@pytest.mark.parametrize("decision,status", [("keep", "waived"), ("reject", "open")])
def test_a_defaults_entry_for_the_rule_stops_the_block(tmp_path, decision, status):
    plan = pilot_shaped_plan()
    entry = {"keep_when": "form-fixed-by-contract-or-brief"} if decision == "keep" else {}
    plan["defaults"].append({"id": RULE_ID, "decision": decision, "basis": "brief", **entry,
                             "reason": "The contract fixes the form and says so"})
    report = run_real(tmp_path, plan)
    found = next(f for f in report["findings"] if f["rule_id"] == RULE_ID)
    assert found["blocking"] is False and found["status"] == status
    assert RULE_ID not in blocking(report)


def test_a_plan_without_levers_is_blocked_unless_it_is_an_operate_screen(tmp_path):
    plan = pilot_shaped_plan()
    del plan["direction"]["levers"]
    assert RULE_ID in blocking(run_real(tmp_path, plan))
    plan["direction"]["read"]["surface_mode"] = ["operate"]
    assert RULE_ID not in {f["rule_id"] for f in run_real(tmp_path, plan)["findings"]}


@pytest.mark.parametrize("path", [SHARED / "plan/example.plan.yaml",
                                  ROOT / "docs/examples/site-booking-en.yaml",
                                  ROOT / "docs/examples/site-booking-ko.yaml"])
def test_the_shipped_example_plans_pass_the_lever_check(tmp_path, path):
    plan = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert RULE_ID not in {f["rule_id"] for f in run_real(tmp_path, plan)["findings"]}


# ---------------------------------------------------------------- the approval summary

def test_summary_shows_the_concept_and_each_lever():
    plan = copy.deepcopy(base_plan())
    text = plan_check.summarize(plan)
    assert f"- **Concept:** {plan['direction']['concept']}" in text
    for lever in plan["direction"]["levers"]:
        assert f"- **Lever:** {lever}" in text
    assert text.index("**World materials:**") < text.index("**Concept:**") < text.index("**Signature:**")


def test_summary_of_a_plan_without_direction_text_has_no_concept_or_lever_lines():
    plan = base_plan()
    del plan["direction"]["concept"], plan["direction"]["levers"]
    text = plan_check.summarize(plan)
    assert "**Concept:**" not in text and "**Lever:**" not in text
