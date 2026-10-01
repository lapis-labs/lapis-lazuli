"""Real browser and wording checks for how the flow, choice, and dialog probes decide: a terms dialog is
agreed to and a marketing offer turned down, cancel and put-off words are read as whole names, a control
is read by its accessible name, and a delete with a Korean undo passes the undo rule."""
from __future__ import annotations

import contextlib
import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

import lapis_design.lint.detectors.behavior  # noqa: F401  (registers the detectors)
from lapis_design import shared_dir
from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import choices, commits, controls, dialogs, flows
from lapis_design.behavior_check.probes._decision import AGAIN, CLOSE, purpose, response
from lapis_design.behavior_check.probes._decision import dialogs as read_dialogs
from lapis_design.behavior_check.session import Session
from lapis_design.lint.types import DETECTORS, Context
from lapis_design.stub.engine import StubEngine

APP = Path(__file__).parent / "fixtures" / "behavior" / "choices-app"
STUB = APP / "choices.stub.yaml"
WORDS = {
    "ko": {"signup": "가입하기", "signup_goal": "회원가입", "signed_up": "가입이 완료됐어요", "agree": "동의하고 계속",
           "no": "아니요", "yes": "동의", "cancel_goal": "구독 취소", "cancel_sub": "구독 취소", "confirm": "확인",
           "ok": "확인", "cancelled": "구독이 취소됐어요", "haeji_goal": "구독 해지", "haeji_sub": "구독 해지하기",
           "haeji_out": "해지하기", "haeji_done": "구독이 해지됐어요", "save": "변경 저장", "reserve_goal": "좌석 예약하기",
           "next": "다음", "reserved": "예약이 완료됐어요", "close": "닫기", "seats": "남은 좌석이 있어요",
           "delete": "삭제", "notice": "점검 안내"},
    "en": {"signup": "Sign up", "signup_goal": "Sign up", "signed_up": "Sign-up complete", "agree": "Agree and continue",
           "no": "No thanks", "yes": "Yes please", "cancel_goal": "Cancel my subscription",
           "cancel_sub": "Cancel subscription", "confirm": "Confirm", "ok": "OK", "cancelled": "Subscription cancelled",
           "haeji_goal": "Cancel my subscription", "haeji_sub": "Cancel subscription",
           "haeji_out": "Cancel subscription", "haeji_done": "Subscription cancelled", "save": "Save changes",
           "reserve_goal": "Reserve a seat", "next": "Next", "reserved": "Reservation complete", "close": "Close",
           "seats": "Seats are still open", "delete": "Delete", "notice": "Maintenance notice"},
}


@contextlib.contextmanager
def _serve(lang, home=""):
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] == "/app.js":
                return super().do_GET()
            body = (APP / "index.html").read_text().replace("{lang}", lang).replace("{home}", home).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(APP)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield WORDS[lang], f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def _session(browser, url, plan=None):
    session = Session(url, "choices", engine=StubEngine.load(STUB), plan=plan)
    session.contexts = {"d": session.contexts["d"]}

    def open_driver(ctx_id):
        driver = Driver(browser, session, ctx_id)
        driver.open(urlsplit(url).path or "/")
        return driver

    return session, open_driver


def _run_flow(browser, url, route, kind, goal, done):
    plan = {"flows": [{"id": "flow", "kind": kind, "goal": goal, "start": route, "done": {"text": done}}]}
    session, open_driver = _session(browser, url, plan)
    flows.run(session, open_driver)
    document = session.document()
    run = document["flows"][0]
    clicked = [document["nodes"][action["target"]]["name"] for step in run["steps"] for action in step["actions"]]
    return run["status"], clicked


@pytest.mark.parametrize("lang", ["ko", "en"])
@pytest.mark.parametrize("route", ["/terms", "/terms-marketing"])
def test_terms_dialog_is_agreed_to_not_turned_down(browser, lang, route):
    """A dialog that asks for the terms (with or without an optional marketing line) is not an offer."""
    with _serve(lang) as (words, url):
        status, clicked = _run_flow(browser, url, route, "signup", words["signup_goal"], words["signed_up"])
    assert (status, clicked) == ("completed", [words["signup"], words["agree"]])


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_optional_marketing_dialog_is_still_turned_down(browser, lang):
    with _serve(lang) as (words, url):
        status, clicked = _run_flow(browser, url, "/marketing", "signup", words["signup_goal"], words["signed_up"])
    assert (status, clicked) == ("completed", [words["signup"], words["no"]])


