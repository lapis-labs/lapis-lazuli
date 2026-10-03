"""A keep waives a default only when it carries the evidence that its keep_when case lists."""
import copy
from pathlib import Path

import pytest
import yaml

from lapis_design import keep_evidence, plan_check
from lapis_design.keep_evidence import Sources
from lapis_design.lint import cli as lint_cli
from lapis_design.lint import engine
from lapis_design.lint.types import DETECTORS, Context, Hit, Result, detector

SHARED = Path(__file__).resolve().parents[1] / "src" / "shared"
SCHEMA = SHARED / "plan/schema.yaml"
RULES = SHARED / "slop/rules.yaml"
LOCK = SHARED / "fonts/example.fonts.lock.json"


def base_plan():
    return yaml.safe_load((SHARED / "plan/example.plan.yaml").read_text(encoding="utf-8"))


def checked(tmp_path, plan, rule_id, files=None):
    """The plan check's finding for one rule, with `files` written into the project root first."""
    for name, text in (files or {}).items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    report = plan_check.run(path, RULES, LOCK, SCHEMA, tmp_path)
    [found] = [f for f in report["findings"] if f["rule_id"] == rule_id]
    return found


def verdict(found):
    return found["status"], found["blocking"]


# ---------------------------------------------------------------- the brand color the skill-only run invented

RULE = "color.terracotta-accent"
DESIGN = {"path": "DESIGN.md", "dialect": "google"}


def orange_plan(**keep):
    """The skill-only run's plan: an orange it authored itself, kept as `brand-color`, in a project with no brand."""
    plan = base_plan()
    plan["tokens"]["color"]["roles"].append({"name": "action", "role": "interaction", "oklch": [0.52, 0.16, 37],
                                             "source_class": "authored"})
    plan["defaults"].append({"id": RULE, "decision": "keep", "basis": "brief", "keep_when": "brand-color",
                             "reason": "Authored orange identifies the vault mark and the recovery action", **keep})
    return plan


def test_a_brand_color_keep_with_no_design_contract_and_no_brand_in_the_brief_does_not_waive(tmp_path):
    found = checked(tmp_path, orange_plan(), RULE)
    assert verdict(found) == ("open", True)
    assert "keep_when 'brand-color' needs evidence" in found["observed"]
    assert "context.design is null" in found["observed"] and "evidence.brief" in found["observed"]


def test_the_same_keep_waives_when_the_declared_design_contract_names_the_color(tmp_path):
    plan = orange_plan(basis="contract", evidence={"design": "DESIGN.md#colors.action"})
    plan["context"]["design"] = DESIGN
    found = checked(tmp_path, plan, RULE, files={"DESIGN.md": "colors:\n  action: '#d9531e'\n"})
    assert verdict(found) == ("waived", False)


@pytest.mark.parametrize("cited, text", [
    ("DESIGN.md#colors.brand", "colors:\n  action: '#d9531e'\n"),   # the contract has no such token
    ("BRAND.md#colors.action", "colors:\n  action: '#d9531e'\n"),   # a file the plan did not declare
    ("DESIGN.md#colors.action", None),                              # the declared file is not there
], ids=["token not in the file", "other file", "no file"])
def test_a_design_citation_that_the_declared_contract_does_not_back_does_not_waive(tmp_path, cited, text):
    plan = orange_plan(basis="contract", evidence={"design": cited})
    plan["context"]["design"] = DESIGN
    found = checked(tmp_path, plan, RULE, files={"DESIGN.md": text} if text else None)
    assert verdict(found) == ("open", True)
    assert "keep_when 'brand-color' needs evidence" in found["observed"]


