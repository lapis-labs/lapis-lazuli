"""Behavioral contract checks for render-derived measurements."""

import json

from jsonschema import Draft202012Validator
import pytest
import yaml

from lapis_design import shared_dir
from lapis_design.render.derived import derive


def box(number, role, rect, parent=None, *, background=None, border=0, shadow=False):
    result = {
        "id": f"b{number:012x}", "parent": parent, "role": role,
        "role_confidence": 1, "rect": dict(zip(("x", "y", "w", "h"), rect)),
    }
    style = {}
    if background is not None:
        style["background"] = background
    if border:
        style["border_px"] = border
    if shadow:
        style["shadow"] = True
    if style:
        result["style"] = style
    return result


def run(number, target, text, size=16, *, type_role="body", measure=12,
        weight=400, tracking=0, transform="none"):
    return {
        "id": f"t{number}", "box": target["id"], "text": text,
        "chars": sum(not ch.isspace() for ch in text), "script": "latn",
        "font": {"requested": "Arial", "rendered": "Arial"},
        "size_px": size, "weight": weight, "letter_spacing_em": tracking,
        "transform": transform, "type_role": type_role, "measure_chars": measure,
    }


def viewport(boxes, text=(), width=390):
    return {"width": width, "theme": "light", "boxes": boxes, "text": list(text)}


def elements_for(boxes, tags=None, attrs=None):
    tags = tags or {}
    attrs = attrs or {}
    elements = {
        b["id"]: {"tag": tags.get(b["id"], "div"),
                    "attrs": attrs.get(b["id"], {}), "children": []}
        for b in boxes
    }
    for b in boxes:
        if b.get("parent") in elements:
            elements[b["parent"]]["children"].append(b["id"])
    return elements


def test_type_fingerprint_groups_and_weights_runs_and_omits_missing_body_measure():
    heading = box(1, "heading", (10, 10, 100, 40))
    body = box(2, "text", (10, 60, 100, 50))
    runs = [
        run(1, heading, "Hello", 24.24, type_role="heading", weight=650,
            tracking=0.014, measure=5),
        run(2, body, "Welcome!", 16.24, measure=13),
        run(3, body, "Article", 16.22, measure=9),
    ]
    result = derive(viewport([heading, body], runs), elements_for([heading, body]), 844)
    assert result["type_fingerprint"] == {
        "roles": [
            {"size_px": 24, "weight": 700, "tracking_em": 0.01,
             "transform": "none", "share": 0.25},
            {"size_px": 16, "weight": 400, "tracking_em": 0,
             "transform": "none", "share": 0.75},
        ],
        "adjacent_ratios": [1.5], "measure_chars": 11,
    }
    for item in runs:
        item["type_role"] = "heading"
    assert "measure_chars" not in derive(viewport([heading, body], runs),
                                      elements_for([heading, body]), 844)["type_fingerprint"]


def test_section_sequence_recognizes_pricing_before_feature_grid():
    hero = box(1, "section", (0, 0, 390, 720))
    title = box(2, "heading", (20, 70, 350, 100), hero["id"])
    features = box(3, "section", (0, 740, 390, 660))
    pricing = box(4, "section", (0, 1420, 390, 650))
    footer = box(5, "section", (0, 2110, 390, 380))
    boxes = [hero, title, features, pricing, footer]
    texts = [run(1, title, "Welcome", 48, type_role="display")]
    counter = 6
    for parent, count in ((features, 3), (pricing, 3)):
        for number in range(count):
            card = box(counter, "card", (10 + 120 * number, parent["rect"]["y"] + 90,
                                         110, 400), parent["id"], border=1)
            heading = box(counter + 1, "heading", (15 + 120 * number,
                            card["rect"]["y"] + 20, 100, 30), card["id"])
            content = box(counter + 2, "text", (15 + 120 * number,
                            card["rect"]["y"] + 60, 100, 40), card["id"])
            boxes.extend((card, heading, content))
            texts.extend((run(counter, heading, "Plan" if parent is pricing else "Feature",
                              22, type_role="heading"),
                          run(counter + 1, content, "$29 / month" if parent is pricing
                              else "Short detail")))
            if parent is pricing:
                boxes.append(box(counter + 3, "button", (15 + 120 * number,
                    card["rect"]["y"] + 130, 100, 35), card["id"]))
                counter += 4
            else:
                counter += 3
    for number in range(3):
        link = box(counter + number, "link", (10, 2150 + number * 40, 200, 20), footer["id"])
        boxes.append(link)
        texts.append(run(counter + number, link, f"Link {number}", type_role="ui"))
    result = derive(viewport(boxes, texts), elements_for(boxes, {footer["id"]: "footer"}), 844)
    assert result["section_sequence"] == ["hero", "feature-grid", "pricing", "footer"]
    assert [item["box"] for item in result["sections"]] == [
        hero["id"], features["id"], pricing["id"], footer["id"]]
    assert result["sections"][2]["confidence"] == 1


