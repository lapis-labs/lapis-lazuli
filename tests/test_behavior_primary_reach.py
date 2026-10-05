"""Primary next-step reach: required selections, page geometry, and sticky actions on loopback pages."""
from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from lapis_design import shared_dir
from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import flows
from lapis_design.behavior_check.session import Session
from lapis_design.lint.engine import lint
from lapis_design.lint.types import Context
from lapis_design.stub.engine import StubEngine

RULES = yaml.safe_load((shared_dir() / "slop/rules.yaml").read_text())
STUB = Path(__file__).parent / "fixtures/behavior/flows-choices/choices.stub.yaml"


def plan(*, reach=True):
    flow = {"id": "booking", "kind": "primary", "goal": "Choose date and time and continue",
            "start": "/", "done": {"text": "Appointment chosen"}}
    if reach:
        flow["reach"] = {"forward": "Continue", "selections": ["Date", "Time"]}
    return {"version": 0, "mode": "repair", "task": {"id": "booking", "title": "Booking"},
            "brief": {"subject": "Clinic appointments", "one_job": "Book an appointment", "platform": ["web"],
                      "locales": ["en"], "product_frame": "forms-onboarding-checkout"}, "flows": [flow]}


def test_booking_plan_without_reach_warns_and_identifies_the_flow():
    found = lint(Context(rules=RULES, plan=plan(reach=False)), ["plan"], ["layout.primary-action-reach"])
    assert [(f["status"], f["severity"], f["blocking"], f["location"]["flow"]) for f in found] == [
        ("open", {"create": "warn", "review": "P2"}, False, "booking")]
    assert lint(Context(rules=RULES, plan=plan()), ["plan"], ["layout.primary-action-reach"]) == []
    marketing = plan(reach=False)
    marketing["brief"].update(product_frame="marketing-landing", one_job="Read about a product")
    assert lint(Context(rules=RULES, plan=marketing), ["plan"], ["layout.primary-action-reach"]) == []


@pytest.mark.parametrize("gap,sticky,fires", [(600, False, True), (24, False, False), (600, True, False)])
def test_next_action_reach_is_measured_before_activation_not_locator_autoscroll(browser, tmp_path, gap, sticky, fires):
    action_style = "position:fixed;bottom:16px" if sticky else f"margin-top:{gap}px"
    (tmp_path / "index.html").write_text(f"""<!doctype html><html lang=en><meta name=viewport content="width=device-width,initial-scale=1"><style>
    body{{margin:0}} label{{display:block}} #time{{margin-top:1000px}} button{{display:block;height:44px;{action_style}}}
    </style><main><h1>Book an appointment</h1>
    <label><input type=radio name=date required aria-label=Date>Date</label>
    <label id=time><input type=radio name=time required aria-label=Time>Time</label>
    <button onclick="if(document.querySelectorAll('input:checked').length===2) document.querySelector('main').innerHTML='<h1>Appointment chosen</h1>'">Continue</button>
    </main></html>""")
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    session = Session(f"http://127.0.0.1:{server.server_port}/", "booking", engine=StubEngine.load(STUB), plan=plan())
    session.contexts = {key: session.contexts[key] for key in ("m", "d")}
    def open_driver(context):
        driver = Driver(browser, session, context)
        driver.open()
        return driver
    try:
        flows.run(session, open_driver)
        document = session.document()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    assert all(run["status"] == "completed" for run in document["flows"])
    reaches = [run["steps"][0]["action_reach"] for run in document["flows"]]
    if not sticky:
        assert all(r["initial"]["below_first_view_px"] > 0 for r in reaches), reaches
        assert all((r["after_selections"]["gap_px"] > 500) == fires for r in reaches), reaches
    found = lint(Context(rules=RULES, plan=plan(), session=document), ["behavior"], ["layout.primary-action-reach"])
    open_findings = [f for f in found if f["status"] == "open"]
    assert {f["location"]["viewport"] for f in open_findings} == ({390, 1440} if fires else set())
    assert all(f["severity"] == {"create": "warn", "review": "P2"} and not f["blocking"] for f in open_findings)
    if sticky:
        assert all(r["after_selections"]["visible"] and r["after_selections"]["pinned"] for r in reaches)
