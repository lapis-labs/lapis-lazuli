"""Bounded source evidence for rendered alternatives; structural identity is not a design-quality score."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from lapis_design.lint.detectors.source import _DECL, _balanced

# Relations rather than finishes: order, type size, color, margin and motion do not change grouping.
RELATION_PROPERTIES = {"display", "position", "width", "max-width", "min-width", "grid-template-columns",
                       "grid-template-rows", "grid-template-areas", "grid-area", "flex-direction", "flex-wrap",
                       "overflow", "overflow-x", "border", "border-width", "border-style"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tree = ["document", [], []]
        self.stack = [self.tree]
        self.classes = set()
        self.stylesheets = []
        self.styles = []
        self.main = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.classes.update((attrs.get("class") or "").split())
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.stylesheets.append(attrs.get("href", ""))
        if attrs.get("style"):
            self.styles.append(("inline:" + tag, attrs["style"]))
        node = [tag, [], []]
        self.stack[-1][1].append(node)
        if tag == "main":
            self.main = node
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.stack) - 1, 0, -1) if self.stack[i][0] == tag), None)
        if index is not None:
            del self.stack[index:]

    def handle_data(self, data):
        if self.stack[-1][0] == "style":
            self.styles.append(("sheet", data))
        elif self.stack[-1][0] not in ("script", "head"):
            self.stack[-1][2].append(" ".join(data.split()))


def _tree(node):
    tag, children, text = node
    if tag in ("script", "style", "link", "head"):
        return None
    # Sort siblings so element-order changes cannot masquerade as changed group membership.
    groups = [value for child in children if (value := _tree(child)) is not None]
    return tag, tuple(sorted(groups, key=repr)), " ".join(t for t in text if t)


def _values(css):
    values = tuple(sorted((m.group(1).lower(), m.group(2).strip()) for m in _DECL.finditer(css)
                          if m.group(1).lower() in RELATION_PROPERTIES))
    # A plain flex column only enabling CSS order preserves block-flow grouping and boundaries.
    if values == (("display", "flex"), ("flex-direction", "column")):
        return ()
    return values


def _relations(css, classes, context=""):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, start = set(), 0
    while (opener := css.find("{", start)) >= 0:
        close = _balanced(css, opener, len(css))
        if close < 0:
            break
        selector, content = css[start:opener].strip(), css[opener + 1:close - 1]
        if selector.startswith("@"):
            out |= _relations(content, classes, context + selector)
        else:
            for branch in selector.split(","):
                selected = set(re.findall(r"\.([\w-]+)", branch))
                if selected.issubset(classes) and (values := _values(content)):
                    out.add((context, branch.strip(), values))
        start = close
    return out


def signature(file: Path, root: Path):
    parser = Markup()
    parser.feed(file.read_text(encoding="utf-8"))
    relations = set()
    for kind, style in parser.styles:
        if kind == "sheet":
            relations |= _relations(style, parser.classes)
        else:
            values = _values(style)
            if values:
                relations.add(("", kind, values))
    for name in parser.stylesheets:
        if urlsplit(name).scheme or name.startswith("//"):
            continue
        sheet = (file.parent / name).resolve()
        if sheet.is_relative_to(root.resolve()) and sheet.is_file():
            relations |= _relations(sheet.read_text(encoding="utf-8"), parser.classes)
    return _tree(parser.main or parser.tree), frozenset(relations)


def files_problem(entry: dict, root: Path | None) -> list[str]:
    kind = entry.get("decision")
    if kind not in ("layout", "direction", "motion"):
        return []
    if kind != "motion" and "render" not in entry.get("compared_on", []):
        return []
    errors, artifacts = [], []
    candidates = entry.get("candidates") or []
    for candidate in candidates:
        name = candidate.get("artifact")
        # A source may itself be an implementation path, as opposed to its inspiration.
        if not name and root is not None and str(candidate.get("source", "")).endswith(".html"):
            name = candidate["source"]
        if not name:
            errors.append(f"{kind} candidate {candidate.get('name')!r} has no implemented artifact")
        elif root is not None:
            file = (root / name.split("#")[0]).resolve()
            if not file.is_relative_to(root.resolve()) or not file.is_file():
                errors.append(f"{kind} candidate artifact is not an existing project file: {name}")
            else:
                artifacts.append(file)
    comparisons = entry.get("comparisons") or []
    if not comparisons:
        errors.append(f"{kind} has no matched observed comparisons")
    for comparison in comparisons:
        captures = comparison.get("playback" if kind == "motion" else "captures") or {}
        for candidate in candidates:
            name = captures.get(candidate.get("name"))
            if not name:
                errors.append(f"{kind} comparison has no {'playback' if kind == 'motion' else 'capture'} for {candidate.get('name')!r}")
            elif root is not None:
                file = (root / name).resolve()
                if not file.is_relative_to(root.resolve()) or not file.is_file():
                    errors.append(f"{kind} evidence file does not exist: {name}")
        if not comparison.get("state") or not comparison.get("viewport"):
            errors.append(f"{kind} comparison has no common interaction/state or viewport")
    if kind in ("layout", "direction") and root is not None and len(artifacts) >= 2 and all(p.suffix == ".html" for p in artifacts):
        signatures = [signature(p, root) for p in artifacts]
        if len(set(signatures)) == 1:
            errors.append("candidates preserve the same groups and boundaries; differences are only element/CSS order or finishes, not a new layout relation")
    return errors
