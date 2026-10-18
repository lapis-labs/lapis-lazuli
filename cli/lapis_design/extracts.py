"""`lapis-design extract`: grounded excerpts of a document, kept once per run and read instead of the whole document.

A run's workers read the same brief, README, install notes, license text, and reference record again and again. `extract add`
copies a few lines of a source into `.lapis/extracts/<task>.json` (shape: `shared/extracts/schema.yaml`): the CLI cuts
the excerpt out of the file itself, so the text is the source's and never a worker's own words, and it keeps the source path,
the sha256 of the source's bytes, the line range (a `--heading` is resolved to one), and for a page taken from a URL the
address, the capture date, and the rights the owner gave it. There is no field for a summary or an opinion, and no
argument that could carry one.

`extract show` prints the extracts that still hold, with the source path and lines to open for the original. An extract
whose source changed (another hash), vanished, or whose text no longer matches its lines is stale: `show` prints no
text for it, says why and what to do, and exits 1, and `extract check` reports the same without printing text. `extract
drop` removes extracts (`--stale` every one that no longer holds); re-running `add` for the same lines replaces it.

The critic packet lists the record as an input (`critic_packet`), so the critic reads only grounded facts, and refuses a
record that is malformed, names a source the critic never reads (the maker's plan, answers, drafts, questions, disputes,
direction), holds text that differs from its source, or is stale.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from datetime import date
from pathlib import Path, PurePosixPath

import yaml
from jsonschema import Draft202012Validator

from lapis_design import shared_dir, telemetry

TASK = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
MAX_SOURCE_BYTES = 1_000_000
MAX_EXCERPT_CHARS = 4000        # "short": a longer passage is split, or read from the source
MAX_EXTRACTS = 200
# What the critic never reads (critic_packet.HIDDEN) and the record itself: never a source of an extract.
BLOCKED = (".lapis/plans", ".lapis/answers", ".lapis/drafts", ".lapis/questions", ".lapis/disputes", ".lapis/direction",
           ".lapis/extracts")
FORBIDDEN_PARTS = {".git", "CoreSync", "livetype"}
LINES = re.compile(r"(\d+)(?:-(\d+))?")
HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
FRESH, STALE, MISSING, ALTERED = "fresh", "stale", "missing", "altered"


class ExtractError(ValueError):
    """An extract or its record cannot be made or read as asked (exit 2 for a command, a PacketError for the critic)."""


def record_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "extracts" / f"{task}.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=None)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(yaml.safe_load((shared_dir() / "extracts" / "schema.yaml").read_text(encoding="utf-8")))


def _problem(document: object) -> str | None:
    error = next(iter(sorted(_validator().iter_errors(document), key=lambda e: list(map(str, e.absolute_path)))), None)
    return None if error is None else f"{'/'.join(map(str, error.absolute_path)) or 'document'}: {error.message}"


def source_lines(data: bytes, name: str) -> list[str]:
    """The lines of a text source: UTF-8, `\\n` or `\\r\\n` ends, no empty last line for a final newline."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ExtractError(f"{name} is not UTF-8 text; an extract holds lines of a text file") from None
    if "\x00" in text:
        raise ExtractError(f"{name} holds a NUL byte; an extract holds lines of a text file")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line.rstrip("\r") for line in lines]


def excerpt(lines: list[str], start: int, end: int) -> str:
    return "\n".join(lines[start - 1:end])


def extract_id(path: str, start: int, end: int) -> str:
    """The id of the extract of `path` lines `start`-`end`: the same lines of the same source are the same extract."""
    return "X" + digest(f"{path}\x00{start}\x00{end}".encode("utf-8"))[:8]


def blocked(rel: str) -> bool:
    return any(rel == name or rel.startswith(name + "/") for name in BLOCKED)


def named(root: Path, path: Path) -> str:
    """How a source is recorded: project-relative with `/` inside the project, else absolute with `/`. A link is not
    followed here (`read_source` refuses one as the last part)."""
    full = Path(os.path.abspath(path if path.is_absolute() else root / path))
    try:
        return full.relative_to(os.path.abspath(root)).as_posix()
    except ValueError:
        return full.as_posix()


def real_blocked(root: Path, name: str) -> bool:
    """Whether `name`, or where it really is (through a linked folder), is a maker's record."""
    try:
        real = locate(root, name).resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        real = name
    return blocked(name) or blocked(real)


