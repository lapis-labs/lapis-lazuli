"""Visible boxes and accessible names, sharing the render capture selection and DOM path."""
from __future__ import annotations

import json

from lapis_design.render.capture import _DOM
from lapis_design.render.ids import box_id

# Boxes with no semantic of their own can still take a click: a listener makes them a control.
_LISTENER_ROLES = ("card", "section", "other", "text", "icon")
_POINTER_EVENTS = ("click", "pointerdown", "mousedown", "touchstart")

# The capture reads the page's mutation count first: its own line-height probe nodes count as mutations (below).
# It also reads where the page stands (see UNCHANGED), and hands the Python side only what a box is made of: the
# capture's text runs and styles are the render check's, and serializing them costs more than taking them (so does
# a path of many steps, which crosses as one string).
WHERE = "o ? [o.documentToken, o.events, scrollX, scrollY] : null"
CAPTURE = ("() => { const o=window.__lapisObserve; const before=o ? o.mutations : 0, at=" + WHERE + "; "
           "const data=(" + _DOM + ")(); "
           "return {before, at, boxes:data.boxes.map(({index, path, role, tag, rect}) => "
           "({index, path:JSON.stringify(path), role, tag, rect}))}; }")

# Whether the page is still the one a snapshot saw: the same document, scroll position, and mutation count, and none
# of the events the init script counts (input, focus, scroll, resize, transition, animation, font, load) has reached
# it since. A hover reveal or a focus ring changes no node, so the mutation count alone cannot say; a scroll event
# comes a frame after the scroll, so the position is read as well. `repeat` is the mutations the snapshot's own
# probe nodes add (see CAPTURE): a snapshot that stands in for another counts them again, so a page that measures
# with probe nodes counts what it always counted.
UNCHANGED = r"""([seen, repeat]) => {
  const o=window.__lapisObserve;
  if (!o || o.mutations!==seen.mutations || [o.documentToken, o.events, scrollX, scrollY].some((v, i) => v!==seen.at[i]))
    return false;
  o.mutations+=repeat;
  return true;
}"""

# The capture marks every element with its index; this stamps the box ids the probes address, then reads what each
# box is (by id, as a probe would find it: the first element carrying it) for every box in one call.
DETAILS = r"""({ids, order}) => {
  document.querySelectorAll('[data-lapis-capture-index]').forEach(el => {
    const id=ids[el.getAttribute('data-lapis-capture-index')];
    if (id) el.setAttribute('data-lapis-box',id);
    el.removeAttribute('data-lapis-capture-index');
  });
  const first=new Map();
  for (const el of document.querySelectorAll('[data-lapis-box]')) {
    const id=el.getAttribute('data-lapis-box');
    if (!first.has(id)) first.set(id, el);
  }
  const details=order.map(id => {
    const el=first.get(id);
    const s=getComputedStyle(el), role=el.getAttribute('role')||'';
    const focusable=el.tabIndex>=0 && !el.disabled;
    const interactive=/^(button|link|input|select|textarea|summary)$/.test(el.localName)
        || /^(button|link|checkbox|radio|switch|tab|option|menuitem|combobox|slider|textbox)$/.test(role)
        || (s.cursor==='pointer' && getComputedStyle(el.parentElement||el).cursor!=='pointer')
        || !!el.onclick;
    const landmarks=['header','nav','main','aside','footer','form'];
    let landmark='none', inMain=false;
    for(let p=el;p;p=p.parentElement) {
        if(p.localName==='main'||p.getAttribute('role')==='main') inMain=true;
        if(landmark==='none') {const t=p.getAttribute('role')||p.localName;
            if(landmarks.includes(t)) landmark=({header:'banner',nav:'navigation',
                aside:'complementary',footer:'contentinfo'})[t]||t;
            else if(['banner','navigation','complementary','contentinfo','search','region'].includes(t)) landmark=t;
        }
    }
    return {interactive,focusable,enabled:!el.disabled&&el.getAttribute('aria-disabled')!=='true',
            in_main:inMain,landmark,pointer_handler:!!el.onclick};
  });
  const o=window.__lapisObserve;
  return {details, mutations:o?.mutations ?? 0, at:__WHERE__};
}""".replace("__WHERE__", WHERE)

