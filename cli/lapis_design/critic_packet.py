"""Critic packet: the fixed inputs a critic report is judged against, built and verified by the CLI.

`lapis-design critic packet --task T` writes `.lapis/critic/T.packet.json`: the owner's requirement rows, the plan's
design fields without the maker's reasons, a digest of every file the critic may read, the lint findings, the change
rows that were reactive or touched an open finding, the maker's disputes without their reasons, and the reference digest (what
each reference gives the page and what it leaves out, with the owner's replies applied; `reference_digest.py`). The bytes are
deterministic (sorted keys, no timestamps), so an unchanged input set reproduces the same digest.

A critic report counts only for the packet whose file bytes hash to its `target.packet.sha256`. `check` rebuilds the
packet from the arguments recorded in it, so a changed input (a capture, the lint report, a requirement row, a plan
field the packet carries, a change row) makes the report stale, and it checks that the report judges every row,
change, and dispute of the packet and cites only files and quotes that exist. That proves which inputs were declared,
never what the critic actually read or that it was independent.

A delta packet (`lapis-design critic packet --task T --prior REPORT`) follows a report that judged a full packet. When only
the owner's rows changed on the same shown build (requirement rows, change rows, disputes, and the owner-decided gaps
and asks that come with them), it carries the new and changed rows, the prior report's findings those rows affect (every
open core finding among them), the digest of the prior report, and the unchanged evidence by digest. `check` accepts a
report on it as full coverage with the prior report only for a caller that allows delta (the pre-show review and the
slice seal); the release's critic is always a full independent review. Anything but owner rows (a capture, the lint
report, the plan, the direction, the worker rules, the packet format) forces a full packet.
"""
from __future__ import annotations

import argparse
import copy
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

from lapis_design import asks, direction, draft, gaps, motion, reference_digest, shared_dir, telemetry, workers
from lapis_design import extracts as source_extracts

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
# What a delta packet may differ in from the full packet it follows: the owner's rows, with the owner's own answers
# (decided gaps, asks) that come with them. Everything else is evidence, and a change in it needs a full review.
ROW_SECTIONS = ("requirements", "changes", "disputes", "gaps", "asks", "supporting")


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
                       for r in [*record["rows"], *_seq(record.get("guideline_rows"))])):
        raise PacketError(f"the requirement record {path} has no rows with an id and a text")
    return record


def _requirements(record: dict | None) -> dict:
    if record is None:
        return {"sha256": None, "rows": [], "owner_decisions": []}
    rows = [_wrap(id=r["id"], section=r.get("section"), text=r["text"]) for r in record["rows"]]
    # the guideline rows follow the owner's, with what measures each (a lapis source, never the owner's words)
    rows += [_wrap(id=r["id"], section=r.get("section"), text=r["text"], guideline=r.get("guideline"))
             for r in _seq(record.get("guideline_rows"))]
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


MOTION_WIDTHS = (390, 1440)
MOTION_KINDS = ("playback", "settled", "reduced")


def _base(tag: object) -> str:
    return str(tag or "").split("-")[0].lower()


def _documents(extracts: list[Path]) -> list[dict]:
    return [doc for path in extracts if isinstance(doc := _json(path, "the render extract"), dict)]


def _moves(documents: list[dict]) -> bool:
    """Whether a page of these extracts moves on its own or on scroll: a CSS animation, a box that moves at rest, or one
    that is hidden until it scrolls into view (plain hover and focus transitions are not motion to show)."""
    for doc in documents:
        for view in _seq(doc.get("viewports")):
            for box in _seq(_map(view).get("boxes")):
                found = _map(_map(box).get("motion"))
                if found.get("animations") or found.get("moves_at_rest") or found.get("hidden_until_scroll"):
                    return True
    return False


def _shown_locales(documents: list[dict]) -> list[str]:
    """The base languages the extracts' text runs declare, sorted; empty when none declares one."""
    return sorted({_base(run.get("lang")) for doc in documents for view in _seq(doc.get("viewports"))
                   for run in _seq(_map(view).get("text")) if isinstance(run, dict) and run.get("lang")} - {""})


