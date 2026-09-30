"""Layout detectors of slop_lint (cli/lapis_design/lint/detectors/render_layout.py), run through the
registry with the shipped rules. Fixtures are small extracts and sessions that validate against
their schemas."""
from __future__ import annotations

import copy

import pytest
import yaml
from jsonschema import Draft202012Validator

from lapis_design import shared_dir
from lapis_design.lint.detectors import render_layout  # noqa: F401  (registers the detectors)
from lapis_design.lint.types import DETECTORS, Context

SHARED = shared_dir()
RULES = yaml.safe_load((SHARED / "slop" / "rules.yaml").read_text(encoding="utf-8"))
EXTRACT = Draft202012Validator(yaml.safe_load((SHARED / "render" / "extract.schema.yaml").read_text(encoding="utf-8")))
SESSION = Draft202012Validator(yaml.safe_load((SHARED / "behavior" / "session.schema.yaml").read_text(encoding="utf-8")))
HEIGHT = {320: 568, 390: 844, 768: 1024, 1440: 900}
BORDER = {"border_px": 1, "border_color": [0.8, 0.0, 0.0]}


# ---------------------------------------------------------------- builders

def bid(n: int) -> str:
    return f"b{n:012x}"


def box(n, role, x, y, w, h, parent=None, **extra):
    return {"id": bid(n), "parent": None if parent is None else bid(parent), "role": role,
            "role_confidence": 0.9, "rect": {"x": x, "y": y, "w": w, "h": h}, **extra}


def run(n, box_n, text, type_role="body", size=16, **extra):
    return {"id": f"t{n}", "box": bid(box_n), "text": text, "chars": sum(not c.isspace() for c in text),
            "script": "latn", "type_role": type_role, "font": {"requested": "Inter", "rendered": "Inter"},
            "size_px": size, **extra}


def viewport(width, boxes=(), text=(), derived=None, **extra):
    vp = {"width": width, "height": HEIGHT[width], "theme": "light", "boxes": list(boxes), "text": list(text),
          **extra}
    if derived is not None:
        vp["derived"] = derived
    return vp


def extract(*viewports):
    doc = {"version": 1,
           "meta": {"extractor": {"name": "render_check", "version": "test"}, "generated_at": "2026-09-26T00:00:00Z"},
           "source": {"kind": "render", "task": "demo"}, "viewports": list(viewports)}
    errors = list(EXTRACT.iter_errors(doc))
    assert not errors, errors[0].message
    return doc


def session(probes, coverage=None):
    doc = {"version": 0,
           "meta": {"driver": {"name": "behavior_check", "version": "test"}, "generated_at": "2026-09-26T00:00:00Z",
                    "backend": "stub"},
           "source": {"kind": "render", "url": "http://127.0.0.1:8000/", "task": "demo"},
           "contexts": [{"id": "m", "width": 390, "height": 844, "theme": "light", "pointer": "coarse",
                         "network": "normal"},
                        {"id": "d", "width": 1440, "height": 900, "theme": "light", "pointer": "fine",
                         "network": "normal"}],
           "nodes": {bid(n): {"role": "other"} for n in range(1, 40)},
           "probes": probes,
           "coverage": coverage if coverage is not None else [{"probe": p, "status": "ran"} for p in probes]}
    errors = list(SESSION.iter_errors(doc))
    assert not errors, errors[0].message
    return doc


def lint(rule_id, layer="render", *, threshold=None, params=None, **inputs):
    rule = copy.deepcopy(next(r for r in RULES["rules"] if r["id"] == rule_id))
    det = rule["detect"][layer]
    if threshold:
        det.setdefault("threshold", {}).update(threshold)
    if params:
        det.setdefault("params", {}).update(params)
    return DETECTORS[det["detector"]].fn(Context(rules=RULES, **inputs), det, rule, layer)


def observed(result):
    assert result.skipped is None, result.skipped
    return [hit.observed for hit in result.hits]

def test_label_persistence_needs_behavior_layer():
    rule = next(r for r in RULES["rules"] if r["id"] == "component.unlabeled-input")
    result = render_layout.accessibility_tree(
        Context(rules=RULES, extract=extract(viewport(390))),
        rule["detect"]["behavior"], rule, "render")
    assert result.skipped == "label persistence is observed only in the behavior session"
    assert result.cause == "layer"


# ---------------------------------------------------------------- template-repetition

def icon_section(n, y, heading_first=False):
    section = box(n, "section", 0, y, 390, 300)
    tile = box(n + 1, "other", 20, y + 20, 48, 48, parent=n, style={"background": [0.9, 0.05, 250]})
    icon = box(n + 2, "icon", 32, y + 32, 24, 24, parent=n + 1, icon={"kind": "svg"})
    heading = box(n + 3, "heading", 20, y + 84, 350, 32, parent=n)
    text = box(n + 4, "text", 20, y + 132, 350, 60, parent=n)
    if heading_first:
        heading["rect"]["y"], tile["rect"]["y"], icon["rect"]["y"] = y + 20, y + 68, y + 80
        return [section, heading, tile, icon, text]
    return [section, tile, icon, heading, text]


def icon_sections(*heading_first):
    boxes, sections = [], []
    for index, first in enumerate(heading_first):
        n = 1 + index * 5
        boxes += icon_section(n, index * 300, first)
        sections.append({"box": bid(n), "archetype": "feature-grid"})
    return extract(viewport(390, boxes, derived={"sections": sections}))


