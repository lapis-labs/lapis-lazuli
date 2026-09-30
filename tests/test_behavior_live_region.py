"""Real browser check of which result messages the driver records as announced: the live-region
semantics WAI-ARIA gives a role (status and log polite, alert assertive, timer off) hold without an
explicit aria-live, and an explicit aria-live overrides them, off included."""
from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.session import Session

PAGE = Path(__file__).parent / "fixtures" / "behavior" / "live-regions"


@pytest.fixture
def live_driver(browser):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(PAGE)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    session = Session(f"http://127.0.0.1:{server.server_port}/", "live-regions", backend="local-dev", outbound="none")
    driver = Driver(browser, session, "d")
    driver.open()
    try:
        yield driver
    finally:
        driver.close()
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.mark.parametrize(("region", "channel"), [
    ("status", "live-polite"),               # role=status is polite without aria-live
    ("log", "live-polite"),                  # so is role=log
    ("alert", "alert"),                      # role=alert is assertive without aria-live
    ("assertive", "live-assertive"),         # a plain element with an explicit aria-live
    ("polite", "live-polite"),
    ("status-assertive", "live-assertive"),  # an explicit aria-live overrides the role's default
    ("alert-polite", "live-polite"),
    ("status-off", None),                    # aria-live=off silences a role that would be polite
    ("alert-off", None),                     # and one that would be assertive
    ("timer", None),                         # role=timer is off by default
    ("plain", None),                         # text with neither is not announced
])
def test_result_message_is_announced_as_the_role_and_aria_live_say(live_driver, region, channel):
    button = next(box["id"] for box in live_driver.boxes()
                  if box["role"] == "button" and live_driver.page.locator(
                      f'[data-lapis-box="{box["id"]}"]').get_attribute("data-region") == region)
    effect = live_driver.act({"kind": "click", "target": button})
    changed = live_driver.page.locator(f"#{region}").get_attribute("data-lapis-box")
    assert changed in effect["text_changed"]                      # the message did appear
    announced = [(a["channel"], a["text"]) for a in effect["announcements"]]
    assert announced == ([(channel, f"Saved {region}")] if channel else [])
