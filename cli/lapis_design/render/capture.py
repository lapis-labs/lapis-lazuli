"""Capture visible semantic and visually meaningful boxes and maximal styled text runs.

A box must have a non-zero rect in a visible subtree and be a landmark, section,
heading, text-bearing block, media, control/link, list, dialog, icon (SVG, icon-font,
emoji), or have a visible boundary (different background, border, or shadow).
Unboxed ancestors are skipped when assigning each box's nearest box parent.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Browser
from playwright.sync_api import Page

from lapis_design.render.color import to_oklch
from lapis_design.render.derived import derive
from lapis_design.render.fields import after_scroll, apply_fields, init_scripts, observe_rest
from lapis_design.render.ids import DOM_PATH_JS, box_id
from lapis_design.render.raw import RawView
from lapis_design.render.script import script_of
from lapis_design.text_sig import page_sig, run_sig

# Chromium delivers a `resize` event to the window and to visualViewport for every full-page screenshot,
# although neither size changes. Pages answer it by rebuilding charts and live regions, which detaches the
# text nodes and `data-lapis-box` elements the field passes still hold. These contexts never resize, so a
# browser-made resize that leaves the size where it was is dropped before the page's listeners run. A resize
# event the page dispatches itself is not the browser's (`isTrusted` is false) and goes through.
_DROP_SAME_SIZE_RESIZE = r"""(() => {
  const drop = (target, size) => {
    let last = size();
    target.addEventListener('resize', event => {
      const now = size();
      if (event.isTrusted && now === last) event.stopImmediatePropagation();
      last = now;
    }, true);
  };
  drop(window, () => innerWidth + 'x' + innerHeight);
  if (window.visualViewport)
    drop(visualViewport, () => visualViewport.width + 'x' + visualViewport.height + '@' + visualViewport.scale);
})()"""

# One evaluation preserves DOM order and exact style boundaries before Python converts colors.
_DOM = r"""() => {
 const nodes = [...document.querySelectorAll('*')];
 nodes.forEach((el, i) => el.setAttribute('data-lapis-capture-index', String(i)));
 const boxTags = new Set(['html','body','main','header','footer','nav','aside','section','article',
    'h1','h2','h3','h4','h5','h6','p','blockquote','pre','code','li','ul','ol','dl','dt','dd',
    'img','picture','video','canvas','svg','button','input','select','textarea','label','a',
    'dialog','figure','figcaption','table','tr','th','td','form','summary','details']);
 const roles = {main:'section',header:'section',footer:'section',aside:'section',section:'section',
    article:'section',nav:'nav',h1:'heading',h2:'heading',h3:'heading',h4:'heading',h5:'heading',
    h6:'heading',p:'text',blockquote:'text',pre:'text',code:'text',li:'text',dd:'text',dt:'text',
    img:'media',picture:'media',video:'media',canvas:'media',svg:'icon',button:'button',
    input:'input',select:'input',textarea:'input',label:'text',a:'link',dialog:'dialog',
    ul:'list',ol:'list',dl:'list',table:'list',summary:'button',figure:'media',figcaption:'text'};
 const ariaRoles = {navigation:'nav',main:'section',region:'section',banner:'section',
    contentinfo:'section',complementary:'section',heading:'heading',button:'button',link:'link',
    textbox:'input',searchbox:'input',listbox:'input',list:'list',listitem:'text',img:'media',
    dialog:'dialog',alertdialog:'dialog'};
    /* shared DOM path */
 function visible(el, style, rect) {
    if (!rect.width || !rect.height || style.display==='none' || style.visibility==='hidden') return false;
    for (let p=el; p; p=p.parentElement) {
      let s=getComputedStyle(p);
      if (s.display==='none' || s.visibility==='hidden' || s.visibility==='collapse' || Number(s.opacity)===0) return false;
    }
    return true;
 }
 const boxes = [];
 const indexes = new Set();
 for (const el of nodes) {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    if (!visible(el,s,r)) continue;
    const tag=el.localName, parent=el.parentElement && getComputedStyle(el.parentElement);
    const sides=['Top','Right','Bottom','Left'].map(side => ({px:parseFloat(s['border'+side+'Width'])||0,
      color:s['border'+side+'Color'], style:s['border'+side+'Style']}));
    const bordered=sides.some(b => b.px>0 && b.style!=='none' && b.style!=='hidden');
    const shadow=s.boxShadow!=='none' || s.textShadow!=='none' || s.filter.includes('drop-shadow(');
    const background=s.backgroundColor;
    const boundary=(background!==parent?.backgroundColor && background!=='rgba(0, 0, 0, 0)' &&
      background!=='transparent') || bordered || shadow || s.backgroundImage!=='none';
    const iconFont=/icon|symbol|awesome|material/i.test(s.fontFamily) || /(?:^|\s)(?:icon|fa[sbrl]?|material-icons)(?:\s|$)/i.test(el.className?.baseVal || el.className || '');
    const directText=[...el.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim();
    const emojiIcon=/\p{Extended_Pictographic}/u.test(directText) && !/[\p{L}\p{N}]/u.test(directText);
    const semantic=boxTags.has(tag) || !!el.getAttribute('role') || iconFont || emojiIcon ||
      (el.childNodes.length && [...el.childNodes].some(n=>n.nodeType===3 && n.textContent.trim()) &&
       ['block','flex','grid','list-item','inline-block','flow-root'].includes(s.display));
    if (!semantic && !boundary) continue;
    const i=Number(el.getAttribute('data-lapis-capture-index'));
    indexes.add(i);
    const aria=el.getAttribute('role')?.split(/\s+/)[0];
    let role, basis, confidence;
    if (aria && ariaRoles[aria]) { role=ariaRoles[aria]; basis='aria'; confidence=1; }
    else if (roles[tag]) {role=roles[tag]; basis='semantic'; confidence=1;}
    else {role=tag==='html'||tag==='body'?'other':iconFont||emojiIcon?'icon':boundary?'card':'other';
      basis='heuristic'; confidence=boundary?0.7:0.5;}
    const attrs={};
    for (const name of ['id','class','role','lang','type','data-lapis-signature','aria-level'])
      if (el.hasAttribute(name)) attrs[name]=el.getAttribute(name);
    if (el.hasAttribute('href')) attrs.href='';
    const radii=['TopLeft','TopRight','BottomRight','BottomLeft']
      .flatMap(corner => s['border'+corner+'Radius'].split(' ').map((part,i) =>
        part.endsWith('%') ? parseFloat(part) * (i ? r.height : r.width) / 100 : parseFloat(part)));
    boxes.push({index:i, path:path(el), parentIndex:null, tag, attrs, role,basis,confidence,
      rect:{x:r.x+scrollX,y:r.y+scrollY,w:r.width,h:r.height},
      style:{background, sides,shadow,radius:Math.max(0,...radii),
        font:s.fontFamily, color:s.color, display:s.display}, children:[]});
 }
 const byIndex=new Map(boxes.map(b=>[b.index,b]));
 for (const box of boxes) {
    const el=nodes[box.index];
    for (let p=el.parentElement;p;p=p.parentElement) {
      const ix=Number(p.getAttribute('data-lapis-capture-index'));
      if (indexes.has(ix)) {box.parentIndex=ix;byIndex.get(ix).children.push(box.index);break;}
    }
 }
 const runs=[];
 const normalHeights=new Map();
 const walker=document.createTreeWalker(document.documentElement,NodeFilter.SHOW_TEXT);
 for (let node; node=walker.nextNode();) {
   const parent=node.parentElement;
   if (!parent || !node.nodeValue.trim()) continue;
   let box=null;
   for (let p=parent;p;p=p.parentElement) {
     const ix=Number(p.getAttribute('data-lapis-capture-index'));
     if (indexes.has(ix)) {box=ix;break;}
   }
   if (box===null) continue;
   const s=getComputedStyle(parent), r=document.createRange();
   r.selectNodeContents(node);
   if (!visible(parent,s,parent.getBoundingClientRect()) || !r.getClientRects().length) continue;
   const whiteSpace=s.whiteSpace;
   let original=node.nodeValue;
   if (!['pre','pre-wrap','break-spaces'].includes(whiteSpace)) original=original.replace(/\s+/g,' ');
   if (!/[^\s\p{Cf}]/u.test(original)) continue;
   const lang=parent.closest('[lang]')?.getAttribute('lang') || null;
   let locale;
   try { locale=lang ? Intl.getCanonicalLocales(lang.replaceAll('_','-'))[0] : undefined; }
   catch (_) { locale=undefined; }
   const previous=runs.at(-1);
   const transform=s.textTransform.split(' ')[0];
   let text=original;
   if (transform==='uppercase') text=text.toLocaleUpperCase(locale);
   if (transform==='lowercase') text=text.toLocaleLowerCase(locale);
   if (transform==='capitalize') {
     const continuous=previous && previous.box===box && /[\p{L}\p{N}]$/u.test(previous.original);
     text=text.replace(/\p{L}[\p{L}\p{N}]*/gu, (word,offset) =>
       continuous && offset===0 ? word : word[0].toLocaleUpperCase(locale)+word.slice(1));
   }
   const chunks=[...r.getClientRects()].filter(q=>q.width && q.height);
   if (!chunks.length) continue;
   const lineYs=chunks.map(q=>Math.round((q.y+scrollY)*2)/2);
   let lineBoxHeight;
   if (s.lineHeight==='normal') {
     const key=s.font+'|'+original.slice(0,64);
     if (!normalHeights.has(key)) {
       const probe=document.createElement('span');
       probe.style.cssText='all:initial;position:absolute;visibility:hidden;display:inline-block;white-space:nowrap;line-height:normal';
       probe.style.font=s.font;
       probe.textContent=original.slice(0,64);
       document.body.append(probe);
       normalHeights.set(key,probe.getBoundingClientRect().height);
       probe.remove();
     }
     lineBoxHeight=normalHeights.get(key);
   }
   const style={fontFamily:s.fontFamily,size:s.fontSize,weight:s.fontWeight,lineHeight:s.lineHeight,
     letterSpacing:s.letterSpacing,transform,style:s.fontStyle,color:s.color,wordBreak:s.wordBreak,
     whiteSpace:s.whiteSpace,lang};
   let textOrdinal=0;
   for (let sibling=node.previousSibling; sibling; sibling=sibling.previousSibling)
     if (sibling.nodeType===3) textOrdinal++;
   const fontNode=[Number(parent.getAttribute('data-lapis-capture-index')),textOrdinal];
   if (previous && previous.box===box && JSON.stringify(previous.style)===JSON.stringify(style)) {
      previous.text+=text; previous.original+=original;
      previous.lineYs.push(...lineYs);
      previous.fontNodes.push(fontNode);
      previous.nodes.push(node);
   } else runs.push({box, text, original,style,lineYs,lineBoxHeight,fontNodes:[fontNode],nodes:[node]});
 }
 window.__lapisRunNodes=runs.map(run=>run.nodes);
 return {boxes,runs:runs.map(({lineYs,nodes,...run})=>({...run,lines:new Set(lineYs).size})),
         scrollWidth:Math.max(document.documentElement.scrollWidth,document.body.scrollWidth),
         pageHeight:Math.max(document.documentElement.scrollHeight,document.body.scrollHeight)};
}"""
_DOM = _DOM.replace("/* shared DOM path */", DOM_PATH_JS)


def _lang(value: str | None) -> str | None:
    if not value:
        return None
    value = value.replace("_", "-")
    parts = value.split("-")
    if not re.fullmatch(r"[a-zA-Z]{2,3}", parts[0]) or any(
        not re.fullmatch(r"[a-zA-Z0-9]{1,8}", part) for part in parts[1:]
    ):
        return None
    return "-".join([parts[0].lower(), *(part.upper() if len(part) == 2 and part.isalpha()
                      else part.title() if len(part) == 4 and part.isalpha() else part.lower()
                      for part in parts[1:])])


def _family(value: str) -> str:
    match = re.match(r"""^\s*(?:"([^"]+)"|'([^']+)'|([^,]+))""", value)
    return next((part for part in match.groups() if part is not None), "").strip() if match else ""


