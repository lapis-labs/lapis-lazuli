"""A long check reports its end once; the same check asked again while it runs joins it; and a checkpoint never calls a check
that runs, or that has no result for the build shown, finished. Nothing here starts a browser: a fake producer writes the
report, and a lock stands for a run in progress."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from lapis_design import check_cache, checks, next_step, owner, owner_text
from lapis_design.cli import main as cli_main
from procedure_support import TASK, make_interactive, make_project, save
from test_draft_review import project as shown_project, reviewed  # noqa: F401

PAGE = "<!doctype html><title>t</title><link rel=stylesheet href=style.css><h1>hi</h1>"


@pytest.fixture
def site(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("LAZULI_DB", "")
    monkeypatch.delenv("LAPIS_TASK", raising=False)
    root = make_project(tmp_path)
    (root / "site").mkdir()
    (root / "site" / "index.html").write_text(PAGE)
    (root / "site" / "style.css").write_text("h1{font-size:32px}\n")
    monkeypatch.chdir(root)
    return root


def render_key(root: Path, render_task: str = "shown", widths=check_cache.WIDTHS, build_of: str = "index.html") -> check_cache.Key:
    served = check_cache.served((root / "site" / build_of).as_uri(), root)
    return check_cache.make_key("render", served, {"task": render_task}, {"widths": sorted(widths), "out": f"{render_task}.json"})


def stored_render(root: Path, key: check_cache.Key, render_task: str = "shown") -> None:
    out = root / ".lapis" / "renders" / f"{render_task}.json"

    def produce() -> int:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("{}\n")
        return 0
    assert check_cache.run(root, key, out=out, shots=None, fresh=True, produce=produce).cache in ("miss", "off")


def hold_lock(root: Path, kind: str, out: str, build: str = "b" * 16, started: float | None = None) -> Path:
    """A lock as a live check holds it: this process's id, fresh."""
    lock = root / check_cache.CACHE_DIR / "locks" / f"{kind}-{'s' * 32}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"kind": kind, "build_id": build, "state_key": "s" * 32, "out": out, "pid": os.getpid(),
                                "started": started or time.time() - 125}))
    return lock


def draft_page(root: Path, url: str, **page) -> None:
    save(root, f"drafts/{TASK}.yaml", {"version": 1, "task": TASK, "pages": [
        {"url": url, "render_task": "shown", "sources": ["site/index.html"], "direction": "new", "area": "page",
         "widths": [390, 1440], "behavior_changed": False, **page}]})


# ---------------------------------------------------------------- a second identical check joins

def test_a_second_identical_check_joins_the_one_running_and_says_so(site, capsys):
    key, calls, release, results = render_key(site), [], threading.Event(), {}
    out_a, out_b = site / ".lapis/renders/a.json", site / ".lapis/renders/b.json"

    def long_run() -> int:
        calls.append(1)
        assert release.wait(20)
        out_a.parent.mkdir(parents=True, exist_ok=True)
        out_a.write_text("{}\n")
        return 0

    def second() -> None:
        results["second"] = check_cache.run(site, key, out=out_b, shots=None, fresh=False, produce=lambda: pytest.fail("a second run"),
                                            poll=0.05)

    first = threading.Thread(target=lambda: results.update(first=check_cache.run(
        site, key, out=out_a, shots=None, fresh=False, produce=long_run, poll=0.05)))
    first.start()
    while not check_cache.running(site):
        time.sleep(0.02)
    [live] = check_cache.running(site)
    assert (live["kind"], live["pid"], live["build_id"], live["out"]) == ("render", os.getpid(), key.build_id, ".lapis/renders/a.json")
    joiner = threading.Thread(target=second)
    joiner.start()
    time.sleep(0.4)
    assert "second" not in results and len(calls) == 1             # it waits; it does not start
    release.set()
    first.join(20), joiner.join(20)
    assert results["first"].cache == "miss" and results["second"].cache == "join" and len(calls) == 1
    assert "the identical run is still going" in capsys.readouterr().err
    assert check_cache.running(site) == []                         # the lock goes with the run


def test_a_lock_whose_holder_is_gone_is_no_running_check(site):
    lock = hold_lock(site, "behavior", ".lapis/behavior/t.json")
    assert [row["kind"] for row in check_cache.running(site)] == ["behavior"]
    info = json.loads(lock.read_text())
    lock.write_text(json.dumps({**info, "pid": 2147483646}))
    assert check_cache.running(site) == []


