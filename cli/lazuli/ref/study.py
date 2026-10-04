"""Study copies of a reference: what `--task` keeps under `.lapis/references/<task>/<slug>/`.

A reference is only used when it has been looked at, and a profile in the render extract format is numbers: it
does not show the page. With `--task`, `lazuli ref capture` keeps the screenshots it took, the page's own HTML,
and its stylesheets there, with `facts.md`, a digest of what that source says about type, color, and layout;
`lazuli ref profile` keeps the picture. They are for study only: the folder carries a `.gitignore` that excludes
everything in it, nothing ships from `.lapis/`, and nothing deletes them.

The stylesheets are read the way every request of `lazuli ref` is: through the source registry, robots.txt, and
the per-host pace, one GET each, at most `MAX_SHEETS` of them and `MAX_SHEET_BYTES` each; a sheet that is
refused, blocked, or too large is named in the digest and not kept. The digest counts declarations in the CSS as
written (a regular-expression scan, not a cascade): it says what the source states, not what the browser
rendered, which the profile measures. Scripts are not run and links are not followed.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from lazuli.catalog import net
from lazuli.ref.common import InputError

MAX_SHEETS = 6
MAX_SHEET_BYTES = 1_500_000
MAX_IMAGE_BYTES = 25_000_000
GITIGNORE = "# Study captures of other people's pages and pictures: for study only, never committed or shipped.\n*\n"
LANDMARKS = {"header", "nav", "main", "section", "article", "aside", "footer", "form", "dialog"}
OUTLINE_LINES = 60


def folder(project: Path, task: str, slug: str) -> Path:
    return project / ".lapis" / "references" / task / slug


@dataclass
class Source:
    """A page's own HTML and the stylesheets read for it, with the digest."""
    html: bytes
    sheets: list[tuple[str, bytes]] = field(default_factory=list)       # (address, CSS) in document order
    notes: list[str] = field(default_factory=list)                      # sheets not read, and why
    facts: str = ""


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class _Page(HTMLParser):
    """The stylesheet links, inline styles, named images, and landmark outline of one page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.inline: list[str] = []
        self.images: list[str] = []
        self.outline: list[str] = []
        self.elements = 0
        self._style = False
        self._open: list[str] = []                      # open elements, innermost last
        self._depth = 0                                 # landmarks among them

    def handle_starttag(self, tag, attrs):
        self.elements += 1
        values = {name: value or "" for name, value in attrs}
        if tag == "link" and "stylesheet" in values.get("rel", "").lower().split() and values.get("href"):
            self.links.append(values["href"])
        elif tag == "meta" and values.get("property", "").lower() in ("og:image", "twitter:image"):
            if values.get("content"):
                self.images.append(values["content"])
        elif tag == "style":
            self._style = True
            self.inline.append("")
        if tag in LANDMARKS and len(self.outline) < OUTLINE_LINES:
            classes = ".".join(token[:24] for token in values.get("class", "").split()[:2])
            self.outline.append(f"{'  ' * self._depth}{tag}{'.' + classes if classes else ''}")
        if tag not in VOID:
            self._open.append(tag)
            self._depth += tag in LANDMARKS

    def handle_endtag(self, tag):
        if tag == "style":
            self._style = False
        if tag in self._open:                           # markup left unclosed (a <p>, an <li>) closes with its parent
            while (closed := self._open.pop()) != tag:
                self._depth -= closed in LANDMARKS
            self._depth -= tag in LANDMARKS

    def handle_data(self, data):
        if self._style:
            self.inline[-1] += data


_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_DECLARATION = re.compile(r"(?<![\w-])(--[\w-]+|[a-z][a-z-]*)\s*:\s*([^;{}]+?)\s*(?=;|\}|$)",
                          re.IGNORECASE | re.MULTILINE)
_FONT_FACE = re.compile(r"@font-face\s*\{[^}]*?font-family\s*:\s*([^;}]+)", re.IGNORECASE)
_BREAKPOINT = re.compile(r"@media[^{]*?\(\s*(min|max)-width\s*:\s*([\d.]+)\s*(px|em|rem)\s*\)", re.IGNORECASE)
_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|(?:rgba?|hsla?|oklch|oklab|lab|lch|color)\([^)]{3,60}\)")
_TYPE = ("font", "font-size", "line-height", "letter-spacing", "font-weight")
_LAYOUT = ("grid-template-columns", "max-width", "gap", "column-gap", "row-gap")
_DISPLAY = ("grid", "flex", "inline-flex", "inline-grid", "block", "none")


def _top(counter: Counter, limit: int, width: int = 60) -> str:
    return ", ".join(f"{value[:width]} ×{count}" for value, count in counter.most_common(limit)) or "none found"


def _unquote(name: str) -> str:
    return name.strip().strip("\"'").strip()


def css_facts(sheets: list[str]) -> list[str]:
    """Lines of Markdown that count what the stylesheets state about type, color, and layout."""
    text = _COMMENT.sub("", "\n".join(sheets))
    by_property: dict[str, Counter] = {}
    custom: dict[str, str] = {}
    for name, value in _DECLARATION.findall(text):
        value = " ".join(value.split())
        if name.startswith("--"):
            if len(value) <= 60 and "url(" not in value:
                custom.setdefault(name, value)
        elif (name := name.lower()) in (*_TYPE, *_LAYOUT, "font-family", "display"):
            by_property.setdefault(name, Counter())[value] += 1

    def counted(name: str) -> Counter:
        return by_property.get(name, Counter())

    stacks = Counter()
    for value, count in counted("font-family").items():
        stacks[", ".join(_unquote(part) for part in value.split(",")[:3])] += count
    faces = Counter(_unquote(match) for match in _FONT_FACE.findall(text))
    colors = Counter(match.lower() for match in _COLOR.findall(text))
    breakpoints = sorted({f"{kind}-width {amount}{unit}" for kind, amount, unit in _BREAKPOINT.findall(text)})
    shown = list(custom.items())[:40]
    lines = ["## Type", f"- font-family stacks (first three faces): {_top(stacks, 8, 70)}",
             f"- @font-face families: {_top(faces, 8)}"]
    lines += [f"- {name}: {_top(counted(name), 12)}" for name in _TYPE]
    lines += ["", "## Color", f"- color values as written: {_top(colors, 14, 50)}",
              f"- custom properties ({len(custom)}; the first {len(shown)}): "
              + ("; ".join(f"{name}: {value}" for name, value in shown) or "none found")]
    lines += ["", "## Layout",
              f"- display: {_top(Counter({v: c for v, c in counted('display').items() if v in _DISPLAY}), 6)}"]
    lines += [f"- {name}: {_top(counted(name), 8, 70)}" for name in _LAYOUT]
    lines.append(f"- media-query breakpoints: {', '.join(breakpoints) or 'none found'}")
    return lines


def _digest(url: str, html: bytes, page: _Page, sheets: list[tuple[str, bytes]], notes: list[str]) -> str:
    kept = [f"{urlsplit(address).path.rsplit('/', 1)[-1] or address} ({len(body):,} bytes)" for address, body in sheets]
    lines = [f"# Source facts: {urlsplit(url).hostname}", "",
             "Read from the page's own HTML and the stylesheets it links, as written. Scripts were not run, so a page "
             "that builds its interface in script shows less here; the profile in `.lapis/refs/` measures the "
             "rendered page. For study only.", "",
             f"- HTML: {len(html):,} bytes, {page.elements} elements, {len(page.inline)} inline style blocks",
             f"- stylesheets kept as style-N.css: {', '.join(kept) or 'none'}"]
    lines += [f"- not read: {note}" for note in notes]
    if page.images:
        lines.append("- images the page names for sharing (pass one to `lazuli ref profile` to look at it): "
                     + ", ".join(urljoin(url, image) for image in page.images[:3]))
    lines += ["", "## Landmarks in order", "```", *(page.outline or ["(none: the page has no landmark elements)"]), "```",
              ""]
    css = [body.decode("utf-8", errors="replace") for _, body in sheets] + page.inline
    lines += css_facts(css)
    return "\n".join(lines) + "\n"


def read_source(final_url: str, page: net.Response, fetcher: net.Fetcher) -> Source:
    """The page's HTML and its linked stylesheets (at most `MAX_SHEETS`), each through `fetcher`, with the digest."""
    parsed = _Page()
    parsed.feed(page.text())
    parsed.close()
    sheets: list[tuple[str, bytes]] = []
    notes: list[str] = []
    seen: set[str] = set()
    for href in parsed.links:
        address = urljoin(final_url, href)
        if urlsplit(address).scheme not in ("http", "https") or address in seen:
            continue
        seen.add(address)
        name = urlsplit(address).path.rsplit("/", 1)[-1] or address
        if len(sheets) >= MAX_SHEETS:
            notes.append(f"{name}: past the first {MAX_SHEETS} stylesheets")
            continue
        try:
            reply = fetcher.get(address)
        except net.Blocked as exc:
            notes.append(f"{name}: {exc.reason}")
            continue
        except (net.FetchError, OSError, ValueError) as exc:
            notes.append(f"{name}: {exc}")
            continue
        kind = reply.headers.get("content-type", "").split(";")[0].strip().lower()
        if kind not in ("", "text/plain") and "css" not in kind:
            notes.append(f"{name}: answered {kind}, not CSS")
        elif len(reply.body) > MAX_SHEET_BYTES:
            notes.append(f"{name}: {len(reply.body):,} bytes, over the {MAX_SHEET_BYTES:,} kept")
        else:
            sheets.append((address, reply.body))
    return Source(page.body, sheets, notes, _digest(final_url, page.body, parsed, sheets, notes))


