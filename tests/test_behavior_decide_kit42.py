"""Kit Q42 (G81-G85, G88, G89, bare refusals, G125 status words): how the probes read a control's name, a
dialog's question, a commit's message, an option's price, and the text a box gained. Pure wording; the status
text of a changed box in a real page is in test_behavior_status_text.py."""
from __future__ import annotations

import re
import types

import pytest

from lapis_design.behavior_check.probes import choices, commits, flows
from lapis_design.behavior_check.probes._decision import (
    BARE_REFUSAL, LATER, REFUSE, asks_exit, new_text, reads_as_status, response)


def _screen(names, dialog_text, prompt=None):
    controls = [dict(id=f"b{i}", name=name, type="button", required=False, filled=False, checked=False,
                     disabled=False, in_main=False, in_dialog=True, href="", name_attr="", autocomplete="",
                     rect={"y": 0, "h": 10}) for i, name in enumerate(names)]
    screen = {"dialog": "d1", "dialog_text": dialog_text, "controls": controls, "_context": "d"}
    if prompt is not None:
        screen["dialog_prompt"] = prompt
    return screen


SESSION = types.SimpleNamespace(contexts={"d": {"pointer": "fine"}}, values_engine=None)


def _order(names, text, kind, goal, *, prompt=None):
    """Every control `flows._choose` presses on a dialog, in order, until it would stop."""
    screen, tried, out = _screen(names, text, prompt), set(), []
    while True:
        action, chosen = flows._choose(screen, {"kind": kind, "goal": goal}, tried, SESSION)
        if action is None:
            return out
        out.append(chosen)
        tried.add(action["target"])


# G81: a negated result is a failure; "no longer" and "no" before a number or identifier are not negations.

@pytest.mark.parametrize("text, leaving, claim", [
    ("You are no longer subscribed", True, "success"), ("You are no longer subscribed", False, "success"),
    ("Order no 1234 confirmed", False, "success"), ("Ref no A12 saved", False, "success"),
    ("No changes saved", False, "failure"), ("No payment was processed", False, "failure"),
    ("Nothing was saved", False, "failure"), ("Not all items were saved", False, "failure"),
])
def test_no_longer_and_no_before_an_identifier_are_not_a_negated_result(text, leaving, claim):
    assert commits._claimed(text, leaving) == claim


# G89: leaving is completed in Korean passive forms, an unknown error is a failure, a notice is not a refusal.

@pytest.mark.parametrize("text, leaving, claim", [
    ("수신 거부되었습니다", True, "success"), ("삭제됨", True, "success"), ("해지되었습니다", True, "success"),
    ("수신 거부되었습니다", False, "none"), ("삭제됨", False, "none"),
    ("An unknown error occurred. Try again.", False, "failure"), ("Unknown error", False, "failure"),
    ("Your payment status is unknown", False, "unknown"), ("결제됐는지 확인할 수 없어요", False, "unknown"),
])
def test_exit_completed_forms_and_an_unknown_error_are_read_as_what_they_say(text, leaving, claim):
    assert commits._claimed(text, leaving) == claim


