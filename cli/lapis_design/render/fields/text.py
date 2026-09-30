"""Measured typography, pixel backdrops, and interactive text states.

The browser keeps source text nodes for each run until capture closes. Run geometry
is read in batches, and each state's backdrop uses one decoded full-page DPR-2
image. All interactive boxes receive the same forced pseudo state together; nested
interactive boxes may consequently affect one another rather than being isolated.
"""
from __future__ import annotations

import io
import math
import re
from collections import Counter, defaultdict
from statistics import median

import numpy as np
from PIL import Image

from lapis_design.render.color import contrast_ratio, delta_e_ok, to_oklch
from lapis_design.render.raw import RawView


_GEOMETRY = r"""locators => {
  const faces = [...document.fonts].map(f => ({family:f.family.replace(/^['\"]|['\"]$/g,''),
    weight:f.weight, style:f.style, status:f.status}));
  const result = {};
  // A run's text block: the nearest ancestor-or-self of its element that is not laid out inline.
  const blocks = new Map();
  const blockOf = element => {
    let block = element;
    while (block.parentElement && ['inline', 'contents'].includes(getComputedStyle(block).display))
      block = block.parentElement;
    if (!blocks.has(block)) blocks.set(block, blocks.size);
    return blocks.get(block);
  };
  for (const [id,index] of Object.entries(locators)) {
    const nodes = window.__lapisRunNodes?.[index] || [];
    if (!nodes.length) continue;
    const element = nodes[0].parentElement;
    const style = getComputedStyle(element);
    const ancestor = [];
    for (let p=element;p;p=p.parentElement) {
      const s=getComputedStyle(p);
      ancestor.push({tag:p.localName,role:p.getAttribute('role') || '',box:p.getAttribute('data-lapis-box'),
        href:p.hasAttribute('href'),background:s.backgroundImage,clip:s.backgroundClip,
        text:p.textContent?.trim().slice(0,100) || ''});
    }
    const closest = element.closest('a[href],button,input,select,textarea,[role="button"],[role="link"],[role="textbox"],[role="searchbox"]');
    const lines = new Map();
    const range = document.createRange();
    for (const node of nodes) {
      const source = node.nodeValue;
      for (let i=0;i<source.length;) {
        const character = String.fromCodePoint(source.codePointAt(i));
        const end=i+character.length;
        range.setStart(node,i);range.setEnd(node,end);
        const rect=range.getBoundingClientRect();
        if (rect.width>0 && rect.height>0) {
          const y=Math.round((rect.y+scrollY)*2)/2;
          if (!lines.has(y)) lines.set(y,{count:0,left:Infinity,right:-Infinity,boxes:[]});
          const line=lines.get(y);
          line.count++;
          if (!/^\s$/u.test(character)) {
            line.left=Math.min(line.left,rect.left+scrollX);
            line.right=Math.max(line.right,rect.right+scrollX);
            line.boxes.push([rect.left+scrollX,rect.top+scrollY,rect.width,rect.height]);
          }
        }
        i=end;
      }
    }
    const next=element.nextElementSibling;
    const body=next?.matches('p,li,dd,blockquote') ? next :
      next?.querySelector('p,li,dd,blockquote');
    result[id]={lines:[...lines.entries()].sort((a,b)=>a[0]-b[0]).map(([y,line])=>({y,...line})),
      ancestors:ancestor, interactive:closest?.getAttribute('data-lapis-box') || null,
      block:blockOf(element),
      firstBlock:['block','flex','grid','list-item','flow-root'].includes(style.display),
      followedByBody:!!body && !!body.textContent.trim(),
      nextTag:next?.localName || '',nextText:next?.textContent?.trim().slice(0,60) || '',
      color:style.color, fillColor:style.webkitTextFillColor,
      synthesisWeight:style.fontSynthesisWeight,synthesisStyle:style.fontSynthesisStyle,
      fontSynthesis:style.fontSynthesis};
  }
  return {runs:result, faces};
}"""

_COLOR = re.compile(r"(?:rgba?|hsla?|oklch|oklab|lab|lch|color)\([^()]*\)", re.I)


