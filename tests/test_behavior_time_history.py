"""Live, synthetic-clock tests for urgency, session expiration, and history."""
from __future__ import annotations

import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import history, time_limits, urgency
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine

APP = Path(__file__).parent / "fixtures" / "behavior" / "time-history"


@pytest.fixture
def app_server():
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path == "/prg-submit":
                self.send_response(303)
                self.send_header("Location", "/detail.html")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path != "/submitted.html":
                self.send_error(404)
                return
            content = b"<!doctype html><title>Submitted</title><main>Form submitted</main>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(APP)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def _run(browser, url, module, *, plan=None, flows=()):
    session = Session(url, "time-history", engine=StubEngine.load(APP / "app.stub.yaml"), plan=plan)
    for flow in flows:
        session.add_flow_run(flow)
    def open_driver(ctx):
        return Driver(browser, session, ctx)
    started = time.monotonic()
    module.run(session, open_driver)
    print(f"{module.__name__}: {time.monotonic()-started:.2f}s for {', '.join(session.contexts)}")
    return session.document()


def test_claim_readings_for_locale_and_time_zone_forms():
    start = 1_790_380_800_000  # 2026-09-26T00:00:00Z
    # An absolute time without a zone is read in the context's zone: 09:10 in Seoul is 00:10 UTC.
    assert urgency._claim("Offer ends at 2026-09-26 09:10", start, ZoneInfo("Asia/Seoul")) == ("deadline", 600, 60, "seconds")
    assert urgency._claim("Offer ends at 2026-09-26 00:10", start) == ("deadline", 600, 60, "seconds")   # UTC by default
    assert urgency._claim("Offer ends at 2026-09-26 09:10 UTC", start, ZoneInfo("Asia/Seoul"))[1] == 9 * 3600 + 600
    # The zone's offset on the deadline's own date: New York leaves daylight time on 2026-11-01,
    # so midnight on 2026-11-02 is 05:00 UTC, not the 04:00 today's offset would give.
    assert urgency._claim("Offer ends at 2026-11-02 00:00", start, ZoneInfo("America/New_York"))[1] == 37 * 86400 + 5 * 3600
    assert urgency._claim("마감 2026년 9월 26일", start) == ("deadline", 86400, 86400, "seconds")
    assert urgency._claim("3일 남음", start) == ("countdown", 3 * 86400, 86400, "seconds")
    assert urgency._claim("좌석을 04:59 동안 임시 예약했어요", start) == ("hold", 299, 1, "seconds")
    assert urgency._claim("Pottery class on 9월 30일", start) is None


def test_urgency_detects_backing_resets_and_drifts(browser, app_server):
    document = _run(browser, app_server, urgency, plan={"brief": {"locales": ["ko-KR"]}})
    entries = document["probes"]["urgency"]
    assert {context["locale"] for context in document["contexts"]} == {"ko-KR"}
    for ctx in ("m", "d"):
        items = [item for item in entries if item["context"] == ctx]
        assert any(item["kind"] == "countdown" and item["derived"]["resets"] and
                   item["backed"] is False and item["at_expiry"] == "restarts" for item in items), [
                       (item["kind"], item.get("backed"), item["readings"], item.get("at_expiry")) for item in items]
        assert any(item["kind"] == "deadline" and item["backed"] and
                   not item["derived"]["resets"] for item in items)
        assert any(item["kind"] == "hold" and item["backed"] and
                   item["derived"]["resets"] is False for item in items)
        stock = [item for item in items if item["kind"] == "stock"]
        assert {item["readings"][0]["value"]: item["backed"] for item in stock} == {3: False, 5: True, 7: False}
        assert next(item for item in stock if item["readings"][0]["value"] == 3)["derived"]["drifts"]
        assert any(item["kind"] == "demand" and item["backed"] for item in items)
        assert any(item["kind"] == "activity" and item["backed"] for item in items)
        assert sum(item["kind"] == "deadline" and item["backed"] for item in items) == 2
        assert sum(item["kind"] == "demand" and item["backed"] for item in items) == 2
        assert sum(item["kind"] == "activity" and item["backed"] for item in items) == 2
        for item in items:
            assert item["readings"][0]["elapsed_ms"] == 0
            assert {"later", "reload", "fresh-profile"} <= {r["when"] for r in item["readings"]}
            assert "derived" in item  # filled by Session.document, not the probe
    assert next(entry for entry in document["coverage"] if entry["probe"] == "urgency")["status"] == "ran"


