"""Record complete decision routes and their visible affordances."""
from __future__ import annotations

import re

from lapis_design.behavior_check.probes._decision import (
    CANCEL, CLOSE, CUSTOMIZE, DECLINE, DISMISS, REFUSE, advance, dialogs, purpose, reopen_with, route)
from lapis_design.behavior_check.probes.permissions import INIT as DENY_DEVICES

NAMES = ("choices",)

OPTIONS = """(rootId) => {
 const root=document.querySelector('[data-lapis-box="'+rootId+'"]');if(!root)return [];
 const parse=(color)=>{const v=color.match(/[\\d.]+/g)||[];return v.length>=3?v.slice(0,3).map(Number):[255,255,255]};
 const linear=n=>{n/=255;return n<=.04045?n/12.92:((n+.055)/1.055)**2.4};
 const luminance=c=>{const v=parse(c).map(linear);return v[0]*.2126+v[1]*.7152+v[2]*.0722};
 const oklchL=c=>{const [r,g,b]=parse(c).map(linear);return Math.cbrt(.4122214708*r+.5363325363*g+.0514459929*b)*.2104542553+
 Math.cbrt(.2119034982*r+.6806995451*g+.1073969566*b)*.7936177850-
 Math.cbrt(.0883024619*r+.2817188376*g+.6299787005*b)*.0040720468};
 return [...root.querySelectorAll('button,a[href],input[type=checkbox],input[type=radio],[role=button],[role=switch]')]
 .filter(el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width&&r.height&&s.visibility!=='hidden'&&s.display!=='none'})
 .map(el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el),parent=getComputedStyle(el.parentElement||el),
 label=(el.labels?.[0]?.innerText||el.innerText||el.getAttribute('aria-label')||el.value||'').trim(),
 background=s.backgroundColor==='rgba(0, 0, 0, 0)'?parent.backgroundColor:s.backgroundColor,
 filled=Math.abs(oklchL(background)-oklchL(parent.backgroundColor))>=.05,
 bordered=!filled&&parseFloat(s.borderTopWidth)>0&&s.borderTopStyle!=='none',
 range=document.createRange();range.selectNodeContents(el);
 const textRect=range.getBoundingClientRect(),size=filled||bordered?r.width*r.height:
   (textRect.width*textRect.height||r.width*r.height);
 const a=luminance(s.color),b=luminance(background);
 return {id:el.getAttribute('data-lapis-box'),label,tag:el.localName,type:el.type||el.getAttribute('role')||'',
   checked:!!el.checked,lang:el.lang||document.documentElement.lang||null,
   visual:{area_px:Math.round(size*100)/100,filled,bordered,contrast:Math.round((Math.max(a,b)+.05)/(Math.min(a,b)+.05)*100)/100,
   size_px:parseFloat(s.fontSize)||0,weight:parseInt(s.fontWeight)||400,
   in_first_viewport:r.top>=0&&r.bottom<=innerHeight&&r.left>=0&&r.right<=innerWidth}}});
}"""


GROUPS = """() => [...document.querySelectorAll('fieldset,[role="group"]')]
 .filter(el=>!el.closest('dialog,[role="dialog"],[role="alertdialog"]'))
 .map(el=>({id:el.getAttribute('data-lapis-box'),text:(el.innerText||'').slice(0,800)}))
 .filter(group=>group.id && /plan|add-on|optional|gift wrap|요금제|추가 ?상품|선택 ?사항|선물 ?포장/i.test(group.text))"""


def _kind(text, input_type, purpose_name):
    if re.search(rf"{CUSTOMIZE}|options|옵션|선택 ?사항", text, re.I):
        return "customize"
    if re.search(rf"{REFUSE}|{DECLINE}|opt out|unsubscribe|수신 ?거부|구독 ?(?:해지|취소)|{CANCEL}", text, re.I):
        return "decline" if purpose_name != "confirm" else "neutral"
    if re.search(rf"{CLOSE}|{DISMISS}", text, re.I):
        return "dismiss"
    if input_type == "radio" and purpose_name != "plan":
        return "neutral"
    if purpose_name == "confirm":
        return "neutral"
    return "accept"


def _option(driver, item, purpose_name, layer=1, interactions=1):
    kind = _kind(item["label"], item["type"], purpose_name)
    name = driver.clean(item["label"])
    option = {"kind": kind, "control": "checkbox" if item["type"] == "checkbox" else
              "radio" if item["type"] == "radio" else "link" if item["tag"] == "a" else
              "icon" if not name or name in ("×", "✕") else "button",
              "label": name, "layer": layer, "interactions": interactions,
              "visual": item["visual"]}
    if item["id"]:
        option["box"] = item["id"]
    if item["lang"]:
        option["lang"] = item["lang"]
    if item["type"] in ("checkbox", "radio"):
        option["preselected"] = item["checked"]
    price = re.search(r"(?:(USD|EUR|GBP)\s*|([$€£]))\s*(\d+(?:\.\d{1,2})?)", name)
    if price:
        option["price"] = float(price[3])
        option["currency"] = price[1] or {"$": "USD", "€": "EUR", "£": "GBP"}[price[2]]
        option["cadence"] = next((value for value in ("day", "week", "month", "year")
                                  if re.search(rf"(?:/|per )\s*{value}", name, re.I)), "once")
    return option


