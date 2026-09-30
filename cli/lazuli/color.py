"""`lazuli color lookup|record` and `lazuli search --type color`: color system codes, links, and values.

The spec path and the detection path never mix (vocab/color.yaml `value_source_classes`):

lookup   normalizes and validates a code of one of the code systems in vocab/color.yaml and gives the
         system's reference link from the source registry. Only coordinate codes get computed values:
         freieFarbe HLC and RAL DESIGN SYSTEM plus codes are CIE LCh positions, converted to OKLCH and
         labeled `computed` (approximate, never a spec value). Pantone, RAL CLASSIC, NCS, Munsell, and
         Freetone are codes and links only; their values come only from the user's own records.
record   keeps a value the user has for a code (provider data, a measurement, or a screen sample) in
         the lazuli database in the user cache, never in a project. A screen sample is always
         `detection_only`; provider and measured values may be `spec`.
search   a color value (hex or CSS color) returns the nearest candidates: computed HLC and RAL DESIGN
         SYSTEM plus codes and the user's recorded values, each with its ΔE_OK. A nearest candidate is
         never an identity. A system code routes to lookup.

Conversion: HLC codes read CIE LCh(ab) under D50/2° (the CSS lch() interpretation): Lab → XYZ D50
→ linear Bradford adaptation → XYZ D65 → Oklab → OKLCH. RAL DESIGN SYSTEM plus reads CIE LCh(ab)
under D65/10° (X 94.811, Y 100, Z 107.304): Lab → XYZ, then Oklab without chromatic adaptation.
Every matrix is derived here from its definition: sRGB primaries and the D50/D65 white points as
CSS Color 4 gives them, the Bradford cone matrix, and Ottosson's 2021 linear-sRGB → LMS and
LMS → Oklab coefficients, so XYZ → LMS is consistent with the linear-sRGB path the Pantone
reference derivation uses (#336699 → oklch(0.49931445 0.09866436 250.43305)).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import yaml

from lapis_design import shared_dir
from lapis_design.render.color import delta_e_ok, to_oklch
from lazuli import db, paths, sources

# ---------------------------------------------------------------- conversion math

Matrix = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
Vector = tuple[float, float, float]

_EPSILON = 216 / 24389                     # CIE Lab constants as exact ratios (CSS Color 4)
_KAPPA = 24389 / 27
OKLCH_POWERLESS = 0.000004                 # chroma at or below this has no meaningful hue
LAB_POWERLESS = 0.0001


def _white(x: float, y: float) -> Vector:
    return (x / y, 1.0, (1 - x - y) / y)


D50 = _white(0.3457, 0.3585)
D65 = _white(0.3127, 0.3290)
D65_10 = (94.811 / 100, 1.0, 107.304 / 100)  # RAL DESIGN SYSTEM plus Lab reference white, 10° observer
_SRGB_PRIMARIES = ((0.64, 0.33), (0.30, 0.60), (0.15, 0.06))
_BRADFORD: Matrix = ((0.8951, 0.2664, -0.1614),
                     (-0.7502, 1.7135, 0.0367),
                     (0.0389, -0.0685, 1.0296))
_SRGB_TO_LMS: Matrix = ((0.4122214708, 0.5363325363, 0.0514459929),
                        (0.2119034982, 0.6806995451, 0.1073969566),
                        (0.0883024619, 0.2817188376, 0.6299787005))
_LMS_TO_OKLAB: Matrix = ((0.2104542553, 0.7936177850, -0.0040720468),
                         (1.9779984951, -2.4285922050, 0.4505937099),
                         (0.0259040371, 0.7827717662, -0.8086757660))


def _mv(m: Matrix, v: Vector) -> Vector:
    return tuple(r[0] * v[0] + r[1] * v[1] + r[2] * v[2] for r in m)


def _mm(a: Matrix, b: Matrix) -> Matrix:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _inv(m: Matrix) -> Matrix:
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return ((( e * i - f * h) / det, -(b * i - c * h) / det, ( b * f - c * e) / det),
            (-(d * i - f * g) / det, ( a * i - c * g) / det, -(a * f - c * d) / det),
            (( d * h - e * g) / det, -(a * h - b * g) / det, ( a * e - b * d) / det))


def _diag(v: Vector) -> Matrix:
    return ((v[0], 0.0, 0.0), (0.0, v[1], 0.0), (0.0, 0.0, v[2]))


def _bradford(source: Vector, target: Vector) -> Matrix:
    """Linear Bradford chromatic adaptation from one white to another."""
    cone_s, cone_t = _mv(_BRADFORD, source), _mv(_BRADFORD, target)
    return _mm(_inv(_BRADFORD), _mm(_diag(tuple(t / s for s, t in zip(cone_s, cone_t))), _BRADFORD))


def _rgb_to_xyz(primaries, white: Vector) -> Matrix:
    """RGB → XYZ from xy primaries: the primaries' XYZ columns, each scaled so RGB 1,1,1 is the white."""
    columns = tuple(zip(*(_white(x, y) for x, y in primaries)))
    return _mm(columns, _diag(_mv(_inv(columns), white)))


