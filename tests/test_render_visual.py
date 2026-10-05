"""End-to-end checks of screenshot palette, paint layers, icons and media."""
from __future__ import annotations

from pathlib import Path

import pytest

import lapis_design.render.fields as fields
from lapis_design.render import _configs
from lapis_design.render.capture import capture
from lapis_design.render.color import delta_e_ok, to_oklch
from lapis_design.render.extract import assemble, validate
from lapis_design.render.fields import visual


@pytest.fixture
def visual_capture(monkeypatch, browser, render_server, tmp_path: Path):
    monkeypatch.setattr(fields, "FIELD_MODULES", (visual,))
    requested = []

    class RequestProbe:
        def new_context(self, **kwargs):
            context = browser.new_context(**kwargs)
            context.on("request", lambda request: requested.append(request.url))
            return context


    def run(filename: str):
        url = f"{render_server}/{filename}"
        result = capture(RequestProbe(), url, _configs(False, [390])[0],
                         tmp_path / f"{filename}.png", key=bytes(range(32)))
        assert not (issues := validate(assemble(url, None, [result], bytes(range(32)), dark_theme=False))), issues
        assert not any("placeholder.invalid" in url for url in requested)
        return result

    return run


def test_palette_from_painted_pixels_and_roles(visual_capture):
    vp = visual_capture("visual-palette.html")
    assert sum(entry["share"] for entry in vp["palette"]) == pytest.approx(1, abs=.001)
    white = next(entry for entry in vp["palette"] if entry.get("exact") and entry["oklch"][0] > .995)
    assert white["share"] == pytest.approx(.5, abs=.035)
    assert white["role_guess"] == "field"
    black = next(entry for entry in vp["palette"] if entry.get("exact") and entry["oklch"][0] < .005)
    assert black["role_guess"] == "foreground"
    blue = max((entry for entry in vp["palette"] if .3 < entry["oklch"][0] < .6),
               key=lambda item: item["share"])
    assert blue["share"] == pytest.approx(.5, abs=.035)
    assert blue["role_guess"] == "interaction"


def test_charts_paint_data_by_role_and_name_or_by_structure(visual_capture):
    vp = visual_capture("visual-chart-roles.html")

    def guessed(rgb: str) -> str:
        want = to_oklch(f"rgb({rgb})")
        entry = min(vp["palette"], key=lambda item: delta_e_ok(item["oklch"], want))
        assert delta_e_ok(entry["oklch"], want) < .06, rgb
        return entry["role_guess"]

    assert guessed("220 40 40") == "data"      # role img, aria-label "Revenue chart"
    assert guessed("240 140 0") == "data"      # role img, <title>Latency graph</title>
    assert guessed("30 160 60") == "data"      # three bars and two text labels
    assert guessed("220 0 200") == "data"      # canvas, role img, "Traffic plot"
    assert guessed("120 60 0") == "data"       # class "bar-chart"
    assert guessed("30 60 200") == "identity"  # three bars and one label
    assert guessed("150 30 200") == "content"  # "Sparkline chart" at 40 px
    assert guessed("230 200 0") == "content"   # role img, "Company logo"


def test_gradient_painted_above_every_box_has_no_behind(visual_capture):
    vp = visual_capture("visual-gradient-topmost.html")
    gradients = [g for b in vp["boxes"] for g in b["style"].get("gradients", [])]
    assert len(gradients) == 1 and "behind" not in gradients[0]


