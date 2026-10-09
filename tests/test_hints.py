"""Genre hints offer starting points while preserving independent reference discovery."""
import json

import pytest
import yaml
from jsonschema import Draft202012Validator

from lapis_design import references, shared_dir
from lazuli.cli import main as lazuli_main
from procedure_support import TASK, record, references_text, write_references


def test_every_axis_offers_its_count_and_rotation_is_reproducible():
    from lapis_design import hints

    axes = hints.load()["axes"]
    assert len(axes["genre"]) == 25 and axes["expression"] and axes["beyond-web"]
    for field, data in axes["genre"].items():
        offered = hints.offer(TASK, field, "2026-10-05")
        assert len(offered) == 3 and len({entry["url"] for entry in offered}) == 3
        assert offered == hints.offer(TASK, field, "2026-10-05")
        all_urls = {entry["url"] for entry in data["entries"]}
        rotations = [hints.offer(f"task-{n}", field, "2026-10-05") for n in range(100)]
        assert {entry["url"] for draw in rotations for entry in draw} == all_urls
        assert any(draw != offered for draw in rotations)
        assert any(hints.offer(TASK, field, f"2026-10-{day:02d}") != offered for day in range(6, 12))
    assert hints.offer(TASK, "none", "2026-10-05") == []
    for axis in ("expression", "beyond-web"):
        for name, data in axes[axis].items():
            offered = hints.offer_axis(TASK, axis, name, "2026-10-05")
            assert len(offered) == 2 and offered == hints.offer_axis(TASK, axis, name, "2026-10-05")
            rotations = [hints.offer_axis(f"task-{n}", axis, name, "2026-10-05") for n in range(100)]
            assert {entry["url"] for draw in rotations for entry in draw} == {e["url"] for e in data["entries"]}


def test_offers_are_recorded_per_axis_and_the_same_choice_keeps_its_original_date(tmp_path):
    from lapis_design import hints

    first = hints.draw(tmp_path, TASK, "museums-culture", "2026-10-05", ["motion-led"], ["poster", "film-title"])
    path = tmp_path / f".lapis/references/{TASK}.hints.json"
    record = json.loads(path.read_text())
    assert (record["version"], record["genre"], record["expression"], record["beyond_web"], record["date"]) == (
        1, "museums-culture", ["motion-led"], ["poster", "film-title"], "2026-10-05")
    assert len(first) == 3 + 2 + 4 and record["offered"] == [entry["url"] for entry in first]
    assert hints.draw(tmp_path, TASK, "museums-culture", "2026-10-06", ["motion-led"], ["poster", "film-title"]) == first
    assert json.loads(path.read_text())["date"] == "2026-10-05"
    again = hints.draw(tmp_path, TASK, "museums-culture", "2026-10-06", ["motion-led"], ["poster"])
    assert json.loads(path.read_text())["date"] == "2026-10-06" and len(again) == 3 + 2 + 2
    with pytest.raises(ValueError, match="at most 2"):
        hints.draw(tmp_path, TASK, "none", "2026-10-05", list(hints.names("expression"))[:3])
    with pytest.raises(ValueError, match="beyond-web"):
        hints.draw(tmp_path, TASK, "none", "2026-10-05", (), ["no-such-medium"])


def test_a_version_0_offer_is_refused_with_its_message(tmp_path):
    from lapis_design import hints

    write_references(tmp_path)
    path = tmp_path / f".lapis/references/{TASK}.hints.json"
    path.write_text(json.dumps({"task": TASK, "field": "none", "date": "2026-10-05", "offered": []}))
    assert hints.read(tmp_path, TASK) is None
    assert any("version 0" in reason and "--genre" in reason for reason in references.problems(tmp_path, TASK))


def test_agent_found_minimum_is_one_per_axis_beyond_the_whole_list(tmp_path):
    from lapis_design import hints

    entries = write_references(tmp_path)
    listed = [entry for axis in hints.load()["axes"].values() for data in axis.values() for entry in data["entries"]]
    # Even hints not offered on this rotation, in another axis or field, are not independent finds.
    for i, entry in enumerate(entries):
        entry["url"] = listed[i * 7]["url"]
    record(tmp_path, "references", references_text(entries), 50)
    reasons = references.problems(tmp_path, TASK)
    assert [axis for axis in references.AXES if any(f"no agent-found reference is on the {axis} axis" in r for r in reasons)
            ] == list(references.AXES)
    for index in (0, 2, 4):                             # one source-only reference on each axis
        entries[index].pop("url")
        entries[index]["source"] = "The user's own firing log photograph"
    record(tmp_path, "references", references_text(entries), 50)
    assert not any("agent-found" in reason for reason in references.problems(tmp_path, TASK))