@pytest.mark.parametrize("lang, route", [("en", "/cancel-confirm"), ("en", "/cancel-ok"), ("ko", "/cancel-confirm")])
def test_cancel_flow_goes_through_the_confirm_dialog(browser, lang, route):
    """[Cancel][Confirm] and [Cancel][OK]: Cancel names the goal but only backs out of the dialog."""
    with _serve(lang) as (words, url):
        status, clicked = _run_flow(browser, url, route, "cancel-subscription", words["cancel_goal"], words["cancelled"])
    assert (status, clicked) == ("completed", [words["cancel_sub"], words["ok" if route == "/cancel-ok" else "confirm"]])


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_retention_benefit_is_not_taken_when_cancelling(browser, lang):
    """The way out of a retention offer is the word that cancels (해지하기 shares the goal word 해지)."""
    with _serve(lang) as (words, url):
        status, clicked = _run_flow(browser, url, "/retention", "cancel-subscription", words["haeji_goal"],
                                    words["haeji_done"])
    assert (status, clicked) == ("completed", [words["haeji_sub"], words["haeji_out"]])


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_save_beside_cancel_subscription_picks_cancel_subscription(browser, lang):
    """A name with more than the cancel word keeps its points, so it beats the confirm-like control."""
    with _serve(lang) as (words, url):
        status, clicked = _run_flow(browser, url, "/cancel-save", "cancel-subscription", words["cancel_goal"],
                                    words["cancelled"])
    assert (status, clicked) == ("completed", [words["cancel_sub"]])


@pytest.mark.parametrize("lang", ["ko", "en"])
@pytest.mark.parametrize("route", ["/cancel-next", "/next-time"])
def test_cancel_and_put_off_are_not_forward_outside_an_exit_flow(browser, lang, route):
    """[Cancel][Next] and [다음에 할게요][다음] go on with Next: only an exit flow moves forward by cancelling."""
    with _serve(lang) as (words, url):
        status, clicked = _run_flow(browser, url, route, "primary", words["reserve_goal"], words["reserved"])
    assert (status, clicked) == ("completed", [words["next"]])


def test_pay_later_is_not_a_put_off_in_an_offer(browser):
    """"Pay later" and "Save for later" are actions, not the phrases that put an offer off."""
    with _serve("en") as (_, url):
        status, clicked = _run_flow(browser, url, "/pay-offer", "purchase", "Buy the print", "Order placed")
    assert (status, clicked) == ("completed", ["Buy", "Pay now"])


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_icon_close_button_is_read_by_its_accessible_name(browser, lang):
    """<button aria-label="닫기">✕</button> is a close control; it stays an icon-only control."""
    with _serve(lang, home="/notice") as (words, url):
        session, open_driver = _session(browser, url)
        driver = open_driver("d")
        try:
            (dialog,) = read_dialogs(driver)
        finally:
            driver.close()
        assert [control["text"] for control in dialog["controls"]] == [words["close"]]
        session, open_driver = _session(browser, url)
        dialogs.run(session, open_driver)
        choices.run(session, open_driver)
        document = session.document()
        (row,) = document["probes"]["dialogs"]
        assert row["focus"]["close_control"] is True
        assert {appearance["response"] for appearance in row["appearances"]} == {"decline"}
        (choice,) = document["probes"]["choices"]
        assert [(o["label"], o["kind"], o["control"]) for o in choice["options"]] == [
            (words["close"], "dismiss", "icon")]
        status, clicked = _run_flow(browser, url, "/notice", "primary", words["reserve_goal"], words["seats"])
        assert (status, clicked) == ("completed", [words["close"]])


