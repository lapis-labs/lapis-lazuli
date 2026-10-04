"""Compact-width detectors of slop_lint (cli/lapis_design/lint/detectors/render_compact.py), run through the
registry with the shipped rules. Fixtures are small extracts that validate against the extract schema."""
from __future__ import annotations

from layout_support import box, extract, lint, observed, run, viewport

NAV = "layout.compact-desktop-navigation"
OPENING = "layout.compact-object-opening"
LENGTH = "layout.compact-empty-length"


# ---------------------------------------------------------------- compact-navigation

def rail_page(width=390, rail_x=0, rail_w=56, stops=4):
    """A narrow column of stacked icon links beside a heading and a paragraph."""
    boxes = [box(1, "section", rail_x, 0, rail_w, 844)]
    boxes.append(box(2, "nav", rail_x + 6, 100, rail_w - 12, 60 * stops, parent=1))
    for k in range(stops):
        boxes.append(box(10 + k, "link", rail_x + 6, 100 + 60 * k, rail_w - 12, 44, parent=2))
    left = 24 if rail_x > 100 else rail_w + 12
    room = (rail_x - 48) if rail_x > 100 else width - rail_w - 24
    boxes += [box(3, "heading", left, 40, room, 40), box(4, "text", left, 100, room, 60)]
    text = [run(1, 3, "Operations", "heading", 24), run(2, 4, "Live arrivals for every route today.")]
    return extract(viewport(width, boxes, text))


def test_a_persistent_rail_at_phone_width_is_found():
    hits = observed(lint(NAV, extract=rail_page()))
    assert len(hits) == 1 and "56 px column of 4 stacked links and icons stays at the left edge" in hits[0]


def test_a_right_edge_rail_is_found_too():
    hits = observed(lint(NAV, extract=rail_page(rail_x=334)))
    assert len(hits) == 1 and "right edge" in hits[0]


def test_a_closed_drawer_off_the_page_is_not_a_rail():
    assert observed(lint(NAV, extract=rail_page(rail_x=-230, rail_w=210))) == []


def test_a_wide_open_menu_is_not_a_rail():
    assert observed(lint(NAV, extract=rail_page(rail_w=280))) == []


def test_a_rail_with_two_stops_is_not_a_rail():
    assert observed(lint(NAV, extract=rail_page(stops=2))) == []


def test_the_desktop_capture_keeps_its_sidebar():
    doc = extract(viewport(1440, [box(1, "section", 0, 0, 240, 900), box(2, "nav", 12, 100, 216, 300, parent=1),
                                  *[box(10 + k, "link", 12, 100 + 60 * k, 216, 44, parent=2) for k in range(4)],
                                  box(3, "text", 280, 100, 600, 60)], [run(1, 3, "Operations today")]))
    assert lint(NAV, extract=doc).skipped == "the extract has no capture narrower than 600 px"


def bar_page(count, widths=None, lines=1, stacked=False, x0=12):
    boxes = [box(1, "nav", 0, 60, 390, 48 if not stacked else 48 * count)]
    text, x = [], x0
    for k in range(count):
        w = (widths or [360 // count] * count)[k]
        boxes.append(box(10 + k, "link", x if not stacked else x0, 60 if not stacked else 60 + 48 * k, w, 44, parent=1))
        text.append(run(k, 10 + k, f"Item {k}", "nav", 14, lines=lines))
        x += w
    return extract(viewport(390, boxes, text))


def test_a_bar_that_fits_in_one_row_is_left_alone():
    assert observed(lint(NAV, extract=bar_page(3))) == []


def test_a_bar_item_that_runs_past_the_edge_is_found():
    hits = observed(lint(NAV, extract=bar_page(3, widths=[120, 120, 160])))
    assert len(hits) == 1 and "1 item run past the page edge" in hits[0]


def test_labels_that_wrap_inside_the_bar_are_found():
    hits = observed(lint(NAV, extract=bar_page(3, lines=2)))
    assert len(hits) == 1 and "3 item labels wrap onto a second line" in hits[0]


def test_five_items_in_one_row_are_found_and_the_bound_is_the_rules():
    assert len(observed(lint(NAV, extract=bar_page(5)))) == 1
    assert observed(lint(NAV, extract=bar_page(5), threshold={"row_items_min": 6})) == []


def test_a_stacked_menu_is_not_a_bar():
    assert observed(lint(NAV, extract=bar_page(6, stacked=True))) == []


def test_the_rail_check_can_be_run_alone():
    assert observed(lint(NAV, extract=bar_page(5), params={"checks": ["sidebar"]})) == []


# ---------------------------------------------------------------- compact-opening

def opening_page(object_y=300, object_h=300, role="media", control=False, heading_y=60, object_w=350):
    boxes = [box(1, "heading", 20, heading_y, 350, 80), box(2, role, 20, object_y, object_w, object_h)]
    text = [run(1, 1, "Your work. Safe by default.", "display", 36)]
    if control:
        boxes.append(box(3, "button", 40, object_y + 20, 120, 44, parent=2))
    return extract(viewport(390, boxes, text))


def test_an_image_filling_the_first_view_below_the_heading_is_found():
    hits = observed(lint(OPENING, extract=opening_page()))
    assert len(hits) == 1 and "fills 32% of the first view below the heading" in hits[0]


def test_a_small_object_is_left_alone():
    assert observed(lint(OPENING, extract=opening_page(object_h=140))) == []


def test_an_object_mostly_below_the_fold_is_left_alone():
    assert observed(lint(OPENING, extract=opening_page(object_y=700))) == []


def test_an_object_above_the_heading_is_not_pushed_below_it():
    assert observed(lint(OPENING, extract=opening_page(object_y=0, heading_y=400))) == []


def test_a_panel_with_a_control_in_it_is_the_task_not_an_ornament():
    assert observed(lint(OPENING, extract=opening_page(control=True))) == []


def test_the_share_bound_is_the_rules():
    assert observed(lint(OPENING, extract=opening_page(), threshold={"object_view_share_min": 0.4})) == []


# ---------------------------------------------------------------- compact-length

def long_page(bands, screens=6, text_every=250):
    """A phone page of `screens` viewports with a text row every `text_every` px, except inside `bands`."""
    length = screens * 844
    boxes, text, n = [box(1, "section", 0, 0, 390, length)], [], 10
    y = 0
    while y < length - 40:
        if not any(a <= y < b for a, b in bands):
            boxes.append(box(n, "text", 20, y, 350, 40, parent=1))
            text.append(run(n, n, "A paragraph of the page."))
            n += 1
        y += text_every if text_every else 40
    return extract(viewport(390, boxes, text))


def test_a_phone_page_made_of_empty_bands_is_found():
    doc = long_page([(500, 900), (1800, 2200), (3000, 3400)], text_every=60)
    hits = observed(lint(LENGTH, extract=doc))
    assert len(hits) == 1 and "of a 6.0-screen page is 3 bands with nothing to read or press" in hits[0]


def test_a_page_that_reads_all_the_way_down_is_left_alone():
    assert observed(lint(LENGTH, extract=long_page([], text_every=60))) == []


def test_a_short_page_is_not_judged():
    doc = long_page([(500, 900)], screens=3, text_every=60)
    assert observed(lint(LENGTH, extract=doc)) == []


def test_bands_below_the_height_bound_do_not_count():
    doc = long_page([(500, 700), (1800, 2000), (3000, 3200)], text_every=60)
    assert observed(lint(LENGTH, extract=doc)) == []
