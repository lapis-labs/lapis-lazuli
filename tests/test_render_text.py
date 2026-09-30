"""Browser-observed measured text fields and resulting derivations."""
from __future__ import annotations

from time import perf_counter

import pytest

import lapis_design.render.fields as fields
from lapis_design.render import _configs
from lapis_design.render.capture import capture
from lapis_design.render.color import contrast_ratio, to_oklch
from lapis_design.render.extract import assemble, validate
from lapis_design.render.fields import text


@pytest.fixture(scope='module')
def measured(browser, render_server: str, tmp_path_factory):
    out = tmp_path_factory.mktemp('render-text') / 'text.png'
    url = f'{render_server}/text-measured.html'
    key = bytes(range(32))
    timing = {}
    actual_apply = text.apply

    def timed(view, vp):
        start = perf_counter()
        actual_apply(view, vp)
        timing['pass'] = perf_counter() - start
        assert view.page.evaluate("""() => ({
          leftover: !!document.querySelector('#lapis-text-backdrop-style, #lapis-text-no-transition, [data-lapis-text-clip]'),
          runNodes: !!window.__lapisRunNodes,
          color: getComputedStyle(document.querySelector('#state')).color
        })""") == {'leftover': False, 'runNodes': False, 'color': 'rgb(255, 255, 255)'}

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(fields, 'FIELD_MODULES', (text,))
        monkeypatch.setattr(text, 'apply', timed)
        viewport = capture(browser, url, _configs(False, [390])[0], out, key)
    viewport['screenshot'] = out.name
    assert validate(assemble(url, "text-fields", [viewport], key, dark_theme=False)) == []
    return viewport, timing['pass']


def _run(vp, value):
    return next(run for run in vp['text'] if value in run['text'])


def test_typography_roles_and_wrapped_measure(measured):
    vp, _ = measured
    expected = {
        'Display heading': 'display', 'Secondary heading': 'heading',
        'Block-based heading': 'heading',
        'Opening body copy': 'body', 'Navigation item': 'nav',
        'State button': 'ui', 'Standalone action': 'ui',
        'const answer': 'code', 'nav() => 2': 'code',
        '429.00': 'data', '€19': 'data', '€29': 'data',
        'Picture caption': 'caption', 'Small label': 'label', 'Field label': 'ui',
    }
    for value, role in expected.items():
        assert _run(vp, value)['type_role'] == role
    wrapped = _run(vp, 'We measure words')
    assert wrapped['lines'] >= 2
    assert 15 < wrapped['measure_chars'] < len(wrapped['text'])
    assert vp['derived']['type_fingerprint']['measure_chars'] > 0


def test_link_in_body_text_is_body_and_other_links_are_ui(measured):
    vp, _ = measured
    assert _run(vp, 'Inline body sentence')['type_role'] == 'body'
    assert _run(vp, 'an inline link')['type_role'] == 'body'
    assert _run(vp, 'Listed link')['type_role'] == 'ui'           # alone in its list item
    assert _run(vp, 'Standalone action')['type_role'] == 'ui'


def test_gradient_weakest_stop_and_backdrop_sources(measured):
    vp, _ = measured
    gradient = _run(vp, 'Weakest gradient stop')
    assert gradient['fill'] == 'gradient'
    assert gradient['color'] == pytest.approx(to_oklch('rgb(238 238 238)'), abs=.02)
    assert gradient['backdrop']['kind'] == 'solid'
    flat = _run(vp, 'Flat background text')
    assert flat['backdrop']['kind'] == 'solid'
    assert flat['backdrop']['oklch'] == pytest.approx(to_oklch('rgb(190 233 209)'), abs=.02)
    assert _run(vp, 'Gradient background text')['backdrop']['kind'] == 'gradient'
    assert _run(vp, 'Image background text')['backdrop']['kind'] == 'image'
    for run in (flat, gradient):
        assert contrast_ratio(run['color'], run['backdrop']['worst']) > 0


