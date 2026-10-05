"""Computed CSS paint layers, filter effects, patterns, and clip geometry."""
from __future__ import annotations

import math
import re

import numpy as np
from PIL import Image
from lapis_design.render import detached
from lapis_design.render.color import to_oklch

_NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:e[-+]?\d+)?"
_LENGTH = re.compile(rf"({_NUMBER})(px|%)?", re.I)
_COLOR = re.compile(r"(?:rgba?|hsla?|oklch|oklab|lch|lab|color)\([^)]*\)|#[\da-fA-F]{3,8}|\btransparent\b", re.I)
_FUNCTION = re.compile(r"([\w-]+)\(")


def split_top_level(value: str, separator=",") -> list[str]:
    """Split a CSS list without splitting function arguments or quoted URLs."""
    parts, start, depth, quote = [], 0, 0, None
    for index, char in enumerate(value):
        if quote:
            if char == quote and (index == 0 or value[index - 1] != "\\"):
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == separator and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return parts


def _functions(value: str):
    for match in _FUNCTION.finditer(value):
        depth = 1
        for end in range(match.end(), len(value)):
            if value[end] == "(":
                depth += 1
            elif value[end] == ")":
                depth -= 1
                if not depth:
                    yield match.group(1).lower(), value[match.end():end]
                    break


def _length(value: str, reference: float = 1) -> float | None:
    match = _LENGTH.fullmatch(value.strip())
    if not match:
        return None
    amount = float(match.group(1))
    return amount * reference / 100 if match.group(2) == "%" else amount


def _color(value: str) -> list[float] | None:
    if value.lower() == "transparent":
        return [0, 0, 0, 0]
    if re.search(r"[,/]\s*0(?:\.0+)?\s*\)$", value):
        opaque = re.sub(r"([,/]\s*)0(?:\.0+)?\s*\)$", r"\g<1>0.0001)", value)
        color = to_oklch(opaque)
        if color:
            color[-1] = 0
        return color
    return to_oklch(value) if value else None


def _shadows(value: str, source: str) -> list[dict]:
    if value == "none":
        return []
    shadows = []
    for layer in split_top_level(value):
        colors = list(_COLOR.finditer(layer))
        color = _color(colors[-1].group()) if colors else None
        if not color:
            continue
        lengths = [_length(part) for part in re.findall(rf"{_NUMBER}(?:px)?", _COLOR.sub("", layer))]
        lengths = [number for number in lengths if number is not None]
        if len(lengths) < 2:
            continue
        item = {"source": source, "offset_x": round(lengths[0], 2),
                "offset_y": round(lengths[1], 2), "blur_px": round(max(0, lengths[2]), 2) if len(lengths) > 2 else 0,
                "color": color}
        if source == "box-shadow":
            item["inset"] = bool(re.search(r"\binset\b", layer))
            item["spread_px"] = round(lengths[3], 2) if len(lengths) > 3 else 0
        shadows.append(item)
    return shadows


def _filter(value: str, name: str) -> float | None:
    return next((_length(contents) for kind, contents in _functions(value) if kind == name), None)


