"""Live context driver: actions, effects, boxes, and shared controlled time."""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from time import monotonic, sleep
from urllib.parse import urlsplit

import numpy as np
from playwright.sync_api import Browser

from lapis_design.behavior import outcome
from lapis_design.behavior_check import nodes, redact, settle
from lapis_design.behavior_check.network import Network, navigation_guard


class MissingSyntheticValues(ValueError):
    """A local-dev input action has no declared synthetic fixture."""


ATTRS = ("aria-expanded", "aria-pressed", "aria-selected", "aria-checked", "aria-current",
         "aria-invalid", "aria-busy", "aria-disabled", "aria-hidden", "aria-label", "disabled",
         "open", "value", "paused")
# WAI-ARIA 1.2 roles an author can give, plus the graphics roles: `role="status note"` means its first token in this list.
_ARIA_ROLES = ("alert alertdialog application article banner blockquote button caption cell checkbox code columnheader "
               "combobox complementary contentinfo definition deletion dialog directory document emphasis feed figure "
               "form generic grid gridcell group heading img insertion link list listbox listitem log main marquee math "
               "menu menubar menuitem menuitemcheckbox menuitemradio meter navigation none note option paragraph "
               "presentation progressbar radio radiogroup region row rowgroup rowheader scrollbar search searchbox "
               "separator slider spinbutton status strong subscript superscript switch tab table tablist tabpanel term "
               "textbox time timer toolbar tooltip tree treegrid treeitem "
               "graphics-document graphics-object graphics-symbol").split()
OBSERVE = r"""() => {
  const attrs=['aria-expanded','aria-pressed','aria-selected','aria-checked','aria-current',
   'aria-invalid','aria-busy','aria-disabled','aria-hidden','aria-label','disabled','open'];
  const result={}, dialogs=[], live=[];
  for (const el of document.querySelectorAll('[data-lapis-box]')) {
    const id=el.getAttribute('data-lapis-box'), r=el.getBoundingClientRect();
    if (!r.width || !r.height || getComputedStyle(el).visibility==='hidden') continue;
    const text=el.innerText?.trim() || '';
    const state={text,attrs:Object.fromEntries(attrs.map(a=>[a,el.getAttribute(a)])),
      rect:{x:r.x+scrollX,y:r.y+scrollY,w:r.width,h:r.height}};
    if (['INPUT','TEXTAREA','SELECT'].includes(el.tagName)) state.attrs.value=el.value;
    if (el.matches('input[type=checkbox],input[type=radio]')) state.attrs['aria-checked']=String(el.checked);
    if (['VIDEO','AUDIO'].includes(el.tagName)) state.attrs.paused=String(el.paused);
    result[id]=state;
    const role=el.getAttribute('role');
    const area=r.width*r.height/(innerWidth*innerHeight);
    if (el.localName==='dialog' || role==='dialog' || role==='alertdialog' ||
        el.hasAttribute('aria-modal') || (area>=.3 && getComputedStyle(el).position==='fixed' &&
        Number(getComputedStyle(el).zIndex)>0 && !el.closest('main'))) dialogs.push(id);
  }
  const o=window.__lapisObserve||{mutations:0,shifts:[]};
  // Live regions, as the contract's Announcements sentence reads them. A region is an element whose aria-live
  // is polite or assertive, or that has no aria-live and a role with a live default: status and log polite,
  // alert assertive (`output` has the role status). The nearest enclosing element with aria-live or such a
  // role owns the text inside it, so text added to a child counts for that region, and an inner region that
  // is off (aria-live=off, timer, marquee) silences it. Nothing inside an aria-hidden subtree or an element
  // that is not rendered is announced.
  const roles=new Set(__ARIA_ROLES__), LIVE_ROLE={status:'polite',log:'polite',alert:'assertive',timer:'off',marquee:'off'};
  const roleOf=el=>{
    for (const token of (el.getAttribute('role')||'').toLowerCase().split(/\s+/)) if (roles.has(token)) return token;
    return el.localName==='output'?'status':'';
  };
  const liveOf=el=>{
    const explicit=(el.getAttribute('aria-live')||'').trim().toLowerCase();
    return ['polite','assertive','off'].includes(explicit)?explicit:LIVE_ROLE[roleOf(el)]||null;
  };
  const textOf=root=>{
    const parts=[];
    const walk=(node,shown)=>{
      if (node.nodeType===3) {if (shown) parts.push(node.data); return;}
      if (node.nodeType!==1) return;
      const s=getComputedStyle(node);
      if (node!==root && (node.getAttribute('aria-hidden')==='true' || s.display==='none' || liveOf(node))) return;
      const block=!s.display.startsWith('inline');
      if (block) parts.push(' ');
      for (const child of node.childNodes) walk(child, s.visibility==='visible');
      if (block || node.localName==='br') parts.push(' ');
    };
    walk(root,true);
    return parts.join('').replace(/\s+/g,' ').trim();
  };
  // A region is matched across the two observations by the element itself, else by its place in the document.
  const known=(window.__lapisLive ||= {ids:new WeakMap(), count:0});
  const identity=el=>{
    if (!known.ids.has(el)) known.ids.set(el, ++known.count);
    return o.documentToken+':'+known.ids.get(el);
  };
  const place=el=>{
    const steps=[];
    for (let x=el; x; x=x.parentElement) {
      let index=0;
      for (let sib=x.previousElementSibling; sib; sib=sib.previousElementSibling) if (sib.localName===x.localName) index++;
      steps.unshift(x.id?'#'+x.id:x.localName+':'+index);
    }
    return steps.join('/');
  };
  for (const el of document.querySelectorAll('[aria-live],[role],output')) {
    const politeness=liveOf(el);
    if (!politeness || politeness==='off' || !el.getClientRects().length || el.closest('[aria-hidden="true"]')) continue;
    live.push({key:identity(el), place:place(el), text:textOf(el),
      box:el.closest('[data-lapis-box]')?.getAttribute('data-lapis-box')||null,
      channel:politeness==='polite'?'live-polite':roleOf(el)==='alert'?'alert':'live-assertive'});
  }
  const focus=document.activeElement?.closest('[data-lapis-box]')?.getAttribute('data-lapis-box')||null;
  return {boxes:result,dialogs,live,focus,scroll:scrollY,mutations:o.mutations,shifts:o.shifts.length,
     href:location.href,documentToken:o.documentToken};
}""".replace("__ARIA_ROLES__", json.dumps(_ARIA_ROLES))


