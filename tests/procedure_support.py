"""Shared by the procedure tests (`next`, the exit gate, failure records): a project folder whose inputs and
reports are all in place, built the way test_release_check builds its own, plus the changes that make it interactive."""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
from pathlib import Path

import yaml
from PIL import Image

from lapis_design import critic_packet, hints, shared_dir
from lapis_design.cli import main as cli_main

TASK = "kiln-shop-landing"
SHARED = shared_dir()
PROBES = ("controls", "commits", "keyboard", "dialogs", "choices", "forms", "states", "urgency", "time_limits",
          "history", "pointer", "motion", "scroll", "permissions", "media", "flows", "console")
BRIEF_RECORD = """# Brief: kiln shop landing

## Found

- The studio fires once a month and keeps a ruled firing log. Source: PRODUCT.md.

## Answers

- [known] Q1 Who buys? Craft lovers in their 30s and 40s. Basis: PRODUCT.md.
- [assumed] Q2 What is the one job? Reserve a piece from this firing. Basis: nobody to ask; the request names no other action.
"""


def save(root: Path, name: str, document) -> Path:
    path = root / ".lapis" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document) if path.suffix == ".yaml" else json.dumps(document), encoding="utf-8")
    return path


def update(root: Path, name: str, change) -> Path:
    path = root / ".lapis" / name
    document = yaml.safe_load(path.read_text()) if path.suffix == ".yaml" else json.loads(path.read_text())
    change(document)
    return save(root, name, document)


def touch(root: Path, name: str, seconds: int) -> None:
    os.utime(root / ".lapis" / name, (seconds, seconds))


def report(tool: str, **target) -> dict:
    return {"version": 0, "tool": {"name": tool, "version": "0.1.0"}, "target": {"task": TASK, **target},
            "findings": [], **({"scope": {"layers": ["plan", "source", "render"]}} if tool == "slop_lint" else {})}


def load_skills(root: Path, task: str = TASK) -> None:
    from lapis_design import skill_load

    for skill, sections in skill_load.REQUIRED.items():
        argv = ["--root", str(root), "--task", task, "--skill", skill,
                "--context", os.environ.get("LAPIS_CONTEXT", "procedure-test")]
        if skill == "lps-copy":
            sections = (*sections, "references/interface-copy.md#Korean")
        for section in sections:
            argv += ["--read", str(SHARED.parent / "skills" / skill / section)]
        assert skill_load.main(argv) == 0


def seal_requirements(root: Path, task: str = TASK, *owner_files: str) -> None:
    """The requirement record of the brief record already written, sealed the way `requirements seal` does."""
    from lapis_design import requirements

    requirements.seal(root, task, owner_files)


def row_id(text: str) -> str:
    """The id `requirements seal` gives a row of this text: R and the first six hex digits of its normalized text."""
    from lapis_design import requirements

    return "R" + hashlib.sha256(requirements.norm(text).encode("utf-8")).hexdigest()[:6]


def write_requirements(root: Path, rows: tuple[str, ...] = (), task: str = TASK) -> None:
    """Seal the requirement record of an owner brief that lists `rows`, one list item each (`owner-brief.md` in the
    project, which the record then reads again on every call, as it does for a real owner's file); no rows seal the
    brief record alone. The tests that use it are about what reads the record, not about extracting it."""
    if rows:
        (root / "owner-brief.md").write_text("".join(f"- {text}\n" for text in rows), encoding="utf-8")
    seal_requirements(root, task, *(["owner-brief.md"] if rows else []))


def seal_slice(root: Path, task: str = TASK) -> None:
    """A slice the owner approved, sealed in the state file the way `next` seals it: an attended create run no longer
    stops at the `slice` step."""
    from lapis_design import integrity

    integrity.seal_slice(root, task, {"url": "http://localhost/", "draft_sha256": None, "packet_sha256": None,
                                      "questions_sha256": None, "answers_sha256": None, "requirements_sha256": None})


def unseal_slice(root: Path, task: str = TASK) -> None:
    """The state of a run whose owner has not yet approved a slice."""
    state = root / ".lapis" / "state" / f"{task}.json"
    document = json.loads(state.read_text(encoding="utf-8"))
    document.pop("slice")
    state.write_text(json.dumps(document), encoding="utf-8")