D50_TO_D65 = _bradford(D50, D65)
D65_TO_D50 = _bradford(D65, D50)
SRGB_TO_XYZ = _rgb_to_xyz(_SRGB_PRIMARIES, D65)
_XYZ_TO_LMS = _mm(_SRGB_TO_LMS, _inv(SRGB_TO_XYZ))
_LMS_TO_XYZ = _inv(_XYZ_TO_LMS)
_OKLAB_TO_LMS = _inv(_LMS_TO_OKLAB)


def _lab_to_xyz(l: float, a: float, b: float, white: Vector) -> Vector:
    fy = (l + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    x = fx ** 3 if fx ** 3 > _EPSILON else (116 * fx - 16) / _KAPPA
    y = fy ** 3 if l > _KAPPA * _EPSILON else l / _KAPPA
    z = fz ** 3 if fz ** 3 > _EPSILON else (116 * fz - 16) / _KAPPA
    return (x * white[0], y * white[1], z * white[2])


def _xyz_to_lab(xyz: Vector, white: Vector) -> Vector:
    def f(t: float) -> float:
        return math.cbrt(t) if t > _EPSILON else (_KAPPA * t + 16) / 116
    fx, fy, fz = (f(v / w) for v, w in zip(xyz, white))
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _polar(a: float, b: float, powerless: float) -> tuple[float, float | None]:
    chroma = math.hypot(a, b)
    if chroma <= powerless:
        return 0.0, None
    return chroma, math.degrees(math.atan2(b, a)) % 360


def _cartesian(c: float, h: float | None) -> tuple[float, float]:
    if h is None:
        return 0.0, 0.0
    return c * math.cos(math.radians(h)), c * math.sin(math.radians(h))


def _oklab_from_xyz_d65(xyz: Vector) -> Vector:
    return _mv(_LMS_TO_OKLAB, tuple(math.cbrt(v) for v in _mv(_XYZ_TO_LMS, xyz)))


def _xyz_d65_from_oklab(lab: Vector) -> Vector:
    return _mv(_LMS_TO_XYZ, tuple(v ** 3 for v in _mv(_OKLAB_TO_LMS, lab)))


def lch_d50_to_oklch(l: float, c: float, h: float | None) -> tuple[float, float, float | None]:
    """CIE LCh(ab) D50/2° → OKLCH D65: Lab → XYZ D50 → Bradford → XYZ D65 → Oklab → polar."""
    a, b = _cartesian(c, h)
    ok = _oklab_from_xyz_d65(_mv(D50_TO_D65, _lab_to_xyz(l, a, b, D50)))
    chroma, hue = _polar(ok[1], ok[2], OKLCH_POWERLESS)
    return ok[0], chroma, hue


def lch_d65_10_to_oklch(l: float, c: float, h: float | None) -> tuple[float, float, float | None]:
    """CIE LCh(ab) D65/10° → OKLCH: Lab → XYZ with the D65/10° white, no chromatic adaptation."""
    a, b = _cartesian(c, h)
    ok = _oklab_from_xyz_d65(_lab_to_xyz(l, a, b, D65_10))
    chroma, hue = _polar(ok[1], ok[2], OKLCH_POWERLESS)
    return ok[0], chroma, hue


def oklch_to_lch_d50(l: float, c: float, h: float | None) -> tuple[float, float, float | None]:
    """OKLCH D65 → CIE LCh(ab) D50/2°, the inverse of `lch_d50_to_oklch`."""
    a, b = _cartesian(c, h)
    lab = _xyz_to_lab(_mv(D65_TO_D50, _xyz_d65_from_oklab((l, a, b))), D50)
    chroma, hue = _polar(lab[1], lab[2], LAB_POWERLESS)
    return lab[0], chroma, hue


def oklch_to_lch_d65_10(l: float, c: float, h: float | None) -> tuple[float, float, float | None]:
    """OKLCH D65 → CIE LCh(ab) D65/10°, the inverse of `lch_d65_10_to_oklch`."""
    a, b = _cartesian(c, h)
    lab = _xyz_to_lab(_xyz_d65_from_oklab((l, a, b)), D65_10)
    chroma, hue = _polar(lab[1], lab[2], LAB_POWERLESS)
    return lab[0], chroma, hue


def srgb_hex_to_oklch(value: str) -> tuple[float, float, float | None]:
    """Opaque #RRGGBB → OKLCH through linear sRGB and Ottosson's direct coefficients (no gamut mapping)."""
    rgb = tuple(int(value.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    linear = tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)
    ok = _mv(_LMS_TO_OKLAB, tuple(math.cbrt(v) for v in _mv(_SRGB_TO_LMS, linear)))
    chroma, hue = _polar(ok[1], ok[2], OKLCH_POWERLESS)
    return ok[0], chroma, hue


def css_oklch(oklch) -> str:
    l, c, h = oklch
    return f"oklch({l:.4f} {c:.4f} {'none' if h is None else f'{h:.2f}'})"


def _distance(a, b) -> float:
    return delta_e_ok([a[0], a[1], a[2] or 0.0], [b[0], b[1], b[2] or 0.0])


# ---------------------------------------------------------------- systems and codes

_VOCAB = yaml.safe_load((shared_dir() / "vocab" / "color.yaml").read_text(encoding="utf-8"))
SYSTEMS = {s["id"]: s for s in _VOCAB["systems"] if s["store"] != "name-and-value"}   # the code systems
COMPUTED = ("hlc", "ral-design-plus")        # codes that are CIE LCh coordinates
ALIASES = {"pms": "pantone", "ral-design": "ral-design-plus", "ral-design-system-plus": "ral-design-plus",
           "rdsp": "ral-design-plus", "freiefarbe": "hlc", "freiefarbe-hlc": "hlc"}
LABELS = {"pantone": "Pantone", "ral-classic": "RAL CLASSIC", "ral-design-plus": "RAL DESIGN SYSTEM plus",
          "ncs": "NCS", "munsell": "Munsell", "hlc": "freieFarbe HLC", "freetone": "Freetone"}
SOURCE_CLASSES = ("provider", "screen-sample", "measured")
USES = ("spec", "detection_only")


class CodeError(ValueError):
    """The code is not a valid code of the system."""


@dataclass
class Code:
    system: str
    code: str                                  # the normalized code, as stored
    complete: bool = True
    problem: str | None = None                 # why an incomplete code is not a usable spec
    fields: dict = field(default_factory=dict)  # parsed parts (hue, lightness, chroma, suffix, library, ...)


def _title(system: str, code: str) -> str:
    """How a code reads to people: `Pantone 185 C`, `RAL 180 40 20 (RAL DESIGN SYSTEM plus)`."""
    return f"Pantone {code}" if system == "pantone" else f"{code} ({LABELS[system]})"


def _clean(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.replace("®", "").replace("™", "")).strip().upper()


def _hlc(raw: str) -> Code:
    text = _clean(raw)
    match = (re.fullmatch(r"(?:HLC ?)?H ?(\d{1,3}) ?L ?(\d{1,3}) ?C ?(\d{1,3})", text)
             or re.fullmatch(r"(?:HLC ?)?(\d{1,3}) (\d{1,3}) (\d{1,3})", text)
             or re.fullmatch(r"(?:HLC ?)?(\d{3})(\d{2})(\d{2})", text))
    if not match:
        raise CodeError(f"{raw!r} is not an HLC code; write hue, lightness, chroma as H040 L60 C40")
    h, l, c = map(int, match.groups())
    if h >= 360 or l > 100:
        raise CodeError(f"{raw!r}: hue must be below 360 and lightness at most 100")
    return Code("hlc", f"H{h:03d} L{l:02d} C{c:02d}", fields={"hue": h, "lightness": l, "chroma": c})


def _ral_design(raw: str) -> Code:
    text = _clean(raw)
    match = re.fullmatch(r"(?:RAL ?)?(?:DESIGN(?: ?SYSTEM)?(?: ?PLUS)? ?)?(\d{3}) ?(\d{2}) ?(\d{2})", text)
    if not match:
        raise CodeError(f"{raw!r} is not a RAL DESIGN SYSTEM plus code; it has seven digits: RAL 180 40 20")
    h, l, c = map(int, match.groups())
    if h > 360:
        raise CodeError(f"{raw!r}: the hue field runs from 000 to 360")
    return Code("ral-design-plus", f"RAL {h:03d} {l:02d} {c:02d}", fields={"hue": h, "lightness": l, "chroma": c})


def _ral_classic(raw: str) -> Code:
    match = re.fullmatch(r"(?:RAL ?)?(?:CLASSIC ?)?([1-9]\d{3})", _clean(raw))
    if not match:
        raise CodeError(f"{raw!r} is not a RAL CLASSIC code; it has four digits, the first 1 to 9: RAL 3020")
    return Code("ral-classic", f"RAL {match.group(1)}")


_NCS_ORDER = "YRBG"


def _ncs(raw: str) -> Code:
    match = re.fullmatch(r"(?:NCS ?)?(?:(S) ?)?(\d{2})(\d{2}) ?- ?(N|[YRBG](?:\d{2}[YRBG])?)", _clean(raw))
    if not match:
        raise CodeError(f"{raw!r} is not an NCS notation; write it as NCS S 1040-R20B")
    edition, black, chromatic, hue = match.group(1), int(match.group(2)), int(match.group(3)), match.group(4)
    if black + chromatic > 100:
        raise CodeError(f"{raw!r}: blackness {black} and chromaticness {chromatic} add up to more than 100")
    if hue == "N" and chromatic:
        raise CodeError(f"{raw!r}: a neutral (N) has chromaticness 00")
    if hue != "N" and not chromatic:
        raise CodeError(f"{raw!r}: chromaticness 00 is a neutral; write the hue as N")
    if len(hue) == 4:
        first, share, second = hue[0], int(hue[1:3]), hue[3]
        if _NCS_ORDER[(_NCS_ORDER.index(first) + 1) % 4] != second or not 0 < share < 100:
            raise CodeError(f"{raw!r}: a hue runs from one elementary color to the next (Y→R→B→G→Y) "
                            "with a share from 01 to 99, as in R20B")
    code = f"NCS {'S ' if edition else ''}{black:02d}{chromatic:02d}-{hue}"
    return Code("ncs", code, fields={"blackness": black, "chromaticness": chromatic, "hue": hue,
                                     "standard_sample": bool(edition)})


_MUNSELL_FAMILIES = ("R", "YR", "Y", "GY", "G", "BG", "B", "PB", "P", "RP")


def _num(value: str) -> str:
    return f"{float(value):g}"


def _munsell(raw: str) -> Code:
    text = _clean(raw)
    if neutral := re.fullmatch(r"N ?(\d+(?:\.\d+)?) ?(?:/ ?0?)?", text):
        value = float(neutral.group(1))
        if value > 10:
            raise CodeError(f"{raw!r}: Munsell value runs from 0 to 10")
        return Code("munsell", f"N {_num(neutral.group(1))}/", fields={"value": value})
    match = re.fullmatch(r"(\d+(?:\.\d+)?) ?(RP|YR|GY|BG|PB|R|Y|G|B|P) ?(\d+(?:\.\d+)?) ?/ ?(\d+(?:\.\d+)?)", text)
    if not match:
        raise CodeError(f"{raw!r} is not a Munsell notation; write hue value/chroma as 5R 4/14, or N 5/ for a neutral")
    step, family, value, chroma = match.groups()
    if not 0 < float(step) <= 10 or float(value) > 10:
        raise CodeError(f"{raw!r}: the hue step runs above 0 up to 10 and the value from 0 to 10")
    return Code("munsell", f"{_num(step)}{family} {_num(value)}/{_num(chroma)}",
                fields={"hue": f"{_num(step)}{family}", "value": float(value), "chroma": float(chroma)})


# Suffixes name the library; FHI libraries are recorded by their product label, never expanded.
PANTONE_LIBRARIES = {
    "C": "Graphics, coated", "U": "Graphics, uncoated", "M": "Graphics, matte",
    "CP": "Color Bridge coated process simulation", "UP": "Color Bridge uncoated process simulation",
    "XGC": "Extended Gamut coated",
    "TCX": "FHI Cotton TCX", "TPG": "FHI Paper TPG", "TPX": "FHI Paper TPX", "TSX": "FHI TSX", "TN": "FHI TN",
}
_FHI = ("TCX", "TPG", "TPX", "TSX", "TN")
_PANTONE_INCOMPLETE = ("a Pantone code without its suffix is an incomplete spec: the suffix names the library "
                       "and stock ({examples}). Copy the suffix from the source; never infer it")


def _pantone(raw: str) -> Code:
    text = re.sub(r"^(?:PANTONE|PMS)\b ?", "", _clean(raw))
    suffixes = "|".join(sorted(PANTONE_LIBRARIES, key=len, reverse=True))
    match = (re.fullmatch(rf"(.+?) ({suffixes})", text)
             or re.fullmatch(rf"(\d{{3,5}}|\d{{2}}-\d{{4}}|P ?\d{{1,3}}-\d{{1,2}})({suffixes})", text))
    body, suffix = (match.group(1), match.group(2)) if match else (text, None)
    body = re.sub(r"^P ?(\d)", r"P \1", body)
    if re.fullmatch(r"\d{2}-\d{4}", body):
        kind = "fhi"
    elif re.fullmatch(r"\d{3,5}", body):
        kind = "graphics"
    elif re.fullmatch(r"P \d{1,3}-\d{1,2}", body):
        kind = "cmyk-guide"
    elif re.fullmatch(r"[A-Z][A-Z ]*[A-Z](?: \d{1,4})?", body):
        kind, body = "named", body.title()
    else:
        raise CodeError(f"{raw!r} is not a Pantone code; write the number or name with its suffix, "
                        "as in 185 C or 19-4052 TCX")
    if suffix is None:
        examples = (f"{body} TCX cotton, {body} TPG paper" if kind == "fhi"
                    else f"{body} C coated, {body} U uncoated, {body} CP process simulation")
        return Code("pantone", body, complete=False, problem=_PANTONE_INCOMPLETE.format(examples=examples),
                    fields={"kind": kind})
    if (kind == "fhi") != (suffix in _FHI):
        raise CodeError(f"{raw!r}: " + ("an FHI number (NN-NNNN) takes an FHI library suffix (TCX, TPG, TPX, TSX, TN)"
                                         if kind == "fhi" else f"{suffix} is an FHI library suffix; FHI numbers look like 19-4052"))
    if kind == "cmyk-guide" and suffix not in ("C", "U"):
        raise CodeError(f"{raw!r}: CMYK guide codes (P 1-8) take C or U")
    library = (f"CMYK guide, {'coated' if suffix == 'C' else 'uncoated'}" if kind == "cmyk-guide"
               else PANTONE_LIBRARIES[suffix])
    return Code("pantone", f"{body} {suffix}", fields={"kind": kind, "suffix": suffix, "library": library})


def _freetone(raw: str) -> Code:
    text = re.sub(r"^FREETONE\b ?", "", _clean(raw))
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9 .\-]*", text):
        raise CodeError(f"{raw!r} is not a Freetone code (letters, digits, spaces, dots, and hyphens)")
    return Code("freetone", text)


PARSERS = {"pantone": _pantone, "ral-classic": _ral_classic, "ral-design-plus": _ral_design, "ncs": _ncs,
           "munsell": _munsell, "hlc": _hlc, "freetone": _freetone}


def system_id(name: str, raw: str = "") -> str:
    """A vocab system id from a name or alias; `ral` picks the collection by the code's digit count."""
    name = name.strip().lower()
    if name == "ral":
        return "ral-design-plus" if len(re.sub(r"\D", "", raw)) == 7 else "ral-classic"
    name = ALIASES.get(name, name)
    if name not in SYSTEMS:
        raise CodeError(f"unknown color system {name!r}; code systems: {', '.join(SYSTEMS)} (and ral)")
    if name not in PARSERS:
        raise CodeError(f"lazuli cannot read {name} codes yet")
    return name


def normalize(system: str, raw: str) -> Code:
    return PARSERS[system_id(system, raw)](raw)


_DETECT = (
    (r"(PANTONE|PMS)\b.*", "pantone"),
    (r"(\d{3,5}|\d{2}-\d{4}) ?(C|U|M|CP|UP|XGC|TCX|TPG|TPX|TSX|TN)", "pantone"),
    (r"RAL ?(CLASSIC ?)?\d{4}", "ral-classic"),
    (r"RAL ?(DESIGN( ?SYSTEM)?( ?PLUS)? ?)?\d{3} ?\d{2} ?\d{2}", "ral-design-plus"),
    (r"(NCS ?)?(S ?)?\d{4} ?-.*|NCS\b.*", "ncs"),
    (r"HLC\b.*|H ?\d{1,3} ?L ?\d{1,3} ?C ?\d{1,3}", "hlc"),
    (r"\d+(\.\d+)? ?(RP|YR|GY|BG|PB|R|Y|G|B|P) ?\d+(\.\d+)? ?/ ?\d+(\.\d+)?|N ?\d+(\.\d+)? ?/ ?0?", "munsell"),
    (r"FREETONE\b.*", "freetone"),
)


def detect_system(text: str) -> str | None:
    """The code system a free-form query names, or None when it is not a system code."""
    cleaned = _clean(text)
    return next((system for pattern, system in _DETECT if re.fullmatch(pattern, cleaned)), None)


# ---------------------------------------------------------------- color values

_HEX = re.compile(r"#?([0-9a-fA-F]{6})|#([0-9a-fA-F]{3})")


def parse_hex(text: str) -> str | None:
    """#RRGGBB (uppercase) for a six-digit hex with or without # or a three-digit one with #."""
    match = _HEX.fullmatch(text.strip())
    if not match:
        return None
    digits = match.group(1) or "".join(ch * 2 for ch in match.group(2))
    return "#" + digits.upper()


def parse_color(text: str) -> tuple[float, float, float | None] | None:
    """OKLCH of a hex or CSS color (oklch() at full precision; other CSS forms through the render parser)."""
    text = text.strip()
    if hex_value := parse_hex(text):
        return srgb_hex_to_oklch(hex_value)
    if match := re.fullmatch(r"oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+|none)\s*(?:/\s*[\d.]+%?\s*)?\)", text, re.I):
        l = float(match.group(1)) / (100 if match.group(2) else 1)
        h = None if match.group(4).lower() == "none" else float(match.group(4)) % 360
        c, h = (0.0, None) if float(match.group(3)) <= OKLCH_POWERLESS else (float(match.group(3)), h)
        return l, c, h
    if re.fullmatch(r"(rgba?|hsla?|hwb|lab|lch|oklab|color)\(.*\)", text, re.I) and (value := to_oklch(text)):
        return value[0], value[1], value[2] if value[1] > OKLCH_POWERLESS else None
    return None


def _oklch_arg(values: list[str]) -> tuple[float, float, float | None]:
    try:
        l = float(values[0].rstrip("%")) / (100 if values[0].endswith("%") else 1)
        c, h = float(values[1]), (None if values[2].lower() == "none" else float(values[2]) % 360)
    except ValueError:
        raise CodeError(f"--oklch takes three numbers L C H, as in 0.62 0.14 40 (got {' '.join(values)})") from None
    if not 0 <= l <= 1 or c < 0:
        raise CodeError("--oklch lightness runs from 0 to 1 (or 0% to 100%) and chroma is 0 or more")
    return (l, 0.0, None) if c <= OKLCH_POWERLESS or h is None else (l, c, h)


# ---------------------------------------------------------------- records (the user's own values)

def _records(system: str | None = None, code: str | None = None) -> list[dict]:
    """The user's recorded values; none when the database does not exist yet (lookups never create it)."""
    path = paths.db_path()
    if not path.exists():
        return []
    conn = db.connect(path)
    try:
        rows = conn.execute(
            """SELECT * FROM color_record WHERE (? IS NULL OR system = ?) AND (? IS NULL OR code = ?)
               ORDER BY system, code, use, source_class""", (system, system, code, code)).fetchall()
    finally:
        conn.close()
    return [{"system": r["system"], "code": r["code"], "source_class": r["source_class"], "use": r["use"],
             "oklch": [r["l"], r["c"], r["h"]], "hex": r["hex"], "note": r["note"],
             "recorded_at": r["recorded_at"]} for r in rows]


def record(code: Code, oklch, *, source_class: str, use: str, hex_value: str | None, note: str | None) -> bool:
    """Store (or replace) the user's value of one source class for a code; True when it replaced one."""
    conn = db.connect(paths.db_path())
    try:
        replaced = conn.execute("SELECT 1 FROM color_record WHERE system = ? AND code = ? AND source_class = ?",
                                (code.system, code.code, source_class)).fetchone() is not None
        conn.execute(
            """INSERT INTO color_record (system, code, source_class, use, l, c, h, hex, note, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (system, code, source_class) DO UPDATE SET use = excluded.use, l = excluded.l,
                 c = excluded.c, h = excluded.h, hex = excluded.hex, note = excluded.note,
                 recorded_at = excluded.recorded_at""",
            (code.system, code.code, source_class, use, *oklch, hex_value, note,
             datetime.now(timezone.utc).isoformat(timespec="seconds")))
        conn.commit()
    finally:
        conn.close()
    return replaced


# ---------------------------------------------------------------- lookup

METHOD = {
    "hlc": ("the code's H/L/C read as CIE LCh(ab) D50/2° (the CSS lch() interpretation); "
            "Lab → XYZ D50 → linear Bradford → XYZ D65 → Oklab → OKLCH"),
    "ral-design-plus": ("the code's H/L/C read as CIE LCh(ab) D65/10° (X 94.811, Y 100, Z 107.304); "
                        "Lab → XYZ D65 → Oklab → OKLCH with no chromatic adaptation"),
}
NOTES = {
    "hlc": "HLC codes are CIELAB LCh coordinates under D50/2°",
    "ral-design-plus": SYSTEMS["ral-design-plus"]["note"],
}


def computed(code: Code) -> dict | None:
    """The approximate OKLCH of a coordinate code, labeled computed; None for systems without coordinates."""
    if code.system not in COMPUTED:
        return None
    f = code.fields
    convert = lch_d50_to_oklch if code.system == "hlc" else lch_d65_10_to_oklch
    oklch = convert(f["lightness"], f["chroma"], f["hue"] if f["chroma"] else None)
    return {"oklch": list(oklch), "css": css_oklch(oklch), "source_class": "computed", "approximate": True,
            "spec": False, "method": METHOD[code.system], "note": NOTES[code.system]}


def lookup(code: Code) -> dict:
    system = SYSTEMS[code.system]
    reference = sources.for_color_system(code.system)
    if reference is not None:
        reference = {k: reference[k] for k in ("id", "name", "url", "access", "reason") if k in reference}
    return {"system": code.system, "system_name": LABELS[code.system], "code": code.code,
            "title": _title(code.system, code.code),
            "complete": code.complete, "problem": code.problem, "fields": code.fields,
            "store": system["store"], "values_from": system["values_from"], "reference": reference,
            "computed": computed(code) if code.complete else None,
            "records": _records(code.system, code.code) if code.complete else []}


def _values_line(result: dict) -> str:
    if result["computed"]:
        return "values: computed from the code (approximate, never a spec value)"
    return (f"values: this repository keeps {LABELS[result['system']]} codes and links only; values come only "
            "from your own records (`lazuli color record`)")


def _record_line(r: dict) -> str:
    use = "spec" if r["use"] == "spec" else "detection only"
    extra = "  ".join(x for x in (r["hex"], r["recorded_at"][:10], r["note"]) if x)
    return f"  {r['source_class']:13} {use:14} {css_oklch(r['oklch'])}  {extra}"


def render_lookup(result: dict) -> str:
    head = _title(result["system"], result["code"])
    if library := result["fields"].get("library"):
        head += f": {library}"
    lines = [head]
    if not result["complete"]:
        lines.append(result["problem"])
    if ref := result["reference"]:
        how = {"read": "lazuli read may fetch it", "adapter": "a lazuli catalog reads it"}.get(
            ref["access"], f"{ref['access']}: {ref.get('reason', '')}".rstrip(": "))
        lines.append(f"reference: {ref['name']} <{ref['url']}> ({how})")
    if not result["complete"]:
        return "\n".join(lines)
    lines.append(_values_line(result))
    if comp := result["computed"]:
        lines.append(f"  computed {comp['css']}  ({comp['note']})")
        lines.append(f"  method: {comp['method']}")
    if result["records"]:
        lines.append("your records (user cache):")
        lines.extend(_record_line(r) for r in result["records"])
    else:
        lines.append("your records: none")
    return "\n".join(lines)


def _lookup_cmd(args) -> int:
    try:
        code = normalize(args.system, args.code)
    except CodeError as exc:
        print(f"lazuli color lookup: {exc}", file=sys.stderr)
        return 2
    result = lookup(code)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_lookup(result))
    return 0 if code.complete else 1


