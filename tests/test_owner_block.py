"""The owner block: what `done` and every approval wait show the owner, written by the CLI from the files."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from lapis_design import attempts, gate, integrity, next_step, owner, requirements, waiting
from lapis_design.cli import main as cli_main
from procedure_support import (TASK, ask, finish, make_project, record, refresh_critic, reply, save, seal_requirements,
                               touch, update)

BRIEF = """# Brief

- Show the firing log on the first screen.
- A reservation button that never needs an account.
- Keep prices out of the hero.
- Use no stock photos.
"""
ROW_TEXT = ["Show the firing log on the first screen.", "A reservation button that never needs an account.",
            "Keep prices out of the hero.", "Use no stock photos."]
PAGE = "http://127.0.0.1:4173/slice.html"
RELEASE = f".lapis/critic/{TASK}.json"


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    """A finished procedure, its owner's brief sealed as four requirement rows, and no critic judgement of them yet."""
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    (root / "brief.md").write_text(BRIEF, encoding="utf-8")
    seal_requirements(root, TASK, "brief.md")
    return root


def step_of(root: Path) -> str:
    result = next_step.evaluate(root, TASK)
    return result["step"]["id"] if result["step"] else "done"


def ids(root: Path) -> list[str]:
    return [row["id"] for row in requirements.rows(root, TASK)]


def judge(root: Path, states: list[str | None], **more) -> None:
    """The critic report with a judgement of each row (`None` leaves the row out), as a critic that read the packet
    writes it: it names the packet built from the inputs as they are now."""
    refresh_critic(root, extra={"requirements": [{"id": rid, "state": state, "refs": []}
                                                 for rid, state in zip(ids(root), states) if state], **more})


# ---- 4. the marker an approval wait has to carry

def test_a_wait_whose_questions_lack_the_current_block_line_is_sent_back_to_paste_it(project):
    seal = project / f".lapis/state/{TASK}.json"
    assert seal.is_file()
    record(project, "questions", "lapis-questions: approval\nWhich headline do you prefer?", 200)
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "draft-review")
    block = (project / f".lapis/owner/{TASK}.md").read_text(encoding="utf-8")
    last = block.splitlines()[-1]
    assert last.startswith("lapis-owner-block ") and len(last.split()[1]) == 8
    assert result["owner_block"] == block
    why = result["step"]["why"]
    assert f"paste .lapis/owner/{TASK}.md into .lapis/questions/{TASK}.md unchanged" in why and f"`{last}`" in why
    assert result["step"]["command"] == f"lapis-design draft check --task {TASK}"


def test_pasting_the_block_ends_it_and_a_block_that_has_gone_out_of_date_does_not_count(project):
    record(project, "questions", "lapis-questions: approval\nWhich headline do you prefer?", 200)
    block = next_step.evaluate(project, TASK)["owner_block"]
    record(project, "questions", f"lapis-questions: approval\nWhich headline do you prefer?\n\n{block}", 200)
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["then"]["id"]) == ("waiting-for-user", "critic")
    assert result["owner_block"] == block
    judge(project, ["met", "partly", None, None])                        # a record the block reports has changed
    stale = next_step.evaluate(project, TASK)
    assert stale["step"]["id"] == "draft-review" and stale["owner_block"] != block
    assert owner.carries(f"Which headline?\n{block}", owner.block(project, TASK)[1]) is False


def test_an_unattended_run_is_continued_with_the_paste_and_a_plan_phase_question_needs_no_block(project, tmp_path_factory):
    record(project, "questions", "lapis-questions: approval\nWhich headline do you prefer?", 200)
    answer = gate.stop_output(project, "s1", unattended=True, task=TASK)
    assert answer["decision"] == "block" and "Next step: draft-review." in answer["reason"]
    assert f"paste .lapis/owner/{TASK}.md" in answer["reason"]
    bare = tmp_path_factory.mktemp("bare")
    ask(bare, "1. Who visits the kiln shop page?\n2. Is the monthly firing date fixed?\n", 200)
    assert next_step.evaluate(bare, TASK)["state"] == "waiting-for-user"


