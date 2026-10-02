"""How the flow driver reads a price and decides its choices. No browser: the screens are plain dicts, as
`flows.SCREEN` returns them (the pages themselves are in test_behavior_flow_choices.py)."""
from __future__ import annotations

import itertools
import types

import pytest

from lapis_design.behavior_check.probes import flows


# The price and period reader, shared by the flows and the choices.

@pytest.mark.parametrize("text, amount, currency, cadence", [
    ("USD 12 per month", 12.0, "USD", "month"),
    ("Pro EUR 10/month", 10.0, "EUR", "month"),
    ("Pro GBP 8.50 monthly", 8.5, "GBP", "month"),
    ("Pro KRW 9900/month", 9900.0, "KRW", "month"),
    ("12 USD / month", 12.0, "USD", "month"),
    ("월 9,900원", 9900.0, "KRW", "month"),
    ("프로 월 ₩9,900", 9900.0, "KRW", "month"),
    ("연 99,000원", 99000.0, "KRW", "year"),
    ("9,900원/월", 9900.0, "KRW", "month"),
    ("Pro $1,200/year", 1200.0, "USD", "year"),
    ("Pro €10 monthly", 10.0, "EUR", "month"),
    ("Setup fee USD 5", 5.0, "USD", None),
    ("-$5 discount", -5.0, "USD", None),
    ("10월 1일 9,900원", 9900.0, "KRW", None),          # 월 after a number is a date, not a period
    ("9월 30일", None, None, None),
    ("SUSD 12", None, None, None),                      # a code is a word of its own
    ("Plan 12", None, None, None),
])
def test_price_and_period(text, amount, currency, cadence):
    assert flows._money(text) == (amount, currency)
    assert flows._cadence(text) == cadence


def test_the_label_of_a_price_row_loses_its_leading_period_and_currency():
    assert flows._label("프로 요금제 월 9,900원") == "프로 요금제"
    assert flows._label("Pro plan USD 12 per month") == "Pro plan"


# What a screen needs chosen (DERIVED.md, Flows, Choices).

_ids = itertools.count()


def choice(name, *, kind="checkbox", checked=False, disabled=False, missing=False, aria_required=False,
           aria_invalid=False, group=None, prompt="", dialog=False, box=True):
    return dict(id=f"c{next(_ids)}" if box else None, kind=kind, name=name, checked=checked, disabled=disabled,
                in_dialog=dialog, missing=missing, aria_required=aria_required, aria_invalid=aria_invalid,
                group=group, prompt=prompt)


def needed(*choices, asked=False, dialog=False, closed=()):
    screen = {"dialog": "d1" if dialog else None, "choices": list(choices)}
    return [(kind, option["name"]) for kind, option in flows._needed(screen, asked, set(closed))]


def radios(prompt, *names, group="g", **flags):
    return [choice(name, kind="radio", group=group, prompt=prompt, **flags) for name in names]


@pytest.mark.parametrize("flags, name, wanted", [
    ({"missing": True}, "서비스 이용약관 동의", True),                       # the browser reports the value missing
    ({"aria_required": True}, "서비스 이용약관 동의", True),
    ({"aria_invalid": True}, "서비스 이용약관 동의", False),                  # aria-invalid counts once a forward control was tried
    ({}, "[필수] 서비스 이용약관 동의", True),
    ({}, "(필수) 서비스 이용약관 동의", True),
    ({}, "I agree to the Terms (required)", True),
    ({}, "I agree to the Terms *", True),
    ({}, "I agree to the Terms", False),                                   # nothing says it is required
    ({"missing": True}, "[선택] 서비스 이용약관 동의", False),                 # an optional mark rules it out beside a signal
    ({"missing": True}, "I agree to the Terms (optional)", False),
    ({"missing": True}, "이용약관을 선택해 동의", True),                       # a bare 선택 is "choose", not a mark
    ({"missing": True}, "[필수] 개인정보 수집·이용에 동의", True),
    ({"missing": True}, "I have read the Privacy Policy", True),
    ({"missing": True}, "[필수] 만 14세 이상입니다", True),
    ({"missing": True}, "I am over 18", True),
    ({"missing": True}, "I agree to all the terms and conditions", True),   # all the terms is terms, not agree-to-all
    ({"missing": True}, "[필수] 전체 동의", False),
    ({"missing": True}, "모두 동의", False),
    ({"missing": True}, "Accept all", False),
    ({"missing": True}, "[필수] 마케팅 정보 수신 동의 이용약관", False),
    ({"missing": True}, "[필수] 보험 가입과 약관 동의", False),
    ({"missing": True}, "[필수] 약관 동의 (+₩1,000)", False),               # an amount
    ({"missing": True}, "나는 로봇이 아닙니다", False),                       # agrees to none of the three
    ({"missing": True, "checked": True}, "서비스 이용약관 동의", False),     # never unchecks
    ({"missing": True, "disabled": True}, "서비스 이용약관 동의", False),
])
def test_a_checkbox_is_chosen_when_it_is_required_and_asks_for_terms_privacy_or_age(flags, name, wanted):
    assert bool(needed(choice(name, **flags))) is wanted


