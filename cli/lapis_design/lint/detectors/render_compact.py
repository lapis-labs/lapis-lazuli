"""Compact-width layout detectors: desktop navigation kept on a phone, a decorative object that fills the
first phone view below the heading, and a phone page whose length is mostly bands with nothing to read.

They read the captures narrower than `_COMPACT` (320 and 390 px), where a layout either was composed for
the width or is the desktop one squeezed. Every number is a seed, not a validated bound (the rules' provenance
says how each was checked). Meanings of the extract fields: render/DERIVED.md."""
from __future__ import annotations

from typing import Iterable

from lapis_design.lint.detectors.render_layout import (
    _CONTROLS, _HEADING_RUNS, _SPLIT_OBJECT_ROLES, _Obs, _Page, _bound, _count, _in_nav, _merge, _no_bound, _pages,
    _params, _split_object_kind,
)
from lapis_design.lint.types import Context, Result, detector

_COMPACT = 600                    # captures narrower than this are phone layouts
_RAIL_MIN_PX = 32                 # a column narrower than this is a divider, not a rail
_RAIL_TOP = 0.25                  # a rail starts in the top quarter of the viewport
_RAIL_STOPS = 3                   # a rail holds at least this many stacked links, buttons, or icons
_RAIL_BESIDE = 24                 # px: content this close to the rail's inner edge still sits beside it
_NAV_ROW_TOLERANCE = 8            # px: links whose tops differ by less than this are in one row
_HEADING_PX = 20                  # the opening heading on a phone is a display or heading run at least this large
_OBJECT_WIDE = 0.5                # the opening's object spans at least this share of the page width
_OBJECT_TALL = 0.12               # and at least this share of the viewport height
_OBJECT_TOP = 0.75                # and starts above this share of the viewport height
_BAND_PX = 4                      # px: an object below the heading may overlap its box by this much


def _compact(pages: list[_Page]) -> list[_Page]:
    return [p for p in pages if p.width < _COMPACT]


def _stops(page: _Page, ident: str) -> list[str]:
    """Links, buttons, and icons inside a box, in document order."""
    return [i for i in page.descendants(ident) if page.by_id[i]["role"] in (*_CONTROLS, "icon")]


def _rails(page: _Page, width_max: float, height_min: float) -> Iterable[_Obs]:
    """A narrow column at a page edge, full height, holding stacked links or icons, with content beside it."""
    seen: set[str] = set()
    for ident in page.pre_order():
        box, r = page.by_id[ident], page.rect(ident)
        if (box["role"] not in ("nav", "section", "other", "list", "card") or ident in seen
                or not _RAIL_MIN_PX <= r["w"] <= width_max * page.width or r["h"] < height_min * page.height
                or r["y"] > _RAIL_TOP * page.height or r["x"] + r["w"] <= 0 or r["x"] >= page.width):
            continue
        left = r["x"] <= _RAIL_BESIDE / 3
        right = r["x"] + r["w"] >= page.width - _RAIL_BESIDE / 3
        if not left and not right:
            continue
        stops = _stops(page, ident)
        rows = sorted({round(page.rect(s)["y"] / 12) for s in stops})
        if len(stops) < _RAIL_STOPS or len(rows) < _RAIL_STOPS:
            continue
        inner = r["x"] + r["w"] if left else r["x"]
        inside = {ident, *page.descendants(ident)}
        beside = any(
            i not in inside and page.runs_by_box.get(i) and (
                page.rect(i)["x"] >= inner - _RAIL_BESIDE if left else page.rect(i)["x"] + page.rect(i)["w"] <= inner + _RAIL_BESIDE)
            for i in page.pre_order())
        if not beside:
            continue
        seen.update(inside)
        yield _Obs(("rail", ident),
                   f"a {round(r['w'])} px column of {len(stops)} stacked links and icons stays "
                   f"at the {'left' if left else 'right'} edge with the content beside it",
                   box=ident, refs=tuple(stops[:4]))


