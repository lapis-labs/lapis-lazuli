"""The slice hold: from the first time `next` names `slice`, an attended create run may write only the files its slice page
declares; the slice reaches the owner within a clock; open core findings go to the owner; a revision is the next round."""
from __future__ import annotations

import json
import time
from datetime import timedelta
from pathlib import Path

import pytest

from lapis_design import draft, integrity, next_step, order, owner, slice_step, waiting
from procedure_support import (TASK, ask, gaps_seen, make_project, record, reply, save, unseal_slice, update)

URL = "http://127.0.0.1:4173/slice.html"
FILES = ["index.html", "style.css", "app.js"]


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    unseal_slice(root)
    (root / ".lapis/fonts.lock.json").unlink()
    return root


def declare(root: Path, sources: list[str] = FILES, direction: str = "new", core: list[dict] | None = None,
            extracts: list[str] | None = None) -> None:
    """The slice page in the draft record, as the run declares it before it builds, with a critic report that holds `core`."""
    save(root, "critic/shown-0.json", {"version": 0, "tool": {"name": "critic", "version": "0.1.0"},
                                         "target": {"packet": {"path": ".lapis/critic/packet.json", "sha256": "1" * 64}},
                                         "findings": core or []})
    save(root, f"drafts/{TASK}.yaml", {"version": 0, "task": TASK, "pages": [
        {"url": URL, "render_task": "shown", "sources": sources, "direction": direction, "area": "first view",
         "widths": [390, 1440], "behavior_changed": False,
         "review": {"extracts": extracts or [], "critic": {"report": ".lapis/critic/shown-0.json"}}}]})


def write(root: Path, name: str = "index.html", env: dict | None = None) -> dict | None:
    """The hook's answer to an edit tool writing `name`."""
    event = {"cwd": str(root), "tool_input": {"file_path": str(root / name)}}
    return order.decide(event, env or {})


def refused(answer: dict | None) -> str | None:
    return answer["hookSpecificOutput"]["permissionDecisionReason"] if answer else None


def step_of(root: Path) -> dict:
    return next_step.evaluate(root, TASK)["step"]


# ---- the hold on the files

def test_a_write_to_an_undeclared_page_file_is_refused_and_a_declared_file_and_a_record_are_not(project):
    declare(project)
    assert write(project, "index.html") is None and write(project, "app.js") is None
    why = refused(write(project, "pricing.html"))
    assert "task kiln-shop-landing has an unsealed slice" in why and "pricing.html is not one of them" in why
    assert f"Build only the slice files declared in .lapis/drafts/{TASK}.yaml" in why
    assert "a questions file of kind `approval`" in why and "owner block" in why
    assert write(project, ".lapis/specimens/rough.html") is None and write(project, "notes.md") is None
    assert write(project, "pricing.html") is not None                           # no cap: it refuses again


def test_a_write_with_no_slice_page_declared_or_more_than_twelve_files_declared_refuses_every_page_write(project):
    assert next_step.evaluate(project, TASK)["step"]["id"] == "slice"
    assert "Declare the slice page first" in refused(write(project, "index.html"))
    declare(project, [f"part-{n}.html" for n in range(12)])
    assert write(project, "part-0.html") is None
    declare(project, [f"part-{n}.html" for n in range(13)])
    assert "declares 13 files, and a slice is at most 12" in refused(write(project, "part-0.html"))


def test_the_hold_starts_when_next_first_names_slice_not_before(project):
    update(project, f"plans/{TASK}.yaml", lambda plan: plan.pop("brief"))               # a plan blocker comes first
    assert write(project, "pricing.html") is None
    assert (integrity.read_state(project, TASK) or {}).get("slice_since") is None


def test_a_redesign_a_repair_and_an_unattended_run_are_not_held(project, monkeypatch):
    declare(project)
    assert refused(write(project, "pricing.html"))
    assert write(project, "pricing.html", {"LAPIS_UNATTENDED": "1"}) is None
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    assert step_of(project)["id"] == "fonts-lock"
    monkeypatch.delenv("LAPIS_UNATTENDED")
    update(project, f"plans/{TASK}.yaml", lambda plan: plan.update(mode="repair"))
    assert write(project, "pricing.html") is None


def test_an_owner_skip_lifts_the_hold_and_the_step_and_the_block_says_so(project):
    declare(project)
    assert refused(write(project, "pricing.html"))
    record(project, "answers", (project / f".lapis/answers/{TASK}.md").read_text(encoding="utf-8")
           + '\n## Replies\n\n- Slice skipped: "build it all, I will look at the whole page"\n', 60)
    assert write(project, "pricing.html") is None and step_of(project)["id"] == "fonts-lock"
    text, _ = owner.block(project, TASK)
    assert 'Slice skipped by you: "build it all, I will look at the whole page"' in text
    from lapis_design import requirements

    assert not any("Slice skipped" in row["text"] for row in requirements.rows(project, TASK))