def test_references_require_a_real_offer_record(tmp_path):
    from lapis_design import hints

    write_references(tmp_path)
    (tmp_path / f".lapis/references/{TASK}.hints.json").unlink()
    assert any("lazuli hints" in reason for reason in references.problems(tmp_path, TASK))
    hints.draw(tmp_path, TASK, "none", "2026-10-05")
    assert references.problems(tmp_path, TASK) == []
    path = tmp_path / f".lapis/references/{TASK}.hints.json"
    path.write_text(json.dumps({"version": 1, "task": TASK, "date": "2026-10-05", "genre": "museums-culture",
                                "expression": [], "beyond_web": [], "offered": []}))
    assert any("lazuli hints" in reason for reason in references.problems(tmp_path, TASK))


def test_suggest_lists_modes_whose_words_occur():
    from lapis_design import hints

    found = hints.suggest("The owner wants it artistic and dynamic, with 움직임 and a raw feel.")
    assert "motion-led" in found and "dynamic" in found["motion-led"]
    assert hints.suggest("A calm booking page for a pottery studio.") == {}


@pytest.mark.parametrize("url,match", [("https://www.gov.uk/service-manual/design/patterns", True),
                                       ("https://gov.uk/service-manual/designer", False),
                                       ("https://not-gov.uk/service-manual/design", False)])
def test_reference_matching_respects_host_and_path_segments(url, match):
    from lapis_design import hints

    assert hints.matches(url, "https://www.gov.uk/service-manual/design") == match


def test_cli_lists_axes_records_its_offer_and_suggests(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert lazuli_main(["hints"]) == 0
    listing = capsys.readouterr().out
    assert "museums-culture" in listing and "motion-led [motion]" in listing and "poster [print]" in listing
    assert lazuli_main(["hints", "--genre", "museums-culture", "--expression", "motion-led", "--beyond-web",
                        "poster", "--task", TASK, "--date", "2026-10-05"]) == 0
    output = capsys.readouterr().out
    offered = json.loads((tmp_path / f".lapis/references/{TASK}.hints.json").read_text())["offered"]
    assert len(offered) == 3 + 2 + 2 and all(url in output for url in offered)
    assert "Shows:" in output and "one agent-found reference per axis" in output
    with pytest.raises(SystemExit):
        lazuli_main(["hints", "--genre", "museums-culture"])             # a genre goes with a task
    (tmp_path / ".lapis").mkdir(exist_ok=True)
    (tmp_path / ".lapis/taste.md").write_text("# Taste\n\n## Feel\n\nartistic and dynamic\n")
    assert lazuli_main(["hints", "--suggest", "--task", TASK]) == 0
    assert "motion-led: dynamic" in capsys.readouterr().out


def test_data_obeys_schema_and_access_boundaries():
    from lapis_design import hints
    from lazuli.sources import load_registry, find

    data = hints.load()
    schema = yaml.safe_load((shared_dir() / "sources/hints.schema.yaml").read_text())
    Draft202012Validator(schema).validate(data)
    sources = load_registry()
    for axis in data["axes"].values():
        for field in axis.values():
            assert len(field["entries"]) >= 4
            for entry in field["entries"]:
                source = find(entry["url"], sources)
                assert source is None or source["access"] not in {"refused", "browser-link"}, entry["url"]
    assert all(entry["shows"] for mode in data["axes"]["expression"].values() for entry in mode["entries"])


def test_critic_comparison_reports_visitor_choice_with_evidence():
    from lapis_design.lint.cli import problems

    report = {"version": 0, "tool": {"name": "critic", "version": "test"}, "target": {"task": TASK},
              "findings": [], "comparisons": [{"reference": ".lapis/references/demo/museum/390.png",
                  "viewport": 390, "would_choose_ours": "no", "why": "Ours hides hours below two screens of artwork.",
                  "refs": [".lapis/renders/demo.shots/390.png"]}]}
    assert problems(report, "report") == []
    report["comparisons"][0]["would_choose_ours"] = "maybe"
    assert problems(report, "report")
