"""The harness hooks stay light: `hook exit-plan`, `hook session-start`, and `hook stop` load neither numpy, Pillow,
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


def test_stop_answers_for_a_project_with_a_plan_without_heavy_modules(env, tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from procedure_support import make_project

    project = make_project(tmp_path / "project")
    (project / ".lapis/assets.ledger.json").unlink()
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    monkeypatch.setenv("LAZULI_DB", "")
    report, out = run_hook("stop", {"hook_event_name": "Stop", "cwd": str(project), "session_id": "s"})
    decision = json.loads(out)
    assert decision["decision"] == "block" and "Next step: ledger." in decision["reason"]
    assert report == {"code": 0, "heavy": []}


def test_stop_in_an_attended_folder_without_a_plan_prints_nothing_and_loads_neither_the_checks_nor_yaml(env, tmp_path):
    child = CHILD.replace("sorted(m for m in ('numpy', 'PIL', 'playwright') if m in sys.modules)",
                          "sorted(m for m in ('numpy', 'PIL', 'playwright', 'yaml', 'jsonschema', 'lapis_design.next_step') "
                          "if m in sys.modules)")
    r = subprocess.run([sys.executable, "-c", child, "stop"], input=json.dumps({"cwd": str(tmp_path)}),
                       capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "LAPIS_UNATTENDED"},
                       timeout=120)
    assert r.returncode == 0 and r.stdout == ""
    assert json.loads(r.stderr.strip().splitlines()[-1]) == {"code": 0, "heavy": []}


ANTIGRAVITY_CHILD = f"""
import json, sys
from lapis_design import hooks
code = hooks.main(["--plugin-version", hooks.__version__, "--host", "antigravity", sys.argv[1]])
sys.stdout.flush()
print(json.dumps({{"code": code, "heavy": sorted(m for m in {HEAVY + ("yaml", "jsonschema")!r} if m in sys.modules)}}), file=sys.stderr)
"""


@pytest.mark.parametrize("name, event, answered", [
    ("pre-write", lambda p: {"workspacePaths": [str(p)], "conversationId": "c", "toolCall": {
        "name": "write_to_file", "args": {"TargetFile": str(p / ".lapis/state/demo.json")}}}, True),
    ("pre-write", lambda p: {"workspacePaths": [str(p)], "conversationId": "c", "toolCall": {
        "name": "write_to_file", "args": {"TargetFile": str(p / "notes.md")}}}, False),
    ("stop", lambda p: {"workspacePaths": [str(p)], "conversationId": "c", "terminationReason": "NO_TOOL_CALL",
                        "fullyIdle": True, "transcriptPath": str(p / "t.jsonl")}, False),
])
def test_the_antigravity_hooks_run_before_every_file_edit_without_the_checks_or_yaml(tmp_path, name, event, answered):
    (tmp_path / ".lapis").mkdir()
    (tmp_path / "t.jsonl").write_text('{"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT"}\n', encoding="utf-8")
    r = subprocess.run([sys.executable, "-c", ANTIGRAVITY_CHILD, name], input=json.dumps(event(tmp_path)),
                       capture_output=True, text=True, timeout=120,
                       env={k: v for k, v in os.environ.items() if k != "LAPIS_UNATTENDED"})
    assert r.returncode == 0, r.stderr
    assert bool(r.stdout) == answered
    assert json.loads(r.stderr.strip().splitlines()[-1]) == {"code": 0, "heavy": []}
