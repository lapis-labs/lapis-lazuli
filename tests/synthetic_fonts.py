"""Tiny fonts built in code with known geometry, for scanner and measurement tests.

No font file enters the repository: each test builds what it needs in a temporary folder. Units are
per 1000 em. Outer contours run clockwise and counters counter-clockwise (TrueType), so FreeType fills
rings correctly.
"""
from __future__ import annotations

import math
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTCollection, TTFont

CAP = 700
X_HEIGHT = 500
LETTERS = [chr(c) for c in range(ord("A"), ord("Z") + 1)] + [chr(c) for c in range(ord("a"), ord("z") + 1)]


def _rect(pen, x0, y0, x1, y1, *, hole=False):
    points = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]           # clockwise
    if hole:
        points.reverse()
    pen.moveTo(points[0])
    for point in points[1:]:
        pen.lineTo(point)
    pen.closePath()


def _ellipse(pen, cx, cy, rx, ry, *, hole=False, steps=144):
    points = [(cx + rx * math.cos(-2 * math.pi * i / steps), cy + ry * math.sin(-2 * math.pi * i / steps))
              for i in range(steps)]                                 # clockwise
    if hole:
        points.reverse()
    pen.moveTo(tuple(map(round, points[0])))
    for point in points[1:]:
        pen.lineTo(tuple(map(round, point)))
    pen.closePath()


def _glyph(draw):
    pen = TTGlyphPen(None)
    draw(pen)
    return pen.glyph()


def build(path: Path, *, family="Test Sans", style="Regular", stem=100, serif=False, contrast=False,
          mono=False, bu=False, reverse=False, spread=False, hangul=True, latin=True, names_ko=None,
          square_pixel=False, straight_samples_only=False, extra_letters="") -> Path:
    """One face. `stem`: E and H vertical stems; `serif`: H feet 2.2x the stem; `contrast`: an O whose
    sides (200) are five times its top and bottom (40); `bu`: a nub on top of the ㅣ of 이; `reverse`: 口 with
    horizontals twice the verticals; `spread`: syllables of different heights."""
    glyphs = {".notdef": _glyph(lambda p: _rect(p, 50, 0, 450, CAP))}
    cmap: dict[int, str] = {}
    advances: dict[str, int] = {".notdef": 500}

    def add(name, ch, draw, advance=700):
        glyphs[name] = _glyph(draw)
        advances[name] = 600 if mono else advance
        if ch:
            cmap[ord(ch)] = name

    if latin:
        def h(p):
            _rect(p, 100, 0, 100 + stem, CAP)
            _rect(p, 500 - stem, 0, 500, CAP)
            _rect(p, 100 + stem, 330, 500 - stem, 330 + stem // 2)
            if serif:
                foot = int(stem * 2.2)
                for x in (100 + stem // 2, 500 - stem // 2):
                    _rect(p, x - foot // 2, 0, x + foot // 2, 30)
        add("H", "H", h, 600)
        if not straight_samples_only:
            add("E", "E", lambda p: (_rect(p, 100, 0, 100 + stem, CAP), _rect(p, 100 + stem, 0, 480, 60),
                                     _rect(p, 100 + stem, 320, 430, 380), _rect(p, 100 + stem, CAP - 60, 480, CAP)), 560)

            def o(p):
                if square_pixel:
                    _rect(p, 50, 0, 650, CAP)
                    _rect(p, 50 + stem, stem, 650 - stem, CAP - stem, hole=True)
                else:
                    _ellipse(p, 350, CAP / 2, 300, CAP / 2)
                    if contrast:
                        _ellipse(p, 350, CAP / 2, 300 - 200, CAP / 2 - 40, hole=True)
                    else:
                        _ellipse(p, 350, CAP / 2, 300 - stem, CAP / 2 - stem, hole=True)
            add("O", "O", o, 700)
            add("S", "S", lambda p: _rect(p, 80, 0, 480, CAP), 560)
            add("x", "x", lambda p: _rect(p, 50, 0, 450, X_HEIGHT), 500)
            add("period", ".", lambda p: _rect(p, 100, 0, 200, 100), 300)
            add("zero", "0", lambda p: _rect(p, 60, 0, 440, CAP), 500)
            for ch in LETTERS:
                if ord(ch) not in cmap:
                    add(f"u{ord(ch):04X}", ch, lambda p: _rect(p, 60, 0, 60 + stem, CAP),
                        600 if ch in "mW" else 300)
    if hangul:
        if not straight_samples_only:
            def i_eung(p):
                _rect(p, 80, 150, 480, 550)                           # ㅇ drawn as a square ring
                _rect(p, 160, 230, 400, 470, hole=True)
                _rect(p, 700, 50, 780, 800)                           # ㅣ, 80 wide
                if bu:
                    _rect(p, 650, 740, 700, 800)                      # nub reaching left of the stem top
            add("uC774", "이", i_eung, 1000)
        v, hz = (40, 80) if reverse else (80, 40)
        add("uAD6C", "口", lambda p: (_rect(p, 100, 100, 900, 800),
                                    _rect(p, 100 + v, 100 + hz, 900 - v, 800 - hz, hole=True)), 1000)
        if not straight_samples_only:
            for i, ch in enumerate("가각과곽괄늙뷁히흐을의쀍"):
                top = 800 - (i % 4) * 90 if spread else 800
                add(f"u{ord(ch):04X}", ch, lambda p, top=top: _rect(p, 100, 50, 900, top), 1000)
    for ch in extra_letters:
        add(f"u{ord(ch):04X}", ch, lambda p: _rect(p, 80, 0, 480, CAP))
    fb = FontBuilder(1000, isTTF=True)
    order = list(glyphs)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    glyf = fb.font["glyf"]
    metrics = {}
    for name in order:
        glyph = glyf[name]
        glyph.recalcBounds(glyf)
        metrics[name] = (advances[name], getattr(glyph, "xMin", 0))
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=900, descent=-200)
    family_name = {"en": family, **({"ko": names_ko} if names_ko else {})}
    fb.setupNameTable({"familyName": family_name, "styleName": style,
                       "psName": f"{family.replace(' ', '')}-{style}", "manufacturer": "LapisLazuli tests"})
    fb.setupOS2(sTypoAscender=900, sTypoDescender=-200, usWinAscent=900, usWinDescent=200, achVendID="LLTS",
                usWeightClass=400)
    fb.setupPost()
    path.parent.mkdir(parents=True, exist_ok=True)
    fb.save(str(path))
    return path


def collection(path: Path, faces: list[Path]) -> Path:
    ttc = TTCollection()
    ttc.fonts = [TTFont(str(face)) for face in faces]
    ttc.save(str(path))
    return path
