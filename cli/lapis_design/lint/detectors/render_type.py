"""Type, contrast, target, overflow, and occlusion detectors on the render extract.

Render detectors read the render extract (render/extract.schema.yaml; meanings in render/DERIVED.md).
A text run or box seen in several captures is one hit whose observation lists the captures. The
`browser_chrome` capture repeats the 390 px light layout with less visible height; only the
dynamic-viewport check reads it. A rule with `locales` sees only the text runs of those locales.

When part of the input a detector needs is missing and nothing hit, the detector skips with the
reason instead of passing. Runs whose box is at most 1 px wide or tall (visually hidden text) are
not judged.

rendered-family-region judges rendered families against the font feature regions of rules.yaml
`lists`, as vocab/type.yaml `font_feature_regions` defines them, with the measured-face lookup it
shares with plan-font-region (font_regions.py). Reports name the family and its measured classes,
never a local font's file or PostScript name.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable

from lapis_design import system_fonts
from lapis_design.lint.detectors.font_regions import definitions, describe, faces, judge_face, pick, region_list
from lapis_design.lint.types import Context, Hit, Result, detector
from lapis_design.render.color import contrast_ratio, delta_e_ok, oklab, to_oklch
from lazuli.scan import norm as family_norm

HEADINGS = ("display", "heading")
CONTROLS = ("button", "link", "input")
SCRIPT_NAMES = {"latn": "Latin", "cyrl": "Cyrillic", "grek": "Greek", "hang": "Hangul", "kana": "Japanese",
                "hani": "Han", "arab": "Arabic", "hebr": "Hebrew", "thai": "Thai", "mixed": "mixed-script",
                "other": "other-script"}
TRACKED_EM = 0.05          # eyebrow labels: letter-spacing at or above this reads as tracked
LABEL_CHARS = 40           # DERIVED.md label role: at most 40 characters
MARKER_CHARS = 8           # a standalone index marker such as "01", "(02)", "No. 3"
OCCLUDED_SHARE = 0.2       # share of a text box an opaque layer painted above must cover
OPAQUE_ALPHA = 0.5         # background or gradient alpha at or above this hides what is below
CHROME_PX = 180            # DERIVED.md: emulated browser UI covers 180 px of the 390 x 844 layout
LARGE_PX, LARGE_BOLD_PX, BOLD = 24.0, 18.66, 700   # WCAG large text: 18 pt, or 14 pt bold
GRAY_L = (0.15, 0.95)      # gray-on-color: neutral text lighter than near-black, darker than near-white
REF_LIMIT = 12

INDEX_MARKER = re.compile(r"[/(\[#№]?\s*(?:no\.?\s*)?0*(\d{1,2})\s*[.)\]/:—–-]?\s*(?:/\s*\d{1,2})?", re.I)
INDEX_PREFIX = re.compile(r"\s*(?:\(?0(\d)\)?|(\d{1,2})[.)])\s*[/:—–-]?\s+\S")


# ---------------------------------------------------------------- extract access

@dataclass
class View:
    """One captured viewport with its boxes indexed and its text runs limited to the rule's locales."""
    vp: dict
    boxes: dict[str, dict]
    runs: list[dict]                                   # painted runs of the rule's locales, document order
    runs_by_box: dict[str, list[dict]]
    label: str
    width: int
    chains: dict[str, tuple[str, ...]] = field(default_factory=dict)
    sections: dict[str, str] | None = None             # derived section box id -> archetype

    @classmethod
    def of(cls, vp: dict, keep: Callable[[dict], bool]) -> "View":
        boxes = {b["id"]: b for b in vp.get("boxes") or []}
        runs = []
        for run in vp.get("text") or []:
            rect = (boxes.get(run.get("box")) or {}).get("rect")
            if (rect is None or (rect["w"] > 1 and rect["h"] > 1)) and keep(run):
                runs.append(run)
        by_box: dict[str, list[dict]] = {}
        for run in runs:
            by_box.setdefault(run["box"], []).append(run)
        label = f"{vp['width']} px {vp.get('theme', 'light')}"
        if vp.get("reduced_motion"):
            label += " reduced motion"
        if vp.get("browser_chrome"):
            label += " with browser UI"
        derived = vp.get("derived") or {}
        sections = ({s["box"]: s.get("archetype", "other") for s in derived["sections"]}
                    if "sections" in derived else None)
        return cls(vp, boxes, runs, by_box, label, vp["width"], sections=sections)

    def chain(self, box_id: str) -> tuple[str, ...]:
        """Ancestor ids of a box, nearest first."""
        if box_id not in self.chains:
            out, seen = [], {box_id}
            parent = (self.boxes.get(box_id) or {}).get("parent")
            while parent and parent not in seen:
                out.append(parent)
                seen.add(parent)
                parent = (self.boxes.get(parent) or {}).get("parent")
            self.chains[box_id] = tuple(out)
        return self.chains[box_id]

    def contains(self, outer: str, inner: str) -> bool:
        return outer == inner or outer in self.chain(inner)

    def related(self, a: str, b: str) -> bool:
        return self.contains(a, b) or self.contains(b, a)

    def rect(self, box_id: str) -> dict | None:
        return (self.boxes.get(box_id) or {}).get("rect")

    def section_of(self, box_id: str) -> str | None:
        """The derived section (DERIVED.md sections) holding a box."""
        return next((b for b in (box_id, *self.chain(box_id)) if b in (self.sections or {})), None)

    def band_of(self, box_id: str) -> str | None:
        """The nearest section-role box holding a box that spans at least half the viewport width,
        so cards (article boxes in a grid) are not taken for page sections."""
        return next((b for b in (box_id, *self.chain(box_id)) if (box := self.boxes.get(b))
                     and box.get("role") == "section" and box["rect"]["w"] >= self.width / 2), None)

    def location(self, box_id: str | None = None) -> dict:
        return {"viewport": self.width, **({"box": box_id} if box_id else {})}


def views(ctx: Context, rule: dict) -> tuple[list[View], str | None]:
    """The extract's captures, with text runs limited to the rule's `locales` (the engine runs a
    locale-limited rule on the whole extract; each detector restricts its own runs)."""
    if not ctx.extract:
        return [], "no render extract given"
    locales = tuple(sorted(rule.get("locales") or ()))
    memo = ctx.cache.get("render_type.views")
    if memo is None or memo[0] is not ctx.extract:
        memo = (ctx.extract, {})
        ctx.cache["render_type.views"] = memo
    if locales not in memo[1]:
        if not locales or "all" in locales:
            keep: Callable[[dict], bool] = lambda run: True  # noqa: E731
        else:
            from lapis_design.lint.engine import in_locales   # the engine imports this module

            keep = lambda run: in_locales(run, locales)  # noqa: E731
        memo[1][locales] = [View.of(vp, keep) for vp in ctx.extract.get("viewports") or []]
    found = memo[1][locales]
    if not found:
        return [], "the render extract has no viewports"
    return found, None


def layout_views(all_views: list[View], width: int | None = None) -> list[View]:
    return [v for v in all_views if not v.vp.get("browser_chrome") and (width is None or v.width == width)]