def _record_cmd(args) -> int:
    try:
        code = normalize(args.system, args.code)
        if not code.complete:
            raise CodeError(f"{_title(code.system, code.code)}: {code.problem}; a record needs the full code")
        allowed = set(SYSTEMS[code.system]["values_from"]) & set(SOURCE_CLASSES)
        if not allowed:
            raise CodeError(f"{LABELS[code.system]} has no recordable class")
        if args.source_class not in allowed:
            raise CodeError(f"{LABELS[code.system]} does not allow {args.source_class} values")
        if (args.oklch is None) == (args.hex is None):
            raise CodeError("give the value once: --oklch L C H or --hex RRGGBB")
        hex_value = None
        if args.hex is not None:
            hex_value = parse_hex(args.hex)
            if hex_value is None or len(args.hex.lstrip("#")) != 6:
                raise CodeError(f"--hex takes six hex digits RRGGBB (got {args.hex!r})")
            oklch = srgb_hex_to_oklch(hex_value)
        else:
            oklch = _oklch_arg(args.oklch)
        use = args.use or ("detection_only" if args.source_class == "screen-sample" else "spec")
        if args.source_class == "screen-sample" and use != "detection_only":
            raise CodeError("a screen sample is detection only; it never becomes a spec value")
    except CodeError as exc:
        print(f"lazuli color record: {exc}", file=sys.stderr)
        return 2
    replaced = record(code, oklch, source_class=args.source_class, use=use, hex_value=hex_value, note=args.note)
    out = {"system": code.system, "code": code.code, "source_class": args.source_class, "use": use,
           "oklch": list(oklch), "hex": hex_value, "note": args.note, "replaced": replaced,
           "database": str(paths.db_path())}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        verb = "replaced" if replaced else "recorded"
        shown = css_oklch(oklch) + (f" ({hex_value})" if hex_value else "")
        print(f"{verb} {_title(code.system, code.code)}: {args.source_class} value {shown} as "
              f"{'spec' if use == 'spec' else 'detection only'}")
        print(f"kept in the lazuli database ({out['database']}), a user cache that never goes into a project")
    return 0