class Driver:
    def __init__(self, browser: Browser, session, ctx_id: str):
        self.browser = browser
        self.session = session
        self.ctx_id = ctx_id
        self.ctx = session.contexts[ctx_id]
        self.context = None
        self.page = None
        self.cdp = None
        self.network = None
        self._loaded = False
        self._acted = False
        self._start = monotonic()
        self._popups = 0
        self._downloads = 0
        session.drivers.add(self)

    def clean(self, value: str) -> str:
        return redact.text(value, self.session.fixture_values)

    def t_ms(self) -> float:
        return max(0, round((monotonic() - self._start) * 1000, 2))

    def open(self, path: str | None = None, *, storage: str = "fresh") -> None:
        """Load a route of the source host in a new page; without one, the URL the run was given."""
        self._load(self.session.start_url if path is None else self.session.url_for(path), storage)

    def _load(self, url: str, storage: str) -> None:
        self.close_page()
        if self.context is not None and storage == "fresh":
            self.context.close()
            self.context = None
        if self.context is None:
            self.context = self.browser.new_context(
                viewport={"width": self.ctx["width"], "height": self.ctx["height"]},
                device_scale_factor=self.ctx.get("dpr", 2), color_scheme=self.ctx["theme"],
                reduced_motion="reduce" if self.ctx.get("reduced_motion") else "no-preference",
                has_touch=self.ctx["pointer"] == "coarse", is_mobile=self.ctx["pointer"] == "coarse",
                locale=self.ctx.get("locale", "en-US"), timezone_id=self.ctx.get("timezone", "UTC"))
            self.context.add_init_script(settle.INIT_SCRIPT)
            self.context.add_init_script(navigation_guard(urlsplit(self.session.source["url"]).hostname))
        self.page = self.context.new_page()
        self._loaded = False
        self._acted = False
        self._start = monotonic()
        self.context.unroute("**/*")
        self.network = Network(self)
        self.network.attach(self.context, self.page)
        self.page.on("console", self._console)
        self.page.on("pageerror", lambda error: self._log("exception", str(error)))
        self.page.on("popup", lambda _: setattr(self, "_popups", self._popups + 1))
        self.page.on("download", lambda _: setattr(self, "_downloads", self._downloads + 1))
        self.cdp = self.context.new_cdp_session(self.page)
        self.cdp.send("DOM.enable")
        self.cdp.send("Accessibility.enable")
        if self.ctx["network"] in ("slow", "offline"):
            self.cdp.send("Network.enable")
            if self.ctx["network"] == "slow":
                self.cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 400,
                              "downloadThroughput": 50_000, "uploadThroughput": 50_000})
        self.page.clock.install(time=datetime.fromtimestamp(self.session.clock.now_ms() / 1000, timezone.utc))
        frozen_at = self.session.clock.now_ms() + 250
        self.page.clock.pause_at(datetime.fromtimestamp(frozen_at / 1000, timezone.utc))
        self.session.clock.advance(250)
        for other in tuple(self.session.drivers):
            if other is not self and other.page is not None:
                other.page.clock.run_for(250)
        self._start = monotonic()
        self.page.goto(url, wait_until="domcontentloaded")
        settle.quiet(self, 0)
        self._loaded = True
        if self.ctx["network"] == "offline":
            self.cdp.send("Network.emulateNetworkConditions", {"offline": True, "latency": 0,
                          "downloadThroughput": 0, "uploadThroughput": 0})
        self.ctx["dir"] = self.page.evaluate("getComputedStyle(document.documentElement).direction")
        self.boxes()

    def close_page(self):
        if self.page is not None:
            self.page.close()
            self.page = None

    def close(self) -> None:
        self.close_page()
        if self.context is not None:
            self.context.close()
            self.context = None
        self.session.drivers.discard(self)

    def reload(self, *, reset_storage: bool = True) -> None:
        if reset_storage:
            here = urlsplit(self.page.url)      # the same page, query and fragment included
            same_host = here.scheme in ("http", "https") and here.hostname == urlsplit(self.session.start_url).hostname
            self._load(self.page.url if same_host else self.session.start_url, "fresh")
        else:
            self._start = monotonic()
            self.page.reload(wait_until="domcontentloaded")
            settle.quiet(self, 0)
            self.boxes()

    def boxes(self) -> list[dict]:
        return nodes.snapshot(self)

    def locate(self, box_id):
        self.boxes()
        return self.page.locator(f'[data-lapis-box="{box_id}"]').first

    def interactive(self) -> list[dict]:
        boxes = self.boxes()
        focusable = [box["id"] for box in boxes if box["focusable"] and box["interactive"] and box["enabled"]]

        def delegated(box):
            if box["focusable"] or box["pointer_handler"] or box["role"] not in ("card", "section", "other"):
                return False
            return self.page.locator(f'[data-lapis-box="{box["id"]}"]').evaluate("""(el, ids) => {
                const outer=el.getBoundingClientRect();
                return ids.some(id => {
                    const child=document.querySelector('[data-lapis-box="'+id+'"]');
                    if(!child || !el.contains(child)) return false;
                    const inner=child.getBoundingClientRect();
                    return inner.width*inner.height>=outer.width*outer.height*.95 &&
                        inner.left<=outer.left+2 && inner.top<=outer.top+2 &&
                        inner.right>=outer.right-2 && inner.bottom>=outer.bottom-2;
                });
            }""", focusable)

        return [box for box in boxes if box["interactive"] and box["enabled"] and not delegated(box)]

    def ax_name(self, box_id) -> str | None:
        return next((box["name"] for box in self.boxes() if box["id"] == box_id), None)

    def screenshot(self, clip: dict | None = None) -> np.ndarray:
        from PIL import Image
        return np.asarray(Image.open(io.BytesIO(self.page.screenshot(clip=clip))).convert("RGB"))

    def advance_clock(self, ms: int, *, jump: bool = False) -> None:
        self.session.advance_clock(ms, jump=jump)

    def _log(self, kind: str, message: str, level="error") -> None:
        if any(token in message for token in ("ERR_BLOCKED_BY_CLIENT", "blockedbyclient", "net::ERR_FAILED")):
            return
        if "Failed to fetch" in message and self.network and any(
                entry.get("blocked") and self.t_ms() - entry["t_ms"] < 1000
                for entry in self.network.entries[-5:]):
            return
        self.session.console({"context": self.ctx_id, "t_ms": self.t_ms(), "level": level,
                              "kind": kind, "message": redact.console(message, self.session.fixture_values)})

    def _console(self, message):
        if message.type not in ("error", "warning"):
            return
        text = message.text
        kind = ("hydration-mismatch" if "hydration" in text.lower() else
                "csp" if "content security policy" in text.lower() else
                "unhandled-rejection" if "unhandled" in text.lower() else
                "network" if "failed to load resource" in text.lower() else "other")
        self._log(kind, text, "warning" if message.type == "warning" else "error")

    def _perform(self, action):
        kind = action["kind"]
        target = self.locate(action["target"]) if "target" in action else None
        if kind in ("click", "tap"):
            (target.tap() if kind == "tap" or self.ctx["pointer"] == "coarse" else target.click())
        elif kind == "key":
            self.page.keyboard.press(action["key"])
        elif kind in ("type", "paste"):
            if self.session.values_engine is None:
                raise MissingSyntheticValues("no synthetic values (--values)")
            value_id = action.get("value_id") or self.session.values_engine.values_for(
                target.get_attribute("type") or "text", action.get("value", "valid"))
            value = self.session.values_engine.value(value_id)
            target.focus()
            if kind == "type":
                for index, char in enumerate(value):
                    if index:
                        sleep(.03)
                        self.advance_clock(30)
                    self.page.keyboard.type(char)
            else:
                target.evaluate("""(el,text) => {
                    const data=new DataTransfer();data.setData('text/plain',text);
                    const event=new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data});
                    el.dispatchEvent(event);
                    if(!event.defaultPrevented) {
                      const start=el.selectionStart??el.value.length, end=el.selectionEnd??start;
                      const next=el.value.slice(0,start)+text+el.value.slice(end);
                      const set=Object.getOwnPropertyDescriptor(el.constructor.prototype,'value')?.set;
                      if(set) set.call(el,next); else el.value=next;
                      el.dispatchEvent(new InputEvent('input',{bubbles:true,data:text,inputType:'insertFromPaste'}));
                    }
                }""", value)
            action["value_id"] = value_id.split(":")[0]
        elif kind == "select":
            if self.session.values_engine is None:
                raise MissingSyntheticValues("no synthetic values (--values)")
            selected = action.get("value_id") or self.session.values_engine.values_for(
                "text", action.get("value", "valid"))
            target.select_option(value=self.session.values_engine.value(selected))
            action["value_id"] = selected.split(":")[0]
        elif kind in ("check", "uncheck"):
            getattr(target, kind)()
        elif kind in ("hover", "focus"):
            getattr(target, kind)()
        elif kind == "drag":
            bounds = target.bounding_box()
            x, y = bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2
            self.page.mouse.move(x, y)
            self.page.mouse.down()
            self.page.mouse.move(x + bounds["width"], y + bounds["height"], steps=8)
            self.page.mouse.up()
        elif kind == "scroll":
            self.page.mouse.wheel(0, action.get("y", self.ctx["height"]))
        elif kind in ("back", "forward"):
            getattr(self.page, "go_" + kind)(wait_until="domcontentloaded")
        elif kind == "reload":
            self.page.reload(wait_until="domcontentloaded")
        elif kind == "navigate":
            destination = self.session.url_for(action.get("path", "/"))
            if urlsplit(destination).hostname != urlsplit(self.session.source["url"]).hostname:
                self.network.record_external(destination)
            else:
                self.page.goto(destination, wait_until="domcontentloaded")
        elif kind == "wait":
            until = monotonic() + action["ms"] / 1000
            while monotonic() < until:
                started = monotonic()
                sleep(min(.05, max(0, until - started)))
                self.advance_clock(round((monotonic() - started) * 1000))
        elif kind == "clock-advance":
            self.advance_clock(action["ms"])
        elif kind == "pointer-leave":
            self.page.mouse.move(self.ctx["width"] / 2, self.ctx["height"] / 2)
            self.page.mouse.move(self.ctx["width"] / 2, 0)
            self.page.mouse.move(self.ctx["width"] / 2, -1)
        else:
            raise ValueError(f"unknown action: {kind}")

    def act(self, action: dict) -> dict:
        self.boxes()
        before = self.page.evaluate(OBSERVE)
        req_start = len(self.network.entries)
        console_start = len(self.session.console_entries)
        popup_start, download_start = self._popups, self._downloads
        self.network.external = False
        self.network.external_path = None
        action["t_ms"] = self.t_ms()
        self.page.evaluate(settle.START_LAYOUT_ANIMATIONS)
        try:
            self._perform(action)
        except Exception:
            if not self.network.external:
                raise
        try:
            attempted = self.page.evaluate("window.__lapisExternalNavigation||null")
        except Exception:
            attempted = None
        if attempted and not self.network.external:
            self.network.record_external(attempted["url"], method=attempted["method"])
        if self.network.external and self.page.url.startswith("chrome-error:"):
            self.page.goto(self.session.start_url, wait_until="domcontentloaded")
        self._acted = True
        elapsed = settle.quiet(self, before["mutations"])
        self.boxes()
        animated_ids = [bid for bid in self.page.evaluate(settle.LAYOUT_ANIMATED) if bid in self.session.nodes]
        after = self.page.evaluate(OBSERVE)
        same_document = after["documentToken"] == before["documentToken"]
        resized = self.page.evaluate(settle.APART_FROM_ANIMATED, {"animated": animated_ids, "ids": [
            bid for bid, state in after["boxes"].items() if same_document and bid in before["boxes"] and any(
                abs(state["rect"][side] - before["boxes"][bid]["rect"][side]) > .5 for side in ("w", "h"))]})
        changed = [bid for bid, state in after["boxes"].items() if state["text"] !=
                   before["boxes"].get(bid, {}).get("text", "") and state["text"]]
        status = [bid for bid in changed if self.page.locator(f'[data-lapis-box="{bid}"]').evaluate(
            """(el, changed) => {
              if (changed.some(id => id!==el.getAttribute('data-lapis-box') &&
                  el.contains(document.querySelector('[data-lapis-box="'+id+'"]')))) return false;
              return !!el.closest('[role=status],[role=alert],[aria-live],output,.toast,.snackbar')
                || /\\b(cart|items|results|saved|added|sent|reserved)\\b/i.test(el.innerText||'');
            }""", changed)]
        aria = []
        for bid, state in after["boxes"].items():
            old = before["boxes"].get(bid, {}).get("attrs", {})
            for attr, value in state["attrs"].items():
                if attr in ATTRS and value != old.get(attr) and bid in before["boxes"]:
                    aria.append({"box": bid, "attr": attr, "from": self.clean(str(old[attr])) if old.get(attr) is not None else None,
                                 "to": self.clean(str(value)) if value is not None else None})
        announcement = []
        by_element = {live["key"]: live["text"] for live in before["live"]}
        by_place = {live["place"]: live["text"] for live in before["live"]}
        for live in after["live"]:
            old = by_element[live["key"]] if live["key"] in by_element else by_place.get(live["place"], "")
            if live["text"] and live["text"] != old:
                entry = {"channel": live["channel"], "text": self.clean(live["text"]), "t_ms": self.t_ms()}
                announcement.append({"box": live["box"], **entry} if live["box"] else entry)
        if after["focus"] and after["focus"] != before["focus"] and after["focus"] in changed:
            announcement.append({"channel": "focus", "box": after["focus"],
                                 "text": self.clean(after["boxes"][after["focus"]]["text"]), "t_ms": self.t_ms()})
        shifts = self.page.evaluate("start => window.__lapisObserve.shifts.slice(start)", before["shifts"])
        requests = [entry.copy() for entry in self.network.entries[req_start:]]
        navigation = "none"
        if self._downloads > download_start:
            navigation = "download"
        elif self._popups > popup_start:
            navigation = "new-window"
        elif after["documentToken"] != before["documentToken"]:
            navigation = "document"
        elif after["href"] != before["href"]:
            navigation = "same-document" if urlsplit(after["href"]).path != urlsplit(before["href"]).path or (
                urlsplit(after["href"]).fragment and self.page.locator(
                    f'[id="{urlsplit(after["href"]).fragment}"]').count()) else "none"
        effect = {"settle_ms": elapsed, "navigation": navigation,
                  "path": redact.path(after["href"], self.session.fixture_values),
                  "dom_mutations": max(0, after["mutations"] - before["mutations"]),
                  "text_changed": changed, "status_changed": status, "aria_changes": aria,
                  "focus_to": after["focus"], "requests": requests, "announcements": announcement,
                  "layout_shift": sum(item["value"] for item in shifts),
                  "shift_sources": list(dict.fromkeys(source for item in shifts for source in item["sources"])),
                  "layout_animated": animated_ids, "resized": resized,
                  "console_errors": sum(entry["level"] == "error" for entry in
                     self.session.console_entries[console_start:]), "scroll_y_delta": after["scroll"] - before["scroll"]}
        if self.network.external:
            effect["external"] = True
            effect["navigation"] = "document"
            effect["path"] = self.network.external_path
        if opened := next((bid for bid in after["dialogs"] if bid not in before["dialogs"]), None):
            effect["dialog_opened"] = opened
        if closed := next((bid for bid in before["dialogs"] if bid not in after["dialogs"]), None):
            effect["dialog_closed"] = closed
        effect["outcome"] = outcome(effect, action.get("target"))
        return effect
