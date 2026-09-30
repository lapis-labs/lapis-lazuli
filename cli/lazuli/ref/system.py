"""`lazuli ref system PATH_OR_URL`: type scale, color roles, and state rules from a design system file.

Inputs are DTCG tokens (JSON whose tokens carry `$value`) or a DESIGN.md in one of the plan schema's
dialects, detected as the DESIGN.md guidance does:
- google: YAML frontmatter with `colors:`; read from `colors`, `typography`, and `components`.
- opendesign (an H1 with numbered H2 sections) and stitch-legacy (the five unnumbered legacy
  headings) are prose: colors and font sizes found in their color and typography sections are
  candidates for review, and the profile notes that.
- An unknown dialect is refused, never guessed.

Type scale: font sizes in px (rem at 16 px, bare numbers as px; em and unitless values are skipped).
`steps_px` are the distinct sizes, ascending. `ratio` is the ratio a prose document states, else the
median ratio of adjacent steps. `base_px` is the size of the style named body (the lower median when
several are), omitted when none is.
Color roles: every color token in document order, aliases resolved, converted to OKLCH.
States: interaction states (hover, focus, ...) found in token names, grouped by the name they vary;
for prose, the states its component sections mention. Summaries are generated, never quoted.
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

import yaml

from lapis_design.render.color import to_oklch
from lazuli.ref.common import InputError, Profile, fetch, is_url, new_document, page_url, slugify

ROOT_PX = 16.0
STATES = ("hover", "focus", "active", "pressed", "disabled", "selected", "checked", "visited", "invalid",
          "dragged")
_STITCH_HEADINGS = {"visual theme & atmosphere", "color palette & roles", "typography rules",
                    "component stylings", "layout principles"}
_ALIAS = re.compile(r"^\{([^{}]+)\}$")
_DIMENSION = re.compile(r"\s*(\d+(?:\.\d+)?|\.\d+)\s*(px|rem)?\s*", re.I)
_COLOR_SPACES = {"srgb", "srgb-linear", "display-p3", "a98-rgb", "prophoto-rgb", "rec2020", "xyz", "xyz-d65",
                 "xyz-d50"}
# Prose patterns
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_CSS_COLOR = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b"
                        r"|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\([^()]*\)", re.I)
_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(px|rem)\b", re.I)
_NOT_FONT_SIZE = re.compile(r"(line[- ]?height|leading|letter[- ]?spacing|tracking|spacing|padding|margin|gap|"
                            r"radius|border|width|height)\W*$", re.I)
_RATIO = re.compile(r"ratio\D{0,20}?(\d+(?:\.\d+)?)", re.I)


# ------------------------------------------------------------------ values

def _hex(value: str, alpha: float = 1.0) -> list[float] | None:
    digits = value.strip().removeprefix("#")
    if len(digits) in (3, 4):
        digits = "".join(c * 2 for c in digits)
    if len(digits) not in (6, 8) or not re.fullmatch(r"[0-9a-fA-F]+", digits):
        return None
    r, g, b = (int(digits[i:i + 2], 16) for i in (0, 2, 4))
    a = (int(digits[6:8], 16) / 255 if len(digits) == 8 else 1) * alpha
    return to_oklch(f"rgb({r} {g} {b} / {a})")


def _css_color(value: str) -> list[float] | None:
    value = value.strip()
    return _hex(value) if value.startswith("#") else to_oklch(value)


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _color(value) -> list[float] | None:
    """A DTCG color object (colorSpace, components, alpha, hex fallback) or a CSS color string."""
    if isinstance(value, str):
        return _css_color(value)
    if not isinstance(value, dict):
        return None
    alpha = value.get("alpha", 1)
    components = value.get("components")
    space = str(value.get("colorSpace", "")).lower()
    if (_number(alpha) and isinstance(components, list) and len(components) == 3
            and all(c == "none" or _number(c) for c in components)):
        a, b, c = map(str, components)
        css = {"oklch": f"oklch({a} {b} {c} / {alpha})", "oklab": f"oklab({a} {b} {c} / {alpha})",
               "lab": f"lab({a} {b} {c} / {alpha})", "lch": f"lch({a} {b} {c} / {alpha})",
               "hsl": f"hsl({a} {b}% {c}% / {alpha})", "hwb": f"hwb({a} {b}% {c}% / {alpha})"}.get(space)
        if css is None and space in _COLOR_SPACES:
            css = f"color({space} {a} {b} {c} / {alpha})"
        if css and (result := to_oklch(css)) is not None:
            return result
    if isinstance(value.get("hex"), str) and _number(alpha):
        return _hex(value["hex"], alpha)
    return None


def _px(value) -> float | None:
    """A font size in px: px, rem (at 16 px), or a bare number; None for em and anything else."""
    if _number(value):
        number, unit = value, "px"
    elif isinstance(value, dict) and _number(value.get("value")):
        number, unit = value["value"], str(value.get("unit", ""))
    elif isinstance(value, str) and (match := _DIMENSION.fullmatch(value)):
        number, unit = float(match.group(1)), match.group(2) or "px"
    else:
        return None
    unit = unit.lower()
    px = number if unit == "px" else number * ROOT_PX if unit == "rem" else None
    return round(float(px), 2) if px else None


def _type_scale(sizes: list[float], body: list[float], ratio: float | None) -> dict:
    steps = sorted(set(sizes))
    scale = {}
    if body:
        scale["base_px"] = sorted(body)[(len(body) - 1) // 2]
    if ratio is None and len(steps) >= 2:
        ratio = statistics.median(b / a for a, b in zip(steps, steps[1:]))
    if ratio:
        scale["ratio"] = round(ratio, 3)
    if steps:
        scale["steps_px"] = steps
    return scale


def _states(names: list[str]) -> list[str]:
    """`base: state, state` for token names that vary a base name by interaction state."""
    groups: dict[str, set[str]] = {}
    for name in names:
        segments = name.split(".")
        for i in range(len(segments) - 1, -1, -1):
            words = [w for w in re.split(r"[-_]", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", segments[i]).lower()) if w]
            state = rest = None
            for j, word in enumerate(words):
                if word == "focus" and words[j + 1:j + 2] in (["visible"], ["within"]):
                    state, rest = f"focus-{words[j + 1]}", words[:j] + words[j + 2:]
                elif word in STATES:
                    state, rest = word, words[:j] + words[j + 1:]
                if state:
                    break
            if state:
                base = segments[:i] + (["-".join(rest)] if rest else []) + segments[i + 1:]
                if base:
                    groups.setdefault(".".join(base), set()).add(state)
                break
    return [f"{base}: {', '.join(sorted(states))}" for base, states in sorted(groups.items())]


# ------------------------------------------------------------------ DTCG

def _pointer(root: dict, ref) -> object:
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    node = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node["$value"] if isinstance(node, dict) and "$value" in node else node


def _dtcg(root: dict) -> dict:
    tokens: dict[str, dict] = {}

    def walk(node: dict, path: list[str], inherited: str | None) -> None:
        group_type = node.get("$type", inherited)
        for key, child in node.items():
            if (key.startswith("$") and key != "$root") or not isinstance(child, dict):
                continue
            if "$value" in child:
                tokens[".".join(path + [key])] = {"value": child["$value"], "type": child.get("$type", group_type)}
            else:
                walk(child, path + [key], group_type)

    walk(root, [], None)
    if not tokens:
        raise InputError("no DTCG tokens: nothing in the file carries a `$value`")

    def target(value) -> str | None:
        """The token a whole-value alias or `$ref` points at."""
        if isinstance(value, str) and (match := _ALIAS.match(value.strip())):
            return match.group(1)
        if isinstance(value, dict) and set(value) == {"$ref"} and isinstance(value["$ref"], str) \
                and value["$ref"].startswith("#/") and value["$ref"].endswith("/$value"):
            return ".".join(p.replace("~1", "/").replace("~0", "~") for p in value["$ref"][2:].split("/")[:-1])
        return None

    def resolve(value, seen: tuple = ()):
        while True:
            if isinstance(value, dict) and set(value) == {"$ref"}:
                if value["$ref"] in seen:
                    return None
                seen += (value["$ref"],)
                value = _pointer(root, value["$ref"])
            elif (name := target(value)) is not None:
                if name in seen or name not in tokens:
                    return None
                seen += (name,)
                value = tokens[name]["value"]
            else:
                return value

    def type_of(name: str, seen: tuple = ()) -> str | None:
        if tokens[name]["type"]:
            return tokens[name]["type"]
        aliased = target(tokens[name]["value"])
        return type_of(aliased, seen + (name,)) if aliased in tokens and aliased not in seen else None

    colors, sizes, body, skipped = [], [], [], []
    for name, token in tokens.items():
        kind = type_of(name)
        role = name.replace(".$root", "")
        if kind == "color":
            if (oklch := _color(resolve(token["value"]))) is not None:
                colors.append({"role": role, "oklch": oklch})
            else:
                skipped.append(role)
            continue
        if kind == "typography":
            value = resolve(token["value"])
            px = _px(resolve(value.get("fontSize"))) if isinstance(value, dict) else None
        elif kind in ("dimension", "fontSize", "fontSizes") and "fontsize" in re.sub(r"[^a-z]", "", name.lower()):
            px = _px(resolve(token["value"]))
        else:
            continue
        if px is None:
            skipped.append(f"{role} (font size)")
            continue
        sizes.append(px)
        if "body" in name.lower():
            body.append(px)
    return {"colors": colors, "type_scale": _type_scale(sizes, body, None), "states": _states(list(tokens)),
            "skipped": skipped}


# ------------------------------------------------------------------ DESIGN.md

def _frontmatter(text: str) -> dict | None:
    match = re.match(r"\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise InputError(f"the DESIGN.md frontmatter is not valid YAML: {exc}") from exc
    return data if isinstance(data, dict) else None


def _headings(text: str) -> list[tuple[int, str, str, str]]:
    """(level, title as written, the titles from the top down to it, the text up to the next heading),
    outside code fences. Each line belongs to one heading; subsections carry their parents' topics."""
    lines = text.splitlines()
    found, fenced = [], False
    for index, line in enumerate(lines):
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced and (match := _HEADING.match(line)):
            found.append((index, len(match.group(1)), match.group(2).strip()))
    sections, stack = [], []
    for n, (index, level, title) in enumerate(found):
        end = found[n + 1][0] if n + 1 < len(found) else len(lines)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        sections.append((level, title, " / ".join(t for _, t in stack), "\n".join(lines[index + 1:end])))
    return sections


