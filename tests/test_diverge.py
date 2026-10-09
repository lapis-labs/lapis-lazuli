"""`lapis-design diverge`: the draws the CLI owns, the cards read against them, the distances measured from renders, the
contact sheet, the seal, and where the step sits between the two turns of the direction conversation."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from diverge_support import card_for, rough_html, signature, write_render, write_rough
from lapis_design import direction, diverge, next_step, references
from lapis_design.cli import main as cli_main
from procedure_support import (BRIEF_RECORD, DEFAULTS_ACCEPTED, DIRECTION_PROPOSAL, TASK, load_skills, make_project,
                               record, save, seal_requirements, write_references)

PROPOSAL = {**DIRECTION_PROPOSAL, "objects": [{**DIRECTION_PROPOSAL["objects"][0], "options": [
    *DIRECTION_PROPOSAL["objects"][0]["options"],
    {"id": "c", "text": "the two versions as an annotated diff", "family": "annotated-diff",
     "does": "accept a change", "source": "own"}]}]}


@pytest.fixture(autouse=True)
def attended(monkeypatch):
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")


def conversation(root: Path, answers: str = DEFAULTS_ACCEPTED) -> None:
    """The brief record with `answers` to the first turn, as old as the brief."""
    record(root, "answers", BRIEF_RECORD + answers, 50)


@pytest.fixture
def run(tmp_path) -> Path:
    """A create run that has its references and a first turn answered with the defaults, and has not drawn."""
    record(tmp_path, "answers", BRIEF_RECORD, 50)
    seal_requirements(tmp_path)
    load_skills(tmp_path)
    write_references(tmp_path)                                     # the record (and, here, a finished conversation)
    shutil.rmtree(tmp_path / ".lapis/state/diverge")
    shutil.rmtree(tmp_path / ".lapis/diverge")
    save(tmp_path, f"direction/{TASK}.yaml", PROPOSAL)
    conversation(tmp_path)
    return tmp_path


def draws(root: Path) -> list[dict]:
    return diverge.draw_records(root, TASK)


def standing(root: Path) -> dict:
    return diverge.effective(draws(root))


def start(root: Path, k: int = 3, entropy: str = "e1") -> list[dict]:
    return diverge.start(root, TASK, k, entropy=entropy)


def make_all(root: Path) -> None:
    for candidate in diverge.candidate_ids(root, TASK):
        write_rough(root, TASK, candidate)


# ---- 1. the draws

def test_the_draws_are_deterministic_given_the_recorded_seed_and_chained_by_prev(run, tmp_path_factory):
    first = start(run)
    assert [d["id"] for d in first] == [f"d{n}" for n in range(1, len(first) + 1)]
    assert diverge.chain_problem(run, TASK) is None
    other = tmp_path_factory.mktemp("other")
    shutil.copytree(run / ".lapis", other / ".lapis", dirs_exist_ok=True)
    shutil.rmtree(other / ".lapis/state/diverge")
    again = diverge.start(other, TASK, 3, entropy="e1")
    assert [{k: v for k, v in d.items() if k != "prev"} for d in again] == [{k: v for k, v in d.items() if k != "prev"} for d in first]
    third = tmp_path_factory.mktemp("third")
    shutil.copytree(run / ".lapis", third / ".lapis", dirs_exist_ok=True)
    shutil.rmtree(third / ".lapis/state/diverge")
    assert [d["item"] for d in diverge.start(third, TASK, 3, entropy="another")] != [d["item"] for d in first]
    seed = json.loads((run / f".lapis/state/diverge/{TASK}/seed.json").read_text(encoding="utf-8"))
    assert seed["entropy"] == "e1" and seed["task"] == TASK and seed["k"] == 3


def test_a_draw_that_is_edited_or_dropped_breaks_the_chain(run):
    start(run)
    path = run / f".lapis/state/diverge/{TASK}/draws.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0].replace('"C1"', '"C2"'), *lines[1:]]) + "\n", encoding="utf-8")
    assert "hash chain" in diverge.chain_problem(run, TASK)
    assert "hash chain" in " ".join(diverge.check(run, TASK)["problems"])                  # check says so and writes nothing
    path.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    assert "is not draw d1" in diverge.chain_problem(run, TASK)
    path.unlink()
    assert diverge.chain_problem(run, TASK) == "draws.jsonl is missing"


def test_candidates_draw_without_replacement_and_the_pale_default_goes_to_at_most_one(run):
    for n in range(40):
        shutil.rmtree(run / ".lapis/state/diverge", ignore_errors=True)
        got = start(run, entropy=f"seed-{n}")
        held = standing(run)
        assert sorted(held) == ["C1", "C2", "C3"]
        assert len({held[c]["direction"]["item"] for c in held}) == 3                       # a direction each
        assert len({held[c]["O1"]["item"] for c in held}) == 3                              # a family each
        stances = [held[c]["color"]["item"] for c in held]
        assert len(set(stances)) == 3 and stances.count("high-key-one-signal") <= 1
        assert {d["item"] for d in got if d["slot"] == "direction"} <= {"A", "B", "C"}
        assert all(d["candidate"] in held and d["reason"] == "start" for d in got)


def test_the_families_come_from_the_options_the_owner_left_open_first_and_a_narrowed_or_decided_object_follows_the_answer(run):
    conversation(run, DEFAULTS_ACCEPTED + '\n## Direction 3\n\n- [declared] O1 the log: a, c — "not the fader"\n')
    start(run)
    assert {standing(run)[c]["O1"]["item"] for c in ("C1", "C2")} == {"ledger", "annotated-diff"}
    assert standing(run)["C3"]["O1"]["option"] is None and standing(run)["C3"]["O1"]["pool"] == "representation.record-document"
    shutil.rmtree(run / ".lapis/state/diverge")
    conversation(run, DEFAULTS_ACCEPTED + '\n## Direction 3\n\n- [declared] O1 the log: b — "this one"\n')
    start(run)
    assert all("O1" not in standing(run)[c] for c in standing(run))                      # decided: nothing to draw


def test_start_refuses_a_second_time_an_unfinished_conversation_and_a_k_the_directions_cannot_carry(run, tmp_path_factory):
    with pytest.raises(diverge.DivergeError, match="K is 5"):
        start(run, 5)
    with pytest.raises(diverge.DivergeError, match="defines 3 directions"):
        start(run, 4)
    start(run)
    with pytest.raises(diverge.DivergeError, match="already drawn"):
        start(run)
    bare = tmp_path_factory.mktemp("bare")
    record(bare, "answers", BRIEF_RECORD, 50)
    save(bare, f"direction/{TASK}.yaml", PROPOSAL)
    with pytest.raises(diverge.DivergeError, match="direction conversation is not finished"):
        start(bare)


def test_a_candidate_is_resampled_twice_at_most_each_time_with_its_reason_and_never_onto_another_candidates_item(run):
    start(run)
    before = standing(run)["C2"]["O1"]["id"]
    one = diverge.resample(run, TASK, "C2", "O1", "a fader means nothing for a firing log")
    assert one["replaces"] == before and one["slot"] == "O1" and one["candidate"] == "C2"
    held = standing(run)
    assert held["C2"]["O1"]["id"] == one["id"] and len({held[c]["O1"]["item"] for c in held}) == 3
    two = diverge.resample(run, TASK, "C2", "color", "a dark field hides the glaze colors")
    assert two["replaces"] and diverge.chain_problem(run, TASK) is None
    with pytest.raises(diverge.DivergeError, match="resampled 2 times"):
        diverge.resample(run, TASK, "C2", "direction", "the direction does not fit this subject")
    assert diverge.resample(run, TASK, "C3", "color", "the stance does not fit this subject")["candidate"] == "C3"
    with pytest.raises(diverge.DivergeError, match="reason"):
        diverge.resample(run, TASK, "C1", "color", "no")
    with pytest.raises(diverge.DivergeError, match="no candidate C9"):
        diverge.resample(run, TASK, "C9", "color", "a reason of several words")
    with pytest.raises(diverge.DivergeError, match="no draw for O2"):
        diverge.resample(run, TASK, "C1", "O2", "a reason of several words")


def test_an_owner_variant_is_a_new_candidate_with_reason_owner_and_asks_for_the_pick_again(run):
    start(run)
    make_all(run)
    assert not diverge.check(run, TASK)["problems"]
    diverge.seal(run, TASK)
    conversation(run, DEFAULTS_ACCEPTED + '\n## Direction 2\n\n- [declared] Pick: C2 — "this"\n')
    assert direction.pick(run, TASK) is not None
    added = diverge.variant(run, TASK, "bolder, not a card list")
    assert {d["candidate"] for d in added} == {"C4"} and all(d["reason"] == "owner" and d["variant"] for d in added)
    assert added[0]["owner_words"] == "bolder, not a card list" and added[0]["picks_seen"] == 1
    assert diverge.variant_floor(run, TASK) == 1 and direction.pick(run, TASK) is None
    assert "C4" in diverge.owed(run, TASK)                                                # sealed set misses it
    with pytest.raises(diverge.DivergeError, match="cannot be sealed"):
        diverge.seal(run, TASK)
    write_rough(run, TASK, "C4", signature=signature("C4"))
    diverge.seal(run, TASK)
    assert diverge.owed(run, TASK) is None and direction.owed(run, TASK, 2).startswith("Direction conversation, turn two")
    conversation(run, DEFAULTS_ACCEPTED + '\n## Direction 2\n\n- [declared] Pick: C2 — "this"\n- [declared] Pick: C4 — "the bold one"\n')
    assert direction.pick(run, TASK)["candidate"] == "C4" and direction.owed(run, TASK, 2) is not None  # C4's signature G1 is open


# ---- 2. the cards and the renders

def test_a_card_that_disagrees_with_the_draws_is_named(run):
    start(run)
    make_all(run)
    assert diverge.check(run, TASK)["problems"] == []
    held = standing(run)
    other = next(a for a in "ABC" if a != held["C1"]["direction"]["item"])
    cases = [
        ({"direction": other}, "draws on direction"),
        ({"draws": ["d1"]}, "spends the draws"),
        ({"id": "C2"}, "names itself C2"),
        ({"objects": []}, "shows no representation of O1"),
        ({"objects": [{**card_for(run, TASK, "C1")["objects"][0], "family": "radial-hub"}]}, "was drawn as"),
        ({"color": [{"name": "field", "role": "field", "oklch": [0.9, 0.01, 90]}, {"name": "i", "role": "identity",
                                                                                  "oklch": [0.5, 0.2, 30], "area": "the mark only, about 3%"}]}, "diverge/card.schema.yaml"),
        ({"made_in": "someone"}, "diverge/card.schema.yaml"),
    ]
    for changes, fragment in cases:
        write_rough(run, TASK, "C1", **changes)
        problems = " | ".join(diverge.check(run, TASK)["problems"])
        assert fragment in problems, (changes, problems)
    write_rough(run, TASK, "C1")
    assert diverge.check(run, TASK)["problems"] == []


def test_an_object_the_owner_decided_must_show_that_option_and_a_missing_rough_or_render_is_named(run):
    conversation(run, DEFAULTS_ACCEPTED + '\n## Direction 3\n\n- [declared] O1 the log: b — "this one"\n')
    start(run)
    make_all(run)
    assert diverge.check(run, TASK)["problems"] == []
    write_rough(run, TASK, "C2", objects=[{"id": "O1", "option": "a", "family": "ledger", "medium": "css-drawing",
                                          "first_view_share": 0.3, "representation": "the log as ruled rows again"}])
    assert "the owner decided O1 as option b (fader-overlay)" in " | ".join(diverge.check(run, TASK)["problems"])
    write_rough(run, TASK, "C2")
    (run / ".lapis/diverge" / TASK / "C3" / "index.html").unlink()
    (run / ".lapis/renders" / f"{TASK}-C1.narrow.json").unlink()
    problems = " | ".join(diverge.check(run, TASK)["problems"])
    assert "C3/index.html is missing" in problems and "C1 has no render extract" in problems
    assert f"lapis-design render check .lapis/diverge/{TASK}/C1/index.html --task {TASK}-C1 --width 390 --width 1440" in problems


def test_a_render_older_than_its_rough_or_of_another_task_is_refused(run):
    start(run)
    make_all(run)
    rough = run / ".lapis/diverge" / TASK / "C1" / "index.html"
    import os
    later = rough.stat().st_mtime + 100
    os.utime(rough, (later, later))
    assert "older than C1's index.html" in " | ".join(diverge.check(run, TASK)["problems"])
    write_render(run, TASK, "C1", standing(run)["C1"]["color"]["item"], 1)
    assert diverge.check(run, TASK)["problems"] == []
    path = run / ".lapis/renders" / f"{TASK}-C1.narrow.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["source"]["task"] = "someone-else"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert "a capture of another task" in " | ".join(diverge.check(run, TASK)["problems"])


# ---- 3. distance, contact sheet, seal

def test_distances_are_measured_from_the_renders_and_written_with_the_contact_sheet(run):
    start(run)
    make_all(run)
    found = diverge.check(run, TASK)
    assert found["problems"] == [] and len(found["distances"]["pairs"]) == 3
    state = run / f".lapis/state/diverge/{TASK}"
    prints = json.loads((state / "fingerprints.json").read_text(encoding="utf-8"))["candidates"]
    assert sorted(prints) == ["C1", "C2", "C3"] and set(prints["C1"]["grids"]) == {"1440", "390"}
    assert set(prints["C1"]["grids"]["1440"]) == {"text", "media", "control"} and len(prints["C1"]["grids"]["1440"]["text"]) == 8
    assert len(prints["C1"]["grids"]["390"]["text"]) == 10 and len(prints["C1"]["grids"]["390"]["text"][0]) == 4
    report = json.loads((state / "distances.json").read_text(encoding="utf-8"))
    assert report["calibrated"] is False and report["weights"] == {"struct": 0.35, "mass": 0.35, "repr": 0.30}
    for pair in report["pairs"]:
        assert 0 <= pair["total"] <= 1 and pair["repr"] == 1.0 and not pair["refused"]   # three families, none shared
    assert report["minimum_pair"] == min(p["total"] for p in report["pairs"])
    from PIL import Image

    with Image.open(state / "contact.png") as sheet:
        assert sheet.width >= 1600 and sheet.height >= 400
    assert all(0 <= prints[c]["mass"][k] <= 1 for c in prints for k in ("vivid_share", "dark_share", "media_share", "line_share"))
    for c, stance in ((c, standing(run)[c]["color"]["item"]) for c in prints):          # the mass follows what was painted
        assert (prints[c]["mass"]["field_lightness"] < 0.35) == (stance == "dark-field")
        assert (prints[c]["mass"]["dark_share"] > 0.5) == (stance == "dark-field")


def test_two_roughs_with_the_same_structure_and_the_same_color_mass_differ_in_finish_only_and_are_refused(run):
    start(run)
    make_all(run)
    for candidate in ("C1", "C2"):                                 # one markup, one stance: only the card's names differ
        folder = run / ".lapis/diverge" / TASK / candidate
        (folder / "index.html").write_text(rough_html(1), encoding="utf-8")
        write_render(run, TASK, candidate, "content-carries-color", 1)
    problems = " | ".join(diverge.check(run, TASK)["problems"])
    assert "C1 and C2 keep the same structure" in problems and "order or finish only" in problems
    assert not (run / f".lapis/state/diverge/{TASK}/distances.json").exists()
    write_render(run, TASK, "C2", "dark-field", 1)                  # the same markup, a different mass: allowed, and reported
    found = diverge.check(run, TASK)
    assert found["problems"] == [] and next(p for p in found["distances"]["pairs"] if (p["a"], p["b"]) == ("C1", "C2"))["mass"] > 0.10


def test_the_seal_records_the_digests_and_an_edit_after_it_is_reported(run):
    start(run)
    make_all(run)
    record = diverge.seal(run, TASK)
    assert sorted(record["candidates"]) == ["C1", "C2", "C3"] and record["d1_turns"] == 1
    row = record["candidates"]["C1"]
    assert {"card", "rough", "captures", "direction"} <= set(row) and set(row["captures"]) == {"1440", "390"}
    assert len(row["card"]["sha256"]) == 64 and len(record["draws_sha256"]) == 64 and record["contact"]["path"].endswith("contact.png")
    assert diverge.drift(run, TASK) == [] and diverge.owed(run, TASK) is None
    assert diverge.owner_lines(run, TASK)[0].startswith("- Rough first views sealed: C1, C2, C3")
    (run / ".lapis/diverge" / TASK / "C2" / "index.html").write_text(rough_html(7), encoding="utf-8")
    assert diverge.drift(run, TASK) == ["C2: rough changed after the seal"]
    assert any("Rough C2: rough changed after the seal" in line for line in diverge.owner_lines(run, TASK))
    assert diverge.owed(run, TASK) is None                                              # reported, not blocking
    diverge.resample(run, TASK, "C3", "color", "the stance does not fit this subject")
    assert "the draws changed" in " ".join(diverge.drift(run, TASK)) and "not sealed" in diverge.owed(run, TASK)


def test_the_seal_is_refused_while_check_has_a_problem_and_a_first_seal_keeps_its_turn_count_on_a_reseal(run):
    start(run)
    make_all(run)
    (run / ".lapis/diverge" / TASK / "C1" / "card.yaml").unlink()
    with pytest.raises(diverge.DivergeError, match="cannot be sealed: .*card.yaml is missing"):
        diverge.seal(run, TASK)
    write_rough(run, TASK, "C1")
    assert diverge.seal(run, TASK)["d1_turns"] == 1
    conversation(run, DEFAULTS_ACCEPTED + '\n## Direction 2\n\n- [declared] Pick: C1 — "x"\n')
    assert diverge.seal(run, TASK)["d1_turns"] == 1


# ---- 4. the step

def test_next_names_references_then_owner_direction_then_diverge_then_owner_direction_then_the_plan(tmp_path):
    record(tmp_path, "answers", BRIEF_RECORD, 50)
    seal_requirements(tmp_path)
    load_skills(tmp_path)

    def step() -> str:
        return next_step.evaluate(tmp_path, TASK)["step"]["id"]

    assert step() == "references"
    write_references(tmp_path)                                     # the fixture finishes the whole conversation
    assert step() == "plan"
    shutil.rmtree(tmp_path / ".lapis/state/diverge")
    shutil.rmtree(tmp_path / ".lapis/diverge")
    record(tmp_path, "answers", BRIEF_RECORD, 50)                  # as it was after the references
    assert step() == "owner-direction"
    conversation(tmp_path)
    result = next_step.evaluate(tmp_path, TASK)
    assert result["step"]["id"] == "diverge" and result["step"]["command"] == f"lapis-design diverge start --task {TASK}"
    assert f"lapis-design diverge start --task {TASK}" in result["step"]["why"] and "contact sheet" not in result["step"]["why"]
    start(tmp_path)
    make_all(tmp_path)
    write_rough(tmp_path, TASK, "C2", signature=signature("C2"))
    result = next_step.evaluate(tmp_path, TASK)
    assert result["step"]["id"] == "diverge" and result["step"]["command"] == f"lapis-design diverge check --task {TASK}"
    assert "not sealed" in result["step"]["why"]
    diverge.seal(tmp_path, TASK)
    result = next_step.evaluate(tmp_path, TASK)
    assert result["step"]["id"] == "owner-direction" and "turn two" in result["step"]["why"]
    conversation(tmp_path, DEFAULTS_ACCEPTED + '\n## Direction 2\n\n- [declared] Pick: C2 — "this one"\n'
                 '- [declared] C2.G1 mark of C2: a — "yes"\n')
    assert step() == "plan"


def test_the_pre_write_hook_refuses_page_code_while_diverge_is_owed_in_an_unattended_run(run, monkeypatch):
    from lapis_design import order

    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    assert "diverge" in order.BEFORE_CODE and "owner-direction" in order.BEFORE_CODE
    event = {"cwd": str(run), "tool_name": "Write", "tool_input": {"file_path": str(run / "index.html")}}
    refusal = order.decide(event, {"LAPIS_UNATTENDED": "1", "LAPIS_TASK": TASK})
    assert refusal and "rough first views of `lapis-design diverge`" in refusal["hookSpecificOutput"]["permissionDecisionReason"]
    assert order.decide({**event, "tool_input": {"file_path": str(run / ".lapis/diverge" / TASK / "C1" / "index.html")}},
                        {"LAPIS_UNATTENDED": "1", "LAPIS_TASK": TASK}) is None          # roughs under .lapis are never refused


# ---- 5. the command line

def test_the_commands_start_resample_check_seal_and_show_run_as_verbs_of_lapis_design(run, capsys):
    base = ["--task", TASK, "--root", str(run)]
    assert cli_main(["diverge", "show", *base]) == 0 and "No rough was drawn" in capsys.readouterr().out
    assert cli_main(["diverge", "start", *base, "--k", "2"]) == 0
    assert "2 roughs" in capsys.readouterr().out
    assert cli_main(["diverge", "start", *base]) == 2 and "already drawn" in capsys.readouterr().err
    assert cli_main(["diverge", "resample", *base, "--candidate", "C1", "--slot", "color", "--reason",
                     "this stance does not fit"]) == 0 and "C1 color is now" in capsys.readouterr().out
    assert cli_main(["diverge", "check", *base]) == 1 and "card.yaml is missing" in capsys.readouterr().err
    make_all(run)
    assert cli_main(["diverge", "check", *base]) == 0
    capsys.readouterr()
    assert cli_main(["diverge", "seal", *base]) == 0 and "sealed C1, C2" in capsys.readouterr().out
    assert cli_main(["diverge", "show", *base]) == 0 and "sealed" in capsys.readouterr().out
    assert cli_main(["diverge", "variant", *base, "--words", "a bolder first view"]) == 0
    assert "C3 added for the owner" in capsys.readouterr().out


# ---- 6. real renders (browser)

@pytest.mark.browser
def test_check_measures_two_real_renders_and_writes_the_contact_sheet(run):
    from PIL import Image

    from narrow_support import run as run_cli

    start(run, 2)
    pages = {"C1": "<!doctype html><html lang='en'><body style='margin:0;background:#2846c8'><main style='padding:60px'>"
                   "<h1 style='color:#fff;font:700 64px sans-serif'>Firing log</h1><p style='color:#fff'>Ruled rows.</p>"
                   "</main></body></html>",
             "C2": "<!doctype html><html lang='en'><body style='margin:0;background:#12141c'><main style='display:grid;"
                   "grid-template-columns:1fr 1fr;gap:40px;padding:60px'><h1 style='color:#eee;font:700 48px sans-serif'>"
                   "Last month</h1><button style='height:48px'>Compare</button></main></body></html>"}
    for candidate, html in pages.items():
        write_rough(run, TASK, candidate)
        (run / ".lapis/diverge" / TASK / candidate / "index.html").write_text(html, encoding="utf-8")
        done = run_cli(run, "render", f".lapis/diverge/{TASK}/{candidate}/index.html", "--task", f"{TASK}-{candidate}",
                       "--width", "390", "--width", "1440")
        assert done.returncode == 0, done.stderr
    found = diverge.check(run, TASK)
    assert found["problems"] == [] and len(found["distances"]["pairs"]) == 1
    state = run / f".lapis/state/diverge/{TASK}"
    prints = json.loads((state / "fingerprints.json").read_text(encoding="utf-8"))["candidates"]
    assert prints["C1"]["mass"]["field_lightness"] > 0.3 > prints["C2"]["mass"]["field_lightness"]
    assert prints["C2"]["mass"]["dark_share"] > 0.8 and prints["C1"]["structure"] != prints["C2"]["structure"]
    with Image.open(state / "contact.png") as sheet:
        assert sheet.width > 1000 and sheet.height > 400
    assert sorted(diverge.seal(run, TASK)["candidates"]["C2"]["captures"]) == ["1440", "390"]