def _motion(root: Path, task: str, name: str | None, extracts: list[Path]) -> tuple[dict, list[Path]]:
    """The packet's `motion` section and the files it lists, from the manifest `render motion` wrote (`name`). A page that
    moves needs one: playback, settled, and reduced-motion captures at 390 and 1440 for each locale its extracts show,
    recorded from the build the extracts captured. PacketError names what is missing and the command that records it."""
    documents = _documents(extracts)
    moves = _moves(documents)
    command = f"lapis-design render motion <url> --task {task} [--lang <tag>]"
    manifest = _inside(root, name) if name else None
    if manifest is None:
        if moves or name:
            untied = not any(isinstance(_map(doc.get("source")).get("document_sha256"), str) for doc in documents)
            first = ("the extracts carry no `source.document_sha256`, so a motion record could not be tied to them: run "
                     "`lapis-design render check` again first, then ") if untied else ""
            raise PacketError(f"the page moves (a CSS animation, a box that moves at rest, or one hidden until scroll) and the "
                              f"packet has no motion evidence ({name or motion.manifest_path(root, task).relative_to(root).as_posix()}): "
                              f"{first}record it with `{command}`, once for each locale the owner is shown")
        return {}, []
    document = _json(manifest, "the motion evidence")
    if problem := _first_error(_validator("render/motion.schema.yaml"), document):
        raise PacketError(f"{_rel(root, manifest)} does not match render/motion.schema.yaml: {problem}")
    if document["task"] != task:
        raise PacketError(f"{_rel(root, manifest)} names task {document['task']!r}, not {task!r}")
    wanted = _shown_locales(documents)
    entries = {_base(e["lang"]): e for e in document["locales"]}
    missing = [f"locale {tag}" for tag in wanted if tag not in entries and "und" not in entries]
    identities = {src for doc in documents if isinstance(src := _map(doc.get("source")).get("document_sha256"), str)}
    files: list[Path] = [manifest]
    scenes: list[dict] = []
    locales = []
    for entry in sorted(document["locales"], key=lambda e: e["lang"]):
        blocks = {b["width"]: b for b in entry["widths"]}
        for width in MOTION_WIDTHS:
            block = blocks.get(width)
            if block is None:
                missing.append(f"{entry['lang']} at {width}")
                continue
            kinds = {r["kind"] for r in block["recordings"]}
            missing += [f"{entry['lang']} {kind} at {width}" for kind in MOTION_KINDS if kind not in kinds]
            if not identities:
                raise PacketError(f"{_rel(root, manifest)} cannot be tied to the build the extracts captured: they carry no "
                                  "`source.document_sha256`; run `lapis-design render check` again, then record the motion")
            if block["document_sha256"] not in identities:
                raise PacketError(f"{_rel(root, manifest)}: the {entry['lang']} recording at {width} is of another build than "
                                  "the extracts (the main document differs): run `render check` and "
                                  f"`{command}` on the same build")
            for row in block["recordings"]:
                files.append(_file(root, row["path"], "a motion recording"))
            for scene in block["scenes"]:
                dwell = round(scene["runway_px"] * 1000 / document["meta"]["px_per_s"])
                scenes.append({"id": f"{entry['lang']}-{width}-{scene['id']}", "selector": scene["selector"],
                               "text": scene["text"], "content_px": scene["content_px"], "runway_px": scene["runway_px"],
                               "dwell_ms": dwell})
        locales.append({"lang": entry["lang"], "widths": [
            {"width": b["width"], "document_sha256": b["document_sha256"], "scroll_height": b["scroll_height"],
             "recordings": [{k: r[k] for k in ("kind", "path", "sha256", "scroll_y", "seconds") if k in r}
                            for r in b["recordings"]]} for b in sorted(entry["widths"], key=lambda b: b["width"])]})
    if missing:
        raise PacketError(f"the motion evidence {_rel(root, manifest)} lacks {_names(missing, 6)}: record it with `{command}`")
    return ({"manifest": {"path": _rel(root, manifest), "sha256": digest(manifest.read_bytes())},
             "px_per_s": document["meta"]["px_per_s"], "locales": locales, "scenes": scenes}, files)