def test_session_timeout_warning_extension_and_unwarned_limit(browser, app_server):
    plan = {"flows": [{"id": "good", "start": "/session.html"},
                      {"id": "bad", "start": "/session-bad.html"}]}
    document = _run(browser, app_server, time_limits, plan=plan)
    entries = document["probes"]["time_limits"]
    assert len(entries) == 4
    for ctx in ("m", "d"):
        good = next(item for item in entries if item.get("flow") == "good" and item["context"] == ctx)
        bad = next(item for item in entries if item.get("flow") == "bad" and item["context"] == ctx)
        assert good["kind"] == "session" and abs(good["limit_s"] - 900) <= 2, good
        assert good["warned"] and abs(good["warn_lead_s"] - 60) <= 2 and good["extendable"], good
        assert good["extensions"] == 10 and good["input_after_expiry"] == "lost", good
        assert abs(bad["limit_s"] - 900) <= 2 and not bad["warned"] and not bad["extendable"], bad
    assert next(entry for entry in document["coverage"] if entry["probe"] == "time_limits")["status"] == "ran"


def test_time_limit_found_at_a_later_flow_step(browser, app_server):
    probe_session = Session(app_server, "time-history", engine=StubEngine.load(APP / "app.stub.yaml"))
    driver = Driver(browser, probe_session, "d")
    driver.open("/")
    link = next(box["id"] for box in driver.boxes() if box["name"] == "Session form")
    driver.close()
    runs = [{"id": "enter", "context": ctx, "kind": "primary", "status": "completed",
             "effort": {"steps": 2, "interactions": 1},
             "steps": [{"index": 0, "path": "/", "actions": [{"kind": "click", "target": link}]},
                       {"index": 1, "path": "/session.html"}]} for ctx in ("m", "d")]
    document = _run(browser, app_server, time_limits,
                    plan={"flows": [{"id": "enter", "start": "/", "max_steps": 2}]}, flows=runs)
    entries = document["probes"]["time_limits"]
    # The entry step's 1 s countdown ticks never end a session; the second step's timer does.
    assert [(item["flow"], item["context"]) for item in entries] == [("enter", "m"), ("enter", "d")]
    assert all(abs(item["limit_s"] - 900) <= 2 and item["warned"] for item in entries), entries


def _plan_runs(browser, app_server, toggles, *, follow_link):
    """Flow runs over plan.html: `toggles` steps that open and close its details panel, then either one more
    step on the same screen or the click that leads to the session form and the form itself."""
    probe_session = Session(app_server, "time-history", engine=StubEngine.load(APP / "app.stub.yaml"))
    driver = Driver(browser, probe_session, "d")
    driver.open("/plan.html")
    boxes = {box["name"]: box["id"] for box in driver.boxes()}
    driver.close()
    toggle = {"kind": "click", "target": boxes["Plan details"]}
    steps = [{"index": index, "path": "/plan.html", "actions": [dict(toggle)]} for index in range(toggles)]
    if follow_link:
        steps.append({"index": toggles, "path": "/plan.html", "actions": [{"kind": "click", "target": boxes["Session form"]}]})
        steps.append({"index": toggles + 1, "path": "/session.html"})
    else:
        steps.append({"index": toggles, "path": "/plan.html"})
    return [{"id": "wander", "context": ctx, "kind": "primary", "status": "abandoned",
             "effort": {"steps": toggles, "interactions": toggles}, "steps": steps} for ctx in ("m", "d")], boxes["Plan details"]


def test_time_limit_probe_replays_each_flow_action_once_per_context(browser, app_server, monkeypatch):
    runs, toggle = _plan_runs(browser, app_server, 6, follow_link=False)
    acts = []
    original = Driver.act

    def counting(self, action):
        acts.append((self.ctx_id, action["target"]))
        return original(self, action)

    monkeypatch.setattr(Driver, "act", counting)
    document = _run(browser, app_server, time_limits,
                    plan={"flows": [{"id": "wander", "start": "/plan.html", "max_steps": 7}]}, flows=runs)
    # Seven quiet steps, each reached by the actions before it. Replaying the whole prefix for every step
    # clicks 0 + 1 + ... + 6 = 21 times per context (a 40-action run: 820), and no timer in the page can
    # end a session: each recorded action is clicked once per context.
    assert sorted(acts) == sorted((ctx, toggle) for ctx in ("m", "d") for _ in range(6)), acts
    assert "time_limits" not in document["probes"]
    coverage = next(entry for entry in document["coverage"] if entry["probe"] == "time_limits")
    assert coverage["status"] == "not-applicable", coverage


