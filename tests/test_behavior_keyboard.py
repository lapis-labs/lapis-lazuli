"""Browser-level keyboard walks against synthetic, local multi-route fixtures."""
from __future__ import annotations

import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema
import pytest
import yaml

from lapis_design import shared_dir
from lapis_design.behavior_check import probes
from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import keyboard
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine

APP = Path(__file__).parent / "fixtures" / "behavior" / "keyboard-app"
STUB = APP / "keyboard.stub.yaml"


@pytest.fixture
def keyboard_server():
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(APP)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_keyboard_routes_and_observations(browser, keyboard_server, monkeypatch):
    schema = yaml.safe_load((shared_dir() / "behavior" / "stub.schema.yaml").read_text())
    jsonschema.Draft202012Validator(schema).validate(yaml.safe_load(STUB.read_text()))
    session = Session(keyboard_server, "keyboard", engine=StubEngine.load(STUB),
                      plan={"flows": [{"id": "jump-flow", "start": "/jump/", "done": {"route": "/second/"}}]})
    monkeypatch.setattr(probes, "PROBES", (keyboard,))
    def open_driver(ctx):
        driver = Driver(browser, session, ctx)
        driver.open()
        return driver
    start = time.monotonic()
    keyboard.run(session, open_driver)
    elapsed = time.monotonic()-start
    document = session.document()
    session_schema = yaml.safe_load((shared_dir() / "behavior" / "session.schema.yaml").read_text())
    jsonschema.Draft202012Validator(session_schema).validate(document)
    walks = document["probes"]["keyboard"]
    assert len(walks) == 10
    assert {(w["context"],w["path"]) for w in walks} == {
        (ctx,path) for ctx in ("m","d") for path in ("/","/jump/","/second/","/exittrap/","/linked/")}
    assert [w["path"] for w in walks if w["context"] == "d"] == [
        "/","/jump/","/second/","/exittrap/","/linked/"]
    for ctx in ("m","d"):
        home = next(w for w in walks if w["context"] == ctx and w["path"] == "/")
        jump = next(w for w in walks if w["context"] == ctx and w["path"] == "/jump/")
        second = next(w for w in walks if w["context"] == ctx and w["path"] == "/second/")
        escaped = next(w for w in walks if w["context"] == ctx and w["path"] == "/exittrap/")
        linked = next(w for w in walks if w["context"] == ctx and w["path"] == "/linked/")
        by_name = {s["name"]:s for s in home["stops"]}
        assert home["completed"] is True
        assert home["reverse_matches"] is True
        assert home["skip_link"]["lands_at"] == by_name["Covered control"]["index"]
        assert home["presses_to_main"] == by_name["Covered control"]["index"] + 1
        assert home["landmarks"]["main"] is True
        assert {"banner","navigation","main","contentinfo"} <= set(home["landmarks"]["roles"])
        assert any(h["level"]==1 and h["next_stop"]==by_name["Covered control"]["index"]
                   for h in home["headings"])
        assert by_name["Outline control"]["indicator"]["area_px"] > 0
        assert by_name["Outline control"]["focus_visible"] is True
        assert by_name["Quiet control"]["focus_visible"] is False
        assert by_name["Outline control"]["indicator"]["contrast"] >= 3
        assert by_name["Quiet control"]["context_change"] == "none"
        assert by_name["Outline control"]["obscured_share"] == 0
        assert by_name["Covered control"]["obscured_share"] > 0
        assert by_name["Covered control"]["obscured_by"] in document["nodes"]
        assert home["derived"]["order_inversions"] >= 1
        assert home["derived"]["repeated_stops"] >= 2
        assert any(u["semantic"] is False for u in home["unreachable"])
        assert any(u["semantic"] is True for u in home["unreachable"])
        assert by_name["Tile A"]["container"] in home["containers"]
        assert home["containers"][by_name["Tile A"]["container"]]["parent"] in home["containers"]
        assert jump["completed"] is False
        assert any(s["name"] == "Move on focus" and s["context_change"] == "navigated"
                   for s in jump["stops"])
        assert second["skip_link"]["lands_at"] is None
        assert second["completed"] is False
        assert second["traps"] and second["traps"][0]["escape_leaves"] is False
        assert {document["nodes"][bid]["name"] for bid in second["traps"][0]["boxes"]} == {"Widget A","Widget B"}
        assert "unreachable" not in second
        assert escaped["traps"] and escaped["traps"][0]["escape_leaves"] is True
        assert escaped["completed"] is False
        assert linked["completed"] is True
        deep_stops = {s["name"]:s for s in linked["stops"]}
        for name in ("First task", "Second task"):
            stop = deep_stops[name]
            assert stop["rect"]["y"] > 2*session.contexts[ctx]["height"]
            assert stop["indicator"]["area_px"] > 0
            assert stop["focus_visible"] is True
    assert next(c for c in document["coverage"] if c["probe"]=="keyboard")["status"] == "partial"
    print(f"keyboard fixture runtime: {elapsed:.2f}s for ten walks")

def test_no_keyboard_targets_is_not_applicable(browser, keyboard_server):
    session = Session(keyboard_server + "empty/", "empty", engine=StubEngine.load(STUB))
    def open_driver(ctx):
        driver = Driver(browser, session, ctx)
        driver.open()
        return driver
    keyboard.run(session, open_driver)
    doc = session.document()
    assert len(doc["probes"]["keyboard"]) == 2
    assert all(w["completed"] and w["presses"] == 0 and not w["stops"]
               for w in doc["probes"]["keyboard"])
    assert next(c for c in doc["coverage"] if c["probe"]=="keyboard")["status"] == "not-applicable"