def test_a_brief_case_waives_only_for_a_line_the_brief_holds(tmp_path):
    plan = orange_plan(evidence={"brief": "the studio's  BRAND orange is #d9531e"})
    plan["brief"]["constraints"].append("The studio's brand orange is #d9531e, taken from the printed catalog")
    assert verdict(checked(tmp_path, plan, RULE)) == ("waived", False)

    invented = orange_plan(evidence={"brief": "the vault mark uses an authored orange"})
    invented["brief"]["constraints"].append("The studio's brand orange is #d9531e, taken from the printed catalog")
    found = checked(tmp_path, invented, RULE)
    assert verdict(found) == ("open", True) and "evidence.brief is not a line of brief" in found["observed"]


def test_a_keep_whose_case_lists_alternatives_needs_only_one_of_them(tmp_path):
    plan = orange_plan(evidence={"brief": "the studio's brand orange", "design": "DESIGN.md#colors.action"})
    plan["brief"]["constraints"].append("The studio's brand orange is #d9531e")
    assert verdict(checked(tmp_path, plan, RULE)) == ("waived", False)


# ---------------------------------------------------------------- a comparison the kept face has to have won

COMPARISON = "type.overused-neutral-grotesque"


def platform_face_plan(*explorations, **keep):
    """Every text role on the platform's own face, kept as `won-comparison`."""
    plan = base_plan()
    plan["tokens"]["type"]["roles"] = [{"role": role, "family": "system-ui"} for role in ("heading", "body", "ui")]
    plan["explorations"] += list(explorations)
    plan["defaults"] = [d for d in plan["defaults"] if not d["id"].startswith("type.")]
    plan["defaults"].append({"id": COMPARISON, "decision": "keep", "basis": "brief", "keep_when": "won-comparison",
                             "reason": "The platform's own face won the body comparison on the phone", **keep})
    return plan


def type_exploration(chosen, candidates, covers=("body", "ui"), **more):
    return {"decision": "type", "covers": list(covers), "chosen": chosen, "compared_on": ["specimen"],
            "candidates": [{"name": name, "source": "generic" if name == "system-ui" else "local"}
                           for name in candidates],
            "runner_up_lost": "Pretendard needs a file to ship and read the same on the phone", **more}


def test_a_won_comparison_keep_with_no_exploration_that_the_kept_face_won_does_not_waive(tmp_path):
    # the example's explorations chose Gowun Batang and Pretendard; no role uses either
    found = checked(tmp_path, platform_face_plan(evidence={"exploration": "system-ui"}), COMPARISON)
    assert verdict(found) == ("open", True)
    assert "no complete type comparison in explorations was won by a face that a type role uses" in found["observed"]


def test_a_won_comparison_keep_waives_when_an_exploration_chose_the_face_a_role_uses(tmp_path):
    won = type_exploration("system-ui", ["system-ui", "Pretendard"])
    found = checked(tmp_path, platform_face_plan(won, evidence={"exploration": "System-UI"}), COMPARISON)
    assert verdict(found) == ("waived", False)


@pytest.mark.parametrize("exploration", [
    type_exploration("system-ui", ["system-ui"]),
    type_exploration("system-ui", ["system-ui", "Pretendard"], compared_on=["sketch"]),
    type_exploration("Pretendard", ["system-ui", "Pretendard"]),
], ids=["one candidate", "judged on a sketch, not the page's copy", "the kept face lost"])
def test_a_comparison_that_is_incomplete_or_lost_does_not_waive(tmp_path, exploration):
    found = checked(tmp_path, platform_face_plan(exploration, evidence={"exploration": "system-ui"}), COMPARISON)
    assert verdict(found) == ("open", True)
    assert "keep_when 'won-comparison' needs evidence" in found["observed"]


def test_a_keep_that_cites_a_face_it_did_not_win_names_the_ones_that_won(tmp_path):
    won = type_exploration("system-ui", ["system-ui", "Pretendard"])
    found = checked(tmp_path, platform_face_plan(won, evidence={"exploration": "Pretendard"}), COMPARISON)
    assert verdict(found) == ("open", True) and "won: system-ui" in found["observed"]


# ---------------------------------------------------------------- slop lint applies the same evidence

