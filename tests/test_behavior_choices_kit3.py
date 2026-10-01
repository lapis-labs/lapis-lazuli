"""Kit Q33 (G54-G61): how the flow, dialog, choice, state, time-limit, history, commit, pointer, and permission
probes read wording. A dialog asks for agreement only when its text does; the agree and exit words win where
they should; 해지 ends a contract and never backs out; a reminder and 알림 받기 are not put-offs; a control is
read by its accessible name (a button's value, an image's alt); the shared lists hold both languages."""
from __future__ import annotations

import contextlib
import re
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import choices, commits, flows, history, permissions, pointer, states, time_limits
from lapis_design.behavior_check.probes._decision import purpose, response
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine
from test_behavior_choices_ko import _run_flow

FIXTURES = Path(__file__).parent / "fixtures" / "behavior"
LABELS_STUB = FIXTURES / "labels-app" / "labels.stub.yaml"
PIXEL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"


# Wording that needs no browser.

def _choose(dialog_text, names, kind, goal, *, dialog=True, prompt=None):
    """The control `flows._choose` picks on a screen of plain buttons: a dialog's, or the page's own."""
    controls = [dict(id=f"b{i}", name=name, type="button", disabled=False, in_dialog=dialog, in_main=not dialog,
                     href="", required=False, filled=False, name_attr="", autocomplete="")
                for i, name in enumerate(names)]
    screen = {"dialog": "d1" if dialog else None, "dialog_text": dialog_text if dialog else "",
              "controls": controls, "_context": "d"}
    if prompt is not None:
        screen["dialog_prompt"] = prompt
    session = types.SimpleNamespace(contexts={"d": {"pointer": "fine"}}, values_engine=None)
    return flows._choose(screen, {"kind": kind, "goal": goal}, set(), session)[1]


ASKS = [  # a dialog's text, and whether it is an optional offer (it asks for nothing the flow needs)
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
    ("Before you cancel. Special offer: keep your plan for 50% off. See terms.", True),
    ("Before you go: 50% off. Terms of the offer apply.", True),
    ("해지하기 전에 잠깐만요. 3개월 50% 할인 혜택을 드려요. 혜택 약관 보기", True),
    ("Upgrade offer: try Premium free. No credit card required.", True),
    ("업그레이드 특가! 카드 등록 필수 아님", True),
    ("[필수] 개인정보 수집·이용 동의 [선택] 마케팅 정보 수신 동의", False),
    ("필수 약관에 모두 동의해 주세요. 마케팅 수신(선택)", False),
    ("By continuing you accept our Terms and cookie policy", False),
    # An offer's own terms are not an ask, even beside the word accept.
    ("Before you go: accept 50% off for 3 months (terms apply)", True),
    ("Special offer, terms apply: accept it now and save", True),
    ("혜택 약관에 동의하고 50% 할인 받기", True),
]


@pytest.mark.parametrize("text, optional", ASKS)
def test_dialog_is_optional_unless_its_text_asks_for_agreement(text, optional):
    assert flows._optional(text) is optional


@pytest.mark.parametrize("text, asked, optional", [
    # Buttons are not the question: a Terms link beside "Accept offer", or "모두 동의" beside "필수 쿠키만 허용".
    ("Before you go: 50% off\nSee terms\nAccept offer\nNo thanks", "Before you go: 50% off See terms", True),
    ("쿠키 사용 안내\n모두 동의\n필수 쿠키만 허용", "쿠키 사용 안내", True),
    ("Cookies and terms\nAccept\nDecline", "Cookies and terms Please accept the Terms of Service", False),
])
def test_only_what_is_asked_not_the_button_names_asks_for_agreement(text, asked, optional):
    assert flows._optional(text, asked) is optional