def _roles(runs: list[dict], info: dict[str, dict], boxes: list[dict]) -> None:
    box_roles = {box['id']: box['role'] for box in boxes}
    paragraph = defaultdict(int)
    overall = defaultdict(int)
    for run in runs:
        size = math.floor(run['size_px'] * 2 + 0.5) / 2
        overall[size] += run['chars']
        ancestors = info.get(run['id'], {}).get('ancestors', [])
        if any(a['tag'] in ('p', 'li', 'dd', 'blockquote') for a in ancestors) or run.get('lines', 0) >= 2:
            paragraph[size] += run['chars']
    groups = paragraph or overall
    body_size = max(groups, key=lambda size: (groups[size], -size)) if groups else 0
    heading = [r for r in runs if any(a['tag'] in ('h1','h2','h3','h4','h5','h6') or
               a['role'] == 'heading' for a in info.get(r['id'], {}).get('ancestors', []))]
    first_section = next((a['box'] for detail in info.values() for a in detail['ancestors']
                          if a['tag'] == 'section' or a['role'] == 'region'), None)
    in_first = [r for r in heading if first_section is None or any(
        a['box'] == first_section for a in info.get(r['id'], {}).get('ancestors', []))]
    largest = max(in_first, key=lambda r: r['size_px']) if in_first else None
    following = max((r['size_px'] for r in heading if r is not largest), default=0)
    display = largest['id'] if largest and following and largest['size_px'] >= 1.5 * following else None
    body_weights = [r['weight'] for r in runs if math.floor(r['size_px'] * 2 + 0.5) / 2 == body_size]
    body_weight = median(body_weights) if body_weights else 400
    columns = {}
    for run in runs:
        content = run.get('text', '').strip()
        if not re.fullmatch(r'[$€£¥₩₹+\-\d\s.,/%°a-zA-Z]+', content) or not any(
                char.isdigit() for char in content):
            continue
        digits = sum(char.isdigit() for char in content)
        if digits < max(1, len(content.replace(' ', '')) * .35):
            continue
        lines = info.get(run['id'], {}).get('lines', [])
        if lines and lines[0]['left'] < lines[0]['right']:
            columns[run['id']] = [lines[0]['left'], lines[0]['right'], lines[0]['y']]
    aligned = {ident for ident, (left, right, y) in columns.items()
               if any(other != ident and abs(y - oy) > 2 and
                      (abs(left - ol) <= 4 or abs(right - ore) <= 4)
                      for other, (ol, ore, oy) in columns.items())}
    in_link = set()
    link_only = []
    for run in runs:
        detail = info.get(run['id'], {})
        ancestors = detail.get('ancestors', [])
        tags = {a['tag'] for a in ancestors}
        aria = {a['role'].split()[0] for a in ancestors if a['role']}
        size = run['size_px']
        text = run.get('text', '')
        link = any(a['tag'] == 'a' and a['href'] for a in ancestors) or 'link' in aria
        if link:
            in_link.add(run['id'])
        control = tags & {'button','input','select','textarea','label'} or aria & {
            'button','textbox','searchbox','listbox','combobox','checkbox','radio','switch','slider'}
        if tags & {'code','pre','kbd','samp'}:
            role = 'code'
        elif tags & {'td','th'} or run['id'] in aligned:
            role = 'data'
        elif 'nav' in tags or 'navigation' in aria:
            role = 'nav'
        elif control or link:
            role = 'ui'
            if not control:
                link_only.append(run)
        elif run['id'] == display:
            role = 'display'
        elif tags & {'h1','h2','h3','h4','h5','h6'} or 'heading' in aria or (
                run['chars'] <= 80 and detail.get('firstBlock') and
                detail.get('followedByBody') and
                (size >= body_size * 1.1 or run['weight'] >= body_weight + 200)):
            role = 'heading'
        elif run['chars'] <= 40 and size < body_size and (
                detail.get('nextTag') in {'h1','h2','h3','h4','h5','h6'} or
                (detail.get('nextText') and any(c.isdigit() for c in detail['nextText']))):
            role = 'label'
        elif 'figcaption' in tags or 'small' in tags or (size < body_size and
                (tags & {'figure','article','footer'} or aria & {'contentinfo','img'} or
                 any(box_roles.get(a['box']) in {'media', 'card'} for a in ancestors))):
            role = 'caption'
        elif math.floor(size * 2 + 0.5) / 2 == body_size:
            role = 'body'
        else:
            role = 'other'
        run['type_role'] = role
    # A link inside a text block whose other runs (those outside links) are all body is body.
    blocks = defaultdict(list)
    for run in runs:
        if (block := info.get(run['id'], {}).get('block')) is not None and run['id'] not in in_link:
            blocks[block].append(run['type_role'])
    for run in link_only:
        others = blocks.get(info.get(run['id'], {}).get('block'), [])
        if others and all(role == 'body' for role in others):
            run['type_role'] = 'body'


