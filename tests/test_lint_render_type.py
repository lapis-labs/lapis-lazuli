"""Type, contrast, target, overflow, and occlusion detectors (lint/detectors/render_type.py), run with
the shipped rules on small hand-built render extracts that validate against the extract schema."""
from __future__ import annotations

import copy
import json

import pytest
import yaml
from jsonschema import Draft202012Validator

from lapis_design import shared_dir
from lapis_design.lint.detectors import render_type  # noqa: F401  (registers the detectors)
from lapis_design.lint.types import DETECTORS, Context, Result
from lazuli.db import connect
from lazuli.scan import norm

RULES = yaml.safe_load((shared_dir() / "slop" / "rules.yaml").read_text(encoding="utf-8"))
EXTRACT_SCHEMA = Draft202012Validator(
    yaml.safe_load((shared_dir() / "render" / "extract.schema.yaml").read_text(encoding="utf-8")))
WHITE, BLACK = [1.0, 0.0, 0.0], [0.0, 0.0, 0.0]


# ---------------------------------------------------------------- builders

class Page:
    """One captured viewport of a render extract."""

    def __init__(self, width: int = 1440, height: float = 900, theme: str = "light", **fields):
        self.vp = {"width": width, "height": height, "theme": theme, "boxes": [], "text": [], **fields}
        self.count = 0

    def box(self, role: str, rect: tuple, parent: str | None = None, **fields) -> str:
        self.count += 1
        ident = f"b{self.count:012x}"
        self.vp["boxes"].append({"id": ident, "parent": parent, "role": role, "role_confidence": 1,
                                 "rect": dict(zip("xywh", rect)), **fields})
        return ident

    def run(self, box: str, text: str, *, size: float = 16, role: str | None = "body", script: str = "latn",
            family: str = "Grotesk Test", rendered: str | None = None, font: dict | None = None, **fields) -> dict:
        run = {"id": f"{box}-t{len(self.vp['text'])}", "box": box, "text": text,
               "chars": sum(not c.isspace() for c in text), "script": script,
               "font": {"requested": family, "rendered": rendered or family, **(font or {})},
               "size_px": size, **fields}
        if role is not None:
            run["type_role"] = role
        self.vp["text"].append(run)
        return run

    def sections(self, *boxes: str, archetype: str = "other") -> None:
        self.vp.setdefault("derived", {})["sections"] = [{"box": b, "archetype": archetype} for b in boxes]


def extract(*pages: Page) -> dict:
    doc = {"version": 1,
           "meta": {"extractor": {"name": "render_check", "version": "test"}, "generated_at": "2026-09-26T00:00:00Z"},
           "source": {"kind": "render"}, "viewports": [p.vp for p in pages]}
    EXTRACT_SCHEMA.validate(doc)
    return doc


def rule(rule_id: str) -> dict:
    return copy.deepcopy(next(r for r in RULES["rules"] if r["id"] == rule_id))


def lint(rule_id: str, doc: dict | None = None, *, layer: str = "render", det: dict | None = None,
         **ctx) -> Result:
    """Run the detector the shipped rule names at a layer; `det` overrides parts of its entry."""
    spec = rule(rule_id)
    entry = {**spec["detect"][layer], **(det or {})}
    detector = DETECTORS[entry["detector"]]
    assert layer in detector.layers
    return detector.fn(Context(rules=RULES, extract=doc, **ctx), entry, spec, layer)


def one_hit(result: Result):
    assert result.skipped is None, result.skipped
    assert len(result.hits) == 1, [h.observed for h in result.hits]
    return result.hits[0]


def no_hits(result: Result) -> None:
    assert result.skipped is None, result.skipped
    assert result.hits == [], [h.observed for h in result.hits]


# ---------------------------------------------------------------- fonts

def test_font_fallback_reports_each_script_that_falls_back_once_across_captures():
    pages = []
    for width in (390, 1440):
        page = Page(width)
        para = page.box("text", (0, 0, 300, 40))
        page.run(para, "Hello", family="Grotesk Test")
        page.run(para, "안녕하세요", script="hang", family="Grotesk Test", rendered="Hangul System Gothic",
                 font={"fallback": True})
        pages.append(page)
    hit = one_hit(lint("type.font-fallback", extract(*pages)))
    assert "Hangul" in hit.observed and "'Grotesk Test'" in hit.observed and "'Hangul System Gothic'" in hit.observed
    assert "390 px light" in hit.observed and "1440 px light" in hit.observed
    assert hit.location["box"] == "b000000000001"


def test_font_fallback_ignores_generic_families_and_emoji():
    page = Page()
    para = page.box("text", (0, 0, 300, 40))
    page.run(para, "Plain", family="system-ui", rendered="Platform Sans", font={"fallback": True})
    page.run(para, "Mixed case", family="System-UI", rendered="Platform Sans", font={"fallback": True})
    page.run(para, "🎉", script="other", family="Grotesk Test", rendered="Color Emoji", font={"fallback": True})
    no_hits(lint("type.font-fallback", extract(page)))


