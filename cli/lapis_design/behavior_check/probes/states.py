"""Induce each reachable data-surface state against isolated stub snapshots."""
from __future__ import annotations

import re

from playwright.sync_api import Error as PlaywrightError

from lapis_design.behavior_check.probes._decision import PROBLEM, RETRY, names


NAMES = ("states",)
_FAILURES = (("error", "fail-5xx"), ("offline", "fail-network"), ("timeout", "hang"),
             ("forbidden", "forbidden"), ("not-found", "not-found"))
# The driver freezes the page clock, so `performance.now` is fake; `document.timeline` keeps real time.
_TRACE = """(() => {
  if (window.__lapisStateTrace) return;
  const trace = window.__lapisStateTrace = {};
  const clock = () => document.timeline.currentTime ?? 0;
  const find = () => [...document.querySelectorAll('[role=progressbar],.spinner,.skeleton,[aria-busy=true],[data-loading],.loading')]
    .find(el => el.getClientRects().length && getComputedStyle(el).visibility!=='hidden');
  const mark = () => {const el=find(), now=clock();
    if(el) {
      if(trace.start===undefined) trace.start=now;
      trace.indicator=el.matches('[role=progressbar]')?'progress':el.matches('.skeleton')?'skeleton':
        el.matches('.spinner')?'spinner':el.matches('[aria-busy=true]')?'inline-status':'text';
    } else if(trace.start!==undefined && trace.finished===undefined) trace.finished=now;
  };
  new MutationObserver(mark).observe(document, {subtree:true,childList:true,attributes:true});
  const original=window.fetch;
  window.fetch=function(...args){if(trace.request===undefined) trace.request=clock();return original.apply(this,args)};
  document.addEventListener('DOMContentLoaded',mark);
})()"""


def _surface(driver, token):
    driver.boxes()
    return driver.page.evaluate("""token => {
      const items=[...document.querySelectorAll('[data-state-surface],[data-surface],main section,main [role=list],main ul,main ol,main table,main')]
        .filter(el => !!el.getAttribute('data-lapis-box') && el.getClientRects().length);
      const sections=items.filter(el => el.matches('section,[data-state-surface],[data-surface]'));
      const name=el => [el.id,el.getAttribute('data-surface'),el.querySelector('h1,h2,h3')?.textContent,
        el.getAttribute('aria-label')].join(' ').toLowerCase();
      const match=sections.find(el => name(el).includes(token)) || sections.find(el => el.querySelector('ul,ol,table,[role=list]'));
      return (match || items.find(el => el.matches('main ul,main ol,main table,main [role=list]')) ||
        items.find(el => el.matches('main')))?.getAttribute('data-lapis-box') || null;
    }""", token)


# A surface keeps its identity across reloads by marker, heading, then position in main,
# because a variant or failure can re-render it under a different DOM path.
_IDENTITY = """el => {
  const main=document.querySelector('main')||document.body;
  const heading=node => (node.querySelector('h1,h2,h3,h4')?.textContent||node.getAttribute('aria-label')||'').trim();
  return {tag:el.localName, main:el===main,
    marker:el.getAttribute('data-state-surface')||el.getAttribute('data-surface')||'',
    heading:heading(el), index:[...main.querySelectorAll(el.localName)].indexOf(el)};
}"""
_RESOLVE = """ident => {
  const main=document.querySelector('main')||document.body;
  if(ident.main) return main.getAttribute('data-lapis-box');
  const visible=node => !!node.getClientRects().length && getComputedStyle(node).visibility!=='hidden';
  const heading=node => (node.querySelector('h1,h2,h3,h4')?.textContent||node.getAttribute('aria-label')||'').trim();
  const peers=[...main.querySelectorAll(ident.tag)];
  const found=(ident.marker && peers.find(node => (node.getAttribute('data-state-surface')||
      node.getAttribute('data-surface'))===ident.marker)) ||
    (ident.heading && peers.find(node => heading(node)===ident.heading)) || peers[ident.index];
  return found && visible(found) ? found.getAttribute('data-lapis-box') : null;
}"""
_TIMEOUT_MS = 3000


def _identity(driver, box):
    return driver.page.locator(f'[data-lapis-box="{box}"]').first.evaluate(_IDENTITY, timeout=_TIMEOUT_MS)


def _resolve(driver, box, identity):
    """The surface's current box id, or None when the surface is no longer rendered."""
    driver.boxes()
    if driver.page.locator(f'[data-lapis-box="{box}"]').count():
        return box
    return driver.page.evaluate(_RESOLVE, identity)


