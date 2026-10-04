"""The references step: what `lapis-design next` asks for between the brief and the plan, and what counts as the
references record. The record is the evidence that a run looked at its references, so the cases here are the ways
a run can look as if it had without having: text pages, encyclopedias, files that are no images, one capture
reused, facts that state no value."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from lapis_design import attempts, gate, hints, next_step, order, references
from lapis_design.cli import main as cli_main
from procedure_support import (BRIEF_RECORD, FACTS, TASK, finish, make_project, record, reference_entries,
                               references_text, save, update, write_references)


@pytest.fixture
def bare(tmp_path, monkeypatch) -> Path:
    """A project folder with a brief record and nothing else: the run is at the references."""
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    record(tmp_path, "answers", BRIEF_RECORD, 50)
    return tmp_path


def evaluated(root: Path) -> dict:
    return next_step.evaluate(root, TASK)


def step_of(root: Path) -> str:
    result = evaluated(root)
    return result["step"]["id"] if result["step"] else "done"


def write(root: Path, entries: list[dict], **kwargs) -> None:
    hints.draw(root, TASK, "none", "2026-10-05")
    record(root, "references", references_text(entries, **kwargs), 100)


def problems(root: Path) -> str:
    return " | ".join(references.problems(root, TASK))


def test_a_run_with_a_brief_and_no_references_is_sent_to_the_references_before_the_plan(bare):
    result = evaluated(bare)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "references")
    assert result["step"]["command"] is None
    assert f".lapis/references/{TASK}.md" in result["step"]["why"] and "lazuli ref capture" in result["step"]["why"]


def test_a_brief_with_a_no_network_line_still_gets_the_references_step_and_its_text_says_how_to_decline_it(bare):
    """A museum brief said 'no network requests, no external assets' and the run refused to research on that ground:
    the step is still asked for, since only the user's own line can decline it, and the step says how."""
    record(bare, "answers", BRIEF_RECORD + "- [declared] Q3 Network? The page makes no network requests and uses "
           "no external assets.\n", 60)
    result = evaluated(bare)
    assert result["step"]["id"] == "references" and "--declined references --brief-line" in result["step"]["why"]
    write_references(bare, 70)
    assert step_of(bare) == "plan"


def test_a_references_record_that_passes_hands_the_run_on_to_the_plan(bare):
    write_references(bare)
    assert references.problems(bare, TASK) == []
    assert step_of(bare) == "plan"


