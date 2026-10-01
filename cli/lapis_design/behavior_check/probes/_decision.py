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
# Cancelling backs out of a step ("Cancel", "취소"). 해지 ends a contract: it answers like a cancel when a
# question is read, but a control named only 해지 is how an exit flow ends, never a way back.
BACK_OUT = "cancel|취소"
CANCEL = f"{BACK_OUT}|해지"
# A control named for the action that leaves something. A bare cancel is not here: it backs out.
EXIT_ACTION = r"unsubscribe|withdraw|\bstop\b|\bdelete|해지|탈퇴|철회|수신 ?거부"
CLOSE = r"\bclose\b|닫기|✕|✖"
CONFIRM = r"confirm|submit|save|done|finish|\bok\b|확인|제출|저장|완료"           # finishes a step
ACCEPT = r"confirm|continue|accept|yes|okay|확인|계속|수락"                      # goes on with what a dialog asks
AGREE = r"\bagree\b|동의"                                                       # agrees, unless REFUSE says it refuses
DECLINE = (r"decline|no thanks|not now|\bskip\b|\bleave\b|거절|건너뛰|아니요|아니오|"
           r"괜찮아요|괜찮습니다")                                              # turns an offer down
REFUSE = (r"reject|don't allow|거부|허용 ?안|허용하지 않|동의 ?안(?!내)|동의하지 않|비동의|미동의|"
          r"\b(?:only|just) (?:the )?(?:necessary|essential|required)\b|\b(?:necessary|essential|required)(?: cookies)? only\b|"
          r"(?:continue|proceed) without\b|필수(?: ?쿠키)?만 ?(?:허용|동의|수락|사용)")  # refuses a request, consent, an add-on, or all but the necessary
# Puts an offer off: a phrase, or the word alone as a whole label. A word inside another action ("Pay
# later", "Save for later", "나중에 결제") does not put anything off.
LATER = (r"\bmaybe later\b|\bremind me later\b|^\W*later\W*$|^\W*(?:나중에|다음에)\W*$|"
         r"나중에 ?(?:할게요|하기|할래요|볼게요|다시|알려|알림)|다음에 ?(?:할게요|하기)")
REMIND = "remind|다시 ?알려"                                                    # asks for a future reminder; turning notifications on (알림 받기) is an accept
DISMISS = "dismiss|숨기|×|^x$"                                                 # hides without choosing an offer
_TRY_AGAIN_KO = "다시 ?시도|다시 ?해 ?보|재시도"
RETRY = f"retry|try again|reload|{_TRY_AGAIN_KO}|다시 ?불러|새로 ?고침"   # runs a failed load again
RESUBMIT = f"retry|try again|resubmit|{_TRY_AGAIN_KO}|다시 ?(?:제출|전송|보내)|재(?:제출|전송)"   # sends a failed commit again
PROBLEM = ("error|fail|offline|unavailable|not found|forbidden|denied|timed out|오류|에러|실패|못했|못해|수 없|"
           "되지 않|존재하지 않|오프라인|연결이 끊|권한이 없|거부|시간이? ?초과|문제가 (?:생|발생)")   # says what went wrong
CUSTOMIZE = "manage|settings|preferences|customi[sz]e|설정|관리"       # opens finer choices
_PAUSE_KO = "일시 ?정지|일시 ?중지|정지|중지|멈춤|멈추기"
PAUSE = rf"\b(?:pause|stop)\b|{_PAUSE_KO}"                              # halts content that moves by itself
# A control of a media element. English words match inside longer ones ("unmute", "playback"), as they did
# before; "play" starts playback, the rest halt it or set its volume.
MEDIA_HALT = rf"pause|stop|mute|volume|{_PAUSE_KO}|음소거|볼륨|음량"
MEDIA_CONTROL = rf"{MEDIA_HALT}|play|재생"
WAITING = (r"\b(?:pending|saving|processing|please wait)\b|(?:처리|저장|전송|요청|제출|결제|등록|삭제) ?중(?![단지])|잠시만|"
           r"기다려 ?(?:주세요|주십시오|주시기|주시겠|줘)")                  # a commit is under way
