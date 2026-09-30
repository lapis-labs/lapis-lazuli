"""Real browser check that a Korean-only app is read like its English twin: the reservation flow finishes
through the confirm button, a modal whose only control is its close button gets closed, a retention offer
is turned down, a failed load counts as an error with a retry, a commit's result and retry are read from
its words, and a cookie dialog is managed to its reject-all with its 'don't show again' offer noticed."""
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
from lapis_design.behavior_check.probes import choices, commits, controls, dialogs, flows, forms, permissions, states
from lapis_design.behavior_check.probes._decision import PROBLEM, RETRY, purpose, response
from lapis_design.behavior_check.probes._decision import dialogs as read_dialogs
from lapis_design.behavior_check.session import Session
from lapis_design.lint.types import DETECTORS, Context
from lapis_design.stub.engine import StubEngine

APP = Path(__file__).parent / "fixtures" / "behavior" / "labels-app"
STUB = APP / "labels.stub.yaml"
WORDS = {
    "ko": {"goal": "좌석 예약하기", "reserve": "예약하기", "next": "다음", "confirm": "확인", "cancel": "취소",
           "close": "닫기", "done": "예약이 완료됐어요", "seats": "남은 좌석이 있어요",
           "offer_no": "괜찮아요", "offer_later": "나중에 할게요", "offer_done": "제안을 사양했어요",
           "accept_all": "모두 수락", "manage": "설정", "reject_all": "모두 거부", "save_choices": "선택 저장",
           "again": "7일 동안 다시 보지 않기", "openSettings": "설정 열기", "openNotice": "대화상자 열기",
           "delete": "삭제", "pay": "결제", "action": "예약",
           "apply": "신청하기", "apply_goal": "좌석 신청", "apply_done": "신청이 완료됐어요",
           "withdraw_goal": "알림 수신 철회", "withdraw_done": "알림 수신을 취소했어요",
           "delete_object": "기록 삭제", "delete_confirm": "삭제 확인"},
    "en": {"goal": "Reserve a seat", "reserve": "Reserve", "next": "Next", "confirm": "Confirm", "cancel": "Cancel",
           "close": "Close", "done": "Reservation complete", "seats": "Seats are still open",
           "offer_no": "No thanks", "offer_later": "Maybe later", "offer_done": "Offer declined",
           "accept_all": "Accept all", "manage": "Manage", "reject_all": "Reject all", "save_choices": "Save choices",
           "again": "Don't show again for 7 days", "openSettings": "Open settings", "openNotice": "Open dialog",
           "delete": "Delete", "pay": "Pay", "action": "Reserve",
           "apply": "Apply", "apply_goal": "Apply for a seat", "apply_done": "Application complete",
           "withdraw_goal": "Withdraw notification consent", "withdraw_done": "Notifications cancelled",
           "delete_object": "Delete record", "delete_confirm": "Confirm deletion"},
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


@pytest.fixture(params=["ko", "en"])
def app(request):
    with _serve(request.param) as served:
        yield served


@pytest.fixture(params=["ko", "en"])
def cookie_app(request):
    """The same app whose front page is the cookie dialog."""
    with _serve(request.param, home="/consent") as served:
        yield served


def _session(browser, url, plan=None):
    session = Session(url, "seat-reservation", engine=StubEngine.load(STUB), plan=plan)
    session.contexts = {"d": session.contexts["d"]}

    def open_driver(ctx_id):
        driver = Driver(browser, session, ctx_id)
        driver.open(urlsplit(url).path or "/")
        return driver

    return session, open_driver


def _clicked(document, run):
    return [document["nodes"][action["target"]]["name"] for step in run["steps"] for action in step["actions"]]


def test_confirm_outranks_cancel_on_the_confirm_screen(browser, app):
    words, url = app
    plan = {"flows": [{"id": "reserve", "kind": "primary", "goal": words["goal"], "start": "/reserve",
                       "done": {"text": words["done"]}}]}
    session, open_driver = _session(browser, url, plan)
    flows.run(session, open_driver)
    document = session.document()
    run = document["flows"][0]
    clicked = _clicked(document, run)
    assert (clicked[0], clicked[-1]) == (words["reserve"], words["confirm"]) and words["cancel"] not in clicked
    assert run["status"] == "completed"
    assert session.engine.effects_total == 1                         # the confirm button committed once
    assert next(entry for entry in document["coverage"] if entry["probe"] == "flows")["status"] == "ran"


def test_close_only_modal_outside_main_is_found_and_closed(browser, app):
    words, url = app
    plan = {"flows": [{"id": "read-notice", "kind": "primary", "goal": words["goal"], "start": "/",
                       "done": {"text": words["seats"]}}]}
    session, open_driver = _session(browser, url, plan)
    dialogs.run(session, open_driver)
    choices.run(session, open_driver)
    document = session.document()
    (row,) = document["probes"]["dialogs"]
    assert row["focus"]["close_control"] is True
    assert {appearance["response"] for appearance in row["appearances"]} == {"decline"}
    (choice,) = document["probes"]["choices"]
    assert [(option["label"], option["kind"]) for option in choice["options"]] == [(words["close"], "dismiss")]

    session, open_driver = _session(browser, url, plan)
    flows.run(session, open_driver)
    document = session.document()
    run = document["flows"][0]
    assert _clicked(document, run) == [words["close"]]
    assert run["status"] == "completed"


@pytest.mark.parametrize("route, label", [("/offer", "offer_no"), ("/offer-later", "offer_later")])
def test_retention_offer_is_turned_down_not_taken(browser, app, route, label):
    words, url = app
    plan = {"flows": [{"id": "keep-plan", "kind": "primary", "goal": words["goal"], "start": route,
                       "done": {"text": words["offer_done"]}}]}
    session, open_driver = _session(browser, url, plan)
    flows.run(session, open_driver)
    document = session.document()
    run = document["flows"][0]
    assert _clicked(document, run) == [words[label]] and run["status"] == "completed"


@pytest.mark.parametrize("route, answer", [("/offer", "decline"), ("/offer-later", "later")])
def test_offer_dialog_is_answered_by_what_the_button_says(browser, app, route, answer):
    _, url = app
    session, open_driver = _session(browser, url + route.lstrip("/"))
    dialogs.run(session, open_driver)
    document = session.document()
    row = next(row for row in document["probes"]["dialogs"] if row["path"] == route)   # the front page has its own notice
    assert row["appearances"][0]["response"] == answer
    assert row["purpose"] == "retention"


@pytest.mark.parametrize("label, kind", [
    ("No thanks", "decline"), ("아니요", "decline"), ("괜찮아요", "decline"), ("거절", "decline"), ("모두 거부", "decline"),
    ("허용 안 함", "decline"), ("Reject all", "decline"), ("취소", "decline"), ("Cancel", "decline"),
    ("수신 거부", "decline"), ("Opt out", "decline"), ("구독 해지", "decline"), ("Unsubscribe", "decline"),
    ("숨기기", "dismiss"), ("Dismiss", "dismiss"),
    ("닫기", "dismiss"), ("Close", "dismiss"), ("수락", "accept"), ("Accept all", "accept"),
    ("설정", "customize"), ("쿠키 설정", "customize"), ("개인정보 관리", "customize"), ("선택 사항", "customize"),
    ("옵션 보기", "customize"), ("Manage", "customize"), ("Cookie settings", "customize"), ("Options", "customize"),
])
def test_choice_kind_reads_both_languages(label, kind):
    assert choices._kind(label, "", "consent") == kind


@pytest.mark.parametrize("label, expected", [
    ("Marketing updates", "marketing"), ("마케팅 정보 수신 동의", "marketing"),
    ("Terms and conditions", "terms"), ("이용약관 동의", "terms"),
    ("Add-on insurance", "add-on"), ("추가 상품 보험", "add-on"),
    ("Permission consent", "consent"), ("알림 권한 동의", "consent"),
])
def test_form_field_label_purpose_reads_both_languages(label, expected):
    assert forms._purpose(label.lower()) == expected


def test_failed_loads_count_as_errors_with_a_retry(browser, app):
    _, url = app
    session, open_driver = _session(browser, url + "seats")
    states.run(session, open_driver)
    document = session.document()
    rows = {row["state"]: row for row in document["probes"]["states"]}
    for state in ("error", "offline", "timeout", "forbidden", "not-found"):
        assert (rows[state]["shown"], rows[state]["problem_text"], rows[state]["recovery_action"]) == (True, True, True), state
    assert rows["error"]["recovery_works"] is True
    rules = yaml.safe_load((shared_dir() / "slop" / "rules.yaml").read_text())
    rule = next(r for r in rules["rules"] if r["id"] == "copy.error-without-recovery")
    det = rule["detect"]["behavior"]
    result = DETECTORS[det["detector"]].fn(Context(rules=rules, session=document, plan=None), det, rule, "behavior")
    assert result.hits == []


@pytest.mark.parametrize("labels, expected", [
    (["Accept", "No thanks"], "decline"), (["수락", "아니요"], "decline"), (["수락", "괜찮습니다"], "decline"),
    (["수락", "거절"], "decline"), (["모두 수락", "모두 거부"], "decline"), (["허용", "허용 안 함"], "decline"),
    (["Allow", "Don't allow"], "decline"),
    (["Accept", "Remind me later"], "later"), (["수락", "나중에"], "later"), (["수락", "다음에 할게요"], "later"),
    (["허용", "다시 알려주세요"], "later"), (["수락", "아니오"], "decline"),
    (["수락", "숨기기"], "dismiss"),
    (["나중에", "거절"], "decline"), (["Maybe later", "Reject all"], "decline"),          # a refusal beats a deferral
    (["수락", "확인", "허용"], "none"), (["Accept", "Continue"], "none"),                  # acceptance is never forced
])
def test_response_prefers_refusal_then_deferral_in_both_languages(labels, expected):
    controls = [{"id": f"b{n}", "text": label} for n, label in enumerate(labels)]
    kind, control = response(controls)
    assert kind == expected
    assert (control is None) == (expected == "none")


@pytest.mark.parametrize("text, problem", [
    ("좌석 정보에 문제가 생겼어요. 다시 시도해 주세요.", True), ("저장하지 못했어요", True), ("예약에 실패했어요", True),
    ("오류가 발생했어요", True), ("이 좌석을 볼 권한이 없어요.", True), ("좌석을 찾을 수 없어요.", True),
    ("인터넷 연결이 끊겨 있어요", True), ("요청 시간이 초과됐어요", True), ("저장되지 않았어요", True),
    ("Seat information failed to load", True), ("You are offline", True),
    ("좌석 3개가 남았어요", False), ("아직 좌석이 없어요", False), ("문제 없이 예약했어요", False),
    ("No seats yet", False),
])
def test_problem_wording_is_what_went_wrong_not_what_is_empty(text, problem):
    assert bool(re.search(PROBLEM, text, re.I)) is problem


@pytest.mark.parametrize("label, retry", [
    ("다시 시도", True), ("다시시도", True), ("재시도", True), ("새로고침", True), ("다시 불러오기", True),
    ("다시 해보기", True), ("Try again", True), ("Reload", True),
    ("좌석 추가", False), ("다음", False), ("예약하기", False), ("Add a seat", False),
])
def test_retry_wording_is_a_second_try_not_any_button(label, retry):
    assert bool(re.search(RETRY, label, re.I)) is retry


@pytest.mark.parametrize("text, claim", [
    ("예약이 완료됐어요", "success"), ("저장했어요", "success"), ("예약되었어요", "success"), ("예약됐어요", "success"),
    ("가입되었어요", "success"), ("삭제했어요", "success"), ("메시지를 보냈어요", "success"), ("성공적으로 저장됐어요", "success"),
    ("예약하지 못했어요. 다시 시도해 주세요.", "failure"), ("저장에 실패했어요", "failure"), ("오류가 발생했어요", "failure"),
    ("저장되지 않았어요", "failure"), ("저장할 수 없었어요", "failure"), ("문제가 생겼어요", "failure"),
    ("다시 시도해 주세요", "failure"), ("완료하지 못했어요", "failure"),
    ("예약을 처리 중이에요", "pending"), ("잠시만 기다려 주세요", "pending"), ("저장 중…", "pending"), ("진행 중이에요", "pending"),
    ("결제 여부를 확인 중이에요", "unknown"), ("결제됐는지 확인할 수 없어요", "unknown"), ("아직 확실하지 않아요", "unknown"),
    ("이 기기에 저장했어요", "saved-locally"), ("오프라인 사본을 만들었어요", "saved-locally"),
    ("Reservation saved", "success"), ("Reservation completed", "success"), ("Could not reserve. Try again.", "failure"),
    ("Reservation failed", "failure"), ("Saving reservation", "pending"), ("Checking your payment", "unknown"),
    ("Saved to this device", "saved-locally"),
    # Fixed notes and labels are not a result: a Korean "cannot", "if a problem comes up" and "complete" button
    # read the way their English twins do.
    ("예약 후에는 취소할 수 없어요", "none"), ("문제가 생기면 알려 주세요", "none"), ("완료하기", "none"),
    ("예약이 완료되면 문자를 보내 드려요", "none"), ("좌석이 남아 있어요", "none"), ("예약을 취소했어요", "none"),
    ("You cannot cancel after booking", "none"), ("Consent recorded", "none"), ("Reservation cancelled", "none"),
])
def test_commit_result_wording_reads_both_languages(text, claim):
    assert commits._claimed(text) == claim


@pytest.mark.parametrize("text, name", [
    ("쿠키 사용 안내 더 나은 서비스를 위해 쿠키를 사용해요", "consent"), ("개인정보 수집에 동의해 주세요", "consent"),
    ("알림 권한을 허용해 주세요", "permission-preprompt"), ("알림을 켜 주세요", "permission-preprompt"),
    ("뉴스레터를 구독하시겠어요", "marketing"), ("이메일 소식을 받아 보세요", "marketing"),
    ("지금 계속 이용하시면 다음 달 이용료를 50% 할인해 드려요", "retention"), ("떠나기 전에 잠깐만요", "retention"),
    ("요금제를 유지하시면 할인해 드려요", "retention"),
    ("프리미엄으로 업그레이드하세요", "upsell"), ("장바구니에 담을까요", "upsell"),
    ("정말 삭제하시겠어요?", "confirm"), ("주문을 취소할까요", "confirm"),
    ("저장하지 못했어요", "error"), ("오류가 발생했어요", "error"),
    ("점검 안내 오늘 밤 12시에 점검이 있어요", "other"),
    ("예약 내용을 살펴 주세요 확인", "other"),                       # a bare 확인 is the OK button, not a question to confirm
    ("해지하기 전에 잠깐만요 구독을 유지하시겠어요", "other"),          # 구독 alone is the subscription, not an invitation to subscribe
    ("We use cookies", "consent"), ("Allow notifications?", "permission-preprompt"),
    ("Subscribe to our newsletter", "marketing"), ("Keep your plan", "retention"), ("Upgrade now", "upsell"),
    ("Are you sure?", "confirm"), ("Something failed", "error"), ("Maintenance notice", "other"),
])
def test_dialog_purpose_reads_both_languages(text, name):
    assert purpose(text, None)[0] == name


def test_commit_result_retry_and_pending_are_read_from_words(browser, app):
    _, url = app
    session, open_driver = _session(browser, url + "book")
    controls.run(session, open_driver)
    commits.run(session, open_driver)
    document = session.document()
    (probe,) = document["probes"]["commits"]
    assert probe["kind"] == "reserve"
    assert probe["double_activation"]["pending_shown"] is True and probe["double_activation"]["name_kept"] is True
    outcomes = {row["injected"]: row for row in probe["outcomes"]}
    assert set(outcomes) == {"none", "fail-5xx", "fail-network", "hang", "forbidden"}
    assert (outcomes["none"]["claimed"], outcomes["none"]["announced"], outcomes["none"]["retry_offered"]) == ("success", True, False)
    for mode in ("fail-5xx", "fail-network", "forbidden"):
        row = outcomes[mode]
        assert (row["claimed"], row["announced"], row["retry_offered"], row["retry_effects"]) == ("failure", True, True, 1), mode


def test_cookie_dialog_is_managed_to_its_reject_all(browser, cookie_app):
    words, url = cookie_app
    session, open_driver = _session(browser, url)
    dialogs.run(session, open_driver)
    choices.run(session, open_driver)
    document = session.document()
    (row,) = (row for row in document["probes"]["dialogs"] if row["path"] == "/")
    assert row["purpose"] == "consent"
    assert row["dont_show_again"] == {"offered": True, "days": 7}
    # The manage control is found, so Escape is not spent on the dialog and the answer is its reject-all.
    assert "escape_closes" not in row["focus"]
    assert {appearance["response"] for appearance in row["appearances"]} == {"decline"}
    (choice,) = document["probes"]["choices"]
    assert choice["purpose"] == "consent"
    buttons = [(option["label"], option["kind"], option["layer"], option["interactions"])
               for option in choice["options"] if option["control"] == "button"]
    assert buttons == [(words["accept_all"], "accept", 1, 1), (words["manage"], "customize", 1, 1),
                       (words["reject_all"], "decline", 2, 2), (words["save_choices"], "accept", 2, 2)]


@pytest.mark.parametrize("phrase, days", [
    ("다시 보지 않기", None), ("다시 표시하지 않기", None), ("더 이상 보지 않기", None),
    ("오늘 하루 보지 않기", "1"), ("오늘 하루 다시 보지 않기", "1"), ("오늘 하루 안 보기", "1"),
    ("7일 동안 다시 보지 않기", "7"), ("30일간 보지 않기", "30"),
    ("Don't show again", None), ("Do not ask me again", None), ("Never show again for 14 days", "14"),
    ("다시 보기", False), ("안 보이는 알림 3개를 확인하세요", False), ("오늘 하루 더 보기", False), ("Show again", False),
])
def test_not_shown_again_offer_is_read_in_both_languages(browser, app, phrase, days):
    _, url = app
    session, open_driver = _session(browser, url + "consent")
    driver = open_driver("d")
    try:
        driver.page.evaluate("text => { document.querySelector('#again').nextSibling.textContent = text; }", phrase)
        (dialog,) = read_dialogs(driver)
    finally:
        driver.close()
    assert dialog["again_offered"] is (days is not False)
    assert dialog["again"] == (days or None)


@pytest.mark.parametrize("lang", ["ko", "en"])
@pytest.mark.parametrize("kind, opener", [("settings-dialog", "openSettings"), ("dialog-opener", "openNotice")])
def test_korean_and_english_controls_open_observable_dialogs(browser, lang, kind, opener):
    with _serve(lang, home="/" + kind) as (words, url):
        session, open_driver = _session(browser, url)
        dialogs.run(session, open_driver)
        rows = session.document()["probes"]["dialogs"]
        assert any(row.get("trigger") == "control" and
                   session.nodes[row["trigger_box"]]["name"] == words[opener] for row in rows)


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_open_control_promise_reads_both_languages(browser, lang):
    with _serve(lang) as (words, url):
        _, open_driver = _session(browser, url + "settings-dialog")
        driver = open_driver("d")
        try:
            (box,) = (box for box in driver.interactive() if box["name"] == words["openSettings"])
            assert controls.promise(driver, box) == "open"
        finally:
            driver.close()


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_korean_and_english_plan_controls_open_choices(browser, lang):
    with _serve(lang, home="/choice-opener") as (words, url):
        session, open_driver = _session(browser, url)
        choices.run(session, open_driver)
        rows = session.document()["probes"]["choices"]
        assert any(any(option["label"] == words["cancel"] for option in row["options"]) for row in rows)


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_permission_pre_prompt_and_allow_button_work_in_both_languages(browser, lang):
    with _serve(lang, home="/permission") as (_, url):
        session, open_driver = _session(browser, url)
        permissions.run(session, open_driver)
        calls = session.document()["probes"]["permissions"]
        assert any(call["api"] == "notifications" and call.get("preprompt") for call in calls)


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_destructive_and_commit_labels_are_never_clicked_on_restricted_backend(browser, lang):
    with _serve(lang) as (words, url):
        session = Session(url + "actions", "seat-reservation", backend="local-dev", outbound="restricted")
        session.contexts = {"d": session.contexts["d"]}
        opened = []
        def open_driver(ctx_id):
            driver = Driver(browser, session, ctx_id)
            driver.open("/actions")
            opened.append(driver)
            return driver
        controls.run(session, open_driver)
        coverage = session.document()["coverage"][0]
        assert coverage["status"] == "partial"
        assert f"{words['delete']}: destructive action requires stub" in coverage["reason"]
        assert f"{words['pay']}: possible commit requires outbound none" in coverage["reason"]
        assert not [entry for driver in opened for entry in driver.network.entries
                    if entry["method"] == "POST" and entry["path"] == "/api/actions"]


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_commit_kind_reads_the_visible_action_not_a_generic_api_path(browser, lang):
    with _serve(lang) as (words, url):
        session, open_driver = _session(browser, url + "action")
        controls.run(session, open_driver)
        commits.run(session, open_driver)
        rows = [row for row in session.document()["probes"]["commits"]
                if session.nodes[row["box"]].get("name") == words["action"]]
        assert len(rows) == 1 and rows[0]["kind"] == "reserve"


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_next_step_form_control_is_found_in_both_languages(browser, lang):
    with _serve(lang) as (_, url):
        session, open_driver = _session(browser, url + "steps")
        forms.run(session, open_driver)
        rows = session.document()["probes"]["forms"]
        assert any(any(item["after"] == "back" for item in row.get("preservation", ())) for row in rows)


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_application_confirmation_completes_and_flows_are_ran(browser, lang):
    with _serve(lang) as (words, url):
        plan = {"flows": [{"id": "apply", "kind": "primary", "goal": words["apply_goal"], "start": "/apply",
                           "done": {"text": words["apply_done"]}}]}
        session, open_driver = _session(browser, url, plan)
        flows.run(session, open_driver)
        doc = session.document()
        run = doc["flows"][0]
        assert run["status"] == "completed"
        assert _clicked(doc, run) == [words["apply"], words["confirm"]]
        assert next(item for item in doc["coverage"] if item["probe"] == "flows")["status"] == "ran"


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_cancel_is_forward_in_a_withdrawal_flow(browser, lang):
    with _serve(lang) as (words, url):
        plan = {"flows": [{"id": "withdraw", "kind": "withdraw-consent", "goal": words["withdraw_goal"],
                           "start": "/withdraw", "done": {"text": words["withdraw_done"]}}]}
        session, open_driver = _session(browser, url, plan)
        flows.run(session, open_driver)
        doc = session.document()
        run = doc["flows"][0]
        assert run["status"] == "completed"
        assert _clicked(doc, run) == [words["cancel"]]
        assert next(item for item in doc["coverage"] if item["probe"] == "flows")["status"] == "ran"


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_destructive_confirmation_and_undo_are_read_in_both_languages(browser, lang):
    with _serve(lang) as (words, url):
        session, open_driver = _session(browser, url + "destructive")
        driver = open_driver("d")
        try:
            driver.boxes()
            opener = driver.page.get_by_role("button", name=words["delete_object"]).get_attribute("data-lapis-box")
            driver.act({"kind": "click", "target": opener})
            driver.boxes()
            target = driver.page.get_by_role("button", name=words["delete_confirm"]).get_attribute("data-lapis-box")
            result = commits._confirm_and_undo(driver, target, opener)
        finally:
            driver.close()
        assert result["confirm"] == {"shown": True, "names_object": True, "initial_focus": "safe"}
        assert result["undo"]["offered"] is True
        assert result["undo"]["restores"] is True
