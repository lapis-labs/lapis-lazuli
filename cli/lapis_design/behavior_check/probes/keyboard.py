"""Measure sequential keyboard access on the entry route and representative routes."""
from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import numpy as np

from lapis_design.behavior import FOCUS_CONTRAST_MIN
from lapis_design.behavior_check import redact

NAMES = ("keyboard",)

# One DOM read per step: the focused element, its grouping chain, occlusion samples,
# and page structure are read without repeatedly resolving Playwright locators.
OBSERVE = r"""({roles,full,detail}) => {
  const visible = el => {
    if (!el) return false;
    const r=el.getBoundingClientRect();
    if (!r.width || !r.height) return false;
    for(let p=el;p;p=p.parentElement) {
      const s=getComputedStyle(p);
      if(s.display==='none'||s.visibility==='hidden'||s.visibility==='collapse'||+s.opacity===0||p.inert) return false;
    }
    return true;
  };
  const id=el=>el?.getAttribute('data-lapis-box')||null;
  const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,w:r.width,h:r.height}};
  const role=el=>{
    const r=el.getAttribute('role');
    return r&&['banner','navigation','main','complementary','contentinfo','search','form','region'].includes(r)?r:
      ({header:'banner',nav:'navigation',main:'main',aside:'complementary',footer:'contentinfo',form:'form'})[el.localName]||null;
  };
  const grouping=el=>el.matches('article,li,ul,ol,dl,dialog,[role="dialog"],[role="alertdialog"]') ||
    !!role(el) || roles[id(el)]==='card' ||
    (el.matches('section') && !!el.querySelector('h1,h2,h3,h4,h5,h6,[role="heading"]')) ||
    (el.hasAttribute('data-lapis-box') && getComputedStyle(el).display!=='contents' &&
      el.matches('figure,[role="list"],[role="listitem"]'));
  const focus=document.activeElement;
  const el=focus&&focus!==document.body&&focus!==document.documentElement?focus:null;
  const box=el?.closest('[data-lapis-box]');
  const view=[visualViewport.pageLeft,visualViewport.pageTop,visualViewport.scale];
  if(!detail && !full) return {id:id(box),href:location.href,scroll:scrollY,view,
    dialogs:[...document.querySelectorAll('dialog,[role="dialog"],[role="alertdialog"]')]
      .filter(visible).map(id).filter(Boolean)};
  const chain=[];
  if(box) for(let p=box.parentElement;p;p=p.parentElement) if(grouping(p)&&id(p))
    chain.push({id:id(p),rect:rect(p)});
  let landmark='none',in_main=false,in_dialog=null;
  for(let p=el;p;p=p.parentElement){
    if(role(p)==='main') in_main=true;
    if(landmark==='none'&&role(p)) landmark=role(p);
    if(!in_dialog && p.matches('dialog,[role="dialog"],[role="alertdialog"]')) in_dialog=id(p);
  }
  let total=0,covered=0;
  const covers=new Map();
  if(el){
    const r=el.getBoundingClientRect();
    const left=Math.max(0,r.left), right=Math.min(innerWidth,r.right);
    const top=Math.max(0,r.top),bottom=Math.min(innerHeight,r.bottom);
    for(let y=top+2;y<bottom;y+=4) for(let x=left+2;x<right;x+=4){
      total++;
      const topmost=document.elementsFromPoint(x,y).find(node=>getComputedStyle(node).pointerEvents!=='none');
      if(topmost && topmost!==el && !el.contains(topmost)){
        covered++;
        const cover=topmost.closest('[data-lapis-box]');
        const key=id(cover);
        if(key) covers.set(key,(covers.get(key)||0)+1);
      }
    }
  }
  const headings=full?[...document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"]')]
    .filter(h=>visible(h)&&!h.closest('[aria-hidden="true"],[role="presentation"],[role="none"]'))
    .map(h=>{
      let l='none';for(let p=h.parentElement;p;p=p.parentElement) if(role(p)){l=role(p);break;}
      return {id:id(h),level:+h.getAttribute('aria-level')||(+h.localName.slice(1)),
        landmark:l,in_main:!!h.closest('main,[role="main"]')};
    }).filter(h=>h.id&&h.level>=1&&h.level<=6):[];
  const landmarks=full?[...document.querySelectorAll('header,nav,main,aside,footer,form,[role]')]
    .filter(visible).map(role).filter(Boolean):[];
  const tabbable=full?[...document.querySelectorAll('a[href],button,input,select,textarea,summary,[tabindex],[contenteditable]')]
    .filter(e=>visible(e)&&e.tabIndex>=0&&!e.disabled&&!e.closest('[inert]')).map(id).filter(Boolean):[];
  const order=full?[...document.querySelectorAll('[data-lapis-box]')].map(id):[];
  const dialogs=[...document.querySelectorAll('dialog,[role="dialog"],[role="alertdialog"]')]
    .filter(visible).map(id).filter(Boolean);
  const modal_dialogs=[...document.querySelectorAll('dialog,[role="dialog"],[role="alertdialog"]')]
    .filter(el=>visible(el)&&(el.matches(':modal')||el.getAttribute('aria-modal')==='true'))
    .map(id).filter(Boolean);
  return {id:id(box),name:el?.getAttribute('aria-label')||null,rect:el?rect(el):null,
    chain,landmark,in_main,in_dialog,share:total?Math.floor(covered/total*100)/100:0,
    obscured_by:[...covers].sort((a,b)=>b[1]-a[1])[0]?.[0]||null,
    headings,landmarks,tabbable,order,dialogs,modal_dialogs,scroll:scrollY,view,href:location.href};
}"""


