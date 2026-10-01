"""Advance the controlled clock across scheduled timers and observe expiration."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from lapis_design.behavior_check.probes._decision import names

NAMES = ("time_limits",)

# Installed before the measured document loads; records due times without changing callback timing.
_TIMERS = """(() => {
 const timers = new Map(), setTimeoutNative=window.setTimeout.bind(window),
   clearTimeoutNative=window.clearTimeout.bind(window),
   setIntervalNative=window.setInterval.bind(window), clearIntervalNative=window.clearInterval.bind(window);
 window.__lapisTimers = timers;
 window.setTimeout=(fn,ms=0,...args)=>{
   let id; const delay=Math.max(0,Number(ms)||0);
   id=setTimeoutNative((...rest)=>{timers.delete(id); typeof fn==='function' ? fn(...rest) : (0,eval)(fn)},ms,...args);
   timers.set(id,{at:Date.now()+delay,delay}); return id;
 };
 window.setInterval=(fn,ms=0,...args)=>{
   const delay=Math.max(1,Number(ms)||0);
   const id=setIntervalNative((...rest)=>{const item=timers.get(id);
     if(item) item.at=Date.now()+delay;
     typeof fn==='function' ? fn(...rest) : (0,eval)(fn)},ms,...args);
   timers.set(id,{at:Date.now()+delay,delay}); return id;
 };
 window.clearTimeout=id=>{timers.delete(id);clearTimeoutNative(id)};
 window.clearInterval=id=>{timers.delete(id);clearIntervalNative(id)};
})()"""
# Timers shorter than this are display ticks (a countdown repainting every second). The page is
# checked at most once per window while only they are due.
_TICK_MS = 60_000
_COARSE_AFTER_MS = 2 * 3600_000
_COARSE_MS = 600_000
# Every tick callback runs for the first 30 simulated minutes, so a limit counted in ticks is exact
# there. Afterwards ticks fire once per window (Date-based checks stay exact); replaying each tick
# for 20 hours costs minutes of wall time per context.
_EVERY_TICK_MS = 30 * 60_000
_WARNING = re.compile(r"\b(?:warning|about to expire|expir(?:es|ing) soon|time remaining|session ending)\b|(?:곧|잠시 후).{0,30}(?:만료|종료)|(?:만료|종료).{0,30}(?:예정|주의)", re.I)
_EXPIRED = re.compile(r"\b(?:session expired|session ended|time(?:d)? out|hold (?:released|expired)|form expired|time is up)\b|(?:세션|시간|예약|보류).{0,15}(?:만료|종료|해제)", re.I)
_EXTEND = re.compile(r"\b(?:extend|stay (?:signed|logged) in|keep (?:working|session)|continue session)\b|(?:연장|계속\s*사용|로그인\s*유지)", re.I)
_TURN_OFF = re.compile(r"\b(?:disable|turn off|no time limit|never expire)\b|(?:시간\s*제한\s*(?:끄기|해제)|자동\s*로그아웃\s*끄기)", re.I)
_ADJUST = re.compile(r"\b(?:duration|timeout|session length|time limit)\b|(?:제한\s*시간|세션\s*시간)", re.I)


def _snapshot(driver, *, ids=False):
    """The page's text, fields, and controls. With `ids`, controls are named by their accessible name (a button's
    value, an image's alt, aria-label), which needs a fresh snapshot; without, by what they show."""
    named = names(driver) if ids else {}
    return driver.page.evaluate("""named => ({
      text:document.body?.innerText||'', path:location.pathname,
      inputs:[...document.querySelectorAll('input:not([type=hidden]),textarea')]
        .map(e=>({name:e.name||e.id||e.outerHTML.slice(0,60),value:e.value})),
      controls:[...document.querySelectorAll('button,a,[role=button],input[type=button],input[type=submit],input[type=image]')]
        .filter(e=>e.getBoundingClientRect().width && e.getBoundingClientRect().height)
        .map(e=>{const id=e.getAttribute('data-lapis-box');
          return {id,name:(named[id]||e.innerText||e.value||e.getAttribute('aria-label')||'').trim()}})
    })""", named)


