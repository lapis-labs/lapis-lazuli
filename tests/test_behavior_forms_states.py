"""Live loopback evidence for form and data-state probes."""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic

import pytest

from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import forms, states
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine

APP = Path(__file__).parent / "fixtures" / "behavior" / "forms-states-app"
BAD_APP = Path(__file__).parent / "fixtures" / "behavior" / "forms-states-bad"
POTTERY = Path(__file__).parent / "fixtures" / "behavior" / "flows-pottery"


@contextmanager
def _serve(directory):
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def probe_server():
    with _serve(APP) as url:
        yield url


@pytest.fixture
def bad_server():
    with _serve(BAD_APP) as url:
        yield url


def _run(browser, url, module, fixture=APP / "app.stub.yaml", contexts=("m", "d")):
    session = Session(url, "signup-results", engine=StubEngine.load(fixture))
    for ctx in set(session.contexts) - set(contexts):
        session.contexts.pop(ctx)
    def open_driver(ctx):
        driver = Driver(browser, session, ctx)
        driver.open()
        return driver
    started = monotonic()
    module.run(session, open_driver)
    print(f"{module.__name__} elapsed={monotonic()-started:.2f}s")
    return session.document()


def test_states_survive_a_surface_that_rerenders_or_disappears(browser):
    # The pottery page renders its list only after the notices request; a failure leaves main empty.
    with _serve(POTTERY) as url:
        doc = _run(browser, url, states, POTTERY / "pottery.stub.yaml", contexts=("m",))
    rows = {row["state"]: row for row in doc["probes"]["states"] if row["context"] == "m"}
    assert {"empty", "partial", "error", "offline", "timeout", "forbidden", "not-found"} <= set(rows)
    assert rows["empty"]["path"] == "/api/firing-notices"
    assert rows["offline"]["shown"] is True and rows["offline"]["blank"] is True
    coverage = next(entry for entry in doc["coverage"] if entry["probe"] == "states")
    assert coverage["status"] == "partial" and "could not observe" not in coverage["reason"]


@pytest.mark.parametrize("context", ["m", "d"])
def test_forms_record_all_six_steps_and_bad_cases(browser, probe_server, context):
    # One context per test, so the two take turns on different workers; the detail is read on the desktop one.
    doc = _run(browser, probe_server, forms, contexts=(context,))
    probes = doc["probes"]["forms"]
    if context == "d":
        signup = next(p for p in probes if p["purpose"] == "signup" and p["context"] == "d")
        assert signup["validation"] == {"first_error": "submit", "untouched_invalid_on_load": False}
        assert signup["invalid_submit"]["described_in_text"] is True
        assert signup["invalid_submit"]["associated"] is True
        assert signup["invalid_submit"]["announced"] is False
        assert signup["invalid_submit"]["new_requirement"] is True
        assert signup["invalid_submit"]["focus_to"] == "first-error"
        assert next(f for f in signup["fields"] if f["kind"] == "password")["paste_blocked"] is True
        assert next(f for f in signup["fields"] if f["kind"] == "email")["paste_blocked"] is False
        assert next(f for f in signup["fields"] if f["purpose"] == "marketing")["checked_on_load"] is True
        assert next(f for f in signup["fields"] if f["purpose"] == "terms")["checked_on_load"] is False
        assert next(f for f in signup["fields"] if f["kind"] == "email")["label"] == {
            "visible": True, "programmatic": True, "persists_after_input": True}
        assert next(f for f in signup["fields"] if f["box"] == next(
            box for box, node in doc["nodes"].items() if node.get("name") == "Display name"))["label"]["visible"] is False
        assert next(row for row in signup["preservation"] if row["after"] == "server-error")["cleared"] >= 1
        assert next(row for row in signup["preservation"] if row["after"] == "server-error")["cleared_sensitive"] == 1
        assert next(row for row in signup["preservation"] if row["after"] == "invalid-submit")["kept"] >= 1
        instant = next(p for p in probes if p["purpose"] == "other" and p["context"] == "d")
        assert instant["validation"]["first_error"] == "keystroke"
        assert instant["invalid_submit"]["associated"] is False
    assert len(probes) == 2                                          # the two forms of this context; four over both
    serialized = json.dumps(doc)
    assert "visitor@example.com" not in serialized
    assert "SyntheticPass123" not in serialized


def test_states_induce_empty_partial_slow_and_recoverable_failure(browser, probe_server):
    doc = _run(browser, probe_server, states)
    rows = doc["probes"]["states"]
    desktop = [row for row in rows if row["context"] in ("d", "d-slow", "d-off")]
    assert next(row for row in desktop if row["state"] == "empty")["shown"] is True
    assert next(row for row in desktop if row["state"] == "partial")["shown"] is True
    loading = next(row for row in desktop if row["state"] == "loading")
    assert loading["indicator"] == "progress" and loading["shown"]
    assert loading["indicator_shown_ms"] >= 300
    error = next(row for row in desktop if row["state"] == "error")
    assert error["shown"] and error["problem_text"] and error["recovery_action"] and error["recovery_works"]
    assert "offline" in error.get("same_as", [])
    success = next(row for row in desktop if row["state"] == "success")
    assert success["shown"] and success["on_action"] and success["induced_by"] == "action"
    assert next(row for row in desktop if row["state"] == "offline")["shown"] is True
    assert {row["state"] for row in desktop} >= {"empty", "partial", "loading", "error", "success", "offline", "timeout", "forbidden", "not-found"}


def test_states_record_indistinct_and_unrecoverable_negative_cases(browser, bad_server):
    doc = _run(browser, bad_server, states, BAD_APP / "app.stub.yaml")
    rows = doc["probes"]["states"]
    desktop = [row for row in rows if row["context"] in ("d", "d-slow", "d-off")]
    assert next(row for row in desktop if row["state"] == "partial")["shown"] is False
    loading = next(row for row in desktop if row["state"] == "loading")
    assert loading["shown"] is False
    error = next(row for row in desktop if row["state"] == "error")
    assert error["problem_text"] is False and error["recovery_action"] is False
    assert error["blank"] is True
    assert "empty" in error["same_as"]
    coverage = next(entry for entry in doc["coverage"] if entry["probe"] == "states")
    assert coverage["status"] == "partial" and "successful user action" in coverage["reason"]


def test_local_dev_never_submits_or_injects_form_requests(browser, probe_server):
    fixture_values = StubEngine.load(APP / "app.stub.yaml")
    session = Session(probe_server, "synthetic-local", backend="local-dev", outbound="none",
                      values_engine=fixture_values)
    session.contexts.pop("m")
    opened = []

    def open_driver(ctx):
        driver = Driver(browser, session, ctx)
        driver.open()
        opened.append(driver)
        return driver

    forms.run(session, open_driver)
    assert all(entry["method"] != "POST" for driver in opened for entry in driver.network.entries)
    doc = session.document()
    assert next(entry for entry in doc["coverage"] if entry["probe"] == "forms")["status"] == "partial"
    assert all("server-error" not in [p["after"] for p in form.get("preservation", [])]
               for form in doc["probes"]["forms"])
