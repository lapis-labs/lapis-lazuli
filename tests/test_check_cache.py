"""One run per build and state: the identity of the served tree, the stored result, the lock, and what a stylesheet
change can reach. Nothing here starts a browser: a fake producer writes the report."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from lapis_design import check_cache, telemetry

PAGE = "<!doctype html><title>t</title><link rel=stylesheet href=style.css><script src=app.js></script><h1>hi</h1>"
CSS = "body{margin:0}\nh1{font-size:32px}\n@media (max-width: 500px){ h1{font-size:20px} }\n"


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(PAGE)
    (site / "style.css").write_text(CSS)
    (site / "app.js").write_text("console.log(1)")
    (site / "font.woff2").write_bytes(b"\x00\x01font")
    (site / ".env").write_text("secret=1")                 # a dotted name is never served
    monkeypatch.chdir(tmp_path)
    return tmp_path


def served(project: Path, query: str = "") -> check_cache.Served:
    found = check_cache.served((project / "site" / "index.html").as_uri() + query, project)
    assert found is not None
    return found


def key_of(project: Path, query: str = "", **params) -> check_cache.Key:
    return check_cache.make_key("render", served(project, query), {"task": "t", **params}, {"widths": [320], "out": "t.json"})


def producer(out: Path, calls: list, *, shots: Path | None = None, code: int = 0, seconds: float = 0.0):
    def produce() -> int:
        calls.append(1)
        time.sleep(seconds)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"call": len(calls)}) + "\n")
        if shots is not None:
            shots.mkdir(parents=True, exist_ok=True)
            (shots / "00.png").write_bytes(b"png" + bytes([len(calls)]))
        return code
    return produce


# -------------------------------------------------------------------------------- identity

def test_the_build_id_covers_every_file_the_server_answers_for(project):
    before = served(project).build_id
    assert served(project).build_id == before
    for name, content in (("style.css", CSS + "p{color:red}"), ("app.js", "console.log(2)"),
                          ("font.woff2", b"\x00\x02font")):
        path = project / "site" / name
        original = path.read_bytes()
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        assert served(project).build_id != before, name
        path.write_bytes(original)
    (project / "site" / "img").mkdir()
    (project / "site" / "img" / "a.png").write_bytes(b"png")
    assert served(project).build_id != before                    # a new asset
    assert served(project).build_id == served(project).build_id


def test_a_file_the_server_never_serves_does_not_change_the_build(project):
    before = served(project).build_id
    (project / "site" / ".env").write_text("secret=2")
    (project / "site" / ".git").mkdir()
    (project / "site" / ".git" / "HEAD").write_text("x")
    assert served(project).build_id == before


def test_the_state_key_separates_query_params_selection_and_day(project, monkeypatch):
    base = key_of(project)
    assert key_of(project).state_key == base.state_key and key_of(project).build_id == base.build_id
    assert key_of(project, "?footer=fluid").state_key != base.state_key       # a state of the same build
    assert key_of(project, "?footer=fluid").build_id == base.build_id
    assert key_of(project, public=True).state_key != base.state_key
    other = check_cache.make_key("render", served(project), {"task": "t"}, {"widths": [390], "out": "t.json"})
    assert other.state_key != base.state_key
    monkeypatch.setattr(check_cache, "date", type("D", (), {"today": staticmethod(lambda: __import__("datetime").date(2030, 1, 1))}))
    assert key_of(project).state_key != base.state_key


def test_an_address_the_cli_does_not_serve_has_no_identity(project):
    assert check_cache.served("http://127.0.0.1:9/", project) is None
    assert check_cache.served("https://example.com/", project) is None


def test_a_folder_too_large_to_hash_has_no_identity(project, monkeypatch):
    monkeypatch.setattr(check_cache, "MAX_FILES", 2)
    assert check_cache.tree_manifest(project / "site") is None
    assert check_cache.served((project / "site" / "index.html").as_uri(), project) is None


# -------------------------------------------------------------------------------- reuse

def test_an_identical_request_is_a_hit_that_restores_the_same_bytes_and_screenshots(project):
    out, shots, calls = project / ".lapis/renders/t.json", project / ".lapis/renders/t.shots", []
    key = key_of(project)
    first = check_cache.run(project, key, out=out, shots=shots, fresh=False, produce=producer(out, calls, shots=shots))
    assert (first.cache, first.exit, len(calls)) == ("miss", 0, 1)
    stored = out.read_bytes()
    out.unlink()
    for shot in shots.iterdir():
        shot.unlink()
    again = check_cache.run(project, key_of(project), out=out, shots=shots, fresh=False,
                            produce=producer(out, calls, shots=shots))
    assert (again.cache, len(calls)) == ("hit", 1)                     # the producer did not run
    assert out.read_bytes() == stored and (shots / "00.png").read_bytes() == b"png\x01"
    assert (again.build_id, again.state_key) == (key.build_id, key.state_key)


def test_a_changed_file_or_request_is_a_miss_and_never_reuses_the_old_result(project):
    out, calls = project / "t.json", []
    run = lambda key: check_cache.run(project, key, out=out, shots=None, fresh=False, produce=producer(out, calls))
    assert run(key_of(project)).cache == "miss"
    assert run(key_of(project, "?q=1")).cache == "miss"
    (project / "site" / "style.css").write_text(CSS + "p{margin:0}")
    changed = run(key_of(project))
    assert changed.cache == "miss" and json.loads(out.read_text())["call"] == len(calls) == 3
    assert run(key_of(project)).cache == "hit" and json.loads(out.read_text())["call"] == 3
    (project / "site" / "app.js").write_text("console.log(3)")
    assert run(key_of(project)).cache == "miss"
    (project / "site" / "font.woff2").write_bytes(b"new")
    assert run(key_of(project)).cache == "miss"
    assert len(calls) == 5


def test_fresh_runs_again_and_replaces_the_stored_result(project):
    out, calls = project / "t.json", []
    key = key_of(project)
    check_cache.run(project, key, out=out, shots=None, fresh=False, produce=producer(out, calls))
    forced = check_cache.run(project, key, out=out, shots=None, fresh=True, produce=producer(out, calls))
    assert (forced.cache, forced.reason, len(calls)) == ("off", "--fresh", 2)
    reused = check_cache.run(project, key, out=out, shots=None, fresh=False, produce=producer(out, calls))
    assert reused.cache == "hit" and json.loads(out.read_text())["call"] == 2 and len(calls) == 2


def test_no_key_runs_as_it_always_did(project):
    out, calls = project / "t.json", []
    outcome = check_cache.run(project, None, out=out, shots=None, fresh=False, produce=producer(out, calls))
    again = check_cache.run(project, None, out=out, shots=None, fresh=False, produce=producer(out, calls))
    assert (outcome.cache, again.cache, len(calls)) == ("off", "off", 2)
    assert not (project / ".lapis").exists()


def test_a_failed_run_is_never_stored(project):
    out, calls = project / "t.json", []
    key = key_of(project)
    assert check_cache.run(project, key, out=out, shots=None, fresh=False,
                           produce=producer(out, calls, code=2)).exit == 2
    again = check_cache.run(project, key, out=out, shots=None, fresh=False, produce=producer(out, calls))
    assert again.cache == "miss" and len(calls) == 2
    assert not list((project / ".lapis/cache/checks/locks").glob("*.lock"))          # the failed call released its lock


def test_a_run_the_build_cannot_account_for_is_not_stored(project):
    out, calls = project / "t.json", []
    key = key_of(project)
    unstable = check_cache.run(project, key, out=out, shots=None, fresh=False, produce=producer(out, calls),
                               stable=lambda: "the page asked other origins (http://127.0.0.1:1)")
    assert unstable.cache == "off" and "other origins" in unstable.reason
    assert check_cache.run(project, key, out=out, shots=None, fresh=False, produce=producer(out, calls)).cache == "miss"
    assert len(calls) == 2


def test_origins_the_page_asked_for_besides_its_own_are_named():
    assert check_cache.foreign_origins({"http://127.0.0.1:5", "http://127.0.0.1:9"}, "http://127.0.0.1:5") == ["http://127.0.0.1:9"]
    assert check_cache.foreign_origins({"http://127.0.0.1:5"}, "http://127.0.0.1:5") == []


# -------------------------------------------------------------------------------- one run for concurrent identical calls

def test_concurrent_identical_calls_run_the_producer_once_and_share_its_result(project):
    out_a, out_b, calls, results = project / "a.json", project / "b.json", [], {}
    key = key_of(project)

    def go(name: str, out: Path, delay: float) -> None:
        time.sleep(delay)
        results[name] = check_cache.run(project, key, out=out, shots=None, fresh=False,
                                        produce=producer(out, calls, seconds=1.0), poll=0.05)

    first = threading.Thread(target=go, args=("a", out_a, 0.0))
    second = threading.Thread(target=go, args=("b", out_b, 0.3))
    first.start(); second.start(); first.join(); second.join()
    assert len(calls) == 1
    assert sorted(r.cache for r in results.values()) == ["join", "miss"]
    assert results["b"].cache == "join" and results["b"].waited > 0.3
    assert out_a.read_bytes() == out_b.read_bytes()


def test_concurrent_processes_share_one_run(project):
    script = ("import json, sys, time\nfrom pathlib import Path\nfrom lapis_design import check_cache\n"
              "project = Path.cwd()\nserved = check_cache.served((project / 'site' / 'index.html').as_uri(), project)\n"
              "key = check_cache.make_key('render', served, {'task': 't'}, {'widths': [320], 'out': 'o.json'})\n"
              "out = Path(sys.argv[1])\n"
              "def produce():\n    Path('ran-' + out.name).write_text('1'); time.sleep(1.5); out.write_text('{}\\n'); return 0\n"
              "print(check_cache.run(project, key, out=out, shots=None, fresh=False, produce=produce, poll=0.05).cache)\n")
    procs = [subprocess.Popen([sys.executable, "-c", script, name], cwd=project, stdout=subprocess.PIPE, text=True)
             for name in ("one.json", "two.json")]
    results = sorted(p.communicate(timeout=60)[0].strip() for p in procs)
    assert results == ["join", "miss"]
    assert len(list(project.glob("ran-*"))) == 1


def test_a_lock_of_a_dead_process_is_broken_and_the_run_goes_ahead(project):
    out, calls = project / "t.json", []
    key = key_of(project)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    lock = project / ".lapis/cache/checks/locks" / f"render-{key.state_key}.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": dead.pid, "started": time.time()}))
    outcome = check_cache.run(project, key, out=out, shots=None, fresh=False, produce=producer(out, calls), poll=0.05)
    assert (outcome.cache, len(calls)) == ("miss", 1) and not lock.exists()


def test_a_lock_nobody_has_touched_for_a_minute_is_stale_even_when_its_pid_lives(project):
    import os

    out, calls = project / "t.json", []
    key = key_of(project)
    lock = project / ".lapis/cache/checks/locks" / f"render-{key.state_key}.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": os.getpid(), "started": time.time()}))
    os.utime(lock, (time.time() - 3600, time.time() - 3600))
    outcome = check_cache.run(project, key, out=out, shots=None, fresh=False, produce=producer(out, calls), poll=0.05)
    assert outcome.cache == "miss" and len(calls) == 1


def test_a_waiter_takes_over_when_the_running_call_fails(project):
    out_a, out_b, calls, results = project / "a.json", project / "b.json", [], {}
    key = key_of(project)

    def go(name: str, out: Path, delay: float, code: int) -> None:
        time.sleep(delay)
        results[name] = check_cache.run(project, key, out=out, shots=None, fresh=False,
                                        produce=producer(out, calls, seconds=0.8, code=code), poll=0.05)

    a = threading.Thread(target=go, args=("a", out_a, 0.0, 2))
    b = threading.Thread(target=go, args=("b", out_b, 0.3, 0))
    a.start(); b.start(); a.join(); b.join()
    assert (results["a"].exit, results["a"].cache) == (2, "miss")
    assert (results["b"].exit, results["b"].cache, len(calls)) == (0, "miss", 2)


# -------------------------------------------------------------------------------- which report came from which build

def test_a_report_is_known_only_while_it_is_the_file_the_cache_wrote(project):
    out, calls = project / ".lapis/renders/t.json", []
    key = key_of(project)
    check_cache.run(project, key, out=out, shots=None, fresh=False, produce=producer(out, calls))
    assert check_cache.previous(project, out)["state_key"] == key.state_key
    out.write_text('{"edited": true}\n')
    assert check_cache.previous(project, out) is None
    assert check_cache.previous(project, project / "never.json") is None


# -------------------------------------------------------------------------------- what a stylesheet change can reach

def stored(page: check_cache.Served) -> dict:
    return {"tree": page.manifest, "css": json.loads(json.dumps(page.css))}


def reach(project: Path, before: dict) -> frozenset[int] | None:
    return check_cache.affected_widths(before, served(project))[0]


def edit(project: Path, name: str, text: str) -> None:
    (project / "site" / name).write_text(text)


def test_nothing_changed_reaches_no_width(project):
    assert reach(project, stored(served(project))) == frozenset()


@pytest.mark.parametrize("css, widths", [
    (CSS.replace("font-size:20px", "font-size:22px"), {320, 390}),                        # inside max-width: 500px
    (CSS + "@media (min-width: 1000px){ h1{color:red} }\n", {1440}),
    (CSS + "@media (min-width: 350px) and (max-width: 800px){ h1{color:red} }\n", {390, 768}),
    (CSS + "@media screen and (min-width: 48em){ h1{color:red} }\n", {768, 1440}),          # em is 16 px
    (CSS + "@media (min-width: 2000px){ h1{color:red} }\n", set()),                          # matches no capture width
    (CSS + "/* a note */", set()),                                                           # comment only
    (CSS.replace("\n", "\n\n   "), set()),                                                   # whitespace only
])
def test_a_stylesheet_change_confined_to_width_queries_reaches_only_those_widths(project, css, widths):
    before = stored(served(project))
    edit(project, "style.css", css)
    assert reach(project, before) == frozenset(widths)


@pytest.mark.parametrize("css", [
    CSS.replace("margin:0", "margin:1px"),                                    # a rule outside any query
    CSS + ":root{--gap:4px}\n",                                               # a custom property, shared by everything
    CSS + "@font-face{font-family:x;src:url(a.woff2)}\n",
    CSS + "@keyframes spin{to{opacity:0}}\n",
    CSS + "@supports (display:grid){ h1{color:red} }\n",
    CSS + "@media (prefers-color-scheme: dark){ h1{color:red} }\n",           # not a width query
    CSS + "@media (min-width: 40rem) and (orientation: landscape){ h1{color:red} }\n",
    CSS + "@media not all and (min-width: 400px){ h1{color:red} }\n",
    CSS + "@media (width >= 400px){ h1{color:red} }\n",                       # range syntax is not proven
    CSS + '@import url("more.css");\n',
])
def test_a_stylesheet_change_outside_a_width_query_reaches_every_width(project, css):
    before = stored(served(project))
    edit(project, "style.css", css)
    assert reach(project, before) is None


def test_reordering_a_width_query_against_global_rules_reaches_only_where_it_applies(project):
    # the query's own widths: where it does not apply, its position among the global rules changes nothing
    before = stored(served(project))
    edit(project, "style.css", "@media (max-width: 500px){ h1{font-size:20px} }\nbody{margin:0}\nh1{font-size:32px}\n")
    assert reach(project, before) == frozenset({320, 390})


def test_reordering_two_global_rules_reaches_every_width(project):
    before = stored(served(project))
    edit(project, "style.css", "h1{font-size:32px}\nbody{margin:0}\n@media (max-width: 500px){ h1{font-size:20px} }\n")
    assert reach(project, before) is None


@pytest.mark.parametrize("name, content", [("app.js", "console.log(2)"), ("index.html", PAGE + "<p>x</p>"),
                                           ("font.woff2", b"other"), ("new.png", b"png")])
def test_a_changed_script_page_font_or_asset_reaches_every_width(project, name, content):
    before = stored(served(project))
    path = project / "site" / name
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    assert reach(project, before) is None


def test_a_removed_or_added_stylesheet_reaches_every_width(project):
    before = stored(served(project))
    (project / "site" / "extra.css").write_text("@media (max-width: 500px){ h1{color:red} }")
    assert reach(project, before) is None
    (project / "site" / "extra.css").unlink()
    (project / "site" / "style.css").unlink()
    assert reach(project, before) is None


def test_a_stylesheet_the_entry_has_no_signature_for_reaches_every_width(project):
    before = stored(served(project))
    before["css"].pop("style.css")
    edit(project, "style.css", CSS.replace("20px", "21px"))
    assert reach(project, before) is None


@pytest.mark.parametrize("condition, widths", [
    ("(max-width: 640px)", {320, 390}), ("screen and (min-width: 768px)", {768, 1440}),
    ("only screen and (min-width: 391px) and (max-width: 1000px)", {768}),
    ("(max-width: 400px), (min-width: 1400px)", {320, 390, 1440}), ("all", {320, 390, 768, 1440}),
    ("(max-width: 25em)", {320, 390}),
])
def test_media_widths_reads_the_conditions_it_can_prove(condition, widths):
    assert check_cache.media_widths(condition) == frozenset(widths)


@pytest.mark.parametrize("condition", ["print", "(hover: hover)", "(min-width: 400px) and (hover: hover)",
                                       "(max-width: calc(10px + 5px))", "(min-resolution: 2dppx)"])
def test_media_widths_gives_up_on_anything_else(condition):
    assert check_cache.media_widths(condition) is None


def test_comments_and_strings_do_not_confuse_the_statement_split():
    css = '/* } { */ a::after{content:"} {"}\n@media (max-width:500px){ b{c:d} }\n'
    assert len(check_cache.stylesheet_signature(css)) == 2


# -------------------------------------------------------------------------------- telemetry

def test_the_telemetry_line_carries_every_field_and_ignores_nothing_it_is_given(tmp_path):
    telemetry.record(tmp_path, command="render check", task="t", build_id="b", state_key="s", scope="narrow", cache="join",
                     started=telemetry.stamp(), ended=telemetry.stamp(), exit=0, output_chars=12,
                     report_path=Path("x.json"), extra="kept")
    telemetry.record(tmp_path, command="x", scope="bogus", cache="bogus")
    lines = [json.loads(line) for line in (tmp_path / ".lapis/telemetry/checks.jsonl").read_text().splitlines()]
    assert set(telemetry.FIELDS) <= set(lines[0]) and lines[0]["cache"] == "join" and lines[0]["extra"] == "kept"
    assert lines[0]["report_path"] == "x.json" and lines[0]["started"].endswith("+00:00")
    assert (lines[1]["scope"], lines[1]["cache"], lines[1]["task"]) == (None, None, None)


def test_a_telemetry_line_that_cannot_be_written_never_stops_the_check(tmp_path):
    blocker = tmp_path / ".lapis"
    blocker.write_text("a file where the folder should be")
    telemetry.record(tmp_path, command="x")


# -------------------------------------------------------------------------------- a preview we run

def test_a_page_on_the_port_of_a_live_preview_is_identified_by_the_folder_it_serves(project, monkeypatch):
    from lapis_design import preview

    (project / ".lapis/preview").mkdir(parents=True)
    (project / ".lapis/preview/t.json").write_text(json.dumps({"pid": 4242, "port": 4173, "dir": str(project / "site")}))
    monkeypatch.setattr(preview, "_alive", lambda record: record["port"] == 4173)
    found = check_cache.served("http://127.0.0.1:4173/index.html?x=1", project)
    assert found is not None and found.request == "/index.html?x=1" and found.build_id == served(project).build_id
    assert check_cache.served("http://127.0.0.1:4174/index.html", project) is None        # another port: not ours
    monkeypatch.setattr(preview, "_alive", lambda record: False)
    assert check_cache.served("http://127.0.0.1:4173/index.html", project) is None        # the recorded server is gone
