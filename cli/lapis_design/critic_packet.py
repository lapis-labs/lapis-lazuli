"""Critic packet: the fixed inputs a critic report is judged against, built and verified by the CLI.

`lapis-design critic packet --task T` writes `.lapis/critic/T.packet.json`: the owner's requirement rows, the plan's
design fields without the maker's reasons, a digest of every file the critic may read, the lint findings, the change
rows that were reactive or touched an open finding, and the maker's disputes without their reasons. The bytes are
deterministic (sorted keys, no timestamps), so an unchanged input set reproduces the same digest.

A critic report counts only for the packet whose file bytes hash to its `target.packet.sha256`. `check` rebuilds the
packet from the arguments recorded in it, so a changed input (a capture, the lint report, a requirement row, a plan
field the packet carries, a change row) makes the report stale, and it checks that the report judges every row,
change, and dispute of the packet and cites only files and quotes that exist. That proves which inputs were declared,
never what the critic actually read or that it was independent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path, PurePosixPath

import yaml
from jsonschema import Draft202012Validator

from lapis_design import asks, direction, gaps, shared_dir

TASK = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
# What the critic never reads: the maker's plan and records. The packet carries what it may know of them.
HIDDEN = (".lapis/plans", ".lapis/answers", ".lapis/drafts", ".lapis/questions", ".lapis/disputes", ".lapis/direction")
# Keys that hold a maker's justification; a change row never carries them to the critic.
REASONS = {"reason", "evidence", "runner_up_lost"}
# A reference to one of these is a file; any other reference is a box id or a session step.
FILE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".json", ".html", ".css", ".js", ".md", ".txt",
                 ".yaml", ".yml", ".mp4", ".webm"}
FACT_SOURCE = re.compile(r"(?P<path>[^#]+)#L(?P<first>\d+)(?:-L?(?P<last>\d+))?")
STALE = "critic report was made from another packet"


class PacketError(ValueError):
    """The packet cannot be built from its inputs: a file is missing or unreadable, or a record is malformed."""


def record_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "requirements" / f"{task}.json"


def has_record(root: Path, task: str) -> bool:
    """Whether the task has a requirement record: only then must a critic report judge a packet's rows."""
    return record_path(root, task).is_file()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(text: str) -> str:
    """The comparison form of a quote: case folded, white space collapsed."""
    return " ".join(text.casefold().split())


@lru_cache(maxsize=None)
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(yaml.safe_load((shared_dir() / name).read_text(encoding="utf-8")))


def _first_error(validator: Draft202012Validator, document: object) -> str | None:
    error = next(iter(sorted(validator.iter_errors(document), key=lambda e: list(map(str, e.absolute_path)))), None)
    return None if error is None else f"{'/'.join(map(str, error.absolute_path)) or 'document'}: {error.message}"


def _map(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _seq(value: object) -> list:
    return value if isinstance(value, list) else []


def _wrap(**parts) -> dict:
    """The parts that hold something; a packet leaves an empty section out instead of carrying it."""
    return {key: value for key, value in parts.items() if value not in (None, "", [], {})}


def _scrub(value: object) -> object:
    """`value` without any maker's justification (`reason`, `evidence`, `runner_up_lost`), at any depth."""
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items() if key not in REASONS}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _resolve(root: Path, name: object) -> Path | None:
    """Where `name` (relative to `root`, or absolute) points, when that is inside `root`."""
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        path = (root / name).resolve()
    except (OSError, ValueError):                                    # a name no file system takes
        return None
    return path if path.is_relative_to(root) else None


def _inside(root: Path, name: object) -> Path | None:
    """The existing file `name` names inside `root`, else None."""
    path = _resolve(root, name)
    return path if path is not None and path.is_file() else None


def _file(root: Path, name: str, what: str) -> Path:
    path = _inside(root, name)
    if path is None:
        raise PacketError(f"{what} is not a file inside the project: {name}")
    return path


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _hidden(rel: str) -> bool:
    return any(rel == name or rel.startswith(name + "/") for name in HIDDEN)