def test_a_create_plan_without_a_record_goes_back_to_the_references_and_the_other_modes_do_not(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    assert step_of(root) == "release"
    (root / f".lapis/references/{TASK}.md").unlink()
    assert step_of(root) == "references"
    for mode in ("redesign", "repair"):
        update(root, f"plans/{TASK}.yaml", lambda plan, mode=mode: plan.update(mode=mode))
        assert step_of(root) != "references", mode


def test_the_brief_still_comes_first(bare):
    (bare / f".lapis/answers/{TASK}.md").unlink()
    assert step_of(bare) == "brief"


def test_a_plan_that_cannot_be_read_is_fixed_before_anything_asks_for_references(bare):
    save(bare, f"plans/{TASK}.yaml", {"mode": "create"})
    (bare / f".lapis/plans/{TASK}.yaml").write_text("brief: [oops\n", encoding="utf-8")
    assert step_of(bare) == "plan-fix"


def test_the_json_and_the_text_of_the_command_name_the_references(bare, capsys):
    assert cli_main(["next", "--task", TASK, "--root", str(bare), "--json"]) == 0
    assert '"id": "references"' in capsys.readouterr().out
    assert cli_main(["next", "--task", TASK, "--root", str(bare)]) == 0
    assert capsys.readouterr().out.startswith(f"next: references ({TASK})")


def test_the_task_of_a_run_that_only_recorded_its_references_is_found_by_the_record(tmp_path):
    assert next_step.resolve_task(tmp_path) is None
    write_references(tmp_path, 110, task="kiln-remake")
    assert next_step.resolve_task(tmp_path) == "kiln-remake"


# ------------------------------------------------------------------ what is not a record

def swap(entries: list[dict], index: int, **change) -> list[dict]:
    """`entries` with entry `index` changed; a value of None removes the field."""
    out = [dict(entry) for entry in entries]
    out[index] = {key: value for key, value in {**out[index], **change}.items() if value is not None}
    return out


def text_capture(root: Path, entries: list[dict], index: int, name: str = "page.md") -> list[dict]:
    """Entry `index` captured as text only: a page saved as Markdown, which is what `lazuli read` gives."""
    path = root / ".lapis" / "references" / TASK / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{name}: a page saved as text. " * 40, encoding="utf-8")
    return swap(entries, index, capture=path.relative_to(root).as_posix())


def wikipedia(entries: list[dict], index: int) -> list[dict]:
    """Entry `index` is an encyclopedia page whose capture is an image of it."""
    return swap(entries, index, url=f"https://en.wikipedia.org/wiki/Topic_{index}")



CASES = [
    ("five references", lambda root, e: e[:5], "at least 6"),
    ("no yaml block", lambda root, e: None, "yaml block"),
    ("two kinds", lambda root, e: swap(swap(swap(e, 3, kind="print"), 4, kind="print"), 5, kind="print"), "2 kinds"),
    ("web design only", lambda root, e: [swap(e, i, kind="web-ui", source_facts=FACTS)[i] for i in range(6)],
     "0 references outside web-ui"),
    ("a kind that is not one of ours", lambda root, e: swap(e, 2, kind="inspiration"), "`kind` is 'inspiration'"),
    ("no capture field", lambda root, e: swap(e, 2, capture=None), "has no `capture`"),
    ("a capture that does not exist", lambda root, e: swap(e, 2, capture=".lapis/references/%s/gone.png" % TASK),
     "does not exist"),
    ("a capture outside the task's folder", lambda root, e: swap(e, 2, capture="index.html"), "is not under"),
    ("a capture that climbs out of the folder", lambda root, e: swap(e, 2, capture=f".lapis/references/{TASK}/../x.png"),
     "is not under"),
    ("a file named .png that is no image", lambda root, e: swap(e, 2, capture=_fake_png(root)), "is not an image"),
    ("one capture used twice", lambda root, e: swap(e, 3, capture=e[2]["capture"]), "same capture"),
    ("three text pages", lambda root, e: text_capture(root, text_capture(root, text_capture(root, e, 2, "a.md"), 3,
                                                                        "b.md"), 4, "c.md"),
     "3 references are text-only"),
    ("three encyclopedia pages with screenshots", lambda root, e: wikipedia(wikipedia(wikipedia(e, 2), 3), 4),
     "3 references are text-only"),
    ("a web reference without source facts", lambda root, e: swap(e, 0, source_facts=None), "without `source_facts`"),
    ("source facts that state no value", lambda root, e: swap(e, 0, source_facts="a calm layout with a nice serif face"),
     "without `source_facts`"),
    ("a reference without a maker", lambda root, e: swap(e, 2, maker=None), "no `maker`"),
    ("a one-word relation", lambda root, e: swap(e, 2, relation="rhythm"), "`relation` is empty"),
    ("neither url nor source", lambda root, e: swap(e, 2, url=None), "neither `url` nor `source`"),
    ("a url that is no web address", lambda root, e: swap(e, 2, url="museum object 12"), "not an http(s) address"),
    ("the same page twice", lambda root, e: swap(e, 3, url=e[2]["url"] + "/"), "same page"),
    ("an id used twice", lambda root, e: swap(e, 3, id=e[2]["id"]), "used twice"),
]


def _fake_png(root: Path) -> str:
    path = root / ".lapis" / "references" / TASK / "fake.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not a picture " * 200, encoding="utf-8")
    return path.relative_to(root).as_posix()


@pytest.mark.parametrize("case, change, part", CASES, ids=[case for case, _, _ in CASES])
def test_a_record_that_only_looks_complete_leaves_the_run_at_the_references_and_says_what_is_missing(
        bare, case, change, part):
    entries = change(bare, reference_entries(bare))
    if entries is None:
        record(bare, "references", "# References\n\nWe looked at six sites.\n", 100)
    else:
        write(bare, entries)
    assert step_of(bare) == "references", case
    assert part in problems(bare), case


def test_a_record_that_does_not_say_its_captures_are_for_study_is_not_one(bare):
    write(bare, reference_entries(bare), captures=None)
    assert step_of(bare) == "references" and "study-only" in problems(bare)


def test_a_yaml_block_that_cannot_be_read_is_reported_and_not_raised(bare):
    record(bare, "references", "```yaml\nreferences: [oops\n```\n", 100)
    assert step_of(bare) == "references" and "cannot be read" in problems(bare)


