"""Layout detectors: section structure, spacing, symmetry, cards and grids, decorative DOM, contract
diffs, motion, the accessibility tree, and layout shift.

Render detectors read the render extract (render/extract.schema.yaml, meanings in render/DERIVED.md).
Each viewport width is read once, from its canonical capture: the light theme with full motion and
no emulated browser UI, falling back to the first capture of that width. An observation that repeats
across widths becomes one hit naming the widths. Behavior detectors read the behavior session
(behavior/session.schema.yaml, behavior/DERIVED.md); the engine adds coverage findings for probes
that ran partly or not at all, so a probe with no entries here only means nothing was observed.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Callable, Iterable

from lapis_design import system_fonts
from lapis_design.lint.types import Context, Hit, Result, detector
from lapis_design.render.color import delta_e_ok

# Visible heights per width when a capture omits `height` (render/DERIVED.md, Capture).
_HEIGHTS = {320: 568, 390: 844, 768: 1024, 1440: 900}
_CONTENT = frozenset({"heading", "text", "media", "button", "link", "input", "icon"})
_CONTROLS = frozenset({"button", "link", "input"})
_HEADING_RUNS = frozenset({"heading", "display"})
_ICON_MEDIA_PX = 64          # a media box this small may stand in for an icon tile
_FULL_SPAN = 0.9             # boxes this wide relative to their section say nothing about alignment
_CENTERED = 0.9              # hero shape "centered" when content symmetry exceeds this (no threshold)
_SCALED_TOLERANCE = 0.05     # responsive-structure: normalized x and width kept within this
_SCALED_SHARE = 0.8          # responsive-structure: share of side-by-side boxes that must keep columns
_TRANSFORMS = frozenset({"transform", "translate", "scale", "rotate"})
_PULSE = frozenset({"opacity", "transform", "scale", "box-shadow", "filter"})
_METRIC = re.compile(
    r"[~≈<>+±]?\s*[$€£¥₩]?\s*\d[\d.,]*\s*(?:[kmb]|만|천|억|명|개|배)?\s*(?:[+%×x★]|/\s*\d+(?:\.\d+)?)?\s*\+?",
    re.I)
_BEZIER = re.compile(r"cubic-bezier\(\s*([-\d.e]+)\s*,\s*([-\d.e]+)\s*,\s*([-\d.e]+)\s*,\s*([-\d.e]+)\s*\)")
_LINEAR = re.compile(r"linear\(([^)]*)\)")
_BLINK_NAME = re.compile(r"blink|caret|cursor", re.I)


# ---------------------------------------------------------------- shared helpers

def _dig(doc: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(doc, dict):
            return None
        doc = doc.get(key)
    return doc


def _bound(det: dict, key: str) -> float | None:
    value = (det.get("threshold") or {}).get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _no_bound(key: str) -> Result:
    return Result(skipped=f"the rule sets no threshold {key}")


def _params(det: dict) -> dict:
    return det.get("params") or {}


def _names(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]


def _edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def _area(rect: dict) -> float:
    return rect["w"] * rect["h"]


def _h_overlap(a: dict, b: dict) -> float:
    return max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))


def _v_overlap(a: dict, b: dict) -> float:
    return max(0.0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))


def _side_by_side(a: dict, b: dict) -> bool:
    """Same row: vertical overlap of at least half the shorter box, no horizontal overlap."""
    shorter = min(a["h"], b["h"])
    return shorter > 0 and _v_overlap(a, b) >= shorter / 2 and _h_overlap(a, b) <= 1


def _stacked(a: dict, b: dict) -> bool:
    """One above the other: horizontal overlap of at least half the narrower box."""
    narrower = min(a["w"], b["w"])
    return narrower > 0 and _h_overlap(a, b) >= narrower / 2


def _union_area(rects: Iterable[dict]) -> float:
    """Area of the union of rectangles (sweep over x with merged y intervals)."""
    spans = [(r["x"], r["x"] + r["w"], r["y"], r["y"] + r["h"]) for r in rects if r["w"] > 0 and r["h"] > 0]
    xs = sorted({x for s in spans for x in s[:2]})
    total = 0.0
    for left, right in zip(xs, xs[1:]):
        intervals = sorted((y1, y2) for x1, x2, y1, y2 in spans if x1 <= left and x2 >= right)
        covered, low, high = 0.0, None, None
        for y1, y2 in intervals:
            if high is None or y1 > high:
                if high is not None:
                    covered += high - low
                low, high = y1, y2
            else:
                high = max(high, y2)
        if high is not None:
            covered += high - low
        total += (right - left) * covered
    return total


def _count(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else plural or singular + 's'}"


def _fmt(value: float) -> str:
    return f"{value:g}" if float(value).is_integer() else f"{value:.2f}"


# ---------------------------------------------------------------- render pages

class _Page:
    """One canonical capture with the indexes the render detectors share."""

    def __init__(self, vp: dict):
        self.vp = vp
        self.width: int = vp["width"]
        self.height: float = vp.get("height") or _HEIGHTS.get(self.width, 0)
        self.boxes: list[dict] = vp.get("boxes") or []
        self.runs: list[dict] = vp.get("text") or []
        self.derived: dict = vp.get("derived") or {}
        self.by_id = {b["id"]: b for b in self.boxes}
        self.children: dict[str, list[str]] = defaultdict(list)
        for b in self.boxes:
            if b.get("parent") in self.by_id:
                self.children[b["parent"]].append(b["id"])
        self.runs_by_box: dict[str, list[dict]] = defaultdict(list)
        for r in self.runs:
            self.runs_by_box[r["box"]].append(r)
        self._subtree_runs: dict[str, list[dict]] | None = None
        self._card: dict[str, bool] = {}
        self.roots = [b["id"] for b in self.boxes if b.get("parent") not in self.by_id]
        self.memo: dict[str, Any] = {}

    def rect(self, ident: str) -> dict:
        return self.by_id[ident]["rect"]

    def ancestors(self, ident: str) -> Iterable[str]:
        seen = {ident}
        parent = self.by_id.get(ident, {}).get("parent")
        while parent in self.by_id and parent not in seen:
            seen.add(parent)
            yield parent
            parent = self.by_id[parent].get("parent")

    def descendants(self, ident: str) -> list[str]:
        """Descendants in document order, excluding `ident`."""
        out: list[str] = []
        stack = list(reversed(self.children.get(ident, ())))
        while stack:
            current = stack.pop()
            out.append(current)
            stack.extend(reversed(self.children.get(current, ())))
        return out

    def pre_order(self) -> list[str]:
        """Every box in document order, parents before children."""
        if "pre_order" not in self.memo:
            self.memo["pre_order"] = [i for root in self.roots for i in (root, *self.descendants(root))]
        return self.memo["pre_order"]

    def post_order(self) -> list[str]:
        """Every box, children before parents."""
        out: list[str] = []
        stack = [(root, False) for root in reversed(self.roots)]
        while stack:
            ident, done = stack.pop()
            if done:
                out.append(ident)
                continue
            stack.append((ident, True))
            stack.extend((child, False) for child in reversed(self.children.get(ident, ())))
        return out

    def subtree_runs(self, ident: str) -> list[dict]:
        if self._subtree_runs is None:
            index: dict[str, list[dict]] = defaultdict(list)
            for r in self.runs:
                if r["box"] in self.by_id:
                    index[r["box"]].append(r)
                    for ancestor in self.ancestors(r["box"]):
                        index[ancestor].append(r)
            self._subtree_runs = index
        return self._subtree_runs.get(ident, [])

    def content_boxes(self, root: str | None = None) -> list[str]:
        """Outermost boxes with a content role under `root` (the whole page when None)."""
        roots = self.children.get(root, ()) if root else self.roots
        out: list[str] = []
        stack = list(reversed(roots))
        while stack:
            current = stack.pop()
            if self.by_id[current]["role"] in _CONTENT:
                out.append(current)
                continue
            stack.extend(reversed(self.children.get(current, ())))
        return out

    def sections(self) -> list[dict] | None:
        sections = self.derived.get("sections")
        if sections is None:
            return None
        return [s for s in sections if s["box"] in self.by_id]

    def section_of(self, ident: str, section_ids: set[str]) -> str | None:
        if ident in section_ids:
            return ident
        return next((a for a in self.ancestors(ident) if a in section_ids), None)

    def has_style(self) -> bool:
        return any("style" in b for b in self.boxes)

    def card_like(self, ident: str) -> bool:
        """render/DERIVED.md, card_nesting_max: not a control, at least 2% of the first viewport,
        and a visible boundary (a background unlike the nearest ancestor background, a border, or
        a shadow)."""
        if ident in self._card:
            return self._card[ident]
        box = self.by_id[ident]
        style = box.get("style") or {}
        result = False
        if box["role"] not in _CONTROLS and _area(box["rect"]) >= 0.02 * self.width * self.height:
            result = bool(style.get("border_px", 0) > 0
                          or any(side.get("px", 0) > 0 for side in (style.get("border_sides") or {}).values())
                          or style.get("shadow") or style.get("shadows"))
            background = style.get("background")
            if not result and background is not None:
                ancestor = next((self.by_id[a]["style"]["background"] for a in self.ancestors(ident)
                                 if (self.by_id[a].get("style") or {}).get("background") is not None), None)
                result = ancestor is not None and delta_e_ok(background, ancestor) > 0.02
        self._card[ident] = result
        return result

    def heading_boxes(self) -> list[str]:
        """Content boxes that are headings by role or by the type role of their runs."""
        return [b for b in self.content_boxes()
                if self.by_id[b]["role"] == "heading"
                or any(r.get("type_role") in _HEADING_RUNS for r in self.runs_by_box.get(b, ()))]


def _pages(ctx: Context) -> list[_Page] | str:
    extract = ctx.extract
    if not extract:
        return "no render extract was given"
    key = ("render_layout.pages", id(extract))
    pages = ctx.cache.get(key)
    if pages is None:
        chosen: dict[int, tuple[tuple[bool, bool, bool], dict]] = {}
        for vp in extract.get("viewports") or ():
            score = (vp.get("theme") == "light", not vp.get("reduced_motion"), not vp.get("browser_chrome"))
            width = vp.get("width")
            if width not in chosen or score > chosen[width][0]:
                chosen[width] = (score, vp)
        pages = [_Page(vp) for _, (_, vp) in sorted(chosen.items())]
        ctx.cache[key] = pages
    return pages or "the render extract has no viewports"


@dataclass
class _Obs:
    key: Any
    observed: str
    box: str | None = None
    detail: str | None = None
    refs: tuple[str, ...] = ()


def _merge(pages: list[_Page], observe: Callable[[_Page], Iterable[_Obs]],
           evidence: str = "measurement") -> list[Hit]:
    """One hit per observation key; widths (and per-width details) are appended to `observed`."""
    merged: dict[Any, tuple[_Obs, list[int], list[str | None], list[str]]] = {}
    for page in pages:
        for obs in observe(page):
            entry = merged.get(obs.key)
            if entry is None:
                entry = merged[obs.key] = (obs, [], [], [])
            entry[1].append(page.width)
            entry[2].append(obs.detail)
            entry[3].extend(ref for ref in obs.refs if ref not in entry[3])
    hits = []
    for obs, widths, details, refs in merged.values():
        if any(detail is not None for detail in details):
            where = "; ".join(f"{d} at {w} px" if d is not None else f"at {w} px"
                              for w, d in zip(widths, details))
        else:
            where = "at " + ", ".join(str(w) for w in widths) + " px"
        location: dict[str, Any] = {"viewport": widths[0]}
        if obs.box:
            location["box"] = obs.box
        hits.append(Hit(observed=f"{obs.observed} ({where})", location=location, evidence=evidence,
                        refs=list(refs)))
    return hits


# ---------------------------------------------------------------- behavior session

def _session_items(ctx: Context, probe: str) -> list[dict] | str:
    session = ctx.session
    if not session:
        return "no behavior session was given"
    items = (session.get("probes") or {}).get(probe) or []
    if items:
        return items
    if any(entry.get("probe") == probe for entry in session.get("coverage") or ()):
        return []        # ran and found nothing, or the engine reports the partial/skipped coverage
    return f"the session has no {probe} probe results and no coverage entry for it"


def _merge_contexts(observations: Iterable[tuple[Any, str, str, str | None, list[str]]]) -> list[Hit]:
    """(key, observed, context, box, refs) -> one runtime hit per key naming its contexts."""
    merged: dict[Any, tuple[str, list[str], str | None, list[str]]] = {}
    for key, observed, context, box, refs in observations:
        entry = merged.get(key)
        if entry is None:
            entry = merged[key] = (observed, [], box, [])
        if context not in entry[1]:
            entry[1].append(context)
        entry[3].extend(ref for ref in refs if ref not in entry[3])
    hits = []
    for observed, contexts, box, refs in merged.values():
        location: dict[str, Any] = {"context": contexts[0]}
        if box:
            location["box"] = box
        label = "context" if len(contexts) == 1 else "contexts"
        hits.append(Hit(observed=f"{observed} (in {label} {', '.join(contexts)})", location=location,
                        evidence="runtime", refs=refs))
    return hits


# ---------------------------------------------------------------- template-repetition

def _role_matches(box: dict, role: str) -> bool:
    if box["role"] == role:
        return True
    rect = box["rect"]
    return (role == "icon" and box["role"] == "media"
            and rect["w"] <= _ICON_MEDIA_PX and rect["h"] <= _ICON_MEDIA_PX)


def _opens_with(page: _Page, section: str, pattern: list[str]) -> bool:
    head = page.content_boxes(section)[:len(pattern)]
    if len(head) < len(pattern):
        return False
    if not all(_role_matches(page.by_id[b], role) for b, role in zip(head, pattern)):
        return False
    rects = [page.rect(b) for b in head]
    return all(nxt["y"] >= prev["y"] + prev["h"] / 2 for prev, nxt in zip(rects, rects[1:]))


def _media_text_rows(page: _Page) -> list[tuple[float, float, str, str]]:
    """(top, bottom, media side, media box) for large media with text beside it on one side."""
    media = [b for b in page.boxes if b["role"] == "media" and b["rect"]["w"] >= 0.25 * page.width
             and b["rect"]["h"] >= 80
             and not any(page.by_id[a]["role"] == "media" for a in page.ancestors(b["id"]))]
    text_boxes = [page.by_id[i] for i in page.runs_by_box if i in page.by_id]
    rows = []
    for m in media:
        r = m["rect"]
        top, bottom = r["y"], r["y"] + r["h"]
        sides = set()
        for t in text_boxes:
            if t["id"] == m["id"] or m["id"] in page.ancestors(t["id"]):
                continue
            tr = t["rect"]
            if not top <= tr["y"] + tr["h"] / 2 <= bottom:
                continue
            if tr["x"] >= r["x"] + r["w"] - 1:
                sides.add("left")
            elif tr["x"] + tr["w"] <= r["x"] + 1:
                sides.add("right")
        if len(sides) == 1:
            rows.append((top, bottom, sides.pop(), m["id"]))
    rows.sort()
    return [row for row in rows
            if not any(other is not row and other[0] < row[1] and row[0] < other[1] for other in rows)]


@detector("template-repetition", layers=("render",))
def template_repetition(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    bound = _bound(det, "repeats_max")
    if bound is None:
        return _no_bound("repeats_max")
    pattern = _params(det).get("pattern")
    if pattern == "alternating-media-text":
        def observe(page: _Page) -> Iterable[_Obs]:
            rows = _media_text_rows(page)
            runs: list[list[tuple[float, float, str, str]]] = []
            for row in rows:
                if runs and runs[-1][-1][2] != row[2]:
                    runs[-1].append(row)
                else:
                    runs.append([row])
            for run in runs:
                if len(run) > bound:
                    yield _Obs(("zigzag", run[0][3]),
                               f"media and text alternate sides in {len(run)} consecutive rows "
                               f"(media {', '.join(row[2] for row in run)})",
                               box=run[0][3], refs=tuple(row[3] for row in run))
        return Result(hits=_merge(pages, observe))
    roles = _names(pattern) if isinstance(pattern, list) else re.split(r"[\s,>]+", str(pattern or "").strip())
    roles = [r for r in roles if r]
    if not roles:
        return Result(skipped="the rule names no pattern")
    measured = [p for p in pages if p.sections() is not None]
    if not measured:
        return Result(skipped="the extract has no derived.sections")

    def observe(page: _Page) -> Iterable[_Obs]:
        run: list[str] = []
        for section in [s["box"] for s in page.sections()] + [None]:
            if section is not None and _opens_with(page, section, roles):
                run.append(section)
                continue
            if len(run) > bound:
                yield _Obs(("sections", run[0]),
                           f"{len(run)} consecutive sections open with stacked {' > '.join(roles)}",
                           box=run[0], refs=tuple(run))
            run = []
    return Result(hits=_merge(measured, observe))


# ---------------------------------------------------------------- section-sequence

@detector("section-sequence", layers=("render",))
def section_sequence(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    params = _params(det)
    templates = [_names(t) for t in params.get("templates") or () if t]
    if not templates:
        return Result(skipped="the rule lists no templates")
    max_distance = float(params.get("max_distance", 0.34))
    min_sections = int(params.get("min_sections", 0))
    measured = [p for p in pages if p.derived.get("section_sequence") is not None]
    if not measured:
        return Result(skipped="the extract has no derived.section_sequence")

    def observe(page: _Page) -> Iterable[_Obs]:
        # No template names a footer and every page ends with one, so it is not compared. The sections
        # before the first hero are the site header, and an archetype repeated in a row is one section
        # split in two, so a template is compared with the page from its hero, each archetype once.
        sequence = [a for a in page.derived["section_sequence"] if a != "footer"]
        if "hero" in sequence:
            sequence = sequence[sequence.index("hero"):]
        sequence = [a for i, a in enumerate(sequence) if i == 0 or a != sequence[i - 1]]
        if not sequence or len(sequence) < min_sections:
            return
        def distance(template: list[str]) -> float:
            return _edit_distance(sequence, template) / max(len(sequence), len(template))
        best = min(templates, key=distance)
        d = distance(best)
        if d <= max_distance:
            yield _Obs(("template", tuple(best)),
                       f"section order follows the template {' > '.join(best)}",
                       detail=f"{' > '.join(sequence)} at distance {d:.2f}")
    return Result(hits=_merge(measured, observe))


# ---------------------------------------------------------------- section-inventory

def _logo_row(page: _Page, ids: list[str]) -> int:
    """Largest count of small media or image icons of similar height sharing one row."""
    limit = min(120.0, 0.15 * page.height)
    items = [page.by_id[i] for i in ids
             if (page.by_id[i]["role"] == "media"
                 or (page.by_id[i]["role"] == "icon"
                     and (page.by_id[i].get("icon") or {}).get("kind") in ("image", "svg")))
             and 0 < page.rect(i)["h"] <= limit and page.rect(i)["w"] <= 0.3 * page.width]
    best = 0
    for anchor in items:
        ar = anchor["rect"]
        center = ar["y"] + ar["h"] / 2
        row = [b for b in items
               if abs(b["rect"]["y"] + b["rect"]["h"] / 2 - center) <= max(8.0, ar["h"] / 2)
               and 2 / 3 <= b["rect"]["h"] / ar["h"] <= 1.5]
        best = max(best, len(row))
    return best


def _button_like(box: dict) -> bool:
    if box["role"] in ("button", "input"):
        return True
    style = box.get("style") or {}
    return box["role"] == "link" and (style.get("background") is not None or style.get("border_px", 0) > 0)


@detector("section-inventory", layers=("render",))
def section_inventory(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    params = _params(det)
    check = params.get("check")
    if check not in ("proof-in-hero", "task-below-ornament"):
        return Result(skipped=f"unknown section-inventory check {check!r}")
    which = params.get("section", "first")
    measured = [p for p in pages if p.sections()]
    if not measured:
        return Result(skipped="the extract has no derived.sections")
    judged = [False]

    def observe(page: _Page) -> Iterable[_Obs]:
        sections = page.sections()
        chosen = sections[:1] if which == "first" else sections
        for index, section in enumerate(chosen):
            ident = section["box"]
            label = "first" if index == 0 else f"{section['archetype']} ({ident})"
            ids = [ident, *page.descendants(ident)]
            runs = page.subtree_runs(ident)
            if check == "proof-in-hero":
                judged[0] = True
                logos = _logo_row(page, ids)
                metrics = sum(1 for r in runs if len(r.get("text", "").strip()) <= 24
                              and _METRIC.fullmatch(r.get("text", "").strip() or "-"))
                proof = []
                if logos >= 4:
                    proof.append(f"a row of {logos} logos")
                if metrics >= 2:
                    proof.append(f"{metrics} metrics")
                if proof:
                    actions = sum(1 for i in ids if _button_like(page.by_id[i]))
                    blocks = len({r["box"] for r in runs if r.get("type_role") in ("body", "other", None)})
                    yield _Obs(("proof", ident),
                               f"the {label} section holds {' and '.join(proof)} beside {_count(actions, 'action')} "
                               f"and {_count(blocks, 'body text block')}", box=ident)
                continue
            task = next((i for i in ids if _button_like(page.by_id[i])), None)
            kind = "first action"
            if task is None:
                task = next((i for i in ids if page.by_id[i]["role"] == "heading"
                             or any(r.get("type_role") in _HEADING_RUNS for r in page.runs_by_box.get(i, ()))),
                            None)
                kind = "first heading"
            if task is None:
                continue
            judged[0] = True
            top = 0.0 if section is sections[0] else page.rect(ident)["y"]
            limit = top + page.height
            task_top = page.rect(task)["y"]
            if task_top < limit:
                continue
            subtrees = _subtrees(page)
            above = {i for i in ids if page.rect(i)["y"] < min(limit, task_top)}
            media = sum(1 for i in above if page.by_id[i]["role"] == "media")
            drawn = sum(1 for i in above if subtrees[i].decorative
                        and not subtrees.get(page.by_id[i].get("parent"), _PLAIN).decorative)
            if media + drawn == 0:
                continue                          # only text precedes it: a long-form opening, not ornament
            texts = sum(1 for r in runs if r["box"] in above)
            yield _Obs(("task", ident),
                       f"the {kind} of the {label} section ({task}) starts at {_fmt(task_top)} px, below "
                       f"the {_fmt(limit)} px reach, under {_count(media, 'media box', 'media boxes')}, "
                       f"{_count(drawn, 'CSS-drawn box', 'CSS-drawn boxes')}, and {_count(texts, 'text run')}",
                       box=task)

    hits = _merge(measured, observe)
    if not hits and not judged[0]:
        return Result(skipped="the chosen sections hold no action or heading to judge")
    return Result(hits=hits)


@detector("primary-task-first-view", layers=("plan", "render"))
def primary_task_first_view(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    from lapis_design.lint.detectors.behavior import _operating_plan

    if ctx.plan is None:
        return Result(skipped="no plan identifies the operating task or its first result")
    modes = set(_dig(ctx.plan, "direction", "read", "surface_mode") or [])
    frame = _dig(ctx.plan, "brief", "product_frame")
    work_frame = frame in ("forms-onboarding-checkout", "saas-dashboard-admin", "internal-tools")
    # A museum/article/landing may offer a secondary booking; its reading opening is not a work screen.
    work_mode = "operate" in modes and not modes & {"persuade", "experience"}
    if not _operating_plan(ctx.plan) or (modes and not work_frame and not work_mode):
        return Result()
    task = _dig(ctx.plan, "layout", "phone_task")
    if layer == "plan":
        if task:
            return Result()
        return Result(hits=[Hit(observed="operating screen has no phone-task acceptance: name the decision, "
                               "first useful result, what precedes it, and the captured task that proves it",
                               location={"path": "layout.phone_task"}, evidence="plan")])
    if not task:
        return Result(skipped="layout.phone_task is missing; the first useful result cannot be guessed from a CTA")
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    phone = [p for p in pages if p.width <= 430]
    notes = []

    def observe(page: _Page) -> Iterable[_Obs]:
        fact = page.derived.get("primary_task") or {}
        if fact.get("selector") != task["first_result"] or "y" not in fact or fact.get("unmeasured"):
            notes.append(f"{page.width}px: {fact.get('unmeasured') or 'plan-linked first-result geometry not recorded'}")
            return
        if fact["y"] >= page.height:
            before = "; ".join(fact.get("before") or []) or "no preceding labels recorded"
            yield _Obs(("primary-task", task["first_result"]),
                       f"first task result {task['first_result']!r} starts below the first phone view",
                       detail=f"y={_fmt(fact['y'])}px, view={_fmt(page.height)}px; visitor passes {before}")

    hits = _merge(phone, observe)
    return Result(hits=hits, skipped="; ".join(notes) or (None if phone else "no phone capture"))


# ---------------------------------------------------------------- sibling-identity

def _priorities(plan: dict | None) -> list[str]:
    values = _dig(plan, "layout", "procedure", "priority") or []
    return [str(v).casefold() for v in values if str(v).strip()]


@detector("sibling-identity", layers=("render",))
def sibling_identity(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    bound = _bound(det, "similarity_max")
    if bound is None:
        return _no_bound("similarity_max")
    measured = [p for p in pages if p.derived.get("sibling_groups") is not None]
    if not measured:
        return Result(skipped="the extract has no derived.sibling_groups")
    similar = [(p, g) for p in measured for g in p.derived["sibling_groups"] if g["similarity"] > bound]
    if not similar:
        return Result()
    by_plan = _params(det).get("compare") == "plan-priority"
    priorities: list[str] = []
    if by_plan:
        if ctx.plan is None:
            return Result(skipped="compare: plan-priority needs the plan")
        priorities = _priorities(ctx.plan)
        if not priorities:
            return Result(skipped="the plan has no layout.procedure.priority to compare siblings against")
    unjudged = set()

    def observe(page: _Page) -> Iterable[_Obs]:
        for g in page.derived["sibling_groups"]:
            if g["similarity"] <= bound:
                continue
            members = g["members"]
            head = f"{len(members)} siblings under {g['parent']} are {g['similarity']:.2f} similar"
            if not by_plan:
                yield _Obs(("group", g["parent"]), head, box=g["parent"], refs=tuple(members))
                continue
            ranks = {}
            for m in members:
                text = " ".join(r.get("text", "") for r in page.subtree_runs(m)).casefold()
                rank = next((i for i, p in enumerate(priorities) if p in text), None)
                if rank is not None:
                    ranks[m] = rank
            if len(set(ranks.values())) < 2:
                unjudged.add(g["parent"])
                continue
            ranked = ", ".join(f"{m}: {priorities[r]}" for m, r in ranks.items())
            yield _Obs(("group", g["parent"]),
                       f"{head} though the plan ranks them differently ({ranked})",
                       box=g["parent"], refs=tuple(members))

    hits = _merge(measured, observe)
    note = None
    if unjudged:
        note = (f"{_count(len(unjudged), 'sibling group')} above similarity {_fmt(bound)} not judged: no two "
                "members match distinct entries of the plan's layout.procedure.priority")
    return Result(hits=hits, skipped=note)


# ---------------------------------------------------------------- pricing-offers

# Same shape as render/derived.py, which decides what a priced card is.
_PRICE = re.compile(r"(?:[$€£¥₩₹]\s*\d|\d[\d,.]*\s*(?:[$€£¥₩₹]|원|usd|eur|krw|/\s*(?:mo|month|yr|year|월|년)))", re.I)
_EMPHASIS_DE = 0.03          # ΔE_OK by which a card's fill or border stands apart from its siblings'
_EMPHASIS_PX = 8             # px by which a card rises above or outgrows its siblings
_BADGE_WORDS = 4             # a ribbon or badge on a card is at most this many words


def _fill(box: dict) -> list[float] | None:
    background = (box.get("style") or {}).get("background")
    return background if background is not None and (len(background) < 4 or background[3] > 0) else None


def _effective_fill(page: _Page, ident: str) -> list[float]:
    """The card's own fill, else the nearest ancestor's, else white."""
    for i in (ident, *page.ancestors(ident)):
        fill = _fill(page.by_id[i])
        if fill is not None:
            return fill
    return [1.0, 0.0, 0.0]


def _shadowed(box: dict) -> bool:
    style = box.get("style") or {}
    return bool(style.get("shadow") or style.get("shadows"))


def _recommendation(text: str, phrases: list[str]) -> bool:
    folded = text.casefold()
    return any(re.search(rf"(?<!\w){re.escape(p.casefold())}(?!\w)", folded) if p.isascii() else p in folded
               for p in phrases)


def _plan_cards(page: _Page) -> Iterable[tuple[str, list[str]]]:
    """(parent, members in reading order) of each group of exactly three offerings: siblings that each
    hold a control, at least two of which show a price."""
    for group in page.derived.get("sibling_groups") or ():
        members = [m for m in group["members"] if m in page.by_id]
        if len(members) != 3:
            continue
        texts = {m: " ".join(r.get("text", "") for r in page.subtree_runs(m)) for m in members}
        controls = all(any(page.by_id[d]["role"] in _CONTROLS for d in page.descendants(m)) for m in members)
        if controls and sum(1 for t in texts.values() if _PRICE.search(t)) >= 2:
            rects = [page.rect(m) for m in members]
            row = all(_side_by_side(a, b) for a, b in combinations(rects, 2))
            yield group["parent"], sorted(members, key=lambda m: page.rect(m)["x" if row else "y"])


def _center_emphasis(page: _Page, members: list[str], phrases: list[str]) -> list[str]:
    """How the middle offering stands out from the two outer ones."""
    first, mid, last = members
    a, m, c = (page.by_id[i] for i in members)
    outer = (a, c)
    signals: list[str] = []
    fills = [_effective_fill(page, i) for i in members]
    if all(delta_e_ok(fills[1], f) > _EMPHASIS_DE for f in (fills[0], fills[2])):
        signals.append("its own fill")
    style = [(b.get("style") or {}) for b in (a, m, c)]
    widths = [s.get("border_px", 0) for s in style]
    colors = [s.get("border_color") for s in style]
    if widths[1] > max(widths[0], widths[2]) or (
            widths[1] > 0 and all(x is not None for x in colors)
            and all(delta_e_ok(colors[1], colors[k]) > 2 * _EMPHASIS_DE for k in (0, 2))):
        signals.append("a border the others lack" if widths[1] > max(widths[0], widths[2]) else "a different border color")
    if _shadowed(m) and not any(_shadowed(b) for b in outer):
        signals.append("a shadow")
    ra, rm, rc = (page.rect(i) for i in members)
    if _side_by_side(ra, rm) and _side_by_side(rm, rc):
        if rm["y"] <= min(ra["y"], rc["y"]) - _EMPHASIS_PX or rm["h"] >= max(ra["h"], rc["h"]) + _EMPHASIS_PX:
            signals.append("a raised or larger frame")

    def action(ident: str) -> dict | None:
        return next((page.by_id[d] for d in page.descendants(ident) if _button_like(page.by_id[d])), None)

    buttons = [action(i) for i in members]
    if all(buttons):
        filled = [_fill(b) is not None and delta_e_ok(_fill(b), f) > 0.15 for b, f in zip(buttons, fills)]
        if filled[1] and not filled[0] and not filled[2]:
            signals.append("the only filled action")
    own = {i: [r for r in page.subtree_runs(i)] for i in members}
    others = {r.get("text", "").strip().casefold() for i in (first, last) for r in own[i]}
    names = [r["box"] for r in own[mid] if r.get("type_role") in _HEADING_RUNS]
    name_top = min((page.rect(b)["y"] for b in names if b in page.by_id), default=None)
    for run in own[mid]:
        text = run.get("text", "").strip()
        if not text or not 1 <= len(text.split()) <= _BADGE_WORDS or run.get("type_role") in _HEADING_RUNS:
            continue
        if _recommendation(text, phrases):
            signals.append(f'the badge "{text}"')
            break
        box = page.by_id.get(run["box"])
        # a ribbon sits above the plan name, which every card has
        if (box and name_top is not None and text.casefold() not in others and not _PRICE.search(text)
                and box["rect"]["y"] + box["rect"]["h"] <= name_top + 1):
            signals.append(f'a label "{text}" above the plan name')
            break
    return signals


@detector("pricing-offers", layers=("render",))
def pricing_offers(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    check = _params(det).get("check")
    if check != "center-recommendation":
        return Result(skipped=f"unknown pricing-offers check {check!r}")
    bound = _bound(det, "emphasis_signals_max")
    if bound is None:
        return _no_bound("emphasis_signals_max")
    measured = [p for p in pages if p.derived.get("sibling_groups") is not None and p.has_style()]
    if not measured:
        return Result(skipped="the extract has no derived.sibling_groups or box styles")
    phrases = ctx.list_values(det["list"]) if det.get("list") else []

    def observe(page: _Page) -> Iterable[_Obs]:
        for parent, members in _plan_cards(page):
            signals = _center_emphasis(page, members, phrases)
            if len(signals) > bound:
                yield _Obs(("pricing", parent),
                           f"three offerings under {parent}, the middle one ({members[1]}) set apart by "
                           f"{', '.join(signals)}", box=members[1], refs=tuple(members))

    return Result(hits=_merge(measured, observe))


# ---------------------------------------------------------------- card-nesting

def _card_depths(page: _Page) -> dict[str, int]:
    depths: dict[str, int] = {}
    for box in page.boxes:            # parents come before children in document order
        ident = box["id"]
        chain = [ident, *page.ancestors(ident)]
        depths[ident] = sum(1 for i in chain if page.card_like(i))
    return depths


@detector("card-nesting", layers=("render",))
def card_nesting(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    check = _params(det).get("check", "depth")
    if check == "depth":
        bound = _bound(det, "depth_max")
        if bound is None:
            return _no_bound("depth_max")
        measured = [p for p in pages if p.derived.get("card_nesting_max") is not None or p.has_style()]
        if not measured:
            return Result(skipped="the extract has neither derived.card_nesting_max nor box styles")

        def observe(page: _Page) -> Iterable[_Obs]:
            depths = _card_depths(page) if page.has_style() else {}
            value = page.derived.get("card_nesting_max")
            if value is None:
                value = max(depths.values(), default=0)
            if value > bound:
                innermost = next((i for i, d in depths.items() if d == value), None)
                yield _Obs("depth", f"card-like boxes nest deeper than {_fmt(bound)}",
                           box=innermost, detail=f"depth {value}")
        return Result(hits=_merge(measured, observe))
    if check != "card-share":
        return Result(skipped=f"unknown card-nesting check {check!r}")
    bound = _bound(det, "content_share_max")
    if bound is None:
        return _no_bound("content_share_max")
    measured = [p for p in pages if p.has_style()]
    if not measured:
        return Result(skipped="boxes carry no style, so card boundaries cannot be read")

    def observe(page: _Page) -> Iterable[_Obs]:
        content = set(page.content_boxes()) | {r["box"] for r in page.runs if r["box"] in page.by_id}
        inside = [i for i in content if page.card_like(i) or any(page.card_like(a) for a in page.ancestors(i))]
        total = _union_area(page.rect(i) for i in content)
        if total <= 0:
            return
        share = _union_area(page.rect(i) for i in inside) / total
        if share > bound:
            yield _Obs("share", f"cards hold more than {_fmt(bound)} of the content area",
                       detail=f"share {share:.2f}")
    return Result(hits=_merge(measured, observe))


# ---------------------------------------------------------------- grid-filler

def _has_content(page: _Page, ident: str) -> bool:
    if page.subtree_runs(ident):
        return True
    for i in (ident, *page.descendants(ident)):
        box = page.by_id[i]
        media = box.get("media")
        if box["role"] in _CONTROLS or (box.get("a11y") or {}).get("name"):
            return True
        if media and not media.get("decorative") and media.get("kind") != "css-background":
            return True
        if box["role"] == "media" and not media:
            return True
    return False


@detector("grid-filler", layers=("render",))
def grid_filler(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)

    def observe(page: _Page) -> Iterable[_Obs]:
        min_area = 0.02 * page.width * page.height
        for parent, kids in page.children.items():
            if page.by_id[parent]["role"] == "nav":
                continue
            cells = [k for k in kids if page.by_id[k]["role"] not in _CONTENT - {"media"}
                     and _area(page.rect(k)) >= min_area]
            if len(cells) < 3 or not any(_side_by_side(page.rect(a), page.rect(b))
                                         for a, b in combinations(cells, 2)):
                continue
            filled = {c: _has_content(page, c) for c in cells}
            empty = [c for c in cells if not filled[c]]
            if not empty or 2 * len(empty) >= len(cells):
                continue                          # fillers are the exception in a grid of content
            for cell in empty:
                yield _Obs(("cell", cell),
                           f"grid cell {cell}, one of {len(cells)} cells under {parent}, holds no text, "
                           "meaningful media, or control", box=cell)
    return Result(hits=_merge(pages, observe))


# ---------------------------------------------------------------- gap-proximity

def _card_owner(page: _Page, ident: str) -> str | None:
    return next((a for a in page.ancestors(ident) if page.card_like(a) or page.by_id[a]["role"] == "card"), None)


def _neighbor(page: _Page, ident: str, candidates: list[str], above: bool) -> str | None:
    r = page.rect(ident)
    best, best_edge = None, None
    for other in candidates:
        if other == ident:
            continue
        o = page.rect(other)
        if not _stacked(r, o):
            continue
        if above and o["y"] + o["h"] <= r["y"] + 1:
            edge = o["y"] + o["h"]
            if best_edge is None or edge > best_edge:
                best, best_edge = other, edge
        elif not above and o["y"] >= r["y"] + r["h"] - 1:
            edge = o["y"]
            if best_edge is None or edge < best_edge:
                best, best_edge = other, edge
    return best


@detector("gap-proximity", layers=("render",))
def gap_proximity(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    check = _params(det).get("check")
    if check == "monotonous":
        bound = _bound(det, "level_ratio_min")
        if bound is None:
            return _no_bound("level_ratio_min")
        measured = [p for p in pages if (p.derived.get("gaps") or {}).get("level_ratio") is not None]
        if not measured:
            if any(p.derived.get("gaps") is not None for p in pages):
                return Result(skipped="derived.gaps.level_ratio is omitted (no inside-group gaps to compare)")
            return Result(skipped="the extract has no derived.gaps")

        def observe(page: _Page) -> Iterable[_Obs]:
            ratio = page.derived["gaps"]["level_ratio"]
            if ratio < bound:
                yield _Obs("ratio", f"sections are spaced less than {_fmt(bound)} times the gaps inside groups",
                           detail=f"level_ratio {ratio:.2f}")
        return Result(hits=_merge(measured, observe))
    if check != "heading-above-vs-below":
        return Result(skipped=f"unknown gap-proximity check {check!r}")

    def observe(page: _Page) -> Iterable[_Obs]:
        content = page.content_boxes()
        for heading in page.heading_boxes():
            top_box = heading
            above = _neighbor(page, heading, content, above=True)
            if above is not None and page.runs_by_box.get(above) and all(
                    r.get("type_role") == "label" for r in page.runs_by_box[above]):
                top_box = above                  # an eyebrow label belongs to its heading
                above = _neighbor(page, above, content, above=True)
            below = _neighbor(page, heading, content, above=False)
            if above is None or below is None:
                continue
            owner = _card_owner(page, heading)
            if owner is not None and owner == _card_owner(page, above):
                continue                          # inside one card every item belongs together
            a, h, b = page.rect(above), page.rect(top_box), page.rect(heading)
            gap_above = h["y"] - (a["y"] + a["h"])
            gap_below = page.rect(below)["y"] - (b["y"] + b["h"])
            if gap_above <= gap_below:
                yield _Obs(("heading", heading),
                           f"heading has {_fmt(gap_above)} px above and {_fmt(gap_below)} px below",
                           box=heading, refs=(above, below))

    return Result(hits=_merge(pages, observe))


# ---------------------------------------------------------------- symmetry

def _section_shape(page: _Page, section: str, centered: float) -> str | None:
    s = page.rect(section)
    if s["w"] <= 0:
        return None
    axis = s["x"] + s["w"] / 2
    content = [page.rect(i) for i in page.content_boxes(section) if page.rect(i)["w"] > 0]
    slack = 0.05 * s["w"]
    left = [r for r in content if r["x"] + r["w"] <= axis + slack and r["x"] + r["w"] / 2 < axis]
    right = [r for r in content if r["x"] >= axis - slack and r["x"] + r["w"] / 2 > axis]
    if left and right:
        def bbox(rects: list[dict]) -> dict:
            x1, y1 = min(r["x"] for r in rects), min(r["y"] for r in rects)
            x2, y2 = max(r["x"] + r["w"] for r in rects), max(r["y"] + r["h"] for r in rects)
            return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}
        lb, rb = bbox(left), bbox(right)
        band_top, band_bottom = max(lb["y"], rb["y"]), min(lb["y"] + lb["h"], rb["y"] + rb["h"])
        spanning = [r for r in content if r not in left and r not in right
                    and r["y"] < band_bottom and r["y"] + r["h"] > band_top]
        if _v_overlap(lb, rb) >= min(lb["h"], rb["h"]) / 2 and not spanning:
            equal = min(lb["w"], rb["w"]) >= 0.8 * max(lb["w"], rb["w"]) and min(lb["w"], rb["w"]) >= 0.3 * s["w"]
            return "split-50-50" if equal else "split"
    informative = [r for r in content if r["w"] < _FULL_SPAN * s["w"]]
    weight = sum(_area(r) for r in informative)
    if not weight:
        return None
    score = sum(_area(r) * max(0.0, 1 - abs(r["x"] + r["w"] / 2 - axis) / (s["w"] / 2))
                for r in informative) / weight
    return "centered" if score > centered else "asymmetric"


@detector("symmetry", layers=("render",))
def symmetry(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    params = _params(det)
    shapes = _names(params.get("shapes"))
    section = params.get("section", "all")
    if not shapes and section == "all":
        bound = _bound(det, "max")
        if bound is None:
            return _no_bound("max")
        measured = [p for p in pages if p.derived.get("symmetry") is not None]
        if not measured:
            return Result(skipped="the extract has no derived.symmetry")

        def observe(page: _Page) -> Iterable[_Obs]:
            score = page.derived["symmetry"]
            if score > bound:
                yield _Obs("page", f"content centers on the vertical axis above {_fmt(bound)}",
                           detail=f"symmetry {score:.2f}")
        return Result(hits=_merge(measured, observe))

    note = ""
    if params.get("compare") == "plan-priority":
        if ctx.plan is None:
            return Result(skipped="compare: plan-priority needs the plan")
        if _priorities(ctx.plan):
            return Result()      # the plan ranked the content first; review judges the shell
        note = " and the plan ranks no content (layout.procedure.priority is empty)"
    shapes = shapes or ["centered", "split-50-50"]
    centered = _bound(det, "max")
    centered = _CENTERED if centered is None else centered
    measured = [p for p in pages if p.sections()]
    if not measured:
        return Result(skipped="the extract has no derived.sections")
    targets, judged = [False], [False]

    def observe(page: _Page) -> Iterable[_Obs]:
        for s in page.sections():
            if section == "hero" and s["archetype"] != "hero":
                continue
            targets[0] = True
            shape = _section_shape(page, s["box"], centered)
            if shape is None:
                continue
            judged[0] = True
            if shape in shapes:
                yield _Obs(("shape", s["box"]), f"the {s['archetype']} section uses a stock shell{note}",
                           box=s["box"], detail=shape)

    hits = _merge(measured, observe)
    if not hits and targets[0] and not judged[0]:
        return Result(skipped=f"no {section} section with content whose placement can be read")
    return Result(hits=hits)


# ---------------------------------------------------------------- opening-split

_DESKTOP = 1024                    # captures at least this wide are judged; narrower ones stack on purpose
_SPLIT_HEADING_PX = 28             # the opening's heading is a display or heading run at least this large
_SPLIT_WIDTH = (0.2, 0.7)          # the object's share of the page width: narrower is an accent, wider a cover
_SPLIT_HEIGHT = 0.2                # the object's share of the first viewport height
_SPLIT_REACH = 0.08                # a heading box may reach this share of the page width, and a fifth of its own
                                   # width, into the object: a box is wider than the text set in it
_SPLIT_PROSE = 200                 # a box that holds a run this long is prose, not an object
_SPLIT_VISUAL = 0.25               # media or drawings must cover this share of a box that carries no fill itself
_SPLIT_OBJECT_ROLES = frozenset({"media", "icon", "card", "section", "other"})
_SPLIT_TEXT_ROLES = frozenset({"heading", "text", "button", "link"})


def _in_nav(page: _Page, ident: str) -> bool:
    return page.by_id[ident]["role"] == "nav" or any(page.by_id[a]["role"] == "nav" for a in page.ancestors(ident))


def _opening_heading(page: _Page) -> str | None:
    """The box of the largest display or heading run that starts in the first viewport outside navigation, when
    it is at least `_SPLIT_HEADING_PX`; the nearest heading box around it when there is one."""
    best: tuple[float, str] | None = None
    for run in page.runs:
        box = page.by_id.get(run["box"])
        size = run.get("size_px") or 0
        if (box is None or run.get("type_role") not in _HEADING_RUNS or size < _SPLIT_HEADING_PX
                or box["rect"]["y"] >= page.height or _in_nav(page, run["box"])):
            continue
        if best is None or size > best[0]:
            best = (size, run["box"])
    if best is None:
        return None
    return next((a for a in (best[1], *page.ancestors(best[1])) if page.by_id[a]["role"] == "heading"), best[1])


def _split_object_kind(page: _Page, ident: str) -> str | None:
    """What the box is as the second column: images and drawings, or a filled or bordered panel that holds
    content (a mock); None for prose and for unfilled wrappers of text."""
    subtree = (ident, *page.descendants(ident))
    if any((r.get("chars") or len(r.get("text", ""))) >= _SPLIT_PROSE for i in subtree for r in page.runs_by_box.get(i, ())):
        return None
    visual = _union_area(page.rect(i) for i in subtree
                         if page.by_id[i]["role"] in ("media", "icon") or page.by_id[i].get("media"))
    if visual >= _SPLIT_VISUAL * _area(page.rect(ident)):
        return "an image or drawing"
    if _painted(page.by_id[ident]) and (page.subtree_runs(ident) or visual):
        return "a boxed panel"
    return None


def _opening_splits(page: _Page, area_min: float, chars_max: float) -> Iterable[_Obs]:
    """The first viewport divides into two side-by-side groups: the heading with short text and controls on one
    side, an image, drawing, or boxed panel on the other. Either side counts, and the heading may be the
    larger box."""
    heading = _opening_heading(page)
    if heading is None:
        return
    h = page.rect(heading)
    view = page.width * page.height
    reach = min(_SPLIT_REACH * page.width, 0.2 * h["w"])
    around = {heading, *page.ancestors(heading)}
    objects: list[tuple[float, str, str, str]] = []          # (area, box, side, kind)
    for ident in page.pre_order():
        box, r = page.by_id[ident], page.rect(ident)
        if (box["role"] not in _SPLIT_OBJECT_ROLES or r["y"] >= page.height or _area(r) < area_min * view
                or not _SPLIT_WIDTH[0] * page.width <= r["w"] <= _SPLIT_WIDTH[1] * page.width
                or r["h"] < _SPLIT_HEIGHT * page.height or ident in around or heading in page.ancestors(ident)
                or _in_nav(page, ident)):
            continue
        if r["x"] >= h["x"] + h["w"] - reach:
            side = "right"
        elif r["x"] + r["w"] <= h["x"] + reach:
            side = "left"
        else:
            continue
        if _v_overlap(r, h) < min(r["h"], h["h"]) / 2:
            continue
        kind = _split_object_kind(page, ident)
        if kind is not None:
            objects.append((_area(r), ident, side, kind))
    if not objects:
        return
    _, obj, side, kind = max(objects, key=lambda o: o[0])    # the first of equal areas is the outermost
    o = page.rect(obj)
    near = o["x"] if side == "right" else o["x"] + o["w"]
    band = (min(o["y"], h["y"]), max(o["y"] + o["h"], h["y"] + h["h"]))
    inside = {obj, *page.descendants(obj)}
    controls = {i for i in page.pre_order() if page.by_id[i]["role"] in _CONTROLS}
    texts = actions = chars = 0
    for ident in page.pre_order():
        box = page.by_id[ident]
        if box["role"] not in _SPLIT_TEXT_ROLES or ident == heading or ident in inside or _in_nav(page, ident):
            continue
        ancestors = set(page.ancestors(ident))
        if heading in ancestors:
            continue
        r = page.rect(ident)
        cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
        if not band[0] <= cy <= band[1] or (cx >= near if side == "right" else cx <= near):
            continue
        if box["role"] in _CONTROLS:
            actions += 1
        elif not ancestors & controls:
            runs = page.subtree_runs(ident)
            texts += bool(runs)
            chars += sum(run.get("chars") or len(run.get("text", "")) for run in runs)
    if texts + actions == 0 or chars > chars_max:
        return
    label = " ".join(run.get("text", "") for run in page.subtree_runs(heading)).split()
    title = " ".join(label)[:40]
    yield _Obs(("split", heading), f'the first screen holds the heading "{title}" with {_count(texts, "text box", "text boxes")} and '
                                   f'{_count(actions, "control")} beside {kind} on the {side}', box=heading, refs=(obj,))


@detector("opening-split", layers=("render",))
def opening_split(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    area_min, chars_max = _bound(det, "object_area_share_min"), _bound(det, "text_chars_max")
    if area_min is None or chars_max is None:
        return _no_bound("object_area_share_min and text_chars_max")
    desktop = [p for p in pages if p.width >= _DESKTOP]
    if not desktop:
        return Result(skipped="the extract has no capture at desktop width, and narrower captures stack by design")
    return Result(hits=_merge(desktop, lambda page: _opening_splits(page, area_min, chars_max)))


# ---------------------------------------------------------------- opening-empty-area

# Seeds, like every number in the rule that reads them. The extract stores boxes and not the ink inside them,
# so a page is read from its boxes, and only the stack's own width may shrink to the text it holds.
_EMPTY_ROW_WIDE = 0.6              # a row of content this share of the page wide is the page's content, not an opening stack
_EMPTY_FOLLOW_WIDE = 0.5           # a row or box below the stack this share of the page wide ends the opening's band
_EMPTY_GAP = (48, 0.6)             # px plus this many heading sizes: the widest gap inside one stack
_EMPTY_BESIDE = 48                 # px: a part this close beside the stack's right edge is in its row
_EMPTY_EDGE = 4                    # px: left edges this close are one edge
_EMPTY_NARROWER = 0.85             # a box this much narrower than the heading's box shows where the stack aligns
_EMPTY_SIDE = 0.4                  # a stack is on the left when its center is no further than this share from the left edge
_EMPTY_PAD = 16                    # px between the stack and the region beside it
_EMPTY_OBJECT = 0.06               # a boxed panel with content fills the opening when it covers this share of the viewport
_EMPTY_TIGHT = 1.3                 # a one-line text box up to this times its text is wrapped tight around it
_EMPTY_ADVANCE = {"hang": 1.0, "kana": 1.0, "hani": 1.0}     # em per character; 0.6 for any other script
_EMPTY_FLOW = ("text", "control")
_EMPTY_KEYS = ("stack_width_share_min", "empty_share_max", "band_height_share_max", "occupancy_min",
               "below_width_share_min", "below_height_share_min")


@dataclass
class _Info:
    """One thing in the first viewport that tells the visitor something: text, a control, meaningful media, or a
    boxed panel that holds content (a mock or a figure, which layout.split-hero and the critic judge)."""
    box: str
    kind: str          # "text", "control", "media", or "object"
    x: float
    y: float
    w: float
    h: float           # what the content fills: a text box counts only as tall as its set lines
    set_w: float       # what one line of text is estimated to fill; the box's width for anything else
    known: bool        # the content fills its box, so the box's left edge is the content's left edge

    def ink(self, aligned: bool) -> tuple[float, float]:
        """Left and right edge of what the content fills. A one-line text box wider than its text is as wide as
        the text when the stack is left-aligned and as wide as the box otherwise: the extract cannot say where
        text sits in a wider box, and a wider answer never calls a page empty."""
        return self.x, self.x + (self.set_w if aligned and not self.known else self.w)

    def rect(self, aligned: bool | None = None) -> dict:
        """The box, or with `aligned` the ink in it."""
        left, right = (self.x, self.x + self.w) if aligned is None else self.ink(aligned)
        return {"x": left, "y": self.y, "w": right - left, "h": self.h}


def _text_fill(runs: list[dict], box: dict) -> tuple[float, float, bool]:
    """(width, height, tight) a text box's runs are estimated to fill: wrapped text fills its box's width; one
    line is as wide as its characters advance, and the box is tight when it is no wider than that."""
    height = min(box["h"], 1.1 * sum((r.get("lines") or 1) * (r.get("size_px") or 16) * max(r.get("line_height") or 1.2, 1.0)
                                     for r in runs) + 4)
    if any((r.get("lines") or 1) >= 2 for r in runs):
        return box["w"], height, True
    widest = max((r.get("measure_chars") or r.get("chars") or len(r.get("text", ""))) * (r.get("size_px") or 16)
                 * (_EMPTY_ADVANCE.get(r.get("script"), 0.6) + (r.get("letter_spacing_em") or 0)) for r in runs)
    return min(box["w"], widest), height, box["w"] <= _EMPTY_TIGHT * widest


def _opening_items(page: _Page, heading: str) -> list[_Info]:
    """What the first viewport holds outside navigation: text, controls, media that is not decorative, a
    placeholder, or unloaded, and boxed panels that hold content. Text inside a control does not count twice (the
    control stands for it); a box's own fill, border, shadow, and gradient never count, and aria-hidden text
    does, because it is on the screen."""
    items: list[_Info] = []
    controls: set[str] = set()
    around = {heading, *page.ancestors(heading)}
    view = page.width * page.height
    for ident in page.pre_order():
        box, r = page.by_id[ident], page.rect(ident)
        if (r["w"] <= 0 or r["h"] <= 0 or r["y"] >= page.height or r["y"] + r["h"] <= 0
                or r["x"] >= page.width or r["x"] + r["w"] <= 0 or _in_nav(page, ident)
                or any(a in controls for a in page.ancestors(ident))):
            continue
        if box["role"] in _CONTROLS:
            controls.add(ident)
            items.append(_Info(ident, "control", r["x"], r["y"], r["w"], r["h"], r["w"], True))
            continue
        media = box.get("media")
        if (box["role"] == "media" or media) and not (
                media and (media.get("decorative") or media.get("placeholder") or not media.get("loaded"))):
            items.append(_Info(ident, "media", r["x"], r["y"], r["w"], r["h"], r["w"], True))
        elif (box["role"] in _SPLIT_OBJECT_ROLES and ident not in around and heading not in page.ancestors(ident)
              and _area(r) >= _EMPTY_OBJECT * view and r["h"] >= _SPLIT_HEIGHT * page.height
              and _SPLIT_WIDTH[0] * page.width <= r["w"] <= _SPLIT_WIDTH[1] * page.width
              and _split_object_kind(page, ident) == "a boxed panel"):
            items.append(_Info(ident, "object", r["x"], r["y"], r["w"], r["h"], r["w"], True))
        runs = page.runs_by_box.get(ident)
        if runs:
            width, height, tight = _text_fill(runs, r)
            items.append(_Info(ident, "text", r["x"], r["y"], r["w"], height, width, tight))
    return items


def _item_rows(items: list[_Info]) -> list[dict]:
    """Text and controls grouped into rows by their boxes: an item joins the row it overlaps vertically by half
    of the shorter of the two."""
    rows: list[dict] = []
    for item in sorted((i for i in items if i.kind in _EMPTY_FLOW), key=lambda i: i.y):
        if (match := next((r for r in rows if min(r["y1"], item.y + item.h) - max(r["y0"], item.y)
                           >= 0.5 * min(r["y1"] - r["y0"], item.h)), None)) is None:
            rows.append({"y0": item.y, "y1": item.y + item.h, "x0": item.x, "x1": item.x + item.w, "items": [item]})
        else:
            match["y1"] = max(match["y1"], item.y + item.h)
            match["x0"], match["x1"] = min(match["x0"], item.x), max(match["x1"], item.x + item.w)
            match["items"].append(item)
    return rows


def _empty_openings(page: _Page, bound: dict[str, float]) -> Iterable[_Obs]:
    """A short left stack (the heading and the lede, labels, and controls attached to it) with no content beside
    it, and none wide enough below it to fill the first viewport. The stack is the heading plus what is
    connected to it, above and below, until a row as wide as the page's content starts."""
    heading = _opening_heading(page)
    if heading is None:
        return
    items = _opening_items(page, heading)
    inside = {heading, *page.descendants(heading)}
    seeds = [i for i in items if i.kind in _EMPTY_FLOW and i.box in inside]
    if not seeds:
        return
    width, height = page.width, page.height
    size = max((r.get("size_px") or 0) for r in page.subtree_runs(heading))
    gap = _EMPTY_GAP[0] + _EMPTY_GAP[1] * size
    left, widest, first = min(i.x for i in seeds), max(i.w for i in seeds), min(i.y for i in seeds)
    top, bottom = first, max(i.y + i.h for i in seeds)
    # Left-aligned when a box narrower than the heading's, or a control, sits on the heading's left edge below it.
    aligned = any(i.kind in _EMPTY_FLOW and i.known and i.box not in inside and abs(i.x - left) <= _EMPTY_EDGE
                  and i.w <= _EMPTY_NARROWER * widest and first <= i.y <= bottom + 2 * gap for i in items)
    rows = _item_rows(items)
    row_of = {id(i): row for row in rows for i in row["items"]}

    def wide(row: dict) -> bool:
        return row["x1"] - row["x0"] >= _EMPTY_ROW_WIDE * width

    stop = min((r["y0"] for r in rows if r["y0"] >= bottom - _EMPTY_EDGE and wide(r)), default=height)
    members = {id(i): i for i in seeds}
    e0, e1 = min(i.ink(aligned)[0] for i in seeds), max(i.ink(aligned)[1] for i in seeds)
    grown = True
    while grown:
        grown = False
        for i in items:
            if (i.kind not in _EMPTY_FLOW or id(i) in members or wide(row_of[id(i)]) or i.y >= stop
                    or max(i.y - bottom, top - (i.y + i.h), 0) > gap
                    or (i.kind == "control" and i.y + i.h <= first + _EMPTY_EDGE)     # a header's logo or link
                    or not e0 - _EMPTY_EDGE <= i.x < e1 + _EMPTY_BESIDE):
                continue
            members[id(i)] = i
            e0, e1 = min(e0, i.ink(aligned)[0]), max(e1, i.ink(aligned)[1])
            top, bottom = min(top, i.y), max(bottom, i.y + i.h)
            grown = True
    share = (e1 - e0) / width
    if share >= bound["stack_width_share_min"] or (e0 + e1) / 2 > _EMPTY_SIDE * width:
        return

    others = [i for i in items if id(i) not in members]
    navs = [n for n in (page.rect(i) for i in page.pre_order() if page.by_id[i]["role"] == "nav") if n["y"] < height]
    band_top = max([0.0, *(i.y + i.h for i in others if i.y + i.h <= top + _EMPTY_EDGE),
                    *(n["y"] + n["h"] for n in navs if n["y"] + n["h"] <= top + _EMPTY_EDGE)])
    below_rows = [r for r in rows if r["y0"] >= bottom - _EMPTY_EDGE and not any(id(i) in members for i in r["items"])]
    below_blocks = [i for i in others if i.kind not in _EMPTY_FLOW and i.y >= bottom - _EMPTY_EDGE]
    band_bottom = min([height,
                       *(r["y0"] for r in below_rows if r["x1"] - r["x0"] >= _EMPTY_FOLLOW_WIDE * width),
                       *(i.y for i in below_blocks if i.w >= _EMPTY_FOLLOW_WIDE * width)])
    region = {"x": e1 + _EMPTY_PAD, "y": band_top, "w": width - e1 - _EMPTY_PAD, "h": band_bottom - band_top}
    if region["w"] <= 0 or region["h"] <= 0:
        return
    band = region["h"] / height
    beside = []
    for i in others:
        rect = i.rect()
        w = min(rect["x"] + rect["w"], region["x"] + region["w"]) - max(rect["x"], region["x"])
        h = min(rect["y"] + rect["h"], region["y"] + region["h"]) - max(rect["y"], region["y"])
        if w > 0 and h > 0:
            beside.append({"x": max(rect["x"], region["x"]), "y": max(rect["y"], region["y"]), "w": w, "h": h})
    empty = 1 - _union_area(beside) / _area(region)
    shown = []
    for i in items:
        rect = i.rect(aligned if id(i) in members else None)
        w = min(rect["x"] + rect["w"], width) - max(rect["x"], 0)
        h = min(rect["y"] + rect["h"], height) - max(rect["y"], 0)
        if w > 0 and h > 0:
            shown.append({"x": max(rect["x"], 0), "y": max(rect["y"], 0), "w": w, "h": h})
    occupancy = _union_area(shown) / (width * height)
    # Content below the stack fills the first view when it is nearly as wide as the page's widest row, and tall.
    near = bound["below_width_share_min"] * max(r["x1"] - r["x0"] for r in rows)
    deep = [(r["y0"], r["y1"]) for r in below_rows if r["x1"] - r["x0"] >= near]
    deep += [(i.y, i.y + i.h) for i in below_blocks if i.w >= near]
    visible = min(height, max(b for _, b in deep)) - min(a for a, _ in deep) if deep else 0
    if (empty <= bound["empty_share_max"] or band <= bound["band_height_share_max"]
            or occupancy >= bound["occupancy_min"] or visible >= bound["below_height_share_min"] * height):
        return
    label = max(page.subtree_runs(heading), key=lambda r: r.get("size_px") or 0).get("text", "")
    title = " ".join(label.split())[:40]
    yield _Obs(("empty-opening", heading),
               f'the first screen holds the heading "{title}" in a left column {share:.0%} of the page wide, and '
               f'{empty:.0%} of the area beside it stays empty over {band:.0%} of the viewport height while '
               f'content fills {occupancy:.0%} of the viewport', box=heading)