def test_template_repetition_fires_when_more_consecutive_sections_than_bound_open_with_pattern():
    hits = lint("type.icon-tile-heading", extract=icon_sections(False, False, False)).hits
    assert len(hits) == 1
    assert "3 consecutive sections open with stacked icon > heading > text" in hits[0].observed
    assert hits[0].location == {"viewport": 390, "box": bid(1)}


def test_template_repetition_allows_repeats_up_to_the_bound():
    assert observed(lint("type.icon-tile-heading", extract=icon_sections(False, False))) == []
    assert observed(lint("type.icon-tile-heading", extract=icon_sections(False, True, False))) == []


def test_template_repetition_skips_without_sections():
    result = lint("type.icon-tile-heading", extract=extract(viewport(390, icon_section(1, 0))))
    assert "derived.sections" in result.skipped


def zigzag(sides):
    boxes, text = [], []
    for i, side in enumerate(sides):
        y = 100 + i * 600
        media_x, text_x = (100, 760) if side == "left" else (740, 100)
        boxes += [box(10 + i, "media", media_x, y, 600, 400, media={"kind": "img", "loaded": True}),
                  box(20 + i, "heading", text_x, y + 150, 580, 100)]
        text.append(run(i, 20 + i, f"Idea {i}", "heading", 32))
    return extract(viewport(1440, boxes, text))


def test_zigzag_counts_rows_whose_media_alternates_sides():
    hits = lint("layout.zigzag", extract=zigzag(["left", "right", "left"])).hits
    assert len(hits) == 1 and "alternate sides in 3 consecutive rows" in hits[0].observed
    assert observed(lint("layout.zigzag", extract=zigzag(["left", "right"]))) == []
    assert observed(lint("layout.zigzag", extract=zigzag(["left", "left", "left"]))) == []


# ---------------------------------------------------------------- section-sequence

def sequence(*archetypes):
    return extract(viewport(1440, derived={"section_sequence": list(archetypes)}))


def test_section_sequence_hits_a_landing_template_and_ignores_the_footer():
    hits = lint("layout.template-section-sequence",
                extract=sequence("hero", "feature-grid", "pricing", "cta", "footer")).hits
    assert len(hits) == 1 and "hero > feature-grid > pricing > cta" in hits[0].observed
    assert observed(lint("layout.template-section-sequence",
                         extract=sequence("hero", "other", "other", "faq", "footer"))) == []


def test_section_sequence_max_distance_is_the_allowed_edge():
    near = sequence("hero", "feature-grid", "pricing", "other")        # 1 edit of 4 = 0.25
    assert lint("layout.template-section-sequence", params={"max_distance": 0.25}, extract=near).hits
    assert observed(lint("layout.template-section-sequence", params={"max_distance": 0.24}, extract=near)) == []


def test_section_sequence_skips_without_a_sequence():
    assert lint("layout.template-section-sequence", extract=extract(viewport(1440))).skipped


# ---------------------------------------------------------------- section-inventory

def hero(extra_boxes=(), extra_text=(), height=900):
    boxes = [box(1, "section", 0, 0, 1440, height), box(2, "heading", 200, 200, 1040, 80, parent=1),
             box(3, "text", 200, 300, 1040, 60, parent=1), box(4, "button", 200, 400, 200, 48, parent=1),
             *extra_boxes]
    text = [run(1, 2, "Fire once a month", "display", 56), run(2, 3, "Pieces from this firing"),
            run(3, 4, "Reserve", "ui"), *extra_text]
    return extract(viewport(1440, boxes, text, derived={"sections": [{"box": bid(1), "archetype": "hero"}]}))


def test_proof_in_hero_counts_logo_rows_and_metrics_in_the_first_section():
    logos = [box(10 + i, "media", 200 + i * 150, 700, 100, 32, parent=1, media={"kind": "img", "loaded": True})
             for i in range(5)]
    metrics = [box(20, "text", 200, 600, 120, 40, parent=1), box(21, "text", 400, 600, 120, 40, parent=1)]
    hits = lint("layout.crowded-hero", extract=hero([*logos, *metrics],
                                                    [run(20, 20, "10,000+"), run(21, 21, "99.9%")])).hits
    assert len(hits) == 1
    assert "a row of 5 logos and 2 metrics" in hits[0].observed
    assert observed(lint("layout.crowded-hero", extract=hero())) == []


def test_task_below_ornament_hits_an_action_pushed_below_the_first_viewport_by_ornament():
    def page(button_y, opening="media"):
        opener = (box(2, "media", 0, 0, 390, min(900, button_y - 20), parent=1, media={"kind": "img", "loaded": True})
                  if opening == "media" else box(2, "text", 20, 20, 350, button_y - 40, parent=1))
        boxes = [box(1, "section", 0, 0, 390, 1800), opener, box(3, "button", 20, button_y, 350, 48, parent=1)]
        text = [run(1, 3, "Reserve", "ui")] + ([run(2, 2, "A long essay about the firing.")] if opening == "text" else [])
        return extract(viewport(390, boxes, text, derived={"sections": [{"box": bid(1), "archetype": "hero"}]}))
    hits = lint("layout.decorative-opening-stack", extract=page(1000)).hits
    assert len(hits) == 1 and "starts at 1000 px, below the 844 px reach, under 1 media box" in hits[0].observed
    assert hits[0].location["box"] == bid(3)
    assert observed(lint("layout.decorative-opening-stack", extract=page(500))) == []
    assert observed(lint("layout.decorative-opening-stack", extract=page(1000, opening="text"))) == []


def test_section_inventory_skips_without_sections():
    assert lint("layout.crowded-hero", extract=extract(viewport(1440))).skipped