class Hits:
    """Hits keyed by what they describe, so one element seen in several captures is one hit."""

    def __init__(self) -> None:
        self.seen: dict[Any, tuple[Hit, list[str]]] = {}

    def add(self, key: Any, view: View, hit: Hit) -> None:
        if key in self.seen:
            if view.label not in self.seen[key][1]:
                self.seen[key][1].append(view.label)
        else:
            self.seen[key] = (hit, [view.label])

    def __bool__(self) -> bool:
        return bool(self.seen)

    def hits(self) -> list[Hit]:
        return [replace(hit, observed=f"{hit.observed} (at {', '.join(labels)})") for hit, labels in self.seen.values()]


def finish(hits: Hits | list[Hit], unjudged: Iterable[str] = ()) -> Result:
    """Hits when there are any; otherwise a skip when something could not be judged; else a pass."""
    found = hits.hits() if isinstance(hits, Hits) else hits
    if found:
        return Result(hits=found)
    reasons = list(dict.fromkeys(reason for reason in unjudged if reason))
    return Result(skipped="; ".join(reasons)) if reasons else Result()


def quote(text: str | None, limit: int = 32) -> str:
    text = " ".join((text or "").split())
    if not text:
        return "(no text)"
    return f"'{text[:limit - 1]}…'" if len(text) > limit else f"'{text}'"


def refs(items: Iterable[dict], key: str = "box") -> list[str]:
    return list(dict.fromkeys(item[key] for item in items if item.get(key)))[:REF_LIMIT]


def count(runs: list[dict]) -> str:
    chars = sum(r.get("chars", 0) for r in runs)
    return f"{len(runs)} run{'s' if len(runs) != 1 else ''}, {chars} characters"


def script_name(script: str | None) -> str:
    return SCRIPT_NAMES.get(script or "other", script or "unknown-script")


def bound(value: Any, script: str | None = None) -> float | None:
    """A threshold that is a number or a per-script map (`other` covers unlisted scripts)."""
    if isinstance(value, dict):
        picked = value.get(script) if script else None
        if picked is None:
            picked = value.get("other", value.get("all"))
        return picked
    return value


def weighted_median(pairs: list[tuple[float, float]]) -> float:
    items = sorted(pairs)
    total = sum(w for _, w in items)
    acc = 0.0
    for value, weight in items:
        acc += weight
        if acc >= total / 2:
            return value
    return items[-1][0]


def edges(rect: dict) -> tuple[float, float, float, float]:
    return rect["x"], rect["y"], rect["x"] + rect["w"], rect["y"] + rect["h"]


def intersection(a: tuple, b: tuple) -> tuple | None:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def union_area(rects: list[tuple]) -> float:
    xs = sorted({r[0] for r in rects} | {r[2] for r in rects})
    area = 0.0
    for x0, x1 in zip(xs, xs[1:]):
        spans = sorted((r[1], r[3]) for r in rects if r[0] <= x0 and r[2] >= x1)
        covered, top, bottom = 0.0, None, None
        for y0, y1 in spans:
            if bottom is None or y0 > bottom:
                if bottom is not None:
                    covered += bottom - top
                top, bottom = y0, y1
            else:
                bottom = max(bottom, y1)
        if bottom is not None:
            covered += bottom - top
        area += covered * (x1 - x0)
    return area


def all_caps(text: str) -> bool:
    cased = [c for c in text if c.isupper() or c.islower()]
    return len(cased) >= 2 and all(c.isupper() for c in cased)


def is_emoji_family(name: str) -> bool:
    return "emoji" in name.casefold()


# ---------------------------------------------------------------- color

def srgb(color: list[float]) -> tuple[float, float, float]:
    """Gamma-encoded sRGB channels (0-1, clipped) of an OKLCH color."""
    l, a, b = oklab(color)
    lm = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3
    mm = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3
    sm = (l - 0.0894841775 * a - 1.2914855480 * b) ** 3
    linear = (4.0767416621 * lm - 3.3077115913 * mm + 0.2309699292 * sm,
              -1.2684380046 * lm + 2.6097574011 * mm - 0.3413193965 * sm,
              -0.0041960863 * lm - 0.7034186147 * mm + 1.7076147010 * sm)
    return tuple(12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
                 for v in (min(1.0, max(0.0, c)) for c in linear))


def over(fg: list[float], bg: list[float]) -> list[float]:
    """The text color as painted: a translucent color composited over its backdrop in sRGB."""
    alpha = fg[3] if len(fg) > 3 else 1.0
    if alpha >= 1:
        return fg[:3]
    mixed = [255 * (alpha * f + (1 - alpha) * b) for f, b in zip(srgb(fg), srgb(bg))]
    return to_oklch(f"rgb({mixed[0]:.4f} {mixed[1]:.4f} {mixed[2]:.4f})") or bg[:3]


def contrast(fg: list[float], bg: list[float]) -> float:
    return contrast_ratio(over(fg, bg), bg[:3])


# ---------------------------------------------------------------- fonts

