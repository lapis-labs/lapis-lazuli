"""Pointer movement and hover-reveal observations on fresh context pages."""
from __future__ import annotations

from playwright.sync_api import Error as PlaywrightError

from lapis_design.behavior_check.probes.motion import base_contexts

NAMES = ("pointer",)


# One DOM read per hover state; reveal candidates are visible nodes rather than
# mutations, because a tooltip may be present but hidden in the original DOM.
VISIBLE = """() => [...document.querySelectorAll('[data-lapis-box]')].filter(el => {
  const s=getComputedStyle(el),r=el.getBoundingClientRect();
  return r.width>0 && r.height>0 && s.visibility!=='hidden' &&
    s.display!=='none' && Number(s.opacity)>.03 && !el.closest('[hidden],[inert]');
}).map(el=>el.getAttribute('data-lapis-box'))"""

CANDIDATES = r"""() => [...document.querySelectorAll('[data-lapis-box]')].filter(el => {
  const s=getComputedStyle(el), role=el.getAttribute('role')||'';
  return el.matches('[draggable=true],input[type=range],[aria-roledescription*=sort i]') ||
    ['slider','spinbutton'].includes(role) || /\b(grab|grabbing|move|ew-resize|ns-resize)\b/.test(s.cursor) ||
    (s.touchAction==='none' && (el.hasAttribute('tabindex') || el.hasAttribute('aria-label') || el.matches('canvas')));
}).map(el=>({id:el.getAttribute('data-lapis-box'),role:el.getAttribute('role'),
  type:el.getAttribute('type'),tag:el.localName,drag:el.draggable,
  touch:getComputedStyle(el).touchAction,
  cursor:getComputedStyle(el).cursor,
  keys:el.getAttribute('aria-keyshortcuts')||''}))"""

STATE = """id => {const el=document.querySelector('[data-lapis-box="'+id+'"]');
  if (!el) return null;
  const group=el.closest('[role=list],ul,ol,[role=group]')||el;
  return [group.innerText,el.value,el.getAttribute('aria-valuenow'),
    el.getAttribute('aria-valuetext'),el.getAttribute('aria-pressed'),
    [...group.children].map(child=>child.getAttribute('data-lapis-box')||child.textContent).join('|')];
}"""


def _alternative(driver, item):
    """Identify controls *in the same widget*, not unrelated page buttons."""
    return driver.page.evaluate(r"""id => {
      const el=document.querySelector('[data-lapis-box="'+id+'"]');
      if(!el) return 'none';
      const group=el.closest('section,[role=group]')||el.parentElement;
      const others=[...group.querySelectorAll('button,[role=button],[role=menuitem],select,input')]
        .filter(x=>x!==el && !x.disabled && x.getBoundingClientRect().width);
      if(others.some(x=>/\b(move up|move down|reorder|previous|next|increase|decrease|increment|decrement)\b/i.test(
        (x.getAttribute('aria-label')||'')+' '+x.textContent))) return 'buttons';
      if(others.some(x=>x.matches('select,[role=menuitem]') ||
        /\b(menu|options|actions)\b/i.test(x.getAttribute('aria-label')||x.textContent))) return 'menu';
      if(others.some(x=>x.matches('input:not([type=range])'))) return 'input';
      return el.matches('input[type=range],[role=slider]') || el.tabIndex>=0 ||
        el.hasAttribute('aria-keyshortcuts') ? 'keyboard-only' : 'none';
    }""", item["id"])


def _drag(driver, box):
    el = driver.page.locator(f'[data-lapis-box="{box["id"]}"]').first
    el.scroll_into_view_if_needed()
    before = driver.page.evaluate(STATE, box["id"])
    bounds = el.bounding_box()
    if not bounds:
        return False
    x, y = bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2
    if box["tag"] == "input" and box["type"] == "range":
        end_x, end_y = bounds["x"] + bounds["width"] * .85, y
    else:
        end_x, end_y = x, y + max(bounds["height"] * 1.4, 55)
    driver.page.mouse.move(x, y)
    driver.page.mouse.down()
    driver.page.mouse.move(end_x, end_y, steps=10)
    driver.page.mouse.up()
    return before != driver.page.evaluate(STATE, box["id"])



def _touch_gesture(driver, item, fingers):
    el = driver.page.locator(f'[data-lapis-box="{item["id"]}"]').first
    el.scroll_into_view_if_needed()
    before = driver.page.evaluate(STATE, item["id"])
    rect = el.bounding_box()
    if not rect:
        return False
    x, y = rect["x"]+rect["width"]/2, rect["y"]+rect["height"]/2
    cdp = driver.cdp
    if fingers == 1:
        start = [{"x":x-rect["width"]*.3,"y":y}]
    else:
        start = [{"x":x-rect["width"]*.12,"y":y},{"x":x+rect["width"]*.12,"y":y}]
    cdp.send("Input.dispatchTouchEvent", {"type":"touchStart","touchPoints":start})
    for step in range(1,7):
        points = ([{"x":start[0]["x"]+rect["width"]*.5*step/6,"y":y}]
                  if fingers == 1 else [
                      {"x":start[0]["x"]-rect["width"]*.22*step/6,"y":y},
                      {"x":start[1]["x"]+rect["width"]*.22*step/6,"y":y}])
        cdp.send("Input.dispatchTouchEvent", {"type":"touchMove","touchPoints":points})
    cdp.send("Input.dispatchTouchEvent", {"type":"touchEnd","touchPoints":[]})
    return before != driver.page.evaluate(STATE, item["id"])

