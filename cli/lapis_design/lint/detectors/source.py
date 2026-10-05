"""Source-layer detectors: what the project's CSS, markup, scripts, and package manifests say.

Registered here: css-font-family, css-literal-color, css-off-scale-value, source-pattern, source-ast,
and dependency-check. Each reads the tree under `ctx.source_root`; css-font-family also reads the
contract families from the plan's type roles and the fonts lock, and css-off-scale-value the
contract scales from the plan's tokens (and, for scales the plan has no token for, from the
project's own token definitions).

The tree is read as text by a tolerant tokenizer, not by a parser (no dependency beyond the
standard library). Its limits:
- Comments are blanked first (CSS `/* */`; `//` lines in SCSS, Sass, Less, and Stylus; HTML
  `<!-- -->`; JS and TS comments outside strings, template literals, and regex literals), keeping
  every offset, so locations are the file's own lines. A regex literal is recognized only where an
  expression can start; JSX text holding `//` or a lone quote is read approximately.
- Markup (HTML, Vue, Svelte, Astro, and JSX in .js/.jsx/.tsx/.mjs/.cjs; never .ts) is read tag by
  tag: attributes with quoted, bare, or `{expression}` values (nested braces included), spread
  props, and an element stack. There is no DOM: omitted closing tags and markup assembled from
  strings are read approximately.
- CSS is read declaration by declaration (`property: value` up to `;` or a brace) in style files,
  `<style>` blocks, `style="..."` attributes, and CSS tagged template literals; JS style objects as
  `key: 'value'` or `key: number` pairs whose key is a CSS property; Tailwind arbitrary values
  (`p-[13px]`, `bg-[#fff]`) anywhere.
- Not read: dependency, build, cache, and hidden folders, minified bundles, declaration files,
  source maps, tests and stories, and files over 1 MB.
A value the text alone cannot settle (`var()`, `calc()`, relative units, spread props) is not
judged. Where a query cannot judge some elements, its result also carries a skipped reason naming
them, so an unread element never reads as a pass.
"""
from __future__ import annotations

import bisect
import html
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Iterator

import yaml

from lapis_design import shared_dir, system_fonts
from lapis_design.lint.types import Context, Hit, Result, detector
from lapis_design.plan_check import resolve

MAX_BYTES = 1_000_000
MAX_REFS = 50

_STYLE = {".css", ".scss", ".sass", ".less", ".styl", ".pcss", ".postcss"}
_STYLE_LINE_COMMENTS = {".scss", ".sass", ".less", ".styl"}
_HTML = {".html", ".htm"}
_SFC = {".vue", ".svelte", ".astro"}
_SCRIPT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}
_JSX = {".js", ".jsx", ".tsx", ".mjs", ".cjs"}               # scripts that may hold JSX markup
_SKIP_DIRS = {"node_modules", "bower_components", "jspm_packages", "vendor", "dist", "build", "out", "target",
              "obj", "Pods", "DerivedData", "coverage", "storybook-static", "__tests__", "__mocks__",
              "__pycache__", "venv"}
_SKIP_FILE = re.compile(r"\.(?:min|test|spec|stories|story)\.[^.]+$|\.d\.[cm]?ts$", re.I)
_LOCKFILES = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock",
              "bun.lockb")


# ================================================================ reading the tree

_STR = {q: re.compile(q + r"(?:[^" + q + r"\\\n]|\\[\s\S])*" + q + "?") for q in ("'", '"')}
_JS_NEXT = re.compile(r"[/'\"`{}]")
_TPL_NEXT = re.compile(r"[\\`$]")
_REGEX_LITERAL = re.compile(r"/(?![*/])(?:[^/\\\[\n]|\\.|\[(?:[^\]\\\n]|\\.)*\])+/[A-Za-z]*")
_REGEX_AFTER = set("(,=:[!&|?{};+-*%~^")
_REGEX_KEYWORDS = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw",
                   "yield", "await", "instanceof"}
_LAST_WORD = re.compile(r"([A-Za-z_$][\w$]*)$")
_CSS_NEXT = re.compile(r"/\*|//|['\"]|url\(", re.I)
_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
_BLOCK = re.compile(r"<(script|style)\b([^>]*)>(.*?)</\1\s*>", re.S | re.I)
_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---", re.S)
# the tag right before a CSS template literal: css`, styled.div`, styled(Link)`, styled.a.attrs({...})`,
# createGlobalStyle<Props>`, or the body of <style jsx>{`...`}
_CSS_TEMPLATE_TAG = re.compile(
    r"(?:(?<![\w$.])(?:css|createGlobalStyle|keyframes|injectGlobal|styled(?:\.\w+|\([^()`]*\))(?:\.attrs\([^`]*\))?)"
    r"\s*(?:<[^`<>]*>)?|<style\b[^>]*>\s*\{)\s*$")


def _regex_can_start(text: str, i: int, start: int) -> bool:
    j = i - 1
    while j >= start and text[j] in " \t\r\n":
        j -= 1
    if j < start:
        return True
    ch = text[j]
    if ch in _REGEX_AFTER:
        return True
    if ch == ">":
        return j > start and text[j - 1] == "="            # `=>` starts an expression; a JSX `>` does not
    if ch.isalnum() or ch in "_$":
        m = _LAST_WORD.search(text, max(start, j - 20), j + 1)
        return bool(m) and m.group(1) in _REGEX_KEYWORDS
    return False


def _template_end(text: str, i: int, end: int, comments: list | None = None,
                  templates: list | None = None) -> int:
    """End of the template literal whose backtick is at i (the index after the closing backtick)."""
    j = i + 1
    while True:
        m = _TPL_NEXT.search(text, j, end)
        if not m:
            if templates is not None:
                templates.append((i, i + 1, end))
            return end
        k = m.start()
        ch = text[k]
        if ch == "\\":
            j = k + 2
        elif ch == "`":
            if templates is not None:
                templates.append((i, i + 1, k))
            return k + 1
        elif k + 1 < end and text[k + 1] == "{":
            j = _js_code(text, k + 2, end, comments, templates, closing=True)
        else:
            j = k + 1


def _js_code(text: str, i: int, end: int, comments: list | None, templates: list | None,
             closing: bool = False) -> int:
    """Scan JS code from i; with `closing`, stop after the `}` that closes a template `${`."""
    depth = 0
    while True:
        m = _JS_NEXT.search(text, i, end)
        if not m:
            return end
        k = m.start()
        ch = text[k]
        if ch == "/":
            nxt = text[k + 1] if k + 1 < end else ""
            if nxt == "/":
                e = text.find("\n", k, end)
                e = end if e < 0 else e
                if comments is not None:
                    comments.append((k, e))
                i = e
            elif nxt == "*":
                e = text.find("*/", k + 2, end)
                e = end if e < 0 else e + 2
                if comments is not None:
                    comments.append((k, e))
                i = e
            elif _regex_can_start(text, k, 0):
                r = _REGEX_LITERAL.match(text, k, end)
                i = r.end() if r else k + 1
            else:
                i = k + 1
        elif ch in "'\"":
            i = _STR[ch].match(text, k, end).end()
        elif ch == "`":
            i = _template_end(text, k, end, comments, templates)
        elif ch == "{":
            depth += 1
            i = k + 1
        else:
            if closing and depth == 0:
                return k + 1
            depth -= 1
            i = k + 1


def _css_comments(text: str, start: int, end: int, line_comments: bool) -> list[tuple[int, int]]:
    out = []
    i = start
    while True:
        m = _CSS_NEXT.search(text, i, end)
        if not m:
            return out
        s, tok = m.start(), m.group()
        if tok == "/*":
            e = text.find("*/", s + 2, end)
            e = end if e < 0 else e + 2
            out.append((s, e))
            i = e
        elif tok == "//":
            if line_comments and (s == start or text[s - 1] in " \t\n;{}"):
                e = text.find("\n", s, end)
                e = end if e < 0 else e
                out.append((s, e))
                i = e
            else:
                i = s + 2
        elif tok in "'\"":
            i = _STR[tok].match(text, s, end).end()
        else:
            e = text.find(")", s, end)
            i = end if e < 0 else e + 1


def _mask(text: str, spans: Iterable[tuple[int, int]]) -> str:
    """Replace each span with spaces, keeping line breaks, so offsets stay those of the file."""
    out, last = [], 0
    for s, e in sorted(spans):
        s = max(s, last)
        if e <= s:
            continue
        out.append(text[last:s])
        out.append(re.sub(r"[^\n]", " ", text[s:e]))
        last = e
    out.append(text[last:])
    return "".join(out)


@dataclass
class _Attr:
    name: str
    value: str | None          # quoted text, expression text without braces, bare text; None: boolean
    expr: bool                 # the value was a {expression}
    start: int                 # the value's span in the file (the name's span when boolean)
    end: int


@dataclass
class _Tag:
    name: str
    start: int
    end: int
    attrs: list[_Attr]
    spread: bool = False       # `{...props}`: attributes the text cannot see
    closing: bool = False
    self_closing: bool = False
    parents: tuple[int, ...] = ()   # indexes of the open ancestors in the file's tag list
    close: int | None = None        # index of the matching closing tag

    def attr(self, *names: str) -> _Attr | None:
        wanted = {n.lower() for n in names}
        for a in self.attrs:
            if _attr_key(a.name) in wanted:
                return a
        return None


_TAG_OPEN = re.compile(r"<(/?)([A-Za-z][\w.:-]*)")
_ATTR_NAME = re.compile(r"[\w:@.#*\[\]()|$-]+")
_BARE_VALUE = re.compile(r"[^\s>]+")
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
         "track", "wbr"}


def _attr_key(name: str) -> str:
    n = name.lower()
    for prefix in ("v-bind:", "bind:", ":", "[attr.", "["):
        if n.startswith(prefix):
            n = n[len(prefix):]
            break
    return n.rstrip("]")


_BRACKETS: dict[str, re.Pattern] = {}


def _balanced(code: str, j: int, end: int, open_: str = "{", close: str = "}") -> int:
    """Index after the bracket that closes the one at j, or -1."""
    pattern = _BRACKETS.get(open_ + close) or _BRACKETS.setdefault(
        open_ + close, re.compile("[" + re.escape(open_ + close) + "'\"`]"))
    depth, i = 0, j
    while True:
        m = pattern.search(code, i, end)
        if not m:
            return -1
        k, ch = m.start(), m.group()
        if ch in "'\"":
            i = _STR[ch].match(code, k, end).end()
        elif ch == "`":
            i = _template_end(code, k, end)
        elif ch == open_:
            depth += 1
            i = k + 1
        else:
            depth -= 1
            if depth == 0:
                return k + 1
            i = k + 1


def _scan_tags(code: str) -> list[_Tag]:
    tags: list[_Tag] = []
    end, pos = len(code), 0
    while True:
        m = _TAG_OPEN.search(code, pos)
        if not m:
            break
        name, j = m.group(2), m.end()
        if m.group(1):
            k = code.find(">", j)
            if k < 0:
                break
            tags.append(_Tag(name, m.start(), k + 1, [], closing=True))
            pos = k + 1
            continue
        attrs: list[_Attr] = []
        spread = ok = self_closing = False
        while j < end:
            while j < end and code[j] in " \t\r\n":
                j += 1
            if j >= end:
                break
            ch = code[j]
            if ch == ">":
                ok, j = True, j + 1
                break
            if code.startswith("/>", j):
                ok = self_closing = True
                j += 2
                break
            if ch == "{":
                k = _balanced(code, j, end)
                if k < 0:
                    break
                inner = code[j + 1:k - 1].strip()
                if inner.startswith("..."):
                    spread = True
                else:
                    attrs.append(_Attr(inner, inner, True, j + 1, k - 1))
                j = k
                continue
            am = _ATTR_NAME.match(code, j)
            if not am or j == m.end():
                break                                   # not a tag: `a<b;`, a generic, a comparison
            aname, j = am.group(), am.end()
            if aname == "v-bind":
                spread = True                           # v-bind="obj" binds every key of obj
            k = j
            while k < end and code[k] in " \t\r\n":
                k += 1
            if k < end and code[k] == "=":
                k += 1
                while k < end and code[k] in " \t\r\n":
                    k += 1
                if k >= end:
                    break
                q = code[k]
                if q in "\"'":
                    e = code.find(q, k + 1)
                    if e < 0:
                        break
                    attrs.append(_Attr(aname, code[k + 1:e], False, k + 1, e))
                    j = e + 1
                elif q == "{":
                    e = _balanced(code, k, end)
                    if e < 0:
                        break
                    attrs.append(_Attr(aname, code[k + 1:e - 1], True, k + 1, e - 1))
                    j = e
                else:
                    vm = _BARE_VALUE.match(code, k)
                    value = vm.group().removesuffix("/") if vm else ""
                    attrs.append(_Attr(aname, value, False, k, k + len(value)))
                    j = k + len(value)
            else:
                attrs.append(_Attr(aname, None, False, am.start(), am.end()))
        if ok:
            tags.append(_Tag(name, m.start(), j, attrs, spread=spread, self_closing=self_closing))
            pos = j
        else:
            pos = m.end()
    stack: list[int] = []
    for i, tag in enumerate(tags):
        if tag.closing:
            for depth in range(len(stack) - 1, -1, -1):
                if tags[stack[depth]].name == tag.name:
                    tags[stack[depth]].close = i
                    del stack[depth:]
                    break
            continue
        tag.parents = tuple(stack)
        if not tag.self_closing and tag.name.lower() not in _VOID:
            stack.append(i)
    return tags


