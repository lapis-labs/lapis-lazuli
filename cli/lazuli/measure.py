"""Measure installed faces: PANOSE Latin Text digits and the CJK extension (vocab/type.yaml).

Outline bounds (heights, widths, advances) come from the font's own outlines in font units; stroke
thicknesses come from a FreeType raster at RASTER_PX pixels per em and are converted back to font
units. The font's own PANOSE bytes are never trusted.

Two ways to reach a face, recorded as metrics.method:
  file       fontTools reads the outlines and Pillow's FreeType draws the raster (`Face`); every face
             that has a file lazuli may open. Measurements stored before the key existed are file
             measurements, so MEASURER_VERSION did not change when it was added.
  coretext   Adobe Fonts (origin `adobe-sync`) are never opened as files. `coretext.CTFace` answers the
             same questions from Core Text metrics in font units and from glyphs the system draws into an
             in-memory grayscale bitmap at RASTER_PX (discarded after each measurement), and only the
             derived numbers below are stored. Nothing there returns an outline or a table, so
             pixel_outline is not checked (a Core Text face is never marked `pixel`, and its Latin
             contrast, bu_ratio, and CJK contrast are measured from the raster), the OS/2 values become
             metrics from Core Text traits (weight_class is the class nearest the weight trait, italic
             the italic trait), and `variable` and width_class are not recorded. See
             tests/test_coretext.py for the parity with the file method on the same synthetic faces.

Latin (vocab `panose_latin_text`):
  weight       WeightRat = CapH (H) / vertical stem of E. The stem is the leftmost ink run on rows
               between E's arms (20-40% and 60-80% of its height), median over those rows.
  proportion   monospaced when i, m, W, 0, and period share one advance width; otherwise ORat = height /
               width of O and PropRat = mean(E, S widths) / mean(O, H widths) with the vocab's rules.
  contrast     ConRat = narrowest / widest stroke of O. Rays from the counter's centre every 5 degrees
               measure the ring's thickness; narrowest and widest are the 5th and 95th percentiles.
               Thickness along a ray is radial, not perpendicular, which is close for an O.
  x_height     XRat = height of x / CapH, sized small / standard / large by the vocab thresholds; the
               constant / ducking half needs accented capitals: ducking when Á rises less than 10% of
               CapH above A (the capital was shortened to make room), constant otherwise. Without Á the
               digit is left out and only the size is recorded.
  serif        Not a PANOSE value: whether H's stems end in serifs (metrics.serif, see _serif).
               The fine serif-style digit is left to catalogs.
CJK (vocab `cjk_measurements`, measured on Hangul when present, else Han):
  bu_ratio     width at the top of the vertical stroke (max over its top 12%) / mid-stroke width, on
               the ㅣ of 이 (Hangul) or the vertical of 十 (Han, mid below the bar); `bu` at 1.35 or
               above. See _stroke_head_ratio for how the stroke is isolated.
  cjk_contrast horizontal / vertical stroke thickness in 口 (or ㅁ): the top bar's first ink run at
               mid-width over the left bar's first ink run at mid-height. Above 1 is reverse contrast;
               classes use the Latin contrast thresholds on min(value, 1 / value).
  square_spread std / mean of outline heights of structurally different syllables.
  weight_ratio_cjk_latin  (height of 口 / its vertical stem) / Latin WeightRat.
family_kind: symbol when the cmap has fewer than 20 Unicode letters (Lu, Ll, Lt, Lm, Lo) and covers
less than 90% of the assigned letters in its most-represented Unicode Script. Private Use and
Mathematical Alphanumeric Symbols are excluded; otherwise hand when a name hint says so, else text.
Both the letter categories and Script denominators use fontTools.unicodedata backed by the locked
unicodedata2 version; metrics.unicode_version records that version on each measured face.
Pixel outlines have only horizontal and vertical on-curve contour segments in sampled glyphs (including
O or 이); their Latin contrast, bu_ratio, and CJK contrast are unmeasured, not zero. Monospace is a
width attribute beside the measured serif/sans form. Hand and decorative forms are better labeled by
catalogs.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import statistics
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from lazuli import coretext

if TYPE_CHECKING:     # numpy, Pillow, and fontTools load only to measure: the session hook imports this module
    import numpy as np

MEASURER_VERSION = "0.3.1"
RASTER_PX = 512
HANGUL_SPREAD = "가각과곽괄늙뷁히흐을의쀍"
HAN_SPREAD = "国龍鬱永書風道間開寒"   # full-height characters only

logging.getLogger("fontTools").setLevel(logging.ERROR)


def _vocab() -> dict:
    import yaml

    from lapis_design import shared_dir

    return yaml.safe_load((shared_dir() / "vocab" / "type.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- glyph access

class Face:
    method = "file"

    def __init__(self, path: str, index: int):
        from fontTools.ttLib import TTFont
        from PIL import ImageFont

        coretext.refuse_adobe_file(path)
        self.font = TTFont(path, fontNumber=index, lazy=True)
        self.cmap = self.font.getBestCmap() or {}
        self.upm = self.font["head"].unitsPerEm
        self.glyphs = self.font.getGlyphSet()
        self.raster_font = ImageFont.truetype(path, RASTER_PX, index=index)
        self._bounds: dict[str, tuple | None] = {}

    def font_metrics(self) -> dict:
        """The face-level numbers the measurer records, from the head, fvar, and OS/2 tables."""
        metrics = {"upm": self.upm, "variable": "fvar" in self.font}
        if "OS/2" in self.font:
            os2 = self.font["OS/2"]
            metrics.update(weight_class=os2.usWeightClass, width_class=os2.usWidthClass,
                           italic=bool(os2.fsSelection & 1))
        return metrics

    def has(self, ch: str) -> bool:
        return ord(ch) in self.cmap

    def bounds(self, ch: str) -> tuple[float, float, float, float] | None:
        """(xMin, yMin, xMax, yMax) in font units."""
        if ch not in self._bounds:
            from fontTools.pens.boundsPen import BoundsPen

            if not self.has(ch):
                self._bounds[ch] = None
            else:
                pen = BoundsPen(self.glyphs)
                self.glyphs[self.cmap[ord(ch)]].draw(pen)
                self._bounds[ch] = pen.bounds
        return self._bounds[ch]

    def height(self, ch: str) -> float | None:
        b = self.bounds(ch)
        return b[3] - b[1] if b else None

    def width(self, ch: str) -> float | None:
        b = self.bounds(ch)
        return b[2] - b[0] if b else None

    def advance(self, ch: str) -> int | None:
        return self.font["hmtx"][self.cmap[ord(ch)]][0] if self.has(ch) else None

    def raster(self, ch: str) -> np.ndarray | None:
        """Ink mask of one glyph, cropped to its ink; rows run top to bottom."""
        import numpy as np
        from PIL import Image, ImageDraw

        if not self.has(ch):
            return None
        box = self.raster_font.getbbox(ch)
        if box[2] <= box[0] or box[3] <= box[1]:
            return None
        pad = 8
        image = Image.new("L", (box[2] - box[0] + 2 * pad, box[3] - box[1] + 2 * pad), 0)
        ImageDraw.Draw(image).text((pad - box[0], pad - box[1]), ch, font=self.raster_font, fill=255)
        ink = np.asarray(image) > 127
        rows, cols = np.where(ink)
        if not len(rows):
            return None
        return ink[rows.min():rows.max() + 1, cols.min():cols.max() + 1]

    def units(self, px: float) -> float:
        return px * self.upm / RASTER_PX


def _pixel_outline(face: Face) -> bool | None:
    """Inspect actual contours, not raster stair-steps; a curve sample must have ink to decide."""
    from fontTools.pens.recordingPen import DecomposingRecordingPen

    samples = [ch for ch in ("H", "O", "이", "口" if face.has("口") else "ㅁ") if face.bounds(ch)]
    if not any(ch in samples for ch in ("O", "이")):
        return None
    for ch in samples:
        pen = DecomposingRecordingPen(face.glyphs)
        face.glyphs[face.cmap[ord(ch)]].draw(pen)
        start = previous = None
        for op, points in pen.value:
            if op == "moveTo":
                start = previous = points[0]
            elif op in ("lineTo", "closePath"):
                point = points[0] if op == "lineTo" else start
                if previous is None or point is None or (previous[0] != point[0] and previous[1] != point[1]):
                    return False
                previous = point
            else:  # curves, open contours, or an unsupported outline
                return False
    return True


def _first_run(line: np.ndarray) -> int:
    """Length of the first ink run along a line of pixels."""
    import numpy as np

    idx = np.flatnonzero(line)
    if not len(idx):
        return 0
    breaks = np.flatnonzero(np.diff(idx) > 1)
    return int((breaks[0] + 1) if len(breaks) else len(idx))


# ---------------------------------------------------------------- Latin

def _bound_class(value: float, thresholds: dict[str, float]) -> str:
    for name, bound in thresholds.items():         # ordered from the highest bound down
        if value >= bound:
            return name
    return list(thresholds)[-1]


def _e_stem(face: Face) -> float | None:
    ink = face.raster("E")
    if ink is None:
        return None
    h = ink.shape[0]
    rows = [r for lo, hi in ((0.2, 0.4), (0.6, 0.8)) for r in range(int(lo * h), int(hi * h))]
    runs = [_first_run(ink[r]) for r in rows]
    runs = [r for r in runs if r]
    return face.units(statistics.median(runs)) if runs else None


def _o_contrast(face: Face) -> float | None:
    import numpy as np

    ink = face.raster("O")
    if ink is None:
        return None
    h, w = ink.shape
    cy, cx = h / 2, w / 2
    reach = int(max(h, w))
    thickness = []
    for angle in np.deg2rad(np.arange(0, 360, 5)):
        dy, dx = -np.sin(angle), np.cos(angle)
        inside = False
        start = None
        for step in range(reach):
            y, x = int(cy + dy * step), int(cx + dx * step)
            if not (0 <= y < h and 0 <= x < w):
                break
            if ink[y, x] and not inside:
                inside, start = True, step
            elif not ink[y, x] and inside:
                thickness.append(step - start)
                break
    if len(thickness) < 36:
        return None
    return float(np.percentile(thickness, 5) / np.percentile(thickness, 95))


def _serif(face: Face) -> bool | None:
    """Serifs on H: the left stem's foot, the widest first ink run in the bottom 6% of rows, is at
    least 1.3 times the stem at a quarter of the height. H rather than l, whose foot in monospaced
    sans faces is a bar, not a serif."""
    ink = face.raster("H")
    if ink is None:
        return None
    h = ink.shape[0]
    stem = _first_run(ink[int(h * 0.25)])
    foot = max(_first_run(ink[r]) for r in range(int(h * 0.94), h))
    return bool(stem and foot / stem >= 1.3)


def latin(face: Face, vocab: dict, *, pixel_outline: bool = False) -> tuple[dict, dict]:
    digits = {d["id"]: d for d in vocab["panose_latin_text"]}
    panose: dict = {}
    metrics: dict = {}
    cap = face.height("H")
    stem = _e_stem(face)
    if cap and stem:
        metrics["weight_rat"] = round(cap / stem, 3)
        panose["weight"] = _bound_class(cap / stem, digits["weight"]["thresholds"])
    advances = {face.advance(ch) for ch in "imW0."}
    if None not in advances and len(advances) == 1:
        panose["proportion"] = "monospaced"
        metrics["monospaced"] = True
    elif all(face.width(ch) for ch in "OHES"):
        o_rat = face.height("O") / face.width("O")
        prop_rat = (face.width("E") + face.width("S")) / (face.width("O") + face.width("H"))
        metrics.update(o_rat=round(o_rat, 3), prop_rat=round(prop_rat, 3), monospaced=False)
        panose["proportion"] = ("very-condensed" if o_rat >= 2.0 else "condensed" if o_rat >= 1.27
                                else "very-extended" if o_rat < 0.90 else "extended" if o_rat < 0.92
                                else "old-style" if prop_rat < 0.70 else "modern" if prop_rat < 0.83
                                else "even-width")
    if not pixel_outline:
        con = _o_contrast(face)
        if con is not None:
            metrics["con_rat"] = round(con, 3)
            panose["contrast"] = _bound_class(con, digits["contrast"]["thresholds"])
    x = face.height("x")
    if cap and x:
        x_rat = x / cap
        size = "small" if x_rat <= 0.50 else "standard" if x_rat <= 0.66 else "large"
        metrics.update(x_rat=round(x_rat, 3), x_height_size=size)
        a, a_acute = face.bounds("A"), face.bounds("Á")
        if a and a_acute:
            ducking = (a_acute[3] - a[3]) < 0.10 * cap
            panose["x_height"] = f"{'ducking' if ducking else 'constant'}-{size}"
    serif = _serif(face)
    if serif is not None:
        metrics["serif"] = serif
    return panose, metrics


# ---------------------------------------------------------------- CJK

def _stroke_head_ratio(ink: np.ndarray, pick: str) -> float | None:
    """Top width / mid width of one vertical stroke. The stroke is a group of adjacent columns
    whose ink covers at least half the glyph height (the rightmost group for the ㅣ of 이, the tallest
    for the vertical of 十). Its top width is the longest row run touching those columns within the
    top 12% of the stroke, so a bu-ri nub that reaches beyond the stem counts; its mid width is the
    run through the stroke's centre."""
    import numpy as np

    h = ink.shape[0]
    counts = ink.sum(axis=0)
    tall = np.flatnonzero(counts >= 0.5 * h)
    if not len(tall):
        return None
    groups = np.split(tall, np.flatnonzero(np.diff(tall) > 1) + 1)
    group = groups[-1] if pick == "right" else max(groups, key=lambda g: counts[g].sum())
    c0, c1 = int(group[0]), int(group[-1])
    rows = np.flatnonzero(ink[:, c0:c1 + 1].any(axis=1))
    top, bottom = int(rows.min()), int(rows.max())
    length = bottom - top + 1

    def run_through(r: int) -> int:
        line = ink[r]
        best = 0
        for part in np.split(np.flatnonzero(line), np.flatnonzero(np.diff(np.flatnonzero(line)) > 1) + 1):
            if len(part) and part[0] <= c1 and part[-1] >= c0:
                best = max(best, len(part))
        return best

    mid = run_through(top + length // 2) if pick == "right" else run_through(top + int(length * 0.8))
    head = max(run_through(r) for r in range(top, top + max(2, int(length * 0.12))))
    return head / mid if mid else None


def _bu_ratio(face: Face, script: str) -> float | None:
    ink = face.raster("이" if script == "hang" else "十")
    if ink is None:
        return None
    return _stroke_head_ratio(ink, "right" if script == "hang" else "tallest")


def _box_strokes(face: Face) -> tuple[float, float, float] | None:
    ch = "口" if face.has("口") else "ㅁ" if face.has("ㅁ") else None
    ink = face.raster(ch) if ch else None
    if ink is None:
        return None
    h, w = ink.shape
    vertical = _first_run(ink[h // 2])
    horizontal = _first_run(ink[:, w // 2])
    if not vertical or not horizontal:
        return None
    return face.units(horizontal), face.units(vertical), face.units(h)


def cjk(face: Face, vocab: dict, coverage: dict, weight_rat: float | None, *, pixel_outline: bool = False) -> dict:
    script = "hang" if coverage.get("hangul_syllables") else "hani" if coverage.get("han") else None
    if script is None:
        return {}
    out: dict = {"script": script}
    if not pixel_outline:
        bu = _bu_ratio(face, script)
        if bu is not None:
            out["bu_ratio"] = round(bu, 3)
            out["bu_class"] = "bu" if bu >= 1.35 else "min_bu"
    strokes = _box_strokes(face)
    if strokes:
        horizontal, vertical, box_height = strokes
        if not pixel_outline:
            value = horizontal / vertical
            out["cjk_contrast"] = round(value, 3)
            contrast = next(d for d in vocab["panose_latin_text"] if d["id"] == "contrast")["thresholds"]
            out["contrast_class"] = _bound_class(min(value, 1 / value), contrast)
            out["reverse_contrast"] = value > 1
        if weight_rat:
            out["weight_ratio_cjk_latin"] = round((box_height / vertical) / weight_rat, 3)
    heights = [h for ch in (HANGUL_SPREAD if script == "hang" else HAN_SPREAD) if (h := face.height(ch))]
    if len(heights) >= 5:
        out["square_spread"] = round(statistics.pstdev(heights) / statistics.mean(heights), 4)
    return out


LETTER_CATEGORIES = frozenset(("Lu", "Ll", "Lt", "Lm", "Lo"))
NAME_WORDS = re.compile(r"(?<=[a-z])(?=[A-Z])|[\s_\-\d]+")


@lru_cache(maxsize=1)
def _assigned_letter_counts() -> Counter[str]:
    """Count assigned letters with fontTools' locked Unicode category and Script data."""
    from fontTools import unicodedata as unicode_data

    counts: Counter[str] = Counter()
    for code in range(0x110000):
        if not 0x1D400 <= code <= 0x1D7FF:
            ch = chr(code)
            if unicode_data.category(ch) in LETTER_CATEGORIES:
                counts[unicode_data.script(ch)] += 1
    return counts


def _covers_small_script(cmap: dict[int, str]) -> bool:
    from fontTools import unicodedata as unicode_data

    by_script: Counter[str] = Counter()
    for code in cmap:
        if not 0x1D400 <= code <= 0x1D7FF:
            ch = chr(code)
            if unicode_data.category(ch) in LETTER_CATEGORIES:
                by_script[unicode_data.script(ch)] += 1
    if not by_script:
        return False
    script, present = by_script.most_common(1)[0]
    return present * 10 >= _assigned_letter_counts()[script] * 9


def _name_words(names: list[str]) -> set[str]:
    return {word.casefold() for name in names if name for word in NAME_WORDS.split(name) if word}

# ---------------------------------------------------------------- whole face

def _name_hints(vocab: dict, names: list[str]) -> list[str]:
    text = " ".join(n for n in names if n).casefold()
    words = _name_words(names)
    return [label for label, hints in vocab["name_hints"].items()
            if any(hint.casefold() in words if hint.isascii() else hint.casefold() in text
                   for hint in hints)]


def open_face(path: str, index: int, row: dict, provider: coretext.Provider | None = None):
    """The face a row describes. An `adobe-sync` row is an identity, not a path: it is opened only through the
    operating system's font list, never as a file."""
    if row.get("origin") != "adobe-sync":
        return Face(path, index)
    if provider is None:
        raise LookupError("Adobe Fonts are measured only through the operating system's font list")
    return provider.open(path, RASTER_PX)


def measure_face(path: str, index: int, row: dict, vocab: dict, *, provider: coretext.Provider | None = None) -> dict:
    face = open_face(path, index, row, provider)
    coverage = json.loads(row.get("coverage_json") or "{}")
    names = [row.get("family"), row.get("postscript_name"),
             *json.loads(row.get("names_i18n_json") or "{}").values()]
    hints = _name_hints(vocab, names)
    metrics = {**face.font_metrics(), "method": face.method}
    from fontTools import unicodedata as unicode_data
    metrics["unicode_version"] = unicode_data.unidata_version

    letter_count = sum(unicode_data.category(chr(code)) in LETTER_CATEGORIES
                       for code in face.cmap if not 0x1D400 <= code <= 0x1D7FF)
    metrics["letter_count"] = letter_count
    pixel_outline = _pixel_outline(face) if face.method == "file" else None      # contours are never read via Core Text
    if pixel_outline is not None:
        metrics["pixel_outline"] = pixel_outline
    panose: dict = {}
    if coverage.get("latin", 0) >= 52:
        panose, latin_metrics = latin(face, vocab, pixel_outline=pixel_outline is True)
        metrics.update(latin_metrics)
    cjk_values = cjk(face, vocab, coverage, metrics.get("weight_rat"), pixel_outline=pixel_outline is True)
    if hints:
        cjk_values = {**cjk_values, "name_hints": hints} if cjk_values else cjk_values
        metrics["name_hints"] = hints
    kind = ("symbol" if letter_count < 20 and not _covers_small_script(face.cmap)
            else "hand" if "hand" in hints else "text")
    return {"family_kind": kind, "panose_json": json.dumps(panose) if panose else None,
            "cjk_json": json.dumps(cjk_values, ensure_ascii=False) if cjk_values else None,
            "metrics_json": json.dumps(metrics, ensure_ascii=False)}


def measure_pending(conn: sqlite3.Connection, *, limit: int | None = None) -> tuple[int, list[str]]:
    """Measure faces without a measurement from this measurer version. Returns (measured, failures). Adobe
    Fonts faces (origin `adobe-sync`) go through Core Text and wait, unmeasured, while it is not available
    (another platform, or `LAZULI_FONT_ROOTS` set)."""
    vocab = _vocab()
    rows = conn.execute(
        """SELECT lf.* FROM local_font lf
           WHERE NOT EXISTS (SELECT 1 FROM measurement m WHERE m.local_font_id = lf.id
                             AND m.measurer_version = ?) ORDER BY lf.id""", (MEASURER_VERSION,)).fetchall()
    if limit is not None:
        rows = rows[:limit]
    failures = []
    measured = 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    provider = None
    if any(row["origin"] == "adobe-sync" for row in rows):
        try:
            provider = coretext.provider()                # one listing for the whole run
        except Exception as exc:
            failures.append(f"Adobe Fonts: {type(exc).__name__} opening Core Text")
    for row in rows:
        data = dict(row)
        if data["origin"] == "adobe-sync":
            if provider is None:
                continue
            arguments = {"provider": provider}
        else:
            arguments = {}
        try:
            values = measure_face(data["path"], data["face_index"], data, vocab, **arguments)
        except Exception as exc:                  # one unreadable face must not stop the rest
            # recorded once per measurer version, so it is not retried on every run
            failures.append(f"{Path(data['path']).name}#{data['face_index']}: {type(exc).__name__}")
            values = {"family_kind": None, "panose_json": None, "cjk_json": None,
                      "metrics_json": json.dumps({"unmeasurable": type(exc).__name__})}
        conn.execute("DELETE FROM measurement WHERE local_font_id = ?", (data["id"],))
        conn.execute("""INSERT INTO measurement (local_font_id, measurer_version, family_kind, panose_json,
                          cjk_json, metrics_json, measured_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                     (data["id"], MEASURER_VERSION, values["family_kind"], values["panose_json"],
                      values["cjk_json"], values["metrics_json"], now))
        measured += values["family_kind"] is not None
        if measured % 100 == 0:
            conn.commit()
    conn.commit()
    return measured, failures
