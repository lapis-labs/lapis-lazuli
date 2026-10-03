"""A browser that is missing or cannot start ends `render check` and `behavior check` with one line of ours.

Run in subprocesses against a Playwright browser folder the test controls, so no real browser is needed and
the message that Playwright itself would print is what the check replaces.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from lapis_design import attempts, browser_install_command

STUB = Path(__file__).resolve().parents[1] / "src" / "shared" / "behavior" / "example.stub.yaml"
URL = "http://127.0.0.1:9/"       # nothing listens here; the checks must fail at the browser, before any request

LAUNCH = """
from playwright.sync_api import Error, sync_playwright
with sync_playwright() as playwright:
    try:
        playwright.chromium.launch()
    except Error as error:
        print(str(error).splitlines()[0])
"""

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the stand-in browser is a shell script")


def environment(tmp_path: Path, *, stand_in: bool) -> dict[str, str]:
    """A browser folder with nothing in it, or with a stand-in executable at the path Playwright will launch."""
    home = tmp_path / "ms-playwright"
    home.mkdir()
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(home), "LAPIS_SIG_KEY_FILE": str(tmp_path / "sig.key")}
    if stand_in:
        first = subprocess.run([sys.executable, "-c", LAUNCH], env=env, capture_output=True, text=True, timeout=60).stdout
        executable = Path(re.search(r"Executable doesn't exist at (.+)", first).group(1).strip())
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\nexit 1\n")                   # a browser a sandbox lets exist but not run
        executable.chmod(0o755)
    return env


def run_check(command: str, env: dict[str, str], tmp_path: Path) -> subprocess.CompletedProcess:
    argv = ({"render": ["--out", str(tmp_path / "out.json")],
             "behavior_check": ["--task", "t", "--stub", str(STUB), "--out", str(tmp_path / "out.json")]}[command])
    script = f"import sys\nfrom lapis_design.{command} import main\nraise SystemExit(main(sys.argv[1:]))"
    return subprocess.run([sys.executable, "-c", script, URL, *argv], env=env, cwd=tmp_path, capture_output=True,
                          text=True, timeout=120)


@pytest.mark.parametrize("command, prog", [("render", "render check"), ("behavior_check", "behavior check")])
def test_a_missing_browser_names_the_command_that_installs_it_and_nothing_else(tmp_path: Path, command: str, prog: str):
    result = run_check(command, environment(tmp_path, stand_in=False), tmp_path)
    assert result.returncode == 2 and result.stdout == ""
    assert result.stderr == (f"{prog}: the browser is not installed; run {browser_install_command()} "
                             "and run the check again\n")
    assert not (tmp_path / "out.json").exists()


@pytest.mark.parametrize("command, prog", [("render", "render check"), ("behavior_check", "behavior check")])
def test_a_browser_that_cannot_start_says_so_in_one_line_without_launch_flags(tmp_path: Path, command: str, prog: str):
    result = run_check(command, environment(tmp_path, stand_in=True), tmp_path)
    assert result.returncode == 2 and result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert result.stderr.startswith(f"{prog}: the browser is installed but could not start (BrowserType.launch: ")
    assert "not run" in result.stderr and "--disable-" not in result.stderr and "playwright install" not in result.stderr
    assert not (tmp_path / "out.json").exists()


def run_task(command: str, env: dict[str, str], tmp_path: Path, *flags: str) -> subprocess.CompletedProcess:
    """The check as an agent runs it for a task: reports go to the task's own paths under the working folder."""
    argv = {"render": ["--task", "demo"], "behavior_check": ["--task", "demo", "--stub", str(STUB)]}[command]
    script = f"import sys\nfrom lapis_design.{command} import main\nraise SystemExit(main(sys.argv[1:]))"
    return subprocess.run([sys.executable, "-c", script, URL, *argv, *flags], env=env, cwd=tmp_path,
                          capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("stand_in", [False, True], ids=["not-installed", "cannot-start"])
@pytest.mark.parametrize("command, step", [("render", "render"), ("behavior_check", "behavior")])
def test_a_full_run_that_cannot_start_the_browser_records_the_failure_itself(tmp_path: Path, command: str, step: str,
                                                                              stand_in: bool):
    result = run_task(command, environment(tmp_path, stand_in=stand_in), tmp_path)
    assert result.returncode == 2
    record = json.loads((tmp_path / ".lapis" / "attempts" / "demo" / f"{step}.json").read_text())
    assert record["failure_kind"] == "environment" and record["exit"] == 2
    assert record["task"] == "demo" and record["step"] == step
    assert result.stderr.split(": ", 1)[1].strip() == record["reason"]       # the same one line the check printed
    assert record["command"][:3] == ["lapis-design", step.split("_")[0], "check"] and "--task" in record["command"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", record["at"])
    assert attempts.read(tmp_path, "demo", step) == record


@pytest.mark.parametrize("command, flags", [
    ("render", ["--width", "390"]),
    ("render", ["--out", "elsewhere.json"]),
    ("behavior_check", ["--probe", "console"]),
    ("behavior_check", ["--context", "d"]),
    ("behavior_check", ["--out", "elsewhere.json"]),
])
def test_a_run_that_is_not_the_step_the_gate_reads_leaves_no_record(tmp_path: Path, command: str, flags: list[str]):
    result = run_task(command, environment(tmp_path, stand_in=False), tmp_path, *flags)
    assert result.returncode == 2
    assert not (tmp_path / ".lapis" / "attempts").exists()


def test_an_input_error_is_not_an_environment_failure_and_leaves_no_record(tmp_path: Path):
    # a stub that is not valid stops the check before the browser: an input to fix, not an environment
    stub = tmp_path / "stub.yaml"
    stub.write_text("version: 99\n", encoding="utf-8")
    script = "import sys\nfrom lapis_design.behavior_check import main\nraise SystemExit(main(sys.argv[1:]))"
    result = subprocess.run([sys.executable, "-c", script, URL, "--task", "demo", "--stub", str(stub)],
                            env=environment(tmp_path, stand_in=False), cwd=tmp_path, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 2 and "browser" not in result.stderr
    assert not (tmp_path / ".lapis" / "attempts").exists()
