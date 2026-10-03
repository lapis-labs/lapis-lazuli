"""Measure accessibility, interaction, motion, overflow and layout shifts.

Record a11y on controls, links, headings, landmarks, media, icons and dialogs,
and on boxes with a pointer/keyboard handler, pointer cursor or explicit tabindex.
Ordinary layout/text wrappers do not get an empty accessibility object.
"""
from __future__ import annotations

import re

from lapis_design.render import detached
from lapis_design.render.color import delta_e_ok, to_oklch
from lapis_design.render.raw import RawView

INIT_SCRIPT = r"""(() => {
  const shifts = [];
  window.__lapisShifts = shifts;
  const record = list => {
    for (const entry of list) {
      if (!entry.hadRecentInput) shifts.push({value: entry.value,
        nodes: (entry.sources || []).map(source => source.node).filter(Boolean)});
    }
  };
  const observer = new PerformanceObserver(list => record(list.getEntries()));
  observer.observe({type: 'layout-shift', buffered: true});
  window.__lapisShiftObserver = {observer, record};
})()"""

_REST_START = r"""() => {
  const state = new Map();
  for (const el of document.querySelectorAll('*')) {
    const s = getComputedStyle(el);
    if (s.animationName === 'none' && s.transform === 'none' && Number(s.opacity) >= .05) continue;
    const r = el.getBoundingClientRect();
    state.set(el, {x:r.x + scrollX, y:r.y + scrollY, w:r.width, h:r.height,
                   opacity:Number(s.opacity), transform:s.transform});
  }
  window.__lapisRest = state;
}"""
# Layout shifts count from navigation start until the network has been idle for 1 s after the last
# scroll step, so lazy content loaded by the scroll pass is included (render/DERIVED.md, metrics).
_CLS_END = r"""() => {
  const tracker = window.__lapisShiftObserver;
  if (tracker) {
    tracker.record(tracker.observer.takeRecords());
    tracker.observer.disconnect();
  }
  const entries = window.__lapisShifts || [];
  window.__lapisCls = {value:entries.reduce((total, entry) => total+entry.value, 0),
                       nodes:entries.flatMap(entry => entry.nodes)};
}"""
_REST_END = r"""() => {
  const reveal = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting && scrollY > 0)
      window.__lapisRest.get(entry.target).scrolledIntoView = true;
  });
  for (const [el, start] of window.__lapisRest) {
    const r = el.getBoundingClientRect(), style = getComputedStyle(el);
    start.moves = Math.abs(start.x - r.x - scrollX) > 1 ||
                  Math.abs(start.y - r.y - scrollY) > 1 ||
                  Math.abs(start.w - r.width) > 1 || Math.abs(start.h - r.height) > 1;
    start.restOpacity = Number(style.opacity);
    start.restTransform = style.transform;
    if (start.opacity < .05 || start.transform !== 'none') reveal.observe(el);
  }
  window.__lapisRevealObserver = reveal;
}"""

