"""The behavior check's cost is bounded by what it observes, not by how often it looks or how long it waits: a
snapshot costs the same browser round trips on a page of any size, a snapshot stands while nothing has reached the
page, an action on a page just seen snapshots only what it changed, a control costs a fixed number of snapshots, a
window the page spends doing nothing is not waited out, and neither is a box that nothing on the browser's own clock
can reveal, while work the controlled clock cannot drive is waited for in real time."""
from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.sync_api import Locator

from lapis_design.behavior_check import nodes, settle
from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import controls, motion
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

    serve.file = lambda name, text: (tmp_path / name).write_text(text)
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


def test_a_snapshot_stands_while_nothing_reaches_the_page(opened, monkeypatch):
    _, driver = opened("calm.html", '<button id="go">go</button>')
    snapshots = _count_snapshots(monkeypatch)
    first = driver.boxes()
    assert driver.boxes() is first and driver.interactive() == [box for box in first if box["interactive"]]
    assert driver.locate(first[-1]["id"]).count() == 1
    assert len(snapshots) == 0                      # the load's snapshot stands for all of them


# No node changes in either of these: an input makes the page show what was not there to see.
REVEALS = {
    "hover": ("<style>.tip{display:none} #host:hover + .tip{display:block}</style>"
              '<button id="host">host</button><p class="tip" id="shown">tip</p>',
              lambda driver: driver.page.hover("#host")),
    "focus": ("<style>#shown{opacity:0} #shown:focus{opacity:1}</style>"
              '<a id="shown" href="#end">skip</a><p id="end">end</p>',
              lambda driver: driver.page.keyboard.press("Tab")),
}


@pytest.mark.parametrize("arrival", list(REVEALS))
def test_what_an_input_shows_without_changing_a_node_is_seen_by_the_next_snapshot(opened, arrival):
    body, reach = REVEALS[arrival]
    _, driver = opened(f"reveal-{arrival}.html", body)
    before = {box["id"] for box in driver.boxes()}
    reach(driver)
    revealed = driver.page.eval_on_selector("#shown", "el => el.getAttribute('data-lapis-box')")
    assert revealed not in before                   # the snapshot that stands has not seen it
    assert {box["id"] for box in driver.boxes()} > before


def test_a_scroll_that_has_not_yet_fired_its_event_still_ends_a_snapshot(opened):
    # A fixed bar keeps its place in the window, so its place in the page follows the scroll.
    body = ('<style>body{height:3000px} #bar{position:fixed;top:0;left:0}</style>'
            '<button id="bar">bar</button><button style="margin-top:900px">far</button>')
    _, driver = opened("scrolled.html", body)
    bar = lambda: next(box for box in driver.boxes() if box["name"] == "bar")["rect"]["y"]
    assert bar() == 0
    # the scroll event fires with the next frame; the position is there at once
    driver.page.evaluate("scrollTo({top: 500, behavior: 'instant'})")
    assert bar() == 500


def test_a_clock_move_a_new_node_and_a_new_document_each_end_a_snapshot(opened, monkeypatch):
    session, driver = opened("moves.html", '<button id="go">go</button>')
    snapshots = _count_snapshots(monkeypatch)
    driver.boxes()
    session.advance_clock(1)
    driver.boxes()
    assert len(snapshots) == 1                      # the clock moved
    driver.page.evaluate("document.body.append(Object.assign(document.createElement('button'), "
                         "{id: 'late', textContent: 'late'}))")
    assert "late" in {box["name"] for box in driver.boxes()}
    assert len(snapshots) == 2                      # a node came
    driver.page.reload()
    driver.boxes()
    assert len(snapshots) == 3                      # another document, with the same nodes
    driver.boxes()
    assert len(snapshots) == 3