def _json(path: Path, what: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PacketError(f"{what} cannot be read: {path}: {exc}") from exc


def _plan(root: Path, task: str) -> dict:
    from lapis_design.plan_check import read_plan

    path = root / ".lapis" / "plans" / f"{task}.yaml"
    try:
        plan = read_plan(path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise PacketError(f"the plan {path} cannot be read: {exc}") from exc
    if not isinstance(plan, dict):
        raise PacketError(f"the plan {path} is not a mapping")
    return plan


def _record(root: Path, task: str) -> dict | None:
    path = record_path(root, task)
    if not path.is_file():
        return None
    record = _json(path, "the requirement record")
    if (not isinstance(record, dict) or not isinstance(record.get("rows"), list)
            or not all(isinstance(r, dict) and isinstance(r.get("id"), str) and isinstance(r.get("text"), str)
                       for r in record["rows"])):
        raise PacketError(f"the requirement record {path} has no rows with an id and a text")
    return record


def _requirements(record: dict | None) -> dict:
    if record is None:
        return {"sha256": None, "rows": [], "owner_decisions": []}
    rows = [_wrap(id=r["id"], section=r.get("section"), text=r["text"]) for r in record["rows"]]
    decisions = [{"row": str(d.get("row")), "decision": str(d.get("decision")), "quote": str(d.get("quote", ""))}
                 for d in _seq(record.get("owner_decisions")) if isinstance(d, dict)]
    body = json.dumps({"owner_decisions": decisions, "rows": rows}, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return {"sha256": digest(body), "rows": rows, "owner_decisions": decisions}


@lru_cache(maxsize=4)
def _cases_of(path: str, mtime_ns: int) -> dict[str, dict[str, str]]:
    from lapis_design.plan_check import load_yaml

    rules = _map(load_yaml(Path(path))).get("rules")
    return {rule["id"]: {case["id"]: case["when"] for case in _seq(rule.get("keep_when"))
                         if isinstance(case, dict) and "id" in case and "when" in case}
            for rule in _seq(rules) if isinstance(rule, dict) and "id" in rule}


def _cases() -> dict[str, dict[str, str]]:
    """Each rule's `keep_when` cases as id -> `when`, from the packaged rules."""
    path = shared_dir() / "slop" / "rules.yaml"
    return _cases_of(str(path), path.stat().st_mtime_ns)


def _design(plan: dict) -> dict:
    """The plan's design fields, in the packet's own shape, without any reason, evidence, or concept of the maker."""
    layout, tokens, content = _map(plan.get("layout")), _map(plan.get("tokens")), _map(plan.get("content"))
    keeps = any(isinstance(d, dict) and d.get("keep_when") for d in _seq(plan.get("defaults")))
    cases = _cases() if keeps else {}

    def exploration(entry: dict) -> dict:
        return _wrap(decision=entry.get("decision"), covers=entry.get("covers"),
                     candidates=[_wrap(name=c.get("name"), source=c.get("source"), artifact=c.get("artifact"))
                                 for c in _seq(entry.get("candidates")) if isinstance(c, dict)],
                     compared_on=entry.get("compared_on"), comparisons=entry.get("comparisons"),
                     chosen=entry.get("chosen"), fixed_by=entry.get("fixed_by"))

    def default(entry: dict) -> dict:
        case = entry.get("keep_when")
        return _wrap(id=entry.get("id"), decision=entry.get("decision"), keep_when=case,
                     case_when=_map(cases.get(entry.get("id"))).get(case) if case else None)

    return _wrap(
        brief=plan.get("brief"), world_materials=plan.get("world_materials"),
        layout=_wrap(phone_task=layout.get("phone_task"), sections=layout.get("sections"),
                     signature=layout.get("signature"),
                     procedure=_wrap(priority=_map(layout.get("procedure")).get("priority"))),
        tokens=_wrap(type=_wrap(roles=_map(tokens.get("type")).get("roles"), scale=_map(tokens.get("type")).get("scale")),
                     color=_wrap(roles=_map(tokens.get("color")).get("roles")),
                     space=_wrap(base_px=_map(tokens.get("space")).get("base_px"),
                                 scale=_map(tokens.get("space")).get("scale")),
                     shape=_wrap(radius=_map(tokens.get("shape")).get("radius"),
                                 media_contours=_scrub(_map(tokens.get("shape")).get("media_contours")))),
        content=_wrap(voice=content.get("voice"), key_copy=content.get("key_copy")),
        flows=[_wrap(id=f.get("id"), kind=f.get("kind"), goal=f.get("goal"), start=f.get("start"), done=f.get("done"))
               for f in _seq(plan.get("flows")) if isinstance(f, dict)],
        references=[_wrap(source=r.get("source"), kind=r.get("kind"), take=r.get("take"), leave=r.get("leave"),
                          profile=r.get("profile")) for r in _seq(plan.get("references")) if isinstance(r, dict)],
        explorations=[exploration(e) for e in _seq(plan.get("explorations")) if isinstance(e, dict)],
        defaults=[default(d) for d in _seq(plan.get("defaults")) if isinstance(d, dict)])


def _screenshots(root: Path, extract: Path) -> list[Path]:
    shots = []
    for view in _seq(_map(_json(extract, "the render extract")).get("viewports")):
        name = _map(view).get("screenshot")
        if not name:
            continue
        shot = (extract.parent / name).resolve()
        if not shot.is_relative_to(root) or not shot.is_file():
            raise PacketError(f"{_rel(root, extract)} names the screenshot {name}, which is not a file inside the project")
        shots.append(shot)
    return shots


def _listed(root: Path, task: str, plan: dict, record: dict | None, extracts: list[Path], lint: Path,
            session: Path | None) -> list[dict]:
    """Every file the critic may read, once, with its digest. The first kind that names a file stands."""
    seen: dict[str, dict] = {}

    def add(kind: str, path: Path | None) -> None:
        if path is None:
            return
        rel = _rel(root, path)
        if rel not in seen and not _hidden(rel):
            seen[rel] = {"kind": kind, "path": rel, "sha256": digest(path.read_bytes())}

    def outside(kind: str, name: object) -> None:
        if isinstance(name, str) and (path := _inside(root, name)) and not _rel(root, path).startswith(".lapis/"):
            add(kind, path)

    for path in extracts:
        add("extract", path)
    for path in extracts:
        for shot in _screenshots(root, path):
            add("screenshot", shot)
    add("lint", lint)
    add("session", session)
    for source in _seq((record or {}).get("sources")):
        if _map(source).get("kind") == "owner-file":
            outside("requirement-source", source.get("path"))
    context = _map(plan.get("context"))
    outside("product", context.get("product"))
    outside("design", _map(context.get("design")).get("path"))
    for name in _seq(context.get("other")):
        outside("context", name)
    add("taste", _inside(root, ".lapis/taste.md"))
    add("references-record", _inside(root, f".lapis/references/{task}.md"))
    for path in sorted((root / ".lapis" / "references" / task).rglob("*")):
        add("reference-capture", _inside(root, str(path)))
    for reference in _seq(plan.get("references")):
        add("reference-profile", _inside(root, _map(reference).get("profile")))
    shown = direction.packet(root, task)
    outside_state = [("direction-contact", shown["contact"]),
                     *(("direction-capture", name) for name in _seq(_map(shown["pick"]).get("captures")))]
    for kind, name in outside_state:
        if isinstance(name, str):
            add(kind, _inside(root, name))
    for exploration in _seq(plan.get("explorations")):
        exploration = _map(exploration)
        names = [c.get(key) for c in _seq(exploration.get("candidates")) for key in ("artifact", "token_file")
                 if isinstance(c, dict)]
        for comparison in _seq(exploration.get("comparisons")):
            names += [*_map(_map(comparison).get("captures")).values(), *_map(_map(comparison).get("playback")).values()]
        for name in names:
            if isinstance(name, str):
                add("exploration", _inside(root, name.partition("#")[0]))
    return sorted(seen.values(), key=lambda item: item["path"])


def _findings(root: Path, lint: Path) -> list[dict]:
    items = _map(_json(lint, "the lint report")).get("findings")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise PacketError(f"{_rel(root, lint)} has no findings list")
    return [_wrap(index=index, rule_id=item.get("rule_id"), layer=item.get("layer"), observed=item.get("observed"),
                  location=item.get("location"), status=item.get("status")) for index, item in enumerate(items)]


def _changes(root: Path, task: str) -> list[dict]:
    """The change-log rows (`.lapis/changes/<task>.jsonl`) a critic judges: reactive, or on an open finding, or after
    the slice. A line that is not a row is left to the integrity check that notices a log edited outside the CLI."""
    path = root / ".lapis" / "changes" / f"{task}.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or not isinstance(row.get("seq"), int):
            continue
        if row.get("reactive") or row.get("related_open") or row.get("after_slice"):
            pointer = str(row.get("pointer", ""))
            prose = pointer.rsplit("/", 1)[-1] in REASONS         # a protected leaf that is itself a maker's reason
            rows.append({"seq": row["seq"], "kind": str(row.get("kind", "")), "pointer": pointer,
                         "before": None if prose else _scrub(row.get("before")),
                         "after": None if prose else _scrub(row.get("after")),
                         "related_open": [str(rule) for rule in _seq(row.get("related_open"))],
                         "reactive": bool(row.get("reactive")), "after_slice": bool(row.get("after_slice"))})
    return rows


def _disputes(root: Path, task: str) -> list[dict]:
    path = root / ".lapis" / "disputes" / f"{task}.yaml"
    if not path.is_file():
        return []
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise PacketError(f"{_rel(root, path)} cannot be read: {exc}") from exc
    if problem := _first_error(_validator("review/disputes.schema.yaml"), document):
        raise PacketError(f"{_rel(root, path)}: {problem}")
    if document["task"] != task:
        raise PacketError(f"{_rel(root, path)} names task {document['task']!r}, not {task!r}")
    return [_wrap(index=index, report=item["report"], rule_id=item["rule_id"], location=item.get("location"),
                  observed=item["observed"]) for index, item in enumerate(document["disputes"])]


def _named(root: Path, name: object, what: str) -> str:
    """The project-relative path of an input that may not exist yet."""
    path = _resolve(root, name)
    if path is None:
        raise PacketError(f"{what} is not a path inside the project: {name}")
    return _rel(root, path)


def build(root: Path, task: str, inputs: dict) -> bytes:
    """The packet's bytes for `task`. `inputs` is `{"extracts": [path, ...], "lint": path, "session": path | None}`,
    paths relative to `root`. An extract or session that is not there (a render or a behavior run that could not run
    here) is named in `args` and lists no file, so the critic gets no captures from it and a later capture makes the
    packet change. PacketError when the lint report is missing or a record is malformed."""
    root = root.resolve()
    if not _seq(inputs.get("extracts")):
        raise PacketError("a packet needs at least one render extract")
    extract_names = [_named(root, name, "the render extract") for name in inputs["extracts"]]
    extracts = [path for name in extract_names if (path := _inside(root, name))]
    lint = _file(root, inputs.get("lint"), "the lint report")
    session_name = _named(root, inputs["session"], "the behavior session") if inputs.get("session") else None
    session = _inside(root, session_name) if session_name else None
    plan, record = _plan(root, task), _record(root, task)
    document = {
        "version": 0, "task": task,
        "args": _wrap(extracts=extract_names, lint=_rel(root, lint), session=session_name),
        "requirements": _requirements(record), "plan": _design(plan),
        "direction": direction.packet(root, task),
        "gaps": [_wrap(id=g["id"], area=g["area"], text=g["text"]) for g in gaps.compute(root, task)],
        "asks": [_wrap(trigger=a["trigger"], by=a["by"], said=a["said"]) for a in asks.recorded(root, task)],
        "inputs": _listed(root, task, plan, record, extracts, lint, session),
        "findings": _findings(root, lint), "changes": _changes(root, task), "disputes": _disputes(root, task)}
    if problem := _first_error(_validator("review/critic-packet.schema.yaml"), document):
        raise PacketError(f"the packet does not match review/critic-packet.schema.yaml: {problem}")
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


@dataclass
class Verdict:
    """What `check` found. `stale`: the report was not made from the current packet. `gaps`: it does not judge what
    the packet lists, or cites a file or a quote that is not there. `packet` is the packet file, when it was readable."""
    stale: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    packet: dict | None = None

    @property
    def problems(self) -> list[str]:
        return [*self.stale, *self.gaps]


def _names(items: list, shown: int = 4) -> str:
    return ", ".join(map(str, items[:shown])) + (f" and {len(items) - shown} more" if len(items) > shown else "")


def _moved(old: dict, new: dict) -> str:
    """What differs between the packet the critic judged and the packet the project now gives."""
    parts = []
    for key in sorted(set(old) | set(new)):
        if old.get(key) == new.get(key):
            continue
        if key == "inputs":
            before, after = ({i["path"]: i["sha256"] for i in packet.get("inputs", [])} for packet in (old, new))
            parts.append("inputs " + _names(sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))))
        elif key == "plan":
            parts.append("plan " + _names(sorted(k for k in set(old["plan"]) | set(new["plan"])
                                                if old["plan"].get(k) != new["plan"].get(k))))
        else:
            parts.append(key)
    return "; ".join(parts)


def _ref_problem(root: Path, ref: str) -> str | None:
    name = ref.partition("#")[0].strip()
    if PurePosixPath(name).suffix.lower() not in FILE_SUFFIXES:
        return None                                       # a box id or a session step
    path = _resolve(root, name)
    if path is None or not path.is_file():
        return f"the ref {ref} is not a file in the project"
    if _hidden(_rel(root, path)):
        return f"the ref {ref} is a file the critic does not read"
    return None


def _fact_problem(root: Path, index: int, fact: dict, listed: set[str]) -> str | None:
    source = fact.get("source")
    if source in (None, "none"):
        return None
    found = FACT_SOURCE.fullmatch(str(source))
    if not found:
        return f"fact {index}: the source {source!r} is neither `none` nor `path#Lx-Ly`"
    name = PurePosixPath(found["path"]).as_posix()
    if name not in listed:
        return f"fact {index}: {name} is not a file the packet lists"
    try:
        lines = (root / name).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return f"fact {index}: {name} cannot be read as text"
    first, last = int(found["first"]), int(found["last"] or found["first"])
    if not 1 <= first <= last <= len(lines):
        return f"fact {index}: lines {first}-{last} are outside {name} ({len(lines)} lines)"
    quote = normalize(str(fact.get("quote") or ""))
    if not quote or quote not in normalize(" ".join(lines[first - 1:last])):
        return f"fact {index}: the quote is not in {name} lines {first}-{last}"
    return None


def _gaps(root: Path, packet: dict, report: dict) -> list[str]:
    gaps: list[str] = []

    def entries(name: str) -> list[dict]:
        return [item for item in _seq(report.get(name)) if isinstance(item, dict)]

    def judged(name: str, key: str, wanted: list, label: str) -> None:
        seen = [value for item in entries(name) if isinstance(value := item.get(key), (str, int))]
        if missing := [item for item in wanted if item not in seen]:
            gaps.append(f"`{name}` has no entry for {_names([label + str(m) for m in missing])}")
        if unknown := [item for item in dict.fromkeys(seen) if item not in wanted]:
            gaps.append(f"`{name}` names {_names([label + str(u) for u in unknown])}, which the packet does not list")
        if repeated := [item for item in dict.fromkeys(seen) if item in wanted and seen.count(item) > 1]:
            gaps.append(f"`{name}` judges {_names([label + str(r) for r in repeated])} more than once")

    rows = [row["id"] for row in packet["requirements"]["rows"]]
    judged("requirements", "id", rows, "")
    judged("changes", "seq", [change["seq"] for change in packet["changes"]], "change ")
    judged("disputes", "index", [dispute["index"] for dispute in packet["disputes"]], "dispute ")
    for change in entries("changes"):
        if unknown := [row for row in _seq(change.get("rows")) if row not in rows]:
            gaps.append(f"change {change.get('seq')} names {_names(unknown)}, which are not requirement rows of the packet")
    refs = [ref for name in ("requirements", "facts", "disputes", "walkthroughs") for item in entries(name)
            for ref in _seq(item.get("refs")) if isinstance(ref, str)]
    gaps += [problem for ref in dict.fromkeys(refs) if (problem := _ref_problem(root, ref))]
    listed = {item["path"] for item in packet["inputs"]}
    gaps += [problem for index, fact in enumerate(_seq(report.get("facts")))
             if isinstance(fact, dict) and (problem := _fact_problem(root, index, fact, listed))]
    return gaps


def check(root: Path, report_path: Path | str) -> Verdict:
    """Compare the critic report at `report_path` (a path this process can open) with the packet it names and the
    project as it is now. Never raises for a bad report or packet: each fault is a line of the verdict."""
    root = root.resolve()
    verdict = Verdict()
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        named = _map(_map(report).get("target")).get("packet")
    except (OSError, ValueError) as exc:
        verdict.stale.append(f"{STALE}: the report cannot be read ({exc})")
        return verdict
    if not (isinstance(named, dict) and isinstance(named.get("path"), str) and isinstance(named.get("sha256"), str)):
        verdict.stale.append(f"{STALE}: it names none; run `lapis-design critic packet --task <task>`, give the critic "
                             "that packet, and have it record `target.packet` {path, sha256}")
        return verdict
    packet_file = _inside(root, named["path"])
    if packet_file is None:
        verdict.stale.append(f"{STALE}: the packet {named['path']} is not a file in the project")
        return verdict
    data = packet_file.read_bytes()
    if digest(data) != named["sha256"]:
        verdict.stale.append(f"{STALE}: {named['path']} was rebuilt after the critic named it "
                             f"(the report names {named['sha256'][:12]}, the file is {digest(data)[:12]})")
        return verdict
    try:
        packet = json.loads(data)
        if problem := _first_error(_validator("review/critic-packet.schema.yaml"), packet):
            raise PacketError(f"the packet is not valid: {problem}")
        rebuilt = build(root, packet["task"], packet["args"])
    except (ValueError, OSError) as exc:
        verdict.stale.append(f"{STALE}: it cannot be rebuilt now ({exc})")
        return verdict
    verdict.packet = packet
    if rebuilt != data:
        verdict.stale.append(f"{STALE}: {_moved(packet, json.loads(rebuilt))} changed since; rebuild it with "
                             f"`lapis-design critic packet --task {packet['task']}` and run the critic on the new one")
        return verdict
    verdict.gaps = _gaps(root, packet, _map(report))
    return verdict


def verify(root: Path, report_path: Path | str) -> list[str]:
    """The faults of a critic report against its packet and the project, empty when it holds."""
    return check(root, report_path).problems


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _observe(root: Path, task: str, plan: dict) -> None:
    from lapis_design import integrity

    outcome = integrity.observe(root, task, plan, "critic packet")
    if error := _map(outcome).get("error"):
        print(f"critic packet: integrity not recorded: {error}", file=sys.stderr)


def main(argv: list[str] | None = None, prog: str = "lapis-design critic packet") -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n")[0], allow_abbrev=False)
    ap.add_argument("--task", required=True, help="the plan's task id")
    ap.add_argument("--root", type=Path, default=Path("."), help="the project folder (default: .)")
    ap.add_argument("--extract", action="append", default=[], help="a render extract the critic judges (repeatable; "
                    "default: .lapis/renders/<task>.json). A draft passes its narrow extracts")
    ap.add_argument("--lint", help="the lint report (default: .lapis/lint/<task>.json)")
    ap.add_argument("--session", help="the behavior session (default: .lapis/behavior/<task>.json when it exists and "
                    "no --extract was given)")
    ap.add_argument("--out", help="where to write the packet, under .lapis/critic/ (default: "
                    ".lapis/critic/<task>.packet.json)")
    args = ap.parse_args(argv)
    if not TASK.fullmatch(args.task):
        ap.error("--task must be a plan task id (lowercase letters, digits, and hyphens)")
    root = args.root.resolve()
    try:
        from lapis_design import release_check

        paths = {name: _rel(root, path) for name, path in release_check.input_paths(root, args.task).items()}
        out = (root / (args.out or paths["packet"])).resolve()
        if not out.is_relative_to((root / ".lapis" / "critic").resolve()) or not out.is_relative_to(root) \
                or out.suffix != ".json":
            raise PacketError("--out must be a .json file under .lapis/critic/")
        plan = _plan(root, args.task)
        _observe(root, args.task, plan)
        session = args.session or (paths["session"] if not args.extract and (root / paths["session"]).is_file() else None)
        data = build(root, args.task, {"extracts": args.extract or [paths["extract"]],
                                       "lint": args.lint or paths["lint"], "session": session})
        _write(out, data)
    except (PacketError, OSError) as exc:
        print(f"critic packet: {exc}", file=sys.stderr)
        return 2
    packet, shown = json.loads(data), _rel(root, out)
    print(f"critic packet: {shown} (sha256 {digest(data)}): {len(packet['requirements']['rows'])} requirement rows, "
          f"{len(packet['changes'])} changes, {len(packet['disputes'])} disputes, {len(packet['inputs'])} input files")
    print("  give the critic this packet and the files it lists, nothing else; its report names it:")
    print(f"  target.packet: {{path: {shown}, sha256: {digest(data)}}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