def _gradient(value: str, target: str, rect: dict, vp: dict, blur: float | None,
              others: list[dict], own: dict) -> list[dict]:
    result = []
    for layer in split_top_level(value):
        for name, inner in _functions(layer):
            match = re.fullmatch(r"(repeating-)?(linear|radial|conic)-gradient", name)
            if not match:
                continue
            repeating, kind = match.groups()
            parts = split_top_level(inner)
            heading = parts[0]
            angle = None
            if kind == "linear":
                direction = re.search(rf"({_NUMBER})deg", heading)
                if direction:
                    angle = float(direction.group(1)) % 360
                elif heading.startswith("to "):
                    directions = heading[3:].split()
                    vertical = 0 if "top" in directions else 180 if "bottom" in directions else None
                    horizontal = 90 if "right" in directions else 270 if "left" in directions else None
                    if vertical is not None and horizontal is not None:
                        corner = math.degrees(math.atan2(rect["w"], rect["h"]))
                        angle = ((corner if horizontal == 90 else 360-corner) if vertical == 0
                                 else (180-corner if horizontal == 90 else 180+corner))
                    else:
                        angle = vertical if vertical is not None else horizontal
                else:
                    angle = 180
                line = abs(rect["w"] * math.sin(math.radians(angle))) + abs(rect["h"] * math.cos(math.radians(angle)))
            elif kind == "radial":
                line = math.hypot(rect["w"] / 2, rect["h"] / 2)
            else:
                direction = re.search(rf"from\s+({_NUMBER})deg", heading)
                if direction:
                    angle = float(direction.group(1)) % 360
                line = 360
            stops = []
            for part in parts:
                color_match = _COLOR.search(part)
                if not color_match or not (color := _color(color_match.group())):
                    continue
                remainder = part[color_match.end():].strip()
                positions = re.findall(rf"{_NUMBER}(?:px|%|deg|turn)?", remainder)
                for position in (positions[:2] if positions else (None,)):
                    stop = {"oklch": color}
                    if position:
                        if position.endswith("turn") and kind == "conic":
                            stop["at"] = round(float(position[:-4]), 4)
                        elif position.endswith("deg") and kind == "conic":
                            stop["at"] = round(float(position[:-3]) / 360, 4)
                        elif (px := _length(position, line)) is not None and line:
                            stop["at"] = round(px / line, 4)
                    stops.append(stop)
            if len(stops) < 2:
                continue
            # CSS fills unspecified endpoints and interpolates intermediate stops evenly.
            positions = [stop.get("at") for stop in stops]
            positions[0] = 0 if positions[0] is None else positions[0]
            positions[-1] = 1 if positions[-1] is None else positions[-1]
            known = [i for i, position in enumerate(positions) if position is not None]
            for start, end in zip(known, known[1:]):
                for i in range(start + 1, end):
                    positions[i] = positions[start] + (positions[end] - positions[start]) * (i - start) / (end - start)
            for stop, position in zip(stops, positions):
                stop["at"] = round(position, 4)
            page_area = vp["width"] * max(vp["height"], own["page_height"])
            x1, y1 = max(0, rect["x"]), max(0, rect["y"])
            x2 = min(vp["width"], rect["x"] + rect["w"])
            y2 = min(own["page_height"], rect["y"] + rect["h"])
            area = max(0, x2-x1) * max(0, y2-y1)
            first = max(0, x2-x1) * max(0, min(vp["height"], y2)-y1)
            if target == "text" and own.get("text_area") is not None:
                area = min(area, own["text_area"])
                first = min(first, own["text_first"])
            item = {"target": target, "kind": kind, "repeating": bool(repeating), "stops": stops,
                    "area_share": round(min(1, area / page_area), 4),
                    "first_viewport_share": round(min(1, first / (vp["width"] * vp["height"])), 4)}
            if angle is not None:
                item["angle_deg"] = round(angle, 4)
            if blur is not None:
                item["blur_px"] = round(blur, 2)
            above = ((max(0, min(rect["x"] + rect["w"], b["rect"]["x"]+b["rect"]["w"]) -
                          max(rect["x"], b["rect"]["x"])) *
                      max(0, min(rect["y"] + rect["h"], b["rect"]["y"]+b["rect"]["h"]) -
                          max(rect["y"], b["rect"]["y"])), b["id"])
                     for b in others if b.get("paint_order", -1) > own["paint_order"])
            if (best := max(above, default=(0, None)))[0] > 0:
                item["behind"] = best[1]
            result.append(item)
    return result


def _painted_lightness(image: Image.Image, rect: dict, dpr: float, max_px: int = 192):
    left, top = max(0, round(rect["x"] * dpr)), max(0, round(rect["y"] * dpr))
    right = min(image.width, left + max_px, round((rect["x"] + rect["w"]) * dpr))
    bottom = min(image.height, top + max_px, round((rect["y"] + rect["h"]) * dpr))
    if right - left < 8 or bottom - top < 8:
        return None
    rgb = np.asarray(image.crop((left, top, right, bottom)).convert("RGB"), dtype=np.float32) / 255
    rgb = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    l = np.cbrt(rgb @ np.array([.4122214708, .5363325363, .0514459929]))
    m = np.cbrt(rgb @ np.array([.2119034982, .6806995451, .1073969566]))
    s = np.cbrt(rgb @ np.array([.0883024619, .2817188376, .6299787005]))
    return .2104542553*l + .7936177850*m - .0040720468*s