# One traversal reads computed longhands, animation keyframes, geometry and event props.
_MEASURE = r"""() => {
  const result = {};
  const expand = name => {
    name=name.replace(/[A-Z]/g, c => '-'+c.toLowerCase());
    if (name === 'all' || name === 'none' || name.startsWith('--')) return [name];
    const style = document.createElement('span').style;
    for (const value of ['1px', 'red', '1px solid red', '1', 'auto', 'none',
                         'italic 12px Arial', 'translateX(1px)']) {
      style.setProperty(name, value);
      if (style.length) return [...style].sort();
    }
    return [name];
  };
  const state = el => {
    const s = getComputedStyle(el), fields = {};
    for (const name of s) fields[name] = s.getPropertyValue(name);
    return fields;
  };
  for (const el of document.querySelectorAll('[data-lapis-box]')) {
    const id=el.getAttribute('data-lapis-box'), s=getComputedStyle(el), r=el.getBoundingClientRect();
    const scrollCandidate = ['auto','scroll'].includes(s.overflowX) ||
      ['auto','scroll'].includes(s.overflowY) || el.matches('ul,ol,dl,table,[role=list]');
    const children=scrollCandidate ? [...el.children].filter(child =>
      getComputedStyle(child).display !== 'none') : [];
    const first=children[0]?.getBoundingClientRect(), last=children.at(-1)?.getBoundingClientRect();
    const props = Object.getOwnPropertyNames(el).filter(k => /^__reactProps\$/.test(k))
      .flatMap(k => Object.entries(el[k] || {}));
    const own = props.some(([key,value]) => typeof value === 'function' &&
      /^on(?:Click|DoubleClick|AuxClick|Pointer|Mouse)/.test(key));
    const keys = props.some(([key,value]) => typeof value === 'function' && /^onKey/.test(key));
    const animations = [...el.getAnimations({subtree:false})].filter(a => a instanceof CSSAnimation)
      .map(a => {
        const frames = a.effect.getKeyframes();
        return {name:a.animationName,
          properties:[...new Set(frames.flatMap(frame =>
            Object.keys(frame).filter(k => !['offset','easing','composite','computedOffset'].includes(k))
              .flatMap(k => expand(k))))].sort(),
          stepped:frames.some(frame => frame.easing?.includes('steps('))};
      });
    const transitionProperties=s.transitionProperty.split(',').map(x => x.trim());
    const transitionDurations=s.transitionDuration.split(',').map(x => x.trim());
    const transitionDelays=s.transitionDelay.split(',').map(x => x.trim());
    const transitionEasing=s.transitionTimingFunction.split(/,(?![^()]*\))/).map(x => x.trim());
    const transitions=transitionProperties.map((name,i) => ({
      properties:expand(name),
      duration:transitionDurations[i % transitionDurations.length],
      delay:transitionDelays[i % transitionDelays.length],
      easing:transitionEasing[i % transitionEasing.length]
    }));
    const animationNames=s.animationName.split(',').map(x => x.trim());
    const animationDurations=s.animationDuration.split(',').map(x => x.trim());
    const animationIterations=s.animationIterationCount.split(',').map(x => x.trim());
    const animationEasing=s.animationTimingFunction.split(/,(?![^()]*\))/).map(x => x.trim());
    const data={cursor:s.cursor, tabindex:el.hasAttribute('tabindex') ? el.tabIndex : null,
      disabled:el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true',
      hidden:!!el.closest('[aria-hidden="true"], [hidden], [inert]'),
      pointer:own || [...['onclick','onauxclick','ondblclick','onmousedown','onmouseup',
        'onmousemove','onmouseover','onmouseout','onmouseenter','onmouseleave',
        'onpointerdown','onpointerup','onpointermove','onpointerenter','onpointerleave']]
          .some(k => typeof el[k] === 'function'),
      keyboard:keys || ['onkeydown','onkeyup','onkeypress'].some(k => typeof el[k] === 'function'),
      transitions,
      animationNames,animationDurations,animationIterations,animationEasing,animations,
      overflowX:s.overflowX,overflowY:s.overflowY, scrollW:el.scrollWidth,scrollH:el.scrollHeight,
      clientW:el.clientWidth,clientH:el.clientHeight,children:children.length,
      insetsX:first && [first.left-r.left+el.scrollLeft,
                         el.scrollWidth-(last.right-r.left+el.scrollLeft)],
      insetsY:first && [first.top-r.top+el.scrollTop,
                         el.scrollHeight-(last.bottom-r.top+el.scrollTop)],
      textOverflow:s.textOverflow, clamp:s.webkitLineClamp,
      style:state(el)};
    result[id]=data;
  }
  return result;
}"""

_AFTER_SCROLL = r"""() => {
  const result = {};
  for (const [el, rest] of window.__lapisRest || []) {
    const id=el.getAttribute('data-lapis-box');
    if (!id) continue;
    const s=getComputedStyle(el), r=el.getBoundingClientRect();
    result[id]={start:rest, end:{opacity:Number(s.opacity),transform:s.transform,
      x:r.x+scrollX,y:r.y+scrollY}, visible:r.width>0 && r.height>0 &&
      s.visibility==='visible' && s.display!=='none'};
  }
  return {rest:result, shift:(window.__lapisCls?.nodes || [])
    .map(node => node?.closest?.('[data-lapis-box]')?.getAttribute('data-lapis-box') ||
      node?.parentElement?.closest?.('[data-lapis-box]')?.getAttribute('data-lapis-box'))
    .filter(Boolean)};
}"""


def observe_rest(view: RawView) -> None:
    """Sample motion over 2 s without input, after load plus one second."""
    view.page.evaluate(_REST_START)
    view.page.wait_for_timeout(2000)
    view.page.evaluate(_REST_END)


def after_scroll(view: RawView) -> None:
    """Close the layout-shift window at the bottom of the page, before returning to the top."""
    view.page.evaluate(_CLS_END)