def main(argv: list[str], prog: str = "lazuli color") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Color system codes: normalize and look up codes, and keep "
                                 "your own values for them in the lazuli database.")
    sub = ap.add_subparsers(dest="command", required=True)
    systems = ", ".join([*SYSTEMS, "ral"])
    look = sub.add_parser("lookup", help="normalize a code and give its reference link (and computed values "
                          "for HLC and RAL DESIGN SYSTEM plus)")
    look.add_argument("system", help=f"one of: {systems}")
    look.add_argument("code", help="the code, e.g. \"185 C\", \"RAL 180 40 20\", \"NCS S 1040-R20B\"")
    look.add_argument("--json", action="store_true")
    rec = sub.add_parser("record", help="keep your value for a code (user cache, never a project)")
    rec.add_argument("system", help=f"one of: {systems}")
    rec.add_argument("code")
    rec.add_argument("--oklch", nargs=3, metavar=("L", "C", "H"))
    rec.add_argument("--hex", metavar="RRGGBB")
    rec.add_argument("--source-class", required=True, choices=SOURCE_CLASSES,
                     help="provider: published by the standard's owner; measured: from a physical sample; "
                          "screen-sample: sampled from a screen or photo (detection only)")
    rec.add_argument("--use", choices=USES, help="spec or detection_only (default: spec, but a screen sample "
                     "is always detection_only)")
    rec.add_argument("--note")
    rec.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    return _lookup_cmd(args) if args.command == "lookup" else _record_cmd(args)


