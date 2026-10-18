"""The mechanical checks of guideline items: target size against each guideline's own threshold, with the unit kept and the web
prototype's mapping stated, and the findings of existing rules (reflow at 320, focus, WCAG's own target minimum) naming the
guideline items they are evidence for."""
from __future__ import annotations

import copy

import pytest
import yaml
from jsonschema import Draft202012Validator

from lapis_design import guidelines, shared_dir
from lapis_design.lint import detectors, engine
from lapis_design.lint.types import Context
from test_lint_render_type import FOCUSABLE, Page, extract, target_page

RULES = yaml.safe_load((shared_dir() / "slop" / "rules.yaml").read_text(encoding="utf-8"))
FINDINGS = Draft202012Validator(yaml.safe_load((shared_dir() / "slop" / "finding.schema.yaml").read_text(encoding="utf-8")))
ROUTE = {"kind": "official-docs", "ref": "https://example.org/docs"}


def plan(*entries: tuple[str, list[str]]) -> dict:
    return {"brief": {"guidelines": [{"id": gid, "platforms": platforms, "basis": "suggested", "route": ROUTE} for gid, platforms in entries]}}


def findings(the_plan: dict | None, doc: dict, *rules: str, layers=("render",)) -> list[dict]:
    detectors.load()
    return engine.lint(Context(rules=RULES, plan=the_plan, extract=doc), layers, list(rules) or None, probes={})


def sized(width: float, height: float, *, at: int = 390, name: str = "Menu") -> dict:
    page = Page(at, 844)
    section = page.box("section", (0, 0, at, 844))
    box = page.box("button", (10, 10, width, height), section, **FOCUSABLE)
    page.run(box, name, role="ui")
    return extract(page)


# ---------------------------------------------------------------- a target-size finding names the item

def test_a_target_smaller_than_the_guidelines_minimum_is_a_finding_that_names_the_item_and_both_units():
    [found] = findings(plan(("apple-hig", ["ios"])), sized(30, 30), "guideline.target-size")
    assert found["rule_id"] == "guideline.target-size" and found["layer"] == "render" and found["status"] == "open"
    assert found["guideline_items"] == ["apple-hig/target-size"]
    assert found["observed"].startswith("apple-hig/target-size: button 'Menu' is 30 x 30 CSS px; the item asks at least 44 pt = 44 CSS px")
    assert "(1 pt : 1 CSS px for a web prototype, guidelines/units.yaml)" in found["observed"]
    assert "390 px light" in found["observed"] and found["location"]["viewport"] == 390 and found["evidence"]["type"] == "measurement"
    assert found["severity"] == {"create": "warn", "review": "P2"} and found["blocking"] is False
    assert not list(FINDINGS.iter_errors({"version": 0, "tool": {"name": "slop_lint", "version": "0"}, "target": {}, "findings": [found]}))


def test_a_target_at_the_minimum_passes_and_so_does_a_plan_with_no_checklist_that_measures_one():
    assert findings(plan(("apple-hig", ["ios"])), sized(44, 44), "guideline.target-size") == []
    assert findings(plan(("apple-hig", ["ios"])), sized(44, 43.9), "guideline.target-size") != []
    assert findings(plan(("toss-tds", ["web"]), ("wcag-2.2", ["web"])), sized(10, 10), "guideline.target-size") == []
    assert findings({"brief": {}}, sized(10, 10), "guideline.target-size") == []


def test_with_no_plan_the_check_says_it_could_not_judge_and_never_passes():
    [skipped] = findings(None, sized(30, 30), "guideline.target-size")
    assert skipped["status"] == "skipped" and "no plan given" in skipped["observed"]


def test_each_guideline_keeps_its_own_unit_and_threshold_and_the_same_box_is_judged_against_each():
    doc = sized(46, 46)
    both = findings(plan(("apple-hig", ["ios"]), ("material-3", ["android"])), doc, "guideline.target-size")
    assert [f["guideline_items"] for f in both] == [["material-3/target-size"]]            # 46 reaches 44 pt, not 48 dp
    assert "asks at least 48 dp = 48 CSS px (1 dp : 1 CSS px" in both[0]["observed"]
    small = findings(plan(("apple-hig", ["ios"]), ("material-3", ["android"])), sized(40, 40), "guideline.target-size")
    assert [f["guideline_items"] for f in small] == [["apple-hig/target-size"], ["material-3/target-size"]]
    assert "44 pt" in small[0]["observed"] and "48 dp" in small[1]["observed"] and "dp" not in small[0]["observed"].split("asks")[1]


