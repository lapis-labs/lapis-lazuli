"""End-to-end synthetic faces for kind, outline, and independent width/form measurements."""
from __future__ import annotations

import json

import pytest

from lazuli import cli
from synthetic_fonts import build


@pytest.fixture
def fonts(tmp_path, monkeypatch):
    root = tmp_path / "fonts"
    root.mkdir()
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={root}")
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    return root


def inventory(capsys):
    assert cli.main(["local", "fonts", "--json"]) == 0
    return {family["family"]: family for family in json.loads(capsys.readouterr().out)}

def test_unicode_backend_knows_sunuwar_letters():
    from fontTools import unicodedata as unicode_data

    assert unicode_data.category(chr(0x11BC0)) == "Lo"


def test_fonttools_script_data_matches_unicode_categories():
    import re
    from pathlib import Path

    import unicodedata2
    from fontTools.unicodedata import Scripts

    script_header = Path(Scripts.__file__).read_text(encoding="utf-8").splitlines()[:20]
    versions = [match.group(1) for line in script_header
                if (match := re.fullmatch(r"# Scripts-(\d+\.\d+\.\d+)\.txt", line))]
    assert len(versions) == 1
    assert versions[0] == unicodedata2.unidata_version


def test_sunuwar_letters_measure_as_text(fonts, capsys):
    from fontTools import unicodedata as unicode_data

    sunuwar = "".join(chr(cp) for cp in range(0x11BC0, 0x11BE1))
    build(fonts / "Sunuwar.ttf", family="Sunuwar Writing", latin=False, hangul=False,
          extra_letters=sunuwar)
    face = inventory(capsys)["Sunuwar Writing"]["faces"][0]
    assert face["kind"] == "text"
    assert face["metrics"]["letter_count"] == 33
    assert face["metrics"]["unicode_version"] == unicode_data.unidata_version



def test_letters_count_across_scripts_but_not_private_use_or_math(fonts, capsys):
    arabic = "".join(chr(cp) for cp in range(0x0621, 0x0639))
    build(fonts / "Arabic.ttf", family="Arabic Writing", latin=False, hangul=False, extra_letters=arabic)
    build(fonts / "Short.ttf", family="Nineteen Letters", latin=False, hangul=False,
          extra_letters=arabic[:19])
    build(fonts / "Twenty.ttf", family="Twenty Letters", latin=False, hangul=False,
          extra_letters=arabic[:20])
    build(fonts / "Icons.ttf", family="Private Icons", latin=False, hangul=False, extra_letters="\ue000\ue001")
    build(fonts / "Math.ttf", family="Math Icons", latin=False, hangul=False,
          extra_letters="".join(chr(cp) for cp in range(0x1D400, 0x1D414)))
    result = inventory(capsys)
    assert result["Arabic Writing"]["faces"][0]["kind"] == "text"
    assert result["Arabic Writing"]["faces"][0]["metrics"]["letter_count"] == 24
    assert result["Nineteen Letters"]["faces"][0]["kind"] == "symbol"
    assert result["Nineteen Letters"]["faces"][0]["metrics"]["letter_count"] == 19
    assert result["Twenty Letters"]["faces"][0]["kind"] == "text"
    assert result["Twenty Letters"]["faces"][0]["metrics"]["letter_count"] == 20
    for family in ("Private Icons", "Math Icons"):
        face = result[family]["faces"][0]
        assert face["kind"] == "symbol" and face["metrics"]["letter_count"] == 0


def test_small_script_near_complete_is_text(fonts, capsys):
    tagalog = "ᜀᜁᜂᜃᜄᜅᜆᜇᜈᜉᜊᜋᜌᜍᜎᜏᜐᜑ"
    build(fonts / "Tagalog.ttf", family="Tagalog Writing", latin=False, hangul=False, extra_letters=tagalog)
    build(fonts / "TagalogPartial.ttf", family="Partial Tagalog", latin=False, hangul=False,
          extra_letters=tagalog[:-1])
    result = inventory(capsys)
    assert result["Tagalog Writing"]["faces"][0]["metrics"]["letter_count"] == 18
    assert result["Tagalog Writing"]["faces"][0]["kind"] == "text"
    assert result["Partial Tagalog"]["faces"][0]["kind"] == "symbol"