OFFER = "Before you cancel. Special offer: keep your plan for 50% off. See terms."
CHOICES = [  # (dialog text, controls in order, flow kind, goal, chosen)
    (OFFER, ["Keep my plan for 50% off", "No thanks"], "cancel-subscription", "Cancel my subscription", "No thanks"),
    ("Before you cancel: 50% off for 3 months. Offer terms apply.", ["Accept offer", "No thanks"],
     "cancel-subscription", "Cancel my subscription", "No thanks"),
    ("Before you go: 50% off for 3 months. Terms of the offer apply.", ["Accept offer", "No thanks"],
     "cancel-subscription", "Cancel my subscription", "No thanks"),
    ("Before you go: accept 50% off for 3 months (terms apply)", ["Accept 50% off", "No thanks"],
     "cancel-subscription", "Cancel my subscription", "No thanks"),
    ("Special offer, terms apply: accept it now and save", ["Accept now", "No thanks"],
     "cancel-subscription", "Cancel my subscription", "No thanks"),
    ("해지하기 전에 잠깐만요. 3개월 50% 할인 혜택을 드려요. 혜택 약관 보기", ["혜택 받기", "괜찮아요"],
     "cancel-subscription", "구독 해지", "괜찮아요"),
    ("혜택 약관에 동의하고 50% 할인 받기", ["혜택 받기", "괜찮아요"], "cancel-subscription", "구독 해지", "괜찮아요"),
    ("업그레이드 특가! 카드 등록 필수 아님", ["업그레이드", "괜찮아요"], "purchase", "액자 구매", "괜찮아요"),
    ("Special offer: try Premium free for 30 days. No credit card required.", ["Start free trial", "No thanks"],
     "purchase", "Buy the print", "No thanks"),
    ("Special offer: upgrade. No credit card required.", ["Upgrade now", "Maybe later"], "purchase", "Buy the print",
     "Maybe later"),
    # Necessary-only and reject are the refusal of consent.
    ("쿠키 사용 안내. 필수 쿠키 외에 분석 쿠키를 사용해요.", ["모두 허용", "필수 쿠키만 허용"], "signup", "회원가입", "필수 쿠키만 허용"),
    ("이 사이트는 쿠키를 사용해요", ["모두 허용", "거부"], "signup", "회원가입", "거부"),
    ("쿠키 사용에 동의하시겠어요?", ["모두 동의", "거부"], "signup", "회원가입", "거부"),
    ("We use cookies. Required cookies are always on.", ["Accept all", "Reject all"], "signup", "Sign up", "Reject all"),
    ("We use cookies", ["Accept all", "Only necessary"], "signup", "Sign up", "Only necessary"),
    ("필수 쿠키 외에 쿠키 사용에 동의하시겠어요?", ["동의", "아니요"], "signup", "회원가입", "아니요"),
    # What the flow needs is agreed to, in either order, and the agree words count.
    ("서비스 이용약관에 동의해 주세요", ["동의하고 계속", "아니요"], "signup", "회원가입", "동의하고 계속"),
    ("[필수] 이용약관에 동의합니다 [선택] 마케팅 정보 수신에 동의합니다", ["동의하고 계속", "아니요"], "signup", "회원가입", "동의하고 계속"),
    ("이용약관 동의가 필요해요", ["동의", "동의 안 함"], "signup", "회원가입", "동의"),
    ("이용약관 동의가 필요해요", ["동의 안 함", "동의"], "signup", "회원가입", "동의"),
    ("이용약관 동의가 필요해요", ["동의하지 않음", "동의"], "signup", "회원가입", "동의"),
    ("약관 동의", ["전체 동의", "취소"], "signup", "회원가입", "전체 동의"),
    ("필수 약관에 동의해 주세요", ["동의", "거절"], "signup", "회원가입", "동의"),
    ("Please accept the Terms of Service to continue", ["Accept", "Decline"], "signup", "Sign up", "Accept"),
    ("Please agree to the Terms of Service", ["Agree", "Cancel"], "signup", "Sign up", "Agree"),
    ("Please agree to the Terms of Service", ["I agree", "No thanks"], "signup", "Sign up", "I agree"),
    ("Please agree to the Terms of Service", ["Cancel", "Agree"], "signup", "Sign up", "Agree"),
    # An exit flow's confirm control is the one named for the exit.
    ("Unsubscribe from all emails?", ["Cancel", "Unsubscribe"], "unsubscribe", "Unsubscribe from the newsletter", "Unsubscribe"),
    ("Withdraw your consent?", ["Cancel", "Withdraw"], "withdraw-consent", "Withdraw marketing consent", "Withdraw"),
    ("Stop marketing emails?", ["Cancel", "Stop emails"], "withdraw-consent", "Withdraw marketing consent", "Stop emails"),
    ("Cancel your plan?", ["Cancel", "Cancel plan"], "cancel-subscription", "Cancel my subscription", "Cancel plan"),
    ("Delete your account?", ["Cancel", "Delete"], "delete-account", "Delete my account", "Delete"),
    ("동의를 철회할까요?", ["취소", "철회"], "withdraw-consent", "마케팅 동의 철회", "철회"),
    ("수신을 거부할까요?", ["취소", "수신 거부"], "unsubscribe", "이메일 수신 거부", "수신 거부"),
    ("구독을 해지할까요?", ["취소", "구독 해지"], "unsubscribe", "뉴스레터 구독 해지", "구독 해지"),
    ("정말 탈퇴하시겠어요? 되돌릴 수 없어요.", ["취소", "탈퇴하기"], "delete-account", "회원 탈퇴", "탈퇴하기"),
    ("Cancel your plan?", ["Cancel", "Keep my plan"], "cancel-subscription", "Cancel my subscription", "Cancel"),
    # A put-off is the whole word or a phrase; 나중에 결제 is an action.
    ("특가 제안: 액자를 1만원에 추가하세요", ["지금 결제", "나중에 결제"], "purchase", "액자 구매", "지금 결제"),
    ("특가 제안: 액자를 1만원에 추가하세요", ["지금 결제", "나중에"], "purchase", "액자 구매", "나중에"),
    ("알림 안내. 알림을 받으면 특별 혜택을 알려 드려요.", ["알림 받기", "나중에"], "primary", "좌석 예약하기", "나중에"),
]


