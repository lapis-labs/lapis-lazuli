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


# What a poll reads: the mutation count, and whether anything runs in real time that the controlled clock does not
# drive: a CSS transition or animation, a media element playing, a document still loading. Reading the animations
# also brings the page's style up to date, as a rendered frame would, so a transition a timer starts is seen.
POLL = """() => ({mutations: window.__lapisObserve?.mutations || 0,
  moving: document.readyState !== 'complete' || document.getAnimations().some(a => a.playState === 'running') ||
    [...document.querySelectorAll('video,audio')].some(m => !m.paused && !m.ended)})"""

QUIET_MS = 500       # a quiet window is this long in the page's own time
FOLLOW_MS = 100      # real time, after any mutation or request, for what real time delivers: frames, observers, events
STEP_MS = 16         # between polls the clock moves one frame


def _window(driver, last_mutations: int, limit_ms: int) -> tuple[bool, int, int]:
    """Advance the controlled clock until `limit_ms` have passed or 500 ms went by without mutations or pending
    requests. The clock follows real time (a poll, a 16 ms sleep, the clock moved by what the loop took) while a
    request is pending, a transition runs, the document loads, or the page changed less than `FOLLOW_MS` ago.
    Past that nothing is in flight that real time would let finish, so the rest of the quiet window passes a
    frame per poll without waiting. Returns whether the page went quiet, the last mutation count, and the
    controlled ms that passed."""
    advanced_at = monotonic()
    elapsed = quiet = 0
    while elapsed < limit_ms:
        try:
            seen = driver.page.evaluate(POLL)
        except Exception:
            return True, last_mutations, elapsed
        pending = bool(driver.network.pending)
        if seen["mutations"] != last_mutations or pending:
            last_mutations = seen["mutations"]
            quiet = 0
        if quiet >= QUIET_MS:
            return True, last_mutations, elapsed
        if pending or seen["moving"] or quiet < FOLLOW_MS:
            sleep(.016)
            now = monotonic()
            step = max(1, round((now - advanced_at) * 1000))
        else:
            now = monotonic()
            step = STEP_MS
        driver.advance_clock(step)
        advanced_at = now
        elapsed += step
        quiet += step
    return False, last_mutations, elapsed


def _hung(driver) -> bool:
    return any(entry.get("injected") == "hang" for entry, _ in driver.network._open.values())


def quiet(driver, start_mutations: int) -> float:
    """Settle window: 500 ms without mutations or pending requests, capped at 5 s. While an
    injected hang is pending, the cap is 10 s of controlled time: the clock advances in 1 s steps
    and the page is checked after each, so app timeouts and the stub's close fire in order.
    Returns the controlled ms the window took."""
    done, last, elapsed = _window(driver, start_mutations, 1000)
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
        elapsed += _window(driver, last, 4000)[2]
    return round(elapsed + controlled, 2)