def _snapshot(driver, box):
    """Observe the surface; with the surface gone, observe what main shows in its place."""
    named = names(driver)                       # a control's wording is its accessible name (value, alt, aria-label)
    selector = f'[data-lapis-box="{box}"]' if box else "main" if driver.page.locator("main").count() else "body"
    target = driver.page.locator(selector).first
    snap = target.evaluate("""(el, words) => {
      const visible=node => !!node.getClientRects().length && getComputedStyle(node).visibility!=='hidden' &&
        getComputedStyle(node).display!=='none';
      const descendants=[el,...el.querySelectorAll('*')].filter(visible);
      const body=el.innerText.replace(/\\s+/g,' ').trim();
      const markers=[...el.querySelectorAll('[role=alert],[role=status],[aria-live],.error,.empty,.offline,.loading,.spinner,.skeleton')]
        .filter(node=>visible(node) && node.innerText.trim());
      const indicator=[...el.querySelectorAll('[role=progressbar],.spinner,.skeleton,[aria-busy=true],[data-loading],.loading')].find(visible);
      return {text:body,boxes:descendants.map(node => node.getAttribute('data-lapis-box')).filter(Boolean).sort(),
        blank:![...el.querySelectorAll('*')].some(node => visible(node) &&
          !node.closest('h1,h2,h3,h4,h5,h6,button,a,nav,header,footer') &&
          !node.matches('ul,ol,table,section,main') && (!node.matches('div') || !node.children.length) &&
          ((node.innerText || '').trim() || node.matches('img,svg,canvas,video'))),
        indicator:indicator && visible(indicator) ? indicator.matches('[role=progressbar]')?'progress':
          indicator.matches('.spinner')?'spinner':indicator.matches('.skeleton')?'skeleton':
          indicator.matches('[aria-busy=true]')?'inline-status':'text' : 'none',
        problem:new RegExp(words.problem,'i').test(body),
        recovery:!![...el.querySelectorAll('button,a,[role=button],input[type=button],input[type=submit],input[type=image]')].find(node=>visible(node) &&
          new RegExp(words.retry,'i').test(words.names[node.getAttribute('data-lapis-box')] ?? node.innerText)),
        announced:markers.some(node => node.matches('[role=alert],[role=status],[aria-live]') ||
          node.closest('[role=alert],[role=status],[aria-live]')),
        scope:el.matches('main')?'page':el.matches('li,article')?'object':'region'};
    }""", {"problem": PROBLEM, "retry": RETRY, "names": named}, timeout=_TIMEOUT_MS)
    return snap


def _retry(driver, box):
    scope = driver.page.locator(f'[data-lapis-box="{box}"]' if box else "main").first
    return scope.get_by_role("button", name=re.compile(RETRY, re.I)).first


def _record(session, driver, state, induced, box, path, snap, baseline, *, on_action=False, effect=None, trace=None):
    distinct = (snap["text"], snap["boxes"]) != (baseline["text"], baseline["boxes"])
    shown = (trace is not None and "start" in trace) if state == "loading" else distinct
    entry = {"context": driver.ctx_id, "surface": box, "path": path, "state": state,
             "induced_by": induced, "on_action": on_action, "shown": shown,
             "blank": snap["blank"], "indicator": (trace or {}).get("indicator", snap["indicator"]),
             "scope": snap["scope"], "problem_text": snap["problem"],
             "recovery_action": snap["recovery"], "announced": bool((effect or {}).get("announcements")) or snap["announced"]}
    if trace and "start" in trace:
        entry["indicator_delay_ms"] = max(0, round(trace["start"] - trace.get("request", trace["start"]), 2))
        if "finished" in trace:
            entry["indicator_shown_ms"] = max(0, round(trace["finished"] - trace["start"], 2))
    session.add_probe("states", entry)
    return entry


def _twin(session, ctx, network):
    profile = {**session.contexts[ctx], "network": network}
    profile.pop("id")
    return session.context(f"{ctx}-{'slow' if network == 'slow' else 'off'}", **profile)


def _attempt(gaps, label, step):
    """Run one state attempt; a page that cannot be observed makes coverage partial, not the probe fail."""
    try:
        step()
        return True
    except (PlaywrightError, KeyError, ValueError) as exc:
        gaps.add(f"{label}: could not observe ({type(exc).__name__}: {str(exc).splitlines()[0][:120]})")
        return False


