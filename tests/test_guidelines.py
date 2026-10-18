"""The guideline files (`src/shared/guidelines/`): their schema, the rule ids they lean on, their licenses and routes, and the
unit table. Behavior of the code that reads them is tested beside the code that uses them (plan check, the requirement
record, the critic packet, the lint)."""
from __future__ import annotations

import copy
import re

import pytest
import yaml

from lapis_design import guidelines, shared_dir

RULES = yaml.safe_load((shared_dir() / "slop" / "rules.yaml").read_text(encoding="utf-8"))
RULE_IDS = {r["id"] for r in RULES["rules"]}
CHECKLISTS = [g for g in guidelines.IDS if guidelines.load(g)["kind"] == "checklist"]
CONSULT_ONLY = [g for g in guidelines.IDS if guidelines.load(g)["kind"] == "consult-only"]


def test_each_guideline_file_names_its_own_guideline_and_other_has_no_file():
    for gid in guidelines.IDS:
        assert guidelines.load(gid)["guideline"] == gid
    assert guidelines.load("other") is None and guidelines.load("nonsense") is None


@pytest.mark.parametrize("gid", guidelines.IDS)
def test_each_guideline_file_matches_the_checklist_schema(gid):
    assert guidelines.validate(guidelines.load(gid)) == []


def test_the_schema_refuses_what_a_checklist_must_not_hold():
    doc = copy.deepcopy(guidelines.load("wcag-2.2"))
    bad = copy.deepcopy(doc)
    bad["items"][0]["measure"] = "guess"
    assert any("measure" in p for p in guidelines.validate(bad))
    bad = copy.deepcopy(doc)
    del bad["items"][0]["source"]["url"]
    assert any("url" in p for p in guidelines.validate(bad))
    bad = copy.deepcopy(doc)
    bad["items"][0]["threshold"] = {"value": 24, "unit": "inch", "quantity": "target-size"}
    assert any("inch" in p for p in guidelines.validate(bad))
    bad = copy.deepcopy(doc)
    bad["items"][1]["id"] = bad["items"][0]["id"]
    assert any("used twice" in p for p in guidelines.validate(bad))
    bad = copy.deepcopy(guidelines.load("apple-hig"))
    bad["items"][0].pop("threshold")             # a mechanical check without its threshold
    assert any("threshold" in p for p in guidelines.validate(bad))
    empty = copy.deepcopy(doc)
    empty["items"] = []
    assert any("non-empty" in p or "should be non-empty" in p for p in guidelines.validate(empty))


@pytest.mark.parametrize("gid", CONSULT_ONLY)
def test_toss_and_seed_are_consult_only_references_with_links_and_no_items(gid):
    doc = guidelines.load(gid)
    assert doc["items"] == [] and len(doc["links"]) >= 5
    assert all(link["url"].startswith("https://") for link in doc["links"])
    assert guidelines.rows({"brief": {"guidelines": [{"id": gid, "platforms": ["web"]}]}}) == []
    bad = copy.deepcopy(doc)
    bad["items"] = [{"id": "x", "requirement": "A requirement that should not be here.", "source": {"section": "S", "url": "https://x.example/"},
                     "platforms": ["web"], "measure": "judge"}]
    assert guidelines.validate(bad)


def test_the_toss_file_records_the_kit_license_as_a_reason_for_having_no_checklist():
    doc = guidelines.load("toss-tds")
    assert any("outside Apps in Toss" in f for f in doc["license"]["forbids"])


@pytest.mark.parametrize("gid", CHECKLISTS)
def test_items_name_rules_that_exist_and_their_source_in_their_own_words(gid):
    doc = guidelines.load(gid)
    for item in doc["items"]:
        for rule in item.get("rules") or ():
            assert rule in RULE_IDS, f"{gid}/{item['id']} names the unknown rule {rule}"
        assert not re.search(r"[\"“”]", item["requirement"]), f"{gid}/{item['id']} quotes: write it in our words"
        assert item["source"]["url"].startswith("https://")
        assert set(item["platforms"]) <= set(doc["platforms"]), f"{gid}/{item['id']} reaches past the file's platforms"


# Resolved in Context7 on 2026-10-21 (the owner's list): the library id each guideline is read by, and how much the index held.
CONTEXT7 = {"apple-hig": ("/websites/developer_apple_design_human-interface-guidelines", 2550),
            "material-3": ("/websites/m3_material_io", 4154),
            "fluent-2": ("/websites/fluent2_microsoft_design", 818),
            "wcag-2.2": ("/websites/w3_tr_wcag22", 215),
            "daangn-seed": ("/llmstxt/seed-design_io_react_llms-full_txt", None),
            "krds": ("/im6705/krds-markdown", 427)}


@pytest.mark.parametrize("gid", guidelines.IDS)
def test_every_file_records_when_it_was_read_what_from_and_the_official_source_to_check_or_fall_back_to(gid):
    doc = guidelines.load(gid)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", doc["checked_at"])
    assert doc["route"]["written_from"]
    assert doc["route"]["official"]["kind"] in ("official-docs", "repo", "owner-saved") and doc["route"]["official"]["ref"]