def test_a_questions_file_that_holds_only_the_block_asks_nothing_and_links_nothing(project):
    record(project, "questions", "lapis-questions: approval\nWhich headline do you prefer?", 200)
    block = next_step.evaluate(project, TASK)["owner_block"]
    save(project, f"drafts/{TASK}.yaml", {"version": 0, "task": TASK, "pages": [
        {"url": PAGE, "direction": "new", "widths": [390, 1440], "review": {"extracts": []}}]})
    shown, _ = owner.write(project, TASK)                      # the block now names the page it shows
    assert PAGE in shown
    only = project / f".lapis/questions/{TASK}.md"
    only.write_text(shown, encoding="utf-8")
    assert waiting.counts(only) is False and waiting.words(shown) == 0
    from lapis_design import draft

    only.write_text(f"Which headline do you prefer? {PAGE}\n\n{shown}", encoding="utf-8")
    assert draft.links(project, TASK) == [PAGE]
    only.write_text(f"Which headline do you prefer?\n\n{shown}", encoding="utf-8")
    assert draft.links(project, TASK) == [] and block


# ---- 5. done and the critic's coverage of every row

def test_done_needs_a_critic_report_that_judges_every_requirement_row(project):
    result = next_step.evaluate(project, TASK)
    assert result["step"]["id"] == "critic"                        # the report lacks `requirements`
    assert "4 rows, 4 not judged yet" in result["step"]["why"]
    judge(project, ["met", "partly", "missing", None])
    result = next_step.evaluate(project, TASK)
    assert result["step"]["id"] == "critic" and "4 rows, 1 not judged yet" in result["step"]["why"]
    judge(project, ["met", "partly", "missing", "not-in-slice"])
    assert step_of(project) == "release"
    assert finish(project, "--static") in (0, 1)
    result = next_step.evaluate(project, TASK)
    assert result["state"] == "done" and result["step"] is None


def test_a_recorded_unavailable_critic_still_allows_done_and_the_block_says_the_requirements_were_not_judged(project, capsys):
    (project / RELEASE).unlink()
    assert step_of(project) == "critic"
    assert cli_main(["next", "--task", TASK, "--root", str(project), "--unavailable", "critic",
                     "--reason", "this harness cannot start a separate context"]) == 0
    assert finish(project, "--static") == 1                       # release.critic-missing is still blocking
    result = next_step.evaluate(project, TASK)
    assert result["state"] == "done"
    block = result["owner_block"]
    assert "- 4 rows. requirements not judged: this harness cannot start a separate context." in block
    assert "- critic: this harness cannot start a separate context" in block


