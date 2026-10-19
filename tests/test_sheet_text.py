"""Text on the picture sheets: Korean, Japanese, and Chinese labels are drawn with a system font that has them, and a
string no font can draw is said so, never drawn as tofu in silence."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFont

from lapis_design import hints, references_sheet, sheet_text
from lapis_design.cli import main as design_main
from procedure_support import BRIEF_RECORD, TASK, load_skills, record, reference_entries, references_text, seal_requirements

LABELS = {"ko": "한글 표본 — 가마 기록", "ja": "ひらがなとカタカナ、漢字の見本", "zh": "简体中文与繁體中文的字样"}
DIRECTIONS = {"A": LABELS["ko"], "B": LABELS["ja"], "C": LABELS["zh"]}


@pytest.fixture(autouse=True)
def fresh_choices():
    """The choice is cached per process; each test starts with none."""
    sheet_text._choose.cache_clear()
    yield
    sheet_text._choose.cache_clear()


@pytest.fixture
def bare(tmp_path, monkeypatch) -> Path:
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    record(tmp_path, "answers", BRIEF_RECORD, 50)
    seal_requirements(tmp_path)
    load_skills(tmp_path)
    hints.draw(tmp_path, TASK, "none", "2026-10-05")
    record(tmp_path, "references", references_text(reference_entries(tmp_path), directions=DIRECTIONS), 100)
    return tmp_path


def need_font_for(text: str) -> None:
    face, missing = sheet_text._choose(sheet_text._needed(text))
    if missing:
        pytest.skip(f"no system font on this runner covers {text!r}")


def ink(image: Image.Image) -> Image.Image:
    """What is drawn on the sheet's background: black where nothing is, so `getbbox` is the extent of the drawing."""
    return ImageChops.difference(image.convert("RGB"), Image.new("RGB", image.size, references_sheet.BACKGROUND)).convert("L")


def heading_crop(sheet: Image.Image, column: int, lines: int = 1) -> Image.Image:
    x = references_sheet.PAD + column * (references_sheet.CELL_W + references_sheet.GAP)
    return ink(sheet.crop((x, references_sheet.PAD, x + references_sheet.CELL_W + references_sheet.GAP - 1,
                           references_sheet.PAD + 28 * lines)))


def rendered(line: str, font) -> Image.Image:
    """A heading line as the sheet draws it: at the column's left edge, ink only."""
    sheet = Image.new("RGB", (references_sheet.CELL_W + references_sheet.GAP - 1, 28), references_sheet.BACKGROUND)
    ImageDraw.Draw(sheet).text((0, 0), line, fill=references_sheet.INK, font=font)
    return ink(sheet)


@pytest.mark.parametrize("language", ["ko", "ja", "zh"])
def test_a_label_in_each_cjk_language_is_drawn_with_glyphs_and_not_the_notdef_box(language):
    text = LABELS[language]
    need_font_for(text)
    font, missing = sheet_text.font_for(text, 22)
    assert not missing
    boxed = [c for c in text if not c.isspace() and not sheet_text.draws_glyph(font, c)]
    assert boxed == []
    assert sheet_text.draws_glyph(font, "A")                                                            # and a letter


def test_the_built_in_font_draws_hangul_as_a_box_and_the_probe_sees_it():
    assert not sheet_text._default_draws("한") and not sheet_text._default_draws("あ") and not sheet_text._default_draws("中")
    assert sheet_text._default_draws("A") and sheet_text._default_draws("-")


