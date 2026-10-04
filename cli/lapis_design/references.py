"""The references record: what a create run looked at before it plans, kept in one file.

`lapis-design next` names the step `references` after `brief` and before `plan` while a create run has no
references record. The record is `.lapis/references/<task>.md`: Markdown with one fenced `yaml` block that says
`captures: study-only` and lists `references`. Each reference gives where it is (`url`, or `source` when it has
none), its `maker`, its `kind`, the open `decision` it informs, the `relation` taken from it, and its evidence
of looking: a `capture` under `.lapis/references/<task>/` (a screenshot of the page or the picture itself) and,
for a `web-ui` reference, `source_facts` read from its HTML and CSS. The captures are for study only: they are
never shipped or copied into the page, and nothing deletes them.

What is checked is the record and the files it names, not whether the looking was good: at least six
references; at least three kinds and two outside `web-ui` among the references seen as images; every capture
an existing file under the task's folder, each one its own; every `web-ui` reference with source facts that
state a value; and at most two text-only references. A reference is text-only when its capture is not an image
(a page saved as text) or its page is an encyclopedia: reading about a thing is not looking at it, so a
text-only reference counts toward the total and toward nothing else.

A run with no network records that with `lapis-design next --unavailable references` (attempts.py), which
`next` counts as the step done and reports as a step that did not run. The command first tries one plain GET
(`unreachable`) and records only when that fails.

Stdlib and PyYAML only: `next` and the stop hook import this.
"""
from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from lapis_design import waiting

STEP = "references"
KINDS = {
    "web-ui": "a website, web app, app screen, or design system",
    "print": "a book, poster, packaging, label, map, or ticket",
    "signage": "wayfinding, a sign, lettering on a building, or a transit graphic",
    "physical-object": "a product, tool, instrument, or building",
    "archive": "a record from a museum, library, or archive",
    "media": "a painting, photograph, film, or other work",
}
MIN_REFERENCES, MIN_KINDS, MIN_OUTSIDE, MAX_TEXT_ONLY = 6, 3, 2, 2
MIN_IMAGE_BYTES = 1024
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ENCYCLOPEDIAS = ("wikipedia.org", "wikiwand.com", "britannica.com", "wiktionary.org", "namu.wiki", "grokipedia.com")
STUDY_ONLY = "study-only"

_FENCE = re.compile(r"^```(?:ya?ml)[ \t]*\n(.*?)^```[ \t]*$", re.DOTALL | re.MULTILINE)
_VALUE = re.compile(r"\d|#[0-9a-f]{3}", re.IGNORECASE)      # a size, a count, or a color: a stated value
_WORD = re.compile(r"[^\W_]+")


def record_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "references" / f"{task}.md"


def folder(root: Path, task: str) -> Path:
    """Where the task's captures live: `.lapis/references/<task>/`."""
    return root / ".lapis" / "references" / task


def _text(value: Any) -> str:
    """A field as one string: a string as written, a list or mapping as its strings joined (a list of facts is a
    natural way to write them)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    return "" if value is None else str(value)


def _words(value: Any) -> int:
    return len(_WORD.findall(_text(value)))


def _is_image(path: Path) -> bool | None:
    """Whether `path` holds an image by its first bytes, or None when its suffix says it is no image file."""
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        return None
    try:
        with path.open("rb") as handle:
            head = handle.read(12)
        size = path.stat().st_size
    except OSError:
        return False
    magic = (head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff") or head[:6] in (b"GIF87a", b"GIF89a")
             or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"))
    return magic and size >= MIN_IMAGE_BYTES


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _encyclopedia(url: str) -> bool:
    host = _host(url)
    return any(host == name or host.endswith("." + name) for name in ENCYCLOPEDIAS)


def _normal(url: str) -> str:
    parts = urlsplit(url.strip())
    return f"{(parts.hostname or '').lower().removeprefix('www.')}{parts.path.rstrip('/')}"


def parse(text: str) -> tuple[dict | None, str | None]:
    """The record's mapping, or None with why it cannot be read."""
    match = _FENCE.search(text)
    if not match:
        return None, "it has no fenced ```yaml block"
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return None, f"its yaml block cannot be read: {(str(exc).splitlines() or [''])[0]}"
    if not isinstance(data, dict) or not isinstance(data.get("references"), list):
        return None, "its yaml block has no `references` list"
    return data, None