# ---- the clock

def later(root: Path, monkeypatch, minutes: int) -> None:
    """`minutes` after the clock started (`state.slice_since`, which `next` records the first time it names the slice)."""
    started = slice_step._parse(integrity.read_state(root, TASK)["slice_since"])
    monkeypatch.setattr(slice_step, "now", lambda: started + timedelta(minutes=minutes))


def test_at_61_minutes_every_page_write_is_refused_and_next_says_overdue(project, monkeypatch):
    declare(project)
    assert write(project) is None
    later(project, monkeypatch, 60)
    assert write(project) is None
    later(project, monkeypatch, 61)
    why = refused(write(project, "index.html"))
    assert "The slice is overdue (61 minutes since" in why and "every page write is refused" in why
    step = step_of(project)
    assert step["id"] == "slice" and step["why"].startswith("The slice is overdue (61 minutes since")
    assert write(project, ".lapis/specimens/rough.html") is None                  # records are never refused

def test_the_forty_first_page_write_is_refused_and_an_approval_question_with_the_block_lifts_it(project):
    declare(project)
    assert [write(project) for _ in range(40)] == [None] * 40
    assert "40 page writes since" in refused(write(project))
    now = int(time.time())
    ask(project, f"Approve this slice? {URL}", now + 5)
    assert write(project) is None


def test_a_question_without_the_current_block_or_without_the_page_does_not_lift_it(project, monkeypatch):
    declare(project)
    step_of(project)                                                                 # `next` names the slice: the clock starts
    later(project, monkeypatch, 61)
    now = int(time.time())
    ask(project, f"Approve this slice? {URL}", now + 5)
    path = project / f".lapis/questions/{TASK}.md"
    path.write_text(path.read_text(encoding="utf-8").replace("lapis-owner-block ", "lapis-owner-block 0000"), encoding="utf-8")
    assert "overdue" in refused(write(project))
    ask(project, "Approve this slice? nothing is linked", now + 6)
    assert "overdue" in refused(write(project))

def test_an_answered_ask_restarts_the_clock(project, monkeypatch):
    declare(project)
    step_of(project)
    now = int(time.time())
    later(project, monkeypatch, 61)
    assert "overdue" in refused(write(project))
    ask(project, "1. Keep the repeated plate?\nTrigger: finding-vs-decision — critic\nDefault: a — keep it.\n", now + 3700,
        kind="ask")
    next_step.evaluate(project, TASK)                                                # the log sees the set
    reply(project, "- [declared] Ask finding-vs-decision: a — keep it", now + 3710)
    next_step.evaluate(project, TASK)                                                # and sees it answered
    assert write(project) is None


# ---- a tall slice, core findings, rounds

def extract(root: Path, bottom: int) -> str:
    save(root, "renders/shown.json", {"version": 1, "source": {"kind": "render", "url": URL, "task": "shown"},
                                      "viewports": [{"width": 1440, "boxes": [{"rect": {"x": 0, "y": 0, "w": 1440, "h": bottom}}]}]})
    return ".lapis/renders/shown.json"


@pytest.fixture
def checked(monkeypatch):
    """`draft check` accepts the page and reports the core findings its critic report holds open."""
    def check(root, task, *, asked=None):
        report = json.loads((root / ".lapis/critic/shown-0.json").read_text(encoding="utf-8"))
        core = [{"rule_id": f["rule_id"], "observed": f["observed"], "report": ".lapis/critic/shown-0.json"}
                for f in report["findings"] if draft.is_core(f)]
        return [], [{"url": URL, "area": "first view", "widths": [390, 1440], "findings": [], "core_open": core, "critic": None}]
    monkeypatch.setattr(draft, "check", check)


def test_a_shown_page_taller_than_3600_px_at_1440_returns_slice_instead_of_waiting(project, checked):
    declare(project, extracts=[extract(project, 3601)])
    ask(project, f"Approve this slice? {URL}", 200)
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "slice")
    assert "3,601 px tall at 1440" in result["step"]["why"] and "cut it to the first view and the one section" in result["step"]["why"]
    declare(project, extracts=[extract(project, 3600)])
    ask(project, f"Approve this slice? {URL}", 210)
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"


CORE = {"rule_id": "copy.fabricated-proof", "status": "open", "observed": "the page shows two invented customer quotes",
        "approval_impact": "core-product-explanation"}


def approved(root: Path) -> None:
    update(root, f"plans/{TASK}.yaml", lambda plan: plan.update(approval={"state": "approved"}))


def test_an_open_core_finding_no_longer_blocks_the_wait_and_the_block_lists_it_for_the_owner(project, checked):
    declare(project, core=[CORE])
    ask(project, f"Approve this slice? {URL}", 200)
    result = next_step.evaluate(project, TASK)
    assert result["state"] == "waiting-for-user"
    assert ("## Open core findings: your decision\nThe critic's report still holds these open. Say what to do about each"
            in result["owner_block"])
    assert "- copy.fabricated-proof: the page shows two invented customer quotes" in result["owner_block"]