@pytest.mark.parametrize("name, request_, kind, leaves", [
    ("Unsubscribe", {"method": "POST", "path": "/api/unsubscribe"}, "cancel", True),
    ("구독 해지", {"method": "POST", "path": "/api/x"}, "cancel", True),
    ("Cancel subscription", {"method": "POST", "path": "/api/x"}, "cancel", True),
    ("구독 취소", {"method": "POST", "path": "/api/x"}, "cancel", True),
    ("주문 취소", {"method": "POST", "path": "/api/x"}, "cancel", True),
    ("예약 취소", {"method": "POST", "path": "/api/x"}, "cancel", True),
    ("결제 취소", {"method": "POST", "path": "/api/x"}, "cancel", True),
    ("Cancel booking", {"method": "POST", "path": "/api/x"}, "cancel", True),
    ("Withdraw consent", {"method": "POST", "path": "/api/x"}, "cancel", True),
    ("Delete subscription", {"method": "POST", "path": "/api/x"}, "delete", True),
    ("Delete account", {"method": "POST", "path": "/api/x"}, "delete", True),
    # A name that mentions leaving without being the action keeps the kind its other words give.
    ("Book with free cancellation", {"method": "POST", "path": "/api/x"}, "reserve", False),
    ("무료 취소 가능 예약하기", {"method": "POST", "path": "/api/x"}, "reserve", False),
    ("Non-stop flights: book", {"method": "POST", "path": "/api/x"}, "reserve", None),
    ("Subscribe", {"method": "POST", "path": "/api/x"}, "subscribe", False),
    ("Pay now", {"method": "POST", "path": "/api/x"}, "purchase", False),
    ("Reserve", {"method": "POST", "path": "/api/x"}, "reserve", False),
    # A name that negates the exit is neither the exit action nor an exit commit (G84).
    ("Don't cancel", {"method": "POST", "path": "/api/x"}, "submit", False),
    ("해지 취소", {"method": "POST", "path": "/api/x"}, "submit", False),
    ("취소 안 함", {"method": "POST", "path": "/api/x"}, "submit", False),
    ("Keep my plan", {"method": "POST", "path": "/api/keep"}, "submit", False),
])
def test_a_commit_named_for_leaving_is_that_kind_before_the_word_it_leaves(name, request_, kind, leaves):
    assert commits._kind(name, request_) == kind
    if leaves is not None:
        assert commits._exits(name, commits._kind(name, request_)) is leaves


# G82, G83: refusals of consent. A name that refuses or declines gets no points for agreeing.

@pytest.mark.parametrize("name", [
    "Do not agree", "I don't agree", "I do not agree", "Disagree", "Don't accept", "Deny", "Refuse", "Do not allow",
    "Don't allow", "Allow necessary cookies", "Accept essential", "Accept necessary only", "Essential cookies only",
    "필수 항목만 동의", "필수 약관만 동의", "필수적인 쿠키만 허용", "필수만 허용", "필수 쿠키만 허용", "선택 항목 제외하고 동의",
    "동의 안 함", "동의하지 않고 계속", "Continue without accepting", "허용 안 함",
])
def test_refusals_of_consent_and_necessary_only_choices_are_refuse(name):
    assert re.search(REFUSE, name, re.I)


@pytest.mark.parametrize("name", [
    "I agree", "Agree", "Accept all", "Allow all", "Accept", "모두 동의", "모두 허용", "동의하고 계속", "동의", "필수 항목 입력",
    "동의 안내", "알림 허용 안내", "Allow notifications",
])
def test_agreement_and_notices_that_mention_it_are_not_refuse(name):
    assert not re.search(REFUSE, name, re.I)


@pytest.mark.parametrize("name", ["No thanks", "No, thanks", "No thank you", "Deny", "Reject all", "필수 항목만 동의"])
def test_a_refusing_name_is_a_decline_in_every_probe(name):
    assert choices._kind(name, "button", "consent") == "decline"
    assert response([{"id": "b", "text": name}])[0] == "decline"


@pytest.mark.parametrize("names, text, chosen", [
    (["I agree", "Continue without accepting"], "Please agree to the Terms of Service", "I agree"),
    (["Continue without accepting", "I agree"], "Please agree to the Terms of Service", "I agree"),
    (["동의", "동의하지 않고 계속"], "이용약관 동의가 필요해요", "동의"),
    (["동의하지 않고 계속", "동의"], "이용약관 동의가 필요해요", "동의"),
    (["I do not agree", "I agree"], "Please agree to the Terms of Service", "I agree"),
    (["I don't agree", "I agree"], "Please agree to the Terms of Service", "I agree"),
    (["Disagree", "Agree"], "Please agree to the Terms of Service", "Agree"),
    (["Do not allow", "Accept"], "Please accept the Terms of Service to continue", "Accept"),
])
def test_a_terms_dialog_is_agreed_to_never_refused(names, text, chosen):
    assert _order(names, text, "signup", "Sign up")[0] == chosen
    assert "Continue without accepting" not in _order(names, text, "signup", "Sign up")[:1]


def test_a_refusal_in_a_terms_dialog_is_never_pressed():
    pressed = _order(["I agree", "Continue without accepting", "I do not agree"], "Please agree to the Terms of Service",
                     "signup", "Sign up")
    assert pressed == ["I agree"]


