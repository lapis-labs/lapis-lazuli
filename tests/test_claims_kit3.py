"""What a commit's result message claims (the Outcomes sentence of behavior/DERIVED.md): a negated result that
starts with "cannot", "nothing", "no ...", or "not all" is a failure, "cannot be confirmed" is unknown, and the
completed forms of leaving (unsubscribed, cancelled, 해지됐어요) are a success only for a commit that leaves
something, so "Payment cancelled" after a payment is not one."""
from __future__ import annotations

import pytest

from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import commits, controls
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine
from test_behavior_outcomes import FIXTURES, _serve

EXIT_CLAIMS = FIXTURES / "exit-claims"


@pytest.mark.parametrize("text", [
    "Cannot be saved", "Can't be saved", "Cannot be successfully submitted", "Nothing was saved",
    "Nothing has been sent", "No changes saved", "No items were deleted", "Not all items were saved",
    "Not every item was sent", "Your subscription was not cancelled", "Your account wasn't deleted",
    "Consent was not withdrawn",
])
@pytest.mark.parametrize("leaving", [False, True])
def test_a_result_that_says_nothing_happened_is_a_failure(text, leaving):
    assert commits._claimed(text, leaving) == "failure"


@pytest.mark.parametrize("text", [
    "Cannot be confirmed", "Can't be confirmed", "Could not be confirmed", "Couldn't be confirmed",
    "Your payment cannot be confirmed right now",
])
def test_a_result_that_cannot_be_confirmed_is_unknown(text):
    assert commits._claimed(text) == "unknown"


@pytest.mark.parametrize("text", [
    "Unsubscribed", "You've been unsubscribed", "You have unsubscribed", "Your subscription has been cancelled",
    "Your subscription was canceled", "Cancelled", "Reservation cancelled", "Account deleted", "Consent withdrawn",
    "구독이 해지됐어요", "해지되었습니다", "예약이 취소됐어요", "예약을 취소했어요", "탈퇴했어요",
    "탈퇴가 완료되었습니다", "철회했어요", "계정을 삭제했어요",
])
def test_the_completed_forms_of_leaving_are_a_success_for_a_commit_that_leaves(text):
    assert commits._claimed(text, True) == "success"


@pytest.mark.parametrize("text", [
    "Unsubscribed", "Your subscription has been cancelled", "Payment cancelled", "Account deleted",
    "Consent withdrawn", "구독이 해지됐어요", "결제가 취소됐어요", "예약이 취소됐어요", "탈퇴했어요", "삭제했어요",
])
def test_the_completed_forms_of_leaving_are_not_a_success_after_any_other_commit(text):
    assert commits._claimed(text) == "none"


@pytest.mark.parametrize("text, claim", [
    ("Your subscription will be cancelled on Oct 31", "none"),
    ("You can cancel any time", "none"),
    ("Once cancelled, your plan ends", "none"),
    ("You're still subscribed", "none"),
    ("구독을 해지하지 못했어요", "failure"),
    ("구독이 해지되지 않았어요", "failure"),
    ("해지하면 혜택이 사라져요", "none"),
    ("Couldn't cancel your subscription", "failure"),
])
def test_what_is_not_yet_a_result_stays_none_for_a_commit_that_leaves(text, claim):
    assert commits._claimed(text, True) == claim


@pytest.mark.parametrize("name, kind, leaves", [
    ("Delete account", "delete", True),
    ("Cancel plan", "cancel", True),
    ("Unsubscribe", "subscribe", True),
    ("Cancel subscription", "subscribe", True),
    ("Cancel reservation", "reserve", True),
    ("Withdraw consent", "submit", True),
    ("Stop emails", "submit", True),
    ("구독 해지", "subscribe", True),
    ("예약 취소", "reserve", True),
    ("탈퇴하기", "submit", True),
    ("Pay now", "purchase", False),
    ("Book now – free cancellation", "reserve", False),
    ("Subscribe", "subscribe", False),
    ("예약하기", "reserve", False),
    ("결제하기", "purchase", False),
])
def test_a_commit_leaves_by_its_kind_or_by_the_action_its_name_gives(name, kind, leaves):
    assert commits._exits(name, kind) is leaves


@pytest.mark.parametrize("path, failure", [
    ("cancel-sub", "failure"), ("unsubscribe", "failure"), ("cancel-booking", "failure"),
    ("withdraw", "failure"), ("haeji", "failure"),
    # The words that say a payment was cancelled are not a success, and are not a failure claim either.
    ("pay", "none"),
])
def test_a_commit_that_leaves_claims_success_when_it_says_it_left(browser, path, failure):
    with _serve(EXIT_CLAIMS, single_page=True) as url:
        session = Session(url + path, "account", engine=StubEngine.load(EXIT_CLAIMS / "exit.stub.yaml"))
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
    assert (outcomes["none"]["claimed"], outcomes["none"]["actual"]) == ("success", "applied")
    for mode in ("fail-5xx", "fail-network", "forbidden"):
        assert (outcomes[mode]["claimed"], outcomes[mode]["actual"]) == (failure, "not-applied"), mode
