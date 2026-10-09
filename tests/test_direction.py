"""The direction conversation (`direction.py`): the proposal's form, the answers that settle each item, when the step
`owner-direction` is owed and when a `direction` questions file waits, the pick of the second turn, and what the
requirement record and the critic packet make of the answers. Files only; the draws and renders of `diverge` have
their own tests (`test_diverge.py`)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from lapis_design import critic_packet, direction, next_step, requirements
from procedure_support import (BRIEF_RECORD, DIRECTION_PROPOSAL, TASK, load_skills, make_project, record, save,
                               seal_requirements, write_references)

BRIEF = BRIEF_RECORD.split("## Direction 1")[0]


def proposal() -> dict:
    """Three items a style carries, an object with three representations, and one signature element."""
    return {
        "version": 0, "task": TASK,
        "styles": [{"id": "S1", "name": "neo-brutalism", "default": "a",
                    "options": [{"id": "a", "text": "expose the record: every block shows its raw text"},
                                {"id": "b", "text": "collision: display words break the grid on purpose"},
                                {"id": "c", "text": "bare HTML: system type and underlined links"}],
                    "kit": [{"id": "K1", "item": "full-bleed slabs with drawn line fields", "seen_in": ["ref-1"],
                             "default": "keep", "why": "they can carry the three plugins"},
                            {"id": "K2", "item": "ticker band between slabs", "seen_in": ["ref-2"], "default": "drop",
                             "why": "it moves without carrying information"}]}],
        "objects": [{"id": "O1", "object": "the monthly firing log", "kind": "record-document", "default": "all",
                     "options": [{"id": "a", "text": "the log as ruled rows", "family": "ledger",
                                  "does": "scan which pieces are free", "source": "ref-1"},
                                 {"id": "b", "text": "this firing over last month's", "family": "fader-overlay",
                                  "does": "move a fader between versions", "source": "own"},
                                 {"id": "c", "text": "the two versions as an annotated diff", "family": "annotated-diff",
                                  "does": "accept a change", "source": "the firing log"}]}],
        "signature": [{"id": "G1", "element": "procedure animation", "default": "a",
                       "options": [{"id": "a", "text": "which step is current and what it produced"},
                                   {"id": "b", "text": "only the order of the steps"}]}]}


@pytest.fixture(autouse=True)
def attended(monkeypatch):
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")


@pytest.fixture
def run(tmp_path) -> Path:
    """A create run after its references, with the full proposal and no answer to it."""
    record(tmp_path, "answers", BRIEF, 50)
    seal_requirements(tmp_path)
    write_references(tmp_path)
    record(tmp_path, "answers", BRIEF, 50)                       # no answer to the conversation yet
    save(tmp_path, f"direction/{TASK}.yaml", proposal())
    return tmp_path


def answer(root: Path, *lines: str, turn: int = 1, at: int = 60) -> None:
    body = "\n".join(lines)
    record(root, "answers", f"{BRIEF}\n## Direction {turn}\n\n{body}\n", at)


def step_of(root: Path) -> str:
    result = next_step.evaluate(root, TASK)
    return result["step"]["id"] if result["step"] else "done"


def states(root: Path, env: dict | None = None) -> dict[str, str]:
    return {i["id"]: i["state"] for i in direction.items(root, TASK, env or {})}


def seal_diverge(root: Path, signature: dict[str, list[dict]], d1_turns: int = 1) -> None:
    """A sealed set of roughs as the CLI writes it, with the cards the agent wrote."""
    for cid, elements in signature.items():
        card = root / ".lapis" / "diverge" / TASK / cid / "card.yaml"
        card.parent.mkdir(parents=True, exist_ok=True)
        card.write_text(yaml.safe_dump({"id": cid, "signature": elements}), encoding="utf-8")
    state = root / ".lapis" / "state" / "diverge" / TASK
    state.mkdir(parents=True, exist_ok=True)
    (state / "seal.json").write_text(json.dumps({
        "version": 0, "task": TASK, "d1_turns": d1_turns, "contact": {"path": f".lapis/state/diverge/{TASK}/contact.png"},
        "candidates": {cid: {"captures": {"1440": {"path": f".lapis/diverge/{TASK}/{cid}/1440.png"}}}
                       for cid in signature}}), encoding="utf-8")


# ---- 1. the proposal's form

def test_a_well_formed_proposal_passes_and_each_malformed_one_is_named(run):
    assert direction.proposal_problem(run, TASK) is None
    cases = [
        (lambda d: d["styles"][0]["options"].__delitem__(slice(1, None)), "options"),             # one job is no choice
        (lambda d: d["styles"][0]["kit"][0].update(seen_in=["nowhere"]), "`seen_in` names nowhere"),
        (lambda d: d["objects"][0].update(kind="gadget"), "the kind 'gadget'"),
        (lambda d: d["objects"][0].update(default="z"), "default"),
        (lambda d: d["styles"][0].update(default="d"), "the default of S1"),
        (lambda d: d["styles"][0]["kit"][1].update(id="K1"), "repeats the kit id K1"),
        (lambda d: d["objects"][0]["options"][0].pop("does"), "does"),
        (lambda d: d.update(task="other-task"), "is for task"),
        (lambda d: d["signature"][0].update(id="X1"), "id"),
    ]
    for change, fragment in cases:
        doc = proposal()
        change(doc)
        save(run, f"direction/{TASK}.yaml", doc)
        assert fragment in (direction.proposal_problem(run, TASK) or ""), fragment
    (run / f".lapis/direction/{TASK}.yaml").unlink()
    assert "does not exist" in direction.proposal_problem(run, TASK)


def test_a_proposal_with_no_style_and_the_fixture_object_is_valid_and_a_style_less_task_asks_only_about_objects(run):
    save(run, f"direction/{TASK}.yaml", DIRECTION_PROPOSAL)
    assert direction.proposal_problem(run, TASK) is None
    assert [i["id"] for i in direction.items(run, TASK, {})] == ["O1"]


# ---- 2. the first turn

def test_the_first_turn_is_owed_until_every_style_kit_and_object_item_has_an_owner_answer(run):
    result = next_step.evaluate(run, TASK)
    assert result["step"]["id"] == "owner-direction" and result["step"]["command"] is None
    why = result["step"]["why"]
    assert "turn one" in why and "S1 neo-brutalism" in why and "K2 ticker band between slabs" in why and "O1" in why
    assert "lapis-questions: direction" in why and "## Direction" in why and "Defaults accepted" in why
    answer(run, '- [declared] S1 neo-brutalism: a — "show the record"', '- [declared] K1 slabs: keep — "yes"',
           '- [declared] K2 ticker band: drop — "no ticker"')
    assert step_of(run) == "owner-direction"                                    # O1 is still open
    assert states(run) == {"S1": "decided", "K1": "decided", "K2": "decided", "O1": "open", "G1": "open"}
    answer(run, '- [declared] S1 neo-brutalism: a — "show the record"', '- [declared] K1 slabs: keep — "yes"',
           '- [declared] K2 ticker band: drop — "no ticker"', '- [declared] O1 the log: b — "the fader one"')
    assert step_of(run) != "owner-direction"                                    # G1 is asked, never gating, at the first turn


def test_an_object_cut_to_two_options_is_narrowed_and_one_option_is_decided(run):
    answer(run, '- [declared] O1 the log: a, c — "not the fader"')
    found = {i["id"]: i for i in direction.items(run, TASK, {})}
    assert (found["O1"]["state"], found["O1"]["choice"], found["O1"]["by"]) == ("narrowed", ["a", "c"], "owner")
    answer(run, '- [declared] O1 the log: b — "this one"')
    assert states(run)["O1"] == "decided"
    answer(run, "- [declared] O1 the log: all — \"try them all\"")
    assert states(run)["O1"] == "decided"


def test_an_answer_that_names_no_option_does_not_settle_the_item(run):
    answer(run, '- [declared] S1 neo-brutalism: e — "x"', '- [declared] K1 slabs: a — "x"', '- [declared] O1 the log: z')
    assert states(run)["S1"] == states(run)["K1"] == states(run)["O1"] == "open"


def test_defaults_accepted_takes_every_open_item_and_an_answer_still_wins_over_it(run):
    answer(run, '- [declared] K2 ticker band: keep — "keep the ticker"',
           '- Defaults accepted (direction 1): "your defaults are fine"')
    found = {i["id"]: i for i in direction.items(run, TASK, {})}
    assert found["K2"]["state"] == "decided" and found["K2"]["choice"] == ["keep"]
    assert {i: found[i]["state"] for i in ("S1", "K1", "O1", "G1")} == {k: "delegated" for k in ("S1", "K1", "O1", "G1")}
    assert found["S1"]["choice"] == ["a"] and found["O1"]["choice"] == ["all"] and found["K1"]["choice"] == ["keep"]
    assert step_of(run) != "owner-direction"
    assert [d["kind"] for d in direction.decisions(run, TASK)] == ["defaults"]


def test_an_assumed_answer_never_counts_in_an_attended_run_and_counts_unattended_only_with_its_basis(run, monkeypatch):
    lines = ('- [assumed] S1 neo-brutalism: a — Basis: nobody to ask; the brief says the record is the subject.',
             '- [assumed] K1 slabs: keep — Basis: the references show them carrying content in two places.',
             '- [assumed] K2 ticker band: drop — Basis: it carries no information in the references.',
             '- [assumed] O1 the log: b — nothing more')
    answer(run, *lines)
    assert states(run)["S1"] == "open" and step_of(run) == "owner-direction"        # attended
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    assert states(run, {"LAPIS_UNATTENDED": "1"}) == {"S1": "decided", "K1": "decided", "K2": "decided", "O1": "open",
                                                      "G1": "open"}
    why = next_step.evaluate(run, TASK)["step"]["why"]
    assert "[assumed]" in why and "Basis" in why and "1 [assumed] items give no `Basis:`" in why
    answer(run, *lines[:3], '- [assumed] O1 the log: b — Basis: it is the version the references show working.')
    assert step_of(run) != "owner-direction"
    assert {i["by"] for i in direction.items(run, TASK, {"LAPIS_UNATTENDED": "1"}) if i["state"] == "decided"} == {"assumed"}


def test_the_conversation_does_not_touch_the_briefs_cap_on_answers(run):
    from lapis_design import brief

    answer(run, *[f'- [declared] K{n} item: keep — "x"' for n in range(1, 12)])
    assert brief.cap_problem(run, TASK) is None


# ---- 3. the second turn

def settled(run: Path) -> None:
    answer(run, '- Defaults accepted (direction 1): "your defaults are fine"')


def test_the_second_turn_is_owed_only_after_the_seal_and_until_the_pick_and_the_picked_rough_signature_are_answered(run):
    settled(run)
    seal_diverge(run, {"C1": [{"id": "G1", "element": "crystal stone", "carries": "the three plugin names as facets"}],
                       "C2": [{"id": "G1", "element": "fader strip", "carries": "which page is shown, with and without"}]})
    result = next_step.evaluate(run, TASK)
    assert result["step"]["id"] == "owner-direction" and "turn two" in result["step"]["why"]
    assert "no `Pick:`" in result["step"]["why"] and "contact.png" in result["step"]["why"]
    assert direction.asked(run, TASK, {}) == ["Pick", "C1.G1", "C2.G1"]
    answer(run, '- Defaults accepted (direction 1): "your defaults are fine"', '- [declared] Pick: C2 — "the fader one"',
           turn=1)
    assert step_of(run) == "owner-direction" and "C2.G1" in next_step.evaluate(run, TASK)["step"]["why"]
    assert direction.asked(run, TASK, {}) == ["C2.G1"]
    answer(run, '- Defaults accepted (direction 1): "your defaults are fine"', '- [declared] Pick: C2 — "the fader one"',
           '- [declared] C2.G1 fader strip: a — "yes, that is the job"')
    assert step_of(run) != "owner-direction"
    assert direction.pick(run, TASK, {}) == {"candidate": "C2", "by": "owner", "quote": '[declared] Pick: C2 — "the fader one"'}


def test_a_pick_of_a_rough_the_set_does_not_have_is_not_a_pick_and_the_last_pick_stands(run):
    settled(run)
    seal_diverge(run, {"C1": [], "C2": []})
    base = '- Defaults accepted (direction 1): "your defaults are fine"'
    answer(run, base, '- [declared] Pick: C7 — "the seventh"')
    assert "names no rough of the set" in next_step.evaluate(run, TASK)["step"]["why"]
    answer(run, base, '- [declared] Pick: C1 — "first"', '- [declared] Pick: C2 — "no, the second"')
    assert direction.pick(run, TASK, {})["candidate"] == "C2" and step_of(run) != "owner-direction"


def test_a_defaults_line_after_the_seal_takes_the_picked_rough_signature_and_one_before_it_does_not(run):
    settled(run)
    seal_diverge(run, {"C1": [{"id": "G1", "element": "crystal stone", "carries": "the three plugin names"}]})
    base = '- Defaults accepted (direction 1): "your defaults are fine"'
    answer(run, base, '- [declared] Pick: C1 — "this one"')
    assert next_step.evaluate(run, TASK)["step"]["id"] == "owner-direction"          # the turn-1 line is not a turn-2 answer
    answer(run, base, '- [declared] Pick: C1 — "this one"')
    record(run, "answers", (run / f".lapis/answers/{TASK}.md").read_text(encoding="utf-8")
           + '\n## Direction 2\n\n- Defaults accepted (direction 2): "all fine"\n', 70)
    assert direction.items(run, TASK, {})[-1]["state"] == "delegated" and step_of(run) != "owner-direction"


def test_a_variant_asked_for_after_the_pick_makes_the_pick_owed_again(run):
    settled(run)
    seal_diverge(run, {"C1": [], "C2": []})
    answer(run, '- Defaults accepted (direction 1): "x"', '- [declared] Pick: C2 — "this"')
    assert step_of(run) != "owner-direction"
    state = run / ".lapis" / "state" / "diverge" / TASK
    (state / "draws.jsonl").write_text(json.dumps({"id": "d1", "candidate": "C3", "variant": True, "picks_seen": 1}) + "\n",
                                       encoding="utf-8")
    assert direction.pick(run, TASK, {}) is None and step_of(run) == "owner-direction"
    answer(run, '- Defaults accepted (direction 1): "x"', '- [declared] Pick: C2 — "this"', '- [declared] Pick: C2 — "still this"')
    assert direction.pick(run, TASK, {})["candidate"] == "C2"


# ---- 4. the questions that wait

def test_a_direction_file_with_fifteen_items_waits_and_is_not_under_the_brief_cap(run):
    save(run, f"direction/{TASK}.yaml", {**proposal(), "styles": [
        {**proposal()["styles"][0], "kit": [{"id": f"K{n}", "item": f"kit item {n}", "seen_in": ["ref-1"],
                                             "default": "keep", "why": "seen"} for n in range(1, 14)]}]})
    ids = ["S1", *[f"K{n}" for n in range(1, 14)], "O1", "G1"]
    record(run, "questions", "lapis-questions: direction\n" + "".join(f"{n}. {i} — keep or drop?\n" for n, i in
                                                                       enumerate(ids, 1)), 200)
    result = next_step.evaluate(run, TASK)
    assert (result["state"], result["then"]["id"]) == ("waiting-for-user", "owner-direction")
    assert result["waiting"]["kind"] == "direction"


def test_a_direction_file_that_leaves_an_open_item_out_or_has_none_open_does_not_wait(run):
    record(run, "questions", "lapis-questions: direction\n1. S1, K1, K2 and O1: what should they do?\n", 200)
    result = next_step.evaluate(run, TASK)
    assert result["state"] == "needs-step" and "do not wait: it does not name the open items G1" in result["step"]["why"]
    settled(run)
    record(run, "questions", "lapis-questions: direction\n1. S1 K1 K2 O1 G1: anything else to decide?\n", 300)
    record(run, "answers", (run / f".lapis/answers/{TASK}.md").read_text(encoding="utf-8"), 100)
    result = next_step.evaluate(run, TASK)
    assert result["state"] == "needs-step" and "nothing to ask" in result["step"]["why"]


def test_an_unattended_run_never_waits_on_direction_questions(run, monkeypatch):
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    record(run, "questions", "lapis-questions: direction\n1. S1 K1 K2 O1 G1: what should they do?\n", 200)
    result = next_step.evaluate(run, TASK)
    assert result["state"] == "needs-step" and result["step"]["id"] == "owner-direction"
    assert "Nobody can be asked" in result["step"]["why"]


# ---- 5. what the records make of the answers

def test_a_declared_item_is_a_requirement_row_and_the_pick_is_not(run):
    answer(run, '- [declared] K2 ticker band: drop — "no ticker"', '- [declared] Pick: C2 — "the fader one"',
           '- Defaults accepted (direction 1): "fine"', '- [declared] O1 the log: a, c — "not the fader"')
    seal_requirements(run)
    texts = [r["text"] for r in requirements.rows(run, TASK)]
    assert any(t.startswith('K2 ticker band: drop') for t in texts) and any(t.startswith("O1 the log: a, c") for t in texts)
    assert not any("Pick" in t or "Defaults" in t for t in texts)


def test_the_critic_packet_resolves_the_chosen_option_to_its_text_and_leaves_the_makers_reasons_out(tmp_path, monkeypatch):
    run = make_project(tmp_path)
    save(run, f"direction/{TASK}.yaml", proposal())
    answer(run, '- [declared] O1 the log: a, c — "not the fader"', '- [declared] K2 ticker band: drop — "no ticker"',
           '- Defaults accepted (direction 1): "fine"', at=40)
    seal_diverge(run, {"C1": [], "C2": [{"id": "G1", "element": "fader strip", "carries": "which page is shown"}]})
    answer(run, '- [declared] O1 the log: a, c — "not the fader"', '- [declared] K2 ticker band: drop — "no ticker"',
           '- Defaults accepted (direction 1): "fine"', '- [declared] Pick: C2 — "the fader one"', at=40)
    data = json.loads(critic_packet.build(run, TASK, {"extracts": [f".lapis/renders/{TASK}.json"],
                                                     "lint": f".lapis/lint/{TASK}.json", "session": None}))
    section = data["direction"]
    o1 = next(i for i in section["items"] if i["id"] == "O1")
    assert (o1["state"], o1["choice"], o1["by"]) == ("narrowed", ["a", "c"], "owner")
    assert [(o["id"], o["text"]) for o in o1["options"]][0] == ("a", "the log as ruled rows")
    assert next(i for i in section["items"] if i["id"] == "K2")["choice"] == ["drop"]
    assert section["pick"]["candidate"] == "C2" and section["pick"]["captures"] == [f".lapis/diverge/{TASK}/C2/1440.png"]
    assert section["contact"] == f".lapis/state/diverge/{TASK}/contact.png"
    assert "why" not in json.dumps(section) and "they can carry the three plugins" not in json.dumps(section)
