"""The controls probe's cost is bounded by what it observes, not by how often it looks: a snapshot costs the same
browser round trips on a page of any size, an action snapshots a calm page twice, a control costs a fixed number of
snapshots, and a window the page spends doing nothing does not wait the real time out."""
from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.sync_api import Locator

from lapis_design.behavior_check import nodes, settle
from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import controls
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine

STUB = """version: 0
clock: {start: '2026-10-01T00:00:00Z'}
collections: {}
variants: {empty: {}, partial: {}}
routes: []
values: {}
"""
# Every text has a set `line-height` (a button needs `font: inherit` for it), so the capture measures none with
# probe nodes: a snapshot adds no mutations to the page.
STYLE = ("<style>body{margin:0;font:16px/1.4 sans-serif} button,input{font:inherit} "
         ".card{border:1px solid #444;padding:6px;margin:4px}</style>")


@pytest.fixture
def site(tmp_path):
    (tmp_path / "stub.yaml").write_text(STUB)

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    def serve(name: str, body: str) -> str:
        (tmp_path / name).write_text(
            f"<!doctype html><html><head><meta charset=utf-8>{STYLE}</head><body>{body}</body></html>")
        return f"http://127.0.0.1:{server.server_port}/{name}"

    serve.engine = lambda: StubEngine.load(tmp_path / "stub.yaml")
    try:
        yield serve
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.fixture
def opened(browser, site):
    drivers = []

    def open_page(name: str, body: str, context: str = "m"):
        session = Session(site(name, body), "speed", engine=site.engine())
        session.contexts = {context: session.contexts[context]}
        driver = Driver(browser, session, context)
        driver.open()
        drivers.append(driver)
        return session, driver

    try:
        yield open_page
    finally:
        for driver in drivers:
            driver.close()


def _count_snapshots(monkeypatch) -> list:
    snapshots, real = [], nodes.snapshot
    monkeypatch.setattr(nodes, "snapshot", lambda target: snapshots.append(1) or real(target))
    return snapshots


def _cards(count: int) -> str:
    return "".join(f'<div class="card" id="card{i}">card {i}</div>' for i in range(count))


def test_a_snapshot_costs_the_same_round_trips_on_a_page_of_any_size(opened, monkeypatch):
    spent = {}
    for count in (4, 60):
        _, driver = opened(f"cards{count}.html", _cards(count))
        calls = {"cdp": 0, "locator": 0}
        send, evaluate = driver.cdp.send, Locator.evaluate

        def counted_send(*args, send=send, calls=calls, **kwargs):
            calls["cdp"] += 1
            return send(*args, **kwargs)

        def counted_evaluate(self, *args, evaluate=evaluate, calls=calls, **kwargs):
            calls["locator"] += 1
            return evaluate(self, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(driver.cdp, "send", counted_send)
            patch.setattr(Locator, "evaluate", counted_evaluate)
            driver.boxes()
        spent[count] = calls
    assert spent[4] == spent[60]
    assert spent[60]["locator"] == 0 and spent[60]["cdp"] <= 5


def test_a_listener_makes_its_own_box_a_control_and_nothing_around_it(opened):
    body = """
      <div class="card" id="plain">plain</div>
      <div class="card" id="listener">listener</div>
      <div class="card" id="inline" onclick="void 0">inline</div>
      <div class="card" id="property">property</div>
      <div class="card" id="outer"><div class="card" id="inner">inner</div></div>
      <div class="card" id="down">down</div>
      <div class="card" id="touch">touch</div>
      <div class="card" id="hover">hover</div>
      <script>
        const on = (id, type, options) => document.getElementById(id).addEventListener(type, () => {}, options);
        on('listener', 'click'); on('inner', 'click'); on('down', 'pointerdown'); on('hover', 'mouseover');
        on('touch', 'touchstart', {passive: true});
        document.getElementById('property').onclick = () => {};
      </script>"""
    _, driver = opened("listeners.html", body)
    by_id = {box["id"]: box for box in driver.boxes()}
    names = ("plain", "listener", "inline", "property", "outer", "inner", "down", "touch", "hover")
    handled = {name: by_id[driver.page.eval_on_selector(f"#{name}", "el => el.getAttribute('data-lapis-box')")]
               for name in names}
    assert {name for name, box in handled.items() if box["pointer_handler"] and box["interactive"]} == {
        "listener", "inline", "property", "inner", "down", "touch"}


def test_an_action_on_a_calm_page_snapshots_it_before_and_after(opened, monkeypatch):
    _, driver = opened("toggle.html", '<button id="go" onclick="this.textContent=\'done\'">go</button>')
    button = next(box for box in driver.interactive() if box["name"] == "go")
    snapshots = _count_snapshots(monkeypatch)
    effect = driver.act({"kind": "click", "target": button["id"]})
    assert button["id"] in effect["text_changed"]
    assert len(snapshots) == 2


def test_a_control_costs_a_fixed_number_of_snapshots(opened, monkeypatch):
    names = ("one", "two", "three")
    body = "".join(f'<button id="{name}" onclick="this.textContent=\'{name} done\'">{name}</button>' for name in names)
    session, driver = opened("controls.html", body)
    snapshots = _count_snapshots(monkeypatch)
    controls.run(session, lambda ctx: driver)
    assert len(session.probes["controls"]) == len(names)
    # one snapshot after each load, two around each action; a control loads twice and acts twice
    assert len(snapshots) <= 6 * len(names)


def test_timers_due_inside_the_window_still_run_and_hold_it_open(opened):
    body = '<p id="out"></p><button id="go" onclick="setTimeout(() => out.textContent = \'later\', 300)">go</button>'
    _, driver = opened("later.html", body)
    button = next(box for box in driver.interactive() if box["name"] == "go")
    effect = driver.act({"kind": "click", "target": button["id"]})
    assert effect["text_changed"] and effect["settle_ms"] >= 800          # 300 ms until the text, then 500 quiet


def test_a_window_the_page_spends_doing_nothing_is_not_waited_out(opened, monkeypatch):
    _, driver = opened("still.html", "<p>nothing happens here</p>")
    sleeps, nap = [], settle.sleep
    monkeypatch.setattr(settle, "sleep", lambda seconds: (sleeps.append(seconds), nap(seconds)))
    settled = settle.quiet(driver, driver.page.evaluate("window.__lapisObserve.mutations"))
    assert settled >= 500                           # the page's own clock still moved the whole window
    assert len(sleeps) <= 10                        # real time only for its first 100 ms: about seven 16 ms naps
