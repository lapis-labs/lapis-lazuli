"""Render-layer visual detectors of slop_lint: palette, theme pair, gradients, surfaces, icons,
images, typicality, and references. Every extract here is hand-built and validated against
render/extract.schema.yaml; each detector runs against the shipped rule that uses it."""
from __future__ import annotations

import copy

import pytest
import yaml
from jsonschema import Draft202012Validator

import lapis_design.lint.detectors.render_visual  # noqa: F401  (registers the detectors)
from lapis_design import shared_dir, text_sig
from lapis_design.lint.types import DETECTORS, Context
from lapis_design.render.color import to_oklch

RULES = yaml.safe_load((shared_dir() / "slop" / "rules.yaml").read_text(encoding="utf-8"))
RULE = {rule["id"]: rule for rule in RULES["rules"]}
VALIDATOR = Draft202012Validator(yaml.safe_load(
    (shared_dir() / "render" / "extract.schema.yaml").read_text(encoding="utf-8")))
HEIGHT = {320: 568, 390: 844, 768: 1024, 1440: 900}
KEY = bytes(range(32))
OTHER_KEY = bytes(range(1, 33))
EQUIVALENT_KEPT = "no required information or accessible equivalent is lost"


# ---------------------------------------------------------------- builders

def bid(n: int) -> str:
    return f"b{n:012x}"


def box(n: int, role: str = "card", parent: int | None = None, rect=(0, 0, 100, 100), **fields) -> dict:
    x, y, w, h = rect
    return {"id": bid(n), "parent": None if parent is None else bid(parent), "role": role,
            "role_confidence": 0.9, "rect": {"x": x, "y": y, "w": w, "h": h}, **fields}


def run(n: int, box_n: int, text: str = "Plain body copy", script: str = "latn", **fields) -> dict:
    return {"id": f"{bid(box_n)}-t{n}", "box": bid(box_n), "text": text, "chars": text_sig.chars(text),
            "script": script, "font": {"requested": "Serif", "rendered": "Serif"}, "size_px": 16, **fields}


def viewport(width: int = 390, theme: str = "light", boxes=(), text=(), **fields) -> dict:
    return {"width": width, "theme": theme, "height": HEIGHT[width], "boxes": list(boxes), "text": list(text),
            **fields}


def extract(*viewports: dict, rights: str | None = None, url: str | None = None, key: bytes | None = None) -> dict:
    doc = {"version": 1,
           "meta": {"extractor": {"name": "lazuli-ref" if rights else "render_check", "version": "test"},
                    "generated_at": "2026-09-26T00:00:00Z"},
           "source": {"kind": "site" if rights else "render"},
           "viewports": list(viewports)}
    if url:
        doc["source"]["url"] = url
    if rights:
        doc["reference"] = {"rights": rights}
    if key:
        doc["meta"]["sig_key_id"] = text_sig.key_id(key)
    errors = sorted(VALIDATOR.iter_errors(doc), key=lambda e: list(e.path))
    assert not errors, f"{list(errors[0].path)}: {errors[0].message}"
    return doc


def palette(*entries) -> list[dict]:
    out = []
    for oklch, share, *rest in entries:
        entry = {"oklch": oklch, "share": share}
        if rest and rest[0]:
            entry["role_guess"] = rest[0]
        if len(rest) > 1:
            entry["exact"] = rest[1]
        out.append(entry)
    return out


def rule_det(rule_id: str, **changes) -> dict:
    det = copy.deepcopy(RULE[rule_id]["detect"]["render"])
    for key, value in changes.items():
        det[key] = value
    return det


def judge(rule_id: str, doc: dict | None, *, det: dict | None = None, refs=(), corpus=()):
    rule = RULE[rule_id]
    det = det or rule["detect"]["render"]
    ctx = Context(rules=RULES, extract=doc, refs=list(refs), corpus=list(corpus))
    return DETECTORS[det["detector"]].fn(ctx, det, rule, "render")


def observed(result) -> list[str]:
    assert result.skipped is None, result.skipped
    return [hit.observed for hit in result.hits]


def test_every_detector_needs_an_extract():
    for rule_id in ("color.cream-base", "color.competing-accents", "color.inverted-dark-theme",
                    "color.violet-blue-gradient", "color.neon-glow", "component.emoji-icons",
                    "imagery.jagged-clip", "imagery.generic-stock", "layout.typical-composition",
                    "reference.clone-risk", "reference.brand-asset-reuse"):
        assert judge(rule_id, None).skipped == "no render extract was given"


# ---------------------------------------------------------------- palette-region

CREAM = [0.95, 0.02, 80]