def _nav_rows(page: _Page, links_min: float) -> Iterable[_Obs]:
    """A navigation bar whose items run off the page, wrap inside an item, or number more than a phone fits in a row."""
    for ident in page.pre_order():
        box = page.by_id[ident]
        if box["role"] != "nav" or page.rect(ident)["y"] >= page.height or page.rect(ident)["x"] + page.rect(ident)["w"] <= 0:
            continue
        links = [i for i in page.descendants(ident) if page.by_id[i]["role"] in ("link", "button")
                 and page.by_id[i]["rect"]["w"] > 0]
        if len(links) < 2:
            continue
        tops = sorted(page.rect(i)["y"] for i in links)
        row = [i for i in links if abs(page.rect(i)["y"] - tops[0]) < _NAV_ROW_TOLERANCE]
        if len(row) < 2:
            continue                                   # a stacked list is a menu, not a bar of tabs
        beyond = [i for i in row if page.rect(i)["x"] + page.rect(i)["w"] > page.width + 1 or page.rect(i)["x"] < -1]
        wrapped = [i for i in row if any((run.get("lines") or 1) > 1 for r in (i, *page.descendants(i))
                                         for run in page.runs_by_box.get(r, ()))]
        scrolls = (box.get("scroll") or {}).get("axis") in ("x", "both") and len(row) >= links_min
        many = len(row) >= links_min
        if not (beyond or wrapped or scrolls or many):
            continue
        reason = (f"{_count(len(beyond), 'item')} run past the page edge" if beyond
                  else f"{_count(len(wrapped), 'item label')} wrap onto a second line" if wrapped
                  else f"{len(row)} items sit in one row")
        yield _Obs(("row", ident), f"a navigation bar of {_count(len(row), 'item')}: {reason}", box=ident,
                   refs=tuple((beyond or wrapped or row)[:4]))