def test_time_limit_found_after_quiet_flow_steps(browser, app_server):
    runs, _ = _plan_runs(browser, app_server, 3, follow_link=True)
    document = _run(browser, app_server, time_limits,
                    plan={"flows": [{"id": "wander", "start": "/plan.html", "max_steps": 5}]}, flows=runs)
    entries = document["probes"]["time_limits"]
    # The page stands where the quiet steps left it and follows the link to the form, whose timer ends the
    # session; the timer hook survives that navigation, and the extension run starts from a fresh load.
    assert [(item["flow"], item["context"]) for item in entries] == [("wander", "m"), ("wander", "d")]
    assert all(abs(item["limit_s"] - 900) <= 2 and item["warned"] and item["extensions"] == 10 for item in entries), entries


def test_time_limits_without_flows_probe_entry_route(browser, app_server):
    document = _run(browser, app_server + "session-bad.html", time_limits)
    assert {item["context"] for item in document["probes"]["time_limits"]} == {"m", "d"}
    coverage = next(entry for entry in document["coverage"] if entry["probe"] == "time_limits")
    assert coverage == {"probe": "time_limits", "status": "ran", "contexts": ["m", "d"],
                        "reason": "No plan flows; probed entry route"}


def test_history_exposes_broken_filter_pushed_entries_and_home_redirect(browser, app_server):
    document = _run(browser, app_server, history)
    entries = document["probes"]["history"]
    for ctx in ("m", "d"):
        here = [item for item in entries if item["context"] == ctx]
        assert any(item["action"] == "back" and item.get("restored", {}).get("filters") is False
                   for item in here), (here, document["coverage"])
        restoration = next(item["restored"] for item in here if "restored" in item)
        assert restoration["input"] is True and restoration["page"] is False, restoration
        assert restoration["selection"] is False and restoration["scroll"] is True, restoration
        assert any(item["action"] == "back" and item.get("pushed_entries", 0) >= 1 and
                   item["left_page"] and item["presses"] >= 2 for item in here)
        assert any(item["action"] == "deep-link-after-sign-in" and item["landed"] == "home" for item in here)
        assert any(item["action"] == "reload" and item["from"] == "/submitted.html" and
                   item["resubmit_prompt"] is True for item in here), here
    assert next(entry for entry in document["coverage"] if entry["probe"] == "history")["status"] == "ran"


def test_a_page_with_no_link_to_another_route_has_no_navigation_to_go_back_from_and_history_still_ran(browser, app_server):
    session = Session(app_server + "single.html", "time-history", engine=StubEngine.load(APP / "single.stub.yaml"))
    def open_driver(ctx):
        return Driver(browser, session, ctx)
    history.run(session, open_driver)
    document = session.document()
    status = next(entry for entry in document["coverage"] if entry["probe"] == "history")
    assert status["status"] == "ran" and status.get("reason") is None, status
    assert {item["action"] for item in document["probes"]["history"]} == {"back"}      # the entry Back; no navigation entry
    assert all("restored" not in item for item in document["probes"]["history"])


def test_reload_after_redirected_post_offers_no_resubmission(browser, app_server):
    session = Session(app_server + "prg.html", "time-history", engine=StubEngine.load(APP / "app.stub.yaml"))
    driver = Driver(browser, session, "d")
    try:
        assert history._reload_post(session, driver) is None
    finally:
        driver.close()
    assert session.probes["history"] == [{"context": "d", "action": "reload", "from": "/detail.html",
                                          "to": "/detail.html", "resubmit_prompt": False}]


def test_sign_in_that_keeps_the_deep_link_lands_on_target(browser, app_server):
    session = Session(app_server + "hub.html", "time-history", engine=StubEngine.load(APP / "app.stub.yaml"))
    driver = Driver(browser, session, "m")
    try:
        assert history._deep_link(session, driver) is None
    finally:
        driver.close()
    assert session.probes["history"] == [{"context": "m", "action": "deep-link-after-sign-in",
                                          "from": "/orders.html", "to": "/orders.html", "landed": "target"}]


def test_back_from_entry_without_pushed_entries_leaves_in_one_press(browser, app_server):
    session = Session(app_server + "hub.html", "time-history", engine=StubEngine.load(APP / "app.stub.yaml"))
    driver = Driver(browser, session, "d")
    try:
        history._entry_back(session, driver)
    finally:
        driver.close()
    assert session.probes["history"] == [{"context": "d", "action": "back", "from": "/hub.html", "presses": 1,
                                          "left_page": True, "pushed_entries": 0,
                                          "overlay_closed_first": False}]