def test_the_windows_minimum_is_in_epx_with_a_second_way_to_pass_and_applies_to_the_desktop_captures():
    wide_short = findings(plan(("fluent-2", ["desktop"])), sized(130, 33, at=1440), "guideline.target-size")
    assert wide_short == []                                                                  # 32 epx tall passes when 120 epx wide
    [found] = findings(plan(("fluent-2", ["desktop"])), sized(130, 30, at=1440), "guideline.target-size")
    assert found["guideline_items"] == ["fluent-2/target-size-touchable"]
    assert "asks at least 40 epx = 40 CSS px (1 epx : 1 CSS px for a web prototype, guidelines/units.yaml), or 120 epx = 120 CSS px" in found["observed"]


def test_an_item_reads_only_the_captures_it_names_and_says_when_the_extract_has_none_of_them():
    desktop_only = sized(20, 20, at=1440)
    skipped = findings(plan(("apple-hig", ["ios"])), desktop_only, "guideline.target-size")
    assert [f["status"] for f in skipped] == ["skipped"] and "reads the 390 px capture" in skipped[0]["observed"]
    page = Page(390, 844)
    page.box("button", (0, 0, 20, 20), **FOCUSABLE)
    doc = extract(page)                               # only the phone capture
    assert [f["status"] for f in findings(plan(("fluent-2", ["desktop"])), doc, "guideline.target-size")] == ["skipped"]


def test_only_the_platforms_an_entry_covers_set_a_threshold():
    assert findings(plan(("apple-hig", ["web"])), sized(20, 20), "guideline.target-size") == []      # an HIG entry for the web has no item
    assert findings(plan(("material-3", ["web"])), sized(20, 20), "guideline.target-size")[0]["guideline_items"] == ["material-3/target-size"]


def test_a_link_in_a_sentence_and_an_unstyled_native_control_are_left_alone_as_the_wcag_rule_does():
    page = Page(390, 844)
    para = page.box("text", (0, 0, 390, 40))
    page.run(para, "Read the terms and the policy first.")
    page.box("link", (60, 4, 16, 16), para, **FOCUSABLE)
    page.box("input", (10, 100, 100, 20), **FOCUSABLE)
    assert findings(plan(("apple-hig", ["ios"])), extract(page), "guideline.target-size") == []


# ---------------------------------------------------------------- units

def test_a_threshold_is_converted_by_the_stated_mapping_and_the_finding_says_the_factor(monkeypatch):
    real = guidelines.units()
    table = {**real, "pt": {**real["pt"], "css_px_per_unit": 2}}
    monkeypatch.setattr(guidelines, "units", lambda: table)
    [found] = findings(plan(("apple-hig", ["ios"])), sized(60, 60), "guideline.target-size")        # 44 pt would be 88 CSS px
    assert "asks at least 44 pt = 88 CSS px (1 pt : 2 CSS px for a web prototype" in found["observed"]
    monkeypatch.setattr(guidelines, "units", lambda: real)
    assert findings(plan(("apple-hig", ["ios"])), sized(60, 60), "guideline.target-size") == []


def test_a_threshold_in_a_unit_that_is_no_length_is_not_compared_with_pixels(monkeypatch):
    real = guidelines.units()
    monkeypatch.setattr(guidelines, "units", lambda: {**real, "pt": {**real["pt"], "css_px_per_unit": None}})
    [found] = findings(plan(("apple-hig", ["ios"])), sized(10, 10), "guideline.target-size")
    assert found["status"] == "skipped" and "gives its size in pt, which is no length" in found["observed"]


def test_the_mapping_is_one_to_one_by_the_table_and_a_typographic_point_is_not_an_apple_point():
    assert [guidelines.css_px(1, u) for u in ("css-px", "pt", "dp", "epx")] == [1, 1, 1, 1]
    assert "typographic point" in (shared_dir() / "guidelines" / "units.yaml").read_text(encoding="utf-8")


# ---------------------------------------------------------------- existing rules name the items they are evidence for

