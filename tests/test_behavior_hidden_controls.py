"""A control that no pointer can hit is reached the way a person would reach it, or recorded as not
reachable; one such control never skips a probe. Loopback pages: custom radios and a checkbox that are
visually hidden behind visible labels, a page whose hidden checkbox and off-screen link nothing visible can
toggle or show, a skip link that slides in on focus, a label with a link in its middle, and labels that do
not toggle, leave the page, or are covered by another input's label (one press, then stop)."""
from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError

from lapis_design.behavior_check import settle
from lapis_design.behavior_check.driver import Driver, NotReachable
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
    # A run that cannot finish names what it could not press, and so does the one that finished.
    assert never["status"] == "blocked"
    reason = _coverage(document, "flows")["reason"]
    assert "d/visit-0: completed (계속 진행: not reachable by pointer" in reason
    assert "d/visit-1: blocked (goal not reached; 계속 진행: not reachable by pointer" in reason


def test_flow_that_finishes_still_reports_what_it_could_not_press(browser, site):
    document = _run(browser, site, "unreachable.html", flows)
    (done,) = document["flows"]
    assert done["status"] == "completed" and _actions(done) == ["type", "click"]
    coverage = _coverage(document, "flows")
    assert coverage["status"] == "partial"
    assert coverage["reason"].startswith("d/visit-0: completed (계속 진행: not reachable by pointer")


def test_flow_does_not_call_an_error_after_the_press_a_control_nothing_reaches(browser, site, monkeypatch):
    quiet = settle.quiet

    def failing(driver, mutations):
        if driver._acted:               # the action ran, and reading what it did fails
            raise PlaywrightError("the page went away while its effect was read")
        return quiet(driver, mutations)

    monkeypatch.setattr(settle, "quiet", failing)
    with pytest.raises(PlaywrightError, match="went away"):
        _run(browser, site, "unreachable.html", flows)


@contextlib.contextmanager
def _page(browser, site, name):
    session = Session(site + name, "hidden-controls", engine=StubEngine.load(STUB))
    session.contexts = {"d": session.contexts["d"]}
    driver = Driver(browser, session, "d")
    driver.open()
    try:
        yield driver
    finally:
        driver.close()


def _box(driver, element_id):
    driver.boxes()
    return driver.page.evaluate("id => document.getElementById(id).getAttribute('data-lapis-box')", element_id)


def test_a_label_with_a_link_in_its_middle_is_pressed_beside_the_link(browser, site):
    with _page(browser, site, "link-label.html") as driver:
        driver.act({"kind": "check", "target": _box(driver, "terms")})
        assert driver.page.url == site + "link-label.html"
        assert driver.page.evaluate("document.getElementById('terms').checked") is True


def test_flow_agrees_to_terms_through_a_label_that_holds_a_link(browser, site):
    document = _run(browser, site, "link-label.html", flows, flow_done=("가입 완료",))
    (run,) = document["flows"]
    assert run["status"] == "completed" and _actions(run) == ["click", "check", "click"]
    assert {step["path"] for step in run["steps"]} == {"/link-label.html"}
    assert _coverage(document, "flows") == {"probe": "flows", "status": "ran", "contexts": ["d"]}


def test_a_wrapper_that_only_holds_another_inputs_label_is_not_pressed(browser, site):
    with _page(browser, site, "press-points.html") as driver:
        with pytest.raises(NotReachable, match="inside another link, button, or input's label"):
            driver.act({"kind": "check", "target": _box(driver, "solo")})
        assert driver.page.evaluate("document.getElementById('other').checked") is False


def test_a_label_that_does_not_toggle_is_pressed_once_and_the_next_one_is_left_alone(browser, site):
    with _page(browser, site, "press-points.html") as driver:
        with pytest.raises(NotReachable, match="did not change it"):
            driver.act({"kind": "check", "target": _box(driver, "twice-box")})
        assert driver.page.evaluate("window.presses") == {"first": 1, "second": 0}


def test_a_press_that_leaves_the_page_is_not_a_check(browser, site):
    with _page(browser, site, "press-points.html") as driver:
        with pytest.raises(NotReachable, match="left the page"):
            driver.act({"kind": "check", "target": _box(driver, "leaves-box")})
        assert driver.page.url == site + "terms.html"


def test_a_control_the_page_replaces_in_response_to_the_press_counts_as_pressed(browser, site):
    # The state of the replaced control cannot be read, and the page is the same document: it reacted.
    with _page(browser, site, "press-points.html") as driver:
        driver.act({"kind": "check", "target": _box(driver, "swaps-box")})
        assert driver.page.url == site + "press-points.html"
        assert driver.page.evaluate("document.getElementById('swaps-box').checked") is True


def test_pressing_a_label_records_the_state_of_the_transparent_input_it_stands_for(browser, site):
    with _page(browser, site, "press-points.html") as driver:
        label = _box(driver, "clear-label")
        assert _box(driver, "clear-box") is None            # the input has no box: the label's box is what to address
        effect = driver.act({"kind": "check", "target": label})
        assert driver.page.evaluate("document.getElementById('clear-box').checked") is True
        assert effect["outcome"] == "state-changed"
        assert effect["aria_changes"] == [{"box": label, "attr": "aria-checked", "from": "false", "to": "true"}]


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