# ---------------------------------------------------------------- a checkpoint says what has not finished

def test_the_owner_summary_lists_a_running_check_as_not_finished_and_not_when_it_ends(shown_project):
    reviewed(shown_project)
    quiet = owner.delivery(shown_project, TASK, {"kind": "approval"})
    assert "Checks not finished" not in quiet.summary
    lock = hold_lock(shown_project, "behavior", ".lapis/behavior/shown-page.narrow.json")
    busy = owner.delivery(shown_project, TASK, {"kind": "approval"})
    section = busy.summary.split("## Checks not finished for the build shown\n")[1].split("\n\n")[0]
    assert section.startswith("- behavior check: still running since ") and "has not finished" in section
    assert "done" not in section.lower().replace("not finished", "")
    [line] = [line for what, line in busy.required if what == "check not finished"]
    assert line in busy.summary and line == section
    assert busy.sha8 != quiet.sha8 and "behavior check: still running" in busy.block        # the full block names it too
    lock.unlink()
    assert "Checks not finished" not in owner.delivery(shown_project, TASK, {"kind": "approval"}).summary


def test_questions_that_drop_the_running_check_line_do_not_carry_the_summary(shown_project):
    reviewed(shown_project)
    hold_lock(shown_project, "render", ".lapis/renders/shown-page.narrow.json")
    delivery = owner.delivery(shown_project, TASK, {"kind": "approval"})
    kept = "\n".join(delivery.summary.splitlines())
    assert delivery.problems(kept) == []
    dropped = "\n".join(line for line in kept.splitlines() if "still running" not in line)
    assert any("check not finished" in problem for problem in delivery.problems(dropped))


def test_the_summary_names_a_running_check_in_the_owners_language(shown_project):
    reviewed(shown_project)
    hold_lock(shown_project, "behavior", ".lapis/behavior/shown-page.narrow.json")
    korean = owner_text.say("ko", "checks.running", kind=owner_text.say("ko", "checks.kind.behavior"), since="12:00:00", out="x")
    assert "아직 돌고 있어요" in korean and "끝나지 않아서" in korean
    assert set(owner_text.EN) == set(owner_text.KO)


def test_next_discloses_the_running_check_when_it_waits_for_the_owner(shown_project):
    reviewed(shown_project)
    hold_lock(shown_project, "behavior", ".lapis/behavior/shown-page.narrow.json")
    result = next_step.evaluate(shown_project, TASK)
    assert result["state"] in ("needs-step", "waiting-for-user")
    assert [row["kind"] for row in result["checks_unfinished"]["running"]] == ["behavior"]
    assert "running, not finished" in next_step._text({**result, "step": result["step"] or {"id": "x", "command": None, "why": "w"}})


def test_a_shown_build_with_no_stored_result_is_disclosed_and_a_changed_build_again(site):
    draft_page(site, (site / "site" / "index.html").as_uri())
    assert checks.unfinished(site, TASK)["not_run"] == [
        {"kind": "render", "url": (site / "site" / "index.html").as_uri(), "build_id": render_key(site).build_id,
         "widths": [390, 1440]}]
    stored_render(site, render_key(site))
    assert checks.unfinished(site, TASK) == {"running": [], "not_run": []}
    (site / "site" / "style.css").write_text("h1{font-size:40px}\n")        # the build changed after the check
    [row] = checks.unfinished(site, TASK)["not_run"]
    assert row["kind"] == "render" and row["build_id"] == render_key(site).build_id


def test_a_narrower_stored_run_does_not_cover_the_widths_shown(site):
    draft_page(site, (site / "site" / "index.html").as_uri())
    stored_render(site, render_key(site, widths=(390,)))
    assert [r["widths"] for r in checks.unfinished(site, TASK)["not_run"]] == [[390, 1440]]


def test_a_changed_behavior_with_no_stored_behavior_result_is_disclosed(site):
    draft_page(site, (site / "site" / "index.html").as_uri(), behavior_changed=True)
    stored_render(site, render_key(site))
    assert [r["kind"] for r in checks.unfinished(site, TASK)["not_run"]] == ["behavior"]


def test_a_page_this_cli_does_not_serve_says_nothing_of_its_build(site):
    draft_page(site, "https://example.com/page")
    assert checks.unfinished(site, TASK) == {"running": [], "not_run": []}


# ---------------------------------------------------------------- the steps wait for a running check