def test_a_snapshot_that_stands_counts_the_mutations_a_new_one_would_have_added(opened, monkeypatch):
    # A text with `line-height: normal` is measured with probe nodes, which count as mutations of the page.
    _, driver = opened("normal.html", "<style>p{line-height:normal}</style><p>measured by a probe node</p>")
    snapshots = _count_snapshots(monkeypatch)
    added = driver.snapshot_mutations
    assert added > 0

    def count():
        return driver.page.evaluate("window.__lapisObserve.mutations")

    before = count()
    driver.boxes()
    driver.locate(driver.boxes()[-1]["id"])
    assert count() - before == 3 * added and not snapshots


def test_an_action_counts_the_probe_nodes_of_every_snapshot_it_stands_in_for(opened):
    body = ("<style>p,button{line-height:normal}</style><p>probe</p>"
            '<button id="go" onclick="this.textContent=\'done\'">go</button>')
    _, driver = opened("measured.html", body)
    button = next(box for box in driver.interactive() if box["name"] == "go")
    before = driver.snapshot_mutations
    effect = driver.act({"kind": "click", "target": button["id"]})
    # the click replaces the button's text (2 mutations); the snapshot that found the button, which stood in for a
    # new one, and the snapshot after the action each add the probe nodes of their own texts
    assert before > 0 and effect["dom_mutations"] == 2 + before + driver.snapshot_mutations


def test_an_action_on_a_page_just_seen_snapshots_only_what_it_changed(opened, monkeypatch):
    _, driver = opened("toggle.html", '<button id="go" onclick="this.textContent=\'done\'">go</button>')
    button = next(box for box in driver.interactive() if box["name"] == "go")
    snapshots = _count_snapshots(monkeypatch)
    effect = driver.act({"kind": "click", "target": button["id"]})
    assert button["id"] in effect["text_changed"]
    assert len(snapshots) == 1


def test_a_control_costs_a_fixed_number_of_snapshots(opened, monkeypatch):
    names = ("one", "two", "three")
    body = "".join(f'<button id="{name}" onclick="this.textContent=\'{name} done\'">{name}</button>' for name in names)
    session, driver = opened("controls.html", body)
    snapshots = _count_snapshots(monkeypatch)
    controls.run(session, lambda ctx: driver)
    assert len(session.probes["controls"]) == len(names)
    # one snapshot after each of the two loads; the pointer action snapshots what it changed, and the key action
    # the page the Tab presses reached, and what it changed
    assert len(snapshots) <= 5 * len(names)


def test_a_control_that_carries_another_is_found_by_one_question_to_the_page(opened, monkeypatch):
    wrapped = "".join(f'<div class="wrap" id="wrap{i}"><button class="fill">fill {i}</button></div>' for i in range(30))
    body = ("<style>.wrap{background:#eee;cursor:pointer} .fill{display:block;width:100%;margin:0;padding:0;border:0;"
            "background:#ddd} .roomy{padding:12px}</style>" + wrapped +
            '<div class="wrap roomy" id="roomy"><button>roomy</button></div>')
    _, driver = opened("wrapped.html", body)
    asked = {"locator": 0}
    evaluate = Locator.evaluate

    def counted(self, *args, **kwargs):
        asked["locator"] += 1
        return evaluate(self, *args, **kwargs)

    monkeypatch.setattr(Locator, "evaluate", counted)
    carried = {driver.page.eval_on_selector(f"#wrap{i}", "el => el.getAttribute('data-lapis-box')") for i in range(30)}
    roomy = driver.page.eval_on_selector("#roomy", "el => el.getAttribute('data-lapis-box')")
    found = {box["id"] for box in driver.interactive()}
    assert not carried & found and roomy in found      # the wrapper that the control only nearly fills is still a target
    assert asked["locator"] == 0


def test_timers_due_inside_the_window_still_run_and_hold_it_open(opened):
    body = '<p id="out"></p><button id="go" onclick="setTimeout(() => out.textContent = \'later\', 300)">go</button>'
    _, driver = opened("later.html", body)
    button = next(box for box in driver.interactive() if box["name"] == "go")
    effect = driver.act({"kind": "click", "target": button["id"]})
    assert effect["text_changed"] and effect["settle_ms"] >= 800          # 300 ms until the text, then 500 quiet


