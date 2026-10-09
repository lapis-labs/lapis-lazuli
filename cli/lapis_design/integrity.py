"""The change log over the plan's protected inputs, kept by the CLI and never by the maker.

Every command that reads the plan calls `observe` first. It snapshots the protected plan pointers (`PROTECTED`),
compares them with the values the last observation stored, and appends one row per difference to
`.lapis/changes/<task>.jsonl`, with the findings that were open on that input at the time. A change is surfaced,
never forbidden: the rows reach the owner block and the critic packet, and no release rule counts them as defects.

  .lapis/state/<task>.json     the protected values as last observed, the findings open at the time, the digest of the
                               requirement record, the hash of the last log line, and the sealed slice
  .lapis/changes/<task>.jsonl  one JSON line per change; `seq` and `prev` (the sha256 of the line before) form a chain
  .lapis/state/<task>.lock     held for the length of one observation (`O_CREAT|O_EXCL`, bounded wait)

The shapes are `integrity/schema.yaml`. The files are found modified, not prevented: the pre-write hook refuses an
edit tool's write to them (`order.py`), and a shell write shows up here as a row of kind `integrity` (the last line
does not match the state, a link of the chain is broken, the state is missing). Rows that were shown stay shown: a
broken link is reported once, by a row that names its line.

Stdlib only until a rule file must be read: the exit gate and the pre-write hook reach this through `next`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

KINDS = ("protected", "requirements", "answers-headings", "integrity")
ANSWERS = "answers:headings"            # the pointer (and the key in `values`) of the answers file's headings
SOURCES = ("plan_check", "slop_lint", "critic")
LOCK_WAIT_S = 3.0                       # how long one observation waits for another before giving up (fail-open)
LOCK_STALE_S = 30.0                     # a lock older than this was left by a process that died

# The plan pointers whose changes are logged. `name[k1,k2]` addresses the items of a list by those fields (a
# concrete pointer reads `name[k1=v1,k2=v2]`; `#` adds the item's position among those with the same key). A pattern
# that ends at such an item holds the whole item; any other pattern ends at a value whose mapping is split into one
# leaf per key, and whose list or scalar is one leaf. `*` collects a field of every item of a list.
PROTECTED = (
    "/brief", "/claims", "/approval", "/sources[ref]",
    "/references[source]/take", "/references[source]/leave",
    "/defaults[id]",
    "/explorations[decision,covers]/chosen", "/explorations[decision,covers]/fixed_by",
    "/explorations[decision,covers]/candidates/*/name",
    "/flows[id]/goal", "/flows[id]/done", "/flows[id]/reach", "/flows[id]/kind",
    "/tokens/space/base_px", "/tokens/space/scale", "/tokens/type/scale",
    "/tokens/shape/radius/scale", "/tokens/shape/radius/by_role", "/tokens/color/roles[name,theme]",
    "/layout/phone_task",
    "/content/key_copy[slot,locale,#]",
    # the direction the owner saw in the slice: a change after it is a `new-direction` ask (`asks.detected`)
    "/direction/concept", "/direction/levers", "/layout/signature", "/layout/sections[id]",
    "/tokens/type/roles[role,#]", "/tokens/motion/principles",
)

_MISSING = object()
_SEGMENT = re.compile(r"([a-z_]+)(?:\[([a-z_,#]+)\])?")
_DEFAULTS_POINTER = re.compile(r"/defaults\[id=([^\],]+)(?:,n=\d+)?\]")
_FLOW_POINTER = re.compile(r"/flows\[id=([^\],]+)(?:,n=\d+)?\]")
_SELECTOR = re.compile(r"\[[^\]]*\]")
_HEADING = re.compile(r"^(#{1,2})(?!#)\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_TASK = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")


# ---------------------------------------------------------------- paths

def state_path(root: Path, task: str) -> Path:
    return Path(root) / ".lapis" / "state" / f"{task}.json"


def log_path(root: Path, task: str) -> Path:
    return Path(root) / ".lapis" / "changes" / f"{task}.jsonl"


def lock_path(root: Path, task: str) -> Path:
    return Path(root) / ".lapis" / "state" / f"{task}.lock"


def locate(plan: Path, root: Path | None = None) -> tuple[Path, str] | None:
    """The project folder and task of a plan file at `<root>/.lapis/plans/<task>.yaml`, else None. A relative path is
    taken from `root` when given, else from the working directory."""
    path = Path(os.path.abspath(Path(root) / plan if root is not None and not Path(plan).is_absolute() else plan))
    if path.suffix == ".yaml" and path.parent.name == "plans" and path.parent.parent.name == ".lapis" \
            and _TASK.fullmatch(path.stem):
        return path.parent.parent.parent, path.stem
    return None


# ---------------------------------------------------------------- canonical values

def _plain(value: Any) -> Any:
    """`value` as JSON holds it: a plan read from YAML can carry dates and other scalars JSON has no name for."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(v) for v in value), key=_canon)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _canon(value: Any) -> str:
    return json.dumps(_plain(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: Any) -> str:
    """The sha256 of the canonical JSON of `value` (sorted keys, no spaces)."""
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _key_text(value: Any) -> str:
    text = "|".join(str(v) for v in value) if isinstance(value, list) else str(value)
    return text.replace("]", "%5D")


def _compile(pattern: str) -> tuple[list[tuple], bool]:
    """A `PROTECTED` pattern as segments, and whether it ends at a list item (so the item is the value)."""
    segments: list[tuple] = []
    for part in pattern.strip("/").split("/"):
        if part == "*":
            segments.append(("each",))
            continue
        match = _SEGMENT.fullmatch(part)
        if match is None:
            raise ValueError(f"bad protected pointer {pattern!r}")
        name, fields = match.groups()
        if fields is None:
            segments.append(("name", name))
        else:
            ordinal = "#" in fields.split(",")
            segments.append(("keyed", name, [f for f in fields.split(",") if f != "#"], ordinal))
    return segments, segments[-1][0] == "keyed"


def _item_keys(items: list, fields: Sequence[str], ordinal: bool) -> list[str]:
    raw = []
    for item in items:
        parts = [f"{f}={_key_text(item[f])}" for f in fields if isinstance(item, Mapping) and item.get(f) is not None]
        raw.append(",".join(parts))
    totals = {key: raw.count(key) for key in raw}
    seen: dict[str, int] = {}
    keys = []
    for key in raw:
        seen[key] = seen.get(key, 0) + 1
        if ordinal or totals[key] > 1:
            key = f"{key},n={seen[key]}" if key else f"n={seen[key]}"
        keys.append(key)
    return keys


def _leaves(node: Any, prefix: str) -> Iterator[tuple[str, Any]]:
    if isinstance(node, Mapping) and node:
        for key in sorted(node, key=str):
            yield from _leaves(node[key], f"{prefix}/{key}")
    else:
        yield prefix, node


def _walk(node: Any, segments: Sequence[tuple], prefix: str, whole: bool) -> Iterator[tuple[str, Any]]:
    if not segments:
        yield from ([(prefix, node)] if whole else _leaves(node, prefix))
        return
    head, rest = segments[0], segments[1:]
    if head[0] == "name":
        if isinstance(node, Mapping) and head[1] in node:
            yield from _walk(node[head[1]], rest, f"{prefix}/{head[1]}", whole)
    elif head[0] == "keyed":
        items = node.get(head[1]) if isinstance(node, Mapping) else None
        if isinstance(items, list):
            for item, key in zip(items, _item_keys(items, head[2], head[3])):
                yield from _walk(item, rest, f"{prefix}/{head[1]}[{key}]", whole)
    elif isinstance(node, list):                        # `*`: the named field of every item
        names = [seg[1] for seg in rest]
        found = []
        for item in node:
            for name in names:
                item = item.get(name, _MISSING) if isinstance(item, Mapping) else _MISSING
            if item is not _MISSING:
                found.append(item)
        yield f"{prefix}/*/{'/'.join(names)}", found


_COMPILED = [_compile(p) for p in PROTECTED]


def protected_values(plan: Mapping[str, Any]) -> dict[str, Any]:
    """The plan's protected pointers as `{concrete pointer: JSON value}`, in pointer order."""
    found: dict[str, Any] = {}
    for segments, whole in _COMPILED:
        for pointer, value in _walk(plan, segments, "", whole):
            found[pointer] = _plain(value)
    return dict(sorted(found.items()))


def answers_headings(root: Path, task: str) -> list[dict] | None:
    """The `##` headings of `.lapis/answers/<task>.md` with the count of list items under each, or None without the
    file. A heading renamed or an item added shows as a change (the round cap counts by these headings)."""
    from lapis_design import brief

    try:
        text = (Path(root) / ".lapis" / "answers" / f"{task}.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found: list[dict] = []
    body: list[str] = []
    fenced = collecting = False

    def close() -> None:
        if collecting:
            found[-1]["items"] = len(brief.items("\n".join(body)))

    for line in text.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
        match = None if fenced else _HEADING.match(line)
        if match:                                   # a heading of the same or a higher level ends the section
            close()
            collecting = len(match.group(1)) == 2
            if collecting:
                found.append({"heading": match.group(2), "items": 0})
                body = []
        elif collecting:
            body.append(line)
    close()
    return found


# ---------------------------------------------------------------- related rules

def related_rules(rules: Mapping[str, Any], detectors: Mapping[str, Any]) -> dict[str, list[tuple[str, ...]]]:
    """The plan inputs of each rule, as path segments: its `detect.<layer>.path` and the `reads_plan` of the detector
    it names, both in the plan path grammar of slop/detectors.yaml. Selectors are dropped: a rule that reads
    `tokens.color.roles[?role=field]` is related to every color role."""
    reads = {d.get("name"): d.get("reads_plan") or [] for d in detectors.get("detectors") or [] if isinstance(d, Mapping)}
    found: dict[str, list[tuple[str, ...]]] = {}
    for rule in rules.get("rules") or []:
        if not isinstance(rule, Mapping) or not isinstance(rule.get("id"), str):
            continue
        paths: list[str] = []
        for detect in (rule.get("detect") or {}).values():
            if isinstance(detect, Mapping):
                if isinstance(detect.get("path"), str):
                    paths.append(detect["path"])
                paths += [p for p in reads.get(detect.get("detector"), []) if isinstance(p, str)]
        segments = [seg for seg in dict.fromkeys(_segments(p) for p in paths) if seg]
        if segments:
            found[rule["id"]] = segments
    return found


def _segments(pointer: str) -> tuple[str, ...]:
    return tuple(part for part in re.split(r"[./]", _SELECTOR.sub("", pointer)) if part)


def _overlaps(path: Sequence[str], pointer: Sequence[str]) -> bool:
    """One covers the other: they agree on the segments they share (a `*` in the pointer agrees with any)."""
    return all(a == b or b == "*" for a, b in zip(path, pointer))


@lru_cache(maxsize=2)
def _registry(shared: str) -> dict[str, list[tuple[str, ...]]]:
    import yaml

    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    read = lambda name: yaml.load((Path(shared) / "slop" / name).read_text(encoding="utf-8"), Loader=loader)  # noqa: E731
    return related_rules(read("rules.yaml"), read("detectors.yaml"))


def _related(pointer: str, entries: Sequence[Mapping[str, Any]], plan_inputs) -> list[str]:
    """Ids of the rules among the open `entries` that read what `pointer` names."""
    segments = _segments(pointer)
    default = _DEFAULTS_POINTER.match(pointer)
    flow = _FLOW_POINTER.match(pointer)
    found: set[str] = set()
    for entry in entries:
        rule = entry["rule_id"]
        if default and default.group(1) == rule:
            found.add(rule)
        elif flow and entry.get("flow") == flow.group(1):
            found.add(rule)
        elif entry.get("path") and _overlaps(_segments(entry["path"]), segments):
            found.add(rule)
        elif any(_overlaps(path, segments) for path in plan_inputs().get(rule, ())):
            found.add(rule)
    return sorted(found)


# ---------------------------------------------------------------- the lock

@contextmanager
def lock(root: Path, task: str, wait: float | None = None) -> Iterator[None]:
    """Hold `.lapis/state/<task>.lock` for the block. It is made with `O_CREAT|O_EXCL`, which works on every
    platform, and waited for `wait` seconds (`LOCK_WAIT_S`); a lock older than `LOCK_STALE_S` is taken over. A
    TimeoutError is raised when it cannot be had, and the caller fails open."""
    path = lock_path(root, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + (LOCK_WAIT_S if wait is None else wait)
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
            break
        except FileExistsError:
            try:
                stamp = path.stat().st_mtime
            except OSError:
                continue
            if time.time() - stamp > LOCK_STALE_S:
                try:
                    if path.stat().st_mtime == stamp:       # not a lock someone else just made in its place
                        path.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{path} is held by another lapis-design command")
            time.sleep(0.01)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------- reading the files

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _valid_state(state: Any, task: str) -> bool:
    return (isinstance(state, dict) and state.get("version") == 0 and state.get("task") == task
            and isinstance(state.get("values"), dict) and isinstance(state.get("open"), list)
            and all(isinstance(e, dict) and isinstance(e.get("rule_id"), str) for e in state["open"])
            and (state.get("last_change") is None or isinstance(state["last_change"], str)))


def read_state(root: Path, task: str) -> dict | None:
    """The state of `task`, or None when the file is missing or is not a state."""
    state = _json(state_path(root, task))
    return state if _valid_state(state, task) else None


def _read_log(path: Path) -> tuple[list[bytes], list[dict | None]]:
    """The log's lines as bytes and as rows (None for a line that is not a row)."""
    try:
        data = path.read_bytes()
    except OSError:
        return [], []
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    rows: list[dict | None] = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            row = None
        rows.append(row if isinstance(row, dict) else None)
    return lines, rows


def changes(root: Path, task: str) -> list[dict]:
    """The rows of the change log in file order; none when there is no log. A line that is not a row is left out
    (`observe` reports it)."""
    return [row for row in _read_log(log_path(root, task))[1] if row is not None]


def _broken_links(lines: Sequence[bytes], rows: Sequence[dict | None]) -> list[tuple[int, str]]:
    """The 1-based lines whose link to the line before is broken, not yet reported by an `integrity` row."""
    shown = {r["before"].get("line") for r in rows
             if r and r.get("kind") == "integrity" and isinstance(r.get("before"), dict)}
    found = []
    for index, row in enumerate(rows):
        number = index + 1
        if number in shown:
            continue
        if row is None:
            found.append((number, f"line {number} of the change log is not a change row"))
        else:
            expected = _sha(lines[index - 1]) if index else None
            if row.get("prev") != expected:
                found.append((number, f"line {number} of the change log does not follow the line before it"))
    return found


# ---------------------------------------------------------------- the open findings

def _entries(findings: Iterable[Any], source: str) -> list[dict]:
    """The open findings as state entries: the rule, its layer, where it came from, and the plan path and flow it
    names. Equal entries are kept once."""
    found: dict[tuple, dict] = {}
    for finding in findings:
        if not isinstance(finding, Mapping) or finding.get("status") != "open" or not isinstance(finding.get("rule_id"), str):
            continue
        layer = finding.get("layer") if isinstance(finding.get("layer"), str) else ""
        entry: dict[str, Any] = {"rule_id": finding["rule_id"], "layer": layer, "from": source}
        location = finding.get("location") if isinstance(finding.get("location"), Mapping) else {}
        if layer == "plan" and isinstance(location.get("path"), str):
            entry["path"] = location["path"]
        if isinstance(location.get("flow"), str):
            entry["flow"] = location["flow"]
        found[tuple(sorted(entry.items()))] = entry
    return list(found.values())


def _sorted_open(entries: Iterable[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: (e["from"], e["rule_id"], e.get("layer", ""), e.get("flow", ""),
                                          e.get("path", "")))


def _reports(root: Path, task: str) -> dict[str, list[dict]]:
    """The open findings of the lint report(s) and the critic report on disk, by source. A source with no readable
    report is left out, so its entries from the last observation stay."""
    folder = Path(root) / ".lapis"
    files = {"slop_lint": (folder / "lint" / f"{task}.json", folder / "lint" / f"{task}.narrow.json"),
             "critic": (folder / "critic" / f"{task}.json",)}
    found: dict[str, list[dict]] = {}
    for source, paths in files.items():
        for path in paths:
            report = _json(path)
            if isinstance(report, dict) and isinstance(report.get("findings"), list):
                found.setdefault(source, []).extend(_entries(report["findings"], source))
    return found


def _with_reports(entries: Sequence[dict], reports: Mapping[str, list[dict]]) -> list[dict]:
    kept = [e for e in entries if e.get("from") not in reports]
    return _sorted_open(kept + [e for found in reports.values() for e in found])


# ---------------------------------------------------------------- writing

def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        mask = os.umask(0)
        os.umask(mask)
        os.chmod(temp, 0o666 & ~mask)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _append(path: Path, lines: Sequence[bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joint = b""
    try:
        with open(path, "rb") as head:
            head.seek(0, os.SEEK_END)
            if head.tell():
                head.seek(-1, os.SEEK_END)
                joint = b"" if head.read(1) == b"\n" else b"\n"      # a hand-edited log may end without one
    except FileNotFoundError:
        pass
    with open(path, "ab") as stream:
        stream.write(joint + b"".join(line + b"\n" for line in lines))
        stream.flush()
        os.fsync(stream.fileno())


def _row(seq: int, at: str, by: str, prev: str | None, kind: str, pointer: str, before: Any, after: Any,
         related: list[str], reactive: bool, after_slice: bool) -> bytes:
    row = {"seq": seq, "at": at, "by": by, "kind": kind, "pointer": pointer, "before": _plain(before),
           "after": _plain(after), "related_open": related, "reactive": reactive, "after_slice": after_slice,
           "prev": prev}
    return json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _unsafe(plan: Mapping[str, Any]) -> bool:
    """Whether the plan check would refuse to read `plan` (aliases that expand past its limits, a key that is not a
    string, a value JSON cannot hold). Such a plan is not walked here either: its protected values are not observed
    until it reads again, and the plan check reports the fault."""
    from lapis_design import plan_check

    return bool(plan_check.expansion_problem(plan) or next(plan_check.non_string_key_paths(plan), None) is not None)


def _approved(plan: Any) -> bool:
    return isinstance(plan, Mapping) and isinstance(plan.get("approval"), Mapping) \
        and plan["approval"].get("state") == "approved"


# ---------------------------------------------------------------- observe

def _observe(root: Path, task: str, plan: Any, by: str, extra: Sequence[Mapping[str, Any]]) -> list[dict]:
    root = Path(root)
    if not _TASK.fullmatch(task):
        raise ValueError(f"{task!r} is not a task id")
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a project folder")
    if isinstance(plan, Mapping) and _unsafe(plan):
        plan = None
    with lock(root, task):
        path, log = state_path(root, task), log_path(root, task)
        raw = _json(path)
        state = raw if _valid_state(raw, task) else None
        lines, parsed = _read_log(log)
        last = _sha(lines[-1]) if lines else None
        answers = answers_headings(root, task)
        notes: list[tuple[str, Any, str]] = []           # (pointer, before, after) of the integrity rows

        if state is None and (lines or path.exists()):
            notes.append(("state", None, "the state file is missing or cannot be read while a change log exists: "
                          "the change log or the state was edited outside lapis-design" if lines else
                          "the state file cannot be read: it was edited outside lapis-design"))
        elif state is None:
            if _approved(plan) or answers is not None:
                notes.append(("history", None, "history starts here; earlier changes were not observed"))
        elif state.get("last_change") != last:
            notes.append(("changes", None, "the change log does not match its state (the last line is not the one "
                          "recorded): the change log or the state was edited outside lapis-design"))
        for number, why in _broken_links(lines, parsed):
            notes.append(("changes", {"line": number}, why + ": the change log was edited outside lapis-design"))

        values = dict(state["values"]) if state else {}
        before_open = list(state["open"]) if state else []
        open_now = _with_reports(before_open, _reports(root, task))

        pending: list[tuple[str, str, Any, Any]] = []    # (kind, pointer, before, after)
        for item in (*_requirements(root, task), *extra):
            pending.append(("requirements", str(item["pointer"]), item.get("before"), item.get("after")))
        if isinstance(plan, Mapping):
            now = protected_values(plan)
            if any(key.startswith("/") for key in values):
                for pointer in sorted({*values, *now} - {ANSWERS}):
                    if pointer.startswith("/") and values.get(pointer) != now.get(pointer):
                        pending.append(("protected", pointer, values.get(pointer), now.get(pointer)))
            values = {key: value for key, value in values.items() if not key.startswith("/")} | now
        if answers is not None or ANSWERS in values:
            if ANSWERS in values and values[ANSWERS] != answers:
                pending.append(("answers-headings", ANSWERS, values[ANSWERS], answers))
            values[ANSWERS] = answers

        after_slice = bool(state and state.get("slice"))
        open_ids = {e["rule_id"] for e in open_now}
        shared: list = []

        def plan_inputs() -> dict:
            if not shared:
                from lapis_design import shared_dir

                shared.append(_registry(str(shared_dir())))
            return shared[0]

        at, prev = _now(), last
        seq = next((r["seq"] for r in reversed(parsed) if r and isinstance(r.get("seq"), int)), 0)
        encoded: list[bytes] = []
        rows: list[dict] = []
        pending[:0] = [("integrity", pointer, before, after) for pointer, before, after in notes]
        for kind, pointer, before, after in pending:
            related = _related(pointer, open_now, plan_inputs) if kind == "protected" and open_now else []
            default = _DEFAULTS_POINTER.match(pointer)
            reactive = bool(kind == "protected" and default and after is not None and default.group(1) in open_ids)
            seq += 1
            line = _row(seq, at, by, prev, kind, pointer, before, after, related, reactive, after_slice)
            encoded.append(line)
            rows.append(json.loads(line))
            prev = _sha(line)
        record = _record_sha(root, task)
        updated = {**(state or {}), "version": 0, "task": task, "values": values, "open": open_now,
                   "requirements_sha256": record, "last_change": prev}
        if encoded:
            _append(log, encoded)
        if updated != state:
            _write_state(path, updated)
        return rows


def _requirements(root: Path, task: str) -> list[Mapping[str, Any]]:
    """What re-reading the requirement record's sources changed; nothing without a record."""
    if not (Path(root) / ".lapis" / "requirements" / f"{task}.json").is_file():
        return []
    from lapis_design import requirements

    return requirements.refresh(root, task)


def _record_sha(root: Path, task: str) -> str | None:
    if not (Path(root) / ".lapis" / "requirements" / f"{task}.json").is_file():
        return None
    from lapis_design import requirements

    return requirements.sha256(root, task)


def observe(root: Path, task: str, plan: Any, by: str, *, extra: Sequence[Mapping[str, Any]] = ()) -> dict:
    """The first call of every command that reads the plan. Compares the protected pointers of `plan` (a parsed plan,
    or None when the plan is missing or unreadable: then only the other records are observed) and the answers file's
    headings with the last observation, refreshes the requirement record (`requirements.refresh`), and appends one row
    per difference, under the task's lock. `extra` are further `{pointer, before, after}` items of kind `requirements`
    that the caller made itself (a reseal), logged in the same write. `by` names the command.

    Returns `{"rows": [the rows this call wrote], "error": None}`. It never raises: a failure prints one line to
    stderr and comes back as `error` ("<ExceptionType>: <message>"), so the command goes on and the owner block can
    say "integrity not recorded: <error>"."""
    try:
        return {"rows": _observe(root, task, plan, by, extra), "error": None}
    except Exception as exc:        # a bug or an unwritable folder here never stops a command or a hook
        error = f"{type(exc).__name__}: {(str(exc).splitlines() or [''])[0]}"
        print(f"lapis-design: integrity not recorded: {error}", file=sys.stderr)
        return {"rows": [], "error": error}


def _load_plan(path: Path) -> Any:
    from lapis_design.plan_check import read_plan

    try:
        plan = read_plan(path)
    except Exception:               # a missing file, bad UTF-8, a YAML error: the plan cannot be read
        return None
    return plan if isinstance(plan, dict) else None


def observe_task(root: Path, task: str, by: str, *, extra: Sequence[Mapping[str, Any]] = ()) -> dict:
    """`observe` with the plan read from `.lapis/plans/<task>.yaml` (None when it cannot be read)."""
    return observe(root, task, _load_plan(Path(root) / ".lapis" / "plans" / f"{task}.yaml"), by, extra=extra)


def observe_plan(plan_path: Path, by: str, root: Path | None = None) -> dict | None:
    """`observe_task` for a plan given by path; None when the path is not `<root>/.lapis/plans/<task>.yaml`."""
    found = locate(plan_path, root)
    return observe_task(found[0], found[1], by) if found else None


def record_findings(root: Path, task: str, findings: Iterable[Any], source: str) -> str | None:
    """Replace the open findings that came from `source` (`plan_check` or `slop_lint`) with `findings`, the report of
    the command that just ran. Nothing is written without a state, since `observe` creates it. It never raises and
    says nothing: it returns the error text when the findings could not be recorded, which only leaves a later row's
    `related_open` shorter (`observe` prints the line that matters when the whole record fails)."""
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")
    try:
        with lock(root, task, wait=1.0):
            state = read_state(root, task)
            if state is None:
                return None
            kept = [e for e in state["open"] if e.get("from") != source]
            updated = {**state, "open": _sorted_open(kept + _entries(findings, source))}
            if updated != state:
                _write_state(state_path(root, task), updated)
    except Exception as exc:
        return f"{type(exc).__name__}: {(str(exc).splitlines() or [''])[0]}"
    return None


def seal_slice(root: Path, task: str, row: Mapping[str, Any]) -> None:
    """Record the slice the owner approved: `state.slice` is `row` (`url` and the digests of the draft record, the
    packet, the questions, the answers and the requirement record) plus the time, the digest of the protected values,
    and the values themselves, so that a later change can be told from a revert. The change chain is not touched; rows
    written after this one carry `after_slice`."""
    with lock(root, task):
        state = read_state(root, task) or {"version": 0, "task": task, "values": {}, "open": [],
                                           "requirements_sha256": None, "last_change": None}
        sealed = {**row, "protected_sha256": digest(state["values"]), "values": dict(state["values"]), "at": _now()}
        _write_state(state_path(root, task), {**state, "slice": sealed})


def mark_slice(root: Path, task: str, **fields: Any) -> None:
    """Set `fields` (`slice_since`, `slice_rounds`, `slice_set`, `slice_heights`) in the state of `task`, the clock and the
    rounds of the slice (`slice_step.py`)."""
    with lock(root, task):
        state = read_state(root, task) or {"version": 0, "task": task, "values": {}, "open": [],
                                           "requirements_sha256": None, "last_change": None}
        _write_state(state_path(root, task), {**state, **fields})