def test_font_fallback_ignores_the_generic_families_of_the_font_table(house_generics):
    page = Page()
    para = page.box("text", (0, 0, 300, 40))
    page.run(para, "Plain", family=house_generics["generic"], rendered="Platform Sans", font={"fallback": True})
    page.run(para, "Mixed case", family="House-Stack", rendered="Platform Sans", font={"fallback": True})
    no_hits(lint("type.font-fallback", extract(page)))


def test_font_fallback_skips_without_text_or_extract():
    assert lint("type.font-fallback", None).skipped == "no render extract given"
    assert "no text runs" in lint("type.font-fallback", extract(Page())).skipped


def test_synthetic_style_reports_synthesized_bold():
    page = Page()
    heading = page.box("heading", (0, 0, 300, 40))
    page.run(heading, "Title", role="heading", weight=700, font={"synthetic": "bold"})
    page.run(page.box("text", (0, 50, 300, 40)), "Body", font={"synthetic": "none"})
    hit = one_hit(lint("type.synthetic-style", extract(page)))
    assert "synthesized bold at weight 700" in hit.observed


def test_synthetic_style_passes_real_faces_and_skips_unrecorded_runs():
    page = Page()
    page.run(page.box("text", (0, 0, 300, 40)), "Body", font={"synthetic": "none"})
    no_hits(lint("type.synthetic-style", extract(page)))
    page.run(page.box("text", (0, 50, 300, 40)), "Unknown")
    assert "synthesized-style record" in lint("type.synthetic-style", extract(page)).skipped


def test_hangul_negative_tracking_fires_only_below_the_bound_on_body_text():
    page = Page(390, 844)
    page.run(page.box("text", (0, 0, 300, 40)), "본문 글자", script="hang", lang="ko-KR", letter_spacing_em=-0.02)
    page.run(page.box("text", (0, 50, 300, 40)), "기본 글자", script="hang", lang="ko-KR", letter_spacing_em=0)
    page.run(page.box("heading", (0, 100, 300, 40)), "제목", role="heading", script="hang", lang="ko-KR",
             letter_spacing_em=-0.03)
    page.run(page.box("text", (0, 150, 300, 40)), "Latin body", letter_spacing_em=-0.02)
    hit = one_hit(lint("type.ko.body-negative-tracking", extract(page)))
    assert "-0.02 em" in hit.observed and hit.location["box"] == "b000000000001"


def test_hangul_negative_tracking_skips_when_roles_are_missing():
    page = Page(390, 844)
    page.run(page.box("text", (0, 0, 300, 40)), "본문", role=None, script="hang", letter_spacing_em=-0.02)
    assert "type role" in lint("type.ko.body-negative-tracking", extract(page)).skipped


def test_keep_all_missing_reports_hangul_body_without_keep_all():
    page = Page(390, 844)
    page.run(page.box("text", (0, 0, 300, 60)), "줄이 바뀌는 본문", script="hang", word_break="normal", lines=2)
    page.run(page.box("text", (0, 70, 300, 60)), "잘 끊기는 본문", script="hang", word_break="keep-all", lines=2)
    hit = one_hit(lint("type.ko.keep-all-missing", extract(page)))
    assert "word-break normal" in hit.observed and "1 wrapping" in hit.observed


def test_keep_all_missing_passes_keep_all_and_skips_unmeasured_runs():
    page = Page(390, 844)
    page.run(page.box("text", (0, 0, 300, 60)), "본문", script="hang", word_break="keep-all")
    no_hits(lint("type.ko.keep-all-missing", extract(page)))
    page.run(page.box("text", (0, 70, 300, 60)), "본문 둘", script="hang")
    assert "word-break" in lint("type.ko.keep-all-missing", extract(page)).skipped


# ---------------------------------------------------------------- hierarchy

def hierarchy_page(heading_size: float, heading_weight: float = 400, *, colors: bool = True) -> Page:
    page = Page()
    paint = {"color": BLACK, "backdrop": {"oklch": WHITE}} if colors else {}
    page.run(page.box("heading", (0, 0, 600, 40)), "Section title", role="heading", size=heading_size,
             weight=heading_weight, **paint)
    page.run(page.box("text", (0, 50, 600, 80)), "Body copy that runs for a while.", size=20, weight=400, **paint)
    return page


def test_flat_hierarchy_fires_when_no_lever_reaches_the_ratio():
    hit = one_hit(lint("type.flat-hierarchy", extract(hierarchy_page(22))))
    assert "size 1.10x" in hit.observed and "weight 1.00x" in hit.observed


def test_flat_hierarchy_passes_at_the_ratio_or_with_another_lever():
    no_hits(lint("type.flat-hierarchy", extract(hierarchy_page(24))))            # 24 / 20 = 1.2, the edge
    no_hits(lint("type.flat-hierarchy", extract(hierarchy_page(20, 700))))


def test_flat_hierarchy_skips_when_a_lever_cannot_be_measured():
    result = lint("type.flat-hierarchy", extract(hierarchy_page(22, colors=False)))
    assert result.hits == [] and "contrast not measured" in result.skipped


def display_page(height: float, lines: int) -> Page:
    page = Page(390, 844)
    section = page.box("section", (0, 0, 390, 844))
    page.run(page.box("heading", (0, 0, 390, height), section), "A very large opening headline", role="display",
             size=56, lines=lines)
    page.run(page.box("text", (0, height, 390, 60), section), "Body", size=16)
    return page


