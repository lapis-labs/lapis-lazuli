"""Five-second motion windows, automatic motion, and reveal observations.

`essential` (motion that conveys the content itself) is decided per moving box:
- video: never in the at-rest window, because the driver made no gesture there, so any
  playback is autoplay (a background video is not essential);
- canvas: only when presented as content and not decorative. Decorative: aria-hidden on it or
  an ancestor, or another element painted over its centre. Content: inside a `figure`; or
  role img, figure, or application with an accessible name; or an accessible name
  (aria-label, aria-labelledby, title) naming a chart, graph, map, or visualization
  (English or Korean terms);
- everything else: not essential.
"""
from __future__ import annotations

from time import monotonic, sleep

import numpy as np
from lapis_design.render.ids import DOM_PATH_JS, box_id

NAMES = ("motion",)

FRAME = """() => {
  const active=[...document.getAnimations()].filter(a=>a.playState==='running');
  const byId={};
  for(const animation of active){
    const el=animation.effect?.target?.closest?.('[data-lapis-box]');
    const id=el?.getAttribute('data-lapis-box');
    if(!id)continue;
    const frames=animation.effect?.getKeyframes?.()||[];
    const keys=frames.flatMap(frame=>Object.keys(frame)).join(' ');
    const record=byId[id] ||= {properties:'',infinite:false};
    record.properties+=' '+keys;
    record.infinite ||= animation.effect?.getTiming?.().iterations===Infinity;
  }
  const CONTENT=/\\b(chart|graph|plot|map|visuali[sz]ation|diagram)s?\\b|차트|그래프|지도|시각화|도표/i;
  function contentCanvas(el){
    if(el.closest('[aria-hidden=true]'))return false;
    const r=el.getBoundingClientRect(),cx=r.x+r.width/2,cy=r.y+r.height/2;
    if(cx>=0&&cy>=0&&cx<innerWidth&&cy<innerHeight){
      const top=document.elementFromPoint(cx,cy);
      if(top&&top!==el&&!el.contains(top))return false;
    }
    const labelled=(el.getAttribute('aria-labelledby')||'').split(/\\s+/).filter(Boolean)
      .map(id=>document.getElementById(id)?.textContent||'').join(' ');
    const name=((el.getAttribute('aria-label')||'')+' '+labelled+' '+(el.getAttribute('title')||'')).trim();
    if(el.closest('figure'))return true;
    if(['img','figure','application'].includes(el.getAttribute('role')||'')&&name)return true;
    return CONTENT.test(name);
  }
  const samples={};
  for(const el of document.querySelectorAll('[data-lapis-box]')){
    const id=el.getAttribute('data-lapis-box'),r=el.getBoundingClientRect(),s=getComputedStyle(el);
    if(r.width<=0||r.height<=0||s.visibility==='hidden'||s.display==='none')continue;
    samples[id]={x:r.x,y:r.y,w:r.width,h:r.height,opacity:Number(s.opacity),
      transform:s.transform,animation:byId[id]||null,tag:el.localName,
      essential:el.localName==='canvas' && contentCanvas(el),
      scrollLinked:!!(byId[id]&&[...active].some(a=>
        a.effect?.target?.closest?.('[data-lapis-box]')===el && a.timeline &&
        a.timeline!==document.timeline))};
  }
  return samples;
}"""

HIDDEN = r"""() => {
  /* dom path */
  return [...document.querySelectorAll('*')].filter(el=>{
    const r=el.getBoundingClientRect(),s=getComputedStyle(el);
    return r.width>0 && r.height>0 && r.top>=innerHeight &&
      (Number(s.opacity)<.05 || /^inset\(50%|^inset\(100%/.test(s.clipPath) ||
        s.visibility==='hidden');
  }).map((el,index)=>{
    el.setAttribute('data-lapis-hidden-index',String(index));
    const r=el.getBoundingClientRect();
    return {index,steps:path(el),tag:el.localName,
      rect:{x:r.x+scrollX,y:r.y+scrollY,w:r.width,h:r.height}};
  });
}""".replace("/* dom path */", DOM_PATH_JS)


def _frame(driver):
    return driver.page.evaluate(FRAME)


def _tick(driver, ms=100):
    # The core's installed page clock keeps JS timers and the stub on one timeline;
    # a real frame interval is still necessary for CSS animation and screenshot diffs.
    started = monotonic()
    sleep(ms / 1000)
    driver.advance_clock(max(ms, round((monotonic()-started)*1000)))


