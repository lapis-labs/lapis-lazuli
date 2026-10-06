"""Derive v1 render measurements from captured boxes and text runs.

Symmetry and density read per-line inked rectangles (`line_extents`) and the document height
(`page_height`) that the capture passes in; without them, text falls back to each run's box
rectangle and the page height to the lowest box. The extract stores neither input, so these two are
capture-time values (render/DERIVED.md). A signature found only by text matching is reported with
`signature_evidence: not-verified`.
"""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
from math import sqrt
from statistics import median
import re

from lapis_design.render.color import delta_e_ok


_PRICE = re.compile(r"(?:[$€£¥₩₹]\s*\d|\d[\d,.]*\s*(?:[$€£¥₩₹]|원|usd|eur|krw|"
                    r"/\s*(?:mo|month|yr|year|월|년)))", re.I)
_QUOTE = re.compile(r'["“”‘’«»]')
_PERSON_NAME = re.compile(r"[A-Z][a-z]+(?:[ -][A-Z][a-z]+){1,3}|[가-힣]{2,4}")
_CONTROL = {"button", "link", "input"}
_ARCHETYPES = ("hero", "pricing", "testimonial", "faq", "logo-strip",
               "feature-grid", "cta", "footer")


def _round(value, places=4):
    return round(value, places)


def _step(value, quantum):
    return float((Decimal(str(value)) / Decimal(str(quantum))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP) * Decimal(str(quantum)))


def _fingerprint(runs):
    if not runs:
        return None
    total = sum(run["chars"] for run in runs)
    groups = defaultdict(int)
    for run in runs:
        if all(key in run for key in ("size_px", "weight", "letter_spacing_em", "transform")):
            key = (_step(run["size_px"], 0.5), _step(run["weight"], 100),
                   _step(run["letter_spacing_em"], 0.01), run["transform"])
            groups[key] += run["chars"]
    result = {}
    if groups:
        roles = []
        for (size, weight, tracking, transform), count in sorted(
                groups.items(), key=lambda item: (-item[0][0], -item[1], item[0][1:])):
            roles.append({"size_px": size, "weight": weight,
                          "tracking_em": tracking, "transform": transform,
                          "share": _round(count / total)})
        result["roles"] = roles
        if all(role["size_px"] > 0 for role in roles[1:]):
            result["adjacent_ratios"] = [_round(a["size_px"] / b["size_px"])
                                         for a, b in zip(roles, roles[1:])]
    body = [run["measure_chars"] for run in runs
            if run.get("type_role") == "body" and "measure_chars" in run]
    if body:
        result["measure_chars"] = _round(median(body))
    return result or None


def _descendants(root, children):
    pending = [root]
    seen = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        yield current
        pending.extend(reversed(children.get(current, ())))


def _section_ids(boxes, by_id, children, elements, viewport_height):
    has_main = any(info.get("tag") == "main" for info in elements.values())
    candidates = []
    for box in boxes:
        if elements.get(box["id"], {}).get("tag") == "main":   # the container of sections, not one
            continue
        parent = box.get("parent")
        tag = elements.get(parent, {}).get("tag")
        if box["role"] == "section" or (tag == "main" or
            (tag == "body" and not has_main)) and box["rect"]["h"] > 0.3 * viewport_height:
            candidates.append(box["id"])
    candidate_set = set(candidates)
    top = []
    for ident in candidates:
        parent = by_id[ident].get("parent")
        while parent in by_id and parent not in candidate_set:
            parent = by_id[parent].get("parent")
        if parent not in candidate_set:
            top.append(ident)
    result = []
    for ident in top:
        parent = by_id[ident]
        large = [by_id[child] for child in children.get(ident, ())
                 if child in by_id and child not in candidate_set
                 and by_id[child]["rect"]["w"] >= parent["rect"]["w"] * 0.5
                 and by_id[child]["rect"]["h"] > viewport_height * 0.3
                 and by_id[child].get("style", {}).get("background")]
        if len(large) >= 2 and any(
                delta_e_ok(a["style"]["background"], b["style"]["background"]) > 0.02
                for a, b in zip(large, large[1:])):
            result.extend(child["id"] for child in large)
        else:
            result.append(ident)
    return result