def test_oversized_display_fires_on_area_share_and_line_count():
    area = one_hit(lint("type.oversized-display", extract(display_page(400, 3))))
    assert "47%" in area.observed and "above 40%" in area.observed
    lines = one_hit(lint("type.oversized-display", extract(display_page(200, 5))))
    assert "wraps to 5 lines" in lines.observed


def test_oversized_display_passes_at_the_bounds():
    no_hits(lint("type.oversized-display", extract(display_page(200, 4))))


def test_oversized_display_skips_line_check_without_a_390_capture():
    page = Page(1440, 900)
    page.run(page.box("heading", (0, 0, 800, 100)), "Headline", role="display", size=64, lines=1)
    assert "390 px" in lint("type.oversized-display", extract(page)).skipped


# ---------------------------------------------------------------- text metrics

def metric_page(**runs: dict) -> Page:
    page = Page()
    for i, (text, fields) in enumerate(runs.items()):
        page.run(page.box("text", (0, i * 50, 600, 40)), text, **fields)
    return page


def test_negative_tracking_fires_only_below_the_bound():
    hit = one_hit(lint("type.negative-tracking", extract(metric_page(
        Tight={"role": "display", "size": 64, "letter_spacing_em": -0.05},
        Edge={"role": "display", "size": 64, "letter_spacing_em": -0.04}))))
    assert "-0.05 em below -0.04 em" in hit.observed


def test_body_tracking_fires_only_above_the_bound():
    hit = one_hit(lint("type.body-tracking", extract(metric_page(
        Loose={"letter_spacing_em": 0.03}, Edge={"letter_spacing_em": 0.02},
        Label={"role": "label", "letter_spacing_em": 0.1}))))
    assert "+0.03 em above" in hit.observed


def test_tight_leading_uses_the_per_script_bound():
    hit = one_hit(lint("type.tight-leading", extract(metric_page(
        한글={"script": "hang", "line_height": 1.3}, Latin={"line_height": 1.3}))))
    assert "Hangul" in hit.observed and "below 1.4" in hit.observed


def test_long_measure_fires_above_the_per_script_bound():
    result = lint("type.long-measure", extract(metric_page(
        Long={"measure_chars": 81}, Edge={"measure_chars": 80}, 한글={"script": "hang", "measure_chars": 46})))
    assert sorted(h.observed.split(" text")[0] for h in result.hits) == ["body Hangul", "body Latin"]


def test_tiny_ui_text_fires_below_the_bound():
    hit = one_hit(lint("type.tiny-ui-text", extract(metric_page(
        Small={"role": "ui", "size": 11}, Edge={"role": "ui", "size": 12}, Heading={"role": "heading", "size": 10}))))
    assert "size 11 px below 12 px" in hit.observed


def test_run_metrics_skip_when_the_field_is_missing():
    assert "line_height" in lint("type.tight-leading", extract(metric_page(Body={}))).skipped


def test_caps_prose_counts_words_set_in_capitals():
    hit = one_hit(lint("type.caps-prose", extract(metric_page(
        **{"Five words set in capitals": {"transform": "uppercase"}, "FOUR WORDS IN CAPS": {}}))))
    assert hit.observed.startswith("5 words")


def test_single_family_fires_below_two_families():
    hit = one_hit(lint("type.single-neutral-sans", extract(metric_page(A={}, B={"role": "heading"}))))
    assert "1 distinct family" in hit.observed
    no_hits(lint("type.single-neutral-sans", extract(metric_page(A={}, B={"family": "Serif Test"}))))


def nav_page(positions: list[tuple[float, float]], *, width: int = 1440, lines: int = 1) -> Page:
    page = Page(width)
    nav = page.box("nav", (0, 0, width, 100))
    items = page.box("list", (0, 0, width, 100), nav)
    for i, (x, y) in enumerate(positions):
        page.run(page.box("link", (x, y, 100, 20), items), f"Item {i}", role="nav", lines=lines)
    return page


def test_wrapped_navigation_fires_on_a_second_row():
    hit = one_hit(lint("layout.wrapped-navigation", extract(nav_page([(0, 0), (120, 0), (240, 0), (0, 30)]))))
    assert "2 rows" in hit.observed


def test_wrapped_navigation_passes_one_row_and_vertical_lists():
    no_hits(lint("layout.wrapped-navigation", extract(nav_page([(0, 0), (120, 0), (240, 0)]))))
    no_hits(lint("layout.wrapped-navigation", extract(nav_page([(0, 0), (0, 30), (0, 60)]))))
    assert "2 rows" in one_hit(lint("layout.wrapped-navigation", extract(nav_page([(0, 0), (120, 0)], lines=2)))).observed


def test_wrapped_navigation_skips_without_a_1440_capture():
    assert "1440 px" in lint("layout.wrapped-navigation", extract(nav_page([(0, 0)], width=390))).skipped


# ---------------------------------------------------------------- labels before headings