def test_background_change_splits_one_section_into_two_real_box_ids():
    parent = box(1, "section", (0, 0, 390, 700))
    first = box(2, "other", (0, 0, 390, 340), parent["id"],
                background=[0.9, 0.02, 40])
    second = box(3, "other", (0, 350, 390, 340), parent["id"],
                 background=[0.5, 0.03, 250])
    title = box(4, "heading", (30, 50, 320, 80), first["id"])
    boxes = [parent, first, second, title]
    result = derive(viewport(boxes, [run(1, title, "Welcome", 40,
                                          type_role="display")]), elements_for(boxes), 500)
    assert [section["box"] for section in result["sections"]] == [first["id"], second["id"]]
    assert len(result["section_sequence"]) == 2
    first["style"]["background"] = [0.5, 0.2, 0]
    second["style"]["background"] = [0.5, 0.2, 180]
    assert len(derive(viewport(boxes), elements_for(boxes), 500)["sections"]) == 2
    second["style"]["background"] = [0.519, 0, 180]
    first["style"]["background"] = [0.5, 0, 0]
    assert len(derive(viewport(boxes), elements_for(boxes), 500)["sections"]) == 1


def test_main_landmark_is_a_container_not_the_only_section():
    body = box(1, "other", (0, 0, 390, 1700))
    main = box(2, "section", (0, 0, 390, 1700), body["id"])     # capture maps <main> to role section
    parts = [box(3 + i, "section", (0, i * 560, 390, 540), main["id"]) for i in range(3)]
    boxes = [body, main, *parts]
    elements = elements_for(boxes, {body["id"]: "body", main["id"]: "main",
                                    **{p["id"]: "section" for p in parts}})
    assert [s["box"] for s in derive(viewport(boxes), elements, 844)["sections"]] == [p["id"] for p in parts]
    for part in parts:                                          # plain div children taller than 30%
        part["role"] = "other"
        elements[part["id"]]["tag"] = "div"
    assert [s["box"] for s in derive(viewport(boxes), elements, 844)["sections"]] == [p["id"] for p in parts]


def test_sibling_similarity_is_pairwise_and_keeps_unequal_groups():
    section = box(1, "section", (0, 0, 390, 800))
    boxes = [section]
    texts = []
    for index in range(3):
        card = box(index + 2, "card", (index * 125, 60, 120, 200), section["id"])
        child = box(index + 5, "text", (index * 125 + 5, 80, 110, 50), card["id"])
        boxes.extend((card, child))
        texts.append(run(index + 1, child, "Identical"))
    original = derive(viewport(boxes, texts), elements_for(boxes), 844)
    matching = next(g for g in original["sibling_groups"] if
                    g["members"] == [boxes[i]["id"] for i in (1, 3, 5)])
    assert matching["similarity"] == 1
    boxes[5]["rect"]["w"] = 60
    boxes[5]["rect"]["h"] = 100
    texts[-1]["text"] = "Short"
    texts[-1]["chars"] = 5
    varied = derive(viewport(boxes, texts), elements_for(boxes), 844)
    unequal = next(g for g in varied["sibling_groups"] if
                   g["parent"] == section["id"])
    assert 0 <= unequal["similarity"] < matching["similarity"]


