"""DOM observations and label wording shared by the dialog, choice, flow, state, and commit probes."""
from __future__ import annotations

import re
from lapis_design.behavior_check import settle
from lapis_design.behavior_check.redact import path as safe_path

# Wording of controls and messages, English and Korean. Each list is read by every probe that judges
# that kind of label, so a language added for one cannot be missing from another. Alternatives are
# regex fragments for `re.I` searches (and JS `RegExp`), joined with `|`. English words that could sit
# inside another word ("sent" in "consent") carry word boundaries; Korean has none, because a Hangul
# word runs into its ending.
CANCEL = "cancel|취소"
CLOSE = "close|닫기"
DECLINE = "decline|no thanks|not now|거절|아니요|아니오|괜찮아요|괜찮습니다"    # turns an offer down
REFUSE = "reject|don't allow|거부|허용 ?안|허용하지 않"                  # refuses a request or consent
LATER = "later|나중에|다음에"                                          # puts an offer off
REMIND = "remind|다시 ?알려|알림 ?받"                                   # asks for a future reminder
DISMISS = "dismiss|숨기|×|^x$"                                         # hides without choosing an offer
_TRY_AGAIN_KO = "다시 ?시도|다시 ?해 ?보|재시도"
RETRY = f"retry|try again|reload|{_TRY_AGAIN_KO}|다시 ?불러|새로 ?고침"   # runs a failed load again
RESUBMIT = f"retry|try again|resubmit|{_TRY_AGAIN_KO}|다시 ?(?:제출|전송|보내)|재(?:제출|전송)"   # sends a failed commit again
PROBLEM = ("error|fail|offline|unavailable|not found|forbidden|denied|timed out|오류|에러|실패|못했|못해|수 없|"
           "되지 않|존재하지 않|오프라인|연결이 끊|권한이 없|거부|시간이? ?초과|문제가 (?:생|발생)")   # says what went wrong
CUSTOMIZE = "manage|settings|preferences|customi[sz]e|설정|관리"       # opens finer choices
WAITING = r"\b(?:pending|saving|processing|please wait)\b|(?:처리|저장|전송|요청|제출|결제|등록|삭제) ?중|잠시만|기다려"   # a commit is under way
# A dialog offering not to be shown again: group 1 is the English "for N days", group 2 the Korean "N일";
# "오늘 하루" is one day. Korean names the span before the verb, English after it.
_NOT_SEEN_KO = r"(?:(?:보|표시하|열|묻)지 ?(?:않|마)|안 ?보)"
AGAIN = (r"(?:don't|do not|never) (?:show|ask)(?: me)? again(?: for (\d+) days)?"
         rf"|(?:(\d+) ?일|오늘 ?하루|하루)(?: ?동안| ?간)? ?(?:다시 ?)?{_NOT_SEEN_KO}"
         rf"|(?:다시|더 이상) ?{_NOT_SEEN_KO}")

# What a commit's result message claims, in the order they are tried: the first list that matches wins.
# A Korean "할 수 없어요" or "문제가 생기면" in a fixed note is not a failure, so failure reads only the
# past tense of a Korean problem, as English reads "could not".
CLAIMS = (
    ("saved-locally", r"\b(?:saved (?:on|to) (?:this )?device|saved locally|offline copy)\b"
                      r"|기기에(?:만)? ?(?:임시 ?)?저장|로컬에 ?저장|오프라인 ?사본"),
    ("unknown", r"\b(?:cannot confirm|checking|unknown|not sure)\b|확인할 수 없|확인 ?중|확인하고 있|확실하지 않"),
    ("failure", r"\b(?:failed|failure|not saved|error|try again|could not|unable to)\b"
                rf"|실패|오류|에러|{_TRY_AGAIN_KO}|못 ?했|수 없었|되지 않았|문제가 (?:생겼|발생했)"),
    ("success", r"\b(?:saved|confirmed|completed|deleted|reserved|sent|success|done)\b"
                r"|완료(?!하기|하려면|하면|되면|되기|시)|성공(?!하면|하기)"
                r"|(?:저장|확정|삭제|예약|전송|발송|접수|등록|가입|신청|제출|구독|결제)(?:했|됐|되었)|보냈"),
    ("pending", rf"{WAITING}|\bin progress\b|진행 ?중"),
)


def advance(driver, ms):
    """Advance the shared controlled timeline without replaying every intermediate animation frame."""
    before = driver.page.evaluate("window.__lapisObserve?.mutations || 0")
    driver.advance_clock(ms, jump=True)
    settle.quiet(driver, before)


class _ScriptedBrowser:
    """Browser proxy whose new contexts carry extra init scripts from their first document."""

    def __init__(self, browser, scripts):
        self._browser = browser
        self._scripts = scripts

    def new_context(self, **options):
        context = self._browser.new_context(**options)
        for script in self._scripts:
            context.add_init_script(script)
        return context


def reopen_with(driver, *scripts):
    """Reload the context in a fresh profile whose API wrappers run before any page script.

    open_driver has already loaded the page once without them; a real permission request from
    that load can hold a device for the rest of the profile, so the profile is replaced."""
    browser = driver.browser
    driver.browser = _ScriptedBrowser(browser, scripts)
    try:
        driver.open(storage="fresh")
    finally:
        driver.browser = browser