def sectioned_page(labels: list[dict | None], *, heading_role: str = "heading") -> Page:
    """One section per label: an optional label run right above a heading, then body text."""
    page = Page()
    sections = []
    for i, label in enumerate(labels):
        top = i * 400
        section = page.box("section", (0, top, 1440, 400))
        sections.append(section)
        if label is not None:
            label = dict(label)
            chip_style = label.pop("chip", None)
            holder = section
            if chip_style:
                holder = page.box("card", (100, top + 40, 80, 24), section, style=chip_style)
            page.run(page.box("text", (100, top + 44, 200, 16), holder), label.pop("text"), size=12,
                     role=label.pop("role", "label"), **label)
        page.run(page.box("heading", (100, top + 70, 800, 48), section), f"Heading {i}", role=heading_role,
                 size=40)
        page.run(page.box("text", (100, top + 130, 800, 60), section), "Body text follows here.")
    page.sections(*sections)
    return page


def test_eyebrow_labels_fire_when_more_sections_than_allowed_open_with_one():
    labels = [{"text": "FEATURES", "transform": "uppercase", "letter_spacing_em": 0.12},
              {"text": "PRICING", "transform": "uppercase"}, {"text": "FAQ", "letter_spacing_em": 0.1}]
    hit = one_hit(lint("type.eyebrow-kicker", extract(sectioned_page(labels))))
    assert hit.observed.startswith("3 sections open with a small label") and "'FEATURES'" in hit.observed


def test_eyebrow_labels_pass_at_the_bound_and_ignore_plain_sentences():
    no_hits(lint("type.eyebrow-kicker", extract(sectioned_page(
        [{"text": "FEATURES", "transform": "uppercase"}, {"text": "PRICING", "transform": "uppercase"}, None]))))
    no_hits(lint("type.eyebrow-kicker", extract(sectioned_page(
        [{"text": "Read this first", "role": "body"}] * 3))))


def test_heading_badge_fires_on_a_chip_above_a_heading():
    chip = {"text": "New", "chip": {"background": [0.9, 0.08, 150], "radius_px": 12}}
    result = lint("type.heading-badge", extract(sectioned_page([chip, None])))
    hit = one_hit(result)
    assert "badge 'New' sits right above the heading 'Heading 0'" in hit.observed
    no_hits(lint("type.heading-badge", extract(sectioned_page([{"text": "NEW", "transform": "uppercase"}]))))


def test_eyebrow_labels_count_page_sections_not_cards():
    page = Page()
    band = page.box("section", (0, 0, 1440, 600))
    for i, tier in enumerate(("STARTER", "TEAM", "SCALE")):
        card = page.box("section", (100 + i * 420, 100, 400, 400), band)
        page.run(page.box("text", (120 + i * 420, 120, 200, 16), card), tier, size=12, role="label",
                 transform="uppercase")
        page.run(page.box("heading", (120 + i * 420, 146, 360, 40), card), f"Plan {i}", role="heading", size=32)
    no_hits(lint("type.eyebrow-kicker", extract(page)))


def test_eyebrow_labels_need_no_derived_sections_but_index_markers_do():
    page = sectioned_page([{"text": "FEATURES", "transform": "uppercase"}, {"text": "PRICING", "transform": "uppercase"},
                           {"text": "FAQ", "transform": "uppercase"}])
    del page.vp["derived"]
    assert one_hit(lint("type.eyebrow-kicker", extract(page)))
    assert "derived sections" in lint("layout.decorative-numbering", extract(page)).skipped


def test_index_markers_fire_when_numbers_label_separate_sections():
    page = sectioned_page([{"text": "01"}, {"text": "02"}, {"text": "03"}])
    hit = one_hit(lint("layout.decorative-numbering", extract(page)))
    assert "number 3 separate sections" in hit.observed


def test_index_markers_fire_on_numbers_out_of_content_order():
    page = sectioned_page([{"text": "01"}, {"text": "03"}])
    assert "do not count up" in one_hit(lint("layout.decorative-numbering", extract(page))).observed


def test_index_markers_pass_steps_numbered_inside_one_section():
    page = Page()
    section = page.box("section", (0, 0, 1440, 900))
    for i in range(3):
        top = 100 + i * 200
        page.run(page.box("text", (100, top, 40, 16), section), f"0{i + 1}", size=12, role="label")
        page.run(page.box("heading", (100, top + 24, 600, 32), section), f"Step {i + 1}", role="heading", size=28)
        page.run(page.box("text", (100, top + 64, 600, 40), section), "What happens in this step.")
    page.sections(section)
    no_hits(lint("layout.decorative-numbering", extract(page)))


# ---------------------------------------------------------------- font feature regions

GROTESK = {"panose": {"weight": "book", "proportion": "even-width", "contrast": "low"},
           "metrics": {"serif": False, "x_height_size": "large", "monospaced": False, "weight_class": 400,
                       "italic": False}}
DIDONE_ITALIC = {"panose": {"weight": "book", "proportion": "modern", "contrast": "very-high"},
                 "metrics": {"serif": True, "x_height_size": "small", "monospaced": False, "weight_class": 400,
                             "italic": True}}
MONO = {"panose": {"weight": "book", "proportion": "monospaced", "contrast": "none"},
        "metrics": {"serif": False, "x_height_size": "large", "monospaced": True, "weight_class": 400,
                    "italic": False}}