@pytest.fixture
def always_hits():
    detector("test-always-hits", layers=engine.LAYERS)(
        lambda ctx, det, rule, layer: Result(hits=[Hit(observed="seen here")]))
    yield
    DETECTORS.pop("test-always-hits", None)


def lint_real(rule_id, plan, **inputs):
    """The rule as rules.yaml writes it, with a detector that always hits, linted against `plan`."""
    real = copy.deepcopy(next(r for r in yaml.safe_load(RULES.read_text(encoding="utf-8"))["rules"]
                              if r["id"] == rule_id))
    real.update(layers=["render"], detect={"render": {"detector": "test-always-hits"}})
    doc = {"version": 0, "as_of": "2026-09", "packages": {}, "rules": [real]}
    [found] = engine.lint(Context(rules=doc, plan=plan, **inputs), ("render",), None, probes={})
    return found


def test_slop_lint_waives_the_brand_color_only_with_the_contract_or_the_brief_behind_it(always_hits):
    assert lint_real(RULE, orange_plan())["status"] == "open"
    with_design = orange_plan(basis="contract", evidence={"design": "DESIGN.md#colors.action"})
    with_design["context"]["design"] = DESIGN
    assert lint_real(RULE, with_design)["status"] == "open"                      # the file was not read
    waived = lint_real(RULE, with_design, design_text="colors:\n  action: '#d9531e'\n")
    assert (waived["status"], waived["blocking"]) == ("waived", False)


def test_slop_lint_reads_the_declared_design_file_from_the_working_directory(tmp_path, monkeypatch):
    from lazuli import paths

    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "empty-cache")
    monkeypatch.delenv("LAZULI_DB", raising=False)
    monkeypatch.chdir(tmp_path)
    plan = base_plan()
    plan["context"]["design"] = DESIGN
    plan["tokens"]["type"]["scale"]["ratio"] = 1.05
    plan["defaults"].append({"id": "type.flat-hierarchy", "decision": "keep", "basis": "contract",
                             "keep_when": "contract-scale", "evidence": {"design": "DESIGN.md#typography.scale"},
                             "reason": "The studio's design file fixes this scale"})
    (tmp_path / "plan.yaml").write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")

    def status():
        report = lint_cli.run(plan=tmp_path / "plan.yaml", layers=["plan"], rule_ids=["type.flat-hierarchy"])
        return [f["status"] for f in report["findings"]]

    assert status() == ["open"]
    (tmp_path / "DESIGN.md").write_text("typography:\n  scale: 1.05\n", encoding="utf-8")
    assert status() == ["waived"]


# ---------------------------------------------------------------- what each kind of evidence looks up

def gap(alternatives, entry=None, plan=None, ledger=None, design_text=None):
    case = {"id": "a-case", "when": "a condition the test states", "evidence": alternatives}
    return keep_evidence.gap(case, {"evidence": entry or {}}, Sources(plan or {}, ledger, design_text))


def test_a_case_without_listed_evidence_waives_on_its_reason_alone():
    assert keep_evidence.gap({"id": "x", "when": "anything at all", "evidence": "none"}, {}, Sources({})) is None
    assert keep_evidence.gap({"id": "x", "when": "anything at all"}, {}, Sources({})) is None


