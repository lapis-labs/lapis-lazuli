"""Compare three native scroll inputs with their default browser distances."""
from __future__ import annotations

from time import monotonic, sleep

from lapis_design.behavior_check.probes.motion import base_contexts

NAMES = ("scroll",)


def _y(page):
    return page.evaluate("scrollY")


def _rest(page, *, limit=1800):
    """Observe scroll continuation after input without synthesizing another input."""
    started=monotonic()
    prev=_y(page)
    last_change=started
    while (monotonic()-started)*1000<limit:
        sleep(.04)
        now=_y(page)
        if abs(now-prev)>.5:
            last_change=monotonic()
        elif (monotonic()-last_change)>.16:
            break
        prev=now
    return round(max(0,(last_change-started)*1000),2)


def _touch(page):
    width=page.viewport_size["width"]
    x=width-8  # avoid touch-action:none widgets in the page's content column
    height=page.viewport_size["height"]
    top=int(height*.68)
    cdp=page.context.new_cdp_session(page)
    cdp.send("Input.dispatchTouchEvent", {
        "type":"touchStart", "touchPoints":[{"x":x,"y":top}]})
    for step in range(1,7):
        cdp.send("Input.dispatchTouchEvent", {"type":"touchMove", "touchPoints":[
            {"x":x,"y":top-step*35}]})
        sleep(.025)
    cdp.send("Input.dispatchTouchEvent", {"type":"touchEnd", "touchPoints":[]})


def _input(page, kind):
    if kind=="wheel": page.mouse.wheel(0,100)
    elif kind=="space": page.keyboard.press("Space")
    elif kind=="arrow": page.keyboard.press("ArrowDown")
    else: _touch(page)


def _baseline(driver, kind):
    """Calibrate native scrolling in the same viewport/browser without app handlers."""
    page=driver.context.new_page()
    try:
        page.set_content('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;height:20000px"></body></html>')
        page.mouse.move(driver.ctx["width"]//2,driver.ctx["height"]//2)
        for _ in range(3):
            _input(page,kind)
            _rest(page,limit=650 if kind!="touch" else 1300)
        return round(_y(page),2)
    finally:
        page.close()


def _snapped(page, start, expected, actual):
    return page.evaluate("""({start,expected,actual}) => {
      const root=document.scrollingElement;
      const snap=getComputedStyle(root).scrollSnapType;
      const sections=[...document.querySelectorAll('main > section,body > section,[data-scroll-section]')]
        .map(el=>el.getBoundingClientRect().top+scrollY);
      return (snap!=='none' || sections.length>=2) &&
        sections.some(y=>Math.abs(y-(start+actual))<=3) && Math.abs(expected-actual)>5;
    }""", {"start":start,"expected":expected,"actual":actual})


def run(session, open_driver):
    contexts=base_contexts(session)
    partial=[]
    recorded=0
    for ctx_id in contexts:
        driver=open_driver(ctx_id)
        try:
            inputs=("wheel","space","arrow")+(("touch",) if driver.ctx["pointer"]=="coarse" else ())
            for kind in inputs:
                try:
                    expected=_baseline(driver,kind)
                    driver.reload()
                    page=driver.page
                    if page.evaluate("""() => [...document.querySelectorAll('dialog[open],[role=dialog],[aria-modal=true]')]
                      .some(el=>el.getBoundingClientRect().width>0 && getComputedStyle(el).visibility!=='hidden')"""):
                        partial.append(f"{ctx_id}/{kind}: modal dialog open; scroll input not attempted")
                        continue
                    available=page.evaluate("document.scrollingElement.scrollHeight-innerHeight-scrollY")
                    if not expected or available < expected*3:
                        partial.append(f"{ctx_id}/{kind}: need {expected*3:.0f}px remaining, have {available:.0f}px")
                        continue
                    page.mouse.move(driver.ctx["width"]//2,driver.ctx["height"]//2)
                    start=_y(page)
                    for index in range(3):
                        _input(page,kind)
                        if index<2: _rest(page)
                    duration=_rest(page)
                    actual=round(max(0,_y(page)-start),2)
                    session.add_probe("scroll",{"context":ctx_id,"input":kind,
                        "expected_px":expected,"actual_px":actual,
                        "snapped":_snapped(page,start,expected,actual),
                        "blocked":actual<1,
                        "animated_ms":duration})
                    recorded+=1
                except Exception as error:
                    partial.append(f"{ctx_id}/{kind}: {type(error).__name__} measuring scroll")
        finally:
            driver.close()
    session.cover("scroll","partial" if partial else "ran" if recorded else "not-applicable",
                  contexts=contexts,reason="; ".join(partial) if partial else None)