def test_a_text_page_costs_a_reference_but_never_counts_toward_the_kinds(bare):
    """The failure the step exists for: screenshots of web pages, plus text pages filed under other kinds."""
    entries = reference_entries(bare)
    for index in (2, 3):
        entries = swap(entries, index, kind="web-ui", source_facts=FACTS)
    entries = text_capture(bare, text_capture(bare, entries, 4, "a.md"), 5, "b.md")     # print and archive, read not seen
    write(bare, entries)
    assert step_of(bare) == "references"
    assert "1 kinds and 0 references outside web-ui" in problems(bare)


def test_two_text_pages_among_enough_images_are_allowed(bare):
    entries = text_capture(bare, text_capture(bare, reference_entries(bare), 3, "a.md"), 4, "b.md")
    write(bare, entries)
    assert references.problems(bare, TASK) == [] and step_of(bare) == "plan"


def test_an_encyclopedia_counts_as_text_even_when_it_is_photographed_but_commons_files_do_not(bare):
    entries = wikipedia(wikipedia(reference_entries(bare), 3), 4)
    write(bare, entries)
    assert references.problems(bare, TASK) == []                       # two encyclopedia pages: allowed
    entries = swap(entries, 2, url="https://commons.wikimedia.org/wiki/File:Poster.jpg")
    write(bare, entries)
    assert references.problems(bare, TASK) == []                       # a Commons file page is not an encyclopedia


def test_a_reference_may_name_a_source_instead_of_an_address(bare):
    write(bare, swap(reference_entries(bare), 3, url=None, source="the user's photograph of the kiln door"))
    assert references.problems(bare, TASK) == []


def test_source_facts_may_be_written_as_a_list(bare):
    write(bare, swap(reference_entries(bare), 0, source_facts=["body 17px/1.55", "ink #1a1a1a on paper #f4f0e8"]))
    assert references.problems(bare, TASK) == []


def test_every_problem_is_named_at_once_and_the_step_shows_the_first_three(bare):
    entries = swap(swap(swap(reference_entries(bare)[:4], 0, source_facts=None), 1, capture=None), 2, kind="inspiration")
    write(bare, entries)
    found = references.problems(bare, TASK)
    assert len(found) > 3
    why = evaluated(bare)["step"]["why"]
    assert f"and {len(found) - 3} more)" in why and found[2] in why and found[3] not in why