def problems(root: Path, task: str) -> list[str]:
    """Why `.lapis/references/<task>.md` under `root` is not a references record, one line each; [] when it is."""
    path = record_path(root, task)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [f"{path.relative_to(root).as_posix()} does not exist"]
    data, why = parse(text)
    if data is None:
        return [why or "it cannot be read"]
    found: list[str] = []
    if data.get("captures") != STUDY_ONLY:
        found.append(f"it does not say `captures: {STUDY_ONLY}`")
    base = folder(root, task).resolve()
    seen: dict[str, str] = {}
    urls: dict[str, str] = {}
    ids: set[str] = set()
    visual: list[str | None] = []                  # the kind of each reference seen as an image
    text_only = total = 0
    for index, ref in enumerate(data["references"], start=1):
        if not isinstance(ref, dict):
            found.append(f"reference {index} is not a mapping")
            continue
        total += 1
        name = ref.get("id") if isinstance(ref.get("id"), str) and ref["id"].strip() else None
        who = f"reference {name}" if name else f"reference {index}"
        if name is None:
            found.append(f"{who} has no `id`")
        elif name in ids:
            found.append(f"{who}: the `id` is used twice")
        ids.add(name or "")
        url = ref.get("url") if isinstance(ref.get("url"), str) and ref["url"].strip() else None
        if url is not None:
            if urlsplit(url).scheme not in ("http", "https") or not _host(url):
                found.append(f"{who}: `url` is not an http(s) address")
            elif (twin := urls.setdefault(_normal(url), who)) != who:
                found.append(f"{who} is the same page as {twin}")
        elif not isinstance(ref.get("source"), str) or not ref["source"].strip():
            found.append(f"{who} has neither `url` nor `source`")
        for field in ("maker", "decision", "relation"):
            if _words(ref.get(field)) < (1 if field == "maker" else waiting.MIN_WORDS):
                found.append(f"{who} has no `{field}`" if field == "maker" else f"{who}: `{field}` is empty or one word")
        kind = ref.get("kind")
        if not isinstance(kind, str) or kind not in KINDS:
            found.append(f"{who}: `kind` is {kind!r}, not one of {', '.join(KINDS)}")
            kind = None
        facts = _text(ref.get("source_facts"))
        if kind == "web-ui" and not (_words(facts) >= 4 and _VALUE.search(facts)):
            found.append(f"{who} is a web-ui reference without `source_facts` that state values read from its HTML or "
                         "CSS (a size, a color, a column count)")
        capture = ref.get("capture")
        if not isinstance(capture, str) or not capture.strip():
            found.append(f"{who} has no `capture`")
            continue
        given = Path(capture)
        target = (given if given.is_absolute() else root / given).resolve()
        if not target.is_relative_to(base):
            found.append(f"{who}: `capture` is not under {folder(root, task).relative_to(root).as_posix()}/")
            continue
        if not target.is_file():
            found.append(f"{who}: the capture file {capture} does not exist")
            continue
        image = _is_image(target)
        if image is False:
            found.append(f"{who}: {capture} is not an image (a {', '.join(sorted(IMAGE_SUFFIXES))} file of at least "
                         f"{MIN_IMAGE_BYTES} bytes)")
            continue
        if image is None and target.stat().st_size == 0:
            found.append(f"{who}: the capture file {capture} is empty")
            continue
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if (twin := seen.setdefault(digest, who)) != who:
            found.append(f"{who} has the same capture as {twin}; each reference needs its own")
            continue
        if image is None or (url is not None and _encyclopedia(url)):
            text_only += 1
        else:
            visual.append(kind)
    if total < MIN_REFERENCES:
        found.append(f"it lists {total} references; at least {MIN_REFERENCES} are needed")
    if text_only > MAX_TEXT_ONLY:
        found.append(f"{text_only} references are text-only (a capture that is no image, or an encyclopedia); at most "
                     f"{MAX_TEXT_ONLY} may be, and a text-only reference counts toward neither the kinds nor the "
                     "references outside web-ui")
    kinds = [kind for kind in visual if kind]
    outside = sum(kind != "web-ui" for kind in kinds)
    if len(set(kinds)) < MIN_KINDS or outside < MIN_OUTSIDE:
        found.append(f"the references seen as images cover {len(set(kinds))} kinds and {outside} references outside "
                     f"web-ui; at least {MIN_KINDS} kinds and {MIN_OUTSIDE} references outside web-ui are needed")
    return found