@pytest.mark.parametrize("text, names, kind, goal, chosen", CHOICES)
def test_dialog_answer_picked_by_the_flow_probe(text, names, kind, goal, chosen):
    assert _choose(text, names, kind, goal) == chosen


@pytest.mark.parametrize("names, kind, goal, chosen", [
    # 해지 ends a contract: beside a confirm control it is still the goal, not a way back.
    (["저장", "해지"], "cancel-subscription", "구독 해지", "해지"),
    (["확인", "해지"], "cancel-subscription", "구독 해지", "해지"),
    (["변경 저장", "해지"], "cancel-subscription", "구독 해지", "해지"),
    (["저장", "해지하기"], "cancel-subscription", "구독 해지", "해지하기"),
    (["저장", "구독 취소"], "cancel-subscription", "구독 해지", "구독 취소"),
    (["취소", "저장"], "primary", "예약", "저장"),
    (["다음에 할게요", "다음"], "primary", "좌석 예약하기", "다음"),
])
def test_page_choice_does_not_back_out_through_해지(names, kind, goal, chosen):
    assert _choose("", names, kind, goal, dialog=False) == chosen


@pytest.mark.parametrize("name, backs_out, exit_forward", [
    ("해지", False, True), ("해지하기", False, True), ("취소", True, True), ("Cancel", True, True),
    ("나중에", True, False), ("나중에 결제", False, True), ("나중에 볼게요", True, False), ("Pay later", False, True),
])
def test_해지_names_the_end_of_a_contract_and_never_backs_out(name, backs_out, exit_forward):
    assert flows._backs_out(name) is backs_out
    assert flows._forward(name, True) is exit_forward


@pytest.mark.parametrize("name, exit_named", [
    ("Unsubscribe", True), ("Withdraw", True), ("Stop emails", True), ("Delete account", True), ("Cancel plan", True),
    ("Cancel subscription", True), ("해지", True), ("탈퇴하기", True), ("철회", True), ("수신 거부", True), ("구독 취소", True),
    ("Cancel", False), ("취소", False), ("Close", False), ("Keep my plan", False), ("확인", False),
])
def test_an_exit_name_is_an_action_that_leaves_not_a_bare_cancel(name, exit_named):
    assert flows._exit_named(name) is exit_named