def run(session, open_driver):
    count = 0
    partial = []
    found: set[tuple[str, str, str]] = set()
    for ctx_id in session.matrix:
        driver = open_driver(ctx_id)
        try:
            reopen_with(driver, DENY_DEVICES)
            links = driver.page.evaluate("""() => [...document.querySelectorAll('a[href]')]
              .filter(a => /plan|pricing|add-on|optional|요금제|가격|추가 ?상품|선택 ?사항/i.test(a.innerText||''))
              .map(a => new URL(a.href)).filter(u => u.origin===location.origin)
              .map(u => u.pathname).slice(0,2)""")
            # Probe load-time, timed and control-opened decisions, without choosing accept routes.
            for stage in ("load", "timer", "controls"):
                if stage == "timer":
                    advance(driver, 5500)
                if stage == "controls" and session.meta["backend"] == "stub":
                    for control in driver.interactive():
                        if re.search(r"open (?:confirm|dialog|offer|plan)|choose plan|"
                                     r"(?:확인|대화 ?상자|제안|요금제).*(?:창|열기|보기|선택)|요금제 ?선택",
                                     control["name"] or "", re.I):
                            driver.act({"kind": "click", "target": control["id"]})
                            break
                for dialog in dialogs(driver):
                    value, basis, flow = purpose(dialog["text"], session.plan)
                    choices = driver.page.evaluate(OPTIONS, dialog["id"])
                    options = [_option(driver, item, value) for item in choices]
                    for opener in (item for item in choices if _kind(item["label"], item["type"], value) == "customize"):
                        if session.meta["backend"] != "stub":
                            partial.append("layer-two choices not opened on local-dev backend")
                            continue
                        driver.act({"kind": "click", "target": opener["id"]})
                        for nested in driver.page.evaluate(OPTIONS, dialog["id"]):
                            if nested["id"] == opener["id"] or nested["id"] in {item["id"] for item in choices}:
                                continue
                            options.append(_option(driver, nested, value, layer=2, interactions=2))
                        break
                    if not options:
                        continue
                    # An optional unchecked add-on is already declined without interaction.
                    if value == "add-on" and any(item["type"] == "checkbox" and not item["checked"] for item in choices):
                        options.append({"kind": "decline", "control": "checkbox", "layer": 1, "interactions": 0})
                    identity = (ctx_id, dialog["id"], value)
                    if identity in found:
                        continue
                    found.add(identity)
                    record = {"id": f"c{len(session.probes.get('choices', [])) + 1}", "context": ctx_id,
                              "container": dialog["id"], "path": route(driver), "purpose": value,
                              "purpose_basis": basis, "options": options}
                    session.add_probe("choices", record)
                    count += 1
                    if session.meta["backend"] == "stub":
                        closing = next((opt for opt in options if opt["kind"] in ("decline", "dismiss")
                                        and opt.get("box") and opt["interactions"] > 0), None)
                        if closing is None and value == "confirm":
                            closing = next((opt for opt in options if re.search(rf"{CANCEL}|{CLOSE}", opt.get("label", ""), re.I)), None)
                        if closing:
                            driver.act({"kind": "click", "target": closing["box"]})
            for target in links:
                driver.act({"kind": "navigate", "path": target})
                driver.boxes()
                for group in driver.page.evaluate(GROUPS):
                    value = "plan" if re.search(r"plan|요금제", group["text"], re.I) else "add-on"
                    options = [_option(driver, item, value) for item in driver.page.evaluate(OPTIONS, group["id"])]
                    if value == "add-on" and any(opt["control"] == "checkbox" and not opt.get("preselected") for opt in options):
                        options.append({"kind": "decline", "control": "checkbox", "layer": 1, "interactions": 0})
                    if not options or (ctx_id, group["id"], value) in found:
                        continue
                    found.add((ctx_id, group["id"], value))
                    session.add_probe("choices", {"id": f"c{len(session.probes.get('choices', [])) + 1}",
                        "context": ctx_id, "container": group["id"], "path": route(driver),
                        "purpose": value, "purpose_basis": "text", "options": options})
                    count += 1
        finally:
            driver.close()
    session.cover("choices", "partial" if partial else "ran" if count else "not-applicable",
                  contexts=list(session.matrix), reason="; ".join(set(partial)) if partial else None)

