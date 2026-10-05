"""A create plan records, for each open decision, the candidates it compared (`explorations`): a decision
made without a second candidate, and a type plan whose candidates are all generic families, block
(plan.uncompared-decision); a recorded comparison passes; what the contract or the brief fixes is exempt."""
import copy
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from lapis_design import plan_check

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "src" / "shared"
SCHEMA = SHARED / "plan/schema.yaml"
RULES = SHARED / "slop/rules.yaml"
LOCK = SHARED / "fonts/example.fonts.lock.json"
RULE_ID = "plan.uncompared-decision"
VALIDATOR = Draft202012Validator(yaml.safe_load(SCHEMA.read_text(encoding="utf-8")))


def base_plan():
    return yaml.safe_load((SHARED / "plan/example.plan.yaml").read_text(encoding="utf-8"))


def check(tmp_path, plan):
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    return plan_check.run(path, RULES, LOCK, SCHEMA, tmp_path)


def found(report):
    return [f for f in report["findings"] if f["rule_id"] == RULE_ID]


def entry_of(plan, decision, covers=None):
    return next(e for e in plan["explorations"]
                if e["decision"] == decision and (covers is None or covers in e.get("covers", [])))


def all_generic(plan, candidates):
    """The pilot's type plan: one platform face for every text role, with the given candidates recorded."""
    plan["tokens"]["type"]["roles"] = [{"role": role, "family": "system-ui", "weights": [400, 600],
                                        "scripts": ["latn"], "source": "inventory"}
                                       for role in ("heading", "body", "ui")]
    plan["explorations"] = [e for e in plan["explorations"] if e["decision"] != "type"] + [
        {"decision": "type", "covers": ["heading", "body", "ui"], "candidates": candidates,
         "compared_on": ["specimen"], "chosen": "system-ui",
         "runner_up_lost": "the second candidate set the same copy no better on a phone"}]
    return plan


def test_the_example_plan_records_a_comparison_for_every_open_decision(tmp_path):
    assert found(check(tmp_path, base_plan())) == []


@pytest.mark.parametrize("decision, covers, said", [
    ("type", "heading", "type roles heading"), ("type", "body", "type roles body"), ("palette", None, "palette"),
    ("layout", None, "layout"), ("motion", None, "motion"), ("direction", None, "direction"),
    ("copy", "headline", "copy slots headline"), ("copy", "cta", "copy slots cta")])
def test_an_open_decision_without_an_entry_blocks_and_is_named(tmp_path, decision, covers, said):
    plan = base_plan()
    plan["explorations"].remove(entry_of(plan, decision, covers))
    [finding] = found(check(tmp_path, plan))
    assert finding["blocking"] and finding["status"] == "open"
    assert finding["observed"] == f"1 open decision with no comparison recorded in explorations: {said}"


def test_a_plan_with_no_explorations_blocks_for_every_decision_it_makes(tmp_path):
    plan = base_plan()
    del plan["explorations"]
    [finding] = found(check(tmp_path, plan))
    assert finding["blocking"] and "8 open decisions" in finding["observed"]
    assert "type roles heading, body; palette; layout; motion; direction; copy slots headline, cta" in finding["observed"]


def test_an_all_generic_type_plan_with_no_named_candidate_blocks(tmp_path):
    plan = all_generic(base_plan(), [{"name": "system-ui", "source": "generic"},
                                     {"name": "sans-serif", "source": "generic"}])
    [finding] = found(check(tmp_path, plan))
    assert finding["blocking"]
    assert "every candidate is a generic family" in finding["observed"]


def test_a_generic_family_listed_under_a_named_source_is_still_generic(tmp_path):
    plan = all_generic(base_plan(), [{"name": "system-ui", "source": "local"},
                                     {"name": "-apple-system", "source": "catalog:system-table"}])
    assert "every candidate is a generic family" in found(check(tmp_path, plan))[0]["observed"]


def test_a_generic_family_that_won_against_a_named_face_passes(tmp_path):
    plan = all_generic(base_plan(), [{"name": "system-ui", "source": "generic"},
                                     {"name": "Pretendard", "source": "local"}])
    assert found(check(tmp_path, plan)) == []