# A hidden box below the fold, and what the motion probe's scroll reveal makes of it.
SPACER = '<div style="height:2000px"></div>'
ON_VIEW = ("<script>new IntersectionObserver(entries => {{ for (const entry of entries) if (entry.isIntersecting) "
           "setTimeout(() => {action}, {ms}) }}).observe(document.querySelector('#late'))</script>")


def _naps(monkeypatch) -> list:
    """Every real wait the motion probe asks for (the waits still happen)."""
    naps, real = [], motion.sleep
    monkeypatch.setattr(motion, "sleep", lambda seconds: (naps.append(seconds), real(seconds)))
    return naps


def test_a_box_revealed_by_a_timer_reads_the_timers_delay(opened, monkeypatch):
    body = (SPACER + '<div id="late" style="opacity:0;height:40px">late</div>' +
            ON_VIEW.format(action="entry.target.style.opacity = 1", ms=1000))
    _, driver = opened("timer.html", body, "d")
    naps = _naps(monkeypatch)
    rows = motion._scroll_reveal(driver)
    assert [row["hidden_at_rest"] for row in rows] == [True]
    assert 900 <= rows[0]["reveal_delay_ms"] <= 1100
    assert sum(naps) < 0.5                          # the timer is on the controlled clock: no real waiting for it


def test_a_box_that_nothing_reveals_costs_its_page_time_and_no_real_waiting(opened, monkeypatch):
    body = SPACER + '<div id="late" style="opacity:0;height:40px">late</div>'
    session, driver = opened("never.html", body, "d")
    naps = _naps(monkeypatch)
    before = session.clock.now_ms()
    rows = motion._scroll_reveal(driver)
    assert len(rows) == 1 and "reveal_delay_ms" not in rows[0]
    assert session.clock.now_ms() - before >= 5100  # the page lived through the whole 5.1 s
    assert sum(naps) < 0.5                          # 51 real ticks would be 5.1 s


def test_a_transition_a_timer_starts_is_waited_for_in_real_time(opened, monkeypatch):
    body = ("<style>#late{opacity:0;height:40px;transition:opacity .4s linear} #late.on{opacity:1}</style>" + SPACER +
            '<div id="late">late</div>' + ON_VIEW.format(action="entry.target.classList.add('on')", ms=250))
    _, driver = opened("transition.html", body, "d")
    naps = _naps(monkeypatch)
    rows = motion._scroll_reveal(driver)
    assert 600 <= rows[0]["reveal_delay_ms"] <= 900     # 250 ms for the timer, then most of the 400 ms transition
    assert sum(naps) >= 0.3                             # the transition runs on the browser's clock, so it was waited for


def test_an_animation_on_an_ancestor_is_waited_for_in_real_time(opened, monkeypatch):
    # The box is hidden by a property that its parent's animation drives; the box itself has no animation.
    body = ("<style>@property --shown{syntax:'<number>';initial-value:0;inherits:true} @keyframes show{to{--shown:1}} "
            "#wrap.on{animation:show .4s linear forwards} #late{opacity:var(--shown);height:40px}</style>" + SPACER +
            '<div id="wrap"><div id="late">late</div></div>' +
            ON_VIEW.format(action="document.querySelector('#wrap').classList.add('on')", ms=250))
    _, driver = opened("ancestor.html", body, "d")
    naps = _naps(monkeypatch)
    rows = motion._scroll_reveal(driver)
    assert 600 <= rows[0]["reveal_delay_ms"] <= 900
    assert sum(naps) >= 0.3