def _dialect(frontmatter: dict | None, headings: list[tuple[int, str, str, str]]) -> str:
    if frontmatter is not None and "colors" in frontmatter:
        return "google"
    numbered = [title for level, title, _, _ in headings if level == 2 and re.match(r"\d+\.\s", title)]
    if any(level == 1 for level, *_ in headings) and len(numbered) >= 2:
        return "opendesign"
    if _STITCH_HEADINGS <= {title.lower() for _, title, _, _ in headings}:
        return "stitch-legacy"
    return "unknown"


def _google(data: dict) -> dict:
    def lookup(path: str):
        node = data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def resolve(value, seen: tuple = ()):
        while isinstance(value, str) and (match := _ALIAS.match(value.strip())):
            if match.group(1) in seen:
                return None
            seen += (match.group(1),)
            value = lookup(match.group(1))
        return value

    def leaves(node, prefix: str = ""):
        for key, value in (node.items() if isinstance(node, dict) else ()):
            name = f"{prefix}{key}"
            if isinstance(value, dict):
                yield from leaves(value, f"{name}.")
            else:
                yield name, value

    colors, sizes, body, skipped = [], [], [], []
    for name, value in leaves(data.get("colors")):
        resolved = resolve(value)
        oklch = _css_color(resolved) if isinstance(resolved, str) else None
        if oklch is None:
            skipped.append(f"colors.{name}")
        else:
            colors.append({"role": name, "oklch": oklch})
    typography = data.get("typography")
    for name, style in (typography.items() if isinstance(typography, dict) else ()):
        style = resolve(style)
        px = _px(resolve(style.get("fontSize"))) if isinstance(style, dict) else None
        if px is None:
            skipped.append(f"typography.{name} (font size)")
            continue
        sizes.append(px)
        if "body" in str(name).lower():
            body.append(px)
    components = data.get("components")
    names = [f"colors.{name}" for name, _ in leaves(data.get("colors"))] + [
        f"components.{name}" for name in (components if isinstance(components, dict) else ())]
    return {"colors": colors, "type_scale": _type_scale(sizes, body, None), "states": _states(names),
            "skipped": skipped}


