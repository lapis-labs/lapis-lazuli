"""Pointer and keyboard observations of visible interactive boxes."""
from __future__ import annotations

import re
from collections import deque
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError

from lapis_design.behavior_check.driver import ACTION_TIMEOUT_MS

NAMES = ("controls",)

_DESTRUCTIVE = re.compile(r"\b(delete|remove|unsubscribe|cancel subscription|leave|erase|destroy)\b|"
                          r"삭제|제거|지우|구독 ?취소|예약 ?취소|해지|탈퇴|떠나|파기|폐기", re.I)
_COMMIT_LABEL = re.compile(r"\b(reserve|book|buy|pay|purchase|checkout|subscribe|submit|save|send|publish|confirm)\b|"
                           r"예약|구매|구입|결제|지불|구독|신청|제출|저장|전송|발송|보내|게시|발행|확인", re.I)


def promise(driver, box: dict) -> str:
    """Infer the affordance before observing its effect (not from the result)."""
    data = element(driver, box["id"]).evaluate("""el => ({
      tag:el.localName, type:el.type||el.getAttribute('type'), explicitType:el.getAttribute('type'),
      inForm:!!el.form, href:el.getAttribute('href'),
      download:el.hasAttribute('download'), expanded:el.hasAttribute('aria-expanded'),
      pressed:el.hasAttribute('aria-pressed'), role:el.getAttribute('role')||'',
      dialog:el.getAttribute('aria-haspopup'), icon:el.querySelector('svg use')?.getAttribute('href')||
        el.querySelector('svg title')?.textContent||el.getAttribute('data-icon')||''
    })""")
    label = f"{box.get('name') or ''} {data['icon']}"
    if _DESTRUCTIVE.search(label):
        return "destructive"
    if data["download"]:
        return "download"
    if data["explicitType"] == "submit" or data["inForm"] and data["type"] == "submit":
        return "submit"
    if data["pressed"] or data["role"] in ("switch", "checkbox"):
        return "toggle"
    if data["expanded"] or re.search(r"\b(expand|collapse|disclose)\b|펼치|접기|접어|더 ?보기", label, re.I):
        return "expand"
    if data["role"] in ("tab", "option", "radio"):
        return "select"
    if data["dialog"] == "dialog" or re.search(r"\b(open|show|details|dialog)\b|열기|보여 ?주|자세히|대화 ?상자", label, re.I):
        return "open"
    if re.search(r"\b(play|pause)\b|재생|일시 ?정지", label, re.I):
        return "play"
    if data["tag"] == "a" or data["role"] == "link":
        return "navigate"
    return "other"


def fresh(driver, path=None):
    """Reload with backend and storage reset, keeping the context's browser profile."""
    if driver.session.engine is not None:
        driver.session.engine.reset()
    if driver.context is not None and driver.page is not None:
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(driver.session.source["url"]))
        driver.cdp.send("Storage.clearDataForOrigin", {"origin": origin, "storageTypes": "all"})
        driver.context.clear_cookies()
        driver.context.clear_permissions()
    driver.open(path or urlsplit(driver.session.source["url"]).path or "/", storage="persisted")
    # A control that is not there fails in seconds, not after Playwright's 30 s default.
    driver.page.set_default_timeout(ACTION_TIMEOUT_MS)
    driver._box_alias = {}


def element(driver, box_id):
    """Locate a box by the id the last snapshot stamped; snapshot again only for unstamped elements.
    A recorded id whose element was found again under another id (see commits) resolves to it."""
    box_id = getattr(driver, "_box_alias", {}).get(box_id, box_id)
    locator = driver.page.locator(f'[data-lapis-box="{box_id}"]').first
    return locator if locator.count() else driver.locate(box_id)


def _box_count(driver):
    return driver.page.evaluate("document.querySelectorAll('[data-lapis-box]').length")


def replay(driver, path):
    """Reach a control created by preceding interactions from an isolated load."""
    for target in path:
        driver.act({"kind": "tap" if driver.ctx["pointer"] == "coarse" else "click", "target": target})


def _tab_focus(driver, box_id, count):
    for _ in range(count + 2):
        driver.page.keyboard.press("Tab")
        if driver.page.evaluate("document.activeElement?.closest('[data-lapis-box]')?.getAttribute('data-lapis-box')") == box_id:
            return True
    return False