PROBE_URL = "https://example.org/"


def unreachable() -> str | None:
    """Why the network cannot be reached from here (one plain GET of a stable page), or None when it can. A server
    that answers with an error status was reached. `next --unavailable references` records only when this fails."""
    try:
        urllib.request.urlopen(PROBE_URL, timeout=10).close()
    except urllib.error.HTTPError:
        return None
    except (OSError, ValueError) as exc:
        return (str(exc).splitlines() or ["unreachable"])[0]
    return None


def why(task: str, found: list[str], planned: bool) -> str:
    """What the `references` step tells the run to do. `planned` says a plan already exists without the record."""
    record = record_path(Path("."), task).as_posix()
    captures = folder(Path("."), task).as_posix()
    shown = "; ".join(found[:3]) + (f"; and {len(found) - 3} more" if len(found) > 3 else "")
    lead = (f"The plan at .lapis/plans/{task}.yaml is in create mode, and no references record stands behind it "
            f"({shown}). Write the record, and change the plan wherever what you see contradicts it." if planned else
            f"Before the plan, look at references yourself; the record is not there yet ({shown}).")
    return " ".join([
        lead,
        "A reference counts when you have looked at it, not when you have read about it: an encyclopedia or any text",
        "page is not a visual reference. Follow the lzl-research skill's exploration guide.",
        "(1) Search for candidates (WebSearch, or `lazuli search --type source <words>` for where to look) in worlds",
        "beyond web design: the subject's own field, print, signage, objects, archives, works. Do not only recall",
        "addresses.",
        f"(2) Capture each: a web page with `lazuli ref capture <url> --rights reference-only --task {task}`",
        "(screenshots at 390, 768, and 1440 px, and the page's own HTML and CSS); a picture or an object with",
        f"`lazuli ref profile <image-url> --rights reference-only --task {task}` (the image itself; a page names its",
        "pictures in its saved digest). Both read the source registry first, so a `refused` or `browser-link` source",
        "stays refused: choose another. Keep a human pace, a few dozen requests in all, and follow no links.",
        "(3) Look: open each capture image with your harness's image viewer (Claude Code: Read the path), and for a",
        "web page read the saved HTML and CSS for its layout, type, and color decisions.",
        f"(4) Write {record}: a fenced ```yaml block with `captures: {STUDY_ONLY}` and `references`, each with `id`,",
        "`url` (or `source`), `maker` (author or institution), `kind`, `decision` (the open decision it informs),",
        f"`relation` (what you take from it, in what you saw), `capture` (a file under {captures}/), and, for web-ui,",
        "`source_facts` (values read from its CSS: sizes, faces, colors, grid).",
        f"Kinds: {', '.join(KINDS)}. Need at least {MIN_REFERENCES} references; among those seen as images at least",
        f"{MIN_KINDS} kinds and {MIN_OUTSIDE} references outside web-ui; every capture an existing file of its own; at",
        f"most {MAX_TEXT_ONLY} text-only.",
        "Take relations (order, ratio, rhythm, density, a label's job), never assets, text, or a layout wholesale.",
        "The captures are for study only: never ship them or copy them into the page.",
        "The brief's no-network or no-external-assets line limits what the page loads, never this research: looking is",
        "not shipping. Only when the network cannot be reached from here at all, record that with",
        f"`lapis-design next --task {task} --unavailable references --reason \"<the error you got>\"`. It sends one",
        "plain GET first and refuses the record when that works: a brief's line, a missing WebSearch, or a",
        "preference is no reason. A record it accepts is an environment record, not a pass, and the finished run",
        "reports that no references were looked at.",
        "Then cite the record from the plan's `context.other` and carry what you took into `references`,",
        "`explorations`, and `sources`."])