def locate(root: Path, name: str) -> Path:
    """Where a recorded source is: relative to the project, or absolute."""
    path = Path(name)
    return path if path.is_absolute() else root / path


def read_source(root: Path, name: str) -> bytes:
    """The bytes of the source `name` (a regular file, not a link, within the size limit). ExtractError otherwise."""
    path = locate(root, name)
    if PurePosixPath(name).parts and any(part in FORBIDDEN_PARTS for part in PurePosixPath(name).parts):
        raise ExtractError(f"{name} is not a source an extract may hold (.git, Adobe CoreSync)")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ExtractError(f"{name} cannot be opened: {exc.strerror or exc}") from exc
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ExtractError(f"{name} is not a regular file")
        data = stream.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise ExtractError(f"{name} is over {MAX_SOURCE_BYTES:,} bytes; extract from a smaller source")
    return data


def heading_range(lines: list[str], wanted: str) -> tuple[int, int]:
    """The lines of the Markdown section whose heading text is `wanted`: from its heading line to the line before the next
    heading of the same or a higher level (or the end), skipping fenced code. ExtractError when none or several match."""
    found, fence = [], None
    for number, line in enumerate(lines, 1):
        mark = re.match(r"^\s*(`{3,}|~{3,})", line)
        if mark:
            fence = None if fence and mark.group(1)[0] == fence else (fence or mark.group(1)[0])
            continue
        if fence is None and (match := HEADING.match(line)) and " ".join(match.group(2).split()) == " ".join(wanted.split()):
            found.append((number, len(match.group(1))))
    if not found:
        raise ExtractError(f"no Markdown heading reads {wanted!r}")
    if len(found) > 1:
        raise ExtractError(f"{len(found)} Markdown headings read {wanted!r} (lines "
                           f"{', '.join(str(n) for n, _ in found)}); give --lines instead")
    start, level = found[0]
    fence = None
    for number in range(start + 1, len(lines) + 1):
        line = lines[number - 1]
        mark = re.match(r"^\s*(`{3,}|~{3,})", line)
        if mark:
            fence = None if fence and mark.group(1)[0] == fence else (fence or mark.group(1)[0])
            continue
        if fence is None and (match := HEADING.match(line)) and len(match.group(1)) <= level:
            return start, number - 1
    return start, len(lines)


def load(root: Path, task: str) -> dict:
    """The record of `task`, or an empty one when there is none. ExtractError when it is not valid JSON of the schema."""
    path = record_path(root, task)
    if not path.is_file():
        return {"version": 0, "task": task, "extracts": []}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExtractError(f"{path.relative_to(root).as_posix()} cannot be read: {exc}") from exc
    if problem := _problem(document):
        raise ExtractError(f"{path.relative_to(root).as_posix()} does not match extracts/schema.yaml: {problem}")
    if document["task"] != task:
        raise ExtractError(f"{path.relative_to(root).as_posix()} names task {document['task']!r}, not {task!r}")
    return document


def save(root: Path, document: dict) -> Path:
    path = record_path(root, document["task"])
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        mask = os.umask(0)
        os.umask(mask)
        os.chmod(name, 0o666 & ~mask)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return path


@dataclass
class Status:
    """One extract and whether it still holds: `state` is fresh, stale (another hash), missing, or altered (its text is not its
    lines); `now` is the source's hash now, `why` the sentence for a state that is not fresh, `source_chars` the size of the
    source as it is now (0 when missing)."""
    extract: dict
    state: str
    now: str | None = None
    why: str = ""
    source_chars: int = 0

    @property
    def where(self) -> str:
        locator = self.extract["locator"]
        return f"{self.extract['source']['path']}:{locator['start']}-{locator['end']}"


