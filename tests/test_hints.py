"""Genre hints offer starting points while preserving independent reference discovery."""
import json

import pytest
import yaml
from jsonschema import Draft202012Validator

from lapis_design import references, shared_dir
from lazuli.cli import main as lazuli_main
from procedure_support import TASK, record, references_text, write_references


def test_every_field_offers_three_and_rotation_is_reproducible():
    from lapis_design import hints

    fields = hints.load()["fields"]
    assert len(fields) == 25
    for field, data in fields.items():
        offered = hints.offer(TASK, field, "2026-10-05")
        assert len(offered) == 3
        assert len({entry["url"] for entry in offered}) == 3
        assert offered == hints.offer(TASK, field, "2026-10-05")
        all_urls = {entry["url"] for entry in data["entries"]}
        rotations = [hints.offer(f"task-{n}", field, "2026-10-05") for n in range(100)]
        assert {entry["url"] for draw in rotations for entry in draw} == all_urls
        assert any(draw != offered for draw in rotations)
        assert any(hints.offer(TASK, field, f"2026-10-{day:02d}") != offered for day in range(6, 12))
    assert hints.offer(TASK, "none", "2026-10-05") == []


def test_offered_hints_are_recorded_and_same_field_keeps_original_date(tmp_path):
    from lapis_design import hints

    first = hints.draw(tmp_path, TASK, "museums-culture", "2026-10-05")
    path = tmp_path / f".lapis/references/{TASK}.hints.json"
    assert json.loads(path.read_text()) == {"task": TASK, "field": "museums-culture", "date": "2026-10-05",
                                           "offered": [entry["url"] for entry in first]}
    assert hints.draw(tmp_path, TASK, "museums-culture", "2026-10-06") == first
    assert json.loads(path.read_text())["date"] == "2026-10-05"


def test_agent_found_minimum_is_beyond_the_whole_list(tmp_path):
    from lapis_design import hints

    entries = write_references(tmp_path)
    hints.draw(tmp_path, TASK, "museums-culture", "2026-10-05")
    # Even hints not offered on this rotation or in this field are not independent finds.
    listed = [entry for data in hints.load()["fields"].values() for entry in data["entries"]]
    for i, entry in enumerate(entries[:4]):
        entry["url"] = listed[i]["url"]
    record(tmp_path, "references", references_text(entries), 50)
    assert any("agent-found" in reason for reason in references.problems(tmp_path, TASK))
    entries[3].pop("url")
    entries[3]["source"] = "The user's own firing log photograph"
    record(tmp_path, "references", references_text(entries), 50)
    assert references.problems(tmp_path, TASK) == []


def test_references_require_a_real_offer_record(tmp_path):
    from lapis_design import hints

    write_references(tmp_path)
    (tmp_path / f".lapis/references/{TASK}.hints.json").unlink()
    assert any("lazuli hints" in reason for reason in references.problems(tmp_path, TASK))
    hints.draw(tmp_path, TASK, "none", "2026-10-05")
    assert references.problems(tmp_path, TASK) == []
    path = tmp_path / f".lapis/references/{TASK}.hints.json"
    path.write_text(json.dumps({"task": TASK, "field": "museums-culture", "date": "2026-10-05", "offered": []}))
    assert any("lazuli hints" in reason for reason in references.problems(tmp_path, TASK))


@pytest.mark.parametrize("url,match", [("https://www.gov.uk/service-manual/design/patterns", True),
                                       ("https://gov.uk/service-manual/designer", False),
                                       ("https://not-gov.uk/service-manual/design", False)])
def test_reference_matching_respects_host_and_path_segments(url, match):
    from lapis_design import hints

    assert hints.matches(url, "https://www.gov.uk/service-manual/design") == match


def test_cli_lists_fields_and_records_its_offer(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert lazuli_main(["hints"]) == 0
    assert "museums-culture" in capsys.readouterr().out
    assert lazuli_main(["hints", "--field", "museums-culture", "--task", TASK, "--date", "2026-10-05"]) == 0
    output = capsys.readouterr().out
    offered = json.loads((tmp_path / f".lapis/references/{TASK}.hints.json").read_text())["offered"]
    assert len(offered) == 3 and all(url in output for url in offered)
    assert "agent-found" in output


def test_data_obeys_schema_and_access_boundaries():
    from lapis_design import hints
    from lazuli.sources import load_registry, find

    data = hints.load()
    schema = yaml.safe_load((shared_dir() / "sources/hints.schema.yaml").read_text())
    Draft202012Validator(schema).validate(data)
    sources = load_registry()
    for field in data["fields"].values():
        assert len(field["entries"]) >= 4
        for entry in field["entries"]:
            source = find(entry["url"], sources)
            assert source is None or source["access"] not in {"refused", "browser-link"}


def test_critic_comparison_reports_visitor_choice_with_evidence():
    from lapis_design.lint.cli import problems

    report = {"version": 0, "tool": {"name": "critic", "version": "test"}, "target": {"task": TASK},
              "findings": [], "comparisons": [{"reference": ".lapis/references/demo/museum/390.png",
                  "viewport": 390, "would_choose_ours": "no", "why": "Ours hides hours below two screens of artwork.",
                  "refs": [".lapis/renders/demo.shots/390.png"]}]}
    assert problems(report, "report") == []
    report["comparisons"][0]["would_choose_ours"] = "maybe"
    assert problems(report, "report")
