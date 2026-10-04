"""Hierarchy detectors: icon tiles set larger than the headings they introduce, sections that repeat one
shape, a page that keeps one background and one shape from top to bottom, and a row of big-number tiles that
opens the page.

They read the desktop capture (1024 px and wider), where the order of sections and the rows of a grid are the
composition; narrower captures stack by design. Every number is a seed, not a validated bound (the rules'
provenance says how each was checked). Meanings of the extract fields: render/DERIVED.md."""
from __future__ import annotations

import re
from typing import Iterable

from lapis_design.lint.detectors.render_layout import (
    _DESKTOP, _HEADING_RUNS, _ICON_MEDIA_PX, _Obs, _Page, _bound, _count, _merge, _no_bound, _pages, _painted,
)
from lapis_design.lint.types import Context, Result, detector
from lapis_design.render.color import delta_e_ok

_TILE_MAX_PX = 120               # an icon tile is at most this large on a side
_TILE_SHAPE = (0.6, 1.6)         # and roughly square
_TILE_LEADING = 12               # a tile is among the first boxes of the item
_TILE_SHARE = 0.8                # of the items in a group open with a tile
_ROW_TOLERANCE = 20              # px: cards whose tops differ by less than this are in one row
_BAND_WIDE = 0.9                 # a tinted band spans this share of the page width
_BAND_TALL = 120                 # and is at least this tall
_NUMBER = re.compile(r"^[~≈<>+±]?\s*[$€£¥₩]?\s*\d[\d.,]*\s*(?:[kmb%]|만|천|억|명|개|대|건|배|분|초|원)?\s*\+?$", re.I)
_TILE_NUMBER_RATIO = 1.4         # the number is this much larger than the other text in its tile
_TILE_RUNS_MAX = 6               # a metric tile holds a label, a number, and a line or two of context


def _desktop(ctx: Context) -> list[_Page] | str:
    pages = _pages(ctx)
    if isinstance(pages, str):
        return pages
    desktop = [p for p in pages if p.width >= _DESKTOP]
    return desktop or "the extract has no capture at desktop width, and narrower captures stack by design"


def _first_run(page: _Page, ident: str) -> dict | None:
    """The heading run of an item, else its first run, in document order."""
    runs = page.subtree_runs(ident)
    return next((r for r in runs if r.get("type_role") in _HEADING_RUNS), runs[0] if runs else None)


# ---------------------------------------------------------------- icon-tile-cards

def _leading_tile(page: _Page, member: str) -> str | None:
    """The icon, or the small painted box that holds it, when the item opens with one before any text."""
    for ident in page.descendants(member)[:_TILE_LEADING]:
        box, r = page.by_id[ident], page.rect(ident)
        if box["role"] in ("heading", "text", "button", "link", "input"):
            return None
        if box["role"] != "icon" and not (box["role"] == "media" and max(r["w"], r["h"]) <= _ICON_MEDIA_PX):
            continue
        parent = box.get("parent")
        if parent and parent != member and parent in page.by_id:
            p = page.rect(parent)
            if (_painted(page.by_id[parent]) and max(p["w"], p["h"]) <= _TILE_MAX_PX and not page.runs_by_box.get(parent)):
                return parent
        return ident
    return None


def _icon_tiles(page: _Page, members_max: float, tile_min: float, ratio_min: float) -> Iterable[_Obs]:
    seen: set[tuple[str, ...]] = set()
    for group in page.derived.get("sibling_groups") or ():
        members = [m for m in group["members"] if m in page.by_id]
        key = tuple(members)
        if len(members) <= members_max or key in seen:
            continue
        seen.add(key)
        tiles = [(m, _leading_tile(page, m)) for m in members]
        led = [(m, t) for m, t in tiles if t is not None]
        if len(led) < _TILE_SHARE * len(members):
            continue
        sizes, ratios = [], []
        for m, t in led:
            r = page.rect(t)
            if not _TILE_SHAPE[0] <= r["w"] / max(r["h"], 1) <= _TILE_SHAPE[1]:
                break
            run = _first_run(page, m)
            sizes.append(min(r["w"], r["h"]))
            ratios.append(min(r["w"], r["h"]) / (run["size_px"] if run and run.get("size_px") else 16))
        else:
            if sizes and min(sizes) >= tile_min and min(ratios) >= ratio_min:
                run = _first_run(page, led[0][0])
                yield _Obs(("tiles", members[0]),
                           f"{len(members)} sibling items each open with an icon tile {round(min(sizes))} px across above "
                           f"text set at {round(run['size_px']) if run and run.get('size_px') else 16} px",
                           box=led[0][1], refs=tuple(t for _, t in led[:4]))


