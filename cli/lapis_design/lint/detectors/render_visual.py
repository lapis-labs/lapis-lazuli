"""Render-layer detectors for color, surfaces, icons, imagery, typicality, and references.

They read the render extract (render/extract.schema.yaml; the meaning of every field is in
render/DERIVED.md). typicality-distance also reads the corpus (`ctx.corpus`; the loader tags each
entry with its corpus name in `_corpus`), and the reference detectors read reference profiles
(`ctx.refs`); both share the extract format, so one distance code serves typicality and clone risk.

A hit that describes one box is reported once, at the first capture that shows it, and names every
capture it was seen in. Page-level measures (shares, spreads, inversions) are judged per capture and
reported once, at the capture with the largest value.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from typing import Any, Callable, Iterable

from lapis_design import text_sig
from lapis_design.lint.types import Context, Hit, Result, detector
from lapis_design.plan_check import edit_distance, oklch_in_region
from lapis_design.render.color import delta_e_ok, from_oklab, oklab, to_oklch
from lapis_design.rights_check import PHASH_MAX_DISTANCE

# Tuning constants. Rule thresholds live in rules.yaml; these only say what counts as an instance.
ACCENT_MIN_C = 0.06          # OKLCH chroma from which a color reads as an accent, not a tinted neutral
TINT_MIN_C = 0.005           # below this chroma a hue is not perceptible, so hue measures ignore the color
HUE_FAMILY_DEG = 45          # hues (and shadow directions) within this arc of a neighbor form one family
SAME_COLOR_DE = 0.03         # palette entries of different captures this close (ΔE_OK) are one color
ACCENT_WORD_DE = 0.08        # ΔE_OK by which an accent word stands apart from the rest of its heading
SIDE_ACCENT_MIN_PX = 2       # a side border this wide, at least twice every other side, is an accent side
JAGGED_MIN = 0.5             # clip-path jaggedness (DERIVED.md) from which a clip reads as a zigzag
ELEVATION_STEP_L = 0.01      # OKLCH L difference that makes a surface lighter or darker than its parent
INVERSION_DE = 0.04          # ΔE_OK within which a dark color equals the literal inversion of the light one
INVERSION_CHANGE_DE = 0.2    # an inversion must move a color this far (ΔE_OK) for the pair to be telling
INVERTED_SHARE_MIN = 0.8     # share of telling color pairs that must be literal inversions
INVERSION_MIN_PAIRS = 3      # fewer telling color pairs than this show no pattern
PALETTE_SCALE_DE = 0.2       # palette ΔE_OK at which two palettes or role colors count as entirely different
TYPE_WEIGHT_SCALE = 500      # font-weight difference that counts as entirely different type
TYPE_TRACKING_SCALE = 0.1    # tracking difference (em) that counts as entirely different type
TYPE_TRANSFORM_GAP = 0.5     # distance added when text-transform differs
STATE_SCALE_DE = 0.1         # difference in state color change (ΔE_OK) that counts as entirely different
MIN_SHARED_FEATURES = 3      # the default typicality feature set needs at least this many shared features
TEXT_MATCH_MIN = 0.8         # run-signature similarity from which reference copy counts as reused
TEXT_MATCH_MIN_CHARS = 20    # runs shorter than this (menu labels, one-word buttons) are not compared

ACCENT_ROLES = ("identity", "interaction")
PANEL_ROLES = {"card", "dialog", "nav"}
CONTAINER_ROLES = ("card", "dialog", "button", "input", "media")
NO_SIDE_ACCENT_ROLES = {"button", "link", "input", "nav", "icon", "media", "heading"}
CAPTURE_HEIGHT = {320: 568, 390: 844, 768: 1024, 1440: 900}   # DERIVED.md, when `height` is absent
DIRECTIONS = ("right", "down-right", "down", "down-left", "left", "up-left", "up", "up-right")
# The severity.adjust condition image hits can satisfy (imagery.missing-content-image)
EQUIVALENT_KEPT = "no required information or accessible equivalent is lost"


# ---------------------------------------------------------------- shared helpers

def _params(det: dict) -> dict:
    return det.get("params") or {}


def _threshold(det: dict) -> dict:
    return det.get("threshold") or {}


def _viewports(ctx: Context) -> tuple[list[dict], str | None]:
    if ctx.extract is None:
        return [], "no render extract was given"
    viewports = ctx.extract.get("viewports") or []
    if not viewports:
        return [], "the render extract has no viewports"
    return viewports, None


def _label(vp: dict) -> str:
    extra = "".join(f" {name}" for name, key in (("reduced-motion", "reduced_motion"),
                                                  ("browser-chrome", "browser_chrome")) if vp.get(key))
    return f"{vp['width']} px {vp['theme']}{extra}"


def _where(vp: dict, box: str | None = None) -> dict:
    return {"viewport": vp["width"], "box": box} if box else {"viewport": vp["width"]}


def _fmt(color: list[float]) -> str:
    return f"oklch({color[0]:.3f} {color[1]:.3f} {color[2]:.1f})"


def _snippet(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _doc_label(doc: dict) -> str:
    source = doc.get("source") or {}
    return source.get("url") or source.get("path") or source.get("task") or "an unnamed profile"


def _index(vp: dict) -> dict[str, dict]:
    return {box["id"]: box for box in vp.get("boxes") or []}


def _ancestors(box: dict, index: dict[str, dict]) -> Iterable[dict]:
    seen: set[str] = set()
    parent = box.get("parent")
    while parent and parent in index and parent not in seen:
        seen.add(parent)
        box = index[parent]
        yield box
        parent = box.get("parent")


def _subtree(roots: set[str], boxes: list[dict]) -> set[str]:
    children: dict[str, list[str]] = defaultdict(list)
    for box in boxes:
        if box.get("parent"):
            children[box["parent"]].append(box["id"])
    out: set[str] = set()
    stack = list(roots)
    while stack:
        current = stack.pop()
        if current not in out:
            out.add(current)
            stack.extend(children[current])
    return out


def _plain(viewports: list[dict]) -> dict[tuple[int, str], dict]:
    """One capture per (width, theme), preferring the one without reduced motion or browser chrome."""
    out: dict[tuple[int, str], dict] = {}
    for vp in viewports:
        key = (vp["width"], vp["theme"])
        held = out.get(key)
        if held is None or ((held.get("reduced_motion") or held.get("browser_chrome"))
                            and not (vp.get("reduced_motion") or vp.get("browser_chrome"))):
            out[key] = vp
    return out


def _families(items: list, hue: Callable[[Any], float]) -> list[list]:
    """Items grouped by hue (or angle): neighbors on the circle more than HUE_FAMILY_DEG apart split."""
    order = sorted(items, key=lambda item: hue(item) % 360)
    angles = [hue(item) % 360 for item in order]
    n = len(order)
    cuts = [i for i in range(n) if n > 1 and (angles[(i + 1) % n] - angles[i]) % 360 > HUE_FAMILY_DEG]
    if not cuts:
        return [order] if order else []
    return [[order[j % n] for j in range(cut + 1, nxt + 1 + (n if nxt <= cut else 0))]
            for cut, nxt in zip(cuts, cuts[1:] + cuts[:1])]


def _hue_spread(hues: list[float]) -> float:
    """The smallest arc of the hue circle that holds every hue."""
    if len(hues) < 2:
        return 0.0
    angles = sorted(h % 360 for h in hues)
    gaps = [(angles[(i + 1) % len(angles)] - angles[i]) % 360 for i in range(len(angles))]
    return 360 - max(gaps)


class _Once:
    """Hits keyed by what they describe, so a box seen in several captures is reported once."""

    def __init__(self) -> None:
        self._hits: dict[Any, tuple[Hit, list[str]]] = {}

    def add(self, key: Any, vp: dict, hit: Hit) -> None:
        if key in self._hits:
            self._hits[key][1].append(_label(vp))
        else:
            self._hits[key] = (hit, [_label(vp)])

    def hits(self) -> list[Hit]:
        out = []
        for hit, labels in self._hits.values():
            hit.observed += f" (seen in {', '.join(labels)})"
            out.append(hit)
        return out


def _worst(found: list[tuple[float, Hit]], total: int) -> list[Hit]:
    """The capture with the largest value, noting how many captures showed the same."""
    if not found:
        return []
    _, hit = max(found, key=lambda item: item[0])
    if len(found) > 1:
        hit.observed += f"; {len(found)} of {total} captures show it"
    return [hit]


def _finish(hits: list[Hit], unjudged: list[str]) -> Result:
    """Hits when there are any; otherwise a skip when part of the input could not be judged."""
    if hits:
        return Result(hits=hits)
    if unjudged:
        return Result(skipped="; ".join(dict.fromkeys(unjudged)))
    return Result()


def _total(shares: Iterable[float]) -> float:
    """A sum of area shares, rounded so that float noise never crosses a bound (0.2 + 0.1 is 0.3)."""
    return round(math.fsum(shares), 6)


def _rights(value: Any) -> set[str] | None:
    if value is None:
        return None
    return {value} if isinstance(value, str) else set(value)


# ---------------------------------------------------------------- palette

def _nearest(color: list[float], anchors: list[list[float]]) -> tuple[list[float] | None, float]:
    if not anchors:
        return None, math.inf
    return min(((anchor, delta_e_ok(color, anchor)) for anchor in anchors), key=lambda pair: pair[1])


@detector("palette-region", layers=("render",))
def palette_region(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    viewports, why = _viewports(ctx)
    if why:
        return Result(skipped=why)
    region = det.get("region") or {}
    if region.get("space", "oklch") != "oklch":
        return Result(skipped=f"palette-region compares OKLCH regions, not {region['space']!r}")
    bounds = region.get("bounds") or {}
    roles = {role.strip() for role in str(region.get("role") or "").split("|") if role.strip()}
    anchors = [anchor["oklch"] for anchor in det.get("anchors") or [] if anchor.get("oklch")]
    radius = region.get("radius")
    palettes = [(vp, vp["palette"]) for vp in viewports if vp.get("palette")]
    if not palettes:
        return Result(skipped="no capture in the render extract carries a palette")
    if roles and not any(entry.get("role_guess") for _, palette in palettes for entry in palette):
        return Result(skipped="the palette carries no role guesses, so the region's roles cannot be matched")

    colors: list[dict] = []
    for vp, palette in palettes:
        for entry in palette:
            color, role = entry["oklch"], entry.get("role_guess")
            if not oklch_in_region(color[:3], bounds) or (roles and role not in roles):
                continue
            anchor, gap = _nearest(color, anchors)
            if radius is not None and anchor is not None and gap > radius:
                continue
            same = next((c for c in colors
                         if c["role"] == role and delta_e_ok(c["oklch"], color) <= SAME_COLOR_DE), None)
            if same is None:
                colors.append({"oklch": color, "role": role, "share": entry["share"], "vp": vp,
                               "anchor": anchor, "gap": gap, "captures": 1})
                continue
            same["captures"] += 1
            if entry["share"] > same["share"]:
                same.update(oklch=color, share=entry["share"], vp=vp, anchor=anchor, gap=gap)

    hits = []
    for c in colors:
        observed = (f"{c['role'] or 'palette'} color {_fmt(c['oklch'])} covers {c['share']:.0%} of the "
                    f"{_label(c['vp'])} capture and falls in the rule's region")
        if c["anchor"] is not None:
            observed += f", {c['gap']:.3f} ΔE_OK from the anchor {_fmt(c['anchor'])}"
        if c["captures"] > 1:
            observed += f" (seen in {c['captures']} captures)"
        hits.append(Hit(observed=observed, location=_where(c["vp"])))
    return Result(hits=hits)


@detector("palette-structure", layers=("render",))
def palette_structure(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    viewports, why = _viewports(ctx)
    if why:
        return Result(skipped=why)
    params, threshold = _params(det), _threshold(det)
    check = params.get("check")
    checks = {"accent-roles": _accent_roles, "neutral-temperature": _neutral_temperature,
              "pure-endpoints": _pure_endpoints}
    if check not in checks:
        return Result(skipped=f"palette-structure has no check {check!r}")
    palettes = [(vp, vp["palette"]) for vp in viewports if vp.get("palette")]
    if not palettes:
        return Result(skipped="no capture in the render extract carries a palette")
    return checks[check](ctx, palettes, params, threshold, len(viewports))


def _plan_lists_data(plan: dict) -> bool:
    """Whether the plan names its data colors: a `data_scales` kind or a color role entry with role data."""
    color = (plan.get("tokens") or {}).get("color") or {}
    return bool(color.get("data_scales")) or any(
        isinstance(entry, dict) and entry.get("role") == "data" for entry in color.get("roles") or ())


def _accent_roles(ctx: Context, palettes: list, params: dict, threshold: dict, total: int) -> Result:
    """Accents (identity and interaction colors) in three or more unrelated hue families, or
    interaction colors in two or more: the color of action is no longer one thing. With a plan, a
    color the render guessed to be data is an accent too, unless the plan lists its data colors."""
    if not any(entry.get("role_guess") for _, palette in palettes for entry in palette):
        return Result(skipped="the palette carries no role guesses, so accents cannot be told by role")
    roles = ACCENT_ROLES
    if ctx.plan is not None and not _plan_lists_data(ctx.plan):
        roles += ("data",)
    found = []
    for vp, palette in palettes:
        accents = [e for e in palette if e.get("role_guess") in roles
                   and e["oklch"][1] >= ACCENT_MIN_C and not e.get("exact")]
        families = _families(accents, lambda e: e["oklch"][2])
        interaction = _families([e for e in accents if e["role_guess"] == "interaction"],
                                lambda e: e["oklch"][2])
        if len(interaction) >= 2:
            groups, what = interaction, "interaction colors"
        elif len(families) >= 3:
            groups, what = families, "accent colors"
        else:
            continue
        parts = []
        for group in groups:
            lead = max(group, key=lambda e: e["share"])
            roles = "/".join(sorted({e["role_guess"] for e in group}))
            parts.append(f"{roles} {lead['oklch'][2]:.0f}°")
        found.append((len(groups), Hit(
            observed=f"{what} fall in {len(groups)} unrelated hue families ({', '.join(parts)}) "
                     f"in the {_label(vp)} capture",
            location=_where(vp))))
    return Result(hits=_worst(found, total))


def _neutral_temperature(ctx: Context, palettes: list, params: dict, threshold: dict, total: int) -> Result:
    bound = threshold.get("hue_spread_deg_max")
    if bound is None:
        return Result(skipped="neutral-temperature needs hue_spread_deg_max")
    neutral_c = params.get("neutral_c", 0.03)
    found = []
    for vp, palette in palettes:
        hues = [e["oklch"][2] for e in palette if not e.get("exact") and e.get("role_guess") != "content"
                and TINT_MIN_C <= e["oklch"][1] <= neutral_c]
        spread = _hue_spread(hues)
        if spread > bound:
            listed = ", ".join(f"{h:.0f}°" for h in sorted(hues))
            found.append((spread, Hit(
                observed=f"neutral colors span {spread:.0f}° of hue ({listed}) in the {_label(vp)} capture, "
                         f"wider than {bound:g}°",
                location=_where(vp))))
    return Result(hits=_worst(found, total))


def _pure_endpoints(ctx: Context, palettes: list, params: dict, threshold: dict, total: int) -> Result:
    uses = params.get("uses", "exact-palette-entries")
    if uses != "exact-palette-entries":
        return Result(skipped=f"pure-endpoints reads exact palette entries only, not {uses!r}")
    bound = threshold.get("area_share_max")
    found = []
    for vp, palette in palettes:
        share = _total(e["share"] for e in palette if e.get("exact"))
        if share > (bound if bound is not None else 0):
            observed = f"pure black and white cover {share:.0%} of the {_label(vp)} capture"
            if bound is not None:
                observed += f", more than {bound:.0%}"
            found.append((share, Hit(observed=observed, location=_where(vp))))
    return Result(hits=_worst(found, total))


# ---------------------------------------------------------------- theme pair

def _gamma(value: float) -> float:
    return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055


def _srgb(color: list[float]) -> tuple[float, float, float]:
    """Gamma-encoded sRGB channels in 0-1, clipped to the gamut."""
    l, a, b = oklab(color)
    lm = (l + 0.3963377774*a + 0.2158037573*b) ** 3
    mm = (l - 0.1055613458*a - 0.0638541728*b) ** 3
    sm = (l - 0.0894841775*a - 1.2914855480*b) ** 3
    linear = (4.0767416621*lm - 3.3077115913*mm + 0.2309699292*sm,
              -1.2684380046*lm + 2.6097574011*mm - 0.3413193965*sm,
              -0.0041960863*lm - 0.7034186147*mm + 1.7076147010*sm)
    return tuple(_gamma(min(1.0, max(0.0, v))) for v in linear)


def _invert_srgb(color: list[float]) -> list[float]:
    r, g, b = _srgb(color)
    return to_oklch(f"color(srgb {1 - r:.6f} {1 - g:.6f} {1 - b:.6f})")


# Ways a dark theme is made by inverting the light one: a token lightness flip, a CSS invert filter,
# and an invert filter followed by a half-turn hue rotation that restores the hue.
INVERSIONS: dict[str, Callable[[list[float]], list[float]]] = {
    "OKLCH lightness flipped (L to 1 - L), hue and chroma kept": lambda c: [1 - c[0], c[1], c[2]],
    "sRGB channels inverted": _invert_srgb,
    "sRGB channels inverted and the hue kept": lambda c: [*_invert_srgb(c)[:2], c[2]],
}


def _theme_pairs(light: dict, dark: dict) -> list[tuple[list[float], list[float]]]:
    """(light color, dark color) for backgrounds, borders, and text matched by id."""
    dark_boxes = _index(dark)
    pairs = []
    for box in light.get("boxes") or []:
        other = dark_boxes.get(box["id"])
        if other is None:
            continue
        for key in ("background", "border_color"):
            a, b = (box.get("style") or {}).get(key), (other.get("style") or {}).get(key)
            if a and b:
                pairs.append((a, b))
    dark_runs = {run["id"]: run for run in dark.get("text") or []}
    for run in light.get("text") or []:
        other = dark_runs.get(run["id"])
        if other and run.get("color") and other.get("color"):
            pairs.append((run["color"], other["color"]))
    return pairs


def _elevation_flips(light: dict, dark: dict) -> int:
    """Surfaces lighter than the surface under them in light, darker in dark."""
    light_index, dark_index = _index(light), _index(dark)
    flips = 0
    for box in light.get("boxes") or []:
        other = dark_index.get(box["id"])
        own = (box.get("style") or {}).get("background")
        own_dark = ((other or {}).get("style") or {}).get("background")
        if not own or not own_dark:
            continue
        parent = next((a for a in _ancestors(box, light_index) if (a.get("style") or {}).get("background")), None)
        parent_dark = ((dark_index.get(parent["id"]) or {}).get("style") or {}).get("background") if parent else None
        if parent_dark is None:
            continue
        if (own[0] > parent["style"]["background"][0] + ELEVATION_STEP_L
                and own_dark[0] < parent_dark[0] - ELEVATION_STEP_L):
            flips += 1
    return flips


@detector("theme-pair", layers=("render",))
def theme_pair(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    viewports, why = _viewports(ctx)
    if why:
        return Result(skipped=why)
    check = _params(det).get("check", "literal-inversion")
    if check != "literal-inversion":
        return Result(skipped=f"theme-pair has no check {check!r}")
    plain = _plain(viewports)
    widths = sorted({w for w, theme in plain if theme == "light"} & {w for w, theme in plain if theme == "dark"})
    if not widths:
        return Result(skipped="no width has both a light and a dark capture: the page has no dark theme, "
                              "or it was not captured")
    found, judged = [], 0
    for width in widths:
        light, dark = plain[(width, "light")], plain[(width, "dark")]
        pairs = _theme_pairs(light, dark)
        best = None
        for name, invert in INVERSIONS.items():
            telling = matched = 0
            for a, b in pairs:
                expected = invert(a[:3])
                if expected is None or delta_e_ok(a, expected) < INVERSION_CHANGE_DE:
                    continue
                telling += 1
                matched += delta_e_ok(b, expected) <= INVERSION_DE
            if telling >= INVERSION_MIN_PAIRS and (best is None or matched / telling > best[1] / best[2]):
                best = (name, matched, telling)
        if best is None:
            continue
        judged += 1
        name, matched, telling = best
        if matched / telling < INVERTED_SHARE_MIN:
            continue
        observed = (f"{matched} of {telling} colors matched by box in the {width} px dark capture are the "
                    f"light colors with {name}")
        if flips := _elevation_flips(light, dark):
            raised = "surface turns" if flips == 1 else "surfaces turn"
            observed += f"; {flips} raised {raised} darker than the surface under them"
        found.append((matched / telling, Hit(observed=observed, location=_where(dark))))
    if not judged:
        return Result(skipped=f"fewer than {INVERSION_MIN_PAIRS} colors matched between the light and dark "
                              "captures change enough under inversion to judge")
    return Result(hits=_worst(found, len(widths)))


# ---------------------------------------------------------------- gradients

def _page_height(vp: dict) -> float:
    height = vp.get("height") or CAPTURE_HEIGHT[vp["width"]]
    return max([height] + [b["rect"]["y"] + b["rect"]["h"] for b in vp.get("boxes") or []])


def _overlap(a: dict, b: dict) -> float:
    w = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    h = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    return max(0.0, w) * max(0.0, h)


def _rect_shares(box: dict, vp: dict) -> tuple[float, float]:
    """(share of the page, share of the first viewport) covered by a box's rect."""
    rect, width = box["rect"], vp["width"]
    height = vp.get("height") or CAPTURE_HEIGHT[width]
    page = _overlap(rect, {"x": 0, "y": 0, "w": width, "h": _page_height(vp)}) / (width * _page_height(vp))
    first = _overlap(rect, {"x": 0, "y": 0, "w": width, "h": height}) / (width * height)
    return page, first