def _families(value: str) -> list[str]:
    """The computed font-family list, unquoted."""
    return [part.strip().strip("\"'") for part in re.findall(r"""(?:"[^"]*"|'[^']*'|[^,])+""", value)]


# Weight and slope words a static face can carry in its family name ("Pretendard SemiBold").
_FACE_STYLE = re.compile(r"(?:[\s-]+(?:thin|hairline|(?:extra|ultra)[\s-]?light|light|book|regular|normal|"
                         r"medium|(?:semi|demi)[\s-]?bold|(?:extra|ultra)[\s-]?bold|bold|heavy|black|italic|"
                         r"oblique))+", re.I)


def _stack_family(name: str, stack: list[str]) -> str:
    """The CSS family a local face stands for: the face's own family, or the stack family that it
    extends only with weight and slope words."""
    for family in stack:
        if name.casefold() == family.casefold() or (
                name.casefold().startswith(family.casefold()) and _FACE_STYLE.fullmatch(name[len(family):])):
            return family
    return name


def _font(cdp, backends: list[int], requested: str, stack: list[str], web_fonts: set[str]) -> str:
    """The family that painted the most glyphs. A web font reports the name inside its file, which
    can be empty or scrambled, so it is named by the first family in the CSS stack that has a
    loaded @font-face instead. A static local face that reports its weight in the family name is
    named by the stack family it extends."""
    if not backends:
        return requested
    web_name = next((family for family in stack if family.casefold() in web_fonts), None)
    counts: Counter[str] = Counter()
    nodes = cdp.send("DOM.pushNodesByBackendIdsToFrontend", {"backendNodeIds": backends})["nodeIds"]
    for node in nodes:
        if node:
            for font in cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"]:
                name = (web_name if font["isCustomFont"] and web_name
                        else _stack_family(font["familyName"], stack))
                counts[name] += font["glyphCount"]
    return counts.most_common(1)[0][0] if counts else requested


