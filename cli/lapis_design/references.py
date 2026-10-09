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

References stand on three axes (`genre`, `expression`, `beyond-web`; hints.py). Each reference names its `axis`
and a `direction` (a lettered direction of the record's `directions` mapping, or `none`); it may name `found_at`
(the curation page where it was found) and `motion` (a recorded `.webm` or `.mp4`). Among the references seen as
images: at least two per axis, every beyond-web one outside `web-ui`; at least one expression reference found at
a registry source tagged `axes: [expression]` that lazuli may read; a motion file when the recorded hints offer
includes an expression mode that needs one; and at least one agent-found reference per axis beyond the whole hints
list. The record has at least three lettered directions, each holding at least two references from at least two axes.
Hints do not replace searching or change access policies.

A run with no network records that with `lapis-design next --unavailable references` (attempts.py), which
`next` counts as the step done and reports as a step that did not run. The command first tries one plain GET
(`unreachable`) and records only when that fails.

A run whose user's words could forbid lookups during the work, with nobody to ask, declines the step instead with
`lapis-design next --declined references --brief-line "<the line>"`. The line must be in what the run recorded of the
request, the brief record or the plan's `brief.constraints` (`declined_problem`); `next` then counts the step done,
the plan's `explorations` compare candidates from local material, and the finished run and `release check` report
that no reference was looked at and why (`declined`).

Stdlib and PyYAML only: `next` and the stop hook import this.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from lapis_design import attempts, hints, shared_dir, waiting

STEP = "references"
KINDS = {
    "web-ui": "a website, web app, app screen, or design system",
    "print": "a book, poster, packaging, label, map, or ticket",
    "signage": "wayfinding, a sign, lettering on a building, or a transit graphic",
    "physical-object": "a product, tool, instrument, or building",
    "archive": "a record from a museum, library, or archive",
    "media": "a painting, photograph, film, or other work",
}
AXES = hints.AXES
DIRECTION_LETTERS = "ABCDE"
MIN_REFERENCES, MIN_KINDS, MIN_OUTSIDE, MAX_TEXT_ONLY = 6, 3, 2, 2
MIN_PER_AXIS, MIN_DIRECTIONS, MIN_PER_DIRECTION = 2, 3, 2
MIN_IMAGE_BYTES = 1024
MIN_MOTION_BYTES = 10 * 1024
MOTION_SUFFIXES = {".webm", ".mp4"}
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


def _registry() -> list[dict]:
    return yaml.safe_load((shared_dir() / "sources/registry.yaml").read_text(encoding="utf-8"))["sources"]


def _expression_source(url: str) -> bool:
    """Whether `url` is on a host of a registry source tagged `axes: [expression]` that lazuli may read (access `read`
    or `adapter`). The host is all that can be checked: it proves the form of the claim, not the visit."""
    host = _host(url).removeprefix("www.")
    if not host:
        return False
    for entry in _registry():
        if "expression" in entry.get("axes", ()) and entry.get("access") in ("read", "adapter"):
            own = [urlsplit(entry["url"]).hostname or "", *entry.get("hosts", ())]
            if host in {name.lower().removeprefix("www.") for name in own}:
                return True
    return False


def _motion_problem(root: Path, task: str, value: Any, who: str) -> str | None:
    """Why `value` is no motion file (a `.webm` or `.mp4` of at least 10 KB under the task's folder), or None."""
    base = folder(root, task).resolve()
    if not isinstance(value, str) or not value.strip():
        return f"{who}: `motion` is empty"
    given = Path(value)
    target = (given if given.is_absolute() else root / given).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        return f"{who}: the motion file {value} does not exist under {folder(root, task).relative_to(root).as_posix()}/"
    try:
        with target.open("rb") as handle:
            head = handle.read(12)
        size = target.stat().st_size
    except OSError:
        return f"{who}: the motion file {value} cannot be read"
    magic = (head.startswith(b"\x1a\x45\xdf\xa3") if target.suffix.lower() == ".webm" else head[4:8] == b"ftyp")
    if target.suffix.lower() not in MOTION_SUFFIXES or not magic or size < MIN_MOTION_BYTES:
        return (f"{who}: {value} is not a recording ({' or '.join(sorted(MOTION_SUFFIXES))} of at least "
                f"{MIN_MOTION_BYTES // 1024} KB)")
    return None


def directions(root: Path, task: str) -> dict[str, dict]:
    """The record's lettered directions: {letter: {"name": the relation it organizes the page around, "refs": the
    references that name it}}; {} when there is no readable record."""
    try:
        data, _ = parse(record_path(root, task).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}
    if data is None or not isinstance(data.get("directions"), dict):
        return {}
    refs = [ref for ref in data["references"] if isinstance(ref, dict)]
    return {letter: {"name": name, "refs": [ref for ref in refs if ref.get("direction") == letter]}
            for letter, name in sorted(data["directions"].items())
            if letter in DIRECTION_LETTERS and len(letter) == 1 and isinstance(name, str)}


def direction_letters(root: Path, task: str) -> list[str]:
    """The letters the record defines under `directions`, sorted; [] when there is no readable record."""
    return list(directions(root, task))


def _direction_problems(data: dict, visual: list[tuple[str | None, str | None, str | None]]) -> list[str]:
    """At least three lettered directions, each named by a relation and holding at least two references seen as
    images from at least two axes."""
    defined = data.get("directions")
    if not isinstance(defined, dict):
        return [f"it has no `directions` mapping; at least {MIN_DIRECTIONS} letters ({DIRECTION_LETTERS[0]}-"
                f"{DIRECTION_LETTERS[-1]}), each named by the relation it would organize the page around"]
    found = []
    for letter, name in defined.items():
        if not (isinstance(letter, str) and len(letter) == 1 and letter in DIRECTION_LETTERS):
            found.append(f"direction {letter!r} is not one letter of {DIRECTION_LETTERS}")
        elif _words(name) < waiting.MIN_WORDS:
            found.append(f"direction {letter} has no name; name the relation it organizes the page around, not a mood")
    if len(defined) < MIN_DIRECTIONS:
        found.append(f"it defines {len(defined)} directions; at least {MIN_DIRECTIONS} are needed")
    for letter in defined:
        axes = {axis for _, axis, direction in visual if direction == letter and axis}
        count = sum(1 for _, _, direction in visual if direction == letter)
        if count < MIN_PER_DIRECTION or len(axes) < 2:
            found.append(f"direction {letter} holds {count} references seen as images from {len(axes)} axes; at least "
                         f"{MIN_PER_DIRECTION} references from 2 axes are needed")
    return found


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
    offered = hints.read(root, task)
    if offered is None:
        found.append(hints.stale(root, task) or f"no valid hints offer is recorded; run `lazuli hints --task {task} "
                     "--genre <nearest-field-or-none> [--expression <mode>] [--beyond-web <medium>]`")
    if data.get("captures") != STUDY_ONLY:
        found.append(f"it does not say `captures: {STUDY_ONLY}`")
    base = folder(root, task).resolve()
    seen: dict[str, str] = {}
    urls: dict[str, str] = {}
    ids: set[str] = set()
    visual: list[tuple[str | None, str | None, str | None]] = []     # (kind, axis, direction) of each reference seen as an image
    letters = [letter for letter in (data.get("directions") if isinstance(data.get("directions"), dict) else {})
               if isinstance(letter, str) and len(letter) == 1 and letter in DIRECTION_LETTERS]
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
        axis = ref.get("axis")
        if axis not in AXES:
            found.append(f"{who}: `axis` is {axis!r}, not one of {', '.join(AXES)}")
            axis = None
        elif axis == "beyond-web" and kind == "web-ui":
            found.append(f"{who} is on the beyond-web axis but its kind is web-ui; a beyond-web reference is print, "
                         "signage, a physical object, an archive record, or a work")
        direction = ref.get("direction")
        if direction != "none" and direction not in letters and (direction is None or isinstance(data.get("directions"), dict)):
            found.append(f"{who}: `direction` is {direction!r}; use a letter of the record's `directions` "
                         f"({', '.join(letters) or 'none defined'}) or `none`")
            direction = None
        if ref.get("found_at") is not None and not (isinstance(ref["found_at"], str) and _host(ref["found_at"])
                                                    and urlsplit(ref["found_at"]).scheme in ("http", "https")):
            found.append(f"{who}: `found_at` is not an http(s) address")
        if ref.get("motion") is not None and (why_not := _motion_problem(root, task, ref["motion"], who)):
            found.append(why_not)
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
            visual.append((kind, axis, direction))
    if total < MIN_REFERENCES:
        found.append(f"it lists {total} references; at least {MIN_REFERENCES} are needed")
    if text_only > MAX_TEXT_ONLY:
        found.append(f"{text_only} references are text-only (a capture that is no image, or an encyclopedia); at most "
                     f"{MAX_TEXT_ONLY} may be, and a text-only reference counts toward neither the kinds nor the "
                     "references outside web-ui")
    kinds = [kind for kind, _, _ in visual if kind]
    outside = sum(kind != "web-ui" for kind in kinds)
    if len(set(kinds)) < MIN_KINDS or outside < MIN_OUTSIDE:
        found.append(f"the references seen as images cover {len(set(kinds))} kinds and {outside} references outside "
                     f"web-ui; at least {MIN_KINDS} kinds and {MIN_OUTSIDE} references outside web-ui are needed")
    for name in AXES:
        count = sum(1 for _, axis, _ in visual if axis == name)
        if count < MIN_PER_AXIS:
            found.append(f"{count} references on the {name} axis are seen as images; at least {MIN_PER_AXIS} are needed "
                         f"per axis ({', '.join(AXES)})")
        if hints.agent_found(data["references"], name) < 1:
            found.append(f"no agent-found reference is on the {name} axis beyond the whole hints list; at least one per "
                         "axis is needed (a list entry's host and path do not count)")
    expression = [ref for ref in data["references"] if isinstance(ref, dict) and ref.get("axis") == "expression"]
    if not any(isinstance(ref.get("found_at"), str) and _expression_source(ref["found_at"]) for ref in expression):
        found.append("no expression reference has a `found_at` on a registry source tagged `axes: [expression]` that "
                     "lazuli may read (`lazuli sources --axis expression`); look at one of those curation pages and "
                     "name the page where you found the work")
    if offered is not None and any(hints.load()["axes"]["expression"][mode]["motion"] for mode in offered["expression"]):
        if not any(isinstance(ref.get("motion"), str) and not _motion_problem(root, task, ref["motion"], "x")
                   for ref in expression):
            found.append("the hints offer includes an expression mode that moves, so at least one expression reference "
                         "needs a `motion` file (`lazuli ref capture <url> --motion --task <task>`, or your own "
                         f"recording of at least {MIN_MOTION_BYTES // 1024} KB under {folder(root, task).relative_to(root).as_posix()}/)")
    found += _direction_problems(data, visual)
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


_QUOTES = "\"'`“”‘’「」『』«»"


def _squash(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def clean_line(text: str) -> str:
    """A quoted line as it is compared: white space collapsed, wrapping quotation marks and a closing full stop
    dropped (in either order: `"...".` and `"...."` are the same line)."""
    line, before = _squash(text), None
    while line != before:
        line, before = line.strip(_QUOTES + " ").rstrip(".。 "), line
    return line


def request_texts(root: Path, task: str, plan: Any = None) -> list[str]:
    """What the run recorded of the request, each part apart: the brief record, and each item of the plan's
    `brief.constraints` when a plan is given."""
    found: list[str] = []
    try:
        found.append(waiting.answers_path(root, task).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        pass
    brief = plan.get("brief") if isinstance(plan, dict) else None
    constraints = brief.get("constraints") if isinstance(brief, dict) else None
    if isinstance(constraints, list):
        found.extend(item for item in constraints if isinstance(item, str))
    return found


def declined_problem(line: str, root: Path, task: str, plan: Any = None) -> str | None:
    """Why `line` cannot decline the step, or None when it can: it has to be a line of the request as the run
    recorded it (verbatim, white space aside) in the brief record or the plan's `brief.constraints`. The check
    cannot tell whether the line forbids lookups; it keeps the claim from being the run's own wording."""
    line = clean_line(line)
    if len(_WORD.findall(line)) < waiting.MIN_WORDS and len(line) < 8:
        return f"{line!r} is too short to be a line of the request; quote the whole line"
    if any(line in _squash(text) for text in request_texts(root, task, plan)):
        return None
    return (f"{line!r} is not in the brief record {waiting.answers_path(Path('.'), task).as_posix()} or in the plan's "
            "brief.constraints, so it is not recorded as the user's words. Copy the line of the request into the "
            "record's `## Found` section exactly as the user wrote it, then run this again; a line the request does "
            "not hold cannot decline a step")


def declined(root: Path, task: str, plan: Any = None) -> dict[str, Any] | None:
    """The record that declines the step, when it stands: one of ours, newer than any references record the run
    wrote after it, and its line still in the request as recorded (a brief rewritten since cannot keep it)."""
    found = attempts.read_declined(root, task, STEP)
    if found is None:
        return None
    mine = record_path(root, task)
    try:
        if mine.is_file() and mine.stat().st_mtime > attempts.path(root, task, STEP).stat().st_mtime:
            return None
    except OSError:
        return None
    return found if declined_problem(found["brief_line"], root, task, plan) is None else None


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
        "(0) Draw starting points on three axes: `lazuli hints` lists the genre fields, expression modes, and",
        f"beyond-web media; record the offer with `lazuli hints --task {task} --genre <field|none> --expression <mode>",
        "--beyond-web <medium>` (`lazuli hints --suggest --task <task>` names the modes the owner's words point at; you",
        "choose, and the direction conversation states the choice). These are starting points, not a canon: on every",
        "axis find at least one reference beyond the whole hints list. The offer is saved in",
        ".lapis/references/<task>.hints.json; repeating the same choice keeps its original date and offer.",
        "(1) Search per axis (WebSearch, or `lazuli sources --axis <axis>` for where to look). Genre: pages of the",
        "subject's own kind. Expression: start from the registry sources tagged expression and from the owner's",
        "expression words, for work that does what they ask (motion, experimental type, generative or 3D). Beyond-web:",
        "the subject's world in print, exhibitions, music, film, and objects, never a web-ui reference. Do not only",
        "recall addresses.",
        f"(2) Capture each: a web page with `lazuli ref capture <url> --rights reference-only --task {task}`",
        "(screenshots at 390, 768, and 1440 px, and the page's own HTML and CSS); a picture or an object with",
        f"`lazuli ref profile <image-url> --rights reference-only --task {task}` (the image itself; a page names its",
        "pictures in its saved digest). Both read the source registry first, so a `refused` or `browser-link` source",
        "stays refused: choose another. Keep a human pace, a few dozen requests in all, and follow no links.",
        "For an expression reference whose point is movement, add `--motion` (a 6-second scripted scroll at 1440 px, saved",
        "as motion.webm with a 4-frame strip.png beside the screenshots).",
        "(3) Look, before you write anything about it: open each capture image with your harness's image viewer",
        "(Claude Code: the Read tool on the image path; a description from a search snippet, a page summary, or",
        "memory is not looking, and a relation that describes a picture you did not open is invented). For a web",
        "page also read the saved HTML and CSS for its layout, type, and color decisions.",
        f"(4) Write {record}: a fenced ```yaml block with `captures: {STUDY_ONLY}`, `directions` (at least",
        f"{MIN_DIRECTIONS} letters A-E, each named by the relation it would organize the page around, not a mood), and",
        "`references`, each with `id`, `url` (or `source`), `maker` (author or institution), `kind`, `axis`, `direction`",
        "(a letter, or `none`), `decision` (the open decision it informs), `relation` (what you take from it, in what",
        f"you saw), `capture` (a file under {captures}/), for web-ui `source_facts` (values read from its CSS), and",
        "where they apply `found_at` (the curation page where you found it) and `motion` (a recording).",
        f"Kinds: {', '.join(KINDS)}. Need at least {MIN_REFERENCES} references; among those seen as images at least",
        f"{MIN_KINDS} kinds and {MIN_OUTSIDE} references outside web-ui, {MIN_PER_AXIS} per axis, a beyond-web kind that is",
        "never web-ui, one expression reference with `found_at` on a registry expression source, a `motion` file when the",
        f"offer has a moving mode, and each direction holding {MIN_PER_DIRECTION} references from 2 axes; every capture an",
        f"existing file of its own; at most {MAX_TEXT_ONLY} text-only. `lapis-design references sheet --task {task}` makes",
        "the sheet for the owner.",
        "Take relations (order, ratio, rhythm, density, a label's job), never assets, text, or a layout wholesale.",
        "The captures are for study only: never ship them or copy them into the page.",
        "Follow the user's words. If the request or the brief forbids network use, lookups, or downloads during the work",
        "and nobody can be asked, do not look things up and do not stop: decline this step with the user's own line, as",
        "the brief record or the plan's `brief.constraints` holds it:",
        f"`lapis-design next --task {task} --declined references --brief-line \"<the line>\"`. It refuses a line that is",
        "in neither: copy the request's line into the brief record's `## Found` as the user wrote it, then run it",
        "again. Then plan from local material (installed fonts, the project, the brief's facts), with no lookups.",
        "If the network cannot be reached from here at all, record that with",
        f"`lapis-design next --task {task} --unavailable references --reason \"<the error you got>\"`; it sends one",
        "plain GET first and refuses the record when that works. Neither record is a pass: the finished run reports",
        "that no references were looked at.",
        "Then cite the record from the plan's `context.other` and carry what you took into `references`,",
        "`explorations`, and `sources`."])