@dataclass
class _File:
    rel: str
    ext: str
    text: str
    code: str                                   # comments blanked; same offsets as text
    styles: list[tuple[int, int]]               # CSS regions
    scripts: list[tuple[int, int]]              # JS regions
    templates: list[tuple[int, int, int]]       # JS template literals: (backtick, content start, end)
    starts: list[int]
    _tags: list[_Tag] | None = None

    @property
    def has_markup(self) -> bool:
        return self.ext in _HTML or self.ext in _SFC or self.ext in _JSX

    def line(self, offset: int) -> int:
        return bisect.bisect_right(self.starts, offset)

    def where(self, offset: int) -> str:
        return f"{self.rel}:{self.line(offset)}"

    def line_span(self, offset: int) -> tuple[int, int]:
        s = self.starts[self.line(offset) - 1]
        e = self.code.find("\n", offset)
        return s, len(self.code) if e < 0 else e

    def tags(self) -> list[_Tag]:
        if self._tags is None:
            self._tags = _scan_tags(self.code) if self.has_markup else []
        return self._tags

    def css_regions(self) -> list[tuple[int, int]]:
        """Style files, <style> blocks, style="..." attributes, and CSS tagged template literals."""
        out = list(self.styles)
        if self.ext in _HTML or self.ext in _SFC:
            out += [(a.start, a.end) for t in self.tags() for a in t.attrs
                    if not a.expr and a.value and _attr_key(a.name) == "style"]
        for tick, s, e in self.templates:
            if _CSS_TEMPLATE_TAG.search(self.code, max(0, tick - 200), tick):
                out.append((s, e))
        return out

    def script_regions(self) -> list[tuple[int, int]]:
        return self.scripts


def _load(path: Path, rel: str) -> _File | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > MAX_BYTES:
        return None
    text = raw.decode("utf-8", errors="replace")
    ext = path.suffix.lower()
    comments: list[tuple[int, int]] = []
    templates: list[tuple[int, int, int]] = []
    styles: list[tuple[int, int]] = []
    scripts: list[tuple[int, int]] = []
    if ext in _STYLE:
        comments = _css_comments(text, 0, len(text), ext in _STYLE_LINE_COMMENTS)
        styles = [(0, len(text))]
    elif ext in _SCRIPT:
        _js_code(text, 0, len(text), comments, templates)
        scripts = [(0, len(text))]
    else:
        comments = [m.span() for m in _HTML_COMMENT.finditer(text)]
        masked = _mask(text, comments)
        if ext == ".astro" and (fm := _FRONTMATTER.match(masked)):
            scripts.append(fm.span(1))
        for m in _BLOCK.finditer(masked):
            s, e = m.span(3)
            if m.group(1).lower() == "script":
                scripts.append((s, e))
            else:
                styles.append((s, e))
                lang = re.search(r"lang\s*=\s*[\"']?(scss|sass|less|stylus)", m.group(2), re.I)
                comments += _css_comments(masked, s, e, bool(lang))
        for s, e in scripts:
            _js_code(masked, s, e, comments, templates)
    code = _mask(text, comments)
    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    return _File(rel, ext, text, code, styles, scripts, templates, starts)


@dataclass
class _Tree:
    root: Path
    files: list[_File]
    manifests: dict[str, dict]                   # rel path -> parsed package.json
    locks: dict[str, set[str] | None]            # rel path -> installed package names; None: unreadable
    decls: list[_Decl] | None = None             # CSS declarations, read on first use


def _source_name(name: str) -> bool:
    """Whether the tree reads a file of this name: a manifest, a lockfile, or style, markup, or script source."""
    if name == "package.json" or name in _LOCKFILES:
        return True
    return Path(name).suffix.lower() in _STYLE | _HTML | _SFC | _SCRIPT and not _SKIP_FILE.search(name)


def _tree(ctx: Context) -> _Tree | str:
    """The source tree, read once per run; a string says why it cannot be read. A file that is a link
    resolving outside the source root is not read, and a folder that is a link is never followed; their
    paths (a folder's with a trailing `/`) are listed in `ctx.cache["source.skipped_links"]`."""
    root = ctx.source_root
    if root is None:
        return "no source tree given"
    root = Path(root)
    if not root.is_dir():
        return f"source root {root} is not a directory"
    key = ("source.tree", str(root.resolve()))
    if key in ctx.cache:
        return ctx.cache[key]
    files: list[_File] = []
    manifests: dict[str, dict] = {}
    locks: dict[str, set[str] | None] = {}
    skipped: list[str] = ctx.cache.setdefault("source.skipped_links", [])
    real_root = root.resolve()
    walk = (os.walk(root) if ctx.source_files is None else
            [(str((root / name).parent), [], [(root / name).name]) for name in ctx.source_files])
    for dirpath, dirnames, filenames in walk:      # selected draft files never widen to their containing folder
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS)
        skipped += [(Path(dirpath) / d).relative_to(root).as_posix() + "/"
                    for d in dirnames if (Path(dirpath) / d).is_symlink()]
        for name in sorted(filenames):
            if not _source_name(name):
                continue
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink() and not path.resolve().is_relative_to(real_root):
                skipped.append(rel)
                continue
            if name == "package.json":
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    doc = None
                if isinstance(doc, dict):
                    manifests[rel] = doc
                continue
            if name in _LOCKFILES:
                locks[rel] = _lock_names(path)
                continue
            f = _load(path, rel)
            if f is not None:
                files.append(f)
    tree = _Tree(root, files, manifests, locks)
    ctx.cache[key] = tree
    return tree


def _hit(f: _File, offset: int, observed: str, refs: list[str] | None = None) -> Hit:
    where = f.where(offset)
    return Hit(observed=observed, location={"file": where}, evidence="source", refs=refs or [where])


def _grouped_hit(occurrences: list[tuple[_File, int]], observed: str) -> Hit:
    refs = list(dict.fromkeys(f.where(o) for f, o in occurrences))
    extra = len(refs) - MAX_REFS
    refs = refs[:MAX_REFS] + ([f"... {extra} more"] if extra > 0 else [])
    f, o = occurrences[0]
    return Hit(observed=observed, location={"file": f.where(o)}, evidence="source", refs=refs)


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {plural or word + 's'}"


# ================================================================ CSS declarations

_DECL = re.compile(r"(?<![\w$@-])(--[\w-]+|[a-zA-Z][\w-]*)\s*:\s*([^;{}]*)")
_SCSS_VAR = re.compile(r"(?<![\w-])([$@][\w-]+)\s*:\s*([^;{}]*)")
_THEME_BLOCK = re.compile(r"@theme\b[^{]*\{")
_FONT_FACE = re.compile(r"@font-face\s*\{")
_JS_PAIR = re.compile(r"(?<![\w$.-])([a-zA-Z]+)\s*:\s*(?:(['\"`])((?:(?!\2)[^\n])*)\2|(-?\d+(?:\.\d+)?)(?![\w.]))")


@dataclass
class _Decl:
    file: _File
    offset: int                 # the property's offset
    prop: str                   # kebab-case property, `--custom`, or `$var`/`@var`
    value: str
    value_offset: int
    token: bool                 # a token definition: custom property, preprocessor variable, @theme entry
    js: bool = False            # read from a JS style object (numbers are px)


def _camel_to_kebab(name: str) -> str:
    return re.sub(r"[A-Z]", lambda m: "-" + m.group().lower(), name)


def _block_spans(code: str, start: int, end: int, opener: re.Pattern) -> list[tuple[int, int]]:
    out = []
    for m in opener.finditer(code, start, end):
        close = _balanced(code, m.end() - 1, end)
        out.append((m.start(), end if close < 0 else close))
    return out


def _declarations(tree: _Tree) -> list[_Decl]:
    if tree.decls is not None:
        return tree.decls
    out: list[_Decl] = []
    for f in tree.files:
        for s, e in f.css_regions():
            faces = _block_spans(f.code, s, e, _FONT_FACE)
            themes = _block_spans(f.code, s, e, _THEME_BLOCK)
            for m in _DECL.finditer(f.code, s, e):
                prop, at = m.group(1), m.start()
                if any(a <= at < b for a, b in faces):
                    continue
                token = prop.startswith("--") or any(a <= at < b for a, b in themes)
                out.append(_Decl(f, at, prop if prop.startswith("--") else prop.lower(), m.group(2).strip(),
                                 m.start(2), token))
            for m in _SCSS_VAR.finditer(f.code, s, e):
                out.append(_Decl(f, m.start(), m.group(1), m.group(2).strip(), m.start(2), True))
        for s, e in f.script_regions():
            for m in _JS_PAIR.finditer(f.code, s, e):
                prop = _camel_to_kebab(m.group(1))
                if prop not in _CSS_PROPS:
                    continue
                if m.group(4) is not None:
                    value, vo = m.group(4), m.start(4)
                else:
                    value, vo = m.group(3), m.start(3)
                    if "${" in value:
                        continue
                out.append(_Decl(f, m.start(), prop, value, vo, False, js=True))
    tree.decls = out
    return out


# CSS properties read from JS style objects (kebab-case)
_COLOR_PROPS = {"color", "background", "background-color", "background-image", "border", "border-color",
                "border-top", "border-right", "border-bottom", "border-left", "border-top-color",
                "border-right-color", "border-bottom-color", "border-left-color", "border-block-color",
                "border-inline-color", "outline", "outline-color", "box-shadow", "text-shadow", "fill",
                "stroke", "caret-color", "accent-color", "text-decoration", "text-decoration-color",
                "column-rule", "column-rule-color", "stop-color", "flood-color", "lighting-color",
                "scrollbar-color", "text-emphasis-color", "-webkit-text-fill-color",
                "-webkit-text-stroke-color"}
_SPACE_PROPS = {"margin", "padding", "gap", "row-gap", "column-gap", "grid-gap", "grid-row-gap",
                "grid-column-gap"} | {f"{p}-{s}" for p in ("margin", "padding")
                                      for s in ("top", "right", "bottom", "left", "inline", "block",
                                                "inline-start", "inline-end", "block-start", "block-end")}
_RADIUS_PROPS = {"border-radius"} | {f"border-{c}-radius" for c in (
    "top-left", "top-right", "bottom-left", "bottom-right", "start-start", "start-end", "end-start", "end-end")}
_CSS_PROPS = _COLOR_PROPS | _SPACE_PROPS | _RADIUS_PROPS | {"font-family", "font-size", "font"}


# ================================================================ css-font-family

# CSS-wide keywords take a value from elsewhere; they are not generic families, so the table in
# fonts/system-fonts.yaml does not list them.
_CSS_WIDE_KEYWORDS = frozenset({"inherit", "initial", "unset", "revert", "revert-layer"})
_EMOJI_FALLBACKS = {"Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji"}
_FONT_SYSTEM_KEYWORDS = {"caption", "icon", "menu", "message-box", "small-caption", "status-bar"}
_FONT_SIZE_TOKEN = re.compile(
    r"^(?:\d*\.?\d+(?:px|rem|em|%|pt|pc|vw|vh|vmin|vmax|ex|ch|q|mm|cm|in|lh|rlh|cqw|cqh)|xx-small|x-small|small|"
    r"medium|large|x-large|xx-large|xxx-large|smaller|larger)(?:/\S+)?$", re.I)
_FONT_CUSTOM_PROP = re.compile(r"(?i)^--[\w-]*(?:font|family)[\w-]*$")
_FONT_CUSTOM_NOT = re.compile(r"(?i)size|weight|feature|variation|style|stretch|leading|tracking|line|"
                              r"spacing|smoothing|synthesis|kerning|optical")