def _noise(lightness: np.ndarray, periods: list[float], dpr: float) -> bool:
    # Aperiodic high-frequency marks, not a photographic edge or a tile that
    # visibly repeats at its CSS background-size.
    horizontal = np.abs(np.diff(lightness, axis=1)).mean()
    vertical = np.abs(np.diff(lightness, axis=0)).mean()
    if min(horizontal, vertical) < .035:
        return False
    for axis, period in enumerate(reversed(periods)):
        step = round(period * dpr)
        if 4 <= step < lightness.shape[axis] - 4:
            before, after = ((lightness[:-step], lightness[step:]) if axis == 0
                             else (lightness[:, :-step], lightness[:, step:]))
            if np.abs(before - after).mean() < .025:
                return False
    return not any(np.abs(lightness[:, :-step] - lightness[:, step:]).mean() < .025
                   and np.abs(lightness[:-step] - lightness[step:]).mean() < .025
                   for step in range(2, min(33, *lightness.shape)))


def _pattern(data: dict, rect: dict, image: Image.Image, dpr: float) -> dict | None:
    background = data["backgroundImage"]
    if background == "none" or not data["backgroundRepeat"].startswith("repeat"):
        return None
    size = split_top_level(data["backgroundSize"])
    dimensions = re.findall(rf"{_NUMBER}(?:px|%)?", size[0]) if size else []
    periods = [_length(value, rect[axis]) for value, axis in zip(dimensions, ("w", "h"))]
    if (len(periods) != 2 or not all(periods) or max(periods) > max(rect["w"], rect["h"])) and "url(" not in background:
        return None
    lightness = _painted_lightness(image, rect, dpr)
    if len(periods) != 2 or not all(periods) or max(periods) > max(rect["w"], rect["h"]):
        if "url(" in background and lightness is not None and _noise(lightness, periods, dpr):
            return {"kind": "noise", "contrast": round(float(np.percentile(lightness, 95) -
                                                              np.percentile(lightness, 5)), 4)}
        return None
    layers = split_top_level(background)
    radial = [layer for layer in layers if "radial-gradient(" in layer]
    linear = [layer for layer in layers if "linear-gradient(" in layer and "radial-gradient(" not in layer]
    fallback = "dot-grid" if radial and not linear else "stripes" if linear else "other"
    result = {"kind": fallback, "cell_px": round(min(periods), 2)}
    if lightness is None:
        return None
    contrast = float(np.percentile(lightness, 95) - np.percentile(lightness, 5))
    if "url(" in background and _noise(lightness, periods, dpr):
        result["kind"] = "noise"
        result["contrast"] = round(contrast, 4)
        return result
    ground = _color(data["backgroundColor"])
    base = ground[0] if ground and len(ground) < 4 else float(np.median(lightness))
    marks = np.abs(lightness - base) > max(.025, contrast * .3)
    if marks.any():
        result["contrast"] = round(float(np.percentile(np.abs(lightness[marks] - base), 90)), 4)
    x_line = marks.mean(axis=0).max() >= .8
    y_line = marks.mean(axis=1).max() >= .8
    if x_line and y_line:
        result["kind"] = "grid"
    elif x_line or y_line:
        result["kind"] = "stripes"
    elif radial and marks.mean() < .35:
        result["kind"] = "dot-grid"
    elif (marks.mean(axis=0).max() > .3 and marks.mean(axis=1).max() > .3
          and marks.mean() < .2):
        result["kind"] = "crosshair"
    elif "url(" in background and 0 < marks.mean() < .06:
        result["kind"] = "dot-grid"
    elif linear and len(linear) >= 2:
        result["kind"] = "crosshair"
    return result