def _quoted_attributions(contained, texts, by_id, elements):
    quote_ids = {box["id"] for box in contained
                 if elements.get(box["id"], {}).get("tag") == "blockquote"}
    all_ids = set(by_id)
    for run in texts:
        if run["box"] in by_id and _QUOTE.search(run.get("text", "")) and not any(
                ancestor in quote_ids for ancestor in _ancestor_ids(
                    run["box"], by_id, all_ids)):
            quote_ids.add(run["box"])
    if not quote_ids:
        return False, False

    def near(quote, candidate):
        rect, other = quote["rect"], candidate["rect"]
        overlap = min(rect["x"] + rect["w"], other["x"] + other["w"]) - max(
            rect["x"], other["x"])
        return overlap > 0 and abs(other["y"] - (rect["y"] + rect["h"])) <= max(
            100, rect["h"])

    for quote_id in quote_ids:
        quote = by_id[quote_id]
        name = any(
            run["box"] != quote_id and run["box"] in by_id and
            near(quote, by_id[run["box"]]) and
            (run.get("type_role") in ("caption", "label") or
             elements.get(run["box"], {}).get("tag") == "cite" or
             bool(_PERSON_NAME.fullmatch(run.get("text", "").strip())))
            for run in texts)
        avatar = any(
            box["role"] == "media" and near(quote, box) and
            ("avatar" in elements.get(box["id"], {}).get("attrs", {}).get("class", "").lower()
             or "avatar" in box.get("a11y", {}).get("name", "").lower())
            for box in contained)
        if not (name or avatar):
            return True, False
    return True, True


def _logo_row(contained, by_id, elements, viewport_height):
    """Three or more image or svg boxes in one row, each at most 15% of the viewport height, the
    smallest at least 80% of the largest. A box nested in another counted box is not counted."""
    marks = {box["id"]: box for box in contained
             if box["role"] == "media" or elements.get(box["id"], {}).get("tag") == "svg"}

    def nested(box):
        parent = box.get("parent")
        while parent in by_id:
            if parent in marks:
                return True
            parent = by_id[parent].get("parent")
        return False

    def center(box):
        return box["rect"]["y"] + box["rect"]["h"] / 2

    small = sorted((box for box in marks.values()
                    if 0 < box["rect"]["h"] <= viewport_height * 0.15 and not nested(box)), key=center)
    for i, first in enumerate(small):
        row = [first]
        for candidate in small[i + 1:]:
            if center(candidate) - center(first) > first["rect"]["h"]:
                break
            heights = [box["rect"]["h"] for box in (*row, candidate)]
            if min(heights) >= 0.8 * max(heights):
                row.append(candidate)
                if len(row) >= 3:
                    return True
    return False