def _label(before: str) -> str | None:
    """A short role label from the text before a color on its line (a bold or code span wins)."""
    before = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", before)
    spans = [bold or code for bold, code in re.findall(r"\*\*([^*]+)\*\*|`([^`#]+)`", before)]
    text = spans[-1] if spans else before
    text = re.sub(r"[*_`|>:()\[\]=–—,;]+", " ", text).strip(" -")
    return slugify(text) if text and len(text) <= 40 and len(text.split()) <= 4 else None


def _prose(headings: list[tuple[int, str, str, str]]) -> dict:
    colors, sizes, body, states, skipped = [], [], [], set(), []
    ratio = None
    used: set[str] = set()
    for _, _, topic, text in headings:
        topic = topic.lower()
        if re.search(r"\bcolou?rs?\b", topic):
            for line in text.splitlines():
                for match in _CSS_COLOR.finditer(line):
                    oklch = _css_color(match.group(0))
                    if oklch is None:
                        skipped.append(match.group(0))
                        continue
                    label = _label(line[:match.start()]) or f"color-{len(colors) + 1}"
                    role, n = label, 2
                    while role in used:
                        role, n = f"{label}-{n}", n + 1
                    used.add(role)
                    colors.append({"role": role, "oklch": oklch})
        if "typograph" in topic:
            for line in text.splitlines():
                for match in _SIZE.finditer(line):
                    if _NOT_FONT_SIZE.search(line[max(0, match.start() - 24):match.start()]):
                        continue
                    px = round(float(match.group(1)) * (ROOT_PX if match.group(2).lower() == "rem" else 1), 2)
                    sizes.append(px)
                    if "body" in line.lower():
                        body.append(px)
            if ratio is None and (match := _RATIO.search(text)) and 1 < float(match.group(1)) < 4:
                ratio = float(match.group(1))
        if re.search(r"\b(components?|interactions?|states?)\b", topic):
            states |= {state for state in STATES if re.search(rf"\b{state}\b", text, re.I)}
    return {"colors": colors, "type_scale": _type_scale(sizes, body, ratio),
            "states": [f"component prose mentions: {', '.join(sorted(states))}"] if states else [],
            "skipped": skipped}


