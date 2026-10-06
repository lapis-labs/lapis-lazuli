"""Antigravity's side of the hooks: `lapis-design antigravity-hook` (cli/lapis_design/antigravity.py) on events
shaped as agy 1.2.17 sends them, and the commands the lapis plugin's hooks.json runs.

Antigravity stops a PreToolUse tool call for a hook that exits non-zero, prints JSON it does not know (`{}` and
`{"systemMessage": ...}` included), or prints text that is not JSON (checked 2026-10-06), so every case here pins what
the hook prints: exactly the fields Antigravity reads, or nothing. A hook's working directory is the plugin's folder, which
the runs below use, so nothing may be found from the current directory."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "build"))

import manifests  # noqa: E402
from lapis_design import __version__, antigravity, gate  # noqa: E402

PRE_FIELDS = {"decision", "reason", "permissionOverrides", "overwrite"}      # what PreToolUse answers may carry
STOP_FIELDS = {"decision", "reason"}
WRITE_TOOLS = ["write_to_file", "replace_file_content", "multi_replace_file_content", "notebook_edit"]
OWNED = [".lapis/requirements", ".lapis/state", ".lapis/changes", ".lapis/owner"]


def project(tmp_path: Path, name: str = "site") -> Path:
    folder = tmp_path / name
    (folder / ".lapis").mkdir(parents=True)
    return folder


def pre_event(folder: Path, target, tool: str = "write_to_file", **extra) -> dict:
    args = {"toolAction": "Writing", "toolSummary": "Write"}
    args.update({"write_to_file": {"TargetFile": str(target), "CodeContent": "x", "Overwrite": True, "Description": "d"},
                 "replace_file_content": {"TargetFile": str(target), "TargetContent": "a", "ReplacementContent": "b",
                                          "Instruction": "i"},
                 "multi_replace_file_content": {"TargetFile": str(target), "ReplacementChunks": [], "Instruction": "i"},
                 "notebook_edit": {"NotebookPath": str(target), "Action": "add", "CellType": "code", "Content": "1"},
                 }.get(tool, {"TargetFile": str(target)}))
    return {"conversationId": "c-1", "workspacePaths": [str(folder)], "stepIdx": 2, "modelName": "gemini-3.8-flash-medium",
            "transcriptPath": str(folder / "t.jsonl"), "artifactDirectoryPath": str(folder / "brain"),
            "toolCall": {"name": tool, "args": args}, **extra}


PERSON = {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE", "content": "<USER_REQUEST>"}
PARENT = {"step_index": 0, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "status": "DONE",
          "content": "[Message] sender=2fac6f67 priority=MESSAGE_PRIORITY_HIGH hello"}


def transcript(folder: Path, first: dict = PERSON, name: str = "transcript_full.jsonl") -> Path:
    path = folder / "brain" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(first) + "\n" + json.dumps({"step_index": 1, "source": "MODEL"}) + "\n", encoding="utf-8")
    return path


def stop_event(folder: Path, reason: str = "NO_TOOL_CALL", idle: bool = True, conversation: str = "c-1",
               first: dict = PERSON) -> dict:
    return {"conversationId": conversation, "workspacePaths": [str(folder)], "executionNum": 0, "error": "",
            "terminationReason": reason, "fullyIdle": idle, "modelName": "gemini-3.8-flash-medium",
            "transcriptPath": str(transcript(folder, first))}


def run(tmp_path: Path, *args: str, event=None, raw: str | None = None, env: dict | None = None):
    plugin = tmp_path / "installed-plugin"
    plugin.mkdir(exist_ok=True)
    base = {k: v for k, v in os.environ.items() if k not in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR")}
    return subprocess.run([sys.executable, "-m", "lapis_design.cli", "antigravity-hook", *args],
                          input=raw if raw is not None else json.dumps(event), capture_output=True, text=True,
                          timeout=30, cwd=plugin, env={**base, **(env or {})})


def hook(tmp_path, name, event=None, *, version=__version__, env=None, raw=None):
    return run(tmp_path, "--plugin-version", version, name, event=event, raw=raw, env=env)


def answer(done, fields: set[str]) -> dict:
    assert done.returncode == 0, done.stderr          # a non-zero exit stops the tool call
    out = json.loads(done.stdout)
    assert len(done.stdout.splitlines()) == 1 and set(out) <= fields and out != {}
    assert out.get("decision") != "allow"             # allow would also skip the permission prompt
    return out


def silent(done):
    assert done.returncode == 0, done.stderr
    assert done.stdout == ""


@pytest.mark.parametrize("tool", WRITE_TOOLS)
@pytest.mark.parametrize("folder", OWNED)
def test_a_write_to_a_record_only_lapis_design_writes_is_denied_in_every_session(tmp_path, tool, folder):
    site = project(tmp_path)
    done = hook(tmp_path, "pre-write", pre_event(site, site / folder / "demo.json", tool))
    out = answer(done, PRE_FIELDS)
    assert out["decision"] == "deny" and f"{folder}/demo.json" in out["reason"] and done.stderr == ""


def test_the_deny_reaches_the_project_from_workspace_paths_not_the_plugins_working_directory(tmp_path):
    first, second = project(tmp_path, "one"), project(tmp_path, "two")
    first_only = pre_event(first, second / ".lapis/owner/demo.md", workspacePaths=[str(first), str(second)])
    assert answer(hook(tmp_path, "pre-write", first_only), PRE_FIELDS)["decision"] == "deny"
    # the write is outside every named workspace: nothing to guard
    elsewhere = pre_event(first, tmp_path / "elsewhere/.lapis/owner/demo.md")
    silent(hook(tmp_path, "pre-write", elsewhere))


@pytest.mark.parametrize("what", ["ordinary-file", "critic-report", "page-in-a-person's-session", "other-tool",
                                  "no-target", "wrong-argument", "no-workspace", "similar-name"])
def test_every_other_write_gets_no_answer(tmp_path, what):
    site = project(tmp_path)
    event = {
        "ordinary-file": pre_event(site, site / "notes.md"),
        "critic-report": pre_event(site, site / ".lapis/critic/demo.json"),
        "page-in-a-person's-session": pre_event(site, site / "index.html"),
        "other-tool": {**pre_event(site, site / ".lapis/owner/x.md"), "toolCall": {
            "name": "run_command", "args": {"CommandLine": "echo > .lapis/owner/x.md", "Cwd": str(site)}}},
        "no-target": {**pre_event(site, site / "x"), "toolCall": {"name": "write_to_file", "args": {}}},
        "wrong-argument": {**pre_event(site, site / "x"), "toolCall": {
            "name": "notebook_edit", "args": {"TargetFile": str(site / ".lapis/owner/x.md")}}},
        "no-workspace": {**pre_event(site, site / ".lapis/owner/x.md"), "workspacePaths": []},
        "similar-name": pre_event(site, site / ".lapis/requirements.md"),
    }[what]
    done = hook(tmp_path, "pre-write", event)
    silent(done)
    assert done.stderr == ""


@pytest.mark.parametrize("raw", ["", "not json", "[]", "null", '{"toolCall": "write_to_file"}'])
def test_input_that_is_not_an_event_gets_no_answer_and_exit_zero(tmp_path, raw):
    for name in ("pre-write", "stop"):
        silent(hook(tmp_path, name, raw=raw))


def test_an_unattended_run_is_refused_its_page_code_until_the_brief_exists(tmp_path):
    site = project(tmp_path)
    done = hook(tmp_path, "pre-write", pre_event(site, site / "index.html"), env={"LAPIS_UNATTENDED": "1"})
    out = answer(done, PRE_FIELDS)
    assert out["decision"] == "deny" and "brief record" in out["reason"] and "index.html" in out["reason"]
    record = json.loads((site / ".lapis/order" / f"{gate.folder_task(site)}.json").read_text(encoding="utf-8"))
    assert record["denied"] == {"step": "brief", "count": 1}
    # files under .lapis/ that the run is meant to write are never refused
    silent(hook(tmp_path, "pre-write", pre_event(site, site / ".lapis/answers/site.md"), env={"LAPIS_UNATTENDED": "1"}))


def test_the_exit_gate_continues_only_an_unattended_run_and_in_antigravitys_words(tmp_path):
    site = project(tmp_path)
    silent(hook(tmp_path, "stop", stop_event(site)))                       # a person at the keyboard decides when to stop
    done = hook(tmp_path, "stop", stop_event(site), env={"LAPIS_UNATTENDED": "1"})
    out = answer(done, STOP_FIELDS)
    assert out["decision"] == "continue"                                  # Claude Code's word, `block`, would not continue
    assert out["reason"].startswith(f"LapisLazuli: the procedure for task {gate.folder_task(site)} is not done")
    assert "Next step: brief" in out["reason"]


def test_the_gate_keeps_its_limits_across_hook_processes(tmp_path):
    site = project(tmp_path)
    env = {"LAPIS_UNATTENDED": "1"}
    results = [hook(tmp_path, "stop", stop_event(site), env=env) for _ in range(4)]
    assert [json.loads(r.stdout)["decision"] if r.stdout else None for r in results] == ["continue"] * 3 + [None]
    assert all(r.returncode == 0 for r in results)


@pytest.mark.parametrize("reason", ["USER_CANCELED", "ERROR", "MAX_INVOCATIONS", "MAX_TOKEN_BUDGET_EXCEEDED", "HALTED_STEP",
                                    "max_steps_exceeded", ""])
def test_a_run_that_ended_for_another_reason_than_the_agents_choice_is_never_continued(tmp_path, reason):
    site = project(tmp_path)
    silent(hook(tmp_path, "stop", stop_event(site, reason), env={"LAPIS_UNATTENDED": "1"}))
    assert not (site / ".lapis/gate").exists()


def test_a_subagent_that_stops_is_never_continued_with_the_procedure(tmp_path):
    # Stop fires for a subagent (the critic) too, in the same shape; its transcript opens with its parent's message
    site = project(tmp_path)
    silent(hook(tmp_path, "stop", stop_event(site, first=PARENT, conversation="sub-1"), env={"LAPIS_UNATTENDED": "1"}))
    assert not (site / ".lapis/gate").exists()
    # the person's conversation, in the same project, is still continued
    assert answer(hook(tmp_path, "stop", stop_event(site), env={"LAPIS_UNATTENDED": "1"}), STOP_FIELDS)


@pytest.mark.parametrize("how", ["missing-file", "no-path", "empty-file", "not-json", "not-an-object"])
def test_a_stop_whose_transcript_cannot_be_read_gets_no_answer(tmp_path, how):
    site = project(tmp_path)
    event = stop_event(site)
    path = Path(event["transcriptPath"])
    if how == "missing-file":
        path.unlink()
    elif how == "no-path":
        del event["transcriptPath"]
    else:
        path.write_text({"empty-file": "", "not-json": "oops\n", "not-an-object": "[1]\n"}[how], encoding="utf-8")
    silent(hook(tmp_path, "stop", event, env={"LAPIS_UNATTENDED": "1"}))
    assert not (site / ".lapis/gate").exists()


def test_a_stop_with_a_background_task_still_running_is_not_counted(tmp_path):
    site = project(tmp_path)
    silent(hook(tmp_path, "stop", stop_event(site, idle=False), env={"LAPIS_UNATTENDED": "1"}))
    assert not (site / ".lapis/gate").exists()


def test_the_documented_stop_reason_is_continued_too(tmp_path):
    # Antigravity's documentation names `model_stop`; agy 1.2.17 sends `NO_TOOL_CALL`
    site = project(tmp_path)
    out = answer(hook(tmp_path, "stop", stop_event(site, "model_stop"), env={"LAPIS_UNATTENDED": "1"}), STOP_FIELDS)
    assert out["decision"] == "continue"


def test_version_skew_prints_nothing_to_stdout_and_one_line_to_stderr_once_per_conversation(tmp_path):
    site = project(tmp_path)
    owned = pre_event(site, site / ".lapis/requirements/demo.json")
    first = hook(tmp_path, "pre-write", owned, version="9.9.9")
    silent(first)                                                          # the guard is skipped, so the write goes on
    assert first.stderr.splitlines() == [
        f"LapisLazuli hooks skipped: plugin 9.9.9, CLI {__version__}; update the CLI and plugins together."]
    again = hook(tmp_path, "pre-write", owned, version="9.9.9")
    silent(again)
    assert again.stderr == ""
    stopped = hook(tmp_path, "stop", stop_event(site), version="9.9.9", env={"LAPIS_UNATTENDED": "1"})
    silent(stopped)
    assert stopped.stderr == ""                                            # one claim for every hook of the conversation
    other = hook(tmp_path, "pre-write", {**owned, "conversationId": "c-2"}, version="9.9.9")
    silent(other)
    assert "plugin 9.9.9" in other.stderr
    assert not (site / ".lapis/gate").exists() and not (site / ".lapis/order").exists()
    assert not (tmp_path / "installed-plugin/.lapis").exists()             # the claim lives in the workspace


def test_a_notice_with_no_workspace_to_hold_the_claim_still_goes_to_stderr_and_writes_nothing(tmp_path):
    done = hook(tmp_path, "pre-write", {"conversationId": "c-1"}, version="9.9.9")
    silent(done)
    assert "plugin 9.9.9" in done.stderr
    assert not (tmp_path / "installed-plugin/.lapis").exists()


@pytest.mark.parametrize("args, said", [
    (("--plugin-version", __version__, "exit-plan"), "does not support 'exit-plan'"),
    (("--plugin-version", __version__, "session-start"), "does not support 'session-start'"),
    (("--plugin-version", __version__, "future-hook"), "does not support 'future-hook'"),
    (("--future-option", "stop"), "hook skipped"),
    (("-h",), "hook skipped"),
    ((), "hook skipped"),
])
def test_an_unsupported_hook_or_option_fails_open_to_stderr_under_antigravity(tmp_path, args, said):
    site = project(tmp_path)
    done = run(tmp_path, *args, event=pre_event(site, site / ".lapis/owner/x.md"))
    silent(done)
    assert said in done.stderr and len(done.stderr.splitlines()) == 1


def test_answers_are_only_what_antigravity_reads():
    deny = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": "why"}}
    assert antigravity._answer("pre-write", json.dumps(deny)) == ({"decision": "deny", "reason": "why"}, None)
    assert antigravity._answer("pre-write", json.dumps({"systemMessage": "line"})) == (None, "line")
    assert antigravity._answer("pre-write", json.dumps({**deny, "systemMessage": "line"})) == (
        {"decision": "deny", "reason": "why"}, "line")
    assert antigravity._answer("stop", json.dumps({"decision": "block", "reason": "go on"})) == (
        {"decision": "continue", "reason": "go on"}, None)
    assert antigravity._answer("stop", json.dumps({"systemMessage": "line"})) == (None, "line")
    for printed in ("", "{}", "not json", "[]", '{"decision": "allow"}', '{"hookSpecificOutput": {}}'):
        assert antigravity._answer("pre-write", printed) == (None, None)
        assert antigravity._answer("stop", printed) == (None, None)


def test_the_body_that_fails_is_swallowed_and_nothing_is_printed(capsys):
    import io

    def broken(stdin, stdout):
        raise RuntimeError("bug")

    out = io.StringIO()
    event = json.dumps({"toolCall": {"name": "write_to_file", "args": {"TargetFile": "/tmp/x/a.txt"}},
                        "workspacePaths": ["/tmp/x"]})
    assert antigravity.run("pre-write", io.StringIO(event), out, {"pre-write": broken}) == 0
    assert out.getvalue() == "" and "RuntimeError: bug" in capsys.readouterr().err


# --- the commands in hooks.json -----------------------------------------------------------------

@pytest.fixture
def commands():
    doc = yaml.safe_load((ROOT / "install/harnesses.yaml").read_text(encoding="utf-8"))
    plugin = next(p for p in doc["plugins"] if p["name"] == "lapis")
    hooks = manifests.antigravity_hooks_json(plugin, __version__)
    return {"stop": hooks["lapis-stop"]["Stop"][0]["command"],
            "pre-write": hooks["lapis-pre-write"]["PreToolUse"][0]["hooks"][0]["command"]}


def bin_dir(tmp_path: Path, runner: str | None) -> Path:
    folder = tmp_path / "bin"
    folder.mkdir()
    if runner is not None:
        stub = folder / "lapis-design"
        stub.write_text(f"#!{sys.executable}\n{runner}", encoding="utf-8")
        stub.chmod(0o755)
    return folder


posix_only = pytest.mark.skipif(os.name == "nt", reason="the commands are read by sh here; cmd.exe is not exercised")


# what `lapis-design` of a release before the Antigravity plugins does with the subcommand: argparse rejects it on stderr
# with status 2 (the stub is that parser, and the first test below checks the premise), where the older `lapis-design-hook`
# would have printed {"systemMessage": ...} on stdout, which Antigravity fails a PreToolUse tool call for
OLD_CLI = """
import argparse
ap = argparse.ArgumentParser(prog="lapis-design")
ap.add_argument("--version", action="version", version="lapis-design 0.2.0")
sub = ap.add_subparsers(dest="command", required=True)
for name in ("plan", "rights", "render", "behavior", "stub", "slop", "release", "draft", "critic", "handoff", "skill",
             "requirements", "next", "hook", "mcp"):
    sub.add_parser(name)