@pytest.mark.parametrize("label, kind", [
    ("나중에 결제", "accept"), ("Pay later", "accept"),
    ("나중에", "dismiss"), ("나중에 할게요", "dismiss"), ("나중에 하기", "dismiss"), ("나중에 할래요", "dismiss"),
    ("나중에 볼게요", "dismiss"), ("나중에 다시", "dismiss"), ("나중에 알려 주세요", "dismiss"), ("나중에 알림 받기", "dismiss"),
    ("알림 받기", "accept"), ("Remind me", "dismiss"), ("다시 알려 주세요", "dismiss"), ("Remind me later", "dismiss"),
    ("옵션 추가하기", "accept"), ("옵션 담기", "accept"), ("옵션을 장바구니에 담기", "accept"),
    ("옵션 추가 안 함", "decline"), ("옵션 추가 없이 계속", "decline"), ("옵션 없이 계속", "decline"),
    ("옵션 추가하지 않음", "decline"), ("Continue without options", "decline"),
    ("추가 옵션 보기", "customize"), ("옵션 설정 추가", "customize"), ("Options", "customize"), ("옵션", "customize"),
    ("필수 쿠키만 허용", "decline"), ("필수만 허용", "decline"), ("Only necessary", "decline"),
    ("Necessary only", "decline"), ("Essential cookies only", "decline"), ("Reject all", "decline"), ("거부", "decline"),
    ("Continue without accepting", "decline"), ("동의하지 않고 계속", "decline"),
    ("모두 허용", "accept"), ("필수 항목 입력", "accept"),
    ("Skip", "decline"), ("건너뛰기", "decline"), ("Leave", "decline"),
])
def test_choice_kind_reads_the_shared_lists(label, kind):
    assert choices._kind(label, "", "consent") == kind


@pytest.mark.parametrize("labels, answer, picked", [
    (["알림 받기", "나중에"], "later", "나중에"),
    (["Remind me", "Maybe later"], "later", "Maybe later"),
    (["다시 알려 주세요", "나중에 할게요"], "later", "나중에 할게요"),
    (["다시 알려 주세요"], "later", "다시 알려 주세요"),
    (["나중에 결제", "지금 결제"], "none", None),
    (["알림 받기"], "none", None),
    (["모두 허용", "필수 쿠키만 허용"], "decline", "필수 쿠키만 허용"),
    (["Accept all", "Skip"], "decline", "Skip"),
    (["수락", "건너뛰기"], "decline", "건너뛰기"),
])
def test_response_puts_off_before_it_asks_for_a_reminder_and_never_for_an_action(labels, answer, picked):
    controls = [{"id": f"b{n}", "text": label} for n, label in enumerate(labels)]
    kind, control = response(controls)
    assert (kind, control["text"] if control else None) == (answer, picked)


@pytest.mark.parametrize("text, goal, kind, found", [
    ("이번 달 구독 해지를 도와드릴게요", "구독 해지", "cancel-subscription", ("retention", "plan", "keep")),
    ("정말 구독을 해지하시겠어요 지금 해지하면 사라져요", "구독 해지", "cancel-subscription", ("retention", "plan", "keep")),
    ("좌석을 예약하시겠어요 예약이 확정돼요", "좌석 예약", "primary", None),
    ("마케팅 수신 동의를 철회할 수 있어요 동의 철회", "마케팅 동의 철회", "withdraw-consent", ("consent", "plan", "keep")),
    ("구독 안내", "구독 해지", "cancel-subscription", None),                  # one goal word is not enough
    ("Your subscription ends soon, cancel your subscription", "Cancel my subscription", "cancel-subscription",
     ("retention", "plan", "keep")),
])
def test_plan_goal_matches_through_hangul_words_of_two_syllables(text, goal, kind, found):
    plan = {"flows": [{"id": "keep", "kind": kind, "goal": goal}]}
    value, basis, flow = purpose(text, plan)
    assert (basis == "plan") is (found is not None)
    if found:
        assert (value, basis, flow) == found


# A real page: the probe reads what the browser says a control is called, and the dialog's own question.

def _page(main="", dialog="", lang="ko"):
    script = ("<script>const post=p=>fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});"
              "document.querySelector('dialog')?.showModal();"
              "for(const c of document.querySelectorAll('[data-go]'))c.addEventListener('click',async e=>{"
              "e.preventDefault();await post('/api/actions');document.querySelector('dialog')?.close();"
              "document.querySelector('main').innerHTML='<h2>Finished</h2>'})</script>")
    modal = f"<dialog>{dialog}</dialog>" if dialog else ""
    return (f'<!doctype html><html lang="{lang}"><meta charset="utf-8"><title>kit</title>'
            f"<body><main><h1>Account</h1>{main}</main>{modal}{script}</body></html>")


