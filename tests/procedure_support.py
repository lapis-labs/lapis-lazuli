"""Shared by the procedure tests (`next`, the exit gate, failure records): a project folder whose inputs and
reports are all in place, built the way test_release_check builds its own, plus the changes that make it interactive."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import yaml

from lapis_design import shared_dir
from lapis_design.cli import main as cli_main

TASK = "kiln-shop-landing"
SHARED = shared_dir()
PROBES = ("controls", "commits", "keyboard", "dialogs", "choices", "forms", "states", "urgency", "time_limits",
          "history", "pointer", "motion", "scroll", "permissions", "media", "flows", "console")


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


def make_project(root: Path) -> Path:
    """A static page with every input and report the gate reads, none of them stale, and no release report."""
    plan = yaml.safe_load((SHARED / "plan/example.plan.yaml").read_text())
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
    save(root, f"critic/{TASK}.json", report("critic", extract=f".lapis/renders/{TASK}.json"))
    for index, name in enumerate((f"plans/{TASK}.yaml", f"renders/{TASK}.json", "fonts.lock.json",
                                  "assets.ledger.json", f"lint/{TASK}.json", f"critic/{TASK}.json")):
        touch(root, name, 100 + index)
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


def ask(root: Path, text: str, at: int, task: str = TASK) -> Path:
    """The questions the run wrote for its user."""
    return record(root, "questions", text, at, task)


def reply(root: Path, text: str, at: int, task: str = TASK) -> Path:
    """The answers the run recorded."""
    return record(root, "answers", text, at, task)