@detector("compact-navigation", layers=("render",))
def compact_navigation(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    bound = {key: _bound(det, key) for key in ("rail_width_share_max", "rail_height_share_min", "row_items_min")}
    if any(value is None for value in bound.values()):
        return _no_bound(", ".join(bound))
    compact = _compact(pages)
    if not compact:
        return Result(skipped="the extract has no capture narrower than 600 px")
    checks = set(_params(det).get("checks") or ["sidebar", "row"])

    def observe(page: _Page) -> Iterable[_Obs]:
        if "sidebar" in checks:
            yield from _rails(page, bound["rail_width_share_max"], bound["rail_height_share_min"])
        if "row" in checks:
            yield from _nav_rows(page, bound["row_items_min"])
    return Result(hits=_merge(compact, observe))


# ---------------------------------------------------------------- compact-opening

def _compact_heading(page: _Page) -> str | None:
    """The box of the largest display or heading run that starts in the first viewport outside navigation."""
    best: tuple[float, str] | None = None
    for run in page.runs:
        box = page.by_id.get(run["box"])
        size = run.get("size_px") or 0
        if (box is None or run.get("type_role") not in _HEADING_RUNS or size < _HEADING_PX
                or box["rect"]["y"] >= page.height or _in_nav(page, run["box"])):
            continue
        if best is None or size > best[0]:
            best = (size, run["box"])
    if best is None:
        return None
    return next((a for a in (best[1], *page.ancestors(best[1])) if page.by_id[a]["role"] == "heading"), best[1])


def _object_openings(page: _Page, share_min: float) -> Iterable[_Obs]:
    """The first phone view below the heading is mostly one image or drawing with nothing to do in it."""
    heading = _compact_heading(page)
    if heading is None:
        return
    h = page.rect(heading)
    view = page.width * page.height
    around = {heading, *page.ancestors(heading)}
    best: tuple[float, str] | None = None
    for ident in page.pre_order():
        box, r = page.by_id[ident], page.rect(ident)
        if (box["role"] not in _SPLIT_OBJECT_ROLES or ident in around or heading in page.ancestors(ident)
                or r["y"] < h["y"] + h["h"] - _BAND_PX or r["y"] >= _OBJECT_TOP * page.height
                or r["w"] < _OBJECT_WIDE * page.width or r["h"] < _OBJECT_TALL * page.height or _in_nav(page, ident)):
            continue
        if any(page.by_id[d]["role"] in _CONTROLS for d in page.descendants(ident)):
            continue                                   # a panel with controls in it is the task, not an ornament
        if _split_object_kind(page, ident) != "an image or drawing":
            continue
        visible = max(0.0, min(r["y"] + r["h"], page.height) - max(r["y"], 0)) * min(r["w"], page.width)
        share = visible / view
        if share >= share_min and (best is None or share > best[0]):
            best = (share, ident)
    if best is None:
        return
    text = " ".join(run.get("text", "") for run in page.subtree_runs(heading)).split()
    yield _Obs(("object", heading),
               f'an image or drawing fills {best[0]:.0%} of the first view below the heading "{" ".join(text)[:40]}"',
               box=best[1], refs=(heading,))


@detector("compact-opening", layers=("render",))
def compact_opening(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    share_min = _bound(det, "object_view_share_min")
    if share_min is None:
        return _no_bound("object_view_share_min")
    compact = _compact(pages)
    if not compact:
        return Result(skipped="the extract has no capture narrower than 600 px")
    return Result(hits=_merge(compact, lambda page: _object_openings(page, share_min)))


# ---------------------------------------------------------------- compact-length

def _reading_spans(page: _Page) -> list[tuple[float, float]]:
    """Vertical spans of the page that hold text or a control, merged."""
    spans = []
    for run in page.runs:
        box = page.by_id.get(run["box"])
        if box is not None:
            spans.append((box["rect"]["y"], box["rect"]["y"] + box["rect"]["h"]))
    for box in page.boxes:
        if box["role"] in _CONTROLS:
            spans.append((box["rect"]["y"], box["rect"]["y"] + box["rect"]["h"]))
    spans.sort()
    merged: list[list[float]] = []
    for top, bottom in spans:
        if merged and top <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], bottom)
        else:
            merged.append([top, bottom])
    return [(a, b) for a, b in merged]


def _empty_bands(page: _Page, band_min: float, empty_min: float, screens_min: float) -> Iterable[_Obs]:
    """Bands of the phone page, each a share of the viewport tall, with nothing in them to read or press."""
    length = max((b["rect"]["y"] + b["rect"]["h"] for b in page.boxes), default=0.0)
    if page.height <= 0 or length < screens_min * page.height:
        return
    spans = _reading_spans(page)
    bands = []
    top = 0.0
    for start, end in spans:
        if start - top >= band_min * page.height:
            bands.append((top, start))
        top = max(top, end)
    if length - top >= band_min * page.height:
        bands.append((top, length))
    empty = sum(b - a for a, b in bands) / length
    if empty >= empty_min:
        where = ", ".join(f"{round(a)}-{round(b)}" for a, b in bands[:3])
        yield _Obs(("empty", "page"),
                   f"{empty:.0%} of a {length / page.height:.1f}-screen page is {_count(len(bands), 'band')} with nothing "
                   f"to read or press (y {where} px)")


@detector("compact-length", layers=("render",))
def compact_length(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    bound = {key: _bound(det, key) for key in ("band_height_share_min", "empty_share_min", "screens_min")}
    if any(value is None for value in bound.values()):
        return _no_bound(", ".join(bound))
    compact = _compact(pages)
    if not compact:
        return Result(skipped="the extract has no capture narrower than 600 px")
    return Result(hits=_merge(compact, lambda page: _empty_bands(
        page, bound["band_height_share_min"], bound["empty_share_min"], bound["screens_min"])))