def _buttons(*labels, joiner=""):
    return joiner.join(f"<button data-go>{label}</button>" for label in labels)


@contextlib.contextmanager
def _serve(pages):
    """`pages`: path -> HTML. Anything else is a 404; the POSTs of the stub are answered by the browser route."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = pages.get(self.path.split("?")[0])
            if body is None:
                self.send_error(404)
                return
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


DIALOG_PAGES = {
    "see-terms-link": (
        "<p>Before you go: 50% off for 3 months.</p><p><a href=\"#\">See terms</a></p>" + _buttons("Accept offer", "No thanks"),
        "cancel-subscription", "Cancel my subscription", ["No thanks"], "en"),
    "ko-inline-cookie-buttons": (
        "<p>쿠키 사용 안내</p><div>" + _buttons("모두 동의", "필수 쿠키만 허용", joiner=" ") + "</div>",
        "signup", "회원가입", ["필수 쿠키만 허용"], "ko"),
    "en-agree": ("<p>Please agree to the Terms of Service</p>" + _buttons("Agree", "Cancel"),
                 "signup", "Sign up", ["Agree"], "en"),
    "ko-agree-after-refusal": ("<p>이용약관 동의가 필요해요</p>" + _buttons("동의 안 함", "동의"),
                               "signup", "회원가입", ["동의"], "ko"),
    "en-unsubscribe": ("<p>Unsubscribe from all emails?</p>" + _buttons("Cancel", "Unsubscribe"),
                       "unsubscribe", "Unsubscribe from the newsletter", ["Unsubscribe"], "en"),
    "en-withdraw": ("<p>Withdraw your consent?</p>" + _buttons("Cancel", "Withdraw"),
                    "withdraw-consent", "Withdraw marketing consent", ["Withdraw"], "en"),
    "en-cancel-plan": ("<p>Cancel your plan?</p>" + _buttons("Cancel", "Cancel plan"),
                       "cancel-subscription", "Cancel my subscription", ["Cancel plan"], "en"),
    "en-unsubscribe-by-value": ("<p>Unsubscribe from all emails?</p><button data-go>Cancel</button>"
                                "<input type=\"submit\" data-go value=\"Unsubscribe\">",
                                "unsubscribe", "Unsubscribe from the newsletter", ["Unsubscribe"], "en"),
    "ko-offer-pay-now": ("<p>특가 제안: 액자를 1만원에 추가하세요</p>" + _buttons("지금 결제", "나중에 결제"),
                         "purchase", "액자 구매", ["지금 결제"], "ko"),
}


@pytest.mark.parametrize("case", DIALOG_PAGES)
def test_flow_answers_a_real_dialog(browser, case):
    dialog, kind, goal, clicked, lang = DIALOG_PAGES[case]
    with _serve({"/": _page(dialog=dialog, lang=lang)}) as url:
        assert _run_flow(browser, url, "/", kind, goal, "Finished") == ("completed", clicked)


PAGE_PAGES = {
    "save-then-해지": (_buttons("저장", "해지"), "cancel-subscription", "구독 해지", ["해지"]),
    "confirm-then-해지": (_buttons("확인", "해지"), "cancel-subscription", "구독 해지", ["해지"]),
    "decoy-then-submit-by-value": ("<button>Cancel</button><input type=\"submit\" data-go value=\"Reserve\">",
                                   "primary", "Reserve a seat", ["Reserve"]),
    "decoy-then-image-link-by-alt": (
        f'<button>Cancel</button><a href="#" data-go><img alt="Reserve a seat" width="24" height="24" src="{PIXEL}"></a>',
        "primary", "Reserve a seat", ["Reserve a seat"]),
}


@pytest.mark.parametrize("case", PAGE_PAGES)
def test_flow_names_controls_by_the_browsers_accessible_name_and_해지_is_the_goal(browser, case):
    main, kind, goal, clicked = PAGE_PAGES[case]
    with _serve({"/": _page(main=main, lang="ko" if "해지" in main else "en")}) as url:
        assert _run_flow(browser, url, "/", kind, goal, "Finished") == ("completed", clicked)


def _session(browser, url, stub=LABELS_STUB, plan=None):
    session = Session(url, "kit3", engine=StubEngine.load(stub), plan=plan)
    session.contexts = {"d": session.contexts["d"]}

    def open_driver(ctx_id):
        driver = Driver(browser, session, ctx_id)
        driver.open(urlsplit(url).path or "/")
        return driver

    return session, open_driver


SEATS = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>seats</title><body><main><h1>Seats</h1>
<section id="seats" data-state-surface="seats"><h2>Seat status</h2><p id="status" role="status"></p><ul id="list"></ul>
<button id="retry" aria-label="다시 시도">⟳</button></section></main>
<script>
const status=document.querySelector('#status'),list=document.querySelector('#list');
async function load(){try{const r=await fetch('/api/seats');if(!r.ok)throw new Error(r.status);
  const rows=await r.json();list.replaceChildren(...rows.map(x=>Object.assign(document.createElement('li'),{textContent:x.name})));
  status.textContent=rows.length+' seats left'}catch(e){list.replaceChildren();status.textContent='좌석 정보에 문제가 생겼어요.'}}
document.querySelector('#retry').onclick=load;load();
</script></body></html>"""