def _measure(driver, duration_ms=5000):
    first = _frame(driver)
    traces = {bid: [state] for bid, state in first.items()}
    # A small thumbnail keeps 10 fps frame comparisons bounded on long pages.
    previous = np.asarray(driver.screenshot())[::8, ::8, :].copy()
    pixel_changed = set()
    for _ in range(duration_ms // 100):
        _tick(driver)
        current = _frame(driver)
        image = np.asarray(driver.screenshot())[::8, ::8, :]
        for bid, state in current.items():
            traces.setdefault(bid, []).append(state)
            if bid not in first or state["tag"] not in ("canvas", "video", "img"):
                continue
            r = state
            dpr = driver.ctx.get("dpr", 2) / 8
            x0,y0 = max(0,int(r["x"]*dpr)),max(0,int(r["y"]*dpr))
            x1,y1 = min(image.shape[1],int((r["x"]+r["w"])*dpr)),min(image.shape[0],int((r["y"]+r["h"])*dpr))
            if x1>x0 and y1>y0 and image.shape==previous.shape and np.mean(
                    np.abs(image[y0:y1,x0:x1].astype(np.int16)-previous[y0:y1,x0:x1].astype(np.int16)))>4:
                pixel_changed.add(bid)
        previous = image.copy()
    moving=[]
    for bid, states in traces.items():
        animation = next((state["animation"] for state in states if state["animation"]), None)
        initial = states[0]
        changed = any(abs(state["x"]-initial["x"])>.5 or abs(state["y"]-initial["y"])>.5 or
                      state["transform"]!=initial["transform"] or abs(state["opacity"]-initial["opacity"])>.03
                      for state in states[1:])
        if not changed and bid not in pixel_changed:
            continue
        # Do not report every descendant of an animated ancestor as independently moving.
        if not animation and bid not in pixel_changed:
            continue
        keys = animation["properties"].lower() if animation else ""
        if initial["tag"]=="video": kind="video"
        elif initial["tag"]=="canvas": kind="canvas"
        elif any(state["scrollLinked"] for state in states): kind="scroll-linked"
        elif "opacity" in keys or any(abs(state["opacity"]-initial["opacity"])>.03 for state in states): kind="opacity"
        elif "transform" in keys or any(state["transform"]!=initial["transform"] for state in states): kind="transform"
        else: kind="other"
        distance = max(((state["x"]-initial["x"])**2+(state["y"]-initial["y"])**2)**.5
                       for state in states)
        moving.append({"box": bid,"kind":kind,"travel_px":round(distance,2),
                       "infinite":bool(animation and animation["infinite"]),
                       "essential":any(state["essential"] for state in states)})
    return moving


def _auto(driver, moving):
    if not moving:
        return []
    tracks={item["box"]: {"seconds":5., "previous":None} for item in moving}
    # Up to 60 s from load, one sample per second. Script timers and animation frames run on
    # the controlled clock, so a second of page time is advanced directly; CSS animations do
    # not follow that clock, but an infinite one still running cannot stop by itself.
    for elapsed in range(6,61):
        driver.advance_clock(1000)
        sleep(.05)
        current = _frame(driver)
        active=False
        for bid, track in tracks.items():
            state=current.get(bid)
            if state is None: continue
            value=(state["x"],state["y"],state["transform"],state["opacity"])
            previous=track["previous"]
            if state["animation"] and state["animation"]["infinite"]:
                track["seconds"]=float(elapsed)
                active=True
            elif previous is not None and value!=previous:
                track["seconds"]=float(elapsed)
                active=True
            track["previous"]=value
        if not active: break
    return [{"box":bid,"seconds":track["seconds"],
             "pause_control":driver.page.evaluate(r"""id=>{
               const el=document.querySelector('[data-lapis-box="'+id+'"]');
               const group=el?.parentElement;
               const controls=[...(group?.querySelectorAll(':scope > button,:scope > [role=button]')||[]),
                 ...document.querySelectorAll('[aria-controls="'+el?.id+'"]')];
               return controls.some(x=>!x.disabled && x.tabIndex>=0 &&
                 x.getBoundingClientRect().width &&
                 /\b(pause|stop)\b/i.test((x.getAttribute('aria-label')||'')+' '+x.innerText));
             }""",bid)} for bid,track in tracks.items() if track["seconds"]>5 or any(
                item["box"]==bid and item["infinite"] for item in moving)]


def _hover_media(driver):
    ids=driver.page.evaluate("""() => [...document.querySelectorAll('img,video')].filter(el=>{
      const r=el.getBoundingClientRect();return r.width>0&&r.height>0;
    }).map(el=>el.getAttribute('data-lapis-box')).filter(Boolean)""")
    transformed=0
    for bid in ids:
        el=driver.page.locator(f'[data-lapis-box="{bid}"]')
        before=el.evaluate("el=>getComputedStyle(el).transform")
        el.hover()
        driver.page.wait_for_timeout(180)
        if el.evaluate("el=>getComputedStyle(el).transform")!=before:
            transformed+=1
        driver.page.mouse.move(0,-1)
    return {"total":len(ids),"transforming":transformed}


def _scroll_reveal(driver):
    driver.page.evaluate("scrollTo({top:0,behavior:'instant'})")
    hidden=driver.page.evaluate(HIDDEN)
    if not hidden:return []
    rows=[]
    for item in hidden:
        bid=box_id(item["steps"])
        target=driver.page.locator(f'[data-lapis-hidden-index="{item["index"]}"]')
        target.evaluate("(el,id)=>{el.setAttribute('data-lapis-box',id);el.removeAttribute('data-lapis-hidden-index')}",bid)
        target=driver.page.locator(f'[data-lapis-box="{bid}"]')
        target.evaluate("el=>el.scrollIntoView({block:'center',behavior:'instant'})")
        delay=None
        for step in range(51):
            visible=target.evaluate(r"""el => {
              const s=getComputedStyle(el);return Number(s.opacity)>.9 && s.visibility!=='hidden' &&
                !/^inset\(50%|^inset\(100%/.test(s.clipPath);
            }""")
            if visible:
                delay=step*100
                break
            _tick(driver)
        driver.boxes()
        if bid not in driver.session.nodes:
            driver.session.node(bid,role="other",rect=item["rect"],context=driver.ctx_id)
        row={"box":bid,"hidden_at_rest":True}
        if delay is not None: row["reveal_delay_ms"]=delay
        rows.append(row)
    return rows


def _input_blocked(driver):
    """Latency of one ArrowDown while animations run; None when it cannot be tried."""
    page=driver.page
    if page.evaluate("document.scrollingElement.scrollHeight-innerHeight-scrollY")<120:
        return None
    if not page.evaluate("document.getAnimations().some(a=>a.playState==='running')"):
        return None
    before=page.evaluate("scrollY")
    page.keyboard.press("ArrowDown")
    started=monotonic()
    blocked=2000.
    for _ in range(101):
        if abs(page.evaluate("scrollY")-before)>1:
            elapsed=round((monotonic()-started)*1000,2)
            # A response within 100 ms (a few frames of the browser's own key scroll) is not ignored input.
            blocked=elapsed if elapsed>100 else 0.
            break
        _tick(driver,20)
    page.evaluate("scrollTo({top:0,behavior:'instant'})")
    return blocked


def base_contexts(session):
    """Plain contexts of the matrix: no reduced motion, normal network."""
    return list(session.matrix)


def run(session, open_driver):
    runs=[]
    partial=[]
    for ctx_id in base_contexts(session):
        runs.append((ctx_id, None))
        twin=ctx_id+"-rm"
        if len(twin)>16:
            partial.append(f"{ctx_id}: reduced-motion twin id too long; comparison not run")
            continue
        if twin not in session.contexts:
            session.context(twin, **{**{k:v for k,v in session.contexts[ctx_id].items()
                                        if k!="id"}, "reduced_motion":True})
        runs.append((twin, ctx_id))
    for ctx_id, compare_to in runs:
        driver=open_driver(ctx_id)
        try:
            moving=_measure(driver)
            probe={"context":ctx_id,"window_ms":5000,"moving":moving}
            if compare_to:
                probe["compare_to"]=compare_to
            probe["auto_moving"]=_auto(driver,moving)
            if driver.ctx["pointer"]=="fine":
                probe["hover_media"]=_hover_media(driver)
            blocked=_input_blocked(driver)
            if blocked is not None:
                probe["input_blocked_ms"]=blocked
            probe["scroll_reveal"]=_scroll_reveal(driver)
            session.add_probe("motion",probe)
        except Exception as error:
            partial.append(f"{ctx_id}: {type(error).__name__} measuring motion")
        finally:
            driver.close()
    session.cover("motion","partial" if partial else "ran",contexts=[cid for cid,_ in runs],
                  reason="; ".join(partial) if partial else None)
