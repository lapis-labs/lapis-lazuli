"""Delegated work carries the rules (no reading check source, process ids only): the text a delegation prints, the hook that
refuses a kill by pattern, and the transcript scan that records what a subagent did and shows it in the owner block."""
from __future__ import annotations

import io
import json
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

from lapis_design import diverge, hooks, owner, slice_step, workers
from lapis_design.cli import main as cli_main
from procedure_support import TASK, make_project

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "build"))

import manifests  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    return make_project(tmp_path)


KILLS = ['pkill -f "claude -p"', "killall node", "sudo pkill chrome", "cd app && pkill -f vite", "echo go; killall python",
         "pgrep -f vite | xargs kill", "kill -9 $(pgrep node)", "lsof -ti :3000 | xargs kill -9", "ps aux | awk '{print $2}' | xargs kill"]
SAFE = ["kill 4242", "kill $(cat .lapis/logs/t.preview.pid)", "grep -rn pkill docs", "echo pkill is banned", "lapis-design preview stop",
        "ps aux | grep vite", "pgrep -f vite"]


@pytest.mark.parametrize("command", KILLS)
def test_a_command_that_stops_a_process_by_pattern_is_found(command):
    assert workers.pattern_kill(command)


@pytest.mark.parametrize("command", SAFE)
def test_a_command_that_stops_a_recorded_process_or_only_looks_is_not(command):
    assert workers.pattern_kill(command) is None


def bash(project: Path, command: str, tool: str = "Bash") -> dict:
    return {"cwd": str(project), "tool_name": tool, "tool_input": {"command": command}}


def run_pre_write(event: dict) -> dict | None:
    out = io.StringIO()
    assert hooks.pre_write(io.StringIO(json.dumps(event)), out) == 0
    return json.loads(out.getvalue()) if out.getvalue() else None


def test_the_pre_write_hook_refuses_a_kill_by_pattern_in_a_project_with_a_plan_and_lets_a_pid_kill_through(project, tmp_path_factory):
    refusal = run_pre_write(bash(project, 'pkill -f "claude -p"'))["hookSpecificOutput"]
    assert refusal["permissionDecision"] == "deny" and "stops a process by pattern" in refusal["permissionDecisionReason"]
    assert ".lapis/logs/<task>.<step>.pid" in refusal["permissionDecisionReason"]
    assert run_pre_write(bash(project, "kill 4242")) is None
    assert run_pre_write(bash(project, "pkill -f vite", tool="bash"))                       # the extension's lower-case tool name
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    assert run_pre_write(bash(elsewhere, "pkill -f vite")) is None                         # no plan: not a lapis project


def transcript(folder: Path, *calls: tuple[str, dict]) -> Path:
    """A subagent transcript as Claude Code writes it: one JSON line per message, tool calls as `tool_use` blocks."""
    lines = [json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "working"}, {"type": "tool_use", "id": f"t{n}", "name": name, "input": args}]}})
        for n, (name, args) in enumerate(calls)]
    path = folder / "agent-abc.jsonl"
    path.write_text("\n".join(lines) + "\nnot json\n", encoding="utf-8")
    return path


BROKE = (("Bash", {"command": "ls"}),
         ("Bash", {"command": "pkill -f 'render check'"}),
         ("Read", {"file_path": "/usr/lib/python3/site-packages/lapis_design/lint/rules.py"}),
         ("Grep", {"pattern": "text_sig", "path": "cli/lapis_design/behavior_check"}),
         ("Read", {"file_path": "index.html"}))


def test_a_transcript_that_kills_by_pattern_or_reads_check_source_is_scanned(project, tmp_path):
    found = workers.scan(transcript(tmp_path, *BROKE))
    assert [(f["kind"], f["tool"]) for f in found] == [("pattern-kill", "Bash"), ("checker-source", "Read"), ("checker-source", "Grep")]
    assert "pkill -f 'render check'" in found[0]["evidence"] and "lapis_design/lint/rules.py" in found[1]["evidence"]
    assert workers.scan(transcript(tmp_path, ("Bash", {"command": "ls"}), ("Read", {"file_path": "index.html"}))) == []


