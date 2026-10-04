"""The printed summary of a check: what it keeps whole, what it shortens, and what it never leaves out."""
from __future__ import annotations

from lapis_design import summary


def finding(rule: str, observed: str = "something was found", *, blocking: bool = True, status: str = "open",
            fix: str | None = None, cause: str | None = None, **location) -> dict:
    return {"rule_id": rule, "class": "default", "severity": {"create": "gate" if blocking else "warn"},
            "layer": "render", "observed": observed, "blocking": blocking, "status": status,
            "evidence": {"type": "measurement"}, **({"fix": fix} if fix else {}),
            **({"skip_cause": cause} if cause else {}), **({"location": location} if location else {})}


def test_clip_cuts_one_line_at_the_limit_and_marks_the_cut():
    assert summary.clip("a  b\n c", 10) == "a b c"
    cut = summary.clip("word " * 50, 40)
    assert len(cut) <= 40 and cut.endswith("…") and "\n" not in cut


def test_blocking_findings_keep_their_place_and_share_a_fix_once():
    lines = summary.finding_lines([
        finding("layout.equal-siblings", "4 siblings", fix="Let content set the span", viewport=320, box="b0123456789ab"),
        finding("layout.equal-siblings", "5 siblings", fix="Let content set the span", viewport=1440, box="bfedcba987654"),
        finding("type.tiny-ui-text", "11 px label", fix="Raise it", viewport=390, box="b1111111111111")])
    text = "\n".join(lines)
    assert text.count("Let content set the span") == 1
    for needle in ("320 px box b0123456789ab", "1440 px box bfedcba987654", "390 px box b1111111111111",
                   "layout.equal-siblings ×2", "type.tiny-ui-text", "Raise it"):
        assert needle in text


def test_a_long_observed_text_is_clipped_and_identical_findings_are_counted():
    long = "measured text " * 40
    lines = summary.finding_lines([finding("color.text-contrast", long, box="b0123456789ab")] * 3)
    assert len(lines) == 2 and "(×3)" in lines[1]
    assert long not in lines[1] and lines[1].count("…") == 1 and len(lines[1]) < summary.OBSERVED_CAP + 60


def test_a_file_the_whole_report_is_about_is_not_repeated_in_each_place():
    plan = finding("plan.uncompared-decision", "7 open decisions", file=".lapis/plans/t.yaml", path="explorations")
    assert summary.place(plan, ".lapis/plans/t.yaml") == "explorations"
    assert summary.place(plan) == ".lapis/plans/t.yaml explorations"


def test_findings_that_did_not_block_are_named_and_every_skipped_rule_is_listed_with_its_reason():
    rest = [finding("copy.buzzwords", blocking=False), finding("copy.buzzwords", blocking=False),
            finding("layout.nested-cards", blocking=False, status="waived"),
            finding("color.palette-swap-only", "no typicality corpus was given", blocking=False, status="skipped",
                    cause="input"),
            finding("layout.typical-composition", "no typicality corpus was given", blocking=False, status="skipped",
                    cause="input"),
            finding("ux.drip-pricing", "flows probe partial", blocking=False, status="skipped", cause="probe"),
            finding("type.synthetic-style", blocking=True)]
    assert summary.rest_lines(rest) == [
        "  open, not blocking: copy.buzzwords ×2",
        "  waived by the plan: layout.nested-cards",
        "  not judged (input): no typicality corpus was given — color.palette-swap-only, layout.typical-composition",
        "  not judged (probe): flows probe partial — ux.drip-pricing"]
    detailed = summary.rest_lines(rest[:2], detail_open=True)
    assert detailed == ["  [WARN] copy.buzzwords ×2", "      something was found  (×2)"]
