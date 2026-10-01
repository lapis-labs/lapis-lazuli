"""A clock time of day is not a countdown: "입실 14:00부터", "11:00까지", "6:00 PM UTC", and a time set apart in its own
element are left alone, while a timer that says time is running out is still read."""
from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import urgency
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine

STUB = Path(__file__).parent / "fixtures" / "behavior" / "time-history" / "app.stub.yaml"


@pytest.mark.parametrize("text", [
    "입실 14:00부터",
    "퇴실 다음 날 11:00까지",
    "매너 타임 22:00부터",
    "입실 14:00 · 퇴실 11:00 · 매너 타임 22:00부터",
    "October 15 · 6:00 PM UTC",
    "October 15, 2026 · 6:00–7:00 PM UTC",
    "Check-in 2:00 pm",
    "Doors open at 18:30",
    "오후 3:00 체크인",
])
def test_a_time_of_day_is_not_a_countdown(text):
    assert urgency._claim(text, 0) is None


@pytest.mark.parametrize("text, kind, seconds", [
    ("Offer ends in 14:59", "countdown", 899),
    ("Sale closes in 05:00", "countdown", 300),
    ("남은 시간 14:00", "countdown", 840),
    ("14:59", "countdown", 899),
    ("01:02:03 left", "countdown", 3723),
    ("Seat held for 09:59", "hold", 599),
    ("좌석을 04:59 동안 임시 예약했어요", "hold", 299),
])
def test_time_running_out_is_still_read(text, kind, seconds):
    assert urgency._claim(text, 0)[:2] == (kind, seconds)


PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>Times</title>
<main>
  <p id="checkin">입실 <strong>14:00</strong>부터</p>
  <p id="event">October 15 · <span>6:00</span> PM UTC</p>
  <p id="timer">Offer ends in <span>14:59</span></p>
</main></html>"""


@pytest.fixture
def page_server(tmp_path):
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_a_time_set_apart_in_its_own_element_is_read_with_the_words_around_it(browser, page_server):
    session = Session(page_server, "clock-times", engine=StubEngine.load(STUB))
    urgency.run(session, lambda ctx: Driver(browser, session, ctx))
    entries = session.document()["probes"]["urgency"]
    for ctx in ("m", "d"):
        claims = [(entry["kind"], entry["readings"][0]["value"]) for entry in entries if entry["context"] == ctx]
        assert claims == [("countdown", 899)], claims