def _next(driver):
    """Earliest due timer, and earliest due timer that is not a display tick. Records whose due
    time has passed (a timer cleared through a reference captured before the hook) are ignored."""
    return driver.page.evaluate("""tick => {
       const now=Date.now();
       const all=[...(window.__lapisTimers?.values()||[])].filter(t=>Number.isFinite(t.at) && t.at>now);
       const due=all.map(t=>t.at), slow=all.filter(t=>t.delay>=tick).map(t=>t.at);
       return {due:due.length ? Math.min(...due) : null, slow:slow.length ? Math.min(...slow) : null};
    }""", _TICK_MS)


def _seed_input(driver, values_engine):
    if values_engine is None:
        return False
    driver.boxes()
    fields = driver.page.evaluate("""() => [...document.querySelectorAll('input,textarea')]
       .filter(el=>!el.disabled && !el.readOnly && el.getBoundingClientRect().width &&
                     !['hidden','submit','button','checkbox','radio','file','password'].includes(el.type))
       .map(el=>({id:el.getAttribute('data-lapis-box'),type:el.type||'text'}))""")
    for field in fields:
        kind = field["type"] if field["type"] in ("email", "search", "number", "date") else "text"
        try:
            value_id = values_engine.values_for(kind, "valid")
        except KeyError:
            continue
        if field["id"]:
            driver.act({"kind": "paste", "target": field["id"], "value_id": value_id})
            return True
    return False


def _step(session, driver, timers, start):
    now = session.clock.now_ms()
    window = _TICK_MS if now - start < _COARSE_AFTER_MS else _COARSE_MS
    target = timers["due"]
    if target - now < window:
        # Only display ticks are imminent: run them all, but check the page once per window
        # or at the next slow timer, whichever comes first.
        target = min(timers["slow"] if timers["slow"] is not None else now + window, now + window)
    delta = max(1, int(target - now))
    if now - start < _EVERY_TICK_MS:
        driver.advance_clock(delta)
        return
    session.advance_clock(delta, jump=True)


def _idle(session, driver, horizon_ms, *, extend=False):
    start = session.clock.now_ms()
    current = _snapshot(driver)
    values = {item["name"]: item["value"] for item in current["inputs"] if item["value"]}
    initial_path = current["path"]
    warn_at = None
    expired_at = None
    extensions = 0
    extendable = False
    attempted = set()
    limit_kind = "session"
    while session.clock.now_ms() - start < horizon_ms:
        timers = _next(driver)
        if timers["due"] is None or timers["due"] - start > horizon_ms:
            break
        _step(session, driver, timers, start)
        state = _snapshot(driver)
        elapsed = (session.clock.now_ms() - start) / 1000
        text = state["text"]
        warning = bool(_WARNING.search(text))
        expiry = bool(_EXPIRED.search(text)) or (state["path"] != initial_path and
                    bool(re.search(r"(?:login|sign-in|expired|timeout)", state["path"], re.I)))
        if warning and warn_at is None and not expiry:
            warn_at = elapsed
        if ("hold" in text.lower() or "보류" in text) and expiry:
            limit_kind = "hold"
        if not expiry and values and any(item["name"] in values and not item["value"] for item in state["inputs"]):
            expiry = True
            limit_kind = "form"
        if warning:
            state = _snapshot(driver, ids=True)
        controls = [item for item in state["controls"] if _EXTEND.search(item["name"]) and item["id"]]
        extendable |= bool(warning and controls)
        if expiry:
            expired_at = elapsed
            break
        if extend and warning and controls and extensions < 10:
            control = controls[0]
            signature = (control["id"], elapsed)
            if signature not in attempted:
                attempted.add(signature)
                before = state
                driver.act({"kind": "click", "target": control["id"]})
                after = _snapshot(driver)
                if after["text"] != before["text"] or _next(driver)["due"] != timers["due"]:
                    extensions += 1
    return {"expired": expired_at, "warn_at": warn_at, "extendable": extendable,
            "extensions": extensions, "kind": limit_kind,
            "input_after_expiry": ("none" if not values else "kept" if all(
                 next((item["value"] for item in _snapshot(driver)["inputs"] if item["name"] == name), None) == value
                 for name, value in values.items()) else "lost") if expired_at is not None else None,
            "had_timers": _next(driver)["due"] is not None}