# ---------------------------------------------------------------- sibling-identity

def tiers(similarity):
    boxes = [box(1, "section", 0, 0, 1440, 900)]
    text = []
    for i, name in enumerate(["Starter plan", "Pro plan", "Team plan"]):
        boxes += [box(2 + i, "card", 100 + i * 420, 100, 400, 600, parent=1, style=BORDER),
                  box(10 + i, "text", 120 + i * 420, 120, 360, 40, parent=2 + i)]
        text.append(run(i, 10 + i, name))
    group = {"parent": bid(1), "members": [bid(2), bid(3), bid(4)], "similarity": similarity}
    return extract(viewport(1440, boxes, text, derived={"sibling_groups": [group]}))


def plan(priority=None, **extra):
    layout = {"procedure": {"priority": priority} if priority is not None else {}}
    return {"layout": layout, **extra}


def test_equal_siblings_hit_when_the_plan_ranks_members_differently():
    hits = lint("layout.equal-siblings", extract=tiers(0.95), plan=plan(["Pro plan", "Starter plan"])).hits
    assert len(hits) == 1 and "0.95 similar though the plan ranks them differently" in hits[0].observed
    assert hits[0].location["box"] == bid(1)


def test_equal_siblings_similarity_max_is_the_allowed_edge():
    assert observed(lint("layout.equal-siblings", extract=tiers(0.9), plan=plan(["Pro plan", "Starter plan"]))) == []


def test_equal_siblings_skip_when_the_plan_cannot_rank_the_members():
    assert "needs the plan" in lint("layout.equal-siblings", extract=tiers(0.95)).skipped
    assert "priority" in lint("layout.equal-siblings", extract=tiers(0.95), plan=plan()).skipped
    unmatched = lint("layout.equal-siblings", extract=tiers(0.95), plan=plan(["gallery"]))
    assert "distinct entries" in unmatched.skipped
    assert "sibling_groups" in lint("layout.equal-siblings", extract=extract(viewport(1440)), plan=plan()).skipped


# ---------------------------------------------------------------- card-nesting

def nested_cards(depth=None, style=True):
    s = {"style": BORDER} if style else {}
    boxes = [box(1, "card", 16, 100, 358, 400, **s), box(2, "card", 32, 120, 326, 200, parent=1, **s),
             box(3, "text", 48, 140, 294, 60, parent=2)]
    derived = {"card_nesting_max": depth} if depth is not None else None
    return extract(viewport(390, boxes, [run(1, 3, "Glaze notes")], derived=derived))


def test_nested_cards_hit_above_depth_max_at_the_innermost_card():
    hits = lint("layout.nested-cards", extract=nested_cards(2)).hits
    assert len(hits) == 1 and "depth 2" in hits[0].observed and hits[0].location["box"] == bid(2)
    assert observed(lint("layout.nested-cards", extract=nested_cards(1))) == []


def test_nested_cards_measure_boxes_when_derived_value_is_missing_and_skip_without_styles():
    assert len(lint("layout.nested-cards", extract=nested_cards()).hits) == 1
    assert lint("layout.nested-cards", extract=nested_cards(style=False)).skipped


def test_card_share_compares_content_inside_cards_with_all_content():
    inside = [box(1, "card", 16, 100, 358, 300, style=BORDER), box(2, "text", 32, 120, 326, 260, parent=1)]
    outside = [box(3, "text", 16, 450, 358, 300)]
    text = [run(1, 2, "Inside"), run(2, 3, "Outside")]
    assert len(lint("layout.card-everything", extract=extract(viewport(390, inside, text[:1]))).hits) == 1
    assert observed(lint("layout.card-everything", extract=extract(viewport(390, inside + outside, text)))) == []


# ---------------------------------------------------------------- grid-filler

def bento(empty_cells):
    cells = [(100, 100), (740, 100), (100, 440), (740, 440)]
    boxes = [box(1, "section", 0, 0, 1440, 900)]
    text = []
    for i, (x, y) in enumerate(cells):
        boxes.append(box(2 + i, "card", x, y, 600, 300, parent=1, style=BORDER))
        if i >= len(cells) - empty_cells:
            gradient = {"target": "background", "kind": "linear", "stops": [{"oklch": [0.7, 0.1, 30]},
                                                                           {"oklch": [0.6, 0.1, 280]}]}
            boxes.append(box(20 + i, "other", x + 20, y + 20, 560, 260, parent=2 + i, style={"gradients": [gradient]}))
        else:
            boxes.append(box(10 + i, "text", x + 20, y + 20, 560, 40, parent=2 + i))
            text.append(run(i, 10 + i, f"Firing step {i}"))
    return extract(viewport(1440, boxes, text))


def test_bento_filler_hits_the_exceptional_grid_cell_without_content():
    hits = lint("layout.bento-filler", extract=bento(1)).hits
    assert len(hits) == 1 and hits[0].location["box"] == bid(5)
    assert observed(lint("layout.bento-filler", extract=bento(0))) == []
    assert observed(lint("layout.bento-filler", extract=bento(2))) == []     # half empty: a pattern, not filler


# ---------------------------------------------------------------- gap-proximity

def heading_gaps(above, below, eyebrow=False):
    boxes = [box(1, "text", 16, 100, 358, 100)]
    text = [run(1, 1, "Previous paragraph")]
    heading_y = 200 + above
    if eyebrow:
        boxes.append(box(4, "text", 16, heading_y, 200, 16))
        text.append(run(4, 4, "STEP ONE", "label", 12))
        heading_y += 24
    boxes += [box(2, "heading", 16, heading_y, 358, 40), box(3, "text", 16, heading_y + 40 + below, 358, 100)]
    text += [run(2, 2, "Firing", "heading", 28), run(3, 3, "Next paragraph")]
    return extract(viewport(390, boxes, text))


