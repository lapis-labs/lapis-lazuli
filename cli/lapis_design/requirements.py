"""The requirement record: the owner's own words, copied by the CLI into `.lapis/requirements/<task>.json`.

`lapis-design requirements seal --task T [--from OWNER_BRIEF ...]` reads up to five files the owner wrote (outside
`.lapis/`, 200 KB each, UTF-8) and every `[declared]` item of the brief record `.lapis/answers/<task>.md`. Each list
item (at any depth, without its children), table body row, fenced code block, and run of prose lines becomes one
row; headings become the `section` of the rows below them. A row's id is `R` and the first six hex digits of the
SHA-256 of its text (NFKC, case-folded, white space collapsed), eight when two different texts share six. The same
text in two places is one row with two `at` entries. The schema is `shared/requirements/schema.yaml`.

An agent never writes the record, so it cannot drop, reword, or leave out a row. `refresh` (run on every CLI call
that reads the plan, by `integrity.observe`) reads the recorded sources again: new text adds rows, text that is gone
moves its row to `removed`, and an owner reply that quotes a row's id (`[declared] R3f2a1c: drop — <words>` or
`narrow`) is copied to `owner_decisions`. Those two kinds of line are no rows of their own, and neither is the owner's
pick among slice candidates (`[declared] Slice: <url> — <words>`). A sealed source is never forgotten: sealing again
adds files, it does not take them away.

The record holds no times, so the same inputs give the same bytes (the critic packet and the owner block hash it).

Stdlib only until `validate` is asked for: the stop hook imports `next_step`, which imports this.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Sequence

from lapis_design import brief

STEP = "requirements"
MAX_FILES = 5
MAX_BYTES = 200 * 1024
MAX_ROWS = 300
KINDS = ("owner-file", "answers")

_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
_HEAD = re.compile(r"^\s{0,3}(#{1,6})(?:\s+(.*?))?\s*#*\s*$")
_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d{1,9}[.)])\s+(\S.*)$")
_RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_SETEXT = re.compile(r"^\s{0,3}(?:=+|-+)\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$|^\s*\|\s*:?-+:?\s*\|?\s*$")
_QUOTE = re.compile(r"^\s{0,3}(?:>\s?)+")
_ID = re.compile(r"R[0-9a-f]{6}(?:[0-9a-f]{2})?")
_DECISION = re.compile(r"^(R[0-9a-f]{6}(?:[0-9a-f]{2})?)\s*:\s*(drop|narrow)\s*(?:—|–|--|-)\s*(\S.*)$",
                       re.IGNORECASE | re.DOTALL)
_PICK = re.compile(r"^slice\s*:", re.IGNORECASE)
_PICK_URL = re.compile(r"^slice\s*:\s*(\S+)", re.IGNORECASE)
_LEAD = re.compile(r"^[\s*_`:\-–—]+")


class RequirementsError(ValueError):
    """A seal that must not go on, or a record that cannot be rebuilt; the message is the reason."""


def record_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "requirements" / f"{task}.json"


def answers_name(task: str) -> str:
    return f".lapis/answers/{task}.md"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm(text: str) -> str:
    """The form the ids and the keep evidence compare in: NFKC, case-folded, white space collapsed."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def write_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` so that no reader sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


# ---------------------------------------------------------------- reading the owner's files

def extract(path: Path | str, name: str | None = None) -> list[dict]:
    """The rows of the Markdown file at `path`, in order, as `{text, section?, kind, at}`; `name` is the path the
    rows record (default: `path`). The file is read as UTF-8 (UnicodeDecodeError and OSError are the caller's)."""
    path = Path(path)
    return rows_of(path.read_text(encoding="utf-8"), name or path.as_posix())


