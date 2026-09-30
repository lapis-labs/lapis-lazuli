"""Browser evidence for control and commit probes against a synthetic reservation desk."""
from __future__ import annotations

import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import commits, controls, flows
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine

APP = Path(__file__).parent / "fixtures" / "behavior" / "controls-commits"
POTTERY = Path(__file__).parent / "fixtures" / "behavior" / "flows-pottery"
PLAN = Path(__file__).parents[1] / "src" / "shared" / "plan" / "example.plan.yaml"


@pytest.fixture
def desk_server():
    class SilentHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SilentHandler, directory=str(APP)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def pottery_server():
    class SpaHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] not in ("/", "/index.html", "/app.js"):
                self.path = "/index.html"
            super().do_GET()

        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SpaHandler, directory=str(POTTERY)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_flow_commit_steps_are_replayed_into_commit_probes(browser, pottery_server):
    plan = yaml.safe_load(PLAN.read_text())
    session = Session(pottery_server, "kiln-shop-landing",
                      engine=StubEngine.load(POTTERY / "pottery.stub.yaml"), plan=plan)
    session.contexts = {"m": session.contexts["m"]}
    drivers = []
    def open_driver(ctx):
        driver = Driver(browser, session, ctx)
        driver.open()
        drivers.append(driver)
        return driver
    try:
        flows.run(session, open_driver)
        commits.run(session, open_driver)
        document = session.document()
    finally:
        for driver in drivers:
            driver.close()
    by_flow = {entry.get("flow"): entry for entry in document["probes"]["commits"]}
    assert by_flow["reserve-piece"]["kind"] == "reserve"
    assert by_flow["firing-notices"]["kind"] == "subscribe"
    # The exit flow's commit exists only in the state its pair left; the pair run seeds it.
    exit_commit = by_flow["stop-firing-notices"]
    assert exit_commit["kind"] == "cancel" and exit_commit["destructive"] is True
    assert exit_commit["double_activation"]["effects"] == 1          # the pair's own effects are not counted
    for entry in (by_flow["reserve-piece"], by_flow["firing-notices"], exit_commit):
        assert {row["injected"]: row["actual"] for row in entry["outcomes"]} == {
            "none": "applied", "fail-5xx": "not-applied", "fail-network": "not-applied",
            "hang": "applied", "forbidden": "not-applied"}
    assert "confirm" in exit_commit and "undo" in exit_commit
    coverage = next(entry for entry in document["coverage"] if entry["probe"] == "commits")
    assert coverage == {"probe": "commits", "status": "ran", "contexts": ["m"]}

    # Without the pair's run the exit commit is not guessed at: it is partial with the reason.
    session.probes["commits"], session.coverage = [], []
    session.flows = [run for run in session.flows if run["id"] == "stop-firing-notices"]
    try:
        commits.run(session, open_driver)
    finally:
        for driver in drivers:
            driver.close()
    assert not session.probes["commits"]
    assert session.coverage[0]["status"] == "partial"
    assert "pair run firing-notices missing" in session.coverage[0]["reason"]