@pytest.mark.parametrize("change, said", [
    ({"candidates": [{"name": "Pretendard", "source": "local"}]}, "1 distinct candidate recorded, 2 needed"),
    ({"candidates": [{"name": "Pretendard", "source": "local"}, {"name": "pretendard", "source": "adobe"}]},
     "1 distinct candidate recorded, 2 needed"),
    ({"chosen": "Inter"}, "chosen 'Inter' is not one of the candidates"),
    ({"chosen": None}, "no chosen candidate"),
    ({"compared_on": []}, "compared_on is empty"),
    ({"compared_on": ["sketch"]}, "neither a specimen nor a render"),
    ({"runner_up_lost": None}, "no runner_up_lost"),
])
def test_a_type_entry_that_is_not_a_comparison_blocks_and_says_why(tmp_path, change, said):
    plan = base_plan()
    body = entry_of(plan, "type", "body")
    for key, value in change.items():
        body.pop(key) if value is None else body.__setitem__(key, value)
    [finding] = found(check(tmp_path, plan))
    assert finding["blocking"] and said in finding["observed"]
    assert f"explorations[{plan['explorations'].index(body)}] (type body)" in finding["observed"]


def test_a_palette_may_be_compared_on_a_sketch(tmp_path):
    plan = base_plan()
    entry_of(plan, "palette")["compared_on"] = ["sketch"]
    assert found(check(tmp_path, plan)) == []

def test_an_older_v0_palette_render_claim_parses_but_is_uncompared_without_evidence(tmp_path):
    plan = base_plan()
    entry = entry_of(plan, "palette")
    entry.pop("comparisons")
    for candidate in entry["candidates"]:
        for key in ("artifact", "roles", "token_file"):
            candidate.pop(key, None)
    report = check(tmp_path, plan)
    assert "schema.invalid" not in {f["rule_id"] for f in report["findings"]}
    [finding] = found(report)
    assert finding["blocking"] and finding["status"] == "open"




def rendered_palette(plan):
    entry = entry_of(plan, "palette")
    for index, candidate in enumerate(entry["candidates"]):
        candidate.pop("token_file", None)
        candidate["artifact"] = f".lapis/specimens/palette-{index}.html"
        candidate["roles"] = [{"name": "canvas", "role": "field", "oklch": [0.97, 0.01, 85]}]
    entry["comparisons"] = [{
        "variable": "neutral temperature", "viewport": {"width": 390, "theme": "light"},
        "state": "dense product list with focus",
        "captures": {c["name"]: f".lapis/renders/palette-{i}/390-light.png"
                     for i, c in enumerate(entry["candidates"])},
    }]
    return entry


@pytest.mark.parametrize("missing", ["artifact", "roles", "comparisons", "captures", "viewport", "state", "variable"])
def test_a_claimed_palette_render_without_reproducible_evidence_blocks(tmp_path, missing):
    plan = base_plan()
    entry = rendered_palette(plan)
    if missing in ("artifact", "roles"):
        entry["candidates"][1].pop(missing)
    elif missing == "comparisons":
        entry.pop(missing)
    else:
        entry["comparisons"][0].pop(missing)
    [finding] = found(check(tmp_path, plan))
    assert finding["blocking"] and finding["status"] == "open"


def test_a_palette_render_records_both_candidates_in_the_same_context(tmp_path):
    plan = base_plan()
    entry = rendered_palette(plan)
    entry["candidates"][1].pop("roles")
    entry["candidates"][1]["token_file"] = ".lapis/tokens/palette-b.css"
    report = check(tmp_path, plan)
    assert found(report) == []
    assert "schema.invalid" not in {f["rule_id"] for f in report["findings"]}
    entry["comparisons"][0]["captures"].pop(entry["candidates"][1]["name"])
    [finding] = found(check(tmp_path, plan))
    assert finding["blocking"]


def test_slots_that_are_not_open_decisions_need_no_entry(tmp_path):
    plan = base_plan()
    plan["content"]["key_copy"].append({"slot": "empty-state", "text": "아직 올라온 작품이 없어요", "locale": "ko-KR"})
    assert found(check(tmp_path, plan)) == []


def test_a_decision_the_brief_fixes_is_exempt_when_the_plan_says_so(tmp_path):
    plan = base_plan()
    palette = entry_of(plan, "palette")
    plan["explorations"][plan["explorations"].index(palette)] = {
        "decision": "palette", "fixed_by": "brief", "reason": "The studio's brief names its two glaze colors"}
    report = check(tmp_path, plan)
    assert found(report) == [] and report["summary"]["blocking"] == 0


def test_a_decision_fixed_by_the_contract_holds_only_when_the_plan_reads_one(tmp_path):
    plan = base_plan()
    fixed = {"decision": "type", "covers": ["body"], "fixed_by": "contract",
             "reason": "DESIGN.md names Pretendard for body text"}
    plan["explorations"][plan["explorations"].index(entry_of(plan, "type", "body"))] = fixed
    [finding] = found(check(tmp_path, plan))
    assert finding["blocking"] and "fixed_by is contract, but context.design is null" in finding["observed"]
    (tmp_path / "DESIGN.md").write_text("# Design\n", encoding="utf-8")
    plan["context"]["design"] = {"path": "DESIGN.md", "dialect": "google"}
    report = check(tmp_path, plan)
    assert found(report) == [] and "schema.invalid" not in {f["rule_id"] for f in report["findings"]}


