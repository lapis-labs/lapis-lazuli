"""The critic packet's `gaps` and `asks` sections, and the schemas of the two records the CLI keeps for them
(`gaps/schema.yaml`, `asks/schema.yaml`)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from lapis_design import asks, critic_packet, integrity, next_step, owner, shared_dir
from procedure_support import TASK, make_project, record, reply, seal_slice, unseal_slice

SHARED = shared_dir()


@pytest.fixture(autouse=True)
def attended(monkeypatch):
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")


def packet(root: Path) -> dict:
    return json.loads(critic_packet.build(root, TASK, {"extracts": [f".lapis/renders/{TASK}.json"],
                                                       "lint": f".lapis/lint/{TASK}.json", "session": None}))


def schema(name: str) -> Draft202012Validator:
    return Draft202012Validator(yaml.safe_load((SHARED / name).read_text(encoding="utf-8")))


def test_the_packet_lists_the_gaps_as_the_owner_block_shows_them(tmp_path):
    root = make_project(tmp_path)
    found = packet(root)["gaps"]
    assert [g["id"] for g in found][:2] == ["objects:O1", "signature"] and {g["area"] for g in found} >= {"color", "layout"}
    text, _ = owner.block(root, TASK)
    assert all(g["text"] in text for g in found)
    assert not list(schema("review/critic-packet.schema.yaml").iter_errors(packet(root)))
    assert packet(root) == packet(root)                                                       # deterministic


def test_a_declared_area_leaves_the_gaps_of_the_packet(tmp_path):
    root = make_project(tmp_path)
    reply(root, "- [declared] color: the page stays white, the kiln blue only on the button\n", 300)
    assert "color" not in [g["id"] for g in packet(root)["gaps"]]


def test_the_packet_carries_the_asks_without_the_runs_basis(tmp_path):
    root = make_project(tmp_path)
    assert packet(root)["asks"] == []
    path = root / f".lapis/answers/{TASK}.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n## Asks\n\n"
                    "- [declared] Ask finding-vs-decision: one composition per plate — they said so\n"
                    "- [assumed] Ask budget: keep going? — took keep going. Basis: nobody to ask; the slice is sealed.\n",
                    encoding="utf-8")
    found = packet(root)["asks"]
    assert found == [{"trigger": "finding-vs-decision", "by": "owner", "said": "one composition per plate — they said so"},
                     {"trigger": "budget", "by": "run", "said": "keep going? — took keep going."}]
    assert "nobody to ask" not in json.dumps(found)


def test_a_changed_gap_or_ask_makes_the_critic_report_stale(tmp_path):
    root = make_project(tmp_path)
    before = critic_packet.build(root, TASK, {"extracts": [f".lapis/renders/{TASK}.json"],
                                              "lint": f".lapis/lint/{TASK}.json", "session": None})
    reply(root, "- [declared] layout: a ruled sheet, no cards\n", 300)
    after = critic_packet.build(root, TASK, {"extracts": [f".lapis/renders/{TASK}.json"],
                                             "lint": f".lapis/lint/{TASK}.json", "session": None})
    assert before != after


def test_the_records_the_cli_writes_hold_to_their_schemas(tmp_path):
    root = make_project(tmp_path)
    unseal_slice(root)
    integrity.observe_task(root, TASK, "test")
    _, sha8 = owner.write(root, TASK)
    gaps_record = json.loads((root / f".lapis/state/{TASK}.gaps.json").read_text(encoding="utf-8"))
    assert sha8 in gaps_record["blocks"] and not list(schema("gaps/schema.yaml").iter_errors(gaps_record))
    record(root, "questions", "lapis-questions: ask\n1. Keep the repeated plate?\n   a) keep  b) change\n"
           "Trigger: finding-vs-decision — the plates\nDefault: a — keep until you see it.\n", 200)
    next_step.evaluate(root, TASK)
    log = json.loads(asks.log_path(root, TASK).read_text(encoding="utf-8"))
    assert log["sets"] and not list(schema("asks/schema.yaml").iter_errors(log))
    assert list(schema("asks/schema.yaml").iter_errors({**log, "sets": [{**log["sets"][0], "kind": "poll"}]}))
    assert list(schema("gaps/schema.yaml").iter_errors({**gaps_record, "blocks": {"xyz": []}}))


def test_the_index_lists_both_records_and_the_critic_is_told_about_the_sections():
    items = {i["id"]: i for i in yaml.safe_load((SHARED / "index.yaml").read_text(encoding="utf-8"))["items"]}
    for ident, path in (("gaps-record", "gaps/schema.yaml"), ("asks-log", "asks/schema.yaml")):
        assert (items[ident]["path"], items[ident]["kind"]) == (path, "contract") and (SHARED / path).is_file()
        assert items[ident]["consumers"]["lapis"] == "full"
    critic = (SHARED.parent / "agents/critic.md").read_text(encoding="utf-8")
    assert "- `gaps`:" in critic and "- `asks`:" in critic
