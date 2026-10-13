"""The real browser, once per build: a second identical `render check` or `behavior check` does not start one, a changed
stylesheet does, and two identical calls made together share one run. (tests/test_check_runs.py covers the same
commands with a fake browser; this proves the cache against the real capture and the real probes.)"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from narrow_support import STUB, behavior, digest

pytestmark = pytest.mark.browser

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Cache</title>
<link rel="stylesheet" href="style.css"></head>
<body><main><h1>Cache</h1><p>One page, one stylesheet, one button.</p>
<button id="go" type="button" onclick="this.textContent='Done'">Go</button></main></body></html>
"""
CSS = "body{margin:0;font:16px/1.4 sans-serif}\nbutton{font:inherit}\n@media (max-width: 500px){ h1{font-size:20px} }\n"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "index.html").write_text(PAGE)
    (tmp_path / "site" / "style.css").write_text(CSS)
    (tmp_path / "stub.yaml").write_text(STUB)
    return tmp_path


def render(project: Path, *argv: str) -> subprocess.CompletedProcess:
    script = "import sys\nfrom lapis_design.render import main\nraise SystemExit(main(sys.argv[1:]))"
    return subprocess.run([sys.executable, "-c", script, "site/index.html", "--task", "t", "--width", "320", *argv],
                          capture_output=True, text=True, cwd=project, timeout=600,
                          env={**os.environ, "LAPIS_SIG_KEY_FILE": str(project / "sig.key")})


def log(project: Path) -> list[dict]:
    return [json.loads(line) for line in (project / ".lapis/telemetry/checks.jsonl").read_text().splitlines()]


def test_a_second_identical_render_does_not_open_a_browser_and_leaves_the_same_files(project):
    first = render(project)
    assert first.returncode == 0, first.stderr
    stored = digest(project / ".lapis/renders")
    again = render(project)
    assert again.returncode == 0, again.stderr
    assert digest(project / ".lapis/renders") == stored                                # byte-identical report and shots
    assert "cache miss" in first.stdout and "cache hit" in again.stdout
    rows = log(project)
    assert [row["cache"] for row in rows] == ["miss", "hit"] and rows[1]["output_chars"] == len(again.stdout)
    assert rows[1]["output_chars"] < 2500 and rows[0]["run_seconds"] > 0.5
    assert abs(rows[1]["run_seconds"] - rows[0]["run_seconds"]) < 0.01          # the hit reports the run it reused


def test_a_changed_stylesheet_or_state_is_captured_again(project):
    render(project)
    (project / "site" / "style.css").write_text(CSS + "p{color:#333}\n")
    changed = render(project)
    assert "cache miss" in changed.stdout, changed.stdout + changed.stderr
    queried = subprocess.run(
        [sys.executable, "-c", "import sys\nfrom lapis_design.render import main\nraise SystemExit(main(sys.argv[1:]))",
         (project / "site" / "index.html").as_uri() + "?state=open", "--task", "t", "--width", "320"],
        capture_output=True, text=True,
        cwd=project, env={**os.environ, "LAPIS_SIG_KEY_FILE": str(project / "sig.key")}, timeout=600)
    assert queried.returncode == 0 and "cache miss" in queried.stdout, queried.stdout + queried.stderr
    forced = render(project, "--fresh")
    assert "cache off: --fresh" in forced.stdout
    assert [row["cache"] for row in log(project)] == ["miss", "miss", "miss", "off"]


def test_two_identical_renders_started_together_open_one_browser(project):
    script = "import sys\nfrom lapis_design.render import main\nraise SystemExit(main(sys.argv[1:]))"
    env = {**os.environ, "LAPIS_SIG_KEY_FILE": str(project / "sig.key")}
    argv = [sys.executable, "-c", script, "site/index.html", "--task", "t", "--width", "320"]
    procs = [subprocess.Popen(argv, cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(2)]
    outputs = [p.communicate(timeout=600) for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outputs
    assert sorted(row["cache"] for row in log(project)) == ["join", "miss"]
    assert any("cache join" in out for out, _ in outputs)


def test_a_narrow_render_and_the_gate_still_want_the_full_one(project):
    first = render(project)
    assert first.returncode == 0
    assert (project / ".lapis/renders/t.narrow.json").is_file() and not (project / ".lapis/renders/t.json").exists()


def test_a_second_identical_behavior_check_runs_no_probe(project):
    first = behavior(project, "--probe", "console", "--context", "d")
    assert first.returncode == 0, first.stderr
    stored = digest(project / ".lapis/behavior")
    again = behavior(project, "--probe", "console", "--context", "d")
    assert again.returncode == 0 and digest(project / ".lapis/behavior") == stored
    assert "cache miss" in first.stdout and "cache hit" in again.stdout and "not selected (--probe)" in again.stdout
    (project / "stub.yaml").write_text(STUB + "# a different stub\n")
    assert "cache miss" in behavior(project, "--probe", "console", "--context", "d").stdout
    assert [row["cache"] for row in log(project)] == ["miss", "hit", "miss"]
