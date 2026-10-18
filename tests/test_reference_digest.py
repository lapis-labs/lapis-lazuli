"""The reference digest: what each reference gives the page and what it leaves out, written in the references record, shown to
the owner at the first direction turn, named by the roughs' cards, carried by the plan, and judged by the critic.

The cases are the ways the digest can fail its purpose: a take with no place on the page, a reference that leaves nothing, a
feature the owner asked for slid into `leave`, a table the owner never sees, an id a card made up."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from diverge_support import write_rough
from lapis_design import direction, diverge, hints, next_step, owner, plan_check, references
from procedure_support import (BRIEF_RECORD, DIRECTION_PROPOSAL, TASK, make_project, record, reference_entries, references_text,
                               refresh_critic, row_id, save, seal_requirements, write_requirements)
from test_diverge import attended, make_all, run, start  # noqa: F401  (a create run with its references and a first turn, not yet drawn)

WIPE = "Add a wipe slider that reveals the kiln before and after firing."
KOREAN_WIPE = "굽기 전과 후를 보여 주는 와이프 슬라이더를 넣어 주세요. 방문하는 사람이 직접 밀어서 비교할 수 있어야 해요."


def start_project(root: Path, *rows: str) -> Path:
    """A brief record, and the requirement record sealed from an owner brief of `rows`."""
    record(root, "answers", BRIEF_RECORD, 50)
    write_requirements(root, rows)
    return root


@pytest.fixture
def project(tmp_path) -> Path:
    return start_project(tmp_path, WIPE)


def write(root: Path, entries: list[dict]) -> None:
    hints.draw(root, TASK, "none", "2026-10-05")
    record(root, "references", references_text(entries), 100)


def problems(root: Path) -> str:
    return " | ".join(references.problems(root, TASK))


def with_item(entries: list[dict], index: int, side: str, **change) -> list[dict]:
    entries[index][side] = [{**entries[index][side][0], **change}]
    return entries


# ---- the checks on the record

def test_a_record_with_a_digest_that_names_places_and_leaves_passes(project):
    write(project, reference_entries(project))
    assert references.problems(project, TASK) == []


@pytest.mark.parametrize("at", ["somewhere nice", "", "the page", "on it"])
def test_a_take_that_names_no_page_location_is_refused(project, at):
    write(project, with_item(reference_entries(project), 1, "take", at=at))
    found = problems(project)
    assert "reference ref-2: take M3 names no page location in `at`" in found
    assert "a region such as hero, header, footer, first view" in found


@pytest.mark.parametrize("at", ["the hero, under the headline", "히어로 아래", "the price table", "first view", "O1"])
def test_a_take_that_names_a_region_or_an_object_id_is_accepted(project, at):
    save(project, f"direction/{TASK}.yaml", DIRECTION_PROPOSAL)             # O1 is a core object of the proposal
    write(project, with_item(reference_entries(project), 1, "take", at=at))
    assert references.problems(project, TASK) == []


def test_a_take_may_name_a_section_of_the_plan_or_of_the_owners_brief(project):
    """The ids of the plan's layout sections and the headings of the owner's own brief are places too."""
    save(project, f"plans/{TASK}.yaml", {"layout": {"sections": [{"id": "reserve-list", "answers": "which pieces are free"}]}})
    (project / "owner-brief.md").write_text(f"## Kiln calendar\n\n- {WIPE}\n", encoding="utf-8")
    seal_requirements(project, TASK, "owner-brief.md")
    entries = reference_entries(project)
    for index, at in ((0, "section reserve-list"), (1, "the Kiln calendar block")):
        with_item(entries, index, "take", at=at)
    write(project, entries)
    assert references.problems(project, TASK) == []


def test_a_reference_with_no_leave_is_refused(project):
    entries = reference_entries(project)
    entries[2].pop("leave")
    write(project, entries)
    assert "reference ref-3 has no `leave` item; every reference leaves something" in problems(project)
    entries[2]["leave"] = []
    write(project, entries)
    assert "reference ref-3 has no `leave` item" in problems(project)


def test_a_reference_with_no_take_is_refused_and_each_item_needs_an_id_and_words_of_its_own(project):
    entries = reference_entries(project)
    entries[0].pop("take")
    with_item(entries, 1, "leave", id="M3")                                   # M3 is the take of the same reference
    with_item(entries, 2, "leave", what="logo")
    write(project, entries)
    found = problems(project)
    assert "reference ref-1 has no `take` items" in found
    assert "the digest id M3 is used twice (also in reference ref-2)" in found
    assert "leave M6 has no `what` (two words at least)" in found


def test_a_leave_that_takes_away_a_requirement_row_is_refused_with_the_row_quoted_and_allowed_after_an_owner_drop(project):
    row = row_id(WIPE)
    write(project, with_item(reference_entries(project), 3, "leave", what="its wipe slider between two photographs",
                             why="the brand's own idiom"))
    found = problems(project)
    assert f"reference ref-4: leave M8 ('its wipe slider between two photographs') takes away the owner's row {row} " in found
    assert f'"{WIPE}"' in found and "(matched on wipe, slider)" in found
    assert f"`[declared] {row}: drop" in found                                    # the way out is the owner's own reply
    record(project, "answers", BRIEF_RECORD + f'\n## Replies\n\n- [declared] {row}: drop — "no slider after all"\n', 60)
    assert references.problems(project, TASK) == []


def test_a_row_the_owner_wrote_in_the_brief_record_is_held_as_well_and_a_quoted_row_id_counts(project):
    record(project, "answers", BRIEF_RECORD + '\n## Replies\n\n- [declared] The ticker band stays at the top — "keep it"\n', 60)
    write(project, with_item(reference_entries(project), 0, "leave", what="its ticker band", why="a trend kit"))
    assert "takes away the owner's row R" in problems(project) and "The ticker band stays at the top" in problems(project)
    row = row_id(WIPE)
    write(project, with_item(reference_entries(project), 0, "leave", what="the marks", why=f"see {row}"))
    assert f"row {row}" in problems(project)


def test_a_leave_with_other_words_than_every_row_passes_and_the_limits_of_the_match_are_what_the_guide_says(project):
    """The match reads words: one shared word of a longer item is not a match, and an item reworded away from the row
    gets through (the guide says so)."""
    write(project, with_item(reference_entries(project), 0, "leave", what="its slider thumb styling", why="the brand's own identity"))
    assert references.problems(project, TASK) == []                            # `slider` alone, in an item of three words
    write(project, with_item(reference_entries(project), 0, "leave", what="the kiln photographs", why="its own pictures"))
    assert references.problems(project, TASK) == []                            # `kiln` alone: one word of two does not match


def test_a_korean_leave_is_matched_to_a_korean_row_through_its_particles(tmp_path):
    start_project(tmp_path, KOREAN_WIPE)
    write(tmp_path, with_item(reference_entries(tmp_path), 0, "leave", what="와이프 슬라이더를", why="브랜드 고유의 표현"))
    assert "takes away the owner's row" in problems(tmp_path) and "와이프" in problems(tmp_path)


# ---- the owner sees it at the first direction turn

def korean(entries: list[dict]) -> list[dict]:
    entries[0]["take"] = [{"id": "M1", "element": "가격표의 가는 줄과 굵은 시간 열", "at": "히어로 아래", "why": "한 줄씩 훑어 읽기 좋아요"}]
    entries[0]["leave"] = [{"id": "M2", "what": "서체와 장식 무늬", "why": "그곳만의 정체성이에요"}]
    return entries


def test_the_direction_summary_shows_the_digest_as_a_table_in_english(project):
    write(project, reference_entries(project))
    delivery = owner.deliver(project, TASK, {"kind": "direction"})
    text = delivery.summary
    assert "## References: what we take and leave" in text
    assert "| id | reference | take or leave | item | where it goes, and why |" in text
    assert "**A — the stone as a specimen sheet**" in text and "**C — the record as a ledger**" in text
    assert "| M1 | ref-1 | take | the ruled rhythm of its listing table | the hero, under the headline — rows scan left to right |" in text
    assert "| M2 | ref-1 | leave | its type and marks | the brand's own identity |" in text
    assert "nothing here waits for your approval" in text and text.count("\nDecision:") == 1
    assert ("reference digest", "| M2 | ref-1 | leave | its type and marks | the brand's own identity |") in delivery.required


def test_the_direction_summary_shows_the_digest_as_a_table_in_korean(tmp_path):
    start_project(tmp_path, "방문하는 사람이 지금 남은 작품을 한눈에 보고 예약할 수 있어야 해요. 가마 일정도 보여 주세요.")
    write(tmp_path, korean(reference_entries(tmp_path)))
    text = owner.deliver(tmp_path, TASK, {"kind": "direction"}).summary
    assert "## 참고 자료에서 가져올 것과 두고 갈 것" in text
    assert "| 번호 | 참고 자료 | 구분 | 항목 | 둘 곳과 이유 |" in text
    assert "| M1 | ref-1 | 가져올 것 | 가격표의 가는 줄과 굵은 시간 열 | 히어로 아래 — 한 줄씩 훑어 읽기 좋아요 |" in text
    assert "| M2 | ref-1 | 두고 갈 것 | 서체와 장식 무늬 | 그곳만의 정체성이에요 |" in text
    assert "따로 승인하실 필요는 없어요" in text and "## References" not in text


def test_the_table_is_shown_at_turn_one_only_and_a_summary_that_drops_a_row_of_it_is_refused(project):
    write(project, reference_entries(project))
    delivery = owner.deliver(project, TASK, {"kind": "direction"})
    row = "| M4 | ref-2 | leave | its type and marks | the brand's own identity |"
    assert delivery.problems(delivery.summary) == []
    problems_found = delivery.problems(delivery.summary.replace(row + "\n", ""))
    assert len(problems_found) == 1 and "reference digest: | M4 | ref-2 | leave" in problems_found[0]
    assert "## References" not in owner.deliver(project, TASK, {"kind": "approval"}).summary      # not an approval's business


def test_a_run_without_a_digest_shows_no_table(project):
    entries = reference_entries(project)
    for entry in entries:
        entry.pop("take"), entry.pop("leave")
    write(project, entries)
    assert "## References" not in owner.deliver(project, TASK, {"kind": "direction"}).summary


# ---- the owner's replies

def reply(root: Path, *lines: str) -> None:
    """The owner's first-turn replies as the run records them: they take the defaults of the direction items, and say `lines`."""
    body = "\n".join(f"- {line}" for line in ('Defaults accepted (direction 1): "go with the defaults"', *lines))
    record(root, "answers", f"{BRIEF_RECORD}\n## Direction 1\n\n{body}\n", 60)