def _listed(root: Path, task: str, plan: dict, record: dict | None, extracts: list[Path], lint: Path,
            session: Path | None, motion_files: list[Path] = (), supporting: list[Path] = ()) -> list[dict]:
    """Every file the critic may read, once, with its digest. The first kind that names a file stands."""
    seen: dict[str, dict] = {}

    def add(kind: str, path: Path | None) -> bool | None:
        if path is None:
            return None
        rel = _rel(root, path)
        if rel not in seen and not _hidden(rel):
            seen[rel] = {"kind": kind, "path": rel, "sha256": digest(path.read_bytes())}
        return rel in seen

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
    for path in motion_files:
        add("motion", path)
    for path in supporting:
        add("supporting-evidence", path)
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
    if add("source-extracts", _inside(root, f".lapis/extracts/{task}.json")):
        for item in source_extracts.load(root, task)["extracts"]:      # the originals, so a claim can be opened at its lines
            outside("extract-source", item["source"]["path"])
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
                  location=item.get("location"), status=item.get("status"), guideline_items=item.get("guideline_items"))
            for index, item in enumerate(items)]


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
    if held := source_extracts.verify(root, task):         # the critic reads only grounded facts that still hold (extracts.py)
        raise PacketError(f"the extract record .lapis/extracts/{task}.json cannot go to a critic: {'; '.join(held[:3])}"
                          + (f" (and {len(held) - 3} more)" if len(held) > 3 else "")
                          + f"; run `lapis-design extract check --task {task}`, then `extract drop --stale` or re-record")
    motion_name = _named(root, inputs["motion"], "the motion evidence") if inputs.get("motion") else None
    shown, motion_files = _motion(root, task, motion_name, extracts)
    support = []
    for entry in draft.supporting_for(root, task, extract_names):
        file = _inside(root, entry["path"])
        if file is not None and not _hidden(_rel(root, file)):
            support.append((file, _wrap(kind=entry["kind"], link=entry["link"], path=_rel(root, file),
                                        sha256=digest(file.read_bytes()), claim=entry["claim"], page=entry.get("page"))))
    document = {
        "version": 0, "task": task,
        "args": _wrap(extracts=extract_names, lint=_rel(root, lint), session=session_name, motion=motion_name),
        "rules": {"sha256": digest(workers.rules().encode("utf-8"))},
        "requirements": _requirements(record), "plan": _design(plan),
        "direction": direction.packet(root, task),
        "gaps": [_wrap(id=g["id"], area=g["area"], text=g["text"]) for g in gaps.compute(root, task)],
        "asks": [_wrap(trigger=a["trigger"], by=a["by"], said=a["said"]) for a in asks.recorded(root, task)],
        "inputs": _listed(root, task, plan, record, extracts, lint, session, motion_files, [f for f, _ in support]),
        "findings": _findings(root, lint), "changes": _changes(root, task), "disputes": _disputes(root, task)}
    if shown:
        document["motion"] = shown
    if digest_section := reference_digest.packet(root, task):
        document["reference_digest"] = digest_section
    if support:
        document["supporting"] = [entry for _, entry in support]
    if problem := _first_error(_validator("review/critic-packet.schema.yaml"), document):
        raise PacketError(f"the packet does not match review/critic-packet.schema.yaml: {problem}")
    return _dump(document)


def _dump(document: dict) -> bytes:
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
        elif key == "rules":
            parts.append("the worker rules")
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


def _entries(report: dict, name: str) -> list[dict]:
    return [item for item in _seq(report.get(name)) if isinstance(item, dict)]


def _covers(gaps: list[str], report: dict, name: str, key: str, wanted: list, label: str) -> None:
    """Add to `gaps` what the report's `name` entries (one per `key` value) leave out, add, or repeat against `wanted`."""
    seen = [value for item in _entries(report, name) if isinstance(value := item.get(key), (str, int))]
    if missing := [item for item in wanted if item not in seen]:
        gaps.append(f"`{name}` has no entry for {_names([label + str(m) for m in missing])}")
    if unknown := [item for item in dict.fromkeys(seen) if item not in wanted]:
        gaps.append(f"`{name}` names {_names([label + str(u) for u in unknown])}, which the packet does not list")
    if repeated := [item for item in dict.fromkeys(seen) if item in wanted and seen.count(item) > 1]:
        gaps.append(f"`{name}` judges {_names([label + str(r) for r in repeated])} more than once")


def _cited(root: Path, report: dict, rows: list[str], listed: set[str]) -> list[str]:
    """What the report cites that is not there: a change that names a row the packet does not list, a file-like ref that is
    no readable file, a fact whose source is not a listed file or whose quote is not in the lines it cites."""
    gaps: list[str] = []
    for change in _entries(report, "changes"):
        if unknown := [row for row in _seq(change.get("rows")) if row not in rows]:
            gaps.append(f"change {change.get('seq')} names {_names(unknown)}, which are not requirement rows of the packet")
    refs = [ref for name in ("requirements", "facts", "disputes", "walkthroughs", "motion") for item in _entries(report, name)
            for ref in _seq(item.get("refs")) if isinstance(ref, str)]
    gaps += [problem for ref in dict.fromkeys(refs) if (problem := _ref_problem(root, ref))]
    gaps += [problem for index, fact in enumerate(_seq(report.get("facts")))
             if isinstance(fact, dict) and (problem := _fact_problem(root, index, fact, listed))]
    return gaps