def test_a_core_finding_open_stops_the_seal_until_a_fresh_critic_closes_it_or_the_owner_decides_it(project, checked):
    declare(project, core=[CORE])
    approved(project)
    ask(project, f"Approve this slice? {URL}", 200)
    reply(project, "- [declared] The first view is right.\n" + gaps_seen(project), 210)
    result = next_step.evaluate(project, TASK)
    why = result["step"]["why"]
    assert result["step"]["id"] == "slice" and "core finding open (copy.fabricated-proof: the page shows two invented" in why
    assert "`- [declared] Ask finding-vs-decision: <rule id> — <their words>`" in why
    assert (integrity.read_state(project, TASK) or {}).get("slice") is None
    declare(project, core=[])                                                      # a fresh critic report closes it
    assert next_step.evaluate(project, TASK)["step"]["id"] == "fonts-lock"


def test_the_owners_decision_on_a_core_finding_lets_the_slice_seal(project, checked):
    declare(project, core=[CORE])
    approved(project)
    ask(project, f"Approve this slice? {URL}", 200)
    reply(project, "- [declared] The first view is right.\n"
          '- [declared] Ask finding-vs-decision: copy.fabricated-proof — keep the two quotes, they are real, I will send the sources\n'
          + gaps_seen(project), 210)
    assert next_step.evaluate(project, TASK)["step"]["id"] == "fonts-lock"
    assert integrity.read_state(project, TASK)["slice"]["url"] == URL


def test_an_unapproved_reply_starts_round_two_restarts_the_clock_and_keeps_the_hold(project, checked, monkeypatch):
    declare(project, extracts=[extract(project, 2400)])
    update(project, f"plans/{TASK}.yaml", lambda plan: plan.update(approval={"state": "assumed", "reason": "nobody could be asked"}))
    ask(project, f"Approve this slice? {URL}", 200)
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"
    state = integrity.read_state(project, TASK)
    assert state["slice_rounds"] == 1
    first = state["slice_since"]
    later(project, monkeypatch, 30)
    reply(project, "- [declared] Make the headline calmer, and show the firing log higher up.\n" + gaps_seen(project), 210)
    result = next_step.evaluate(project, TASK)
    why = result["step"]["why"]
    assert result["step"]["id"] == "slice" and why.startswith("Slice round 2: the owner answered and did not approve (rows R")
    assert "within the slice files you declared" in why and "a direction reply" in why
    state = integrity.read_state(project, TASK)
    assert state["slice_rounds"] == 2 and state["slice_heights"] == {"1": 2400}
    assert state["slice_since"] > first                                                         # the clock restarted
    assert next_step.evaluate(project, TASK)["step"]["why"].startswith("Slice round 2")           # counted once
    assert integrity.read_state(project, TASK)["slice_rounds"] == 2
    assert refused(write(project, "pricing.html")) and write(project, "index.html") is None       # the hold goes on
    text, _ = owner.block(project, TASK)
    assert "- Slice rounds: 2\n  - round 1: document height at 1440: 2,400 px" in text


def test_a_revision_is_round_two_even_when_the_draft_review_is_stale_when_next_first_sees_the_reply(project, checked, monkeypatch):
    declare(project, extracts=[extract(project, 2400)])
    update(project, f"plans/{TASK}.yaml", lambda plan: plan.update(approval={"state": "assumed", "reason": "nobody could be asked"}))
    ask(project, f"Approve this slice? {URL}", 200)
    reply(project, "- [declared] Make the headline calmer.\n" + gaps_seen(project), 210)
    fresh = draft.check
    monkeypatch.setattr(draft, "check", lambda root, task, *, asked=None: (["the critic packet is stale"], []))
    assert "The slice cannot be sealed: the critic packet is stale" in step_of(project)["why"]
    state = integrity.read_state(project, TASK)
    assert state["slice_rounds"] == 2 and state["slice_heights"] == {"1": 2400}
    monkeypatch.setattr(draft, "check", fresh)
    assert step_of(project)["why"].startswith("Slice round 2")                   # counted once
    assert integrity.read_state(project, TASK)["slice_rounds"] == 2


def test_a_slice_of_more_than_one_linked_new_page_is_not_sealed(project, checked):
    declare(project)
    update(project, f"drafts/{TASK}.yaml", lambda doc: doc["pages"].append({**doc["pages"][0], "url": URL + "?b"}))
    approved(project)
    ask(project, f"Approve this slice? {URL} and {URL}?b", 200)
    reply(project, "- [declared] The first view is right.\n" + gaps_seen(project), 210)
    result = next_step.evaluate(project, TASK)
    assert result["step"]["id"] == "slice" and "The slice is one page" in result["step"]["why"]
    assert integrity.read_state(project, TASK).get("slice") is None