def test_latin_name_hints_match_words_and_keep_cjk_substrings(fonts, capsys):
    for family in ("Open Sans", "Handheld Mono", "Songti SC", "Heiti SC", "STHeiti"):
        build(fonts / f"{family.replace(' ', '_')}.ttf", family=family, hangul=False)
    build(fonts / "Korean.ttf", family="Korean Caption", names_ko="손글씨풍", hangul=False)
    build(fonts / "Camel.ttf", family="SuperHand", hangul=False)
    build(fonts / "Digit.ttf", family="Sample2Hand", hangul=False)
    result = inventory(capsys)
    for family in ("Open Sans", "Handheld Mono"):
        face = result[family]["faces"][0]
        assert "hand" not in face["metrics"].get("name_hints", [])
        assert face["kind"] == "text"
    assert "bu-ri" in result["Songti SC"]["faces"][0]["metrics"]["name_hints"]
    for family in ("Heiti SC", "STHeiti"):
        assert "min-bu-ri" in result[family]["faces"][0]["metrics"]["name_hints"]
    assert result["Korean Caption"]["faces"][0]["kind"] == "hand"
    for family in ("SuperHand", "Sample2Hand"):
        assert result[family]["faces"][0]["kind"] == "hand"


def test_pixel_outlines_skip_stroke_shapes_but_keep_other_measures(fonts, capsys):
    build(fonts / "Pixel.ttf", family="Square Pixel", square_pixel=True)
    build(fonts / "Gothic.ttf", family="Straight Gothic", straight_samples_only=True)
    result = inventory(capsys)
    pixel = result["Square Pixel"]["faces"][0]
    assert pixel["metrics"]["pixel_outline"] is True
    assert "bu_ratio" not in pixel["cjk"] and "bu_class" not in pixel["cjk"]
    assert "cjk_contrast" not in pixel["cjk"] and "contrast_class" not in pixel["cjk"]
    assert "contrast" not in pixel["panose"] and "con_rat" not in pixel["metrics"]
    assert {"weight", "proportion"} <= pixel["panose"].keys()
    assert {"serif", "weight_rat"} <= pixel["metrics"].keys()
    assert "square_spread" in pixel["cjk"] and "weight_ratio_cjk_latin" in pixel["cjk"]
    assert "pixel" in result["Square Pixel"]["classes"]
    gothic = result["Straight Gothic"]["faces"][0]
    assert "pixel_outline" not in gothic["metrics"] and "pixel" not in result["Straight Gothic"]["classes"]
    assert cli.main(["local", "fonts", "--summary"]) == 0
    assert "pixel 1" in capsys.readouterr().out


def test_monospace_serif_is_both_a_form_and_a_width(fonts, capsys):
    build(fonts / "MonoSerif.ttf", family="Fixed Serif", serif=True, mono=True, hangul=False)
    families = inventory(capsys)
    face = families["Fixed Serif"]["faces"][0]
    assert face["metrics"]["monospaced"] is True and face["metrics"]["serif"] is True
    assert {"mono", "serif"} <= set(families["Fixed Serif"]["classes"])
    assert cli.main(["local", "fonts", "--summary"]) == 0
    summary = capsys.readouterr().out
    assert "serif 1" in summary and "mono 1" in summary
    assert cli.main(["search", "--category", "serif", "--json"]) == 0
    candidates = json.loads(capsys.readouterr().out)["candidates"]
    assert any(c["family"] == "Fixed Serif" and "category serif (measured)" in c["evidence"]
               for c in candidates)