def _time(value: str) -> float | None:
    """A computed CSS time in milliseconds, or None for `auto`: a scroll- or view-driven animation
    (`animation-timeline`) has no duration in time."""
    if value == 'auto':
        return None
    return round(float(value[:-2]) if value.endswith('ms') else float(value[:-1])*1000, 4)


def _name_source(node: dict) -> str:
    for item in node.get('name', {}).get('sources', []):
        if item.get('superseded') or not item.get('value', {}).get('value'):
            continue
        native = item.get('nativeSource')
        if native in ('label', 'labelfor', 'labelwrapped', 'legend', 'figcaption'):   # CDP spells them lowercase
            return 'label'
        if native in ('placeholder', 'title', 'alt'):
            return native
        attribute = item.get('attribute')
        if attribute in ('aria-label', 'aria-labelledby', 'title', 'alt', 'placeholder'):
            return attribute
        if item.get('type') == 'contents':
            return 'contents'
    return 'none'


def _is_focus_change(before: dict, after: dict) -> bool:
    for kind in ('outline', 'border'):
        sides = ('',) if kind == 'outline' else ('-top', '-right', '-bottom', '-left')
        for side in sides:
            prefix = kind + side
            a = before.get(prefix+'-width', '0px')
            b = after.get(prefix+'-width', '0px')
            if abs(float(a.removesuffix('px')) - float(b.removesuffix('px'))) >= 2:
                return True
            if a != '0px' or b != '0px':
                if _colors_differ(before.get(prefix+'-color'), after.get(prefix+'-color')):
                    return True
    if _colors_differ(before.get('background-color'), after.get('background-color')):
        return True
    if before.get('box-shadow') != after.get('box-shadow'):
        def extent(shadow: str) -> float:
            lengths = re.findall(r'[-+]?\d*\.?\d+px', re.sub(r'(?:rgba?|hsla?)\([^)]*\)', '', shadow))
            return max((abs(float(n[:-2])) for n in lengths), default=0)
        if abs(extent(before.get('box-shadow', 'none')) - extent(after.get('box-shadow', 'none'))) >= 2:
            return True
        def shadow_color(value: str):
            match = re.search(r'(?:rgba?|hsla?)\([^)]*\)', value)
            return match.group() if match else value
        if _colors_differ(shadow_color(before.get('box-shadow', 'none')),
                          shadow_color(after.get('box-shadow', 'none'))):
            return True
    return False


def _colors_differ(left: str | None, right: str | None) -> bool:
    if left == right:
        return False
    a, b = to_oklch(left or ''), to_oklch(right or '')
    if a is None or b is None:
        visible = a if a else b
        return bool(visible and (visible[3] if len(visible) > 3 else 1) > 0.1)
    return delta_e_ok(a, b) > 0.1 or abs((a[3] if len(a) > 3 else 1) -
                                           (b[3] if len(b) > 3 else 1)) > 0.1


def _dom_nodes(tree: dict) -> dict[str, int]:
    result = {}
    def visit(node: dict):
        attrs = node.get('attributes', [])
        if 'data-lapis-box' in attrs:
            result[attrs[attrs.index('data-lapis-box')+1]] = node['backendNodeId']
        for child in node.get('children', []):
            visit(child)
        for shadow in node.get('shadowRoots', []):
            visit(shadow)
        if node.get('contentDocument'):
            visit(node['contentDocument'])
    visit(tree)
    return result


def _scroll(box: dict, data: dict, viewport_height: float) -> dict | None:
    x = data['overflowX'] in ('auto', 'scroll') and data['scrollW'] > data['clientW'] + 1
    y = data['overflowY'] in ('auto', 'scroll') and data['scrollH'] > data['clientH'] + 1
    page = not x and not y and box['role'] == 'list' and box['rect']['h'] > 3*viewport_height
    if not (x or y or page):
        return None
    axis = 'page' if page else 'both' if x and y else 'x' if x else 'y'
    horizontal = x and (not y or data['scrollW']-data['clientW'] >= data['scrollH']-data['clientH'])
    insets = data['insetsX' if horizontal else 'insetsY']
    value = {'axis':axis, 'items':data['children'],
             'content_px':round(data['scrollW'] if horizontal else data['scrollH'], 2)}
    if insets:
        value.update(inset_start_px=round(insets[0], 2), inset_end_px=round(insets[1], 2))
    return value