@detector("font-fallback", layers=("render",))
def font_fallback(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    hits = Hits()
    generic = system_fonts.generic_families()
    any_runs = False
    for view in layout_views(all_views):
        groups: dict[tuple, list[dict]] = {}
        for run in view.runs:
            any_runs = True
            font = run.get("font") or {}
            requested, rendered = font.get("requested", ""), font.get("rendered", "")
            if not requested or requested.casefold() in generic or is_emoji_family(rendered):
                continue
            if font.get("fallback", rendered.casefold() != requested.casefold()):
                groups.setdefault((requested.casefold(), rendered.casefold(), run.get("script")), []).append(run)
        for key, runs in groups.items():
            font = runs[0]["font"]
            hits.add(key, view, Hit(
                observed=f"{script_name(key[2])} text requested in '{font['requested']}' renders in "
                         f"'{font['rendered']}' ({count(runs)})",
                location=view.location(runs[0]["box"]), refs=refs(runs)))
    if not any_runs:
        return Result(skipped="the render extract has no text runs")
    return finish(hits)


@detector("synthetic-style", layers=("render",))
def synthetic_style(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    hits = Hits()
    unrecorded: set[str] = set()
    for view in layout_views(all_views):
        groups: dict[tuple, list[dict]] = {}
        for run in view.runs:
            font = run.get("font") or {}
            kind = font.get("synthetic")
            if kind is None:
                unrecorded.add(run["box"])
            elif kind != "none":
                groups.setdefault((font.get("rendered", "").casefold(), kind, run.get("weight"),
                                   run.get("style", "normal")), []).append(run)
        for key, runs in groups.items():
            kind = {"both": "bold and italic"}.get(key[1], key[1])
            weight = f" at weight {key[2]:g}" if isinstance(key[2], (int, float)) else ""
            hits.add(key, view, Hit(
                observed=f"'{runs[0]['font'].get('rendered', '')}' is synthesized {kind}{weight}, "
                         f"{key[3]} ({count(runs)})",
                location=view.location(runs[0]["box"]), refs=refs(runs)))
    return finish(hits, [f"{len(unrecorded)} text boxes have no synthesized-style record" if unrecorded else ""])


@detector("hangul-negative-tracking", layers=("render",))
def hangul_negative_tracking(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    lowest = (det.get("threshold") or {}).get("min", 0)
    hits = Hits()
    unjudged = []
    for view in layout_views(all_views):
        groups: dict[tuple, list[dict]] = {}
        for run in view.runs:
            if run.get("script") != "hang":
                continue
            if "type_role" not in run:
                unjudged.append("Hangul text runs have no type role")
                continue
            if run["type_role"] != "body":
                continue
            spacing = run.get("letter_spacing_em")
            if spacing is None:
                unjudged.append("Hangul body runs have no letter-spacing")
            elif spacing < lowest:
                groups.setdefault((round(spacing, 3), run["font"].get("rendered", "")), []).append(run)
        for (spacing, family), runs in groups.items():
            hits.add((spacing, family.casefold()), view, Hit(
                observed=f"Hangul body text in '{family}' is tracked {spacing:+g} em, below {lowest:g} em "
                         f"({count(runs)})",
                location=view.location(runs[0]["box"]), refs=refs(runs)))
    return finish(hits, unjudged)


@detector("keep-all-missing", layers=("render",))
def keep_all_missing(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    hits = Hits()
    unjudged = []
    for view in layout_views(all_views):
        groups: dict[str, list[dict]] = {}
        for run in view.runs:
            if run.get("script") != "hang":
                continue
            if "type_role" not in run:
                unjudged.append("Hangul text runs have no type role")
                continue
            if run["type_role"] != "body":
                continue
            value = run.get("word_break")
            if value is None:
                unjudged.append("Hangul body runs have no word-break value")
            elif value != "keep-all":
                groups.setdefault(value, []).append(run)
        for value, runs in groups.items():
            wrapped = sum(1 for r in runs if (r.get("lines") or 0) > 1)
            hits.add(value, view, Hit(
                observed=f"Hangul body text uses word-break {value} instead of keep-all ({count(runs)}, "
                         f"{wrapped} wrapping across lines)",
                location=view.location(runs[0]["box"]), refs=refs(runs)))
    return finish(hits, unjudged)


# ---------------------------------------------------------------- hierarchy and metrics

def run_contrast(run: dict) -> float | None:
    color, backdrop = run.get("color"), (run.get("backdrop") or {}).get("oklch")
    return contrast(color, backdrop) if color and backdrop else None


def symmetric(a: float | None, b: float | None) -> float | None:
    if not a or not b:
        return None
    return max(a / b, b / a)


@detector("type-hierarchy", layers=("render",))
def type_hierarchy(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    check = (det.get("params") or {}).get("check")
    if check == "flat":
        return flat_hierarchy(all_views, det)
    if check == "oversized":
        return oversized_display(all_views, det)
    return Result(skipped=f"unknown type-hierarchy check {check!r}")


def flat_hierarchy(all_views: list[View], det: dict) -> Result:
    params, threshold = det.get("params") or {}, det.get("threshold") or {}
    levers = list(params.get("levers") or ("size", "weight", "contrast"))
    if unknown := [lever for lever in levers if lever not in ("size", "weight", "contrast")]:
        return Result(skipped=f"unknown hierarchy levers {unknown}")
    need = threshold.get("heading_body_ratio_min")
    if need is None:
        return Result(skipped="the rule sets no heading_body_ratio_min")
    hits = Hits()
    unjudged = []
    for view in layout_views(all_views):
        if any("type_role" not in run for run in view.runs):
            unjudged.append("text runs have no type role")
            continue
        body = [r for r in view.runs if r["type_role"] == "body"]
        headings = [r for r in view.runs if r["type_role"] in HEADINGS]
        if not body or not headings:
            continue
        chars = lambda r: max(1, r.get("chars", 1))  # noqa: E731
        body_contrasts = [(c, chars(r)) for r in body if (c := run_contrast(r))]
        body_weights = [(r["weight"], chars(r)) for r in body if "weight" in r]
        reference = {
            "size": weighted_median([(r["size_px"], chars(r)) for r in body]),
            "weight": weighted_median(body_weights) if body_weights else None,
            "contrast": weighted_median(body_contrasts) if body_contrasts else None,
        }
        groups: dict[tuple, list[dict]] = {}
        for run in headings:
            color = tuple(round(v, 2) for v in run.get("color") or ())
            groups.setdefault((round(run["size_px"], 2), run.get("weight"), color), []).append(run)
        for (size, weight, _), runs in groups.items():
            contrasts = sorted(c for r in runs if (c := run_contrast(r)))
            ratios = {
                "size": symmetric(size, reference["size"]),
                "weight": symmetric(weight, reference["weight"]),
                "contrast": symmetric(contrasts[len(contrasts) // 2] if contrasts else None, reference["contrast"]),
            }
            known = {lever: ratios[lever] for lever in levers if ratios[lever] is not None}
            if any(value >= need for value in known.values()):
                continue
            if len(known) < len(levers):
                absent = ", ".join(lever for lever in levers if lever not in known)
                unjudged.append(f"headings at {size:g} px: {absent} not measured")
                continue
            detail = ", ".join(f"{lever} {value:.2f}x" for lever, value in known.items())
            body_weight = f"/{reference['weight']:g}" if reference["weight"] else ""
            head_weight = f"/{weight:g}" if weight else ""
            hits.add((size, weight, reference["size"], reference["weight"]), view, Hit(
                observed=f"headings {quote(runs[0].get('text'))} at {size:g} px{head_weight} against body "
                         f"{reference['size']:g} px{body_weight}: {detail}; no lever reaches {need:g}x",
                location=view.location(runs[0]["box"]), refs=refs(runs)))
    return finish(hits, unjudged)


def oversized_display(all_views: list[View], det: dict) -> Result:
    threshold = det.get("threshold") or {}
    share_max, lines_max = threshold.get("first_viewport_area_share_max"), threshold.get("lines_at_390_max")
    if share_max is None and lines_max is None:
        return Result(skipped="the rule sets no oversized-display bound")
    hits = Hits()
    unjudged = []
    layouts = layout_views(all_views)
    if any("type_role" not in run for view in layouts for run in view.runs):
        return Result(skipped="text runs have no type role")
    if share_max is not None:
        for view in layouts:
            display = [r for r in view.runs if r["type_role"] == "display"]
            if not display:
                continue
            height = view.vp.get("height")
            if not height:
                unjudged.append(f"the {view.width} px capture has no viewport height")
                continue
            first = (0, 0, view.width, height)
            parts = [part for box in dict.fromkeys(r["box"] for r in display)
                     if (rect := view.rect(box)) and (part := intersection(edges(rect), first))]
            share = union_area(parts) / (view.width * height) if parts else 0.0
            if share > share_max:
                hits.add(("area", view.width), view, Hit(
                    observed=f"display text {quote(display[0].get('text'))} covers {share:.0%} of the first "
                             f"viewport ({view.width} x {height:g} px), above {share_max:.0%}",
                    location=view.location(display[0]["box"]), refs=refs(display)))
    if lines_max is not None:
        narrow = layout_views(all_views, 390)
        if not narrow:
            unjudged.append("the render extract has no 390 px capture")
        for view in narrow:
            by_box: dict[str, list[dict]] = {}
            for run in view.runs:
                if run["type_role"] == "display":
                    by_box.setdefault(run["box"], []).append(run)
            for box, runs in by_box.items():
                lines = [r["lines"] for r in runs if "lines" in r]
                if not lines:
                    unjudged.append("display runs at 390 px have no line count")
                elif max(lines) > lines_max:
                    hits.add(("lines", box), view, Hit(
                        observed=f"display heading {quote(runs[0].get('text'))} wraps to {max(lines)} lines "
                                 f"at 390 px, above {lines_max:g}",
                        location=view.location(box), refs=[box]))
    return finish(hits, unjudged)


RUN_METRICS = {
    "letter_spacing_em": ("letter-spacing", lambda v: f"{v:+.3g} em"),
    "line_height": ("line-height", lambda v: f"{v:.3g}"),
    "measure_chars": ("measure", lambda v: f"{v:.0f} characters per line"),
    "size_px": ("size", lambda v: f"{v:.4g} px"),
    "lines": ("line count", lambda v: f"{v:.0f} lines"),
}
PAGE_METRICS = ("rows", "uppercase_run_words", "distinct_families")


def role_match(view: View, run: dict, roles: set[str] | None) -> bool:
    if roles is None:
        return True
    return run.get("type_role") in roles or (view.boxes.get(run["box"]) or {}).get("role") in roles


@detector("text-metrics", layers=("render",))
def text_metrics(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    params, threshold = det.get("params") or {}, det.get("threshold") or {}
    metric = params.get("metric")
    if metric not in RUN_METRICS and metric not in PAGE_METRICS:
        return Result(skipped=f"unknown text metric {metric!r}")
    if threshold.get("min") is None and threshold.get("max") is None:
        return Result(skipped="the rule sets no min or max")
    roles = set(params["roles"]) if params.get("roles") else None
    selected = layout_views(all_views, params.get("viewport"))
    if not selected:
        return Result(skipped=f"the render extract has no {params.get('viewport')} px capture")
    if metric in RUN_METRICS:
        return run_metric(selected, metric, roles, threshold)
    if metric == "rows":
        return rows_metric(selected, roles, threshold)
    if metric == "uppercase_run_words":
        return caps_metric(selected, roles, threshold)
    return families_metric(selected, roles, threshold)


def run_metric(selected: list[View], metric: str, roles: set[str] | None, threshold: dict) -> Result:
    name, fmt = RUN_METRICS[metric]
    hits = Hits()
    unjudged = []
    for view in selected:
        groups: dict[tuple, list[tuple[float, dict]]] = {}
        for run in view.runs:
            if roles is not None and "type_role" not in run:
                unjudged.append("text runs have no type role")
                continue
            if not role_match(view, run, roles):
                continue
            value = run.get(metric)
            if value is None:
                unjudged.append(f"text runs have no {metric}")
                continue
            script = run.get("script")
            low, high = bound(threshold.get("min"), script), bound(threshold.get("max"), script)
            if low is not None and value < low:
                groups.setdefault((run.get("type_role"), script, "below", low), []).append((value, run))
            elif high is not None and value > high:
                groups.setdefault((run.get("type_role"), script, "above", high), []).append((value, run))
        for (role, script, side, edge), items in groups.items():
            values = [v for v, _ in items]
            worst = min(values) if side == "below" else max(values)
            runs = [r for _, r in items]
            example = next(r for v, r in items if v == worst)
            hits.add((role, script, side, tuple(sorted({round(v, 3) for v in values}))), view, Hit(
                observed=f"{role or 'untyped'} {script_name(script)} text has {name} {fmt(worst)} {side} "
                         f"{fmt(edge)} in {count(runs)}, e.g. {quote(example.get('text'))}",
                location=view.location(example["box"]), refs=refs(runs)))
    return finish(hits, unjudged)


def bands(rects: list[tuple[str, dict]]) -> list[list[str]]:
    """Group boxes into rows: a box joins a row when it overlaps the row vertically by at least
    half of the smaller height."""
    out: list[tuple[float, float, list[str]]] = []
    for box, rect in sorted(rects, key=lambda item: item[1]["y"] + item[1]["h"] / 2):
        top, bottom = rect["y"], rect["y"] + rect["h"]
        if out:
            row_top, row_bottom, members = out[-1]
            overlap = min(bottom, row_bottom) - max(top, row_top)
            if overlap >= 0.5 * min(rect["h"], row_bottom - row_top):
                out[-1] = (min(top, row_top), max(bottom, row_bottom), members + [box])
                continue
        out.append((top, bottom, [box]))
    return [members for _, _, members in out]


def rows_metric(selected: list[View], roles: set[str] | None, threshold: dict) -> Result:
    """Distinct rows of the role's text inside one box of that role. Items stacked one per row
    (a vertical list) are one column, not wrapped rows; a run that wraps adds its own lines."""
    high = bound(threshold.get("max"))
    low = bound(threshold.get("min"))
    hits = Hits()
    for view in selected:
        containers = {b for b, box in view.boxes.items() if roles is None or box.get("role") in roles}
        assigned: dict[str, list[dict]] = {}
        for run in view.runs:
            if roles is not None and run.get("type_role") not in roles and \
                    (view.boxes.get(run["box"]) or {}).get("role") not in roles:
                continue
            home = next((b for b in (run["box"], *view.chain(run["box"])) if b in containers),
                        (view.boxes.get(run["box"]) or {}).get("parent") or run["box"])
            assigned.setdefault(home, []).append(run)
        for home, runs in assigned.items():
            groups: dict[str, list[dict]] = {}
            for run in runs:
                chain = (run["box"], *view.chain(run["box"]))
                below = chain[:chain.index(home)] if home in chain else chain
                group = next((b for b in below if (view.boxes.get(b) or {}).get("role") == "list"), home)
                groups.setdefault(group, []).append(run)
            rows = 1
            for members in groups.values():
                rects = [(box, rect) for box in dict.fromkeys(r["box"] for r in members) if (rect := view.rect(box))]
                found = bands(rects)
                if any(len(row) > 1 for row in found):
                    rows = max(rows, len(found))
            rows = max(rows, *(r.get("lines") or 1 for r in runs))
            if (high is not None and rows > high) or (low is not None and rows < low):
                edge = f"above {high:g}" if high is not None and rows > high else f"below {low:g}"
                hits.add((home, rows), view, Hit(
                    observed=f"{(view.boxes.get(home) or {}).get('role', 'text')} text runs over {rows} rows, "
                             f"{edge}, starting {quote(runs[0].get('text'))}",
                    location=view.location(home), refs=refs(runs)))
    return finish(hits)


def caps_metric(selected: list[View], roles: set[str] | None, threshold: dict) -> Result:
    high = bound(threshold.get("max"))
    hits = Hits()
    unjudged = []
    for view in selected:
        for run in view.runs:
            if not role_match(view, run, roles):
                continue
            text = run.get("text")
            if text is None:
                unjudged.append("text runs have no text")
                continue
            if run.get("transform") != "uppercase" and not all_caps(text):
                continue
            words = sum(1 for word in text.split() if any(c.isalpha() for c in word))
            if high is not None and words > high:
                hits.add((run["box"], text), view, Hit(
                    observed=f"{words} words set in capitals, above {high:g}: {quote(text, 48)}",
                    location=view.location(run["box"]), refs=[run["box"]]))
    return finish(hits, unjudged)


def families_metric(selected: list[View], roles: set[str] | None, threshold: dict) -> Result:
    low, high = bound(threshold.get("min")), bound(threshold.get("max"))
    hits = Hits()
    for view in selected:
        families: dict[str, str] = {}
        for run in view.runs:
            rendered = (run.get("font") or {}).get("rendered", "")
            if rendered and not is_emoji_family(rendered) and role_match(view, run, roles):
                families.setdefault(rendered.casefold(), rendered)
        if not families:
            continue
        n = len(families)
        if (low is not None and n < low) or (high is not None and n > high):
            edge = f"below {low:g}" if low is not None and n < low else f"above {high:g}"
            names = ", ".join(f"'{name}'" for name in families.values())
            hits.add(tuple(sorted(families)), view, Hit(
                observed=f"text renders in {n} distinct famil{'y' if n == 1 else 'ies'} ({names}), {edge}",
                location=view.location()))
    return finish(hits)


# ---------------------------------------------------------------- labels before headings

def heading_starts(view: View) -> list[tuple[int, str]]:
    """(run index, heading box) of the first run of each heading, in document order."""
    out, seen = [], set()
    for i, run in enumerate(view.runs):
        if run.get("type_role") not in HEADINGS:
            continue
        anchor = next((b for b in (run["box"], *view.chain(run["box"]))
                       if (view.boxes.get(b) or {}).get("role") == "heading"), run["box"])
        if anchor not in seen:
            seen.add(anchor)
            out.append((i, anchor))
    return out


def lead_in(view: View, index: int, anchor: str, section_of: Callable[[str], str | None]) -> dict | None:
    """The run right before a heading in document order when it sits just above the heading, in
    the same section and horizontally overlapping it."""
    heading = view.runs[index]
    prev = next((r for r in reversed(view.runs[:index]) if not view.contains(anchor, r["box"])), None)
    if prev is None or view.related(prev["box"], anchor):
        return None
    top, low = view.rect(anchor), view.rect(prev["box"])
    if top is None or low is None or section_of(prev["box"]) != section_of(anchor):
        return None
    bottom = low["y"] + low["h"]
    overlap = min(top["x"] + top["w"], low["x"] + low["w"]) - max(top["x"], low["x"])
    if bottom > top["y"] + 2 or top["y"] - bottom > 2 * heading["size_px"] or overlap <= 0:
        return None
    return prev


def chip(view: View, run: dict, anchor: str) -> str | None:
    """The small bounded box (background, border, or shadow) that holds a run, within two levels."""
    for box_id in (run["box"], *view.chain(run["box"])[:2]):
        if view.contains(box_id, anchor):
            return None
        box = view.boxes.get(box_id) or {}
        style = box.get("style") or {}
        if box.get("rect", {}).get("h", math.inf) > 3 * run["size_px"]:
            continue
        background = style.get("background")
        if background:
            behind = next((style_bg for b in view.chain(box_id)
                           if (style_bg := ((view.boxes.get(b) or {}).get("style") or {}).get("background"))), None)
            if behind is None or delta_e_ok(background, behind) > 0.02:
                return box_id
        if style.get("border_px") or style.get("shadow"):
            return box_id
    return None


@detector("eyebrow-relation", layers=("render",))
def eyebrow_relation(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    kind = (det.get("params") or {}).get("kind", "label")
    if kind not in ("label", "badge"):
        return Result(skipped=f"unknown eyebrow kind {kind!r}")
    repeats_max = (det.get("threshold") or {}).get("repeats_max")
    hits = Hits()
    unjudged = []
    layouts = layout_views(all_views)
    widest = max((v.width for v in layouts), default=None)
    # Sections and their labels are the same content at every width; the widest capture is where
    # cards sit side by side and cannot pass for page sections.
    for view in (v for v in layouts if v.width == widest):
        if any("type_role" not in run for run in view.runs):
            unjudged.append("text runs have no type role")
            continue
        found = []                                    # (label run, heading box, chip box, heading run)
        hero = next(((index, anchor) for index, anchor in heading_starts(view)
                     if (rect := view.rect(anchor)) and 0 <= rect["y"] < view.vp.get("height", 0)
                     and (view.runs[index].get("type_role") == "display"
                          or (view.sections or {}).get(view.section_of(anchor)) == "hero")), None)
        opened = set()
        for index, anchor in heading_starts(view):
            section = view.band_of(anchor)
            if section in opened:
                continue
            opened.add(section)
            prev = lead_in(view, index, anchor, view.band_of)
            if prev is None or prev.get("chars", 0) > LABEL_CHARS or prev["size_px"] >= view.runs[index]["size_px"]:
                continue
            if prev.get("type_role") in ("display", "heading", "nav", "ui", "code"):
                continue
            bounded = chip(view, prev, anchor)
            text = prev.get("text") or ""
            if kind == "badge" and bounded:
                found.append((prev, anchor, bounded, view.runs[index]))
            elif kind == "label" and not bounded and (
                    prev.get("type_role") == "label" or prev.get("transform") == "uppercase" or all_caps(text)
                    or (prev.get("letter_spacing_em") or 0) >= TRACKED_EM or INDEX_MARKER.fullmatch(text.strip())):
                found.append((prev, anchor, None, view.runs[index]))
        if kind == "label" and (det.get("params") or {}).get("singleton_hero") and hero:
            index, anchor = hero
            prev = lead_in(view, index, anchor, view.band_of)
            if (prev and prev.get("chars", 0) <= LABEL_CHARS
                    and prev["size_px"] < view.runs[index]["size_px"]
                    and prev.get("type_role") not in (*HEADINGS, "nav", "ui", "code")
                    and not chip(view, prev, anchor)):
                hits.add(("hero", anchor), view, Hit(
                    observed=f"singleton hero label {quote(prev.get('text'))} sits right above the first-view "
                             f"heading {quote(view.runs[index].get('text'))}; verify it adds category, scope, date, or state",
                    location=view.location(prev["box"]), refs=[prev["box"], anchor]))
        if repeats_max is None:
            for prev, anchor, bounded, heading in found:
                hits.add((kind, anchor), view, Hit(
                    observed=f"{kind} {quote(prev.get('text'))} sits right above the heading "
                             f"{quote(heading.get('text'))}",
                    location=view.location(bounded or prev["box"]), refs=[bounded or prev["box"], anchor]))
        elif len(found) > repeats_max:
            texts = ", ".join(quote(prev.get("text"), 24) for prev, *_ in found)
            hits.add((kind, tuple(anchor for _, anchor, *_ in found)), view, Hit(
                observed=f"{len(found)} sections open with a small {kind} before the heading, above "
                         f"{repeats_max:g}: {texts}",
                location=view.location(found[0][2] or found[0][0]["box"]),
                refs=[bounded or prev["box"] for prev, _, bounded, _ in found][:REF_LIMIT]))
    return finish(hits, unjudged)


def emphasis_runs(view: View, anchor: str) -> list[dict]:
    """The runs of one heading box, in document order."""
    return [r for r in view.runs if r.get("type_role") in HEADINGS and view.contains(anchor, r["box"])]


def heading_groups(view: View) -> list[list[dict]]:
    """The runs of each headline. A headline broken into lines may reach the extract as sibling heading boxes
    one under the other, with one size and one left edge; those boxes are one headline."""
    groups: list[dict] = []
    for _, anchor in heading_starts(view):
        runs = emphasis_runs(view, anchor)
        rect = view.rect(anchor)
        if not runs or rect is None:
            continue
        size = max(r.get("size_px", 0) for r in runs)
        last = groups[-1] if groups else None
        if (last and view.boxes[anchor].get("parent") == last["parent"] and abs(size - last["size"]) <= 0.1 * last["size"]
                and -2 <= rect["y"] - (last["rect"]["y"] + last["rect"]["h"]) <= 0.6 * last["size"]
                and abs(rect["x"] - last["rect"]["x"]) <= 16):
            last["runs"] += runs
            last["rect"] = rect
            continue
        groups.append({"runs": runs, "rect": rect, "size": size, "parent": view.boxes[anchor].get("parent")})
    return [g["runs"] for g in groups]


def set_apart(runs: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """The runs a headline sets in italic, or in another typeface than its first run, and how. Only runs
    in the script most of the headline is set in are compared: a second script falls to another typeface by itself."""
    def script(run: dict) -> str:
        return "cjk" if run.get("script") in ("hang", "kana", "hani") else run.get("script", "other")

    scripts: dict[str, int] = {}
    for run in runs:
        scripts[script(run)] = scripts.get(script(run), 0) + run.get("chars", 0)
    main_script = max(scripts, key=scripts.get)
    same = [r for r in runs if script(r) == main_script]
    main = (same[0].get("font") or {}).get("rendered", "")                 # the headline's own face is its first
    italic_main = all(r.get("style") in ("italic", "oblique") for r in same)       # a headline set wholly in italic
    apart, how = [], []
    for run in same:
        family = (run.get("font") or {}).get("rendered", "")
        marks = []
        if run.get("style") in ("italic", "oblique") and not italic_main:
            marks.append("italic")
        if family and family != main:
            marks.append(f"a second typeface ({family})")
        if marks:
            apart.append(run)
            how.extend(m for m in marks if m not in how)
    return same, apart, how


@detector("headline-emphasis", layers=("render",))
def headline_emphasis(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    share_max = (det.get("threshold") or {}).get("emphasis_share_max")
    size_min = (det.get("threshold") or {}).get("size_px_min")
    if share_max is None or size_min is None:
        return Result(skipped="the rule sets no threshold emphasis_share_max and size_px_min")
    hits = Hits()
    unjudged = []
    for view in layout_views(all_views):
        if any("type_role" not in run for run in view.runs):
            unjudged.append("text runs have no type role")
            continue
        for runs in heading_groups(view):
            same, apart, how = set_apart(runs)
            total = sum(r.get("chars", 0) for r in same)
            if len(same) < 2 or not apart or not total or max(r.get("size_px", 0) for r in runs) < size_min:
                continue
            if sum(r.get("chars", 0) for r in apart) > share_max * total:
                continue
            lead = " ".join(r.get("text", "") for r in same if r not in apart)
            tail = " ".join(r.get("text", "") for r in apart)
            hits.add((tuple(r["id"] for r in apart),), view, Hit(
                observed=f"heading {quote(lead)} sets {quote(tail)} apart in {' and '.join(how)}",
                location=view.location(apart[0]["box"]), refs=refs(apart)))
    return finish(hits, unjudged)


@detector("index-markers", layers=("render",))
def index_markers(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    check = (det.get("params") or {}).get("check", "non-sequential")
    if check != "non-sequential":
        return Result(skipped=f"unknown index-marker check {check!r}")
    hits = Hits()
    unjudged = []
    for view in layout_views(all_views):
        if view.sections is None:
            unjudged.append(f"the {view.width} px capture has no derived sections")
            continue
        if any("type_role" not in run for run in view.runs):
            unjudged.append("text runs have no type role")
            continue
        markers = []                                  # (number, section, box, text)
        for index, anchor in heading_starts(view):
            heading = view.runs[index]
            prev = lead_in(view, index, anchor, view.section_of)
            text = (prev or {}).get("text", "").strip()
            if prev and prev.get("chars", 99) <= MARKER_CHARS and (match := INDEX_MARKER.fullmatch(text)):
                markers.append((int(match.group(1)), view.section_of(anchor), prev["box"], text))
            elif match := INDEX_PREFIX.match(heading.get("text") or ""):
                number = match.group(1) or match.group(2)
                markers.append((int(number), view.section_of(anchor), anchor, (heading.get("text") or "")[:12]))
        if len(markers) < 2:
            continue
        numbers = [m[0] for m in markers]
        sections = list(dict.fromkeys(m[1] for m in markers))
        listed = ", ".join(quote(m[3], 12) for m in markers)
        out_of_order = numbers != list(range(numbers[0], numbers[0] + len(numbers)))
        if out_of_order:
            observed = f"index markers {listed} do not count up one by one in content order"
        elif len(sections) > 1:
            kinds = ", ".join((view.sections or {}).get(s, "unsectioned") if s else "unsectioned" for s in sections)
            observed = f"index markers {listed} number {len(sections)} separate sections ({kinds})"
        else:
            continue
        hits.add(tuple((m[0], m[2]) for m in markers), view, Hit(
            observed=observed, location=view.location(markers[0][2]), refs=[m[2] for m in markers][:REF_LIMIT]))
    return finish(hits, unjudged)


# ---------------------------------------------------------------- font feature regions (font_regions.py)

@detector("rendered-family-region", layers=("render",))
def rendered_family_region(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    regions, problem = region_list(ctx, det)
    if problem:
        return Result(skipped=problem)
    if ctx.lazuli is None:
        return Result(skipped="no lazuli database given, so rendered families have no measured features")
    params = det.get("params") or {}
    roles = set(params["roles"]) if params.get("roles") else None
    roles_except = set(params.get("roles_except") or ())
    include_italic = bool(params.get("include_italic"))
    hits = Hits()
    defined = definitions()
    generic = system_fonts.generic_families()
    unjudged = [f"feature region {name!r} has no measured definition" for name, _ in regions if name not in defined]
    for view in layout_views(all_views):
        groups: dict[tuple, list[dict]] = {}
        for run in view.runs:
            role = run.get("type_role")
            if (roles is not None and role not in roles) or role in roles_except:
                continue
            italic = run.get("style", "normal") != "normal"
            family = (run.get("font") or {}).get("rendered", "")
            if (italic and not include_italic) or not family or family.casefold() in generic:
                continue
            groups.setdefault((family, italic, run.get("weight")), []).append(run)
        for (family, italic, weight), runs in groups.items():
            measured, reason = faces(ctx, family)
            if not measured:
                unjudged.append(reason)
                continue
            face = pick(measured, weight, italic)
            scripts = {r.get("script") for r in runs}
            for name, scope in regions:
                if name not in defined or (scope is not None and not scope & scripts):
                    continue
                verdict = judge_face(face, name)
                if verdict is None:
                    unjudged.append(f"'{family}' lacks measurements the region {name!r} needs")
                elif verdict:
                    used = [r for r in runs if scope is None or r.get("script") in scope]
                    used_roles = ", ".join(sorted({r.get("type_role") or "untyped" for r in used}))
                    hits.add((family_norm(family), name), view, Hit(
                        observed=f"'{family}' ({used_roles}; {count(used)}) measures in the feature region "
                                 f"{name}: {describe(face.features)}",
                        location=view.location(used[0]["box"]), refs=refs(used)))
    return finish(hits, unjudged)


# ---------------------------------------------------------------- contrast

def is_large(run: dict) -> bool:
    size, weight = run.get("size_px", 0), run.get("weight", 400)
    return size >= LARGE_PX or (size >= LARGE_BOLD_PX and weight >= BOLD)


def gray_on_color(color: list[float], backdrop: dict | list[float], text_c: float, field_c: float) -> bool:
    ground = backdrop.get("oklch") if isinstance(backdrop, dict) else backdrop
    if isinstance(backdrop, dict) and backdrop.get("kind") == "image":
        return False
    return (color[1] <= text_c and GRAY_L[0] < color[0] < GRAY_L[1] and ground is not None
            and ground[1] >= field_c)


@detector("contrast-wcag", layers=("render",))
def contrast_wcag(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    params, threshold = det.get("params") or {}, det.get("threshold") or {}
    pair = params.get("pair")
    if pair not in (None, "neutral-text-on-chromatic-field"):
        return Result(skipped=f"unknown contrast pair {pair!r}")
    normal_min, large_min = threshold.get("normal_min"), threshold.get("large_min")
    if pair is None and normal_min is None and large_min is None:
        return Result(skipped="the rule sets no contrast bound")
    text_c, field_c = params.get("neutral_text_c", 0.03), params.get("chromatic_background_c", 0.08)
    states = list(params.get("states") or ["rest"])
    skip_disabled = "disabled-excluded" in states
    states = [s for s in states if s != "disabled-excluded"]
    themes = set(params.get("themes") or ())
    hits = Hits()
    unmeasured: set[str] = set()
    for view in layout_views(all_views):
        if themes and view.vp.get("theme", "light") not in themes:
            continue
        for run in view.runs:
            if run.get("fill") == "transparent" and not run.get("color"):
                continue
            chain = (run["box"], *view.chain(run["box"]))
            a11y = [(view.boxes.get(b) or {}).get("a11y") or {} for b in chain]
            if a11y[0].get("hidden") or (skip_disabled and any(a.get("disabled") for a in a11y)):
                continue
            for state in states:
                if state == "rest":
                    color, backdrop = run.get("color"), run.get("backdrop")
                    if not color or not backdrop:
                        unmeasured.add(run["box"])
                        continue
                    ground, surface = backdrop.get("worst") or backdrop["oklch"], backdrop
                else:
                    recorded = (run.get("states") or {}).get(state)
                    if not recorded:
                        continue
                    color = recorded["color"]
                    ground = recorded.get("backdrop") or (run.get("backdrop") or {}).get("oklch")
                    surface = ground
                    if ground is None:
                        unmeasured.add(run["box"])
                        continue
                if pair and not gray_on_color(color, surface, text_c, field_c):
                    continue
                large = is_large(run)
                edge = large_min if large else normal_min
                ratio = contrast(color, ground)
                if edge is not None and ratio >= edge:
                    continue
                if edge is None and pair is None:
                    continue
                where = "" if state == "rest" else f" on {state}"
                size = "large" if large else "normal"
                if pair:
                    field_color = surface.get("oklch") if isinstance(surface, dict) else surface
                    observed = (f"gray text {quote(run.get('text'))} (chroma {color[1]:.3f}) sits on a chromatic "
                                f"surface (chroma {field_color[1]:.3f}){where}, contrast {ratio:.2f}:1")
                else:
                    observed = (f"{size} text {quote(run.get('text'))} has contrast {ratio:.2f}:1{where} on its "
                                f"weakest backdrop, below {edge:g}:1")
                hits.add((run["box"], run.get("text"), state, view.vp.get("theme")), view, Hit(
                    observed=observed, location=view.location(run["box"]), refs=[run["box"]]))
    return finish(hits, [f"{len(unmeasured)} text boxes have no measured backdrop" if unmeasured else ""])


# ---------------------------------------------------------------- targets, overflow, occlusion

def is_target(box: dict, roles: set[str]) -> bool:
    rect = box["rect"]
    if box.get("role") not in roles or rect["w"] <= 1 or rect["h"] <= 1:
        return False
    a11y = box.get("a11y")
    if a11y is None:
        return True
    if a11y.get("hidden") or a11y.get("disabled"):
        return False
    if "focusable" in a11y or "pointer_handler" in a11y:
        return bool(a11y.get("focusable") or a11y.get("pointer_handler"))
    return True


def box_name(view: View, box_id: str) -> str:
    box = view.boxes.get(box_id) or {}
    name = (box.get("a11y") or {}).get("name") or " ".join(
        r.get("text", "") for r in view.runs_by_box.get(box_id, []))
    if not name.strip():
        name = (box.get("icon") or {}).get("action") or ""
    return name.strip()


def rect_distance(x: float, y: float, rect: dict) -> float:
    dx = max(rect["x"] - x, 0.0, x - rect["x"] - rect["w"])
    dy = max(rect["y"] - y, 0.0, y - rect["y"] - rect["h"])
    return math.hypot(dx, dy)


def center(rect: dict) -> tuple[float, float]:
    return rect["x"] + rect["w"] / 2, rect["y"] + rect["h"] / 2


def inline_link(view: View, box: dict) -> bool:
    """A link inside running text: its parent box holds text of its own around it."""
    if box.get("role") != "link" or not box.get("parent"):
        return False
    return any(r.get("type_role") not in ("nav", "ui") for r in view.runs_by_box.get(box["parent"], []))


def native_unstyled(box: dict) -> bool:
    style = box.get("style") or {}
    return box.get("role") == "input" and not (style.get("background") or style.get("border_px")
                                                or style.get("shadow") or style.get("radius_px"))


@detector("target-size", layers=("render",))
def target_size(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    size = (det.get("threshold") or {}).get("size_min")
    if size is None:
        return Result(skipped="the rule sets no size_min")
    roles = set((det.get("params") or {}).get("roles") or CONTROLS)
    radius = size / 2
    hits = Hits()
    for view in layout_views(all_views):
        targets = [b for b in view.boxes.values() if is_target(b, roles)]
        small = {b["id"] for b in targets if b["rect"]["w"] < size or b["rect"]["h"] < size}
        for box in targets:
            if box["id"] not in small or inline_link(view, box) or native_unstyled(box):
                continue
            cx, cy = center(box["rect"])
            touching = [other for other in targets if other["id"] != box["id"]
                        and not view.related(other["id"], box["id"])
                        and (rect_distance(cx, cy, other["rect"]) < radius
                             or (other["id"] in small and math.dist((cx, cy), center(other["rect"])) < size))]
            if not touching:
                continue
            name = box_name(view, box["id"])
            twin = name and any(other["id"] not in small and box_name(view, other["id"]).casefold() == name.casefold()
                                for other in targets)
            neighbours = ", ".join(quote(box_name(view, o["id"]) or o.get("role"), 20) for o in touching[:3])
            observed = (f"{box.get('role')} {quote(name or box.get('role'), 24)} is {box['rect']['w']:.0f} x "
                        f"{box['rect']['h']:.0f} px and its {size:g} px circle touches {neighbours}")
            if twin:
                observed += "; a full-size control with the same name exists, so this may be an equivalent"
            hits.add((box["id"], round(box["rect"]["w"]), round(box["rect"]["h"])), view, Hit(
                observed=observed, location=view.location(box["id"]),
                evidence="not-verified" if twin else "measurement",
                refs=[box["id"], *(o["id"] for o in touching)][:REF_LIMIT]))
    return finish(hits)


OVERFLOW_CHECKS = ("page-horizontal-scroll", "clipped-text", "overlapping-controls", "dynamic-viewport-clip")


def horizontal_scroll(view: View, hits: Hits, unjudged: list[str]) -> None:
    scroll = view.vp.get("scroll_width")
    if scroll is None:
        unjudged.append(f"the {view.width} px capture has no scroll width")
        return
    limit = view.width + 0.5
    if scroll <= limit:
        return

    def right(box_id: str | None) -> float:
        rect = view.rect(box_id) if box_id else None
        return rect["x"] + rect["w"] if rect else 0.0

    # the outermost boxes that reach past the viewport: their parent still fits
    wide = [b["id"] for b in view.boxes.values() if right(b["id"]) > limit and right(b.get("parent")) <= limit]
    hits.add(("page-horizontal-scroll", view.width), view, Hit(
        observed=f"the page scrolls sideways: the document is {scroll:g} px wide in a {view.width} px viewport",
        location=view.location(wide[0] if wide else None), refs=wide[:REF_LIMIT]))


def clipped_text(view: View, hits: Hits, unjudged: list[str]) -> None:
    if not any("clipped" in b for b in view.boxes.values()):
        unjudged.append(f"the {view.width} px capture does not record clipping")
        return
    for box in view.boxes.values():
        if box.get("clipped") != "overflow":
            continue
        outer = edges(box["rect"])
        cut = [r for r in view.runs if r["box"] == box["id"] or (
            view.contains(box["id"], r["box"]) and (rect := view.rect(r["box"]))
            and (inner := edges(rect)) and intersection(inner, outer)
            and not (inner[0] >= outer[0] and inner[1] >= outer[1] and inner[2] <= outer[2] and inner[3] <= outer[3]))]
        if cut:
            hits.add(("clipped-text", box["id"]), view, Hit(
                observed=f"text {quote(cut[0].get('text'))} is cut off by a box that hides its overflow "
                         f"({box.get('role')}, {box['rect']['w']:.0f} x {box['rect']['h']:.0f} px)",
                location=view.location(box["id"]), refs=[box["id"], *refs(cut)][:REF_LIMIT]))


def overlapping_controls(view: View, hits: Hits) -> None:
    page = view.vp.get("scroll_width") or view.width
    controls = [b for b in view.boxes.values() if b.get("role") in CONTROLS and b["rect"]["w"] > 1
                and b["rect"]["h"] > 1 and not (b.get("a11y") or {}).get("hidden")
                and b["rect"]["x"] < page and b["rect"]["x"] + b["rect"]["w"] > 0]
    for i, a in enumerate(controls):
        for b in controls[i + 1:]:
            overlap = intersection(edges(a["rect"]), edges(b["rect"]))
            if not overlap or view.related(a["id"], b["id"]) or overlap[2] - overlap[0] <= 1 or overlap[3] - overlap[1] <= 1:
                continue
            hits.add(("overlapping-controls", *sorted((a["id"], b["id"]))), view, Hit(
                observed=f"{a.get('role')} {quote(box_name(view, a['id']) or a.get('role'), 20)} overlaps "
                         f"{b.get('role')} {quote(box_name(view, b['id']) or b.get('role'), 20)} by "
                         f"{overlap[2] - overlap[0]:.0f} x {overlap[3] - overlap[1]:.0f} px",
                location=view.location(a["id"]), refs=[a["id"], b["id"]]))


def dynamic_viewport_clip(view: View, hits: Hits, unjudged: list[str]) -> None:
    visible = view.vp.get("height")
    if not visible:
        unjudged.append(f"the {view.width} px browser-UI capture has no viewport height")
        return
    layout_h = visible + CHROME_PX
    for shell in view.boxes.values():
        rect = shell["rect"]
        if rect["y"] > 1 or abs(rect["h"] - layout_h) > 1:
            continue
        hidden = [b for b in view.boxes.values() if b.get("role") in CONTROLS and view.contains(shell["id"], b["id"])
                  and b["id"] != shell["id"] and b["rect"]["y"] + b["rect"]["h"] > visible
                  and b["rect"]["y"] < layout_h]
        if hidden:
            names = ", ".join(quote(box_name(view, b["id"]) or b.get("role"), 20) for b in hidden[:4])
            hits.add(("dynamic-viewport-clip", shell["id"]), view, Hit(
                observed=f"a full-height box ({shell.get('role')}, {rect['h']:.0f} px, the layout viewport) puts "
                         f"{len(hidden)} controls below the {visible:g} px left visible by browser UI: {names}",
                location=view.location(shell["id"]), refs=[shell["id"], *(b["id"] for b in hidden)][:REF_LIMIT]))


@detector("overflow-check", layers=("render",))
def overflow_check(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    params = det.get("params") or {}
    checks = list(params.get("checks") or OVERFLOW_CHECKS[:3])
    widths = set(params.get("viewports") or ())
    unjudged = [f"unknown overflow check {c!r}" for c in checks if c not in OVERFLOW_CHECKS]
    in_width = [v for v in all_views if not widths or v.width in widths]
    layouts = [v for v in in_width if not v.vp.get("browser_chrome")]
    chrome = [v for v in in_width if v.vp.get("browser_chrome")]
    wanted = ", ".join(str(w) for w in sorted(widths)) or "any"
    hits = Hits()
    if any(c in checks for c in OVERFLOW_CHECKS[:3]) and not layouts:
        unjudged.append(f"the render extract has no capture at {wanted} px")
    for view in layouts:
        if "page-horizontal-scroll" in checks:
            horizontal_scroll(view, hits, unjudged)
        if "clipped-text" in checks:
            clipped_text(view, hits, unjudged)
        if "overlapping-controls" in checks:
            overlapping_controls(view, hits)
    if "dynamic-viewport-clip" in checks:
        if not chrome:
            unjudged.append(f"the render extract has no browser-UI capture at {wanted} px")
        for view in chrome:
            dynamic_viewport_clip(view, hits, unjudged)
    return finish(hits, unjudged)


def opaque(box: dict) -> bool:
    style = box.get("style") or {}
    background = style.get("background")
    if background and (len(background) < 4 or background[3] >= OPAQUE_ALPHA):
        return True
    if any(g.get("target") == "background" and max((s["oklch"][3] if len(s["oklch"]) > 3 else 1.0)
                                                    for s in g["stops"]) >= OPAQUE_ALPHA
           for g in style.get("gradients") or ()):
        return True
    media = box.get("media")
    return box.get("role") == "media" and media is not None and media.get("loaded", False)


@detector("text-occlusion", layers=("render",))
def text_occlusion(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    all_views, missing = views(ctx, rule)
    if missing:
        return Result(skipped=missing)
    hits = Hits()
    unjudged = []
    for view in layout_views(all_views):
        if not any("paint_order" in b for b in view.boxes.values()):
            unjudged.append(f"the {view.width} px capture has no paint order")
            continue
        dialogs = [b for b, box in view.boxes.items() if box.get("role") == "dialog"]
        layers = [b for b in view.boxes.values() if "paint_order" in b and opaque(b)
                  and not any(view.contains(d, b["id"]) for d in dialogs)]
        for box_id in dict.fromkeys(r["box"] for r in view.runs):
            text_box = view.boxes.get(box_id)
            if text_box is None or "paint_order" not in text_box:
                unjudged.append("some text boxes have no paint order")
                continue
            area = edges(text_box["rect"])
            covering = [(part, layer_box) for layer_box in layers
                        if layer_box["paint_order"] > text_box["paint_order"]
                        and not view.related(layer_box["id"], box_id)
                        and (part := intersection(area, edges(layer_box["rect"])))]
            if not covering:
                continue
            share = union_area([part for part, _ in covering]) / (text_box["rect"]["w"] * text_box["rect"]["h"])
            if share < OCCLUDED_SHARE:
                continue
            top = max(covering, key=lambda item: (item[0][2] - item[0][0]) * (item[0][3] - item[0][1]))[1]
            hits.add((box_id, tuple(sorted(b["id"] for _, b in covering))), view, Hit(
                observed=f"text {quote(view.runs_by_box[box_id][0].get('text'))} is {share:.0%} covered by "
                         f"{len(covering)} opaque layer{'s' if len(covering) > 1 else ''} painted above it "
                         f"(largest layer: {top.get('role')})",
                location=view.location(box_id), refs=[box_id, *(b["id"] for _, b in covering)][:REF_LIMIT]))
    return finish(hits, unjudged)