@pytest.mark.parametrize("condition, plan, holds", [
    ({"plan": "mode", "has": ["repair"]}, {"mode": "repair"}, True),
    ({"plan": "mode", "has": ["repair"]}, {"mode": "create"}, False),
    ({"plan": "brief.platform", "has": ["ios", "android"]}, {"brief": {"platform": ["web", "ios"]}}, True),
    ({"plan": "brief.platform", "lacks": ["web"]}, {"brief": {"platform": ["desktop", "embedded"]}}, True),
    ({"plan": "brief.platform", "lacks": ["web"]}, {"brief": {"platform": ["web", "ios"]}}, False),
    ({"plan": "brief.platform", "lacks": ["web"]}, {}, False),                   # nothing to lack it from
    ({"plan": "flows[*].max_steps", "min": 2}, {"flows": [{"max_steps": 1}, {"max_steps": 3}]}, True),
    ({"plan": "flows[*].max_steps", "min": 2}, {"flows": [{"max_steps": 1}]}, False),
    ({"plan": "flows[*].max_steps", "min": 2}, {"flows": [{"id": "x"}]}, False),
    ({"plan": "output_condition", "present": True}, {"output_condition": {"medium": "print"}}, True),
    ({"plan": "output_condition", "present": True}, {"output_condition": {}}, False),
    ({"plan": "tokens.color.roles[*].role", "has": ["data"]},
     {"tokens": {"color": {"roles": [{"role": "field"}, {"role": "data"}]}}}, True),
])
def test_a_plan_condition_holds_when_the_plan_says_it(condition, plan, holds):
    assert (gap([condition], plan=plan) is None) is holds


def test_a_plan_condition_that_fails_says_what_the_plan_has():
    why = gap([{"plan": "brief.platform", "lacks": ["web"]}], plan={"brief": {"platform": ["web", "ios"]}})
    assert "brief.platform must not include web; it has web, ios" in why


LEDGER = {"assets": [
    {"id": "partner-logo", "kind": "mark", "origin": "third-party", "role": "brand", "used_by": ["kiln-shop-landing"]},
    {"id": "other-logo", "kind": "mark", "origin": "third-party", "role": "brand", "used_by": ["another-task"]},
    {"id": "hero-photo", "kind": "photo", "origin": "own", "role": "informative", "used_by": ["kiln-shop-landing"]},
]}
PLAN = {"task": {"id": "kiln-shop-landing"}}


@pytest.mark.parametrize("cited, spec, ledger, holds", [
    ("partner-logo", {"kind": ["mark"]}, LEDGER, True),
    ("partner-logo", {"kind": ["mark", "logo"], "origin": ["third-party"]}, LEDGER, True),
    ("partner-logo", {"kind": ["mark"]}, None, False),                           # no ledger given
    (None, {"kind": ["mark"]}, LEDGER, False),                                    # nothing cited
    ("missing-logo", {"kind": ["mark"]}, LEDGER, False),                          # not in the ledger
    ("other-logo", {"kind": ["mark"]}, LEDGER, False),                            # used by another task
    ("hero-photo", {"kind": ["mark"]}, LEDGER, False),                            # the wrong kind of asset
    ("hero-photo", {"origin": ["own", "commissioned"]}, LEDGER, True),
    ("partner-logo", {"origin": ["own", "commissioned"]}, LEDGER, False),
])
def test_an_asset_is_evidence_only_when_the_ledger_records_it_for_this_task_with_the_listed_values(
        cited, spec, ledger, holds):
    entry = {"asset": cited} if cited else {}
    assert (gap([{"asset": spec}], entry, PLAN, ledger) is None) is holds


@pytest.mark.parametrize("kind, cited, plan, holds", [
    ("material", "Firing log sheet", {"world_materials": ["firing log sheet", "glaze numbers"]}, True),
    ("material", "kiln", {"world_materials": ["firing log sheet"]}, False),
    ("source", "PRODUCT.md", {"sources": [{"ref": "PRODUCT.md"}, {"ref": "https://example.com/archive"}]}, True),
    ("source", "legal.md", {"sources": [{"ref": "PRODUCT.md"}]}, False),
    ("brief", "keep dates in the studio's own format", {"brief": {"constraints": ["Keep dates in the studio's own format."]}}, True),
    ("brief", "dates in ISO format", {"brief": {"subject": "A pottery shop", "constraints": ["Mobile first"]}}, False),
])
def test_a_cited_line_material_or_source_must_be_in_the_plan_section_it_names(kind, cited, plan, holds):
    assert (gap([kind], {kind: cited}, plan) is None) is holds
    assert gap([kind], {}, plan) is not None                                      # nothing cited