@pytest.mark.parametrize("names, text, chosen", [
    # Necessary-only is the refusal of the optional part; the cookie dialog is an optional offer.
    (["모두 동의", "필수 항목만 동의"], "쿠키를 사용해요. 마케팅 쿠키는 선택이에요.", "필수 항목만 동의"),
    (["모두 동의", "필수적인 쿠키만 허용"], "쿠키를 사용해요. 마케팅 쿠키는 선택이에요.", "필수적인 쿠키만 허용"),
    (["Allow all", "Allow necessary cookies"], "We use cookies for marketing.", "Allow necessary cookies"),
    (["Accept all", "Accept essential"], "We use cookies for marketing.", "Accept essential"),
    (["Accept all", "Do not allow"], "We use cookies for marketing.", "Do not allow"),
    (["Accept all", "Deny"], "We use cookies for marketing.", "Deny"),
    (["I agree", "I do not agree"], "We use cookies for marketing.", "I do not agree"),
])
def test_a_cookie_dialog_is_answered_with_the_refusal(names, text, chosen):
    assert _order(names, text, "signup", "Sign up")[0] == chosen


# G88: a put-off is the word alone, a phrase, or 나중에/다음에 followed by anything but an action noun.

@pytest.mark.parametrize("name, later", [
    ("Maybe later", True), ("Later", True), ("Ask me later", True), ("Remind me later", True), ("Not now", True),
    ("나중에", True), ("나중에 할게요", True), ("나중에 하겠습니다", True), ("나중에 할께요", True), ("나중에 볼래요", True),
    ("나중에 결정할게요", True), ("나중에요", True), ("다음에", True), ("다음에 할게요", True), ("다음에 할래요", True),
    ("다음에 볼게요", True),
    ("Pay later", False), ("Save for later", False), ("나중에 결제", False), ("나중에 결제하기", False), ("나중에 구매", False),
    ("다음에 주문", False), ("나중에 저장", False), ("나중에 예약하기", False), ("나중에 신청", False), ("다음", False),
])
def test_put_off_wording(name, later):
    assert bool(re.search(LATER, name, re.I)) is later
    if name != "Not now":                                         # also a decline, which the kind reads first
        assert (choices._kind(name, "button", "upsell") == "dismiss") is later


def test_a_put_off_is_pressed_before_the_action_it_would_take():
    assert _order(["Yes, add it", "Ask me later"], "Special offer: add gift wrap", "purchase", "buy the bowl")[0] == "Ask me later"
    assert _order(["추가하기", "나중에 하겠습니다"], "특가 제안: 액자를 1만원에 추가하세요", "purchase", "액자 구매")[0] == "나중에 하겠습니다"
    assert _order(["지금 결제", "나중에 결제"], "특가 제안: 액자를 1만원에 추가하세요", "purchase", "액자 구매")[0] == "지금 결제"


# Bare refusals: the whole name is No, Never, 아니요, 싫어요, 안 할래요, or 나가기.

@pytest.mark.parametrize("name, bare", [
    ("No", True), ("no.", True), ("Never", True), ("아니요", True), ("아니오", True), ("싫어요", True), ("안 할래요", True),
    ("나가기", True), ("No thanks", False), ("Nope", False), ("아니요, 유지할게요", False), ("Not now", False),
    ("No more emails", False), ("Never mind", False), ("Notify me", False),
])
def test_a_bare_refusal_is_the_whole_name(name, bare):
    assert bool(re.search(BARE_REFUSAL, name, re.I)) is bare


@pytest.mark.parametrize("name", ["No", "Never", "아니요", "싫어요", "안 할래요", "나가기"])
def test_a_bare_refusal_is_a_decline_and_in_a_confirmation_neutral(name):
    assert choices._kind(name, "button", "upsell") == "decline"
    assert choices._kind(name, "button", "confirm") == "neutral"
    assert response([{"id": "b", "text": name}])[0] == "decline"


@pytest.mark.parametrize("names, text, kind, goal, chosen", [
    (["Yes", "No"], "Special offer: add gift wrap for $5?", "purchase", "buy the bowl", "No"),
    (["좋아요", "싫어요"], "특가 제안: 선물 포장을 추가할까요?", "purchase", "그릇 구매", "싫어요"),
    (["혜택 받기", "나가기"], "떠나기 전에 10% 할인 혜택을 받아 보세요", "purchase", "그릇 구매", "나가기"),
    (["Yes, upgrade", "Never"], "Upgrade offer: try Premium free", "purchase", "Buy the print", "Never"),
])
def test_an_offer_is_turned_down_by_a_bare_refusal(names, text, kind, goal, chosen):
    assert _order(names, text, kind, goal)[0] == chosen