def _targets(session, ctx, flows, missing):
    if not flows:
        return [(None, urlsplit(session.source["url"]).path or "/", None, [])]
    result = []
    for flow in flows:
        start = flow.get("start", "/")
        run = next((item for item in session.flows if item["id"] == flow["id"] and item["context"] == ctx), None)
        if run is None or not run.get("steps"):
            result.append((flow["id"], start, start, []))
            if flow.get("max_steps", 1) > 1:
                missing.append(f"{ctx}:{flow['id']} intermediate flow states unavailable; checked start only")
            continue
        if run["status"] == "skipped":
            missing.append(f"{ctx}:{flow['id']} flow was skipped; checked start only")
            result.append((flow["id"], start, start, []))
            continue
        actions = []
        commit_ok = session.meta["backend"] == "stub" or session.meta.get("outbound") == "none"
        for step in run["steps"]:
            if not commit_ok and run.get("commit_step") is not None and step["index"] > run["commit_step"]:
                missing.append(f"{ctx}:{flow['id']} steps after the commit need stub or outbound none")
                break
            result.append((flow["id"], start, step["path"], list(actions)))
            actions.extend(step.get("actions", []))
    return result


def _load_step(driver, start, expected, actions):
    driver.open(start)
    driver.page.add_init_script(_TIMERS)
    driver.reload(reset_storage=False)
    for action in actions:
        driver.act({key: value for key, value in action.items() if key in
                    ("kind", "target", "key", "value", "value_id", "ms", "path")})
    if expected:
        from lapis_design.behavior_check.redact import path as safe_path
        reached = safe_path(driver.page.url, driver.session.fixture_values)
        if reached != expected:
            raise RuntimeError(f"flow step path {expected} was not reached; landed {reached}")


def run(session, open_driver):
    flows = (session.plan or {}).get("flows") or []
    missing = []
    found = 0
    for ctx in session.matrix:
        limited = set()
        for flow, start, expected, actions in _targets(session, ctx, flows, missing):
            if flow in limited:
                continue
            route = start if flow else expected or start
            driver = open_driver(ctx)
            try:
                _load_step(driver, route, expected, actions)
                starting = _snapshot(driver, ids=True)
                _seed_input(driver, session.values_engine)
                control_names = [item["name"] for item in starting["controls"]]
                turn_off = any(_TURN_OFF.search(name) for name in control_names)
                adjustable = False
                named = names(driver)
                for el in driver.page.locator('input[type=number][max]').all():
                    maximum = el.get_attribute("max")
                    current = el.input_value()
                    if maximum and current and maximum.isdecimal() and current.isdecimal() and int(current) > 0:
                        label = named.get(el.get_attribute("data-lapis-box")) or el.get_attribute("aria-label") or ""
                        adjustable |= int(maximum) >= int(current) * 10 and bool(_ADJUST.search(
                            label + " " + (el.get_attribute("name") or "")))
                baseline = _idle(session, driver, 20 * 3600_000)
                if baseline["expired"] is None:
                    continue
                item = {"context": ctx, "kind": baseline["kind"], "limit_s": baseline["expired"],
                        "warned": baseline["warn_at"] is not None,
                        "extendable": baseline["extendable"], "turn_off": turn_off,
                        "adjustable": adjustable, "input_after_expiry": baseline["input_after_expiry"]}
                if flow:
                    item["flow"] = flow
                if baseline["warn_at"] is not None:
                    item["warn_lead_s"] = max(0, baseline["expired"] - baseline["warn_at"])
                if baseline["extendable"]:
                    _load_step(driver, route, expected, actions)
                    _seed_input(driver, session.values_engine)
                    item["extensions"] = _idle(session, driver, 20 * 3600_000, extend=True)["extensions"]
                session.add_probe("time_limits", item)
                limited.add(flow)
                found += 1
            except Exception as exc:
                missing.append(f"{ctx}:{flow or 'entry'}: {type(exc).__name__}: {exc}")
            finally:
                driver.close()
    status = "partial" if missing else ("ran" if found else "not-applicable")
    reason = "; ".join(missing) if missing else ("No plan flows; probed entry route" if not flows else None)
    session.cover("time_limits", status, contexts=list(session.matrix), reason=reason)
