"""Run the plan's flows end to end and record steps, effort, prices, cart, terms, and gates.

Everything is read from what the screen shows (DERIVED.md, Flows); nothing needs the app's
cooperation. One DOM read per screen collects:

- price rows: the nearest list item, table row, definition, or paragraph around each money
  amount ($, €, £, ₩, 원, or an ISO code). Kind from the label (fee, shipping, tax, deposit,
  discount, subtotal, total, recurring from cadence words, in English and Korean), key from the
  normalized label, state from pending/estimated wording, mandatory unless the line (or the
  same key's cart line) has a remove or uncheck control, placement from geometry (inside a closed
  `details` = collapsed, `role=tooltip` = tooltip, in main at body size or larger = primary,
  otherwise secondary), and user_caused from the driver's own actions since that key was last
  seen (a control touched inside the row, a control whose name shares a word with the label, an
  address entered before shipping or tax, a quantity before an item). A total or subtotal that
  changed with a user-caused component is user-caused too.
- cart lines: price rows inside a region named cart, basket, bag, order, or summary (ARIA name,
  labelling element, or its own heading). added_by is user when the driver touched a control in
  the line, chose the item on an earlier screen with an add/reserve/buy control, or named it;
  preselected when the line holds a checked option the driver never touched; system otherwise.
- terms: renewal price, cadence, trial end and conversion, cancellation method and terms by
  wording; fee and total from price rows. near-commit when readable on the commit step within
  one viewport height of the commit control.
- gates: required fields (password → sign-in, account, or reauth by wording and whether the run
  already signed in; card → payment; address; birth date → age; identity documents; required
  marketing consent) and wording for permission, share, install, survey, and support contact.
- offers: dialogs and headed sections whose wording is a retention, upsell, cross-sell, or survey
  block; blocking when it is a dialog or no enabled forward control exists outside it.

Optional hints locate and group, and never decide a value (DERIVED.md, Flows, Hints):
`data-lapis-price` (component kind) with `data-lapis-key`, `data-lapis-state`,
`data-lapis-mandatory`, `data-lapis-cadence`, `data-lapis-placement`;
`data-lapis-cart-line` (line key) with `data-lapis-added-by`;
`data-lapis-disclosure` (term kind) with `data-lapis-placement`;
`data-lapis-gate` (gate kind) with `data-lapis-skippable`;
`data-lapis-offer` (offer kind) with `data-lapis-blocks`.
A hinted element is read even where the heuristic would not look, and `data-lapis-key` and the
cart-line key become the component and line keys. Every other value comes from the page reading
above; a hint that differs from it is listed by field name in the observation's `hint_mismatch`.
Where the reading finds nothing for a hinted element (no term in its wording, no gate of that
kind on the step, no offer wording), the hint's kind is kept and listed as a mismatch.

Action choice is deterministic: required empty fields first (fixture values only), then controls
ranked by overlap with the goal and the flow kind's vocabulary, forward wording, and the main
region; in an optional-offer dialog the decline control wins. On a screen that offers a confirm control
(in an exit flow also a control named for the exit action, such as Unsubscribe or 탈퇴), a control whose
whole name is cancel, close, or put-off wording gets neither forward nor goal-word points; cancel wording
is forward only in an exit flow, and 해지 never backs out. A control is read by its accessible name. An
action that changed nothing is not repeated on that screen. Runs stop as completed, blocked, dead-end, or
abandoned after 40 actions.
Flows run only against the stub backend, since any control may commit.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from lapis_design.behavior_check.probes._decision import (
    ACCEPT, AGREE, BACK_OUT, CANCEL, CLOSE, CONFIRM, DECLINE, DISMISS, EXIT_ACTION, LATER, REFUSE, names)
from lapis_design.behavior_check.redact import path as safe_path

NAMES = ("flows",)
EXIT_KINDS = {"cancel-subscription", "delete-account", "withdraw-consent", "unsubscribe"}
PRICED_KINDS = {"purchase", "subscribe"}
WORDS = re.compile(r"\w+", re.UNICODE)
KIND_WORDS = {
    "primary": "reserve checkout continue confirm place order",
    "purchase": "buy checkout continue pay place order",
    "subscribe": "subscribe join continue confirm",
    "grant-consent": "notices notification subscribe join continue confirm",
    "cancel-subscription": "cancel subscription manage unsubscribe continue phone call",
    "withdraw-consent": "stop notices unsubscribe cancel manage continue phone call",
    "unsubscribe": "unsubscribe cancel stop continue phone call",
    "delete-account": "delete account close account continue confirm",
    "signup": "sign up register join continue",
    "recover": "recover reset password continue",
}
# CONFIRM finishes a step; WITHDRAW backs out of it, and is read only as a control's whole name ("Cancel
# subscription" is not "Cancel"; 해지 ends a contract and never backs out). Cancel wording is forward only in
# an exit flow, where cancelling is the point; "다음에" is "next time", not the forward word "다음".
WITHDRAW = re.compile(rf"{BACK_OUT}|{CLOSE}|{LATER}|not now", re.I)
# The answer that wins an optional dialog: the shared decline, refuse, and later wording, and these.
TURN_DOWN = re.compile(rf"{DECLINE}|{REFUSE}|{LATER}|continue cancel|계속 (?:취소|해지)", re.I)
# A dialog whose text speaks of an offer, retention ("before you go"), upsell (upgrade), marketing, advertising,
# cookies, optional consent, a discount (50% off), or staying is optional; the Korean words are the counterparts
# of the English ones, in that order. Consent alone is not an offer, and neither is a dialog that asks the user
# to agree to what the flow needs: terms, or an item marked required.
OPTIONAL_DIALOG = re.compile(r"offer|retention|before you (?:go|cancel|leave)|upsell|upgrade|marketing|advertis|cookie|"
                             r"optional consent|discount|\d\s?% off|stay|"
                             r"혜택|제안|특가|해지하기 전|떠나기 전|업그레이드|마케팅|광고성|쿠키|선택 ?동의|할인|유지|계속 이용", re.I)
# What asks for that agreement. Mentioning terms or a required item does not ("Terms apply", "필수 쿠키는
# 항상 켜져 있어요", "No card required"); the terms an offer comes with are cleared before this is read.
ASKS_AGREEMENT = re.compile(
    r"\b(?:agree|accept|consent)\w*\b[^.?!]{0,40}\bterms\b|\bterms\b[^.?!]{0,40}\b(?:agree|accept)"
    r"|[\[(]required[\])]|\brequired to (?:continue|sign up|register|create)"
    r"|약관[^.?!]{0,20}동의|동의[^.?!]{0,10}필수|[\[(]필수[\])]|필수 ?(?:약관|항목|동의)", re.I)
OFFER_TERMS = re.compile(
    r"\b(?:offer|promo(?:tion(?:al)?)?|discount|deal)\s+terms\b"
    r"|\bterms(?:\s+(?:and|&)\s+conditions)?(?:\s+of\s+(?:the|this)\s+(?:offer|deal|promotion))?\s+apply\b"
    r"|(?:혜택|이벤트|프로모션|할인|쿠폰)\s?약관", re.I)
FORWARD = re.compile(rf"{CONFIRM}|continue|next|checkout|reserve|subscribe|join|stop|call|review|manage|pay|"
                     r"신청|예약|계속|다음(?!에)|결제|가입|구독하", re.I)
HANGUL_WORD = re.compile(r"[가-힣]{2,}")
BACK = re.compile(r"back|previous|return|edit|change|뒤로|이전|변경", re.I)
ADD = re.compile(r"\badd\b|\bbuy\b|reserve|\bchoose\b|\bselect\b|\bbook\b|담기|구매|예약|선택", re.I)
FIELD_TYPES = ("text", "email", "password", "tel", "search", "number", "select", "textarea", "date", "url")

MONEY = re.compile(r"(-)?\s?(?:([$€£₩])\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s?(원|KRW|USD|EUR|GBP))")
CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP", "₩": "KRW", "원": "KRW"}
CHARGES = (("discount", r"discount|coupon|promo|savings|할인|쿠폰"),
           ("subtotal", r"subtotal|sub-total|소계|상품 ?금액"),
           ("total", r"\btotal\b|합계|총액|총 ?결제|결제 ?금액"),
           ("shipping", r"shipping|delivery|postage|배송"),
           ("tax", r"\btax\b|\bvat\b|\bgst\b|세금|부가세"),
           ("deposit", r"deposit|보증금|예치금"),
           ("fee", r"\bfee\b|surcharge|service charge|수수료"))
CADENCES = (("day", r"/\s?day\b|per day|\bdaily\b|매일"),
            ("week", r"/\s?(?:wk|week)\b|per week|\bweekly\b|매주"),
            ("month", r"/\s?mo(?:nth)?\b|per month|a month\b|\bmonthly\b|매월|/\s?월"),
            ("year", r"/\s?(?:yr|year)\b|per year|a year\b|\byearly\b|annual(?:ly)?|매년|/\s?년"),
            ("other", r"every \d+ (?:days|weeks|months)|매 ?\d+ ?(?:주|개월)"))
PENDING = re.compile(r"to be calculated|calculated (?:at|later|in)|\bpending\b|\btbd\b|계산 예정|추후", re.I)
ESTIMATED = re.compile(r"approx|estimat|\babout\b|~\s?[$€£₩\d]|약 ?[$€£₩\d]|예상", re.I)
LINE_EXCLUDED = {"total", "subtotal", "discount", "tax", "shipping"}
DISCLOSURE_KINDS = ("renewal-price", "cadence", "trial-end", "trial-conversion", "cancellation-method",
                    "cancellation-terms", "fee", "total")
PLACEMENTS = ("near-commit", "primary", "secondary", "collapsed", "tooltip", "after-commit", "absent")
GATE_KINDS = ("account", "sign-in", "identity", "payment", "address", "age", "reauth", "optional-consent",
              "permission", "share", "install", "survey", "contact")
GATE_WORDING = (("permission", r"allow (?:notifications|location|camera|microphone)|enable (?:notifications|location)|"
                               r"알림 허용|위치 권한"),
                ("share", r"share (?:this )?to (?:continue|unlock)|invite \d* ?friends? to|"
                          r"공유하(?:고|면|여|해야)[^.?!]{0,12}(?:계속|잠금 ?해제)|친구 ?\d* ?명? ?(?:을 )?초대"),
                ("install", r"install (?:the|our) app|download (?:the|our) app to|앱 설치"),
                ("survey", r"tell us why|why are you (?:leaving|cancell)|reason for (?:leaving|cancell)|quick survey|설문"),
                ("contact", r"only by (?:phone|chat|email)|(?:call|contact|email|chat with) (?:us|support|studio support) to "
                            r"(?:cancel|complete|finish)|고객센터(?:로|에) (?:전화|문의)"))
OFFERS = (("retention", r"before you (?:go|cancel|leave)|stay subscribed|hate to see you go|keep your "
                        r"(?:plan|subscription|membership)|pause (?:instead|your)|offer to stay|retention offer|"
                        r"떠나기 전|해지하기 전"),
          ("upsell", r"\bupgrade\b|\bupsell\b|go premium|add .{0,30} for (?:only|just)|업그레이드"),
          ("cross-sell", r"you may also like|frequently bought|customers also|complete the (?:set|look)|함께 구매"),
          ("survey", r"tell us why|why are you (?:leaving|cancell)|quick survey|reason for (?:leaving|cancell)|설문"))
CHANNELS = (("phone", r"only by phone|call (?:us|phone support|studio support|support) to cancel|call to cancel|"
                      r"전화로만|전화로 해지|tel:"),
            ("chat", r"only by chat|chat (?:with us|with support)? ?to cancel|채팅으로만"),
            ("email", r"only by email|email (?:us|support) to cancel|mailto:"),
            ("request-form", r"request form|submit a (?:cancellation )?request|요청서"))
STOP = {"the", "and", "for", "your", "with", "this", "that", "from", "continue", "next", "order", "total",
        "price", "item", "items", "per", "now"}
HINT_FIELDS = ("kind", "state", "mandatory", "cadence", "placement", "added_by", "skippable", "blocks")

SCREEN = r"""(args) => {
 const forward=new RegExp(args.forward,'i');
 const vis=el=>{if(!el)return false; for(let p=el;p;p=p.parentElement){const s=getComputedStyle(p);
   if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}
   const r=el.getBoundingClientRect();return !!(r.width&&r.height)};
 const id=el=>el?.closest('[data-lapis-box]')?.getAttribute('data-lapis-box')||null;
 const rect=el=>{const r=el.getBoundingClientRect();return {y:r.y+scrollY,h:r.height}};
 const flat=t=>(t||'').replace(/\s+/g,' ').trim();
 const labelledBy=el=>(el.getAttribute('aria-labelledby')||'').split(/\s+/).map(i=>document.getElementById(i)?.textContent||'').join(' ');
 const named=args.names||{};
 const labelOf=el=>flat(named[el.getAttribute('data-lapis-box')]||labelledBy(el)||el.getAttribute('aria-label')||
   el.labels?.[0]?.innerText||el.innerText||el.getAttribute('title')||el.getAttribute('placeholder')||'');
 const bodyPx=parseFloat(getComputedStyle(document.body).fontSize)||16;
 const main=document.querySelector('main,[role=main]');
 const dialog=[...document.querySelectorAll('dialog,[role=dialog],[role=alertdialog]')].find(vis);
 const ctrlSel='button,a[href],input:not([type=hidden]),textarea,select,[role=button],[role=link],[role=checkbox],[role=switch],summary';
 const ctrlEls=[...document.querySelectorAll(ctrlSel)].filter(vis);
 const controls=ctrlEls.map(el=>({id:id(el),name:labelOf(el),
   type:el.localName==='input'?el.type:(el.getAttribute('role')||el.getAttribute('type')||el.localName),
   required:el.required||el.getAttribute('aria-required')==='true',
   filled:el.localName==='select'?el.selectedIndex>0:(['INPUT','TEXTAREA'].includes(el.tagName)&&
     !['button','submit','checkbox','radio'].includes(el.type)&&!!el.value),
   checked:!!el.checked||el.getAttribute('aria-checked')==='true',
   disabled:!!el.disabled||el.getAttribute('aria-disabled')==='true',
   in_main:!!el.closest('main,[role=main]'),in_dialog:!!dialog?.contains(el),href:el.getAttribute('href')||'',
   name_attr:el.getAttribute('name')||'',autocomplete:el.getAttribute('autocomplete')||'',rect:rect(el)}));
 const place=el=>{if(el.closest('[role=tooltip]'))return 'tooltip';
   const d=el.closest('details:not([open])'); if(d&&!el.closest('summary'))return vis(d)?'collapsed':null;
   if(!vis(el))return null;
   return el.closest('main,[role=main]')&&parseFloat(getComputedStyle(el).fontSize)>=bodyPx-.5?'primary':'secondary'};
 const money=/(?:[$€£₩]\s?\d|\d[\d,.]*\s?(?:원|KRW|USD|EUR|GBP))/;
 const pending=/to be calculated|calculated (?:at|later|in)|\bpending\b|\btbd\b|계산 예정|추후/i;
 const charge=/fee|shipping|delivery|tax|total|배송|세금|수수료|합계/i;
 const termRe=[['renewal-price',/renewal price|renews? at|after the (?:free )?trial,? .*[$€£₩]|갱신 (?:가격|요금)/i],
   ['cancellation-method',/cancel(?:lation)? (?:by|via|over|through|online|anytime (?:in|from))|call to cancel|해지는? .*(?:전화|온라인)/i],
   ['trial-end',/trial ends?|trial (?:period )?(?:lasts|expires)|체험.*종료/i],
   ['trial-conversion',/trial converts?|after (?:the|your) (?:free )?trial,? you(?:'ll| will) be (?:charged|billed)|유료.*전환/i],
   ['cadence',/(?:billed|charged|renews?) (?:every|monthly|yearly|weekly|annually|each)|매월 결제|월 단위 결제/i],
   ['cancellation-terms',/cancellation (?:terms|policy)|refund policy|환불 규정|해지 규정/i]];
 const termKind=el=>{const t=flat(el.textContent); if(!t||t.length>400)return null;
   for(const [k,re] of termRe) if(re.test(t)) return k; return null};
 const termHint=el=>el.getAttribute('data-lapis-disclosure');
 const bare=el=>{const c=el.cloneNode(true);
   c.querySelectorAll('button,input,select,textarea,[role=button],[role=checkbox],[role=switch]').forEach(n=>n.remove());
   c.querySelectorAll('label').forEach(n=>{if(!money.test(n.textContent))n.remove()});
   return flat(c.textContent)};
 const cartRe=/\bcart\b|basket|\bbag\b|\border\b|summary|장바구니|주문/i;
 const regionName=el=>{let n=el.getAttribute('aria-label')||'';const lb=el.getAttribute('aria-labelledby');
   if(lb)n+=' '+lb.split(/\s+/).map(i=>document.getElementById(i)?.textContent||'').join(' ');
   const h=el.querySelector(':scope>h1,:scope>h2,:scope>h3,:scope>h4,:scope>h5,:scope>h6,:scope>header>h2,:scope>header>h3,:scope>legend,:scope>caption');
   return n+' '+(h?.textContent||'')};
 const cartOf=el=>{for(let p=el.parentElement;p&&p!==document.body;p=p.parentElement)
   if(p.matches('section,aside,article,div,ul,ol,table,form,fieldset,[role=region],[role=list]')&&cartRe.test(regionName(p)))return true;
   return false};
 const rowSel='[data-lapis-price],[data-lapis-cart-line],li,tr,dd,dt,p,[role=row],[role=listitem]';
 const rowSet=new Set();
 const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 for(let n;n=walker.nextNode();){if(!money.test(n.nodeValue))continue;const el=n.parentElement;
   if(!el||el.closest('button,a,[role=button],script,style,option,select,[aria-hidden=true],dialog:not([open])'))continue;
   rowSet.add(el.closest(rowSel)||el);}
 document.querySelectorAll('[data-lapis-price],[data-lapis-cart-line]').forEach(el=>rowSet.add(el));
 document.querySelectorAll('li,tr,dd,p').forEach(el=>{const t=el.textContent;
   if(pending.test(t)&&charge.test(t)&&!el.querySelector('li,tr,dd,p'))rowSet.add(el)});
 const rows=[...rowSet].map(el=>{const placement=place(el);if(!placement)return null;
   if(!el.hasAttribute('data-lapis-price')&&['renewal-price','trial-conversion','trial-end','cancellation-terms'].includes(termKind(el)||termHint(el)))return null;
   let label=bare(el);
   if(el.localName==='dd'&&el.previousElementSibling?.localName==='dt')label=flat(el.previousElementSibling.textContent)+' '+label;
   const ctl=[...el.querySelectorAll('button,input,[role=button],[role=checkbox],[role=switch]')];
   return {id:id(el),text:label,placement,rect:rect(el),
     cart:el.hasAttribute('data-lapis-cart-line')||cartOf(el),
     removable:ctl.some(c=>c.matches('input[type=checkbox],[role=checkbox],[role=switch]')||/remove|delete|삭제|빼기/i.test(labelOf(c))),
     checked:ctl.filter(c=>c.checked||c.getAttribute('aria-checked')==='true').map(id).filter(Boolean),
     controls:ctl.map(id).filter(Boolean),
     hint:{kind:el.getAttribute('data-lapis-price'),key:el.getAttribute('data-lapis-key'),state:el.getAttribute('data-lapis-state'),
       mandatory:el.getAttribute('data-lapis-mandatory'),cadence:el.getAttribute('data-lapis-cadence'),
       placement:el.getAttribute('data-lapis-placement'),line:el.getAttribute('data-lapis-cart-line'),
       added_by:el.getAttribute('data-lapis-added-by')}}}).filter(Boolean);
 const termEls=[...document.querySelectorAll('p,li,dd,dt,small,span,div,td,summary,label,[role=tooltip],[data-lapis-disclosure]')]
   .map(el=>({el,kind:termKind(el),hint:termHint(el)})).filter(t=>t.kind||t.hint);
 const terms=termEls.filter(t=>!termEls.some(o=>o!==t&&(o.kind||o.hint)===(t.kind||t.hint)&&t.el.contains(o.el)))
   .map(t=>({id:id(t.el),kind:t.kind,placement:place(t.el),rect:rect(t.el),text:t.hint?flat(t.el.textContent).slice(0,400):'',
     hint:{kind:t.hint,placement:t.el.getAttribute('data-lapis-placement')}}))
   .filter(t=>t.placement);
 const gates=[...document.querySelectorAll('[data-lapis-gate]')].filter(vis)
   .map(el=>({id:id(el),kind:el.getAttribute('data-lapis-gate'),skippable:el.getAttribute('data-lapis-skippable')}));
 const blocks=[],seen=new Set();
 const addBlock=(el,isDialog)=>{if(!el||seen.has(el)||!vis(el))return;seen.add(el);
   blocks.push({id:id(el),text:flat(el.textContent).slice(0,600),dialog:isDialog,offer:el.getAttribute('data-lapis-offer'),
     blocks:el.getAttribute('data-lapis-blocks'),
     forward_outside:ctrlEls.some(c=>!el.contains(c)&&!c.disabled&&c.getAttribute('aria-disabled')!=='true'&&forward.test(labelOf(c)))})};
 if(dialog)addBlock(dialog,true);
 document.querySelectorAll('[data-lapis-offer]').forEach(el=>addBlock(el,el===dialog));
 if(main)main.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(h=>{const c=h.closest('section,aside,article,[role=region],form,div');
   if(c&&c!==main&&!c.contains(main))addBlock(c,false)});
 const asked=el=>{if(!el)return '';const out=[],w=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
   for(let n;n=w.nextNode();){const p=n.parentElement;
     if(!p||p.closest('button,[role=button],input,select,textarea,script,style')||!vis(p))continue;
     const t=flat(n.nodeValue);if(t)out.push(t)}
   return out.join(' ')};
 return {main:id(main),main_text:main?.innerText||'',dialog:id(dialog),dialog_text:dialog?.innerText||'',dialog_prompt:asked(dialog),
   text:document.body.innerText,path:location.pathname,vh:innerHeight,controls,rows,terms,gates,blocks};
}"""


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _words(text):
    return {w for w in WORDS.findall(text.lower()) if len(w) >= 3 and w not in STOP}


def _bare(name):
    """A control's name without its punctuation: "Cancel." and "취소…" are the word alone."""
    return " ".join("".join(" " if unicodedata.category(ch).startswith("P") else ch for ch in name).split())


def _backs_out(name):
    """The whole name is cancel, close, or put-off wording ("Cancel", "취소", "Not now"); "Cancel
    subscription" and "구독 취소" are not."""
    return bool(WITHDRAW.fullmatch(_bare(name)))


def _exit_named(name):
    """The name says the action that leaves something (Unsubscribe, Withdraw, Stop emails, 탈퇴, Cancel plan):
    unlike a name that is only cancel, it does not back out."""
    return bool(re.search(EXIT_ACTION, name, re.I)) or (bool(re.search(CANCEL, name, re.I)) and not _backs_out(name))


def _forward(name, exit_flow):
    """Forward wording. Cancel wording is forward only in an exit flow, where cancelling is the point."""
    return bool(FORWARD.search(name)) or (exit_flow and bool(re.search(CANCEL, name, re.I)))


def _optional(text, asked=None):
    """A dialog's text speaks of an offer and does not ask the user to agree to what the flow needs (terms, a
    required item). `asked` is the text that can ask, the dialog without its buttons when it is known: a
    button named 모두 동의 beside 필수 쿠키만 허용 asks for nothing."""
    asked = text if asked is None else asked
    return bool(OPTIONAL_DIALOG.search(text)) and not ASKS_AGREEMENT.search(OFFER_TERMS.sub(" ", asked))


def _shared(tokens, vocab):
    """The vocabulary words a name shares: a whole word, or, for a Korean word of two or more syllables,
    a word (eojeol) of the name that begins with it (해지하기 shares 해지)."""
    return {word for word in vocab
            if word in tokens or (HANGUL_WORD.fullmatch(word) and any(token.startswith(word) for token in tokens))}


def _route_matches(pattern, actual):
    escaped = "/".join("[^/]+" if segment == "*" else re.escape(segment) for segment in pattern.split("/"))
    return bool(re.fullmatch(escaped, actual))


def _done(flow, screen, session):
    done = flow["done"]
    return (("route" in done and _route_matches(done["route"], safe_path(screen["path"], session.fixture_values)))
            or ("text" in done and done["text"] in screen["text"]))


def _money(text):
    """(amount, currency) of the first amount in text, or (None, None)."""
    found = MONEY.search(text)
    if not found:
        return None, None
    sign, symbol, number, number2, code = found.groups()
    amount = float((number or number2).replace(",", ""))
    return (-amount if sign else amount), CURRENCY.get(symbol or code, code)


def _label(text):
    text = MONEY.sub(" ", text)
    for _, pattern in CADENCES:
        text = re.sub(pattern, " ", text, flags=re.I)
    text = PENDING.sub(" ", ESTIMATED.sub(" ", text))
    return re.sub(r"[\s:()\-–—/*]+", " ", text).strip()


def _key(label, kind):
    if not label:
        return kind
    if re.search(r"[^\x00-\x7f]", label):
        return f"{kind}-{hashlib.sha1(label.encode()).hexdigest()[:8]}"
    return _slug(label) or kind


def _charge(text):
    return next((kind for kind, pattern in CHARGES if re.search(pattern, text, re.I)), None)


def _cadence(text):
    return next((period for period, pattern in CADENCES if re.search(pattern, text, re.I)), None)


# A second address line (apartment, suite, "상세 주소") is a free-text detail, not another address.
_ADDRESS_LINE2 = re.compile(r"address[ _-]?(?:line[ _-]?)?[23]\b|line[ _-]?[23]\b|apartment|\bapt\b|\bsuite\b|상세 ?주소|나머지 ?주소")


def _field_kind(control):
    label = f"{control['name']} {control['name_attr']} {control['autocomplete']}".lower()
    kind, auto = control["type"].lower(), control["autocomplete"].lower()
    postal = auto == "postal-code" or bool(re.search(r"postal|\bzip\b|우편", label))
    if kind == "password" or auto in ("current-password", "new-password", "one-time-code") or (
            not postal and re.search(r"\bcode\b|\botp\b|verification|인증번호",
                                     f"{control['name']} {control['name_attr']}".lower())):
        return "password"
    if auto.startswith("cc-exp") or re.search(r"expir|만료", label):
        return "card-expiry"
    if auto == "cc-csc" or re.search(r"\bcvc\b|\bcvv\b|security code|보안 ?코드", label):
        return "card-cvc"
    if auto.startswith("cc-") or re.search(r"card|카드", label):
        return "card"
    if kind == "email" or "email" in label or "이메일" in label:
        return "email"
    if kind == "tel" or re.search(r"phone|전화|휴대폰|핸드폰", label):
        return "phone"
    if postal:
        return "postal-code"
    if auto in ("address-line2", "address-line3") or _ADDRESS_LINE2.search(label):
        return "address-line2"
    if re.search(r"street-address|address-line|address-level|address|street|주소", label):
        return "address"
    if auto.startswith("bday") or re.search(r"birth|\bage\b|생년월일|나이", label):
        return "date"
    if re.search(r"passport|identity|id number|national id|신분증|주민", label):
        return "identity"
    if re.search(r"quantity|\bqty\b|수량", label):
        return "number"
    if re.search(r"\bname\b|이름", label):
        return "name"
    return "text"


def _caused(kind, label, row, log):
    words = _words(label)
    for entry in log:
        if entry["target"] in row["controls"] or words & _words(entry["name"]):
            return True
        if kind in ("shipping", "tax") and (entry["field"] in ("address", "postal-code") or
                                            re.search(r"shipping|delivery|배송", entry["name"], re.I)):
            return True
        if kind in ("item", "subtotal") and entry["field"] == "number":
            return True
    return False


def _mismatch(reading: dict, hints: dict) -> list[str]:
    """Fields whose data-lapis-* hint differs from the page reading, in schema order. An absent hint
    agrees with anything; the reading `None` (nothing found) differs from any hint."""
    def norm(value):
        return ("true" if value else "false") if isinstance(value, bool) else value
    return [field for field in HINT_FIELDS
            if hints.get(field) is not None and norm(hints[field]) != norm(reading.get(field))]


def _observe_money(run, screen, driver, index, state):
    rows = [dict(row, text=driver.clean(row["text"])) for row in screen["rows"]]
    lines, line_by_key, components, charged, seen = [], {}, [], [], set()
    for row in rows:
        hint = row["hint"]
        amount, currency = _money(row["text"])
        row["amount"], row["currency"] = amount, currency
        label = _label(row["text"])
        charge = _charge(label)
        row["label"], row["charge"] = label, charge
        # Hints only group: data-lapis-key and the cart-line key name the component and line.
        row["key"] = _slug(hint["key"] or hint["line"] or "") or _key(label, charge or "item")
        if not row["cart"] or charge in LINE_EXCLUDED:
            continue
        if (set(row["controls"]) & state["touched"] or row["key"] in state["chosen"]
                or _words(label) & state["add_words"]):
            added_by = "user"
        elif set(row["checked"]) - state["touched"]:
            added_by = "preselected"
        else:
            added_by = "system"
        line = {"key": row["key"], "added_by": added_by, "amount": amount or 0, "removable": row["removable"]}
        if row["id"]:
            line["box"] = row["id"]
        if mismatch := _mismatch(line, {"added_by": hint["added_by"]}):
            line["hint_mismatch"] = mismatch
        if row["key"] not in line_by_key:
            line_by_key[row["key"]] = line
            lines.append(line)
    currencies = [row["currency"] for row in rows if row["currency"]]
    currency = max(set(currencies), key=currencies.count) if currencies else None
    for row in rows:
        if row["key"] in seen or (row["currency"] and row["currency"] != currency):
            continue
        seen.add(row["key"])
        hint, line = row["hint"], line_by_key.get(row["key"])
        cadence = _cadence(row["text"])
        kind = row["charge"] or ("add-on" if line and line["added_by"] != "user" else "item")
        if cadence and kind in ("item", "add-on"):
            kind = "recurring"
        amount = row["amount"]
        state_value = ("pending" if amount is None or PENDING.search(row["text"]) else
                       "estimated" if ESTIMATED.search(row["text"]) else "known")
        mandatory = not (row["removable"] or (line is not None and line["removable"]))
        placement = row["placement"] if row["placement"] in ("primary", "secondary", "collapsed", "tooltip") else "secondary"
        shown = amount if state_value != "pending" else None
        changed = row["key"] not in state["last_seen"] or state["last_seen"][row["key"]] != shown
        component = {"key": row["key"], "kind": kind, "state": state_value, "mandatory": mandatory,
                     "placement": placement,
                     "user_caused": bool(changed and _caused(kind, row["label"], row, state["log"]))}
        component["_changed"] = changed
        if shown is not None:
            component["amount"] = shown
        if cadence:
            component["cadence"] = cadence
        if row["id"]:
            component["box"] = row["id"]
        # A component with no cadence reading is charged once.
        hints = {field: hint[field] for field in ("kind", "state", "mandatory", "cadence", "placement")}
        if mismatch := _mismatch({**component, "cadence": cadence or "once"}, hints):
            component["hint_mismatch"] = mismatch
        components.append(component)
        charged.append((kind, row))
    if any(c["user_caused"] for c in components if c["kind"] not in ("total", "subtotal")):
        for c in components:
            if c["kind"] in ("total", "subtotal") and c["_changed"]:
                c["user_caused"] = True
    for c in components:
        del c["_changed"]
        state["last_seen"][c["key"]] = c.get("amount")
    if components and currency:
        run.setdefault("prices", []).append({"step": index, "currency": currency, "components": components})
        state["log"].clear()
        state["screen_keys"] = [c["key"] for c in components if c["kind"] in ("item", "add-on", "recurring")]
    if lines:
        run.setdefault("cart", []).append({"step": index, "lines": lines})
    return [(kind, row) for kind, row in charged if kind in ("fee", "total")]


def _row_terms(rows):
    """Fee and total disclosures read from price rows: (kind, placement, rect, box, hint_mismatch)."""
    out = []
    for row in rows:
        charge = _charge(_label(row["text"]))
        out.append((charge, row["placement"], row["rect"], row["id"], _mismatch({"kind": charge}, {"kind": row["hint"]["kind"]})))
    return out


def _screen_terms(screen):
    """Term disclosures read from wording: (kind, placement, rect, box, hint_mismatch). A hinted
    element whose wording names no term but a fee or total is read as that charge; one whose
    wording names nothing keeps the hinted kind, listed as a mismatch."""
    out = []
    for term in screen["terms"]:
        kind = term["kind"]
        if kind is None and term["hint"]["kind"]:
            kind = _charge(_label(term["text"]))
            kind = kind if kind in ("fee", "total") else None
        mismatch = _mismatch({"kind": kind, "placement": term["placement"]}, term["hint"])
        out.append((kind or term["hint"]["kind"], term["placement"], term["rect"], term["id"], mismatch))
    return out


def _disclose(run, index, kind, placement, box, mismatch=()):
    if kind not in DISCLOSURE_KINDS or placement not in PLACEMENTS:
        return
    if "commit_step" in run and index > run["commit_step"]:
        placement = "after-commit"
    known = next((d for d in run.setdefault("disclosures", []) if d["kind"] == kind), None)
    if known is None:
        known = {"kind": kind, "placement": placement, "step": index, "at_commit": False}
        run["disclosures"].append(known)
    elif placement != "after-commit" and (PLACEMENTS.index(placement), bool(mismatch)) < (
            PLACEMENTS.index(known["placement"]), "hint_mismatch" in known):
        known.update(placement=placement, step=index)   # a better placement, or the same one confirmed
    else:
        return
    if box:
        known["box"] = box
    if mismatch:
        known["hint_mismatch"] = list(mismatch)
    else:
        known.pop("hint_mismatch", None)


def _observe(run, screen, driver, step, state, *, include_offers=True):
    index = step["index"]
    charged = _observe_money(run, screen, driver, index, state)
    for kind, placement, _, box, mismatch in _screen_terms(screen):
        _disclose(run, index, kind, placement, box, mismatch)
    for kind, row in charged:
        _disclose(run, index, kind, row["placement"], row["id"], _mismatch({"kind": kind}, {"kind": row["hint"]["kind"]}))
    wording = f"{screen['main_text']} {screen['dialog_text']}"
    skippable = any(re.search(rf"\bskip\b|not now|건너뛰기|{LATER}", c["name"], re.I) and not c["disabled"]
                    for c in screen["controls"])
    readings = {}                                   # gate kind -> box, as the page shows them
    for control in screen["controls"]:
        field = _field_kind(control) if control["type"].lower() in FIELD_TYPES else None
        kind = None
        if field == "password":
            kind = ("reauth" if state["signed_in"] or re.search(
                        r"confirm (?:your )?password|re-?enter|verify (?:it'?s|that it'?s) you|비밀번호 (?:재)?확인", wording, re.I)
                    else "account" if re.search(r"create (?:an )?account|sign ?up|register|회원가입", wording, re.I)
                    else "sign-in")
        elif field in ("card", "card-expiry", "card-cvc"):
            kind = "payment"
        elif control["required"] and field in ("address", "postal-code"):
            kind = "address"
        elif control["required"] and field == "date" and re.search(r"birth|age|생년월일|나이", control["name"] + control["autocomplete"], re.I):
            kind = "age"
        elif control["required"] and field == "identity":
            kind = "identity"
        elif control["required"] and control["type"] == "checkbox" and re.search(
                r"marketing|newsletter|promot|offers|광고|마케팅", control["name"], re.I):
            kind = "optional-consent"
        if kind:
            readings.setdefault(kind, control["id"])
    for kind, pattern in GATE_WORDING:
        if re.search(pattern, wording, re.I):
            readings.setdefault(kind, screen["dialog"] or screen["main"])
    # A gate hint locates the gate; the page must show a gate of that kind on this step too.
    gates = [(hint["kind"], hint["id"] or readings.get(hint["kind"]),
              _mismatch({"kind": hint["kind"] if hint["kind"] in readings else None, "skippable": skippable}, hint))
             for hint in screen["gates"]]
    gates += [(kind, box, []) for kind, box in readings.items()]
    for kind, box, mismatch in gates:
        if kind not in GATE_KINDS or any(g["step"] == index and g["kind"] == kind for g in run.setdefault("gates", [])):
            continue
        entry = {"step": index, "kind": kind, "skippable": skippable, "declared": kind in run["_requires"]}
        if box:
            entry["box"] = box
        if mismatch:
            entry["hint_mismatch"] = mismatch
        run["gates"].append(entry)
        if kind == "reauth":
            run["effort"]["reauth"] = True
    if include_offers:
        kinds = set()
        for block in screen["blocks"]:
            reading = next((k for k, pattern in OFFERS if re.search(pattern, block["text"], re.I)), None)
            kind = reading or block["offer"]
            if kind not in ("retention", "upsell", "cross-sell", "survey") or kind in kinds or not block["id"]:
                continue
            kinds.add(kind)
            blocks = block["dialog"] or not block["forward_outside"]
            offer = {"box": block["id"], "kind": kind, "blocks": blocks}
            if mismatch := _mismatch({"kind": reading, "blocks": blocks}, {"kind": block["offer"], "blocks": block["blocks"]}):
                offer["hint_mismatch"] = mismatch
            step.setdefault("offers", []).append(offer)
    if run["kind"] in EXIT_KINDS and "channel" not in run["effort"]:
        signals = screen["text"] + " " + " ".join(c["href"] for c in screen["controls"])
        channel = next((c for c, pattern in CHANNELS if re.search(pattern, signals, re.I)), None)
        if channel:
            run["effort"]["channel"] = channel
    if not step.get("back_available"):
        step["back_available"] = any(BACK.search(c["name"]) for c in screen["controls"] if not c["disabled"])


def _at_commit(run, screen, target, index):
    control = next((c for c in screen["controls"] if c["id"] == target), None)
    readable = {}                                   # kind -> hint mismatch of its best reading ([] when confirmed)
    for kind, placement, rect, box, mismatch in _screen_terms(screen) + _row_terms(screen["rows"]):
        if kind not in DISCLOSURE_KINDS or placement in ("collapsed", "tooltip"):
            continue
        if not mismatch or kind not in readable:
            readable[kind] = mismatch
        if control and abs((rect["y"] + rect["h"] / 2) - (control["rect"]["y"] + control["rect"]["h"] / 2)) <= screen["vh"]:
            _disclose(run, index, kind, "near-commit", box, mismatch)
    for term in run.get("disclosures", []):
        term["at_commit"] = term["kind"] in readable
        if readable.get(term["kind"]):               # readable at the commit only by an unconfirmed hint
            fields = {*term.get("hint_mismatch", ()), *readable[term["kind"]]}
            term["hint_mismatch"] = [field for field in HINT_FIELDS if field in fields]


def _choose(screen, flow, tried, session):
    dialog = bool(screen["dialog"])
    controls = [c for c in screen["controls"] if c["id"] and not c["disabled"] and
                (c["in_dialog"] if dialog else not c["in_dialog"])]
    actionable = [c for c in controls if c["type"] not in FIELD_TYPES + ("checkbox", "radio", "switch")
                  and not c["href"].startswith(("tel:", "mailto:"))]
    exit_flow = flow["kind"] in EXIT_KINDS
    confirming = any(re.search(CONFIRM, c["name"], re.I) or (exit_flow and _exit_named(c["name"])) for c in actionable)

    def forward(name):
        """Forward wording, except that beside a confirm control a name that only backs out is not."""
        return _forward(name, exit_flow) and not (confirming and _backs_out(name))

    for c in controls:
        kind = c["type"].lower()
        if c["id"] in tried or kind not in FIELD_TYPES or c["filled"]:
            continue
        field = _field_kind(c)
        if c["required"] or (field in ("address", "postal-code", "card", "email", "phone", "name", "password") and
                             not any(forward(item["name"]) and item["id"] not in tried for item in controls)):
            values = session.values_engine
            if values is None:
                return None, "no synthetic values (--values)"
            fixture_kind = "text" if field in ("identity", "address-line2") else field   # no fixture kind of their own
            try:
                value_id = values.values_for(fixture_kind, "valid")
            except (KeyError, ValueError):
                return None, f"no synthetic {fixture_kind} fixture value"
            return ({"kind": "select" if kind == "select" else "type", "target": c["id"],
                     "value": "valid", "value_id": value_id}, None)
    candidates = [c for c in actionable if c["id"] not in tried]
    vocab = set(WORDS.findall(flow["goal"].lower())) | set(WORDS.findall(KIND_WORDS.get(flow["kind"], "")))
    optional = _optional(screen["dialog_text"], screen.get("dialog_prompt"))

    def score(c):
        name = c["name"].lower()
        tokens = set(WORDS.findall(name))
        shared = set() if confirming and _backs_out(name) else _shared(tokens, vocab)
        decline = bool(TURN_DOWN.search(name))
        return (100 if dialog and decline and optional else 0) + (
            30 if shared else 0) + len(shared) * 5 + (14 if forward(name) else 0) + (
            20 if dialog and (re.search(rf"{ACCEPT}|{CLOSE}|{DISMISS}", name) or (
                re.search(AGREE, name) and not re.search(REFUSE, name))) else 0) + (
            4 if c["in_main"] else 0) - (30 if BACK.search(name) else 0) - (
            25 if re.search(r"login|sign in|support|help|로그인|고객 ?(?:센터|지원)|도움말", name) and not dialog else 0)
    candidates.sort(key=score, reverse=True)
    if not candidates or score(candidates[0]) <= 0:
        return None, None
    chosen = candidates[0]
    return {"kind": "tap" if session.contexts[screen["_context"]]["pointer"] == "coarse" else "click",
            "target": chosen["id"]}, chosen["name"]


def _main_replaced(before, after):
    return bool(before and after and SequenceMatcher(None, before, after, autojunk=False).ratio() < .5)


def _read(driver, flow):
    """One DOM read of the screen; cancel wording counts as forward outside an offer only in an exit flow."""
    forward = FORWARD.pattern + (f"|{CANCEL}" if flow["kind"] in EXIT_KINDS else "")
    return driver.page.evaluate(SCREEN, {"forward": forward, "names": names(driver)})


def _run_one(session, open_driver, flow, ctx_id, start):
    driver = open_driver(ctx_id)
    try:
        if urlsplit(driver.page.url).path != start:
            driver.open(start)
        run = {"id": flow["id"], "context": ctx_id, "kind": flow["kind"], "status": "blocked",
               "steps": [], "effort": {"steps": 0, "interactions": 0, "fields": 0,
                                    "single_field_steps": 0, "offers": 0, "blocking_offers": 0, "reauth": False},
               "_requires": set(flow.get("requires") or [])}
        state = {"log": [], "touched": set(), "chosen": set(), "add_words": set(), "last_seen": {},
                 "screen_keys": [], "signed_in": False}
        tried = set()
        prev = None
        for _ in range(41):
            screen = _read(driver, flow)
            screen["_context"] = ctx_id
            path = safe_path(screen["path"], session.fixture_values)
            if re.search(r"\bfree trial\b|\bdiscounted (?:first|introductory) (?:month|week|year)\b|무료 체험", screen["text"], re.I):
                run["trial"] = True
            changed = (prev is None or path != prev["path"] or screen["dialog"] != prev["dialog"]
                       or _main_replaced(prev["main_text"], screen["main_text"]))
            if changed:
                step = {"index": len(run["steps"]), "path": path, "actions": [], "back_available": False}
                if screen["main"]:
                    step["main"] = screen["main"]
                if screen["dialog"]:
                    step["dialog"] = screen["dialog"]
                run["steps"].append(step)
                tried.clear()
                _observe(run, screen, driver, step, state)
            else:
                step = run["steps"][-1]
                if any(screen[k] != prev[k] for k in ("rows", "terms", "gates")):
                    _observe(run, screen, driver, step, state, include_offers=False)
            prev = screen
            if _done(flow, screen, session):
                run["status"] = "completed"
                break
            if sum(len(s["actions"]) for s in run["steps"]) >= 40:
                run["status"] = "abandoned"
                break
            action, name = _choose(screen, flow, tried, session)
            if action is None:
                if name:
                    run["note"] = name
                else:
                    available = bool(tried) or any(c["id"] and not c["disabled"] and
                        (_forward(c["name"], flow["kind"] in EXIT_KINDS) or BACK.search(c["name"]) or c["href"].startswith("/"))
                        for c in screen["controls"])
                    run["status"] = "blocked" if available else "dead-end"
                    if run["status"] == "dead-end":
                        step["dead_end"] = True
                break
            old_signature = (path, screen["main_text"], screen["dialog"])
            control = next((c for c in screen["controls"] if c["id"] == action["target"]), None)
            effect = driver.act(action)
            step["actions"].append(action)
            field = _field_kind(control) if control and control["type"].lower() in FIELD_TYPES else None
            state["log"].append({"target": action["target"], "name": control["name"] if control else "", "field": field})
            state["touched"].add(action["target"])
            if field == "password":
                state["signed_in"] = True
            if action["kind"] in ("click", "tap") and ADD.search(name or ""):
                state["chosen"].update(state["screen_keys"])
                state["add_words"] |= _words(name)
            if action["kind"] in ("click", "tap", "paste", "type", "select", "check", "uncheck", "drag"):
                run["effort"]["interactions"] += 1
            if action["kind"] in ("paste", "type", "select"):
                run["effort"]["fields"] += 1
            if "commit_step" not in run and any(
                    r["method"] in ("POST", "PUT", "PATCH", "DELETE") and not r.get("blocked")
                    for r in effect.get("requests", [])):
                run["commit_step"] = step["index"]
                _at_commit(run, screen, action["target"], step["index"])
                run["review_before_commit"] = bool(run.get("cart") or run.get("disclosures")) and any(
                    p["step"] <= step["index"] and any(c["kind"] == "total" for c in p["components"])
                    for p in run.get("prices", [])) and any(
                    BACK.search(c["name"]) or re.search(r"remove|edit|change|삭제", c["name"], re.I)
                    for c in screen["controls"] if not c["disabled"])
            fresh = _read(driver, flow)
            if (safe_path(fresh["path"], session.fixture_values), fresh["main_text"], fresh["dialog"]) == old_signature:
                tried.add(action["target"])
        else:
            run["status"] = "abandoned"
        effort = run["effort"]
        effort["steps"] = sum(bool(s["actions"]) for s in run["steps"])
        longest = streak = 0
        for step in run["steps"]:
            fields = [a for a in step["actions"] if a["kind"] in ("type", "paste", "select")]
            streak = streak + 1 if len(fields) == 1 and len(step["actions"]) == 1 else 0
            longest = max(longest, streak)
        effort["single_field_steps"] = longest
        effort["offers"] = sum(len(s.get("offers", [])) for s in run["steps"])
        effort["blocking_offers"] = sum(o["blocks"] for s in run["steps"] for o in s.get("offers", []))
        if run["kind"] in EXIT_KINDS and "channel" not in effort and run["status"] == "completed" and "commit_step" in run:
            effort["channel"] = "self-serve"
        if any(c["kind"] == "recurring" or c.get("cadence") in ("day", "week", "month", "year", "other")
               for price in run.get("prices", []) for c in price["components"]):
            required = {"renewal-price", "cadence", "cancellation-method"}
            if run.get("trial"):
                required.update(("trial-end", "trial-conversion"))
            recorded = {d["kind"] for d in run.get("disclosures", [])}
            for kind in sorted(required - recorded):
                run.setdefault("disclosures", []).append({"kind": kind, "placement": "absent", "at_commit": False})
        del run["_requires"]
        return run
    finally:
        driver.close()


def run(session, open_driver):
    plans = (session.plan or {}).get("flows") or []
    if not plans:
        session.cover("flows", "not-applicable")
        return
    if session.meta["backend"] != "stub":
        session.cover("flows", "partial", contexts=list(session.matrix),
                      reason="interactive journeys may commit; flows require the stub backend")
        return
    by_id = {flow["id"]: flow for flow in plans}
    gaps = []
    for ctx_id in session.matrix:
        if session.engine is not None:
            session.engine.reset()
        for flow in plans:
            start = by_id.get(flow.get("pair"), flow)["start"]
            result = _run_one(session, open_driver, flow, ctx_id, start)
            session.add_flow_run(result)
            where = f"{ctx_id}/{flow['id']}"
            if result["status"] != "completed":
                gaps.append(f"{where}: {result['status']} ({result.get('note', 'goal not reached')})")
            if result["kind"] in PRICED_KINDS and "commit_step" in result and not result.get("prices"):
                gaps.append(f"{where}: commit reached without an observed price")
            if result["kind"] in EXIT_KINDS and "channel" not in result["effort"]:
                gaps.append(f"{where}: exit channel not classified")
    session.cover("flows", "partial" if gaps else "ran", contexts=list(session.matrix),
                  reason="; ".join(gaps) if gaps else None)