@pytest.mark.parametrize("phrase, days", [
    ("Don't show this again", None), ("Don't show me this again", None),
    ("오늘 그만 보기", "1"), ("일주일간 보지 않기", "7"), ("다시 알리지 않기", None),
    ("오늘 하루 보지 않기", "1"), ("7일 동안 다시 보지 않기", "7"), ("Don't show again for 3 days", "3"),
    ("다시 보기", False), ("오늘 하루 더 보기", False), ("안 보이는 알림 3개를 확인하세요", False), ("Show this again", False),
])
def test_not_shown_again_offer_reads_more_phrases(browser, phrase, days):
    with _serve("ko") as (_, url):
        _, open_driver = _session(browser, url + "again")
        driver = open_driver("d")
        try:
            driver.page.evaluate("text => { document.querySelector('#again-text').textContent = text; }", phrase)
            (dialog,) = read_dialogs(driver)
        finally:
            driver.close()
    assert dialog["again_offered"] is (days is not False)
    assert dialog["again"] == (days or None)
    assert bool(re.search(AGAIN, phrase, re.I)) is (days is not False)


@pytest.mark.parametrize("lang, route", [("ko", "/undo"), ("ko", "/undo-alt"), ("en", "/undo")])
def test_delete_with_a_korean_or_english_undo_passes_the_undo_rule(browser, lang, route):
    """A delete that acts at once and offers 되돌리기 or 실행 취소 has an undo that restores the record."""
    with _serve(lang) as (words, url):
        commit = _delete_commit(browser, url, route, words)
    assert commit["undo"]["offered"] and commit["undo"]["restores"] and commit["undo"]["survives_reload"]
    assert _undo_hits(commit["document"]) == []


def test_delete_without_a_recognised_undo_fails_the_undo_rule(browser):
    with _serve("ko") as (words, url):
        commit = _delete_commit(browser, url, "/undo-unread", words)
    assert not commit["undo"]["offered"]
    assert len(_undo_hits(commit["document"])) == 1


def _delete_commit(browser, url, route, words):
    session, open_driver = _session(browser, url + route.lstrip("/"))
    drivers = []

    def tracked(ctx_id):
        driver = open_driver(ctx_id)
        drivers.append(driver)
        return driver

    try:
        controls.run(session, tracked)
        commits.run(session, tracked)
        document = session.document()
    finally:
        for driver in drivers:
            driver.close()
    (probe,) = (row for row in document["probes"]["commits"] if session.nodes[row["box"]].get("name") == words["delete"])
    return {**probe, "document": document}


def _undo_hits(document):
    rules = yaml.safe_load((shared_dir() / "slop" / "rules.yaml").read_text())
    rule = next(r for r in rules["rules"] if r["id"] == "ux.destructive-without-undo")
    det = rule["detect"]["behavior"]
    return DETECTORS[det["detector"]].fn(Context(rules=rules, session=document, plan=None), det, rule, "behavior").hits


# Wording that needs no browser: what a dialog's text asks for, how a control's name is read, and that the
# choices probe and the dialog probe's response() read the same label the same way.

@pytest.mark.parametrize("text, optional", [
    ("서비스 이용약관에 동의해 주세요", False), ("Please agree to the Terms", False),
    ("[필수] 이용약관 동의 [선택] 마케팅 수신 동의", False), ("[Required] Terms of Service [Optional] Marketing emails", False),
    ("이용약관 및 쿠키 정책에 동의해 주세요", False), ("Accept the Terms and our cookie policy", False),
    ("개인정보 수집에 동의해 주세요", False), ("Consent to data processing", False),
    ("[선택] 마케팅 정보 수신에 동의하시겠어요?", True), ("Would you like marketing emails?", True),
    ("Advertising preferences", True), ("광고성 정보 수신 동의", True), ("선택 동의 항목이에요", True),
    ("Optional consent for analytics", True), ("We use cookies to improve the service", True),
    ("필수 쿠키 외에 쿠키 사용에 동의하시겠어요?", True), ("Required cookies are always on. Allow more cookies?", True),
    ("Special offer: keep your plan for 50% off. Terms apply.", True),
    ("Special offer: 50% off. Terms and conditions apply.", True),
    ("해지하기 전에 잠깐만요 지금 계속 이용하시면 할인해 드려요", True), ("Before you go, get a discount", True),
    ("점검 안내 오늘 밤 12시에 점검이 있어요", False),
])
def test_dialog_is_an_optional_offer_only_when_it_asks_for_nothing_the_flow_needs(text, optional):
    assert flows._optional(text) is optional