def _clipped(data: dict) -> str:
    cut_x = data['overflowX'] in ('hidden', 'clip') and data['scrollW'] > data['clientW']+1
    cut_y = data['overflowY'] in ('hidden', 'clip') and data['scrollH'] > data['clientH']+1
    if cut_y and data['clamp'] not in ('none', '0'):
        return 'line-clamp'
    if cut_x and data['textOverflow'] == 'ellipsis':
        return 'ellipsis'
    return 'overflow' if cut_x or cut_y else 'none'


def _motion(data: dict, rest: dict | None) -> dict:
    result = {}
    transitions = []
    for transition in data['transitions']:
        duration = _time(transition['duration'])
        if transition['properties'] == ['none'] or (transition['properties'] == ['all'] and duration == 0):
            continue
        for name in transition['properties']:
            transitions.append({'property':name, 'duration_ms':duration,
              'delay_ms':_time(transition['delay']), 'easing':transition['easing']})
    if transitions:
        result['transitions'] = transitions
    animations = []
    for i, name in enumerate(data['animationNames']):
        if name == 'none':
            continue
        animation = next((a for a in data['animations'] if a['name']==name), None)
        iteration = data['animationIterations'][i % len(data['animationIterations'])]
        easing = data['animationEasing'][i % len(data['animationEasing'])]
        entry = {'name':name, 'properties':animation['properties'] if animation else []}
        duration = _time(data['animationDurations'][i % len(data['animationDurations'])])
        if duration is not None:                     # no duration_ms for a scroll-driven animation
            entry['duration_ms'] = duration
        entry.update({'iterations': 'infinite' if iteration == 'infinite' else round(float(iteration),4),
          'easing':easing, 'stepped':'steps(' in easing or bool(animation and animation['stepped'])})
        animations.append(entry)
    if animations:
        result['animations']=animations
    if rest is not None:
        start, end = rest['start'], rest['end']
        result['moves_at_rest']=bool(start.get('moves'))
        def displacement(matrix: str) -> float:
            if matrix.startswith('matrix('):
                values = [float(v) for v in matrix[7:-1].split(',')]
                return max(abs(values[4]), abs(values[5]))
            if matrix.startswith('matrix3d('):
                values = [float(v) for v in matrix[9:-1].split(',')]
                return max(abs(values[12]), abs(values[13]))
            return 0
        hidden_opacity = start['opacity'] < .05 and start['restOpacity'] < .05
        hidden_translation = (displacement(start['transform']) - displacement(end['transform']) > 20
                              and abs(displacement(start['transform']) -
                                      displacement(start['restTransform'])) <= 1)
        shown = end['opacity'] >= .05 and displacement(end['transform']) < displacement(start['transform']) + 1
        result['hidden_until_scroll'] = bool((hidden_opacity or hidden_translation) and shown
                                             and rest['visible'] and start.get('scrolledIntoView'))
    return result