def test_palette_region_reports_a_field_color_in_the_region_once_across_captures():
    field = palette((CREAM, 0.6, "field"), ([0.25, 0.01, 60], 0.1, "foreground"))
    doc = extract(viewport(390, palette=field), viewport(1440, palette=palette(([0.951, 0.021, 81], 0.7, "field"))))
    result = judge("color.cream-base", doc)
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert "field color" in hit.observed and "seen in 2 captures" in hit.observed
    assert hit.location == {"viewport": 1440}          # the capture where it covers the most


def test_palette_region_needs_the_role_and_the_bounds():
    doc = extract(viewport(palette=palette(
        (CREAM, 0.2, "foreground"),                     # in the region, wrong role
        ([0.99, 0.002, 90], 0.7, "field"))))            # right role, chroma below the region
    assert observed(judge("color.cream-base", doc)) == []


def test_palette_region_matches_any_listed_role():
    doc = extract(viewport(palette=palette(
        ([0.6, 0.12, 40], 0.05, "identity"), ([0.62, 0.12, 45], 0.04, "field"))))
    hits = observed(judge("color.terracotta-accent", doc))
    assert len(hits) == 1 and hits[0].startswith("identity color")
    assert "from the anchor" in hits[0]


def test_palette_region_skips_without_palette_or_role_guesses():
    assert judge("color.cream-base", extract(viewport())).skipped
    unguessed = extract(viewport(palette=palette((CREAM, 0.6, None))))
    assert "role guesses" in judge("color.cream-base", unguessed).skipped


# ---------------------------------------------------------------- palette-structure

def test_accent_roles_fire_on_two_interaction_hue_families():
    doc = extract(viewport(palette=palette(
        ([0.97, 0.01, 90], 0.7, "field"), ([0.5, 0.15, 250], 0.05, "interaction"),
        ([0.65, 0.17, 40], 0.04, "interaction"))))
    hits = observed(judge("color.competing-accents", doc))
    assert len(hits) == 1 and "interaction colors fall in 2 unrelated hue families" in hits[0]


def test_accent_roles_fire_on_three_accent_families():
    doc = extract(viewport(palette=palette(
        ([0.5, 0.15, 250], 0.05, "interaction"), ([0.6, 0.15, 140], 0.03, "identity"),
        ([0.65, 0.17, 30], 0.02, "identity"))))
    assert "accent colors fall in 3" in observed(judge("color.competing-accents", doc))[0]


def test_accent_roles_accept_one_accent_family_and_many_status_hues():
    doc = extract(viewport(palette=palette(
        ([0.5, 0.15, 250], 0.05, "interaction"), ([0.55, 0.14, 270], 0.03, "identity"),
        ([0.6, 0.2, 25], 0.01, "status"), ([0.7, 0.18, 145], 0.01, "status"), ([0.8, 0.16, 85], 0.01, "data"))))
    assert observed(judge("color.competing-accents", doc)) == []


def test_accent_roles_skip_without_role_guesses():
    doc = extract(viewport(palette=palette(([0.5, 0.15, 250], 0.05, None))))
    assert judge("color.competing-accents", doc).skipped


@pytest.mark.parametrize("warm, cool, fires", [(60, 105, False), (60, 106, True), (80, 250, True)])
def test_neutral_temperature_fires_only_above_the_spread_bound(warm, cool, fires):
    doc = extract(viewport(palette=palette(
        ([0.97, 0.01, warm], 0.6, "field"), ([0.3, 0.02, cool], 0.1, "foreground"),
        ([0.5, 0.001, 200], 0.05, "field"),              # a pure gray has no perceptible hue
        ([0.5, 0.15, 300], 0.05, "interaction"))))       # an accent is not a neutral
    assert bool(observed(judge("color.mixed-neutrals", doc))) is fires


@pytest.mark.parametrize("white, black, fires", [(0.3, 0.0, False), (0.2, 0.1, False), (0.25, 0.06, True)])
def test_pure_endpoints_fire_only_above_the_area_bound(white, black, fires):
    entries = [([1, 0, 0], white, "field", True), ([0.97, 0.001, 0], 0.4, "field")]
    if black:
        entries.append(([0, 0, 0], black, "foreground", True))
    doc = extract(viewport(palette=palette(*entries)))
    assert bool(observed(judge("color.pure-endpoints", doc))) is fires


# ---------------------------------------------------------------- theme-pair

def theme_boxes(section, card, text, button):
    boxes = [box(1, "section", style={"background": section}),
             box(2, "card", parent=1, style={"background": card}),
             box(3, "button", parent=2, style={"background": button})]
    return boxes, [run(0, 2, "Kiln-fired mugs", color=text)]