def _gaps(root: Path, packet: dict, report: dict) -> list[str]:
    gaps: list[str] = []
    rows = [row["id"] for row in packet["requirements"]["rows"]]
    _covers(gaps, report, "requirements", "id", rows, "")
    _covers(gaps, report, "changes", "seq", [change["seq"] for change in packet["changes"]], "change ")
    _covers(gaps, report, "disputes", "index", [dispute["index"] for dispute in packet["disputes"]], "dispute ")
    _covers(gaps, report, "motion", "scene", [scene["id"] for scene in _map(packet.get("motion")).get("scenes", [])], "scene ")
    return gaps + _cited(root, report, rows, {item["path"] for item in packet["inputs"]})


def _delta_gaps(root: Path, packet: dict, report: dict, listed: set[str]) -> list[str]:
    """What a report on a delta packet leaves out: a changed or new row, change, or dispute it does not judge, an open core
    finding of the prior report it does not re-judge (a finding of the report with `supersedes` the prior finding's index,
    still open and still core, or fixed), or a judgment of what the delta does not list."""
    gaps: list[str] = []
    _covers(gaps, report, "requirements", "id", [row["id"] for row in packet["requirements"]["changed"]], "")
    _covers(gaps, report, "changes", "seq", [change["seq"] for change in packet["changes"]["changed"]], "change ")
    _covers(gaps, report, "disputes", "index", [dispute["index"] for dispute in packet["disputes"]["changed"]], "dispute ")
    _covers(gaps, report, "motion", "scene", [], "scene ")
    prior = {item["index"]: item for item in packet["prior_findings"]}
    redone = [(item["supersedes"], item) for item in _entries(report, "findings") if isinstance(item.get("supersedes"), int)]
    seen = [index for index, _ in redone]
    if missing := [index for index, item in prior.items() if item["rejudge"] and index not in seen]:
        gaps.append(f"`findings` does not re-judge the open core finding {_names([f'{i} ({prior[i]['rule_id']})' for i in missing])}: "
                    "write a finding with `supersedes` its index, still open as a core finding, or fixed")
    if unknown := [index for index in dict.fromkeys(seen) if index not in prior]:
        gaps.append(f"`findings` supersedes {_names(unknown)}, which the packet does not list")
    if repeated := [index for index in dict.fromkeys(seen) if index in prior and seen.count(index) > 1]:
        gaps.append(f"`findings` re-judges {_names(repeated)} more than once")
    for index, item in redone:
        if index not in prior:
            continue
        if item.get("rule_id") != prior[index]["rule_id"]:
            gaps.append(f"finding {index} is re-judged as {item.get('rule_id')}, not as {prior[index]['rule_id']}")
        elif prior[index]["rejudge"]:
            status = item.get("status")
            if status not in ("open", "fixed"):
                gaps.append(f"the open core finding {index} is re-judged as {status!r}; a delta review leaves it open or fixed")
            elif status == "open" and not draft.is_core({"status": "open", "rule_id": item.get("rule_id"),
                                                          "approval_impact": item.get("approval_impact")}):
                gaps.append(f"the open core finding {index} is re-judged open but not core; a delta review keeps it core or fixes it")
    return gaps + _cited(root, report, packet["requirements"]["ids"], listed)


def check(root: Path, report_path: Path | str, *, allow_delta: bool = False) -> Verdict:
    """Compare the critic report at `report_path` (a path this process can open) with the packet it names and the
    project as it is now. Never raises for a bad report or packet: each fault is a line of the verdict. A report on a
    delta packet counts only when `allow_delta` (the pre-show review, the slice seal); the release's critic never takes
    one."""
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
        if _is_delta(packet):
            return _check_delta(root, verdict, packet, data, _map(report), allow_delta)
        if problem := _first_error(_validator("review/critic-packet.schema.yaml"), packet):
            raise PacketError(f"the packet is not valid: {problem}")
        rebuilt = build(root, packet["task"], packet["args"])
    except (ValueError, OSError) as exc:
        verdict.stale.append(f"{STALE}: it cannot be rebuilt now ({exc})")
        return verdict
    verdict.packet = packet
    if rebuilt != data:
        hint = ""
        if allow_delta and delta(root, packet["task"], str(report_path)).document is not None:
            hint = (f" Only the owner's rows changed on the same shown build, so a delta review is enough: `lapis-design critic "
                    f"packet --task {packet['task']} --prior {_rel(root, Path(report_path).resolve())} --out "
                    f".lapis/critic/<name>.delta.packet.json`.")
        verdict.stale.append(f"{STALE}: {_moved(packet, json.loads(rebuilt))} changed since; rebuild it with "
                             f"`lapis-design critic packet --task {packet['task']}` and run the critic on the new one.{hint}")
        return verdict
    verdict.gaps = _gaps(root, packet, _map(report))
    return verdict