def test_wcags_own_target_minimum_keeps_its_rule_and_names_its_item_without_a_second_finding():
    doc = extract(target_page(("button", (10, 10, 16, 16), {**FOCUSABLE, "text": "x"}),
                              ("button", (28, 10, 80, 32), {**FOCUSABLE, "text": "Menu"})))
    out = findings(plan(("wcag-2.2", ["web"])), doc, "component.small-target", "guideline.target-size")
    assert [(f["rule_id"], f["guideline_items"]) for f in out] == [("component.small-target", ["wcag-2.2/target-size-min"])]
    assert "16 x 16 px" in out[0]["observed"]
    assert "guideline_items" not in findings(None, doc, "component.small-target")[0]
    assert "guideline_items" not in findings(plan(("apple-hig", ["ios"])), doc, "component.small-target")[0]


def test_reflow_at_320_names_the_wcag_item_and_every_item_that_lists_the_rule():
    page = Page(320, 568, scroll_width=412)
    page.box("card", (0, 0, 412, 100))
    out = findings(plan(("wcag-2.2", ["web"]), ("krds", ["web"]), ("apple-hig", ["ios"])), extract(page), "layout.compact-overflow")
    assert [f["rule_id"] for f in out] == ["layout.compact-overflow"]
    assert out[0]["guideline_items"] == ["wcag-2.2/reflow", "krds/resize-one-direction", "krds/tabbar-labels", "apple-hig/text-reflow"]
    assert "412 px wide in a 320 px viewport" in out[0]["observed"]


def test_a_skipped_finding_of_such_a_rule_names_the_item_too_so_a_check_that_did_not_run_is_not_a_pass():
    doc = extract(Page(390, 844))
    out = findings(plan(("wcag-2.2", ["web"])), doc, "layout.compact-overflow")
    assert out and all(f["status"] == "skipped" for f in out)


def test_the_focus_outline_rule_names_the_focus_items_at_the_source_layer(tmp_path):
    (tmp_path / "app.css").write_text("button:focus { outline: none; }\n", encoding="utf-8")
    detectors.load()
    out = engine.lint(Context(rules=RULES, plan=plan(("wcag-2.2", ["web"]), ("fluent-2", ["desktop"])), source_root=tmp_path),
                      ("source",), ["code.focus-outline-removed"], probes={})
    assert out and out[0]["guideline_items"] == ["wcag-2.2/focus-visible", "fluent-2/focus-guided"]


def test_every_rule_an_item_names_exists_and_every_item_that_runs_a_check_names_a_detector_that_reads_the_plan():
    ids = {r["id"] for r in RULES["rules"]}
    for gid in guidelines.IDS:
        for item in guidelines.load(gid)["items"]:
            assert set(item.get("rules") or ()) <= ids
    detector = next(d for d in yaml.safe_load((shared_dir() / "slop" / "detectors.yaml").read_text())["detectors"]
                    if d["name"] == "guideline-target-size")
    assert detector["reads_plan"] == ["brief.guidelines"]
    assert copy.deepcopy(next(r for r in RULES["rules"] if r["id"] == "guideline.target-size"))["detect"]["render"]["detector"] == "guideline-target-size"


@pytest.mark.parametrize("gid", ["wcag-2.2", "material-3", "fluent-2", "krds", "apple-hig"])
def test_no_item_measured_by_a_check_is_also_listed_under_a_rule_so_one_item_never_has_two_thresholds(gid):
    for item in guidelines.load(gid)["items"]:
        assert not ("check" in item and item.get("rules")), f"{gid}/{item['id']}"


def test_the_printed_finding_names_the_items_whichever_rule_found_it():
    from lapis_design import summary

    [size] = findings(plan(("apple-hig", ["ios"])), sized(30, 30), "guideline.target-size")
    assert "apple-hig/target-size: button 'Menu' is 30 x 30 CSS px" in "\n".join(summary.finding_lines([size], "WARN"))
    page = Page(320, 568, scroll_width=412)
    page.box("card", (0, 0, 412, 100))
    [reflow] = findings(plan(("wcag-2.2", ["web"])), extract(page), "layout.compact-overflow")
    assert "(guideline item: wcag-2.2/reflow)" in "\n".join(summary.finding_lines([reflow], "WARN"))
