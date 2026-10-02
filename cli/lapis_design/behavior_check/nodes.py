"""Visible boxes and accessible names, sharing the render capture selection and DOM path."""
from __future__ import annotations

import json

from lapis_design.render.capture import _DOM
from lapis_design.render.ids import box_id

# Boxes with no semantic of their own can still take a click: a listener makes them a control.
_LISTENER_ROLES = ("card", "section", "other", "text", "icon")
_POINTER_EVENTS = ("click", "pointerdown", "mousedown", "touchstart")

# The capture reads the page's mutation count first: its own line-height probe nodes count as mutations (below).
CAPTURE = "() => { const o=window.__lapisObserve; return {before:o ? o.mutations : 0, data:(" + _DOM + ")()}; }"

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
  return {details, mutations:window.__lapisObserve?.mutations ?? 0};
}"""

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


def snapshot(driver) -> tuple[list[dict], int]:
    """The visible boxes, and how many mutations the capture added to the page's count (see CAPTURE)."""
    page = driver.page
    captured = page.evaluate(CAPTURE)
    data = captured["data"]
    cdp = driver.cdp
    dom = cdp.send("DOM.getDocument", {"depth": -1, "pierce": True})["root"]
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
    ids = {box["index"]: box_id(box["path"]) for box in data["boxes"]}
    listening = _pointer_listeners(cdp, [box["index"] for box in data["boxes"]
                                         if box["index"] in indexed and box["role"] in _LISTENER_ROLES])
    stamped = page.evaluate(DETAILS, {"ids": {str(k): v for k, v in ids.items()},
                                      "order": [ids[box["index"]] for box in data["boxes"]]})
    details = stamped["details"]
    result = []
    for box, detail in zip(data["boxes"], details):
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
    return result, stamped["mutations"] - captured["before"]
