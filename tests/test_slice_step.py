"""The slice: in an attended create run the owner approves a rendered first view and one core section, and `next` seals
that approval in the state file."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lapis_design import draft, gate, integrity, next_step, owner
from procedure_support import (TASK, ask, make_project, record, reply, save, seal_slice, unseal_slice, update)

URL = "http://127.0.0.1:4173/slice.html"
URL_B = "http://127.0.0.1:4173/slice-b.html"
URL_C = "http://127.0.0.1:4173/slice-c.html"
QUESTIONS = "1. Who visits the kiln shop page?\n2. Is the monthly firing date fixed?\n"


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    """A finished procedure whose owner has not yet approved a slice; no fonts lock, so the step after the slice shows."""
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    unseal_slice(root)
    (root / ".lapis/fonts.lock.json").unlink()
    return root


def step_of(root: Path) -> str:
    result = next_step.evaluate(root, TASK)
    return result["step"]["id"] if result["step"] else "done"


def sealed(root: Path) -> dict | None:
    return (integrity.read_state(root, TASK) or {}).get("slice")


def draft_pages(root: Path, *pages: tuple[str, str]) -> None:
    """A draft record of `(url, direction)` pages, each with a critic report that names a packet digest."""
    entries = []
    for number, (url, direction) in enumerate(pages):
        report = f"critic/shown-{number}.json"
        save(root, report, {"version": 0, "tool": {"name": "critic", "version": "0.1.0"},
                            "target": {"packet": {"path": ".lapis/critic/packet.json", "sha256": f"{number + 1:x}" * 64}},
                            "findings": []})
        entries.append({"url": url, "render_task": "shown", "sources": ["index.html"], "direction": direction,
                        "area": "first view", "widths": [390, 1440], "behavior_changed": False,
                        "review": {"extracts": [], "critic": {"report": f".lapis/{report}"}}})
    save(root, f"drafts/{TASK}.yaml", {"version": 0, "task": TASK, "pages": entries})


@pytest.fixture
def checked(monkeypatch):
    """`draft.check` accepts every linked page, as it does for a reviewed draft; its own rules have their own tests."""
    monkeypatch.setattr(draft, "check", lambda root, task, *, asked=None: ([], []))


def approve(root: Path, state: str = "approved") -> None:
    approval = {"state": "approved"} if state == "approved" else {"state": state, "reason": "nobody could be asked"}
    update(root, f"plans/{TASK}.yaml", lambda plan: plan.update(approval=approval))


# ---- 1. when the step comes

def test_an_attended_create_run_stops_at_the_slice_once_the_plan_steps_pass_and_an_unattended_run_skips_it(
        project, monkeypatch):
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "slice")
    assert result["step"]["command"] == f"lapis-design draft check --task {TASK}"
    why = result["step"]["why"]
    assert "first view and the one section the brief puts first, not the whole page" in why
    assert "390 and 1440" in why and "direction: new" in why and "Copy is provisional" in why
    assert "question tool" in why and "2-3 candidates" in why and "Without a question tool, show one slice" in why
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    assert step_of(project) == "fonts-lock"                  # the run goes on to what comes after the slice


@pytest.mark.parametrize("mode", ["redesign", "repair"])
def test_a_redesign_or_a_repair_has_no_slice(project, mode):
    update(project, f"plans/{TASK}.yaml", lambda plan: plan.update(mode=mode))
    assert step_of(project) != "slice"


def test_the_slice_comes_after_the_plan_blockers_and_before_the_fonts_lock(project):
    assert step_of(project) == "slice"
    seal_slice(project)
    assert step_of(project) == "fonts-lock"
    unseal_slice(project)
    update(project, f"plans/{TASK}.yaml", lambda plan: plan.pop("brief"))
    assert step_of(project) == "plan-fix"


def test_the_slice_phase_loads_the_review_skill(project):
    (project / f".lapis/skills/{TASK}/ultramarine.json").unlink()
    result = next_step.evaluate(project, TASK)
    assert (result["step"]["id"], result["step"]["skill"], result["then"]["id"]) == ("skill-load", "ultramarine", "slice")


def test_the_gate_tells_a_person_about_the_slice_and_never_blocks(project):
    answer = gate.stop_output(project, "s1", unattended=False, task=TASK)
    assert set(answer) == {"systemMessage"} and "next step slice" in answer["systemMessage"]


# ---- 2. approval questions with no rendered page

def test_approval_questions_that_link_no_page_ask_for_the_slice_and_do_not_wait(project):
    ask(project, "Do you approve this plan as it reads?", 200)
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "slice")
    assert gate.stop_output(project, "s1", unattended=False, task=TASK)["systemMessage"].count("slice") == 1


def test_once_a_slice_is_sealed_or_in_an_unattended_run_a_question_without_a_page_waits(project, monkeypatch):
    ask(project, "Do you approve this plan as it reads?", 200)
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"
    monkeypatch.delenv("LAPIS_UNATTENDED")
    seal_slice(project)
    ask(project, "Do you approve this plan as it reads?", 210)             # the block now says the slice is sealed
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"


def test_brief_questions_before_any_plan_still_wait(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    ask(tmp_path, QUESTIONS, 200)
    result = next_step.evaluate(tmp_path, TASK)
    assert (result["state"], result["waiting"]["phase"], result["then"]["id"]) == ("waiting-for-user", "plan", "brief")


# ---- 3. the seal

def test_a_slice_shown_and_asked_for_waits_for_the_owner_under_the_slice_step(project, checked):
    draft_pages(project, (URL, "new"))
    ask(project, f"Approve this slice? {URL}", 200)
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["then"]["id"]) == ("waiting-for-user", "slice")
    assert sealed(project) is None


def test_the_slice_is_sealed_only_when_it_was_asked_answered_approved_and_linked(project, checked):
    draft_pages(project, (URL, "new"))
    ask(project, f"Approve this slice? {URL}", 200)
    reply(project, "- [declared] The first view is right; keep the quiet tone.", 210)
    approve(project, "assumed")                              # the plan does not say the owner approved
    result = next_step.evaluate(project, TASK)
    assert result["step"]["id"] == "slice" and "does not say `approval: {state: approved}`" in result["step"]["why"]
    assert sealed(project) is None
    approve(project)
    assert step_of(project) == "fonts-lock"                  # sealed, so the step after the slice
    assert sealed(project)["url"] == URL and "candidates" not in sealed(project)


def test_the_seal_records_the_digests_of_what_the_owner_saw_and_said(project, checked):
    draft_pages(project, (URL, "new"))
    ask(project, f"Approve this slice? {URL}", 200)
    reply(project, "- [declared] The first view is right.", 210)
    approve(project)
    next_step.evaluate(project, TASK)
    found = sealed(project)

    def digest(name: str) -> str:
        return hashlib.sha256((project / name).read_bytes()).hexdigest()

    assert found["draft_sha256"] == digest(f".lapis/drafts/{TASK}.yaml")
    assert found["questions_sha256"] == digest(f".lapis/questions/{TASK}.md")
    assert found["answers_sha256"] == digest(f".lapis/answers/{TASK}.md")
    assert found["requirements_sha256"] == digest(f".lapis/requirements/{TASK}.json")
    assert found["packet_sha256"] == "1" * 64 and len(found["protected_sha256"]) == 64 and found["at"].endswith("Z")
    assert integrity.read_state(project, TASK)["slice"] == found


def test_nothing_is_sealed_while_the_questions_are_unanswered_or_the_answers_are_older(project, checked):
    draft_pages(project, (URL, "new"))
    approve(project)
    reply(project, "- [declared] An answer that came before the question.", 150)
    ask(project, f"Approve this slice? {URL}", 200)
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"
    assert sealed(project) is None


def test_a_draft_check_that_fails_keeps_the_slice_unsealed(project):
    draft_pages(project, (URL, "new"))                       # the real draft check: this page has no review record
    update(project, f"drafts/{TASK}.yaml", lambda d: d["pages"][0].pop("review"))
    approve(project)
    ask(project, f"Approve this slice? {URL}", 200)
    reply(project, "- [declared] Looks right.", 210)
    result = next_step.evaluate(project, TASK)
    assert result["step"]["id"] == "slice" and "cannot be sealed" in result["step"]["why"]
    assert sealed(project) is None


def test_a_slice_the_questions_did_not_link_is_not_sealed(project, checked):
    draft_pages(project, (URL, "new"))
    approve(project)
    ask(project, f"Approve this slice? {URL_B}", 200)
    reply(project, "- [declared] Looks right.", 210)
    result = next_step.evaluate(project, TASK)
    assert result["step"]["id"] == "slice" and "is a `direction: new` page" in result["step"]["why"]
    ask(project, "Approve the copy in words?", 220)
    reply(project, "- [declared] Yes.", 230)
    assert "link no rendered page" in next_step.evaluate(project, TASK)["step"]["why"]
    assert sealed(project) is None


def test_an_iteration_page_is_no_slice(project, checked):
    draft_pages(project, (URL, "iteration"))
    approve(project)
    ask(project, f"Approve this change? {URL}", 200)
    reply(project, "- [declared] Yes.", 210)
    assert step_of(project) == "slice" and sealed(project) is None


def test_a_protected_change_after_the_seal_is_flagged_and_listed_in_the_block(project, checked):
    draft_pages(project, (URL, "new"))
    ask(project, f"Approve this slice? {URL}", 200)
    reply(project, "- [declared] Yes.", 210)
    approve(project)
    next_step.evaluate(project, TASK)
    assert sealed(project)
    assert [r for r in integrity.changes(project, TASK) if r["kind"] == "protected"] == []
    update(project, f"plans/{TASK}.yaml", lambda plan: plan["brief"].update(one_job="Sell the whole kiln"))
    next_step.evaluate(project, TASK)
    (row,) = [r for r in integrity.changes(project, TASK) if r["kind"] == "protected"]
    assert row["pointer"] == "/brief/one_job" and row["after_slice"] is True
    text, _ = owner.block(project, TASK)
    assert "Changed since you approved the slice:\n- /brief/one_job" in text


# ---- 4. candidates: the owner picks one or gives feedback

def candidates(project: Path, *urls: str) -> None:
    draft_pages(project, *[(url, "new") for url in urls])
    approve(project)
    ask(project, "Which slice do you pick, or what would you change? " + " ".join(urls), 200)


def test_a_pick_among_several_candidates_seals_the_chosen_one_and_records_all_of_them(project, checked):
    candidates(project, URL, URL_B, URL_C)
    reply(project, f"- [declared] Slice: {URL_B} — the second composition, with the calmer header", 210)
    assert step_of(project) == "fonts-lock"
    found = sealed(project)
    assert found["url"] == URL_B and found["candidates"] == [URL, URL_B, URL_C]
    assert found["packet_sha256"] == "2" * 64                # the critic report of the chosen page, not the first one's


def test_feedback_without_a_pick_seals_nothing_and_a_pick_after_it_does(project, checked):
    candidates(project, URL, URL_B)
    reply(project, "- [declared] Make the headline calmer, and show the firing log higher up.", 210)
    result = next_step.evaluate(project, TASK)
    why = result["step"]["why"]
    assert result["step"]["id"] == "slice" and "2 candidates" in why and "names none of them" in why
    assert "[declared] Slice: <the page's address exactly as linked>" in why and "revise the candidates" in why
    assert sealed(project) is None
    reply(project, f"- [declared] Make the headline calmer.\n- [declared] Slice: {URL} — this one, calmer\n", 220)
    assert step_of(project) == "fonts-lock"
    assert sealed(project)["url"] == URL


def test_a_pick_that_names_no_candidate_is_no_pick_and_the_last_pick_wins(project, checked):
    candidates(project, URL, URL_B)
    reply(project, f"- [declared] Slice: {URL_C} — a page that was not shown", 210)
    assert step_of(project) == "slice" and sealed(project) is None
    reply(project, f"- [declared] Slice: {URL} — first\n- [declared] Slice: {URL_B}. — no, the second\n", 220)
    assert step_of(project) == "fonts-lock" and sealed(project)["url"] == URL_B


def test_a_pick_does_not_seal_a_plan_the_owner_did_not_approve(project, checked):
    candidates(project, URL, URL_B)
    approve(project, "assumed")
    reply(project, f"- [declared] Slice: {URL_B} — this one", 210)
    assert "does not say `approval: {state: approved}`" in next_step.evaluate(project, TASK)["step"]["why"]
    assert sealed(project) is None


def test_a_pick_and_a_decision_line_are_no_requirement_rows(project, checked):
    from lapis_design import requirements

    candidates(project, URL, URL_B)
    reply(project, f"- [declared] Slice: {URL_B} — the second\n- [declared] Keep the firing log above the fold.\n", 210)
    next_step.evaluate(project, TASK)
    assert [r["text"] for r in requirements.rows(project, TASK)] == ["Keep the firing log above the fold."]


def test_the_chosen_candidate_shows_in_the_owner_block(project, checked):
    candidates(project, URL, URL_B)
    reply(project, f"- [declared] Slice: {URL_B} — the second composition", 210)
    next_step.evaluate(project, TASK)
    text, _ = owner.block(project, TASK)
    assert f"Slice sealed: {URL_B} (chosen among {URL}, {URL_B})" in text


def test_the_step_text_carries_both_branches_for_a_harness_with_and_without_a_question_tool(project):
    why = next_step.evaluate(project, TASK)["step"]["why"]
    assert "If this harness has a question tool" in why and "Without a question tool, show one slice" in why
    assert "record a pick as `- [declared] Slice: <the page's address exactly as linked> — <their words>`" in why