# ---------------------------------------------------------------- search (nearest candidates)

GRIDS = {"hlc": (10, 5, 10), "ral-design-plus": (10, 10, 10)}   # hue, lightness, chroma steps of candidate codes


def _steps(value: float, step: int, low: int, high: int, *, wrap: bool = False) -> set[int]:
    floor = math.floor(value / step)
    ceil = math.ceil(value / step)
    indices = range(floor - 2, ceil + 3)
    if wrap:
        return {(index * step) % 360 for index in indices}
    return {index * step for index in indices if low <= index * step <= high} or {
        low if value < low else (high // step) * step}


def nearest_codes(system: str, oklch, limit: int) -> list[dict]:
    """Grid codes of a coordinate system around a color, nearest first. A grid point is a candidate code;
    the collection may not hold every point."""
    hue_step, l_step, c_step = GRIDS[system]
    inverse = oklch_to_lch_d50 if system == "hlc" else oklch_to_lch_d65_10
    l, c, h = inverse(*oklch)
    hues = _steps(h or 0.0, hue_step, 0, 360, wrap=True)
    found = {}
    for lightness in _steps(l, l_step, 0, 100 if system == "hlc" else 99):
        for chroma in _steps(c, c_step, 0, 999 if system == "hlc" else 99):
            for hue in (hues if chroma else {0}):
                code = normalize(system, f"{hue:03d} {lightness:02d} {chroma:02d}")
                if code.code not in found:
                    value = computed(code)
                    found[code.code] = {"system": system, "code": code.code, "oklch": value["oklch"],
                                        "delta_e_ok": _distance(oklch, value["oklch"]),
                                        "label": "nearest candidate", "source_class": "computed",
                                        "approximate": True, "use": "detection_only"}
    return sorted(found.values(), key=lambda x: x["delta_e_ok"])[:limit]


def nearest_records(oklch, limit: int) -> list[dict]:
    rows = [{**r, "delta_e_ok": _distance(oklch, r["oklch"]), "label": "nearest candidate"} for r in _records()]
    return sorted(rows, key=lambda x: x["delta_e_ok"])[:limit]


def _candidate_line(c: dict) -> str:
    name = _title(c["system"], c["code"])
    how = ("computed, approximate" if c["source_class"] == "computed"
           else f"your {c['source_class']} record, {'spec' if c['use'] == 'spec' else 'detection only'}")
    return f"  {name:40} {css_oklch(c['oklch']):28} ΔE_OK {c['delta_e_ok']:.4f}  ({how})"


def search_main(argv: list[str], prog: str = "lazuli search --type color") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Nearest color system candidates for a color value, "
                                 "or a lookup when the query is a system code.")
    ap.add_argument("query", nargs="+", help="#RRGGBB, oklch(L C H) or another CSS color, or a system code")
    ap.add_argument("--limit", type=int, default=3, help="candidates per group (default 3)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    query = " ".join(args.query)
    value = parse_color(query)
    if value is None:
        system = detect_system(query)
        if system is None:
            print(f"{prog}: {query!r} is neither a color value (#RRGGBB, oklch(L C H)) nor a color system code",
                  file=sys.stderr)
            return 2
        return _lookup_cmd(argparse.Namespace(system=system, code=query, json=args.json))
    limit = max(args.limit, 0)
    candidates = [*nearest_codes("hlc", value, limit), *nearest_codes("ral-design-plus", value, limit),
                  *nearest_records(value, limit)]
    if args.json:
        print(json.dumps({"query": query, "oklch": list(value), "candidates": candidates}, ensure_ascii=False, indent=2))
        return 0
    print(f"nearest candidates to {query} = {css_oklch(value)}; ΔE_OK is the Oklab distance, and a nearest "
          "candidate is never an identity")
    groups = (("computed HLC codes", "hlc"), ("computed RAL DESIGN SYSTEM plus codes", "ral-design-plus"))
    for title, system in groups:
        print(f"{title} (grid points; check that the collection holds the code):")
        print("\n".join(_candidate_line(c) for c in candidates if c["system"] == system and c["source_class"] == "computed"))
    recorded = [c for c in candidates if c["source_class"] != "computed"]
    print("your recorded values:" if recorded else "your recorded values: none")
    if recorded:
        print("\n".join(_candidate_line(c) for c in recorded))
    return 0
