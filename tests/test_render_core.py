"""Observable render capture and deterministic text/identity behavior."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema
import pytest
import yaml

from lapis_design import shared_dir
from lapis_design.render import _configs
from lapis_design.render.capture import capture, has_dark_theme
from lapis_design.render.color import contrast_ratio, to_oklch
from lapis_design.render.extract import assemble, validate, write_extract
from lapis_design.render.ids import box_id, generated_id
from lapis_design.render.script import script_of
from lapis_design.sig_key import load_key
from lapis_design.text_sig import run_sig


@pytest.mark.parametrize(("text", "expected"), [
    ("안녕하세요 Hello", "hang"),
    ("日本語かな", "kana"),
    ("中文文字", "hani"),
    ("Привет мир", "cyrl"),
    ("Hello привет", "mixed"),
    ("12345 €!", "other"),
])
def test_script_classification(text: str, expected: str) -> None:
    assert script_of(text) == expected


def test_box_identity_and_generated_ids() -> None:
    assert box_id([("html", 0, ""), ("body", 0, ""), ("section", 1, "stable")]) == box_id(
        [("html", 0, None), ("body", 0, None), ("section", 9, "stable")]
    )
    assert box_id([("html", 0, None), ("body", 0, None), ("div", 1, "card20260")]) != box_id(
        [("html", 0, None), ("body", 0, None), ("div", 2, "card20260")]
    )
    assert generated_id(":r0:") and generated_id("item1234")
    assert generated_id("radix-menu") and generated_id("my1234field")
    assert not generated_id("article123")
    assert not generated_id("product42")


def test_color_and_key_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LAPIS_SIG_KEY_FILE", str(tmp_path / "private" / "sig.key"))
    first = load_key()
    assert len(first) == 32 and load_key() == first
    assert (tmp_path / "private" / "sig.key").stat().st_mode & 0o777 == 0o600
    assert to_oklch("rgb(255 255 255)") == [1, 0, 0]
    assert to_oklch("rgb(0 0 0 / 0)") is None
    assert to_oklch("color(display-p3 1 0 0)")[1] > 0.2
    assert to_oklch("hsl(0 100% 50%)") == to_oklch("rgb(255 0 0)")
    assert to_oklch("color(srgb-linear 1 0 0)") == to_oklch("rgb(255 0 0)")
    assert to_oklch("hwb(0 0% 0%)") == to_oklch("rgb(255 0 0)")
    for gamut in ("a98-rgb", "prophoto-rgb", "rec2020", "xyz-d50"):
        assert to_oklch(f"color({gamut} 1 1 1)")[0] >= 0.99
    assert to_oklch("lab(100% 0 0)")[0] == 1
    assert to_oklch("lch(100% 0 0)")[0] == 1
    assert to_oklch("oklch(0.5 none none)") == [0.5, 0, 0]
    assert to_oklch("color(srgb 1 0 0 / .25)")[-1] == 0.25
    assert contrast_ratio([0, 0, 0], [1, 0, 0]) == pytest.approx(21, rel=1e-5)


def test_a98_rgb_neutrals_have_no_chroma() -> None:
    """The Adobe RGB matrix rows each sum to the D65 white, so white and grays stay neutral."""
    assert to_oklch("color(a98-rgb 1 1 1)") == to_oklch("rgb(255 255 255)") == [1, 0, 0]
    assert to_oklch("color(a98-rgb 0.5 0.5 0.5)")[1] == 0


def test_invalid_extract_is_not_written(tmp_path: Path) -> None:
    out = tmp_path / "invalid.json"
    assert validate({"version": 1})
    assert write_extract({"version": 1}, out)
    assert not out.exists()


def test_render_extract_records_detected_dark_theme():
    dark = assemble("http://localhost/", "demo", [], bytes(range(32)), dark_theme=True)
    light = assemble("http://localhost/", "demo", [], bytes(range(32)), dark_theme=False)
    assert dark["meta"]["dark_theme"] is True
    assert light["meta"]["dark_theme"] is False
    assert not validate(dark) and not validate(light)


def run_capture(browser, server: str, filename: str, out: Path):
    url = f"{server}/{filename}"
    key = bytes(range(32))
    dark = has_dark_theme(browser, url)
    viewports = []
    for i, config in enumerate(_configs(dark, None)):
        shot = out.parent / f"{out.stem}.shots" / f"{i}.png"
        vp = capture(browser, url, config, shot, key)
        vp["screenshot"] = shot.relative_to(out.parent).as_posix()
        viewports.append(vp)
    extract = assemble(url, "demo", viewports, key, dark_theme=dark)
    assert not write_extract(extract, out)
    return json.loads(out.read_text())


def test_capture_matrix_and_schema(browser, render_server: str, tmp_path: Path) -> None:
    schema = yaml.safe_load((shared_dir() / "render" / "extract.schema.yaml").read_text())
    example = json.loads((shared_dir() / "render" / "example.extract.json").read_text())
    assert not validate(example)
    extract = run_capture(browser, render_server, "dark.html", tmp_path / "dark.json")
    jsonschema.Draft202012Validator(schema).validate(extract)
    assert [(v["width"], v["theme"], v["reduced_motion"], v["browser_chrome"]) for v in extract["viewports"]] == [
        (320, "light", False, False), (390, "light", False, False),
        (390, "dark", False, False), (390, "light", True, False),
        (390, "light", False, True), (768, "light", False, False),
        (768, "dark", False, False), (1440, "light", False, False),
        (1440, "dark", False, False),
    ]
    for vp in extract["viewports"]:
        assert vp["dpr"] == 2
        assert (tmp_path / vp["screenshot"]).is_file()
        assert vp["text_sig"] and all(r["text_sig"] for r in vp["text"])
        assert sorted(b["paint_order"] for b in vp["boxes"]) == list(range(len(vp["boxes"])))
    assert [b["id"] for b in extract["viewports"][1]["boxes"]] == [
        b["id"] for b in extract["viewports"][2]["boxes"]
    ]
    chrome = extract["viewports"][4]
    assert chrome["height"] == 664
    assert next(b for b in chrome["boxes"] if b["role"] == "section")["rect"]["h"] == 844
    assert any(r["script"] == "hang" and r.get("lang") == "ko" for r in extract["viewports"][1]["text"])
    assert any(r["text"] == "Same style text" for r in extract["viewports"][1]["text"])
    vp = extract["viewports"][1]
    assert any(r["script"] == "hani" and r["lang"] == "zh-Hant-TW" for r in vp["text"])
    capital = next(r for r in vp["text"] if r["text"] == "Mixedcase Headline")
    assert capital["transform"] == "capitalize"
    assert capital["text_sig"] == run_sig("mixedcase headline", "latn", bytes(range(32)))
    assert any(r["text"] == "İSTANBUL" and r["lang"] == "tr" for r in vp["text"])
    assert "lang" not in next(r for r in vp["text"] if r["text"] == "Invalid locale")
    fallback = next(r for r in vp["text"] if r["text"] == "Fallback check")
    assert fallback["font"]["requested"] == "Arial, Experimental"
    assert fallback["font"]["fallback"]
    assert not any("Invisible fixture" in r["text"] or "Hidden fixture" in r["text"] for r in vp["text"])
    assert not any(r["text"] == "\u200b\u200d" for r in vp["text"])
    assert len({r["id"] for r in vp["text"]}) == len(vp["text"])
    sparkle = next(r for r in vp["text"] if r["text"] == "✨")
    icon = next(b for b in vp["boxes"] if b["id"] == sparkle["box"])
    assert icon["role"] == "icon" and icon["parent"] == box_id([
        ("html", 0, None), ("body", 0, None), ("main", 0, None), ("section", 0, "hero"),
    ])
    proxy = next(r for r in vp["text"] if r["text"] == "Proxy button")
    assert next(b for b in vp["boxes"] if b["id"] == proxy["box"])["role_basis"] == "aria"
    assert any(b["style"]["radius_px"] == 8 and b["style"]["border_sides"]["top"]["px"] == 1
               for b in vp["boxes"])


def test_kiln_shop_fixture_offers_plan_dark_theme(browser, render_server: str) -> None:
    url = f"{render_server}/kiln-shop/"
    assert has_dark_theme(browser, url)
    light = browser.new_page(color_scheme="light")
    dark = browser.new_page(color_scheme="dark")
    try:
        light.goto(url)
        dark.goto(url)
        colors = lambda page: page.locator("body").evaluate(
            "el => [getComputedStyle(el).backgroundColor, getComputedStyle(el).color]")
        assert colors(light) != colors(dark)
        assert dark.locator("body").evaluate(
            "el => getComputedStyle(el).backgroundColor") == "oklch(0.22 0.01 60)"
        assert dark.locator(".reserve").evaluate(
            "el => getComputedStyle(el).color") == "oklch(0.97 0.01 85)"
    finally:
        light.close()
        dark.close()


def test_no_dark_theme(browser, render_server: str, tmp_path: Path) -> None:
    extract = run_capture(browser, render_server, "light.html", tmp_path / "light.json")
    assert len(extract["viewports"]) == 6
    assert all(v["theme"] == "light" for v in extract["viewports"])


def test_a_row_with_only_a_rule_holding_a_bordered_tag_is_one_card_deep(browser, render_server: str, tmp_path: Path) -> None:
    """The dry run's tool rows, captured: a `border-bottom` per row is a rule, and the loan tag in it is the one card."""
    extract = run_capture(browser, render_server, "ruled-rows.html", tmp_path / "ruled.json")
    narrow = next(v for v in extract["viewports"] if v["width"] == 390 and v["theme"] == "light")
    assert narrow["derived"]["card_nesting_max"] == 1 and max(v["derived"]["card_nesting_max"] for v in extract["viewports"]) == 1
    boxes = narrow["boxes"]
    rules = [b for b in boxes if set((b.get("style") or {}).get("border_sides") or {}) == {"bottom"}]
    tags = [b for b in boxes if set((b.get("style") or {}).get("border_sides") or {}) == {"top", "right", "bottom", "left"}]
    assert len(rules) == 3 and len(tags) == 3