def test_css_paint_icon_media_and_hashes(visual_capture):
    vp = visual_capture("visual-fields.html")
    boxes = vp["boxes"]

    def by_class(name):
        # The fixture's geometry/paint identity remains observable via its CSS gradients,
        # shadow signatures and element sizes rather than private capture metadata.
        return next(b for b in boxes if predicate[name](b))

    predicate = {
        "linear": lambda b: any(g["kind"] == "linear" and g.get("angle_deg") == 90
                                and g["stops"][0]["at"] == .125 for g in b["style"].get("gradients", [])),
        "radial": lambda b: any(g["kind"] == "radial" for g in b["style"].get("gradients", [])),
        "halo": lambda b: b["style"].get("filter_blur_px") == 8,
        "card": lambda b: len(b["style"].get("shadows", [])) == 2,
        "grid": lambda b: b["style"].get("background_pattern", {}).get("kind") == "grid",
        "dots": lambda b: b["style"].get("background_pattern", {}).get("kind") == "dot-grid",
        "zigzag": lambda b: b["style"].get("clip", {}).get("kind") == "polygon",
    }
    linear = by_class("linear")["style"]["gradients"][0]
    assert linear["area_share"] > 0 and linear["first_viewport_share"] > 0
    assert by_class("radial")["style"]["gradients"]
    assert by_class("halo")["style"]["gradients"][0]["blur_px"] == 8
    assert any(g.get("behind") in {child["id"] for child in boxes if child["parent"] == b["id"]
                                  and child["rect"]["w"] == 140}
               for b in boxes for g in b["style"].get("gradients", []))
    assert by_class("card")["style"]["shadows"][1]["inset"]
    assert by_class("card")["style"]["shadows"][0]["color"][3] == .5
    assert by_class("grid")["style"]["background_pattern"]["cell_px"] == 20
    assert by_class("dots")["style"]["background_pattern"]["cell_px"] == 16
    assert any(b["style"].get("background_pattern", {}).get("kind") == "noise" for b in boxes)
    assert any(b["style"].get("background_pattern", {}).get("kind") == "stripes" for b in boxes)
    assert any(b["style"].get("background_pattern", {}).get("kind") == "crosshair" for b in boxes)
    clip = by_class("zigzag")["style"]["clip"]
    assert clip["vertices"] == 13 and clip["jaggedness"] > .6
    assert any(b.get("icon", {}).get("library") == "lucide" and b["icon"].get("grid_px") == 24
               and b["icon"].get("stroke_px") == 2 for b in boxes)
    assert any(b.get("icon", {}).get("kind") == "emoji" and b["icon"].get("glyph") == "U+2B50"
               for b in boxes)
    assert any(b["role"] == "button" and b.get("icon", {}).get("kind") == "svg"
               and b["icon"].get("grid_px") == 24 for b in boxes)
    assert any({g["target"] for g in b["style"].get("gradients", [])} >= {"border", "mask"}
               and any(shadow["source"] == "drop-shadow" for shadow in b["style"].get("shadows", []))
               for b in boxes)
    assert any(any(g["target"] == "text" for g in b["style"].get("gradients", []))
               and any(shadow["source"] == "text-shadow" for shadow in b["style"].get("shadows", []))
               for b in boxes)
    assert any(b["style"].get("backdrop_filter") ==
               {"blur_px": 4, "other": ["saturate(1.4)"]} for b in boxes)
    media = [b["media"] for b in boxes if "media" in b]
    loaded = [item for item in media if item.get("alt") == "Striped mountain"]
    assert len(loaded) == 1 and loaded[0]["loaded"]
    assert loaded[0]["natural_w"] == 128 and loaded[0]["natural_h"] == 64
    assert loaded[0]["intrinsic_size"] and loaded[0]["host"] == "127.0.0.1"
    assert any(item.get("alt") == "Broken view" and not item["loaded"] for item in media)
    assert any(item["placeholder"] and item["host"] == "placeholder.invalid" and not item["loaded"]
               for item in media)
    assert any(item.get("alt") == "Template slot" and item["placeholder"] and
               item["host"] is None and not item["loaded"] for item in media)
    assert any(item["kind"] == "img" and item["loaded"] and item.get("alt") is None
               and not item["decorative"] for item in media)
    assert any(item["kind"] == "img" and item["loaded"] and item.get("alt") == ""
               and item["decorative"] for item in media)
    assert any(item["kind"] == "css-background" and item["loaded"] and
               item["natural_w"] == 128 and item["natural_h"] == 64 for item in media)
    assert any(b.get("media", {}).get("kind") == "css-background" and
               b["media"].get("overlay") == {"alpha_max": .5, "coverage": 1}
               for b in boxes)
    overlay = next(item for item in media if item.get("alt") == "Mountain with overlay")
    assert overlay["overlay"]["alpha_max"] == pytest.approx(.5, abs=.01)
    assert overlay["overlay"]["coverage"] == pytest.approx(1, abs=.01)
    hashes = [item["phash"] for item in media if (item.get("alt") or "").startswith("Striped mountain")]
    assert len(hashes) == 2 and (int(hashes[0], 16) ^ int(hashes[1], 16)).bit_count() <= 8