@pytest.mark.parametrize("gid", guidelines.IDS)
def test_the_context7_library_id_is_the_recorded_one_and_a_guideline_with_no_index_records_none(gid):
    held = guidelines.load(gid)["route"].get("context7")
    if gid not in CONTEXT7:
        assert held is None                         # toss-tds: Context7 holds no official TDS index
        return
    library_id, snippets = CONTEXT7[gid]
    assert held["library_id"] == library_id
    assert held.get("snippets") == snippets         # SEED's llms-full.txt index has no snippet count recorded
    assert held["resolved_on"] == "2026-10-21"


def test_the_wcag_id_is_the_index_that_holds_the_text_not_the_one_snippet_one():
    held = guidelines.load("wcag-2.2")["route"]["context7"]
    assert held["library_id"] == "/websites/w3_tr_wcag22" and "/websites/w3_wai_wcag22" in held["note"]


def test_the_krds_context7_route_is_marked_third_party_and_points_at_the_official_source_for_any_claim_that_matters():
    route = guidelines.load("krds")["route"]
    assert route["context7"]["origin"] == "third-party"
    assert "official" in route["context7"]["note"] and "PDF" in route["context7"]["note"] and "/websites/krds_go_kr_html_site_index" in route["context7"]["note"]
    assert route["official"]["ref"] == "https://www.krds.go.kr/html/site/index.html" and "PDF" in route["official"]["note"]
    assert all(guidelines.load(g)["route"].get("context7", {}).get("origin", "official") == "official" for g in CONTEXT7 if g != "krds")


def test_only_the_hig_index_is_marked_as_lagging_and_the_file_lists_what_it_lacks():
    lagging = [g for g in guidelines.IDS if "lags" in guidelines.load(g)["route"].get("context7", {})]
    assert lagging == ["apple-hig"]
    assert "Live Activities" in guidelines.load("apple-hig")["route"]["context7"]["lags"]       # only the newest change may be missing


def test_the_schema_refuses_a_malformed_library_id_and_a_third_party_route_with_no_note():
    doc = guidelines.load("krds")
    bad = copy.deepcopy(doc)
    bad["route"]["context7"]["library_id"] = "krds-markdown"
    assert any("library_id" in p for p in guidelines.validate(bad))
    bad = copy.deepcopy(doc)
    del bad["route"]["context7"]["note"]
    assert any("note" in p for p in guidelines.validate(bad))
    bad = copy.deepcopy(doc)
    bad["route"]["official"]["kind"] = "context7"
    assert any("context7" in p for p in guidelines.validate(bad))
    bad = copy.deepcopy(doc)
    del bad["route"]["official"]
    assert any("official" in p for p in guidelines.validate(bad))


def test_licenses_that_ask_for_attribution_have_their_line_in_the_file():
    krds, m3, wcag, fluent = (guidelines.load(g)["license"] for g in ("krds", "material-3", "wcag-2.2", "fluent-2"))
    assert "KOGL Type 1" in krds["attribution"] and "krds.go.kr" in krds["attribution"] and "Ministry of the Interior and Safety" in krds["attribution"]
    assert "CC BY 4.0" in m3["attribution"] and "m3.material.io" in m3["attribution"]
    assert "World Wide Web Consortium" in wcag["attribution"] and "REC-WCAG22-20241212" in wcag["attribution"]
    assert "CC BY 4.0" in fluent["attribution"] and "learn.microsoft.com" in fluent["attribution"]


def test_the_hig_file_names_the_2026_changes_its_index_does_not_hold_and_how_to_read_it_without_automation():
    doc = guidelines.load("apple-hig")
    text = " ".join(doc["not_covered"])
    for changed in ("Menus", "Tab bars", "Generative AI", "iPhone Duo", "Live Activities"):
        assert changed in text
    assert doc["route"]["context7"]["library_id"] == "/websites/developer_apple_design_human-interface-guidelines"
    assert doc["route"]["official"]["kind"] == "owner-saved" and "no fetcher" in doc["route"]["official"]["ref"]
    assert any("automated fetching" in f for f in doc["license"]["forbids"])


def test_hig_items_from_the_index_are_not_marked_unreviewed_and_unread_ones_are():
    assert not any(i.get("needs_review") for i in guidelines.load("apple-hig")["items"])
    assert [i["id"] for i in guidelines.load("material-3")["items"] if i.get("needs_review")] == ["text-resizing"]


def test_units_keep_apple_points_android_dp_and_windows_epx_apart_with_a_stated_mapping():
    table = guidelines.units()
    assert {"css-px", "pt", "dp", "epx", "percent", "count"} == set(table)
    for unit in ("pt", "dp", "epx"):
        assert table[unit]["css_px_per_unit"] == 1 and table[unit]["basis"]
    assert "typographic" in (shared_dir() / "guidelines" / "units.yaml").read_text(encoding="utf-8")
    assert guidelines.css_px(44, "pt") == 44 and guidelines.css_px(48, "dp") == 48 and guidelines.css_px(40, "epx") == 40
    assert guidelines.css_px(200, "percent") is None and guidelines.css_px(5, "count") is None and guidelines.css_px(1, "inch") is None


def test_every_mechanical_check_has_a_threshold_in_a_unit_that_is_a_length():
    seen = []
    for gid in CHECKLISTS:
        for item in guidelines.load(gid)["items"]:
            if "check" in item:
                seen.append(f"{gid}/{item['id']}")
                assert guidelines.css_px(item["threshold"]["value"], item["threshold"]["unit"]) is not None
    assert seen == ["apple-hig/target-size", "material-3/target-size", "fluent-2/target-size-touchable"]