def test_theme_pair_fires_on_a_lightness_flip():
    light = viewport(390, "light", *theme_boxes([0.97, 0.01, 85], [1, 0, 0], [0.2, 0.01, 85], [0.5, 0.15, 250]))
    dark = viewport(390, "dark", *theme_boxes([0.03, 0.01, 85], [0, 0, 0], [0.8, 0.01, 85], [0.5, 0.15, 250]))
    hits = observed(judge("color.inverted-dark-theme", extract(light, dark)))
    assert len(hits) == 1
    assert "3 of 3 colors" in hits[0] and "lightness flipped" in hits[0]
    assert "1 raised surface turns darker" in hits[0]


def test_theme_pair_fires_on_an_invert_filter():
    def rgb(*channels):
        return to_oklch(f"rgb({' '.join(map(str, channels))})")
    light = viewport(390, "light", *theme_boxes(rgb(245, 245, 245), rgb(255, 255, 255), rgb(30, 30, 30),
                                                rgb(37, 99, 235)))
    dark = viewport(390, "dark", *theme_boxes(rgb(10, 10, 10), rgb(0, 0, 0), rgb(225, 225, 225),
                                              rgb(218, 156, 20)))
    hits = observed(judge("color.inverted-dark-theme", extract(light, dark)))
    assert len(hits) == 1 and "sRGB channels inverted" in hits[0]


def test_theme_pair_accepts_a_designed_dark_theme():
    light = viewport(390, "light", *theme_boxes([0.97, 0.01, 85], [1, 0, 0], [0.2, 0.01, 85], [0.5, 0.15, 250]))
    dark = viewport(390, "dark", *theme_boxes([0.18, 0.01, 260], [0.24, 0.01, 260], [0.93, 0.005, 260],
                                              [0.65, 0.14, 250]))
    assert observed(judge("color.inverted-dark-theme", extract(light, dark))) == []


def test_theme_pair_skips_without_a_dark_capture_or_enough_colors():
    light = viewport(390, "light", *theme_boxes([0.97, 0.01, 85], [1, 0, 0], [0.2, 0.01, 85], [0.5, 0.15, 250]))
    assert "no dark theme" in judge("color.inverted-dark-theme", extract(light)).skipped
    sparse = viewport(390, "dark", [box(1, "section", style={"background": [0.03, 0.01, 85]})])
    assert "fewer than 3" in judge("color.inverted-dark-theme", extract(light, sparse)).skipped


# ---------------------------------------------------------------- gradient-inventory

VIOLET, BLUE, ORANGE = [0.55, 0.2, 290], [0.6, 0.18, 260], [0.7, 0.17, 50]


def gradient(stops, kind="linear", target="background", **fields):
    return {"target": target, "kind": kind, "stops": [{"oklch": s} for s in stops], **fields}


@pytest.mark.parametrize("area, fires", [(0.05, False), (0.051, True)])
def test_violet_blue_gradient_fires_only_above_the_area_bound(area, fires):
    doc = extract(viewport(boxes=[box(1, "section", style={"gradients": [
        gradient([VIOLET, BLUE], area_share=area, first_viewport_share=0.5)]})]))
    hits = observed(judge("color.violet-blue-gradient", doc))
    assert bool(hits) is fires
    if fires:
        assert "with at least 2 stops in the rule's region" in hits[0] and "5.1% of the page" in hits[0]


def test_violet_blue_gradient_needs_two_stops_in_the_region():
    doc = extract(viewport(boxes=[box(1, "section", style={"gradients": [
        gradient([VIOLET, ORANGE], area_share=0.6)]})]))
    assert observed(judge("color.violet-blue-gradient", doc)) == []


def test_violet_blue_gradient_skips_when_a_counted_gradient_has_no_area():
    doc = extract(viewport(boxes=[box(1, "section", style={"gradients": [gradient([VIOLET, BLUE])]})]))
    assert "area_share" in judge("color.violet-blue-gradient", doc).skipped


def hero_page(*extra_boxes):
    boxes = [box(1, "section", rect=(0, 0, 390, 700)), box(2, "heading", parent=1, rect=(20, 100, 350, 80)),
             box(9, "section", rect=(0, 700, 390, 400)), *extra_boxes]
    derived = {"sections": [{"box": bid(1), "archetype": "hero"}, {"box": bid(9), "archetype": "footer"}]}
    return extract(viewport(boxes=boxes, derived=derived))


@pytest.mark.parametrize("share, fires", [(0.15, False), (0.2, True)])
def test_hero_halo_fires_only_above_the_first_viewport_bound(share, fires):
    halo = box(3, "other", parent=1, style={"gradients": [
        gradient([VIOLET, [0.55, 0.2, 290, 0.1]], kind="radial", first_viewport_share=share)]})
    assert bool(observed(judge("color.hero-halo", hero_page(halo)))) is fires