def rows_of(text: str, name: str) -> list[dict]:
    lines = [_QUOTE.sub("", line).expandtabs(4) for line in text.splitlines()]
    rows: list[dict] = []
    section: str | None = None
    para: list[tuple[int, str]] = []          # the run of prose lines being read
    item: list[tuple[int, str]] = []          # the list item being read: its own lines, not its children's

    def add(kind: str, body: list[tuple[int, str]], span: tuple[int, int] | None = None) -> None:
        joined = "\n".join(t for _, t in body).strip()
        if re.search(r"\w", joined):
            first, last = span or (body[0][0], body[-1][0])
            rows.append({"text": joined, **({"section": section} if section else {}), "kind": kind,
                         "at": [{"path": name, "lines": [first, last]}]})

    def flush() -> None:
        nonlocal para, item
        if para:
            add("paragraph", para)
        if item:
            add("item", item)
        para, item = [], []

    i, count = 0, len(lines)
    if count and lines[0].strip() == "---":          # front matter is the file's first row
        end = next((j for j in range(1, count) if lines[j].strip() in ("---", "...")), None)
        if end is not None:
            add("code", [(j + 1, lines[j]) for j in range(1, end)], (1, end + 1))
            i = end + 1
    while i < count:
        line, number = lines[i], i + 1
        stripped = line.strip()
        fence = _FENCE.match(line)
        if fence:
            flush()
            marker = fence.group(2)
            close = re.compile(r"^\s*" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*$")
            end = next((j for j in range(i + 1, count) if close.match(lines[j])), count)
            indent = len(fence.group(1))
            add("code", [(j + 1, lines[j][indent:] if not lines[j][:indent].strip() else lines[j])
                         for j in range(i + 1, end)] or [(number, "")], (number, min(end + 1, count)))
            i = end + 1
            continue
        if stripped.startswith("<!--"):
            flush()
            end = next((j for j in range(i, count) if "-->" in lines[j]), count - 1)
            i = end + 1
            continue
        if not stripped:
            flush()
            i += 1
            continue
        head = _HEAD.match(line)
        if head:
            flush()
            section = (head.group(2) or "").strip() or None
            i += 1
            continue
        if para and _SETEXT.match(line):                       # a paragraph underlined by === or ---
            section = " ".join(t for _, t in para)
            para = []
            i += 1
            continue
        if _RULE.match(line):
            flush()
            i += 1
            continue
        if "|" in line and i + 1 < count and "|" in lines[i + 1] and _TABLE_SEP.match(lines[i + 1]):
            flush()
            i += 2                                              # the header row and its rule name columns, no rows
            while i < count and lines[i].strip() and "|" in lines[i]:
                cells = [c.strip() for c in _cells(lines[i])]
                if any(cells):
                    add("table-row", [(i + 1, " | ".join(cells))])
                i += 1
            continue
        bullet = _ITEM.match(line)
        if bullet:
            flush()
            item = [(number, bullet.group(2).strip())]
        elif item:
            item.append((number, line.strip()))                 # a line right under an item goes on with it
        else:
            para.append((number, line.strip()))
        i += 1
    flush()
    return rows


def _cells(line: str) -> list[str]:
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [c.replace("\\|", "|") for c in re.split(r"(?<!\\)\|", body)]


def _answer_items(text: str) -> list[dict]:
    """The top-level items of the brief record with their first and last line and their heading: the items at the
    outermost indent under each heading (as `brief.answer_rounds` counts them), with the lines below an item, a
    sub-list among them, going on with it."""
    chunks: list[tuple[str | None, list[tuple[int, str]]]] = [(None, [])]
    for number, line in enumerate(text.splitlines(), 1):
        if head := brief._HEADING.match(line):
            chunks.append((head.group(2).strip() or None, []))
        else:
            chunks[-1][1].append((number, line))
    found: list[dict] = []
    for section, lines in chunks:
        top = min((len(line) - len(line.lstrip()) for _, line in lines if brief._ITEM.match(line)), default=0)
        current: dict | None = None
        for number, line in lines:
            bullet = brief._ITEM.match(line)
            if bullet and len(line) - len(line.lstrip()) == top:
                current = {"lines": [number, number], "parts": [bullet.group(1)], "section": section}
                found.append(current)
            elif current and line.strip():
                current["parts"].append(line.strip())
                current["lines"][1] = number
    return found


def _declared_items(text: str) -> Iterable[tuple[dict, str, str]]:
    """Each `[declared]` top-level item of a brief record as (the item, its text as written, its words after the tag)."""
    for found in _answer_items(text):
        quote = "\n".join(found["parts"])
        tag = brief._TAG.match(quote)
        if tag and tag.group(1).lower() == "declared":
            yield found, quote, _LEAD.sub("", quote[tag.end():])


def _declared(text: str, name: str) -> tuple[list[dict], list[dict]]:
    """`[declared]` answers as rows, and the owner's decisions among them. A decision line and a slice pick are no rows."""
    rows, decisions = [], []
    for found, quote, body in _declared_items(text):
        if decided := _DECISION.match(body):
            decisions.append({"row": "R" + decided.group(1)[1:].lower(), "decision": decided.group(2).lower(),
                              "quote": quote, "at": {"path": name, "line": found["lines"][0]}})
        elif body and not _PICK.match(body) and re.search(r"\w", body):
            rows.append({"text": body, **({"section": found["section"]} if found["section"] else {}),
                         "kind": "declared", "at": [{"path": name, "lines": found["lines"]}]})
    return rows, decisions


# ---------------------------------------------------------------- the record

def _problem(doc: Any, task: str) -> str | None:
    """Why `doc` is not a record of `task`, or None. A light check of the shape the code reads; `validate` is the schema."""
    if not isinstance(doc, dict) or doc.get("version") != 0:
        return "it is not a version 0 requirement record"
    if doc.get("task") != task:
        return f"it names task {doc.get('task')!r}, not {task!r}"
    rows, sources = doc.get("rows"), doc.get("sources")
    if not isinstance(sources, list) or not all(isinstance(s, dict) and isinstance(s.get("path"), str)
                                                and s.get("kind") in KINDS and isinstance(s.get("sha256"), str)
                                                for s in sources):
        return "its `sources` are not a list of {path, sha256, kind}"
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("id"), str)
                                             and isinstance(r.get("text"), str) for r in rows):
        return "its `rows` are not a list of {id, text, ...}"
    if not all(isinstance(doc.get(k), list) for k in ("owner_decisions", "removed")):
        return "it has no `owner_decisions` and `removed` lists"
    return None


