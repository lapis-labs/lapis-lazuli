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
_GENERIC_FAMILIES = frozenset({
    "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif",
    "ui-sans-serif", "ui-monospace", "ui-rounded", "math", "emoji", "fangsong", "-apple-system",
    "blinkmacsystemfont"})
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
    measured = [p for p in pages if p.derived.get("section_sequence") is not None]
    if not measured:
        return Result(skipped="the extract has no derived.section_sequence")

    def observe(page: _Page) -> Iterable[_Obs]:
        # No template names a footer and every page ends with one, so it is not compared.
        sequence = [a for a in page.derived["section_sequence"] if a != "footer"]
        if not sequence:
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


@detector("decorative-dom", layers=("render",))
def decorative_dom(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    kind = _params(det).get("kind")
    observe = {"app-window": _app_windows, "shape-illustration": _shape_illustrations}.get(kind)
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
    fallback = set(_GENERIC_FAMILIES)
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
