"""The direction conversation (`direction.py`): the proposal's form, the answers that settle each item, when the step
`owner-direction` is owed and when a `direction` questions file waits, the pick of the second turn, and what the
requirement record and the critic packet make of the answers. The roughs of the second turn are drawn, made, and sealed with
the real `diverge` commands; their own cases are in `test_diverge.py`."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from diverge_support import FACES, complete, inventory, write_rough
from lapis_design import critic_packet, direction, diverge, next_step, requirements
from procedure_support import (BRIEF_RECORD, DIRECTION_PROPOSAL, TASK, ask, load_skills, make_project, record, save,
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
def attended(monkeypatch, tmp_path_factory):
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", str(inventory(tmp_path_factory.mktemp("inventory") / "lazuli.db", *FACES.values())))


@pytest.fixture
def run(tmp_path) -> Path:
    """A create run after its references, with the full proposal and no answer to it."""
    record(tmp_path, "answers", BRIEF, 50)
    seal_requirements(tmp_path)
    write_references(tmp_path)
    reset_diverge(tmp_path)                                      # the fixture ran the whole conversation: undo it
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


def reset_diverge(root: Path) -> None:
    """No rough drawn, made, or sealed."""
    for name in (".lapis/state/diverge", ".lapis/diverge"):
        shutil.rmtree(root / name, ignore_errors=True)
    for file in (root / ".lapis/renders").glob(f"{TASK}-C*.narrow*"):
        shutil.rmtree(file) if file.is_dir() else file.unlink()


def seal_diverge(root: Path, signature: dict[str, list[dict]]) -> None:
    """The roughs drawn, made, and sealed with the real commands (`diverge_support.complete`); each rough's card then
    holds the signature elements given, as an agent may add them (the seal reports an edit, never refuses it)."""
    reset_diverge(root)
    complete(root, TASK, len(signature))
    for cid, elements in signature.items():
        file = root / ".lapis" / "diverge" / TASK / cid / "card.yaml"
        file.write_text(yaml.safe_dump({**yaml.safe_load(file.read_text(encoding="utf-8")), "signature": elements}), encoding="utf-8")


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


def test_a_type_role_item_asks_whether_the_owner_has_fonts_they_have_not_installed_and_a_proposal_without_one_stays_valid(run):
    doc = proposal()
    doc["type_roles"] = [{"id": "T1", "role": "heading"}, {"id": "T2", "role": "body"}]
    save(run, f"direction/{TASK}.yaml", doc)
    assert direction.proposal_problem(run, TASK) is None
    items = {i["id"]: i for i in direction.items(run, TASK, {})}
    assert items["T2"]["kind"] == "T" and items["T2"]["default"] == "a" and items["T2"]["state"] == "open"
    assert items["T2"]["label"] == "body: Are there fonts you own but have not installed that I should consider?"
    assert [o["id"] for o in items["T2"]["options"]] == ["a", "b"] and "lazuli owned add" in items["T2"]["options"][1]["text"]
    for change, fragment in [(lambda d: d["type_roles"][1].update(role="heading"), "twice for the role heading"),
                             (lambda d: d["type_roles"][1].update(id="T1"), "repeats the type-role id T1"),
                             (lambda d: d["type_roles"][1].update(id="K9"), "id"),
                             (lambda d: d["type_roles"][1].update(role="Body Text"), "role")]:
        broken = proposal()
        broken["type_roles"] = [{"id": "T1", "role": "heading"}, {"id": "T2", "role": "body"}]
        change(broken)
        save(run, f"direction/{TASK}.yaml", broken)
        assert fragment in (direction.proposal_problem(run, TASK) or ""), fragment


def test_the_first_turn_is_owed_until_each_type_role_has_an_owner_answer_and_the_question_is_named(run):
    doc = proposal()
    doc["type_roles"] = [{"id": "T1", "role": "heading"}, {"id": "T2", "role": "body"}]
    save(run, f"direction/{TASK}.yaml", doc)
    settled = ['- [declared] S1 neo-brutalism: a — "show the record"', '- [declared] K1 slabs: keep — "yes"',
               '- [declared] K2 ticker band: drop — "no ticker"', '- [declared] O1 the log: b — "the fader one"']
    answer(run, *settled)
    why = next_step.evaluate(run, TASK)["step"]["why"]
    assert next_step.evaluate(run, TASK)["step"]["id"] == "owner-direction"
    assert "T1 heading: Are there fonts you own but have not installed that I should consider?" in why and "T2 body" in why
    answer(run, *settled, '- [declared] T1 heading: a — "no, just what is installed"')
    assert states(run)["T1"] == "decided" and states(run)["T2"] == "open" and step_of(run) == "owner-direction"
    answer(run, *settled, '- [declared] T1 heading: a — "no, just what is installed"',
           '- [declared] T2 body: b — "yes, I have Qqq Serif in my Adobe library"')
    assert step_of(run) != "owner-direction"
    found = {i["id"]: i for i in direction.items(run, TASK, {})}
    assert (found["T2"]["choice"], found["T2"]["by"]) == (["b"], "owner")
    answer(run, *settled, '- [declared] T1 heading: c — "x"', '- [declared] T2 body: all — "x"')
    assert states(run)["T1"] == states(run)["T2"] == "open"                      # no such option
    answer(run, '- Defaults accepted (direction 1): "no owned fonts, go with your defaults"')
    assert states(run)["T1"] == "delegated" and {i["default"] for i in direction.items(run, TASK, {}) if i["kind"] == "T"} == {"a"}


def test_a_type_role_answer_is_a_requirement_row_the_critic_judges(run):
    answer(run, '- [declared] T2 body: b — "yes, I have Qqq Serif in my Adobe library"')
    seal_requirements(run)
    assert any(r["text"].startswith("T2 body: b") for r in requirements.rows(run, TASK))


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
    seal_diverge(run, {"C1": [{"id": "G1", "element": "crystal stone", "carries": "the three plugin names"}], "C2": []})
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
    diverge.variant(run, TASK, "bolder, not a card list")
    assert direction.pick(run, TASK, {}) is None and step_of(run) == "diverge"          # the new rough is not made or sealed
    write_rough(run, TASK, "C3")
    diverge.seal(run, TASK)
    assert step_of(run) == "owner-direction" and "no `Pick:`" in next_step.evaluate(run, TASK)["step"]["why"]
    answer(run, '- Defaults accepted (direction 1): "x"', '- [declared] Pick: C2 — "this"', '- [declared] Pick: C2 — "still this"')
    assert direction.pick(run, TASK, {})["candidate"] == "C2" and step_of(run) != "owner-direction"


def test_an_unattended_pick_is_assumed_and_counts_only_with_its_basis(run, monkeypatch):
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    settled(run)
    seal_diverge(run, {"C1": [], "C2": []})
    base = '- Defaults accepted (direction 1): "your defaults are fine"'
    answer(run, base, "- [assumed] Pick: C2 — it looks fine")
    assert direction.pick(run, TASK, {"LAPIS_UNATTENDED": "1"}) is None
    assert "1 [assumed] items give no `Basis:`" in next_step.evaluate(run, TASK)["step"]["why"]
    answer(run, base, "- [assumed] Pick: C2 — Basis: the references show the fader strip working on a phone.")
    assert direction.pick(run, TASK, {"LAPIS_UNATTENDED": "1"})["by"] == "assumed" and step_of(run) != "owner-direction"
    assert direction.pick(run, TASK, {}) is None                                          # an attended run takes no assumed pick


# ---- 4. the questions that wait

def test_a_direction_file_with_fifteen_items_waits_and_is_not_under_the_brief_cap(run):
    save(run, f"direction/{TASK}.yaml", {**proposal(), "styles": [
        {**proposal()["styles"][0], "kit": [{"id": f"K{n}", "item": f"kit item {n}", "seen_in": ["ref-1"],
                                             "default": "keep", "why": "seen"} for n in range(1, 14)]}]})
    ids = ["S1", *[f"K{n}" for n in range(1, 14)], "O1", "G1"]
    questions = "".join(f"{n}. Keep or drop this part? ({i})\n" for n, i in enumerate(ids, 1))
    record(run, "questions", "lapis-questions: direction\n" + questions, 200)
    unpasted = next_step.evaluate(run, TASK)                     # the owner block is the CLI's: the file must carry it
    assert unpasted["state"] == "needs-step" and unpasted["step"]["id"] == "owner-direction"
    assert ".lapis/owner/" in unpasted["step"]["why"] and "lapis-owner-block" in unpasted["step"]["why"]
    ask(run, questions, 201, kind="direction")
    result = next_step.evaluate(run, TASK)
    assert (result["state"], result["then"]["id"]) == ("waiting-for-user", "owner-direction")
    assert result["waiting"]["kind"] == "direction" and result["owner_summary"].startswith(f"# Owner summary: {TASK}")
    assert "Decision: pick or change what the direction items name" in result["owner_summary"]


def test_a_style_name_with_colons_does_not_hide_the_choice(run):
    answer(run, '- [declared] S1 neo-brutalism: bold and dynamic: a — "the record one"',
           '- [declared] K1 slabs: drop — "no"', '- [declared] K2 ticker: all: keep',
           '- [declared] O1 the log: all — "all"', '- [declared] G1 animation: other: the first one: b')
    found = {i["id"]: i for i in direction.items(run, TASK, {})}
    assert found["S1"]["state"] == "decided" and found["S1"]["choice"] == ["a"]
    assert found["K2"]["choice"] == ["keep"] and found["O1"]["choice"] == ["all"]
    assert found["G1"]["choice"] == ["b"]
    answer(run, '- [declared] S1 neo-brutalism: other — "my own"', '- [declared] O1 the log: a,c — "two"')
    found = {i["id"]: i for i in direction.items(run, TASK, {})}
    assert found["S1"]["choice"] == ["other"] and found["O1"]["choice"] == ["a", "c"]


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
    assert section["pick"]["candidate"] == "C2" and section["pick"]["captures"] == [
        f".lapis/renders/{TASK}-C2.narrow.shots/{width}-light.png" for width in (1440, 390)]
    assert section["contact"] == f".lapis/state/diverge/{TASK}/contact.png"
    assert section["pick"]["card"]["id"] == "C2" and section["pick"]["card"]["signature"][0]["element"] == "fader strip"
    listed = {i["path"]: i["kind"] for i in data["inputs"]}
    assert listed[section["contact"]] == "direction-contact" and listed[section["pick"]["captures"][0]] == "direction-capture"
    assert "why" not in json.dumps(section) and "they can carry the three plugins" not in json.dumps(section)


# ---- 6. the questions put each item in plain words

PLAIN = ("What should the neo-brutalist look do for your visitors? (S1)\n"
         "   a) expose the record: every block shows its raw text (default)\n"
         "Keep or drop the full-bleed slabs? (K1) And the ticker band? (K2)\n"
         "How should the page show the firing log? (O1)\n"
         "   a) ruled rows (ledger)  b) a fader between versions (fader-overlay)  c) an annotated diff (annotated-diff)\n"
         "What should the procedure animation tell the visitor? (G1)\n")


def asked_with(run: Path, text: str) -> dict:
    ask(run, text, 201, kind="direction")
    return next_step.evaluate(run, TASK)


def why_of(result: dict) -> str:
    assert result["state"] == "needs-step" and result["step"]["id"] == "owner-direction", result["state"]
    return result["step"]["why"]


def test_questions_in_plain_words_with_ids_and_family_names_in_parentheses_wait(run):
    result = asked_with(run, PLAIN)
    assert (result["state"], result["then"]["id"]) == ("waiting-for-user", "owner-direction")
    assert direction.questions_problem(run, TASK, {}) is None


@pytest.mark.parametrize("line", ["S1 neo-brutalism: what should it do here?", "1. K2 ticker band: keep or drop?",
                                  "- **O1** the firing log: pick one", "> G1, the animation: what does it carry?"])
def test_a_line_that_opens_with_an_item_id_does_not_wait_and_names_the_line(run, line):
    why = why_of(asked_with(run, f"{PLAIN}{line}\n"))
    assert "do not wait: the line" in why and "opens with the item id" in why and "in plain words first" in why
    assert "(for example `What should neo-brutalism do here? (S1)`)" in why


def test_a_family_name_outside_parentheses_does_not_wait_and_inside_parentheses_does(run):
    why = why_of(asked_with(run, f"{PLAIN}Option b is the fader-overlay version of the log.\n"))
    assert "shows the family name fader-overlay outside parentheses" in why
    assert asked_with(run, PLAIN)["state"] == "waiting-for-user"                  # the same name, in parentheses


def test_a_recorded_distance_between_roughs_does_not_wait_but_the_same_number_elsewhere_does(run):
    save(run, f"state/diverge/{TASK}/distances.json",
         {"version": 0, "pairs": [{"a": "C1", "b": "C2", "total": 0.43, "struct": 0.51, "mass": 0.12, "repr": 0.33}]})
    for line in ("The distance between the roughs is 0.43.", "C1 and C2 differ by .51 in structure",
                 "C1 vs C2: total 0.43 (struct 0.51, mass 0.12, repr 0.33)"):
        why = why_of(asked_with(run, f"{PLAIN}{line}\n"))
        assert "shows the distance number" in why and "stay in the records and the critic packet" in why
    assert (asked_with(run, f"{PLAIN}The slabs take 0.43 of the width at 1440.\n")["state"], ) == ("waiting-for-user",)
    assert (asked_with(run, f"{PLAIN}The roughs differ in how the first view is laid out.\n")["state"], ) == ("waiting-for-user",)


def test_with_no_recorded_distances_a_number_next_to_the_word_distance_is_the_runs_own_words(run):
    assert asked_with(run, f"{PLAIN}The commute distance on the page is 0.43 of the route.\n")["state"] == "waiting-for-user"


def test_after_the_seal_a_line_that_opens_with_a_roughs_signature_id_does_not_wait(run):
    settled(run)
    seal_diverge(run, {"C1": [{"id": "G1", "element": "crystal stone", "carries": "the three plugin names as facets"}],
                       "C2": [{"id": "G1", "element": "fader strip", "carries": "which page is shown"}]})
    opening = "Which rough do you pick (Pick), and do you want the crystal stone (C1.G1) and the fader strip (C2.G1)?\n"
    ask(run, opening, 201, kind="direction")
    assert "Pick" in direction.asked(run, TASK, {}) and direction.questions_problem(run, TASK, {}) is None
    ask(run, f"{opening}C2.G1 fader strip: which page is shown\n", 202, kind="direction")
    assert "opens with the item id C2.G1" in direction.questions_problem(run, TASK, {})
    ask(run, f"{opening}Pick the rough you like best.\n", 203, kind="direction")
    assert direction.questions_problem(run, TASK, {}) is None                    # `Pick` is a word, not an id
