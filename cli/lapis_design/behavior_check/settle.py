"""Quiet-window observation with a bounded settle deadline.

`layout_animated` does not sample frames: the page's timers and requestAnimationFrame run on the
controlled clock, so frame sampling would depend on who advances it. The init script records each
transition (`transitionrun`), CSS animation (`animationstart`), and `Element.animate()` call on a
layout property (width, height, inset, top/right/bottom/left, margin, padding) with its duration and
the target's rect at that moment. A box counts as animated when a recorded animation lasted 50 ms or
longer and the target's rect at the end of the settle window differs from the recorded start rect.
Instant changes and zero- or short-duration transitions are not animations: a box whose size they
changed is `resized` instead, unless it holds or sits inside an animated box.
"""
from __future__ import annotations

from time import monotonic, sleep

INIT_SCRIPT = """(() => {
  window.__lapisObserve={mutations:0,last:performance.now(),shifts:[],layoutAnimations:[],
    documentToken:Math.random()};
  const LAYOUT=/^(width|height|inset(-.+)?|top|right|bottom|left|margin(-.+)?|padding(-.+)?)$/;
  const kebab=name=>name.replace(/[A-Z]/g,c=>'-'+c.toLowerCase());
  const rectOf=el=>{const r=el.getBoundingClientRect();return [r.x,r.y,r.width,r.height];};
  function record(target, properties, duration) {
    if(!(target instanceof Element) || !(duration>=50)) return;
    const layout=properties.map(kebab).filter(p=>LAYOUT.test(p));
    if(!layout.length) return;
    window.__lapisObserve.layoutAnimations.push({target,properties:layout,duration,rect:rectOf(target)});
  }
  const keyframeProperties=effect=>[...new Set((effect?.getKeyframes?.()||[]).flatMap(k=>Object.keys(k))
    .filter(k=>!['offset','easing','composite','computedOffset'].includes(k)))];
  const durationOf=animation=>{const d=animation?.effect?.getTiming?.().duration;return typeof d==='number'?d:0;};
  document.addEventListener('transitionrun', event => {
    const animation=event.target.getAnimations?.().find(a=>a.transitionProperty===event.propertyName);
    let duration=durationOf(animation);
    if(!animation){
      const s=getComputedStyle(event.target), names=s.transitionProperty.split(',').map(x=>x.trim());
      const times=s.transitionDuration.split(',').map(x=>parseFloat(x)*(x.trim().endsWith('ms')?1:1000));
      const i=Math.max(names.indexOf(event.propertyName),names.indexOf('all'));
      duration=i<0?0:times[i%times.length];
    }
    record(event.target,[event.propertyName],duration);
  },true);
  document.addEventListener('animationstart', event => {
    const animation=event.target.getAnimations?.().find(a=>a.animationName===event.animationName);
    record(event.target,keyframeProperties(animation?.effect),durationOf(animation));
  },true);
  const animate=Element.prototype.animate;
  Element.prototype.animate=function(...args){
    const animation=animate.apply(this,args);
    try { record(this,keyframeProperties(animation.effect),durationOf(animation)); } catch(_){}
    return animation;
  };
  new MutationObserver(records => {
    const o=window.__lapisObserve;
    for(const record of records) {
      if(record.target?.closest?.('[data-lapis-capture-index],[data-lapis-box]') &&
         record.type==='attributes' && record.attributeName?.startsWith('data-lapis-')) continue;
      o.mutations+=record.addedNodes.length+record.removedNodes.length+(record.type==='childList'?0:1);
      o.last=performance.now();
    }
  }).observe(document,{subtree:true,childList:true,characterData:true,attributes:true});
  try {new PerformanceObserver(list => {
    for(const entry of list.getEntries()) window.__lapisObserve.shifts.push({value:entry.value,
      sources:entry.sources.map(source=>source.node?.getAttribute?.('data-lapis-box')).filter(Boolean)});
  }).observe({type:'layout-shift',buffered:true});} catch(_){}
})();"""

START_LAYOUT_ANIMATIONS = "() => { if (window.__lapisObserve) window.__lapisObserve.layoutAnimations=[]; }"

LAYOUT_ANIMATED = """() => {
  const ids=[];
  for (const item of window.__lapisObserve?.layoutAnimations || []) {
    if (!item.target.isConnected) continue;
    const r=item.target.getBoundingClientRect(), now=[r.x,r.y,r.width,r.height];
    if (!now.some((v,i)=>Math.abs(v-item.rect[i])>.5)) continue;
    const id=item.target.closest('[data-lapis-box]')?.getAttribute('data-lapis-box');
    if (id && !ids.includes(id)) ids.push(id);
  }
  return ids;
}"""

# Boxes that are, contain, or sit inside an animated box changed with the animation, not on their own.
APART_FROM_ANIMATED = """({ids, animated}) => {
  const box=id=>document.querySelector('[data-lapis-box="'+id+'"]');
  const moving=animated.map(box).filter(Boolean);
  return ids.filter(id => {const el=box(id);
    return el && !moving.some(other => other===el || other.contains(el) || el.contains(other));});
}"""


def _window(driver, last_mutations: int, limit: float) -> tuple[bool, int]:
    """Wait up to `limit` real seconds for 500 ms without mutations or pending requests."""
    started = monotonic()
    quiet_since = started
    advanced_at = started
    while monotonic() - started < limit:
        try:
            count = driver.page.evaluate("window.__lapisObserve?.mutations || 0")
        except Exception:
            return True, last_mutations
        if count != last_mutations or driver.network.pending:
            last_mutations = count
            quiet_since = monotonic()
        if monotonic() - quiet_since >= .5:
            return True, last_mutations
        sleep(.016)
        now = monotonic()
        driver.advance_clock(max(1, round((now - advanced_at) * 1000)))
        advanced_at = now
    return False, last_mutations


def _hung(driver) -> bool:
    return any(entry.get("injected") == "hang" for entry, _ in driver.network._open.values())


def quiet(driver, start_mutations: int) -> float:
    """Settle window: 500 ms without mutations or pending requests, capped at 5 s. While an
    injected hang is pending, the cap is 10 s of controlled time: the clock advances in 1 s steps
    and the page is checked after each, so app timeouts and the stub's close fire in order."""
    started = monotonic()
    done, last = _window(driver, start_mutations, 1)
    controlled = 0
    while not done and _hung(driver) and controlled < 10_000:
        driver.advance_clock(1000, jump=True)  # each 1 s step fires due timers once, in order
        controlled += 1000
        sleep(.05)  # let the page run due timers and the browser deliver network events
        try:
            driver.page.evaluate("0")
        except Exception:
            break
    if not done:
        _window(driver, last, 4)
    return round((monotonic() - started) * 1000 + controlled, 2)
