"""Visible boxes and accessible names, sharing the render capture selection and DOM path."""
from __future__ import annotations

from lapis_design.render.capture import _DOM
from lapis_design.render.ids import box_id


def snapshot(driver) -> list[dict]:
    page = driver.page
    data = page.evaluate(_DOM)
    cdp = driver.cdp
    dom = cdp.send("DOM.getDocument", {"depth": -1, "pierce": True})["root"]
    backend_by_index = {}
    node_by_index = {}

    def visit(node):
        attrs = node.get("attributes", [])
        mapping = dict(zip(attrs[::2], attrs[1::2]))
        if "data-lapis-capture-index" in mapping:
            idx = int(mapping["data-lapis-capture-index"])
            backend_by_index[idx] = node.get("backendNodeId")
            node_by_index[idx] = node.get("nodeId")
        for child in node.get("children", []):
            visit(child)
        for child in node.get("shadowRoots", []):
            visit(child)
    visit(dom)
    ax = {node.get("backendDOMNodeId"): node for node in
          cdp.send("Accessibility.getFullAXTree")["nodes"] if node.get("backendDOMNodeId")}
    ids = {box["index"]: box_id(box["path"]) for box in data["boxes"]}
    page.evaluate("""ids => document.querySelectorAll('[data-lapis-capture-index]').forEach(el => {
        const id=ids[el.getAttribute('data-lapis-capture-index')];
        if (id) el.setAttribute('data-lapis-box',id);
        el.removeAttribute('data-lapis-capture-index');
    })""", {str(k): v for k, v in ids.items()})
    result = []
    for box in data["boxes"]:
        idx = box["index"]
        bid = ids[idx]
        ax_node = ax.get(backend_by_index.get(idx), {})
        ax_name = ax_node.get("name", {}).get("value")
        locator = page.locator(f'[data-lapis-box="{bid}"]').first
        detail = locator.evaluate("""el => {
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
        }""")
        if idx in node_by_index and box["role"] in ("card", "section", "other", "text", "icon"):
            try:
                resolved = cdp.send("DOM.resolveNode", {"nodeId": node_by_index[idx]})
                listeners = cdp.send("DOMDebugger.getEventListeners", {"objectId": resolved["object"]["objectId"]})
                detail["pointer_handler"] |= any(listener["type"] in
                    ("click", "pointerdown", "mousedown", "touchstart") for listener in listeners["listeners"])
                detail["interactive"] |= detail["pointer_handler"]
            except Exception:
                pass
        rect = {k: round(v, 2) for k, v in box["rect"].items()}
        name = driver.clean(ax_name) if ax_name is not None else None
        entry = {"id": bid, "role": box["role"], "name": name, "rect": rect, "tag": box["tag"], **detail}
        result.append(entry)
        driver.session.node(bid, role=box["role"], name=name, rect=rect, context=driver.ctx_id,
                            appears="action" if driver._acted else "load")
    return result
