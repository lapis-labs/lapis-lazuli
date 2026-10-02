"""A clock time of day is not a countdown: "입실 14:00부터", "11:00까지", "6:00 PM UTC", and a time set apart in its own
element are left alone, while a timer that says time is running out is still read. Time-of-day wording counts
only where it sits beside the time, and a `mm:ss` with no words about time running out is a countdown only if
its value goes down."""
from __future__ import annotations

import threading
from contextlib import contextmanager
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
    "Sale ends 11:59 PM tonight",
    "Ends at 23:59",
    "오늘 23:59까지 주문",
    "Offer ends until 6:00 PM",
    "Reserved for you until 14:00",
    "임시 예약 14:00까지 유지",
    "오늘만 특가 02:15:10까지",
    "Order by 17:30 today",
    "Open 9:00–18:00",
    "Doors open 9:00 to 17:00",
    "평일 09:00 ~ 18:00",
    "Check-in from 14:00",
])
def test_a_time_of_day_is_not_a_countdown(text):
    assert urgency._claim(text, 0) is None


@pytest.mark.parametrize("text, kind, seconds", [
    ("Offer ends in 14:59", "countdown", 899),
    ("Sale closes in 05:00", "countdown", 300),
    ("남은 시간 14:00", "countdown", 840),
    ("01:02:03 left", "countdown", 3723),
    ("Seat held for 09:59", "hold", 599),
    ("좌석을 04:59 동안 임시 예약했어요", "hold", 299),
    # 마감까지, 종료까지, and 만료까지 say time is running out, so a time right after them is time left.
    ("마감까지 02:15:10", "countdown", 8110),
    ("종료까지 04:59", "countdown", 299),
    ("만료까지 01:00", "countdown", 60),
    # A time-of-day word elsewhere in the text does not make the time a time of day.
    ("Ends in 02:15:10 from $29", "countdown", 8110),
    ("Sale from today, ends in 04:59", "countdown", 299),
    ("Ends in 04:59 until stock runs out", "countdown", 299),
    ("내일까지 특가, 마감까지 04:59", "countdown", 299),
])
def test_time_running_out_is_still_read(text, kind, seconds):
    assert urgency._claim(text, 0)[:2] == (kind, seconds)


@pytest.mark.parametrize("text, seconds", [
    # The time of day is left out and the two hours are read.
    ("Closes at 18:00, 2 hours left", 2 * 3600),
    ("Check-in from 14:00 · 마감까지 04:59", 299),
    ("Doors open at 18:30 · 3시간 남음", 3 * 3600),
])
def test_a_time_of_day_is_a_time_of_day_whatever_else_the_text_says(text, seconds):
    assert urgency._claim(text, 0)[:2] == ("countdown", seconds)


@pytest.mark.parametrize("text", [
    "09:30", "14:00", "14:59", "10:30 예약 가능", "진료 09:00", "Posted 12:45", "Video 12:34", "John 3:16", "Ratio 16:10",
    "점심 12:30 13:30", "Flash sale 04:59 from $29", "Sale ends at midnight 02:15:10", "Hurry! Offer ends 04:59",
    "특가 마감 04:59", "Look at this deal 09:59",
])
def test_a_clock_time_with_no_words_about_time_running_out_is_not_a_claim_until_it_goes_down(text):
    assert urgency._claim(text, 0) is None


PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>Times</title>
<main>
  <p id="checkin">입실 <strong>14:00</strong>부터</p>
  <p id="event">October 15 · <span>6:00</span> PM UTC</p>
  <p id="timer">Offer ends in <span>14:59</span></p>
</main></html>"""


@contextmanager
def _serving(tmp_path, page):
    (tmp_path / "index.html").write_text(page, encoding="utf-8")

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


@pytest.fixture
def page_server(tmp_path):
    with _serving(tmp_path, PAGE) as url:
        yield url


def test_a_time_set_apart_in_its_own_element_is_read_with_the_words_around_it(browser, page_server):
    session = Session(page_server, "clock-times", engine=StubEngine.load(STUB))
    urgency.run(session, lambda ctx: Driver(browser, session, ctx))
    entries = session.document()["probes"]["urgency"]
    for ctx in ("m", "d"):
        claims = [(entry["kind"], entry["readings"][0]["value"]) for entry in entries if entry["context"] == ctx]
        assert claims == [("countdown", 899)], claims


SLOTS = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>Clinic</title>
<main>
  <p id="slots"><button type="button">09:30</button> <button type="button">10:30 예약 가능</button></p>
  <p id="hours">평일 09:00 ~ 18:00</p>
  <p id="video">Video 12:34</p>
  %s
</main></html>"""
TICKING = """<p id="spots">5 spots left · <span>10:30</span> slot</p>
  <p id="timer">Offer ends in <span>14:59</span></p>
  <p id="batch">Next batch in <span id="batch-time">04:59</span></p>
  <script>
    const end = Date.now() + 299000;
    const paint = () => {
      const seconds = Math.max(0, Math.ceil((end - Date.now()) / 1000));
      document.getElementById("batch-time").textContent =
        String(Math.floor(seconds / 60)).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
    };
    paint(); setInterval(paint, 1000);
  </script>"""


def test_a_bare_clock_time_is_a_claim_only_when_it_goes_down(browser, tmp_path):
    with _serving(tmp_path, SLOTS % TICKING) as url:
        session = Session(url, "clock-slots", engine=StubEngine.load(STUB))
        urgency.run(session, lambda ctx: Driver(browser, session, ctx))
    document = session.document()
    entries = document["probes"]["urgency"]
    for ctx in ("m", "d"):
        claims = sorted((entry["kind"], entry["readings"][0]["value"]) for entry in entries if entry["context"] == ctx)
        # The ticking batch time (04:59, a little less once the page has loaded), the timer that says it ends in
        # 14:59, and the stock of the line that also holds a slot time. The slot buttons, the opening hours, and
        # "Video 12:34" never change and are not claims.
        assert [claim[0] for claim in claims] == ["countdown", "countdown", "stock"], claims
        assert 290 <= claims[0][1] <= 299 and claims[1][1] == 899 and claims[2][1] == 5, claims
        ticking = next(entry for entry in entries if entry["context"] == ctx and entry["kind"] == "countdown"
                       and entry["readings"][0]["value"] < 300)
        assert [reading["when"] for reading in ticking["readings"]][:2] == ["load", "later"]
        assert ticking["readings"][1]["value"] < ticking["readings"][0]["value"]
    assert next(entry for entry in document["coverage"] if entry["probe"] == "urgency")["status"] == "ran"


def test_a_page_of_times_that_never_change_has_no_urgency_claims(browser, tmp_path):
    with _serving(tmp_path, SLOTS % "") as url:
        session = Session(url, "clock-slots", engine=StubEngine.load(STUB))
        urgency.run(session, lambda ctx: Driver(browser, session, ctx))
    document = session.document()
    assert document["probes"].get("urgency", []) == []
    assert next(entry for entry in document["coverage"] if entry["probe"] == "urgency")["status"] == "not-applicable"