def _check_delta(root: Path, verdict: Verdict, packet: dict, data: bytes, report: dict, allow_delta: bool) -> Verdict:
    """`check` for a report whose packet is a delta: the prior report is as it was, the delta is what the project now
    gives, and the report judges everything the delta lists."""
    if not allow_delta:
        verdict.stale.append(f"{STALE}: it judges a delta packet, and a delta review never counts where a full independent "
                             f"review is required (the release's critic); run `lapis-design critic packet --task "
                             f"{packet.get('task', '<task>')}` without --prior and have a fresh critic judge that packet")
        return verdict
    try:
        if problem := _first_error(_validator("review/critic-delta-packet.schema.yaml"), packet):
            raise PacketError(f"the delta packet is not valid: {problem}")
        prior = packet["prior"]["report"]
        file = _inside(root, prior["path"])
        if file is None or digest(file.read_bytes()) != prior["sha256"]:
            verdict.stale.append(f"{STALE}: the prior report {prior['path']} is not the one the delta packet named "
                                 f"({prior['sha256'][:12]}); a changed prior report is no review. Run a full review: "
                                 f"`lapis-design critic packet --task {packet['task']}`")
            return verdict
        found = delta(root, packet["task"], prior["path"])
    except (ValueError, OSError) as exc:
        verdict.stale.append(f"{STALE}: it cannot be rebuilt now ({exc})")
        return verdict
    verdict.packet = packet
    if found.document is None:
        verdict.stale.append(f"{STALE}: it can no longer be a delta ({'; '.join(found.reasons)}); a full review is needed: "
                             f"`lapis-design critic packet --task {packet['task']}`")
        return verdict
    if _dump(found.document) != data:
        verdict.stale.append(f"{STALE}: {_moved(packet, found.document)} changed since; rebuild it with `lapis-design critic "
                             f"packet --task {packet['task']} --prior {prior['path']}` and run the critic on the new one")
        return verdict
    verdict.gaps = _delta_gaps(root, packet, report, {item["path"] for item in found.full["inputs"]})
    return verdict


def verify(root: Path, report_path: Path | str, *, allow_delta: bool = False) -> list[str]:
    """The faults of a critic report against its packet and the project, empty when it holds."""
    return check(root, report_path, allow_delta=allow_delta).problems


def _is_delta(packet: object) -> bool:
    return isinstance(packet, dict) and packet.get("kind") == "delta"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decisions(packet: dict) -> dict[str, list]:
    found: dict[str, list] = {}
    for item in packet["requirements"]["owner_decisions"]:
        found.setdefault(item["row"], []).append((item["decision"], item["quote"]))
    return {row: sorted(items) for row, items in found.items()}


def _dispute_key(dispute: dict) -> str:
    return _canonical([dispute.get("report"), dispute.get("rule_id"), dispute.get("location"), dispute.get("observed")])


@dataclass
class Delta:
    """What `delta` found: the delta packet's document, with the full packet the project gives now (`full`, and its size in
    characters), or the reasons a full review is needed instead."""
    document: dict | None = None
    full: dict | None = None
    full_chars: int = 0
    reasons: list[str] = field(default_factory=list)