def refresh_critic(root: Path, at: int | None = None, *, task: str = TASK, extracts: list[str] | None = None,
                   lint: str | None = None, session: str | None = None, name: str | None = None,
                   extra: dict | None = None) -> dict:
    """Rebuild the critic packet from the inputs as they are now, and write the critic report that names it and judges
    every row, change, and dispute in it, as a critic that did its job would. The defaults are the release inputs
    (`.lapis/critic/<task>.json` and `.packet.json`); a draft passes its narrow extracts and lint report and `name`.
    `extra` is merged into the report. `at` sets the report's modification time."""
    stem = name or task
    if session is None and extracts is None and (root / ".lapis/behavior" / f"{task}.json").is_file():
        session = f".lapis/behavior/{task}.json"
    extracts = extracts or [f".lapis/renders/{task}.json"]
    data = critic_packet.build(root, task, {"extracts": extracts, "lint": lint or f".lapis/lint/{task}.json",
                                            "session": session})
    packet_path = root / ".lapis" / "critic" / f"{stem}.packet.json"
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_bytes(data)
    packet = json.loads(data)
    document = {
        **report("critic", extract=extracts[0], packet={"path": f".lapis/critic/{stem}.packet.json",
                                                       "sha256": hashlib.sha256(data).hexdigest()}),
        "requirements": [{"id": row["id"], "state": "met", "refs": []} for row in packet["requirements"]["rows"]],
        "changes": [{"seq": c["seq"], "verdict": "repair", "rows": [], "why": "the change repairs the finding"}
                    for c in packet["changes"]],
        "disputes": [{"index": d["index"], "verdict": "finding-holds", "why": "the capture shows the finding",
                      "refs": []} for d in packet["disputes"]],
        **(extra or {})}
    save(root, f"critic/{stem}.json", document)
    if at is not None:
        touch(root, f"critic/{stem}.json", at)
    return document


def make_project(root: Path) -> Path:
    """A static page with every input and report the gate reads, none of them stale, and no release report."""
    plan = yaml.safe_load((SHARED / "plan/example.plan.yaml").read_text())
    load_skills(root)
    plan["flows"], plan["references"], plan["tokens"]["type"]["roles"] = [], [], []
    plan["tokens"]["color"]["themes"] = ["light"]
    plan["tokens"]["color"]["roles"] = [r for r in plan["tokens"]["color"]["roles"] if r.get("theme") != "dark"]
    save(root, f"plans/{TASK}.yaml", plan)
    save(root, f"renders/{TASK}.json",
         {"version": 1, "meta": {"extractor": {"name": "render_check", "version": "0.1.0"},
                                 "generated_at": "2026-09-27T00:00:00Z", "dark_theme": False},
          "source": {"kind": "render", "url": "http://localhost/", "task": TASK},
          "viewports": [{"width": w, "theme": "light", "boxes": [], "text": []} for w in (320, 390, 768, 1440)]})
    save(root, "fonts.lock.json", {"version": 0, "locked_at": "2026-09-27T00:00:00Z", "fonts": []})
    save(root, "assets.ledger.json", {"version": 0, "updated_at": "2026-09-27T00:00:00Z", "assets": []})
    save(root, f"lint/{TASK}.json", report("slop_lint", plan=f".lapis/plans/{TASK}.yaml",
                                           extract=f".lapis/renders/{TASK}.json", ledger=".lapis/assets.ledger.json",
                                           lock=".lapis/fonts.lock.json", source="."))
    for index, name in enumerate((f"plans/{TASK}.yaml", f"renders/{TASK}.json", "fonts.lock.json",
                                  "assets.ledger.json", f"lint/{TASK}.json")):
        touch(root, name, 100 + index)
    record(root, "answers", BRIEF_RECORD, 50)                    # the brief record, older than the plan and any questions
    seal_requirements(root)                                      # the owner's words from it, copied by the CLI
    seal_slice(root)                                             # the owner has approved a rendered slice
    write_references(root)                                       # the references record, as old
    refresh_critic(root, 105)                                    # the packet of all of it, and a critic report that judges it
    return root


def make_interactive(root: Path) -> None:
    """Flows in the plan, a stub, and a behavior session the lint report names, all newer than the plan."""
    update(root, f"plans/{TASK}.yaml",
           lambda d: d.update(flows=[{"id": "reserve", "kind": "primary", "goal": "Reserve one piece",
                                      "start": "/", "done": {"route": "/done"}}]))
    shutil.copy(SHARED / "behavior/example.stub.yaml", root / ".lapis/stub.yaml")
    save(root, f"behavior/{TASK}.json", {
        "version": 0, "meta": {"driver": {"name": "behavior_check", "version": "0.1.0"},
                               "generated_at": "2026-09-27T00:00:00Z", "backend": "stub", "stub": ".lapis/stub.yaml"},
        "source": {"kind": "render", "url": "http://localhost/", "task": TASK},
        "contexts": [{"id": "m", "width": 390, "height": 844, "theme": "light", "pointer": "coarse",
                      "network": "normal"}],
        "nodes": {}, "probes": {}, "coverage": [{"probe": name, "status": "not-applicable"} for name in PROBES]})
    update(root, f"lint/{TASK}.json", lambda d: (d["target"].update(session=f".lapis/behavior/{TASK}.json"),
                                                  d["scope"]["layers"].append("behavior")))
    refresh_critic(root)                                         # the critic judged the session and the flows too
    for index, name in enumerate(("plans/" + TASK + ".yaml", "stub.yaml", f"behavior/{TASK}.json")):
        touch(root, name, 90 + index)
    for index, name in enumerate(("renders/" + TASK + ".json", "fonts.lock.json", "assets.ledger.json",
                                  f"lint/{TASK}.json", f"critic/{TASK}.json")):
        touch(root, name, 100 + index)


