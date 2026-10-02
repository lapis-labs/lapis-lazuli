"""Observe requests that interrupt the page across routes and controlled time."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from lapis_design.behavior_check.probes._decision import (
    CANCEL, CLOSE, CUSTOMIZE, DISMISS, advance, dialogs, purpose, reopen_with, response, route)
from lapis_design.behavior_check.probes.permissions import INIT as DENY_DEVICES

NAMES = ("dialogs",)


def _focus(driver, dialog, trigger, trigger_box, try_escape):
    box = dialog["id"]
    el = driver.locate(box)
    result = {"moved_in": bool(dialog["focus"]), "background_inert": dialog["background_inert"]}
    if dialog["focus"]:
        result["initial"] = dialog["focus"]
    result["close_control"] = any(re.search(rf"{CLOSE}|{CANCEL}|{DISMISS}", c["text"], re.I)
                                  for c in dialog["controls"])
    if dialog["blocks"]:
        focusable = el.locator('button,a[href],input,select,textarea,[tabindex]:not([tabindex="-1"])').count()
        contained = True
        for key in ("Tab", "Shift+Tab"):
            for _ in range(min(focusable + 2, 20)):
                driver.page.keyboard.press(key)
                # A native modal lets Tab cycle through the browser UI (activeElement is the body);
                # only focus landing on page content outside the dialog breaks containment.
                contained &= el.evaluate("""el => el.contains(document.activeElement) ||
                    !document.activeElement || document.activeElement === document.body""")
        result["contained"] = contained
    if not try_escape:
        return result
    driver.page.keyboard.press("Escape")
    result["escape_closes"] = not any(d["id"] == box for d in dialogs(driver))
    if result["escape_closes"] and trigger == "control":
        focused = driver.page.evaluate("document.activeElement?.closest('[data-lapis-box]')?.getAttribute('data-lapis-box') || null")
        invoker_present = driver.page.locator(f'[data-lapis-box="{trigger_box}"]').count() > 0
        result["returns_to"] = ("invoker" if focused == trigger_box else "body" if not focused
                                else "other" if invoker_present else "logical")
    return result


def _routes(driver, session):
    path = urlsplit(session.source["url"]).path or "/"
    links = driver.page.evaluate("""() => [...document.querySelectorAll('a[href]')].map(a => {
      try {const u=new URL(a.href);return u.origin===location.origin?u.pathname:null} catch(_) {return null}
    }).filter(Boolean)""")
    planned = [flow.get("start") for flow in (session.plan or {}).get("flows", [])]
    return list(dict.fromkeys(p for p in [*planned, *links] if p and p != path))[:2]


def run(session, open_driver):
    seen = 0
    limited = []
    for ctx_id in session.matrix:
        driver = open_driver(ctx_id)
        observations = {}
        order = []
        try:
            reopen_with(driver, DENY_DEVICES)
            paths = _routes(driver, session)
            origin = urlsplit(session.source["url"]).path or "/"

            def observe(trigger, preceded, *, trigger_box=None, after=None, scroll_share=None):
                nonlocal seen
                for dialog in dialogs(driver):
                    value, basis, flow = purpose(dialog["text"] + " " + " ".join(c["text"] for c in dialog["controls"]), session.plan)
                    key = dialog["id"], value
                    current = route(driver)
                    appeared_at = driver.t_ms()
                    if key not in observations:
                        entry = {"box": dialog["id"], "context": ctx_id, "kind": dialog["kind"],
                                 "trigger": trigger, "path": current, "blocks_content": dialog["blocks"],
                                 "area_share": round(dialog["area"], 4), "purpose": value,
                                 "purpose_basis": basis, "appearances": [],
                                 "dont_show_again": {"offered": dialog["again_offered"]}}
                        if dialog["again"] is not None:
                            entry["dont_show_again"]["days"] = int(dialog["again"])
                        if trigger_box:
                            entry["trigger_box"] = trigger_box
                        if trigger in ("timer", "idle") and after is not None:
                            entry["trigger_after_ms"] = after
                        if trigger == "scroll" and scroll_share is not None:
                            entry["trigger_scroll_share"] = round(min(1, scroll_share), 3)
                        observations[key] = entry
                        order.append(key)
                        seen += 1
                        # Escape would consume the driver's answer, so it is tried only where the
                        # dialog can be reopened (control trigger) or where dismissal is the answer anyway.
                        try_escape = trigger == "control" or (
                            response(dialog["controls"], dialog["exit_question"])[0] in ("dismiss", "none") and not any(
                                re.search(CUSTOMIZE, item["text"], re.I)
                                for item in dialog["controls"]))
                        entry["focus"] = _focus(driver, dialog, trigger, trigger_box, try_escape)
                        if entry["focus"].get("escape_closes"):
                            if trigger_box:
                                driver.act({"kind": "click", "target": trigger_box})
                            else:
                                entry["appearances"].append({"preceded_by": preceded, "response": "dismiss",
                                                             "path": current, "t_ms": appeared_at})
                                continue
                    entry = observations[key]
                    if entry["appearances"] and entry["appearances"][-1]["response"] == "none" and (
                            entry["appearances"][-1]["path"] == current):
                        continue
                    answer, control = response(dialog["controls"], dialog["exit_question"])
                    if answer == "none" and session.meta["backend"] == "stub":
                        customize = next((item for item in dialog["controls"]
                                          if re.search(CUSTOMIZE, item["text"], re.I)), None)
                        if customize and customize["id"]:
                            driver.act({"kind": "click", "target": customize["id"]})
                            expanded = next((candidate for candidate in dialogs(driver)
                                             if candidate["id"] == dialog["id"]), None)
                            if expanded:
                                answer, control = response(expanded["controls"], expanded["exit_question"])
                    if session.meta["backend"] == "stub" and control:
                        driver.act({"kind": "click", "target": control["id"]})
                    else:
                        answer = "none"
                        if session.meta["backend"] != "stub":
                            limited.append("cannot answer decisions on local-dev backend")
                    entry["appearances"].append({"preceded_by": preceded, "response": answer,
                                                 "path": current, "t_ms": appeared_at})

            observe("load", "none")
            advance(driver, 5500)
            observe("timer", "none", after=5500)
            driver.act({"kind": "scroll"})
            scroll_share = driver.page.evaluate("scrollY / Math.max(document.documentElement.scrollHeight, 1)")
            observe("scroll", "scroll", scroll_share=scroll_share)
            driver.act({"kind": "pointer-leave"})
            observe("exit-intent", "none")
            if session.meta["backend"] != "stub":
                limited.append("control-triggered dialogs not exercised on local-dev backend")
            for box in driver.interactive() if session.meta["backend"] == "stub" else ():
                if not re.search(r"confirm|settings|preferences|manage|dialog|offer|"
                                 r"enable (?:notifications|location|camera|microphone)|"
                                 r"allow notifications|request (?:notification|location) permission|"
                                 r"확인|설정|관리|대화 ?상자|제안|(?:알림|위치|카메라|마이크) ?권한|"
                                 r"알림(?:을)? ?(?:켜|허용)|(?:알림|위치|카메라|마이크).*허용",
                                 box["name"] or "", re.I):
                    continue
                if not driver.locate(box["id"]).is_visible():
                    continue
                try:
                    driver.act({"kind": "click", "target": box["id"]})
                    observe("control", "control", trigger_box=box["id"])
                except Exception:
                    limited.append(f"control {box['id']} could not open")
            advance(driver, 30000)
            observe("idle", "idle", after=35500)
            for target in paths:
                driver.act({"kind": "navigate", "path": target})
                observe("navigation", "navigation")
            driver.act({"kind": "navigate", "path": origin})
            observe("navigation", "navigation")
            driver.act({"kind": "reload"})
            observe("navigation", "reload")
            advance(driver, 60000)
            observe("idle", "idle", after=60000)
            for key in order:
                session.add_probe("dialogs", observations[key])
        finally:
            driver.close()
    session.cover("dialogs", "partial" if limited else "ran" if seen else "not-applicable",
                  contexts=list(session.matrix), reason="; ".join(dict.fromkeys(limited)) if limited else None)