_JS_FONT_FAMILY = re.compile(r"(?<![\w$.-])fontFamily\s*:\s*(?:(['\"`])((?:(?!\1)[^\n])*)\1|(\[)|(\{))")
_JS_FAMILY_ENTRY = re.compile(r"(?:[\w$-]+|(['\"])[^'\"\n]+\1)\s*:\s*(?:\[([^\]]*)\]|(['\"])([^'\"\n]*)\3)")
_QUOTED = re.compile(r"(['\"`])((?:(?!\1)[^\n])*)\1")
_TW_FONT = re.compile(r"(?<![\w-])font-\[([^\]\s]+)\]")
_NEXT_FONT = re.compile(r"\bimport\s*\{([^}]*)\}\s*from\s*['\"]next/font/google['\"]")
_HOSTED_CSS = re.compile(r"(?:fonts\.googleapis\.com|fonts\.bunny\.net)/css2?\?[^\"'\s)`]*")
_FONTSOURCE = re.compile(r"['\"]@fontsource(?:-variable)?/([\w-]+)")


def _family_key(name: str) -> str:
    key = re.sub(r"[\s_-]+", "", name.strip().strip("'\"").casefold())
    stripped = re.sub(r"(?:variable|vf)$", "", key)
    return stripped or key


def _names_no_face(name: str) -> bool:
    """A CSS-wide keyword or a generic family of fonts/system-fonts.yaml: there is no face to check."""
    folded = name.strip().casefold()
    return folded in _CSS_WIDE_KEYWORDS or folded in system_fonts.generic_families()


def _split_top(value: str, sep: str = ",") -> list[str]:
    parts, depth, quote, cur = [], 0, "", []
    for ch in value:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts]


def _family_list(value: str) -> list[str] | None:
    """Families of a font-family value, in order; None when a var(), function, or interpolation decides."""
    v = re.sub(r"!\s*important", "", value).strip()
    if not v or "(" in v or "${" in v or "{" in v:
        return None
    return [p.strip("'\"").strip() for p in _split_top(v) if p.strip("'\"").strip()]


def _shorthand_families(value: str) -> list[str] | None:
    v = re.sub(r"!\s*important", "", value).strip()
    if not v or "(" in v or "${" in v or v.lower() in _FONT_SYSTEM_KEYWORDS or _names_no_face(v):
        return None
    tokens = list(re.finditer(r"\"[^\"]*\"|'[^']*'|[^\s,]+|,", v))
    for i, t in enumerate(tokens):
        if _FONT_SIZE_TOKEN.match(t.group()):
            rest = v[t.end():].strip()
            if rest.startswith("/"):
                rest = re.sub(r"^/\s*\S+", "", rest).strip()
            return _family_list(rest) if rest else None
    return None


@dataclass
class _FamilyUse:
    file: _File
    offset: int
    family: str
    primary: bool               # the first family of its stack, or a loaded face


def _family_uses(tree: _Tree) -> list[_FamilyUse]:
    uses: list[_FamilyUse] = []

    def add(f: _File, offset: int, families: list[str] | None, loaded: bool = False) -> None:
        for i, fam in enumerate(families or []):
            if _names_no_face(fam):
                continue
            uses.append(_FamilyUse(f, offset, fam, loaded or i == 0))

    for d in _declarations(tree):
        if d.prop == "font-family":
            add(d.file, d.offset, _family_list(d.value))
        elif d.prop == "font" and not d.js:
            add(d.file, d.offset, _shorthand_families(d.value))
        elif (d.prop.startswith("--") and _FONT_CUSTOM_PROP.match(d.prop)
              and not _FONT_CUSTOM_NOT.search(d.prop)):
            fams = _family_list(d.value)
            if fams and not re.match(r"^[\d.]|^(?:normal|bold|bolder|lighter|italic|oblique)$", fams[0], re.I):
                add(d.file, d.offset, fams)
    for f in tree.files:
        for s, e in f.script_regions():
            for m in _JS_FONT_FAMILY.finditer(f.code, s, e):
                if m.group(2) is not None:
                    continue                            # a plain string: read as a style declaration
                close = _balanced(f.code, m.end() - 1, e, *("[]" if m.group(3) else "{}"))
                body = f.code[m.end() - 1:close if close > 0 else e]
                if m.group(3):
                    add(f, m.start(), [q.group(2) for q in _QUOTED.finditer(body)])
                    continue
                for entry in _JS_FAMILY_ENTRY.finditer(body, 1):
                    if entry.group(2) is not None:
                        add(f, m.start(), [q.group(2) for q in _QUOTED.finditer(entry.group(2))])
                    else:
                        add(f, m.start(), _family_list(entry.group(4)))
            for m in _NEXT_FONT.finditer(f.code, s, e):
                for name in m.group(1).split(","):
                    name = name.split(" as ")[0].strip()
                    if name and name != "type":
                        add(f, m.start(), [name.replace("_", " ")], loaded=True)
            for m in _FONTSOURCE.finditer(f.code, s, e):
                add(f, m.start(), [m.group(1).replace("-", " ")], loaded=True)
        for m in _TW_FONT.finditer(f.code):
            inner = m.group(1).replace("_", " ")
            if re.match(r"^[\d.]|^var\(|^--", inner):
                continue
            add(f, m.start(), _family_list(inner))
        for m in _HOSTED_CSS.finditer(f.code):
            for fam in re.findall(r"family=([^&:;]+)", m.group()):
                add(f, m.start(), [re.sub(r"%20|\+", " ", fam)], loaded=True)
    return uses