def test_a_capture_that_is_a_symlink_out_of_the_folder_is_not_inside_it(bare, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "elsewhere.png"
    outside.write_bytes((bare / reference_entries(bare)[0]["capture"]).read_bytes())
    entries = reference_entries(bare)
    link = bare / ".lapis/references" / TASK / "linked.png"
    link.symlink_to(outside)
    write(bare, swap(entries, 2, capture=link.relative_to(bare).as_posix()))
    assert "is not under" in problems(bare)


# ------------------------------------------------------------------ no network
@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No test here touches the network: the probe behind `--unavailable references` finds none unless a test says so."""
    monkeypatch.setattr(references, "unreachable", lambda: "Network is unreachable")


def unavailable(root: Path, reason: str = "WebFetch is denied in this harness and curl cannot resolve hosts") -> int:
    return cli_main(["next", "--task", TASK, "--root", str(root), "--unavailable", "references", "--reason", reason])


def test_a_run_with_no_network_records_that_and_goes_on_but_it_is_reported_as_not_looked(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    (root / f".lapis/references/{TASK}.md").unlink()
    assert step_of(root) == "references"
    assert unavailable(root) == 0
    assert attempts.read(root, TASK, "references")["reason"].startswith("WebFetch is denied")
    assert step_of(root) != "references"
    assert finish(root, "--static") == 0
    result = evaluated(root)
    assert result["state"] == "done" and "No references were looked at: WebFetch is denied" in result["reason"]


def test_an_environment_record_does_not_stand_in_once_the_run_writes_a_record_of_its_own(bare):
    assert unavailable(bare) == 0
    assert step_of(bare) == "plan"
    write(bare, reference_entries(bare)[:3])                           # tried after all, and left unfinished
    os.utime(bare / f".lapis/references/{TASK}.md", None)
    assert step_of(bare) == "references"
    write_references(bare, int(os.stat(bare / f".lapis/references/{TASK}.md").st_mtime) + 5)
    result = evaluated(bare)
    assert result["step"]["id"] == "plan" and "No references" not in result["reason"]


def test_a_finished_run_that_looked_does_not_report_that_it_did_not(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    assert unavailable(root) == 0                                      # a stale claim beside a record that passes
    assert finish(root, "--static") == 0
    result = evaluated(root)
    assert result["state"] == "done" and "No references were looked at" not in result["reason"]


def test_the_environment_record_needs_a_reason(bare, capsys):
    with pytest.raises(SystemExit):
        cli_main(["next", "--task", TASK, "--root", str(bare), "--unavailable", "references"])
    assert "--unavailable and --reason go together" in capsys.readouterr().err
    assert attempts.read(bare, TASK, "references") is None


def test_the_record_is_refused_while_the_network_works_whatever_the_reason_says(bare, monkeypatch, capsys):
    """The run that recorded 'I chose not to: the brief says no network' instead of looking."""
    monkeypatch.setattr(references, "unreachable", lambda: None)
    reason = "The brief says no network requests or external assets, so I did not run the step"
    assert unavailable(bare, reason) == 2
    err = capsys.readouterr().err
    assert "the network is reachable from here" in err and "--declined references --brief-line" in err
    assert attempts.read(bare, TASK, "references") is None and step_of(bare) == "references"


def test_the_probe_failure_is_kept_in_the_record(bare):
    assert unavailable(bare) == 0
    assert "probe of https://example.org/: Network is unreachable" in attempts.read(bare, TASK, "references")["reason"]


# ------------------------------------------------------------------ declined with the user's own line
LINE = "Use no network requests, external services, downloads, or external assets"
QUOTED = f"- The request says: {LINE}.\n"


def with_line(root: Path, text: str = QUOTED, at: int = 50) -> None:
    """The brief record with `text` among its findings."""
    record(root, "answers", BRIEF_RECORD.replace("\n## Answers", text + "\n## Answers"), at)


def decline(root: Path, line: str = LINE) -> int:
    return cli_main(["next", "--task", TASK, "--root", str(root), "--declined", "references", "--brief-line", line])


def declined_file(root: Path) -> Path:
    return root / ".lapis" / "attempts" / TASK / "references.json"


@pytest.fixture
def forbidden(bare) -> Path:
    """A run at the references whose brief record holds the request's no-network line as the user wrote it."""
    with_line(bare)
    return bare


def test_a_line_of_the_brief_declines_the_references_and_the_run_goes_on_to_the_plan(forbidden, monkeypatch):
    monkeypatch.setattr(references, "unreachable", lambda: None)        # the network works: this is not the other record
    assert step_of(forbidden) == "references"
    assert decline(forbidden, f"\u201c{LINE}.\u201d") == 0                 # quotation marks and the full stop are not the line
    saved = json.loads(declined_file(forbidden).read_text(encoding="utf-8"))
    assert (saved["kind"], saved["step"], saved["task"], saved["brief_line"]) == (
        "declined-by-brief", "references", TASK, LINE)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", saved["at"])
    result = evaluated(forbidden)
    assert result["step"]["id"] == "plan"
    assert LINE in result["step"]["why"] and "local material" in result["step"]["why"]
    assert attempts.read(forbidden, TASK, "references") is None          # a decline is no failure of the environment


@pytest.mark.parametrize("line, part", [
    ("Use no network requests, external services, downloads or external assets", "is not in the brief record"),
    ("The page fires once a week", "is not in the brief record"),
    ("offline", "too short"),
], ids=["the-user's-words-where-the-record-paraphrased-them", "a-line-nobody-wrote", "one-word"])
def test_a_line_the_brief_does_not_hold_cannot_decline_the_step(bare, capsys, line, part):
    with_line(bare, "- The request says: no network requests, external services, downloads or external assets.\n")
    assert decline(bare, line) == 2
    assert part in capsys.readouterr().err
    assert not declined_file(bare).exists() and step_of(bare) == "references"


def test_white_space_and_wrapping_do_not_make_a_line_another_line(bare):
    with_line(bare, "- The request says: use no network\n  requests,   external services.\n")
    assert decline(bare, "use no network requests, external services") == 0
    assert step_of(bare) == "plan"


def test_a_line_of_the_plans_brief_constraints_is_the_request_too(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    (root / f".lapis/references/{TASK}.md").unlink()
    assert step_of(root) == "references"
    assert decline(root, "Photos show pieces straight out of the kiln") == 0       # brief.constraints of the example plan
    assert step_of(root) != "references"


def test_the_option_needs_its_line_and_is_not_the_other_record(bare, capsys):
    with pytest.raises(SystemExit):
        cli_main(["next", "--task", TASK, "--root", str(bare), "--declined", "references"])
    assert "--declined and --brief-line go together" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli_main(["next", "--task", TASK, "--root", str(bare), "--declined", "references", "--brief-line", LINE,
                  "--unavailable", "references", "--reason", "no network"])
    assert "give one" in capsys.readouterr().err
    assert not declined_file(bare).exists()


def test_a_references_record_written_after_the_decline_takes_over(forbidden):
    assert decline(forbidden) == 0 and step_of(forbidden) == "plan"
    stamp = declined_file(forbidden).stat().st_mtime + 5
    write(forbidden, reference_entries(forbidden)[:3])                  # tried after all, and left unfinished
    os.utime(forbidden / f".lapis/references/{TASK}.md", (stamp, stamp))
    assert step_of(forbidden) == "references"


def test_a_decline_stops_standing_once_its_line_is_gone_from_the_brief(forbidden):
    assert decline(forbidden) == 0 and step_of(forbidden) == "plan"
    record(forbidden, "answers", BRIEF_RECORD, 50)
    assert step_of(forbidden) == "references"


def test_a_decline_written_by_hand_with_a_line_the_brief_lacks_counts_for_nothing(bare):
    declined_file(bare).parent.mkdir(parents=True)
    declined_file(bare).write_text(json.dumps({
        "version": 0, "task": TASK, "step": "references", "kind": "declined-by-brief",
        "brief_line": "Never look anything up", "command": ["by", "hand"], "at": "2026-10-04T00:00:00Z"}), encoding="utf-8")
    assert step_of(bare) == "references"


def test_a_declined_run_is_not_a_run_that_looked_and_both_the_release_and_the_end_say_so(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    (root / f".lapis/references/{TASK}.md").unlink()
    with_line(root)
    assert decline(root) == 0
    assert finish(root, "--static") == 0                                 # nothing blocks on it
    report = json.loads((root / f".lapis/release/{TASK}.json").read_text(encoding="utf-8"))
    [found] = [f for f in report["findings"] if f["rule_id"] == "release.references-declined"]
    assert found["blocking"] is False and found["class"] == "quality" and found["layer"] == "plan"
    assert found["severity"] == {"create": "warn", "review": "P2"} and report["summary"]["blocking"] == 0
    assert LINE in found["observed"] and "local material" in found["observed"]
    result = evaluated(root)
    assert result["state"] == "done" and "No references were looked at" in result["reason"] and LINE in result["reason"]


def test_a_decline_beside_a_references_record_that_passes_is_not_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    (root / f".lapis/references/{TASK}.md").unlink()
    with_line(root)
    assert decline(root) == 0
    write_references(root, 50)                                           # the run looked after all
    assert finish(root, "--static") == 0
    report = json.loads((root / f".lapis/release/{TASK}.json").read_text(encoding="utf-8"))
    assert not [f for f in report["findings"] if f["rule_id"] == "release.references-declined"]
    assert "No references were looked at" not in evaluated(root)["reason"]


def page_write(root: Path) -> tuple[dict, dict]:
    """A page-file write event of an unattended run in `root`, with the environment the hooks read."""
    event = {"cwd": str(root), "tool_input": {"file_path": str(root / "index.html"), "content": "<h1>x</h1>"}}
    return event, {"LAPIS_UNATTENDED": "1", "CLAUDE_PROJECT_DIR": str(root)}


def test_the_exit_gate_and_the_pre_write_hook_stop_sending_a_declined_run_back_to_the_references(forbidden):
    event, env = page_write(forbidden)
    held = order.decide(event, env)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "references record" in held and "declined" in held
    assert "Next step: references." in gate.stop_output(forbidden, "s1")["reason"]
    assert decline(forbidden) == 0
    still = order.decide(event, env)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "references record" not in still and "the plan" in still
    assert "Next step: plan." in gate.stop_output(forbidden, "s1")["reason"]


def test_a_declined_run_that_has_done_everything_else_is_let_stop_and_write(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    root = make_project(tmp_path)
    (root / f".lapis/references/{TASK}.md").unlink()
    with_line(root)
    event, env = page_write(root)
    assert order.decide(event, env) is not None and "Next step: references." in gate.stop_output(root, "s1")["reason"]
    assert decline(root) == 0 and finish(root, "--static") == 0
    assert order.decide(event, env) is None and gate.stop_output(root, "s1") is None