def _obscures(driver, ids):
    return driver.page.evaluate("""ids => ids.some(id => {
      const el=document.querySelector('[data-lapis-box="'+id+'"]');
      if(!el)return false;
      const r=el.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;
      if(x<0||y<0||x>=innerWidth||y>=innerHeight)return false;
      const stack=document.elementsFromPoint(x,y),position=stack.indexOf(el);
      return stack.slice(position+1).some(other => !el.contains(other) &&
        !other.contains(el) && other.matches('p,button,a,input,section,li,article,[data-lapis-box]'));
    })""", ids)


def run(session, open_driver):
    found = False
    partial = []
    contexts = base_contexts(session)
    for ctx_id in contexts:
        driver = open_driver(ctx_id)
        try:
            boxes = {box["id"]: box for box in driver.boxes()}
            candidates = driver.page.evaluate(CANDIDATES)
            for candidate in candidates:
                box = boxes.get(candidate["id"])
                if not box:
                    continue
                if session.meta["backend"] != "stub" and box["tag"] != "input" and candidate["role"] != "slider":
                    partial.append(f"{ctx_id}: drag on potentially state-changing widget omitted on local-dev")
                    continue
                changed = True
                try:
                    changed = _drag(driver, candidate)
                    if changed:
                        session.add_probe("pointer", {"box": box["id"], "context": ctx_id,
                            "kind": "drag", "alternative": _alternative(driver, candidate)})
                        found = True
                except PlaywrightError:
                    partial.append(f"{ctx_id}: drag could not be performed on {box['id']}")
                if changed:
                    driver.reload()
                if driver.ctx["pointer"] == "coarse" and candidate["touch"] == "none" and not candidate["drag"] and candidate["type"] != "range":
                    for kind, fingers in (("path-gesture",1),("multipoint",2)):
                        changed = True
                        try:
                            changed = _touch_gesture(driver, candidate, fingers)
                            if changed:
                                session.add_probe("pointer", {"box": box["id"], "context": ctx_id,
                                    "kind": kind, "alternative": _alternative(driver, candidate)})
                                found = True
                        except PlaywrightError:
                            partial.append(f"{ctx_id}: {kind} could not be performed on {box['id']}")
                        if changed:
                            driver.reload()
            if driver.ctx["pointer"] == "coarse":
                # Hover does not exist in a coarse pointer context.
                continue
            for box in driver.interactive():
                bid = box["id"]
                try:
                    driver.page.mouse.move(0, -1)
                    before = set(driver.page.evaluate(VISIBLE))
                    driver.locate(bid).hover(timeout=2000)
                    driver.page.wait_for_timeout(100)
                    driver.boxes()  # register dynamically revealed boxes before recording their ids
                    revealed = list(set(driver.page.evaluate(VISIBLE)) - before)
                    if not revealed:
                        continue
                    found = True
                    driver.page.mouse.move(0, -1)
                    driver.locate(bid).focus()
                    driver.page.wait_for_timeout(100)
                    on_focus = any(x in driver.page.evaluate(VISIBLE) for x in revealed)
                    driver.locate(bid).hover()
                    driver.page.keyboard.press("Escape")
                    driver.page.wait_for_timeout(60)
                    dismissible = not any(x in driver.page.evaluate(VISIBLE) for x in revealed)
                    driver.page.mouse.move(0, -1)
                    driver.locate(bid).hover()
                    target = driver.page.locator(f'[data-lapis-box="{revealed[0]}"]')
                    if target.is_visible():
                        r = target.bounding_box()
                        if r:
                            driver.page.mouse.move(r["x"]+r["width"]/2, r["y"]+r["height"]/2)
                    hoverable = any(x in driver.page.evaluate(VISIBLE) for x in revealed)
                    driver.locate(bid).hover()
                    driver.advance_clock(5000)
                    persistent = any(x in driver.page.evaluate(VISIBLE) for x in revealed)
                    session.add_probe("pointer", {"box": bid, "context": ctx_id,
                        "kind": "hover-reveal", "revealed": revealed,
                        "on_focus_too": on_focus, "obscures": _obscures(driver, revealed),
                        "dismissible": dismissible, "hoverable": hoverable, "persistent": persistent})
                    driver.reload()
                except PlaywrightError:
                    partial.append(f"{ctx_id}: hover/focus measurement unavailable for {bid}")
                    driver.reload()
        finally:
            driver.close()
    reasons = list(dict.fromkeys(partial))
    session.cover("pointer", "partial" if reasons else "ran" if found else "not-applicable",
                  contexts=contexts, reason="; ".join(reasons) if reasons else None)