def _paint_and_fonts(cdp, indexes: set[int]) -> tuple[dict[int, int], dict[tuple[int, int], int]]:
    snapshot = cdp.send("DOMSnapshot.captureSnapshot", {"computedStyles": [], "includePaintOrder": True})
    strings = snapshot["strings"]
    nodes = snapshot["documents"][0]["nodes"]
    indexed = {}
    for i, attributes in enumerate(nodes["attributes"]):
        pairs = iter(attributes)
        for name, value in zip(pairs, pairs):
            if strings[name] == "data-lapis-capture-index":
                indexed[int(strings[value])] = i
    parents = {node: index for index, node in indexed.items() if index in indexes}
    ordinals: Counter[int] = Counter()
    text_backend = {}
    for node, parent in enumerate(nodes["parentIndex"]):
        if parent in parents and strings[nodes["nodeName"][node]] == "#text":
            text_backend[(parents[parent], ordinals[parent])] = nodes["backendNodeId"][node]
            ordinals[parent] += 1
    layout = snapshot["documents"][0]["layout"]
    if "paintOrders" not in layout:
        raise ValueError("CDP DOM snapshot did not include paint order")
    orders = layout["paintOrders"]
    ranked = sorted(((orders[slot], slot, layout["nodeIndex"][slot])
                     for slot in range(len(orders))), key=lambda item: item[:2])
    positions = {node: rank for rank, (_, _, node) in enumerate(ranked)}
    return {index: positions[i] for index, i in indexed.items() if i in positions}, text_backend