def test_hero_halo_counts_a_blurred_solid_shape():
    blob = box(3, "other", parent=1, rect=(0, 0, 390, 300), style={"background": VIOLET, "filter_blur_px": 60})
    hits = observed(judge("color.hero-halo", hero_page(blob)))
    assert len(hits) == 1 and "35.5% of the first viewport" in hits[0]


def test_hero_halo_ignores_gradients_outside_the_hero():
    footer_glow = box(3, "other", parent=9, style={"gradients": [
        gradient([VIOLET, BLUE], kind="radial", first_viewport_share=0.6)]})
    thin_blur = box(4, "other", parent=1, rect=(0, 0, 390, 300), style={"background": VIOLET, "filter_blur_px": 20})
    assert observed(judge("color.hero-halo", hero_page(footer_glow, thin_blur))) == []


def test_hero_halo_skips_without_sections_only_when_something_could_be_behind_the_hero():
    doc = extract(viewport(boxes=[box(1, "section", style={"gradients": [
        gradient([VIOLET, BLUE], kind="radial", first_viewport_share=0.6)]})]))
    assert "behind the hero" in judge("color.hero-halo", doc).skipped
    plain = judge("color.hero-halo", extract(viewport(boxes=[box(1, "section", style={"background": VIOLET})])))
    assert plain.skipped is None and plain.hits == []


def test_gradient_headline_fires_on_gradient_text():
    doc = extract(viewport(boxes=[box(1, "heading")], text=[
        run(0, 1, "Make pottery", type_role="display", fill="gradient", color=VIOLET)]))
    hits = observed(judge("color.gradient-headline", doc))
    assert hits == ['display text "Make pottery" is painted with a gradient fill (seen in 390 px light)']


def test_gradient_headline_fires_on_one_accent_colored_word():
    doc = extract(viewport(boxes=[box(1, "heading")], text=[
        run(0, 1, "Pottery for people who", type_role="heading", color=[0.2, 0.01, 60]),
        run(1, 1, "cook", type_role="heading", color=[0.62, 0.15, 35])]))
    hits = observed(judge("color.gradient-headline", doc))
    assert len(hits) == 1 and 'sets "cook" apart with the accent color' in hits[0]


def test_gradient_headline_ignores_body_text_and_plain_headings():
    doc = extract(viewport(boxes=[box(1, "heading"), box(2, "text")], text=[
        run(0, 1, "Pottery for people", type_role="heading", color=[0.2, 0.01, 60]),
        run(1, 1, "who cook", type_role="heading", color=[0.25, 0.01, 60]),
        run(0, 2, "Body copy in a gradient", type_role="body", fill="gradient", color=VIOLET)]))
    assert observed(judge("color.gradient-headline", doc)) == []


def test_gradient_headline_skips_without_type_roles():
    doc = extract(viewport(boxes=[box(1, "heading")], text=[run(0, 1, "Make pottery", fill="gradient")]))
    assert "type roles" in judge("color.gradient-headline", doc).skipped


# ---------------------------------------------------------------- surface-effects

def glow_page(ground_l, shadow, *, field=True):
    boxes = [box(1, "section", style={"background": [ground_l, 0.02, 280]} if field else {}),
             box(2, "card", parent=1, style={"shadows": [shadow]})]
    return extract(viewport(boxes=boxes))


def shadow(color, blur=20, x=0, y=0, source="box-shadow", **fields):
    return {"source": source, "offset_x": x, "offset_y": y, "blur_px": blur, "color": color, **fields}


def test_neon_glow_fires_at_its_inclusive_edges():
    hits = observed(judge("color.neon-glow", glow_page(0.25, shadow([0.65, 0.12, 300, 0.6], blur=8))))
    assert len(hits) == 1 and "box-shadow glow" in hits[0] and "(L 0.25)" in hits[0]


@pytest.mark.parametrize("ground, glow", [
    (0.26, shadow([0.65, 0.2, 300, 0.6])),               # background not dark enough
    (0.15, shadow([0.3, 0.02, 280, 0.5])),               # a gray shadow is not a glow
    (0.15, shadow([0.65, 0.2, 300], blur=6)),            # too sharp to glow
    (0.15, shadow([0.65, 0.2, 300], inset=True)),        # an inner shadow is not an outer glow
])
def test_neon_glow_ignores_ordinary_shadows(ground, glow):
    assert observed(judge("color.neon-glow", glow_page(ground, glow))) == []