def _keyboard(driver, box, path, pointer_effect):
    fresh(driver)
    replay(driver, path)
    reachable = _tab_focus(driver, box["id"], _box_count(driver))
    if not reachable:
        try:
            element(driver, box["id"]).focus()
        except Exception:
            return {"focusable": False, "activation": "not-tried"}
    focused = driver.page.evaluate("document.activeElement?.closest('[data-lapis-box]')?.getAttribute('data-lapis-box')") == box["id"]
    if not focused:
        return {"focusable": reachable, "activation": "not-tried"}
    results = []
    native = box["tag"] in ("button",) or element(driver, box["id"]).evaluate(
        "el => el.localName==='input' && ['button','submit','reset'].includes(el.type)")
    # Checkboxes and radios activate with Space only; buttons and switches with Enter and Space
    keys = element(driver, box["id"]).evaluate(
        "el => ['checkbox','radio'].includes(el.getAttribute('role')) || el.localName==='input' && "
        "['checkbox','radio'].includes(el.type) ? ['Space'] : ['button','switch'].includes(el.getAttribute('role')) "
        "|| el.localName==='button' || el.localName==='input' && ['button','submit','reset'].includes(el.type) "
        "? ['Enter','Space'] : ['Enter']")
    if box["role"] == "button" and keys == ["Enter"]:
        keys = ["Enter", "Space"]
    for key in keys:
        if results:
            # Native buttons activate on Space exactly as on Enter unless a key handler intervenes,
            # which the Enter run would already show as a difference.
            if native and results == ["same"]:
                break
            fresh(driver)
            replay(driver, path)
            if not _tab_focus(driver, box["id"], _box_count(driver)):
                element(driver, box["id"]).focus()
        effect = driver.act({"kind": "key", "key": key, "target": box["id"]})
        if effect["outcome"] == "no-effect" and pointer_effect["outcome"] != "no-effect":
            results.append("none")
        elif (effect["outcome"] == pointer_effect["outcome"] and
              ({*effect["text_changed"], *(entry["box"] for entry in effect["aria_changes"])} ==
               {*pointer_effect["text_changed"], *(entry["box"] for entry in pointer_effect["aria_changes"])})):
            results.append("same")
        else:
            results.append("different")
    # Enter and Space must each reproduce the pointer effect; keep the worse reading.
    return {"focusable": reachable, "activation": "different" if "different" in results else
            "none" if "none" in results else "same"}


def run(session, open_driver):
    session._control_commit_requests = set()
    session._control_paths = {}
    statuses = []
    total_ran = total_skipped = 0
    empty_contexts = []
    for ctx_id in session.matrix:
        if session.engine is not None:
            session.engine.reset()
        driver = open_driver(ctx_id)
        try:
            queue = deque((box["id"], ()) for box in driver.interactive())
            seen = set()
            ran = 0
            skipped = []
            first = True
            while queue:
                box_id, path = queue.popleft()
                if box_id in seen:
                    continue
                if len(path) > 3:
                    skipped.append(f"{box_id}: requires more than three preceding actions")
                    continue
                seen.add(box_id)
                label = box_id
                try:
                    if first:
                        first = False
                    else:
                        fresh(driver)
                    replay(driver, path)
                    box = next((item for item in driver.interactive() if item["id"] == box_id), None)
                    if box is None:
                        skipped.append(f"{box_id}: not visible after replaying prerequisite actions")
                        continue
                    label = box.get("name") or box_id
                    session._control_paths[(ctx_id, box_id)] = path
                    expected = promise(driver, box)
                    restricted = session.meta["backend"] == "local-dev" and session.meta.get("outbound") != "none"
                    if expected == "destructive" and session.meta["backend"] != "stub":
                        skipped.append(f"{box.get('name') or box_id}: destructive action requires stub")
                        continue
                    if restricted and (expected == "submit" or _COMMIT_LABEL.search(box.get("name") or "")):
                        skipped.append(f"{box.get('name') or box_id}: possible commit requires outbound none")
                        continue
                    action = {"kind": "tap" if driver.ctx["pointer"] == "coarse" else "click", "target": box_id}
                    before_effects = session.engine.effects_total if session.engine else None
                    effect = driver.act(action)
                    if (before_effects is not None and session.engine.effects_total > before_effects and
                            any(req["method"] in ("POST", "PUT", "PATCH", "DELETE")
                                for req in effect.get("requests", ()))):
                        session._control_commit_requests.add((ctx_id, box_id))
                    for child in driver.interactive():
                        if child["id"] not in seen and all(child["id"] != queued for queued, _ in queue):
                            queue.append((child["id"], (*path, box_id)))
                    keyboard = _keyboard(driver, box, path, effect)
                    session.add_probe("controls", {"box": box_id, "context": ctx_id,
                        "promise": expected, "action": action,
                        "effect": {key: value for key, value in effect.items() if key != "outcome"},
                        "keyboard": keyboard})
                    ran += 1
                except PlaywrightError as exc:
                    # One control that cannot be acted on is a gap in the probe, never the end of it.
                    skipped.append(f"{label}: {driver.reason(exc)}")
            if skipped:
                statuses.extend(f"{ctx_id}: {reason}" for reason in skipped)
            if not ran and not skipped:
                empty_contexts.append(ctx_id)
            total_ran += ran
            total_skipped += len(skipped)
        finally:
            driver.close()
    status = ("partial" if total_skipped or (total_ran and empty_contexts) else
              "ran" if total_ran else "not-applicable")
    reasons = statuses + [f"{ctx_id}: no interactive controls" for ctx_id in empty_contexts]
    session.cover("controls", status, contexts=list(session.matrix), reason="; ".join(reasons) if status == "partial" else None)