def finish(root: Path, *flags: str) -> int:
    """Run the real release gate offline so its report is the newest file: the procedure is then complete."""
    return cli_main(["release", "check", "--task", TASK, "--root", str(root), "--offline", *flags])


def record(root: Path, folder: str, text: str, at: int, task: str = TASK) -> Path:
    """`.lapis/<folder>/<task>.md` with `text`, modified at second `at` (the order of two records is what counts)."""
    path = root / ".lapis" / folder / f"{task}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (at, at))
    return path


def ask(root: Path, text: str, at: int, task: str = TASK, kind: str | None = None) -> Path:
    """The questions the run wrote for its user, marked with their kind: `brief` before a plan exists, `approval` after
    (the default), or the kind given. Approval questions carry the owner block, as the run pastes it."""
    planned = (root / ".lapis" / "plans" / f"{task}.yaml").is_file()
    kind = kind or ("approval" if planned else "brief")
    text = f"lapis-questions: {kind}\n{text}" if text else text
    path = record(root, "questions", text, at, task)
    if planned and kind == "approval":
        from lapis_design import integrity, owner

        integrity.observe_task(root, task, "test")
        block, _ = owner.write(root, task)
        record(root, "questions", f"{text}\n\n{block}", at, task)
    return path


def reply(root: Path, text: str, at: int, task: str = TASK) -> Path:
    """The answers the run recorded: the brief record with the replies added under their own heading."""
    return record(root, "answers", f"{BRIEF_RECORD}\n## Replies\n\n{text}", at, task)


def gaps_seen(root: Path, task: str = TASK) -> str:
    """The owner's acknowledgment of the gaps in the owner block the questions file carries, as the run records it."""
    from lapis_design import waiting

    sha8 = waiting.carried((root / ".lapis" / "questions" / f"{task}.md").read_text(encoding="utf-8"))
    return f"- Gaps seen (lapis-owner-block {sha8}): \"seen, all of it\"\n"


def capture_file(root: Path, name: str, seed: int, task: str = TASK) -> str:
    """An image under `.lapis/references/<task>/` that differs from every other seed's (noise does not shrink below
    the record's size floor); returns its path as a record names it."""
    path = root / ".lapis" / "references" / task / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.frombytes("RGB", (24, 24), random.Random(seed).randbytes(24 * 24 * 3)).save(path)
    return path.relative_to(root).as_posix()


FACTS = "body 17px/1.55 in a serif, one 62ch column, ink #1a1a1a on #f4f0e8, rules 1px"


def reference_entries(root: Path, task: str = TASK) -> list[dict]:
    """Six references seen as images in four kinds, two of them outside web-ui and two of them web-ui with facts."""
    kinds = ("web-ui", "web-ui", "print", "signage", "physical-object", "archive")
    entries = []
    for index, kind in enumerate(kinds, start=1):
        entries.append({"id": f"ref-{index}", "url": f"https://museum.example/{kind}/{index}", "maker": f"Maker {index}",
                        "kind": kind, "decision": "the order of the page",
                        "capture": capture_file(root, f"ref-{index}.png", index, task),
                        "relation": "take the ruled rhythm and the label's job; leave the type and the marks",
                        **({"source_facts": FACTS} if kind == "web-ui" else {})})
    return entries


def references_text(entries: list[dict], captures: str | None = "study-only") -> str:
    body = yaml.safe_dump({**({"captures": captures} if captures else {}), "references": entries}, sort_keys=False)
    return f"# References: kiln shop landing\n\nThe captures are for study only.\n\n```yaml\n{body}```\n"


def write_references(root: Path, at: int = 50, task: str = TASK) -> list[dict]:
    """A references record that passes, with its captures, modified at second `at`."""
    load_skills(root, task)
    entries = reference_entries(root, task)
    hints.draw(root, task, "none", "2026-10-05")                  # these tests exercise evidence, not genre selection
    record(root, "references", references_text(entries), at, task)
    return entries
