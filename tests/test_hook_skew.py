"""Plugin/CLI skew must never become a Stop continuation or deny every write."""
from __future__ import annotations

import importlib.util
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


@pytest.mark.parametrize("event", ["Stop", "PreToolUse"])
def test_updated_plugin_with_legacy_cli_does_not_signal_a_block(tmp_path, event):
    # The 0.2.0 CLI supports neither stop nor pre-write. Its argparse error is
    # exit 2, which both command-hook harnesses interpret as a control decision.
    legacy = tmp_path / "legacy.py"
    legacy.write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser(prog='lapis-design')\n"
        "p.add_argument('command', choices=['hook'])\n"
        "p.add_argument('name', choices=['exit-plan', 'session-start'])\n"
        "p.parse_args()\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if os.name == "nt":
        (bin_dir / "lapis-design.cmd").write_text(
            f'@"{sys.executable}" "{legacy}" %*\r\n', encoding="utf-8")
    else:
        stub = bin_dir / "lapis-design"
        stub.write_text(f"#!{sys.executable}\n" + legacy.read_text(encoding="utf-8"), encoding="utf-8")
        stub.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir)}
    name = "stop" if event == "Stop" else "pre-write"
    old = subprocess.run(f"lapis-design hook {name}", shell=True, env=env,
                         input="{}", text=True, capture_output=True, timeout=10)
    assert old.returncode == 2 and "invalid choice" in old.stderr

    doc = yaml.safe_load((ROOT / "install/harnesses.yaml").read_text(encoding="utf-8"))
    generated = manifests.emit(doc, "0.3.0", "MIT AND CC-BY-4.0")
    command = json.loads(generated["plugins/lapis/hooks/hooks.json"])["hooks"][event][0]["hooks"][0]["command"]
    updated = subprocess.run(command, shell=True, env=env, input="{}", text=True,
                             capture_output=True, timeout=10)
    # A failed lookup is a visible, non-blocking hook error, not exit 2; no
    # stdout decision can turn the failure into another Stop continuation.
    assert updated.returncode != 2, updated.stderr
    assert updated.stdout == "" and updated.stderr.strip()


def run_hook(tmp_path, *args, session="s", module="lapis_design.hooks"):
    event = {"session_id": session, "cwd": str(tmp_path), "hook_event_name": "Stop",
             "tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "index.html"),
                                                  "plan": "```yaml lapis-plan\nnot: [valid\n```"}}
    return subprocess.run([sys.executable, "-m", module, *args], input=json.dumps(event),
                          capture_output=True, text=True, timeout=30,
                          env={**os.environ, "LAPIS_UNATTENDED": "1", "CLAUDE_PROJECT_DIR": str(tmp_path)})


@pytest.mark.parametrize("plugin_version", ["0.1.0", "99.0.0"])
def test_version_skew_warns_once_per_session_and_never_runs_a_gate(tmp_path, plugin_version):
    from lapis_design import __version__

    first = run_hook(tmp_path, "--plugin-version", plugin_version, "session-start")
    assert first.returncode == 0
    notice = json.loads(first.stdout)
    assert set(notice) == {"systemMessage"}
    assert f"plugin {plugin_version}, CLI {__version__}" in notice["systemMessage"]
    assert len(first.stdout.splitlines()) == 1
    for name in ("stop", "pre-write", "exit-plan", "future-hook"):
        later = run_hook(tmp_path, "--plugin-version", plugin_version, name)
        assert later.returncode == 0 and later.stdout == ""
    assert not (tmp_path / ".lapis/gate").exists()
    assert not (tmp_path / ".lapis/order").exists()
    another = run_hook(tmp_path, "--plugin-version", plugin_version, "stop", session="another")
    assert another.returncode == 0 and json.loads(another.stdout) == notice


@pytest.mark.parametrize("args", [("future-hook",), ("stop", "--future-option"), ()])
@pytest.mark.parametrize("module", ["lapis_design.hooks", "lapis_design.cli"])
def test_unsupported_hook_interface_fails_open_with_one_visible_line(tmp_path, args, module):
    prefix = ("hook",) if module == "lapis_design.cli" else ()
    done = run_hook(tmp_path, *prefix, *args, module=module)
    assert done.returncode == 0, done.stderr
    notice = json.loads(done.stdout)
    assert set(notice) == {"systemMessage"} and "hook skipped" in notice["systemMessage"]
    assert len(done.stdout.splitlines()) == 1


@pytest.mark.parametrize("name", ["stop", "pre-write", "exit-plan"])
def test_matching_version_still_enforces_the_actual_hook(tmp_path, name):
    from lapis_design import __version__

    done = run_hook(tmp_path, "--plugin-version", __version__, name)
    assert done.returncode == 0, done.stderr
    answer = json.loads(done.stdout)
    if name == "stop":
        assert answer["decision"] == "block"
    elif name == "pre-write":
        assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    else:
        assert answer["hookSpecificOutput"]["decision"]["behavior"] == "deny"


def test_hermes_skew_notice_is_visible_without_context_or_a_followup_turn(tmp_path, capsys):
    import build

    doc = yaml.safe_load((ROOT / "install/harnesses.yaml").read_text(encoding="utf-8"))
    out = next(o for o in doc["outputs"] if o["id"] == "hermes-plugin")
    files = build.Build(ROOT, doc, "99.0.0").hermes_plugin(out)
    plugin_path = tmp_path / "hermes.py"
    plugin_path.write_text(files[out["path"] + "__init__.py"], encoding="utf-8")
    spec = importlib.util.spec_from_file_location("skew_hermes", plugin_path)
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    # Launch the actual hook entry function through this environment's Python,
    # not an echoing fake executable. The plugin still supplies its built version.
    plugin.COMMAND = [sys.executable, "-m", "lapis_design.hooks", *plugin.COMMAND[1:]]
    event = {"session_id": "hermes-session", "cwd": str(tmp_path)}
    assert plugin.pre_llm_call(is_first_turn=True, **event) is None
    notice = capsys.readouterr()
    assert notice.out == "" and len(notice.err.splitlines()) == 1
    assert "plugin 99.0.0" in notice.err
    assert plugin.pre_llm_call(is_first_turn=True, **event) is None
    assert plugin.pre_llm_call(is_first_turn=False, **event) is None
    assert capsys.readouterr().err == ""
