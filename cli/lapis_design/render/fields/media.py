"""Icon identity and media pixels, provenance, intrinsic sizing, and overlays."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlsplit

import numpy as np
from PIL import Image

from lapis_design.render.color import to_oklch
from lapis_design.render.fields.paint import split_top_level

_PLACEHOLDER = re.compile(r"(?:^|[./-])(?:placehold(?:\.co|\.it)?|placeholder(?:\.com)?|"
                          r"picsum\.photos|lorem(?:flickr|picsum|pixel)|dummyimage\.com)(?:[./-]|$)", re.I)
_TEMPLATE = re.compile(r"(?:\{\{|\{%|\$\{|<%|\bimage[_-]?here\b)", re.I)
_COS = np.cos(np.pi * (np.arange(8)[:, None] * (np.arange(32)[None, :] + .5)) / 32)


def _phash(image: Image.Image, rect: dict, dpr: float) -> str | None:
    left = max(0, round(rect["x"] * dpr))
    top = max(0, round(rect["y"] * dpr))
    right = min(image.width, round((rect["x"] + rect["w"]) * dpr))
    bottom = min(image.height, round((rect["y"] + rect["h"]) * dpr))
    if right <= left or bottom <= top:
        return None
    # Deliberately hash the painted screenshot region of the displayed image, not
    # its original file: object-fit, clipping, color transforms and overlays count.
    pixels = np.asarray(image.crop((left, top, right, bottom)).convert("L").resize(
        (32, 32), Image.Resampling.LANCZOS), dtype=np.float64)
    coefficients = _COS @ pixels @ _COS.T
    low = coefficients[:8, :8].ravel()
    median = np.median(low[1:])
    return f"{sum(int(v > median) << (63 - i) for i, v in enumerate(low)):016x}"


def _library(data: dict) -> str | None:
    classes = data.get("class", "").split()
    for cls in classes:
        for prefix, name in (("lucide-", "lucide"), ("heroicon-", "heroicons"),
                             ("fa-", "font-awesome"), ("fas", "font-awesome"),
                             ("far", "font-awesome"), ("material-icons", "material-icons"),
                             ("bi-", "bootstrap-icons"), ("ph-", "phosphor"),
                             ("iconify", "iconify"), ("mdi-", "material-design-icons")):
            if cls == prefix or cls.startswith(prefix):
                return name
    if sprite := data.get("sprite"):
        ident = sprite.split("#", 1)[-1]
        prefix = ident.split("-", 1)[0] if "-" in ident else None
        return prefix if prefix not in ("icon", "symbol", "svg", None) else None
    module = data.get("module", "")
    for marker, name in (("lucide", "lucide"), ("heroicon", "heroicons"),
                         ("fortawesome", "font-awesome"), ("iconify", "iconify")):
        if marker in module.lower():
            return name
    return None


def _icon(data: dict, kind: str) -> dict:
    result = {"kind": kind, "library": _library(data)}
    if kind == "svg":
        if data.get("grid") is not None:
            result["grid_px"] = round(data["grid"], 2)
        if data.get("stroke") is not None:
            result["stroke_px"] = round(data["stroke"], 2)
    elif kind in ("emoji", "icon-font") and data.get("glyph"):
        glyph = data["glyph"].strip()
        symbols = [char for char in glyph if unicodedata.category(char).startswith("S") or
                   ord(char) in (0xfe0e, 0xfe0f, 0x200d)]
        if symbols:
            result["glyph"] = " ".join(f"U+{ord(char):04X}" for char in symbols)
    return result


def _intersect(one: dict, two: dict) -> tuple[float, float, float, float] | None:
    left, top = max(one["x"], two["x"]), max(one["y"], two["y"])
    right, bottom = min(one["x"] + one["w"], two["x"] + two["w"]), min(one["y"] + one["h"], two["y"] + two["h"])
    return (left, top, right, bottom) if right > left and bottom > top else None


def _overlays(box: dict, boxes: list[dict], styles: dict) -> dict | None:
    layers = []
    # CSS lists paint from front to back: gradients before the first url() cover
    # that image even though they share its box and paint_order.
    background_layers = split_top_level(styles[box["id"]]["backgroundImage"])
    image_index = next((i for i, layer in enumerate(background_layers) if "url(" in layer), None)
    if image_index is not None:
        above = [layer for layer in background_layers[:image_index] if "-gradient(" in layer]
        painted = [gradient for gradient in box["style"].get("gradients", [])
                   if gradient["target"] == "background"]
        for gradient in painted[:len(above)]:
            alpha = max(stop["oklch"][3] if len(stop["oklch"]) == 4 else 1
                        for stop in gradient["stops"]) * float(styles[box["id"]]["opacity"])
            if alpha:
                r = box["rect"]
                layers.append(((r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]), alpha))
    for candidate in boxes:
        if candidate["paint_order"] <= box["paint_order"] or candidate["id"] == box["id"]:
            continue
        if not (intersection := _intersect(box["rect"], candidate["rect"])):
            continue
        css = styles[candidate["id"]]
        if css["backgroundColor"] not in ("transparent", "rgba(0, 0, 0, 0)"):
            color = to_oklch(css["backgroundColor"])
            alpha = (color[3] if color and len(color) == 4 else 1) if color else 0
        else:
            alpha = 0
        if "gradients" in candidate["style"]:
            for gradient in candidate["style"]["gradients"]:
                if gradient["target"] in ("background", "border"):
                    alpha = max(alpha, *(stop["oklch"][3] if len(stop["oklch"]) == 4 else 1
                                         for stop in gradient["stops"]))
        alpha *= float(css["opacity"])
        if alpha > 0:
            layers.append((intersection, alpha))
    if not layers:
        return None
    # Sweep cell boundaries to avoid double-counting area; overlapping translucent
    # layers compound opacity rather than taking a simple maximum.
    edges = sorted({edge for (left, _, right, _), _ in layers for edge in (left, right)})
    area, alpha_max = 0., 0.
    for left, right in zip(edges, edges[1:]):
        active = [(rect, alpha) for rect, alpha in layers if rect[0] < right and rect[2] > left]
        heights = sorted({edge for (_, top, _, bottom), _ in active for edge in (top, bottom)})
        for top, bottom in zip(heights, heights[1:]):
            opacity_left = 1.
            for (_, y1, _, y2), alpha in active:
                if y1 < bottom and y2 > top:
                    opacity_left *= 1 - alpha
            if opacity_left < 1:
                area += (right-left) * (bottom-top)
                alpha_max = max(alpha_max, 1-opacity_left)
    image_area = box["rect"]["w"] * box["rect"]["h"]
    return {"alpha_max": round(min(1, alpha_max), 4),
            "coverage": round(min(1, area / image_area), 4)} if image_area else None


def apply(view, vp: dict, styles: dict, screenshot: Image.Image) -> None:
    info = view.page.evaluate("""async () => {
      const entries = {};
      const choices = [];
      for (const el of document.querySelectorAll('[data-lapis-box]')) {
        const id = el.getAttribute('data-lapis-box'), tag = el.localName;
        const image = tag === 'picture' ? el.querySelector('img') : el;
        const svg = tag === 'svg' ? el : el.querySelector('svg');
        const use = svg?.querySelector('use');
        const path = svg?.querySelector('path, line, circle, rect, polygon, polyline');
        const fiber = svg && svg[Object.keys(svg).find(k => /reactFiber|reactInternalInstance/.test(k))];
        const module = fiber?.elementType?.displayName || fiber?.elementType?.name || '';
        const bg = getComputedStyle(el).backgroundImage;
        const url = /url\\(["']?([^"')]+)["']?\\)/.exec(bg)?.[1] || null;
        const source = image.currentSrc || image.getAttribute('src') ||
                       image.getAttribute('data-src') || image.getAttribute('data-placeholder-url') || null;
        entries[id] = {tag, class:el.getAttribute('class') || svg?.getAttribute('class') || '',
          sprite:use?.getAttribute('href') || use?.getAttribute('xlink:href') || null,
          module, glyph:el.innerText || el.textContent || '',
          svg:!!svg, iconImage:!!el.querySelector('img'),
          iconOnly:tag==='button' &&
            !!(svg || el.querySelector('img') || /[\\p{S}\\p{Extended_Pictographic}]/u.test(el.innerText || '')) &&
            !/[\\p{L}\\p{N}]/u.test(el.innerText || ''),
          grid:svg?.viewBox?.baseVal ? Math.max(svg.viewBox.baseVal.width, svg.viewBox.baseVal.height) || null : null,
          stroke:path && parseFloat(getComputedStyle(path).strokeWidth) || null,
          source, url, alt:image.hasAttribute('alt') ? image.getAttribute('alt') : null,
          hidden:el.getAttribute('aria-hidden')==='true' || image.getAttribute('aria-hidden')==='true',
          natural_w:image.naturalWidth || image.videoWidth || (tag==='canvas' ? image.width : 0) || 0,
          natural_h:image.naturalHeight || image.videoHeight || (tag==='canvas' ? image.height : 0) || 0,
          intrinsic:image.hasAttribute('width') && image.hasAttribute('height') ||
            getComputedStyle(image).aspectRatio!=='auto',
          complete:image.complete ?? (tag==='video' ? image.readyState>=2 : true)};
        if (url && !/placehold|placeholder|lorem|picsum|dummyimage|\\{\\{|\\$\\{/.test(url))
          choices.push([id, url]);
      }
      // CSS images were already requested during navigation. The same URL hits the browser
      // cache; decode supplies actual success and natural dimensions rather than guessing.
      await Promise.all(choices.map(async ([id,url]) => {
        const image = new Image(); image.src = url;
        try { await image.decode(); entries[id].cssLoaded=true;
              entries[id].cssW=image.naturalWidth; entries[id].cssH=image.naturalHeight; }
        catch (_) { entries[id].cssLoaded=false; }
      }));
      return entries;
    }""")
    page_host = urlsplit(view.page.url).hostname
    for box in vp["boxes"]:
        data = info[box["id"]]
        role = box["role"]
        tag = data["tag"]
        icon = role == "icon" or (role == "button" and data["iconOnly"])
        if icon:
            if data["svg"]:
                kind = "svg"
            elif data["iconImage"] or tag == "img":
                kind = "image"
            elif any(unicodedata.category(c).startswith("S") for c in data["glyph"]):
                kind = "emoji"
            else:
                kind = "icon-font"
            box["icon"] = _icon(data, kind)
        if role != "media" and not data["url"]:
            continue
        kind = ("css-background" if data["url"] else tag if tag in ("img", "picture", "video", "canvas", "svg")
                else "css-background" if styles[box["id"]]["backgroundImage"] != "none" else None)
        if kind is None:
            continue
        source = data["url"] if kind == "css-background" else data["source"]
        parsed = urlsplit(source) if source and not _TEMPLATE.search(source) else None
        hostname = parsed.hostname if parsed else None
        if parsed and hostname == page_host:
            for _, value in parse_qsl(parsed.query):
                try:
                    inner = urlsplit(value)
                    inner_host = inner.hostname
                except ValueError:
                    continue
                if inner.scheme in ("http", "https") and inner_host:
                    hostname = inner_host
                    break
        placeholder = bool(source and (_PLACEHOLDER.search(source) or _TEMPLATE.search(source)))
        loaded = bool(data.get("cssLoaded")) if kind == "css-background" else (
            bool(data["complete"] and data["natural_w"] and data["natural_h"]) if kind in ("img", "picture", "video")
            else bool(data["natural_w"] and data["natural_h"]) if kind == "canvas" else True)
        media = {"kind": kind, "loaded": loaded, "host": hostname,
                 "intrinsic_size": bool(data["intrinsic"]), "placeholder": placeholder,
                 "decorative": data["alt"] == "" or data["hidden"]}
        if kind in ("img", "picture"):
            media["alt"] = data["alt"]
        if loaded:
            width = data.get("cssW") if kind == "css-background" else data["natural_w"]
            height = data.get("cssH") if kind == "css-background" else data["natural_h"]
            if width and height:
                media.update(natural_w=width, natural_h=height)
            if phash := _phash(screenshot, box["rect"], view.config["dpr"]):
                media["phash"] = phash
        if overlay := _overlays(box, vp["boxes"], styles):
            media["overlay"] = overlay
        box["media"] = media