def _observe(driver, *, full=False, detail=True):
    return driver.page.evaluate(OBSERVE, {"roles":getattr(driver, "_keyboard_roles", {}),
                                          "full":full, "detail":detail})


# Scrolling uses window.scrollTo: element.scrollIntoView moves Chromium's sequential focus
# navigation starting point, so the next Tab would skip the target.
REGION = """(el, prepare) => {
  const v=visualViewport, doc=document.scrollingElement||document.documentElement;
  if (prepare) {
    const r=el.getBoundingClientRect();
    scrollTo({left:v.pageLeft+r.left-v.offsetLeft+r.width/2-v.width/2,
              top:v.pageTop+r.top-v.offsetTop+r.height/2-v.height/2, behavior:'instant'});
  }
  const r=el.getBoundingClientRect();
  const x=r.left-v.offsetLeft-8, y=r.top-v.offsetTop-8, w=r.width+16, h=r.height+16;
  // The inflated edge may be cut only where the document itself ends.
  const eps=.5, maxLeft=doc.scrollWidth-v.width, maxTop=doc.scrollHeight-v.height;
  const box=r.left-v.offsetLeft>=0 && r.top-v.offsetTop>=0 &&
    r.right-v.offsetLeft<=v.width && r.bottom-v.offsetTop<=v.height;
  const edges=(x>=0 || v.pageLeft<=eps) && (y>=0 || v.pageTop<=eps) &&
    (x+w<=v.width || v.pageLeft>=maxLeft-eps) && (y+h<=v.height || v.pageTop>=maxTop-eps);
  return {x, y, w, h, vw:v.width, vh:v.height, view:[v.pageLeft, v.pageTop, v.scale], inside:box&&edges};
}"""


def _region(driver, box_id, *, prepare=False):
    """The box inflated by 8 px, in visual-viewport CSS px (mobile layouts may be zoomed out)."""
    return driver.page.locator(f'[data-lapis-box="{box_id}"]').first.evaluate(REGION, prepare)


def _crop(image, region):
    scale = image.shape[1] / region["vw"]
    left, top = int(np.floor(region["x"] * scale)), int(np.floor(region["y"] * scale))
    right = int(np.ceil((region["x"] + region["w"]) * scale))
    bottom = int(np.ceil((region["y"] + region["h"]) * scale))
    return image[max(0, top):min(image.shape[0], bottom), max(0, left):min(image.shape[1], right)], scale


def _indicator(before, after, region):
    """Changed pixels in one unscrolled region, with area converted back to CSS px²."""
    if not region["inside"]:
        return None
    prior, scale = _crop(before, region)
    current, _ = _crop(after, region)
    if not prior.size or prior.shape != current.shape:
        return None
    different = np.max(np.abs(current.astype(np.int16)-prior.astype(np.int16)), axis=2) > 8
    area = float(different.sum()/scale**2)
    if not different.any():
        return {"area_px": 0, "contrast": 1, "contrast_area_px": 0}
    old = prior[different].astype(np.float64)/255
    new = current[different].astype(np.float64)/255
    old = np.where(old <= .04045, old/12.92, ((old+.055)/1.055)**2.4)
    new = np.where(new <= .04045, new/12.92, ((new+.055)/1.055)**2.4)
    lum_old = old @ np.array([.2126, .7152, .0722])
    lum_new = new @ np.array([.2126, .7152, .0722])
    ratios = (np.maximum(lum_old, lum_new)+.05)/(np.minimum(lum_old, lum_new)+.05)
    return {"area_px": round(area, 2), "contrast": round(float(np.median(ratios)), 3),
            "contrast_area_px": round(float((ratios >= FOCUS_CONTRAST_MIN).sum()/scale**2), 2)}