def test_worker_check_records_the_findings_once_and_the_owner_block_lists_them(project, tmp_path, capsys):
    file = transcript(tmp_path, *BROKE)
    args = ["worker", "check", "--task", TASK, "--root", str(project), "--transcript", str(file), "--agent", "rough worker C2"]
    assert cli_main(args) == 1
    assert cli_main(args) == 1
    record = json.loads((project / f".lapis/state/{TASK}.workers.json").read_text(encoding="utf-8"))
    assert len(record["findings"]) == 3 and {f["agent"] for f in record["findings"]} == {"rough worker C2"}
    text, _ = owner.block(project, TASK)
    assert "- worker rules: rough worker C2 stopped a process by pattern" in text
    assert "- worker rules: rough worker C2 read the source of `lapis-design`" in text and "2 times" in text
    assert "(module behavior_check, lint; path ×2)" in text
    clean = transcript(tmp_path / ".", ("Bash", {"command": "ls"}))
    assert cli_main(["worker", "check", "--task", TASK, "--root", str(project), "--transcript", str(clean)]) == 0
    assert "nothing in agent-abc.jsonl" in capsys.readouterr().out


def test_the_block_of_a_run_without_findings_says_nothing_of_workers(project):
    assert "worker rules" not in owner.block(project, TASK)[0]


def test_subagent_stop_reads_the_subagents_own_transcript_and_records_what_it_found(project, tmp_path):
    file = transcript(tmp_path, *BROKE)
    event = {"cwd": str(project), "hook_event_name": "SubagentStop", "agent_type": "rough-worker",
             "agent_transcript_path": str(file), "transcript_path": str(tmp_path / "main.jsonl")}
    out = io.StringIO()
    assert hooks.subagent_stop(io.StringIO(json.dumps(event)), out) == 0
    said = json.loads(out.getvalue())["systemMessage"]
    assert "3 findings" in said and f".lapis/state/{TASK}.workers.json" in said
    assert "rough-worker" in (project / f".lapis/state/{TASK}.workers.json").read_text(encoding="utf-8")
    again = io.StringIO()
    hooks.subagent_stop(io.StringIO(json.dumps(event)), again)
    assert again.getvalue() == ""                                                           # nothing new to say
    quiet = io.StringIO()
    hooks.subagent_stop(io.StringIO(json.dumps({**event, "cwd": str(tmp_path)})), quiet)
    assert quiet.getvalue() == ""                                                           # no project: nothing recorded


def test_the_subagent_hook_is_named_and_a_hook_without_a_subagent_transcript_does_nothing(project):
    assert "subagent-stop" in hooks.HOOKS
    out = io.StringIO()
    hooks.subagent_stop(io.StringIO(json.dumps({"cwd": str(project)})), out)
    assert out.getvalue() == ""


def test_the_manifests_register_the_bash_matcher_in_the_shared_file_and_subagent_stop_inline_for_claude_code_only():
    doc = yaml.safe_load((ROOT / "install/harnesses.yaml").read_text(encoding="utf-8"))
    generated = manifests.emit(doc, "0.3.0", "MIT AND CC-BY-4.0")
    shared = json.loads(generated["plugins/lapis/hooks/hooks.json"])["hooks"]
    assert shared["PreToolUse"][0]["matcher"] == "Write|Edit|MultiEdit|apply_patch|Bash" and "SubagentStop" not in shared
    inline = json.loads(generated["plugins/lapis/.claude-plugin/plugin.json"])["hooks"]
    assert inline["SubagentStop"][0]["hooks"][0]["command"].endswith("subagent-stop")


def test_the_rules_are_the_lines_a_delegation_prints_and_each_delegation_prints_them(project):
    text = workers.rules()
    assert text.count("\n- ") == 4 and "pkill" in text and ".lapis/disputes/<task>.yaml" in text and "lapis_design/" in text and "inspect.getsource" in text
    assert "lapis-design extract show --task <task>" in text and "open the source at its lines" in text
    assert text in diverge._how(TASK)
    assert "worker-rules.md" in slice_step.text(TASK)


# --- every way of reading the source of lapis-design, and none of running it ----------------------

AGY = ROOT / "tests" / "fixtures" / "antigravity" / "transcript_full.jsonl"
MODULES = sorted(p.stem if p.suffix else p.name for p in Path(workers.__file__).parent.iterdir()
                 if (p.suffix == ".py" and p.stem != "__init__") or (p.is_dir() and (p / "__init__.py").exists()))


def reads(text: str) -> set[tuple[str, str]]:
    return {(r["module"], r["how"]) for r in workers.source_reads(text)}