def test_an_owner_reply_moves_an_item_between_take_and_leave_and_the_tables_follow(project):
    from lapis_design import reference_digest

    write(project, reference_entries(project))
    reply(project, '[declared] take M2: the footer, small — "yes, keep the marks"', '[declared] leave M3: — "no, too busy"')
    digest = reference_digest.effective(project, TASK)
    first, second = digest["references"][0], digest["references"][1]
    assert [i["id"] for i in first["take"]] == ["M1", "M2"] and first["take"][1]["by"] == "owner"
    assert first["take"][1]["at"] == "the footer, small" and first["leave"] == []
    assert second["take"] == [] and second["leave"][0]["id"] == "M3" and second["leave"][0]["by"] == "owner"
    assert [i["id"] for i in second["leave"]] == ["M3", "M4"]
    text = owner.deliver(project, TASK, {"kind": "direction"}).summary
    assert "| M2 | ref-1 | take | its type and marks | the footer, small — " in text and "(your word)" in text
    assert "| M3 | ref-2 | leave | the ruled rhythm of its listing table |" in text


def test_a_reply_that_names_no_item_or_moves_one_to_take_with_no_place_keeps_the_direction_turn_open(project):
    save(project, f"direction/{TASK}.yaml", DIRECTION_PROPOSAL)
    write(project, reference_entries(project))
    reply(project)
    assert direction.owed(project, TASK, 1) is None
    reply(project, '[declared] take M99: the hero — "this one"')
    assert "names an item the digest does not list" in direction.owed(project, TASK, 1)
    reply(project, '[declared] take M2: — "keep them"')
    assert "said nothing of where it goes" in direction.owed(project, TASK, 1)
    reply(project, '[declared] take M2: the footer — "keep them"')
    assert direction.owed(project, TASK, 1) is None


