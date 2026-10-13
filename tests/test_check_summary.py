"""What a check prints: a few KB however many findings there are, with every blocker, count, skipped item and limit kept."""
from __future__ import annotations

import json
import random
from pathlib import Path

from lapis_design import check_summary as cs
from lapis_design.lint.cli import _summary_lines
from lapis_design.summary import finding_lines


def finding(rule: str, n: int, *, blocking: bool = True, status: str = "open", severity: str | None = None,
            fix: str | None = "Do the specific thing", cause: str | None = None, observed: str | None = None) -> dict:
    return {"rule_id": rule, "class": "quality", "layer": "render",
            "severity": {"create": severity or ("gate" if blocking else "warn")},
            "observed": observed or f"element {n} measured {n * 7} px, which the rule does not allow here",
            "blocking": blocking, "status": status, "evidence": {"type": "measurement"},
            "location": {"viewport": (320, 390, 768, 1440)[n % 4], "box": f"b{n:012x}"},
            **({"fix": fix} if fix else {}), **({"skip_cause": cause} if cause else {})}


def report(findings: list[dict]) -> dict:
    return {"version": 0, "tool": {"name": "slop_lint", "version": "t"}, "target": {"task": "t"},
            "summary": {"blocking": sum(f["blocking"] for f in findings), "total": len(findings),
                        "skipped": sum(f["status"] == "skipped" for f in findings)},
            "scope": {"layers": ["plan", "render"]}, "findings": findings}


MANY = ([finding(f"layout.rule-{r}", r * 1000 + n) for r in range(6) for n in range(50)]
        + [finding("copy.buzzwords", n, blocking=False) for n in range(40)]
        + [finding("motion.idle", n, blocking=False, status="skipped", cause="probe", observed="motion probe partial")
           for n in range(10)])


def test_a_hundred_blockers_stay_listed_by_rule_with_their_exact_count_and_ids():
    blocking = [f for f in MANY if f["blocking"]]
    lines = cs.blocker_lines(blocking)
    text = "\n".join(lines)
    assert len(text) < 2 * cs.BLOCKER_BUDGET
    for r in range(6):
        assert f"[BLOCK] layout.rule-{r} ×50" in text                             # the exact count of each rule
    assert "fix: Do the specific thing" in text
    ids = [cs.finding_id(f) for f in blocking]
    shown = sum(i in text for i in ids)
    assert shown >= 6 * (cs.DETAIL_ROWS + cs.ID_CAP)                               # rows plus ids; the rest is counted
    assert f"(+{50 - cs.DETAIL_ROWS - cs.ID_CAP} more in the report)" in text


def test_few_blockers_print_exactly_as_before_with_their_places_and_fixes():
    few = [finding("layout.equal-siblings", n) for n in range(3)] + [finding("type.tiny", 9, fix="Raise it")]
    assert cs.blocker_lines(few) == finding_lines(few)


def test_blockers_stay_listed_when_a_thousand_of_them_exceed_every_budget():
    huge = [finding(f"layout.rule-{r}", n) for r in range(20) for n in range(60)]
    text = "\n".join(cs.blocker_lines(huge))
    for r in range(20):
        assert f"[BLOCK] layout.rule-{r} ×60" in text
    assert len(text) < 12000


def test_the_whole_printed_result_of_a_page_with_hundreds_of_findings_is_a_few_kb_and_hides_nothing(tmp_path):
    out = tmp_path / "lint.json"
    document = report(MANY)
    out.write_text(json.dumps(document, indent=2))
    printed = "\n".join(_summary_lines(document, out, [cs.severity_line(MANY), cs.state_line(cs.RunInfo(command="slop lint"))]))
    assert len(printed) < 9000 and len(printed) < out.stat().st_size / 8
    assert "300 blocking, 350 findings, 10 skipped: not judged" in printed
    assert "judged by severity: BLOCK 300, WARN 40 (open 340)" in printed
    assert "not judged (probe): motion probe partial — motion.idle ×10" in printed      # skipped is counted, not dropped
    assert "open, not blocking: copy.buzzwords ×40" in printed and str(out) in printed


def test_a_finding_id_is_stable_and_names_the_rule_place_and_text():
    a = finding("layout.x", 1)
    assert cs.finding_id(a) == cs.finding_id(json.loads(json.dumps(a)))
    assert len(cs.finding_id(a)) == 8
    assert cs.finding_id(a) != cs.finding_id({**a, "observed": "other text"})
    assert cs.finding_id(a) != cs.finding_id({**a, "location": {**a["location"], "viewport": 1}})
    assert cs.finding_id(a) != cs.finding_id({**a, "rule_id": "layout.y"})


def test_new_changed_and_gone_findings_are_told_apart_with_their_ids():
    kept, reworded, vanished = finding("a.kept", 1), finding("a.reworded", 2), finding("a.vanished", 3)
    before = [kept, reworded, vanished]
    now = [kept, {**reworded, "observed": "now it measures differently"}, finding("a.fresh", 4),
           {**finding("a.kept", 9), "blocking": False}]
    change = cs.delta(before, now)
    assert [f["rule_id"] for f in change["new"]] == ["a.fresh", "a.kept"]                  # a.kept at another place is new
    assert [f["rule_id"] for f in change["changed"]] == ["a.reworded"]
    assert [f["rule_id"] for f in change["gone"]] == ["a.vanished"] and change["unchanged"] == 1
    text = "\n".join(cs.delta_lines(change, ".lapis/lint/t.json"))
    for item in (*change["new"], *change["changed"], *change["gone"]):
        assert cs.finding_id(item) in text
    assert "2 new, 1 changed, 1 gone, 1 unchanged" in text