def test_neon_glow_reads_text_backdrops_for_text_shadows():
    doc = extract(viewport(boxes=[box(1, "heading", style={"shadows": [
        shadow([0.7, 0.2, 200], blur=12, source="text-shadow")]})], text=[
        run(0, 1, "Night market", backdrop={"oklch": [0.1, 0.02, 270]})]))
    assert len(observed(judge("color.neon-glow", doc))) == 1


def test_neon_glow_skips_when_the_background_is_unknown():
    assert "no measured background" in judge(
        "color.neon-glow", glow_page(0.1, shadow([0.65, 0.2, 300]), field=False)).skipped


def panels(glass: int, plain: int) -> dict:
    boxes = [box(i, "card", style={"backdrop_filter": {"blur_px": 12}}) for i in range(glass)]
    boxes += [box(100 + i, "card", style={"background": [1, 0, 0]}) for i in range(plain)]
    return extract(viewport(boxes=boxes + [box(500, "text")]))


@pytest.mark.parametrize("glass, plain, fires", [(2, 2, False), (3, 1, True)])
def test_glass_everywhere_fires_only_above_the_panel_share(glass, plain, fires):
    hits = observed(judge("surface.glass-everywhere", panels(glass, plain)))
    assert bool(hits) is fires
    if fires:
        assert hits[0].startswith("3 of 4 panels (75%) blur the backdrop")


@pytest.mark.parametrize("large, fires", [(4, False), (5, True)])
def test_uniform_radius_fires_only_above_the_container_share(large, fires):
    roles = ["card", "card", "button", "input", "media"]
    boxes = [box(i, role, style={"radius_px": 24 if i < large else 4}) for i, role in enumerate(roles)]
    boxes.append(box(9, "text", style={"radius_px": 2}))       # text boxes are not containers
    assert bool(observed(judge("surface.uniform-large-radius", extract(viewport(boxes=boxes))))) is fires


def sided(role="card", radius=8, color=(0.6, 0.15, 250), px=4, other=0):
    sides = {"top": {"px": other}, "right": {"px": other}, "bottom": {"px": other},
             "left": {"px": px, "color": list(color)}}
    return box(1, role, style={"radius_px": radius, "border_sides": sides})


def test_side_accent_border_fires_on_a_colored_side_of_a_rounded_card():
    hits = observed(judge("surface.side-accent-border", extract(viewport(boxes=[sided()]))))
    assert len(hits) == 1 and "border on the left side only" in hits[0]


@pytest.mark.parametrize("variant", [
    {"radius": 0}, {"color": (0.4, 0.01, 250)}, {"role": "button"}, {"other": 3}])
def test_side_accent_border_ignores_other_borders(variant):
    assert observed(judge("surface.side-accent-border", extract(viewport(boxes=[sided(**variant)])))) == []


def test_depth_cue_conflict_fires_when_shadows_point_different_ways():
    boxes = [box(1, "card", style={"shadows": [shadow([0, 0, 0, 0.2], x=0, y=4)]}),
             box(2, "card", style={"shadows": [shadow([0, 0, 0, 0.2], x=0, y=-4)]})]
    hits = observed(judge("surface.depth-cue-conflict", extract(viewport(boxes=boxes))))
    assert len(hits) == 1 and "card boxes cast shadows in 2 directions" in hits[0]


def test_depth_cue_conflict_accepts_one_light_direction():
    boxes = [box(1, "card", style={"shadows": [shadow([0, 0, 0, 0.2], x=0, y=4)]}),
             box(2, "card", style={"shadows": [shadow([0, 0, 0, 0.2], x=1, y=6), shadow([0, 0, 0, 0.1])]})]
    assert observed(judge("surface.depth-cue-conflict", extract(viewport(boxes=boxes)))) == []


def test_decorative_grid_texture_counts_listed_pattern_kinds():
    boxes = [box(1, "section", style={"background_pattern": {"kind": "grid", "cell_px": 24}}),
             box(2, "section", style={"background_pattern": {"kind": "noise"}})]
    hits = observed(judge("surface.decorative-grid-texture", extract(viewport(boxes=boxes))))
    assert len(hits) == 1 and "grid background pattern with a 24 px cell" in hits[0]


@pytest.mark.parametrize("hard, fires", [(2, False), (3, True)])
def test_hard_offset_shadow_fires_only_above_the_card_share(hard, fires):
    boxes = [box(i, "card", style={"shadows": [shadow([0, 0, 0], blur=0, x=4, y=4)]}) for i in range(hard)]
    boxes += [box(10, "card", style={"shadows": [shadow([0, 0, 0, 0.2], blur=12, x=4, y=4)]})]   # soft
    boxes += [box(11 + i, "card", style={"shadows": [shadow([0, 0, 0], blur=0, x=1, y=1)]})       # hairline
              for i in range(3 - hard)]
    assert bool(observed(judge("surface.hard-offset-shadow", extract(viewport(boxes=boxes))))) is fires