def test_heading_proximity_hits_when_space_above_is_not_larger_than_below():
    hits = lint("layout.heading-proximity", extract=heading_gaps(10, 20)).hits
    assert len(hits) == 1 and "10 px above and 20 px below" in hits[0].observed
    assert observed(lint("layout.heading-proximity", extract=heading_gaps(48, 16))) == []


def test_heading_proximity_measures_above_an_eyebrow_label():
    assert observed(lint("layout.heading-proximity", extract=heading_gaps(48, 16, eyebrow=True))) == []


def gaps(level_ratio=None):
    value = {"inside_group": {"median": 16}, "between_sections": {"median": 24}}
    if level_ratio is not None:
        value["level_ratio"] = level_ratio
    return extract(viewport(1440, derived={"gaps": value}))


def test_monotonous_spacing_level_ratio_min_is_the_allowed_edge():
    assert len(lint("layout.monotonous-spacing", extract=gaps(1.2)).hits) == 1
    assert observed(lint("layout.monotonous-spacing", extract=gaps(1.5))) == []
    assert "level_ratio is omitted" in lint("layout.monotonous-spacing", extract=gaps()).skipped


# ---------------------------------------------------------------- symmetry

def symmetry_page(value):
    return extract(viewport(1440, derived={"symmetry": value}))


def test_symmetry_excess_max_is_the_allowed_edge():
    assert "symmetry 0.90" in lint("layout.symmetry-excess", extract=symmetry_page(0.9)).hits[0].observed
    assert observed(lint("layout.symmetry-excess", extract=symmetry_page(0.85))) == []
    assert lint("layout.symmetry-excess", extract=extract(viewport(1440))).skipped


def hero_shape(shape):
    content = {
        "centered": [box(2, "heading", 320, 200, 800, 80, parent=1), box(3, "text", 420, 300, 600, 60, parent=1),
                     box(4, "button", 640, 400, 160, 48, parent=1)],
        "split": [box(2, "heading", 100, 200, 560, 80, parent=1), box(3, "text", 100, 300, 560, 100, parent=1),
                  box(4, "media", 780, 150, 560, 400, parent=1, media={"kind": "img", "loaded": True})],
        "left": [box(2, "heading", 100, 200, 700, 80, parent=1), box(3, "text", 100, 300, 600, 60, parent=1),
                 box(4, "button", 100, 400, 160, 48, parent=1)],
    }[shape]
    return extract(viewport(1440, [box(1, "section", 0, 0, 1440, 800), *content],
                            [run(1, 2, "Fire once a month", "display", 56), run(2, 3, "Pieces")],
                            derived={"sections": [{"box": bid(1), "archetype": "hero"}]}))


def test_hero_shell_hits_centered_and_even_split_heroes_when_the_plan_ranks_nothing():
    centered = lint("layout.hero-before-priority", extract=hero_shape("centered"), plan=plan()).hits
    assert len(centered) == 1 and "centered at 1440 px" in centered[0].observed
    split = lint("layout.hero-before-priority", extract=hero_shape("split"), plan=plan()).hits
    assert len(split) == 1 and "split-50-50" in split[0].observed
    assert observed(lint("layout.hero-before-priority", extract=hero_shape("left"), plan=plan())) == []


def test_hero_shell_passes_a_plan_with_priorities_and_skips_without_a_plan():
    assert observed(lint("layout.hero-before-priority", extract=hero_shape("centered"),
                         plan=plan(["pieces", "reservation"]))) == []
    assert "needs the plan" in lint("layout.hero-before-priority", extract=hero_shape("centered")).skipped


def test_hero_shell_skips_a_hero_whose_placement_cannot_be_read():
    page = extract(viewport(1440, [box(1, "section", 0, 0, 1440, 800),
                                   box(2, "media", 0, 0, 1440, 800, parent=1, media={"kind": "img", "loaded": True})],
                            derived={"sections": [{"box": bid(1), "archetype": "hero"}]}))
    assert "placement" in lint("layout.hero-before-priority", extract=page, plan=plan()).skipped


# ---------------------------------------------------------------- reading-path

def heading_and_intro(intro_rect):
    boxes = [box(1, "heading", 100, 100, 400, 80), box(2, "text", *intro_rect)]
    return extract(viewport(1440, boxes, [run(1, 1, "Why one firing", "heading", 40),
                                          run(2, 2, "Each month the kiln is fired once.")]))


def test_split_heading_hits_an_intro_in_another_column():
    hits = lint("layout.split-heading", extract=heading_and_intro((600, 100, 700, 200))).hits
    assert len(hits) == 1 and hits[0].location["box"] == bid(1)
    assert observed(lint("layout.split-heading", extract=heading_and_intro((100, 200, 700, 100)))) == []


# ---------------------------------------------------------------- edge-inset

def edge(x, w, **extra):
    return extract(viewport(390, [box(1, "card", x, 100, w, 200, style=BORDER), *extra.get("more", ())]))


def test_edge_flush_inset_px_min_is_the_allowed_edge():
    hits = lint("layout.edge-flush", extract=edge(4, 370)).hits
    assert len(hits) == 1 and "4 px from the left" in hits[0].observed
    assert observed(lint("layout.edge-flush", extract=edge(12, 366))) == []
    assert observed(lint("layout.edge-flush", extract=edge(0, 390))) == []       # full-bleed


