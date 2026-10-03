"""Full-page screenshot palette and painted-pixel role attribution."""
from __future__ import annotations

import math
import re

import numpy as np
from PIL import Image

from lapis_design.render.color import from_oklab


# Equal pixel votes break ties in this fixed order. Rects are painted in browser
# paint order; rendered glyph ranges are applied last over their containing fills.
_ROLES = ("field", "unknown", "identity", "status", "data", "content", "interaction", "foreground")
_ROLE_INDEX = {role: index for index, role in enumerate(_ROLES)}


# A chart is named by a whole word of the box's own class or id, split at whitespace, hyphens, underscores,
# and case changes: `bar-chart` and `lineChart` name one; `paragraph`, `hero-graphic`, and
# `MuiTypography-root` do not.
_CHART_WORDS = frozenset(("chart", "graph", "plot", "sparkline"))
_WORD_BREAK = re.compile(r"[\s_-]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
# An `svg` or `canvas` of at least this many CSS px on its shorter side is a chart when it is presented as
# one (a role of img, figure, or graphics-document and an accessible name that says chart) or, for an `svg`,
# is drawn as one (three sibling shapes of one type and two text labels).
_CHART_MIN_PX = 48
_CHART_ROLES = frozenset(("img", "figure", "graphics-document"))
_CHART_NAME = re.compile(r"\b(?:chart|graph|plot|visuali[sz]ation)s?\b|차트|그래프", re.I)
_CHART_JS = r"""ids => {
  const shapes = new Set(['rect','circle','ellipse','line','path','polyline','polygon']);
  const result = {};
  for (const id of ids) {
    const element = document.querySelector('[data-lapis-box="' + id + '"]');
    if (!element) continue;
    const labelled = (element.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean)
      .map(ref => document.getElementById(ref)?.textContent || '').join(' ');
    const title = element.localName === 'svg'
      ? [...element.children].find(child => child.localName === 'title')?.textContent || '' : '';
    let siblings = 0;
    for (const parent of [element, ...element.querySelectorAll('*')]) {
      const counts = {};
      for (const child of parent.children)
        if (shapes.has(child.localName)) counts[child.localName] = (counts[child.localName] || 0) + 1;
      siblings = Math.max(siblings, ...Object.values(counts));
    }
    result[id] = {
      name: [element.getAttribute('aria-label'), labelled, title, element.getAttribute('title')]
        .filter(Boolean).join(' '),
      siblings, labels: [...element.querySelectorAll('text')].filter(text => text.textContent.trim()).length};
  }
  return result;
}"""

_LINEAR = np.array([v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
                    for v in np.arange(256) / 255], dtype=np.float32)


def _lab(rgb: np.ndarray) -> np.ndarray:
    r, g, b = np.moveaxis(rgb, -1, 0)
    l = np.cbrt(.4122214708*r + .5363325363*g + .0514459929*b)
    m = np.cbrt(.2119034982*r + .6806995451*g + .1073969566*b)
    s = np.cbrt(.0883024619*r + .2817188376*g + .6299787005*b)
    return np.stack((.2104542553*l + .7936177850*m - .0040720468*s,
                     1.9779984951*l - 2.4285922050*m + .4505937099*s,
                     .0259040371*l + .7827717662*m - .8086757660*s), axis=-1)


def _named_chart(attrs: dict) -> bool:
    return any(word.lower() in _CHART_WORDS
               for key in ("class", "id") for word in _WORD_BREAK.split(str(attrs.get(key, ""))))


def _chart_boxes(view, boxes: list[dict]) -> set[str]:
    """Ids of the `svg` and `canvas` boxes that read as charts by role and name or by structure."""
    candidates = [box["id"] for box in boxes if view.elements[box["id"]]["tag"] in ("svg", "canvas")
                  and min(box["rect"]["w"], box["rect"]["h"]) >= _CHART_MIN_PX]
    if not candidates:
        return set()
    found = set()
    for ident, data in view.page.evaluate(_CHART_JS, candidates).items():
        meta = view.elements[ident]
        role = str(meta["attrs"].get("role", "")).split()
        presented = bool(role) and role[0].lower() in _CHART_ROLES and bool(_CHART_NAME.search(data["name"]))
        drawn = meta["tag"] == "svg" and data["siblings"] >= 3 and data["labels"] >= 2
        if presented or drawn:
            found.add(ident)
    return found


def _role(box: dict, meta: dict, charts: frozenset[str] | set[str] = frozenset()) -> str:
    attrs = meta["attrs"]
    hint = " ".join(str(attrs.get(k, "")) for k in ("class", "id", "role")).lower()
    role = box["role"]
    if role in ("button", "link", "input"):
        return "interaction"
    if any(word in hint for word in ("alert", "badge", "error", "success", "warning", "status")):
        return "status"
    if _named_chart(attrs) or meta["tag"] in ("td", "th") or box["id"] in charts:
        return "data"
    if role == "media" or "media" in box:
        return "content"
    if role == "icon" or any(word in hint for word in ("logo", "brand", "accent")):
        return "identity"
    if role in ("heading", "text"):
        return "foreground"
    if role in ("section", "card", "nav", "dialog", "list", "other"):
        return "field"
    return "unknown"


def _mask(view, vp: dict, shape: tuple[int, int], screenshot_size: tuple[int, int],
          painted_lab: np.ndarray) -> np.ndarray:
    height, width = shape
    source_width, source_height = screenshot_size
    sx, sy = width / source_width * view.config["dpr"], height / source_height * view.config["dpr"]
    roles = np.zeros((height, width), dtype=np.uint8)
    boxes = sorted((b for b in vp["boxes"] if "paint_order" in b), key=lambda b: b["paint_order"])

    def paint(rect, role, icon_ink=False):
        x = max(0, math.floor(rect["x"] * sx))
        y = max(0, math.floor(rect["y"] * sy))
        right = min(width, math.ceil((rect["x"] + rect["w"]) * sx))
        bottom = min(height, math.ceil((rect["y"] + rect["h"]) * sy))
        if right <= x or bottom <= y:
            return
        destination = roles[y:bottom, x:right]
        if icon_ink:
            pixels = painted_lab[y:bottom, x:right]
            ground = np.median(pixels.reshape(-1, 3), axis=0)
            destination[np.linalg.norm(pixels - ground, axis=2) > .04] = _ROLE_INDEX[role]
        else:
            destination[:] = _ROLE_INDEX[role]

    by_id = {box["id"]: box for box in vp["boxes"]}
    charts = _chart_boxes(view, boxes)
    for box in boxes:
        role = _role(box, view.elements[box["id"]], charts)
        style = box["style"]
        if role == "icon" or box["role"] == "icon":
            parent = by_id.get(box["parent"])
            while parent and parent["role"] not in ("button", "link", "input"):
                parent = by_id.get(parent["parent"])
            if parent:
                role = "interaction"
        # Transparent semantic wrappers carry no painted pixels of their own.
        if role != "foreground" and (style.get("background") or style.get("gradients") or "media" in box):
            paint(box["rect"], role)
        elif box["role"] == "icon":
            paint(box["rect"], role, icon_ink=True)

    # One DOM read obtains the rendered Range rects for all text nodes. Each run has
    # already been assigned its nearest captured ancestor by the core extractor.
    rects = view.page.evaluate("""() => {
      const result = [];
      const walker = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_TEXT);
      for (let n; n = walker.nextNode();) {
        if (!n.textContent.trim()) continue;
        const box = n.parentElement.closest('[data-lapis-box]');
        if (!box) continue;
        const range = document.createRange(); range.selectNodeContents(n);
        for (const r of range.getClientRects()) if (r.width && r.height)
          result.push({id:box.getAttribute('data-lapis-box'), x:r.x+scrollX,
                       y:r.y+scrollY,w:r.width,h:r.height});
      }
      return result;
    }""")
    glyph_roles = {}
    for run in vp["text"]:
        box = by_id[run["box"]]
        chain = box
        while chain and chain["role"] not in ("button", "link", "input"):
            chain = by_id.get(chain["parent"])
        if chain:
            role = "interaction"
        elif box["role"] == "heading" and len(run.get("color", ())) >= 3 and run["color"][1] > .05:
            role = "identity"
        else:
            classified = _role(box, view.elements[box["id"]], charts)
            role = classified if classified in ("status", "data", "identity") else "foreground"
        glyph_roles[box["id"]] = role
    for rect in rects:
        paint(rect, glyph_roles.get(rect["id"], "foreground"))
    return roles


def apply(view, vp: dict, image: Image.Image) -> None:
    target_width = min(256, image.width)
    target_height = max(1, round(image.height * target_width / image.width))
    # Integrate each sRGB-decoded channel separately: retaining a full-page float
    # RGB image would multiply the working set on long pages.
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    channels = []
    for channel in rgb.split():
        linear = _LINEAR[np.asarray(channel)]
        channels.append(np.asarray(Image.fromarray(linear, "F").resize(
            (target_width, target_height), Image.Resampling.BOX)))
    reduced = np.stack(channels, axis=-1)
    lab = _lab(reduced).reshape(-1, 3)
    roles = _mask(view, vp, (target_height, target_width), image.size,
                  lab.reshape(target_height, target_width, 3)).reshape(-1)
    chroma = np.linalg.norm(lab[:, 1:], axis=1)
    white = (lab[:, 0] >= .995) & (chroma <= .002)
    black = (lab[:, 0] <= .005) & (chroma <= .002)
    normal = ~(white | black)
    results = []
    count = len(lab)

    def entry(indices, exact=False):
        center = lab[indices].mean(axis=0)
        color = from_oklab(*map(float, center), 1)
        votes = np.bincount(roles[indices], minlength=len(_ROLES))
        item = {"oklch": color, "share": round(int(indices.sum()) / count, 4),
                "role_guess": _ROLES[int(votes.argmax())]}
        if exact:
            item["exact"] = True
        results.append(item)

    for indices in (white, black):
        if indices.any():
            entry(indices, True)
    if normal.any():
        points = lab[normal]
        # 0.02 OKLab grid: frequency then lexicographic bin coordinates break ties.
        bins = np.floor(points / .02 + .5).astype(np.int32)
        quantized, frequency = np.unique(bins, axis=0, return_counts=True)
        order = sorted(range(len(frequency)), key=lambda i: (-frequency[i], *quantized[i]))
        centers = quantized[order[:8]].astype(np.float64) * .02
        assignments = np.full(len(points), -1, dtype=np.int16)
        for _ in range(50):
            nearest = np.argmin(((points[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2), axis=1)
            if np.array_equal(assignments, nearest):
                break
            assignments = nearest
            for i in range(len(centers)):
                if (nearest == i).any():
                    centers[i] = points[nearest == i].mean(axis=0)
        locations = np.flatnonzero(normal)
        for i in range(len(centers)):
            if (assignments == i).any():
                membership = np.zeros(count, dtype=bool)
                membership[locations[assignments == i]] = True
                entry(membership)
    vp["palette"] = sorted(results, key=lambda item: (-item["share"], item["oklch"]))