# ---------------------------------------------------------------- icon-inventory

def icon_box(n, **icon):
    return box(n, "icon", rect=(0, 0, 24, 24), icon=icon)


def test_emoji_icons_fire_per_icon_box():
    doc = extract(viewport(boxes=[icon_box(1, kind="emoji", glyph="U+1F680"), icon_box(2, kind="svg", library="lucide")]),
                  viewport(1440, boxes=[icon_box(1, kind="emoji", glyph="U+1F680")]))
    hits = observed(judge("component.emoji-icons", doc))
    assert hits == ["emoji U+1F680 serves as an icon (seen in 390 px light, 1440 px light)"]


def test_emoji_icons_skip_when_icon_boxes_were_not_inventoried():
    assert judge("component.emoji-icons", extract(viewport(boxes=[box(1, "icon")]))).skipped


def test_hand_drawn_icons_fire_on_hand_authored_standard_actions():
    doc = extract(viewport(boxes=[
        icon_box(1, kind="svg", library=None, action="close"),
        icon_box(2, kind="svg", library="lucide", action="close"),
        icon_box(3, kind="svg", library=None)]))                  # a subject-specific drawing
    assert observed(judge("component.hand-drawn-icons", doc)) == [
        "hand-authored SVG draws the standard close icon (seen in 390 px light)"]


def test_mixed_icon_families_fire_above_one_family():
    doc = extract(viewport(boxes=[icon_box(1, kind="svg", library="lucide"), icon_box(2, kind="svg", library="Lucide"),
                                  icon_box(3, kind="svg", library="heroicons")]))
    hits = observed(judge("component.mixed-icon-families", doc))
    assert hits == ["2 icon families appear: lucide (2), heroicons (1)"]
    one = extract(viewport(boxes=[icon_box(1, kind="svg", library="lucide"), icon_box(2, kind="svg", library="lucide")]))
    assert observed(judge("component.mixed-icon-families", one)) == []


def test_mixed_icon_families_skip_when_an_icon_family_is_unknown():
    doc = extract(viewport(boxes=[icon_box(1, kind="svg", library="lucide"), icon_box(2, kind="icon-font")]))
    assert "no identified family" in judge("component.mixed-icon-families", doc).skipped


# ---------------------------------------------------------------- image-inventory

def image(n, style=None, a11y=None, **media):
    fields = {"media": {"kind": "img", "loaded": True, **media}}
    if style:
        fields["style"] = style
    if a11y:
        fields["a11y"] = a11y
    return box(n, "media", **fields)


def test_jagged_clip_fires_on_zigzag_clips_only():
    doc = extract(viewport(boxes=[
        image(1, style={"clip": {"kind": "polygon", "vertices": 14, "jaggedness": 0.8}}, alt="Kiln"),
        image(2, style={"clip": {"kind": "polygon", "vertices": 6, "jaggedness": 0.2}}, alt="Kiln"),
        image(3, style={"clip": {"kind": "circle"}}, alt="Kiln")]))
    hits = judge("imagery.jagged-clip", doc).hits
    assert [hit.location["box"] for hit in hits] == [bid(1)]


@pytest.mark.parametrize("coverage, alpha, fires", [(0.9, 0.7, True), (0.9, 0.6, False), (0.5, 0.9, False)])
def test_buried_raster_fires_only_above_the_overlay_bound(coverage, alpha, fires):
    doc = extract(viewport(boxes=[image(1, alt="Kiln", overlay={"coverage": coverage, "alpha_max": alpha})]))
    assert bool(observed(judge("imagery.buried-raster", doc))) is fires


def test_missing_content_image_reports_each_failure_with_its_adjust_condition():
    doc = extract(viewport(boxes=[
        image(1, loaded=False, alt="A mug fresh from the kiln", host="cdn.example"),
        image(2, placeholder=True, alt=None),
        image(3, alt=None),
        image(4, alt=None, a11y={"name": "Glaze samples"}),
        image(5, alt="", decorative=True),
        image(6, alt="Wood-fired kiln")]))
    found = {(hit.location["box"], hit.observed.removesuffix(" (seen in 390 px light)")): hit.conditions
             for hit in judge("imagery.missing-content-image", doc).hits}
    missing = "content image has no text alternative (no alt attribute or accessible name)"
    assert found == {
        (bid(1), "image from cdn.example failed to load"): {EQUIVALENT_KEPT},   # the alt text still stands in
        (bid(2), "image is an unresolved placeholder"): frozenset(),
        (bid(2), missing): frozenset(),
        (bid(3), missing): frozenset(),
    }