def _clip(value: str, rect: dict) -> dict | None:
    if value == "none":
        return None
    name = value.split("(", 1)[0]
    if name not in ("polygon", "circle", "ellipse", "inset", "path"):
        return None
    result = {"kind": name}
    if name != "polygon":
        return result
    content = value[value.find("(")+1:-1]
    points = []
    for vertex in split_top_level(content):
        matches = re.findall(rf"{_NUMBER}(?:px|%)?", vertex)
        if len(matches) == 2:
            x, y = _length(matches[0], rect["w"]), _length(matches[1], rect["h"])
            if x is not None and y is not None:
                points.append((x, y))
    result["vertices"] = len(points)
    if len(points) < 4:
        result["jaggedness"] = 0
        return result
    turns = []
    for i in range(len(points)):
        a, b, c = points[i-1], points[i], points[(i+1) % len(points)]
        turn = (b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])
        turns.append(1 if turn > 1e-6 else -1 if turn < -1e-6 else 0)
    result["jaggedness"] = round(sum(turns[i] * turns[(i+1) % len(turns)] < 0
                                     for i in range(len(turns))) / len(turns), 4)
    return result


def apply(view, vp: dict, screenshot: Image.Image) -> dict[str, dict]:
    """Read all CSS properties in one browser call; return raw paint data for media."""
    records = view.page.evaluate("""viewportHeight => {
      const result = {};
      for (const el of document.querySelectorAll('[data-lapis-box]')) {
        const s = getComputedStyle(el), id = el.getAttribute('data-lapis-box');
        let textArea = null, textFirst = null;
        if (s.backgroundClip.split(',').includes('text') && s.backgroundImage.includes('-gradient(')) {
          const range = document.createRange(); range.selectNodeContents(el);
          textArea = 0; textFirst = 0;
          for (const r of range.getClientRects()) {
            textArea += r.width*r.height;
            textFirst += r.width*Math.max(0, Math.min(r.bottom+scrollY, viewportHeight)-Math.max(0,r.top+scrollY));
          }
        }
        result[id] = {boxShadow:s.boxShadow,textShadow:s.textShadow,filter:s.filter,
          backdropFilter:s.backdropFilter,backgroundImage:s.backgroundImage,
          backgroundColor:s.backgroundColor,backgroundSize:s.backgroundSize,
          backgroundRepeat:s.backgroundRepeat,backgroundClip:s.backgroundClip,
          borderImage:s.borderImageSource,maskImage:s.maskImage,clipPath:s.clipPath,
          opacity:s.opacity,display:s.display,textArea,textFirst};
      }
      return {records:result, pageHeight:Math.max(document.documentElement.scrollHeight,
                                                  document.body.scrollHeight)};
    }""", vp["height"])
    values, page_height = records["records"], records["pageHeight"]
    for box in vp["boxes"]:
        data = values.get(box["id"])
        if data is None or "paint_order" not in box:       # the page took the box out of the document
            detached.mark(box)
            continue
        style = box["style"]
        shadows = _shadows(data["boxShadow"], "box-shadow") + _shadows(data["textShadow"], "text-shadow")
        for name, contents in _functions(data["filter"]):
            if name == "drop-shadow":
                shadows.extend(_shadows(contents, "drop-shadow"))
        if shadows:
            style["shadows"] = shadows
        blur = _filter(data["filter"], "blur")
        if blur is not None:
            style["filter_blur_px"] = round(max(0, blur), 2)
        if data["backdropFilter"] != "none":
            backdrop = {}
            other = []
            for name, contents in _functions(data["backdropFilter"]):
                if name == "blur":
                    value = _length(contents)
                    if value is not None:
                        backdrop["blur_px"] = round(max(0, value), 2)
                else:
                    other.append(f"{name}({contents})")
            if other:
                backdrop["other"] = other
            if backdrop:
                style["backdrop_filter"] = backdrop
        target = "text" if "text" in data["backgroundClip"].split(",") else "background"
        own = {"paint_order": box["paint_order"], "page_height": page_height,
               "text_area": data["textArea"], "text_first": data["textFirst"]}
        gradients = (_gradient(data["backgroundImage"], target, box["rect"], vp, blur, vp["boxes"], own) +
                     _gradient(data["borderImage"], "border", box["rect"], vp, blur, vp["boxes"], own) +
                     _gradient(data["maskImage"], "mask", box["rect"], vp, blur, vp["boxes"], own))
        if gradients:
            style["gradients"] = gradients
        if pattern := _pattern(data, box["rect"], screenshot, view.config["dpr"]):
            style["background_pattern"] = pattern
        if clip := _clip(data["clipPath"], box["rect"]):
            style["clip"] = clip
    return values