@pytest.mark.parametrize("text, name", [
    ("서비스 이용약관에 동의해 주세요", "other"), ("Please agree to the Terms", "other"),
    ("개인정보 수집에 동의해 주세요", "consent"), ("We use cookies", "consent"),
    ("[선택] 마케팅 정보 수신에 동의하시겠어요?", "marketing"), ("Send me marketing emails", "marketing"),
    ("구독해 주셔서 감사합니다", "other"), ("뉴스레터를 구독하시겠어요", "marketing"),
    ("예약을 확정할까요?", "confirm"), ("정말 삭제하시겠어요?", "confirm"),
])
def test_dialog_purpose_does_not_read_agreement_alone_as_consent(text, name):
    assert purpose(text, None)[0] == name


@pytest.mark.parametrize("label, kind", [
    ("Maybe later", "dismiss"), ("Remind me later", "dismiss"), ("Later", "dismiss"), ("나중에 할게요", "dismiss"),
    ("다음에 할게요", "dismiss"), ("다음에 하기", "dismiss"),
    ("동의 안 함", "decline"), ("동의하지 않음", "decline"), ("동의 안함", "decline"), ("비동의", "decline"),
    ("미동의", "decline"), ("해지하기", "decline"), ("구독 해지", "decline"),
    ("동의하고 계속", "accept"), ("동의 안내", "accept"), ("Pay later", "accept"), ("Save for later", "accept"),
    ("옵션 추가하기", "accept"), ("옵션 담기", "accept"), ("Add to cart", "accept"),
    ("옵션", "customize"), ("옵션 보기", "customize"), ("옵션 설정 추가", "customize"), ("Options", "customize"),
])
def test_choice_kind_reads_put_off_refusal_and_options(label, kind):
    assert choices._kind(label, "", "consent") == kind


@pytest.mark.parametrize("label, answer, kind", [
    ("Maybe later", "later", "dismiss"), ("Remind me later", "later", "dismiss"), ("나중에 할게요", "later", "dismiss"),
    ("다음에 하기", "later", "dismiss"), ("Later", "later", "dismiss"),
    ("동의 안 함", "decline", "decline"), ("동의하지 않음", "decline", "decline"), ("비동의", "decline", "decline"),
    ("해지하기", "decline", "decline"), ("Reject all", "decline", "decline"), ("거절", "decline", "decline"),
    ("Close", "decline", "dismiss"), ("닫기", "decline", "dismiss"),      # closing is the answer, and a dismiss route
    ("숨기기", "dismiss", "dismiss"),
    ("동의하고 계속", "none", "accept"), ("Pay later", "none", "accept"), ("Accept all", "none", "accept"),
    ("옵션 추가하기", "none", "accept"), ("Manage", "none", "customize"),
])
def test_choices_probe_and_response_read_a_label_the_same_way(label, answer, kind):
    assert response([{"id": "b", "text": label}])[0] == answer
    assert choices._kind(label, "", "consent") == kind


@pytest.mark.parametrize("name, backs_out, forward, exit_forward", [
    ("Cancel", True, False, True), ("Cancel.", True, False, True), ("취소", True, False, True), ("취소…", True, False, True),
    ("Not now", True, False, False), ("Later", True, False, False), ("Close", True, False, False), ("닫기", True, False, False),
    ("✕", True, False, False), ("Maybe later", True, False, False), ("나중에", True, False, False),
    ("Cancel subscription", False, False, True), ("구독 취소", False, False, True), ("해지", False, False, True),
    ("해지하기", False, False, True), ("Pay later", False, True, True), ("Save for later", False, True, True),
    ("다음에 할게요", True, False, False), ("다음", False, True, True), ("Confirm", False, True, True), ("OK", False, True, True),
])
def test_only_a_name_that_is_the_whole_cancel_or_put_off_word_backs_out(name, backs_out, forward, exit_forward):
    assert flows._backs_out(name) is backs_out
    assert flows._forward(name, False) is forward
    assert flows._forward(name, True) is exit_forward


@pytest.mark.parametrize("text, closes", [
    ("Close", True), ("Close dialog", True), ("닫기", True), ("✕", True), ("✖", True),
    ("Disclose", False), ("Enclosed", False), ("Closed", False),
])
def test_close_wording_has_word_boundaries(text, closes):
    assert bool(re.search(CLOSE, text, re.I)) is closes