def test_edge_flush_reads_scroller_item_insets():
    scroller = box(2, "list", 0, 400, 390, 200, style={"background": [0.95, 0.0, 0.0]},
                   scroll={"axis": "x", "items": 6, "inset_start_px": 0, "inset_end_px": 16})
    hits = lint("layout.edge-flush", extract=edge(16, 358, more=[scroller])).hits
    assert [h.location["box"] for h in hits] == [bid(2)] and "0 px from its start edge" in hits[0].observed


def test_edge_flush_skips_without_the_requested_width():
    assert "390 px" in lint("layout.edge-flush", extract=extract(viewport(1440, [box(1, "card", 0, 0, 10, 10)]))).skipped


# ---------------------------------------------------------------- responsive-structure

def columns(narrow_rects):
    wide = [box(1, "section", 0, 0, 1440, 600)] + [box(2 + i, "text", x, 100, 400, 200, parent=1)
                                                    for i, x in enumerate((60, 520, 980))]
    narrow = [box(1, "section", 0, 0, 390, 1200)] + [box(2 + i, "text", *r, parent=1)
                                                      for i, r in enumerate(narrow_rects)]
    text = [run(i, 2 + i, f"Column {i}") for i in range(3)]
    sections = {"sections": [{"box": bid(1), "archetype": "feature-grid"}]}
    return extract(viewport(390, narrow, text), viewport(1440, wide, text, derived=sections))


def test_shrunk_desktop_hits_columns_that_only_scale_down():
    scaled = [(16.25, 100, 108.3, 300), (140.8, 100, 108.3, 300), (265.4, 100, 108.3, 300)]
    hits = lint("layout.shrunk-desktop", extract=columns(scaled)).hits
    assert len(hits) == 1 and "3 of 3 side-by-side boxes" in hits[0].observed
    assert hits[0].location == {"viewport": 390, "box": bid(1)}
    stacked = [(16, 100, 358, 200), (16, 320, 358, 200), (16, 540, 358, 200)]
    assert observed(lint("layout.shrunk-desktop", extract=columns(stacked))) == []


def test_shrunk_desktop_skips_without_both_widths():
    assert "390" in lint("layout.shrunk-desktop", extract=extract(viewport(1440))).skipped


# ---------------------------------------------------------------- signature-present

def test_missing_signature_merges_widths_and_reads_only_light_full_motion_captures():
    page = extract(viewport(390, derived={"signature_found": False}),
                   viewport(390, derived={"signature_found": True}, theme="dark"),
                   viewport(1440, derived={"signature_found": False}))
    hits = lint("layout.missing-signature", extract=page, plan={"layout": {"signature": "firing log row"}}).hits
    assert len(hits) == 1
    assert "'firing log row' is not found" in hits[0].observed and "(at 390, 1440 px)" in hits[0].observed
    found = extract(viewport(390, derived={"signature_found": True}))
    assert observed(lint("layout.missing-signature", extract=found)) == []
    assert lint("layout.missing-signature", extract=extract(viewport(390))).skipped

def test_signature_text_only_evidence_is_skipped_without_missing_widths():
    page = extract(viewport(390, derived={"signature_found": True, "signature_evidence": "not-verified"}),
                   viewport(1440, derived={"signature_found": True, "signature_evidence": "verified"}))
    result = lint("layout.missing-signature", extract=page)
    assert result.hits == []
    assert result.skipped == "signature found by text only; not verified"


def test_signature_mixed_widths_report_only_missing_widths_even_with_text_only_evidence():
    page = extract(viewport(320, derived={"signature_found": True, "signature_evidence": "not-verified"}),
                   viewport(390, derived={"signature_found": False}),
                   viewport(768, derived={"signature_found": True, "signature_evidence": "verified"}),
                   viewport(1440, derived={"signature_found": False}))
    result = lint("layout.missing-signature", extract=page)
    assert result.skipped is None
    assert len(result.hits) == 1
    assert "(at 390, 1440 px)" in result.hits[0].observed
    assert "320" not in result.hits[0].observed


def test_signature_old_extract_without_evidence_still_passes_found_widths():
    result = lint("layout.missing-signature", extract=extract(viewport(390, derived={"signature_found": True})))
    assert result.hits == [] and result.skipped is None


# ---------------------------------------------------------------- large-list

def test_unvirtualized_list_rendered_items_max_is_the_allowed_edge():
    def page(items):
        return extract(viewport(1440, [box(1, "list", 0, 0, 800, 600, scroll={"axis": "y", "items": items})]))
    hits = lint("code.unvirtualized-list", extract=page(501)).hits
    assert len(hits) == 1 and "renders 501 items" in hits[0].observed
    assert observed(lint("code.unvirtualized-list", extract=page(500))) == []


# ---------------------------------------------------------------- decorative-dom

def app_window(dot_role="other"):
    boxes = [box(1, "other", 200, 100, 800, 500, style={"background": [0.2, 0.0, 0.0], "radius_px": 12}),
             box(2, "other", 200, 100, 800, 36, parent=1, style={"background": [0.3, 0.0, 0.0]})]
    for i, hue in enumerate((25, 90, 145)):
        boxes.append(box(3 + i, dot_role, 216 + i * 20, 112, 12, 12, parent=2,
                         style={"background": [0.7, 0.15, hue], "radius_px": 6}))
    boxes.append(box(6, "text", 220, 160, 700, 300, parent=1))
    return extract(viewport(1440, boxes, [run(1, 6, "const firing = 1")]))