# A dialog offering not to be shown again: group 1 is the English "for N days", group 2 the Korean "N일";
# "오늘 하루" is one day and "일주일" seven. Korean names the span before the verb, English after it.
_NOT_SEEN_KO = r"(?:(?:보|표시하|열|묻|알리)지 ?(?:않|마)|안 ?보)"
AGAIN = (r"(?:don't|do not|never) (?:show|ask)(?: me)?(?: this)? again(?: for (\d+) days)?"
         rf"|(?:(\d+) ?일|일주일|오늘 ?하루|하루)(?: ?동안| ?간)? ?(?:다시 ?)?{_NOT_SEEN_KO}"
         r"|(?:오늘|하루|일주일) ?(?:동안|간)? ?그만 ?보"
         rf"|(?:다시|더 이상) ?{_NOT_SEEN_KO}")

# What a commit's result message claims, in the order they are tried: the first list that matches wins.
# What the page cannot confirm comes first, then a negated or stopped result (a failure), then what was
# kept on the device, then success, then "in progress". A conditional or future mention of a result
# ("once saved", "완료 후") and a state that was there already ("still subscribed") report nothing: NOT_A_RESULT
# blanks them before the lists are read. Korean "할 수 없어요" or "문제가 생기면" in a fixed note is not a
# failure, so failure reads only the past tense of a Korean problem, as English reads "could not".
# The completed forms of leaving (unsubscribed, cancelled, 해지됐어요, 탈퇴했어요) are a success only for a commit
# that leaves something (EXIT_SUCCESS, through `claim_table`): after a payment, "Payment cancelled" is not one.
_DONE_EN = (r"(?:sav(?:e|ed)|confirm(?:ed)?|complet(?:e|ed)|delet(?:e|ed)|reserv(?:e|ed)|sen[dt]|submit(?:ted)?|"
            r"subscrib(?:e|ed)|un-?subscrib(?:e|ed)|cancel(?:l?ed)?|withdr(?:aw|awn|ew)|"
            r"regist(?:er|ered)|sign(?:ed)? up|pa(?:y|id)|book(?:ed)?|plac(?:e|ed)|"
            r"process(?:ed)?|deliver(?:ed)?|go(?:ne)? through)")           # what a commit does, base form or participle
_DONE_PARTICIPLE = (r"(?:saved|confirmed|completed|deleted|reserved|sent|submitted|subscribed|unsubscribed|"
                    r"cancel(?:l?ed)|withdrawn|registered|signed up|paid|booked|placed|processed|delivered|gone through)")