def test_missing_content_image_skips_when_alternatives_were_not_recorded():
    doc = extract(viewport(boxes=[image(1)]))
    assert "alt attribute was not recorded" in judge("imagery.missing-content-image", doc).skipped


# ---------------------------------------------------------------- image-embedding-region

def test_generic_stock_skips_for_want_of_image_embeddings():
    result = judge("imagery.generic-stock", extract(viewport(boxes=[image(1, alt="Team at a laptop")])))
    assert "no local image embedding model is installed" in result.skipped
    assert judge("imagery.generic-stock", extract(viewport(boxes=[box(1, "text")]))).hits == []
    unlisted = rule_det("imagery.generic-stock", list="no_such_list")
    assert "no_such_list" in judge("imagery.generic-stock", extract(viewport()), det=unlisted).skipped


# ---------------------------------------------------------------- typicality-distance

LANDING = ["hero", "feature-grid", "testimonial", "cta", "footer"]


def layout_page(sequence=LANDING, symmetry=0.8, density=0.4, **fields):
    derived = {"section_sequence": sequence, "symmetry": symmetry, "density": density}
    return extract(viewport(derived=derived, **fields), url="http://127.0.0.1/entry")


def tagged(doc: dict, corpus: str) -> dict:
    return {**doc, "_corpus": corpus}


def test_typical_composition_fires_near_a_defaults_entry():
    result = judge("layout.typical-composition", layout_page(),
                   corpus=[tagged(layout_page(symmetry=0.78, density=0.42), "defaults"),
                           tagged(layout_page(["hero", "other", "other"], 0.3, 0.1), "defaults")])
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.distance == pytest.approx(0.01) and "nearest defaults entry" in hit.observed


@pytest.mark.parametrize("density, fires", [(0.0, False), (0.01, True)])
def test_typical_composition_fires_only_below_the_distance_bound(density, fires):
    # sequence and archetypes 0, symmetry 0.4 apart, density 0.4 or 0.39 apart: mean 0.2 or 0.1975
    entry = tagged(layout_page(symmetry=0.4, density=density), "defaults")
    assert bool(judge("layout.typical-composition", layout_page(density=0.4), corpus=[entry]).hits) is fires


def test_typical_composition_skips_without_a_matching_corpus_or_features():
    assert "no typicality corpus" in judge("layout.typical-composition", layout_page()).skipped
    other = tagged(layout_page(), "starter-themes")
    assert "no defaults entries" in judge("layout.typical-composition", layout_page(), corpus=[other]).skipped
    bare = extract(viewport())
    assert "cannot give" in judge("layout.typical-composition", bare,
                                  corpus=[tagged(layout_page(), "defaults")]).skipped


def starter(field, accent, **extra):
    boxes = [box(i, "card", style={"radius_px": 8}) for i in range(3)]
    fingerprint = {"roles": [{"size_px": 48, "weight": 700, "share": 0.1}, {"size_px": 16, "weight": 400, "share": 0.9}]}
    derived = {"section_sequence": LANDING, "symmetry": 0.8, "density": 0.4, "type_fingerprint": fingerprint,
               "gaps": {"inside_group": {"median": 12}, "between_sections": {"median": 96}}}
    colors = palette((field, 0.8, "field"), (accent, 0.05, "interaction"))
    return extract(viewport(boxes=boxes, palette=colors, derived=derived, **extra), url="http://127.0.0.1/starter")


def test_palette_swap_only_ignores_the_palette_and_fires_on_an_unchanged_starter():
    ours = starter([0.2, 0.02, 30], [0.7, 0.18, 40])
    result = judge("color.palette-swap-only", ours,
                   corpus=[tagged(starter([0.99, 0, 0], [0.55, 0.2, 265]), "starter-themes")])
    assert len(result.hits) == 1 and result.hits[0].distance == 0
    assert "palette" not in result.hits[0].observed


def test_palette_swap_only_accepts_a_reworked_surface():
    ours = starter([0.2, 0.02, 30], [0.7, 0.18, 40])
    ours["viewports"][0]["derived"].update(section_sequence=["hero", "other", "faq"], symmetry=0.2, density=0.8)
    ours["viewports"][0]["derived"]["type_fingerprint"]["roles"][0].update(size_px=96, weight=300)
    ours["viewports"][0]["boxes"] = [box(i, "card", style={"radius_px": 0}) for i in range(3)]
    result = judge("color.palette-swap-only", ours,
                   corpus=[tagged(starter([0.99, 0, 0], [0.55, 0.2, 265]), "starter-themes")])
    assert result.skipped is None and result.hits == []