def test_fake_app_window_hits_css_window_dots():
    hits = lint("component.fake-app-window", extract=app_window()).hits
    assert len(hits) == 1 and hits[0].location["box"] == bid(1)
    assert observed(lint("component.fake-app-window", extract=app_window("button"))) == []


def test_fake_app_window_hits_textless_bars():
    bars = [box(2 + i, "other", 120, 120 + i * 20, 200 + i * 20, 8, parent=1, style={"background": [0.8, 0.0, 0.0]})
            for i in range(6)]
    page = extract(viewport(1440, [box(1, "other", 100, 100, 400, 300, style={"background": [0.95, 0.0, 0.0]}),
                                   *bars]))
    hits = lint("component.fake-app-window", extract=page).hits
    assert len(hits) == 1 and "6 textless CSS bars" in hits[0].observed


def shapes(with_text):
    boxes = [box(1, "other", 100, 100, 300, 300)]
    boxes += [box(2 + i, "other", 120 + i * 40, 150 + i * 20, 80, 80, parent=1,
                  style={"background": [0.6, 0.12, i * 60], "radius_px": 40}) for i in range(5)]
    text = []
    if with_text:
        boxes.append(box(10, "heading", 120, 110, 200, 30, parent=1))
        text.append(run(1, 10, "Kiln", "heading", 24))
    return extract(viewport(1440, boxes, text))


def test_css_illustration_hits_textless_shape_clusters():
    hits = lint("imagery.css-illustration", extract=shapes(False)).hits
    assert len(hits) == 1 and "5 CSS shapes" in hits[0].observed
    assert observed(lint("imagery.css-illustration", extract=shapes(True))) == []


def test_decorative_dom_skips_without_box_styles():
    assert lint("imagery.css-illustration", extract=extract(viewport(1440, [box(1, "other", 0, 0, 9, 9)]))).skipped


# ---------------------------------------------------------------- contract-diff

TOKENS_PLAN = {"tokens": {
    "type": {"roles": [{"role": "body", "family": "Pretendard"}], "scale": {"base_px": 16, "ratio": 1.25}},
    "color": {"roles": [{"name": "paper", "role": "field", "oklch": [0.97, 0.01, 85]},
                        {"name": "ink", "role": "foreground", "oklch": [0.25, 0.01, 60]}]},
    "space": {"scale": [4, 8, 16, 24, 32, 48]}}}
LOCK = {"fonts": [{"family": "Gowun Batang", "fallback": ["Noto Serif KR"]}]}


def families(*names):
    boxes = [box(i + 1, "text", 0, i * 40, 300, 30) for i in range(len(names))]
    text = [dict(run(i, i + 1, f"Run {i}"), font={"requested": n, "rendered": n}) for i, n in enumerate(names)]
    return extract(viewport(390, boxes, text))


def test_font_outside_contract_hits_requested_families_outside_plan_lock_and_fallbacks():
    hits = lint("system.font-outside-contract", extract=families("Pretendard", "Inter", "Gowun Batang",
                                                                 "Noto Serif KR", "serif"),
                plan=TOKENS_PLAN, lock=LOCK).hits
    assert len(hits) == 1 and "request 'Inter'" in hits[0].observed and hits[0].location["box"] == bid(2)
    assert lint("system.font-outside-contract", extract=families("Inter")).skipped
    assert lint("system.font-outside-contract", extract=families("System-UI"),
                plan=TOKENS_PLAN, lock=LOCK).hits == []


def test_literal_color_hits_colors_farther_than_delta_e_ok_max_from_every_token():
    page = extract(viewport(390, [box(1, "section", 0, 0, 390, 400, style={"background": [0.97, 0.01, 85]}),
                                  box(2, "text", 0, 0, 300, 30, parent=1)],
                            [run(1, 2, "Reserve", color=[0.62, 0.19, 25])]))
    hits = lint("system.literal-color", extract=page, plan=TOKENS_PLAN).hits
    assert len(hits) == 1 and "oklch(0.62 0.19 25)" in hits[0].observed and hits[0].location["box"] == bid(2)


def off_scale(size, inside_gap):
    return extract(viewport(390, [box(1, "text", 0, 0, 300, 30)], [run(1, 1, "Body", size=size)],
                            derived={"gaps": {"inside_group": {"median": inside_gap}}}))


def test_off_scale_value_hits_font_sizes_and_gaps_off_the_plan_scales_and_names_radius_unjudged():
    result = lint("system.off-scale-value", extract=off_scale(17, 20), plan=TOKENS_PLAN)
    hits = [h.observed for h in result.hits]
    assert len(hits) == 2
    assert any("17 px, between steps" in h for h in hits) and any("inside group gap" in h for h in hits)
    assert result.skipped.startswith("radius:")


def test_off_scale_value_reports_radius_as_not_judged_when_the_rest_matches():
    result = lint("system.off-scale-value", extract=off_scale(20, 16), plan=TOKENS_PLAN)
    assert result.hits == [] and "radius" in result.skipped
    assert "plan" in lint("system.off-scale-value", extract=off_scale(20, 16)).skipped


# ---------------------------------------------------------------- motion-inventory (render)

def moving(*boxes):
    return extract(viewport(390, list(boxes)))


def animation(**values):
    return {"name": "pulse", "properties": ["opacity"], "duration_ms": 1000, "iterations": "infinite",
            "easing": "ease", **values}