def test_an_antigravity_transcript_that_reads_lapis_design_source_in_every_way_is_found_with_the_module_and_how():
    found = workers.scan(AGY)
    assert {(f["module"], f["how"]) for f in found if f["kind"] == "checker-source"} == {
        ("brief", "getsource"), ("next_step", "import"), ("requirements", "import"), ("lapis_design", "package-dir"),
        ("direction", "path"), ("owner", "import")}
    by_tool = {(f["tool"], f["module"]): f for f in found if f["kind"] == "checker-source"}
    assert "inspect.getsource(brief)" in by_tool[("run_command", "brief")]["evidence"]
    assert by_tool[("view_file", "direction")]["evidence"].endswith("lapis_design/direction.py")
    assert by_tool[("write_to_file", "owner")]["how"] == "import"        # a script that imports it counts when it is written
    kills = [f for f in found if f["kind"] == "pattern-kill"]
    assert [(f["tool"], f["evidence"]) for f in kills] == [("run_command", 'pkill -f "render check"')]   # on a second line


@pytest.mark.parametrize("command", [
    "lapis-design next --task demo --json", "lapis-design --help", "lapis-design next --help", "lapis-design skill loaded --help",
    "lazuli --help", "lazuli ls", "python3 -m lapis_design.cli next --task demo", "uv run --no-sync python -m lapis_design.workers",
    "head -n 5 $(which lapis-design)", "/Users/a/.local/share/uv/tools/lapis-design/bin/python build.py",
    "cat /Users/a/.gemini/config/plugins/lapis/skills/lapis/SKILL.md", "cat site-packages/lapis_design-0.3.0.dist-info/METADATA",
    "echo the lapis_design package"])
def test_running_the_cli_or_reading_its_guides_is_not_reading_its_source(command):
    assert workers.source_reads(command) == []
    assert workers.scan_rows([{"tool_calls": [{"name": "run_command", "args": {"CommandLine": command}}]}]) == []


@pytest.mark.parametrize("module", MODULES)
def test_every_internal_module_is_found_by_import_by_path_and_by_getsource(module):
    assert reads(f"python -c 'from lapis_design import {module}'") == {(module, "import")}
    assert reads(f"python -c 'from lapis_design.{module} import x'") == {(module, "import")}
    assert reads(f"python -c 'import lapis_design.{module} as m; print(m)'") == {(module, "import")}
    assert reads(f"python -c 'import inspect, lapis_design.{module} as m; inspect.getsource(m)'") == {(module, "getsource")}
    assert reads(f"cat /usr/lib/python3/site-packages/lapis_design/{module}.py") == {(module, "path")}


@pytest.mark.parametrize("text, expected", [
    ("import lapis_design", {("lapis_design", "import")}),
    ("import os, lapis_design.brief", {("brief", "import")}),
    ("from lapis_design import brief, waiting as w", {("brief", "import"), ("waiting", "import")}),
    ("from lapis_design import (\n  brief,\n)", {("lapis_design", "import")}),
    ("python -c \"import lapis_design; print(lapis_design.__file__)\"", {("lapis_design", "getsource")}),
    ("python -c \"import lapis_design; lapis_design.brief.problem\"", {("lapis_design", "import"), ("brief", "import")}),
    ("importlib.import_module('lapis_design.brief')", {("brief", "import")}),
    ("ls ~/.local/share/uv/tools/lapis-design/lib/python3.13/site-packages/lapis_design", {("lapis_design", "package-dir")}),
    ("grep -rn x site-packages/lapis_design/", {("lapis_design", "package-dir")}),
    ("cat cli/lapis_design/behavior_check/session.py", {("behavior_check", "path")}),
    ("cat cli/lapis_design/lint/rules.py cli/lapis_design/render/extract.py", {("lint", "path"), ("render", "path")}),
])
def test_the_ways_a_call_reads_source_are_named(text, expected):
    assert reads(text) == expected


def test_worker_check_on_an_antigravity_transcript_counts_the_findings_with_module_and_how(project, capsys):
    args = ["worker", "check", "--task", TASK, "--root", str(project), "--transcript", str(AGY), "--agent", "agy worker"]
    assert cli_main(args) == 1
    assert "checker-source (getsource, brief)" in capsys.readouterr().err
    recorded = json.loads((project / f".lapis/state/{TASK}.workers.json").read_text(encoding="utf-8"))["findings"]
    assert Counter(f["kind"] for f in recorded) == {"checker-source": 6, "pattern-kill": 1}
    text, _ = owner.block(project, TASK)
    assert "module brief, direction, lapis_design, next_step, owner, requirements; getsource ×1, import ×3, package-dir ×1, path ×1" in text