def keep(project: Path, task: str, slug: str, files: dict[str, bytes | Path]) -> Path:
    """Put `files` (name to bytes, or to a file to copy) in `.lapis/references/<task>/<slug>/`, replacing what an
    earlier run of the same slug left, and make sure the task's folder excludes itself from git. The folder is
    built beside its place first, so a failure leaves the earlier one. Raises OSError when the disk does."""
    base = project / ".lapis" / "references" / task
    base.mkdir(parents=True, exist_ok=True)
    ignore = base / ".gitignore"
    if not ignore.exists():
        ignore.write_text(GITIGNORE, encoding="utf-8")
    staging = Path(tempfile.mkdtemp(prefix=f".{slug}-", dir=base))
    target = base / slug
    aside = base / f".{slug}-old-{uuid.uuid4().hex}"
    moved = False
    try:
        for name, content in files.items():
            if isinstance(content, Path):
                shutil.copyfile(content, staging / name)
            else:
                (staging / name).write_bytes(content)
        if os.path.lexists(target):
            os.rename(target, aside)
            moved = True
        os.rename(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if moved:
            os.rename(aside, target)
        raise
    if moved:
        shutil.rmtree(aside, ignore_errors=True)
    return target


def image_extension(content_type: str, image_format: str | None) -> str:
    """The suffix for a downloaded picture: from what Pillow decoded, else the content type."""
    named = {"jpeg": ".jpg", "png": ".png", "gif": ".gif", "webp": ".webp", "avif": ".avif", "bmp": ".bmp",
             "tiff": ".tif"}
    for candidate in ((image_format or "").lower(), content_type.split("/")[-1].split(";")[0].strip().lower()):
        if candidate in named:
            return named[candidate]
    raise InputError(f"cannot tell what kind of picture this is ({image_format or content_type or 'unknown type'})")