_ASIDE = r"(?:(?:yet|been|be|being|successfully|properly|fully|really)\s+){0,3}"
_STOPPED_KO = r"중[단지](?:됐|되었|됨|되어|돼|됩니다|했|하였|함)"           # "중단됐어요", "중지됨"; a bare 중지 is a button
_PAST_KO = r"(?:했|하였|됐|되었)"                                        # done, in the past tense
CLAIMS = (
    ("unknown", r"\b(?:cannot confirm|can['’]t confirm|could not confirm|couldn['’]t confirm|unable to confirm|"
                r"(?:cannot|can ?not|can['’]t|could not|couldn['’]t) be confirmed|checking|unknown|not sure)\b|"
                r"확인할 수 없|확인하지 못했|확인 ?중|확인하고 있|확실하지 않"),
    ("failure", r"\b(?:failed|failure|error|try again|could not|unable to)\b|couldn['’]t\b"
                rf"|\b(?:not|never)\s+{_ASIDE}{_DONE_PARTICIPLE}\b|n['’]t\s+{_ASIDE}{_DONE_PARTICIPLE}\b"
                rf"|\b(?:cannot|can['’]t)\s+{_ASIDE}{_DONE_PARTICIPLE}\b"
                rf"|\b(?:nothing|no\s+\w+|not\s+(?:all|every)(?:\s+\w+){{0,2}})\s+(?:(?:was|were|has|have|is|are)\s+)?{_ASIDE}{_DONE_PARTICIPLE}\b"
                rf"|\b(?:did|was|were)(?:n['’]t| not)(?:\s+able to)?\s+{_DONE_EN}\b"
                rf"|실패|오류|에러|{_TRY_AGAIN_KO}|지 ?않았(?!다면|으면|을 경우)|못 ?했|수 없었|"
                rf"문제가 (?:생겼|발생했)|{_STOPPED_KO}"),
    ("saved-locally", r"\b(?:saved (?:on|to) (?:this |your |the )?device|saved locally|(?:saved|created|kept) (?:an )?offline copy)\b"
                      rf"|(?:기기에(?:만)? ?(?:임시 ?)?|로컬에 ?)저장{_PAST_KO}"
                      rf"|오프라인 ?사본.{{0,8}}?(?:만들었|만들어졌|저장{_PAST_KO})"),
    ("success", r"\b(?:saved|confirmed|completed|reserved|sent|success|done|subscribed|signed up|registered|"
                r"submitted|paid|booked|placed)\b"
                r"|(?<!미)완료(?!하기|하려면|하면|되면|되기|되지|하지|될|할| ?예정| ?후| ?시(?![각간]))|성공(?!하면|하기|하지|할|될)"
                rf"|(?:저장|확정|예약|전송|발송|접수|등록|가입|신청|제출|구독|결제){_PAST_KO}|보냈"),
    ("pending", rf"{WAITING}|\bin progress\b|진행 ?중(?![단지])"),
)
# What also reads as success after a commit that leaves something (an exit flow's commit, or a control that
# cancels, deletes, unsubscribes, or withdraws): "Unsubscribed", "Your subscription has been cancelled",
# "구독이 해지됐어요", "탈퇴했어요".
EXIT_SUCCESS = (r"\b(?:unsubscribed|cancel(?:l?ed)|deleted|withdrawn|withdrew)\b"
                rf"|(?:해지|취소|탈퇴|철회|삭제){_PAST_KO}(?!다면)")


def claim_table(leaving: bool):
    """CLAIMS in reading order; for a commit that leaves something, success also reads EXIT_SUCCESS."""
    return tuple((claim, f"{words}|{EXIT_SUCCESS}" if leaving and claim == "success" else words) for claim, words in CLAIMS)


