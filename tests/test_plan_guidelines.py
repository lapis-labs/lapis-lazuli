"""`brief.guidelines` of the plan: the defaults `plan check` suggests from the brief, a guideline the owner named becoming
`declared`, the plan's schema for an entry, and the owner's `visual` choice carried from the direction conversation."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from lapis_design import direction, guidelines, plan_check, shared_dir
from procedure_support import DIRECTION_PROPOSAL, TASK, clear_direction, make_project, row_id, save, write_requirements

BRIEF = {"subject": "Online sales for a small pottery studio", "one_job": "Let visitors see this firing's pieces and reserve one",
         "audience": "Craft lovers in their 30s and 40s", "platform": ["web"], "locales": ["en"], "product_frame": "e-commerce",
         "constraints": ["Most visits are on mobile"]}
ROUTE = {"kind": "official-docs", "ref": "https://www.w3.org/TR/2024/REC-WCAG22-20241212/"}
SCHEMA = shared_dir() / "plan" / "schema.yaml"


def entry(gid: str, platforms: list[str], **more) -> dict:
    return {"id": gid, "platforms": platforms, "basis": "suggested", "route": ROUTE, **more}


def plan_with(**brief) -> dict:
    plan = yaml.safe_load((shared_dir() / "plan" / "example.plan.yaml").read_text(encoding="utf-8"))
    plan["brief"] = {**copy.deepcopy(BRIEF), **brief}
    return plan


def findings(plan: dict, root: Path, rule: str | None = None) -> list[dict]:
    found = plan_check.check_guidelines(plan, root, "plan.yaml")
    return [f for f in found if rule is None or f["rule_id"] == rule]


def suggested(plan: dict, root: Path) -> list[str]:
    return [f["observed"] for f in findings(plan, root, "guideline.suggested-missing")]


@pytest.fixture
def root(tmp_path) -> Path:
    return tmp_path


# ---------------------------------------------------------------- the defaults

@pytest.mark.parametrize(("platform", "constraints", "expected"), [
    (["ios"], [], ["apple-hig"]),
    (["android"], [], ["material-3"]),
    (["web"], [], ["wcag-2.2"]),
    (["ios", "web"], [], ["apple-hig", "wcag-2.2"]),
    (["desktop"], ["a Windows 11 desktop app"], ["fluent-2"]),
    (["desktop", "web"], ["runs on Windows"], ["fluent-2", "wcag-2.2"]),
    (["desktop"], ["runs on macOS"], []),
    (["email"], [], []),
])
def test_the_defaults_come_from_the_platform(platform, constraints, expected):
    found, _ = guidelines.suggest({**BRIEF, "platform": platform, "constraints": constraints})
    assert [f["id"] for f in found] == expected
    assert all(f["platforms"] and f["why"] for f in found)


@pytest.mark.parametrize("frame", ["marketing-landing", "saas-dashboard-admin", "consumer-mobile-app", "fintech-regulated", "other"])
def test_the_product_frame_changes_none_of_them(frame):
    base = [f["id"] for f in guidelines.suggest({**BRIEF, "platform": ["ios", "web"], "product_frame": "e-commerce"})[0]]
    assert [f["id"] for f in guidelines.suggest({**BRIEF, "platform": ["ios", "web"], "product_frame": frame})[0]] == base


def test_a_desktop_whose_system_is_not_named_is_a_question_and_gets_no_guideline():
    found, questions = guidelines.suggest({**BRIEF, "platform": ["desktop"]})
    assert found == [] and len(questions) == 1 and "operating system" in questions[0]
    assert guidelines.suggest({**BRIEF, "platform": ["desktop"], "constraints": ["Windows"]})[1] == []


@pytest.mark.parametrize(("locales", "subject", "expected"), [
    (["ko-KR"], "주민센터 민원 신청 서비스", True),
    (["ko"], "A city hall portal for permit applications", True),
    (["ko"], "A pottery studio's shop", False),
    (["en"], "A municipal government portal", False),          # a Korean public service: the locale has to be Korean
])
def test_a_korean_public_service_gets_krds(locales, subject, expected):
    found, _ = guidelines.suggest({**BRIEF, "platform": ["web"], "locales": locales, "subject": subject})
    assert ("krds" in [f["id"] for f in found]) is expected


def test_plan_check_suggests_what_the_brief_calls_for_and_never_blocks(root):
    plan = plan_with(platform=["ios", "web", "desktop"])
    out = findings(plan, root)
    assert sorted(f["rule_id"] for f in out) == ["guideline.desktop-os-unknown", "guideline.suggested-missing", "guideline.suggested-missing"]
    assert not any(f["blocking"] for f in out)
    by_id = {f["observed"].split("for ")[-1]: f for f in out if f["rule_id"] == "guideline.suggested-missing"}
    assert by_id["the WCAG 2.2 web accessibility guidelines"]["severity"]["create"] == "warn"      # web: always
    assert by_id["Apple's Human Interface Guidelines"]["severity"]["create"] == "info"
    hig = by_id["Apple's Human Interface Guidelines"]
    assert "id: apple-hig" in hig["fix"] and "platforms: [ios]" in hig["fix"] and "context7" in hig["fix"] and hig["location"]["path"] == "brief.guidelines"


def test_a_listed_guideline_is_not_suggested_again(root):
    plan = plan_with(platform=["web"], guidelines=[entry("wcag-2.2", ["web"], visual="none")])
    assert findings(plan, root) == []


def test_the_example_plan_lists_wcag_and_passes_the_check_with_no_guideline_finding(root):
    plan = yaml.safe_load((shared_dir() / "plan" / "example.plan.yaml").read_text(encoding="utf-8"))
    assert [g["id"] for g in plan["brief"]["guidelines"]] == ["wcag-2.2"]
    assert findings(plan, root) == []
    report = plan_check.run(None, shared_dir() / "slop" / "rules.yaml", None, SCHEMA, root, plan=plan, plan_label="example.plan.yaml")
    assert not any(f["rule_id"].startswith("schema.") for f in report["findings"])


def test_an_entry_that_covers_no_platform_of_its_checklist_gives_no_rows_and_says_so(root):
    plan = plan_with(platform=["ios"], guidelines=[entry("apple-hig", ["web"])])
    out = findings(plan, root, "guideline.platform-not-covered")
    assert len(out) == 1 and "none of its items becomes a requirement row" in out[0]["observed"] and not out[0]["blocking"]


# ---------------------------------------------------------------- the schema

def schema_problems(plan: dict) -> list[str]:
    return [f["observed"] for f in plan_check.check_schema(plan, plan_check.load_yaml(SCHEMA), "plan.yaml")]


def test_the_schema_takes_an_entry_with_a_route_and_refuses_a_malformed_one():
    plan = plan_with(guidelines=[entry("apple-hig", ["ios"], visual="follow",
                                       route={"kind": "context7", "ref": "/websites/developer_apple_design_human-interface-guidelines"})])
    assert schema_problems(plan) == []
    bad = plan_with(guidelines=[entry("apple-hig", ["ios"], visual="loudly")])
    assert any("loudly" in p for p in schema_problems(bad))
    bad = plan_with(guidelines=[{"id": "apple-hig", "platforms": ["ios"], "basis": "suggested"}])
    assert any("route" in p for p in schema_problems(bad))
    bad = plan_with(guidelines=[entry("apple-hig", ["ios"], route={"kind": "scraping", "ref": "https://developer.apple.com"})])
    assert any("scraping" in p for p in schema_problems(bad))
    bad = plan_with(guidelines=[entry("hig", ["ios"])])
    assert any("hig" in p for p in schema_problems(bad))


def test_an_other_guideline_needs_a_name_and_a_url_and_the_others_do_not():
    assert schema_problems(plan_with(guidelines=[entry("other", ["web"])])) != []
    ok = plan_with(guidelines=[entry("other", ["web"], name="Acme design language", url="https://design.acme.example/guide")])
    assert schema_problems(ok) == []
    assert guidelines.rows(ok) == []                          # no checklist of ours: nothing enters the record for it
    assert schema_problems(plan_with(guidelines=[entry("other", ["web"], name="Acme", url="http://insecure.example/")])) != []


def test_the_plan_schema_and_the_guideline_files_name_the_same_guidelines():
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    assert schema["$defs"]["guideline"]["properties"]["id"]["enum"] == list(guidelines.PLAN_IDS)
    direction_schema = yaml.safe_load((shared_dir() / "direction" / "schema.yaml").read_text(encoding="utf-8"))
    asked = direction_schema["properties"]["guidelines"]["items"]["properties"]["guideline"]["enum"]
    assert asked == [g for g in guidelines.PLAN_IDS if guidelines.has_visual_layer(g)]


# ---------------------------------------------------------------- declared

def owner_project(root: Path, *rows: str) -> Path:
    make_project(root)
    clear_direction(root)                                 # the fixture's owner already took the defaults of a direction proposal
    write_requirements(root, rows)
    return root


HIG_ROW = "Follow Apple's Human Interface Guidelines, it has to feel like an iPhone app"


def test_a_guideline_the_owner_named_in_the_brief_has_to_be_listed_as_declared(tmp_path):
    root = owner_project(tmp_path, HIG_ROW, "Let a visitor reserve one without an account")
    rid = row_id(HIG_ROW)
    plan = plan_with(platform=["ios"])
    missing = findings(plan, root, "guideline.declared-missing")
    assert len(missing) == 1 and rid in missing[0]["observed"] and "lists no entry" in missing[0]["observed"]
    assert missing[0]["blocking"] and missing[0]["class"] == "requirement" and f"row: {rid}" in missing[0]["fix"] and "basis: declared" in missing[0]["fix"]
    plan["brief"]["guidelines"] = [entry("apple-hig", ["ios"])]          # listed, but as a default
    again = findings(plan, root, "guideline.declared-missing")
    assert len(again) == 1 and "not declared" in again[0]["observed"]
    plan["brief"]["guidelines"] = [entry("apple-hig", ["ios"], basis="declared", row=rid)]
    assert findings(plan, root, "guideline.declared-missing") == [] and findings(plan, root, "guideline.declared-unsupported") == []


def test_a_declared_guideline_that_no_owner_row_names_is_not_taken_for_the_owners(tmp_path):
    root = owner_project(tmp_path, "Let a visitor reserve one without an account")
    plan = plan_with(platform=["ios"], guidelines=[entry("apple-hig", ["ios"], basis="declared")])
    out = findings(plan, root, "guideline.declared-unsupported")
    assert len(out) == 1 and "no row of the owner's requirement record names it" in out[0]["observed"] and not out[0]["blocking"]
    plan["brief"]["guidelines"] = [entry("apple-hig", ["ios"], basis="declared", row="R000000")]
    assert "does not hold" in findings(plan, root, "guideline.declared-unsupported")[0]["observed"]


@pytest.mark.parametrize(("text", "named"), [
    ("Use Material 3 on Android", ["material-3"]),
    ("We follow Material Design", ["material-3"]),
    ("Fluent 2 for the Windows app", ["fluent-2"]),
    ("Must meet WCAG 2.2 AA", ["wcag-2.2"]),
    ("KWCAG 준수", ["wcag-2.2"]),
    ("KRDS를 따라 주세요", ["krds"]),
    ("Apple HIG compliant, plus WCAG", ["apple-hig", "wcag-2.2"]),
    ("Toss Design System components only", ["toss-tds"]),
    ("SEED Design for the Daangn-style market", ["daangn-seed"]),
    ("Material of the pots is stoneware and the seed data is fake", []),          # a bare word is no guideline
    ("A higher bar for the hero image", []),
])
def test_what_names_a_guideline_in_the_owners_words(text, named):
    assert guidelines.named(text) == named


def test_the_owners_rows_are_read_as_they_are_a_declared_check_without_a_record_says_nothing(root):
    plan = plan_with(platform=["ios"], guidelines=[entry("apple-hig", ["ios"], basis="declared")])
    assert findings(plan, root, "guideline.declared-unsupported") == []         # no requirement record: nothing to compare with


# ---------------------------------------------------------------- the owner's visual choice

HEARD = "\n## Direction 1\n\n- [declared] V1 Apple's Human Interface Guidelines: {choice} — \"{words}\"\n"


def direction_project(root: Path, answer: str | None = None, *guideline_asks: dict) -> Path:
    owner_project(root)
    asks = guideline_asks or ({"id": "V1", "guideline": "apple-hig"},)
    save(root, f"direction/{TASK}.yaml", {**DIRECTION_PROPOSAL, "guidelines": list(asks)})
    if answer:
        answers = root / ".lapis" / "answers" / f"{TASK}.md"
        answers.write_text(answers.read_text(encoding="utf-8") + answer, encoding="utf-8")
    return root


def drift(plan: dict, root: Path) -> list[dict]:
    return findings(plan, root, "guideline.visual-drift")


def test_the_visual_question_is_one_item_per_guideline_in_plain_words_with_consult_as_the_default(tmp_path):
    root = direction_project(tmp_path, None, {"id": "V1", "guideline": "apple-hig"}, {"id": "V2", "guideline": "other", "name": "Acme design language"})
    assert direction.proposal_problem(root, TASK) is None
    asked = {i["id"]: i for i in direction.items(root, TASK) if i["kind"] == "V"}
    assert set(asked) == {"V1", "V2"} and asked["V1"]["guideline"] == "apple-hig" and asked["V2"]["guideline"] == "other:acme design language"
    label = asked["V1"]["label"]
    assert label.startswith("How closely should the look follow Apple's Human Interface Guidelines?")
    assert "How things behave is followed whichever you pick" in label
    assert "Acme design language" in asked["V2"]["label"]
    assert [o["id"] for o in asked["V1"]["options"]] == ["a", "b", "c"] and asked["V1"]["default"] == "b"
    assert [direction.VISUAL_BY_OPTION[o["id"]] for o in asked["V1"]["options"]] == ["follow", "consult", "none"]
    assert asked["V1"]["state"] == "open"
    assert "V1" in direction.asked(root, TASK) and "V2" in direction.owed(root, TASK, 1)


def test_the_owner_answers_it_like_any_item_and_it_is_one_of_their_declared_rows(tmp_path):
    root = direction_project(tmp_path, HEARD.format(choice="a", words="make it look like the real thing"))
    item = next(i for i in direction.items(root, TASK) if i["id"] == "V1")
    assert (item["state"], item["by"], item["choice"]) == ("decided", "owner", ["a"])
    from lapis_design import requirements

    requirements.refresh(root, TASK)
    assert any("V1 Apple" in r["text"] for r in requirements.rows(root, TASK))


def test_a_plan_whose_visual_is_not_the_owners_answer_is_refused_and_one_that_is_passes(tmp_path):
    root = direction_project(tmp_path, HEARD.format(choice="a", words="make it look like the real thing"))
    plan = plan_with(platform=["ios"], guidelines=[entry("apple-hig", ["ios"], visual="consult")])
    out = drift(plan, root)
    assert len(out) == 1 and out[0]["blocking"] and "chose option a" in out[0]["observed"] and "visual: follow" in out[0]["fix"]
    assert out[0]["location"]["path"] == "brief.guidelines[0].visual"
    plan["brief"]["guidelines"] = [entry("apple-hig", ["ios"], visual="follow")]
    assert drift(plan, root) == []


def test_an_absent_visual_reads_as_consult_so_the_default_answer_needs_nothing_and_another_one_does(tmp_path):
    root = direction_project(tmp_path, HEARD.format(choice="b", words="just look at it"))
    plan = plan_with(platform=["ios"], guidelines=[entry("apple-hig", ["ios"])])
    assert drift(plan, root) == [] and guidelines.visual_of(plan["brief"]["guidelines"][0]) == "consult"
    root2 = direction_project(tmp_path / "second", HEARD.format(choice="c", words="behavior only"))
    assert len(drift(plan, root2)) == 1


def test_a_question_nobody_answered_is_not_a_drift_and_a_guideline_never_asked_is_a_note(tmp_path):
    root = direction_project(tmp_path)
    plan = plan_with(platform=["ios", "web"], guidelines=[entry("apple-hig", ["ios"], visual="follow"), entry("wcag-2.2", ["web"], visual="none")])
    assert drift(plan, root) == []
    plan["brief"]["guidelines"].append(entry("material-3", ["android"]))
    unasked = findings(plan, root, "guideline.visual-unasked")
    assert len(unasked) == 1 and "Google's Material 3" in unasked[0]["observed"] and not unasked[0]["blocking"]
    assert not any("WCAG" in f["observed"] for f in findings(plan, root, "guideline.visual-unasked"))      # no visual layer: never asked


def test_the_proposal_asks_no_visual_question_for_wcag_and_asks_none_twice(tmp_path):
    root = direction_project(tmp_path, None, {"id": "V1", "guideline": "wcag-2.2"})
    assert "wcag-2.2" in (direction.proposal_problem(root, TASK) or "")
    root = direction_project(tmp_path / "again", None, {"id": "V1", "guideline": "apple-hig"}, {"id": "V2", "guideline": "apple-hig"})
    assert "twice" in direction.proposal_problem(root, TASK)
    root = direction_project(tmp_path / "other", None, {"id": "V1", "guideline": "other"})
    assert "name" in direction.proposal_problem(root, TASK)


def test_no_direction_proposal_means_nothing_to_compare(tmp_path):
    owner_project(tmp_path)
    plan = plan_with(platform=["ios"], guidelines=[entry("apple-hig", ["ios"], visual="follow")])
    assert findings(plan, tmp_path, "guideline.visual-drift") == [] and findings(plan, tmp_path, "guideline.visual-unasked") == []


def test_every_check_the_plan_runs_reads_the_guidelines_after_the_flows(tmp_path):
    plan = plan_with(platform=["ios"])
    report = plan_check.run(None, shared_dir() / "slop" / "rules.yaml", None, SCHEMA, tmp_path, plan=plan, plan_label="plan.yaml")
    assert any(f["rule_id"] == "guideline.suggested-missing" for f in report["findings"])