def _style(data: dict) -> dict:
    result = {}
    if background := to_oklch(data["background"]):
        result["background"] = background
    sides = {}
    for name, side in zip(("top", "right", "bottom", "left"), data["sides"]):
        if side["px"] and side["style"] not in ("none", "hidden"):
            item = {"px": round(side["px"], 2)}
            if color := to_oklch(side["color"]):
                item["color"] = color
            sides[name] = item
    if sides:
        result["border_sides"] = sides
        widest = max(sides.values(), key=lambda s: s["px"])
        result["border_px"] = widest["px"]
        if "color" in widest:
            result["border_color"] = widest["color"]
    result["shadow"] = data["shadow"]
    result["radius_px"] = round(data["radius"], 2)
    return result


def _run(data: dict, box: str, index: int, cdp, backend: dict[tuple[int, int], int], key: bytes,
         web_fonts: set[str]) -> dict:
    style = data["style"]
    text = data["text"]
    requested = _family(style["fontFamily"])
    rendered = _font(cdp, [backend[tuple(node)] for node in data["fontNodes"]
                           if tuple(node) in backend], requested, _families(style["fontFamily"]), web_fonts)
    size = float(style["size"].removesuffix("px"))
    line_height = style["lineHeight"]
    if line_height == "normal":
        # Measure a representative used line box in the browser with the run's computed font.
        line_height = data["lineBoxHeight"]
    else:
        line_height = float(line_height.removesuffix("px"))
    script = script_of(data["original"])
    spacing = style["letterSpacing"]
    tracking = 0 if spacing == "normal" else float(spacing.removesuffix("px"))
    run = {"id": f"{box}-t{index}", "box": box, "text": text,
           "chars": sum(not char.isspace() for char in text), "script": script,
           "font": {"requested": requested, "rendered": rendered,
                    "fallback": rendered.casefold() != requested.casefold()},
           "size_px": round(size, 2),
           "weight": round(float(style["weight"]), 4),
           "line_height": round(float(line_height) / size, 4) if size else 0,
           "letter_spacing_em": round(tracking / size, 4) if size else 0,
           "transform": style["transform"] if style["transform"] in (
               "uppercase", "lowercase", "capitalize") else "none",
           "style": style["style"] if style["style"] in ("normal", "italic", "oblique") else "oblique",
           "lines": data["lines"], "word_break": style["wordBreak"]}
    if lang := _lang(style["lang"]):
        run["lang"] = lang
    if color := to_oklch(style["color"]):
        run["color"] = color
    if data["original"].strip():
        run["text_sig"] = run_sig(data["original"], script, key)
    return run