def _rgb_color(pixel: tuple[int, int, int]) -> list[float]:
    return to_oklch(f'rgb({pixel[0]} {pixel[1]} {pixel[2]})')


def _pixels(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert('RGB'))


def _ink_extents(original: np.ndarray, backdrop: np.ndarray,
                 detail: dict, dpr: int) -> list[dict[str, float]]:
    """Pixel-difference line rectangles exclude whitespace and side bearings."""
    height, width = original.shape[:2]
    result = []
    for line in detail['lines']:
        if not line['boxes']:
            continue
        x0 = max(0, math.floor(min(box[0] for box in line['boxes']) * dpr))
        y0 = max(0, math.floor(min(box[1] for box in line['boxes']) * dpr))
        x1 = min(width, math.ceil(max(box[0] + box[2] for box in line['boxes']) * dpr))
        y1 = min(height, math.ceil(max(box[1] + box[3] for box in line['boxes']) * dpr))
        if x1 <= x0 or y1 <= y0:
            continue
        before = original[y0:y1, x0:x1].astype(np.int16)
        after = backdrop[y0:y1, x0:x1].astype(np.int16)
        ink = np.any(np.abs(before - after) >= 12, axis=2)
        xs = np.flatnonzero(np.any(ink, axis=0))
        ys = np.flatnonzero(np.any(ink, axis=1))
        if xs.size and ys.size:
            result.append({'x': round((x0 + int(xs[0])) / dpr, 2),
                           'y': round((y0 + int(ys[0])) / dpr, 2),
                           'w': round((int(xs[-1]) - int(xs[0]) + 1) / dpr, 2),
                           'h': round((int(ys[-1]) - int(ys[0]) + 1) / dpr, 2)})
    return result


def _backdrop(image: np.ndarray, geometry: dict, color: list[float] | None,
              media: list[dict], dpr: int, stops: list[list[float]] | None = None
              ) -> tuple[dict | None, list[float] | None]:
    height, width = image.shape[:2]
    points = []
    sources = Counter()
    ancestors = geometry['ancestors']
    for line in geometry['lines']:
        for x, y, w, h in line['boxes']:
            source = next((('image' if a['tag'] in ('img','picture','video','canvas') or
                            re.search(r'\burl\(', a['background']) else 'gradient')
                           for a in ancestors if a['clip'] != 'text' and
                           (a['tag'] in ('img','picture','video','canvas') or
                            re.search(r'\burl\(|gradient\(', a['background']))), None)
            if source is None and any(b['rect']['x'] <= x+w/2 <= b['rect']['x']+b['rect']['w'] and
                                      b['rect']['y'] <= y+h/2 <= b['rect']['y']+b['rect']['h']
                                      for b in media):
                source = 'image'
            for fx in (.3, .5, .7):
                for fy in (.3, .5, .7):
                    px, py = int((x+w*fx)*dpr), int((y+h*fy)*dpr)
                    if 0 <= px < width and 0 <= py < height:
                        points.append(tuple(map(int, image[py,px])))
                        sources[source] += 1
    if not points:
        return None, None
    unique = {_pixel: _rgb_color(_pixel) for _pixel in set(points)}
    midpoint = tuple(int(round(median(channel))) for channel in zip(*points))
    central = _rgb_color(midpoint)
    if stops:
        color = min(stops, key=lambda stop: contrast_ratio(stop, central))
    result = {'oklch': central}
    if color:
        result['worst'] = min(unique.values(), key=lambda pixel: contrast_ratio(color, pixel))
    if all(delta_e_ok(pixel, central) <= .02 for pixel in unique.values()):
        result['kind'] = 'solid'
    elif sources['image'] > len(points) / 2:
        result['kind'] = 'image'
    elif sources['gradient'] > len(points) / 2:
        result['kind'] = 'gradient'
    else:
        result['kind'] = 'mixed'
    return result, color


