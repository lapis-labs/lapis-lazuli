"""Real browser check of two readings the contract states: which changes assistive technology would
announce (text added anywhere inside the nearest live region, `output`, role lists, `timer` and
`marquee`, `aria-hidden`), and what a commit claims after an injected failure, read from the text that
was not on the page before the commit."""
from __future__ import annotations

import contextlib
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import commits, controls
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine

FIXTURES = Path(__file__).parent / "fixtures" / "behavior"
ANNOUNCEMENTS = FIXTURES / "announcements"
OUTCOMES = FIXTURES / "outcomes-app"


@contextlib.contextmanager
def _serve(directory, *, single_page=False):
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if single_page and self.path.split("?")[0] != "/index.html":
                self.path = "/index.html"
            super().do_GET()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(directory)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.fixture
def announce_driver(browser):
    with _serve(ANNOUNCEMENTS) as url:
        session = Session(url, "announcements", backend="local-dev", outbound="none")
        driver = Driver(browser, session, "d")
        driver.open()
        try:
            yield driver
        finally:
            driver.close()


def _press(driver, attribute, name):
    driver.boxes()
    button = driver.page.locator(f'button[data-{attribute}="{name}"]').get_attribute("data-lapis-box")
    return driver.act({"kind": "click", "target": button})


@pytest.mark.parametrize(("case", "channel"), [
    # Text added to a child counts for the nearest enclosing live region, whatever the region's box is.
    ("child-polite", "live-polite"),
    ("deep-status", "live-polite"),
    ("child-alert", "alert"),
    ("child-assertive", "live-assertive"),
    # <output> has the role status; an explicit aria-live or another role takes that away.
    ("output", "live-polite"),
    ("output-off", None),
    ("output-note", None),
    # A role list means its first role that exists.
    ("list-first", "live-polite"),
    ("list-second", None),
    ("list-unknown", "live-polite"),
    # The nearest region decides: an inner off, timer, or marquee silences it, an inner polite speaks.
    ("inner-off", None),
    ("inner-timer", None),
    ("marquee", None),
    ("inner-marquee", None),
    ("inner-polite", "live-polite"),
    # Nothing inside an aria-hidden subtree is announced; aria-hidden=false hides nothing.
    ("hidden-region", None),
    ("hidden-ancestor", None),
    ("hidden-child", None),
    ("hidden-false", "live-polite"),
    ("plain-child", None),
])
def test_text_added_inside_the_nearest_live_region_is_announced_as_that_region_says(announce_driver, case, channel):
    effect = _press(announce_driver, "write", case)
    assert announce_driver.page.locator(f"#{case}-text").text_content() == f"Saved {case}"   # the message did appear
    assert [(a["channel"], a["text"]) for a in effect["announcements"]] == (
        [(channel, f"Saved {case}")] if channel else [])


def test_an_announcement_names_the_box_that_holds_the_region(announce_driver):
    effect = _press(announce_driver, "write", "child-polite")
    (announcement,) = effect["announcements"]
    assert announcement["box"] in announce_driver.session.nodes
    assert announce_driver.page.locator(f'[data-lapis-box="{announcement["box"]}"]').evaluate(
        "el => el.contains(document.getElementById('child-polite-text'))")


def test_a_region_whose_text_did_not_change_is_not_announced_when_an_element_is_inserted_before_it(announce_driver):
    effect = _press(announce_driver, "insert", "shift")
    assert announce_driver.page.locator("text=Inserted").count() == 1        # something did change
    assert effect["announcements"] == []


@pytest.mark.parametrize(("path", "failure_claim"), [
    # A note that is already on the page ("완료 후 …", "once … is confirmed") is not the commit's result.
    ("notice", "none"),
    ("notice-en", "none"),
    ("standing", "none"),
    # A negated result is a failure, not the success its verb names.
    ("negated", "failure"),
    ("negated-en", "failure"),
])
def test_an_injected_failure_is_read_from_new_text_not_from_the_notice_beside_it(browser, path, failure_claim):
    with _serve(OUTCOMES, single_page=True) as url:
        session = Session(url + path, "booking", engine=StubEngine.load(OUTCOMES / "outcomes.stub.yaml"))
        session.contexts = {"d": session.contexts["d"]}

        def open_driver(ctx_id):
            driver = Driver(browser, session, ctx_id)
            driver.open("/" + path)
            return driver

        controls.run(session, open_driver)
        commits.run(session, open_driver)
        document = session.document()
    (probe,) = document["probes"]["commits"]
    outcomes = {row["injected"]: row for row in probe["outcomes"]}
    assert set(outcomes) == {"none", "fail-5xx", "fail-network", "hang", "forbidden"}
    assert (outcomes["none"]["claimed"], outcomes["none"]["actual"]) == ("success", "applied")
    for mode in ("fail-5xx", "fail-network", "forbidden"):
        assert (outcomes[mode]["claimed"], outcomes[mode]["actual"]) == (failure_claim, "not-applied"), mode
    # The stub closes a hung connection after 10 s of controlled time, so the page ends on its failure message too.
    assert outcomes["hang"]["claimed"] == failure_claim
