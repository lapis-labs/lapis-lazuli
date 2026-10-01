"""CSS computed colors converted through linear sRGB to perceptual OKLCH."""
from __future__ import annotations

import colorsys
import math
import re

_NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:e[-+]?\d+)?%?", re.I)


def _linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = rgb
    l = 0.4122214708*r + 0.5363325363*g + 0.0514459929*b
    m = 0.2119034982*r + 0.6806995451*g + 0.1073969566*b
    s = 0.0883024619*r + 0.2817188376*g + 0.6299787005*b
    l, m, s = math.cbrt(l), math.cbrt(m), math.cbrt(s)
    return (0.2104542553*l + 0.7936177850*m - 0.0040720468*s,
            1.9779984951*l - 2.4285922050*m + 0.4505937099*s,
            0.0259040371*l + 0.7827717662*m - 0.8086757660*s)


def oklab(color: list[float]) -> tuple[float, float, float]:
    l, c, h = color[:3]
    return l, c * math.cos(math.radians(h)), c * math.sin(math.radians(h))


def from_oklab(l: float, a: float, b: float, alpha: float) -> list[float] | None:
    if alpha == 0:
        return None
    c = math.hypot(a, b)
    result = [round(min(1., max(0., l)), 4), round(min(0.5, c), 4),
              round(math.degrees(math.atan2(b, a)) % 360 if c > 1e-6 else 0., 4)]
    if alpha < 1:
        result.append(round(alpha, 4))
    return result


def _xyz_to_rgb(x: float, y: float, z: float, d50: bool = False) -> tuple[float, float, float]:
    if d50:
        x, y, z = (0.9555766*x - 0.0230393*y + 0.0631636*z,
                   -0.0282895*x + 1.0099416*y + 0.0210077*z,
                   0.0122982*x - 0.0204830*y + 1.3299098*z)
    return (3.2404542*x - 1.5371385*y - 0.4985314*z,
            -0.9692660*x + 1.8760108*y + 0.0415560*z,
            0.0556434*x - 0.2040259*y + 1.0572252*z)