def test_the_owners_replies_to_the_digest_are_not_rows_a_leave_is_held_against(project):
    """An owner's `leave M1: — "no wipe slider here"` is a requirement row of their own, and the row a later leave item of the
    run would match by its words: it is left out of the match, or the owner's own word would refuse the run's item."""
    from lapis_design import reference_digest

    write(project, reference_entries(project))
    reply(project, '[declared] leave M1: — "no wipe slider here"')
    assert all(not row["text"].startswith("leave M1") for row in reference_digest.owner_rows(project, TASK))
    assert [row["text"] for row in reference_digest.owner_rows(project, TASK)] != []


# ---- the rough's card

def test_a_card_that_names_no_take_or_one_the_digest_does_not_hold_is_refused(run):
    start(run)
    make_all(run)
    assert diverge.check(run, TASK)["problems"] == []
    leave = "M2"                                                              # the leave of ref-1, whatever the direction
    cases = [(["M99"], "names the take M99, which is no item of the reference digest"),
             ([leave], f"uses {leave}, which the digest leaves out"),
             ([], "names no take")]
    for takes, fragment in cases:
        write_rough(run, TASK, "C1", takes=takes)
        found = " | ".join(diverge.check(run, TASK)["problems"])
        assert fragment in found, (takes, found)
    write_rough(run, TASK, "C1")
    assert diverge.check(run, TASK)["problems"] == []