def _synthetic(run: dict, detail: dict, faces: list[dict], platform: list[dict]) -> str | None:
    """Infer synthesis from the used CDP face and loaded CSS FontFace descriptors.

    Loaded web faces declare supported weight/style ranges in document.fonts; a
    requested bold/slant absent from those ranges is synthesized only when CSS
    font-synthesis allows it. For system faces CDP gives a used PostScript name,
    not a synthetic flag: style tokens identify real bold/italic faces; absent
    style tokens are inconclusive for variable faces, so omit instead of guessing.
    """
    requested = run['font']['requested'].casefold()
    if run['weight'] < 600 and run['style'] == 'normal':
        return 'none'
    loaded = [face for face in faces if face['family'].casefold() == requested and face['status'] == 'loaded']
    if not loaded and not platform:
        return None
    weight = run['weight'] >= 600
    italic = run['style'] in ('italic', 'oblique')
    synthesis = detail.get('fontSynthesis', 'none')
    allow_bold = detail.get('synthesisWeight') != 'none' and synthesis != 'none'
    allow_italic = detail.get('synthesisStyle') != 'none' and synthesis != 'none'

    def matching(face: dict, requested_weight: float, requested_italic: bool) -> bool:
        weights = [float(value) for value in re.findall(r'\d+(?:\.\d+)?', face['weight'])]
        has_weight = bool(weights) and min(weights) <= requested_weight <= max(weights)
        has_style = (face['style'] != 'normal') == requested_italic
        return has_weight and has_style

    if loaded:
        bold = weight and allow_bold and not any(matching(f, run['weight'], italic) for f in loaded)
        slant = italic and allow_italic and not any(matching(f, run['weight'], True) for f in loaded)
    else:
        used = max(platform, key=lambda face: face.get('glyphCount', 0))
        name = used.get('postScriptName', '').lower()
        if not name or (weight and not re.search(r'bold|heavy|black|semibold|demi', name)) or (
                italic and not re.search(r'italic|oblique', name)):
            return None
        bold = slant = False
    return 'both' if bold and slant else 'bold' if bold else 'italic' if slant else 'none'


def _node_ids(view: RawView, ids: set[str]) -> dict[str, int]:
    """Resolve all required box backend IDs with one CDP snapshot and push."""
    if not ids:
        return {}
    snapshot = view.cdp.send('DOMSnapshot.captureSnapshot', {'computedStyles': []})
    strings = snapshot['strings']
    nodes = snapshot['documents'][0]['nodes']
    backends = {}
    for backend, attributes in zip(nodes['backendNodeId'], nodes['attributes']):
        for i in range(0, len(attributes), 2):
            if strings[attributes[i]] == 'data-lapis-box':
                ident = strings[attributes[i + 1]]
                if ident in ids and backend:
                    backends[ident] = backend
                break
    names = list(backends)
    if not names:
        return {}
    found = view.cdp.send('DOM.pushNodesByBackendIdsToFrontend', {
        'backendNodeIds': [backends[name] for name in names]})['nodeIds']
    return {name: node for name, node in zip(names, found) if node}


def _platform_fonts(view: RawView, vp: dict, nodes: dict[str, int]) -> dict[str, list[dict]]:
    needed = {run['box'] for run in vp['text'] if run['weight'] >= 600 or
              run['style'] in ('italic', 'oblique')}
    return {box: view.cdp.send('CSS.getPlatformFontsForNode', {'nodeId': nodes[box]})['fonts']
            for box in needed & nodes.keys()}


def _gradient_stops(background: str) -> list[list[float]]:
    return [converted for css in _COLOR.findall(background) if (converted := to_oklch(css))]


def _set_backdrop_mode(view: RawView, enabled: bool) -> None:
    view.page.evaluate("""enabled => {
      if (enabled) {
        const style=document.createElement('style');
        style.id='lapis-text-backdrop-style';
        style.textContent='* , *::before, *::after { color: transparent !important; -webkit-text-fill-color: transparent !important; } [data-lapis-text-clip] { background-image: none !important; }';
        document.head.append(style);
        const changed=[];
        for(const element of document.querySelectorAll('*')) {
          if(getComputedStyle(element).backgroundClip === 'text') {
            changed.push([element,element.getAttribute('data-lapis-text-clip')]);
            element.setAttribute('data-lapis-text-clip','');
          }
        }
        window.__lapisTextBackdropChanged=changed;
      } else {
        document.getElementById('lapis-text-backdrop-style')?.remove();
        for(const [element,value] of window.__lapisTextBackdropChanged || []) {
          if(value===null) element.removeAttribute('data-lapis-text-clip');
          else element.setAttribute('data-lapis-text-clip',value);
        }
        delete window.__lapisTextBackdropChanged;
      }
    }""", enabled)


