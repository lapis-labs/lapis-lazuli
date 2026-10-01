"""What the urgency probe reads as a stock, demand, or activity claim, and what it leaves alone: a count with the
noun it counts ("Only 2 sites left", "2곳 남았어요", "잔여 2석"), viewers with words in between, a purchase that
says "booked", and a span that looks back, which is not a countdown."""
from __future__ import annotations

import pytest

from lapis_design.behavior_check.probes import urgency


def claim(text: str):
    return urgency._claim(text, 0)


@pytest.mark.parametrize("text, count", [
    ("전기 되는 자리 2곳 남았어요", 2),
    ("잔여 2석", 2),
    ("마지막 1자리", 1),
    ("남은 3팀", 3),
    ("객실 4실 남았어요", 4),
    ("Only 2 sites left", 2),
    ("3 rooms remaining", 3),
    ("12 sites in stock", 12),
    # Read before this change.
    ("2석 남았어요", 2),
    ("Only 3 left", 3),
    ("5 items left", 5),
    ("재고 7개 남음", 7),
])
def test_a_count_with_the_thing_it_counts_is_a_stock_claim(text, count):
    assert claim(text) == ("stock", count, 0, "items")


@pytest.mark.parametrize("text, count", [
    ("14명이 이 날짜를 보고 있어요", 14),
    ("14 people are viewing this site", 14),
    ("9 visitors are currently looking at this page", 9),
    # Read before this change.
    ("지금 14명이 보고 있어요", 14),
    ("14 people viewing this site", 14),
])
def test_viewers_with_words_between_are_a_demand_claim(text, count):
    assert claim(text) == ("demand", count, 0, "people")


@pytest.mark.parametrize("text, count", [
    ("3 people just booked this", 3),
    ("Someone booked this a minute ago", 1),
    ("방금 예약됐어요", 1),
    ("최근 3시간 동안 5명이 예약했어요", 5),
    ("5 people booked this in the last 3 hours", 5),
])
def test_a_booking_notice_is_an_activity_claim_with_its_count(text, count):
    assert claim(text) == ("activity", count, 0, "events")


@pytest.mark.parametrize("text", [
    "5 minutes left", "3 months remaining", "남은 3개월", "남은 2동안", "5분 남았어요",
    "Booked in the last 3 hours", "Booked in the last 7 days", "최근 3시간 동안 인기",
])
def test_a_span_of_time_is_not_a_count_of_things_left(text):
    assert claim(text) is None


@pytest.mark.parametrize("text, seconds, resolution", [
    ("3시간 남음", 3 * 3600, 3600),
    ("Sale ends in 3 hours", 3 * 3600, 3600),
    ("2 days left", 2 * 86400, 86400),
    ("Closes in the next 3 hours", 3 * 3600, 3600),
])
def test_a_span_that_counts_down_is_still_a_countdown(text, seconds, resolution):
    assert claim(text) == ("countdown", seconds, resolution, "seconds")


@pytest.mark.parametrize("text", [
    "최근 3시간 동안 5명이 예약했어요", "5 people booked this in the last 3 hours", "12 people booked in the past 24 hours",
    "12 people booked this in the last 7 days",
])
def test_a_look_back_window_is_not_a_countdown(text):
    assert claim(text)[0] == "activity"
