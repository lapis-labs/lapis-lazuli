"""`render check`, `behavior check`, `slop lint`, and `worker check` as commands: one run per build and state, the narrow
set after a change, what they print, and the telemetry line each leaves. The browser and the probes are replaced by
fakes that write the reports a run would, so these run in seconds; tests/test_check_browser.py runs the real ones."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
import yaml

from lapis_design import behavior_check, render, shared_dir
from lapis_design.cli import main as cli_main

SHARED = shared_dir()
PAGE = "<!doctype html><title>t</title><link rel=stylesheet href=style.css><script src=app.js></script><h1>hi</h1>"
CSS = "body{margin:0}\nh1{font-size:32px}\n@media (max-width: 500px){ h1{font-size:20px} }\n"
STUB = "version: 0\nclock: {start: '2026-10-01T00:00:00Z'}\ncollections: {}\nvariants: {empty: {}, partial: {}}\nroutes: []\nvalues: {}\n"
ALL = [320, 390, 768, 1440]


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(PAGE)
    (site / "style.css").write_text(CSS)
    (site / "app.js").write_text("console.log(1)")
    (tmp_path / "stub.yaml").write_text(STUB)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LAPIS_SIG_KEY_FILE", str(tmp_path / "sig.key"))
    monkeypatch.setenv("LAZULI_DB", "")
    return tmp_path


def lines(project: Path) -> list[dict]:
    path = project / ".lapis/telemetry/checks.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.fixture
def captures(monkeypatch):
    """The render browser, replaced: each call records the widths it was asked for and writes a valid-enough extract."""
    calls: list[list[int]] = []

    def capture(parser, args):
        widths = sorted(args.width or ALL)
        calls.append(widths)
        time.sleep(getattr(capture, "seconds", 0))
        out = args.out
        shots = out.parent / f"{out.stem}.shots"
        shots.mkdir(parents=True, exist_ok=True)
        views = []
        for width in widths:
            (shots / f"{width}.png").write_bytes(f"png{len(calls)}".encode())
            views.append({"width": width, "theme": "light", "boxes": [{"id": f"b{width:012x}"}], "text": [{}],
                          "screenshot": f"{out.stem}.shots/{width}.png"})
        out.write_text(json.dumps({"version": 1, "source": {"kind": "render", "url": args.url, "task": args.task},
                                   "call": len(calls), "viewports": views}, indent=2) + "\n")
        args.origins = set()
        return 0

    monkeypatch.setattr(render, "_capture", capture)
    capture.calls = calls
    return capture


def page(project: Path) -> str:
    return str(project / "site" / "index.html")


def run_render(project: Path, capsys, *argv: str) -> tuple[int, str]:
    code = render.main([page(project), "--task", "t", *argv])
    return code, capsys.readouterr().out


def edit(project: Path, name: str, text: str | bytes) -> None:
    path = project / "site" / name
    path.write_bytes(text if isinstance(text, bytes) else text.encode())


# ----------------------------------------------------------------------------------------- render: one run per build

def test_an_identical_render_is_a_hit_with_the_same_extract_and_shots(project, captures, capsys):
    code, first = run_render(project, capsys)
    renders = project / ".lapis/renders"
    stored = {path.name: path.read_bytes() for path in sorted(renders.rglob("*")) if path.is_file()}
    code_again, again = run_render(project, capsys)
    assert (code, code_again, len(captures.calls)) == (0, 0, 1)                   # the second call never opened a browser
    assert {path.name: path.read_bytes() for path in sorted(renders.rglob("*")) if path.is_file()} == stored
    assert "cache miss" in first and "cache hit" in again and "--fresh" in again
    log = lines(project)
    assert [row["cache"] for row in log] == ["miss", "hit"]
    assert log[0]["build_id"] == log[1]["build_id"] and log[0]["state_key"] == log[1]["state_key"] and log[0]["build_id"]
    assert [row["command"] for row in log] == ["render check"] * 2 and {row["scope"] for row in log} == {"full"}
    assert [row["output_chars"] for row in log] == [len(first), len(again)]
    assert all(row["report_path"] == ".lapis/renders/t.json" and row["exit"] == 0 for row in log)


def test_a_hit_rewrites_the_extract_so_it_is_as_new_as_a_rerun(project, captures, capsys):
    run_render(project, capsys)
    extract = project / ".lapis/renders/t.json"
    import os

    os.utime(extract, (1, 1))
    run_render(project, capsys)
    assert extract.stat().st_mtime > 1000


@pytest.mark.parametrize("change", [
    lambda p: edit(p, "style.css", CSS + "p{color:red}"),
    lambda p: edit(p, "app.js", "console.log(2)"),
    lambda p: edit(p, "index.html", PAGE + "<p>more</p>"),
    lambda p: edit(p, "font.woff2", b"\x00new font"),
    lambda p: (p / "site" / "img").mkdir() or edit(p, "img/a.png", b"png"),
])
def test_any_served_file_change_is_a_miss(project, captures, capsys, change):
    run_render(project, capsys)
    change(project)
    run_render(project, capsys)
    assert len(captures.calls) == 2 and [row["cache"] for row in lines(project)] == ["miss", "miss"]
    assert lines(project)[0]["build_id"] != lines(project)[1]["build_id"]


def test_a_different_state_of_the_same_build_is_a_miss_and_returns_to_a_hit(project, captures, capsys):
    run_render(project, capsys)
    code = render.main([(project / "site" / "index.html").as_uri() + "?footer=fluid", "--task", "t"])
    capsys.readouterr()
    assert code == 0 and len(captures.calls) == 2                                    # a query is a state of the build
    run_render(project, capsys)
    assert len(captures.calls) == 2                                                  # the unqueried state is still stored
    log = lines(project)
    assert [row["cache"] for row in log] == ["miss", "miss", "hit"] and log[0]["build_id"] == log[1]["build_id"]
    assert len({row["state_key"] for row in log}) == 2


def test_a_different_task_or_width_set_is_a_miss(project, captures, capsys):
    run_render(project, capsys)
    render.main([page(project), "--task", "other"])
    run_render(project, capsys, "--width", "390")
    capsys.readouterr()
    assert len(captures.calls) == 3


def test_fresh_bypasses_the_cache_and_replaces_the_result(project, captures, capsys):
    run_render(project, capsys)
    code, forced = run_render(project, capsys, "--fresh")
    assert code == 0 and len(captures.calls) == 2 and "cache off: --fresh" in forced
    run_render(project, capsys)
    assert len(captures.calls) == 2                                                  # the replaced result is reused
    assert json.loads((project / ".lapis/renders/t.json").read_text())["call"] == 2
    assert [row["cache"] for row in lines(project)] == ["miss", "off", "hit"]


def test_an_address_the_cli_does_not_serve_always_runs(project, captures, capsys):
    for _ in range(2):
        assert render.main(["http://127.0.0.1:9/", "--task", "t"]) == 0
    capsys.readouterr()
    assert len(captures.calls) == 2
    log = lines(project)
    assert [row["cache"] for row in log] == ["off", "off"] and log[0]["build_id"] is None and log[0]["state_key"] is None


def test_a_capture_that_asked_another_origin_or_changed_the_files_is_not_stored(project, captures, capsys, monkeypatch):
    real = render._capture

    def asks_elsewhere(parser, args):
        code = real(parser, args)
        args.origins = {args.page_origin, "http://127.0.0.1:7"}
        return code

    monkeypatch.setattr(render, "_capture", asks_elsewhere)
    run_render(project, capsys)
    run_render(project, capsys)
    out = capsys.readouterr().out
    assert len(captures.calls) == 2 and [row["cache"] for row in lines(project)] == ["off", "off"]
    assert "other origins" in lines(project)[0]["cache_reason"] and out == ""


def test_concurrent_identical_renders_run_the_browser_once(project, captures, capsys):
    captures.seconds = 1.0
    codes: list[int] = []

    def go(delay: float) -> None:
        time.sleep(delay)
        codes.append(render.main([page(project), "--task", "t"]))

    threads = [threading.Thread(target=go, args=(delay,)) for delay in (0.0, 0.3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    capsys.readouterr()
    assert codes == [0, 0] and len(captures.calls) == 1
    assert sorted(row["cache"] for row in lines(project)) == ["join", "miss"]


# ----------------------------------------------------------------------------------------- render: the narrow set

def full_then_edit(project, captures, capsys, name: str, text: str) -> tuple[int, str]:
    run_render(project, capsys)
    edit(project, name, text)
    return run_render(project, capsys, "--changed-since", ".lapis/renders/t.json")


def test_a_change_inside_a_width_query_captures_only_those_widths_beside_the_full_extract(project, captures, capsys):
    run_render(project, capsys)
    full = (project / ".lapis/renders/t.json").read_bytes()
    edit(project, "style.css", CSS.replace("20px", "22px"))
    code, printed = run_render(project, capsys, "--changed-since", ".lapis/renders/t.json")
    assert code == 0 and captures.calls == [ALL, [320, 390]]
    narrow = json.loads((project / ".lapis/renders/t.narrow.json").read_text())
    assert [v["width"] for v in narrow["viewports"]] == [320, 390]
    assert (project / ".lapis/renders/t.json").read_bytes() == full                  # the full extract is untouched
    assert "scope: NARROW" in printed and "320, 390" in printed and "t.narrow.json" in printed
    assert "not captured this run" not in printed or "768" in printed
    row = lines(project)[-1]
    assert (row["scope"], row["cache"], row["report_path"]) == ("narrow", "miss", ".lapis/renders/t.narrow.json")


@pytest.mark.parametrize("name, text", [
    ("style.css", CSS.replace("margin:0", "margin:2px")),            # a rule outside a width query
    ("style.css", CSS + ":root{--a:1}\n"),                           # shared custom properties
    ("app.js", "console.log(2)"),
    ("index.html", PAGE + "<p>x</p>"),
])
def test_a_shared_change_widens_to_every_width_and_writes_the_full_extract(project, captures, capsys, name, text):
    code, printed = full_then_edit(project, captures, capsys, name, text)
    assert code == 0 and captures.calls == [ALL, ALL]
    assert not (project / ".lapis/renders/t.narrow.json").exists()
    assert "scope: full" in printed
    assert json.loads((project / ".lapis/renders/t.json").read_text())["call"] == 2
    assert lines(project)[-1]["scope"] == "full"


def test_nothing_changed_since_the_report_runs_no_browser_and_says_so(project, captures, capsys):
    run_render(project, capsys)
    code, printed = run_render(project, capsys, "--changed-since", ".lapis/renders/t.json")
    assert code == 0 and len(captures.calls) == 1
    assert "nothing to capture" in printed and "no served file changed" in printed and "no browser run" in printed
    assert not (project / ".lapis/renders/t.narrow.json").exists()
    assert lines(project)[-1]["scope"] == "narrow" and lines(project)[-1]["cache"] == "hit"


def test_a_change_no_width_can_see_says_which_widths_it_checked(project, captures, capsys):
    run_render(project, capsys)
    edit(project, "style.css", CSS + "@media (min-width: 2000px){ h1{color:red} }\n")
    code, printed = run_render(project, capsys, "--changed-since", ".lapis/renders/t.json")
    assert code == 0 and len(captures.calls) == 1 and "nothing to capture" in printed
    assert "comments or whitespace" not in printed and "style.css changed only inside width-bounded" in printed


def test_a_report_the_cache_did_not_write_is_not_trusted_for_a_narrow_run(project, captures, capsys):
    run_render(project, capsys)
    (project / ".lapis/renders/t.json").write_text('{"edited": true}\n')
    edit(project, "style.css", CSS.replace("20px", "22px"))
    code = render.main([page(project), "--task", "t", "--changed-since", ".lapis/renders/t.json"])
    captured = capsys.readouterr()
    assert code == 0 and captures.calls[-1] == ALL and "is not a report this CLI stored" in captured.err


def test_changed_since_cannot_be_combined_with_the_flags_that_choose_widths_or_reuse(project, captures, capsys):
    for flag in (["--width", "390"], ["--fresh"]):
        with pytest.raises(SystemExit) as stop:
            render.main([page(project), "--task", "t", "--changed-since", "x.json", *flag])
        assert stop.value.code == 2
    assert captures.calls == [] and not (project / ".lapis").exists()


def test_narrow_receipts_alone_never_pass_the_release_gate(project, captures, capsys):
    plan = yaml.safe_load((SHARED / "plan/example.plan.yaml").read_text())
    task = plan["task"]["id"]
    plan["flows"], plan["references"] = [], []                                         # what `--static` accepts
    plan["tokens"]["type"]["roles"] = []
    plan["tokens"]["color"]["themes"] = ["light"]
    plan["tokens"]["color"]["roles"] = [r for r in plan["tokens"]["color"]["roles"] if r.get("theme") != "dark"]
    (project / ".lapis/plans").mkdir(parents=True)
    (project / f".lapis/plans/{task}.yaml").write_text(yaml.safe_dump(plan))
    run_render_task = lambda *argv: render.main([page(project), "--task", task, *argv])
    run_render_task("--width", "390")
    run_render_task("--width", "390")                                                 # a hit, still narrow
    capsys.readouterr()
    renders = project / ".lapis/renders"
    assert sorted(p.name for p in renders.glob("*.json")) == [f"{task}.narrow.json"]
    code = cli_main(["release", "check", "--task", task, "--root", str(project), "--offline", "--static"])
    document = json.loads((project / f".lapis/release/{task}.json").read_text())
    missing = [f for f in document["findings"] if f["rule_id"] == "release.input-missing"]
    assert code == 1 and any(f"renders/{task}.json" in json.dumps(f) for f in missing)
    capsys.readouterr()


@pytest.mark.parametrize("flag", [["--width", "390"]])
def test_a_narrowed_hit_still_refuses_to_write_the_full_path(project, captures, capsys, flag):
    run_render(project, capsys, *flag)
    with pytest.raises(SystemExit) as stop:
        run_render(project, capsys, *flag, "--out", ".lapis/renders/t.json")
    assert stop.value.code == 2 and not (project / ".lapis/renders/t.json").exists()


# ----------------------------------------------------------------------------------------- render: what is printed

def test_the_printed_result_is_a_bounded_summary_with_the_path_scope_build_and_counts(project, captures, capsys):
    code, printed = run_render(project, capsys)
    assert len(printed) < 2500 and ".lapis/renders/t.json" in printed
    for needle in ("4 viewports", "boxes", "runs", "scope: full", "build ", "state ", "cache miss", "judges nothing"):
        assert needle in printed
    edit(project, "style.css", CSS + "p{color:red}")
    _, changed = run_render(project, capsys)
    assert "since the previous extract: no change in boxes or runs" in changed       # same boxes, different build


# ----------------------------------------------------------------------------------------- behavior

@pytest.fixture
def probes(monkeypatch):
    """The behavior probes, replaced: each call records the contexts it was asked for and writes a session."""
    calls: list[list[str]] = []

    def check(parser, args):
        contexts = sorted(args.context or ["m", "d"])
        calls.append(contexts)
        time.sleep(getattr(check, "seconds", 0))
        out = args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        coverage = [{"probe": "controls", "status": "ran", "contexts": contexts},
                    {"probe": "scroll", "status": "partial", "reason": "d/space: need 7083px remaining"}]
        out.write_text(json.dumps({"call": len(calls), "contexts": [{"id": c} for c in contexts], "nodes": [{"id": "b1"}],
                                   "coverage": coverage, "source": {"task": args.task}}, indent=2) + "\n")
        return 0

    monkeypatch.setattr(behavior_check, "_check", check)
    check.calls = calls
    return check


def run_behavior(project: Path, capsys, *argv: str) -> tuple[int, str]:
    code = behavior_check.main([page(project), "--task", "t", "--stub", "stub.yaml", *argv])
    return code, capsys.readouterr().out


def test_an_identical_behavior_check_is_a_hit_and_a_stub_change_is_a_miss(project, probes, capsys):
    _, first = run_behavior(project, capsys)
    stored = (project / ".lapis/behavior/t.json").read_bytes()
    _, again = run_behavior(project, capsys)
    assert len(probes.calls) == 1 and (project / ".lapis/behavior/t.json").read_bytes() == stored
    assert "cache miss" in first and "cache hit" in again
    for text in (first, again):
        assert "partial scroll — d/space: need 7083px remaining" in text and "coverage: 1 ran, 1 partial" in text
    (project / "stub.yaml").write_text(STUB + "# changed\n")
    run_behavior(project, capsys)
    assert len(probes.calls) == 2
    edit(project, "style.css", CSS + "p{color:red}")
    run_behavior(project, capsys)
    assert len(probes.calls) == 3
    assert [row["cache"] for row in lines(project)] == ["miss", "hit", "miss", "miss"]
    assert {row["command"] for row in lines(project)} == {"behavior check"}


def test_behavior_check_has_no_identity_for_a_backend_it_does_not_run(project, probes, capsys):
    for _ in range(2):
        behavior_check.main([page(project), "--task", "t", "--stub-url", "http://127.0.0.1:9/"])
    capsys.readouterr()
    assert len(probes.calls) == 2 and [row["cache"] for row in lines(project)] == ["off", "off"]


def test_concurrent_identical_behavior_checks_run_the_probes_once(project, probes, capsys):
    probes.seconds = 1.0
    threads = [threading.Thread(target=lambda delay=delay: (time.sleep(delay), run_behavior(project, capsys)))
               for delay in (0.0, 0.3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(probes.calls) == 1 and sorted(row["cache"] for row in lines(project)) == ["join", "miss"]


@pytest.mark.parametrize("css, contexts", [
    (CSS.replace("20px", "22px"), ["m"]),                                              # max-width: 500px reaches 390
    (CSS + "@media (min-width: 1000px){ h1{color:red} }\n", ["d"]),                    # reaches 1440
])
def test_a_width_bounded_change_runs_only_the_context_it_reaches_beside_the_full_session(project, probes, capsys, css, contexts):
    run_behavior(project, capsys)
    full = (project / ".lapis/behavior/t.json").read_bytes()
    edit(project, "style.css", css)
    code, printed = run_behavior(project, capsys, "--changed-since", ".lapis/behavior/t.json")
    assert code == 0 and probes.calls == [["d", "m"], contexts]
    assert (project / ".lapis/behavior/t.json").read_bytes() == full
    assert (project / ".lapis/behavior/t.narrow.json").is_file() and "scope: NARROW" in printed
    assert lines(project)[-1]["scope"] == "narrow"


def test_a_change_no_behavior_context_runs_at_runs_nothing_and_says_so(project, probes, capsys):
    run_behavior(project, capsys)
    edit(project, "style.css", CSS + "@media (min-width: 600px) and (max-width: 900px){ h1{color:red} }\n")
    code, printed = run_behavior(project, capsys, "--changed-since", ".lapis/behavior/t.json")
    assert code == 0 and len(probes.calls) == 1
    assert "nothing to run" in printed and "390 and 1440" in printed and "no browser run" in printed
    assert not (project / ".lapis/behavior/t.narrow.json").exists()


@pytest.mark.parametrize("name, text", [("app.js", "console.log(2)"), ("style.css", CSS.replace("margin:0", "margin:3px"))])
def test_a_shared_change_runs_both_contexts_and_writes_the_full_session(project, probes, capsys, name, text):
    run_behavior(project, capsys)
    edit(project, name, text)
    code, printed = run_behavior(project, capsys, "--changed-since", ".lapis/behavior/t.json")
    assert code == 0 and probes.calls == [["d", "m"], ["d", "m"]]
    assert json.loads((project / ".lapis/behavior/t.json").read_text())["call"] == 2
    assert not (project / ".lapis/behavior/t.narrow.json").exists() and "scope: full" in printed


def test_changed_since_after_a_stub_change_runs_both_contexts(project, probes, capsys):
    run_behavior(project, capsys)
    (project / "stub.yaml").write_text(STUB + "# changed\n")
    edit(project, "style.css", CSS.replace("20px", "22px"))
    run_behavior(project, capsys, "--changed-since", ".lapis/behavior/t.json")
    assert probes.calls[-1] == ["d", "m"]


def test_a_narrowed_behavior_check_that_is_a_hit_still_stays_off_the_full_path(project, probes, capsys):
    run_behavior(project, capsys, "--context", "d")
    code, printed = run_behavior(project, capsys, "--context", "d")
    assert code == 0 and len(probes.calls) == 1 and "cache hit" in printed
    assert (project / ".lapis/behavior/t.narrow.json").is_file() and not (project / ".lapis/behavior/t.json").exists()


# ----------------------------------------------------------------------------------------- lint

def lint(project: Path, capsys, *argv: str, plan: Path | None = None) -> tuple[int, str]:
    code = cli_main(["slop", "lint", "--plan", str(plan or project / "plan.yaml"), *argv])
    return code, capsys.readouterr().out


@pytest.fixture
def plan(project) -> Path:
    path = project / "plan.yaml"
    path.write_text((SHARED / "plan/example.plan.yaml").read_text())
    return path


def test_lint_shows_the_report_again_for_unchanged_inputs_and_runs_again_when_they_change(project, plan, capsys, monkeypatch):
    out = project / ".lapis/lint/t.json"
    code, first = lint(project, capsys, "-o", str(out))
    stored = out.read_bytes()
    from lapis_design.lint import cli as lint_cli

    real, runs = lint_cli.run, []
    monkeypatch.setattr(lint_cli, "run", lambda **kw: runs.append(1) or real(**kw))
    code_again, again = lint(project, capsys, "-o", str(out))
    assert runs == [] and code_again == code and out.read_bytes() == stored            # no second lint; same exit code
    assert "cache miss" in first and "cache hit" in again and "0 new, 0 changed, 0 gone" in again
    plan.write_text(plan.read_text() + "\n# an edit\n")
    lint(project, capsys, "-o", str(out))
    assert runs == [1]
    lint(project, capsys, "-o", str(out), "--fresh")
    assert runs == [1, 1]
    assert [row["cache"] for row in lines(project)] == ["miss", "hit", "miss", "off"]
    assert {row["command"] for row in lines(project)} == {"slop lint"} and lines(project)[0]["report_path"] == ".lapis/lint/t.json"


def test_lint_without_an_output_path_has_nothing_to_reuse(project, plan, capsys):
    lint(project, capsys)
    lint(project, capsys)
    assert [row["cache"] for row in lines(project)] == ["off", "off"] and "no -o" in lines(project)[0]["cache_reason"]


def test_a_reader_touching_the_lazuli_databases_shm_file_does_not_make_the_lint_a_new_one(project, plan, capsys):
    import os

    from lazuli import db as lazuli_db

    db = project / "lazuli.db"
    held = lazuli_db.connect(db)                                # a WAL database keeps `-shm` beside it while a connection is open
    out = project / ".lapis/lint/t.json"
    lint(project, capsys, "-o", str(out), "--lazuli-db", str(db))
    shm = Path(f"{db}-shm")
    assert shm.is_file()
    held.execute("select count(*) from sqlite_master").fetchall()  # every reader moves the index's mtime, the lint run itself included
    later = shm.stat().st_mtime_ns + 5_000_000_000
    os.utime(shm, ns=(later, later))
    _, again = lint(project, capsys, "-o", str(out), "--lazuli-db", str(db))
    held.close()
    assert "cache hit" in again and [row["cache"] for row in lines(project)] == ["miss", "hit"]



def test_a_file_the_plan_names_is_an_input_of_the_lint(project, plan, capsys, monkeypatch):
    document = yaml.safe_load(plan.read_text())
    (project / "DESIGN.md").write_text("# design\n")
    document.setdefault("context", {})["design"] = {"path": "DESIGN.md", "dialect": "unknown"}
    plan.write_text(yaml.safe_dump(document))
    out = project / ".lapis/lint/t.json"
    lint(project, capsys, "-o", str(out))
    (project / "DESIGN.md").write_text("# design, edited\n")
    lint(project, capsys, "-o", str(out))
    assert [row["cache"] for row in lines(project)] == ["miss", "miss"]


def test_a_source_file_change_is_a_new_lint(project, plan, capsys):
    out = project / ".lapis/lint/t.json"
    lint(project, capsys, "-o", str(out), "--source", "site")
    lint(project, capsys, "-o", str(out), "--source", "site")
    edit(project, "style.css", CSS + "p{margin:0}")
    lint(project, capsys, "-o", str(out), "--source", "site")
    assert [row["cache"] for row in lines(project)] == ["miss", "hit", "miss"]


def test_an_edited_report_is_not_shown_as_the_stored_one(project, plan, capsys):
    out = project / ".lapis/lint/t.json"
    lint(project, capsys, "-o", str(out))
    document = json.loads(out.read_text())
    document["findings"] = []
    document["summary"] = {"blocking": 0, "total": 0, "skipped": 0}
    out.write_text(json.dumps(document))
    lint(project, capsys, "-o", str(out))
    assert [row["cache"] for row in lines(project)] == ["miss", "miss"]


def test_lint_json_prints_the_report_whole_even_for_a_hit(project, plan, capsys):
    out = project / ".lapis/lint/t.json"
    lint(project, capsys, "-o", str(out))
    _, text = lint(project, capsys, "-o", str(out), "--json")
    assert json.loads(text) == json.loads(out.read_text())
    assert lines(project)[-1]["cache"] == "hit" and lines(project)[-1]["output_chars"] == len(text)


def test_lint_says_what_is_new_changed_and_gone_since_its_last_report_by_finding_id(project, plan, capsys):
    out = project / ".lapis/lint/t.json"
    lint(project, capsys, "-o", str(out))
    document = json.loads(out.read_text())
    from lapis_design.check_summary import finding_id

    current = document["findings"]
    assert len(current) >= 2, "the example plan is expected to have findings"
    appeared, reworded = current[0], current[1]
    stale = {**current[1], "observed": current[1]["observed"] + " (earlier wording)"}
    vanished = {**current[0], "rule_id": "layout.vanished", "observed": "a finding the next run no longer has"}
    document["findings"] = [stale, vanished, *current[2:]]                           # the previous report, as it was
    document["summary"] = {"blocking": 0, "total": len(document["findings"]), "skipped": 0}
    out.write_text(json.dumps(document))
    _, printed = lint(project, capsys, "-o", str(out))
    assert "1 new, 1 changed, 1 gone" in printed
    assert f"new {finding_id(appeared)}" in printed and f"changed {finding_id(reworded)}" in printed
    assert f"gone: {finding_id(vanished)}" in printed


# ----------------------------------------------------------------------------------------- worker check

def test_worker_check_prints_counts_and_a_few_findings_and_keeps_every_one_in_its_file(project, capsys):
    transcript = project / "agent.jsonl"
    rows = [json.dumps({"type": "tool_use", "name": "Bash", "input": {"command": f"pkill -f 'job-{i}'"}}) for i in range(40)]
    transcript.write_text("\n".join(rows) + "\n")
    code = cli_main(["worker", "check", "--task", "t-task", "--transcript", str(transcript), "--root", str(project)])
    captured = capsys.readouterr()
    record = json.loads((project / ".lapis/state/t-task.workers.json").read_text())
    assert code == 1 and len(record["findings"]) == 40
    assert "40 findings" in captured.out and "pattern-kill ×40" in captured.out and "40 new" in captured.out
    assert len(captured.err.splitlines()) <= 6 and "…and 35 more of the 40" in captured.err
    assert len(captured.out) + len(captured.err) < 1500
    row = lines(project)[-1]
    assert (row["command"], row["task"], row["exit"], row["scope"]) == ("worker check", "t-task", 1, "full")
    assert row["output_chars"] == len(captured.out) and row["report_path"] == ".lapis/state/t-task.workers.json"


def test_worker_check_of_a_clean_transcript_still_says_what_it_read(project, capsys):
    transcript = project / "agent.jsonl"
    transcript.write_text(json.dumps({"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}) + "\n")
    assert cli_main(["worker", "check", "--task", "t-task", "--transcript", str(transcript), "--root", str(project)]) == 0
    assert "nothing in agent.jsonl" in capsys.readouterr().out and lines(project)[-1]["exit"] == 0


def test_a_usage_error_found_once_the_run_began_is_still_one_line_in_the_log(project, captures):
    with pytest.raises(SystemExit) as stop:
        render.main(["file:///no/such/page.html", "--task", "t"])
    assert stop.value.code == 2 and captures.calls == []
    assert [(row["command"], row["exit"], row["cache"]) for row in lines(project)] == [("render check", 2, "off")]