# ------------------------------------------------------------------ command

def profile_system(source: str, rights: str) -> Profile:
    if is_url(source):
        _, response = fetch(source)
        text, path = response.text(), None
    else:
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise InputError(f"cannot read {source}: {exc}") from exc
    notes = []
    if text.lstrip("\ufeff \t\r\n").startswith(("{", "[")):
        try:
            root = json.loads(text.lstrip("\ufeff"))
        except json.JSONDecodeError as exc:
            raise InputError(f"{source} is not valid JSON: {exc}") from exc
        if not isinstance(root, dict):
            raise InputError(f"{source} is not a DTCG token file: the top level is not an object")
        dialect, parsed = "dtcg", _dtcg(root)
    else:
        frontmatter, headings = _frontmatter(text), _headings(text)
        dialect = _dialect(frontmatter, headings)
        if dialect == "unknown":
            raise InputError(f"{source}: unknown DESIGN.md dialect (no frontmatter `colors:`, no numbered sections "
                             "under a title, not the five legacy headings); not guessing a schema")
        if dialect == "google":
            parsed = _google(frontmatter)
        else:
            parsed = _prose(headings)
            notes.append(f"Colors and font sizes come from {dialect} DESIGN.md prose: candidates for review, "
                         "not declared tokens.")
    if not (parsed["colors"] or parsed["type_scale"] or parsed["states"]):
        raise InputError(f"{source}: no colors, font sizes, or state rules found")
    document = new_document("system", rights)
    system = {}
    if path is None:
        document["source"]["url"] = page_url(source)
    else:
        document["source"]["path"] = system["tokens_path"] = str(path)
    if parsed["type_scale"]:
        system["type_scale"] = parsed["type_scale"]
    if parsed["colors"]:
        system["color_roles"] = parsed["colors"]
    if parsed["states"]:
        system["states"] = parsed["states"]
    document["system"] = system
    summary = {"format": dialect, "color_roles": len(parsed["colors"]),
               "type_scale": parsed["type_scale"] or "none found", "state_rules": len(parsed["states"])}
    if parsed["skipped"]:
        summary["skipped"] = parsed["skipped"]
    return Profile(document, summary, notes=notes)