def test_card_depth_requires_area_boundary_and_noninteractive_role():
    page = box(1, "section", (0, 0, 390, 844), background=[1, 0, 0])
    first = box(2, "card", (20, 20, 300, 500), page["id"], border=1)
    second = box(3, "card", (40, 40, 220, 250), first["id"],
                 background=[0.6, 0.1, 30])
    button = box(4, "button", (45, 50, 200, 150), second["id"], border=1)
    tiny = box(5, "card", (50, 80, 30, 30), button["id"], border=1)
    neutral = box(6, "card", (50, 180, 120, 100), second["id"])
    boxes = [page, first, second, button, tiny, neutral]
    assert derive(viewport(boxes), elements_for(boxes), 844)["card_nesting_max"] == 2


def test_gap_order_stats_skip_side_by_side_and_undefined_ratio():
    section = box(1, "section", (0, 0, 390, 300))
    group = box(2, "card", (0, 20, 390, 100), section["id"])
    other = box(3, "card", (0, 150, 390, 100), section["id"])
    children = [box(i + 4, "text", (0, 30 + 30 * i, 100, 20), group["id"])
                for i in range(3)]
    alongside = box(7, "text", (250, 100, 100, 20), group["id"])
    next_section = box(8, "section", (0, 360, 390, 260))
    boxes = [section, group, other, *children, alongside, next_section]
    children[2]["rect"]["y"] = 110
    gaps = derive(viewport(boxes), elements_for(boxes), 844)["gaps"]
    assert gaps["inside_group"] == {"median": 20, "p10": 12, "p90": 28, "cv": 0.5}
    assert gaps["between_groups"]["median"] == 30
    assert gaps["between_sections"]["median"] == 60
    assert gaps["level_ratio"] == 3
    children[1]["rect"]["y"] = 50
    children[2]["rect"]["y"] = 70
    zero = derive(viewport(boxes), elements_for(boxes), 844)["gaps"]
    assert zero["inside_group"]["median"] == 0
    assert "level_ratio" not in zero


def test_density_uses_union_not_sum_and_symmetry_uses_run_box_fallback():
    outer = box(1, "text", (145, 0, 100, 100))
    nested = box(2, "media", (155, 20, 80, 60), outer["id"])
    control = box(3, "button", (145, 100, 100, 100))
    boxes = [outer, nested, control]
    vp = viewport(boxes, [run(1, outer, "Centered")])
    result = derive(vp, elements_for(boxes), 200)
    assert result["density"] == pytest.approx(20000 / (390 * 200), abs=1e-4)
    assert result["symmetry"] == 1
    outer["rect"].update(x=0, w=350)
    assert derive(vp, elements_for(boxes), 200)["symmetry"] < 1
    left = box(4, "text", (0, 0, 200, 100))
    crossing = box(5, "media", (100, 50, 200, 100))
    exact = derive(viewport([left, crossing]), elements_for([left, crossing]), 150)
    assert exact["density"] == pytest.approx(35000 / (390 * 150), abs=1e-4)


def test_signature_attribute_precedes_unverified_text_fallback():
    item = box(1, "text", (0, 0, 100, 20))
    vp = viewport([item], [run(1, item, "Unique woven mark")])
    attrs = {item["id"]: {"data-lapis-signature": ""}}
    assert derive(vp, elements_for([item], attrs=attrs), 844)["signature_found"] is True
    assert derive(vp, elements_for([item]), 844, "woven mark")["signature_found"] is True
    assert derive(vp, elements_for([item]), 844, "absent")["signature_found"] is False
    assert derive(viewport([]), {}, 844)["signature_found"] is False