OLDSTYLE = {"panose": {"weight": "book", "proportion": "old-style", "contrast": "medium-low"},
            "metrics": {"serif": True, "x_height_size": "small", "monospaced": False, "weight_class": 400,
                        "italic": False}}


@pytest.fixture
def lazuli(tmp_path):
    conn = connect(tmp_path / "lazuli.db")

    def add(family: str, measured: dict | None, subfamily: str = "Regular") -> None:
        ps = f"{family.replace(' ', '')}-{subfamily}"
        cur = conn.execute(
            "INSERT INTO local_font (path, size, mtime, postscript_name, family, family_norm, subfamily, "
            "coverage_json, origin) VALUES (?, 1, '2026-09-26', ?, ?, ?, ?, '{}', 'user')",
            (f"/fonts/{ps}.otf", ps, family, norm(family), subfamily))
        if measured is not None:
            conn.execute(
                "INSERT INTO measurement (local_font_id, measurer_version, family_kind, panose_json, metrics_json, "
                "measured_at) VALUES (?, '0.1.0', 'text', ?, ?, '2026-09-26')",
                (cur.lastrowid, json.dumps(measured["panose"]), json.dumps(measured["metrics"])))

    add("Grotesk Test", GROTESK)
    add("Didone Test", DIDONE_ITALIC, "Italic")
    add("Mono Test", MONO)
    add("Oldstyle Test", OLDSTYLE)
    add("Unmeasured Test", None)
    conn.commit()
    yield conn
    conn.close()


def family_page(*runs: tuple[str, dict]) -> Page:
    page = Page()
    for i, (family, fields) in enumerate(runs):
        fields = dict(fields)
        page.run(page.box("text", (0, i * 50, 600, 40)), fields.pop("text", f"Text in {family}"), family=family,
                 **fields)
    return page


def test_rendered_family_region_fires_on_a_measured_neutral_grotesque(lazuli):
    hit = one_hit(lint("type.overused-neutral-grotesque",
                       extract(family_page(("Grotesk Test", {}), ("Oldstyle Test", {"role": "heading"}))),
                       lazuli=lazuli))
    assert "'Grotesk Test'" in hit.observed and "neutral-grotesque-low-contrast-high-xheight" in hit.observed
    assert "sans" in hit.observed and hit.refs == [hit.location["box"]]      # no local font names in the report


def test_rendered_family_region_resolves_hashed_loader_names(lazuli):
    doc = extract(family_page(("__Grotesk_Test_d65c78", {})))
    assert one_hit(lint("type.overused-neutral-grotesque", doc, lazuli=lazuli))


def test_rendered_family_region_applies_latin_regions_to_latin_text_only(lazuli):
    doc = extract(family_page(("Grotesk Test", {"script": "hang", "text": "한글 본문"})))
    no_hits(lint("type.overused-neutral-grotesque", doc, lazuli=lazuli))


def test_rendered_family_region_respects_role_filters(lazuli):
    no_hits(lint("type.costume-monospace", extract(family_page(("Mono Test", {"role": "code"}))), lazuli=lazuli))
    hit = one_hit(lint("type.costume-monospace", extract(family_page(("Mono Test", {"role": "heading"}))),
                       lazuli=lazuli))
    assert "monospaced-proportion" in hit.observed


def test_rendered_family_region_counts_italic_runs_only_when_included(lazuli):
    italic = ("Didone Test", {"role": "display", "size": 64, "style": "italic"})
    hit = one_hit(lint("type.serif-luxury-display", extract(family_page(italic)), lazuli=lazuli))
    assert "high-contrast-italic-display" in hit.observed
    no_hits(lint("type.serif-luxury-display", extract(family_page(italic)), lazuli=lazuli,
                 det={"params": {"roles": ["display"]}}))


def test_rendered_family_region_skips_unmeasured_families_and_without_a_database(lazuli):
    doc = extract(family_page(("Unmeasured Test", {}), ("Web Only Test", {})))
    skipped = lint("type.overused-neutral-grotesque", doc, lazuli=lazuli).skipped
    assert "'Unmeasured Test' is installed but not measured" in skipped
    assert "'Web Only Test' is not among the measured local fonts" in skipped
    assert "lazuli database" in lint("type.overused-neutral-grotesque", doc).skipped


def test_rendered_family_region_never_looks_up_a_generic_family(house_generics, lazuli):
    no_hits(lint("type.overused-neutral-grotesque",
                 extract(family_page((house_generics["generic"], {}), ("SYSTEM-UI", {}))), lazuli=lazuli))


def font_plan(locales: list[str], *roles: dict) -> dict:
    return {"brief": {"locales": locales}, "tokens": {"type": {"roles": list(roles)}}}


def test_plan_font_region_fires_on_a_planned_family_in_a_listed_region(lazuli):
    plan = font_plan(["en-US"], {"role": "body", "family": "Grotesk Test"}, {"role": "code", "family": "Mono Test"})
    hit = one_hit(lint("type.overused-neutral-grotesque", layer="plan", plan=plan, lazuli=lazuli))
    assert hit.observed.startswith("'Grotesk Test' (body) measures in the feature region")
    assert hit.location == {"path": "tokens.type.roles[*].family"}
    no_hits(lint("type.costume-monospace", layer="plan", plan=plan, lazuli=lazuli))   # code is not selected