def judge(root: Path, item: dict, cache: dict[str, tuple[bytes | None, str]] | None = None) -> Status:
    """Whether `item` still holds: its source's bytes hash as recorded and its lines are the recorded text."""
    name, locator = item["source"]["path"], item["locator"]
    cache = {} if cache is None else cache
    if name not in cache:
        try:
            cache[name] = (read_source(root, name), "")
        except ExtractError as exc:
            cache[name] = (None, str(exc))
    data, error = cache[name]
    if data is None:
        return Status(item, MISSING, why=f"the source cannot be read now ({error})")
    now = digest(data)
    try:
        lines = source_lines(data, name)
    except ExtractError as exc:
        return Status(item, STALE, now, f"the source is no longer a text file ({exc})", len(data))
    chars = len("\n".join(lines))
    if now != item["source"]["sha256"]:
        return Status(item, STALE, now, f"the source changed since the extract was recorded (recorded sha256 "
                                        f"{item['source']['sha256'][:12]}, now {now[:12]})", chars)
    if locator["end"] > len(lines) or excerpt(lines, locator["start"], locator["end"]) != item["text"]:
        return Status(item, ALTERED, now, "its text is not the source's text at its lines, though the hash matches: the "
                                          "record was edited outside `lapis-design extract`", chars)
    return Status(item, FRESH, now, source_chars=chars)


def statuses(root: Path, document: dict) -> list[Status]:
    cache: dict[str, tuple[bytes | None, str]] = {}
    return [judge(root, item, cache) for item in document["extracts"]]


def verify(root: Path, task: str) -> list[str]:
    """What keeps the task's record from reaching a critic: a record that is not valid, an extract whose source the critic
    never reads, and every extract that is not fresh. Empty when there is no record or every extract holds."""
    path = record_path(root, task)
    if not path.is_file():
        return []
    try:
        document = load(root, task)
    except ExtractError as exc:
        return [str(exc)]
    problems = []
    for status in statuses(root, document):
        name = status.extract["source"]["path"]
        if real_blocked(root, name):
            problems.append(f"{status.extract['id']}: {name} is a maker's record the critic never reads, so no extract of it "
                            "may be listed")
        elif status.state != FRESH:
            problems.append(f"{status.extract['id']} ({status.where}): {status.why}")
    return problems


def add(root: Path, task: str, source: str, *, lines: str | None = None, heading: str | None = None, url: str | None = None,
        captured: str | None = None, rights: str | None = None) -> tuple[dict, list[Status], bool]:
    """Record the extract of `source` at `lines` (`A` or `A-B`) or the section under `heading`. Returns the extract, the
    other extracts of the same source that are no longer fresh, and whether it replaced one. ExtractError when refused."""
    if (lines is None) == (heading is None):
        raise ExtractError("give the locator: --lines A-B (or A), or --heading TEXT of a Markdown section; an extract "
                           "without a locator cannot be reopened at its original")
    if bool(url) != bool(captured) or (url and not rights):
        raise ExtractError("a page taken from a URL carries its address, the date it was captured, and the rights the owner "
                           "gave it: give --url, --captured YYYY-MM-DD, and --rights together")
    if url:
        try:
            date.fromisoformat(captured)
        except ValueError:
            raise ExtractError("--captured is a date as YYYY-MM-DD") from None
        if rights == "reference-only":
            raise ExtractError("a reference-only source keeps no copy of its text, so no extract of it is recorded")
        if not re.match(r"https?://[^\s]+$", url):
            raise ExtractError("--url is an http(s) address")
    path = locate(root, source)
    name = named(root, path)
    if real_blocked(root, name):
        raise ExtractError(f"{name} is a maker's record (plan, answers, draft, questions, dispute, direction, or an extract "
                           "record), which the critic never reads; extract the document it came from")
    data = read_source(root, name)
    text_lines = source_lines(data, name)
    if heading is not None:
        start, end = heading_range(text_lines, heading)
    else:
        match = LINES.fullmatch(lines.strip())
        if not match:
            raise ExtractError("--lines is A-B or A (1-based, inclusive)")
        start = int(match.group(1))
        end = int(match.group(2) or start)
    if heading is None and end < start:
        raise ExtractError(f"lines {start}-{end} run backwards: give --lines A-B with A at most B")
    if start < 1 or end < start or end > len(text_lines):
        raise ExtractError(f"lines {start}-{end} are not within {name}, which has {len(text_lines)} lines")
    text = excerpt(text_lines, start, end)
    if not text.strip():
        raise ExtractError(f"lines {start}-{end} of {name} are blank")
    if len(text) > MAX_EXCERPT_CHARS:
        raise ExtractError(f"lines {start}-{end} of {name} are {len(text):,} characters; an extract is at most "
                           f"{MAX_EXCERPT_CHARS:,}: take the lines that state the fact, or read the source")
    origin: dict = {"path": name, "sha256": digest(data)}
    if url:
        origin.update(url=url, captured=captured, rights=rights)
    locator: dict = {"start": start, "end": end}
    if heading is not None:
        locator["heading"] = " ".join(heading.split())
    item = {"id": extract_id(name, start, end), "source": origin, "locator": locator, "text": text}
    document = load(root, task)
    kept = [old for old in document["extracts"] if old["id"] != item["id"]]
    replaced = len(kept) != len(document["extracts"])
    if len(kept) + 1 > MAX_EXTRACTS:
        raise ExtractError(f"the record holds {MAX_EXTRACTS} extracts; drop stale or unused ones first")
    document["extracts"] = sorted([*kept, item], key=lambda e: (e["source"]["path"], e["locator"]["start"],
                                                                 e["locator"]["end"]))
    save(root, document)
    others = [s for s in statuses(root, document) if s.extract["source"]["path"] == name and s.extract["id"] != item["id"]
              and s.state != FRESH]
    return item, others, replaced