@lru_cache(maxsize=1)
def _system_families() -> frozenset[str]:
    try:
        doc = yaml.safe_load((shared_dir() / "fonts" / "system-fonts.yaml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    return frozenset(_family_key(f["family"]) for f in (doc or {}).get("fonts", []) if f.get("family"))


@detector("css-font-family", layers=("source",))
def css_font_family(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    tree = _tree(ctx)
    if isinstance(tree, str):
        return Result(skipped=tree)
    if not tree.files:
        return Result(skipped="no CSS, markup, or script files under the source tree")
    contract: dict[str, str] = {}
    fallbacks: set[str] = set()
    if ctx.plan:
        for fam in resolve(ctx.plan, "tokens.type.roles[*].family"):
            if isinstance(fam, str):
                contract.setdefault(_family_key(fam), fam)
        for change in ctx.plan.get("proposed_design_changes") or []:
            if isinstance(change.get("to"), str):
                contract.setdefault(_family_key(change["to"]), change["to"])
    if ctx.lock:
        for entry in ctx.lock.get("fonts") or []:
            if entry.get("family"):
                contract.setdefault(_family_key(entry["family"]), entry["family"])
            fallbacks |= {_family_key(x) for x in entry.get("fallback") or []}
    if not contract:
        return Result(skipped="no contract families: give a plan with tokens.type.roles or a fonts lock")
    allowed_fallback = set(contract) | fallbacks | _system_families() | {_family_key(x) for x in _EMOJI_FALLBACKS}
    groups: dict[str, list[_FamilyUse]] = {}
    for use in _family_uses(tree):
        groups.setdefault(_family_key(use.family), []).append(use)
    names = ", ".join(sorted(contract.values()))
    hits = []
    for key, uses in groups.items():
        if key in contract:
            continue
        primary = [u for u in uses if u.primary]
        if primary:
            observed = (f"font family {primary[0].family!r} is not a contract family (contract: {names}); "
                        f"{_plural(len(uses), 'use')}")
            ordered = primary + [u for u in uses if not u.primary]
        elif key not in allowed_fallback:
            observed = (f"fallback font family {uses[0].family!r} is neither a contract family, a locked "
                        f"fallback, nor a system font; {_plural(len(uses), 'use')}")
            ordered = uses
        else:
            continue
        hits.append(_grouped_hit([(u.file, u.offset) for u in ordered], observed))
    return Result(hits=hits)


# ================================================================ css-literal-color

_COLOR_LITERAL = re.compile(
    r"(?<![\w&#-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])"
    r"|(?<![\w-])(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\([^()]*\)", re.I)
_URL = re.compile(r"url\([^)]*\)", re.I)
_TW_COLOR = re.compile(
    r"(?<![\w-])(?:bg|text|border(?:-[trblxyse])?|ring|ring-offset|outline|fill|stroke|from|via|to|decoration|"
    r"shadow|accent|caret|divide|placeholder)-\[(#[0-9a-fA-F]{3,8}|(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)"
    r"\([^\]]*\))\]"
    r"|\[(?:color|background(?:-color)?|border-color|fill|stroke):(#[0-9a-fA-F]{3,8}|[a-z]+\([^\]]*\))\]")
_COLOR_ATTRS = {"color", "fill", "stroke", "stop-color", "stopcolor", "flood-color", "floodcolor",
                "lighting-color", "lightingcolor", "bgcolor"}
_TOKEN_NAME = re.compile(r"^_?(?:design[-_.]?)?(?:tokens?|themes?|variables|vars|palette|colou?rs)$", re.I)
_TOKEN_DIRS = {"tokens", "design-tokens", "theme", "themes"}


def _is_token_file(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1].lower()
    base = name.split(".")[0]
    if name.startswith("tailwind.config.") or _TOKEN_NAME.match(base):
        return True
    if re.search(r"[._-](?:tokens?|theme)\.[^.]+$", name):
        return True
    return any(p.lower() in _TOKEN_DIRS for p in parts[:-1])


def _color_literals(value: str) -> list[re.Match]:
    """Color literals in a value, outside url(); a function holding var() is not a literal."""
    return list(_COLOR_LITERAL.finditer(_URL.sub(lambda m: " " * len(m.group()), value)))


@detector("css-literal-color", layers=("source",))
def css_literal_color(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    tree = _tree(ctx)
    if isinstance(tree, str):
        return Result(skipped=tree)
    if not tree.files:
        return Result(skipped="no CSS, markup, or script files under the source tree")
    groups: dict[str, dict[tuple[str, int], tuple[_File, int, str]]] = {}

    def add(f: _File, offset: int, literal: str, where: str) -> None:
        key = re.sub(r"\s+", " ", literal.lower())
        groups.setdefault(key, {}).setdefault((f.rel, offset), (f, offset, where))

    token_files = {f.rel for f in tree.files if _is_token_file(f.rel)}
    for d in _declarations(tree):
        if d.token or d.file.rel in token_files or (d.js and d.prop not in _COLOR_PROPS):
            continue
        for m in _color_literals(d.value):
            add(d.file, d.value_offset + m.start(), m.group(), d.prop)
    for f in tree.files:
        if f.rel in token_files:
            continue
        for m in _TW_COLOR.finditer(f.code):
            group = 1 if m.group(1) else 2
            add(f, m.start(group), m.group(group), m.group())
        for tag in f.tags():
            for a in tag.attrs:
                if a.value and not a.expr and _attr_key(a.name) in _COLOR_ATTRS:
                    for m in _color_literals(a.value):
                        add(f, a.start + m.start(), m.group(), f"{a.name} attribute")
    hits = []
    for literal, found in groups.items():
        uses = sorted(found.values(), key=lambda u: (u[0].rel, u[1]))
        f, o, where = uses[0]
        hits.append(_grouped_hit([(u[0], u[1]) for u in uses],
                                 f"literal color {literal} outside the token files ({where}); "
                                 f"{_plural(len(uses), 'use')}"))
    return Result(hits=hits)


# ================================================================ css-off-scale-value

_LENGTH = re.compile(r"^(-?)(\d*\.?\d+)(px|rem)?$", re.I)
_TW_SCALE = re.compile(
    r"(?<![\w-])(-?)(p[xytrblse]?|m[xytrblse]?|gap(?:-[xy])?|space-[xy]|rounded(?:-(?:[trblse]|tl|tr|br|bl|ss|se|es|ee))?"
    r"|text)-\[([^\]\s]+)\]")
_TW_CATEGORY = {"p": "padding", "m": "margin", "g": "gap", "s": "margin", "r": "border-radius", "t": "font-size"}
_ROOT_PX = 16.0


def _category(prop: str) -> str | None:
    if prop in _SPACE_PROPS:
        return "padding" if prop.startswith("padding") else "margin" if prop.startswith("margin") else "gap"
    if prop in _RADIUS_PROPS:
        return "border-radius"
    if prop == "font-size":
        return "font-size"
    return None


_SCALE_KIND = {"padding": "space", "margin": "space", "gap": "space", "border-radius": "radius",
               "font-size": "font-size"}


def _px(token: str, js: bool = False) -> float | None:
    m = _LENGTH.match(token.strip())
    if not m:
        return None
    number = float(m.group(2))
    unit = (m.group(3) or "").lower()
    if unit == "rem":
        return number * _ROOT_PX
    if unit == "px" or (js and not unit):
        return number
    return 0.0 if number == 0 else None                 # a unitless non-zero CSS length is invalid


@dataclass
class _Scale:
    kind: str
    values: list[float] = field(default_factory=list)
    base: float | None = None
    relative: bool = False       # tolerance scales with the step (type scale)
    source: str = ""

    def allows(self, v: float) -> bool:
        v = abs(v)
        if v < 1e-9:
            return True
        if self.kind == "radius" and v >= 999:
            return True                                 # a full (pill or circle) radius
        if self.base:
            r = v % self.base
            return min(r, self.base - r) <= 0.5 + 1e-9
        return any(abs(v - s) <= (max(0.5, 0.02 * s) if self.relative else 0.5) + 1e-9 for s in self.values)

    def describe(self) -> str:
        if self.base:
            return f"multiples of {self.base:g}px from {self.source}"
        return f"{', '.join(f'{s:g}' for s in self.values)} px from {self.source}"


_TOKEN_KIND = (("radius", re.compile(r"(?i)radius|rounded")),
               ("font-size", re.compile(r"(?i)font-?size|^--text-|^\$text-|^--fs-|type-?size")),
               ("space", re.compile(r"(?i)spac|gap|gutter")))


def _scales(ctx: Context, tree: _Tree) -> dict[str, _Scale]:
    scales: dict[str, _Scale] = {}
    plan = ctx.plan or {}
    space = ((plan.get("tokens") or {}).get("space") or {})
    if space.get("scale"):
        scales["space"] = _Scale("space", sorted(float(v) for v in space["scale"]), source="plan tokens.space.scale")
    elif space.get("base_px"):
        scales["space"] = _Scale("space", base=float(space["base_px"]), source="plan tokens.space.base_px")
    type_scale = (((plan.get("tokens") or {}).get("type") or {}).get("scale") or {})
    if type_scale.get("base_px") and type_scale.get("ratio"):
        base, ratio = float(type_scale["base_px"]), float(type_scale["ratio"])
        steps = sorted({round(base * ratio ** n, 3) for n in range(-4, 13)} if ratio > 1 else {base})
        scales["font-size"] = _Scale("font-size", steps, relative=True, source="plan tokens.type.scale")
    defined: dict[str, set[float]] = {}
    base_spacing: float | None = None
    for d in _declarations(tree):
        if not d.token:
            continue
        value = _px(d.value)
        if value is None or value <= 0:
            continue
        if d.prop == "--spacing":
            base_spacing = value
            continue
        for kind, pattern in _TOKEN_KIND:
            if pattern.search(d.prop):
                defined.setdefault(kind, set()).add(value)
                break
    for kind in ("space", "radius", "font-size"):
        if kind in scales:
            continue
        if kind in defined:
            scales[kind] = _Scale(kind, sorted(defined[kind]), relative=kind == "font-size",
                                  source="project token definitions")
        elif kind == "space" and base_spacing:
            scales[kind] = _Scale(kind, base=base_spacing, source="project --spacing token")
    return scales


@detector("css-off-scale-value", layers=("source",))
def css_off_scale_value(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    tree = _tree(ctx)
    if isinstance(tree, str):
        return Result(skipped=tree)
    if not tree.files:
        return Result(skipped="no CSS, markup, or script files under the source tree")
    wanted = [str(p).lower() for p in (det.get("params") or {}).get("properties") or []]
    if not wanted:
        return Result(skipped="the rule lists no properties")
    scales = _scales(ctx, tree)
    judged = {p for p in wanted if _SCALE_KIND.get(p) in scales}
    missing: dict[str | None, list[str]] = {}
    for p in wanted:
        if p not in judged:
            missing.setdefault(_SCALE_KIND.get(p), []).append(p)
    notes = [f"{', '.join(props)}: no contract {kind} scale (plan tokens or project token definitions)" if kind
             else f"{', '.join(props)}: no contract scale is known for these properties"
             for kind, props in missing.items()]
    groups: dict[tuple[str, float], list[tuple[_File, int, str, str]]] = {}

    def check(f: _File, offset: int, prop: str, category: str, value: str, js: bool) -> None:
        scale = scales[_SCALE_KIND[category]]
        v = re.sub(r"!\s*important", "", value).strip()
        if not v or "(" in v or "$" in v or "{" in v:
            return
        for token in re.split(r"[\s/]+", v):
            px = _px(token, js)
            if px is None or scale.allows(px):
                continue
            groups.setdefault((category, round(abs(px), 3)), []).append((f, offset, prop, token))

    for d in _declarations(tree):
        if d.token:
            continue
        category = _category(d.prop)
        if category in judged:
            check(d.file, d.offset, d.prop, category, d.value, d.js)
    for f in tree.files:
        for m in _TW_SCALE.finditer(f.code):
            prefix, raw = m.group(2), m.group(3).replace("_", " ")
            category = "gap" if prefix.startswith("gap") else _TW_CATEGORY[prefix[0]]
            if category in judged and _px(raw) is not None:
                check(f, m.start(), m.group(), category, raw, False)
    hits = []
    for (category, px), uses in sorted(groups.items()):
        uses.sort(key=lambda u: (u[0].rel, u[1]))
        scale = scales[_SCALE_KIND[category]]
        f, o, prop, token = uses[0]
        hits.append(_grouped_hit([(u[0], u[1]) for u in uses],
                                 f"{prop} {token}{'' if token == f'{px:g}px' else f' ({px:g}px)'} is off the "
                                 f"contract {scale.kind} scale: {scale.describe()}; {_plural(len(uses), 'use')}"))
    return Result(hits=hits, skipped="; ".join(notes) or None)


# ================================================================ source-pattern

# Extended_Pictographic as ECMAScript engines report it (Unicode 17.0, checked 2026-09-26)
_EXTENDED_PICTOGRAPHIC = (
    (0xA9, 0xA9), (0xAE, 0xAE), (0x203C, 0x203C), (0x2049, 0x2049), (0x2122, 0x2122), (0x2139, 0x2139),
    (0x2194, 0x2199), (0x21A9, 0x21AA), (0x231A, 0x231B), (0x2328, 0x2328), (0x23CF, 0x23CF), (0x23E9, 0x23F3),
    (0x23F8, 0x23FA), (0x24C2, 0x24C2), (0x25AA, 0x25AB), (0x25B6, 0x25B6), (0x25C0, 0x25C0), (0x25FB, 0x25FE),
    (0x2600, 0x2604), (0x260E, 0x260E), (0x2611, 0x2611), (0x2614, 0x2615), (0x2618, 0x2618), (0x261D, 0x261D),
    (0x2620, 0x2620), (0x2622, 0x2623), (0x2626, 0x2626), (0x262A, 0x262A), (0x262E, 0x262F), (0x2638, 0x263A),
    (0x2640, 0x2640), (0x2642, 0x2642), (0x2648, 0x2653), (0x265F, 0x2660), (0x2663, 0x2663), (0x2665, 0x2666),
    (0x2668, 0x2668), (0x267B, 0x267B), (0x267E, 0x267F), (0x2692, 0x2697), (0x2699, 0x2699), (0x269B, 0x269C),
    (0x26A0, 0x26A1), (0x26A7, 0x26A7), (0x26AA, 0x26AB), (0x26B0, 0x26B1), (0x26BD, 0x26BE), (0x26C4, 0x26C5),
    (0x26C8, 0x26C8), (0x26CE, 0x26CF), (0x26D1, 0x26D1), (0x26D3, 0x26D4), (0x26E9, 0x26EA), (0x26F0, 0x26F5),
    (0x26F7, 0x26FA), (0x26FD, 0x26FD), (0x2702, 0x2702), (0x2705, 0x2705), (0x2708, 0x270D), (0x270F, 0x270F),
    (0x2712, 0x2712), (0x2714, 0x2714), (0x2716, 0x2716), (0x271D, 0x271D), (0x2721, 0x2721), (0x2728, 0x2728),
    (0x2733, 0x2734), (0x2744, 0x2744), (0x2747, 0x2747), (0x274C, 0x274C), (0x274E, 0x274E), (0x2753, 0x2755),
    (0x2757, 0x2757), (0x2763, 0x2764), (0x2795, 0x2797), (0x27A1, 0x27A1), (0x27B0, 0x27B0), (0x27BF, 0x27BF),
    (0x2934, 0x2935), (0x2B05, 0x2B07), (0x2B1B, 0x2B1C), (0x2B50, 0x2B50), (0x2B55, 0x2B55), (0x3030, 0x3030),
    (0x303D, 0x303D), (0x3297, 0x3297), (0x3299, 0x3299), (0x1F004, 0x1F004), (0x1F02C, 0x1F02F), (0x1F094, 0x1F09F),
    (0x1F0AF, 0x1F0B0), (0x1F0C0, 0x1F0C0), (0x1F0CF, 0x1F0D0), (0x1F0F6, 0x1F0FF), (0x1F170, 0x1F171), (0x1F17E, 0x1F17F),
    (0x1F18E, 0x1F18E), (0x1F191, 0x1F19A), (0x1F1AE, 0x1F1E5), (0x1F201, 0x1F20F), (0x1F21A, 0x1F21A), (0x1F22F, 0x1F22F),
    (0x1F232, 0x1F23A), (0x1F23C, 0x1F23F), (0x1F249, 0x1F25F), (0x1F266, 0x1F321), (0x1F324, 0x1F393), (0x1F396, 0x1F397),
    (0x1F399, 0x1F39B), (0x1F39E, 0x1F3F0), (0x1F3F3, 0x1F3F5), (0x1F3F7, 0x1F3FA), (0x1F400, 0x1F4FD), (0x1F4FF, 0x1F53D),
    (0x1F549, 0x1F54E), (0x1F550, 0x1F567), (0x1F56F, 0x1F570), (0x1F573, 0x1F57A), (0x1F587, 0x1F587), (0x1F58A, 0x1F58D),
    (0x1F590, 0x1F590), (0x1F595, 0x1F596), (0x1F5A4, 0x1F5A5), (0x1F5A8, 0x1F5A8), (0x1F5B1, 0x1F5B2), (0x1F5BC, 0x1F5BC),
    (0x1F5C2, 0x1F5C4), (0x1F5D1, 0x1F5D3), (0x1F5DC, 0x1F5DE), (0x1F5E1, 0x1F5E1), (0x1F5E3, 0x1F5E3), (0x1F5E8, 0x1F5E8),
    (0x1F5EF, 0x1F5EF), (0x1F5F3, 0x1F5F3), (0x1F5FA, 0x1F64F), (0x1F680, 0x1F6C5), (0x1F6CB, 0x1F6D2), (0x1F6D5, 0x1F6E5),
    (0x1F6E9, 0x1F6E9), (0x1F6EB, 0x1F6F0), (0x1F6F3, 0x1F6FF), (0x1F7DA, 0x1F7FF), (0x1F80C, 0x1F80F), (0x1F848, 0x1F84F),
    (0x1F85A, 0x1F85F), (0x1F888, 0x1F88F), (0x1F8AE, 0x1F8AF), (0x1F8BC, 0x1F8BF), (0x1F8C2, 0x1F8CF), (0x1F8D9, 0x1F8FF),
    (0x1F90C, 0x1F93A), (0x1F93C, 0x1F945), (0x1F947, 0x1F9FF), (0x1FA58, 0x1FA5F), (0x1FA6E, 0x1FAFF), (0x1FC00, 0x1FFFD),
)
_CATEGORY_NAMES = {"letter": "L", "cased_letter": "LC", "uppercase_letter": "Lu", "lowercase_letter": "Ll",
                   "titlecase_letter": "Lt", "modifier_letter": "Lm", "other_letter": "Lo", "mark": "M",
                   "nonspacing_mark": "Mn", "spacing_mark": "Mc", "enclosing_mark": "Me", "number": "N",
                   "decimal_number": "Nd", "digit": "Nd", "letter_number": "Nl", "other_number": "No",
                   "punctuation": "P", "punct": "P", "symbol": "S", "math_symbol": "Sm",
                   "currency_symbol": "Sc", "modifier_symbol": "Sk", "other_symbol": "So", "separator": "Z",
                   "space_separator": "Zs", "other": "C", "control": "Cc", "format": "Cf"}


@lru_cache(maxsize=None)
def _property_class(name: str) -> str:
    """Character-class body for a Unicode property escape; ValueError when it is not supported."""
    key = name.split("=", 1)[1] if name.lower().startswith(("general_category=", "gc=")) else name
    if key in ("Extended_Pictographic", "ExtPict"):
        ranges = _EXTENDED_PICTOGRAPHIC
    else:
        cat = _CATEGORY_NAMES.get(key.lower(), key)
        if not re.fullmatch(r"[LMNPSZC][a-z]?|LC", cat):
            raise ValueError(f"unsupported Unicode property \\p{{{name}}}")
        match = (lambda c: c in ("Lu", "Ll", "Lt")) if cat == "LC" else (lambda c: c.startswith(cat))
        ranges, start = [], None
        for cp in range(0x110000):
            ok = match(unicodedata.category(chr(cp)))
            if ok and start is None:
                start = cp
            elif not ok and start is not None:
                ranges.append((start, cp - 1))
                start = None
        if not ranges:
            raise ValueError(f"unsupported Unicode property \\p{{{name}}}")
    return "".join(f"\\U{a:08X}" if a == b else f"\\U{a:08X}-\\U{b:08X}" for a, b in ranges)


def _translate(pattern: str) -> str:
    """ECMAScript (u flag) pattern syntax that Python's `re` lacks: \\p{..}, \\u{..}, (?<name>, \\k<name>."""
    out, i, n, in_class = [], 0, len(pattern), False
    while i < n:
        c = pattern[i]
        if c == "\\" and i + 1 < n:
            nxt = pattern[i + 1]
            if nxt in "pP" and pattern.startswith("{", i + 2):
                close = pattern.index("}", i + 3)
                body = _property_class(pattern[i + 3:close])
                if nxt == "p":
                    out.append(body if in_class else f"[{body}]")
                elif in_class:
                    raise ValueError("\\P{...} inside a character class is not supported")
                else:
                    out.append(f"[^{body}]")
                i = close + 1
                continue
            if nxt == "u" and pattern.startswith("{", i + 2):
                close = pattern.index("}", i + 3)
                out.append(f"\\U{int(pattern[i + 3:close], 16):08X}")
                i = close + 1
                continue
            if nxt == "k" and pattern.startswith("<", i + 2):
                close = pattern.index(">", i + 3)
                out.append(f"(?P={pattern[i + 3:close]})")
                i = close + 1
                continue
            out.append(pattern[i:i + 2])
            i += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
            out.append(c)
        elif c == "[":
            in_class = True
            out.append(c)
            if pattern.startswith("^", i + 1):
                out.append("^")
                i += 1
            if pattern.startswith("]", i + 1):
                out.append("\\]")
                i += 1
        elif pattern.startswith("(?<", i) and i + 3 < n and pattern[i + 3] not in "=!":
            out.append("(?P<")
            i += 3
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _compile(pattern: str) -> re.Pattern:
    # ECMAScript semantics: \d, \w, and \b are ASCII (so is \s here, a small difference)
    return re.compile(_translate(pattern), re.ASCII)


_ICON_KEY = re.compile(r"(?i)[\w-]*icon[\w-]*['\"]?\s*[:=]\s*\{?\s*['\"`][^'\"`\n]*$")
_CSS_CONTENT = re.compile(r"(?<![\w-])content\s*:\s*[^;{}\n]*$")
_ICON_TAG = re.compile(r"(?i)^<(?:i|[\w.-]*icon[\w.-]*)[\s>/]|\bclass(?:name)?\s*=\s*[{'\"`][^>]*\bicon")
_GLYPH_ONLY = re.compile("[\\s\ufe0e\ufe0f\u200d\U0001F3FB-\U0001F3FF]+")
_LEGAL_MARKS = set("\u00a9\u00ae\u2122")      # (c), (R), TM: marks in running text unless VS16 asks for emoji


def _in_icon_slot(f: _File, s: int, e: int) -> bool:
    """The match sits where an icon goes: an icon prop or key, CSS `content`, an icon element, or alone
    (or leading or trailing a short label) in its text node or string."""
    ls, le = f.line_span(s)
    before, after = f.code[ls:s], f.code[e:le]
    if set(f.code[s:e]) <= _LEGAL_MARKS and not after.startswith("\ufe0f"):
        return False
    if _ICON_KEY.search(before) or _CSS_CONTENT.search(before):
        return True
    lt = before.rfind("<")
    if lt >= 0 and ">" in before[lt:]:
        tag = before[lt:before.index(">", lt) + 1]
        if _ICON_TAG.search(tag) and "<" not in before[before.index(">", lt) + 1:]:
            return True
    left = max(before.rfind(ch) for ch in "'\"`>{}")
    right = min([i for i in (after.find(ch) for ch in "'\"`<{}") if i >= 0] or [len(after)])
    head, tail = before[left + 1:], after[:right]
    if _GLYPH_ONLY.sub("", head) and _GLYPH_ONLY.sub("", tail):
        return False                                    # inside running text
    return len((head + f.code[s:e] + tail).strip()) <= 40


_SCOPES: dict[str, Callable[[_File, int, int], bool]] = {"icon-slots": _in_icon_slot}


@detector("source-pattern", layers=("source",))
def source_pattern(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    params = det.get("params") or {}
    raw_patterns = params.get("patterns") or []
    if not raw_patterns:
        return Result(skipped="the rule lists no patterns")
    scope = params.get("scope")
    if scope is not None and scope not in _SCOPES:
        return Result(skipped=f"unknown scope {scope!r}")
    tree = _tree(ctx)
    if isinstance(tree, str):
        return Result(skipped=tree)
    if not tree.files:
        return Result(skipped="no CSS, markup, or script files under the source tree")
    patterns, notes = [], []
    for p in raw_patterns:
        try:
            patterns.append(_compile(p))
        except (ValueError, re.error) as exc:
            notes.append(f"pattern {p!r} not run: {exc}")
    in_scope = _SCOPES.get(scope)
    hits = []
    for f in tree.files:
        found: dict[int, str] = {}                      # offset -> the longest match there, over all patterns
        for ls, line in zip(f.starts, f.code.split("\n")):
            for pattern in patterns:
                for m in pattern.finditer(line):
                    if m.end() == m.start() or len(found.get(ls + m.start(), "")) >= len(m.group()):
                        continue
                    if in_scope and not in_scope(f, ls + m.start(), ls + m.end()):
                        continue
                    found[ls + m.start()] = m.group()
        if not found:
            continue
        found = dict(sorted(found.items()))
        seen = list(dict.fromkeys(text.strip() for text in found.values()))
        shown = ", ".join(repr(t) for t in seen[:5]) + (f", and {len(seen) - 5} more" if len(seen) > 5 else "")
        hits.append(_grouped_hit([(f, o) for o in found],
                                 f"{shown} in {f.rel}{' (icon slots)' if scope else ''}; "
                                 f"{_plural(len(found), 'match', 'matches')}"))
    return Result(hits=hits, skipped="; ".join(notes) or None)


# ================================================================ source-ast

def _markup_files(tree: _Tree) -> list[_File]:
    return [f for f in tree.files if f.has_markup]


def _unjudged_note(what: str, where: list[str]) -> str | None:
    if not where:
        return None
    shown = ", ".join(where[:5]) + (f", and {len(where) - 5} more" if len(where) > 5 else "")
    return f"{_plural(len(where), what)} not judged, their attributes come from spread props: {shown}"


def _value(a: _Attr | None) -> str | None:
    if a is None:
        return None
    return a.value if a.value is not None else ""


def _literal(a: _Attr | None) -> str | None:
    """The attribute's static text: a quoted value, or a string literal expression."""
    if a is None or a.value is None:
        return None
    if not a.expr:
        return a.value
    m = re.fullmatch(r"\s*(['\"`])([^'\"`]*)\1\s*", a.value)
    return m.group(2) if m else None


# ---- img-without-alt / img-without-intrinsic-size

def _images(tree: _Tree) -> Iterator[tuple[_File, _Tag]]:
    for f in _markup_files(tree):
        for tag in f.tags():
            if not tag.closing and tag.name == "img":
                yield f, tag


def _q_img_without_alt(ctx: Context, tree: _Tree) -> tuple[list[Hit], str | None]:
    hits, unjudged = [], []
    for f, tag in _images(tree):
        if tag.attr("alt") is not None:
            continue
        if tag.spread:
            unjudged.append(f.where(tag.start))
            continue
        src = _literal(tag.attr("src")) or _value(tag.attr("src")) or "?"
        hits.append(_hit(f, tag.start, f"<img> without an alt attribute (src {src[:80]})"))
    return hits, _unjudged_note("image", unjudged)


_SIZE_CLASSES = re.compile(r"(?<![\w-])(?:aspect-|size-)")
_W_CLASS = re.compile(r"(?<![\w-])(?:[\w-]+:)*w-(?!auto\b)\S")
_H_CLASS = re.compile(r"(?<![\w-])(?:[\w-]+:)*h-(?!auto\b)\S")


def _q_img_without_intrinsic_size(ctx: Context, tree: _Tree) -> tuple[list[Hit], str | None]:
    hits, unjudged = [], []
    for f, tag in _images(tree):
        if tag.attr("width") is not None and tag.attr("height") is not None:
            continue
        style = _value(tag.attr("style")) or ""
        if re.search(r"aspect-?ratio", style, re.I):
            continue
        classes = _value(tag.attr("class", "classname")) or ""
        if _SIZE_CLASSES.search(classes) or (_W_CLASS.search(classes) and _H_CLASS.search(classes)):
            continue
        if tag.spread:
            unjudged.append(f.where(tag.start))
            continue
        missing = [a for a in ("width", "height") if tag.attr(a) is None]
        src = _literal(tag.attr("src")) or _value(tag.attr("src")) or "?"
        hits.append(_hit(f, tag.start, f"<img> without {' or '.join(missing)} and no aspect ratio (src {src[:80]})"))
    return hits, _unjudged_note("image", unjudged)


# ---- input-without-associated-label

_UNLABELED_TYPES = {"hidden", "submit", "reset", "button", "image"}


def _q_input_without_label(ctx: Context, tree: _Tree) -> tuple[list[Hit], str | None]:
    hits, unjudged = [], []
    for f in _markup_files(tree):
        tags = f.tags()
        label_for = {(_value(t.attr("for", "htmlfor")) or "").strip() for t in tags
                     if not t.closing and t.name.lower().endswith("label") and t.attr("for", "htmlfor") is not None}
        for tag in tags:
            if tag.closing or tag.name not in ("input", "select", "textarea"):
                continue
            kind = (_literal(tag.attr("type")) or "text").lower() if tag.name == "input" else tag.name
            if kind in _UNLABELED_TYPES:
                continue
            if tag.attr("aria-label", "aria-labelledby", "title") is not None:
                continue
            ident = _value(tag.attr("id"))
            if ident is not None and ident.strip() in label_for:
                continue
            if any(tags[p].name.lower() == "label" for p in tag.parents):
                continue
            if tag.spread:
                unjudged.append(f.where(tag.start))
                continue
            placeholder = _literal(tag.attr("placeholder"))
            name = _literal(tag.attr("name")) or ident or ""
            what = f"<{tag.name}{' type=' + kind if tag.name == 'input' else ''}{' name=' + name if name else ''}>"
            if placeholder:
                hits.append(_hit(f, tag.start, f"{what} whose only label is its placeholder {placeholder!r}"))
            else:
                hits.append(_hit(f, tag.start, f"{what} without an associated label"))
    return hits, _unjudged_note("form field", unjudged)


# ---- click-handler-on-non-interactive-element

_INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "option", "optgroup", "summary", "details",
                     "label", "dialog", "video", "audio", "iframe", "embed", "object", "area", "form", "html",
                     "body", "menuitem"}
_INTERACTIVE_ROLES = {"button", "link", "checkbox", "radio", "switch", "tab", "menuitem", "menuitemcheckbox",
                      "menuitemradio", "option", "treeitem", "slider", "spinbutton", "combobox", "textbox",
                      "searchbox", "gridcell", "row"}
_POINTER_EVENTS = {"click", "mousedown", "mouseup", "pointerdown", "pointerup", "dblclick"}
_KEY_EVENTS = {"keydown", "keyup", "keypress"}
_EVENT_ATTR = re.compile(r"^(?:on([A-Za-z]+)|@([\w-]+)(\.[\w.]+)?|v-on:([\w-]+)(\.[\w.]+)?|on:([\w-]+)(\|[\w|]+)?|\(([\w.-]+)\))$")
_STOP_ONLY = re.compile(r"^\s*(?:\(?\s*\w*\s*\)?\s*=>\s*\{?\s*\w+\.stopPropagation\(\)\s*;?\s*\}?|\w*stopPropagation\w*)\s*$",
                        re.I)


def _event(a: _Attr) -> tuple[str, str] | None:
    m = _EVENT_ATTR.match(a.name)
    if not m:
        return None
    name = next(g for g in (m.group(1), m.group(2), m.group(4), m.group(6), m.group(8)) if g)
    modifiers = m.group(3) or m.group(5) or m.group(7) or ""
    return name.lower(), modifiers


def _q_click_non_interactive(ctx: Context, tree: _Tree) -> tuple[list[Hit], str | None]:
    hits, unjudged = [], []
    for f in _markup_files(tree):
        for tag in f.tags():
            if tag.closing or not tag.name.islower():
                continue                                # closing tags and components
            if tag.name in _INTERACTIVE_TAGS and not (tag.name == "a" and tag.attr("href") is None):
                continue
            events = [(ev[0], a) for a in tag.attrs if (ev := _event(a))]
            real = [a for name, a in events
                    if name in _POINTER_EVENTS and a.value and not _STOP_ONLY.match(a.value)]
            if not real:
                continue                                # no handler, or a modifier-only or stopPropagation one
            if ((_value(tag.attr("aria-hidden")) or "").strip().strip("'\"`").lower()) == "true":
                continue                                # a redundant pointer affordance, hidden on purpose
            role_attr = tag.attr("role")
            role = _literal(role_attr)
            keys = any(name in _KEY_EVENTS for name, _ in events)
            tabindex = tag.attr("tabindex") is not None
            if role in _INTERACTIVE_ROLES and keys and tabindex:
                continue
            if tag.spread or (role_attr is not None and role is None):
                unjudged.append(f.where(tag.start))
                continue
            missing = [x for x, ok in (("an interactive role", role in _INTERACTIVE_ROLES),
                                       ("tabindex", tabindex), ("a key handler", keys)) if not ok]
            lacking = " or ".join(missing) if len(missing) < 3 else f"{missing[0]}, {missing[1]}, or {missing[2]}"
            hits.append(_hit(f, tag.start, f"<{tag.name}> has a {real[0].name} handler without {lacking}"))
    return hits, _unjudged_note("clickable element", unjudged)


# ---- raw-element-where-adopted-primitive-exists

_PRIMITIVES = {"button": ("Button",), "input": ("Input", "TextField"), "checkbox": ("Checkbox",),
               "radio": ("Radio", "RadioGroup"), "range": ("Slider",), "select": ("Select",),
               "textarea": ("Textarea", "TextArea"), "dialog": ("Dialog", "Modal")}
_IMPORT_NAMES = re.compile(r"\bimport\s+(?:type\s+)?(?:([A-Z]\w*)\s*,?\s*)?(?:\{([^}]*)\})?\s*from\s*['\"]([^'\"]+)['\"]")
_DEFINES = r"(?:export\s+(?:default\s+)?)?(?:function|const|let|class)\s+{name}\b|export\s*\{{[^}}]*\b{name}\b"
_TEST_PATH = re.compile(r"(?:^|/)(?:tests?|e2e|stories|fixtures?)/")


def _family(ext: str) -> str:
    return "jsx" if ext in _JSX else ext


def _raw_kind(tag: _Tag) -> str | None:
    if tag.name == "input":
        kind = (_literal(tag.attr("type")) or "text").lower()
        if kind in _UNLABELED_TYPES | {"file", "color"}:
            return None
        return kind if kind in ("checkbox", "radio", "range") else "input"
    return tag.name if tag.name in _PRIMITIVES else None


def _q_raw_element(ctx: Context, tree: _Tree) -> tuple[list[Hit], str | None]:
    # adopted primitives: components the project defines in a file named for them, or imports by name
    adopted: dict[tuple[str, str], str] = {}          # (family, component) -> where it comes from
    definers: dict[str, set[str]] = {}                # component -> files that define it
    names = {n for group in _PRIMITIVES.values() for n in group}
    for f in tree.files:
        if f.ext not in _JSX | _SFC or _TEST_PATH.search(f.rel):
            continue
        stem = re.sub(r"[-_]", "", f.rel.rsplit("/", 1)[-1].split(".")[0]).lower()
        for name in names:
            if stem == name.lower() and (f.ext in _SFC or re.search(_DEFINES.format(name=name), f.code)):
                adopted.setdefault((_family(f.ext), name), f.rel)
                definers.setdefault(name, set()).add(f.rel)
        for m in _IMPORT_NAMES.finditer(f.code):
            bound = [m.group(1) or ""] + [x.split(" as ")[-1].strip() for x in (m.group(2) or "").split(",")]
            for name in bound:
                if name in names:
                    adopted.setdefault((_family(f.ext), name), m.group(3))
    if not adopted:
        return [], None
    hits = []
    for f in _markup_files(tree):
        if f.ext in _HTML or _TEST_PATH.search(f.rel):
            continue
        fam = _family(f.ext)
        for tag in f.tags():
            if tag.closing or not (kind := _raw_kind(tag)):
                continue
            for name in _PRIMITIVES[kind]:
                origin = adopted.get((fam, name))
                if origin and f.rel not in definers.get(name, set()):
                    raw = f"<input type={kind}>" if tag.name == "input" and kind != "input" else f"<{tag.name}>"
                    hits.append(_hit(f, tag.start, f"raw {raw} while the project has a {name} primitive ({origin})"))
                    break
    return hits, None


# ---- inline-svg-path-for-standard-action

_ACTIONS = {"close", "dismiss", "cancel", "xmark", "search", "menu", "hamburger", "bars", "chevron", "arrow",
            "caret", "check", "checkmark", "tick", "plus", "add", "minus", "remove", "edit", "pencil", "delete",
            "trash", "bin", "settings", "gear", "cog", "user", "profile", "account", "home", "share", "copy",
            "clipboard", "download", "upload", "external", "link", "info", "help", "question", "warning",
            "alert", "error", "heart", "like", "favorite", "star", "bookmark", "filter", "sort", "more",
            "ellipsis", "dots", "kebab", "calendar", "bell", "notification", "mail", "email", "envelope",
            "send", "refresh", "reload", "sync", "play", "pause", "stop", "next", "prev", "previous", "back",
            "forward", "expand", "collapse", "logout", "login", "signin", "signout", "lock", "unlock", "eye",
            "visibility", "hide", "show", "attach", "paperclip", "print", "save", "undo", "redo", "zoom",
            "sun", "moon", "phone", "cart", "spinner", "loader", "x"}
_ACTIONS_KO = ("닫기", "검색", "메뉴", "삭제", "편집", "수정", "설정", "공유", "복사", "다운로드", "업로드",
               "추가", "더보기", "이전", "다음", "확인", "취소", "알림", "장바구니", "로그인", "로그아웃")
_DRAWING = {"path", "polyline", "polygon", "line"}
_ICON_COMPONENT = re.compile(r"(?:function\s+|(?:const|let)\s+)([A-Z]\w*)")
_CONTROL_ROLES = {"button", "link", "menuitem", "tab"}
MAX_ICON_GEOMETRY = 1200       # characters of path data: standard action icons are short, logos long


def _words(text: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])|([A-Z])([A-Z][a-z])", lambda m: " ".join(g for g in m.groups() if g), text)
    return {w.lower() for w in re.split(r"[^A-Za-z]+", spaced) if w}


def _q_inline_svg(ctx: Context, tree: _Tree) -> tuple[list[Hit], str | None]:
    """An inline <svg> drawn with paths whose naming says it is a standard action: the svg's own
    label, title, class, or id; the *Icon component it is the body of; or the accessible name and
    text of the button or link it sits in."""
    hits = []
    for f in _markup_files(tree):
        tags = f.tags()
        for i, tag in enumerate(tags):
            if tag.closing or tag.name != "svg" or tag.close is None:
                continue
            inner = [t for t in tags[i + 1:tag.close] if not t.closing]
            drawing = [t for t in inner if t.name in _DRAWING]
            geometry = sum(len(_value(t.attr("d", "points")) or "") for t in drawing)
            if not drawing or geometry > MAX_ICON_GEOMETRY:
                continue
            context = [a.value or "" for a in tag.attrs if _attr_key(a.name) in (
                "aria-label", "title", "class", "classname", "id", "data-icon", "name")]
            context += [f.code[t.end:tags[t.close].start] for t in inner if t.name == "title" and t.close is not None]
            owner = list(_ICON_COMPONENT.finditer(f.code, 0, tag.start))
            if owner and re.search(r"Icon$|^Icon|Svg$|Glyph$", owner[-1].group(1)):
                context.append(owner[-1].group(1))
            if tag.parents:
                parent = tags[tag.parents[-1]]
                role = (_literal(parent.attr("role")) or "").lower()
                if parent.name.lower() in ("button", "a") or role in _CONTROL_ROLES:
                    context += [a.value or "" for a in parent.attrs
                                if _attr_key(a.name) in ("aria-label", "title")]
                    if parent.close is not None:
                        inside = f.code[parent.end:tag.start] + " " + f.code[tags[tag.close].end:tags[parent.close].start]
                        context.append(re.sub(r"<[^>]*>|\{[^}]*\}", " ", inside)[:80])
            text = " ".join(context)
            found = sorted(_words(text) & _ACTIONS) + [w for w in _ACTIONS_KO if w in text]
            if "x" in found and not re.search(r"\bX(?:Icon|Mark)\b|\bx-?mark\b|\bicon-x\b|\bx-icon\b", text):
                found.remove("x")
            if not found:
                continue
            hits.append(_hit(f, tag.start, f"hand-drawn inline <svg> for a standard action "
                                           f"({', '.join(found[:3])})"))
    return hits, None


# ---- hard-coded-date-number-or-locale-string

_LOCALE_CALL = re.compile(r"\.(toLocale(?:Date|Time)?String)\(\s*(\)|(['\"])([A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)\3)?")
_INTL_CALL = re.compile(r"\bIntl\.(DateTimeFormat|NumberFormat|RelativeTimeFormat|PluralRules|ListFormat)\(\s*(\)|undefined\b|(['\"])([A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)\3)?")
_NOW = re.compile(r"new Date\(\s*\)|\bDate\.now\(\)")
_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
_TEXT_DATES = (
    ("a hard-coded copyright year", re.compile(r"(?:©|&copy;|\(c\)|Copyright)\s*(?:19|20)\d{2}\b", re.I)),
    ("a hard-coded date", re.compile(
        r"\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b"
        rf"|\b{_MONTHS}\s+\d{{1,2}},?\s+(?:19|20)\d{{2}}\b|\b\d{{1,2}}\s+{_MONTHS}\s+(?:19|20)\d{{2}}\b"
        r"|\b\d{1,2}/\d{1,2}/(?:19|20)\d{2}\b|(?:19|20)\d{2}\.\s?\d{1,2}\.\s?\d{1,2}\.?"
        r"|(?:19|20)\d{2}년\s*\d{1,2}월(?:\s*\d{1,2}일)?")),
    ("a hand-formatted number", re.compile(r"(?<![\w.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w,])")),
)


def _locale_ok(tag: str, locales: list[str]) -> bool:
    t = tag.lower().split("-")
    for loc in locales:
        parts = loc.lower().split("-")
        if parts[0] == t[0] and (len(t) == 1 or len(parts) == 1 or parts[1:] == t[1:]):
            return True
    return False


_NOT_TEXT = {"script", "style", "code", "pre"}


def _text_nodes(f: _File) -> Iterator[tuple[int, str]]:
    """Text between tags, outside script, style, code, and pre elements."""
    tags = f.tags()
    opener = {t.close: i for i, t in enumerate(tags) if t.close is not None}
    for i, (a, b) in enumerate(zip(tags, tags[1:])):
        if a.end >= b.start:
            continue
        if a.closing:
            chain = tags[opener[i]].parents if i in opener else ()
        else:
            chain = a.parents + (() if a.self_closing or a.name.lower() in _VOID else (i,))
        if not any(tags[p].name.lower() in _NOT_TEXT for p in chain):
            yield a.end, f.code[a.end:b.start]


def _q_locale_time(ctx: Context, tree: _Tree) -> tuple[list[Hit], str | None]:
    locales = [str(x) for x in ((ctx.plan or {}).get("brief") or {}).get("locales") or []]
    hits = []
    for f in tree.files:
        for s, e in f.script_regions():
            for pattern in (_LOCALE_CALL, _INTL_CALL):
                for m in pattern.finditer(f.code, s, e):
                    call = m.group(1)
                    if m.group(4):
                        if not locales or not _locale_ok(m.group(4), locales):
                            target = f" (plan locales: {', '.join(locales)})" if locales else ""
                            hits.append(_hit(f, m.start(), f"{call} hard-codes the locale {m.group(4)!r}{target}"))
                    elif m.group(2):
                        hits.append(_hit(f, m.start(), f"{call} without a locale formats with the runtime's "
                                                       "default, which can differ between server and client"))
        if not f.has_markup:
            continue
        if locales:
            for tag in f.tags():
                if tag.name == "html" and not tag.closing:
                    lang = _literal(tag.attr("lang"))
                    if lang and not _locale_ok(lang, locales):
                        hits.append(_hit(f, tag.start, f"<html lang={lang!r}> is hard-coded outside the plan "
                                                       f"locales ({', '.join(locales)})"))
        for start, text in _text_nodes(f):
            if f.ext in _JSX and re.search(r";|=>|\breturn\b|\bfunction\b", text):
                continue
            k = 0
            visible = []
            while k < len(text):
                if text[k] == "{":
                    close = _balanced(text, k, len(text))
                    if close < 0:
                        break
                    expr = text[k:close]
                    if f.ext in _JSX | _SFC and _NOW.search(expr):
                        hits.append(_hit(f, start + k, f"{expr.strip()[:60]} renders the current time "
                                                       "into markup, so server and client output differ"))
                    visible.append(" " * len(expr))
                    k = close
                else:
                    visible.append(text[k])
                    k += 1
            plain = "".join(visible)
            for what, pattern in _TEXT_DATES:
                for m in pattern.finditer(plain):
                    hits.append(_hit(f, start + m.start(), f"{what} in markup text: {m.group()!r}"))
    return hits, None


# ---- state-setter-in-pointer-or-scroll-handler

_CONTINUOUS = {"mousemove", "pointermove", "touchmove", "scroll", "wheel", "drag", "dragover", "pointerrawupdate"}
_STATE_HOOK = re.compile(r"\[\s*[\w$]+\s*,\s*([\w$]+)\s*\]\s*=\s*(?:React\.)?use(?:State|Reducer)\s*[<(]")
_LISTENER = re.compile(r"addEventListener\(\s*(['\"])(\w+)\1\s*,")


def _function_body(code: str, name: str) -> str | None:
    n = re.escape(name)
    m = re.search(rf"function\s+{n}\s*\([^)]*\)\s*(?::\s*[\w<>\[\]| ]+)?\{{"
                  rf"|(?:const|let|var)\s+{n}\s*(?::[^=]+)?=\s*(?:(?:React\.)?useCallback\(\s*)?(?:async\s*)?"
                  rf"(?:\([^)]*\)|[\w$]+)\s*(?::\s*[\w<>\[\]| ]+)?=>\s*", code)
    if not m:
        return None
    start = m.end()
    if code[m.end() - 1] == "{":
        close = _balanced(code, m.end() - 1, len(code))
        return code[m.end() - 1:close if close > 0 else len(code)]
    if code.startswith("{", start):
        close = _balanced(code, start, len(code))
        return code[start:close if close > 0 else len(code)]
    end = code.find("\n", start)
    return code[start:end if end > 0 else len(code)]


def _q_state_setter(ctx: Context, tree: _Tree) -> tuple[list[Hit], str | None]:
    hits = []
    for f in tree.files:
        if f.ext not in _SCRIPT and f.ext not in _SFC:
            continue
        setters = set(_STATE_HOOK.findall(f.code))
        if not setters:
            continue
        calls = re.compile(r"(?<![\w$.])(" + "|".join(map(re.escape, sorted(setters))) + r")\s*\(")

        def setter_in(expr: str) -> str | None:
            m = calls.search(expr)
            if m:
                return m.group(1)
            ident = re.fullmatch(r"\s*(?:this\.)?([\w$]+)\s*", expr)
            if ident:
                body = _function_body(f.code, ident.group(1))
                if body and (m := calls.search(body)):
                    return m.group(1)
            return None

        for tag in f.tags():
            for a in tag.attrs:
                ev = _event(a)
                if ev and ev[0] in _CONTINUOUS and a.value and (setter := setter_in(a.value)):
                    hits.append(_hit(f, a.start, f"{setter}() runs in the {a.name} handler of <{tag.name}>: "
                                                 "a continuous value stored in component state"))
        for m in _LISTENER.finditer(f.code):
            if m.group(2).lower() not in _CONTINUOUS:
                continue
            close = _balanced(f.code, m.start() + len("addEventListener"), len(f.code), "(", ")")
            args = f.code[m.end():close - 1 if close > 0 else len(f.code)]
            handler = _split_top(args)[0] if args.strip() else ""
            if setter := setter_in(handler):
                hits.append(_hit(f, m.start(), f"{setter}() runs in a {m.group(2)} listener: a continuous "
                                               "value stored in component state"))
    return hits, None


def _break_selector(selector: str, tag: _Tag, tags: list[_Tag]) -> bool | None:
    """Match type/class/id selectors with descendant and child combinators; other syntax is unjudged."""
    if not re.fullmatch(r"[\w.*#\s>-]+", selector):
        return None
    parts = re.findall(r"[^\s>]+|>", selector)
    if not parts or parts[0] == ">" or parts[-1] == ">":
        return None

    def compound(part: str, node: _Tag) -> bool:
        kind = re.match(r"^[\w*-]+", part)
        if kind and kind.group() not in ("*", node.name):
            return False
        for prefix, value in re.findall(r"([.#])([\w-]+)", part):
            attr = node.attr("class", "className") if prefix == "." else node.attr("id")
            if not attr or attr.expr or value not in (attr.value or "").split():
                return False
        return True

    def match(index: int, node: _Tag) -> bool:
        if not compound(parts[index], node):
            return False
        if index == 0:
            return True
        direct = parts[index - 1] == ">"
        previous = index - 2 if direct else index - 1
        parents = node.parents[-1:] if direct else tuple(reversed(node.parents))
        return previous >= 0 and any(match(previous, tags[p]) for p in parents)

    return match(len(parts) - 1, tag)


def _q_hidden_heading_break(ctx: Context, tree: _Tree) -> tuple[list[Hit], str | None]:
    hiding = []
    for css in tree.files:
        for start, end in css.css_regions():
            media = _block_spans(css.code, start, end, re.compile(r"@media\b[^{]*\{", re.I))
            for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", css.code[start:end]):
                at = start + block.start()
                if not any(a <= at < b for a, b in media):
                    continue
                if re.search(r"(?:^|;)\s*display\s*:\s*none\s*(?:!\s*important\s*)?(?:;|$)", block.group(2), re.I):
                    hiding.extend((selector.strip(), css.where(at)) for selector in block.group(1).split(","))
    hits, unjudged = [], []
    for f in _markup_files(tree):
        tags = f.tags()
        for tag in tags:
            if tag.name != "br" or tag.closing:
                continue
            heading = next((tags[p] for p in reversed(tag.parents) if re.fullmatch(r"h[1-6]", tags[p].name)), None)
            if heading is None or heading.close is None:
                continue
            def text_between(start: int, end: int) -> str:
                raw = _HTML_COMMENT.sub("", f.text[start:end])
                return html.unescape(re.sub(r"<[^>]*>", "", raw))
            before = text_between(heading.end, tag.start)
            after = text_between(tag.end, tags[heading.close].start)
            if not before or not after or before[-1].isspace() or after[0].isspace():
                continue
            if not before[-1].isalnum() or not after[0].isalnum():
                continue
            refs = []
            for selector, where in hiding:
                matches = _break_selector(selector, tag, tags)
                if matches:
                    refs.append(where)
                elif matches is None and "br" in selector:
                    unjudged.append(f"{where}: unsupported selector {selector!r}")
            if refs:
                hits.append(_hit(f, tag.start, f"media-query display:none on <br> joins heading text "
                                 f"{before[-24:]!r} and {after[:24]!r} without whitespace",
                                 [f.where(tag.start), *dict.fromkeys(refs)]))
    return hits, "; ".join(dict.fromkeys(unjudged)) or None


_QUERIES: dict[str, Callable[[Context, _Tree], tuple[list[Hit], str | None]]] = {
    "img-without-alt": _q_img_without_alt,
    "img-without-intrinsic-size": _q_img_without_intrinsic_size,
    "input-without-associated-label": _q_input_without_label,
    "click-handler-on-non-interactive-element": _q_click_non_interactive,
    "raw-element-where-adopted-primitive-exists": _q_raw_element,
    "inline-svg-path-for-standard-action": _q_inline_svg,
    "hard-coded-date-number-or-locale-string": _q_locale_time,
    "state-setter-in-pointer-or-scroll-handler": _q_state_setter,
    "hidden-heading-break": _q_hidden_heading_break,
}
_MARKUP_QUERIES = {"img-without-alt", "img-without-intrinsic-size", "input-without-associated-label",
                   "click-handler-on-non-interactive-element", "raw-element-where-adopted-primitive-exists",
                   "inline-svg-path-for-standard-action", "hidden-heading-break"}


@detector("source-ast", layers=("source",))
def source_ast(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    query = (det.get("params") or {}).get("query")
    fn = _QUERIES.get(query)
    if fn is None:
        return Result(skipped=f"unknown source-ast query {query!r}")
    tree = _tree(ctx)
    if isinstance(tree, str):
        return Result(skipped=tree)
    if not tree.files:
        return Result(skipped="no CSS, markup, or script files under the source tree")
    if query in _MARKUP_QUERIES and not _markup_files(tree):
        return Result(skipped="no markup files (HTML, JSX/TSX, Vue, Svelte, Astro) under the source tree")
    if query == "state-setter-in-pointer-or-scroll-handler" and not any(
            f.ext in _SCRIPT or f.ext in _SFC for f in tree.files):
        return Result(skipped="no script or component files under the source tree")
    hits, note = fn(ctx, tree)
    return Result(hits=hits, skipped=note)


# ================================================================ dependency-check

_ICON_PACKAGES = {
    "lucide": "lucide", "lucide-react": "lucide", "lucide-vue-next": "lucide", "lucide-svelte": "lucide",
    "lucide-preact": "lucide", "lucide-solid": "lucide", "lucide-static": "lucide", "lucide-angular": "lucide",
    "@heroicons/react": "heroicons", "@heroicons/vue": "heroicons", "heroicons": "heroicons",
    "@tabler/icons": "tabler", "@tabler/icons-react": "tabler", "@tabler/icons-vue": "tabler",
    "@tabler/icons-svelte": "tabler", "@phosphor-icons/react": "phosphor", "@phosphor-icons/vue": "phosphor",
    "@phosphor-icons/web": "phosphor", "phosphor-react": "phosphor", "phosphor-svelte": "phosphor",
    "@mui/icons-material": "material", "@material-ui/icons": "material", "material-icons": "material",
    "material-symbols": "material", "@radix-ui/react-icons": "radix", "@iconify/react": "iconify",
    "@iconify/vue": "iconify", "iconify-icon": "iconify", "feather-icons": "feather", "react-feather": "feather",
    "ionicons": "ionicons", "bootstrap-icons": "bootstrap", "react-bootstrap-icons": "bootstrap",
    "remixicon": "remix", "@remixicon/react": "remix", "@ant-design/icons": "ant-design",
    "@primer/octicons-react": "octicons", "@primer/octicons": "octicons", "@carbon/icons-react": "carbon",
    "@carbon/icons": "carbon", "hugeicons-react": "hugeicons", "@untitled-ui/icons-react": "untitled-ui",
    "boxicons": "boxicons", "@mdi/js": "mdi", "@mdi/react": "mdi", "@mdi/font": "mdi",
    "@icon-park/react": "icon-park", "css.gg": "css.gg", "@fluentui/react-icons": "fluent",
}
_ICON_PREFIXES = {"@fortawesome/": "font-awesome", "@hugeicons/": "hugeicons", "@material-symbols/": "material",
                  "@material-design-icons/": "material", "@iconify-icon/": "iconify", "@iconify-icons/": "iconify"}
_REACT_ICONS = {"fa": "font-awesome", "fa6": "font-awesome", "md": "material", "hi": "heroicons",
                "hi2": "heroicons", "fi": "feather", "lu": "lucide", "bs": "bootstrap", "ai": "ant-design",
                "io": "ionicons", "io5": "ionicons", "ri": "remix", "tb": "tabler", "pi": "phosphor",
                "bi": "boxicons", "go": "octicons", "rx": "radix", "ci": "circum", "cg": "css.gg",
                "ti": "typicons", "vsc": "codicons", "sl": "simple-line", "lia": "line-awesome",
                "gr": "grommet", "fc": "flat-color", "im": "icomoon", "tfi": "themify", "gi": "game-icons",
                "wi": "weather", "si": "simple-icons", "di": "devicons"}
_VECTOR_ICONS = {"@expo/vector-icons", "react-native-vector-icons"}
_VECTOR_FAMILIES = {"ionicons": "ionicons", "materialicons": "material", "materialcommunityicons": "mdi",
                    "fontawesome": "font-awesome", "fontawesome5": "font-awesome", "fontawesome6": "font-awesome",
                    "feather": "feather", "antdesign": "ant-design", "octicons": "octicons",
                    "evilicons": "evil-icons", "simplelineicons": "simple-line"}
_ANIMATION = {"framer-motion": "motion", "motion": "motion", "framer-motion-3d": "motion", "gsap": "gsap",
              "@gsap/react": "gsap", "react-spring": "react-spring", "animejs": "anime", "popmotion": "popmotion",
              "velocity-animate": "velocity", "@formkit/auto-animate": "auto-animate",
              "react-transition-group": "transition-group", "@vueuse/motion": "vueuse-motion"}
_ANIMATION_PREFIXES = {"@react-spring/": "react-spring", "@motionone/": "motion-one"}
_DEP_FIELDS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
_IMPORT_SPEC = re.compile(r"(?<![\w$.])(?:from|import|require)\s*\(?\s*(['\"])([^'\"\n]+)\1")


def _split_spec(spec: str) -> tuple[str, str] | None:
    if spec.startswith((".", "/", "~", "#", "$", "@/", "node:", "http:", "https:", "data:", "virtual:")):
        return None
    parts = spec.split("/")
    if spec.startswith("@"):
        return ("/".join(parts[:2]), "/".join(parts[2:])) if len(parts) >= 2 else None
    return parts[0], "/".join(parts[1:])


def _prefixed(pkg: str, table: dict[str, str], prefixes: dict[str, str]) -> str | None:
    if pkg in table:
        return table[pkg]
    return next((v for p, v in prefixes.items() if pkg.startswith(p)), None)


def _lock_names(path: Path) -> set[str] | None:
    """Package names a lockfile installs; None when it cannot be read as text."""
    if path.name == "bun.lockb":
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    names: set[str] = set()
    try:
        if path.name in ("package-lock.json", "npm-shrinkwrap.json"):
            doc = json.loads(text)
            for key in (doc.get("packages") or {}):
                if "node_modules/" in key:
                    names.add(key.rsplit("node_modules/", 1)[1])

            def walk(deps: dict) -> None:
                for name, entry in (deps or {}).items():
                    names.add(name)
                    walk((entry or {}).get("dependencies") or {})
            walk(doc.get("dependencies") or {})
        elif path.name == "pnpm-lock.yaml":
            doc = yaml.safe_load(text) or {}
            for section in ("packages", "snapshots"):
                for key in doc.get(section) or {}:
                    k = str(key).lstrip("/")
                    at = k.find("@", 1)
                    names.add(k[:at] if at > 0 else k.rsplit("/", 1)[0])
            for importer in (doc.get("importers") or {".": doc}).values():
                for field_name in _DEP_FIELDS:
                    names |= set((importer or {}).get(field_name) or {})
        elif path.name == "yarn.lock":
            for line in text.splitlines():
                if line and not line[0].isspace() and line.rstrip().endswith(":") and not line.startswith("#"):
                    for spec in line.rstrip()[:-1].split(","):
                        spec = spec.strip().strip('"')
                        at = spec.find("@", 1)
                        if at > 0 and spec != "__metadata":
                            names.add(spec[:at])
        elif path.name == "bun.lock":
            names |= set(re.findall(r"^\s*\"((?:@[^\"/]+/)?[^\"@/][^\"@]*)\":\s*\[\s*\"\1@", text, re.M))
    except (ValueError, yaml.YAMLError, AttributeError):
        return None
    return names


@dataclass
class _Import:
    file: _File
    offset: int
    spec: str
    package: str
    subpath: str
    bindings: list[str]


def _imports(tree: _Tree) -> list[_Import]:
    out = []
    for f in tree.files:
        regions = f.script_regions() if f.ext not in _STYLE else f.styles
        for s, e in regions:
            for m in _IMPORT_SPEC.finditer(f.code, s, e):
                split = _split_spec(m.group(2))
                if not split:
                    continue
                clause = ""
                if m.group().startswith("from"):
                    ls = f.code.rfind("import", s, m.start())
                    if ls >= 0 and ";" not in f.code[ls:m.start()]:
                        clause = re.sub(r"\bas\s+[\w$]+|\btype\b|\bimport\b", " ", f.code[ls + 6:m.start()])
                bindings = re.findall(r"[A-Za-z_$][\w$]*", clause)
                out.append(_Import(f, m.start(), m.group(2), split[0], split[1], bindings))
    return out


def _icon_families(imp: _Import) -> list[tuple[str, str]]:
    """(family, what the import names) for each icon family an import brings in."""
    if imp.package == "react-icons":
        sub = imp.subpath.split("/")[0]
        return [(_REACT_ICONS[sub], f"react-icons/{sub}")] if sub in _REACT_ICONS else []
    if imp.package in _VECTOR_ICONS:
        sub = imp.subpath.split("/")[0]
        names = [sub] if sub else imp.bindings
        return sorted({(_VECTOR_FAMILIES.get(n.lower(), n.lower()), f"{imp.package} {n}") for n in names if n})
    fam = _prefixed(imp.package, _ICON_PACKAGES, _ICON_PREFIXES)
    return [(fam, imp.package)] if fam else []


def _declared(tree: _Tree) -> dict[str, tuple[str, str]]:
    """Directly declared packages: name -> (version range, manifest)."""
    out: dict[str, tuple[str, str]] = {}
    for rel, doc in tree.manifests.items():
        for field_name in _DEP_FIELDS:
            for name, version in (doc.get(field_name) or {}).items():
                out.setdefault(name, (str(version), rel))
    return out


def _check_icon_packages(tree: _Tree) -> Result:
    code_files = [f for f in tree.files if f.ext in _SCRIPT or f.ext in _SFC]
    if not code_files:
        if not tree.manifests:
            return Result(skipped="no package.json and no script files under the source tree")
        declared: dict[str, list[str]] = {}
        for name in _declared(tree):
            if fam := _prefixed(name, _ICON_PACKAGES, _ICON_PREFIXES):
                declared.setdefault(fam, []).append(name)
        if len(declared) < 2:
            return Result()
        desc = "; ".join(", ".join(sorted(pkgs)) for pkgs in sorted(declared.values()))
        return Result(hits=[Hit(observed=f"{len(declared)} icon families declared in package.json: {desc}",
                                location={"file": sorted(tree.manifests)[0]}, evidence="source",
                                refs=sorted(tree.manifests))])
    families: dict[str, list[tuple[_File, int, str]]] = {}
    for imp in _imports(tree):
        for fam, shown in _icon_families(imp):
            families.setdefault(fam, []).append((imp.file, imp.offset, shown))
    if len(families) < 2:
        return Result()
    # the family used in the fewest files first: it is the likely stray
    ordered = sorted(families.values(), key=lambda uses: (len({f.rel for f, _, _ in uses}), uses[0][2]))
    desc = "; ".join(f"{', '.join(sorted({s for _, _, s in uses}))} "
                     f"({_plural(len({f.rel for f, _, _ in uses}), 'file')})" for uses in ordered)
    occurrences = [(f, o) for uses in ordered for f, o, _ in uses]
    return Result(hits=[_grouped_hit(occurrences, f"{len(families)} icon families imported: {desc}")])


def _node_package(tree: _Tree, f: _File, package: str) -> tuple[Path, dict] | None:
    d = (tree.root / f.rel).parent
    root = tree.root.resolve()
    while True:
        candidate = d / "node_modules" / package / "package.json"
        if candidate.is_file():
            try:
                return candidate.parent, json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        if d.resolve() == root or d == d.parent:
            return None
        d = d.parent


def _exports_subpath(pkg_dir: Path, doc: dict, subpath: str) -> bool:
    exports = doc.get("exports")
    key = f"./{subpath}" if subpath else "."
    if exports is None:
        if not subpath:
            return True
        base = pkg_dir / subpath
        return any(p.exists() for p in (base, base.with_name(base.name + ".js"), base.with_name(base.name + ".mjs"),
                                        base.with_name(base.name + ".cjs"), base / "index.js", base / "package.json"))
    if isinstance(exports, (str, list)) or not any(str(k).startswith(".") for k in exports):
        return key == "."
    for k, v in exports.items():
        if k == key:
            return v is not None
        if "*" in k and re.fullmatch(re.escape(k).replace(r"\*", ".*"), key):
            return v is not None
    return False


def _check_animation(tree: _Tree, unobserved: str | None) -> Result:
    code_files = [f for f in tree.files if f.ext in _SCRIPT or f.ext in _SFC]
    if not tree.manifests:
        return Result(skipped="no package.json under the source tree, so the installed packages are unknown")
    if not code_files:
        status = f"; {unobserved}" if unobserved else ""
        return Result(skipped=f"imports could not be read: no script or component files under the source tree{status}")
    declared = _declared(tree)
    locks = {rel: names for rel, names in tree.locks.items() if names is not None}
    installed_any = set().union(*locks.values()) if locks else set()
    by_package: dict[str, list[_Import]] = {}
    for imp in _imports(tree):
        if _prefixed(imp.package, _ANIMATION, _ANIMATION_PREFIXES):
            by_package.setdefault(imp.package, []).append(imp)
    hits = []
    for package, imps in sorted(by_package.items()):
        occurrences = [(i.file, i.offset) for i in imps]
        files = _plural(len({i.file.rel for i in imps}), "file")
        if package not in declared:
            if package in installed_any:
                where = ", ".join(sorted(rel for rel, names in locks.items() if package in names))
                hits.append(_grouped_hit(occurrences, f"imports {package} ({files}), which no package.json declares; "
                                                      f"it is only a transitive dependency in {where}"))
            else:
                hits.append(_grouped_hit(occurrences, f"imports {package} ({files}), which is not installed: "
                                                      "no package.json declares it"
                                                      + (" and no lockfile lists it" if locks else "")))
            continue
        if locks and package not in installed_any:
            hits.append(_grouped_hit(occurrences, f"imports {package} ({files}); package.json declares "
                                                  f"{declared[package][0]} but no lockfile lists it"))
            continue
        for imp in imps:
            found = _node_package(tree, imp.file, package)
            if found and not _exports_subpath(found[0], found[1], imp.subpath):
                version = found[1].get("version", "?")
                hits.append(_hit(imp.file, imp.offset, f"imports {imp.spec!r}, but the installed {package} "
                                                       f"{version} has no {'./' + imp.subpath if imp.subpath else 'main'} "
                                                       "export"))
    stacks: dict[str, list[str]] = {}
    for package in by_package:
        stacks.setdefault(_prefixed(package, _ANIMATION, _ANIMATION_PREFIXES), []).append(package)
    if len(stacks) >= 2:
        occurrences = [(i.file, i.offset) for p in sorted(by_package) for i in by_package[p]]
        desc = "; ".join(f"{', '.join(sorted(pkgs))} "
                         f"({_plural(len({i.file.rel for p in pkgs for i in by_package[p]}), 'file')})"
                         for pkgs in sorted(stacks.values()))
        hits.append(_grouped_hit(occurrences, f"{len(stacks)} animation stacks imported: {desc}"))
    unreadable = sorted(rel for rel, names in tree.locks.items() if names is None)
    note = f"lockfile not read: {', '.join(unreadable)}" if unreadable and not locks else None
    return Result(hits=hits, skipped=note)


@detector("dependency-check", layers=("source",))
def dependency_check(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    params = det.get("params") or {}
    check = params.get("check")
    if check not in ("icon-packages", "animation-imports-vs-installed"):
        return Result(skipped=f"unknown dependency check {check!r}")
    tree = _tree(ctx)
    if isinstance(tree, str):
        return Result(skipped=tree)
    if check == "icon-packages":
        return _check_icon_packages(tree)
    return _check_animation(tree, params.get("unobserved"))