ap.parse_args()
"""


@posix_only
def test_a_cli_older_than_the_plugin_prints_nothing_to_stdout_and_the_command_exits_zero(tmp_path, commands):
    env = {"PATH": str(bin_dir(tmp_path, OLD_CLI)), "HOME": str(tmp_path)}
    site = project(tmp_path)
    event = json.dumps(pre_event(site, site / ".lapis/requirements/demo.json"))
    bare = subprocess.run(["lapis-design", "antigravity-hook", "pre-write"], input=event, capture_output=True, text=True,
                          env=env, timeout=30)
    assert bare.returncode == 2 and bare.stdout == "" and "invalid choice: 'antigravity-hook'" in bare.stderr
    for name, command in commands.items():
        done = subprocess.run(command, shell=True, input=event, capture_output=True, text=True, env=env, timeout=30)
        assert done.returncode == 0, (name, done.stderr)
        assert done.stdout == "", (name, done.stdout)                 # nothing for Antigravity to reject: the write goes on
        assert "invalid choice" in done.stderr                        # and the reason is in the hook's stderr (the CLI log)
        assert not (site / ".lapis/hooks").exists() and not (site / ".lapis/gate").exists()


@posix_only
@pytest.mark.parametrize("runner", [None, "import sys; sys.exit(3)", "import sys; print('{'); sys.exit(1)"],
                         ids=["runner-missing", "runner-exits-3", "runner-crashes-after-output"])
def test_a_runner_that_is_missing_or_fails_never_stops_the_agent(tmp_path, commands, runner):
    env = {"PATH": str(bin_dir(tmp_path, runner)), "HOME": str(tmp_path)}
    for name, command in commands.items():
        done = subprocess.run(command, shell=True, input="{}", capture_output=True, text=True, env=env, timeout=30)
        assert done.returncode == 0, (name, done.stderr)


@posix_only
def test_the_command_runs_the_guard_end_to_end(tmp_path, commands):
    site = project(tmp_path)
    runner = ("from lapis_design.cli import main\nimport sys\nsys.exit(main())\n")
    env = {**os.environ, "PATH": f"{bin_dir(tmp_path, runner)}{os.pathsep}{os.environ['PATH']}"}
    env.pop("LAPIS_UNATTENDED", None)
    owned = subprocess.run(commands["pre-write"], shell=True, capture_output=True, text=True, env=env, timeout=30,
                           cwd=tmp_path, input=json.dumps(pre_event(site, site / ".lapis/changes/demo.jsonl")))
    assert answer(owned, PRE_FIELDS)["decision"] == "deny"
    plain = subprocess.run(commands["pre-write"], shell=True, capture_output=True, text=True, env=env, timeout=30,
                           cwd=tmp_path, input=json.dumps(pre_event(site, site / "notes.md")))
    silent(plain)