def test_signature_evidence_names_how_the_signature_was_found():
    item = box(1, "text", (0, 0, 100, 20))
    vp = viewport([item], [run(1, item, "Unique woven mark")])
    attrs = {item["id"]: {"data-lapis-signature": ""}}
    marked = derive(vp, elements_for([item], attrs=attrs), 844, "woven mark")
    assert (marked["signature_found"], marked["signature_evidence"]) == (True, "verified")
    text_only = derive(vp, elements_for([item]), 844, "woven mark")
    assert (text_only["signature_found"], text_only["signature_evidence"]) == (True, "not-verified")
    missing = derive(vp, elements_for([item]), 844, "absent")
    assert missing["signature_found"] is False and "signature_evidence" not in missing


def test_sample_and_synthetic_derived_results_validate_in_full_schema():
    shared = shared_dir() / "render"
    schema = yaml.safe_load((shared / "extract.schema.yaml").read_text())
    validator = Draft202012Validator(schema)
    sample = json.loads((shared / "example.extract.json").read_text())
    original = sample["viewports"][0]
    boxes = original["boxes"]
    sample["viewports"][0]["derived"] = derive(original, elements_for(boxes), original["height"])
    assert list(validator.iter_errors(sample)) == []
    section = box(1, "section", (0, 0, 390, 400))
    label = box(2, "heading", (20, 20, 350, 40), section["id"])
    vp = viewport([section, label], [run(1, label, "Headline", type_role="heading")])
    vp["derived"] = derive(vp, elements_for(vp["boxes"]), 844)
    document = {"version": 1,
                "meta": {"extractor": {"name": "render_check", "version": "0.1.0"},
                         "generated_at": "2026-09-25T00:00:00Z"},
                "source": {"kind": "render"}, "viewports": [vp]}
    assert list(validator.iter_errors(document)) == []


def test_testimonials_require_attribution_near_each_quotation():
    intro = box(1, "section", (0, 0, 390, 700))
    quotes = box(2, "section", (0, 720, 390, 480))
    first = box(3, "text", (20, 760, 350, 60), quotes["id"])
    first_author = box(4, "text", (20, 825, 350, 25), quotes["id"])
    second = box(5, "text", (20, 1100, 350, 60), quotes["id"])
    second_author = box(6, "text", (20, 1165, 350, 25), quotes["id"])
    boxes = [intro, quotes, first, first_author, second, second_author]
    texts = [run(1, first, "“Beautiful”"), run(2, first_author, "Jane Doe",
             type_role="caption"), run(3, second, "“Fast”"),
             run(4, second_author, "Min Park", type_role="caption")]
    vp = viewport(boxes, texts)
    assert derive(vp, elements_for(boxes), 844)["sections"][1] == {
        "box": quotes["id"], "archetype": "testimonial", "confidence": 1}
    second_author["rect"]["y"] = 1700
    assert derive(vp, elements_for(boxes), 844)["sections"][1]["confidence"] == 0.5


def test_faq_logo_row_and_cta_cues_and_missing_input_omission():
    intro = box(1, "section", (0, 0, 390, 700))
    faq = box(2, "section", (0, 710, 390, 500))
    question_boxes = [box(n + 3, "heading", (20, 730 + n * 90, 350, 40), faq["id"])
                      for n in range(3)]
    logos = box(6, "section", (0, 1230, 390, 300))
    media = [box(n + 7, "media", (n * 90 + 10, 1270, 70, 40), logos["id"])
             for n in range(4)]
    cta = box(11, "section", (0, 1550, 390, 280))
    heading = box(12, "heading", (40, 1580, 300, 40), cta["id"])
    button = box(13, "button", (40, 1640, 300, 40), cta["id"])
    boxes = [intro, faq, *question_boxes, logos, *media, cta, heading, button]
    texts = [run(n + 1, item, f"Question {n}?", type_role="heading")
             for n, item in enumerate(question_boxes)]
    texts.append(run(4, heading, "Join today", type_role="heading"))
    result = derive(viewport(boxes, texts), elements_for(boxes), 844)
    assert result["section_sequence"][1:] == ["faq", "logo-strip", "cta"]
    assert derive({"width": 390, "theme": "light"}, {}, 844) == {}