@detector("opening-empty-area", layers=("render",))
def opening_empty_area(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    bound = {key: _bound(det, key) for key in _EMPTY_KEYS}
    if any(value is None for value in bound.values()):
        return _no_bound(", ".join(_EMPTY_KEYS))
    desktop = [p for p in pages if p.width >= _DESKTOP]
    if not desktop:
        return Result(skipped="the extract has no capture at desktop width, and narrower captures stack by design")
    return Result(hits=_merge(desktop, lambda page: _empty_openings(page, bound)))


# ---------------------------------------------------------------- reading-path

@detector("reading-path", layers=("render",))
def reading_path(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    check = _params(det).get("check")
    if check != "heading-separated-from-intro":
        return Result(skipped=f"unknown reading-path check {check!r}")

    def observe(page: _Page) -> Iterable[_Obs]:
        section_ids = {s["box"] for s in page.sections() or ()}
        runs = [r for r in page.runs if r["box"] in page.by_id]
        for index, run in enumerate(runs):
            if run.get("type_role") not in _HEADING_RUNS:
                continue
            if index + 1 < len(runs) and runs[index + 1]["box"] == run["box"]:
                continue                          # judge a heading once, from its last run
            heading = run["box"]
            intro = None
            for later in runs[index + 1:]:
                if later.get("type_role") in _HEADING_RUNS:
                    break
                if later.get("type_role") == "body":
                    intro = later["box"]
                    break
            if intro is None or intro == heading:
                continue
            if heading in page.ancestors(intro) or intro in page.ancestors(heading):
                continue
            if section_ids and page.section_of(heading, section_ids) != page.section_of(intro, section_ids):
                continue
            h, i = page.rect(heading), page.rect(intro)
            if not _stacked(h, i) and i["y"] < h["y"] + h["h"]:
                yield _Obs(("heading", heading),
                           f"heading {heading} and its intro {intro} sit in separate columns",
                           box=heading, refs=(intro,))

    return Result(hits=_merge(pages, observe))


# ---------------------------------------------------------------- edge-inset

@detector("edge-inset", layers=("render",))
def edge_inset(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    bound = _bound(det, "inset_px_min")
    if bound is None:
        return _no_bound("inset_px_min")
    width = _params(det).get("viewport")
    if width is not None:
        pages = [p for p in pages if p.width == width]
        if not pages:
            return Result(skipped=f"the extract has no {width} px capture")
    if not any(p.has_style() for p in pages):
        return Result(skipped="boxes carry no style, so cards cannot be told apart")

    def observe(page: _Page) -> Iterable[_Obs]:
        scrollers = {b["id"] for b in page.boxes if (b.get("scroll") or {}).get("axis") in ("x", "both")}
        for box in page.boxes:
            ident, r = box["id"], box["rect"]
            scroll = box.get("scroll") or {}
            if ident in scrollers:
                sides = [(name, scroll[key]) for name, key in (("start", "inset_start_px"), ("end", "inset_end_px"))
                         if key in scroll and scroll[key] < bound]
                if sides:
                    where = " and ".join(f"{_fmt(v)} px from its {n} edge" for n, v in sides)
                    yield _Obs(("scroller", ident), f"scroller items sit {where}, under {_fmt(bound)} px",
                               box=ident)
                continue
            if box["role"] == "media" or not page.card_like(ident):
                continue
            if any(a in scrollers for a in page.ancestors(ident)):
                continue                          # judged through the scroller's own insets
            left, right = r["x"], page.width - (r["x"] + r["w"])
            if r["x"] + r["w"] <= 0 or r["x"] >= page.width or (left <= 0.5 and right <= 0.5):
                continue                          # off-canvas, or deliberately full-bleed
            sides = [(n, v) for n, v in (("left", left), ("right", right)) if v < bound]
            if sides:
                where = " and ".join(f"{_fmt(v)} px from the {n}" for n, v in sides)
                yield _Obs(("card", ident), f"card sits {where} viewport edge, under {_fmt(bound)} px", box=ident)
    return Result(hits=_merge(pages, observe))


# ---------------------------------------------------------------- responsive-structure

@detector("responsive-structure", layers=("render",))
def responsive_structure(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    params = _params(det)
    check = params.get("check", "scaled-only")
    if check != "scaled-only":
        return Result(skipped=f"unknown responsive-structure check {check!r}")
    widths = [int(w) for w in params.get("compare") or (390, 1440)]
    by_width = {p.width: p for p in pages}
    narrow_w, wide_w = min(widths), max(widths)
    missing = [w for w in (narrow_w, wide_w) if w not in by_width]
    if missing:
        return Result(skipped=f"the extract has no capture at {', '.join(map(str, missing))} px")
    narrow, wide = by_width[narrow_w], by_width[wide_w]

    def role_index(page: _Page) -> tuple[dict[str, int], dict[str, list[str]]]:
        index, lists = {}, defaultdict(list)
        for b in page.boxes:
            index[b["id"]] = len(lists[b["role"]])
            lists[b["role"]].append(b["id"])
        return index, lists
    wide_index, _ = role_index(wide)
    _, narrow_lists = role_index(narrow)

    def match(ident: str) -> str | None:
        if ident in narrow.by_id:
            return ident
        same_role = narrow_lists.get(wide.by_id[ident]["role"], [])
        position = wide_index[ident]
        return same_role[position] if position < len(same_role) else None

    units = [s["box"] for s in wide.sections() or ()] or [None]
    hits = []
    for unit in units:
        content = wide.content_boxes(unit)
        narrowish = [i for i in content if 0 < wide.rect(i)["w"] < 0.6 * wide.width]
        columns = [i for i in narrowish if any(_side_by_side(wide.rect(i), wide.rect(o)) for o in content if o != i)]
        if len(columns) < 3:
            continue
        pairs = [(i, match(i)) for i in columns]
        pairs = [(i, n) for i, n in pairs if n is not None]
        if len(pairs) < 3:
            continue
        scaled = [i for i, n in pairs
                  if abs(narrow.rect(n)["x"] / narrow.width - wide.rect(i)["x"] / wide.width) <= _SCALED_TOLERANCE
                  and abs(narrow.rect(n)["w"] / narrow.width - wide.rect(i)["w"] / wide.width) <= _SCALED_TOLERANCE]
        if len(scaled) >= _SCALED_SHARE * len(pairs):
            where = f"section {unit}" if unit else "the page"
            location: dict[str, Any] = {"viewport": narrow_w}
            if unit:
                location["box"] = unit
            hits.append(Hit(observed=f"{len(scaled)} of {len(pairs)} side-by-side boxes in {where} keep their "
                                     f"{wide_w} px columns at {narrow_w} px, only scaled",
                            location=location, refs=scaled))
    return Result(hits=hits)


# ---------------------------------------------------------------- signature-present

@detector("signature-present", layers=("render",))
def signature_present(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    measured = [p for p in pages if p.derived.get("signature_found") is not None]
    if not measured:
        return Result(skipped="the extract has no derived.signature_found")
    planned = _dig(ctx.plan, "layout", "signature")
    what = (f"the plan's signature {planned!r} is not found in the render" if planned
            else "the render has no signature element")

    def observe(page: _Page) -> Iterable[_Obs]:
        if not page.derived["signature_found"]:
            yield _Obs("signature", f"{what} (no data-lapis-signature element)")
    hits = _merge(measured, observe)
    if hits:
        return Result(hits=hits)
    if any(page.derived.get("signature_evidence") == "not-verified" for page in measured):
        return Result(skipped="signature found by text only; not verified")
    return Result()


# ---------------------------------------------------------------- large-list

@detector("large-list", layers=("render",))
def large_list(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    bound = _bound(det, "rendered_items_max")
    if bound is None:
        return _no_bound("rendered_items_max")
    scrollers = [b for p in pages for b in p.boxes if "scroll" in b]
    if scrollers and not any("items" in b["scroll"] for b in scrollers):
        return Result(skipped="scroll containers carry no item counts")

    def observe(page: _Page) -> Iterable[_Obs]:
        for box in page.boxes:
            items = (box.get("scroll") or {}).get("items")
            if items is not None and items > bound:
                yield _Obs(("list", box["id"]),
                           f"{box['role']} scroll container ({box['scroll']['axis']}) renders {items} items at once",
                           box=box["id"])
    return Result(hits=_merge(pages, observe))


# ---------------------------------------------------------------- decorative-dom

def _painted(box: dict) -> bool:
    style = box.get("style") or {}
    background = style.get("background")
    return bool((background is not None and (len(background) < 4 or background[3] > 0))
                or style.get("border_px", 0) > 0 or style.get("gradients") or style.get("shadow")
                or style.get("shadows") or (style.get("clip") or {}).get("kind", "none") != "none"
                or style.get("background_pattern"))


@dataclass
class _Subtree:
    text: bool          # a text run in the box or below it
    media: bool         # a media box, or a box with media data, in the box or below it
    control: bool       # a button, link, or input in the box or below it
    decorative: bool    # the box itself is drawn with CSS and carries no text, media, name, or role
    bars: int           # decorative bar-shaped boxes below it
    shapes: int         # decorative boxes below it


_PLAIN = _Subtree(text=False, media=False, control=False, decorative=False, bars=0, shapes=0)


def _subtrees(page: _Page) -> dict[str, _Subtree]:
    """Bottom-up aggregates, computed once per page."""
    cached = page.memo.get("subtrees")
    if cached is not None:
        return cached
    result: dict[str, _Subtree] = {}
    for ident in page.post_order():
        box = page.by_id[ident]
        kids = [result[c] for c in page.children.get(ident, ()) if c in result]
        text = bool(page.runs_by_box.get(ident)) or any(k.text for k in kids)
        media_below = any(k.media for k in kids)
        decorative = (box["role"] in ("other", "card", "section") and not box.get("media")
                      and not (box.get("a11y") or {}).get("name") and not text and not media_below
                      and _painted(box))
        result[ident] = _Subtree(
            text=text,
            media=media_below or box["role"] == "media" or bool(box.get("media")),
            control=box["role"] in _CONTROLS or any(k.control for k in kids),
            decorative=decorative,
            bars=sum(k.bars + (k.decorative and _bar(page.by_id[c]))
                     for c, k in zip(page.children.get(ident, ()), kids)),
            shapes=sum(k.shapes + k.decorative for k in kids))
    page.memo["subtrees"] = result
    return result


def _dot(box: dict) -> bool:
    r = box["rect"]
    return (6 <= r["w"] <= 20 and abs(r["w"] - r["h"]) <= 2
            and (box.get("style") or {}).get("radius_px", 0) >= min(r["w"], r["h"]) / 2 - 1)


def _bar(box: dict) -> bool:
    r = box["rect"]
    return (0 < r["h"] <= 24 and r["w"] >= 3 * r["h"]) or (0 < r["w"] <= 24 and r["h"] >= 3 * r["w"])


def _app_windows(page: _Page) -> Iterable[_Obs]:
    subtrees = _subtrees(page)
    reported: set[str] = set()
    for parent, kids in page.children.items():
        dots = sorted((page.by_id[k] for k in kids if subtrees[k].decorative and _dot(page.by_id[k])),
                      key=lambda b: b["rect"]["x"])
        row = dots[:1]
        for dot in dots[1:]:
            prev, r = row[-1]["rect"], dot["rect"]
            if (abs((r["y"] + r["h"] / 2) - (prev["y"] + prev["h"] / 2)) <= 2
                    and r["x"] - (prev["x"] + prev["w"]) <= 2 * prev["w"]):
                row.append(dot)
            elif len(row) < 3:
                row = [dot]
        if len(row) < 3:
            continue
        size = row[0]["rect"]["h"]
        top = min(d["rect"]["y"] for d in row)
        window = next((i for i in (parent, *page.ancestors(parent))
                       if page.rect(i)["h"] >= 5 * size and page.rect(i)["w"] >= 10 * size), None)
        if (window is None or window in reported
                or top - page.rect(window)["y"] > max(60.0, 0.2 * page.rect(window)["h"])):
            continue
        reported.add(window)
        yield _Obs(("window", window),
                   f"box {window} draws window-control dots ({len(row)} circles) above its content",
                   box=window, refs=tuple(d["id"] for d in row))
    for ident in page.pre_order():
        sub = subtrees[ident]
        if (ident in reported or sub.text or sub.bars < 6 or page.by_id[ident]["role"] == "media"
                or any(a in reported for a in page.ancestors(ident))):
            continue
        reported.add(ident)
        bars = [d for d in page.descendants(ident) if subtrees[d].decorative and _bar(page.by_id[d])]
        yield _Obs(("bars", ident), f"box {ident} fakes data with {len(bars)} textless CSS bars",
                   box=ident, refs=tuple(bars[:12]))


def _round_or_shaped(box: dict) -> bool:
    style = box.get("style") or {}
    r = box["rect"]
    return bool(style.get("radius_px", 0) >= min(r["w"], r["h"]) / 2 - 1 or style.get("gradients")
                or (style.get("clip") or {}).get("kind", "none") != "none")


def _shape_illustrations(page: _Page) -> Iterable[_Obs]:
    subtrees = _subtrees(page)
    min_area = 0.01 * page.width * page.height
    found: set[str] = set()
    for ident in page.pre_order():
        box, sub = page.by_id[ident], subtrees[ident]
        if (box["role"] in _CONTENT or _area(box["rect"]) < min_area or sub.text or sub.media
                or sub.control or sub.shapes < 5 or any(a in found for a in page.ancestors(ident))):
            continue
        shapes = [d for d in page.descendants(ident) if subtrees[d].decorative]
        rects = [page.rect(d) for d in shapes]
        overlapping = sum(1 for a, b in combinations(rects, 2) if _h_overlap(a, b) > 0 and _v_overlap(a, b) > 0)
        rounded = sum(1 for d in shapes if _round_or_shaped(page.by_id[d]))
        if overlapping >= 2 or rounded >= 2:
            found.add(ident)
            yield _Obs(("shapes", ident), f"box {ident} assembles an illustration from {len(shapes)} CSS shapes",
                       box=ident, refs=tuple(shapes[:12]))


_CHIP_WORDS = 8                  # a chip holds a few words, not a paragraph
_CHIP_AREA = 0.04                # of the first viewport
_CHIP_OBJECT_AREA = (0.06, 0.55) # the object the chips float over, as a share of the first viewport
_CHIP_INSIDE = (0.15, 0.97)      # share of a chip over the object: below it the chip sits beside, above it inside
_CHIP_VS_OBJECT = 0.25           # a chip is at most this share of the object's area
_CHIPS_MIN = 2
_OPENING = 1.25                  # the opening is the first viewport and a quarter more
_NOT_CHIP_ROLES = frozenset({"button", "link", "input", "section", "heading", "media", "nav", "list"})


def _overlap(a: dict, b: dict) -> float:
    return _h_overlap(a, b) * _v_overlap(a, b)


def _floating_chips(page: _Page) -> Iterable[_Obs]:
    """Two or more short, boxed labels that overhang the edge of one large object in the opening: status,
    file, and proof panels that float around a hero illustration or mock."""
    if not page.has_style():
        return
    view = page.width * page.height
    opening = [i for i in page.pre_order() if page.rect(i)["y"] + page.rect(i)["h"] / 2 <= _OPENING * page.height]
    chips = []
    for ident in opening:
        box, rect = page.by_id[ident], page.rect(ident)
        if (box["role"] in _NOT_CHIP_ROLES or not _painted(box) or rect["w"] < 60 or rect["h"] < 20
                or _area(rect) > _CHIP_AREA * view or any(a in chips for a in page.ancestors(ident))):
            continue
        words = " ".join(r.get("text", "") for r in page.subtree_runs(ident)).split()
        if 1 <= len(words) <= _CHIP_WORDS and not any(page.by_id[d]["role"] in _CONTROLS for d in page.descendants(ident)):
            chips.append(ident)
    low, high = _CHIP_OBJECT_AREA
    objects = [i for i in opening if low * view <= _area(page.rect(i)) <= high * view and page.rect(i)["w"] <= 0.7 * page.width
               and page.by_id[i]["role"] not in (*_CONTROLS, "heading", "text", "nav")]
    floating: dict[str, list[str]] = defaultdict(list)
    for chip in chips:
        rect = page.rect(chip)
        best, best_overlap = None, 0.0
        ancestors = set(page.ancestors(chip))
        for obj in objects:
            if obj == chip or obj in ancestors or chip in page.ancestors(obj):
                continue
            orect = page.rect(obj)
            shared = _overlap(rect, orect)
            inside = shared / _area(rect)
            if not _CHIP_INSIDE[0] <= inside < _CHIP_INSIDE[1] or _area(rect) > _CHIP_VS_OBJECT * _area(orect):
                continue
            if shared > best_overlap or (shared == best_overlap and best and _area(orect) < _area(page.rect(best))):
                best, best_overlap = obj, shared
        if best is not None:
            floating[best].append(chip)
    for obj, members in floating.items():
        if len(members) >= _CHIPS_MIN:
            labels = ", ".join(f'"{" ".join(r.get("text", "") for r in page.subtree_runs(c))[:28].strip()}"' for c in members[:3])
            yield _Obs(("chips", members[0]), f"{len(members)} short boxed labels float over the edge of box {obj} in the "
                       f"opening: {labels}", box=obj, refs=tuple(members))


@detector("decorative-dom", layers=("render",))
def decorative_dom(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    kind = _params(det).get("kind")
    observe = {"app-window": _app_windows, "shape-illustration": _shape_illustrations,
               "floating-chips": _floating_chips}.get(kind)
    if observe is None:
        return Result(skipped=f"unknown decorative-dom kind {kind!r}")
    if not any(p.has_style() for p in pages):
        return Result(skipped="boxes carry no style, so CSS-drawn shapes cannot be read")
    return Result(hits=_merge(pages, observe))


# ---------------------------------------------------------------- contract-diff

def _family(name: str) -> str:
    return name.strip().strip("'\"").casefold()


def _contract_families(ctx: Context) -> tuple[dict[str, str], set[str]]:
    """Contract families (folded name -> name as written) and the allowed fallbacks."""
    names = [r["family"] for r in _dig(ctx.plan, "tokens", "type", "roles") or () if r.get("family")]
    fallback = set(system_fonts.generic_families())
    for font in (ctx.lock or {}).get("fonts") or ():
        if font.get("family"):
            names.append(font["family"])
        fallback.update(_family(f) for f in font.get("fallback") or ())
    return {_family(n): n.strip().strip("'\"") for n in names}, fallback


def _on_scale(value: float, steps: Iterable[float]) -> bool:
    return any(abs(value - step) <= max(0.5, 0.02 * step) for step in steps)


def _diff_family(ctx: Context, pages: list[_Page], det: dict) -> list[Hit] | str:
    families, fallback = _contract_families(ctx)
    if not families:
        return "font-family: neither the plan nor the fonts lock names contract families"
    allowed = families.keys() | fallback

    def observe(page: _Page) -> Iterable[_Obs]:
        found: dict[str, list[dict]] = defaultdict(list)
        for run in page.runs:
            requested = run["font"]["requested"]
            if _family(requested) not in allowed:
                found[requested].append(run)
        for requested, runs in found.items():
            yield _Obs(("family", _family(requested)),
                       f"{_count(len(runs), 'text run')} request {requested!r}, outside the contract families "
                       f"{', '.join(sorted(families.values()))}", box=runs[0]["box"])
    return _merge(pages, observe)


def _diff_color(ctx: Context, pages: list[_Page], det: dict) -> list[Hit] | str:
    bound = _bound(det, "delta_e_ok_max")
    if bound is None:
        return "color: the rule sets no threshold delta_e_ok_max"
    tokens = [(r.get("name", r.get("role", "?")), r["oklch"])
              for r in _dig(ctx.plan, "tokens", "color", "roles") or () if r.get("oklch")]
    if not tokens:
        return "color: the plan's color roles carry no oklch values"

    def observe(page: _Page) -> Iterable[_Obs]:
        colors: dict[tuple, list[str]] = defaultdict(list)
        def add(value: list[float] | None, ident: str) -> None:
            if value is not None and (len(value) < 4 or value[3] > 0):
                colors[tuple(round(v, 3) for v in value[:3])].append(ident)
        for run in page.runs:
            add(run.get("color"), run["box"])
        for box in page.boxes:
            style = box.get("style") or {}
            add(style.get("background"), box["id"])
            if style.get("border_px", 0) > 0:
                add(style.get("border_color"), box["id"])
        for color, idents in colors.items():
            name, distance = min(((n, delta_e_ok(list(color), t)) for n, t in tokens), key=lambda x: x[1])
            if distance > bound:
                yield _Obs(("color", color),
                           f"color oklch({color[0]:g} {color[1]:g} {color[2]:g}) on {_count(len(idents), 'element')} is "
                           f"{distance:.3f} from the nearest token {name}", box=idents[0])
    return _merge(pages, observe)


def _diff_font_size(ctx: Context, pages: list[_Page], det: dict) -> list[Hit] | str:
    scale = _dig(ctx.plan, "tokens", "type", "scale") or {}
    base, ratio = scale.get("base_px"), scale.get("ratio")
    if not base or not ratio or ratio <= 1:
        return "font-size: the plan's type scale needs base_px and a ratio above 1"

    def steps(size: float) -> list[float]:
        n = round(math.log(size / base) / math.log(ratio)) if size > 0 else 0
        return [base * ratio ** k for k in (n - 1, n, n + 1)]

    def observe(page: _Page) -> Iterable[_Obs]:
        found: dict[float, list[dict]] = defaultdict(list)
        for run in page.runs:
            size = run["size_px"]
            if size > 0 and not _on_scale(size, steps(size)):
                found[round(size * 2) / 2].append(run)
        for size, runs in sorted(found.items()):
            yield _Obs(("font-size", size),
                       f"{_count(len(runs), 'text run')} at {_fmt(size)} px, between steps of the type "
                       f"scale ({_fmt(base)} px x {_fmt(ratio)})", box=runs[0]["box"])
    return _merge(pages, observe)


def _diff_spacing(ctx: Context, pages: list[_Page], det: dict) -> list[Hit] | str:
    space = _dig(ctx.plan, "tokens", "space") or {}
    scale = [float(v) for v in space.get("scale") or () if isinstance(v, (int, float))]
    base = space.get("base_px")
    if not scale and not base:
        return "spacing: the plan's tokens.space has neither scale nor base_px"
    measured = [p for p in pages if p.derived.get("gaps")]
    if not measured:
        return "spacing: the extract has no derived.gaps"

    def fits(value: float) -> bool:
        if value <= 0.5:
            return True
        if scale:
            return _on_scale(value, scale)
        return _on_scale(value, [base * max(1, round(value / base))])

    def observe(page: _Page) -> Iterable[_Obs]:
        for level in ("inside_group", "between_groups", "between_sections"):
            value = (page.derived["gaps"].get(level) or {}).get("median")
            if value is not None and not fits(value):
                yield _Obs(("spacing", level), f"the median {level.replace('_', ' ')} gap is off the spacing scale",
                           detail=f"{_fmt(value)} px")
    return _merge(measured, observe)


_DIFFS = {"font-family": _diff_family, "color": _diff_color, "font-size": _diff_font_size,
          "spacing": _diff_spacing}


@detector("contract-diff", layers=("render",))
def contract_diff(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    kinds = _names(_params(det).get("kind"))
    if not kinds:
        return Result(skipped="the rule names no contract-diff kind")
    if ctx.plan is None and not (kinds == ["font-family"] and ctx.lock):
        return Result(skipped="contract-diff needs the plan's tokens")
    hits, skipped = [], []
    for kind in kinds:
        if kind == "radius":
            skipped.append("radius: the plan declares no radius tokens")
            continue
        diff = _DIFFS.get(kind)
        if diff is None:
            skipped.append(f"unknown kind {kind!r}")
            continue
        outcome = diff(ctx, pages, det)
        if isinstance(outcome, str):
            skipped.append(outcome)
        else:
            hits.extend(outcome)
    return Result(hits=hits, skipped="; ".join(skipped) or None)


# ---------------------------------------------------------------- motion-inventory

def _running(item: dict) -> bool:
    return item.get("duration_ms", 1) > 0


def _infinite(animation: dict) -> bool:
    return animation.get("iterations") == "infinite" and _running(animation)


def _overshoots(easing: str | None) -> bool:
    if not easing:
        return False
    if match := _BEZIER.search(easing):
        y1, y2 = float(match[2]), float(match[4])
        return not (0 <= y1 <= 1 and 0 <= y2 <= 1)
    if match := _LINEAR.search(easing):
        values = [float(token.split()[0]) for token in match[1].split(",") if token.strip()]
        return any(v < 0 or v > 1 for v in values)
    return False


def _motion_render(pages: list[_Page], det: dict, check: str) -> Result:
    params = _params(det)
    if check == "infinite-pulse-small-element":
        def observe(page: _Page) -> Iterable[_Obs]:
            for box in page.boxes:
                r = box["rect"]
                if max(r["w"], r["h"]) > 32:
                    continue
                for a in (box.get("motion") or {}).get("animations") or ():
                    if _infinite(a) and not a.get("stepped") and _PULSE & set(a.get("properties") or ()):
                        yield _Obs(("box", box["id"]),
                                   f"{_fmt(r['w'])}x{_fmt(r['h'])} px element pulses forever "
                                   f"({a.get('name', 'animation')}: {', '.join(a['properties'])})", box=box["id"])
                        break
        return Result(hits=_merge(pages, observe))
    if check == "blink-keyframes":
        def observe(page: _Page) -> Iterable[_Obs]:
            for box in page.boxes:
                for a in (box.get("motion") or {}).get("animations") or ():
                    if _infinite(a) and (a.get("stepped") or _BLINK_NAME.search(a.get("name", ""))):
                        yield _Obs(("box", box["id"]),
                                   f"element blinks forever ({a.get('name', 'animation')}, "
                                   f"{'stepped' if a.get('stepped') else 'blink keyframes'})", box=box["id"])
                        break
        return Result(hits=_merge(pages, observe))
    if check == "auto-moving-content":
        # Rest sampling covers every animated, transformed, or faded element; animations without any
        # rest sample mean the sampling did not run, while no animations at all means nothing moves.
        motions = [b.get("motion") or {} for p in pages for b in p.boxes]
        if any(m.get("animations") for m in motions) and not any("moves_at_rest" in m for m in motions):
            return Result(skipped="the extract records animations but no motion at rest (motion.moves_at_rest)")

        def observe(page: _Page) -> Iterable[_Obs]:
            for box in page.boxes:
                if (box.get("motion") or {}).get("moves_at_rest"):
                    yield _Obs(("box", box["id"]), f"{box['role']} content moves on its own at rest", box=box["id"])
        return Result(hits=_merge(pages, observe))
    if check == "overshoot-easing":
        bound = _bound(det, "share_max")
        if bound is None:
            return _no_bound("share_max")

        def observe(page: _Page) -> Iterable[_Obs]:
            animated, overshoot = [], []
            for box in page.boxes:
                motion = box.get("motion") or {}
                items = [t for t in motion.get("transitions") or () if _running(t)]
                items += [a for a in motion.get("animations") or () if _running(a)]
                if not items:
                    continue
                animated.append(box["id"])
                if any(_overshoots(i.get("easing")) for i in items):
                    overshoot.append(box["id"])
            if animated and len(overshoot) / len(animated) > bound:
                yield _Obs("share", f"overshooting easing on more than {_fmt(bound)} of animated boxes",
                           detail=f"{len(overshoot)} of {len(animated)}", refs=tuple(overshoot))
        return Result(hits=_merge(pages, observe))
    if check == "animated-properties":
        watched = set(_names(params.get("properties")))
        if not watched:
            return Result(skipped="the rule lists no properties to watch")

        def observe(page: _Page) -> Iterable[_Obs]:
            for box in page.boxes:
                motion = box.get("motion") or {}
                found = {t["property"] for t in motion.get("transitions") or ()
                         if t["property"] in watched and _running(t)}
                for a in motion.get("animations") or ():
                    if _running(a):
                        found |= watched & set(a.get("properties") or ())
                if found:
                    yield _Obs(("box", box["id"]), f"{box['role']} animates {', '.join(sorted(found))}",
                               box=box["id"])
        return Result(hits=_merge(pages, observe))
    if check == "transition-property-all":
        def observe(page: _Page) -> Iterable[_Obs]:
            for box in page.boxes:
                for t in (box.get("motion") or {}).get("transitions") or ():
                    if t["property"] == "all" and _running(t):
                        yield _Obs(("box", box["id"]),
                                   f"{box['role']} transitions all properties ({_fmt(t.get('duration_ms', 0))} ms)",
                                   box=box["id"])
                        break
        return Result(hits=_merge(pages, observe))
    if check == "infinite-decorative":
        bound = _bound(det, "count_max")
        if bound is None:
            return _no_bound("count_max")

        def observe(page: _Page) -> Iterable[_Obs]:
            looping = [b["id"] for b in page.boxes
                       if any(_infinite(a) for a in (b.get("motion") or {}).get("animations") or ())]
            if len(looping) > bound:
                yield _Obs("count", f"more than {_fmt(bound)} elements loop forever",
                           detail=_count(len(looping), "element"), refs=tuple(looping))
        return Result(hits=_merge(pages, observe))
    if check == "hover-transform":
        bound = _bound(det, "media_share_max")
        if bound is None:
            return _no_bound("media_share_max")

        def observe(page: _Page) -> Iterable[_Obs]:
            media = [b for b in page.boxes if b["role"] == "media"]
            moving = [b["id"] for b in media if _TRANSFORMS & set((b.get("motion") or {}).get("hover_changes") or ())]
            if media and len(moving) / len(media) > bound:
                yield _Obs("share", f"more than {_fmt(bound)} of media transform on hover",
                           detail=f"{len(moving)} of {len(media)}", refs=tuple(moving))
        return Result(hits=_merge(pages, observe))
    if check == "hidden-at-rest":
        def observe(page: _Page) -> Iterable[_Obs]:
            for box in page.boxes:
                if (box.get("motion") or {}).get("hidden_until_scroll"):
                    yield _Obs(("box", box["id"]), f"{box['role']} stays hidden until scrolled into view",
                               box=box["id"])
        return Result(hits=_merge(pages, observe))
    if check == "pause-control":
        return Result(skipped="pause controls are observed only in the behavior session", cause="layer")
    return Result(skipped=f"unknown motion-inventory check {check!r}")


def _motion_behavior(ctx: Context, det: dict, check: str) -> Result:
    probes = _session_items(ctx, "motion")
    if isinstance(probes, str):
        return Result(skipped=probes)
    found = []
    if check in ("auto-moving-content", "pause-control"):
        bound = None
        if check == "pause-control":
            bound = _bound(det, "seconds_without_control_max")
            if bound is None:
                return _no_bound("seconds_without_control_max")
        for p in probes:
            for item in p.get("auto_moving") or ():
                if bound is None:
                    found.append((item["box"], f"content moves on its own for {_fmt(item['seconds'])} s",
                                  p["context"], item["box"], []))
                elif not item["pause_control"] and item["seconds"] > bound:
                    found.append((item["box"], f"content moves on its own for {_fmt(item['seconds'])} s with no "
                                               "pause or stop control", p["context"], item["box"], []))
    elif check == "hover-transform":
        bound = _bound(det, "media_share_max")
        if bound is None:
            return _no_bound("media_share_max")
        for p in probes:
            hover = p.get("hover_media") or {}
            total, moving = hover.get("total", 0), hover.get("transforming", 0)
            if total and moving / total > bound:
                found.append(("share", f"{moving} of {total} hovered media transform on hover, more than "
                                       f"{_fmt(bound)}", p["context"], None, []))
    elif check == "hidden-at-rest":
        for p in probes:
            for item in p.get("scroll_reveal") or ():
                if item["hidden_at_rest"]:
                    delay = item.get("reveal_delay_ms")
                    extra = f", readable {_fmt(delay)} ms after entering the viewport" if delay is not None else ""
                    found.append((item["box"], f"content stays hidden at rest until scrolled{extra}",
                                  p["context"], item["box"], []))
    elif check == "infinite-decorative":
        bound = _bound(det, "count_max")
        if bound is None:
            return _no_bound("count_max")
        for p in probes:
            looping = [m["box"] for m in p.get("moving") or () if m.get("infinite") and not m.get("essential")]
            if len(looping) > bound:
                found.append(("count", f"{_count(len(looping), 'non-essential element')} loop forever, more than "
                                       f"{_fmt(bound)}", p["context"], None, looping))
    else:
        return Result(skipped=f"motion-inventory check {check!r} reads the render extract")
    return Result(hits=_merge_contexts(found))


@detector("motion-inventory", layers=("render", "behavior"))
def motion_inventory(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    check = _params(det).get("check")
    if layer == "behavior":
        return _motion_behavior(ctx, det, check)
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    return _motion_render(pages, det, check)


# ---------------------------------------------------------------- accessibility-tree

def _icon_note(page: _Page, box: dict) -> str:
    icon = box.get("icon") or next((page.by_id[d].get("icon") for d in page.descendants(box["id"])
                                    if page.by_id[d].get("icon")), None)
    if not icon:
        return ""
    action = f", {icon['action']}" if icon.get("action") else ""
    return f" (icon: {icon['kind']}{action})"


def _a11y_render(pages: list[_Page], det: dict, check: str) -> Result:
    if check == "input-label":
        inputs = [b for p in pages for b in p.boxes if b["role"] == "input"]
        if inputs and not any("a11y" in b for b in inputs):
            return Result(skipped="input boxes carry no accessibility data")

        def observe(page: _Page) -> Iterable[_Obs]:
            for box in page.boxes:
                a11y = box.get("a11y")
                if box["role"] != "input" or a11y is None or a11y.get("hidden"):
                    continue
                if not a11y.get("name") or a11y.get("name_source") == "none":
                    yield _Obs(("box", box["id"]), "input has no programmatic label", box=box["id"])
                elif a11y.get("name_source") == "placeholder":
                    yield _Obs(("box", box["id"]), "input's only label is its placeholder", box=box["id"])
        return Result(hits=_merge(pages, observe))
    if check == "control-name":
        roles = set(_names(_params(det).get("roles"))) or {"button", "link"}
        targets = [b for p in pages for b in p.boxes
                   if b["role"] in roles or (b.get("a11y") or {}).get("role") in roles]
        if targets and not any("a11y" in b for b in targets):
            return Result(skipped="control boxes carry no accessibility data")

        def observe(page: _Page) -> Iterable[_Obs]:
            for box in page.boxes:
                a11y = box.get("a11y")
                if a11y is None or a11y.get("hidden"):
                    continue
                role = box["role"] if box["role"] in roles else a11y.get("role")
                if role not in roles:
                    continue
                if not (a11y.get("name") or "").strip():
                    yield _Obs(("box", box["id"]), f"{role} has no accessible name{_icon_note(page, box)}",
                               box=box["id"])
        return Result(hits=_merge(pages, observe))
    if check == "pointer-only-control":
        # Controls, headings, landmarks, media, and icons always get accessibility data when the
        # interaction pass ran; without any, pointer handlers were not read either.
        recorded = {"button", "link", "input", "heading", "nav", "media", "icon", "dialog", "section"}
        always = [b for p in pages for b in p.boxes if b["role"] in recorded]
        if always and not any("a11y" in b for b in always):
            return Result(skipped="boxes carry no accessibility data")

        def focusable(page: _Page, ident: str) -> bool:
            box = page.by_id[ident]
            return box["role"] in _CONTROLS or bool((box.get("a11y") or {}).get("focusable"))

        def observe(page: _Page) -> Iterable[_Obs]:
            for box in page.boxes:
                a11y = box.get("a11y") or {}
                if not (a11y.get("pointer_handler") or a11y.get("pointer_cursor")):
                    continue
                if a11y.get("focusable") or a11y.get("disabled") or a11y.get("hidden"):
                    continue
                ident = box["id"]
                if any(focusable(page, i) for i in (*page.ancestors(ident), *page.descendants(ident))):
                    continue                      # the pointer lands on, or delegates to, a real control
                how = "has a pointer handler" if a11y.get("pointer_handler") else \
                    "shows a pointer cursor (handler not read)"
                yield _Obs(("box", ident), f"{box['role']} box {how} but is not focusable", box=ident)
        return Result(hits=_merge(pages, observe))
    if check == "label-persists-after-input":
        return Result(skipped="label persistence is observed only in the behavior session", cause="layer")
    return Result(skipped=f"unknown accessibility-tree check {check!r}")


def _a11y_behavior(ctx: Context, check: str) -> Result:
    if check != "label-persists-after-input":
        return Result(skipped=f"accessibility-tree check {check!r} reads the render extract")
    forms = _session_items(ctx, "forms")
    if isinstance(forms, str):
        return Result(skipped=forms)
    fields = [(form, f) for form in forms for f in form.get("fields") or ()]
    judged = [(form, f) for form, f in fields if "persists_after_input" in (f.get("label") or {})]
    if fields and not judged:
        return Result(skipped="no form field records whether its label persists after input")
    return Result(hits=_merge_contexts(
        (f["box"], f"{f['kind']} field's label disappears once the field has a value", form["context"],
         f["box"], [])
        for form, f in judged if not f["label"]["persists_after_input"]))


@detector("accessibility-tree", layers=("render", "behavior"))
def accessibility_tree(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    check = _params(det).get("check")
    if layer == "behavior":
        return _a11y_behavior(ctx, check)
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    return _a11y_render(pages, det, check)


# ---------------------------------------------------------------- layout-shift

@detector("layout-shift", layers=("render", "behavior"))
def layout_shift(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    params = _params(det)
    during = params.get("during", "load")
    measure = params.get("measure", "shift")
    if layer == "render":
        if during != "load" or measure != "shift":
            return Result(skipped="shifts after a state change and layout animation are measured in the behavior "
                                  "session")
        pages = _pages(ctx)
        if isinstance(pages, str):
            return Result(skipped=pages)
        bound = _bound(det, "cls_max")
        if bound is None:
            return _no_bound("cls_max")
        measured = [p for p in pages if (p.vp.get("metrics") or {}).get("cls") is not None]
        if not measured:
            return Result(skipped="the extract has no viewport.metrics.cls")

        def observe(page: _Page) -> Iterable[_Obs]:
            metrics = page.vp["metrics"]
            if metrics["cls"] > bound:
                sources = tuple(metrics.get("shift_sources") or ())
                yield _Obs("cls", f"layout shifts during load and the scroll pass beyond CLS {_fmt(bound)}",
                           box=sources[0] if sources else None, detail=f"CLS {metrics['cls']:.3f}", refs=sources)
        return Result(hits=_merge(measured, observe))
    if during != "state-change":
        return Result(skipped="load shift is measured in the render extract")
    probes = _session_items(ctx, "controls")
    if isinstance(probes, str):
        return Result(skipped=probes)
    found = []
    if measure == "layout-animated":
        for p in probes:
            boxes = p["effect"].get("layout_animated") or []
            if boxes:
                found.append((p["box"], f"activating the control animates the geometry of {_count(len(boxes), 'box', 'boxes')} "
                                        "through a layout property", p["context"], p["box"], list(boxes)))
        return Result(hits=_merge_contexts(found))
    if measure != "shift":
        return Result(skipped=f"unknown layout-shift measure {measure!r}")
    bound = _bound(det, "cls_max")
    if bound is None:
        return _no_bound("cls_max")
    for p in probes:
        shift = p["effect"].get("layout_shift")
        if shift is not None and shift > bound:
            found.append((p["box"], f"activating the control shifts layout by {shift:.3f}, beyond {_fmt(bound)}",
                          p["context"], p["box"], list(p["effect"].get("shift_sources") or ())))
    return Result(hits=_merge_contexts(found))