def test_a_retry_button_named_by_aria_label_is_a_recovery(browser):
    with _serve({"/": SEATS}) as url:
        session, open_driver = _session(browser, url)
        states.run(session, open_driver)
    rows = {row["state"]: row for row in session.document()["probes"]["states"]}
    assert rows["error"]["problem_text"] is True
    assert rows["error"]["recovery_action"] is True


SESSION = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>session</title><body><main>
<label>메모 <input id="memo" type="search"></label><p id="status" role="status">로그인됨</p>
<a id="extend" href="#" hidden><img alt="세션 연장" width="24" height="24" src="@PIXEL@"></a>
<script>
let end=Date.now()+900000;
const status=document.getElementById('status'),extend=document.getElementById('extend');
setInterval(()=>{
  if(Date.now()>=end){status.textContent='세션이 만료되었어요';extend.hidden=true;}
  else if(Date.now()>=end-60000){status.textContent='곧 만료돼요';extend.hidden=false;}
},60000);
extend.onclick=e=>{e.preventDefault();end=Date.now()+900000;status.textContent='로그인됨';extend.hidden=true};
</script></main></body></html>""".replace("@PIXEL@", PIXEL)


def test_a_session_extension_link_named_by_its_image_alt_is_extendable(browser):
    plan = {"flows": [{"id": "work", "start": "/"}]}
    with _serve({"/": SESSION}) as url:
        session, open_driver = _session(browser, url, plan=plan)
        time_limits.run(session, open_driver)
    (item,) = session.document()["probes"]["time_limits"]
    assert item["warned"] is True and item["extendable"] is True and item["extensions"] == 10


def test_history_names_a_link_by_its_image_alt(browser):
    page = (f'<!doctype html><title>h</title><main><a href="/private-area"><img alt="My account" width="24" height="24" '
            f'src="{PIXEL}"></a></main>')
    with _serve({"/": page}) as url:
        session, open_driver = _session(browser, url)
        driver = open_driver("d")
        try:
            (link,) = history._state(driver)["links"]
        finally:
            driver.close()
    assert link["name"] == "My account"


@pytest.mark.parametrize("focused, initial", [
    ('<button autofocus aria-label="삭제">🗑</button><button>취소</button>', "destructive"),
    ('<input type="submit" autofocus value="확인"><button>취소</button>', "destructive"),
    ('<button autofocus>OK</button><button>Cancel</button>', "destructive"),
    ('<button>삭제</button><button autofocus aria-label="Keep">↩</button>', "safe"),
    ('<button>Delete</button><button autofocus aria-label="No thanks">✕</button>', "safe"),
    ('<button>삭제</button><button autofocus aria-label="나중에">↩</button>', "none"),
])
def test_initial_focus_is_read_from_the_focused_controls_accessible_name(browser, focused, initial):
    page = (f'<!doctype html><html lang="ko"><meta charset="utf-8"><title>d</title><main><h1>기록</h1></main>'
            f'<dialog><p>정말 지울까요?</p>{focused}</dialog><script>document.querySelector("dialog").showModal()</script>')
    with _serve({"/": page}) as url:
        session, open_driver = _session(browser, url)
        driver = open_driver("d")
        try:
            driver.boxes()
            target = driver.page.evaluate("document.activeElement.getAttribute('data-lapis-box')")
            result = commits._confirm_and_undo(driver, target, None)
        finally:
            driver.close()
    assert result["confirm"]["initial_focus"] == initial


def test_pointer_alternatives_are_read_in_korean(browser):
    def alternative(control):
        page = ('<!doctype html><html lang="ko"><meta charset="utf-8"><title>p</title><main><section>'
                f'<div draggable="true" tabindex="0">항목</div>{control}</section></main>')
        with _serve({"/": page}) as url:
            session, open_driver = _session(browser, url)
            driver = open_driver("d")
            try:
                box = next(box["id"] for box in driver.boxes() if box["tag"] == "div")
                return pointer._alternative(driver, {"id": box})
            finally:
                driver.close()
    assert alternative("<button>위로 이동</button>") == "buttons"
    assert alternative("<button>순서 바꾸기</button>") == "buttons"
    assert alternative('<button aria-label="아래로">⌄</button>') == "buttons"
    assert alternative("<button>더보기</button>") == "menu"
    assert alternative('<button aria-label="메뉴">⋯</button>') == "menu"
    assert alternative("<button>Move up</button>") == "buttons"
    assert alternative("<button>저장</button>") == "keyboard-only"


def test_a_preprompt_is_granted_by_the_button_that_allows_not_the_one_that_refuses(browser):
    page = ('<!doctype html><html lang="ko"><meta charset="utf-8"><title>n</title><main><button id="ask">알림 허용하기</button></main>'
            "<script>document.getElementById('ask').onclick=()=>{"
            "document.body.insertAdjacentHTML('beforeend','<dialog><p>알림 권한을 허용할까요?</p>"
            "<button id=no>허용 안 함</button><button id=yes>허용</button></dialog>');"
            "const d=document.querySelector('dialog');d.showModal();"
            "d.querySelector('#yes').onclick=()=>{Notification.requestPermission();d.close()};"
            "d.querySelector('#no').onclick=()=>d.close()}</script>")
    with _serve({"/": page}) as url:
        session, open_driver = _session(browser, url)
        permissions.run(session, open_driver)
    assert [row["api"] for row in session.document()["probes"]["permissions"]] == ["notifications"]


def _field(name="", name_attr="", autocomplete="", type="text"):
    return {"name": name, "name_attr": name_attr, "autocomplete": autocomplete, "type": type}


@pytest.mark.parametrize("control, kind", [
    (_field("우편번호", "z", "postal-code"), "postal-code"), (_field("Postal code"), "postal-code"),
    (_field("Zip code", "zip"), "postal-code"), (_field("", "", "postal-code"), "postal-code"),
    (_field("인증번호"), "password"), (_field("Verification code"), "password"), (_field("OTP", "otp"), "password"),
    (_field("", "", "one-time-code"), "password"), (_field("Password", type="password"), "password"),
    (_field("", "", "tel-country-code"), "text"),
    (_field("주소", "", "address-line1"), "address"), (_field("Address"), "address"), (_field("Street address"), "address"),
    (_field("상세 주소", "", "address-line2"), "address-line2"), (_field("상세 주소"), "address-line2"),
    (_field("Address line 2"), "address-line2"), (_field("Apartment, suite"), "address-line2"),
    (_field("", "", "address-line2"), "address-line2"), (_field("Address 2", "address_2"), "address-line2"),
])
def test_field_kind_keeps_postal_codes_and_second_address_lines_apart(control, kind):
    assert flows._field_kind(control) == kind


ADDRESS_STUB = """version: 0
clock: {start: '2026-09-30T00:00:00Z'}
collections: {actions: []}
variants: {empty: {actions: []}, partial: {actions: []}}
routes:
  - {method: POST, path: /api/actions, collection: actions, operation: create}