def test_aria_invalid_makes_a_checkbox_required_only_after_a_forward_control_was_tried():
    box = choice("서비스 이용약관 동의", aria_invalid=True)
    assert needed(box) == [] and needed(box, asked=True) == [("required-checkbox", "서비스 이용약관 동의")]


def test_choices_come_in_document_order_a_group_at_its_first_option():
    terms, privacy = choice("[필수] 이용약관 동의"), choice("[필수] 개인정보 동의")
    plan = radios("[필수] 요금제", "Pro ₩9,900/월", "Basic 무료", group="plan")
    interleaved = [plan[0], terms, plan[1], privacy]          # the second option of the group comes after a checkbox
    assert needed(*interleaved) == [("required-radio", "Basic 무료"), ("required-checkbox", "[필수] 이용약관 동의"),
                                    ("required-checkbox", "[필수] 개인정보 동의")]


@pytest.mark.parametrize("prompt, names, picked", [
    ("이용약관에 동의하시나요? (필수)", ["동의하지 않아요", "동의해요"], "동의해요"),
    ("Do you agree to the Terms? (required)", ["I do not agree", "I agree"], "I agree"),
    ("개인정보 수집·이용 동의 [필수]", ["아니요", "네"], "네"),
    ("[필수] 만 14세 이상입니까?", ["아니요", "예"], "예"),
    ("[필수] 포장", ["프리미엄 포장 ₩3,000", "선택 안 함"], "선택 안 함"),           # turns the offer down
    ("[필수] Insurance", ["Add insurance $5", "No thanks"], "No thanks"),
    ("[필수] Insurance", ["Add insurance $5", "None"], "None"),
    ("[필수] 배송", ["빠른 배송 ₩3,000", "일반 배송 무료"], "일반 배송 무료"),         # no amount above zero
    ("[필수] 요금제", ["Pro ₩9,900/월", "Basic"], "Basic"),
    ("[필수] 크기", ["Large ₩30,000", "Medium ₩25,000", "Small ₩20,000"], "Small ₩20,000"),   # the lowest amount
    ("[필수] 크기", ["Large $30", "Small $20", "Tiny $20"], "Small $20"),                     # the first of equals
])
def test_a_required_radio_group_is_answered_by_agreeing_declining_the_free_or_the_cheapest(prompt, names, picked):
    assert needed(*radios(prompt, *names)) == [("required-radio", picked)]


def test_an_agreement_group_with_no_agreeing_option_is_left_alone():
    assert needed(*radios("이용약관 동의 (필수)", "아니요", "동의하지 않아요")) == []


def test_the_option_names_say_what_a_group_without_a_legend_asks():
    assert needed(*radios("", "I agree to the Terms *", "I do not agree to the Terms *")) == [
        ("required-radio", "I agree to the Terms *")]


def test_a_group_that_has_a_checked_option_is_not_changed():
    group = radios("[필수] 요금제", "Pro ₩9,900/월", "Basic 무료")
    group[0]["checked"] = True
    assert needed(*group) == []


def test_a_radio_group_is_required_by_any_member_signal_and_ruled_out_by_an_optional_mark():
    assert needed(*radios("요금제", "Pro ₩9,900", "Basic 무료")) == []
    group = radios("요금제", "Pro ₩9,900", "Basic 무료")
    group[1]["aria_required"] = True
    assert needed(*group) == [("required-radio", "Basic 무료")]
    assert needed(*radios("[선택] 알림 채널", "문자", "이메일", missing=True)) == []


