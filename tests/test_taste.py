"""User taste remains distinct from an agent's reading and never becomes a gate."""

import pytest
import yaml

from lapis_design import next_step, plan_check, shared_dir
from procedure_support import BRIEF_RECORD, TASK, finish, make_project, record, touch, update

TASTE = """# Taste
Given by: the user in the session, 2026-10-05

## Likes
- Ruled records
## Dislikes
- Luminous gradients
## References
- https://museum.example/collection
## Avoid
- 카드 격자
## Feel
Quiet enough to read the firing log.
## Fixed
- Keep the studio mark
"""


def put_taste(root):
    path = root / ".lapis/taste.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TASTE, encoding="utf-8")


def check(root, plan):
    return plan_check.run(None, None, None, shared_dir() / "plan/schema.yaml", root,
                          plan=plan, plan_label=".lapis/plans/test.yaml")


def base():
    plan = yaml.safe_load((shared_dir() / "plan/example.plan.yaml").read_text())
    plan["tokens"]["type"]["roles"] = []
    return plan


def taste_ids(report):
    return {f["rule_id"] for f in report["findings"] if f["rule_id"].startswith("taste.")}


def test_user_sections_and_plain_feel_are_parsed():
    from lapis_design import taste

    parsed = taste.parse(TASTE)
    assert parsed["likes"] == ["Ruled records"]
    assert parsed["dislikes"] == ["Luminous gradients"]
    assert parsed["avoid"] == ["카드 격자"]
    assert parsed["references"] == ["https://museum.example/collection"]
    assert parsed["feel"] == ["Quiet enough to read the firing log."]
    assert parsed["fixed"] == ["Keep the studio mark"]
    assert parsed["given_by"] == "the user in the session, 2026-10-05"


@pytest.mark.parametrize("line,concept", [("Luminous gradients", "A luminous firing curve"),
                                          ("카드 격자", "카드형 격자로 작품을 배치해요")])
def test_dislike_overlap_needs_an_explicit_stance(tmp_path, line, concept):
    put_taste(tmp_path)
    plan = base()
    plan["direction"].update(concept=concept, taste={"source": ".lapis/taste.md", "follows": ["Ruled records"]})
    report = check(tmp_path, plan)
    assert "taste.dislike-touched" in taste_ids(report)
    assert not any(f["blocking"] for f in report["findings"] if f["rule_id"].startswith("taste."))
    plan["direction"]["taste"]["dislikes"] = [{"line": line, "stance": "against",
                                                "why": "The kiln curve needs this treatment; ask the user to confirm."}]
    # A separate overlap may remain; the acknowledged line must no longer be flagged.
    assert not any(f["rule_id"] == "taste.dislike-touched" and line in f["observed"]
                   for f in check(tmp_path, plan)["findings"])


def test_unattended_not_given_is_a_record_not_an_assumed_preference(tmp_path, monkeypatch):
    from lapis_design import taste

    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    plan = base()
    assert taste.state(tmp_path, TASK) == "unrecorded"
    assert "taste.unrecorded" in taste_ids(check(tmp_path, plan))
    record(tmp_path, "answers", BRIEF_RECORD.replace("## Found", "## Found\n\n- Taste: not given"), 50)
    assert taste.state(tmp_path, TASK) == "not-given"
    assert "taste.unrecorded" not in taste_ids(check(tmp_path, plan))
    plan["direction"]["taste"] = {"source": "invented preference"}
    assert "taste.own-reading-unsaid" in taste_ids(check(tmp_path, plan))
    plan["direction"]["taste"] = {"source": "own-reading"}
    assert not taste_ids(check(tmp_path, plan))
    assert not (tmp_path / ".lapis/taste.md").exists()


@pytest.mark.parametrize("state", ["given", "not-given", "unrecorded"])
def test_done_exposes_taste_provenance_without_a_new_gate(tmp_path, state):
    make_project(tmp_path)
    if state == "given":
        put_taste(tmp_path)
        update(tmp_path, f"plans/{TASK}.yaml", lambda p: p["direction"].update(
            taste={"source": ".lapis/taste.md", "follows": ["Ruled records"]}))
        touch(tmp_path, f"plans/{TASK}.yaml", 90)
    elif state == "not-given":
        record(tmp_path, "answers", BRIEF_RECORD.replace("## Found", "## Found\n\n- Taste: not given"), 50)
    assert finish(tmp_path, "--static") == 0
    result = next_step.evaluate(tmp_path, TASK)
    assert result["state"] == "done"
    reason = result["reason"].lower()
    assert "taste" in reason
    if state == "given":
        assert ".lapis/taste.md" in reason and "the user in the session" in reason and "cited" in reason
    elif state == "not-given":
        assert "not given" in reason and "own reading" in reason
    else:
        assert "unrecorded" in reason


def test_empty_project_taste_does_not_hide_absence_and_given_taste_wins(tmp_path):
    from lapis_design import taste

    record(tmp_path, "answers", BRIEF_RECORD.replace("## Found", "## Found\n\n- Taste: not given"), 50)
    put_taste(tmp_path)
    assert taste.state(tmp_path, "a-different-task") == "given"
    assert taste.state(tmp_path, TASK) == "given"
    (tmp_path / ".lapis/taste.md").write_text("# Taste\n## Likes\n", encoding="utf-8")
    assert taste.state(tmp_path, TASK) == "not-given"
    assert taste.state(tmp_path, "a-different-task") == "unrecorded"


def test_unknown_refusal_and_missing_citation_warn_but_repair_skips(tmp_path):
    put_taste(tmp_path)
    plan = base()
    report = check(tmp_path, plan)
    assert "taste.not-cited" in taste_ids(report)
    plan["direction"]["taste"] = {"source": ".lapis/taste.md", "follows": ["Ruled records"],
                                  "dislikes": [{"line": "Invented refusal", "stance": "clear",
                                                "why": "No such preference was given."}]}
    assert "taste.line-unknown" in taste_ids(check(tmp_path, plan))
    plan["mode"] = "repair"
    assert not taste_ids(check(tmp_path, plan))