def test_a_role_that_says_source_contract_is_fixed_only_when_the_plan_reads_a_contract(tmp_path):
    plan = base_plan()
    plan["explorations"].remove(entry_of(plan, "type", "body"))
    [role] = [r for r in plan["tokens"]["type"]["roles"] if r["role"] == "body"]
    role["source"] = "contract"
    [finding] = found(check(tmp_path, plan))
    assert "type roles body say source contract, but context.design is null" in finding["observed"]
    (tmp_path / "DESIGN.md").write_text("# Design\n", encoding="utf-8")
    plan["context"]["design"] = {"path": "DESIGN.md", "dialect": "google"}
    report = check(tmp_path, plan)
    assert found(report) == [] and "schema.invalid" not in {f["rule_id"] for f in report["findings"]}


@pytest.mark.parametrize("decision", ["keep", "reject"])
def test_a_defaults_entry_cannot_lift_the_block(tmp_path, decision):
    plan = base_plan()
    del plan["explorations"]
    plan["defaults"].append({"id": RULE_ID, "decision": decision, "basis": "brief", "keep_when": "anything",
                             "reason": "The first answer was fine"})
    [finding] = found(check(tmp_path, plan))
    assert finding["blocking"] and finding["status"] == "open"
    assert "takes no defaults entry" in finding["observed"]


@pytest.mark.parametrize("mode", ["redesign", "repair"])
def test_only_a_create_plan_is_held_to_it(tmp_path, mode):
    plan = base_plan()
    plan["mode"] = mode
    del plan["explorations"]
    assert found(check(tmp_path, plan)) == []


def test_the_schema_reads_each_decision_by_the_vocabulary_it_uses(tmp_path):
    def errors(plan):
        return [e.message for e in VALIDATOR.iter_errors(plan)]

    assert errors(base_plan()) == []
    for source in ("catalog:google-fonts", "commercial:Klim", "adobe", "local", "generic"):
        plan = base_plan()
        entry_of(plan, "type", "body")["candidates"][1]["source"] = source
        assert errors(plan) == [], source
    plan = base_plan()
    entry_of(plan, "type", "body")["candidates"][1]["source"] = "bundled"
    assert errors(plan)
    plan = base_plan()
    entry_of(plan, "palette")["candidates"][1]["source"] = "a client's brand sheet"
    assert errors(plan) == []
    for decision in ("type", "copy"):
        plan = base_plan()
        del entry_of(plan, decision)["covers"]
        assert errors(plan), decision
    plan = base_plan()
    entry_of(plan, "palette")["compared_on"] = ["facts"]
    assert errors(plan)
    plan = base_plan()
    plan["explorations"].append({"decision": "palette", "fixed_by": "brief"})
    assert errors(plan)


def test_the_approval_summary_shows_what_was_compared_and_what_is_fixed(tmp_path):
    plan = base_plan()
    plan["explorations"].append({"decision": "palette", "fixed_by": "brief", "reason": "The studio names its glazes"})
    text = plan_check.summarize(plan)
    assert ("- **Compared (type body):** Pretendard (local), Noto Sans KR (catalog:google-fonts); chose Pretendard; "
            "runner-up lost: Noto Sans KR set the same measure") in text
    assert "- **Fixed (palette):** by the brief — The studio names its glazes" in text
    assert "- **Default type.overused-neutral-grotesque:** keep (won-comparison) —" in text


def test_the_pilot_shaped_type_plan_is_stopped_where_the_pilot_was_not(tmp_path):
    """Every role on system-ui, a keep whose reason is the offline constraint, no candidate recorded."""
    plan = base_plan()
    del plan["explorations"]
    plan["tokens"]["type"]["roles"] = [{"role": role, "family": "system-ui", "source": "contract"}
                                       for role in ("display", "heading", "body", "ui")]
    plan["defaults"] = [{"id": "type.single-neutral-sans", "decision": "keep", "basis": "requirement",
                         "reason": "A system font stack is required for offline delivery without downloaded fonts"},
                        {"id": "type.overused-neutral-grotesque", "decision": "keep", "basis": "requirement",
                         "reason": "Use the browser's system sans face without external assets"}]
    report = check(tmp_path, copy.deepcopy(plan))
    blocked = {f["rule_id"] for f in report["findings"] if f["blocking"]}
    assert blocked >= {RULE_ID, "type.single-neutral-sans", "type.overused-neutral-grotesque"}