# G84: in an exit flow, the question can be the exit itself.

@pytest.mark.parametrize("prompt, asks", [
    ("Cancel the subscription?", True), ("정말 해지하시겠어요?", True), ("정말 나가시겠어요?", True),
    ("정말 해지하시겠어요? 지금 해지하면 할인 혜택이 사라져요.", True), ("구독을 해지할까요", True),
    ("Delete your account?", True), ("Are you sure you want to leave?", True),
    ("Before you cancel\nStay for 50% off for 3 months?", False), ("Before you cancel. Special offer: 50% off.", False),
    ("Special offer: add gift wrap for $5?", False), ("Are you sure?", False), ("Cancel anytime. Keep your plan?", False),
    ("해지하기 전에 잠깐만요 지금 계속 이용하시면 할인해 드려요", False), ("", False),
])
def test_a_dialog_asks_about_the_exit_when_a_question_holds_exit_or_cancel_wording(prompt, asks):
    assert asks_exit(prompt) is asks


KO_RETENTION = "정말 해지하시겠어요? 지금 해지하면 할인 혜택이 사라져요."
EN_RETENTION = "Cancel the subscription? You will lose your discount."


@pytest.mark.parametrize("names, text, goal, pressed", [
    (["아니요, 유지할게요", "네, 해지할게요"], KO_RETENTION, "구독을 해지한다", ["네, 해지할게요"]),
    (["네, 해지할게요", "아니요, 유지할게요"], KO_RETENTION, "구독을 해지한다", ["네, 해지할게요"]),
    (["아니요", "네"], "구독을 해지할까요? 해지하면 할인 혜택이 사라져요.", "구독을 해지한다", ["네"]),
    (["No thanks", "Yes, cancel"], EN_RETENTION, "cancel the subscription", ["Yes, cancel"]),
    (["No", "Yes"], EN_RETENTION, "cancel the subscription", ["Yes"]),
    (["No", "Leave"], "Leave the subscription? You will lose your discount.", "cancel the subscription", ["Leave"]),
    (["아니요", "나가기"], "정말 나가시겠어요? 해지하면 할인 혜택이 사라져요.", "구독을 해지한다", ["나가기"]),
])
def test_when_the_question_is_the_exit_the_stay_side_is_not_a_decline_and_the_exit_side_is_the_confirm(names, text, goal, pressed):
    assert _order(names, text, "cancel-subscription", goal) == pressed


def test_a_retention_offer_whose_heading_speaks_of_cancelling_is_still_turned_down():
    text = "Before you cancel\nStay for 50% off for 3 months?"
    assert asks_exit(text) is False
    assert _order(["Yes, claim 50%", "No thanks", "Cancel subscription"], text, "cancel-subscription",
                  "cancel the subscription", prompt=text)[0] == "No thanks"


@pytest.mark.parametrize("names, goal, pressed", [
    (["해지 취소", "해지하기"], "구독을 해지한다", ["해지하기"]),
    (["Don't cancel", "Cancel subscription"], "cancel the subscription", ["Cancel subscription"]),
    (["취소 안 함", "해지"], "구독을 해지한다", ["해지"]),
    (["Keep my plan", "Cancel subscription"], "cancel the subscription", ["Cancel subscription"]),
    (["유지할게요", "해지하기"], "구독을 해지한다", ["해지하기"]),
])
def test_a_name_that_negates_the_exit_backs_out_and_is_not_the_exit_action(names, goal, pressed):
    text = "정말 해지하시겠어요?" if "해지하기" in names or "해지" in names else "Are you sure?"
    assert _order(names, text, "cancel-subscription", goal) == pressed


@pytest.mark.parametrize("name", ["Don't cancel", "Do not cancel", "Don’t unsubscribe", "Keep my plan", "Stay subscribed",
                                  "해지 취소", "취소 안 함", "취소하지 않음", "해지 안 할래요", "탈퇴 철회", "유지할게요"])