def _priced_section(price):
    """A first section, then three cards with a heading, a short price line, and a button each."""
    intro = box(1, "section", (0, 0, 390, 700))
    intro_text = box(2, "heading", (20, 40, 350, 60), intro["id"])
    pricing = box(3, "section", (0, 720, 390, 600))
    boxes = [intro, intro_text, pricing]
    texts = [run(1, intro_text, "Pieces from this firing", 40, type_role="display")]
    for n in range(3):
        card = box(10 + 4 * n, "card", (10 + 125 * n, 760, 120, 400), pricing["id"], border=1)
        title = box(11 + 4 * n, "heading", (15 + 125 * n, 780, 110, 30), card["id"])
        amount = box(12 + 4 * n, "text", (15 + 125 * n, 820, 110, 30), card["id"])
        action = box(13 + 4 * n, "button", (15 + 125 * n, 870, 110, 40), card["id"])
        boxes.extend((card, title, amount, action))
        texts.extend((run(2 + 2 * n, title, f"Bowl {n}", 22, type_role="heading"),
                      run(3 + 2 * n, amount, price)))
    return boxes, texts


@pytest.mark.parametrize("price", ["9,900원", "월 9,900원", "4,900/월", "49,000 /년", "$29", "12 EUR"])
def test_korean_and_one_time_prices_are_price_cues(price):
    boxes, texts = _priced_section(price)
    section = derive(viewport(boxes, texts), elements_for(boxes), 844)["sections"][1]
    assert (section["archetype"], section["confidence"]) == ("pricing", 1)


def test_logo_strip_needs_three_small_image_or_svg_boxes_and_at_most_one_text_run():
    intro = box(1, "section", (0, 0, 390, 700))
    strip = box(2, "section", (0, 720, 390, 200))
    marks = [box(3 + n, "icon", (20 + 120 * n, 800, 90, 36), strip["id"]) for n in range(3)]
    caption = box(6, "text", (20, 740, 350, 24), strip["id"])
    boxes = [intro, strip, *marks, caption]
    tags = {mark["id"]: "svg" for mark in marks}
    one_run = [run(1, caption, "Fired for these studios", type_role="caption")]
    assert derive(viewport(boxes, one_run), elements_for(boxes, tags), 844)["sections"][1] == {
        "box": strip["id"], "archetype": "logo-strip", "confidence": 1}
    two_runs = [*one_run, run(2, caption, "and many more", type_role="caption")]
    assert derive(viewport(boxes, two_runs), elements_for(boxes, tags),
                  844)["section_sequence"][1] != "logo-strip"
    marks[2]["rect"]["h"] = 28                                  # 28 / 36 < 0.8: heights differ by more than 20%
    assert derive(viewport(boxes, one_run), elements_for(boxes, tags),
                  844)["section_sequence"][1] != "logo-strip"
    marks[2]["rect"]["h"] = 36
    del tags[marks[2]["id"]]                                    # a plain icon box is not an image or svg
    assert derive(viewport(boxes, one_run), elements_for(boxes, tags),
                  844)["section_sequence"][1] != "logo-strip"


def test_empty_section_matches_no_archetype():
    intro = box(1, "section", (0, 0, 390, 700))
    title = box(2, "heading", (20, 40, 350, 60), intro["id"])
    empty = box(3, "section", (0, 720, 390, 200))
    spacer = box(4, "other", (0, 720, 390, 100), empty["id"])
    boxes = [intro, title, empty, spacer]
    texts = [run(1, title, "Pieces from this firing", 40, type_role="display")]
    sections = derive(viewport(boxes, texts), elements_for(boxes), 844)["sections"]
    assert sections[1] == {"box": empty["id"], "archetype": "other", "confidence": 0}
    first = derive(viewport(boxes[2:]), elements_for(boxes[2:]), 844)["sections"][0]
    assert first == {"box": empty["id"], "archetype": "other", "confidence": 0}