DIALOGS = """(words) => [...document.querySelectorAll('[data-lapis-box]')].filter(el => {
  const r=el.getBoundingClientRect(), s=getComputedStyle(el);
  if (!r.width || !r.height || s.visibility==='hidden' || s.display==='none' || s.opacity==='0') return false;
  if (el.matches('dialog:not([open]):not([role]), [aria-hidden="true"]')) return false;
  const role=el.getAttribute('role');
  const semantic=el.localName==='dialog'||role==='dialog'||role==='alertdialog'||el.hasAttribute('aria-modal');
  const overlay=s.position==='fixed' && r.width*r.height/(innerWidth*innerHeight)>=.3 &&
    el.querySelector('button,a,[role=button]') && !el.closest('main');
  return semantic||overlay;
}).filter(el => !el.parentElement?.closest('dialog,[role="dialog"],[role="alertdialog"],[aria-modal]'))
.map(el => {const r=el.getBoundingClientRect(), s=getComputedStyle(el);
  const rect={x:r.x,y:r.y,w:r.width,h:r.height};
  const edge=Math.abs(r.bottom-innerHeight)<12, bar=edge||Math.abs(r.top)<12;
  const kind=el.localName==='dialog'||el.getAttribute('aria-modal')==='true'||el.getAttribute('role')==='alertdialog' ?
    (edge && r.height<innerHeight*.7?'sheet':'modal') :
    (s.position==='fixed'&&bar&&r.height<innerHeight*.35?'banner':
    (s.position==='fixed'&&r.width*r.height>=innerWidth*innerHeight*.3?'interstitial':'popover'));
  const active=document.activeElement;
  const body=document.body;
  const outside=[...document.querySelectorAll('main, [role="main"]')].some(main =>
    !el.contains(main) && (main.inert||main.getAttribute('aria-hidden')==='true'));
  return {id:el.getAttribute('data-lapis-box'),kind,area:Math.min(1,r.width*r.height/(innerWidth*innerHeight)),
    text:(el.innerText||'').slice(0,1500),focus:el.contains(active)?active.closest('[data-lapis-box]')?.getAttribute('data-lapis-box'):null,
    background_inert:outside||el.matches('dialog:modal'), blocks:el.matches('dialog:modal,[aria-modal="true"]')||outside||
      (getComputedStyle(body).overflow==='hidden'&&s.position==='fixed'),
    controls:[...el.querySelectorAll('button,a,[role="button"],input[type=button],input[type=submit]')]
      .filter(c => {let q=c.getBoundingClientRect(),t=getComputedStyle(c);return q.width&&q.height&&t.visibility!=='hidden'&&t.display!=='none'})
      .map(c => ({id:c.getAttribute('data-lapis-box'),text:(c.innerText||c.getAttribute('aria-label')||c.value||'').trim()})),
    again:(m=>m?(m[1]||m[2]||(/하루/.test(m[0])?'1':null)):null)((el.innerText||'').match(new RegExp(words.again,'i'))),
    again_offered:new RegExp(words.again,'i').test(el.innerText||'')};
})"""


def dialogs(driver):
    driver.boxes()
    return driver.page.evaluate(DIALOGS, {"again": AGAIN})


def route(driver):
    return safe_path(driver.page.url, driver.session.fixture_values)


def purpose(text, plan):
    content = text.lower()
    for flow in (plan or {}).get("flows", []):
        goal = flow.get("goal", "").lower()
        kind = flow.get("kind", "")
        terms = [word for word in re.findall(r"[\w-]{5,}", goal) if word not in {"their", "after", "before", "using", "there"}]
        if len(set(terms) & set(re.findall(r"[\w-]{5,}", content))) >= 2:
            value = {"grant-consent": "consent", "withdraw-consent": "consent", "subscribe": "marketing",
                     "unsubscribe": "marketing", "cancel-subscription": "retention", "purchase": "upsell"}.get(kind)
            if value:
                return value, "plan", flow.get("id")
    cases = ((r"cookie|privacy|consent|tracking|personal data|쿠키|개인 ?정보|추적|트래킹|동의", "consent"),
             (r"notif(?:ication)? permission|allow notifications|enable notifications|알림 ?권한|알림(?:을)? ?(?:허용|켜|켤)",
              "permission-preprompt"),
             (r"newsletter|subscribe|email updates|뉴스레터|구독(?:하|해)|구독 ?신청|이메일 ?(?:소식|업데이트)|소식(?:을)? ?받", "marketing"),
             (r"stay|don't leave|exit offer|keep your plan|머물|떠나|가지 ?마|계속 ?이용|(?:요금제|플랜)(?:를|을)? ?유지", "retention"),
             (r"upgrade|special offer|add to (?:order|cart)|업그레이드|특별 ?(?:제안|혜택|할인)|장바구니에 ?(?:담|추가)|주문에 ?추가", "upsell"),
             (r"confirm|are you sure|delete|cancel order|정말[^.?!]{0,30}(?:까요|시겠|건가요)|삭제|주문 ?(?:을 )?취소|확인하시겠",
              "confirm"),
             (r"error|failed|couldn't|오류|에러|실패|못했", "error"))
    for expression, value in cases:
        if re.search(expression, content):
            return value, "text", None
    return "other", "heuristic", None


def response(controls):
    """Prefer an actual refusal, then defer, then dismissal; no forced acceptance."""
    def pick(pattern):
        return next((item for item in controls if item['id'] and re.search(pattern, item['text'], re.I)), None)
    for kind, pattern in (("decline", rf"{REFUSE}|{DECLINE}|{CANCEL}|{CLOSE}"),
                          ("later", rf"{REMIND}|{LATER}"), ("dismiss", DISMISS)):
        found = pick(pattern)
        if found:
            return kind, found
    return "none", None