@detector("gradient-inventory", layers=("render",))
def gradient_inventory(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    viewports, why = _viewports(ctx)
    if why:
        return Result(skipped=why)
    params = _params(det)
    target = params.get("target", "background")
    if target == "text":
        return _gradient_text(viewports, params)
    region = det.get("region")
    if region and region.get("space", "oklch") != "oklch":
        return Result(skipped=f"gradient-inventory compares OKLCH regions, not {region['space']!r}")
    bounds = (region or {}).get("bounds") or {}
    min_stops = params.get("min_stops_in_region", 1) if region else 0
    kind, behind, min_blur = params.get("kind"), params.get("behind"), params.get("min_blur_px")
    limits = {k: v for k, v in _threshold(det).items() if k in ("area_share_max", "first_viewport_share_max")}

    desc = " ".join(filter(None, [kind, target, "gradients"]))
    if min_blur is not None:
        desc += f" and shapes blurred {min_blur:g} px or more"
    if region:
        desc += f" with at least {min_stops} stops in the rule's region"
    if behind:
        desc += f" behind the {behind}"

    once, found, unjudged = _Once(), [], []
    for vp in viewports:
        boxes = vp.get("boxes") or []
        index = _index(vp)
        near, section_rects, placed = None, [], True
        if behind:
            sections = (vp.get("derived") or {}).get("sections")
            if sections is None:
                placed = False          # count candidates anyway: none means nothing to place
            else:
                roots = {s["box"] for s in sections if s["archetype"] == behind}
                near = _subtree(roots, boxes)
                section_rects = [index[r]["rect"] for r in roots if r in index]

        items: list[tuple[dict, str, float | None, float | None]] = []
        for box in boxes:
            style = box.get("style") or {}
            layers = [g for g in style.get("gradients") or []
                      if g["target"] == target and (kind is None or g["kind"] == kind)
                      and sum(oklch_in_region(s["oklch"][:3], bounds) for s in g["stops"]) >= min_stops
                      and (near is None or box["id"] in near or g.get("behind") in near)]
            for g in layers:
                items.append((box, f"{g['kind']} gradient", g.get("area_share"), g.get("first_viewport_share")))
            blur = style.get("filter_blur_px") or 0
            if (not layers and min_blur is not None and blur >= min_blur
                    and (style.get("background") or style.get("gradients"))
                    and (not region or (style.get("background")
                                        and oklch_in_region(style["background"][:3], bounds)))
                    and (near is None or box["id"] in near
                         or any(_overlap(box["rect"], r) * 2 >= box["rect"]["w"] * box["rect"]["h"]
                                for r in section_rects))):
                items.append((box, f"shape blurred {blur:g} px", *_rect_shares(box, vp)))
        if not items:
            continue
        if not placed:
            unjudged.append(f"captures without derived sections cannot place anything behind the {behind}")
            continue

        if not limits:
            for box, what, _, _ in items:
                once.add((box["id"], what), vp, Hit(observed=f"{box['role']} box paints a {what} counted as "
                                                             f"{desc}", location=_where(vp, box["id"])))
            continue
        exceeded = []
        for key, bound in limits.items():
            values = [item[2] if key == "area_share_max" else item[3] for item in items]
            known = [v for v in values if v is not None]
            covered = min(1.0, _total(known))
            if covered > bound:
                exceeded.append((covered, key, bound))
            elif len(known) < len(values):
                unjudged.append(f"counted gradients carry no {key.removesuffix('_max')}")
        if exceeded:
            covered, key, bound = max(exceeded)
            area = "page" if key == "area_share_max" else "first viewport"
            found.append((covered, Hit(
                observed=f"{desc} ({len(items)} counted) cover {covered:.1%} of the {area} in the "
                         f"{_label(vp)} capture, more than {bound:.0%}",
                location=_where(vp), refs=list(dict.fromkeys(item[0]["id"] for item in items)))))
    return _finish(once.hits() + _worst(found, len(viewports)), unjudged)


def _heading_of(run: dict, index: dict[str, dict]) -> str:
    """The heading box a run belongs to (itself or its nearest heading ancestor), else its own box."""
    box = index.get(run["box"])
    if box is None:
        return run["box"]
    if box["role"] == "heading":
        return box["id"]
    return next((a["id"] for a in _ancestors(box, index) if a["role"] == "heading"), box["id"])


def _quote(runs: list[dict]) -> str:
    text = " ".join(run["text"] for run in runs if run.get("text"))
    return f'"{_snippet(text)}"' if text else f"run {runs[0]['id']}"


def _gradient_text(viewports: list[dict], params: dict) -> Result:
    """Headings painted with a gradient; with include_accent_word, also headings that set a part
    shorter than half of them apart with a gradient or an accent color."""
    roles = set(params.get("roles") or [])
    accent_words = bool(params.get("include_accent_word"))
    once, unjudged = _Once(), []
    for vp in viewports:
        runs = vp.get("text") or []
        if roles and runs and not any("type_role" in run for run in runs):
            unjudged.append("text runs carry no type roles")
            continue
        index = _index(vp)
        groups: dict[str, list[dict]] = defaultdict(list)
        for run in runs:
            if not roles or run.get("type_role") in roles:
                groups[_heading_of(run, index)].append(run)
        for box_id, group in groups.items():
            total = sum(run["chars"] for run in group)
            role = group[0].get("type_role", "heading")
            painted = [run for run in group if run.get("fill") == "gradient"]
            if painted and sum(run["chars"] for run in painted) * 2 >= total:
                once.add(("text", box_id), vp, Hit(
                    observed=f"{role} text {_quote(group)} is painted with a gradient fill",
                    location=_where(vp, box_id)))
                continue
            if not accent_words or len(group) < 2:
                continue
            weight: Counter = Counter()
            for run in group:
                if run.get("color"):
                    weight[tuple(run["color"][:3])] += run["chars"]
            base = list(weight.most_common(1)[0][0]) if weight else None
            accents = [run for run in group if run.get("fill") == "gradient" or (
                base is not None and run.get("color") and run["color"][1] >= ACCENT_MIN_C
                and delta_e_ok(run["color"], base) >= ACCENT_WORD_DE)]
            if not accents or sum(run["chars"] for run in accents) * 2 >= total:
                continue
            how = ("a gradient fill" if any(run.get("fill") == "gradient" for run in accents)
                   else f"the accent color {_fmt(accents[0]['color'])}")
            once.add(("text", box_id), vp, Hit(
                observed=f"{role} {_quote(group)} sets {_quote(accents)} apart with {how}",
                location=_where(vp, box_id)))
    return _finish(once.hits(), unjudged)


# ---------------------------------------------------------------- surface effects

def _page_field(vp: dict) -> list[float] | None:
    fields = [e for e in vp.get("palette") or [] if e.get("role_guess") == "field"]
    return max(fields, key=lambda e: e["share"])["oklch"] if fields else None


def _ground_l(box: dict, source: str, index: dict, vp: dict, runs_by_box: dict) -> float | None:
    """Lightness of what a shadow falls on: the text backdrop for text shadows, otherwise the nearest
    ancestor background, then the page field."""
    if source == "text-shadow":
        backdrops = [run["backdrop"]["oklch"][0] for run in runs_by_box.get(box["id"], []) if run.get("backdrop")]
        if backdrops:
            return statistics.median(backdrops)
    for ancestor in _ancestors(box, index):
        background = (ancestor.get("style") or {}).get("background")
        if background and (len(background) < 4 or background[3] >= 0.5):
            return background[0]
    field = _page_field(vp)
    return field[0] if field else None


def _direction(angle: float) -> str:
    return DIRECTIONS[round(angle / 45) % 8]


def _offset(shadow: dict) -> float:
    return math.hypot(shadow["offset_x"], shadow["offset_y"])


def _share_check(viewports: list[dict], pool: Callable[[dict], bool], qualifies: Callable[[dict], bool],
                 bound: float | None, noun: str, what: str) -> Result:
    """Share of pool boxes that qualify, per capture; without a bound, every qualifying box."""
    once, found = _Once(), []
    for vp in viewports:
        members = [box for box in vp.get("boxes") or [] if pool(box)]
        chosen = [box for box in members if qualifies(box)]
        if bound is None:
            for box in chosen:
                once.add(box["id"], vp, Hit(observed=f"{box['role']} box is among the {noun} that {what}",
                                            location=_where(vp, box["id"])))
        elif members and len(chosen) / len(members) > bound:
            share = len(chosen) / len(members)
            found.append((share, Hit(
                observed=f"{len(chosen)} of {len(members)} {noun} ({share:.0%}) {what} in the {_label(vp)} "
                         f"capture, more than {bound:.0%}",
                location=_where(vp), refs=[box["id"] for box in chosen])))
    return Result(hits=once.hits() + _worst(found, len(viewports)))


def _side_accent(box: dict) -> tuple[str, float, list[float]] | None:
    style = box.get("style") or {}
    if box["role"] in NO_SIDE_ACCENT_ROLES or (style.get("radius_px") or 0) <= 0:
        return None
    sides = style.get("border_sides") or {}
    for side, spec in sides.items():
        others = [other["px"] for name, other in sides.items() if name != side]
        color = spec.get("color")
        if (spec["px"] >= SIDE_ACCENT_MIN_PX and spec["px"] >= 2 * max(others, default=0)
                and color and color[1] >= ACCENT_MIN_C):
            return side, spec["px"], color
    return None


@detector("surface-effects", layers=("render",))
def surface_effects(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    viewports, why = _viewports(ctx)
    if why:
        return Result(skipped=why)
    params, threshold = _params(det), _threshold(det)
    effect = params.get("effect")
    if effect == "glow":
        return _glow(viewports, params)
    if effect == "shadow":
        if params.get("check") == "light-model-consistency":
            return _shadow_directions(viewports)
        max_blur, min_offset = params.get("max_blur_px"), params.get("min_offset_px")
        conditions = [f"blurred at most {max_blur:g} px" if max_blur is not None else "",
                      f"offset at least {min_offset:g} px" if min_offset is not None else ""]
        described = " and ".join(filter(None, conditions))

        def counted(shadow: dict) -> bool:
            return (shadow["source"] != "text-shadow" and not shadow.get("inset")
                    and (max_blur is None or shadow["blur_px"] <= max_blur)
                    and (min_offset is None or _offset(shadow) >= min_offset))
        return _share_check(
            viewports, lambda box: box["role"] == "card",
            lambda box: any(counted(s) for s in (box.get("style") or {}).get("shadows") or []),
            threshold.get("card_share_max"), "cards",
            f"carry a shadow {described}".rstrip() if described else "carry a shadow")
    if effect == "backdrop-filter":
        def glass(box: dict) -> bool:
            return ((box.get("style") or {}).get("backdrop_filter") or {}).get("blur_px", 0) > 0
        return _share_check(viewports, lambda box: box["role"] in PANEL_ROLES or glass(box), glass,
                            threshold.get("panel_share_max"), "panels", "blur the backdrop behind them")
    if effect == "radius":
        min_radius = params.get("min_radius_px")
        if min_radius is None:
            return Result(skipped="the radius effect needs min_radius_px")
        return _share_check(
            viewports, lambda box: box["role"] in CONTAINER_ROLES,
            lambda box: ((box.get("style") or {}).get("radius_px") or 0) >= min_radius,
            threshold.get("container_share_max"), "containers", f"round their corners by {min_radius:g} px or more")
    if effect == "side-accent-border":
        once = _Once()
        for vp in viewports:
            for box in vp.get("boxes") or []:
                if accent := _side_accent(box):
                    side, px, color = accent
                    once.add(box["id"], vp, Hit(
                        observed=f"rounded {box['role']} box carries a {px:g} px {_fmt(color)} border on the "
                                 f"{side} side only",
                        location=_where(vp, box["id"])))
        return Result(hits=once.hits())
    if effect == "background-pattern":
        kinds = set(params.get("kinds") or [])
        once = _Once()
        for vp in viewports:
            for box in vp.get("boxes") or []:
                pattern = (box.get("style") or {}).get("background_pattern")
                if pattern and (not kinds or pattern["kind"] in kinds):
                    cell = f" with a {pattern['cell_px']:g} px cell" if "cell_px" in pattern else ""
                    once.add(box["id"], vp, Hit(
                        observed=f"{box['role']} box has a {pattern['kind']} background pattern{cell}",
                        location=_where(vp, box["id"])))
        return Result(hits=once.hits())
    return Result(skipped=f"surface-effects has no effect {effect!r}")


def _glow(viewports: list[dict], params: dict) -> Result:
    dark_l, min_chroma = params.get("dark_background_l"), params.get("min_glow_chroma")
    if dark_l is None or min_chroma is None:
        return Result(skipped="the glow effect needs dark_background_l and min_glow_chroma")
    min_blur = params.get("min_glow_blur_px", 0)
    once, unjudged = _Once(), []
    for vp in viewports:
        index = _index(vp)
        runs_by_box: dict[str, list[dict]] = defaultdict(list)
        for run in vp.get("text") or []:
            runs_by_box[run["box"]].append(run)
        for box in vp.get("boxes") or []:
            for shadow in (box.get("style") or {}).get("shadows") or []:
                if shadow.get("inset") or shadow["blur_px"] < min_blur or shadow["color"][1] < min_chroma:
                    continue
                ground = _ground_l(box, shadow["source"], index, vp, runs_by_box)
                if ground is None:
                    unjudged.append("glowing shadows sit on no measured background")
                    continue
                if ground <= dark_l:
                    once.add(box["id"], vp, Hit(
                        observed=f"{shadow['source']} glow {_fmt(shadow['color'])} blurred {shadow['blur_px']:g} px "
                                 f"on a dark background (L {ground:.2f})",
                        location=_where(vp, box["id"])))
                    break
    return _finish(once.hits(), unjudged)


def _shadow_directions(viewports: list[dict]) -> Result:
    """Boxes of one role whose shadows point in unrelated directions (more than one light source)."""
    once = _Once()
    for vp in viewports:
        by_role: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for box in vp.get("boxes") or []:
            cast = [s for s in (box.get("style") or {}).get("shadows") or []
                    if s["source"] != "text-shadow" and not s.get("inset") and _offset(s) >= 1]
            if cast:
                main = max(cast, key=_offset)
                by_role[box["role"]].append(
                    (box["id"], math.degrees(math.atan2(main["offset_y"], main["offset_x"])) % 360))
        for role, items in by_role.items():
            families = _families(items, lambda item: item[1])
            if len(families) >= 2:
                parts = ", ".join(f"{len(f)} {_direction(f[0][1])}" for f in families)
                once.add(role, vp, Hit(
                    observed=f"{role} boxes cast shadows in {len(families)} directions ({parts})",
                    location=_where(vp, families[-1][0][0]), refs=[f[0][0] for f in families]))
    return Result(hits=once.hits())


# ---------------------------------------------------------------- icons and images

def _icon_family(icon: dict) -> str | None:
    if icon.get("library"):
        return icon["library"].casefold()
    if icon["kind"] == "emoji":
        return "emoji"
    if icon["kind"] == "svg" and "library" in icon:
        return "hand-authored svg"
    return None


@detector("icon-inventory", layers=("render",))
def icon_inventory(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    viewports, why = _viewports(ctx)
    if why:
        return Result(skipped=why)
    check = _params(det).get("check")
    icons = [(vp, box) for vp in viewports for box in vp.get("boxes") or [] if box.get("icon")]
    if not icons and any(box["role"] == "icon" for vp in viewports for box in vp.get("boxes") or []):
        return Result(skipped="icon boxes carry no icon inventory")
    once = _Once()
    if check == "emoji":
        for vp, box in icons:
            if box["icon"]["kind"] == "emoji":
                glyph = f" {box['icon']['glyph']}" if box["icon"].get("glyph") else ""
                once.add(box["id"], vp, Hit(observed=f"emoji{glyph} serves as an icon", location=_where(vp, box["id"])))
        return Result(hits=once.hits())
    if check == "hand-authored-standard-actions":
        for vp, box in icons:
            icon = box["icon"]
            if icon["kind"] == "svg" and "library" in icon and icon["library"] is None and icon.get("action"):
                once.add(box["id"], vp, Hit(observed=f"hand-authored SVG draws the standard {icon['action']} icon",
                                            location=_where(vp, box["id"])))
        return Result(hits=once.hits())
    if check == "families":
        bound = _threshold(det).get("families_max", 1)
        families: dict[str, dict[str, dict]] = defaultdict(dict)
        unidentified: set[str] = set()
        for vp, box in icons:
            family = _icon_family(box["icon"])
            if family is None:
                unidentified.add(box["id"])
            else:
                families[family].setdefault(box["id"], vp)
        if len(families) > bound:
            first_vp = next(iter(next(iter(families.values())).values()))
            listed = ", ".join(f"{name} ({len(boxes)})" for name, boxes in families.items())
            return Result(hits=[Hit(observed=f"{len(families)} icon families appear: {listed}",
                                    location=_where(first_vp),
                                    refs=[next(iter(boxes)) for boxes in families.values()])])
        if unidentified and len(families) + 1 > bound:
            return Result(skipped=f"{len(unidentified)} icons have no identified family, so the family count "
                                  "cannot be settled")
        return Result()
    return Result(skipped=f"icon-inventory has no check {check!r}")


def _has_equivalent(box: dict, media: dict) -> bool:
    return bool(media.get("decorative") or (media.get("alt") or "").strip()
                or ((box.get("a11y") or {}).get("name") or "").strip())


MEDIA_NOUN = {"img": "image", "picture": "image", "video": "video", "canvas": "canvas", "svg": "SVG image",
              "css-background": "background image"}


def _image_check(name: str, box: dict, media: dict, params: dict, threshold: dict) -> tuple[str | None, str | None]:
    """(observed, None) for an instance, (None, reason) when it cannot be judged, (None, None) otherwise."""
    kind, noun = media["kind"], MEDIA_NOUN[media["kind"]]
    if name == "decorative-clip-path":
        clip = (box.get("style") or {}).get("clip")
        if not clip or clip["kind"] not in ("polygon", "path"):
            return None, None
        jaggedness = clip.get("jaggedness")
        if jaggedness is None:
            return None, "clip paths without a measured jaggedness"
        if jaggedness < JAGGED_MIN:
            return None, None
        vertices = f" and {clip['vertices']} vertices" if "vertices" in clip else ""
        return f"{clip['kind']} clip path with jaggedness {jaggedness:.2f}{vertices} cuts the {noun}", None
    if name == "overlay-coverage":
        overlay = media.get("overlay")
        if not overlay:
            return None, None
        coverage, alpha = overlay.get("coverage"), overlay.get("alpha_max")
        if coverage is None or alpha is None:
            return None, "image overlays without measured coverage or opacity"
        bound = threshold.get("overlay_alpha_max")
        if coverage < params.get("min_covered_share", 0) or (bound is not None and alpha <= bound):
            return None, None
        return f"an overlay covers {coverage:.0%} of the {noun} at up to {alpha:.0%} opacity", None
    if name == "load-failure":
        host = f" from {media['host']}" if media.get("host") else ""
        return (f"{noun}{host} failed to load", None) if media["loaded"] is False else (None, None)
    if name == "unresolved-placeholder":
        return (f"{noun} is an unresolved placeholder", None) if media.get("placeholder") else (None, None)
    # missing-alternative: content images (img, picture) without alt text or an accessible name
    if kind not in ("img", "picture") or media.get("decorative"):
        return None, None
    if "alt" not in media:
        return None, "images whose alt attribute was not recorded"
    if media["alt"] is None and not ((box.get("a11y") or {}).get("name") or "").strip():
        return "content image has no text alternative (no alt attribute or accessible name)", None
    return None, None


IMAGE_CHECKS = ("decorative-clip-path", "overlay-coverage", "load-failure", "unresolved-placeholder",
                "missing-alternative")


@detector("image-inventory", layers=("render",))
def image_inventory(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    viewports, why = _viewports(ctx)
    if why:
        return Result(skipped=why)
    params, threshold = _params(det), _threshold(det)
    check = params.get("check")
    checks = [check] if isinstance(check, str) else list(check or [])
    unknown = [c for c in checks if c not in IMAGE_CHECKS]
    if not checks or unknown:
        return Result(skipped=f"image-inventory has no check {', '.join(unknown) or 'given'}")
    adjust = (rule.get("severity") or {}).get("adjust") or []
    kept = frozenset({EQUIVALENT_KEPT}) if any(a.get("when") == EQUIVALENT_KEPT for a in adjust) else frozenset()
    once, unjudged = _Once(), []
    for vp in viewports:
        for box in vp.get("boxes") or []:
            media = box.get("media")
            if not media:
                continue
            for name in checks:
                observed, reason = _image_check(name, box, media, params, threshold)
                if reason:
                    unjudged.append(f"{name} cannot judge {reason}")
                if observed is None:
                    continue
                conditions = (kept if name in ("load-failure", "unresolved-placeholder")
                              and _has_equivalent(box, media) else frozenset())
                once.add((name, box["id"]), vp, Hit(observed=observed, location=_where(vp, box["id"]),
                                                    conditions=conditions))
    return _finish(once.hits(), unjudged)


@detector("image-embedding-region", layers=("render",))
def image_embedding_region(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    viewports, why = _viewports(ctx)
    if why:
        return Result(skipped=why)
    key = det.get("list") or _params(det).get("list")
    if not key:
        return Result(skipped="the rule names no list of image regions")
    if not ctx.list_values(key):
        return Result(skipped=f"the rules have no {key!r} list of image regions")
    if not any((box.get("media") or {}).get("loaded") for vp in viewports for box in vp.get("boxes") or []):
        return Result()
    # Comparing crops with listed regions needs image embeddings. Extract v1 has no embedding field,
    # and no local image embedding model is installed, so nothing here can place an image in a region.
    return Result(skipped="image embeddings are unavailable: the render extract carries none and no local "
                          "image embedding model is installed")


# ---------------------------------------------------------------- typicality and references
# Each feature maps one capture to a value (None when the capture cannot give it) and two values to a
# distance in [0, 1]. Typicality and clone risk both use them.

def _derived(vp: dict) -> dict:
    return vp.get("derived") or {}


def _f_sequence(vp: dict, doc: dict) -> list[str] | None:
    return list(_derived(vp).get("section_sequence") or []) or None


def _d_sequence(a: list[str], b: list[str]) -> float:
    return edit_distance(a, b) / max(len(a), len(b))


def _f_archetypes(vp: dict, doc: dict) -> Counter | None:
    sequence = _derived(vp).get("section_sequence")
    return Counter(sequence) if sequence else None


def _d_archetypes(a: Counter, b: Counter) -> float:
    ta, tb = sum(a.values()), sum(b.values())
    return 0.5 * sum(abs(a[k] / ta - b[k] / tb) for k in set(a) | set(b))


def _f_scalar(key: str) -> Callable[[dict, dict], float | None]:
    return lambda vp, doc: _derived(vp).get(key)


def _d_scalar(a: float, b: float) -> float:
    return min(1.0, abs(a - b))


def _directed(x: list[tuple[Any, float]], y: list[tuple[Any, float]], gap: Callable[[Any, Any], float]) -> float:
    total = sum(w for _, w in x)
    weights = [w / total for _, w in x] if total > 0 else [1 / len(x)] * len(x)
    return sum(weight * min(gap(v, u) for u, _ in y) for (v, _), weight in zip(x, weights))


def _chamfer(a: list, b: list, gap: Callable[[Any, Any], float]) -> float:
    """Weighted mean gap from each item to its nearest counterpart, averaged over both directions."""
    return (_directed(a, b, gap) + _directed(b, a, gap)) / 2


def _f_palette(vp: dict, doc: dict) -> list | None:
    return [(e["oklch"], e["share"]) for e in vp.get("palette") or []] or None


def _d_palette(a: list, b: list) -> float:
    return min(1.0, _chamfer(a, b, delta_e_ok) / PALETTE_SCALE_DE)


def _f_roles(vp: dict, doc: dict) -> dict | None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for entry in vp.get("palette") or []:
        if entry.get("role_guess") not in (None, "unknown"):
            groups[entry["role_guess"]].append(entry)
    out = {}
    for role, entries in groups.items():
        total = sum(e["share"] for e in entries) or 1
        mixed = [sum(oklab(e["oklch"])[i] * e["share"] for e in entries) / total for i in range(3)]
        out[role] = from_oklab(*mixed, 1)
    return out or None


def _d_roles(a: dict, b: dict) -> float:
    return statistics.fmean(min(1.0, delta_e_ok(a[r], b[r]) / PALETTE_SCALE_DE) if r in a and r in b else 1.0
                            for r in set(a) | set(b))


def _f_type(vp: dict, doc: dict) -> list | None:
    roles = (_derived(vp).get("type_fingerprint") or {}).get("roles") or []
    return [(role, role.get("share", 0)) for role in roles if role.get("size_px")] or None


def _type_gap(x: dict, y: dict) -> float:
    gap = abs(math.log2(x["size_px"] / y["size_px"]))
    if "weight" in x and "weight" in y:
        gap += abs(x["weight"] - y["weight"]) / TYPE_WEIGHT_SCALE
    gap += abs(x.get("tracking_em", 0) - y.get("tracking_em", 0)) / TYPE_TRACKING_SCALE
    if x.get("transform", "none") != y.get("transform", "none"):
        gap += TYPE_TRANSFORM_GAP
    return min(1.0, gap)


def _d_type(a: list, b: list) -> float:
    return _chamfer(a, b, _type_gap)


def _f_radius(vp: dict, doc: dict) -> dict | None:
    by_role: dict[str, list[float]] = defaultdict(list)
    for box in vp.get("boxes") or []:
        radius = (box.get("style") or {}).get("radius_px")
        if box["role"] in CONTAINER_ROLES and radius is not None:
            by_role[box["role"]].append(radius)
    return {role: statistics.median(values) for role, values in by_role.items()} or None


def _d_radius(a: dict, b: dict) -> float | None:
    common = set(a) & set(b)
    if not common:
        return None
    return statistics.fmean(abs(a[r] - b[r]) / max(a[r], b[r]) if max(a[r], b[r]) > 0 else 0.0 for r in common)


def _f_spacing(vp: dict, doc: dict) -> dict | None:
    gaps = _derived(vp).get("gaps") or {}
    return {level: stats["median"] for level, stats in gaps.items()
            if isinstance(stats, dict) and stats.get("median")} or None


def _d_spacing(a: dict, b: dict) -> float | None:
    common = set(a) & set(b)
    if not common:
        return None
    return statistics.fmean(min(1.0, abs(math.log2(a[k] / b[k]))) for k in common)


def _f_states(vp: dict, doc: dict) -> dict | None:
    """Per state, the median change of text color and backdrop against the run at rest."""
    out = {}
    for state in ("hover", "focus", "active"):
        color_changes, backdrop_changes = [], []
        for run in vp.get("text") or []:
            forced = (run.get("states") or {}).get(state)
            if not forced:
                continue
            if run.get("color"):
                color_changes.append(delta_e_ok(run["color"], forced["color"]))
            if run.get("backdrop") and forced.get("backdrop"):
                backdrop_changes.append(delta_e_ok(run["backdrop"]["oklch"], forced["backdrop"]))
        if color_changes or backdrop_changes:
            out[state] = (statistics.median(color_changes) if color_changes else 0.0,
                          statistics.median(backdrop_changes) if backdrop_changes else 0.0)
    return out or None


def _d_states(a: dict, b: dict) -> float | None:
    common = set(a) & set(b)
    if not common:
        return None
    return statistics.fmean(min(1.0, max(abs(a[s][0] - b[s][0]), abs(a[s][1] - b[s][1])) / STATE_SCALE_DE)
                            for s in common)


def _f_ngram(vp: dict, doc: dict) -> dict | None:
    """Page text as exact shingles when the text is stored, and as the keyed viewport signature."""
    runs = vp.get("text") or []
    grams = None
    if runs and all(run.get("text") for run in runs):
        try:
            grams = text_sig.page_shingles([(run["text"], run["script"]) for run in runs])
        except ValueError:
            grams = None
    key = (doc.get("meta") or {}).get("sig_key_id")
    signature = vp.get("text_sig") if key else None
    if grams is None and signature is None:
        return None
    return {"grams": grams, "sig": signature, "key": key}


def _d_ngram(a: dict, b: dict) -> float | None:
    if a["grams"] and b["grams"]:
        return 1 - len(a["grams"] & b["grams"]) / len(a["grams"] | b["grams"])
    if a["sig"] and b["sig"] and a["key"] == b["key"]:
        return 1 - text_sig.similarity(a["sig"], b["sig"])
    return None


FEATURES: dict[str, tuple[Callable[[dict, dict], Any], Callable[[Any, Any], float | None]]] = {
    "section_sequence": (_f_sequence, _d_sequence),
    "archetypes": (_f_archetypes, _d_archetypes),
    "symmetry": (_f_scalar("symmetry"), _d_scalar),
    "density": (_f_scalar("density"), _d_scalar),
    "palette": (_f_palette, _d_palette),
    "color-roles": (_f_roles, _d_roles),
    "type": (_f_type, _d_type),
    "radius": (_f_radius, _d_radius),
    "spacing": (_f_spacing, _d_spacing),
    "states": (_f_states, _d_states),
    "ngram": (_f_ngram, _d_ngram),
}
# Without `features`, typicality compares the design; copy features (ngram) are compared only when
# named, and color-roles only when named, since it restates the palette by role.
DEFAULT_FEATURES = ("section_sequence", "archetypes", "symmetry", "density", "palette", "type", "radius",
                    "spacing", "states")
UNMEASURABLE = {"construction": "construction patterns need a morphological analyzer, and none is installed"}
DIMENSIONS = {"layout": ("section_sequence", "archetypes", "symmetry", "density"), "palette": ("palette",),
              "type": ("type",), "copy": ("ngram",)}


def _profile(ctx: Context, doc: dict) -> dict[tuple[int, str], dict[str, Any]]:
    key = ("render_visual.profile", id(doc))
    if key not in ctx.cache:
        ctx.cache[key] = {vp_key: {name: extract(vp, doc) for name, (extract, _) in FEATURES.items()}
                          for vp_key, vp in _plain(doc.get("viewports") or []).items()}
    return ctx.cache[key]


def _distances(ours: dict, theirs: dict, features: Iterable[str]) -> dict[str, float]:
    """Per feature, the mean distance over captures of the same width and theme (or width alone)."""
    pairs = [(ours[k], theirs[k]) for k in ours if k in theirs]
    if not pairs:
        by_width = {width: profile for (width, _), profile in theirs.items()}
        pairs = [(profile, by_width[width]) for (width, _), profile in ours.items() if width in by_width]
    out = {}
    for name in features:
        gap = FEATURES[name][1]
        values = [d for a, b in pairs if a[name] is not None and b[name] is not None
                  and (d := gap(a[name], b[name])) is not None]
        if values:
            out[name] = statistics.fmean(values)
    return out


@detector("typicality-distance", layers=("render",))
def typicality_distance(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    viewports, why = _viewports(ctx)
    if why:
        return Result(skipped=why)
    params = _params(det)
    bound = _threshold(det).get("distance_min")
    if bound is None:
        return Result(skipped="typicality-distance needs distance_min")
    named = params.get("features")
    excluded = set(params.get("exclude_features") or [])
    features = [f for f in (named or DEFAULT_FEATURES) if f not in excluded]
    for feature in features:
        if feature in UNMEASURABLE:
            return Result(skipped=UNMEASURABLE[feature])
    if unknown := [f for f in features if f not in FEATURES]:
        return Result(skipped=f"typicality-distance has no feature {', '.join(unknown)}")
    corpus = params.get("corpus")
    if not ctx.corpus:
        return Result(skipped="no typicality corpus was given")
    entries = [entry for entry in ctx.corpus if corpus is None or entry.get("_corpus") == corpus]
    if not entries:
        return Result(skipped=f"the typicality corpus has no {corpus} entries")

    ours = _profile(ctx, ctx.extract)
    available = [f for f in features if any(profile[f] is not None for profile in ours.values())]
    if named and len(available) < len(features):
        missing = ", ".join(f for f in features if f not in available)
        return Result(skipped=f"the render extract cannot give the typicality features {missing}")
    needed = len(features) if named else MIN_SHARED_FEATURES
    if len(available) < needed:
        return Result(skipped=f"the render extract gives only {len(available)} of the typicality features "
                              f"{', '.join(features)}")
    best = None
    for entry in entries:
        distances = _distances(ours, _profile(ctx, entry), available)
        if len(distances) < needed:
            continue
        total = statistics.fmean(distances.values())
        if best is None or total < best[0]:
            best = (total, entry, distances)
    if best is None:
        return Result(skipped=f"no {corpus or 'corpus'} entry shares enough of {', '.join(available)} "
                              "with the render to compare")
    total, entry, distances = best
    if total >= bound:
        return Result()
    per_feature = ", ".join(f"{name} {value:.2f}" for name, value in distances.items())
    return Result(hits=[Hit(
        observed=f"the render is {total:.3f} from the nearest {corpus or 'corpus'} entry ({_doc_label(entry)}), "
                 f"closer than {bound:g} ({per_feature})",
        distance=round(total, 4), refs=[_doc_label(entry)])])


@detector("reference-distance", layers=("render",))
def reference_distance(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    viewports, why = _viewports(ctx)
    if why:
        return Result(skipped=why)
    params = _params(det)
    bound = _threshold(det).get("distance_min")
    if bound is None:
        return Result(skipped="reference-distance needs distance_min")
    dimensions = list(params.get("dimensions") or DIMENSIONS)
    if unknown := [d for d in dimensions if d not in DIMENSIONS]:
        return Result(skipped=f"reference-distance has no dimension {', '.join(unknown)}")
    require_all = bool(params.get("require_all_dimensions"))
    if not ctx.refs:
        return Result(skipped="no reference profiles were given")
    rights = _rights(params.get("rights"))
    refs = [ref for ref in ctx.refs if ref.get("viewports")
            and (rights is None or (ref.get("reference") or {}).get("rights") in rights)]

    ours = _profile(ctx, ctx.extract)
    features = [f for d in dimensions for f in DIMENSIONS[d]]
    hits, unjudged = [], []
    for ref in refs:
        label = _doc_label(ref)
        found = _distances(ours, _profile(ctx, ref), features)
        per_dimension = {d: statistics.fmean(found[f] for f in DIMENSIONS[d] if f in found)
                         for d in dimensions if any(f in found for f in DIMENSIONS[d])}
        missing = [d for d in dimensions if d not in per_dimension]
        if require_all:
            if any(value >= bound for value in per_dimension.values()):
                continue
            if missing:
                close = ", and every compared dimension is close" if per_dimension else ""
                unjudged.append(f"{label}: {', '.join(missing)} cannot be compared{close}")
                continue
            distance = max(per_dimension.values())
        else:
            # Missing dimensions lie somewhere in [0, 1]; decide only when the mean is settled either way.
            low = sum(per_dimension.values()) / len(dimensions)
            distance = (sum(per_dimension.values()) + len(missing)) / len(dimensions)
            if low >= bound:
                continue
            if distance >= bound:
                unjudged.append(f"{label}: {', '.join(missing)} cannot be compared")
                continue
        rights_label = (ref.get("reference") or {}).get("rights", "unlabeled")
        parts = ", ".join(f"{d} {v:.2f}" for d, v in per_dimension.items())
        hits.append(Hit(
            observed=f"the render is close to the {rights_label} reference {label} ({parts}; bound {bound:g})",
            distance=round(distance, 4), refs=[label]))
    return _finish(hits, unjudged)


def _hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


@detector("reference-asset-match", layers=("render",))
def reference_asset_match(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    viewports, why = _viewports(ctx)
    if why:
        return Result(skipped=why)
    if not ctx.refs:
        return Result(skipped="no reference profiles were given")
    rights = _rights(_params(det).get("rights")) or {"reference-only"}
    refs = [ref for ref in ctx.refs if (ref.get("reference") or {}).get("rights") in rights]
    if not refs:
        return Result()
    our_key = (ctx.extract.get("meta") or {}).get("sig_key_id")
    images = [(vp, box) for vp in viewports for box in vp.get("boxes") or [] if (box.get("media") or {}).get("phash")]
    runs = [(vp, run) for vp in viewports for run in vp.get("text") or []
            if run.get("text_sig") and run["chars"] >= TEXT_MATCH_MIN_CHARS]
    signed = any(run.get("text_sig") for vp in viewports for run in vp.get("text") or [])
    if not images and not signed:
        return Result(skipped="the render extract carries no image hashes or text signatures")

    once, unjudged = _Once(), []
    for ref in refs:
        label = _doc_label(ref)
        rights_label = ref["reference"]["rights"]
        ref_viewports = ref.get("viewports") or []
        hashes = {box["media"]["phash"] for vp in ref_viewports for box in vp.get("boxes") or []
                  if (box.get("media") or {}).get("phash")}
        for vp, box in images:
            gap = min((_hamming(box["media"]["phash"], h) for h in hashes), default=None)
            if gap is not None and gap <= PHASH_MAX_DISTANCE:
                once.add(("image", box["id"]), vp, Hit(
                    observed=f"{MEDIA_NOUN[box['media']['kind']]} matches an image of the {rights_label} reference "
                             f"{label} ({gap} of 64 perceptual-hash bits differ)",
                    location=_where(vp, box["id"]), evidence="image", refs=[label]))
        signatures = [run["text_sig"] for vp in ref_viewports for run in vp.get("text") or []
                      if run.get("text_sig") and run["chars"] >= TEXT_MATCH_MIN_CHARS]
        if not signatures or (signed and not runs):
            continue
        ref_key = (ref.get("meta") or {}).get("sig_key_id")
        if not signed:
            unjudged.append("the render's text runs carry no signatures to compare with the references' copy")
            continue
        if ref_key != our_key:
            unjudged.append(f"the copy of {label} was signed with key {ref_key} and the render's with key "
                            f"{our_key}, so they cannot be compared")
            continue
        for vp, run in runs:
            similarity = max(text_sig.similarity(run["text_sig"], s) for s in signatures)
            if similarity >= TEXT_MATCH_MIN:
                text = f'"{_snippet(run["text"])}"' if run.get("text") else f"run {run['id']}"
                once.add(("text", run["id"]), vp, Hit(
                    observed=f"text {text} matches copy of the {rights_label} reference {label} "
                             f"(signature similarity {similarity:.2f})",
                    location=_where(vp, run["box"]), refs=[label]))
    return _finish(once.hits(), unjudged)