def drop(root: Path, task: str, ids: list[str], stale: bool) -> list[Status]:
    """Remove the extracts named in `ids`, and with `stale` every one that no longer holds. Returns what was removed."""
    document = load(root, task)
    found = statuses(root, document)
    unknown = [i for i in ids if i not in {s.extract["id"] for s in found}]
    if unknown:
        raise ExtractError(f"no extract {', '.join(unknown)} in {record_path(root, task).relative_to(root).as_posix()}")
    gone = [s for s in found if s.extract["id"] in ids or (stale and s.state != FRESH)]
    document["extracts"] = [e for e in document["extracts"] if e["id"] not in {s.extract["id"] for s in gone}]
    save(root, document)
    return gone


def _origin(item: dict) -> str:
    source = item["source"]
    return f"  from {source['url']}, captured {source['captured']} ({source['rights']})" if "url" in source else ""


def _stale_line(status: Status) -> str:
    return (f"{status.extract['id']}  {status.where}  {status.state.upper()}: {status.why}. No text is shown for it: open the "
            f"source at {status.where}, then record it again (`lapis-design extract add --task <task> --source "
            f"{status.extract['source']['path']} --lines {status.extract['locator']['start']}-{status.extract['locator']['end']}`) "
            f"or `lapis-design extract drop --task <task> --id {status.extract['id']}`")


def sizes(found: list[Status]) -> dict:
    """What reading the extracts that hold costs, and what the whole sources they come from would cost once each."""
    held = [s for s in found if s.state == FRESH]
    sources = {s.extract["source"]["path"]: s.source_chars for s in held}
    return {"extracts": len(found), "stale": len(found) - len(held), "extract_chars": sum(len(s.extract["text"]) for s in held),
            "source_chars": sum(sources.values()), "sources": len(sources)}