def test_a_blocking_flip_is_a_change_and_no_previous_report_is_said_so():
    a = finding("a.flip", 1)
    assert [f["rule_id"] for f in cs.delta([a], [{**a, "blocking": False}])["changed"]] == ["a.flip"]
    assert "none at this path to compare" in cs.delta_lines(cs.delta(None, [a]), None)[0]


def test_hundreds_of_new_findings_are_counted_and_their_ids_listed_up_to_a_cap():
    change = cs.delta([], MANY)
    lines = cs.delta_lines(change, "x.json")
    assert "350 new" in lines[0]
    assert len(lines) <= 2 + cs.CHANGE_CAP and len("\n".join(lines)) < 3500
    assert "…and 338 more new or changed" in "\n".join(lines)


def test_the_scope_line_says_a_narrow_run_is_not_the_final_evidence():
    assert cs.scope_line(cs.RunInfo(command="x")) == "  scope: full"
    narrow = cs.scope_line(cs.RunInfo(command="x", scope="narrow", scope_note="--width 390"))
    assert "NARROW" in narrow and "--width 390" in narrow and "full run" in narrow


def test_the_state_line_names_build_state_and_what_the_cache_did():
    base = dict(command="x", build_id="b" * 16, state_key="s" * 32, run_seconds=51.3, wall_seconds=0.1)
    assert "cache miss: ran 51.3 s" in cs.state_line(cs.RunInfo(cache="miss", **base))
    hit = cs.state_line(cs.RunInfo(cache="hit", created="2026-10-13T00:00:00+00:00", **base))
    assert "cache hit" in hit and "that run took 51.3 s" in hit and "this call 0.1 s" in hit and "--fresh" in hit
    assert "waited 4.0 s" in cs.state_line(cs.RunInfo(cache="join", waited=4.0, **base))
    off = cs.state_line(cs.RunInfo(cache="off", reason="--fresh", **base))
    assert "cache off: --fresh" in off and "build " + "b" * 16 in off and "state " + "s" * 12 in off


def test_the_render_summary_compares_with_the_previous_extract_and_tolerates_boxes_without_ids():
    def extract(boxes: int, runs: int, *, ids: bool = True) -> dict:
        return {"viewports": [{"width": 390, "theme": "light", "boxes": [{"id": f"b{i}"} if ids else {"role": "x"}
                                                                          for i in range(boxes)],
                               "text": [{}] * runs}]}
    info = cs.RunInfo(command="render check")
    lines = cs.render_lines(extract(5, 3), Path("t.json"), info, extract(4, 3))
    assert "390 light: boxes 4→5 (+1 −0 by id), runs 3→3" in "\n".join(lines) and "judges nothing" in lines[-1]
    assert "no change" in cs.render_lines(extract(4, 3), Path("t.json"), info, extract(4, 3))[3]
    assert "boxes 2→4" in "\n".join(cs.render_lines(extract(4, 3, ids=False), Path("t.json"), info, extract(2, 3, ids=False)))
    narrow = cs.RunInfo(command="render check", scope="narrow", scope_note="--width 390")
    previous = {"viewports": [{"width": 1440, "theme": "light", "boxes": [], "text": []}, *extract(1, 1)["viewports"]]}
    assert "not captured this run (previous extract has them): 1440 light" in "\n".join(
        cs.render_lines(extract(1, 1), Path("t.narrow.json"), narrow, previous))


def test_the_behavior_summary_names_every_partial_and_skipped_probe_even_with_long_distinct_reasons():
    probes = [f"probe-{i:02d}" for i in range(18)]
    coverage = ([{"probe": "controls", "status": "ran", "contexts": ["m"]}]
                + [{"probe": p, "status": "partial", "reason": f"reason {p} " + "x" * 400} for p in probes[:9]]
                + [{"probe": p, "status": "skipped", "reason": f"not run {p} " + "y" * 400} for p in probes[9:]])
    session = {"contexts": [{"id": "m"}], "nodes": [{"id": "b"}] * 3, "coverage": coverage}
    previous = {"coverage": [{"probe": "controls", "status": "partial"}], "nodes": []}
    text = "\n".join(cs.behavior_lines(session, Path("t.json"), cs.RunInfo(command="behavior check"), previous))
    assert all(p in text for p in probes)                                                  # no probe is hidden
    assert "9 partial, 9 skipped" in text and "controls partial→ran" in text and "nodes +3" in text
    assert len(text) < 5000


def test_every_finding_order_gives_the_same_blocker_text():
    blocking = [f for f in MANY if f["blocking"]]
    shuffled = blocking[:]
    random.Random(3).shuffle(shuffled)
    assert cs.blocker_lines(blocking) == cs.blocker_lines(shuffled)