def _cie_lab_to_rgb(l: float, a: float, b: float) -> tuple[float, float, float]:
    fy = (l + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    delta = 6 / 29

    def inverse(t: float) -> float:
        return t**3 if t > delta else 3 * delta**2 * (t - 4 / 29)
    return _xyz_to_rgb(0.96422 * inverse(fx), inverse(fy), 0.82521 * inverse(fz), d50=True)


def _signed_power(value: float, exponent: float) -> float:
    return math.copysign(abs(value) ** exponent, value)


def to_oklch(css: str) -> list[float] | None:
    """Convert computed RGB, Lab, OKLab, HSL and wide-gamut CSS colors to OKLCH."""
    css = css.strip().lower()
    if css == "transparent":
        return None
    kind, _, contents = css.partition("(")
    if kind == "color":
        space, _, contents = contents.partition(" ")
    values = _NUM.findall(re.sub(r"\bnone\b", "0", contents))
    if len(values) < 3:
        return None
    alpha = float(values[3].rstrip("%")) / (100 if values[3].endswith("%") else 1) if len(values) > 3 else 1.
    if kind in ("oklch", "oklab"):
        l = float(values[0].rstrip("%")) / (100 if values[0].endswith("%") else 1)
        a, b = (float(values[1]), float(values[2])) if kind == "oklab" else (
            float(values[1]) * math.cos(math.radians(float(values[2]))),
            float(values[1]) * math.sin(math.radians(float(values[2]))))
        return from_oklab(l, a, b, alpha)
    if kind in ("lab", "lch"):
        l = float(values[0].rstrip("%"))
        a, b = float(values[1].rstrip("%")), float(values[2].rstrip("%"))
        if kind == "lch":
            chroma = a * (1.5 if values[1].endswith("%") else 1)
            a, b = chroma * math.cos(math.radians(b)), chroma * math.sin(math.radians(b))
        else:
            a *= 1.25 if values[1].endswith("%") else 1
            b *= 1.25 if values[2].endswith("%") else 1
        rgb = _cie_lab_to_rgb(l, a, b)
    elif kind in ("rgb", "rgba"):
        rgb = tuple(_linear(float(v.rstrip("%")) / (100 if v.endswith("%") else 255)) for v in values[:3])
    elif kind in ("hsl", "hsla"):
        r, g, b = colorsys.hls_to_rgb(float(values[0]) / 360,
                                      float(values[2].rstrip("%")) / 100,
                                      float(values[1].rstrip("%")) / 100)
        rgb = tuple(map(_linear, (r, g, b)))
    elif kind == "hwb":
        hue = float(values[0]) / 360
        white, black = (float(v.rstrip("%")) / 100 for v in values[1:3])
        if white + black >= 1:
            grey = white / (white + black)
            rgb = tuple(map(_linear, (grey, grey, grey)))
        else:
            rgb = tuple(_linear(white + channel * (1 - white - black))
                        for channel in colorsys.hsv_to_rgb(hue, 1, 1))
    elif kind == "color":
        channels = [float(v.rstrip("%")) / (100 if v.endswith("%") else 1) for v in values[:3]]
        if space in ("xyz", "xyz-d65", "xyz-d50"):
            rgb = _xyz_to_rgb(*channels, d50=space == "xyz-d50")
        elif space == "srgb-linear":
            rgb = tuple(channels)
        elif space in ("srgb", "display-p3"):
            rgb = tuple(map(_linear, channels))
            if space == "display-p3":
                r, g, b = rgb
                rgb = (1.2249401*r - 0.2249401*g, -0.0420569*r + 1.0420569*g,
                       -0.0196376*r - 0.0786361*g + 1.0982737*b)
        elif space == "a98-rgb":
            r, g, b = (_signed_power(c, 563 / 256) for c in channels)
            rgb = _xyz_to_rgb(0.5767309*r + 0.1855540*g + 0.1881852*b,
                              0.2973769*r + 0.6273491*g + 0.0752741*b,
                              0.0270343*r + 0.0703124*g + 0.9911085*b)
        elif space == "prophoto-rgb":
            r, g, b = (c / 16 if abs(c) <= 1/32 else _signed_power(c, 1.8) for c in channels)
            rgb = _xyz_to_rgb(0.79776049*r + 0.135185837*g + 0.031349349*b,
                              0.288071128*r + 0.711843218*g + 0.000085654*b,
                              0.825104603*b, d50=True)
        elif space == "rec2020":
            alpha2020, beta2020 = 1.09929682680944, 0.018053968510807
            r, g, b = (c / 4.5 if abs(c) < beta2020 * 4.5 else
                       math.copysign(((abs(c) + alpha2020 - 1) / alpha2020) ** (1 / 0.45), c)
                       for c in channels)
            rgb = _xyz_to_rgb(0.6369580483*r + 0.1446169036*g + 0.1688809752*b,
                              0.2627002120*r + 0.6779980715*g + 0.0593017165*b,
                              0.0280726930*g + 1.0609850577*b)
        else:
            return None
    else:
        return None
    return from_oklab(*_lab(rgb), alpha)


def delta_e_ok(a: list[float], b: list[float]) -> float:
    return math.dist(oklab(a), oklab(b))


def _luminance(color: list[float]) -> float:
    l, a, b = oklab(color)
    lm = (l + 0.3963377774*a + 0.2158037573*b) ** 3
    mm = (l - 0.1055613458*a - 0.0638541728*b) ** 3
    sm = (l - 0.0894841775*a - 1.2914855480*b) ** 3
    r = 4.0767416621*lm - 3.3077115913*mm + 0.2309699292*sm
    g = -1.2684380046*lm + 2.6097574011*mm - 0.3413193965*sm
    bl = -0.0041960863*lm - 0.7034186147*mm + 1.7076147010*sm
    return (0.2126*min(1, max(0, r)) + 0.7152*min(1, max(0, g)) +
            0.0722*min(1, max(0, bl)))


def contrast_ratio(fg_oklch: list[float], bg_oklch: list[float]) -> float:
    a, b = _luminance(fg_oklch), _luminance(bg_oklch)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)
