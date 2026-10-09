"""References on three axes: per-axis minimums, beyond-web kinds, the curation source of an expression reference, the
motion file, lettered directions, the sheet, the registry's `axes`, and `lazuli ref capture --motion`."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image

from lapis_design import hints, next_step, references, shared_dir
from lapis_design.cli import main as design_main
from lazuli import sources
from lazuli.cli import main as lazuli_main
from procedure_support import (BRIEF_RECORD, DIRECTIONS, TASK, load_skills, record, reference_entries, references_text,
                               seal_requirements)

WEBM = b"\x1a\x45\xdf\xa3" + bytes(12 * 1024)


@pytest.fixture
def bare(tmp_path, monkeypatch) -> Path:
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    record(tmp_path, "answers", BRIEF_RECORD, 50)
    seal_requirements(tmp_path)
    load_skills(tmp_path)
    return tmp_path


def write(root: Path, entries: list[dict], offer: tuple = ("none", (), ()), **kwargs) -> None:
    hints.draw(root, TASK, offer[0], "2026-10-05", offer[1], offer[2])
    record(root, "references", references_text(entries, **kwargs), 100)


def problems(root: Path) -> str:
    return " | ".join(references.problems(root, TASK))


def test_a_record_with_every_axis_direction_and_curation_source_passes(bare):
    write(bare, reference_entries(bare))
    assert references.problems(bare, TASK) == []


def test_each_axis_needs_two_references_seen_as_images(bare):
    entries = reference_entries(bare)
    entries[3]["axis"] = "genre"                     # the second expression reference becomes a genre one
    write(bare, entries)
    assert "1 references on the expression axis are seen as images" in problems(bare)
    entries = reference_entries(bare)
    (bare / entries[5]["capture"]).write_text("a page saved as text\n")
    entries[5]["capture"] = str(Path(entries[5]["capture"]).with_suffix(".md"))
    (bare / entries[5]["capture"]).write_text("a page saved as text\n")
    write(bare, entries)
    assert "1 references on the beyond-web axis are seen as images" in problems(bare)    # text-only counts toward none


def test_an_axis_is_required_and_known(bare):
    entries = reference_entries(bare)
    entries[0].pop("axis")
    entries[1]["axis"] = "mood"
    write(bare, entries)
    assert "`axis` is None" in problems(bare) and "`axis` is 'mood'" in problems(bare)


def test_a_beyond_web_reference_is_never_web_ui(bare):
    entries = reference_entries(bare)
    entries[4].update(kind="web-ui", source_facts="body 17px/1.55 in a serif, ink #1a1a1a")
    write(bare, entries)
    assert "beyond-web axis but its kind is web-ui" in problems(bare)


def test_an_expression_reference_needs_a_curation_source_that_may_be_read(bare):
    entries = reference_entries(bare)
    for found_at, passes in (("https://www.hoverstat.es/", True), ("https://hoverstat.es/archive", True),
                             ("https://www.awwwards.com/sites/example", True),
                             ("https://thefwa.com/", False),            # a browser link: lazuli may not read it
                             ("https://museum.example/curation", False), (None, False)):
        entries[2].pop("found_at", None)
        if found_at:
            entries[2]["found_at"] = found_at
        write(bare, entries)
        assert ("found_at" not in problems(bare)) == passes, found_at


def test_found_at_must_be_an_address(bare):
    entries = reference_entries(bare)
    entries[2]["found_at"] = "hoverstat"
    write(bare, entries)
    assert "`found_at` is not an http(s) address" in problems(bare)


def test_the_motion_rule_applies_only_when_the_offer_has_a_moving_mode(bare):
    moving = next(name for name, data in hints.load()["axes"]["expression"].items() if data["motion"])
    still = next(name for name, data in hints.load()["axes"]["expression"].items() if not data["motion"])
    entries = reference_entries(bare)
    write(bare, entries, ("none", [still], []))
    assert references.problems(bare, TASK) == []
    write(bare, entries, ("none", [moving], []))
    assert "needs a `motion` file" in problems(bare)
    folder = references.folder(bare, TASK)
    for name, content, why in (("small.webm", b"\x1a\x45\xdf\xa3" + bytes(100), "is not a recording"),
                               ("fake.webm", bytes(12 * 1024), "is not a recording"),
                               ("clip.gif", WEBM, "is not a recording")):
        (folder / name).write_bytes(content)
        entries[2]["motion"] = f".lapis/references/{TASK}/{name}"
        write(bare, entries, ("none", [moving], []))
        assert why in problems(bare), name
    entries[2]["motion"] = f".lapis/references/{TASK}/missing.webm"
    write(bare, entries, ("none", [moving], []))
    assert "the motion file" in problems(bare) and "does not exist" in problems(bare)
    (folder / "motion.webm").write_bytes(WEBM)
    entries[2]["motion"] = f".lapis/references/{TASK}/motion.webm"
    write(bare, entries, ("none", [moving], []))
    assert references.problems(bare, TASK) == []
    (folder / "motion.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + bytes(12 * 1024))
    entries[2]["motion"] = f".lapis/references/{TASK}/motion.mp4"
    write(bare, entries, ("none", [moving], []))
    assert references.problems(bare, TASK) == []


def test_a_motion_file_on_a_genre_reference_does_not_satisfy_an_expression_offer(bare):
    moving = next(name for name, data in hints.load()["axes"]["expression"].items() if data["motion"])
    entries = reference_entries(bare)
    (references.folder(bare, TASK) / "motion.webm").write_bytes(WEBM)
    entries[0]["motion"] = f".lapis/references/{TASK}/motion.webm"
    write(bare, entries, ("none", [moving], []))
    assert "needs a `motion` file" in problems(bare)


def test_directions_are_at_least_three_named_each_with_two_references_from_two_axes(bare):
    entries = reference_entries(bare)
    write(bare, entries, directions={})
    assert "defines 0 directions" in problems(bare)
    write(bare, entries, directions={"A": DIRECTIONS["A"], "B": DIRECTIONS["B"]})
    assert "defines 2 directions" in problems(bare) and "`direction` is 'C'" in problems(bare)
    write(bare, entries, directions={**DIRECTIONS, "B": "calm"})
    assert "direction B has no name" in problems(bare)
    write(bare, entries, directions={**DIRECTIONS, "F": "a sixth stone as an index"})
    assert "'F' is not one letter of ABCDE" in problems(bare)
    two_axes = reference_entries(bare)
    two_axes[3]["axis"] = "genre"
    two_axes[3]["direction"] = "A"                    # A now holds genre, genre, expression, genre
    two_axes[2]["direction"] = "none"
    two_axes[0]["direction"] = "none"
    write(bare, two_axes)
    assert "direction A holds 2 references seen as images from 1 axes" in problems(bare) or "direction B" in problems(bare)
    entries[0]["direction"] = "Z"
    write(bare, entries)
    assert "`direction` is 'Z'" in problems(bare)
    entries[0].pop("direction")
    write(bare, entries)
    assert "`direction` is None" in problems(bare)


def test_a_direction_reference_pair_must_cross_axes(bare):
    entries = reference_entries(bare)
    entries[2]["direction"] = "C"                     # C: genre, expression, beyond-web; A: genre alone
    write(bare, entries)
    assert "direction A holds 1 references" in problems(bare)


def test_the_record_exposes_its_directions_for_diverge(bare):
    assert references.directions(bare, TASK) == {} and references.direction_letters(bare, TASK) == []
    write(bare, reference_entries(bare))
    assert references.direction_letters(bare, TASK) == ["A", "B", "C"]
    found = references.directions(bare, TASK)
    assert found["B"]["name"] == DIRECTIONS["B"] and [ref["id"] for ref in found["B"]["refs"]] == ["ref-4", "ref-5"]


def test_next_names_the_references_step_for_a_record_without_directions(bare):
    entries = reference_entries(bare)
    hints.draw(bare, TASK, "none", "2026-10-05")
    body = yaml.safe_dump({"captures": "study-only", "references": entries}, sort_keys=False)
    record(bare, "references", f"# References\n\n```yaml\n{body}```\n", 100)
    result = next_step.evaluate(bare, TASK)
    assert result["step"]["id"] == "references" and "no `directions` mapping" in problems(bare)


def test_the_sheet_groups_the_captures_by_direction(bare, capsys, monkeypatch):
    write(bare, reference_entries(bare))
    monkeypatch.chdir(bare)
    assert design_main(["references", "sheet", "--task", TASK]) == 0
    sheet = bare / f".lapis/references/{TASK}.sheet.png"
    with Image.open(sheet) as image:
        assert image.width > 3 * 360 and image.height > 2 * 270
    assert "one column per direction" in capsys.readouterr().out
    (bare / f".lapis/references/{TASK}.md").write_text("```yaml\nreferences: []\n```\n")
    assert design_main(["references", "sheet", "--task", TASK]) == 1
    assert "no readable `directions`" in capsys.readouterr().err


def test_registry_axes_filter_the_sources(capsys):
    registry = sources.load_registry()
    schema = yaml.safe_load((shared_dir() / "sources/registry.schema.yaml").read_text())
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
        yaml.safe_load((shared_dir() / "sources/registry.yaml").read_text()))) == []
    tagged = [entry for entry in registry if "axes" in entry]
    assert {axis for entry in tagged for axis in entry["axes"]} == set(sources.AXES)
    assert all(entry["type"] != ["font"] for entry in tagged)
    assert lazuli_main(["sources", "--axis", "beyond-web"]) == 0
    output = capsys.readouterr().out
    assert "design-museum" in output and "hoverstates" not in output and "[beyond-web]" in output
    assert lazuli_main(["sources", "--axis", "expression", "--json"]) == 0
    ids = {entry["id"] for entry in json.loads(capsys.readouterr().out)}
    assert {"codrops", "hoverstates", "recent-design", "motionographer", "land-book"} <= ids and "moma" not in ids
    bad = {"id": "x", "name": "X", "url": "https://example.com/", "type": ["search"], "good_for": "testing",
           "access": "read", "terms_url": "https://example.com/terms", "checked_at": "2026-10-09", "axes": ["mood"]}
    assert list(Draft202012Validator(schema).iter_errors({"version": 0, "sources": [bad]}))


def test_land_book_is_read_with_its_credit_note_and_godly_names_its_trap():
    by_id = {entry["id"]: entry for entry in sources.load_registry()}
    assert by_id["land-book"]["access"] == "read" and "credit the designer" in by_id["land-book"]["note"]
    assert "godly.website" in by_id["godly"]["note"] and "index.md" in by_id["godly"]["note"]
    assert by_id["recent-design"]["hosts"] == ["godly.website"]
    assert sources.find("https://godly.website/", None)["id"] == "recent-design"