values:
  v1: {kind: address, valid: 'Example Road 1', invalid: x, alternate: 'Sample Road 2'}
  v2: {kind: postal-code, valid: '00000', invalid: x, alternate: '11111'}
  v3: {kind: text, valid: 'Unit 202', invalid: x, alternate: 'Unit 303'}
"""


def test_korean_address_form_types_each_field_from_its_own_value_and_records_no_sign_in(browser, tmp_path):
    stub = tmp_path / "address.stub.yaml"
    stub.write_text(ADDRESS_STUB)
    form = ('<label>주소 <input autocomplete="address-line1" required></label>'
            '<label>상세 주소 <input autocomplete="address-line2" required></label>'
            '<label>우편번호 <input name="z" autocomplete="postal-code" required></label>' + _buttons("결제하기"))
    plan = {"flows": [{"id": "pay", "kind": "purchase", "goal": "액자 구매", "start": "/", "done": {"text": "Finished"}}]}
    with _serve({"/": _page(main=form)}) as url:
        session, open_driver = _session(browser, url, stub=stub, plan=plan)
        flows.run(session, open_driver)
    run = session.document()["flows"][0]
    typed = [action["value_id"] for step in run["steps"] for action in step["actions"] if action["kind"] == "type"]
    assert run["status"] == "completed", run.get("note")
    assert typed == ["v1", "v3", "v2"]                      # address, its second line (free text), postal code
    assert {gate["kind"] for gate in run["gates"]} == {"address"}      # not an undeclared sign-in


@pytest.mark.parametrize("control, kind", [
    (_field("카드 보안 코드"), "card-cvc"), (_field("CVC"), "card-cvc"), (_field("카드 번호"), "card"),
    (_field("휴대폰 번호"), "phone"), (_field("핸드폰"), "phone"), (_field("Phone"), "phone"),
])
def test_field_kind_reads_korean_card_security_and_mobile_wording(control, kind):
    assert flows._field_kind(control) == kind


@pytest.mark.parametrize("wording, gate", [
    ("친구에게 공유하고 계속하기", "share"), ("공유하면 잠금 해제돼요", "share"), ("친구 3명 초대하면 할인", "share"),
    ("Share to continue", "share"), ("Invite 3 friends to unlock", "share"),
    ("공유 설정을 확인하세요", None), ("친구 목록", None),
])
def test_share_gate_is_read_in_korean(wording, gate):
    found = next((kind for kind, pattern in flows.GATE_WORDING if kind == "share" and re.search(pattern, wording, re.I)), None)
    assert found == gate


def test_help_and_login_links_rank_lower_in_korean_as_they_do_in_english():
    # "예약 도움말" shares the goal word 예약 and so does "예약하기": the help link must not tie with the action.
    assert _choose("", ["예약 도움말", "예약하기"], "primary", "좌석 예약", dialog=False) == "예약하기"
    assert _choose("", ["로그인 후 예약", "예약하기"], "primary", "좌석 예약", dialog=False) == "예약하기"
    assert _choose("", ["Reserve help", "Reserve"], "primary", "Reserve a seat", dialog=False) == "Reserve"


@pytest.mark.parametrize("button, hint_mismatch", [
    ("나중에 결제", []), ("Pay later", []), ("나중에", ["skippable"]), ("Maybe later", ["skippable"]),
    ("건너뛰기", ["skippable"]), ("Skip", ["skippable"]),
])
def test_a_gate_is_skippable_only_by_a_put_off_or_skip_not_by_a_later_action(browser, button, hint_mismatch):
    """The page hints that its gate cannot be skipped; only a real put-off or skip control contradicts it."""
    main = ('<div data-lapis-gate="permission" data-lapis-skippable="false">알림 허용 권한이 필요해요</div>'
            + _buttons(button))
    plan = {"flows": [{"id": "ask", "kind": "primary", "goal": "알림 설정", "start": "/", "done": {"text": "Finished"}}]}
    with _serve({"/": _page(main=main)}) as url:
        session, open_driver = _session(browser, url, stub=FIXTURES / "choices-app" / "choices.stub.yaml", plan=plan)
        flows.run(session, open_driver)
    (gate,) = session.document()["flows"][0]["gates"]
    assert gate["kind"] == "permission" and gate.get("hint_mismatch", []) == hint_mismatch
