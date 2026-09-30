"""Loopback checks for three gaps the reference writers hit: a run pointed at one page of a site must
drive that page (path and query) rather than the origin's root, a fade that also slides is movement, and
a pause or stop control is read by its accessible name in Korean as well as English."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema
import pytest
import yaml

import lapis_design.lint.detectors.behavior  # noqa: F401  (registers the detectors)
import lapis_design.lint.detectors.render_layout  # noqa: F401  (motion-inventory)
from lapis_design import shared_dir
from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import flows, media, motion
from lapis_design.behavior_check.session import Session
from lapis_design.lint.types import DETECTORS, Context
from lapis_design.stub.engine import StubEngine

APP = Path(__file__).parent / "fixtures" / "behavior" / "gaps"
STUB = APP / "gaps.stub.yaml"


class Site:
    """The gaps fixture served on loopback, with a journal of every path the browser asked for. `index`
    names the page served at the root, for tests that are not about where a run starts."""

    def __init__(self, index=None):
        self.requests: list[str] = []
        journal = self.requests

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                journal.append(self.path)
                if index and self.path.split("?")[0] == "/":
                    self.path = "/" + index
                super().do_GET()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(APP)))
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/"

    @property
    def documents(self) -> list[str]:
        """Path and query of every page (not script or media) requested."""
        return [path for path in self.requests if path.split("?")[0].endswith((".html", "/"))]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()


@pytest.fixture
def site():
    served = Site()
    try:
        yield served
    finally:
        served.close()


@pytest.fixture(scope="module")
def motion_site():
    served = Site(index="motion.html")
    try:
        yield served
    finally:
        served.close()


@pytest.fixture(scope="module")
def player_site():
    served = Site(index="player.html")
    try:
        yield served
    finally:
        served.close()


def _session(url, *, plan=None):
    session = Session(url, "gaps", engine=StubEngine.load(STUB), plan=plan)
    session.contexts = {"d": session.contexts["d"]}
    return session


def _opener(browser, session):
    def open_driver(ctx_id):
        driver = Driver(browser, session, ctx_id)
        driver.open()
        return driver
    return open_driver


def _box_ids(open_driver, *element_ids):
    driver = open_driver("d")
    try:
        return driver.page.evaluate(
            "ids => Object.fromEntries(ids.map(id => [id, document.getElementById(id).getAttribute('data-lapis-box')]))",
            list(element_ids))
    finally:
        driver.close()


def _hits(document, rule_id):
    rules = yaml.safe_load((shared_dir() / "slop" / "rules.yaml").read_text())
    rule = next(r for r in rules["rules"] if r["id"] == rule_id)
    det = rule["detect"]["behavior"]
    result = DETECTORS[det["detector"]].fn(Context(rules=rules, session=document, plan=None), det, rule, "behavior")
    return {hit.location["box"] for hit in result.hits if hit.location["context"].startswith("d")}


# Item 1: the start URL

def test_driver_starts_and_restarts_at_the_url_it_was_given(browser, site):
    start = site.url + "other.html?tab=b#pane"
    session = _session(start)
    assert session.source["url"] == site.url + "other.html"        # recorded without query or fragment
    open_driver = _opener(browser, session)
    driver = open_driver("d")
    try:
        assert driver.page.url == start
        assert driver.page.evaluate("document.title") == "Other"
        driver.reload()                                              # a fresh profile, the same page
        assert driver.page.url == start
        driver.open("/")                                            # a route of its own is still reachable
        assert driver.page.url == site.url
        driver.open("/other.html")                                  # the entry's own route is the given URL
        assert driver.page.url == start
        driver.act({"kind": "navigate", "path": "/"})
        assert driver.page.url == site.url
        driver.act({"kind": "navigate", "path": "/other.html"})
        assert driver.page.url == start
    finally:
        driver.close()


def test_every_probe_stays_on_the_page_the_command_names(site, tmp_path):
    output = tmp_path / "other.json"
    script = "import sys\nfrom lapis_design.behavior_check import main\nraise SystemExit(main(sys.argv[1:]))\n"
    result = subprocess.run(
        [sys.executable, "-c", script, site.url + "other.html?tab=b#pane", "--task", "gaps", "--stub", str(STUB),
         "--context", "d", "--out", str(output)], capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr
    document = json.loads(output.read_text())
    assert document["source"]["url"] == site.url + "other.html"
    # Not one page of the run was the origin's root, and the query the command gave was never dropped.
    assert set(site.documents) == {"/other.html?tab=b"}, site.documents
    assert not any("redirected" in (row.get("reason") or "") for row in document["coverage"])
    schema = yaml.safe_load((shared_dir() / "behavior" / "session.schema.yaml").read_text())
    jsonschema.Draft202012Validator(schema).validate(document)
    assert "tab=b" not in json.dumps(document)                       # the query is driven, never recorded


def test_flow_starts_at_its_route_and_other_probes_at_the_given_url(browser, site):
    plan = {"flows": [
        {"id": "open-other", "kind": "primary", "goal": "read the other page", "start": "/other.html",
         "done": {"text": "Other page"}},
        {"id": "open-root", "kind": "primary", "goal": "read the root page", "start": "/",
         "done": {"text": "Root page"}},
    ]}
    session = _session(site.url + "other.html?tab=b", plan=plan)
    flows.run(session, _opener(browser, session))
    runs = {run["id"]: run for run in session.flows}
    assert {run["status"] for run in runs.values()} == {"completed"}, runs
    assert [step["path"] for step in runs["open-other"]["steps"]] == ["/other.html"]
    assert [step["path"] for step in runs["open-root"]["steps"]] == ["/"]
    # Each flow loads the entry once; the flow that starts elsewhere then opens its own route.
    assert site.documents == ["/other.html?tab=b", "/other.html?tab=b", "/"], site.documents


# Items 2 and 3: one motion run over a page that holds every case

@pytest.fixture(scope="module")
def motion_run(browser, motion_site):
    session = _session(motion_site.url)
    open_driver = _opener(browser, session)
    try:
        motion.run(session, open_driver)
        document = session.document()
        ids = _box_ids(open_driver, "slide-fade", "fade", "margin-slide", "guarded", "en-text", "en-labelledby",
                       "ko-text", "ko-spaced", "ko-aria-label", "ko-title", "ko-labelledby", "ko-remote",
                       "unrelated", "alone")
        yield document, ids
    finally:
        for driver in tuple(session.drivers):
            driver.close()


def test_a_fade_that_also_moves_is_movement_under_reduced_motion(motion_run):
    document, ids = motion_run
    rows = {row["context"]: row for row in document["probes"]["motion"]}
    kinds = {item["box"]: item["kind"] for item in rows["d-rm"]["moving"]}
    assert kinds[ids["slide-fade"]] == "transform"                   # opacity and transform in one animation
    assert kinds[ids["margin-slide"]] == "transform"                 # position changed by `left`, not `transform`
    assert kinds[ids["fade"]] == "opacity"                           # a pure fade stays a fade
    assert ids["guarded"] not in kinds                               # the reduced-motion branch removed it
    travel = {item["box"]: item["travel_px"] for item in rows["d-rm"]["moving"]}
    assert travel[ids["slide-fade"]] > 5 and travel[ids["margin-slide"]] > 5
    assert _hits(document, "motion.reduced-motion-missing") == {ids["slide-fade"], ids["margin-slide"]}


def test_pause_and_stop_controls_are_read_by_accessible_name_in_both_languages(motion_run):
    document, ids = motion_run
    rows = {row["context"]: row for row in document["probes"]["motion"]}
    paused = {item["box"]: item["pause_control"] for item in rows["d"]["auto_moving"]}
    controlled = ("en-text", "en-labelledby", "ko-text", "ko-spaced", "ko-aria-label", "ko-title", "ko-labelledby",
                  "ko-remote")
    assert {name: paused[ids[name]] for name in controlled} == {name: True for name in controlled}
    assert not paused[ids["unrelated"]] and not paused[ids["alone"]]  # a control named otherwise is not one
    uncontrolled = _hits(document, "motion.uncontrolled-marquee") & {ids[name] for name in (*controlled, "unrelated", "alone")}
    assert uncontrolled == {ids["unrelated"], ids["alone"]}


def test_media_controls_are_read_by_accessible_name_in_korean(browser, player_site):
    session = _session(player_site.url)
    open_driver = _opener(browser, session)
    try:
        media.run(session, open_driver)
        ids = _box_ids(open_driver, "ko-pause", "ko-volume", "unrelated", "play-tone")
        controls = {row["box"]: row["controls"] for row in session.probes["media"]}
    finally:
        for driver in tuple(session.drivers):
            driver.close()
    cases = ("ko-pause", "ko-volume", "unrelated", "play-tone")   # play-tone: the owner of an AudioContext's output
    assert {name: controls[ids[name]] for name in cases} == {
        "ko-pause": True, "ko-volume": True, "unrelated": False, "play-tone": True}
