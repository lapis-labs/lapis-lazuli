"""Delegated work carries the rules (no reading check source, process ids only): the text a delegation prints, the hook that
refuses a kill by pattern, and the transcript scan that records what a subagent did and shows it in the owner block."""
from __future__ import annotations

import io
import json
import sys
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
    assert "- delegated work: rough worker C2 stopped a process by pattern" in text
    assert "- delegated work: rough worker C2 opened or listed the source of a check" in text and "2 times" in text
    clean = transcript(tmp_path / ".", ("Bash", {"command": "ls"}))
    assert cli_main(["worker", "check", "--task", TASK, "--root", str(project), "--transcript", str(clean)]) == 0
    assert "nothing in agent-abc.jsonl" in capsys.readouterr().out


def test_the_block_of_a_run_without_findings_says_nothing_of_workers(project):
    assert "delegated work" not in owner.block(project, TASK)[0]


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
    assert text.count("\n- ") == 3 and "pkill" in text and ".lapis/disputes/<task>.yaml" in text and "lapis_design/lint" in text
    assert text in diverge._how(TASK)
    assert "worker-rules.md" in slice_step.text(TASK)