def delta(root: Path, task: str, prior_report: object) -> Delta:
    """The delta packet for `task` after the critic report `prior_report` (a path), or the reasons there is none. A delta
    exists only when that report judged a full packet completely, its bytes and its packet's are as the report named them,
    and the packet the project gives now for the same arguments differs from the prior one in owner rows alone: the
    captures, the lint report, the plan, the direction, the motion evidence, and the worker rules are the same."""
    root = root.resolve()
    out = Delta()

    def refuse(reason: str) -> Delta:
        out.reasons.append(reason)
        return out

    file = _inside(root, prior_report)
    if file is None:
        return refuse(f"the prior report {prior_report} is not a file in the project")
    try:
        body = file.read_bytes()
        report = json.loads(body)
    except (OSError, ValueError) as exc:
        return refuse(f"the prior report cannot be read ({exc})")
    named = _map(_map(report).get("target")).get("packet")
    if not (isinstance(named, dict) and isinstance(named.get("path"), str) and isinstance(named.get("sha256"), str)):
        return refuse("the prior report names no packet")
    packet_file = _inside(root, named["path"])
    if packet_file is None:
        return refuse(f"the prior packet {named['path']} is not a file in the project")
    data = packet_file.read_bytes()
    if digest(data) != named["sha256"]:
        return refuse("the prior packet was rebuilt after its report named it")
    try:
        old = json.loads(data)
    except ValueError as exc:
        return refuse(f"the prior packet cannot be read ({exc})")
    if _is_delta(old):
        return refuse("the prior report judges a delta packet; a delta follows a full independent review, never another delta")
    if problem := _first_error(_validator("review/critic-packet.schema.yaml"), old):
        return refuse(f"the prior packet is not a valid full packet: {problem}")
    if old["task"] != task:
        return refuse(f"the prior packet is of task {old['task']}, not {task}")
    if "rules" not in old:
        return refuse("the prior packet carries no digest of the worker rules, so what its critic was told cannot be compared")
    if faults := _gaps(root, old, _map(report)):
        return refuse(f"the prior report does not judge its own packet ({faults[0]})")
    try:
        full = build(root, task, old["args"])
    except PacketError as exc:
        return refuse(f"the packet for the same shown build cannot be built now: {exc}")
    new = json.loads(full)
    if new["requirements"]["sha256"] is None:
        return refuse("the task has no requirement record, so there are no owner rows to review")
    held_old, held_new = ({**{k: v for k, v in p.items() if k not in ROW_SECTIONS},
                           "inputs": [i for i in p["inputs"] if i["kind"] not in ("requirement-source", "supporting-evidence")]}
                          for p in (old, new))
    if held_old != held_new:
        return refuse(f"more than the owner's rows changed since the prior review ({_moved(held_old, held_new)})")
    if old == new:
        return refuse("nothing changed since the prior review; its report still holds")
    rows_before = {row["id"]: row for row in old["requirements"]["rows"]}
    decided_before, decided_now = _decisions(old), _decisions(new)
    changed = []
    for row in new["requirements"]["rows"]:
        before = rows_before.get(row["id"])
        if before is None:
            changed.append({**row, "change": "new"})
        elif before != row or decided_before.get(row["id"]) != decided_now.get(row["id"]):
            changed.append({**row, "change": "changed"})
    ids = [row["id"] for row in new["requirements"]["rows"]]
    changed_ids = {row["id"] for row in changed}
    known = {(d["row"], d["decision"], d["quote"]) for d in old["requirements"]["owner_decisions"]}
    changes_before = {change["seq"]: change for change in old["changes"]}
    changes = [change for change in new["changes"] if changes_before.get(change["seq"]) != change]
    disputes_before = {_dispute_key(d): d["index"] for d in old["disputes"]}
    disputes = [d for d in new["disputes"] if _dispute_key(d) not in disputes_before]
    gaps_before = {g["id"]: g for g in old["gaps"]}
    related = {rule for change in changes for rule in change["related_open"]} | {d["rule_id"] for d in disputes}
    affected = []
    for index, finding in enumerate(_seq(_map(report).get("findings"))):
        if not isinstance(finding, dict):
            continue
        stated = {"status": finding.get("status"), "rule_id": finding.get("rule_id"),
                  "approval_impact": finding.get("approval_impact")}
        core = stated["status"] == "open" and draft.is_core(stated)
        why = ["an open core finding"] if core else []
        if stated["status"] == "open":
            if stated["rule_id"] in related:
                why.append("a changed change row or dispute names its rule")
            if named_rows := sorted(row for row in changed_ids if row in _canonical(finding)):
                why.append(f"it names {', '.join(named_rows)}")
        if why:
            affected.append(_wrap(index=index, rule_id=str(stated["rule_id"] or ""), observed=str(finding.get("observed") or ""),
                                  status=str(stated["status"] or ""), approval_impact=stated["approval_impact"],
                                  rejudge=core, why=why))
    out.full, out.full_chars = new, len(full)
    out.document = {
        "version": 0, "kind": "delta", "task": task, "args": new["args"], "rules": new["rules"],
        "prior": {"report": {"path": _rel(root, file), "sha256": digest(body)},
                  "packet": {"path": _rel(root, packet_file), "sha256": named["sha256"]}},
        "unchanged": {"inputs": {"count": len(held_new["inputs"]),
                                 "sha256": digest(_canonical(held_new["inputs"]).encode("utf-8"))},
                      "sections": {key: digest(_canonical(new[key]).encode("utf-8"))
                                   for key in ("plan", "direction", "reference_digest", "findings", "motion") if key in new}},
        "requirements": {"sha256": new["requirements"]["sha256"], "ids": ids, "sources": [
                             i for i in new["inputs"] if i["kind"] == "requirement-source"],
                         "removed": sorted(set(rows_before) - set(ids)), "changed": changed,
                         "owner_decisions": [d for d in new["requirements"]["owner_decisions"]
                                             if d["row"] in changed_ids or (d["row"], d["decision"], d["quote"]) not in known]},
        "changes": {"seqs": [change["seq"] for change in new["changes"]], "changed": changes},
        "disputes": {"total": len(new["disputes"]), "changed": disputes,
                     "carried": [{"from": disputes_before[key], "to": d["index"]} for d in new["disputes"]
                                 if (key := _dispute_key(d)) in disputes_before]},
        "gaps": {"changed": [g for g in new["gaps"] if gaps_before.get(g["id"]) != g],
                 "removed": sorted(set(gaps_before) - {g["id"] for g in new["gaps"]})},
        "asks": {"changed": [a for a in new["asks"] if a not in old["asks"]]},
        "supporting": {"changed": [s for s in new.get("supporting", []) if s not in old.get("supporting", [])],
                       "removed": sorted({s["path"] for s in old.get("supporting", [])}
                                         - {s["path"] for s in new.get("supporting", [])})},
        "prior_findings": affected}
    return out


