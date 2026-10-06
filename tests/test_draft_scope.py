"""Draft lint isolates the shown page, while candidate and deferred contract findings remain visible."""
import json

import pytest

from lapis_design import next_step
from lapis_design.lint import cli as lint_cli
from layout_support import box, extract, run, viewport
from procedure_support import TASK, make_project, save, update

URL = 'http://127.0.0.1:4173/system.html'


def prepare(root):
    make_project(root)
    update(root, f"plans/{TASK}.yaml", lambda p: p["content"].update(
        key_copy=[{"slot": "headline", "text": "Welcome to excellence", "locale": "en"}]))
    update(root, f"plans/{TASK}.yaml", lambda p: p["tokens"]["type"].update(
        roles=[{"role": "body", "family": "Pretendard", "scripts": ["hang"]}]))
    folder = root / '.lapis/specimens'
    folder.mkdir(parents=True)
    (folder / 'system.html').write_text('<main><h1>Welcome to excellence</h1><button>Reserve piece</button></main>')
    (folder / 'discarded.html').write_text('<style>h1{font-family:"Jost"}</style><h1>Candidate</h1>')
    record = {'version': 1, 'task': TASK, 'pages': [{'url': URL, 'render_task': 'shown-draft',
              'sources': ['.lapis/specimens/system.html'], 'direction': 'new', 'area': 'whole page',
              'widths': [390, 1440], 'behavior_changed': False}]}
    path = save(root, f'drafts/{TASK}.yaml', record)
    data = extract(viewport(390, [box(1, 'card', 16, 100, 358, 300, style={'border_px': 1, 'border_color': [0.8, 0, 0]}),
                                  box(2, 'text', 32, 120, 326, 260, parent=1)],
                             [run(1, 2, 'Welcome to excellence', type_role='heading')]))
    data['source'].update(url=URL, task='shown-draft')
    capture = save(root, 'renders/shown-draft.narrow.json', data)
    return path, capture


def test_shown_card_and_copy_are_separate_from_discarded_font_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv('LAZULI_DB', '')
    draft, capture = prepare(tmp_path)
    report = lint_cli.run(plan=tmp_path / f'.lapis/plans/{TASK}.yaml', source=tmp_path,
                          extract=capture, draft=draft,
                          rule_ids=['layout.card-everything', 'copy.name-swap', 'system.font-outside-contract'])
    assert {'layout.card-everything', 'copy.name-swap'} <= {f['rule_id'] for f in report['findings'] if f['status'] != 'skipped'}
    assert all('Jost' not in f['observed'] for f in report['findings'])
    assert any('Jost' in f['observed'] for f in report['specimen_findings'])
    assert report['scope']['draft']['url'] == URL
    assert report['target']['task'] == TASK
    assert '.lapis/specimens/discarded.html' in report['scope']['draft']['excluded_sources']
    assert report['scope']['draft']['aliases'] == [{'requested': 'Inter', 'rendered': 'Inter'}]


def test_a_draft_extract_of_a_different_page_is_not_combined_with_the_shown_source(tmp_path, monkeypatch):
    monkeypatch.setenv('LAZULI_DB', '')
    draft, capture = prepare(tmp_path)
    data = json.loads(capture.read_text())
    data['source']['url'] = 'http://127.0.0.1:4173/other.html'
    capture.write_text(json.dumps(data))
    with pytest.raises(lint_cli.LintError, match='different page'):
        lint_cli.run(source=tmp_path, extract=capture, draft=draft)


def test_next_links_a_nonstandard_shown_page_to_its_controls(tmp_path, monkeypatch):
    monkeypatch.setenv('LAZULI_DB', '')
    prepare(tmp_path)
    assert next_step.evaluate(tmp_path, TASK)['step']['id'] == 'plan-flows'