def _recover_indicators(driver, route, stops):
    """Replay the Tab order once, scrolling each unmeasured next stop into view before Tab."""
    missing = [i for i, stop in enumerate(stops) if "indicator" not in stop]
    if not missing:
        return 0
    try:
        driver.open(route)
        for stop in stops[:missing[-1]+1]:
            region = before = None
            if "indicator" not in stop:
                region = _region(driver, stop["box"], prepare=True)
                if region["inside"]:
                    before = driver.screenshot()
            driver.page.keyboard.press("Tab")
            if _observe(driver, detail=False)["id"] != stop["box"]:
                break
            if before is None:
                continue
            after_region = _region(driver, stop["box"])
            if after_region["view"] != region["view"]:
                continue
            measured = _indicator(before, driver.screenshot(), region)
            if measured is not None:
                stop["indicator"] = measured
    except Exception:
        # A navigation, replaced route, or removed target leaves the remaining indicators unmeasured.
        pass
    return sum("indicator" not in stop for stop in stops)


def _paths(session, entry):
    """Prefer explicitly named flow routes, then distinct entry-link templates."""
    paths = [entry]
    source = urlsplit(session.source["url"])
    for flow in (session.plan or {}).get("flows", []):
        for candidate in (flow.get("start"), (flow.get("done") or {}).get("route")):
            dest = urlsplit(urljoin(session.source["url"], candidate)) if candidate else None
            if (candidate and "*" not in candidate and candidate.startswith("/") and
                    dest.scheme == source.scheme and dest.netloc == source.netloc and candidate not in paths):
                paths.append(candidate)
                if len(paths) == 5:
                    return paths
    return paths


def _route_links(driver, state, routes):
    links = driver.page.evaluate("""() => [...document.querySelectorAll('a[href][data-lapis-box]')]
      .map(a=>({id:a.getAttribute('data-lapis-box'),href:a.href}))""")
    stop_ids = {s["box"] for s in state["stops"]}
    source = urlsplit(driver.session.source["url"])
    candidates = []
    for link in links:
        dest = urlsplit(link["href"])
        if link["id"] in stop_ids and (dest.scheme, dest.netloc) == (source.scheme, source.netloc):
            path = dest.path or "/"
            if path not in routes and path not in candidates:
                candidates.append(path)
    def first(path):
        return path.strip("/").split("/")[0]
    while candidates and len(routes) < 5:
        chosen = next((p for p in candidates if first(p) not in {first(q) for q in routes}), candidates[0])
        routes.append(chosen)
        candidates.remove(chosen)


def _headings(state, stops):
    indices = {stop["box"]: stop["index"] for stop in stops}
    order = state["order"]
    positions = {bid: index for index, bid in enumerate(order)}
    return [{"box": h["id"], "level": h["level"], "landmark": h["landmark"],
             "in_main": h["in_main"], "next_stop": next((indices[bid] for bid in order[positions[h["id"]]+1:]
                                                     if bid in indices), None)}
            for h in state["headings"] if h["id"] in positions]


