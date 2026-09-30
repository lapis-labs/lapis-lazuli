"""Loopback tests of actual pointer, motion, and scroll observations."""
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
from lapis_design.behavior_check.probes import motion, pointer, scroll
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine

APP=Path(__file__).parent / "fixtures" / "behavior" / "motion-observations"
STUB=APP / "motion.stub.yaml"


@pytest.fixture
def movement_server():
    handler=partial(SimpleHTTPRequestHandler,directory=str(APP))
    server=ThreadingHTTPServer(("127.0.0.1",0),handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.fixture
def probe_session(browser,movement_server):
    schema=yaml.safe_load((shared_dir()/"behavior"/"stub.schema.yaml").read_text())
    jsonschema.Draft202012Validator(schema).validate(yaml.safe_load(STUB.read_text()))
    session=Session(movement_server,"movement",engine=StubEngine.load(STUB))
    def open_driver(ctx_id):
        driver=Driver(browser,session,ctx_id)
        driver.open()
        return driver
    yield session,open_driver
    for driver in tuple(session.drivers):driver.close()


def _id(session,fragment):
    return next(key for key,value in session.nodes.items() if fragment in value.get("name",""))


def test_pointer_drag_alternatives_and_hover(probe_session):
    session,open_driver=probe_session
    started=monotonic()
    pointer.run(session,open_driver)
    rows=session.probes["pointer"]
    d=[row for row in rows if row["context"]=="d"]
    assert any(row["kind"]=="drag" and row["alternative"]=="buttons" for row in d), [(session.nodes[x["box"]].get("name"),x["kind"],x.get("alternative")) for x in d]
    assert any(row["kind"]=="drag" and row["alternative"]=="none" for row in d)
    assert any(row["kind"]=="drag" and row["alternative"]=="keyboard-only" for row in d)
    m=[row for row in rows if row["context"]=="m"]
    assert any(row["kind"]=="path-gesture" and row["alternative"]=="menu" for row in m),m
    assert any(row["kind"]=="multipoint" and row["alternative"]=="none" for row in m),m
    hover=[row for row in d if row["kind"]=="hover-reveal"]
    assert any(row["on_focus_too"] and row["dismissible"] and row["hoverable"] and row["persistent"]
               for row in hover), [(session.nodes[x["box"]].get("name"),x["on_focus_too"],x["dismissible"],x["hoverable"],x["persistent"]) for x in hover]
    assert any(not row["on_focus_too"] and not row["dismissible"] for row in hover)
    assert all(row["revealed"] and all(bid in session.nodes for bid in row["revealed"]) for row in hover)
    assert session.coverage[-1]["status"]=="ran"
    print(f"pointer runtime: {monotonic()-started:.2f}s")


def test_pointer_local_dev_skips_state_changing_gestures(browser,movement_server):
    session=Session(movement_server,"movement",backend="local-dev",outbound="none")
    def open_driver(ctx_id):
        driver=Driver(browser,session,ctx_id)
        driver.open()
        return driver
    try:
        pointer.run(session,open_driver)
        assert session.coverage[-1]["status"]=="partial"
        assert "local-dev" in session.coverage[-1]["reason"]
        assert all(row["kind"]!="drag" or session.nodes[row["box"]]["role"]=="input"
                   for row in session.probes["pointer"])
    finally:
        for driver in tuple(session.drivers):driver.close()


def _media_ids(open_driver,ctx_id):
    driver=open_driver(ctx_id)
    try:
        return dict(driver.page.evaluate("""() => ['bg-video','particles','live-chart'].map(id =>
            [id, document.getElementById(id).getAttribute('data-lapis-box')])"""))
    finally:
        driver.close()


@pytest.mark.parametrize("base",["m","d"])
def test_motion_reduced_twin_and_controls(probe_session,base):
    session,open_driver=probe_session
    # One base context and its reduced-motion twin per test, so the two take turns on different workers;
    # the detail is read on the desktop one.
    session.contexts={base:session.contexts[base]}
    started=monotonic()
    motion.run(session,open_driver)
    rows={row["context"]:row for row in session.probes["motion"]}
    twin=base+"-rm"
    assert rows[twin]["compare_to"]==base
    assert all(row["window_ms"]==5000 for row in rows.values())
    if base=="d":
        assert any(item["kind"]=="transform" for item in rows["d"]["moving"])
        assert any(item["kind"]=="opacity" for item in rows["d"]["moving"])
        assert all(item["kind"]!="opacity" for item in rows["d-rm"]["moving"])
        assert any(item["kind"]=="transform" for item in rows["d-rm"]["moving"])
        assert any(not item["pause_control"] for item in rows["d"]["auto_moving"])
        assert any(item["pause_control"] for item in rows["d"]["auto_moving"])
        assert any(item["hidden_at_rest"] and item.get("reveal_delay_ms",0)>=200
                   for item in rows["d"]["scroll_reveal"])
        assert rows["d"]["hover_media"]=={"total":3,"transforming":1}  # two images and the video
    else:
        assert "hover_media" not in rows["m"]
    assert all(bid in session.nodes for row in rows.values()
               for bid in [i["box"] for i in row["moving"]+row["auto_moving"]+row["scroll_reveal"]])
    if base=="d":
        assert rows["d"]["input_blocked_ms"]==0
    ids=_media_ids(open_driver,base)
    by_box={item["box"]:item for item in rows[twin]["moving"]}
    assert by_box[ids["bg-video"]]["kind"]=="video" and not by_box[ids["bg-video"]]["essential"]
    assert by_box[ids["particles"]]["kind"]=="canvas" and not by_box[ids["particles"]]["essential"]
    assert by_box[ids["live-chart"]]["kind"]=="canvas" and by_box[ids["live-chart"]]["essential"]
    if base=="d":
        assert not any(item["essential"] for item in rows["d"]["moving"]
                       if item["kind"] not in ("canvas","video"))
    assert session.coverage[-1]["status"]=="ran"
    schema=yaml.safe_load((shared_dir()/"behavior"/"session.schema.yaml").read_text())
    jsonschema.Draft202012Validator(schema).validate(session.document())
    print(f"motion runtime: {monotonic()-started:.2f}s")


def test_scroll_three_inputs_and_touch(probe_session):
    session,open_driver=probe_session
    started=monotonic()
    scroll.run(session,open_driver)
    rows=session.probes["scroll"]
    assert {row["input"] for row in rows if row["context"]=="m"}=={"wheel","space","arrow","touch"},session.coverage
    assert {row["input"] for row in rows if row["context"]=="d"}=={"wheel","space","arrow"}
    assert all(row["expected_px"]>0 and row["actual_px"]>0 and not row["blocked"] for row in rows),[(x["context"],x["input"],x["expected_px"],x["actual_px"]) for x in rows]
    assert session.coverage[-1]["status"]=="ran"
    print(f"scroll runtime: {monotonic()-started:.2f}s")


@pytest.mark.parametrize("path,field", [
    ("scroll-jack.html","snapped"),("smooth.html","animated_ms"),("blocked.html","blocked"),
])
def test_scroll_jacking_smooth_and_blocked(browser,movement_server,path,field):
    session=Session(movement_server,"scroll-variant",engine=StubEngine.load(STUB))
    def open_driver(ctx_id):
        driver=Driver(browser,session,ctx_id)
        driver.open("/"+path)
        return driver
    try:
        scroll.run(session,open_driver)
        row=next(row for row in session.probes["scroll"]
                 if row["context"]=="d" and row["input"]=="wheel")
        assert row["expected_px"]>0 and (row["actual_px"]>0 if field!="blocked" else row["actual_px"]==0)
        assert row[field], row
    finally:
        for driver in tuple(session.drivers):driver.close()


def test_input_blocked_while_animation_runs(browser,movement_server):
    session=Session(movement_server,"busy",engine=StubEngine.load(STUB))
    driver=Driver(browser,session,"d")
    try:
        driver.open("/busy.html")
        assert motion._input_blocked(driver)==2000
    finally:
        driver.close()
