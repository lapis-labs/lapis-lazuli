"""The owner summary: what an approval or direction wait carries in chat, against the full block it links. The delivery
contract is a short prioritized summary with one decision, and the checker enforces that contract: dropping a core gap, a
core defect, or a font fact is a problem, and so is a second decision or no link to the full block."""
from __future__ import annotations

import pytest

from lapis_design import gaps, next_step, owner, requirements
from procedure_support import TASK, record, reply, update
from test_owner_block import ids, judge, project  # noqa: F401  (a finished procedure with four sealed owner rows)
from test_slice_hold import CORE, declare

ROLES = [{"role": "display", "family": "Futura PT Cond", "scripts": ["latn"], "source": "contract"},
         {"role": "body", "family": "Pretendard", "scripts": ["latn", "hang"], "source": "catalog"}]


@pytest.fixture
def shown(project):
    """A shown page whose critic report holds one open core finding, two type roles in the plan, and a delivery."""
    update(project, f"plans/{TASK}.yaml", lambda plan: plan["tokens"]["type"].update(roles=ROLES))
    declare(project, core=[CORE])
    return owner.deliver(project, TASK, {"kind": "approval"})


def without(text: str, line: str) -> str:
    assert line in text
    return text.replace(line + "\n", "", 1)


def test_the_summary_is_the_decision_then_what_the_owner_must_see_and_a_link_to_the_rest(shown, project):
    text = shown.summary
    lines = text.splitlines()
    assert lines[0] == f"# Owner summary: {TASK}" and lines[2].startswith("Decision: approve this build or say what to change")
    assert text.count("\nDecision:") == 1 and lines[-1] == shown.marker
    assert [line for line in lines if line.startswith("## ")] == [
        "## Decisions you have not made", "## Defects of the build shown", "## Fonts and rights", "## Shown"]
    found = gaps.compute(project, TASK)
    assert found and all(f"- {g['text']}" in text for g in found)                         # every gap, not a count
    assert "- copy.fabricated-proof: the page shows two invented customer quotes" in text
    assert "- display (latn): Futura PT Cond — source contract; no fonts lock entry yet, so no license is recorded — needs your word" in text
    assert "- body (latn, hang): Pretendard — source " in text
    assert shown.artifact in text and f"({len(shown.block)} characters" in text
    for held_back in ("## Facts shown", "## Integrity", "## Disputes", "## Questions during the work", "## Your decisions"):
        assert held_back not in text and held_back in shown.block
    assert len(text) < len(shown.block)


def test_the_summary_that_is_delivered_passes_the_delivery_check_and_other_text_around_it_does_not_matter(shown):
    assert shown.problems(shown.summary) == []
    assert shown.problems(f"Which headline do you prefer?\n\n{shown.summary}\nAnd one more thing.\n") == []
    assert shown.problems(shown.summary.replace("\n- ", "\n-   ")) == []                  # white space is not content


@pytest.mark.parametrize("what", ["core gap", "core defect", "font fact"])
def test_dropping_a_core_gap_a_core_defect_or_a_rights_fact_fails_the_check(shown, what):
    line = next(line for kind, line in shown.required if kind == what)
    problems = shown.problems(without(shown.summary, line))
    assert len(problems) == 1 and "drops 1 line the owner must see" in problems[0] and f"{what}: {line[:60]}" in problems[0]


def test_every_kind_of_line_the_contract_requires_is_in_the_delivery(shown):
    assert {kind for kind, _ in shown.required} == {"core gap", "core defect", "font fact"}
    assert [line for kind, line in shown.required if kind == "core defect"][0].startswith("- copy.fabricated-proof:")
    assert sum(kind == "font fact" for kind, _ in shown.required) == 2
    assert sum(kind == "core gap" for kind, _ in shown.required) >= 3             # color, layout, motion, and the rest the agent filled in


def test_one_decision_ask_the_link_to_the_full_block_and_the_summary_itself_are_each_required(shown):
    ask = next(line for line in shown.summary.splitlines() if line.startswith("Decision:"))
    assert "exactly one `Decision:` line, and this one has 2" in shown.problems(
        shown.summary.replace(ask, f"{ask}\n\nDecision: and also approve the copy.", 1))[0]
    assert "exactly one `Decision:` line, and this one has 0" in shown.problems(without(shown.summary, ask).replace("\n\n\n", "\n\n"))[0]
    linked = shown.summary.replace(shown.artifact, ".lapis/owner/other.md")
    assert shown.problems(linked) == [f"the owner summary names the full block ({shown.artifact}) and its digest; this one does not"]
    assert "not the owner summary above it" in shown.problems(f"A line.\n\n{shown.block}")[0]    # the whole block is not the summary
    assert "do not carry the current owner summary" in shown.problems("Which headline?")[0]
    assert "do not carry the current owner summary" in shown.problems(shown.summary.replace(shown.sha8, "0" * 8))[0]


