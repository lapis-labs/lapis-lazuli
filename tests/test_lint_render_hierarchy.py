"""Hierarchy detectors of slop_lint (cli/lapis_design/lint/detectors/render_hierarchy.py), run through the
registry with the shipped rules. Fixtures are small extracts that validate against the extract schema."""
from __future__ import annotations

from layout_support import box, extract, lint, observed, run, viewport

TILES = "type.oversized-icon-tile"
SHAPES = "layout.repeated-section-shape"
RHYTHM = "layout.flat-section-rhythm"
METRICS = "layout.metric-tile-opening"
CARD = {"border_px": 1, "border_color": [0.85, 0.0, 0.0]}
FIELD = [{"oklch": [0.98, 0.005, 120], "share": 0.9, "role_guess": "field"}]


# ---------------------------------------------------------------- icon-tile-cards

def tile_cards(tile=64, heading_px=20, items=3, heading_first=False, width=1440):
    """A group of sibling cards that each open with a painted icon tile above a heading and a line of text."""
    boxes, text, groups = [box(1, "section", 0, 0, width, 500)], [], []
    members = []
    for k in range(items):
        n = 10 + k * 10
        x = 40 + k * 400
        boxes.append(box(n, "card", x, 100, 360, 300, parent=1, style=dict(CARD)))
        heading = box(n + 3, "heading", x + 20, 100 + (20 if heading_first else tile + 40), 320, 30, parent=n)
        body = box(n + 4, "text", x + 20, 100 + (60 if heading_first else tile + 80), 320, 60, parent=n)
        tile_box = box(n + 1, "other", x + 20, 100 + (140 if heading_first else 20), tile, tile, parent=n,
                       style={"background": [0.9, 0.05, 250], "radius_px": 12})
        icon = box(n + 2, "icon", x + 20 + tile // 4, 100 + (140 if heading_first else 20) + tile // 4, tile // 2,
                   tile // 2, parent=n + 1, icon={"kind": "svg"})
        boxes += [tile_box, icon, heading, body] if not heading_first else [heading, body, tile_box, icon]
        text += [run(n + 3, n + 3, f"Feature {k}", "heading", heading_px), run(n + 4, n + 4, "What it does for you.")]
        members.append(f"b{n:012x}")
    groups.append({"parent": f"b{1:012x}", "members": members, "similarity": 0.95})
    return extract(viewport(width if width in (320, 390, 768, 1440) else 1440, boxes, text,
                            derived={"sibling_groups": groups}))


def test_icon_tiles_larger_than_their_headings_are_found():
    hits = observed(lint(TILES, extract=tile_cards()))
    assert len(hits) == 1 and "3 sibling items each open with an icon tile 64 px across above text set at 20 px" in hits[0]


def test_a_small_tile_at_the_text_scale_is_left_alone():
    assert observed(lint(TILES, extract=tile_cards(tile=28))) == []


def test_a_tile_not_larger_than_its_heading_is_left_alone():
    assert observed(lint(TILES, extract=tile_cards(tile=64, heading_px=48))) == []


def test_two_items_are_not_a_repeated_group():
    assert observed(lint(TILES, extract=tile_cards(items=2))) == []


def test_items_that_open_with_text_are_left_alone():
    assert observed(lint(TILES, extract=tile_cards(heading_first=True))) == []


def test_the_tile_bounds_are_the_rules():
    assert observed(lint(TILES, extract=tile_cards(tile=64), threshold={"tile_px_min": 80})) == []


def test_a_capture_narrower_than_desktop_is_not_judged():
    doc = extract(viewport(390, [box(1, "section", 0, 0, 390, 400)], [], derived={"sibling_groups": []}))
    assert lint(TILES, extract=doc).skipped == "the extract has no capture at desktop width, and narrower captures stack by design"


# ---------------------------------------------------------------- section blocks

def sections(kinds, tint=None, height=800, cards_style=True):
    """Sections stacked on one root, each a heading over `kind` cards in one row ('row3', 'row2', 'bare') or a picture."""
    root = box(1, "other", 0, 0, 1440, height * len(kinds))
    boxes, text = [root], []
    n = 10
    for index, kind in enumerate(kinds):
        y = index * height
        section = box(n, "section", 0, y, 1440, height, parent=1)
        if tint is not None and index in tint:
            section["style"] = {"background": [0.3, 0.04, 250]}
        boxes += [section, box(n + 1, "heading", 80, y + 60, 600, 44, parent=n)]
        text.append(run(n + 1, n + 1, f"Section {index}", "heading", 32))
        if kind in ("row3", "row2"):
            count = 3 if kind == "row3" else 2
            for k in range(count):
                boxes.append(box(n + 2 + k, "card", 80 + k * 420, y + 160, 380, 300, parent=n,
                                 style=dict(CARD) if cards_style else {}))
                boxes.append(box(n + 20 + k, "text", 100 + k * 420, y + 180, 340, 60, parent=n + 2 + k))
                text.append(run(n + 20 + k, n + 20 + k, "A short line about it."))
        elif kind == "picture":
            boxes.append(box(n + 2, "media", 80, y + 160, 900, 400, parent=n, media={"kind": "img", "loaded": True}))
        else:
            boxes.append(box(n + 2, "text", 80, y + 160, 700, 120, parent=n))
            text.append(run(n + 2, n + 2, "Running text of the section."))
        n += 40
    return extract(viewport(1440, boxes, text, palette=FIELD))


def test_three_sections_that_are_each_a_row_of_cards_are_found():
    hits = observed(lint(SHAPES, extract=sections(["row3", "row3", "row3"])))
    assert len(hits) == 1 and "3 consecutive sections are a heading over a row of three or more cards (3, 3, 3 across)" in hits[0]


def test_two_in_a_row_already_count_under_the_rules_bound():
    assert len(observed(lint(SHAPES, extract=sections(["row3", "row3"])))) == 1
    assert observed(lint(SHAPES, extract=sections(["row3", "row3"]), threshold={"repeats_max": 2})) == []


def test_sections_that_change_structure_are_left_alone():
    assert observed(lint(SHAPES, extract=sections(["row3", "bare", "row3", "picture", "row3"]))) == []


def test_rows_of_two_are_not_the_feature_grid():
    assert observed(lint(SHAPES, extract=sections(["row2", "row2", "row2"]))) == []


# ---------------------------------------------------------------- section-rhythm

def test_one_background_and_one_shape_throughout_is_found():
    hits = observed(lint(RHYTHM, extract=sections(["row3"] * 5)))
    assert len(hits) == 1 and "5 sections on one background, and 4 of 4 neighbour pairs share a shape, in a 4.4-screen page" in hits[0]


def test_a_tinted_band_gives_the_page_a_second_ground():
    assert observed(lint(RHYTHM, extract=sections(["row3"] * 5, tint={2}))) == []


def test_a_page_whose_sections_change_shape_is_left_alone():
    assert observed(lint(RHYTHM, extract=sections(["row3", "bare", "picture", "row2", "bare"]))) == []


def test_few_sections_or_a_short_page_are_not_judged():
    assert observed(lint(RHYTHM, extract=sections(["row3"] * 3))) == []
    assert observed(lint(RHYTHM, extract=sections(["row3"] * 5, height=400))) == []


def test_the_tint_bound_is_the_rules():
    doc = sections(["row3"] * 5, tint={2})
    assert len(observed(lint(RHYTHM, extract=doc, threshold={"band_delta_e_min": 0.9}))) == 1


# ---------------------------------------------------------------- metric-tiles

def metric_tiles(count=4, y=120, label_px=13, number_px=32, nav=False):
    boxes = [box(1, "nav" if nav else "section", 0, 0, 1440, 900)]
    text = []
    for k in range(count):
        n = 10 + k * 10
        boxes += [box(n, "card", 40 + k * 340, y, 320, 110, parent=1, style=dict(CARD)),
                  box(n + 1, "text", 60 + k * 340, y + 16, 200, 20, parent=n),
                  box(n + 2, "text", 60 + k * 340, y + 44, 120, 40, parent=n),
                  box(n + 3, "text", 190 + k * 340, y + 56, 30, 20, parent=n)]
        text += [run(n + 1, n + 1, "Buses running", "label", label_px), run(n + 2, n + 2, str(100 + k * 12), "display", number_px),
                 run(n + 3, n + 3, "buses", "caption", 14)]
    return extract(viewport(1440, boxes, text))


def test_a_row_of_big_number_tiles_in_the_first_view_is_found():
    hits = observed(lint(METRICS, extract=metric_tiles()))
    assert len(hits) == 1 and "4 tiles side by side in the first view each hold one big number (100, 112, 124, 136)" in hits[0]


def test_two_tiles_are_not_a_row():
    assert observed(lint(METRICS, extract=metric_tiles(count=2))) == []


def test_a_number_set_like_its_label_is_not_a_big_number():
    assert observed(lint(METRICS, extract=metric_tiles(number_px=15))) == []


def test_tiles_below_the_first_view_are_left_alone():
    assert observed(lint(METRICS, extract=metric_tiles(y=1200))) == []


def test_numbers_in_navigation_are_left_alone():
    assert observed(lint(METRICS, extract=metric_tiles(nav=True))) == []
