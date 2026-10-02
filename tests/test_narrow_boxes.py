"""`behavior check --box` and `--limit` narrow the per-box probes (controls, pointer) and say how much they left out."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from narrow_support import BUTTONS, behavior, make_project


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return make_project(tmp_path)


def coverage(document: dict, probe: str) -> dict:
    return next(row for row in document["coverage"] if row["probe"] == probe)


def exercised(document: dict, probe: str = "controls") -> list[str]:
    return [row["box"] for row in document["probes"].get(probe, [])]


@pytest.mark.parametrize("flags, message", [
    (["--box", "b1"], "--box"),                                      # not a box id
    (["--box", "B" + "0" * 12], "--box"),
    (["--limit", "0"], "--limit"),
    (["--limit", "-2"], "--limit"),
    (["--probe", "keyboard", "--limit", "2"], "per-box"),             # no per-box probe selected
    (["--probe", "commits", "--box", "b" + "0" * 12], "per-box"),
])
def test_box_and_limit_are_checked_before_anything_runs(project, flags, message):
    result = behavior(project, *flags, "--out", "never.json")
    assert result.returncode == 2 and message in result.stderr
    assert not (project / "never.json").exists()


@pytest.mark.parametrize("flags", [["--limit", "1"], ["--probe", "controls", "--box", BUTTONS["b1"]]])
def test_a_box_narrowed_run_refuses_to_write_the_full_session_path(project, flags):
    result = behavior(project, *flags, "--out", ".lapis/behavior/t.json")
    assert result.returncode == 2
    assert flags[0] in result.stderr and ".lapis/behavior/t.narrow.json" in result.stderr
    assert not (project / ".lapis").exists()


@pytest.mark.browser
def test_limit_exercises_the_first_boxes_and_counts_the_rest_as_left_out(project):
    result = behavior(project, "--probe", "controls", "--context", "d", "--limit", "3")
    assert result.returncode == 0, result.stderr
    document = json.loads((project / ".lapis" / "behavior" / "t.narrow.json").read_text())
    assert exercised(document) == [BUTTONS[name] for name in ("b1", "b2", "b3")]                # document order
    row = coverage(document, "controls")
    assert row["status"] == "partial" and row["contexts"] == ["d"]
    assert "1 box left out" in row["reason"] and "--limit" in row["reason"]


@pytest.mark.browser
def test_box_exercises_only_the_named_boxes_and_counts_the_rest_as_left_out(project):
    chosen = [BUTTONS["b2"], BUTTONS["b4"]]
    result = behavior(project, "--probe", "controls", "--context", "d", "--box", chosen[1], "--box", chosen[0])
    assert result.returncode == 0, result.stderr
    document = json.loads((project / ".lapis" / "behavior" / "t.narrow.json").read_text())
    assert exercised(document) == chosen
    row = coverage(document, "controls")
    assert row["status"] == "partial" and "2 boxes left out" in row["reason"] and "--box" in row["reason"]


@pytest.mark.browser
def test_a_box_that_matches_nothing_is_named_in_the_reason(project):
    missing = "b" + "0" * 12
    result = behavior(project, "--probe", "controls", "--context", "d", "--box", BUTTONS["b3"], "--box", missing)
    assert result.returncode == 0, result.stderr
    document = json.loads((project / ".lapis" / "behavior" / "t.narrow.json").read_text())
    assert exercised(document) == [BUTTONS["b3"]]
    reason = coverage(document, "controls")["reason"]
    assert coverage(document, "controls")["status"] == "partial" and missing in reason and "3 boxes left out" in reason


@pytest.mark.browser
def test_a_limit_above_the_box_count_leaves_nothing_out(project):
    result = behavior(project, "--probe", "controls", "--context", "d", "--limit", "9")
    assert result.returncode == 0, result.stderr
    document = json.loads((project / ".lapis" / "behavior" / "t.narrow.json").read_text())
    assert exercised(document) == list(BUTTONS.values())
    assert coverage(document, "controls") == {"probe": "controls", "status": "ran", "contexts": ["d"]}


@pytest.mark.browser
def test_the_pointer_probe_hovers_only_the_chosen_boxes(project):
    result = behavior(project, "--probe", "pointer", "--context", "d", "--box", BUTTONS["b2"])
    assert result.returncode == 0, result.stderr
    document = json.loads((project / ".lapis" / "behavior" / "t.narrow.json").read_text())
    assert [row["box"] for row in document["probes"]["pointer"]] == [BUTTONS["b2"]]
    row = coverage(document, "pointer")
    assert row["status"] == "partial" and "3 boxes left out" in row["reason"]
    full = behavior(project, "--probe", "pointer", "--context", "d", "--out", "pointer-all.json")
    assert full.returncode == 0, full.stderr
    assert [row["box"] for row in json.loads((project / "pointer-all.json").read_text())["probes"]["pointer"]] \
        == [BUTTONS["b1"], BUTTONS["b2"]]                                                      # --box dropped the other tip


@pytest.mark.browser
def test_commits_say_they_worked_from_the_boxes_controls_left_out(project):
    result = behavior(project, "--probe", "controls", "--probe", "commits", "--context", "d", "--limit", "2")
    assert result.returncode == 0, result.stderr
    document = json.loads((project / ".lapis" / "behavior" / "t.narrow.json").read_text())
    row = coverage(document, "commits")
    assert row["status"] == "partial" and "controls left out 2 boxes" in row["reason"]