def test_a_card_made_before_takes_is_named_with_the_field_and_the_way_to_fix_it(run):
    start(run)
    make_all(run)
    card = run / ".lapis/diverge" / TASK / "C1" / "card.yaml"
    found = yaml.safe_load(card.read_text(encoding="utf-8"))
    found.pop("takes")
    card.write_text(yaml.safe_dump(found, sort_keys=False), encoding="utf-8")
    problems_found = " | ".join(diverge.check(run, TASK)["problems"])
    assert "'takes' is a required property" in problems_found and "references digest --task" in problems_found


# ---- the plan and the critic

def plan_for(root: Path, **change) -> dict:
    from lapis_design import reference_digest

    return {"mode": "create", "task": {"id": TASK}, "references": reference_digest.plan_entries(root, TASK), **change}


def findings(root: Path, plan: dict) -> list[str]:
    return [f["observed"] for f in plan_check.check_references(plan, root, "plan.yaml") if f["rule_id"] == "reference.digest-drift"]


def test_the_plans_references_are_the_digest_and_drift_from_it_is_blocking(project):
    write(project, reference_entries(project))
    plan = plan_for(project)
    assert len(plan["references"]) == 6 and plan["references"][0]["take"][0].startswith("M1: the ruled rhythm of its listing table")
    assert findings(project, plan) == []
    plan["references"][0]["take"] = ["M1: the ruled rhythm", "M4: a take of another reference"]
    plan["references"][1]["leave"] = []
    del plan["references"][2]
    found = " | ".join(findings(project, plan))
    assert "references[0]: `take` names M4, which ref-1 does not hold" in found
    assert "references[1]: `leave` leaves out M4 of ref-2" in found
    assert "the reference ref-3 has take items (M5) and no entry with `record_id`" in found
    assert all(f["blocking"] for f in plan_check.check_references(plan, project, "plan.yaml") if f["rule_id"] == "reference.digest-drift")


def test_what_the_owner_moved_is_what_the_plan_must_carry(project):
    write(project, reference_entries(project))
    reply(project, '[declared] leave M1: — "not this one"')
    plan = plan_for(project)
    assert [e["record_id"] for e in plan["references"]] == ["ref-2", "ref-3", "ref-4", "ref-5", "ref-6"]   # ref-1 has no take left
    stale = plan_for(project, references=[{**plan["references"][0], "record_id": "ref-1"}, *plan["references"][1:]])
    assert any("`take` names M3, which ref-1 does not hold" in f for f in findings(project, stale))


def test_a_run_without_a_digest_or_outside_create_mode_is_not_held_to_it(project):
    assert findings(project, {"mode": "create", "task": {"id": TASK}, "references": []}) == []
    write(project, reference_entries(project))
    assert findings(project, {"mode": "review", "task": {"id": TASK}, "references": []}) == []


def test_the_critic_packet_carries_take_and_leave_with_who_moved_them(tmp_path):
    make_project(tmp_path)
    packet_file = tmp_path / ".lapis/critic" / f"{TASK}.packet.json"
    refresh_critic(tmp_path)
    shown = json.loads(packet_file.read_text(encoding="utf-8"))["reference_digest"]["references"]
    assert [r["id"] for r in shown] == [f"ref-{n}" for n in range(1, 7)] and shown[0]["direction"] == "A"
    assert shown[0]["take"] == [{"id": "M1", "element": "the ruled rhythm of its listing table",
                                 "at": "the hero, under the headline", "why": "rows scan left to right", "by": "agent"}]
    assert shown[0]["leave"][0] == {"id": "M2", "what": "its type and marks", "why": "the brand's own identity", "by": "agent"}
    reply(tmp_path, '[declared] leave M1: — "not this one"')
    refresh_critic(tmp_path)
    moved = json.loads(packet_file.read_text(encoding="utf-8"))["reference_digest"]["references"][0]
    assert moved["take"] == [] and [i["id"] for i in moved["leave"]] == ["M1", "M2"] and moved["leave"][0]["by"] == "owner"


def test_next_sends_a_record_without_a_digest_back_to_the_references_with_the_migration(project):
    entries = reference_entries(project)
    for entry in entries:
        entry.pop("take"), entry.pop("leave")
    write(project, entries)
    from procedure_support import load_skills

    load_skills(project)
    result = next_step.evaluate(project, TASK)
    assert result["step"]["id"] == "references" and "has no `take` items" in result["step"]["why"]
    assert "lapis-design references digest --task kiln-shop-landing --plan" in result["step"]["why"]