def test_an_animation_that_ended_before_the_look_still_reaches_its_box(opened):
    body = '<div id="a" style="opacity:0;transition:transform .02s"></div><div id="b" style="opacity:0"></div>'
    _, driver = opened("ended.html", body)
    driver.page.evaluate("window.__lapisObserve.animated = new WeakSet(); "
                         "document.querySelector('#a').style.transform = 'translateX(5px)'")
    driver.page.wait_for_timeout(300)               # the transition runs and ends on the browser's clock
    assert driver.page.evaluate("document.getAnimations().length") == 0
    read = {name: driver.page.locator(f"#{name}").evaluate(motion.READ_REVEAL) for name in "ab"}
    assert read == {"a": {"visible": False, "reached": True}, "b": {"visible": False, "reached": False}}


def _settle_naps(monkeypatch) -> list:
    """Every real wait the settle window asks for (the waits still happen)."""
    naps, real = [], settle.sleep
    monkeypatch.setattr(settle, "sleep", lambda seconds: (naps.append(seconds), real(seconds)))
    return naps


def _settle(driver) -> float:
    return settle.quiet(driver, driver.page.evaluate("window.__lapisObserve.mutations"))


def test_a_window_the_page_spends_doing_nothing_is_not_waited_out(opened, monkeypatch):
    _, driver = opened("still.html", "<p>nothing happens here</p>")
    naps = _settle_naps(monkeypatch)
    settled = _settle(driver)
    assert settled >= 500                           # the page's own clock still moved the whole window
    assert len(naps) <= 10                          # real time only for its first 100 ms: about seven 16 ms naps


WORK_OFF_THE_CLOCK = {
    "a worker": "new Worker(URL.createObjectURL(new Blob(['0'])))",
    "a shared worker": "new SharedWorker(URL.createObjectURL(new Blob(['0'])))",
    "WebAssembly": "WebAssembly.instantiate(new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0]))",
}


@pytest.mark.parametrize("start", WORK_OFF_THE_CLOCK.values(), ids=WORK_OFF_THE_CLOCK)
def test_a_page_that_starts_work_off_the_controlled_clock_settles_in_real_time(opened, site, monkeypatch, start):
    site.file("sw.js", "self.addEventListener('fetch', () => {})")
    _, driver = opened("off.html", "<p>nothing happens here</p>")
    driver.page.evaluate(start)
    naps = _settle_naps(monkeypatch)
    assert _settle(driver) >= 500
    assert len(naps) >= 15                          # about twenty-four 16 ms naps and polls for the 500 ms


def test_a_page_that_registers_a_service_worker_is_flagged_for_real_time_settling(opened, site):
    # The registration leaves the worker's script request pending in the driver's network log, which already keeps
    # a window in real time; the flag is what holds once that request is gone.
    site.file("sw.js", "self.addEventListener('fetch', () => {})")
    _, driver = opened("registered.html", "<p>nothing happens here</p>")
    assert driver.page.evaluate("window.__lapisObserve.offClock") is False
    driver.page.evaluate("navigator.serviceWorker.register('/sw.js')")
    assert driver.page.evaluate("window.__lapisObserve.offClock") is True


def test_what_a_worker_answers_after_the_quiet_is_still_in_the_window(opened):
    _, driver = opened("answer.html", '<p id="out">waiting</p>')
    driver.page.evaluate("""() => {
      const worker = new Worker(URL.createObjectURL(new Blob(['setTimeout(() => postMessage("answered"), 350)'])));
      worker.onmessage = event => { out.textContent = event.data; };
    }""")
    _settle(driver)
    assert driver.page.locator("#out").inner_text() == "answered"


def test_real_time_settling_lasts_for_the_rest_of_the_run(opened, site, monkeypatch):
    session, driver = opened("first.html", "<p>first</p>")
    driver.page.evaluate("new Worker(URL.createObjectURL(new Blob(['0'])))")
    _settle(driver)
    site("second.html", "<p>nothing happens here</p>")
    driver.open("second.html")
    naps = _settle_naps(monkeypatch)
    _settle(driver)
    assert len(naps) >= 15
