"""Helpers for the tools/eval tests that are not in test_eval_*.py: loading the scripts as modules, a run
folder in the shape run.py and score.py write, and a small evaluation font database."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "eval"))

import evalkit  # noqa: E402

TASK = "kiln-landing-ko"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"eval_{name}", ROOT / "tools" / "eval" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module          # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def run_record(arm: str, order: int, *, skills_read: list[str] | None = None, replicate: int = 1) -> dict:
    return {"id": evalkit.run_id(TASK, replicate, arm), "task": TASK, "arm": arm, "replicate": replicate,
            "order": order, "status": "completed", "exit_code": 0, "duration_s": 60.0, "project": "project",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "session": {"skills_read": skills_read if skills_read is not None else ["lapis"] if arm == "with" else []}}


def score_record(*, lint_code: str = "plan rejected", lint_reason: str = "lint could not use the plan",
                 root: str = "project") -> dict:
    return {
        "site": {"root": root, "refused_links": []},
        "checkers": {
            "render_check": {"status": "ok"},
            "behavior_check": {"status": "not scored", "code": "n/a", "reason": "no behavior check"},
            "lint": {"status": "not scored", "code": lint_code, "reason": lint_reason,
                     "layers": {"plan": {"status": "not scored", "code": lint_code, "reason": lint_reason}}}},
        "copy": {"status": "ok", "words": 100, "viewport": 390, "findings": 2, "blocking": 0,
                 "per_1000_words": 20.0, "rules": {"copy.vague-cta": 2}, "plan_findings": 0}}


def make_out(out: Path, *, score: dict | None = None, skills_read: list[str] | None = None,
             events: dict[str, str] | None = None) -> Path:
    """An out folder with a with and a without run, both scored, and the summaries score.py writes.
    `events` maps an arm to the text of that run's events.jsonl."""
    score_module = load("score")
    evalkit.write_json(out / "manifest.json", {
        "version": 1, "model": "m", "skill_digests": {"lapis": "abc"}, "tasks": {TASK: {"skills": ["lapis"]}},
        "codex": {"version": "codex-cli 0.0-test"}, "repo": {"commit": "0" * 40}})
    for order, arm in enumerate(("with", "without"), 1):
        run_dir = out / "runs" / evalkit.run_id(TASK, 1, arm)
        (run_dir / "project").mkdir(parents=True)
        evalkit.write_json(run_dir / "run.json", run_record(arm, order, skills_read=skills_read if arm == "with" else None))
        evalkit.write_json(run_dir / "score.json", score or score_record())
        if events and arm in events:
            (run_dir / "events.jsonl").write_text(events[arm], encoding="utf-8")
    score_module.write_summary(out, score_module.collect_rows(out))
    return out


def event_log(*events: dict) -> str:
    return "".join(json.dumps(event) + "\n" for event in events)


def make_font_db(path: Path, families: tuple[str, ...] = ("Open Sans", "Noto Serif"), *,
                 origin: str = "user", file_prefix: str = "/fonts/") -> Path:
    """A lazuli database (all migrations) holding one face per family, closed so that no -wal file is left."""
    from lazuli import db

    conn = db.connect(path)
    try:
        for number, family in enumerate(families):
            conn.execute("INSERT INTO local_font (path, size, mtime, family, family_norm, origin) "
                         "VALUES (?, 1, 'm', ?, ?, ?)",
                         (f"{file_prefix}{number}.ttf", family, family.lower().replace(" ", ""), origin))
        conn.commit()
    finally:
        conn.close()
    return path