def test_controls_commits_observe_good_and_bad_behaviors(browser, desk_server):
    session = Session(desk_server, "reservation-desk", engine=StubEngine.load(APP / "desk.stub.yaml"))
    drivers = []
    def open_driver(ctx):
        driver = Driver(browser, session, ctx)
        driver.open()
        drivers.append(driver)
        return driver
    started = time.monotonic()
    try:
        controls.run(session, open_driver)
        commits.run(session, open_driver)
        document = session.document()  # validates the complete document against session.schema.yaml
    finally:
        for driver in drivers:
            driver.close()
    elapsed = time.monotonic() - started
    by_name = {session.nodes[item["box"]].get("name"): item for item in document["probes"]["controls"] if item["context"] == "d"}
    assert by_name["Dead button"]["effect"]["outcome"] == "no-effect"
    assert by_name["Show details"]["keyboard"] == {"focusable": True, "activation": "different"}
    # Nothing on the pointer and nothing on the keyboard is the same effect: the dead-control finding covers it
    assert by_name["Dead button"]["keyboard"]["activation"] == "same"
    assert by_name["Guest name"]["keyboard"]["activation"] == "same"          # a text field takes focus only
    assert by_name["Window seat"]["effect"]["outcome"] == "state-changed"
    assert by_name["Window seat"]["keyboard"]["activation"] == "same"         # a checkbox activates with Space only
    assert by_name["Reserve seat"]["promise"] == "other"
    assert {item["context"] for item in document["probes"]["controls"]} == {"m", "d"}
    commits_by_name = {session.nodes[item["box"]].get("name"): item for item in document["probes"]["commits"] if item["context"] == "d"}
    good = commits_by_name["Reserve seat"]
    assert next(item for item in commits_by_name["Save falsely"]["outcomes"] if item["injected"] == "fail-5xx")["actual"] == "not-applied"
    bad = commits_by_name["Reserve without guard"]
    assert good["kind"] == bad["kind"] == "reserve"
    assert good["double_activation"]["effects"] == 1
    assert good["double_activation"]["pending_shown"] is True
    assert bad["double_activation"]["effects"] == 2
    assert next(item for item in commits_by_name["Save falsely"]["outcomes"] if item["injected"] == "fail-5xx")["claimed"] == "success"
    assert next(item for item in good["outcomes"] if item["injected"] == "hang")["actual"] == "applied"
    assert {row["injected"]: row["actual"] for row in good["outcomes"]} == {
        "none": "applied", "fail-5xx": "not-applied", "fail-network": "not-applied",
        "hang": "applied", "forbidden": "not-applied"}
    assert next(row for row in good["outcomes"] if row["injected"] == "fail-5xx")["claimed"] == "failure"
    assert next(row for row in good["outcomes"] if row["injected"] == "fail-5xx")["input_kept"] is True
    assert next(row for row in good["outcomes"] if row["injected"] == "fail-5xx")["announced"] is True
    deleted = commits_by_name["Confirm deletion"]
    assert deleted["confirm"]["shown"] and deleted["confirm"]["names_object"]
    assert deleted["undo"]["offered"] and deleted["undo"]["restores"] and deleted["undo"]["survives_reload"]
    assert commits_by_name["Delete without confirmation"]["confirm"] == {"shown": False}
    assert {entry["status"] for entry in document["coverage"] if entry["probe"] in ("controls", "commits")} == {"ran"}
    assert [entry["probe"] for entry in document["coverage"]] == ["controls", "commits"]
    print(f"controls+commits m/d runtime: {elapsed:.2f}s")


def test_declared_flow_commit_without_backend_effect_is_not_missed(browser, desk_server):
    session = Session(desk_server, "reservation-desk", engine=StubEngine.load(APP / "desk.stub.yaml"))
    session.contexts.pop("m")
    drivers = []
    def open_driver(ctx):
        driver = Driver(browser, session, ctx)
        driver.open()
        drivers.append(driver)
        return driver
    try:
        controls.run(session, open_driver)
        preview = next(item for item in session.probes["controls"]
                       if session.nodes[item["box"]].get("name") == "Submit preview")
        assert all(req.get("effects", 0) == 0 for req in preview["effect"]["requests"])
        session.add_flow_run({"id": "preview", "context": "d", "kind": "primary", "status": "completed",
                              "steps": [{"index": 0, "path": "/", "actions": [{"kind": "click",
                                         "target": preview["box"]}]}], "commit_step": 0,
                              "effort": {"steps": 1, "interactions": 1}})
        commits.run(session, open_driver)
        document = session.document()
    finally:
        for driver in drivers:
            driver.close()
    observed = next(entry for entry in document["probes"]["commits"] if entry["box"] == preview["box"])
    assert observed["flow"] == "preview" and observed["kind"] == "submit"
    assert next(row for row in observed["outcomes"] if row["injected"] == "none")["actual"] == "not-applied"



def test_local_backend_omits_destructive_actions_and_unsafe_commits(browser, desk_server):
    session = Session(desk_server, "reservation-desk", backend="local-dev", outbound="restricted")
    session.contexts.pop("m")
    drivers = []
    def open_driver(ctx):
        driver = Driver(browser, session, ctx)
        driver.open()
        drivers.append(driver)
        return driver
    try:
        controls.run(session, open_driver)
        commits.run(session, open_driver)
        document = session.document()
    finally:
        for driver in drivers:
            driver.close()
    assert not any(entry["promise"] == "destructive" for entry in document["probes"]["controls"])
    assert not document["probes"].get("commits")
    assert {entry["probe"]: entry["status"] for entry in document["coverage"]} == {"controls": "partial", "commits": "skipped"}