def _cycles(ids, outside):
    """The last three identical periods demonstrate a closed cycle, not one repeated stop."""
    for length in range(1, len(ids)//3+1):
        cycle = ids[-length:]
        if (len(set(cycle)) == length and ids[-3*length:-2*length] == cycle
                and ids[-2*length:-length] == cycle and outside-set(cycle)):
            return cycle
    return None


def _walk(driver, route):
    if urlsplit(driver.page.url).path != route:
        driver.open(route)
    boxes = driver.boxes()
    driver._keyboard_roles = {box["id"]:box["role"] for box in boxes}
    initial = _observe(driver, full=True)
    box_by_id = {box["id"]: box for box in boxes}
    focusable = set(initial["tabbable"])
    cap = 3*len(focusable)+10
    stops, history, containers, traps = [], [], {}, []
    issues = []
    completed = not focusable
    presses = 0
    main_press = None
    initial_href = initial["href"]
    while focusable and presses < cap:
        previous = _observe(driver, detail=False)
        before = driver.screenshot()
        req_index, popups = len(driver.network.entries), driver._popups
        driver.page.keyboard.press("Tab")
        presses += 1
        focused = _observe(driver)
        if not focused["id"]:
            if focused["href"] != previous["href"] or driver._popups > popups:
                issues.append("focus navigated without a capturable stop on " + redact.path(route))
                break
            if stops and not (focusable-{s["box"] for s in stops}):
                completed = True
                break
            continue
        bid = focused["id"]
        if not main_press and focused["in_main"]:
            main_press = presses
        if stops and bid == stops[0]["box"]:
            if not (focusable-{s["box"] for s in stops}):
                completed = True
                break
        history.append(bid)
        if bid not in box_by_id:
            box_by_id = {box["id"]:box for box in driver.boxes()}
            driver._keyboard_roles.update({box["id"]:box["role"] for box in box_by_id.values()})
        if not any(stop["box"] == bid for stop in stops):
            box = box_by_id.get(bid)
            if not box:
                issues.append("focused box not captured")
                break
            stop = {"box": bid,"index": len(stops), "name": driver.clean(focused["name"] or box.get("name") or ""),
                    "landmark":focused["landmark"], "in_main":focused["in_main"],
                    "rect":{k:round(v, 2) for k,v in focused["rect"].items()}}
            if focused["in_dialog"]:
                stop["in_dialog"] = focused["in_dialog"]
            for i, ancestor in enumerate(focused["chain"]):
                containers[ancestor["id"]] = {"parent":focused["chain"][i+1]["id"] if i+1<len(focused["chain"]) else None,
                                               "rect":{k:round(v,2) for k,v in ancestor["rect"].items()}}
                if ancestor["id"] not in driver.session.nodes:
                    driver.boxes()
            if focused["chain"]:
                stop["container"] = focused["chain"][0]["id"]
            if abs(previous["scroll"]-focused["scroll"]) < .01:
                region = _region(driver, bid)
                if region["view"] == previous["view"]:
                    indicator = _indicator(before, driver.screenshot(), region)
                    if indicator is not None:
                        stop["indicator"] = indicator
            stop["obscured_share"] = focused["share"]
            if focused["obscured_by"]:
                stop["obscured_by"] = focused["obscured_by"]
            elif focused["share"]:
                issues.append("obscuring box unidentified for " + bid)
            # Timers are controlled; move the common timeline by exactly the observation window.
            driver.advance_clock(500)
            later = _observe(driver, detail=False)
            if later["href"] != focused["href"] or focused["href"] != previous["href"]:
                change = "navigated"
            elif driver._popups > popups:
                change = "new-window"
            elif set(later["dialogs"])-set(previous["dialogs"]):
                change = "dialog-opened"
            elif any(r["method"] == "POST" for r in driver.network.entries[req_index:]):
                change = "submitted"
            elif later["id"] != bid:
                change = "focus-moved"
            else:
                change = "none"
            stop["context_change"] = change
            stops.append(stop)
            if change != "none":
                issues.append("focus changed context on route " + redact.path(route))
                break
        cycle = _cycles(history, focusable-{s["box"] for s in stops})
        if cycle and not any(s.get("in_dialog") in focused["modal_dialogs"] for s in stops if s["box"] in cycle):
            driver.page.keyboard.press("Escape")
            escaped = _observe(driver, detail=False)
            traps.append({"boxes":cycle,"escape_leaves":escaped["id"] not in cycle,"presses": presses})
            if escaped["id"] in cycle:
                issues.append("keyboard trap prevents completing route " + redact.path(route))
                break
            history.clear()
    else:
        if focusable:
            issues.append("Tab press cap reached on " + redact.path(route))
    walked_ids = [s["box"] for s in stops]
    result = {"context":driver.ctx_id,"path":redact.path(route,driver.session.fixture_values),
              "presses":presses,"completed":completed,"stops":stops,"traps":traps,"containers":containers,
              "landmarks":{"main":"main" in initial["landmarks"],"roles":list(dict.fromkeys(initial["landmarks"]))},
              "headings":_headings(initial, stops)}
    if result["landmarks"]["main"] and main_press is not None:
        result["presses_to_main"] = main_press
    elif result["landmarks"]["main"] and focusable:
        issues.append("main landmark was not reached")
    if completed:
        reverse = []
        for _ in range(cap if walked_ids else 0):
            driver.page.keyboard.press("Shift+Tab")
            bid = _observe(driver, detail=False)["id"]
            if bid in walked_ids:
                reverse.append(bid)
            if len(reverse) == len(walked_ids) or bid is None:
                break
        result["reverse_matches"] = reverse == walked_ids[::-1]
        if len(reverse) < len(walked_ids):
            issues.append("reverse traversal did not reach every stop")
        interactive = {box["id"]:box for box in driver.interactive()}
        result["unreachable"] = []
        for bid, box in interactive.items():
            if bid in walked_ids:
                continue
            el = driver.page.locator(f'[data-lapis-box="{bid}"]')
            if not el.count() or el.evaluate("el=>!![...el.querySelectorAll('[data-lapis-box]')].find(x=>x.tabIndex>=0&&x.getBoundingClientRect().width*x.getBoundingClientRect().height>=el.getBoundingClientRect().width*el.getBoundingClientRect().height*.95)"):
                continue
            semantic = box["tag"] in ("button","input","select","textarea","summary") or el.evaluate(
                "el=>!!(el.localName==='a'&&el.hasAttribute('href'))||/^(button|link|checkbox|radio|switch|tab|option|menuitem|combobox|slider|textbox|listbox)$/.test(el.getAttribute('role')||'')")
            result["unreachable"].append({"box":bid,"semantic":semantic})
    else:
        issues.append("incomplete traversal; reverse and unreachable not measured")
    unmeasured = _recover_indicators(driver, route, stops)
    if unmeasured:
        issues.append(f"{unmeasured}/{len(stops)} focus indicators unmeasured after replay on {redact.path(route)}")
    def same_page_skip(stop):

        if box_by_id[stop["box"]]["tag"] != "a":
            return False
        href = driver.page.locator(f'[data-lapis-box="{stop["box"]}"]').get_attribute("href", timeout=1000) or ""
        dest = urlsplit(urljoin(driver.page.url, href))
        here = urlsplit(driver.page.url)
        return bool(dest.fragment and (dest.scheme, dest.netloc, dest.path) == (here.scheme, here.netloc, here.path))
    skip = next((s for s in stops[:3] if same_page_skip(s)), None)
    if skip:
        # A separate fresh load preserves the ordinary walk and prevents an activated link
        # from disguising the plain-Tab count.
        driver.open(route)
        driver.page.locator(f'[data-lapis-box="{skip["box"]}"]').focus()
        driver.page.keyboard.press("Enter")
        activated = _observe(driver, detail=False)
        driver.page.keyboard.press("Tab")
        next_id = _observe(driver, detail=False)["id"]
        landed = next((s["index"] for s in stops if s["box"] == next_id), None)
        if activated["id"] == skip["box"] and landed == skip["index"]+1:
            landed = None
        result["skip_link"] = {"present":True,"box":skip["box"],"index":skip["index"],"lands_at":landed}
    else:
        result["skip_link"] = {"present":False}
    if initial_href != driver.session.url_for(route):
        issues.append("route redirected on load")
    return result, issues


def run(session, open_driver):
    entry = urlsplit(session.source["url"]).path or "/"
    all_issues = []
    contexts = []
    for context in session.matrix:
        contexts.append(context)
        try:
            driver = open_driver(context)
        except Exception as exc:
            all_issues.append(f"{context} load: " + redact.console(
                f"{type(exc).__name__}: {exc}", session.fixture_values)[:120])
            continue
        try:
            routes = _paths(session, entry)
            index = 0
            while index < len(routes) and index < 5:
                route = routes[index]
                try:
                    result, issues = _walk(driver, route)
                except Exception as exc:
                    all_issues.append(f"{context} {redact.path(route)}: " + redact.console(
                        f"{type(exc).__name__}: {exc}", session.fixture_values)[:120])
                    index += 1
                    continue
                session.add_probe("keyboard", result)
                all_issues.extend(f"{context}: {issue}" for issue in issues)
                if index == 0:
                    try:
                        _route_links(driver, result, routes)
                    except Exception as exc:
                        all_issues.append(f"{context} entry links: " + redact.console(
                            f"{type(exc).__name__}: {exc}", session.fixture_values)[:120])
                index += 1
        finally:
            driver.close()
    observed = session.probes.get("keyboard", [])
    status = ("partial" if all_issues or len(contexts)<2 else
              "not-applicable" if observed and all(not w["stops"] and not w.get("unreachable") for w in observed)
              else "ran")
    session.cover("keyboard", status, contexts=contexts,
                  reason="; ".join(dict.fromkeys(all_issues)) if all_issues else
                         ("context unavailable" if status == "partial" else None))