def test_a_name_that_negates_or_cancels_the_exit_is_a_way_back(name):
    assert flows._backs_out(name) is True
    assert flows._exit_named(name) is False
    assert flows._forward(name, True) is False


@pytest.mark.parametrize("name", ["Cancel subscription", "Unsubscribe", "구독 취소", "해지", "해지하기", "Delete account",
                                  "Cancel subscription (keep access until Nov 5)", "구독 해지 (이번 달까지 계속 이용 가능)"])
def test_the_exit_action_itself_still_does_not_back_out(name):
    assert flows._backs_out(name) is False
    assert flows._exit_named(name) is True
    assert commits._exits(name, "submit") is True


@pytest.mark.parametrize("name, purpose, kind", [
    ("Don't cancel", "retention", "accept"), ("Keep my plan", "retention", "accept"), ("해지 취소", "retention", "accept"),
    ("취소 안 함", "retention", "accept"), ("유지할게요", "retention", "accept"), ("Don't cancel", "confirm", "neutral"),
    ("Cancel subscription", "retention", "decline"), ("해지하기", "retention", "decline"),
])
def test_choice_kind_of_a_name_that_negates_the_exit_is_the_stay_side(name, purpose, kind):
    assert choices._kind(name, "button", purpose) == kind


@pytest.mark.parametrize("name, purpose, kind", [
    ("No", "retention", "accept"), ("Never", "retention", "accept"), ("아니요", "retention", "accept"),
    ("싫어요", "retention", "accept"), ("안 할래요", "retention", "accept"), ("No thanks", "retention", "accept"),
    ("아니요, 유지할게요", "retention", "accept"),
    ("No", "confirm", "neutral"), ("아니요", "confirm", "neutral"), ("No thanks", "confirm", "neutral"),
    ("나가기", "retention", "decline"), ("Leave", "retention", "decline"), ("Yes", "retention", "decline"),
    ("네", "retention", "decline"), ("Yes, cancel", "retention", "decline"),
    ("나가기", "confirm", "neutral"), ("Leave", "confirm", "neutral"), ("Yes", "confirm", "neutral"),
])
def test_in_a_dialog_that_asks_about_the_exit_no_keeps_things_and_leaving_goes_through(name, purpose, kind):
    assert choices._kind(name, "button", purpose, exit_question=True) == kind


def test_response_presses_the_exit_side_when_the_question_is_the_exit():
    controls = [{"id": "b0", "text": "No"}, {"id": "b1", "text": "Yes, cancel"}]
    assert response(controls)[1]["text"] == "No"
    assert response(controls, exit_question=True) == ("decline", controls[1])
    assert response([{"id": "b0", "text": "아니요"}, {"id": "b1", "text": "네"}], exit_question=True)[0] == "none"


def test_response_never_answers_with_a_name_that_negates_the_exit():
    controls = [{"id": "b0", "text": "Don't cancel"}, {"id": "b1", "text": "Cancel subscription"}]
    assert response(controls) == ("decline", controls[1])
    assert response([{"id": "b0", "text": "해지 취소"}, {"id": "b1", "text": "Keep my plan"}])[0] == "none"


# G85: a required mark counts on an agreement item only; an offer's own terms do not make it required.

@pytest.mark.parametrize("text, optional", [
    ("Special offer: 10% off when you join our newsletter. Email (required)", True),
    ("뉴스레터 구독하고 10% 할인 받으세요. 이메일 (필수)", True),
    ("Get 10% off your first order. Join our newsletter. By subscribing you agree to our Terms and Privacy Policy.", True),
    ("첫 구매 10% 할인 쿠폰을 드려요. 구독하면 이용약관에 동의하게 됩니다.", True),
    ("Special offer: 10% off. By signing up you accept our Terms. Email (required)", True),
    ("혜택을 유지하시겠어요? 필수 항목은 없습니다.", True),
    ("Special offer: 10% off for new members\n[Required] Terms of Service\n[Optional] Marketing emails", False),
    ("[필수] 이용약관 동의 [선택] 마케팅 수신 동의", False),
    ("[Required] I agree to the Terms of Service. Special offer: 10% off", False),
    ("Agree to the terms to continue. Marketing emails are optional.", False),
    ("By continuing you accept our Terms and cookie policy", False),
    ("필수 약관에 모두 동의해 주세요. 마케팅 수신(선택)", False),
    ("필수 항목에 동의해 주세요. 특가 혜택 안내", False),
])
def test_a_required_mark_asks_for_agreement_only_on_an_agreement_item(text, optional):
    assert flows._optional(text) is optional


