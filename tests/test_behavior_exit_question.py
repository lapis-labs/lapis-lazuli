"""Real browser check of a dialog whose question is the exit itself (DERIVED.md, Action choice and Kinds): in an
exit flow the stay side (No, No thanks) gets no decline points and the side that goes through is pressed; a
heading that only speaks of cancelling is not that question; the dialog and choices probes read the same."""
from __future__ import annotations

import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import choices, flows
from lapis_design.behavior_check.probes._decision import dialogs, response
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine

STUB = Path(__file__).parent / "fixtures" / "behavior" / "labels-app" / "labels.stub.yaml"

PAGES = {
    # The question is the exit: No keeps the plan, Yes goes through.
    "/question": """<main><p id="state">Subscribed</p><button type="button" onclick="d.showModal()">Cancel subscription</button></main>
<dialog id="d"><h2>Cancel the subscription?</h2><p>You will lose your 50% discount.</p>
<button type="button" onclick="d.close()">No thanks</button>
<button type="button" onclick="state.textContent='Cancelled';d.close()">Yes, cancel</button></dialog>""",
    # The heading speaks of cancelling and the question offers a discount: No thanks turns the offer down and goes on.
    "/offer": """<main><p id="state">Subscribed</p><button type="button" onclick="d.showModal()">Cancel subscription</button></main>
<dialog id="d"><h2>Before you cancel</h2><p>Stay for 50% off for 3 months?</p>
<button type="button" onclick="state.textContent='Discounted';d.close()">Claim 50% off</button>
<button type="button" onclick="state.textContent='Cancelled';d.close()">No thanks</button></dialog>""",
}


@pytest.fixture
def served(tmp_path):
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            body = ('<!doctype html><html lang="en"><head><meta charset="utf-8"></head><body>'
                    + PAGES[self.path.split("?")[0]] + "</body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def _session(browser, url, plan=None):
    session = Session(url, "cancel", engine=StubEngine.load(STUB), plan=plan)
    session.contexts = {"d": session.contexts["d"]}

    def open_driver(ctx_id):
        driver = Driver(browser, session, ctx_id)
        driver.open(urlsplit(url).path or "/")
        return driver

    return session, open_driver


@pytest.mark.parametrize("path, clicked", [
    ("/question", ["Cancel subscription", "Yes, cancel"]),
    ("/offer", ["Cancel subscription", "No thanks"]),
])
def test_the_exit_flow_presses_the_side_that_goes_through(browser, served, path, clicked):
    plan = {"flows": [{"id": "cancel", "kind": "cancel-subscription", "goal": "Cancel the subscription",
                       "start": path, "done": {"text": "Cancelled"}}]}
    session, open_driver = _session(browser, served + path, plan)
    flows.run(session, open_driver)
    document = session.document()
    run = document["flows"][0]
    assert [document["nodes"][action["target"]]["name"] for step in run["steps"] for action in step["actions"]] == clicked
    assert run["status"] == "completed"


@pytest.mark.parametrize("path, exit_question, answer, kinds", [
    ("/question", True, "Yes, cancel", {"No thanks": "accept", "Yes, cancel": "decline"}),
    ("/offer", False, "No thanks", {"Claim 50% off": "accept", "No thanks": "decline"}),
])
def test_the_dialog_and_choices_probes_read_the_same_question(browser, served, path, exit_question, answer, kinds):
    session, open_driver = _session(browser, served + path)
    driver = open_driver("d")
    try:
        driver.act({"kind": "click", "target": next(b["id"] for b in driver.boxes() if b["name"] == "Cancel subscription")})
        (dialog,) = dialogs(driver)
        assert dialog["exit_question"] is exit_question
        assert response(dialog["controls"], dialog["exit_question"])[1]["text"] == answer
        options = [choices._option(driver, item, "retention", exit_question=dialog["exit_question"])
                   for item in choices._options(driver, dialog["id"])]
        assert {option["label"]: option["kind"] for option in options} == kinds
    finally:
        driver.close()


def test_the_prompt_keeps_a_line_break_between_blocks(browser, served):
    session, open_driver = _session(browser, served + "/offer")
    driver = open_driver("d")
    try:
        driver.act({"kind": "click", "target": next(b["id"] for b in driver.boxes() if b["name"] == "Cancel subscription")})
        (dialog,) = dialogs(driver)
        assert dialog["prompt"] == "Before you cancel\nStay for 50% off for 3 months?"
        assert flows._read(driver, {"kind": "cancel-subscription", "goal": ""})["dialog_prompt"] == dialog["prompt"]
    finally:
        driver.close()