def _archetype(ident, index, section_ids, by_id, children, elements, runs, viewport_height,
               largest_size):
    ids = set(_descendants(ident, children))
    contained = [by_id[item] for item in ids if item in by_id]
    texts = [run for run in runs if run["box"] in ids]
    if not texts and not any(box["role"] in ("media", "icon", *_CONTROL) or "media" in box
                             for box in contained):
        return "other", 0                                   # an empty section matches no archetype
    headings = [run for run in texts if run.get("type_role") in ("heading", "display") or
                by_id.get(run["box"], {}).get("role") == "heading"]
    all_text = " ".join(run.get("text", "") for run in texts)
    card_pairs = []
    for parent in ids:
        card_ids = [child for child in children.get(parent, ())
                    if child in by_id and by_id[child]["role"] == "card"]
        if len(card_ids) >= 2:
            card_pairs.extend(card_ids)
    priced_cards = 0
    feature_cards = 0
    for card_id in card_pairs:
        card_ids = set(_descendants(card_id, children))
        if any(by_id[child]["role"] == "button" or
               elements.get(child, {}).get("tag") == "button"
               for child in card_ids if child in by_id):
            priced_cards += 1
        card_text = [run for run in texts if run["box"] in card_ids]
        if (any(run.get("type_role") in ("heading", "display") or
                by_id.get(run["box"], {}).get("role") == "heading"
                for run in card_text) and
                any(run.get("type_role") == "body" and run["chars"] <= 160
                    for run in card_text)):
            feature_cards += 1
    logo_strip = _logo_row(contained, by_id, elements, viewport_height) and len(texts) <= 1
    links = [run for run in texts if any(by_id.get(cid, {}).get("role") == "link" or
             elements.get(cid, {}).get("tag") == "a" for cid in
             _ancestor_ids(run["box"], by_id, ids))]
    has_quote, attributed = _quoted_attributions(contained, texts, by_id, elements)
    questions = sum("?" in run.get("text", "") or "？" in run.get("text", "")
                    for run in headings)
    details = any(elements.get(b["id"], {}).get("tag") in ("details", "summary")
                  for b in contained)
    buttons = sum(b["role"] == "button" or elements.get(b["id"], {}).get("tag") == "button"
                  for b in contained)
    footer = elements.get(ident, {}).get("tag") == "footer" or any(
        b.get("a11y", {}).get("role") == "contentinfo" or
        elements.get(b["id"], {}).get("attrs", {}).get("role") == "contentinfo"
        for b in contained)
    cue_values = (
        (index == 0, any(run.get("size_px") == largest_size for run in texts)
         if largest_size is not None else False, by_id[ident]["rect"]["h"] >= 0.6 * viewport_height),
        (bool(_PRICE.search(all_text)), priced_cards >= 2),
        (has_quote, attributed),
        (questions >= 3, details),
        (logo_strip,),
        (feature_cards >= 3, len(card_pairs) >= 3),
        (by_id[ident]["rect"]["h"] <= 0.4 * viewport_height,
         bool(headings) and buttons <= 2),
        (index == len(section_ids) - 1, len(texts) > 0 and len(links) / len(texts) > 0.5,
         footer),
    )
    confidence, archetype = max(
        ((sum(cues) / len(cues), -idx) for idx, cues in enumerate(cue_values)),
        default=(0, 0))
    if confidence < 0.5:
        return "other", _round(confidence)
    return _ARCHETYPES[-archetype], _round(confidence)


def _ancestor_ids(ident, by_id, within):
    while ident in within:
        yield ident
        ident = by_id.get(ident, {}).get("parent")


def _levenshtein(left, right):
    if not left:
        return len(right)
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def _similarity(a, b, by_id, children, chars):
    ra, rb = by_id[a]["rect"], by_id[b]["rect"]
    size = sum(1 - abs(ra[k] - rb[k]) / max(ra[k], rb[k])
               if max(ra[k], rb[k]) else 1 for k in ("w", "h")) / 2
    roles_a = [by_id[c]["role"] for c in children.get(a, ()) if c in by_id]
    roles_b = [by_id[c]["role"] for c in children.get(b, ()) if c in by_id]
    structure = 1 - _levenshtein(roles_a, roles_b) / max(len(roles_a), len(roles_b), 1)
    length = 1 - abs(chars[a] - chars[b]) / max(chars[a], chars[b]) if max(chars[a], chars[b]) else 1
    return 0.4 * size + 0.4 * structure + 0.2 * length


def _groups(boxes, by_id, children, runs):
    chars = defaultdict(int)
    for run in runs:
        current = run["box"]
        while current in by_id:
            chars[current] += run["chars"]
            current = by_id[current].get("parent")
    result = []
    for parent, siblings in children.items():
        if parent not in by_id:
            continue
        roles = defaultdict(list)
        for ident in siblings:
            if ident in by_id:
                roles[by_id[ident]["role"]].append(ident)
        for members in roles.values():
            if len(members) >= 3:
                scores = [_similarity(a, b, by_id, children, chars)
                          for a, b in combinations(members, 2)]
                result.append({"parent": parent, "members": members,
                               "similarity": _round(sum(scores) / len(scores))})
    return result


def encloses(style):
    """Whether a box's border holds its content in: a side on each axis, top or bottom and left or right. One rule, or
    two parallel ones, divides what lies on either side of it and is not a container, so a ruled row is not a card
    (render/DERIVED.md, card_nesting_max). A style with `border_px` and no `border_sides` cannot say which sides
    carry it and counts as bordered."""
    sides = style.get("border_sides")
    if sides:
        return (any(sides.get(name, {}).get("px", 0) > 0 for name in ("top", "bottom"))
                and any(sides.get(name, {}).get("px", 0) > 0 for name in ("left", "right")))
    return style.get("border_px", 0) > 0