def apply(view: RawView, vp: dict) -> None:
    """Enrich captured runs and leave the live page/CDP pseudo states as found."""
    if not vp['text']:
        return
    geometry = view.page.evaluate(_GEOMETRY, view.extra['run_locators'])
    info, faces = geometry['runs'], geometry['faces']
    _roles(vp['text'], info, vp['boxes'])
    interactive = defaultdict(list)
    for run in vp['text']:
        detail = info.get(run['id'])
        if detail and detail['lines']:
            run['measure_chars'] = round(median(line['count'] for line in detail['lines']), 4)
        if not detail:
            continue
        fill = to_oklch(detail['fillColor'])
        clipped = next((a for a in detail['ancestors'] if a['clip'] == 'text' and
                        a['background'] != 'none'), None)
        run['fill'] = 'gradient' if clipped else 'transparent' if fill is None else 'solid'
        if detail['interactive']:
            interactive[detail['interactive']].append(run)
    font_boxes = {run['box'] for run in vp['text'] if run['weight'] >= 600 or
                  run['style'] in ('italic', 'oblique')}
    nodes = _node_ids(view, font_boxes | interactive.keys())
    fonts = _platform_fonts(view, vp, nodes)
    for run in vp['text']:
        detail = info.get(run['id'])
        if detail and (synthetic := _synthetic(run, detail, faces, fonts.get(run['box'], []))):
            run['font']['synthetic'] = synthetic
    media = [box for box in vp['boxes'] if box['role'] == 'media']
    scroll = view.page.evaluate('({x:scrollX,y:scrollY})')
    backdrop_mode = False
    forced: list[int] = []
    state_style = False
    try:
        view.page.evaluate("""() => {
          const style = document.createElement('style');
          style.id = 'lapis-text-no-transition';
          style.textContent = '*,*::before,*::after { transition: none !important; }';
          document.head.append(style);
        }""")
        state_style = True
        _set_backdrop_mode(view, True)
        backdrop_mode = True
        base = _pixels(view.page.screenshot(full_page=True))
        original = _pixels(view.screenshot_path.read_bytes())
        view.extra['line_extents'] = {
            run['id']: _ink_extents(original, base, info[run['id']], view.config['dpr'])
            for run in vp['text'] if run['id'] in info}
        for run in vp['text']:
            detail = info.get(run['id'])
            if not detail:
                continue
            stops = []
            if run['fill'] == 'gradient':
                layer = next((a['background'] for a in detail['ancestors'] if a['clip'] == 'text' and
                              a['background'] != 'none'), '')
                stops = _gradient_stops(layer)
            sampled, selected = _backdrop(base, detail, run.get('color'), media,
                                           view.config['dpr'], stops)
            if selected and stops:
                run['color'] = selected
            if sampled:
                run['backdrop'] = sampled
        active = [run for box, associated in interactive.items() if box in nodes
                  for run in associated]
        if active:
            target_nodes = [nodes[box] for box in interactive if box in nodes]
            locators = {run['id']: view.extra['run_locators'][run['id']] for run in active}
            for name, pseudo in (('hover', 'hover'), ('focus', 'focus-visible'), ('active', 'active')):
                for node in target_nodes:
                    view.cdp.send('CSS.forcePseudoState', {
                        'nodeId': node, 'forcedPseudoClasses': [pseudo]})
                    forced.append(node)
                _set_backdrop_mode(view, False)
                backdrop_mode = False
                state_geometry = view.page.evaluate(_GEOMETRY, locators)['runs']
                _set_backdrop_mode(view, True)
                backdrop_mode = True
                image = _pixels(view.page.screenshot(full_page=True))
                for run in active:
                    detail = state_geometry.get(run['id'])
                    if not detail:
                        continue
                    color = to_oklch(detail['fillColor'])
                    if color is None:
                        continue
                    entry = {'color': color}
                    sampled, _ = _backdrop(image, detail, color, media, view.config['dpr'])
                    if sampled:
                        entry['backdrop'] = sampled['oklch']
                    run.setdefault('states', {})[name] = entry
                for node in forced:
                    view.cdp.send('CSS.forcePseudoState', {
                        'nodeId': node, 'forcedPseudoClasses': []})
                forced.clear()
    finally:
        for node in forced:
            view.cdp.send('CSS.forcePseudoState', {
                'nodeId': node, 'forcedPseudoClasses': []})
        if backdrop_mode:
            _set_backdrop_mode(view, False)
        if state_style:
            view.page.evaluate("() => { void document.body.offsetWidth; void getComputedStyle(document.body).color; }")
        if state_style:
            view.page.evaluate("document.getElementById('lapis-text-no-transition')?.remove()")
        view.page.evaluate('position => window.scrollTo(position.x,position.y)', scroll)
        view.page.evaluate('delete window.__lapisRunNodes')