def test_next_names_what_the_summary_in_the_questions_drops_and_waits_when_it_holds(project):
    update(project, f"plans/{TASK}.yaml", lambda plan: plan["tokens"]["type"].update(roles=ROLES))
    delivery = owner.deliver(project, TASK, {"kind": "approval"})
    block_line = next(line for kind, line in delivery.required if kind == "core gap")
    record(project, "questions", f"lapis-questions: approval\nWhich headline do you prefer?\n\n{without(delivery.summary, block_line)}", 200)
    result = next_step.evaluate(project, TASK)
    assert result["step"]["id"] == "draft-review" and "drops 1 line the owner must see" in result["step"]["why"]
    assert f"paste .lapis/owner/{TASK}.summary.md" in result["step"]["why"]
    record(project, "questions", f"lapis-questions: approval\nWhich headline do you prefer?\n\n{result['owner_summary']}", 200)
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"


def test_the_decision_line_names_what_the_owner_settles_by_the_kind_of_wait(shown, project):
    assert "also settles the" in shown.summary and "decisions you have not made above" in shown.summary
    assert "1 open core findings above" in shown.summary
    direction = owner.deliver(project, TASK, {"kind": "direction"}).summary
    assert "Decision: pick or change what the direction items name" in direction
    done = owner.deliver(project, TASK, {"verdict": "the release gate's report has 0 blocking findings"})
    assert "Decision: accept this result, or name what to fix first." in done.summary
    assert ("release", "- the release gate's report has 0 blocking findings") in done.required
    assert done.problems(without(done.summary, "- the release gate's report has 0 blocking findings"))


def test_requirement_rows_missing_or_not_judged_are_defects_and_the_counts_name_the_rest(project):
    first, second, third, fourth = ids(project)
    judge(project, ["met", "partly", "missing", None])
    delivery = owner.deliver(project, TASK, {"kind": "approval"})
    text = delivery.summary
    assert "- requirements, the whole page: met 1, partly 1, missing 1, not judged 1 of 4" in text
    assert f"- missing {third} \"Keep prices out of the hero.\"" in text
    assert f"- not judged {fourth}" in text and f"- partly: {second}" in text
    assert any(kind == "core defect" and line.startswith(f"- missing {third} ") for kind, line in delivery.required)
    assert delivery.problems(without(text, next(l for l in text.splitlines() if l.startswith(f"- not judged {fourth}"))))


def test_what_the_owners_last_reply_changed_comes_first_after_the_decision(project):
    first = ids(project)[0]
    reply(project, f"- [declared] {first}: drop — the firing log is not for the first version\n", 260)
    requirements.refresh(project, TASK)
    judge(project, [None, "met", "met", "met"])
    text = owner.deliver(project, TASK, {"kind": "approval"}).summary
    section = text.split("## Changed since your last word\n", 1)[1].split("\n\n", 1)[0]
    assert f"- drop {first}: [declared] {first}: drop — the firing log is not for the first version" in section
    assert text.index("Decision:") < text.index("## Changed since your last word")


def test_a_font_with_a_locked_license_is_listed_with_it_and_one_nobody_confirmed_is_marked(project):
    import json

    update(project, f"plans/{TASK}.yaml", lambda plan: plan["tokens"]["type"].update(roles=ROLES))
    lock = {"version": 0, "locked_at": "2026-09-27T00:00:00Z", "fonts": [
        {"role": "body", "family": "Pretendard", "postscript_names": ["Pretendard-Regular"], "source": "fontsource",
         "license": {"kind": "ofl", "checked_at": "2026-09-27"}, "delivery": {"mode": "self-host"}, "used_by": [TASK]},
        {"role": "display", "family": "Futura PT Cond", "postscript_names": ["FuturaPTCond-Bold"], "source": "adobe-sync",
         "license": {"kind": "commercial-subscription", "checked_at": "2026-09-27"}, "delivery": {"mode": "adobe-web-project"},
         "used_by": [TASK]}]}
    (project / ".lapis/fonts.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    lines = owner.font_facts(project, TASK)
    assert lines[0].endswith("fonts lock: channel adobe-sync, license commercial-subscription (recorded) — needs your word")
    assert lines[1].endswith("fonts lock: channel fontsource, license ofl (recorded)")