def test_plan_font_region_uses_scripts_or_locales_for_scoped_regions(lazuli):
    korean = font_plan(["ko-KR"], {"role": "body", "family": "Grotesk Test"})
    no_hits(lint("type.overused-neutral-grotesque", layer="plan", plan=korean, lazuli=lazuli))
    latin_role = font_plan(["ko-KR"], {"role": "body", "family": "Grotesk Test", "scripts": ["hang", "latn"]})
    assert one_hit(lint("type.overused-neutral-grotesque", layer="plan", plan=latin_role, lazuli=lazuli))


def test_plan_font_region_skips_without_measurements(lazuli):
    plan = font_plan(["en"], {"role": "body", "family": "Web Only Test"})
    assert "Web Only Test" in lint("type.overused-neutral-grotesque", layer="plan", plan=plan, lazuli=lazuli).skipped
    assert "lazuli database" in lint("type.overused-neutral-grotesque", layer="plan", plan=plan).skipped
    assert lint("type.overused-neutral-grotesque", layer="plan").skipped == "no plan given"


def web_plan(*roles: dict, platform: tuple[str, ...] = ("web",)) -> dict:
    return {"brief": {"platform": list(platform), "locales": ["en-US"]}, "tokens": {"type": {"roles": list(roles)}}}


def test_plan_font_region_reports_no_face_chosen_when_every_text_role_is_a_platform_sans(lazuli):
    roles = ({"role": "heading", "family": "System-UI"}, {"role": "body", "family": "sans-serif"},
             {"role": "ui", "family": "-apple-system"}, {"role": "code", "family": "Unmeasured Test"})
    for given in ({}, {"lazuli": lazuli}):                       # nothing is measured, so no database is needed
        hit = one_hit(lint("type.overused-neutral-grotesque", layer="plan", plan=web_plan(*roles), **given))
        assert hit.observed.startswith("no face chosen: each platform substitutes its own sans")
        assert hit.evidence == "plan" and hit.location == {"path": "tokens.type.roles[*].family"}


def test_plan_font_region_does_not_report_a_missing_face_when_a_role_names_one(lazuli):
    system = {"role": "body", "family": "system-ui"}
    rule = "type.overused-neutral-grotesque"
    no_hits(lint(rule, layer="plan", plan=web_plan(system, {"role": "heading", "family": "Oldstyle Test"}),
                 lazuli=lazuli))
    no_hits(lint(rule, layer="plan", plan=web_plan(system, {"role": "ui", "family": "ui-monospace"}),
                 lazuli=lazuli))                                 # a generic keyword that is not a sans counts as no sans
    no_hits(lint(rule, layer="plan", plan=web_plan(system, platform=("ios", "android")), lazuli=lazuli))
    no_hits(lint(rule, layer="plan", plan=web_plan({"role": "code", "family": "system-ui"}), lazuli=lazuli))


def test_plan_font_region_never_looks_up_a_generic_family(lazuli):
    plan = web_plan({"role": "heading", "family": "system-ui"}, {"role": "body", "family": "monospace"})
    for rule in ("type.serif-luxury-display", "type.costume-monospace"):
        no_hits(lint(rule, layer="plan", plan=plan, lazuli=lazuli))


def test_plan_font_region_reads_the_platform_sans_names_from_the_font_table(house_generics, lazuli):
    rule = "type.overused-neutral-grotesque"
    plan = web_plan({"role": "body", "family": house_generics["sans"]}, {"role": "ui", "family": "SYSTEM-UI"})
    assert one_hit(lint(rule, layer="plan", plan=plan, lazuli=lazuli)).observed.startswith("no face chosen")
    no_hits(lint(rule, layer="plan", plan=web_plan({"role": "body", "family": house_generics["generic"]}),
                 lazuli=lazuli))                                 # generic, but not a sans: never looked up


def test_font_feature_regions_are_read_from_the_type_vocabulary(lazuli, tmp_path, monkeypatch):
    vocab = yaml.safe_load((shared_dir() / "vocab" / "type.yaml").read_text(encoding="utf-8"))
    region = next(r for r in vocab["font_feature_regions"] if r["id"] == "neutral-grotesque-low-contrast-high-xheight")
    region["when"]["x_height_size"] = "small"                    # a definition Grotesk Test no longer meets
    shared = tmp_path / "shared"
    for rel, text in (("plan/schema.yaml", (shared_dir() / "plan" / "schema.yaml").read_text(encoding="utf-8")),
                      ("fonts/system-fonts.yaml", (shared_dir() / "fonts" / "system-fonts.yaml").read_text(encoding="utf-8")),
                      ("vocab/type.yaml", yaml.safe_dump(vocab, allow_unicode=True))):
        (shared / rel).parent.mkdir(parents=True, exist_ok=True)
        (shared / rel).write_text(text, encoding="utf-8")
    doc = extract(family_page(("Grotesk Test", {})))
    plan = font_plan(["en-US"], {"role": "body", "family": "Grotesk Test"})
    assert one_hit(lint("type.overused-neutral-grotesque", doc, lazuli=lazuli))
    monkeypatch.setenv("LAPIS_SHARED", str(shared))
    no_hits(lint("type.overused-neutral-grotesque", doc, lazuli=lazuli))
    no_hits(lint("type.overused-neutral-grotesque", layer="plan", plan=plan, lazuli=lazuli))