@detector("icon-tile-cards", layers=("render",))
def icon_tile_cards(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _desktop(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    members_max, tile_min = _bound(det, "repeats_max"), _bound(det, "tile_px_min")
    ratio_min = _bound(det, "tile_to_text_min")
    if members_max is None or tile_min is None or ratio_min is None:
        return _no_bound("repeats_max, tile_px_min, and tile_to_text_min")
    measured = [p for p in pages if p.derived.get("sibling_groups") is not None]
    if not measured:
        return Result(skipped="the extract has no derived.sibling_groups")
    return Result(hits=_merge(measured, lambda page: _icon_tiles(page, members_max, tile_min, ratio_min)))


# ---------------------------------------------------------------- section blocks

def _blocks(page: _Page) -> list[dict]:
    """The page's sections, each the widest box around one heading that holds no other section heading: the
    outermost cards inside it, their widest row, and whether it holds a picture. Headings inside cards, and the
    first display heading when the page opens with one, are not section headings."""
    cached = page.memo.get("hierarchy.blocks")
    if cached is not None:
        return cached
    heads: list[str] = []
    for run in page.runs:
        box = page.by_id.get(run["box"])
        if box is None or run.get("type_role") not in _HEADING_RUNS or (run.get("size_px") or 0) < 20:
            continue
        ident = next((a for a in (run["box"], *page.ancestors(run["box"])) if page.by_id[a]["role"] == "heading"), run["box"])
        if ident not in heads and not any(page.card_like(a) for a in page.ancestors(ident)):
            heads.append(ident)
    heads.sort(key=lambda i: (page.rect(i)["y"], page.rect(i)["x"]))
    blocks = []
    for head in heads:
        block = head
        for ancestor in page.ancestors(head):
            inside = set(page.descendants(ancestor))
            if any(other != head and other in inside for other in heads):
                break
            block = ancestor
        inside = set(page.descendants(block))
        cards = [i for i in inside if page.card_like(i) and page.rect(i)["w"] < _BAND_WIDE * page.width
                 and not any(a in inside and page.card_like(a) for a in page.ancestors(i))]
        rows: dict[int, int] = {}
        for i in cards:
            row = round(page.rect(i)["y"] / _ROW_TOLERANCE)
            rows[row] = rows.get(row, 0) + 1
        widest = max(rows.values(), default=0)
        picture = any(page.by_id[i]["role"] == "media" and page.rect(i)["w"] > _ICON_MEDIA_PX for i in inside)
        shape = "row3" if widest >= 3 else "row2" if widest == 2 else "bare"
        blocks.append({"head": head, "block": block, "cards": len(cards), "widest": widest, "shape": shape,
                       "picture": picture, "top": page.rect(head)["y"]})
    page.memo["hierarchy.blocks"] = blocks
    return blocks


# ---------------------------------------------------------------- section-shapes

def _repeated_shapes(page: _Page, repeats_max: float) -> Iterable[_Obs]:
    blocks = _blocks(page)
    run: list[dict] = []
    for block in [*blocks, None]:
        if block is not None and block["shape"] == "row3" and not block["picture"]:
            run.append(block)
            continue
        if len(run) > repeats_max:
            yield _Obs(("shapes", run[0]["head"]),
                       f"{len(run)} consecutive sections are a heading over a row of three or more cards "
                       f"({', '.join(str(b['widest']) for b in run)} across)",
                       box=run[0]["head"], refs=tuple(b["head"] for b in run))
        run = []


@detector("section-shapes", layers=("render",))
def section_shapes(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _desktop(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    repeats_max = _bound(det, "repeats_max")
    if repeats_max is None:
        return _no_bound("repeats_max")
    measured = [p for p in pages if p.has_style()]
    if not measured:
        return Result(skipped="boxes carry no style, so card boundaries cannot be read")
    return Result(hits=_merge(measured, lambda page: _repeated_shapes(page, repeats_max)))


# ---------------------------------------------------------------- section-rhythm

def _field(page: _Page) -> list[float] | None:
    fields = [e for e in page.vp.get("palette") or [] if e.get("role_guess") == "field"]
    return max(fields, key=lambda e: e["share"])["oklch"] if fields else None


def _tinted_bands(page: _Page, field: list[float], de_min: float) -> list[str]:
    bands = []
    for ident in page.pre_order():
        box, r = page.by_id[ident], page.rect(ident)
        background = (box.get("style") or {}).get("background")
        if (background is None or (len(background) == 4 and background[3] < 0.5) or r["w"] < _BAND_WIDE * page.width
                or r["h"] < _BAND_TALL or delta_e_ok(background, field) < de_min):
            continue
        bands.append(ident)
    return bands


def _flat_rhythm(page: _Page, sections_min: float, screens_min: float, same_min: float, de_min: float) -> Iterable[_Obs]:
    blocks = _blocks(page)
    length = max((b["rect"]["y"] + b["rect"]["h"] for b in page.boxes), default=0.0)
    field = _field(page)
    if len(blocks) < sections_min or field is None or length < screens_min * page.height:
        return
    if _tinted_bands(page, field, de_min):
        return
    pairs = list(zip(blocks, blocks[1:]))
    same = sum(1 for a, b in pairs if (a["shape"], a["picture"]) == (b["shape"], b["picture"]))
    if pairs and same / len(pairs) >= same_min:
        yield _Obs(("rhythm", "page"),
                   f"{len(blocks)} sections on one background, and {same} of {_count(len(pairs), 'neighbour pair')} "
                   f"share a shape, in a {length / page.height:.1f}-screen page")


@detector("section-rhythm", layers=("render",))
def section_rhythm(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _desktop(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    keys = ("sections_min", "screens_min", "same_shape_share_min", "band_delta_e_min")
    bound = {key: _bound(det, key) for key in keys}
    if any(value is None for value in bound.values()):
        return _no_bound(", ".join(keys))
    measured = [p for p in pages if p.has_style() and p.vp.get("palette")]
    if not measured:
        return Result(skipped="boxes carry no style or the capture no palette, so the page's backgrounds cannot be read")
    return Result(hits=_merge(measured, lambda page: _flat_rhythm(
        page, bound["sections_min"], bound["screens_min"], bound["same_shape_share_min"], bound["band_delta_e_min"])))


# ---------------------------------------------------------------- metric-tiles

def _metric_tiles(page: _Page, tiles_min: float) -> Iterable[_Obs]:
    """Tiles that each hold one big number and a label or two, side by side in the first viewport."""
    numbers = [r for r in page.runs if r["box"] in page.by_id and _NUMBER.match(r.get("text", "").strip())
               and (r.get("size_px") or 0) >= 20 and page.rect(r["box"])["y"] < page.height
               and not any(page.by_id[a]["role"] == "nav" for a in page.ancestors(r["box"]))]
    number_ids = {id(r) for r in numbers}
    tiles = []
    for number in numbers:
        tile = None
        for ident in (number["box"], *page.ancestors(number["box"])):
            runs = page.subtree_runs(ident)
            if any(id(r) in number_ids and r is not number for r in runs) or page.rect(ident)["w"] > 0.4 * page.width:
                break
            if len(runs) > 1:
                tile = ident
        if tile is None:
            continue
        others = [r for r in page.subtree_runs(tile) if r is not number]
        if (len(others) + 1 > _TILE_RUNS_MAX
                or number["size_px"] < _TILE_NUMBER_RATIO * max(r["size_px"] for r in others)):
            continue
        tiles.append((tile, number))
    rows: dict[int, list[tuple[str, dict]]] = {}
    for tile, number in tiles:
        rows.setdefault(round(page.rect(tile)["y"] / _ROW_TOLERANCE), []).append((tile, number))
    for row in rows.values():
        distinct = {t: n for t, n in row}
        if len(distinct) >= tiles_min:
            labels = ", ".join(n["text"].strip() for n in list(distinct.values())[:4])
            yield _Obs(("metrics", next(iter(distinct))),
                       f"{len(distinct)} tiles side by side in the first view each hold one big number ({labels})",
                       box=next(iter(distinct)), refs=tuple(list(distinct)[:4]))


@detector("metric-tiles", layers=("render",))
def metric_tiles(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    pages = _desktop(ctx)
    if isinstance(pages, str):
        return Result(skipped=pages)
    tiles_min = _bound(det, "tiles_min")
    if tiles_min is None:
        return _no_bound("tiles_min")
    return Result(hits=_merge(pages, lambda page: _metric_tiles(page, tiles_min)))