def test_pulse_hits_small_infinitely_animated_elements():
    dot = box(1, "other", 10, 10, 10, 10, motion={"animations": [animation()]})
    assert len(lint("motion.pulse-without-status", extract=moving(dot)).hits) == 1
    large = box(1, "other", 10, 10, 100, 100, motion={"animations": [animation()]})
    assert observed(lint("motion.pulse-without-status", extract=moving(large))) == []


def test_blink_hits_stepped_infinite_animations():
    caret = box(1, "other", 10, 10, 2, 20, motion={"animations": [animation(name="caret", stepped=True)]})
    assert len(lint("motion.decorative-cursor", extract=moving(caret)).hits) == 1
    once = box(1, "other", 10, 10, 2, 20, motion={"animations": [animation(name="fade", iterations=1)]})
    assert observed(lint("motion.decorative-cursor", extract=moving(once))) == []


def test_marquee_render_hits_content_moving_at_rest_and_skips_without_rest_samples():
    marquee = box(1, "list", 0, 10, 390, 60, motion={"moves_at_rest": True})
    still = box(2, "list", 0, 100, 390, 60, motion={"moves_at_rest": False})
    hits = lint("motion.uncontrolled-marquee", extract=moving(marquee, still)).hits
    assert [h.location["box"] for h in hits] == [bid(1)]
    unsampled = box(1, "list", 0, 10, 390, 60, motion={"animations": [animation(properties=["transform"])]})
    assert "no motion at rest" in lint("motion.uncontrolled-marquee", extract=moving(unsampled)).skipped
    assert observed(lint("motion.uncontrolled-marquee", extract=moving(box(1, "text", 0, 0, 9, 9)))) == []


def test_bounce_default_share_max_is_the_allowed_edge():
    def page(overshooting):
        boxes = []
        for i in range(4):
            easing = "cubic-bezier(0.34, 1.56, 0.64, 1)" if i < overshooting else "ease-out"
            boxes.append(box(1 + i, "button", 10, 50 * i, 100, 40,
                             motion={"transitions": [{"property": "transform", "duration_ms": 200, "easing": easing}]}))
        return moving(*boxes)
    assert "3 of 4" in lint("motion.bounce-default", extract=page(3)).hits[0].observed
    assert observed(lint("motion.bounce-default", extract=page(2))) == []


def test_layout_property_animation_hits_listed_properties_only():
    height = box(1, "other", 0, 0, 100, 100, motion={"transitions": [{"property": "height", "duration_ms": 300}]})
    transform = box(1, "other", 0, 0, 100, 100,
                    motion={"transitions": [{"property": "transform", "duration_ms": 300}]})
    assert "animates height" in lint("motion.layout-property-animation", extract=moving(height)).hits[0].observed
    assert observed(lint("motion.layout-property-animation", extract=moving(transform))) == []


def test_transition_all_hits_running_all_transitions():
    everything = box(1, "button", 0, 0, 100, 40, motion={"transitions": [{"property": "all", "duration_ms": 200}]})
    named = box(1, "button", 0, 0, 100, 40, motion={"transitions": [{"property": "opacity", "duration_ms": 200}]})
    assert len(lint("motion.transition-all", extract=moving(everything)).hits) == 1
    assert observed(lint("motion.transition-all", extract=moving(named))) == []


def test_ambient_loops_count_max_is_the_allowed_edge():
    loops = [box(1 + i, "other", 0, 40 * i, 200, 30, motion={"animations": [animation(properties=["transform"])]})
             for i in range(2)]
    assert "2 elements" in lint("motion.ambient-loops", extract=moving(*loops)).hits[0].observed
    assert observed(lint("motion.ambient-loops", extract=moving(loops[0]))) == []


# ---------------------------------------------------------------- motion-inventory (behavior)

def motion_probe(**values):
    return {"context": "d", "window_ms": 5000, "moving": [], **values}


def test_marquee_behavior_hits_long_motion_without_a_pause_control():
    def probe(seconds, pause):
        return session({"motion": [motion_probe(auto_moving=[{"box": bid(1), "seconds": seconds,
                                                                "pause_control": pause}])]})
    hits = lint("motion.uncontrolled-marquee", "behavior", session=probe(12, False)).hits
    assert len(hits) == 1 and hits[0].location == {"context": "d", "box": bid(1)} and hits[0].evidence == "runtime"
    assert observed(lint("motion.uncontrolled-marquee", "behavior", session=probe(12, True))) == []
    assert observed(lint("motion.uncontrolled-marquee", "behavior", session=probe(5, False))) == []


def test_hover_zoom_media_share_max_is_the_allowed_edge():
    def probe(total, transforming):
        return session({"motion": [motion_probe(hover_media={"total": total, "transforming": transforming})]})
    assert len(lint("motion.hover-zoom-everything", "behavior", session=probe(10, 9)).hits) == 1
    assert observed(lint("motion.hover-zoom-everything", "behavior", session=probe(10, 8))) == []
    assert observed(lint("motion.hover-zoom-everything", "behavior", session=probe(0, 0))) == []


def test_scroll_gated_content_hits_boxes_hidden_at_rest():
    probe = motion_probe(scroll_reveal=[{"box": bid(1), "hidden_at_rest": True, "reveal_delay_ms": 600},
                                        {"box": bid(2), "hidden_at_rest": False}])
    hits = lint("motion.scroll-gated-content", "behavior", session=session({"motion": [probe]})).hits
    assert [h.location["box"] for h in hits] == [bid(1)] and "600 ms" in hits[0].observed


def test_pause_control_render_skip_requires_later_behavior_layer():
    result = lint("motion.uncontrolled-marquee", extract=extract(viewport(390)),
                  params={"check": "pause-control"})
    assert result.skipped == "pause controls are observed only in the behavior session"
    assert result.cause == "layer"