def record(root: Path, task: str) -> dict | None:
    """The requirement record of `task` under `root`, or None when it is absent or not a record."""
    try:
        doc = json.loads(record_path(root, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if _problem(doc, task) is None else None


def rows(root: Path, task: str) -> list[dict] | None:
    """The rows of the record, or None when there is no record."""
    doc = record(root, task)
    return None if doc is None else doc["rows"]


def sha256(root: Path, task: str) -> str | None:
    """The SHA-256 of the record file's bytes, or None when there is no file."""
    try:
        return _sha(record_path(root, task).read_bytes())
    except OSError:
        return None


def owed(root: Path, task: str) -> str | None:
    """Why the `requirements` step is owed, or None when the record is in place."""
    where = record_path(root, task).relative_to(root).as_posix()
    try:
        doc = json.loads(record_path(root, task).read_text(encoding="utf-8"))
    except OSError:
        return f"{where} does not exist"
    except ValueError:
        return f"{where} is not JSON"
    problem = _problem(doc, task)
    return f"{where} is not a requirement record: {problem}" if problem else None


def why(task: str, reason: str) -> str:
    """What the `requirements` step tells the run to do."""
    where = record_path(Path("."), task).as_posix()
    return (f"Before the references and the plan, the owner's own words have to be copied into the requirement record "
            f"({reason}). Run `lapis-design requirements seal --task {task} --from <the owner's brief file>`, once per "
            f"file the owner wrote their brief in (up to {MAX_FILES}, inside the project and outside .lapis/; leave "
            f"--from out when the owner gave no file, and the record then holds their `[declared]` answers). The CLI "
            "copies each list item, table row, paragraph, and code block as one row with an id, and every `[declared]` "
            "answer too; you cannot drop, reword, or add one, and never write "
            f"{where} by hand. A row leaves the owner's block only when the owner's own reply quotes its id "
            "(`[declared] R3f2a1c: drop — <their words>`). Pass the owner's brief, not product documentation: that "
            f"belongs in the plan's `context.product` or `context.other`. Run `lapis-design requirements show --task "
            f"{task}` to read the rows, then `lapis-design next --task {task}` again.")


def _read(root: Path, name: str, kind: str) -> tuple[str | None, str]:
    """The text of a recorded source and the SHA-256 of the bytes read; a file that is gone or cannot be read as
    UTF-8 text inside the limits reads as empty, so the rows it gave are listed as removed."""
    path = root / name
    try:
        if kind == "owner-file" and not path.resolve().is_relative_to(root.resolve()):
            raise OSError
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise OSError
        data = path.read_bytes()
        return data.decode("utf-8"), _sha(data)
    except (OSError, UnicodeDecodeError):
        return None, _sha(b"")


def _ids(merged: dict[str, dict]) -> None:
    """Give each row of `merged` (by normalized text) its id."""
    digests = {key: _sha(key.encode("utf-8")) for key in merged}
    short: dict[str, list[str]] = {}
    for key, digest in digests.items():
        short.setdefault(digest[:6], []).append(key)
    for key, row in merged.items():
        digits = 8 if len(short[digests[key][:6]]) > 1 else 6
        row["id"] = "R" + digests[key][:digits]


def _build(root: Path, task: str, owner_files: Sequence[str], previous: dict | None) -> dict:
    """The record that `owner_files` and the answers file give now, keeping `previous`'s history of removed rows."""
    names = [(n, "owner-file") for n in owner_files] + [(answers_name(task), "answers")]
    sources: list[dict] = []
    merged: dict[str, dict] = {}
    decisions: list[dict] = []
    for name, kind in names:
        text, digest = _read(root, name, kind)
        sources.append({"path": name, "sha256": digest, "kind": kind})
        if text is None:
            continue
        if kind == "answers":
            found, decisions = _declared(text, name)
        else:
            found = rows_of(text, name)
        for row in found:
            key = norm(row["text"])
            if key in merged:
                merged[key]["at"].extend(row["at"])
            else:
                merged[key] = row
    if len(merged) > MAX_ROWS:
        raise RequirementsError(
            f"{len(merged)} rows are more than the {MAX_ROWS} a record holds. Name the owner's brief, not product "
            "documentation; product docs belong in `context.product`/`context.other`")
    _ids(merged)
    current = [{"id": r["id"], "text": r["text"], **({"section": r["section"]} if "section" in r else {}),
                "kind": r["kind"], "at": r["at"]} for r in merged.values()]
    present = {r["id"] for r in current}
    history: dict[str, dict] = {}
    for entry in (previous or {}).get("removed", []):
        if entry["id"] not in present:
            history[entry["id"]] = entry
    for old in (previous or {}).get("rows", []):
        if old["id"] not in present:
            history[old["id"]] = {"id": old["id"], "text": old["text"], "at": old["at"]}
    return {"version": 0, "task": task, "sources": sources, "rows": current, "owner_decisions": decisions,
            "removed": list(history.values())}


def _changes(old: dict | None, new: dict) -> list[dict]:
    """What differs between two records, as `{pointer, before, after}` items for the change log (kind `requirements`)."""
    if old is None:
        return []
    out: list[dict] = []
    before, after = {r["id"]: r for r in old["rows"]}, {r["id"]: r for r in new["rows"]}
    out += [{"pointer": f"/requirements/{i}", "before": r["text"], "after": None}
            for i, r in before.items() if i not in after]
    out += [{"pointer": f"/requirements/{i}", "before": None, "after": r["text"]}
            for i, r in after.items() if i not in before]
    said_before = {(d["row"], d["decision"], d["quote"]) for d in old["owner_decisions"]}
    said_after = {(d["row"], d["decision"], d["quote"]) for d in new["owner_decisions"]}
    out += [{"pointer": f"/requirements/owner_decisions/{row}", "before": f"{decision} — {quote}", "after": None}
            for row, decision, quote in sorted(said_before - said_after)]
    out += [{"pointer": f"/requirements/owner_decisions/{row}", "before": None, "after": f"{decision} — {quote}"}
            for row, decision, quote in sorted(said_after - said_before)]
    return out


def _dump(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def _store(root: Path, task: str, old: dict | None, new: dict) -> list[dict]:
    if old is None or _dump(old) != _dump(new):
        write_atomic(record_path(root, task), _dump(new))
    return _changes(old, new)


def refresh(root: Path, task: str) -> list[dict]:
    """Read the recorded sources again and write the record when they changed; the changes it found, as
    `{pointer, before, after}` items. No record, no change."""
    old = record(root, task)
    if old is None:
        return []
    owner_files = [s["path"] for s in old["sources"] if s["kind"] == "owner-file"]
    return _store(root, task, old, _build(root, task, owner_files, old))


def _owner_file(root: Path, name: str) -> str:
    """The project-relative path of an owner file `--from` may name, or RequirementsError."""
    base = root.resolve()
    path = Path(name) if Path(name).is_absolute() else base / name
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise RequirementsError(f"{name} is not a file") from None
    if not resolved.is_relative_to(base):
        raise RequirementsError(f"{name} is outside the project folder")
    rel = resolved.relative_to(base).as_posix()
    if rel.startswith(".lapis/"):
        raise RequirementsError(f"{name} is under .lapis/: name a file the owner wrote, not a record of this tool")
    if not resolved.is_file():
        raise RequirementsError(f"{name} is not a regular file")
    if resolved.stat().st_size > MAX_BYTES:
        raise RequirementsError(f"{name} is larger than {MAX_BYTES // 1024} KB: name the owner's brief, not product "
                                "documentation; product docs belong in `context.product`/`context.other`")
    try:
        resolved.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise RequirementsError(f"{name} is not UTF-8 text") from None
    return rel


def seal(root: Path, task: str, owner_files: Iterable[str] = ()) -> list[dict]:
    """Write the record from the owner's files and the `[declared]` answers, adding `owner_files` to the files an
    earlier seal read. Returns the changes against the record that was there, as `refresh` does. Raises
    RequirementsError when the record cannot be sealed."""
    root = root.resolve()
    if reason := brief.record_problem(root, task):
        raise RequirementsError(f"the brief record is not in order ({reason}); seal after it is written")
    old = record(root, task)
    files = [s["path"] for s in (old or {}).get("sources", []) if s["kind"] == "owner-file"]
    for name in owner_files:
        rel = _owner_file(root, name)
        if rel not in files:
            files.append(rel)
    if len(files) > MAX_FILES:
        raise RequirementsError(f"{len(files)} files are more than the {MAX_FILES} an owner's brief may use")
    return _store(root, task, old, _build(root, task, files, old))


# ---------------------------------------------------------------- coverage and the command

def uncovered(root: Path, task: str, report: Any) -> list[str]:
    """The ids of the record's rows that the critic report's `requirements` list does not judge (none without a record)."""
    judged = {r.get("id") for r in (report.get("requirements") or ()) if isinstance(r, dict)} \
        if isinstance(report, dict) and isinstance(report.get("requirements") or [], list) else set()
    return [r["id"] for r in rows(root, task) or () if r["id"] not in judged]


def validate(doc: Any) -> list[str]:
    """The problems `shared/requirements/schema.yaml` finds in `doc`."""
    import yaml
    from jsonschema import Draft202012Validator

    from lapis_design import shared_dir

    schema = yaml.safe_load((shared_dir() / "requirements" / "schema.yaml").read_text(encoding="utf-8"))
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in Draft202012Validator(schema).iter_errors(doc)]


def _show(doc: dict) -> str:
    decided = {d["row"]: d["decision"] for d in doc["owner_decisions"]}
    lines = [f"{len(doc['rows'])} rows from {', '.join(s['path'] for s in doc['sources'])}"]
    for row in doc["rows"]:
        text = " ".join(row["text"].split())
        text = text if len(text) <= 100 else text[:99] + "…"
        mark = f" [{decided[row['id']]}]" if row["id"] in decided else ""
        lines.append(f"{row['id']}{mark}  {text}" + (f"  ({row['section']})" if row.get("section") else ""))
    for entry in doc["removed"]:
        lines.append(f"{entry['id']} [removed]  {' '.join(entry['text'].split())[:100]}")
    for d in doc["owner_decisions"]:
        lines.append(f"owner {d['decision']} {d['row']}: {' '.join(d['quote'].split())}")
    return "\n".join(lines)


def main(argv: list[str] | None = None, prog: str = "lapis-design requirements seal") -> int:
    verb = prog.rsplit(" ", 1)[-1]
    ap = argparse.ArgumentParser(prog=prog, allow_abbrev=False, description=__doc__.split("\n")[0])
    ap.add_argument("--task", help="the plan's task id (default: $LAPIS_TASK, else the newest plan under --root)")
    ap.add_argument("--root", type=Path, default=Path("."), help="the project folder (default: .)")
    if verb == "seal":
        ap.add_argument("--from", dest="owner_files", action="append", default=[], metavar="FILE",
                        help=f"a file the owner wrote their brief in (up to {MAX_FILES}; repeat); the answers file's "
                        "[declared] items are always added")
    else:
        ap.add_argument("--json", action="store_true", help="print the record as JSON")
    args = ap.parse_args(argv)
    from lapis_design import attempts, next_step

    task = next_step.resolve_task(args.root, args.task)
    if not task or not attempts.TASK.fullmatch(task):
        ap.error("no task found; pass --task (lowercase letters, digits, and hyphens)")
    root = args.root.resolve()
    if verb == "show":
        doc = record(root, task)
        if doc is None:
            print(f"requirements: {owed(root, task)}; run `lapis-design requirements seal --task {task}`", file=sys.stderr)
            return 1
        print(json.dumps(doc, ensure_ascii=False, indent=2) if args.json else _show(doc))
        return 0
    try:
        changes = seal(root, task, args.owner_files)
    except RequirementsError as exc:
        print(f"requirements: {exc}", file=sys.stderr)
        return 1
    from lapis_design import integrity

    integrity.observe_task(root, task, "requirements seal", extra=changes)
    doc = record(root, task)
    print(f"requirements: sealed {len(doc['rows'])} rows for {task} from "
          f"{', '.join(s['path'] for s in doc['sources'])} -> {record_path(root, task).relative_to(root).as_posix()}"
          + (f"; {len(changes)} changes since the last seal" if changes else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