class _Network:
    """Requests in flight and the time of the last request event, for the idle second that closes
    the scroll pass."""

    def __init__(self, page) -> None:
        self.pending: set = set()
        self.last = time.monotonic()
        page.on("request", self._start)
        page.on("requestfinished", self._end)
        page.on("requestfailed", self._end)

    def _start(self, request) -> None:
        self.pending.add(request)
        self.last = time.monotonic()

    def _end(self, request) -> None:
        self.pending.discard(request)
        self.last = time.monotonic()

    def wait_idle(self, page, quiet: float = 1.0, limit: float = 10.0) -> None:
        """Return once no request has been in flight for `quiet` seconds counted from now, or after
        `limit` seconds when the network never goes quiet."""
        start = time.monotonic()
        while True:
            page.wait_for_timeout(50)
            now = time.monotonic()
            if (not self.pending and now - max(self.last, start) >= quiet) or now - start >= limit:
                return


def capture(browser: Browser, url: str, config: dict, screenshot_path: Path, key: bytes, *,
            plan_signature: str | None = None, check_document: Callable[[Page], None] | None = None) -> dict:
    """Navigate once, settle and scroll, then capture a viewport while page/CDP remain live.

    `plan_signature` is the plan's `layout.signature`, used only as the unverified text fallback
    for `derived.signature_found`. `check_document` lets a caller refuse a changed main document
    before extraction, and again after the screenshot and the field passes, so nothing is returned
    from a document the last check did not see."""
    context = browser.new_context(viewport={"width": config["width"], "height": config["layout_height"]},
                                  device_scale_factor=2, color_scheme=config["theme"],
                                  reduced_motion="reduce" if config["reduced_motion"] else "no-preference")
    context.add_init_script(_DROP_SAME_SIZE_RESIZE)
    for script in init_scripts():
        context.add_init_script(script)
    try:
        page = context.new_page()
        network = _Network(page)
        cdp = context.new_cdp_session(page)
        cdp.send("DOM.enable")
        cdp.send("CSS.enable")
        page.goto(url, wait_until="networkidle")
        cdp.send("DOM.getDocument", {"depth": -1})
        view = RawView(config, page, cdp, {}, screenshot_path)
        page.wait_for_timeout(1000)
        observe_rest(view)
        step = config["layout_height"]
        y = 0
        while y + step < page.evaluate(
            "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
        ):
            y += step
            page.evaluate("y => window.scrollTo(0, y)", y)
            page.wait_for_timeout(300)
        network.wait_idle(page)
        after_scroll(view)
        page.evaluate("window.scrollTo(0, 0)")
        page.evaluate("""() => { for (const animation of document.getAnimations()) {
            try {
              const timing=animation.effect?.getComputedTiming();
              if (animation.effect?.getTiming().iterations === Infinity) {
                animation.pause(); animation.currentTime=0;
              } else if (!timing || !timing.duration || !Number.isFinite(timing.duration)) {
                animation.finish();
              } else {
                const time=animation.currentTime ?? 0;
                const iteration=Math.floor(Math.max(0,time-timing.delay)/timing.duration)+1;
                const end=Math.min(timing.delay+timing.activeDuration,
                                   timing.delay+iteration*timing.duration);
                animation.pause();
                animation.currentTime=Math.max(0,end-0.001);
              }
            } catch (_) { animation.pause(); }
        } }""")
        page.evaluate("window.scrollTo(0, 0)")
        if check_document is not None:
            check_document(page)
        data = page.evaluate(_DOM)
        indexes = {b["index"] for b in data["boxes"]} | {
            parent for r in data["runs"] for parent, _ in r["fontNodes"]
        }
        paint, backend = _paint_and_fonts(cdp, indexes)
        raw_ids = {b["index"]: box_id(b["path"]) for b in data["boxes"]}
        missing_paint = raw_ids.keys() - paint.keys()
        if missing_paint:
            raise ValueError(f"CDP paint order missing {len(missing_paint)} visible boxes")
        ranks = {index: rank for rank, index in enumerate(sorted(raw_ids, key=paint.__getitem__))}
        boxes = []
        elements = {}
        for b in data["boxes"]:
            bid = raw_ids[b["index"]]
            box = {"id": bid, "parent": raw_ids.get(b["parentIndex"]), "role": b["role"],
                   "role_confidence": b["confidence"], "role_basis": b["basis"],
                   "rect": {k: round(v, 2) for k, v in b["rect"].items()},
                   "style": _style(b["style"]), "paint_order": ranks[b["index"]]}
            boxes.append(box)
            elements[bid] = {"tag": b["tag"], "attrs": b["attrs"],
                             "children": [raw_ids[c] for c in b["children"]],
                             "rect": box["rect"], "style": box["style"],
                             "computed_style": b["style"]}
        texts = []
        run_locators = {}
        web_fonts = set(page.evaluate("""() => [...document.fonts].filter(f => f.status === 'loaded')
            .map(f => f.family.replace(/^["']|["']$/g, '').toLowerCase())"""))
        for i, item in enumerate(data["runs"]):
            run = _run(item, raw_ids[item["box"]], i, cdp, backend, key, web_fonts)
            if run["chars"]:
                texts.append(run)
                run_locators[run["id"]] = i
        # Field passes find a box's element as [data-lapis-box="<id>"] while the page is live.
        page.evaluate("""ids => document.querySelectorAll('[data-lapis-capture-index]').forEach(el => {
            const id = ids[el.getAttribute('data-lapis-capture-index')];
            if (id) el.setAttribute('data-lapis-box', id);
            el.removeAttribute('data-lapis-capture-index'); })""",
                      {str(index): bid for index, bid in raw_ids.items()})
        if check_document is not None:
            check_document(page)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot_path), full_page=True)
        vp = {"width": config["width"], "height": config["height"],
              "browser_chrome": config["browser_chrome"], "dpr": 2,
              "theme": config["theme"], "reduced_motion": config["reduced_motion"],
              "scroll_width": round(data["scrollWidth"], 2), "boxes": boxes, "text": texts}
        if texts:
            vp["text_sig"] = page_sig([(r["original"], script_of(r["original"]))
                                       for r in data["runs"] if r["original"].strip()], key)
        view.elements = elements
        view.extra["run_locators"] = run_locators
        apply_fields(view, vp)
        if check_document is not None:
            check_document(page)
        vp["derived"] = derive(vp, elements, config["height"], plan_signature,
                               page_height=data["pageHeight"],
                               line_extents=view.extra.get("line_extents"))
        return vp
    finally:
        context.close()


def has_dark_theme(browser: Browser, url: str) -> bool:
    """Compare computed foreground/background at html/body and initial sections in both schemes."""
    snapshots = []
    for theme in ("light", "dark"):
        context = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme=theme)
        try:
            page = context.new_page()
            page.goto(url, wait_until="networkidle")
            snapshots.append(page.evaluate("""() => [document.documentElement, document.body,
              ...document.querySelectorAll('main > section, section')].slice(0,6).map(el => {
              const s=getComputedStyle(el); return [s.backgroundColor,s.color]; })"""))
        finally:
            context.close()
    return snapshots[0] != snapshots[1]