def test_behavior_motion_skips_without_session_or_probe_record():
    assert lint("motion.scroll-gated-content", "behavior").skipped
    empty = session({}, coverage=[])
    assert "no motion probe" in lint("motion.scroll-gated-content", "behavior", session=empty).skipped
    ran = session({"motion": []}, coverage=[{"probe": "motion", "status": "ran"}])
    assert observed(lint("motion.scroll-gated-content", "behavior", session=ran)) == []


# ---------------------------------------------------------------- accessibility-tree

def controls(*boxes):
    return extract(viewport(390, list(boxes)))


def test_unlabeled_input_hits_missing_and_placeholder_only_labels():
    placeholder = box(1, "input", 0, 0, 300, 40, a11y={"name": "Email", "name_source": "placeholder"})
    missing = box(2, "input", 0, 60, 300, 40, a11y={"focusable": True})
    labeled = box(3, "input", 0, 120, 300, 40, a11y={"name": "Phone", "name_source": "label"})
    hits = observed(lint("component.unlabeled-input", extract=controls(placeholder, missing, labeled)))
    assert hits == ["input's only label is its placeholder (at 390 px)", "input has no programmatic label (at 390 px)"]
    assert lint("component.unlabeled-input", extract=controls(box(1, "input", 0, 0, 300, 40))).skipped


def test_unnamed_icon_button_hits_controls_without_a_name():
    unnamed = box(1, "button", 0, 0, 44, 44, a11y={"role": "button", "focusable": True},
                  icon={"kind": "svg", "action": "close"})
    named = box(2, "button", 60, 0, 44, 44, a11y={"role": "button", "name": "Close", "name_source": "aria-label"})
    hits = lint("component.unnamed-icon-button", extract=controls(unnamed, named)).hits
    assert len(hits) == 1 and hits[0].location["box"] == bid(1) and "close" in hits[0].observed


def test_clickable_non_interactive_hits_unfocusable_pointer_targets_only():
    clickable = box(1, "other", 0, 0, 200, 60, a11y={"pointer_handler": True, "focusable": False})
    wrapper = box(2, "card", 0, 100, 200, 60, a11y={"pointer_handler": True, "focusable": False})
    inner_button = box(3, "button", 10, 110, 100, 40, parent=2, a11y={"focusable": True, "name": "Open"})
    label_span = box(4, "other", 20, 120, 60, 20, parent=3, a11y={"pointer_cursor": True, "focusable": False})
    hits = lint("code.clickable-non-interactive", extract=controls(clickable, wrapper, inner_button, label_span)).hits
    assert [h.location["box"] for h in hits] == [bid(1)]
    unread = controls(box(1, "button", 0, 0, 100, 40), box(2, "other", 0, 60, 100, 40))
    assert "accessibility data" in lint("code.clickable-non-interactive", extract=unread).skipped


def forms(persists):
    field = {"box": bid(1), "kind": "email", "label": {"visible": True, "persists_after_input": persists}}
    return session({"forms": [{"box": bid(2), "context": "m", "purpose": "signup", "fields": [field]}]})


def test_unlabeled_input_behavior_hits_labels_that_vanish_after_input():
    hits = lint("component.unlabeled-input", "behavior", session=forms(False)).hits
    assert len(hits) == 1 and hits[0].location == {"context": "m", "box": bid(1)}
    assert observed(lint("component.unlabeled-input", "behavior", session=forms(True))) == []


# ---------------------------------------------------------------- layout-shift

def test_image_dimensions_cls_max_is_the_allowed_edge():
    def page(cls):
        return extract(viewport(390, [box(1, "media", 0, 0, 390, 200)],
                                metrics={"cls": cls, "shift_sources": [bid(1)]}))
    hits = lint("code.image-dimensions", extract=page(0.25)).hits
    assert len(hits) == 1 and "CLS 0.250" in hits[0].observed and hits[0].location["box"] == bid(1)
    assert observed(lint("code.image-dimensions", extract=page(0.1))) == []
    assert lint("code.image-dimensions", extract=extract(viewport(390))).skipped


def test_layout_animation_behavior_hits_controls_that_animate_layout_properties():
    def probe(animated):
        effect = {"outcome": "state-changed", "layout_animated": animated}
        return session({"controls": [{"box": bid(1), "context": "d", "action": {"kind": "click", "target": bid(1)},
                                      "effect": effect}]})
    hits = lint("motion.layout-property-animation", "behavior", session=probe([bid(2), bid(3)])).hits
    assert len(hits) == 1 and hits[0].refs == [bid(2), bid(3)]
    assert observed(lint("motion.layout-property-animation", "behavior", session=probe([]))) == []


LAYOUT_DETECTORS = {"template-repetition", "section-sequence", "section-inventory", "sibling-identity",
                    "card-nesting", "grid-filler", "gap-proximity", "symmetry", "reading-path", "edge-inset",
                    "responsive-structure", "signature-present", "large-list", "decorative-dom", "contract-diff",
                    "motion-inventory", "accessibility-tree", "layout-shift"}


@pytest.mark.parametrize("rule_id,layer", sorted(
    (r["id"], layer) for r in RULES["rules"] for layer, det in (r.get("detect") or {}).items()
    if det.get("detector") in LAYOUT_DETECTORS))
def test_layout_detectors_skip_without_their_input(rule_id, layer):
    wanted = "no render extract was given" if layer == "render" else "no behavior session was given"
    assert lint(rule_id, layer, plan=TOKENS_PLAN).skipped == wanted