def render(found: list[Status]) -> str:
    """What `show` prints: each extract that holds with its source and lines, a notice for each that does not."""
    lines = []
    for status in found:
        if status.state == FRESH:
            item = status.extract
            lines.append(f"{item['id']}  {status.where}  sha256 {item['source']['sha256'][:12]}{_origin(item)}")
            lines.extend(f"    {line}" if line else "" for line in item["text"].split("\n"))
    lines += [_stale_line(s) for s in found if s.state != FRESH]
    size = sizes(found)
    if size["extracts"] == size["stale"]:
        lines.append(f"0 of {size['extracts']} extracts hold: read the sources at the paths and lines above")
    else:
        lines.append(f"{size['extracts'] - size['stale']} of {size['extracts']} extracts hold: {size['extract_chars']:,} characters "
                     f"read, instead of {size['source_chars']:,} for {size['sources']} whole sources; open a source at its path "
                     "and lines when a claim matters")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, prog: str = "lapis-design extract show") -> int:
    verb = prog.rsplit(" ", 1)[-1]
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n\n")[0], allow_abbrev=False)
    ap.add_argument("--task", help="the plan's task id (default: $LAPIS_TASK, else the newest plan under --root)")
    ap.add_argument("--root", type=Path, default=Path("."), help="the project folder (default: .)")
    if verb == "add":
        ap.add_argument("--source", required=True, help="the document: project-relative, or the absolute path of a text file")
        ap.add_argument("--lines", help="the lines to keep, A-B or A (1-based, inclusive)")
        ap.add_argument("--heading", help="the Markdown section to keep, by its heading text (instead of --lines)")
        ap.add_argument("--url", help="the address the source was taken from; needs --captured and --rights")
        ap.add_argument("--captured", help="the date the source was captured, YYYY-MM-DD")
        ap.add_argument("--rights", choices=("own", "licensed"), help="the rights the owner gave the page")
    elif verb == "drop":
        ap.add_argument("--id", action="append", default=[], help="an extract id (repeatable)")
        ap.add_argument("--stale", action="store_true", help="every extract that no longer holds")
    else:
        ap.add_argument("--source", help="only the extracts of this source")
        ap.add_argument("--id", action="append", default=[], help="only this extract (repeatable)")
    args = ap.parse_args(argv)
    from lapis_design import next_step

    task = next_step.resolve_task(args.root, args.task)
    if not task or not TASK.fullmatch(task):
        ap.error("no task found; pass --task (lowercase letters, digits, and hyphens)")
    if verb == "drop" and bool(args.id) == args.stale:
        ap.error("drop needs --id ID (repeatable) or --stale, one of them")
    root = args.root.resolve()
    started = telemetry.stamp()
    extra: dict = {}

    def done(code: int, text: str) -> int:
        (sys.stdout if code in (0, 1) else sys.stderr).write(text)
        telemetry.record(root, command=f"extract {verb}", task=task, scope="full", cache="off", started=started,
                         ended=telemetry.stamp(), exit=code, output_chars=len(text) if code in (0, 1) else 0,
                         report_path=record_path(root, task).relative_to(root).as_posix(), **extra)
        return code

    try:
        if verb == "add":
            item, others, replaced = add(root, task, args.source, lines=args.lines, heading=args.heading, url=args.url,
                                         captured=args.captured, rights=args.rights)
            where = f"{item['source']['path']}:{item['locator']['start']}-{item['locator']['end']}"
            out = [f"extract {item['id']}: {where}, {len(item['text']):,} characters, sha256 {item['source']['sha256']}"
                   + (" (replaced the extract of the same lines)" if replaced else "")]
            out += [f"  {_stale_line(s)}" for s in others]
            out.append(f"  a worker reads it with `lapis-design extract show --task {task}`; the original is the source at {where}")
            return done(0, "\n".join(out) + "\n")
        if verb == "drop":
            gone = drop(root, task, args.id, args.stale)
            extra["dropped"] = len(gone)
            return done(0, "".join(f"dropped {s.extract['id']} ({s.where}, {s.state})\n" for s in gone)
                        or "nothing to drop: every extract holds\n")
        found = statuses(root, load(root, task))
        if args.source:
            wanted = named(root, locate(root, args.source))
            found = [s for s in found if s.extract["source"]["path"] == wanted]
        if args.id:
            unknown = [i for i in args.id if i not in {s.extract["id"] for s in found}]
            if unknown:
                raise ExtractError(f"no extract {', '.join(unknown)}" + (f" of {args.source}" if args.source else ""))
            found = [s for s in found if s.extract["id"] in args.id]
        extra.update(sizes(found))
        if not found:
            return done(0 if verb == "check" else 1, f"extract {verb}: no extracts recorded for task {task}"
                        + (f" and source {args.source}" if args.source else "")
                        + "; read the document itself, or record a passage with `lapis-design extract add --task <task> "
                        "--source PATH --lines A-B`\n")
        if verb == "show":
            return done(1 if extra["stale"] else 0, render(found))
        out = [f"extract check: {extra['extracts'] - extra['stale']} of {extra['extracts']} extracts hold"]
        out += [f"  {_stale_line(s)}" for s in found if s.state != FRESH]
        if extra["extracts"] != extra["stale"]:                            # nothing that holds, nothing to cost
            out.append(f"  reading them costs {extra['extract_chars']:,} characters instead of {extra['source_chars']:,} for "
                       f"{extra['sources']} whole sources")
        return done(1 if extra["stale"] else 0, "\n".join(out) + "\n")
    except ExtractError as exc:
        return done(2, f"extract {verb}: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