def test_done_carries_the_block_and_tells_the_agent_to_paste_it_ahead_of_its_own_summary(project, capsys):
    judge(project, ["met", "met", "met", "met"])
    assert step_of(project) == "release"
    finish(project, "--static")
    result = next_step.evaluate(project, TASK)
    block = (project / f".lapis/owner/{TASK}.md").read_text(encoding="utf-8")
    assert result["owner_block"] == block and "## Release\n- the release gate's report has" in block
    assert "Paste the owner block unchanged ahead of your own summary" in result["reason"]
    assert f"`{block.splitlines()[-1]}`" in result["reason"]
    capsys.readouterr()
    assert cli_main(["next", "--task", TASK, "--root", str(project)]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith(f"next: done ({TASK})") and printed.rstrip().endswith(block.splitlines()[-1])
    assert cli_main(["next", "--task", TASK, "--root", str(project), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["owner_block"] == block


def test_a_task_with_no_requirement_record_keeps_its_old_done(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    (root / f".lapis/requirements/{TASK}.json").unlink()
    update(root, f"plans/{TASK}.yaml", lambda plan: plan.update(mode="repair"))
    touch(root, f"plans/{TASK}.yaml", 100)
    touch(root, f"lint/{TASK}.json", 110)
    touch(root, f"critic/{TASK}.json", 111)
    finish(root, "--static")
    result = next_step.evaluate(root, TASK)
    assert result["state"] == "done"
    assert "no requirement record for this task" in result["owner_block"]


# ---- 6. what the block holds

@pytest.fixture
def rich(project) -> tuple[Path, str]:
    """Everything the block reports: judged rows, facts, a dispute, a reactive keep, a change after the slice, a page with
    a height, an owner decision, and a check that did not run."""
    first, second, third, fourth = ids(project)
    lint = json.loads((project / f".lapis/lint/{TASK}.json").read_text(encoding="utf-8"))
    lint["findings"].append({"rule_id": "type.overused-neutral-grotesque", "class": "quality",
                             "severity": {"create": "warn", "review": "P2"}, "layer": "render", "status": "open",
                             "observed": "a neutral grotesque", "blocking": False, "evidence": {"type": "measurement"}})
    save(project, f"lint/{TASK}.json", lint)
    integrity.observe_task(project, TASK, "test")                        # the baseline, with that finding open
    update(project, f"plans/{TASK}.yaml", lambda plan: next(d for d in plan["defaults"]
                                                            if d["id"] == "type.overused-neutral-grotesque").update(
        reason="Body text favors a neutral sans on a phone, and the log is mono"))
    reply(project, f"- [declared] {second}: narrow — only the first screen needs it\n", 260)
    judge(project, ["met", "partly", "missing", "met"], **{
        "requirements": [
            {"id": first, "state": "met", "refs": ["shown-390.png"]},
            {"id": second, "state": "partly", "refs": ["shown-390.png"], "note": "The button sits below the fold at 390"},
            {"id": third, "state": "missing", "refs": [], "note": "The hero shows a price"},
            {"id": fourth, "state": "met", "refs": ["shown-1440.png"], "left_by": ["/references[source=ref-site]/leave"]}],
        "facts": [{"text": "Founded in 1998", "refs": ["b1"], "source": "none", "quote": ""},
                  {"text": "Fires once a month", "refs": ["b2"], "source": "PRODUCT.md#L3-L3",
                   "quote": "fires once a month"}],
        "disputes": [{"index": 0, "verdict": "false-positive", "why": "The capture shows no cards at all.", "refs": ["x"]}],
        "changes": [{"seq": 1, "verdict": "narrows", "rows": [third], "why": "The kept default removes what the row asks."}]})
    save(project, f"disputes/{TASK}.yaml", {"version": 0, "task": TASK, "disputes": [
        {"report": f".lapis/lint/{TASK}.json", "rule_id": "layout.card-everything", "observed": "Repeated cards",
         "reason": "The cards are the firing log's own rows", "refs": ["x"]}]})
    save(project, "renders/shown.narrow.json", {"version": 1, "viewports": [
        {"width": 390, "boxes": [{"rect": {"x": 0, "y": 0, "w": 390, "h": 5000}}]},
        {"width": 1440, "boxes": [{"rect": {"x": 0, "y": 0, "w": 1440, "h": 900}},
                                  {"rect": {"x": 0, "y": 904, "w": 1440, "h": 1200.4}}]}]})
    save(project, f"drafts/{TASK}.yaml", {"version": 0, "task": TASK, "pages": [
        {"url": PAGE, "direction": "new", "widths": [390, 1440], "review": {"extracts": [".lapis/renders/shown.narrow.json"]}}]})
    attempts.record(project, TASK, "render", ["lapis-design", "render", "check"], None, "Chromium would not start here")
    integrity.observe_task(project, TASK, "test")
    return project, "the release gate's report has 2 blocking findings (1 defects, 1 without evidence)"


def test_the_block_lists_the_outcome_the_decisions_the_facts_the_changes_the_disputes_and_what_did_not_run(rich):
    project, verdict = rich
    text, sha8 = owner.block(project, TASK, {"verdict": verdict})
    first, second, third, fourth = ids(project)
    lines = text.splitlines()
    assert lines[0] == f"# Owner block: {TASK}" and lines[-1] == f"lapis-owner-block {sha8}"
    assert f"- the whole page, critic report {RELEASE}: 4 rows: met 2, partly 1, missing 1." in lines
    assert f"  - partly {second} (you narrowed it) \"{ROW_TEXT[1]}\" — The button sits below the fold at 390" in lines
    assert f"  - missing {third} \"{ROW_TEXT[2]}\" — The hero shows a price" in lines
    assert f"  - met {fourth} \"{ROW_TEXT[3]}\"; left out by /references[source=ref-site]/leave" in lines
    assert not any(first in line for line in lines if line.startswith("  - "))     # a met row with nothing left out
    assert any(line.startswith(f"- narrow {second}: [declared] {second}: narrow — only the first screen needs it")
               for line in lines)
    assert lines.index('- "Founded in 1998" — no source found') < lines.index(
        '- "Fires once a month" — asserted by PRODUCT.md#L3-L3: "fires once a month"')
    assert "These are asserted by their source and not independently checked." in lines
    assert any("protected /defaults[id=type.overused-neutral-grotesque] changed" in line
               and "a keep added while its finding was open" in line for line in lines)
    assert "- the critic says change 1 narrows what you asked: The kept default removes what the row asks." in lines
    assert "Changed since you approved the slice:" in lines
    assert "- /defaults[id=type.overused-neutral-grotesque]" in lines
    assert ("- layout.card-everything: Repeated cards; maker: The cards are the firing log's own rows; "
            "critic: false-positive — The capture shows no cards at all.") in lines
    assert f"- {PAGE} at 390, 1440; document height at 1440: 2,104 px" in lines
    assert "- Slice sealed: http://localhost/" in lines
    assert "- render: Chromium would not start here" in lines
    assert lines[lines.index("## Release") + 1] == f"- {verdict}"
    assert str(project) not in text and not re.search(r"\d{4}-\d\d-\d\dT\d\d:\d\d", text)       # no path, no time


def test_the_block_is_deterministic_and_written_whole_to_the_owner_file(rich):
    project, verdict = rich
    first = owner.write(project, TASK, {"verdict": verdict})
    again = owner.write(project, TASK, {"verdict": verdict})
    assert first == again and first == owner.block(project, TASK, {"verdict": verdict})
    target = project / f".lapis/owner/{TASK}.md"
    assert target.read_text(encoding="utf-8") == first[0]
    assert [p.name for p in target.parent.iterdir()] == [f"{TASK}.md"]           # no half-written file is left beside it
    judge(project, ["met", "met", "met", "met"])
    assert owner.write(project, TASK, {"verdict": verdict})[1] != first[1]       # any change a record reports changes it
    assert owner.write(project, TASK, {"verdict": verdict, "integrity_error": "OSError: disk full"})[0].count(
        "- integrity not recorded: OSError: disk full") == 1


def test_the_block_lists_at_most_fifteen_rows_and_says_how_many_more(project):
    (project / "brief.md").write_text("".join(f"- Requirement number {n} of the owner\n" for n in range(40)), encoding="utf-8")
    seal_requirements(project)
    judge_all = [{"id": rid, "state": "missing", "refs": []} for rid in ids(project)]
    save(project, f"critic/{TASK}.json", {"version": 0, "tool": {"name": "critic", "version": "0.1.0"},
                                           "target": {"task": TASK, "extract": f".lapis/renders/{TASK}.json"},
                                           "findings": [], "requirements": judge_all})
    text, _ = owner.block(project, TASK, {"verdict": "the release gate's report has 0 blocking findings"})
    assert f"{len(judge_all)} rows: missing {len(judge_all)}." in text
    assert text.count("  - missing R") == 15 and f"  - and {len(judge_all) - 15} more in {RELEASE}" in text


def test_a_dropped_row_leaves_the_counts_and_stays_in_the_decisions(project):
    first = ids(project)[0]
    reply(project, f"- [declared] {first}: drop — the firing log is not for the first version\n", 260)
    requirements.refresh(project, TASK)
    judge(project, [None, "met", "met", "met"])
    text, _ = owner.block(project, TASK, {"verdict": "v"})
    assert "3 rows: met 3." in text and f"- drop {first}: [declared] {first}: drop — the firing log" in text


def gaps(root: Path) -> list[str]:
    """The lines of the block's "Not run, or stale" section."""
    text = owner.block(root, TASK, {"verdict": "v"})[0]
    return text.split("## Not run, or stale\n", 1)[1].split("\n\n", 1)[0].splitlines()


def test_the_block_says_where_a_critic_report_does_not_hold_against_its_packet(project):
    assert any(line.startswith(f"- the whole page, critic report {RELEASE}: critic report was made from another packet")
               for line in gaps(project))                              # the rows were sealed after the report's packet
    judge(project, ["met", "met", "met", None])
    assert f"- the whole page, critic report {RELEASE}: `requirements` has no entry for {ids(project)[3]}" in gaps(project)
    judge(project, ["met", "met", "met", "met"])
    assert not [line for line in gaps(project) if "critic report" in line]       # a report that holds adds nothing
