"""Rendered alternatives must change relations; comparison waivers stay within the compared font roles."""
import pytest

from test_plan_explorations import base_plan, check, entry_of, found


def layout_pair(tmp_path, plan, *, regroup=False, reordered_markup=False):
    a = '<main><section><h2>Pieces</h2><p>Kiln position</p></section><section><h2>Reserve</h2><button>Reserve piece</button></section></main>'
    b = '<main><section><h2>Pieces</h2><h2>Reserve</h2></section><section><p>Kiln position</p><button>Reserve piece</button></section></main>' if regroup else a
    if reordered_markup:
        b = '<main><section><h2>Reserve</h2><button>Reserve piece</button></section><section><h2>Pieces</h2><p>Kiln position</p></section></main>'
    (tmp_path / 'a.html').write_text('<body class="opening">' + a + '</body>')
    (tmp_path / 'b.html').write_text('<body class="sequence-opening">' + b + '<style>.sequence-opening section{order:2}.sequence-opening h2{font-size:42px;margin:8px}</style></body>')
    entry = entry_of(plan, 'layout')
    entry['compared_on'] = ['render']
    entry['candidates'] = [{'name': 'A', 'source': 'kiln log', 'artifact': 'a.html'},
                           {'name': 'B', 'source': 'own sketch', 'artifact': 'b.html'}]
    entry['chosen'] = 'A'
    entry['comparisons'] = [{'variable': 'content relation', 'viewport': {'width': 390, 'theme': 'light'},
                             'state': 'pieces and reservation', 'captures': {'A': 'a.png', 'B': 'b.png'}}]
    (tmp_path / 'a.png').write_bytes(b'observed capture A')
    (tmp_path / 'b.png').write_bytes(b'observed capture B')
    return entry


@pytest.mark.parametrize('reordered_markup', [False, True], ids=['css-order', 'markup-order'])
def test_order_only_candidates_do_not_count_as_two_layouts(tmp_path, reordered_markup):
    plan = base_plan()
    layout_pair(tmp_path, plan, reordered_markup=reordered_markup)
    hits = found(check(tmp_path, plan))
    assert any(f['blocking'] and 'order' in f['observed'] for f in hits)


def test_different_group_membership_is_a_real_layout_alternative(tmp_path):
    plan = base_plan()
    layout_pair(tmp_path, plan, regroup=True)
    assert not found(check(tmp_path, plan))


def test_a_body_ui_win_does_not_waive_a_hangul_heading_using_the_same_face(tmp_path):
    plan = base_plan()
    plan['tokens']['type']['roles'] = [{'role': r, 'family': 'system-ui', 'scripts': ['hang'], 'source': 'inventory'}
                                     for r in ('display', 'heading', 'body', 'ui')]
    plan['explorations'] = [e for e in plan['explorations'] if e['decision'] != 'type'] + [{
        'decision': 'type', 'covers': ['body', 'ui'], 'candidates': [
            {'name': 'system-ui', 'source': 'generic'}, {'name': 'Pretendard', 'source': 'local'}],
        'compared_on': ['specimen'], 'chosen': 'system-ui',
        'runner_up_lost': 'The system reading face kept paragraph and control labels clearer'}]
    keep = next(d for d in plan['defaults'] if d['id'] == 'type.overused-neutral-grotesque')
    keep['evidence'] = {'exploration': 'system-ui'}
    report = check(tmp_path, plan)
    hit = next(f for f in report['findings'] if f['rule_id'] == 'type.overused-neutral-grotesque')
    assert hit['status'] != 'waived'
    assert found(report)


def test_a_motion_name_and_sketch_are_not_an_implemented_alternative(tmp_path):
    plan = base_plan()
    plan['explorations'] = [e for e in plan['explorations'] if e['decision'] != 'motion'] + [{
        'decision': 'motion', 'candidates': [{'name': 'transition', 'source': 'kiln log'},
                                            {'name': 'feedback only', 'source': 'generic'}],
        'compared_on': ['sketch', 'specimen'], 'chosen': 'transition',
        'runner_up_lost': 'Feedback alone loses the identity of the selected record'}]
    assert any(f['blocking'] and 'implemented' in f['observed'] for f in found(check(tmp_path, plan)))


def test_fixed_motion_remains_exempt(tmp_path):
    plan = base_plan()
    plan['explorations'] = [e for e in plan['explorations'] if e['decision'] != 'motion'] + [{
        'decision': 'motion', 'fixed_by': 'brief', 'reason': 'The user requires feedback only, without entrances'}]
    assert not found(check(tmp_path, plan))
