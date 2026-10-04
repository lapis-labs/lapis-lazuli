"""A narrowed run (`render check --width`; `behavior check --probe`, `--context`, `--box`, `--limit`) writes beside the
full report, never over it."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from narrow_support import behavior, digest, make_project, render


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return make_project(tmp_path)


@pytest.mark.browser
def test_a_narrowed_render_writes_beside_the_full_extract_and_leaves_it_alone(project):
    full = render(project)
    assert full.returncode == 0, full.stderr
    renders = project / ".lapis" / "renders"
    assert (renders / "t.json").is_file() and (renders / "t.shots").is_dir()
    before = digest(renders)

    narrow = render(project, "--width", "390")
    assert narrow.returncode == 0, narrow.stderr
    assert str(Path(".lapis/renders/t.narrow.json")) in narrow.stdout
    document = json.loads((renders / "t.narrow.json").read_text())
    assert {vp["width"] for vp in document["viewports"]} == {390}
    shots = {vp["screenshot"] for vp in document["viewports"]}
    assert shots and all(name.startswith("t.narrow.shots/") for name in shots)
    assert all((renders / name).is_file() for name in shots)
    after = digest(renders)
    assert {name: value for name, value in after.items() if name in before} == before     # the full extract and shots
    assert set(after) - set(before) == {"t.narrow.json", *shots}                           # only the narrowed files are new


@pytest.mark.browser
def test_a_narrowed_behavior_check_writes_beside_the_full_session_and_leaves_it_alone(project):
    sessions = project / ".lapis" / "behavior"
    sessions.mkdir(parents=True)
    (sessions / "t.json").write_text('{"kept": "the full session"}\n')
    before = digest(sessions)

    result = behavior(project, "--probe", "console", "--context", "d")
    assert result.returncode == 0, result.stderr
    assert str(Path(".lapis/behavior/t.narrow.json")) in result.stdout
    assert "not selected (--probe)" in result.stdout and "skipped" in result.stdout    # what the run left out is said
    assert json.loads((sessions / "t.narrow.json").read_text())["source"]["task"] == "t"
    assert {name: value for name, value in digest(sessions).items() if name in before} == before
    assert set(digest(sessions)) == {"t.json", "t.narrow.json"}


def test_the_printed_coverage_names_each_partial_and_skipped_probe_with_its_reason():
    from lapis_design.behavior_check import _coverage_lines
    coverage = [{"probe": "controls", "status": "ran", "contexts": ["m"]},
                {"probe": "dialogs", "status": "not-applicable", "contexts": ["m"]},
                {"probe": "flows", "status": "partial", "reason": "m/start-trial: abandoned (goal not reached)"},
                {"probe": "pointer", "status": "partial", "reason": "m/start-trial: abandoned (goal not reached)"},
                {"probe": "scroll", "status": "partial", "reason": "d/space: need 7083px remaining, have 3924px"},
                {"probe": "motion", "status": "skipped", "reason": "not selected (--probe)"}]
    assert _coverage_lines(coverage) == [
        "  coverage: 1 ran, 3 partial, 1 skipped, 1 not-applicable",
        "  partial flows, pointer — m/start-trial: abandoned (goal not reached)",
        "  partial scroll — d/space: need 7083px remaining, have 3924px",
        "  skipped motion — not selected (--probe)"]


@pytest.mark.browser
def test_a_full_behavior_check_keeps_the_task_path(project):
    # No probe runs (a full run takes minutes); what is observed is where an unnarrowed run writes.
    script = ("import sys\nfrom lapis_design.behavior_check import main, probes\nprobes.PROBES = ()\n"
              "raise SystemExit(main(sys.argv[1:]))")
    result = subprocess.run([sys.executable, "-c", script, "site/index.html", "--task", "t", "--stub", "stub.yaml"],
                            capture_output=True, text=True, cwd=project, timeout=600)
    assert result.returncode == 0, result.stderr
    assert (project / ".lapis" / "behavior" / "t.json").is_file()
    assert not (project / ".lapis" / "behavior" / "t.narrow.json").exists()


@pytest.mark.parametrize("flags", [["--width", "390"], ["--width", "320", "--width", "1440"]])
def test_a_narrowed_render_refuses_to_write_the_full_extract_path(project, flags):
    for out in (".lapis/renders/t.json", "./.lapis/renders/../renders/t.json", str(project / ".lapis/renders/t.json")):
        result = render(project, *flags, "--out", out)
        assert result.returncode == 2
        assert "--width" in result.stderr and ".lapis/renders/t.narrow.json" in result.stderr
    assert not (project / ".lapis").exists()


@pytest.mark.parametrize("flags", [["--probe", "console"], ["--context", "d"],
                                   ["--probe", "console", "--context", "d"]])
def test_a_narrowed_behavior_check_refuses_to_write_the_full_session_path(project, flags):
    result = behavior(project, *flags, "--out", ".lapis/behavior/t.json")
    assert result.returncode == 2
    assert flags[0] in result.stderr and ".lapis/behavior/t.narrow.json" in result.stderr
    assert not (project / ".lapis").exists()


@pytest.mark.browser
def test_a_narrowed_run_may_name_any_other_file(project):
    result = behavior(project, "--probe", "console", "--context", "d", "--out", "mine/elsewhere.json")
    assert result.returncode == 0, result.stderr
    assert (project / "mine" / "elsewhere.json").is_file()
    assert not (project / ".lapis").exists()