def _surface_attempts(session, open_driver, driver, ctx, path, gaps):
    engine = session.engine
    token = path.rstrip("/").split("/")[-1].replace("-", " ").rstrip("s")
    box = _surface(driver, token)
    if not box:
        gaps.add(f"{ctx} {path}: data surface has no visible box")
        return
    identity = _identity(driver, box)
    baseline = _snapshot(driver, box)
    attempts = []

    def record(target, state, induced, **extra):
        current = _resolve(target, box, identity)
        snap = _snapshot(target, current)
        entry = _record(session, target, state, induced, current or box, path, snap, baseline, **extra)
        attempts.append((entry, snap))
        return entry, current

    def fixture(state):
        engine.reset(variant=state)
        driver.reload()
        record(driver, state, "fixture")

    def slow_load():
        slow = open_driver(_twin(session, ctx, "slow"))
        try:
            # Page-side timestamps use document.timeline because the driver freezes the page clock.
            slow.cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
            slow.context.add_init_script(_TRACE)
            slow.reload(reset_storage=False)
            trace = slow.page.evaluate("window.__lapisStateTrace || {}")
            record(slow, "loading", "delay", trace=trace)
        finally:
            slow.close()

    def failure(state, injection):
        try:
            engine.inject(injection, method="GET", path=path)
            driver.reload()
            if injection == "hang":
                advanced = 0
                while driver.network.pending and advanced < 11_000:
                    driver.advance_clock(1000)
                    advanced += 1000
                    driver.page.evaluate("0")
                if driver.network.pending:
                    gaps.add(f"{ctx} {path}: hang did not finish within 11 controlled seconds")
            if not any(r.get("injected") == injection and r["path"] == path for r in driver.network.entries):
                gaps.add(f"{ctx} {path}: {injection} request was not induced")
            entry, current = record(driver, state, injection)
        finally:
            engine.clear_injections()
        if entry["recovery_action"]:
            retry = _retry(driver, current)
            retry_box = retry.get_attribute("data-lapis-box", timeout=_TIMEOUT_MS) if retry.count() else None
            if retry_box:
                driver.act({"kind": "click", "target": retry_box})
                recovered = _snapshot(driver, _resolve(driver, box, identity))
                entry["recovery_works"] = (recovered["text"], recovered["boxes"]) == (
                    baseline["text"], baseline["boxes"])

    def offline_action():
        offline = open_driver(_twin(session, ctx, "offline"))
        try:
            current = _resolve(offline, box, identity)
            retry = _retry(offline, current)
            retry_box = retry.get_attribute("data-lapis-box", timeout=_TIMEOUT_MS) if retry.count() else None
            effect = offline.act({"kind": "click", "target": retry_box}) if retry_box else None
            if not retry_box:
                gaps.add(f"{ctx} {path}: offline state needs a page action after load; none offered")
            record(offline, "offline", "offline", on_action=bool(retry_box), effect=effect)
        finally:
            offline.close()

    def success():
        # A successful state needs an observable data-changing action, never a fixture-only load.
        driver.reload()
        current = _resolve(driver, box, identity)
        buttons = driver.page.locator(f'[data-lapis-box="{current}"]').first.locator(
            'button:not([disabled]),input[type=submit]:not([disabled])').all() if current else []
        targets = [b.get_attribute("data-lapis-box", timeout=_TIMEOUT_MS) for b in buttons
                   if not re.search(RETRY, b.inner_text(timeout=_TIMEOUT_MS), re.I)]
        for target in filter(None, targets):
            if not driver.page.locator(f'[data-lapis-box="{target}"]').count():
                continue
            effect = driver.act({"kind": "click", "target": target})
            if any(r.get("status", 500) < 400 and r["method"] != "GET" for r in effect["requests"]):
                record(driver, "success", "action", on_action=True, effect=effect)
                return
            driver.reload()
        gaps.add(f"{ctx} {path}: no successful user action reached the data surface")

    steps = [("empty", lambda: fixture("empty")), ("partial", lambda: fixture("partial")), ("loading", slow_load)]
    steps += [(state, lambda s=state, i=injection: failure(s, i)) for state, injection in _FAILURES]
    steps += [("offline", offline_action), ("success", success)]
    for state, step in steps:
        engine.reset()
        _attempt(gaps, f"{ctx} {path} {state}", step)
    engine.reset()
    # Same surface: equivalent rendering includes both text and the visible set of boxes.
    for entry, snap in attempts:
        peers = [other["state"] for other, other_snap in attempts if other is not entry and
                 (other_snap["text"], other_snap["boxes"]) == (snap["text"], snap["boxes"])]
        if peers:
            entry["same_as"] = list(dict.fromkeys(peers))


def _one_context(session, open_driver, ctx, gaps):
    session.engine.reset()
    driver = open_driver(ctx)
    try:
        paths = list(dict.fromkeys(r["path"] for r in driver.network.entries if r["method"] == "GET" and
                              r["kind"] in ("fetch", "xhr") and r.get("status") is not None))
        for index, path in enumerate(paths):
            def surface(path=path, fresh=index > 0):
                if fresh:
                    driver.reload()
                _surface_attempts(session, open_driver, driver, ctx, path, gaps)
            _attempt(gaps, f"{ctx} {path}", surface)
        return bool(paths)
    finally:
        driver.close()


def run(session, open_driver):
    contexts = list(session.matrix)
    if session.meta["backend"] != "stub" or session.engine is None:
        session.cover("states", "partial", contexts=contexts, reason="state fixture variants and failure injection require stub backend")
        return
    gaps = set()
    found = False
    for ctx in contexts:
        found |= _one_context(session, open_driver, ctx, gaps)
    session.cover("states", "partial" if gaps else "ran" if found else "not-applicable", contexts=contexts,
                  reason="; ".join(sorted(gaps)) if gaps else None)