def test_the_references_sheet_draws_korean_japanese_and_chinese_directions_in_their_own_glyphs(bare, capsys, monkeypatch):
    for text in LABELS.values():
        need_font_for(text)
    monkeypatch.chdir(bare)
    assert design_main(["references", "sheet", "--task", TASK]) == 0
    assert capsys.readouterr().err == ""                                       # nothing was left undrawn
    with Image.open(bare / f".lapis/references/{TASK}.sheet.png") as image:
        sheet = image.convert("RGB")
    for column, (letter, name) in enumerate(DIRECTIONS.items()):
        lines = sheet_text.wrap(f"{letter} - {name}", 22, references_sheet.CELL_W)
        drawn = heading_crop(sheet, column, len(lines))
        assert drawn.getbbox() is not None and drawn.getbbox()[2] <= references_sheet.CELL_W   # in its own column
        for number, line in enumerate(lines):
            font, missing = sheet_text.font_for(line, 22)
            assert not missing and all(sheet_text.draws_glyph(font, c) for c in line if not c.isspace())
            row = drawn.crop((0, 28 * number, drawn.width, 28 * number + 28))
            assert row.getbbox() is not None
            assert row.tobytes() == rendered(line, font).tobytes()                              # drawn in that font
            if any(not sheet_text._default_draws(c) for c in line if not c.isspace()):
                boxes = line.translate({ord(c): sheet_text.NOTDEF for c in line if not sheet_text._default_draws(c)})
                assert row.tobytes() != rendered(boxes, ImageFont.load_default(size=22)).tobytes()   # not the old boxes


def test_a_string_no_font_has_is_reported_and_the_sheet_says_so(bare, capsys, monkeypatch):
    monkeypatch.setattr(sheet_text, "_faces", lambda language: ())
    monkeypatch.chdir(bare)
    assert design_main(["references", "sheet", "--task", TASK]) == 0
    err = capsys.readouterr().err
    assert "lapis-design references sheet: no font on this machine has U+" in err and "U+D55C" in err
    assert "U+3072" in err and "U+7B80" in err and "show boxes" in err
    assert LABELS["ko"] in err.replace("'", "")                                  # the strings that were not drawn
    with Image.open(bare / f".lapis/references/{TASK}.sheet.png") as image:
        foot = ink(image.crop((0, image.height - 40, image.width, image.height)))
    assert foot.getbbox() is not None                                            # the limit line is under the sheet


def test_a_latin_only_sheet_reads_no_font_file(bare, monkeypatch, capsys):
    def refuse(language):
        raise AssertionError("a Latin sheet must not look for a system font")

    monkeypatch.setattr(sheet_text, "_faces", refuse)
    record(bare, "references", references_text(reference_entries(bare)), 100)
    monkeypatch.chdir(bare)
    assert design_main(["references", "sheet", "--task", TASK]) == 0
    assert capsys.readouterr().err == ""


def test_a_face_in_adobes_folders_is_never_listed_or_opened(monkeypatch, tmp_path):
    adobe = tmp_path / "Library/Application Support/Adobe/CoreSync/plugins/livetype/.r/.10312.otf"
    assert not sheet_text._allowed(str(adobe))
    monkeypatch.setattr(sheet_text.shutil, "which", lambda name: "/usr/bin/fc-match")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, f"{adobe}\n0", ""))
    assert sheet_text._fc_match("ko") == []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "/usr/share/fonts/a.ttc\n2", ""))
    assert sheet_text._fc_match("ko") == [sheet_text.Face("/usr/share/fonts/a.ttc", 2)]


def test_the_choice_is_made_once_per_set_of_characters(monkeypatch):
    need_font_for(LABELS["ko"])
    calls = []
    real = sheet_text._faces
    monkeypatch.setattr(sheet_text, "_faces", lambda language: calls.append(language) or real(language))
    first = sheet_text._choose(sheet_text._needed(LABELS["ko"]))
    count = len(calls)
    assert sheet_text._choose(sheet_text._needed(LABELS["ko"])) == first and len(calls) == count


def test_wrapped_lines_fit_their_column_in_pixels_for_text_without_spaces():
    need_font_for(LABELS["ja"])
    lines = sheet_text.wrap(LABELS["ja"] * 3, 22, 360)
    font, _ = sheet_text.font_for(LABELS["ja"], 22)
    assert len(lines) > 1 and "".join(lines) == LABELS["ja"] * 3
    assert all(font.getlength(line) <= 360 for line in lines)