# ---------------------------------------------------------------- contrast

def contrast_page(theme: str = "light", **fields) -> Page:
    page = Page(theme=theme)
    page.run(page.box("text", (0, 0, 600, 40)), "Muted note", **fields)
    return page


GRAY = [0.7, 0.0, 0.0]                      # about 2.6:1 on white


def test_text_contrast_fires_below_the_normal_bound_and_passes_large_text_above_its_bound():
    hit = one_hit(lint("color.text-contrast", extract(contrast_page(color=GRAY, backdrop={"oklch": WHITE}))))
    assert "normal text 'Muted note' has contrast" in hit.observed and "below 4.5:1" in hit.observed
    mid = [0.62, 0.0, 0.0]                   # about 3.4:1 on white
    no_hits(lint("color.text-contrast", extract(contrast_page(color=mid, size=24, backdrop={"oklch": WHITE}))))
    assert one_hit(lint("color.text-contrast", extract(contrast_page(color=mid, size=18, backdrop={"oklch": WHITE}))))


def test_text_contrast_uses_the_worst_backdrop_and_composites_translucent_text():
    worst = {"oklch": WHITE, "worst": [0.55, 0.0, 0.0]}
    assert one_hit(lint("color.text-contrast", extract(contrast_page(color=BLACK[:3], backdrop=worst))))
    faint = BLACK + [0.3]                    # black at 30 % reads as light gray on white
    assert one_hit(lint("color.text-contrast", extract(contrast_page(color=faint, backdrop={"oklch": WHITE}))))
    no_hits(lint("color.text-contrast", extract(contrast_page(color=BLACK, backdrop={"oklch": WHITE}))))


def test_text_contrast_checks_hover_and_excludes_disabled_controls():
    page = Page(theme="dark")
    button = page.box("button", (0, 0, 120, 40), a11y={"focusable": True})
    page.run(button, "Save", role="ui", color=WHITE, backdrop={"oklch": [0.3, 0.0, 0.0]},
             states={"hover": {"color": WHITE, "backdrop": [0.9, 0.0, 0.0]}})
    disabled = page.box("button", (0, 50, 120, 40), a11y={"disabled": True})
    page.run(disabled, "Off", role="ui", color=[0.5, 0.0, 0.0], backdrop={"oklch": [0.4, 0.0, 0.0]})
    hit = one_hit(lint("color.text-contrast", extract(page)))
    assert "on hover" in hit.observed and "1440 px dark" in hit.observed


def test_text_contrast_skips_runs_without_a_measured_backdrop():
    assert "backdrop" in lint("color.text-contrast", extract(contrast_page(color=GRAY))).skipped


def test_gray_on_color_fires_on_neutral_gray_over_a_chromatic_surface():
    blue = {"oklch": [0.55, 0.15, 260], "kind": "solid"}
    hit = one_hit(lint("color.gray-on-color", extract(contrast_page(color=[0.6, 0.01, 0], backdrop=blue))))
    assert "gray text 'Muted note'" in hit.observed
    no_hits(lint("color.gray-on-color", extract(contrast_page(color=WHITE, backdrop=blue))))
    no_hits(lint("color.gray-on-color", extract(contrast_page(color=[0.6, 0.01, 0], backdrop={"oklch": WHITE}))))


# ---------------------------------------------------------------- targets

def target_page(*targets: tuple[str, tuple, dict]) -> Page:
    page = Page(390, 844)
    section = page.box("section", (0, 0, 390, 844))
    for role, rect, fields in targets:
        fields = dict(fields)
        text = fields.pop("text", None)
        box = page.box(role, rect, section, **fields)
        if text:
            page.run(box, text, role="ui")
    return page


FOCUSABLE = {"a11y": {"focusable": True}}


def test_small_target_fires_when_its_circle_overlaps_a_neighbour():
    page = target_page(("button", (10, 10, 16, 16), {**FOCUSABLE, "text": "x"}),
                       ("button", (28, 10, 80, 32), {**FOCUSABLE, "text": "Menu"}))
    hit = one_hit(lint("component.small-target", extract(page)))
    assert "16 x 16 px" in hit.observed and "'Menu'" in hit.observed and hit.evidence == "measurement"


def test_small_target_passes_spaced_or_full_size_targets():
    spaced = target_page(("button", (10, 10, 16, 16), FOCUSABLE), ("button", (100, 10, 80, 32), FOCUSABLE))
    no_hits(lint("component.small-target", extract(spaced)))
    tangent = target_page(("button", (10, 10, 16, 16), FOCUSABLE), ("button", (30, 10, 80, 32), FOCUSABLE))
    no_hits(lint("component.small-target", extract(tangent)))       # the 24 px circle only reaches its edge
    full = target_page(("button", (10, 10, 24, 24), FOCUSABLE), ("button", (36, 10, 80, 32), FOCUSABLE))
    no_hits(lint("component.small-target", extract(full)))