def test_a_running_render_is_waited_for_with_one_command_not_started_again(site):
    (site / f".lapis/renders/{TASK}.json").unlink()
    assert next_step.evaluate(site, TASK)["step"]["id"] == "render"
    lock = hold_lock(site, "render", f".lapis/renders/{TASK}.json")
    result = next_step.evaluate(site, TASK)
    step = result["step"]
    assert step["id"] == "render-wait" and step["command"] == f"lapis-design checks wait --task {TASK}"
    assert "has not finished" in step["why"] and "joins it" in step["why"]
    assert [row["kind"] for row in result["checks_unfinished"]["running"]] == ["render"]      # every step carries it
    assert "not finished: render check, started" in next_step._text(result)
    lock.unlink()
    assert next_step.evaluate(site, TASK)["step"]["id"] == "render"


def test_a_behavior_check_that_a_lock_shows_running_is_waited_for(site):
    make_interactive(site)
    (site / f".lapis/behavior/{TASK}.json").unlink()
    hold_lock(site, "behavior", f".lapis/behavior/{TASK}.json")
    step = next_step.evaluate(site, TASK)["step"]
    assert step["id"] == "behavior-wait" and step["command"] == f"lapis-design checks wait --task {TASK}"


def test_the_behavior_launch_step_polls_with_the_wait_command(site):
    make_interactive(site)
    (site / f".lapis/behavior/{TASK}.json").unlink()
    step = next_step.evaluate(site, TASK)["step"]
    assert step["id"] == "behavior" and f"lapis-design checks wait --task {TASK}" in step["why"] and "tail -n 3" not in step["why"]


# ---------------------------------------------------------------- the wait reports once

def test_wait_says_a_running_check_has_not_finished_and_exits_3(site, capsys):
    hold_lock(site, "behavior", f".lapis/behavior/{TASK}.json")
    assert cli_main(["checks", "wait", "--task", TASK, "--timeout", "0.3"]) == checks.STILL_RUNNING
    out = capsys.readouterr().out
    assert "not finished: behavior check, started" in out and "joins it" in out


def test_wait_prints_the_end_of_a_background_run_once_with_a_bounded_log(site, capsys):
    pidfile = site / f".lapis/logs/{TASK}.behavior.pid"
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text("2147483646\n")                              # the process ended
    started = time.time() - 600
    os.utime(pidfile, (started, started))
    (site / f".lapis/logs/{TASK}.behavior.log").write_text("behavior: pass\n" + "x" * 9000)
    report = site / f".lapis/behavior/{TASK}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("{}\n")
    os.utime(report, (started + 300, started + 300))
    assert cli_main(["checks", "wait", "--task", TASK]) == 0
    first = capsys.readouterr().out
    assert "behavior check finished after 5 min" in first and "behavior: pass" in first and "the log goes on in" in first
    assert len(first) < 3500
    assert cli_main(["checks", "wait", "--task", TASK]) == 0
    second = capsys.readouterr().out
    assert "finished" not in second and "behavior: pass" not in second and "no check runs" in second


def test_wait_with_nothing_running_says_so_and_status_names_the_unfinished(site, capsys):
    assert cli_main(["checks", "wait", "--task", TASK]) == 0
    assert "no check runs" in capsys.readouterr().out
    draft_page(site, (site / "site" / "index.html").as_uri())
    hold_lock(site, "render", ".lapis/renders/shown.json")
    assert cli_main(["checks", "status", "--task", TASK]) == 0
    out = capsys.readouterr().out
    assert "render check, started" in out and "running, not finished" in out and "no result for this build, not run" in out


def test_the_wait_command_writes_a_telemetry_line(site):
    assert cli_main(["checks", "wait", "--task", TASK]) == 0
    row = json.loads((site / ".lapis/telemetry/checks.jsonl").read_text().splitlines()[-1])
    assert row["command"] == "checks wait" and row["task"] == TASK and row["exit"] == 0 and "waited_seconds" in row


def test_a_lock_names_the_report_its_run_writes(site):
    key = render_key(site)
    seen = []

    def produce() -> int:
        seen.extend(check_cache.running(site))
        (site / ".lapis/renders/shown.json").write_text("{}\n")
        return 0

    check_cache.run(site, key, out=site / ".lapis/renders/shown.json", shots=None, fresh=False, produce=produce)
    assert [(r["kind"], r["out"]) for r in seen] == [("render", ".lapis/renders/shown.json")]
