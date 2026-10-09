"""Browser-observed measured text fields and resulting derivations."""
from __future__ import annotations

from time import perf_counter

import pytest

import lapis_design.render.fields as fields
from lapis_design.lint.detectors.render_type import contrast, srgb
from lapis_design.render import _configs
from lapis_design.render.capture import capture
from lapis_design.render.color import contrast_ratio, delta_e_ok, to_oklch
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
          leftover: !!document.querySelector('[data-lapis-text-clip]') ||
                    document.adoptedStyleSheets.length > 0 || !!window.__lapisSheets,
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


def _wcag(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """WCAG 2 ratio of two painted sRGB triples, independent of lapis_design."""
    def luminance(rgb):
        lin = [c / 255 / 12.92 if c / 255 <= .04045 else ((c / 255 + .055) / 1.055) ** 2.4 for c in rgb]
        return .2126 * lin[0] + .7152 * lin[1] + .0722 * lin[2]
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + .05) / (low + .05)


# text-csp.css written in oklch() and display-p3: the sRGB the browser paints for each text and surface.
CSP_PAINTED = {
    'Ink token on canvas': ((38, 49, 44), (246, 249, 247)),
    'Tinted surface text': ((22, 35, 48), (232, 243, 255)),
    'Display P3 text': ((55, 24, 10), (245, 229, 201)),
    'Translucent white over blue': ((170, 186, 213), (42, 83, 151)),    # white at 60 % over the surface
    'Barely darker than its surface': ((180, 104, 92), (164, 90, 78)),
}


def test_backdrop_is_measured_on_a_page_whose_csp_blocks_injected_styles(browser, render_server, tmp_path):
    """`style-src 'self'` stops an injected <style>, so the text-free render still showed the text and
    every run measured 1.00:1 against itself."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(fields, 'FIELD_MODULES', (text,))
        vp = capture(browser, f'{render_server}/text-csp.html', _configs(False, [390])[0],
                     tmp_path / 'csp.png', bytes(range(32)))
    for value, (ink, surface) in CSP_PAINTED.items():
        run = _run(vp, value)
        assert run['backdrop']['kind'] == 'solid', value
        assert run['backdrop']['worst'] == pytest.approx(to_oklch(f'rgb{surface}'), abs=.01), value
        assert contrast(run['color'], run['backdrop']['worst']) == pytest.approx(_wcag(ink, surface), rel=.01), value
    button = _run(vp, 'Action button')
    assert delta_e_ok(button['states']['hover']['color'], to_oklch('rgb(187 6 30)')) < .01   # not mid-transition


@pytest.fixture(scope='module')
def hidden_backdrops(browser, render_server, tmp_path_factory):
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(fields, 'FIELD_MODULES', (text,))
        return capture(browser, f'{render_server}/text-backdrop-hidden.html', _configs(False, [390])[0],
                       tmp_path_factory.mktemp('backdrop-hidden') / 'hidden.png', bytes(range(32)))


@pytest.mark.parametrize('value', ['one', 'two', 'five'])
def test_backdrop_is_measured_where_the_text_is_hidden(hidden_backdrops, value):
    """A text color from an `!important` rule hides nothing it paints: the fill stays transparent, so
    `::first-letter` and utility colors leave the surface alone."""
    backdrop = _run(hidden_backdrops, value)['backdrop']
    assert backdrop['kind'] == 'solid'
    assert backdrop['worst'] == pytest.approx(to_oklch('rgb(190 233 209)'), abs=.01)


@pytest.mark.parametrize('value', ['three', 'four', 'six', 'seven'])
def test_backdrop_is_left_out_where_the_text_is_still_painted(hidden_backdrops, value):
    """An important fill, a text stroke, a shadow tree's `::slotted` rule, and an SVG fill all beat the
    page-wide hiding rule, so the screenshot holds the run's own ink: the backdrop is not measured."""
    assert 'backdrop' not in _run(hidden_backdrops, value)


def test_state_backdrop_is_left_out_where_the_state_keeps_the_text_painted(hidden_backdrops):
    painted, recolored = _run(hidden_backdrops, 'eight'), _run(hidden_backdrops, 'nine')
    assert painted['states']['hover']['color'] == pytest.approx(to_oklch('rgb(170 0 0)'), abs=.01)
    assert 'backdrop' not in painted['states']['hover']
    assert recolored['states']['hover']['backdrop'] == pytest.approx(to_oklch('rgb(190 233 209)'), abs=.01)
    assert painted['backdrop']['kind'] == 'solid'          # at rest the text is hidden


# CSS colors Chromium returns from getComputedStyle, with the 8-bit sRGB it paints for them.
PAINTED = [
    ('oklch(0.5 0.1 200)', (0, 116, 122)),
    ('oklab(0.6 -0.1 0.05)', (67, 147, 96)),
    ('lab(50 40 30)', (187, 88, 70)),
    ('lch(30 30 200)', (0, 82, 86)),
    ('color(srgb 0.2 0.4 0.6)', (51, 102, 153)),
    ('color(srgb-linear 0.2 0.4 0.6)', (124, 170, 203)),
    ('color(display-p3 0.2 0.4 0.6)', (26, 104, 157)),
    ('color(a98-rgb 0.5 0.3 0.2)', (143, 75, 46)),
    ('color(prophoto-rgb 0.5 0.3 0.2)', (185, 77, 59)),
    ('color(rec2020 0.5 0.3 0.4)', (161, 83, 117)),
    ('color(xyz-d65 0.2 0.3 0.4)', (0, 167, 164)),
    ('color(xyz-d50 0.2 0.3 0.4)', (0, 168, 189)),
]


@pytest.mark.parametrize(('css', 'painted'), PAINTED)
def test_computed_color_forms_convert_to_the_srgb_the_browser_paints(css, painted):
    assert [round(channel * 255) for channel in srgb(to_oklch(css))] == pytest.approx(painted, abs=1)


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


def test_a_line_break_between_text_nodes_is_a_space_in_the_run(browser, render_server, tmp_path):
    """The run kept `감각에근거를` for `감각에<br>근거를`: adjacent text nodes of one run were joined with nothing between
    them, so a forced break fused two words in the stored text, in every check that reads it."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(fields, 'FIELD_MODULES', (text,))
        vp = capture(browser, f'{render_server}/text-breaks.html', _configs(False, [390])[0],
                     tmp_path / 'breaks.png', bytes(range(32)))
    texts = [run['text'] for run in vp['text']]
    assert '감각에 근거를' in texts
    assert '첫 줄 둘째 줄 ' in texts
    assert 'one two three' in texts
    assert 'already spaced' in texts
    assert not any(fused in ''.join(texts) for fused in ('감각에근거를', 'onetwo', 'already  spaced'))

def test_text_pass_capture_duration(measured):
    _, duration = measured
    print(f'text pass per-capture: {duration:.3f}s')
