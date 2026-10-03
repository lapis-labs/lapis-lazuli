"""Failure records: which failures are the environment's, and what the release gate does with them."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from lapis_design import attempts, next_step
from lapis_design.chromium import BrowserUnavailable
from lapis_design.cli import main as cli_main
from procedure_support import TASK, finish, make_project


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("LAZULI_DB", "")
    return make_project(tmp_path)


@pytest.mark.parametrize("exc, reason", [
    (BrowserUnavailable("the browser is not installed; run x"), "the browser is not installed; run x"),
    (PermissionError(13, "Permission denied", "/sandbox/cache"), "[Errno 13] Permission denied: '/sandbox/cache'"),
])
def test_a_browser_that_will_not_start_and_a_path_the_sandbox_denies_are_the_environment(exc, reason):
    assert attempts.environment_reason(exc) == reason


@pytest.mark.parametrize("exc", [
    ValueError("plan names another task"), FileNotFoundError(2, "No such file", "stub.yaml"),
    RuntimeError("probe crashed"), TimeoutError("took too long"), KeyboardInterrupt(),
], ids=lambda exc: type(exc).__name__)
def test_an_input_error_a_timeout_or_a_crash_is_never_recorded_as_the_environment(exc):
    assert attempts.environment_reason(exc) is None


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs a folder the user cannot write to")
def test_a_release_check_that_a_sandbox_stops_records_it_and_next_counts_the_step_done(project):
    (project / ".lapis" / "attempts" / TASK).mkdir(parents=True)
    (project / ".lapis").chmod(0o555)                  # no new folder under .lapis: .lapis/release cannot be made
    try:
        assert finish(project, "--static") == 2
    finally:
        (project / ".lapis").chmod(0o755)
    record = attempts.read(project, TASK, "release")
    assert record["exit"] == 2 and "Permission denied" in record["reason"]
    assert record["command"][:3] == ["lapis-design", "release", "check"] and "--task" in record["command"]
    result = next_step.evaluate(project, TASK)
    assert result["state"] == "done" and "could not run here" in result["reason"]


def test_a_release_check_that_runs_removes_the_record_of_an_earlier_failure(project):
    attempts.record(project, TASK, "release", ["lapis-design", "release", "check"], 2, "Permission denied")
    assert attempts.read(project, TASK, "release")
    assert finish(project, "--static") == 0
    assert attempts.read(project, TASK, "release") is None
    assert next_step.evaluate(project, TASK)["state"] == "done"


def test_a_record_cannot_be_made_for_a_step_no_check_runs_or_a_task_that_is_not_a_plan_id(tmp_path):
    assert attempts.record(tmp_path, TASK, "ledger", ["x"], 2, "claimed") is None
    assert attempts.record(tmp_path, "../escape", "render", ["x"], 2, "claimed") is None
    assert not (tmp_path / ".lapis").exists()


def test_next_refuses_an_unavailable_record_without_a_reason(project, capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main(["next", "--task", TASK, "--root", str(project), "--unavailable", "critic"])
    assert exc.value.code == 2 and "go together" in capsys.readouterr().err
    assert attempts.read(project, TASK, "critic") is None
