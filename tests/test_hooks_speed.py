"""The harness hooks stay light: `hook exit-plan` and `hook session-start` load neither numpy, Pillow,
nor Playwright (AGENTS.md: hooks run at every session start). Each hook runs in a fresh interpreter
the way a harness starts it, with the event on stdin, so modules other tests imported do not count."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from lazuli import cli as lazuli_cli
from lazuli import db
from synthetic_fonts import build

SHARED = Path(__file__).resolve().parents[1] / "src" / "shared"
HEAVY = ("numpy", "PIL", "playwright")

# Runs one hook through the CLI, then reports on stderr which heavy modules the interpreter loaded.
CHILD = f"""
import json, sys
from lapis_design import cli
code = cli.main(["hook", sys.argv[1]])
sys.stdout.flush()
print(json.dumps({{"code": code, "heavy": sorted(m for m in {HEAVY!r} if m in sys.modules)}}), file=sys.stderr)
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    roots = {"system": tmp_path / "system", "user": tmp_path / "user"}
    for path in roots.values():
        path.mkdir()
    monkeypatch.setenv("LAZULI_FONT_ROOTS", os.pathsep.join(f"{origin}={path}" for origin, path in roots.items()))
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "cache" / "lazuli.db"))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return roots


def run_hook(name: str, event: dict) -> tuple[dict, str]:
    r = subprocess.run([sys.executable, "-c", CHILD, name], input=json.dumps(event), capture_output=True,
                       text=True, env=dict(os.environ), timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stderr.strip().splitlines()[-1]), r.stdout


def test_exit_plan_runs_every_plan_layer_rule_without_heavy_modules(env, tmp_path):
    plan = yaml.safe_load((SHARED / "plan" / "example.plan.yaml").read_text(encoding="utf-8"))
    plan["content"]["key_copy"].append({"slot": "cta", "text": "Click here", "locale": "en"})
    block = yaml.safe_dump(plan, allow_unicode=True).rstrip()
    event = {"session_id": "s", "cwd": str(tmp_path), "permission_mode": "plan",
             "hook_event_name": "PermissionRequest", "tool_name": "ExitPlanMode",
             "tool_input": {"plan": f"# Plan\n\n```yaml lapis-plan\n{block}\n```\n"}}
    db.connect(Path(os.environ["LAZULI_DB"])).close()
    report, out = run_hook("exit-plan", event)
    decision = json.loads(out)["hookSpecificOutput"]["decision"]
    # a registry detector (copy-family-rate) judged the plan, next to plan_check's own detectors
    assert decision["behavior"] == "deny" and "copy.vague-cta" in decision["message"]
    assert report == {"code": 0, "heavy": []}


def test_session_start_summarizes_the_inventory_without_heavy_modules(env):
    build(env["user"] / "Gothic.ttf", family="Plain Gothic")
    assert lazuli_cli.main(["local", "fonts", "--json"]) == 0
    event = {"session_id": "s", "cwd": str(env["user"]), "hook_event_name": "SessionStart", "source": "startup"}
    report, out = run_hook("session-start", event)
    assert "lazuli: 1 font families in 1 files" in out
    assert "Latin without a CJK set: 1 families" in out and "unmeasured" not in out    # read at MEASURER_VERSION
    assert report == {"code": 0, "heavy": []}