def effective(root: Path, report_path: Path | str) -> dict | None:
    """The report on a delta packet completed with the prior report it follows, as one report that judges every row, change,
    and dispute of the project now: the prior report's judgments of what did not change, the delta report's of what did,
    and the prior findings with the delta report's re-judgments in place of the ones they supersede. None when the report
    is not on a delta packet or the prior cannot be read; `check` is what says whether it counts."""
    root = root.resolve()
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        packet = json.loads(_inside(root, report["target"]["packet"]["path"]).read_bytes())
        if not _is_delta(packet):
            return None
        prior = json.loads(_inside(root, packet["prior"]["report"]["path"]).read_text(encoding="utf-8"))
        return _merge(prior, report, packet)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _merge(prior: dict, report: dict, packet: dict) -> dict:
    merged = copy.deepcopy(prior)
    merged["target"] = copy.deepcopy(report["target"])

    def pick(name: str, key: str, wanted: list) -> list:
        mine = {item[key]: item for item in _entries(report, name) if key in item}
        before = {item[key]: item for item in _entries(prior, name) if key in item}
        return [copy.deepcopy(mine.get(value) or before[value]) for value in wanted if value in mine or value in before]

    merged["requirements"] = pick("requirements", "id", packet["requirements"]["ids"])
    merged["changes"] = pick("changes", "seq", packet["changes"]["seqs"])
    carried = {step["from"]: step["to"] for step in packet["disputes"]["carried"]}
    merged["disputes"] = [{**copy.deepcopy(item), "index": carried[item["index"]]} for item in _entries(prior, "disputes")
                          if item.get("index") in carried] + copy.deepcopy(_entries(report, "disputes"))
    redone = {item["supersedes"]: item for item in _entries(report, "findings") if isinstance(item.get("supersedes"), int)}
    merged["findings"] = [{k: v for k, v in (redone.get(index) or item).items() if k != "supersedes"}
                          for index, item in enumerate(_seq(prior.get("findings"))) if isinstance(item, dict)]
    merged["findings"] += [copy.deepcopy(item) for item in _entries(report, "findings") if not isinstance(item.get("supersedes"), int)]
    for name in ("facts", "walkthroughs", "comparisons", "motion"):
        found = copy.deepcopy(_entries(prior, name))
        found += [item for item in copy.deepcopy(_entries(report, name)) if item not in found]
        if found:
            merged[name] = found
    merged["summary"] = {**_map(prior.get("summary")), "blocking": sum(bool(f.get("blocking")) for f in merged["findings"]),
                         "total": len(merged["findings"])}
    return merged


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
    ap.add_argument("--motion", help="the motion evidence `lapis-design render motion` wrote (default: "
                    ".lapis/renders/<task>.motion.json when it exists); a page that moves needs it")
    ap.add_argument("--prior", help="a critic report on a full packet of the same shown build: write a delta packet "
                    "(the owner's changed rows, and the prior findings they affect) instead of a full one. Only the owner's "
                    "rows may have changed since; the captures and arguments are the prior packet's, so none are given. "
                    "A delta never counts for the release's critic")
    ap.add_argument("--out", help="where to write the packet, under .lapis/critic/ (default: "
                    ".lapis/critic/<task>.packet.json, or <task>.delta.packet.json with --prior)")
    args = ap.parse_args(argv)
    if not TASK.fullmatch(args.task):
        ap.error("--task must be a plan task id (lowercase letters, digits, and hyphens)")
    if args.prior and (args.extract or args.lint or args.session or args.motion):
        ap.error("--prior takes the arguments of the prior packet: do not give --extract, --lint, --session, or --motion")
    root = args.root.resolve()
    started = telemetry.stamp()

    def done(code: int, text: str, *, path: str | None = None, data: bytes = b"") -> int:
        (sys.stdout if code == 0 else sys.stderr).write(text)
        telemetry.record(root, command="critic packet", task=args.task, scope="delta" if args.prior else "full",
                         cache="off", started=started, ended=telemetry.stamp(), exit=code,
                         output_chars=len(text) if code == 0 else 0, report_path=path,
                         packet_chars=len(data), packet_sha256=digest(data) if data else None)
        return code

    try:
        from lapis_design import release_check

        paths = {name: _rel(root, path) for name, path in release_check.input_paths(root, args.task).items()}
        default = paths["packet"].replace(".packet.json", ".delta.packet.json") if args.prior else paths["packet"]
        out = (root / (args.out or default)).resolve()
        if not out.is_relative_to((root / ".lapis" / "critic").resolve()) or not out.is_relative_to(root) \
                or out.suffix != ".json":
            raise PacketError("--out must be a .json file under .lapis/critic/")
        plan = _plan(root, args.task)
        _observe(root, args.task, plan)
        found = None
        if args.prior:
            found = delta(root, args.task, args.prior)
            if found.document is None:
                raise PacketError("no delta review is possible, so the review is a full independent one "
                                  f"(`lapis-design critic packet --task {args.task}` without --prior): " + "; ".join(found.reasons))
            data = _dump(found.document)
        else:
            motion_default = _rel(root, motion.manifest_path(root, args.task))
            session = args.session or (paths["session"] if not args.extract and (root / paths["session"]).is_file() else None)
            data = build(root, args.task, {"extracts": args.extract or [paths["extract"]],
                                           "lint": args.lint or paths["lint"], "session": session,
                                           "motion": args.motion or (motion_default if (root / motion_default).is_file() else None)})
        _write(out, data)
    except (PacketError, OSError) as exc:
        return done(2, f"critic packet: {exc}\n")
    packet, shown = json.loads(data), _rel(root, out)
    if found is not None:
        ask = packet["requirements"]
        lines = [f"critic packet (delta): {shown} (sha256 {digest(data)}): {len(ask['changed'])} of {len(ask['ids'])} "
                 f"requirement rows, {len(packet['changes']['changed'])} changes, {len(packet['disputes']['changed'])} disputes "
                 f"to judge; {sum(item['rejudge'] for item in packet['prior_findings'])} open core findings and "
                 f"{sum(not item['rejudge'] for item in packet['prior_findings'])} other prior findings to re-judge; "
                 f"{len(data)} characters against {found.full_chars} for the full packet",
                 f"  prior report {packet['prior']['report']['path']} (sha256 {packet['prior']['report']['sha256']}) and its "
                 f"packet {packet['prior']['packet']['path']} stay unchanged; give the critic this delta, the prior report and "
                 "packet, and the files the prior packet lists, nothing else. It judges only what the delta lists, and writes a "
                 "finding with `supersedes` for each prior finding it re-judges",
                 "  put these lines into its task verbatim (shared/review/worker-rules.md):"]
    else:
        guideline = sum(row["id"].startswith("G:") for row in packet["requirements"]["rows"])
        rows = f"{len(packet['requirements']['rows']) - guideline} requirement rows" + (
            f" and {guideline} guideline rows" if guideline else "")
        lines = [f"critic packet: {shown} (sha256 {digest(data)}): {rows}, "
                 f"{len(packet['changes'])} changes, {len(packet['disputes'])} disputes, {len(packet['inputs'])} input files",
                 "  give the critic this packet and the files it lists, nothing else, and put these lines into its task verbatim "
                 "(shared/review/worker-rules.md):"]
    lines += [f"    {line}" for line in workers.rules().splitlines()]
    lines += ["  its report names the packet:", f"  target.packet: {{path: {shown}, sha256: {digest(data)}}}"]
    return done(0, "\n".join(lines) + "\n", path=shown, data=data)


if __name__ == "__main__":
    sys.exit(main())