def test_render_check_command_persists_detection(render_server, tmp_path, monkeypatch):
    # The module's shared browser fixture owns a Sync API loop; run the CLI in its own process.
    monkeypatch.setenv("LAPIS_SIG_KEY_FILE", str(tmp_path / "key"))
    for page, expected in (("dark.html", True), ("light.html", False)):
        out = tmp_path / f"{page}.json"
        result = subprocess.run([sys.executable, "-m", "lapis_design.cli", "render", "check",
                                 f"{render_server}/{page}", "--task", "demo", "--width", "390",
                                 "--out", str(out)], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        document = json.loads(out.read_text(encoding="utf-8"))
        assert document["meta"]["dark_theme"] is expected


# An installed font served as a web font: its file names another family, as subsetted or
# obfuscated web fonts do. Copied to a temporary folder for the test, never into the repository.
INSTALLED_FONTS = [Path(p) for p in ("/System/Library/Fonts/Supplemental/Arial.ttf",
                                     "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                                     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]


@pytest.fixture
def web_font_page(tmp_path: Path):
    font = next((p for p in INSTALLED_FONTS if p.is_file()), None)
    if font is None:
        pytest.skip("no installed TrueType font to serve")
    site = tmp_path / "site"
    site.mkdir()
    shutil.copy(font, site / "brand.ttf")
    (site / "index.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><style>'
        '@font-face { font-family: "Brand Sans"; src: url(brand.ttf) format("truetype"); }'
        'body { margin: 0; font: 16px monospace; } .brand { font-family: "Brand Sans", monospace; }'
        '</style></head><body><main><p class="brand">Web font paragraph</p>'
        '<p>System font paragraph</p></main></body></html>', encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(site)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()
        server.server_close()


def test_web_fonts_are_named_by_their_font_face(browser, web_font_page: str, tmp_path: Path) -> None:
    config = _configs(False, [1440])[0]
    vp = capture(browser, web_font_page, config, tmp_path / "shot.png", bytes(range(32)))
    fonts = {r["text"]: r["font"] for r in vp["text"]}
    assert fonts["Web font paragraph"]["rendered"] == "Brand Sans"
    assert fonts["Web font paragraph"]["fallback"] is False
    assert fonts["System font paragraph"]["rendered"] not in ("Brand Sans", "")


def test_page_that_rebuilds_itself_on_resize_is_captured_whole(browser, render_server: str, tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """Every full-page screenshot makes the browser send a resize event although nothing is resized. A page that
    rebuilds its text and chart in answer lost the nodes the field passes held: `getComputedStyle` of the
    parent of a removed text node, and box ids that were no longer in the page."""
    import lapis_design.render.capture as capture_module
    real, resizes = capture_module.apply_fields, {}

    def observed(view, vp):
        real(view, vp)
        view.page.evaluate("dispatchEvent(new Event('resize'))")      # a page's own event still gets through
        resizes.update(view.page.evaluate("window.__resizes"))

    monkeypatch.setattr(capture_module, "apply_fields", observed)
    vp = capture(browser, f"{render_server}/resize-rerender.html", _configs(False, [390])[0],
                 tmp_path / "shot.png", bytes(range(32)))
    stats = next(run for run in vp["text"] if "12.4%" in run["text"])
    assert stats["fill"] == "solid" and stats["measure_chars"] > 0
    assert resizes == {"browser": 0, "page": 1}


def test_nodes_a_live_page_removes_are_marked_unmeasured_not_read(browser, render_server: str, tmp_path: Path) -> None:
    """A live board replaces a text node and a list row every 50 ms, so the nodes the capture recorded are gone
    from the document when the field passes reach them. The capture completes, measures what stayed, and marks
    each run and box it could not read without a value for what only the field passes add."""
    url, key = f"{render_server}/live-clock.html", bytes(range(32))
    vp = capture(browser, url, _configs(False, [390])[0], tmp_path / "shot.png", key)
    assert validate(assemble(url, "live-clock", [vp], key, dark_theme=False)) == []

    def run(start: str) -> dict:
        return next(item for item in vp["text"] if item["text"].startswith(start))

    stayed = run("The times")
    assert "unmeasured" not in stayed and stayed["fill"] == "solid" and stayed["measure_chars"] > 0
    for start in ("Updated ", "Line "):
        assert run(start)["unmeasured"] == "detached-during-capture"
        assert not {"type_role", "fill", "measure_chars", "backdrop", "states"} & run(start).keys()
    lost = [box for box in vp["boxes"] if "unmeasured" in box]
    assert sorted(box["role"] for box in lost) == ["button", "text"]       # the row and its button
    assert all(box["unmeasured"] == "detached-during-capture" and not {"clipped", "a11y", "motion"} & box.keys()
               for box in lost)
    assert all("clipped" in box for box in vp["boxes"] if "unmeasured" not in box)


def test_cli_writes_extract_and_screenshots(render_server: str, tmp_path: Path) -> None:
    out = tmp_path / "demo.json"
    env = {**os.environ, "LAPIS_SIG_KEY_FILE": str(tmp_path / "sig.key")}
    result = subprocess.run(
        [sys.executable, "-m", "lapis_design.cli", "render", "check", f"{render_server}/dark.html?synthetic=1#top",
         "--task", "demo", "--width", "320", "--out", str(out)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "1 viewports" in result.stdout and "boxes" in result.stdout and "runs" in result.stdout
    document = json.loads(out.read_text())
    assert not validate(document)
    assert document["source"]["url"] == f"{render_server}/dark.html"
    assert (tmp_path / document["viewports"][0]["screenshot"]).is_file()