def test_typical_phrasing_skips_for_want_of_a_morphological_analyzer():
    result = judge("copy.typical-phrasing", layout_page(), corpus=[tagged(layout_page(), "defaults")])
    assert "morphological analyzer" in result.skipped


# ---------------------------------------------------------------- reference-distance and asset match

COPY = ["Hand-thrown stoneware, fired twice in a wood kiln", "Every mug is glazed by hand in small batches"]


def site(copy_lines=COPY, *, rights=None, key=KEY, sequence=LANDING, field=(0.97, 0.01, 85), phash=None,
         url="http://127.0.0.1/site"):
    """A render (rights None) or a reference profile of the same page, with keyed signatures."""
    runs = []
    for i, line in enumerate(copy_lines):
        entry = run(i, 1, line, text_sig=text_sig.run_sig(line, "latn", key))
        if rights == "reference-only":
            del entry["text"]
        runs.append(entry)
    media = {"kind": "img", "loaded": True, **({"phash": phash} if phash else {})}
    if rights != "reference-only":
        media["alt"] = "Mug"
    fingerprint = {"roles": [{"size_px": 40, "weight": 700, "share": 0.2}, {"size_px": 17, "weight": 400, "share": 0.8}]}
    vp = viewport(boxes=[box(1, "section"), box(2, "media", parent=1, media=media)], text=runs,
                  palette=palette((list(field), 0.7, "field"), ([0.25, 0.01, 60], 0.1, "foreground")),
                  derived={"section_sequence": sequence, "symmetry": 0.7, "density": 0.4,
                           "type_fingerprint": fingerprint},
                  text_sig=text_sig.page_sig([(line, "latn") for line in copy_lines], key))
    return extract(vp, rights=rights, key=key, url=url)


def test_clone_risk_fires_when_every_dimension_is_close_to_a_reference_only_profile():
    result = judge("reference.clone-risk", site(), refs=[site(rights="reference-only")])
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.distance == 0 and "reference-only reference http://127.0.0.1/site" in hit.observed
    assert all(f"{dim} 0.00" in hit.observed for dim in ("layout", "palette", "type", "copy"))


def test_clone_risk_accepts_licensed_references_and_different_copy():
    assert judge("reference.clone-risk", site(), refs=[site(rights="licensed")]).hits == []
    rewritten = site(["Porcelain cups thrown on a treadle wheel", "Shipped from the studio each Friday"],
                     rights="reference-only")
    result = judge("reference.clone-risk", site(), refs=[rewritten])
    assert result.skipped is None and result.hits == []


def test_clone_risk_skips_only_when_the_missing_dimension_could_decide():
    foreign_key = site(rights="reference-only", key=OTHER_KEY)
    assert "copy cannot be compared" in judge("reference.clone-risk", site(), refs=[foreign_key]).skipped
    far = site(rights="reference-only", key=OTHER_KEY, sequence=["other", "pricing", "faq"], field=(0.2, 0.1, 150))
    result = judge("reference.clone-risk", site(), refs=[far])
    assert result.skipped is None and result.hits == []
    assert "no reference profiles" in judge("reference.clone-risk", site()).skipped


@pytest.mark.parametrize("theirs, fires", [("0f0f0f0f0f0f0f30", True), ("0f0f0f0f0f0f0f70", False)])
def test_brand_asset_reuse_matches_images_within_the_hash_distance(theirs, fires):
    # 6 of 64 bits apart still match a resized or re-encoded copy; 7 bits do not
    ours = site(["Short"], phash="0f0f0f0f0f0f0f0f")
    hits = judge("reference.brand-asset-reuse", ours, refs=[site(["Tiny"], rights="reference-only", phash=theirs)]).hits
    assert bool(hits) is fires
    if fires:
        assert hits[0].evidence == "image" and hits[0].location == {"viewport": 390, "box": bid(2)}


def test_brand_asset_reuse_matches_reused_copy_but_not_short_labels():
    ours = site([COPY[0], "Menu"])
    ref = site([COPY[0], "Menu"], rights="reference-only")
    hits = judge("reference.brand-asset-reuse", ours, refs=[ref]).hits
    assert [hit.location for hit in hits] == [{"viewport": 390, "box": bid(1)}]
    assert COPY[0] in hits[0].observed and hits[0].evidence == "measurement"
    own = site([COPY[0]], rights="own")
    assert judge("reference.brand-asset-reuse", ours, refs=[own]).hits == []


def test_brand_asset_reuse_skips_copy_signed_with_another_key():
    result = judge("reference.brand-asset-reuse", site(), refs=[site(rights="reference-only", key=OTHER_KEY)])
    assert "signed with key" in result.skipped
    assert "no reference profiles" in judge("reference.brand-asset-reuse", site()).skipped
