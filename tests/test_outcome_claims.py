"""What a commit's result message claims: the order the readings are tried in (cannot confirm, then a
negated or stopped result, then kept on the device, then success, then in progress), the phrases that
name a result without reporting one, and reading only the text the region did not show before."""
from __future__ import annotations

import re

import pytest

from lapis_design.behavior_check.probes import commits
from lapis_design.behavior_check.probes._decision import WAITING


@pytest.mark.parametrize("text, claim", [
    # The rows of the contract's Outcomes sentence that used to read backwards.
    ("이 기기에 저장하지 못했어요", "failure"),
    ("결제를 완료하지 않았어요", "failure"),
    ("저장하지 않았어요", "failure"),
    ("예약 완료 후 문자를 보내 드려요", "none"),
    ("결제가 완료되지 않으면 예약이 취소돼요", "none"),
    ("미완료 상태예요", "none"),
    ("결제 중단됐어요", "failure"),
    ("전송 중지됨", "failure"),
    ("기다려 주셔서 감사해요", "none"),
    ("저장하였습니다", "success"),
    ("예약하였습니다", "success"),
    ("Payment not completed", "failure"),
    ("Message not sent", "failure"),
    ("Couldn't send", "failure"),
    ("예약이 접수됐는지 확인하지 못했어요", "unknown"),
    ("Couldn't confirm your payment", "unknown"),
    ("Couldn’t confirm your payment", "unknown"),
    ("결제됐는지 확인할 수 없어요", "unknown"),
    ("We could not confirm the booking", "unknown"),
])
def test_commit_result_table_reads_negation_conditionals_and_unconfirmed_first(text, claim):
    assert commits._claimed(text) == claim


@pytest.mark.parametrize("text, claim", [
    ("Thanks, you're subscribed!", "success"), ("You signed up", "success"), ("Registered", "success"),
    ("Form submitted", "success"), ("Paid", "success"), ("Seat booked", "success"), ("Order placed", "success"),
    ("Reservation saved", "success"), ("Reservation confirmed", "success"),
    # A negated result is a failure whichever verb form it has.
    ("Payment not paid", "failure"), ("Your order was not placed", "failure"), ("Not subscribed", "failure"),
    ("Booking hasn't been saved", "failure"), ("It never got sent, message not sent", "failure"),
    ("Message did not send", "failure"), ("Wasn't able to save", "failure"), ("Couldn't cancel", "failure"),
    ("Payment failed after 3 attempts", "failure"),
    # A condition, a future, or a state that was there already names a result without reporting one.
    ("Once saved, we'll email you", "none"), ("You'll get a receipt when the payment is completed", "none"),
    ("Your order will be placed shortly", "none"), ("Your booking will be confirmed by email", "none"),
    ("You're still subscribed", "none"), ("This email is already registered", "none"),
    ("Payment will not be completed until you confirm", "none"),
    # Not a result: an instruction, a button.
    ("Don't forget to pay by Friday", "none"), ("Sign up", "none"), ("Pay now", "none"),
])
def test_english_results_read_the_completed_forms_and_not_their_conditions(text, claim):
    assert commits._claimed(text) == claim


def test_still_subscribed_after_a_failed_cancel_is_not_a_success():
    assert commits._claimed("You're still subscribed") == "none"
    assert commits._claimed("Couldn't cancel your subscription. You're still subscribed.") == "failure"
    assert commits._claimed("구독을 해지하지 못했어요. 아직 구독 중이에요") == "failure"


@pytest.mark.parametrize("text, claim", [
    ("결제가 완료되지 않았다면 예약이 취소돼요", "none"), ("완료 시 문자를 보내 드려요", "none"),
    ("완료시 알려 드려요", "none"), ("완료 예정이에요", "none"), ("완료 시각 10:30", "success"),
    ("결제가 완료되었어요", "success"), ("저장 완료", "success"),
    ("이 기기에 저장했어요", "saved-locally"), ("이 기기에 저장하였어요", "saved-locally"),
    ("Saved to this device", "saved-locally"), ("Saved on this device", "saved-locally"),
    # Only past tense is kept on the device; a note about what will happen is not.
    ("이 기기에 저장돼요", "none"), ("Will be saved to this device", "none"), ("Saves on this device", "none"),
    # A device save that failed is a failure, since the negation is read before it.
    ("이 기기에 저장하지 않았어요", "failure"), ("Not saved on this device", "failure"),
])
def test_device_save_and_completion_read_only_the_past_tense(text, claim):
    assert commits._claimed(text) == claim


@pytest.mark.parametrize("text, claim", [
    ("저장 중…", "pending"), ("결제 중이에요", "pending"), ("잠시만 기다려 주세요", "pending"),
    ("기다려 주세요", "pending"), ("진행 중이에요", "pending"), ("Saving reservation", "pending"),
    ("결제 중단됐어요", "failure"), ("결제 중지됐어요", "failure"), ("진행 중단됨", "failure"),
    ("기다려 주셔서 감사해요", "none"), ("오래 기다려 주셨어요", "none"),
])
def test_pending_wording_leaves_out_stopped_and_thanks_for_waiting(text, claim):
    assert commits._claimed(text) == claim


@pytest.mark.parametrize("text, waiting", [
    ("저장 중", True), ("처리 중이에요", True), ("잠시만 기다려 주세요", True), ("기다려 주시겠어요", True),
    ("전송 중단", False), ("결제 중지", False), ("기다려 주셔서 감사합니다", False), ("please wait", True),
])
def test_waiting_wording_is_shared_with_the_pending_state(text, waiting):
    assert bool(re.search(WAITING, text, re.I)) is waiting


def test_a_stop_button_in_a_pending_region_is_not_a_failure():
    # 저장 중… with a 중지 button beside it is still pending: only a stopped result is a failure.
    assert commits._claimed("저장 중… 중지") == "pending"


def test_new_text_leaves_out_notes_the_region_already_showed():
    before = ["예약 확정하기\n예약 완료 후 문자를 보내 드려요", ""]
    after = ["예약 확정하기\n예약 완료 후 문자를 보내 드려요", "결제를 완료하지 않았어요"]
    assert commits._new_text(before, after) == "결제를 완료하지 않았어요"
    assert commits._new_text(before, before) == ""


def test_new_text_reads_a_sentence_at_a_time():
    before = ["Changes are saved on this device only. This cannot be undone."]
    after = ["Changes are saved on this device only. This cannot be undone. Payment not completed."]
    assert commits._new_text(before, after) == "Payment not completed."
    # A line that repeats is new only as many times as it grew.
    assert commits._new_text(["Saved"], ["Saved", "Saved"]) == "Saved"
    assert commits._new_text([], ["Reservation saved"]) == "Reservation saved"


@pytest.mark.parametrize("before, after, claim", [
    (["This cannot be undone. Your last booking was confirmed."], ["This cannot be undone. Your last booking was confirmed."], "none"),
    (["We'll email you once your booking is confirmed."],
     ["We'll email you once your booking is confirmed.", "Something went wrong."], "none"),
    (["We'll email you once your booking is confirmed."],
     ["We'll email you once your booking is confirmed.", "Payment not completed"], "failure"),
    (["지난 예약이 확정됐어요"], ["지난 예약이 확정됐어요", "잠시 후 다시 확인해 주세요"], "none"),
    ([""], ["예약이 완료됐어요"], "success"),
])
def test_a_claim_is_read_from_what_was_not_there_before_the_commit(before, after, claim):
    assert commits._claimed(commits._new_text(before, after)) == claim