# Which of the captured elements have a pointer listener, asked of the console API in one call (the
# DOMDebugger domain answers one element per call). Runs before the capture marks are removed.
LISTENERS = r"""((indexes, types) => {
  const wanted=new Set(indexes), found=[];
  for (const el of document.querySelectorAll('[data-lapis-capture-index]')) {
    const index=Number(el.getAttribute('data-lapis-capture-index'));
    if (!wanted.has(index)) continue;
    const listeners=getEventListeners(el);
    if (types.some(type => (listeners[type]||[]).length)) found.push(index);
  }
  return found;
})(__INDEXES__, __TYPES__)"""


def _pointer_listeners(cdp, indexes: list[int]) -> set[int]:
    if not indexes:
        return set()
    expression = LISTENERS.replace("__INDEXES__", json.dumps(indexes)).replace("__TYPES__", json.dumps(_POINTER_EVENTS))
    try:
        answer = cdp.send("Runtime.evaluate", {"expression": expression, "includeCommandLineAPI": True,
                                               "returnByValue": True})
    except Exception:
        return set()
    return set(answer.get("result", {}).get("value") or ())


def snapshot(driver) -> tuple[list[dict], int, dict | None]:
    """The visible boxes, how many mutations the capture added to the page's count (see CAPTURE), and what the
    page was when it was seen (see UNCHANGED; None when it changed while the snapshot ran)."""
    page = driver.page
    clock = driver.session.clock_moves
    captured = page.evaluate(CAPTURE)
    cdp = driver.cdp
    # The DOM domain tells the client of every attribute the page changes in the nodes it has handed out, and the
    # capture sets and clears one on every element: it is on for the tree only.
    cdp.send("DOM.enable")
    try:
        dom = cdp.send("DOM.getDocument", {"depth": -1, "pierce": True})["root"]
    finally:
        cdp.send("DOM.disable")
    backend_by_index = {}
    indexed = set()

    def visit(node):
        attrs = node.get("attributes", [])
        mapping = dict(zip(attrs[::2], attrs[1::2]))
        if "data-lapis-capture-index" in mapping:
            idx = int(mapping["data-lapis-capture-index"])
            backend_by_index[idx] = node.get("backendNodeId")
            indexed.add(idx)
        for child in node.get("children", []):
            visit(child)
        for child in node.get("shadowRoots", []):
            visit(child)
    visit(dom)
    ax = {node.get("backendDOMNodeId"): node for node in
          cdp.send("Accessibility.getFullAXTree")["nodes"] if node.get("backendDOMNodeId")}
    ids = {box["index"]: box_id(json.loads(box["path"])) for box in captured["boxes"]}
    listening = _pointer_listeners(cdp, [box["index"] for box in captured["boxes"]
                                         if box["index"] in indexed and box["role"] in _LISTENER_ROLES])
    stamped = page.evaluate(DETAILS, {"ids": {str(k): v for k, v in ids.items()},
                                      "order": [ids[box["index"]] for box in captured["boxes"]]})
    details = stamped["details"]
    result = []
    for box, detail in zip(captured["boxes"], details):
        idx = box["index"]
        bid = ids[idx]
        ax_node = ax.get(backend_by_index.get(idx), {})
        ax_name = ax_node.get("name", {}).get("value")
        if idx in listening:
            detail["pointer_handler"] = detail["interactive"] = True
        rect = {k: round(v, 2) for k, v in box["rect"].items()}
        name = driver.clean(ax_name) if ax_name is not None else None
        entry = {"id": bid, "role": box["role"], "name": name, "rect": rect, "tag": box["tag"], **detail}
        result.append(entry)
        driver.session.node(bid, role=box["role"], name=name, rect=rect, context=driver.ctx_id,
                            appears="action" if driver._acted else "load")
    # A page that changed while the snapshot ran is not the page the boxes were taken from.
    seen = {"at": stamped["at"], "mutations": stamped["mutations"], "clock": clock} \
        if stamped["at"] == captured["at"] else None
    return result, stamped["mutations"] - captured["before"], seen
