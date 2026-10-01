"""A control that no pointer can hit is reached the way a person would reach it, or recorded as not
reachable; one such control never skips a probe. Loopback pages: custom radios and a checkbox that are
visually hidden behind visible labels, a page whose hidden checkbox and off-screen link nothing visible can
toggle or show, and a skip link that slides in on focus."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import controls, flows, forms
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine

APP = Path(__file__).parent / "fixtures" / "behavior" / "hidden-controls"
STUB = APP / "hidden.stub.yaml"
GOAL = "Choose a department and review the visit"


@pytest.fixture(scope="module")
def site():
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(APP)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def _run(browser, site, page, probe, context="d", flow_done=("예약 내용을 확인해 주세요.",)):
    plan = {"flows": [{"id": f"visit-{index}", "kind": "primary", "goal": GOAL, "start": f"/{page}",
                       "done": {"text": done}, "requires": []} for index, done in enumerate(flow_done)]}
    session = Session(site + page, "hidden-controls", engine=StubEngine.load(STUB), plan=plan)
    session.contexts = {context: session.contexts[context]}
    drivers = []

    def open_driver(ctx):
        driver = Driver(browser, session, ctx)
        driver.open()
        drivers.append(driver)
        return driver

    try:
        probe.run(session, open_driver)
        return session.document()               # validates the document against session.schema.yaml
    finally:
        for driver in drivers:
            driver.close()


def _coverage(document, probe):
    return next(entry for entry in document["coverage"] if entry["probe"] == probe)


def _by_name(document):
    return {document["nodes"][row["box"]].get("name"): row for row in document["probes"]["controls"]}


def _actions(run):
    return [action["kind"] for step in run["steps"] for action in step["actions"]]


@pytest.mark.parametrize("context", ["m", "d"])
def test_controls_act_on_hidden_inputs_through_their_labels(browser, site, context):
    # One context per test, so the two take turns on different workers: labels are tapped in m, clicked in d.
    document = _run(browser, site, "labelled.html", controls, context)
    assert _coverage(document, "controls") == {"probe": "controls", "status": "ran", "contexts": [context]}
    rows = _by_name(document)
    for name in ("소화기내과", "호흡기내과", "방문 전날 문자로 알려 주세요"):
        row = rows[name]
        changes = [(change["attr"], change["from"], change["to"]) for change in row["effect"]["aria_changes"]
                   if change["box"] == row["box"]]
        assert changes == [("aria-checked", "false", "true")], name
        assert row["keyboard"]["activation"] == "same", name


@pytest.mark.parametrize("context", ["m", "d"])
def test_controls_press_a_skip_link_after_focus_brings_it_into_view(browser, site, context):
    document = _run(browser, site, "skip-link.html", controls, context)
    assert _coverage(document, "controls") == {"probe": "controls", "status": "ran", "contexts": [context]}
    # The link sits above the window until it takes focus: a person focuses it, then presses it where it appears.
    assert _by_name(document)["예약 안내로 바로 가기"]["effect"]["navigation"] == "same-document"


def test_flow_presses_a_skip_link_after_focus_brings_it_into_view(browser, site):
    document = _run(browser, site, "skip-link.html", flows, flow_done=("안내 구역에 도착했어요.",))
    (run,) = document["flows"]
    assert run["status"] == "completed" and _actions(run) == ["click"]
    assert _coverage(document, "flows") == {"probe": "flows", "status": "ran", "contexts": ["d"]}


def test_forms_set_hidden_radios_and_checkboxes_through_their_labels(browser, site):
    document = _run(browser, site, "labelled.html", forms)
    (form,) = document["probes"]["forms"]
    assert [field["kind"] for field in form["fields"]] == ["radio", "radio", "checkbox", "text"]
    # Each choice was changed once with no submit, and the run went on to the invalid-submit measurement.
    assert [field.get("on_change") for field in form["fields"]] == ["none", "none", "none", None]
    assert "invalid_submit" in form
    assert "not reachable" not in (_coverage(document, "forms").get("reason") or "")


def test_controls_record_a_control_nothing_visible_toggles_instead_of_timing_out(browser, site):
    document = _run(browser, site, "unreachable.html", controls)
    coverage = _coverage(document, "controls")
    assert coverage["status"] == "partial"
    hidden = next(box for box, node in document["nodes"].items() if node["rect"]["w"] == 1 and node["role"] == "input")
    assert f"d: {hidden}: not reachable by pointer" in coverage["reason"]
    # The controls a pointer can reach were still measured, and the link that is off screen is a gap too.
    assert {"환자 이름", "예약 내용 확인"} <= set(_by_name(document))
    assert "계속 진행: not reachable by pointer" in coverage["reason"]


def test_forms_record_a_choice_nothing_toggles_and_measure_the_rest(browser, site):
    document = _run(browser, site, "unreachable.html", forms)
    (form,) = document["probes"]["forms"]
    assert [field["kind"] for field in form["fields"]] == ["text", "checkbox"]
    assert "on_change" not in form["fields"][1]
    assert form["fields"][0]["paste_blocked"] is False and "invalid_submit" in form
    coverage = _coverage(document, "forms")
    assert coverage["status"] == "partial"
    assert f"checkbox {form['fields'][1]['box']} could not be changed (not reachable by pointer" in coverage["reason"]


def test_flow_goes_on_when_the_control_it_picked_cannot_be_pressed(browser, site):
    document = _run(browser, site, "unreachable.html", flows, flow_done=("예약 내용을 확인해 주세요.", "never shown"))
    done, never = document["flows"]
    # The off-screen "계속 진행" link ranks first and cannot be pressed: the run marks it tried and carries on.
    assert done["status"] == "completed" and _actions(done) == ["type", "click"]
    # A run that cannot finish names what it could not press.
    assert never["status"] == "blocked"
    assert "계속 진행: not reachable by pointer" in _coverage(document, "flows")["reason"]


def test_command_runs_controls_and_forms_instead_of_skipping_them(site, tmp_path):
    output = tmp_path / "unreachable.json"
    script = "import sys\nfrom lapis_design.behavior_check import main\nraise SystemExit(main(sys.argv[1:]))\n"
    result = subprocess.run(
        [sys.executable, "-c", script, site + "unreachable.html", "--task", "hidden", "--stub", str(STUB),
         "--context", "d", "--probe", "controls", "--probe", "forms", "--out", str(output)],
        capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr
    status = {entry["probe"]: entry["status"] for entry in json.loads(output.read_text())["coverage"]}
    assert status["controls"] == "partial" and status["forms"] == "partial"