def _card_depth(boxes, by_id, viewport_area):
    if viewport_area <= 0:
        return None
    depths = {}
    def depth(ident):
        if ident in depths:
            return depths[ident]
        box = by_id[ident]
        parent = box.get("parent")
        ancestor = parent
        while ancestor in by_id and not by_id[ancestor].get("style", {}).get("background"):
            ancestor = by_id[ancestor].get("parent")
        style = box.get("style", {})
        background = style.get("background")
        ancestor_bg = by_id[ancestor].get("style", {}).get("background") if ancestor in by_id else None
        boundary = ((background is not None and ancestor_bg is not None and
                     delta_e_ok(background, ancestor_bg) > 0.02) or
                    encloses(style) or
                    style.get("shadow", False) or bool(style.get("shadows")))
        card = (box["role"] not in _CONTROL and
                box["rect"]["w"] * box["rect"]["h"] >= viewport_area * 0.02
                and boundary)
        depths[ident] = (depth(parent) if parent in by_id else 0) + int(card)
        return depths[ident]
    return max((depth(box["id"]) for box in boxes), default=0)


def _stats(values):
    ordered = sorted(values)
    def percentile(p):
        index = (len(ordered) - 1) * p
        lower = int(index)
        return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (index - lower)

    mean = sum(values) / len(values)
    return {"median": _round(median(values), 2), "p10": _round(percentile(0.1), 2),
            "p90": _round(percentile(0.9), 2),
            "cv": _round(sqrt(sum((v - mean) ** 2 for v in values) / len(values)) / mean)
            if mean else 0}