@pytest.mark.parametrize("names, text, chosen", [
    (["Subscribe", "No thanks"], "Special offer: 10% off when you join our newsletter. Email (required)", "No thanks"),
    (["구독하기", "괜찮아요"], "뉴스레터 구독하고 10% 할인 받으세요. 이메일 (필수)", "괜찮아요"),
    (["Subscribe", "No thanks"], "Get 10% off your first order. Join our newsletter. By subscribing you agree to our Terms.", "No thanks"),
    (["구독하기", "괜찮아요"], "첫 구매 10% 할인 쿠폰을 드려요. 구독하면 이용약관에 동의하게 됩니다.", "괜찮아요"),
])
def test_a_newsletter_offer_with_a_required_field_or_its_own_terms_is_turned_down(names, text, chosen):
    assert _order(names, text, "purchase", "buy the bowl")[0] == chosen


# G89: a choice's price and period are read by the reader a flow's price rows use.

def _option(label):
    item = {"id": "b1", "label": label, "text": label, "tag": "button", "type": "", "checked": False, "lang": None,
            "visual": {}}
    return choices._option(types.SimpleNamespace(clean=lambda text: text), item, "plan")


@pytest.mark.parametrize("label, price, currency, cadence", [
    ("Pro $10/month", 10.0, "USD", "month"), ("Pro $1,200/year", 1200.0, "USD", "year"),
    ("Pro USD 12 per month", 12.0, "USD", "month"), ("Pro 10 USD / month", 10.0, "USD", "month"),
    ("프로 월 9,900원", 9900.0, "KRW", "month"), ("프로 ₩9,900/월", 9900.0, "KRW", "month"),
    ("Pro KRW 9900/month", 9900.0, "KRW", "month"), ("Pro €10 monthly", 10.0, "EUR", "month"),
    ("Gift wrap £5", 5.0, "GBP", "once"),
])
def test_a_choice_reads_the_price_and_period_the_way_a_flow_does(label, price, currency, cadence):
    option = _option(label)
    assert (option["price"], option["currency"], option["cadence"]) == (price, currency, cadence)
    assert flows._money(label) == (price, currency)
    assert (flows._cadence(label) or "once") == cadence


def test_a_choice_without_an_amount_has_no_price():
    assert "price" not in _option("Basic plan")


# G125: the status text a changed box gained.

@pytest.mark.parametrize("text", [
    "12 results", "3 items in your cart", "검색 결과 12개", "3건의 결과", "Saved", "Added to cart", "Item removed", "Link copied",
    "저장했어요", "장바구니에 담았어요", "예약이 완료됐어요", "삭제되었어요", "신청 완료", "No results", "결과 없음", "총 12개", "모두 3건",
    "Cart (3)", "Your bag: 2", "장바구니 3", "No items", "5 matches", "Settings updated", "Reservation booked",
])
def test_text_that_names_a_result_or_a_count_is_status(text):
    assert reads_as_status(text)


@pytest.mark.parametrize("text", [
    "72 pieces in 4 firings", "Cart", "Items", "Results", "Quantity 3", "Page 2 of 5", "Total $42.00", "장바구니", "검색 결과",
    "Sort by price", "Showing 3 of them", "저장하기", "예약 가능", "", "Item 3 selected", "Bagel menu",
])
def test_a_number_that_changes_alone_or_a_label_is_not_status(text):
    assert not reads_as_status(text)


def test_only_the_text_a_box_did_not_show_before_is_new():
    assert new_text(["Cart\nTotal: $5"], ["Cart\nTotal: $7"]) == "Total: $7"
    assert new_text(["Cart"], ["Cart"]) == ""
    assert new_text(["Saved"], ["Saved", "Saved"]) == "Saved"
    assert not reads_as_status(new_text(["Cart\nTotal: $5"], ["Cart\nTotal: $7"]))
    assert reads_as_status(new_text(["Cart"], ["Cart\n3 items in your cart"]))