def test_hover_and_synthetic_bold(measured):
    vp, _ = measured
    button = _run(vp, 'State button')
    assert set(button['states']) == {'hover', 'focus', 'active'}
    assert set(_run(vp, 'Navigation item')['states']) == {'hover', 'focus', 'active'}
    assert set(_run(vp, 'Standalone action')['states']) == {'hover', 'focus', 'active'}
    assert button['states']['hover']['color'] == pytest.approx(to_oklch('rgb(255 48 64)'), abs=.02)
    assert button['states']['hover']['backdrop'] == pytest.approx(to_oklch('rgb(237 237 237)'), abs=.03)
    assert button['states']['focus']['color'] != button['states']['active']['color']
    assert _run(vp, 'Synthetic bold face')['font']['synthetic'] == 'bold'
    assert _run(vp, 'Synthetic italic face')['font']['synthetic'] == 'italic'
    assert _run(vp, 'Synthetic both faces')['font']['synthetic'] == 'both'
    assert _run(vp, 'Opening body copy')['font']['synthetic'] == 'none'


def test_inked_line_symmetry(measured):
    vp, _ = measured
    assert 0 < vp['derived']['symmetry'] < 1
    assert 0 < vp['derived']['density'] < .5  # Small label's captured box is the whole section.


def test_symmetry_uses_ink_extents_not_full_width_paragraph(browser, render_server, tmp_path):
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(fields, 'FIELD_MODULES', (text,))
        config = _configs(False, [390])[0]
        url = f'{render_server}/text-symmetry.html'
        center = capture(browser, url, config, tmp_path / 'center.png', bytes(range(32)))
        left = capture(browser, url + '?left', config, tmp_path / 'left.png', bytes(range(32)))
    assert center['derived']['symmetry'] == pytest.approx(1, abs=.0001)
    assert left['derived']['symmetry'] < .5
    assert _run(center, 'Short inked line')['measure_chars'] == len('Short inked line')


def test_density_uses_document_height_not_last_box_bottom():
    from lapis_design.render.derived import derive

    box = {'id': 'one', 'role': 'text', 'parent': None,
           'rect': {'x': 0, 'y': 0, 'w': 100, 'h': 20},
           'style': {'background': [1, 0, 0]}}
    viewport = {'width': 100, 'boxes': [box], 'text': []}
    result = derive(viewport, {}, 100, page_height=400)
    assert result['density'] == .05


def test_density_uses_sparse_line_rect_not_tall_section():
    from lapis_design.render.derived import derive

    section = {'id': 'section', 'role': 'section', 'parent': None,
               'rect': {'x': 0, 'y': 0, 'w': 100, 'h': 1000},
               'style': {}}
    run = {'id': 'small', 'box': 'section', 'text': 'Label', 'chars': 5, 'size_px': 12}
    viewport = {'width': 100, 'boxes': [section], 'text': [run]}
    lines = {'small': [{'x': 2, 'y': 10, 'w': 20, 'h': 10}]}
    result = derive(viewport, {}, 100, page_height=1000, line_extents=lines)
    assert result['density'] == .002
    assert result['symmetry'] == .24


def test_density_unions_ink_with_media_and_control_boxes():
    from lapis_design.render.derived import derive

    def box(ident, role, x, width):
        return {'id': ident, 'role': role, 'parent': None,
                'rect': {'x': x, 'y': 10, 'w': width, 'h': 10}, 'style': {}}

    text_box = box('container', 'section', 0, 100)
    text_box['rect']['h'] = 990
    media = box('media', 'media', 10, 20)
    button = box('button', 'button', 40, 10)
    viewport = {'width': 100, 'boxes': [text_box, media, button],
                'text': [{'id': 'ink', 'box': 'container', 'chars': 5, 'size_px': 12}]}
    lines = {'ink': [{'x': 2, 'y': 10, 'w': 20, 'h': 10}]}
    result = derive(viewport, {}, 100, page_height=1000, line_extents=lines)
    assert result['density'] == .0038  # 28 px covered in line row plus 10 px button.


def test_text_pass_capture_duration(measured):
    _, duration = measured
    print(f'text pass per-capture: {duration:.3f}s')