def apply(view: RawView, vp: dict) -> None:
    """Fill only measured v1 fields, and undo all forced pseudo-states on exit."""
    measured = view.page.evaluate(_MEASURE)
    after = view.page.evaluate(_AFTER_SCROLL)
    by_id = {box['id']:box for box in vp['boxes']}
    backend = _dom_nodes(view.cdp.send('DOM.getDocument', {'depth':-1,'pierce':True})['root'])
    ax = view.cdp.send('Accessibility.getFullAXTree')['nodes']
    ax_by_backend = {}
    for node in ax:
        ident = node.get('backendDOMNodeId')
        if ident and (ident not in ax_by_backend or ax_by_backend[ident].get('ignored')):
            ax_by_backend[ident] = node
    focus = {id for id, box in by_id.items() if id in measured and (
        box['role'] in ('button','link','input') or measured[id]['tabindex'] is not None)}
    # Batch the post-force DOM reads rather than evaluating once per element.
    node_ids = view.cdp.send('DOM.pushNodesByBackendIdsToFrontend',
                             {'backendNodeIds':list(backend.values())}).get('nodeIds', [])
    front = dict(zip(backend, node_ids))
    hover_ids = set(measured) & front.keys()
    focus_ids = {id for id in focus if id in front}
    try:
        for id in hover_ids:
            detached.send(view.cdp, 'CSS.forcePseudoState', {'nodeId':front[id], 'forcedPseudoClasses':['hover']})
        hovered = view.page.evaluate(r"""ids => {
          // Finish only hover transitions; captured animations stay at their settled state.
          for (const a of document.getAnimations()) if (a instanceof CSSTransition) try { a.finish(); } catch (_) {}
          const out={}; for (const id of ids) {
            const el=document.querySelector('[data-lapis-box="'+id+'"]');
            if (!el) continue;                      // the page took it out of the document
            const s=getComputedStyle(el);
            out[id]=Object.fromEntries([...s].map(k=>[k,s.getPropertyValue(k)]));
          } return out;
        }""", list(hover_ids))
    finally:
        for id in hover_ids:
            detached.send(view.cdp, 'CSS.forcePseudoState', {'nodeId':front[id], 'forcedPseudoClasses':[]})
    try:
        for id in focus_ids:
            detached.send(view.cdp, 'CSS.forcePseudoState', {'nodeId':front[id],
                                                             'forcedPseudoClasses':['focus','focus-visible']})
        focused = view.page.evaluate(r"""ids => {
          for (const a of document.getAnimations()) if (a instanceof CSSTransition) try { a.finish(); } catch (_) {}
          const out={}; for (const id of ids) {
            const el=document.querySelector('[data-lapis-box="'+id+'"]');
            if (!el) continue;
            const s=getComputedStyle(el);
            out[id]=Object.fromEntries([...s].map(k=>[k,s.getPropertyValue(k)]));
          } return out;
        }""", list(focus_ids))
    finally:
        for id in focus_ids:
            detached.send(view.cdp, 'CSS.forcePseudoState', {'nodeId':front[id], 'forcedPseudoClasses':[]})
    for id, box in by_id.items():
        data = measured.get(id)
        if not data:
            detached.mark(box)                      # the page took the box out of the document
            continue
        box['clipped'] = _clipped(data)
        if scroll := _scroll(box,data,view.config['height']):
            box['scroll'] = scroll
        motion = _motion(data, after['rest'].get(id))
        if id in hover_ids:
            if id in hovered:
                change = sorted(k for k, value in data['style'].items() if hovered[id].get(k) != value)
                if change:
                    motion['hover_changes'] = change
            else:
                detached.mark(box)
        if motion:
            box['motion'] = motion
        node = ax_by_backend.get(backend.get(id))
        ax_props = {prop['name']:prop.get('value', {}).get('value')
                    for prop in node.get('properties', [])} if node else {}
        tag = view.elements[id]['tag']
        native = tag in ('button','input','select','textarea','summary') or (
            tag == 'a' and 'href' in view.elements[id]['attrs'])
        if id in front:
            resolved = detached.send(view.cdp, 'DOM.resolveNode', {'nodeId':front[id]})
            object_id = (resolved or {}).get('object',{}).get('objectId')
            if resolved is None:
                detached.mark(box)
            if object_id:
                try:
                    listeners = view.cdp.send('DOMDebugger.getEventListeners', {'objectId':object_id})['listeners']
                    data['pointer'] |= any(re.match(r'^(?:click|dblclick|auxclick|pointer|mouse)', listener['type'])
                                           for listener in listeners)
                    data['keyboard'] |= any(listener['type'].startswith('key') for listener in listeners)
                finally:
                    view.cdp.send('Runtime.releaseObject', {'objectId':object_id})
        candidate = (box['role'] in ('button','link','input','heading','nav','media','icon','dialog','section')
                     or 'media' in box or data['pointer'] or data['keyboard']
                     or data['cursor']=='pointer' or data['tabindex'] is not None)
        if not candidate:
            continue
        a11y = {'focusable':bool(ax_props.get('focusable')),
                'pointer_cursor': data['cursor']=='pointer' and not native,
                'disabled':bool(data['disabled'] or ax_props.get('disabled')),
                'hidden':data['hidden'] or bool(node and node.get('ignored')),
                'keyboard_handler':bool(data['keyboard']), 'pointer_handler':bool(data['pointer'])}
        if node:
            if role := node.get('role',{}).get('value'):
                a11y['role'] = role
            if name := node.get('name',{}).get('value'):
                a11y['name'] = name
                a11y['name_source'] = _name_source(node)
        if data['tabindex'] is not None:
            a11y['tabindex'] = data['tabindex']
        if id in focus_ids:
            if id in focused:
                a11y['focus_indicator'] = _is_focus_change(data['style'], focused[id])
            else:
                detached.mark(box)
        box['a11y'] = a11y
    vp['metrics'] = {'cls':round(view.page.evaluate('window.__lapisCls?.value || 0'),4),
                     'shift_sources':sorted(set(after['shift']) & by_id.keys())}
    view.page.evaluate("""() => {
      window.__lapisRevealObserver?.disconnect();
      delete window.__lapisRest; delete window.__lapisCls;
      delete window.__lapisShifts; delete window.__lapisRevealObserver;
      delete window.__lapisShiftObserver;
    }""")