def test_small_target_excludes_links_in_running_text_and_marks_equivalents_as_leads():
    def links(sentence: str | None) -> dict:
        page = Page(390, 844)
        para = page.box("text", (0, 0, 390, 40))
        if sentence:
            page.run(para, sentence)
        page.box("link", (60, 4, 16, 16), para, **FOCUSABLE)
        page.box("link", (78, 4, 16, 16), para, **FOCUSABLE)
        return extract(page)

    no_hits(lint("component.small-target", links("Read the terms and the policy first.")))
    assert len(lint("component.small-target", links(None)).hits) == 2
    lead = target_page(("button", (10, 10, 16, 16), {"a11y": {"focusable": True, "name": "Close"}}),
                       ("button", (28, 10, 80, 32), {"a11y": {"focusable": True, "name": "Close"}}))
    assert one_hit(lint("component.small-target", extract(lead))).evidence == "not-verified"


# ---------------------------------------------------------------- overflow

def test_compact_overflow_reports_sideways_scroll_at_compact_widths():
    page = Page(320, 568, scroll_width=412)
    wide = page.box("card", (0, 0, 412, 100))
    hit = one_hit(lint("layout.compact-overflow", extract(page)))
    assert "412 px wide in a 320 px viewport" in hit.observed and hit.location["box"] == wide
    fits = Page(320, 568, scroll_width=320)
    fits.box("card", (0, 0, 320, 100), clipped="none")
    no_hits(lint("layout.compact-overflow", extract(fits)))


def test_compact_overflow_reports_text_cut_by_hidden_overflow_but_not_deliberate_truncation():
    page = Page(390, 844, scroll_width=390)
    cut = page.box("card", (0, 0, 200, 40), clipped="overflow")
    page.run(cut, "A label that is much too long for its box")
    ellipsis = page.box("card", (0, 50, 200, 40), clipped="ellipsis")
    page.run(ellipsis, "Deliberately truncated text")
    hit = one_hit(lint("layout.compact-overflow", extract(page)))
    assert hit.location["box"] == cut and "cut off" in hit.observed


def test_compact_overflow_reports_overlapping_controls():
    page = Page(390, 844, scroll_width=390)
    page.box("button", (0, 0, 120, 40), clipped="none")
    page.box("link", (100, 10, 120, 40), clipped="none")
    assert "overlaps" in one_hit(lint("layout.compact-overflow", extract(page))).observed


def test_compact_overflow_skips_without_a_compact_capture():
    assert "320, 390 px" in lint("layout.compact-overflow", extract(Page(1440, 900, scroll_width=1440))).skipped


def test_mobile_100vh_fires_on_controls_hidden_by_browser_ui():
    page = Page(390, 664, browser_chrome=True)
    shell = page.box("section", (0, 0, 390, 844))
    page.box("button", (20, 780, 350, 44), shell, **FOCUSABLE)
    hit = one_hit(lint("code.mobile-100vh", extract(Page(390, 844, scroll_width=390), page)))
    assert "below the 664 px" in hit.observed and hit.location["box"] == shell
    fits = Page(390, 664, browser_chrome=True)
    shell = fits.box("section", (0, 0, 390, 844))
    fits.box("button", (20, 500, 350, 44), shell)
    no_hits(lint("code.mobile-100vh", extract(fits)))


def test_mobile_100vh_skips_without_a_browser_ui_capture():
    assert "browser-UI" in lint("code.mobile-100vh", extract(Page(390, 844))).skipped


# ---------------------------------------------------------------- occlusion

def occlusion_page(layer_order: int, **layer: dict) -> Page:
    page = Page()
    heading = page.box("heading", (0, 0, 400, 100), paint_order=2)
    page.run(heading, "Hidden headline", role="heading", size=48)
    page.box(layer.pop("role", "media"), (0, 0, 400, 60), paint_order=layer_order, **layer)
    return page


def test_occluded_text_fires_when_an_opaque_layer_is_painted_over_text():
    hit = one_hit(lint("layout.occluded-text", extract(occlusion_page(5, media={"kind": "img", "loaded": True}))))
    assert "60% covered" in hit.observed
    assert one_hit(lint("layout.occluded-text", extract(occlusion_page(5, role="card",
                                                                       style={"background": [0.2, 0.02, 250]}))))


def test_occluded_text_passes_layers_below_the_text_or_without_paint():
    no_hits(lint("layout.occluded-text", extract(occlusion_page(1, media={"kind": "img", "loaded": True}))))
    no_hits(lint("layout.occluded-text", extract(occlusion_page(5, role="card"))))
    no_hits(lint("layout.occluded-text", extract(occlusion_page(5, role="card",
                                                                style={"background": [0.2, 0.02, 250, 0.2]}))))


def test_occluded_text_skips_without_paint_order():
    page = Page()
    page.run(page.box("heading", (0, 0, 400, 100)), "Headline", role="heading")
    assert "paint order" in lint("layout.occluded-text", extract(page)).skipped
