"""Browser observations for dialogs, choices, permissions and playback."""
from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic

import jsonschema
import pytest
import yaml

from lapis_design import shared_dir
from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import choices, dialogs, media, permissions
from lapis_design.behavior_check.probes._decision import advance
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine

APP = Path(__file__).parent / "fixtures" / "behavior" / "decisions-app"
FIXTURE = APP / "decisions.stub.yaml"


@pytest.fixture
def decisions_server():
    handler = partial(SimpleHTTPRequestHandler, directory=str(APP))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_decision_probes_across_contexts(browser, decisions_server):
    schema = yaml.safe_load((shared_dir() / "behavior" / "stub.schema.yaml").read_text())
    jsonschema.Draft202012Validator(schema).validate(yaml.safe_load(FIXTURE.read_text()))
    session = Session(decisions_server, "decisions", engine=StubEngine.load(FIXTURE),
                      plan={"flows": [{"id": "newsletter", "kind": "subscribe",
                                       "goal": "Subscribe to our newsletter for weekly email updates",
                                       "start": "/", "done": {"text": "Subscribed"}}]})

    def open_driver(ctx_id):
        driver = Driver(browser, session, ctx_id)
        driver.open()
        return driver

    started = monotonic()
    for module in (dialogs, choices, permissions, media):
        module.run(session, open_driver)
    elapsed = monotonic() - started
    document = session.document()
    schema = yaml.safe_load((shared_dir() / "behavior" / "session.schema.yaml").read_text())
    jsonschema.Draft202012Validator(schema).validate(document)
    assert {entry["probe"]: entry["status"] for entry in document["coverage"]} == {
        "dialogs": "ran", "choices": "ran", "permissions": "ran", "media": "ran"}
    for context in ("m", "d"):
        dialog_rows = [row for row in document["probes"]["dialogs"] if row["context"] == context]
        by_purpose = {row["purpose"]: row for row in dialog_rows}
        assert {"consent", "marketing", "upsell", "confirm"} <= by_purpose.keys()
        assert by_purpose["marketing"]["trigger"] == "timer"
        assert by_purpose["marketing"]["purpose_basis"] == "plan"
        assert any(row["preceded_by"] == "navigation" for row in by_purpose["marketing"]["appearances"])
        assert by_purpose["marketing"]["derived"]["reasks_after_decline"] >= 1
        assert by_purpose["confirm"]["trigger"] == "control"
        assert by_purpose["confirm"]["focus"]["moved_in"] is True
        assert by_purpose["confirm"]["focus"]["contained"] is True
        assert by_purpose["confirm"]["focus"]["escape_closes"] is True
        assert by_purpose["confirm"]["focus"]["returns_to"] == "invoker"
        consent = next(row for row in document["probes"]["choices"] if row["context"] == context and row["purpose"] == "consent")
        accept = next(option for option in consent["options"] if option["kind"] == "accept")
        reject = next(option for option in consent["options"] if option["kind"] == "decline")
        assert (accept["layer"], accept["interactions"]) == (1, 1)
        assert (reject["layer"], reject["interactions"]) == (2, 2)
        assert accept["visual"]["area_px"] > reject["visual"]["area_px"]
        assert consent["derived"]["decline_extra_interactions"] == 1
        plan = next(row for row in document["probes"]["choices"]
                    if row["context"] == context and row["purpose"] == "plan")
        assert {option["price"] for option in plan["options"]} == {5, 10}
        assert all(option["cadence"] == "month" for option in plan["options"])
        addon = next(row for row in document["probes"]["choices"]
                     if row["context"] == context and row["purpose"] == "add-on")
        assert any(option["kind"] == "decline" and option["interactions"] == 0 and "visual" not in option
                   for option in addon["options"])
        requests = [row for row in document["probes"]["permissions"] if row["context"] == context]
        assert any(row["api"] == "notifications" and not row["user_gesture"] for row in requests)
        assert any(row["api"] == "notifications" and row["user_gesture"] and row.get("preprompt") for row in requests)
        assert {row["api"] for row in requests} >= {
            "notifications", "geolocation", "camera", "microphone", "clipboard-read", "persistent-storage"}
        assert any(row["after_denial"] for row in requests if row["api"] == "notifications")
        videos = [row for row in document["probes"]["media"] if row["context"] == context]
        assert len(videos) >= 2
        assert any(row["controls"] and not row["audible"] for row in videos)
        assert any(not row["controls"] for row in videos)
        assert any(row["audible"] and row["user_gesture"] and row["audible_s"] > 0
                   for row in videos)
    print(f"decision probes: {elapsed:.2f}s for two contexts")


def test_controlled_clock_advances_delayed_dialog_without_realtime_wait(browser, decisions_server):
    session = Session(decisions_server, "clock", engine=StubEngine.load(FIXTURE))
    driver = Driver(browser, session, "d")
    try:
        driver.open("/clock.html")
        before = session.clock.now_ms()
        started = monotonic()
        advance(driver, 5500)
        assert driver.page.locator("#state").inner_text() == "timer fired"
        assert monotonic() - started < 3
        assert session.clock.now_ms() - before >= 5500
    finally:
        driver.close()