def _gaps(by_id, children, sections):
    values = defaultdict(list)
    def add_gap(left, right, level):
        a, b = by_id[left]["rect"], by_id[right]["rect"]
        overlap = max(0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
        if min(a["w"], b["w"]) > 0 and overlap >= min(a["w"], b["w"]) / 2:
            values[level].append(max(0, b["y"] - a["y"] - a["h"]))

    section_set = set(sections)
    for parent, siblings in children.items():
        if parent not in by_id:
            continue
        if parent in section_set:
            level = "between_groups"
        elif by_id[parent]["role"] in ("card", "list") or any(
                ancestor in section_set for ancestor in _ancestor_ids(
                    parent, by_id, set(by_id))):
            level = "inside_group"
        else:
            continue
        for a, b in zip(siblings, siblings[1:]):
            if a in by_id and b in by_id and a not in section_set and b not in section_set:
                add_gap(a, b, level)
    for a, b in zip(sections, sections[1:]):
        add_gap(a, b, "between_sections")
    result = {level: _stats(values[level]) for level in (
        "inside_group", "between_groups", "between_sections") if values[level]}
    inside = median(values["inside_group"]) if values["inside_group"] else 0
    if inside and values["between_sections"]:
        result["level_ratio"] = _round(median(values["between_sections"]) / inside)
    return result


def _symmetry(vp, by_id, line_extents=None):
    width = vp.get("width", 0)
    if width <= 0:
        return None
    boxes = []
    for run in vp.get("text", ()):
        if line_extents is not None:
            boxes.extend((rect, rect["w"] * rect["h"])
                         for rect in line_extents.get(run["id"], ())
                         if rect["w"] > 0 and rect["h"] > 0)
        elif run["box"] in by_id:
            rect = by_id[run["box"]]["rect"]
            boxes.append((rect, rect["w"] * rect["h"]))
    boxes += [(box["rect"], box["rect"]["w"] * box["rect"]["h"])
              for box in vp.get("boxes", ()) if box["role"] == "media"]
    area = sum(weight for _, weight in boxes)
    if not area:
        return None
    return _round(sum(weight * max(0, 1 - abs(rect["x"] + rect["w"] / 2 - width / 2) / (width / 2))
                      for rect, weight in boxes) / area)


def _union_area(rectangles):
    events = []
    for x1, y1, x2, y2 in rectangles:
        if x2 > x1 and y2 > y1:
            events.extend(((x1, 1, y1, y2), (x2, -1, y1, y2)))
    events.sort()
    active = defaultdict(int)
    previous = None
    area = 0
    for x, direction, y1, y2 in events:
        if previous is not None and x > previous:
            intervals = sorted((start, end) for (start, end), count in active.items() if count)
            covered = 0
            low = high = None
            for start, end in intervals:
                if low is None:
                    low, high = start, end
                elif start <= high:
                    high = max(high, end)
                else:
                    covered += high - low
                    low, high = start, end
            if low is not None:
                covered += high - low
            area += (x - previous) * covered
        active[(y1, y2)] += direction
        previous = x
    return area


def _density(vp, by_id, viewport_height, page_height=None, line_extents=None):
    width = vp.get("width", 0)
    height = (page_height if page_height is not None else
              max([viewport_height, *(box["rect"]["y"] + box["rect"]["h"]
                                      for box in by_id.values())]))
    if width <= 0 or height <= 0:
        return None
    if line_extents is None:
        text_ids = {run["box"] for run in vp.get("text", ())}
        ids = text_ids | {ident for ident, box in by_id.items()
                          if box["role"] in ("text", "heading", "media", *_CONTROL)}
        rectangles = [by_id[ident]["rect"] for ident in ids & by_id.keys()]
    else:
        rectangles = [rect for run in vp.get("text", ())
                      for rect in line_extents.get(run["id"], ())]
        rectangles.extend(box["rect"] for box in by_id.values()
                          if box["role"] in ("media", *_CONTROL))
    clipped = [(max(0, rect["x"]), max(0, rect["y"]),
                min(width, rect["x"] + rect["w"]), min(height, rect["y"] + rect["h"]))
               for rect in rectangles]
    return _round(_union_area(clipped) / (width * height))


def derive(vp: dict, elements: dict[str, dict], viewport_height: float,
           plan_signature: str | None = None, *, page_height: float | None = None,
           line_extents: dict[str, list[dict[str, float]]] | None = None) -> dict:
    """Return only derivations whose measured inputs are available.

    When line extents or document height are not provided, preserve the original
    run-box approximation and captured-box page-height fallback.
    """
    result = {}
    boxes = vp.get("boxes")
    runs = vp.get("text")
    by_id = {box["id"]: box for box in boxes or ()}
    children = defaultdict(list)
    for box in boxes or ():
        if box.get("parent") in by_id:
            children[box["parent"]].append(box["id"])
    # Prefer the captured DOM order when it is available, retaining only captured boxes.
    for ident, info in elements.items():
        if ident in by_id and "children" in info:
            children[ident] = [child for child in info["children"] if child in by_id]
    if runs is not None:
        fingerprint = _fingerprint(runs)
        if fingerprint is not None:
            result["type_fingerprint"] = fingerprint
    section_ids = []
    if boxes is not None and viewport_height > 0:
        section_ids = _section_ids(boxes, by_id, children, elements, viewport_height)
        largest = max((run["size_px"] for run in runs or () if "size_px" in run), default=None)
        sections = []
        for index, ident in enumerate(section_ids):
            archetype, confidence = _archetype(ident, index, section_ids, by_id, children,
                                                elements, runs or (), viewport_height, largest)
            sections.append({"box": ident, "archetype": archetype,
                             "confidence": confidence})
        result["sections"] = sections
        result["section_sequence"] = [section["archetype"] for section in sections]
        result["card_nesting_max"] = _card_depth(boxes, by_id, vp.get("width", 0) * viewport_height)
        gaps = _gaps(by_id, children, section_ids)
        if gaps:
            result["gaps"] = gaps
        density = _density(vp, by_id, viewport_height, page_height, line_extents)
        if density is not None:
            result["density"] = density
    if boxes is not None and runs is not None:
        result["sibling_groups"] = _groups(boxes, by_id, children, runs)
        symmetry = _symmetry(vp, by_id, line_extents)
        if symmetry is not None:
            result["symmetry"] = symmetry
    marked = any("data-lapis-signature" in info.get("attrs", {}) for info in elements.values())
    matched = bool(plan_signature and runs is not None and plan_signature.casefold() in " ".join(
        run.get("text", "") for run in runs).casefold())
    if marked or matched:
        result["signature_found"] = True
        result["signature_evidence"] = "verified" if marked else "not-verified"
    elif boxes is not None or elements or (plan_signature and runs is not None):
        result["signature_found"] = False
    return result