def test_options_that_cannot_be_pressed_are_skipped():
    group = radios("[필수] 요금제", "Basic 무료", "Pro ₩9,900/월")
    assert needed(*group, closed={group[0]["id"]}) == [("required-radio", "Pro ₩9,900/월")]
    group[0]["disabled"] = True
    assert needed(*group) == [("required-radio", "Pro ₩9,900/월")]
    assert needed(*radios("[필수] 요금제", "Basic 무료", box=False)) == []


def test_only_the_dialogs_choices_count_while_a_dialog_is_open():
    page, inside = choice("[필수] 이용약관 동의"), choice("[필수] 개인정보 동의", dialog=True)
    assert needed(page, inside) == [("required-checkbox", "[필수] 이용약관 동의")]
    assert needed(page, inside, dialog=True) == [("required-checkbox", "[필수] 개인정보 동의")]


# After a choice, what a price is caused by (DERIVED.md, Flows, Choices).

def _row(text, controls=()):
    hint = dict.fromkeys(("kind", "key", "state", "mandatory", "cadence", "placement", "line", "added_by"))
    return dict(id=None, text=text, placement="primary", rect={"y": 0, "h": 10}, cart=False, removable=False,
                checked=[], controls=list(controls), hint=hint)


def _state(log=()):
    return {"log": list(log), "touched": set(), "chosen": set(), "add_words": set(), "last_seen": {},
            "screen_keys": [], "signed_in": False}


def _observe(state, *texts, controls=None):
    run, screen = {}, {"rows": [_row(text, (controls or {}).get(text, ())) for text in texts]}
    flows._observe_money(run, screen, types.SimpleNamespace(clean=lambda text: text), 0, state)
    return {c["kind"]: c["user_caused"] for c in run["prices"][-1]["components"]}


def _entry(name, choice, target, amount=None):
    return {"target": target, "name": name, "field": None, "choice": choice, "amount": amount}


def test_a_terms_checkbox_does_not_make_the_fee_that_follows_user_caused():
    state = _state()
    _observe(state, "도자기 컵 ₩20,000", "합계 ₩20,000")
    state["log"].append(_entry("[필수] 서비스 이용약관에 동의", "required-checkbox", "box-terms"))
    # The fee shares the word 서비스 with the checkbox, and the total rises by its amount.
    assert _observe(state, "도자기 컵 ₩20,000", "서비스 수수료 ₩1,000", "합계 ₩21,000") == {
        "item": False, "fee": False, "total": False}


def test_a_radio_choice_causes_the_price_its_label_showed_or_its_row_holds():
    state = _state()
    _observe(state, "합계 ₩0")
    state["log"].append(_entry("Pro ₩9,900/월", "required-radio", "box-pro", 9900.0))
    # The option's label showed ₩9,900, so the plan priced ₩9,900 is caused and the fee, a different amount, is not.
    # The total rose by ₩9,900, the amount the choice added.
    assert _observe(state, "Pro 요금제 ₩9,900/월", "서비스 수수료 ₩1,000", "합계 ₩9,900") == {
        "recurring": True, "fee": False, "total": True}


def test_a_radio_choice_causes_the_price_in_its_row_and_a_total_that_rose_by_another_amount_is_not_caused():
    state = _state()
    _observe(state, "합계 ₩0")
    state["log"].append(_entry("Standard", "required-radio", "box-standard"))   # the label showed no amount
    caused = _observe(state, "사은품 ₩3,000", "합계 ₩5,000", controls={"사은품 ₩3,000": ["box-standard"]})
    assert caused == {"item": True, "total": False}        # the row holds the chosen control; ₩5,000 is not ₩3,000


def test_a_touched_control_still_causes_the_price_that_shares_a_word_with_it():
    # Pins the reading that was there before choices: a touched control, not a choice.
    state = _state()
    _observe(state, "Subtotal $20.00")
    state["log"].append({"target": "box-ship", "name": "Shipping method", "field": None})
    assert _observe(state, "Subtotal $20.00", "Shipping $5.00", "Total $25.00") == {
        "subtotal": False, "shipping": True, "total": True}
