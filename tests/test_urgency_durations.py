"""A count of days or hours is time left only when words beside it say time is running out: a period the page
describes ("Keep 30 days of changes", "valid for 90 days", "30일 보관") is a quantity, not a countdown."""
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
    "Keep 30 days of changes from one computer.",
    "Keep 90 days of changes from three computers.",
    "Keep 180 days of changes from ten computers.",
    "Valid for 90 days",
    "Try it free for 14 days",
    "Cancel within 24 hours for a full refund",
    "Support answers within 48 hours",
    "Don't show again for 7 days",
    "Up to 7 days of history",
    "Open 24 hours",
    "30일 보관",
    "최대 7일",
    "14일 무료 체험",
    "24시간 고객센터",
    "환불은 결제 후 24시간 이내에 가능해요",
    "Offer valid for 48 hours only",
    "48시간 한정 특가",
    # A period for paying, cancelling, or refunding is a term of the offer, not time left.
    "Payment due in 30 days",
    "Payment due within the next 7 days",
    "Invoices are due within 14 days of the order",
    "24시간 내에 예약 취소 가능",
])
def test_a_period_the_page_describes_is_not_a_countdown(text):
    assert urgency._claim(text, 0) is None


@pytest.mark.parametrize("text, seconds, resolution", [
    ("2 days left", 2 * 86400, 86400),
    ("Sale ends in 2 days 4 hours", 2 * 86400 + 4 * 3600, 3600),
    ("Sale ends in 2 days", 2 * 86400, 86400),
    ("Only 5 hours remaining", 5 * 3600, 3600),
    ("Time left: 2 days", 2 * 86400, 86400),
    ("Offer expires in just 3 hours", 3 * 3600, 3600),
    ("Starts in 2 days", 2 * 86400, 86400),
    ("Deadline: 3 days", 3 * 86400, 86400),
    ("2 days to go", 2 * 86400, 86400),
    ("3일 남음", 3 * 86400, 86400),
    ("3일 5시간 남았어요", 3 * 86400 + 5 * 3600, 3600),
    ("남은 시간 5시간", 5 * 3600, 3600),
    ("5시간 후 마감", 5 * 3600, 3600),
    ("마감까지 5시간", 5 * 3600, 3600),
    ("Time remaining until the sale ends: 2 days", 2 * 86400, 86400),
    # A cut-off ("order within ...") is a deadline frame; a promise of service within a period is not.
    ("Order within the next 3 hours for same-day shipping", 3 * 3600, 3600),
    ("Order within 3 hrs 20 mins for next-day delivery", 3 * 3600 + 20 * 60, 60),
    ("3시간 내 주문하면 내일 도착해요", 3 * 3600, 3600),
    # Days and hours together are how a timer reads, with or without words around them.
    ("02 Days 04 Hours", 2 * 86400 + 4 * 3600, 3600),
    ("3일 5시간", 3 * 86400 + 5 * 3600, 3600),
    # "for the next" and "within the next" frame a window that is running.
    ("Free shipping for the next 3 hours", 3 * 3600, 3600),
    ("Order for the next 2 days and get a gift", 2 * 86400, 86400),
    # Korean day counts: before 후 마감, and after 마감까지.
    ("2일 후 마감", 2 * 86400, 86400),
    ("3일 후 종료", 3 * 86400, 86400),
    ("마감까지 3일", 3 * 86400, 86400),
    ("만료까지 1일 4시간", 86400 + 4 * 3600, 3600),
    # A cut-off word beside a span is not undone by a payment word in another sentence.
    ("Sale ends in 2 days. Cancel anytime", 2 * 86400, 86400),
    ("Sale ends in 2 days · free refunds", 2 * 86400, 86400),
    # The payment word of a cut-off phrase ("시간 내 결제") is the cut-off, not a payment term.
    ("3시간 내 결제하면 오늘 출발", 3 * 3600, 3600),
])
def test_a_span_that_says_time_is_running_out_is_still_a_countdown(text, seconds, resolution):
    assert urgency._claim(text, 0) == ("countdown", seconds, resolution, "seconds")


@pytest.mark.parametrize("text, claim", [
    # The span beside the running-out words is the one read, not the first one on the line.
    ("Keep 30 days of changes. Offer ends in 3 days", ("countdown", 3 * 86400, 86400, "seconds")),
    ("Offer ends in 3 hours · Keep 30 days of changes", ("countdown", 3 * 3600, 3600, "seconds")),
    # Running-out words in another sentence do not reach across.
    ("Keep 30 days of changes. 3 seats left", ("stock", 3, 0, "items")),
    ("Keep 30 days of changes from the one computer you pick, and 3 seats left", ("stock", 3, 0, "items")),
    # The "left" of a stock claim belongs to its count, even in the same sentence.
    ("Keep 30 days of changes, 3 seats left", ("stock", 3, 0, "items")),
    ("Free for 14 days · 5 spots left", ("stock", 5, 0, "items")),
    # A hold the page names keeps its length.
    ("Your seat is held for 2 hours", ("hold", 2 * 3600, 3600, "seconds")),
])
def test_the_running_out_words_belong_to_the_span_they_sit_beside(text, claim):
    assert urgency._claim(text, 0) == claim


PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><title>Plans</title>
<main>
  <p id="keep">Keep 30 days of changes from one computer.</p>
  <p id="trial">Try it free for 14 days.</p>
  <p id="timer">Sale ends in <strong>2 days</strong></p>
  <p id="cells"><span>02 <small>Days</small></span> <span>04 <small>Hours</small></span></p>
  <p id="payment">Payment due in 30 days.</p>
  <p id="cancel">24시간 내에 예약 취소 가능</p>
  <p id="valid">Offer valid for 48 hours only.</p>
  <p id="shipping">Free shipping for the next 3 hours.</p>
  <p id="deadline-ko">마감까지 3일</p>
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


def test_only_the_countdowns_on_a_page_with_retention_periods_are_claims(browser, page_server):
    session = Session(page_server, "durations", engine=StubEngine.load(STUB))
    urgency.run(session, lambda ctx: Driver(browser, session, ctx))
    entries = session.document()["probes"]["urgency"]
    for ctx in ("m", "d"):
        claims = sorted(entry["readings"][0]["value"] for entry in entries if entry["context"] == ctx)
        assert claims == [3 * 3600, 2 * 86400, 2 * 86400 + 4 * 3600, 3 * 86400], claims
        assert all(entry["kind"] == "countdown" for entry in entries if entry["context"] == ctx)
