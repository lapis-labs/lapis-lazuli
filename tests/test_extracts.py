"""`lapis-design extract`: grounded excerpts recorded once with the source's hash, stale when the source changes, refused without a
locator, and never carrying a maker's opinion to the critic."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from lapis_design import critic_packet, extracts, shared_dir
from lapis_design.cli import main as cli_main
from procedure_support import TASK, make_project, update, write_requirements

BRIEF = ("# Kiln shop\n\n## Audience\nVisitors bought a ceramic piece last year.\nThey open the page on a phone, on Sundays.\n\n"
         "## Pickup\nPickup is on Saturdays.\nThe studio is closed in August.\n")
LICENSE = "Licensed under the SIL Open Font License 1.1.\nYou may not sell the font on its own.\n"
OPINION = "The brief is vague and the owner clearly prefers quiet layouts."
INPUTS = {"extracts": [f".lapis/renders/{TASK}.json"], "lint": f".lapis/lint/{TASK}.json", "session": None}
SHA = hashlib.sha256


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    shot = root / "shot.png"
    Image.new("RGB", (4, 4), "white").save(shot)
    update(root, f"renders/{TASK}.json", lambda d: d["viewports"][1].update(screenshot="../../shot.png"))
    write_requirements(root, ("Show which pieces are in this firing",))
    (root / "BRIEF.md").write_text(BRIEF, encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs/LICENSE.txt").write_text(LICENSE, encoding="utf-8")
    return root


def run(project: Path, verb: str, *args: str) -> int:
    try:
        return cli_main(["extract", verb, "--task", TASK, "--root", str(project), *args])
    except SystemExit as exc:                                         # argparse refusals
        return exc.code


def record(project: Path) -> dict:
    return json.loads((project / f".lapis/extracts/{TASK}.json").read_text(encoding="utf-8"))


def write_record(project: Path, document: dict) -> None:
    file = project / f".lapis/extracts/{TASK}.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(document), encoding="utf-8")


def packet(project: Path) -> bytes:
    return critic_packet.build(project, TASK, INPUTS)


def test_an_extract_is_recorded_with_the_hash_of_its_source_and_the_sources_own_lines(project, capsys):
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "4-5") == 0
    [item] = record(project)["extracts"]
    assert item["source"] == {"path": "BRIEF.md", "sha256": SHA(BRIEF.encode()).hexdigest()}
    assert item["locator"] == {"start": 4, "end": 5}
    assert item["text"] == "Visitors bought a ceramic piece last year.\nThey open the page on a phone, on Sundays."
    assert item["id"] == extracts.extract_id("BRIEF.md", 4, 5)
    out = capsys.readouterr().out
    assert item["id"] in out and "BRIEF.md:4-5" in out and SHA(BRIEF.encode()).hexdigest() in out
    assert run(project, "show") == 0
    shown = capsys.readouterr().out
    assert "BRIEF.md:4-5" in shown and "    Visitors bought a ceramic piece last year." in shown
    assert f"sha256 {item['source']['sha256'][:12]}" in shown
    assert "instead of" in shown                                       # the characters read, and the whole sources' size


def test_a_heading_is_resolved_to_the_lines_of_its_section_and_kept_as_the_locator(project):
    assert run(project, "add", "--source", "BRIEF.md", "--heading", "Pickup") == 0
    [item] = record(project)["extracts"]
    assert item["locator"] == {"start": 7, "end": 9, "heading": "Pickup"}
    assert item["text"] == "## Pickup\nPickup is on Saturdays.\nThe studio is closed in August."
    assert run(project, "add", "--source", "BRIEF.md", "--heading", "Missing") == 2


def test_recording_the_same_lines_again_replaces_the_extract(project, capsys):
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "8") == 0
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "8") == 0
    assert len(record(project)["extracts"]) == 1
    assert "replaced the extract of the same lines" in capsys.readouterr().out


def test_a_changed_source_makes_the_extract_stale_and_the_cli_says_so(project, capsys):
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "8") == 0
    assert run(project, "add", "--source", "docs/LICENSE.txt", "--lines", "1") == 0
    capsys.readouterr()
    (project / "BRIEF.md").write_text(BRIEF.replace("Saturdays", "Fridays"), encoding="utf-8")
    assert run(project, "show") == 1
    out = capsys.readouterr().out
    assert "STALE: the source changed since the extract was recorded" in out
    assert "Pickup is on Saturdays" not in out                           # no text is shown for a stale extract
    assert "Licensed under the SIL Open Font License 1.1." in out        # the other source still holds
    assert "open the source at BRIEF.md:8-8" in out
    assert run(project, "check") == 1
    check = capsys.readouterr().out
    assert "1 of 2 extracts hold" in check and "STALE" in check and "Pickup is on" not in check
    assert run(project, "show", "--source", "docs/LICENSE.txt") == 0     # asking only for what holds is fine
    capsys.readouterr()
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "9") == 0       # recording the same source again names the stale one
    assert "STALE" in capsys.readouterr().out
    assert run(project, "drop", "--stale") == 0
    assert [e["locator"]["start"] for e in record(project)["extracts"] if e["source"]["path"] == "BRIEF.md"] == [9]
    assert run(project, "check") == 0


def test_a_source_that_is_gone_is_reported_not_skipped(project, capsys):
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "8") == 0
    (project / "BRIEF.md").unlink()
    assert run(project, "check") == 1
    assert "MISSING" in capsys.readouterr().out


def test_an_extract_without_a_locator_is_refused(project, capsys):
    assert run(project, "add", "--source", "BRIEF.md") == 2
    assert "locator" in capsys.readouterr().err
    assert not (project / f".lapis/extracts/{TASK}.json").exists()
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "2", "--heading", "Pickup") == 2    # one locator, not two
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "40-41") == 2                       # beyond the file
    # a record that was written by hand without one is not read either
    write_record(project, {"version": 0, "task": TASK, "extracts": [
        {"id": "Xa1b2c3d4", "source": {"path": "BRIEF.md", "sha256": SHA(BRIEF.encode()).hexdigest()}, "text": "Pickup"}]})
    capsys.readouterr()
    assert run(project, "show") == 2
    assert "locator" in capsys.readouterr().err
    document = json.loads((shared_dir() / "extracts/example.extracts.json").read_text(encoding="utf-8"))
    assert extracts._problem(document) is None
    del document["extracts"][0]["locator"]
    assert "locator" in extracts._problem(document)


def test_a_url_source_carries_its_capture_date_and_rights_and_a_reference_only_one_is_refused(project, capsys):
    page = project / "docs/atelier.txt"
    page.write_text("Atelier\nEvery piece is signed and numbered.\n", encoding="utf-8")
    assert run(project, "add", "--source", "docs/atelier.txt", "--lines", "2", "--url", "https://example.com/atelier") == 2
    assert run(project, "add", "--source", "docs/atelier.txt", "--lines", "2", "--url", "https://example.com/atelier",
               "--captured", "14 October", "--rights", "own") == 2
    assert run(project, "add", "--source", "docs/atelier.txt", "--lines", "2", "--captured", "2026-10-14", "--rights", "own") == 2
    assert run(project, "add", "--source", "docs/atelier.txt", "--lines", "2", "--url", "https://example.com/atelier",
               "--captured", "2026-10-14", "--rights", "reference-only") == 2          # argparse: not a choice
    assert run(project, "add", "--source", "docs/atelier.txt", "--lines", "2", "--url", "https://example.com/atelier",
               "--captured", "2026-10-14", "--rights", "licensed") == 0
    [item] = record(project)["extracts"]
    assert item["source"]["url"] == "https://example.com/atelier" and item["source"]["captured"] == "2026-10-14"
    assert item["source"]["rights"] == "licensed"
    capsys.readouterr()
    assert run(project, "show") == 0
    assert "captured 2026-10-14" in capsys.readouterr().out


def test_a_source_outside_the_project_is_recorded_by_absolute_path_and_still_checked(project, tmp_path_factory):
    guide = tmp_path_factory.mktemp("skill") / "critic.md"
    guide.write_text("# Critic\nRead the packet.\nOpen the files it lists.\n", encoding="utf-8")
    assert run(project, "add", "--source", str(guide), "--lines", "2-3") == 0
    assert record(project)["extracts"][0]["source"]["path"] == guide.resolve().as_posix()
    assert run(project, "check") == 0
    guide.write_text("# Critic\nRead the packet twice.\n", encoding="utf-8")
    assert run(project, "check") == 1


def test_what_an_extract_may_hold_is_bounded(project, capsys):
    (project / "big.md").write_text("word " * 2000 + "\n", encoding="utf-8")
    assert run(project, "add", "--source", "big.md", "--lines", "1") == 2
    assert "at most" in capsys.readouterr().err
    (project / "blank.md").write_text("a\n\n\nb\n", encoding="utf-8")
    assert run(project, "add", "--source", "blank.md", "--lines", "2-3") == 2
    (project / "bin.dat").write_bytes(b"\x00\x01\x02")
    assert run(project, "add", "--source", "bin.dat", "--lines", "1") == 2
    assert run(project, "add", "--source", "missing.md", "--lines", "1") == 2
    (project / "link.md").symlink_to(project / "BRIEF.md")
    assert run(project, "add", "--source", "link.md", "--lines", "1") == 2           # a link is not followed
    assert run(project, "add", "--source", ".git/config", "--lines", "1") == 2


def test_a_makers_record_is_never_a_source_and_the_record_holds_no_field_for_an_opinion(project, capsys):
    plan = project / f".lapis/plans/{TASK}.yaml"
    assert plan.is_file()
    assert run(project, "add", "--source", f".lapis/plans/{TASK}.yaml", "--lines", "1") == 2
    assert "maker's record" in capsys.readouterr().err
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "8") == 0
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "9", "--note", OPINION) == 2     # no such argument
    capsys.readouterr()
    for field in ("note", "summary", "why", "taste", "rating", "opinion"):
        document = record(project)
        document["extracts"][0][field] = OPINION
        assert "Additional properties" in extracts._problem(document)


def test_the_critic_packet_never_includes_a_makers_opinion_field(project):
    base = json.loads(packet(project))
    assert not any(item["kind"] in ("source-extracts", "extract-source") for item in base["inputs"])
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "8-9") == 0
    document = json.loads(packet(project))
    listed = {item["path"]: item for item in document["inputs"]}
    file = project / f".lapis/extracts/{TASK}.json"
    assert listed[f".lapis/extracts/{TASK}.json"] == {"kind": "source-extracts", "path": f".lapis/extracts/{TASK}.json",
                                                      "sha256": SHA(file.read_bytes()).hexdigest()}
    assert listed["BRIEF.md"]["kind"] == "extract-source"                                          # the original, openable
    assert listed["BRIEF.md"]["sha256"] == record(project)["extracts"][0]["source"]["sha256"]
    # a record carrying a maker's field (written by hand, past the CLI) is refused, whatever its name
    for field in ("note", "summary", "taste", "evaluation"):
        edited = record(project)
        edited["extracts"][0][field] = OPINION
        write_record(project, edited)
        with pytest.raises(critic_packet.PacketError, match="cannot go to a critic.*Additional properties"):
            packet(project)
        del edited["extracts"][0][field]
        write_record(project, edited)
    # so is one whose text is not its source's text, and one of a record the critic never reads
    edited = record(project)
    edited["extracts"][0]["text"] = OPINION
    write_record(project, edited)
    with pytest.raises(critic_packet.PacketError, match="record was edited outside"):
        packet(project)
    edited = record(project)
    plan = project / f".lapis/plans/{TASK}.yaml"
    edited["extracts"][0].update(source={"path": f".lapis/plans/{TASK}.yaml", "sha256": SHA(plan.read_bytes()).hexdigest()},
                                 locator={"start": 1, "end": 1}, text=plan.read_text(encoding="utf-8").split("\n")[0])
    write_record(project, edited)
    with pytest.raises(critic_packet.PacketError, match="maker's record the critic never reads"):
        packet(project)


def test_a_stale_extract_keeps_the_critic_packet_from_being_built_until_it_is_recorded_again(project):
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "8-9") == 0
    before = packet(project)
    (project / "BRIEF.md").write_text(BRIEF.replace("Saturdays", "Fridays"), encoding="utf-8")
    with pytest.raises(critic_packet.PacketError, match="STALE|source changed"):
        packet(project)
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "8-9") == 0
    assert packet(project) != before                                                               # the new bytes are pinned


def test_the_commands_write_one_telemetry_line_each_with_what_a_worker_reads(project):
    assert run(project, "add", "--source", "BRIEF.md", "--lines", "8-9") == 0
    assert run(project, "show") == 0
    assert run(project, "check") == 0
    lines = [json.loads(line) for line in (project / ".lapis/telemetry/checks.jsonl").read_text(encoding="utf-8").splitlines()]
    mine = [line for line in lines if line["command"].startswith("extract ")]
    assert [line["command"] for line in mine] == ["extract add", "extract show", "extract check"]
    shown = mine[1]
    assert shown["task"] == TASK and shown["exit"] == 0 and shown["extracts"] == 1 and shown["stale"] == 0
    assert shown["extract_chars"] == len("Pickup is on Saturdays.\nThe studio is closed in August.")
    assert shown["source_chars"] == len(BRIEF.rstrip("\n")) and shown["output_chars"] > 0


def test_the_worker_rules_and_the_critic_agent_tell_workers_to_read_extracts_first():
    from lapis_design import workers

    text = workers.rules()
    assert "lapis-design extract show --task <task>" in text and "open the source at its lines" in text


def test_the_extract_record_is_cli_owned_so_no_edit_tool_writes_text_into_it(project):
    from lapis_design import order

    assert order.cli_owned(f".lapis/extracts/{TASK}.json")
    event = {"cwd": str(project), "tool_name": "Write", "tool_input": {"file_path": str(project / f".lapis/extracts/{TASK}.json")}}
    refusal = order.decide(event, {})
    assert refusal and "`.lapis/extracts/`" in refusal["hookSpecificOutput"]["permissionDecisionReason"]