# Phrases that name a result without reporting one: after a condition ("once saved"), in the future
# ("will be sent"), or as a state that was there already ("still subscribed").
NOT_A_RESULT = re.compile(
    rf"\b(?:once|when|whenever|if|after|until|unless|as soon as)\b(?:\s+[\w'’]+){{0,3}}?\s+{_DONE_EN}\b"
    rf"|(?:\b(?:will|shall|going to|gonna)|['’]ll)\b(?:\s+[\w'’]+){{0,2}}?\s+{_DONE_EN}\b"
    rf"|\b(?:still|already|currently|remain(?:s|ed)?)\b(?:\s+(?:be|been|is|are))?\s+{_DONE_EN}\b")


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
      .map(c => ({id:c.getAttribute('data-lapis-box'),text:(c.getAttribute('aria-label')||c.innerText||c.value||'').trim()})),
    again:(m=>m?(m[1]||m[2]||(/일주일/.test(m[0])?'7':/하루|오늘/.test(m[0])?'1':null)):null)((el.innerText||'').match(new RegExp(words.again,'i'))),
    again_offered:new RegExp(words.again,'i').test(el.innerText||'')};
})"""


def names(driver):
    """Accessible name by box id, from a fresh snapshot: a control's wording is read from it, not from
    its text (`<button aria-label="닫기">✕</button>` is a close button)."""
    return {box["id"]: box["name"] for box in driver.boxes() if box["name"]}


def dialogs(driver):
    named = names(driver)
    found = driver.page.evaluate(DIALOGS, {"again": AGAIN})
    for dialog in found:
        for control in dialog["controls"]:
            control["text"] = named.get(control["id"], control["text"])
    return found


def route(driver):
    return safe_path(driver.page.url, driver.session.fixture_values)


_IGNORED_GOAL_WORDS = {"their", "after", "before", "using", "there"}
_HANGUL_WORD = re.compile(r"[가-힣]{2,}")


def _goal_overlap(goal, content):
    """The plan goal's words that the text holds. A word is five or more letters, or two or more Hangul
    syllables; a Hangul word is held when a word of the text begins with it (구독 in 구독을)."""
    words = set(re.findall(r"[\w-]{5,}", content))
    runs = re.findall(r"[가-힣]+", content)
    goal_words = {*re.findall(r"[\w-]{5,}", goal), *_HANGUL_WORD.findall(goal)} - _IGNORED_GOAL_WORDS
    return {word for word in goal_words
            if word in words or (_HANGUL_WORD.fullmatch(word) and any(run.startswith(word) for run in runs))}


def purpose(text, plan):
    content = text.lower()
    for flow in (plan or {}).get("flows", []):
        goal = flow.get("goal", "").lower()
        kind = flow.get("kind", "")
        if len(_goal_overlap(goal, content)) >= 2:
            value = {"grant-consent": "consent", "withdraw-consent": "consent", "subscribe": "marketing",
                     "unsubscribe": "marketing", "cancel-subscription": "retention", "purchase": "upsell"}.get(kind)
            if value:
                return value, "plan", flow.get("id")
    cases = ((r"cookie|privacy|consent|tracking|personal data|쿠키|개인 ?정보|추적|트래킹", "consent"),
             (r"notif(?:ication)? permission|allow notifications|enable notifications|알림 ?권한|알림(?:을)? ?(?:허용|켜|켤)",
              "permission-preprompt"),
             (r"newsletter|subscribe|email updates|marketing|뉴스레터|구독(?:하|해)(?! ?주셔서)|구독 ?신청|"
              r"이메일 ?(?:소식|업데이트)|소식(?:을)? ?받|마케팅|광고성", "marketing"),
             (r"stay|don't leave|exit offer|keep your plan|머물|떠나|가지 ?마|계속 ?이용|(?:요금제|플랜)(?:를|을)? ?유지", "retention"),
             (r"upgrade|special offer|add to (?:order|cart)|업그레이드|특별 ?(?:제안|혜택|할인)|장바구니에 ?(?:담|추가)|주문에 ?추가", "upsell"),
             (r"confirm|are you sure|delete|cancel order|정말[^.?!]{0,30}(?:까요|시겠|건가요)|삭제|주문 ?(?:을 )?취소|"
              r"확인하시겠|확정(?:할까요|하시겠)", "confirm"),
             (r"error|failed|couldn't|오류|에러|실패|못했", "error"))
    for expression, value in cases:
        if re.search(expression, content):
            return value, "text", None
    return "other", "heuristic", None


def response(controls):
    """Prefer an actual refusal, then a put-off (before a request for a reminder), then dismissal; no forced
    acceptance. Turning notifications on (알림 받기) is an acceptance, so it is never an answer."""
    def pick(pattern):
        return next((item for item in controls if item['id'] and re.search(pattern, item['text'], re.I)), None)
    for kind, pattern in (("decline", rf"{REFUSE}|{DECLINE}|{CANCEL}|{CLOSE}"),
                          ("later", LATER), ("later", REMIND), ("dismiss", DISMISS)):
        found = pick(pattern)
        if found:
            return kind, found
    return "none", None
