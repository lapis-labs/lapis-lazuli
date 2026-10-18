"""What a rough carries of the owner's declared words (`rough_carries.py`): the families it renders in, the motion the brief
asks for, and the elements that carry the style answers. Roughs, cards, and renders are the files an agent and `render check`
leave (`diverge_support.py`); the CLI reads them as it reads real ones."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
import yaml

from diverge_support import FACES, card_for, inventory, write_brief, write_motion, write_render, write_rough
from lapis_design import direction, diverge, rough_carries
from procedure_support import (BRIEF_RECORD, DIRECTION_PROPOSAL, TASK, load_skills, record, save, seal_requirements,
                               write_references)

STYLE = {"id": "S1", "name": "neo-brutalism", "default": "a",
         "options": [{"id": "a", "text": "expose the record: every block shows its raw text"},
                     {"id": "b", "text": "collision: display words break the grid on purpose"}],
         "kit": [{"id": "K1", "item": "full-bleed slabs with drawn line fields", "seen_in": ["ref-1"], "default": "keep", "why": "they carry the plugins"},
                 {"id": "K2", "item": "ticker band between slabs", "seen_in": ["ref-2"], "default": "drop", "why": "it moves without information"}]}
PROPOSAL = {**DIRECTION_PROPOSAL, "styles": [STYLE]}
STYLE_ANSWERS = ('- [declared] S1 neo-brutalism: a — "raw, like the log"\n- [declared] K1 full-bleed slabs: keep — "yes"\n'
                 '- [declared] K2 ticker band: drop — "no ticker"\n- [declared] O1 the monthly firing log: all — "both"\n')
LOCKED = "Dinamo Prismatica"                         # a family in neither the inventory nor the fixtures' lock


@pytest.fixture(autouse=True)
def attended(monkeypatch):
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def db(tmp_path_factory, monkeypatch) -> Path:
    """The lazuli inventory of the machine: the two families of the fixtures and ABC Favorit, and one system face."""
    path = inventory(tmp_path_factory.mktemp("inventory") / "lazuli.db", *FACES.values(), "ABC Favorit", system=("Arial",))
    monkeypatch.setenv("LAZULI_DB", str(path))
    return path


def conversation(root: Path, words: str = "", direction: str = STYLE_ANSWERS) -> None:
    """The brief record with `words` as owner answers before the direction turn, and the first turn's `direction` lines."""
    record(root, "answers", BRIEF_RECORD + words + f"\n## Direction 1\n\n{direction}", 50)


@pytest.fixture
def run(tmp_path, db) -> Path:
    """A create run that has its references and a first turn answered (the style, a kit item kept, one dropped), no rough yet."""
    record(tmp_path, "answers", BRIEF_RECORD, 50)
    seal_requirements(tmp_path)
    load_skills(tmp_path)
    write_references(tmp_path)
    shutil.rmtree(tmp_path / ".lapis/state/diverge")
    shutil.rmtree(tmp_path / ".lapis/diverge")
    save(tmp_path, f"direction/{TASK}.yaml", PROPOSAL)
    conversation(tmp_path)
    return tmp_path


def make(root: Path, **cards) -> None:
    """Draw two roughs and make each as the agent does; `cards` are changes to a candidate's card (`C1={...}`)."""
    diverge.start(root, TASK, 2, entropy="e1")
    for candidate in diverge.candidate_ids(root, TASK):
        write_rough(root, TASK, candidate, **cards.get(candidate, {}))


def render(root: Path, candidate: str, **fonts: str) -> None:
    """The render of `candidate` again, with the families that painted its headline and body."""
    stance = diverge.effective(diverge.draw_records(root, TASK))[candidate]["color"]["item"]
    write_render(root, TASK, candidate, stance, int(candidate[1:]), fonts={**FACES, **fonts})


def problems(root: Path) -> str:
    return " | ".join(diverge.check(root, TASK)["problems"])


def with_type(candidate: str, headline: dict, body: dict | None = None, answers: str | None = None) -> dict:
    return {candidate: {"type": {"headline": headline, "body": body or {"family": FACES["body"]},
                                 **({"answers": answers} if answers else {})}}}


# ---- 1. type

def test_a_rough_that_renders_in_the_system_default_is_refused_and_the_render_is_what_counts(run):
    make(run)
    assert problems(run) == ""
    render(run, "C1", headline=".SF NS", body="Menlo")                      # the stack the agent left: -apple-system, ui-monospace
    render(run, "C2", headline="Helvetica")
    found = problems(run)
    assert "C1's headline renders 100% of its text in a system default, .SF NS (100%), not in Gowun Batang" in found
    assert "C1's body renders 100% of its text in a system default, Menlo (100%)" in found
    assert "C2's headline renders 100% of its text in a system default, Helvetica" in found and "C2's body" not in found
    render(run, "C2", headline="Roboto")
    assert "system default, Roboto" in problems(run)
    with pytest.raises(diverge.DivergeError, match="cannot be sealed"):
        diverge.seal(run, TASK)


def test_a_generic_keyword_is_a_system_default_as_the_system_fonts_table_has_it(run):
    make(run)
    for name in ("system-ui", "sans-serif", "-apple-system", "BlinkMacSystemFont", "ui-monospace", "SF Pro", "Segoe UI"):
        assert rough_carries.is_system(name), name
    assert not rough_carries.is_system("ABC Favorit") and not rough_carries.is_system("Pretendard")


def test_a_rough_in_an_inventory_family_that_matches_its_card_passes_and_a_mismatch_or_a_missing_family_does_not(run):
    make(run, **with_type("C1", {"family": "ABC Favorit"}))
    render(run, "C1", headline="ABC Favorit")                                # installed, in the inventory, not in a lock
    assert problems(run) == ""
    render(run, "C1", headline="Pretendard")                                 # the render shows another family than the card
    assert "C1's headline renders in Pretendard and its card names ABC Favorit" in problems(run)
    make_missing = with_type("C2", {"family": LOCKED})
    write_rough(run, TASK, "C2", **make_missing["C2"])
    render(run, "C2", headline=LOCKED)
    found = problems(run)
    assert f"C2's headline: {LOCKED} is not installed" in found and "has no such family" in found


def test_a_family_the_run_fetched_with_a_lock_entry_passes_without_an_inventory(run, monkeypatch, tmp_path):
    make(run, **with_type("C1", {"family": LOCKED}), **with_type("C2", {"family": LOCKED}))
    for candidate in ("C1", "C2"):
        render(run, candidate, headline=LOCKED)
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "none.db"))               # a machine that never scanned its fonts
    found = problems(run)
    assert f"{LOCKED} is not in .lapis/fonts.lock.json, and lazuli has no font inventory" in found
    save(run, "fonts.lock.json", {"version": 0, "fonts": [{"family": LOCKED, "role": "heading"}, {"family": FACES["body"], "role": "body"}]})
    assert problems(run) == ""


def test_the_system_face_is_chosen_only_by_quoting_an_owner_declared_line_that_asks_for_it(run):
    conversation(run, '- [declared] Q9 Which type? - 시스템 서체로 해줘. Basis: the user.\n- [declared] Q8 Palette? - warm clay\n')
    said = "the owner asked for the system face, so the headline stays in it and the body in the locked sans"
    make(run, **with_type("C1", {"family": "system-ui", "system_asked_by": "시스템 서체로 해줘"}, answers=said),
         **with_type("C2", {"family": "system-ui"}, answers=said))
    render(run, "C1", headline=".SF NS")
    render(run, "C2", headline=".SF NS")
    found = problems(run)
    assert "C1's headline" not in found                                      # asked for, quoted, and rendered as asked
    assert "C2's headline names system-ui, a system face, with no owner `[declared]` line that asks for it" in found
    write_rough(run, TASK, "C2", **with_type("C2", {"family": "system-ui", "system_asked_by": "warm clay"}, answers=said)["C2"])
    render(run, "C2", headline=".SF NS")
    assert "does not ask for a system face" in problems(run)
    write_rough(run, TASK, "C2", **with_type("C2", {"family": "system-ui", "system_asked_by": "시스템 폰트를 쓰지 마"}, answers=said)["C2"])
    render(run, "C2", headline=".SF NS")
    assert "is in no `[declared]` line of the brief record" in problems(run)
    write_rough(run, TASK, "C2", **with_type("C2", {"family": "system-ui", "system_asked_by": "시스템 서체로 해줘"}, answers=said)["C2"])
    render(run, "C2", headline=".SF NS")
    assert problems(run) == ""
    render(run, "C2", headline="Pretendard")                                 # it said system and the render shows a chosen face
    assert "says the system face system-ui and the render shows Pretendard" in problems(run)


def test_a_card_says_how_its_type_answers_the_families_or_classes_the_owner_named(run):
    make(run)
    assert problems(run) == ""                                               # nothing about type in the owner's words so far
    conversation(run, '- [declared] Q9 Type? - 헤드라인은 지오메트릭 산세리프로, DINAMO 서체 trial을 써도 좋아\n')
    diverge.contract(run, TASK)
    found = problems(run)
    assert found.count("does not say how its type answers the owner's own words about type") == 2 and "산세리프" in found
    write_rough(run, TASK, "C1", type={"headline": {"family": FACES["headline"]}, "body": {"family": FACES["body"]},
                                       "answers": "a geometric sans headline is not installed here, so the locked serif stands in until DINAMO is bought"})
    assert "C1's card does not say" not in problems(run) and "C2's card does not say" in problems(run)
    taste = run / ".lapis" / "taste.md"
    taste.write_text("# Taste\nGiven by: the user\n\n## Likes\n- Söhne Breit and a slab serif\n", encoding="utf-8")
    conversation(run)                                                        # the answers say nothing of type now; the taste does
    assert "does not say how its type answers" in problems(run)


def test_the_render_without_a_headline_or_body_cannot_be_read_and_says_so(run):
    make(run)
    extract = diverge.extract_path(run, TASK, "C1")
    document = json.loads(extract.read_text(encoding="utf-8"))
    for view in document["viewports"]:
        view["text"] = [r for r in view["text"] if r["type_role"] != "body"]
    extract.write_text(json.dumps(document), encoding="utf-8")
    assert "C1's body has no body text in its render" in problems(run)


def test_a_card_made_before_type_and_style_is_named_with_the_migration(run):
    make(run)
    path = diverge.folder(run, TASK) / "C1" / "card.yaml"
    old = {k: v for k, v in yaml.safe_load(path.read_text(encoding="utf-8")).items() if k not in ("type", "style")}
    path.write_text(yaml.safe_dump(old, sort_keys=False), encoding="utf-8")
    found = problems(run)
    assert "card.schema.yaml" in found and "'style' is a required property" in found and "a card made before `type` and `style`" in found


# ---- 2. motion

def test_motion_none_is_refused_at_the_contract_when_the_owner_asked_for_motion(run):
    diverge.start(run, TASK, 2, entropy="e1")
    brief = diverge.brief_path(run, TASK)
    for words in ('- [declared] Q9 Feel? - kinetic type, motion-led\n', '- [declared] Q9 Feel? - 모션 위주, 그런지\n',
                  '- [declared] Q9 Feel? - アニメーションで動く\n'):
        conversation(run, words)
        write_brief(run, TASK, motion="none")
        found = diverge.contract(run, TASK)["problems"]
        assert any("motion is none, and the owner's words ask for it" in p for p in found), words
        assert not diverge.contract_passed(run, TASK)
        write_brief(run, TASK, motion="required", motion_moves="the headline letters shift weight and a band scrolls under it")
        assert diverge.contract(run, TASK)["problems"] == [] and diverge.contract_passed(run, TASK)
    conversation(run, '- [declared] Q9 Mood? - an emotional, quiet page\n')           # "emotional" holds "motion" and asks for none
    write_brief(run, TASK, motion="none")
    assert diverge.contract(run, TASK)["problems"] == []
    assert brief.is_file()


def test_the_taste_a_kept_style_and_a_signature_element_ask_for_motion_too(run):
    diverge.start(run, TASK, 2, entropy="e1")
    (run / ".lapis" / "taste.md").write_text("# Taste\nGiven by: the user\n\n## Likes\n- keep it still\n\n## Avoid\n- motion\n",
                                             encoding="utf-8")
    write_brief(run, TASK, motion="none")
    assert diverge.contract(run, TASK)["problems"] == []                                # an avoided motion is no ask
    (run / ".lapis" / "taste.md").write_text("# Taste\nGiven by: the user\n\n## Feel\n모션 위주\n", encoding="utf-8")
    assert any("taste.md (feel)" in p for p in diverge.contract(run, TASK)["problems"])
    (run / ".lapis" / "taste.md").unlink()
    save(run, f"direction/{TASK}.yaml", {**PROPOSAL, "styles": [{**STYLE, "name": "kinetic typography"}]})
    assert any("direction item S1" in p for p in diverge.contract(run, TASK)["problems"])
    save(run, f"direction/{TASK}.yaml", {**PROPOSAL, "signature": [{"id": "G1", "element": "procedure animation", "default": "a",
                                                                    "options": [{"id": "a", "text": "which step is current"}]}]})
    conversation(run, direction=STYLE_ANSWERS + '- [declared] G1 procedure animation: a — "good"\n')
    assert any("signature item G1" in p for p in diverge.contract(run, TASK)["problems"])


def test_motion_none_stands_against_the_owner_words_only_with_their_declared_line_that_asks_for_stillness(run):
    diverge.start(run, TASK, 2, entropy="e1")
    conversation(run, '- [declared] Q9 Feel? - 모션 위주\n- [declared] Q8 Any limit? - no animation on the page, it must be still\n')
    write_brief(run, TASK, motion="none", motion_still_by="no animation on the page, it must be still")
    assert diverge.contract(run, TASK)["problems"] == []
    write_brief(run, TASK, motion="none", motion_still_by="모션 위주")
    assert "which asks for no stillness" in " ".join(diverge.contract(run, TASK)["problems"])
    write_brief(run, TASK, motion="none", motion_still_by="never any movement at all")
    assert "is in no `[declared]` line" in " ".join(diverge.contract(run, TASK)["problems"])


def test_a_brief_made_before_motion_is_refused_with_the_migration_and_a_required_one_says_what_moves(run):
    diverge.start(run, TASK, 2, entropy="e1")
    write_brief(run, TASK)
    old = {k: v for k, v in yaml.safe_load(diverge.brief_path(run, TASK).read_text(encoding="utf-8")).items() if k != "motion"}
    diverge.brief_path(run, TASK).write_text(yaml.safe_dump(old, sort_keys=False), encoding="utf-8")
    found = " ".join(diverge.contract(run, TASK)["problems"])
    assert "'motion' is a required property" in found and "a brief made before `motion` needs it" in found
    diverge.brief_path(run, TASK).write_text(yaml.safe_dump({**old, "motion": "required"}, sort_keys=False), encoding="utf-8")
    assert "'motion_moves' is a required property" in " ".join(diverge.contract(run, TASK)["problems"])


def test_a_rough_with_no_motion_capture_is_refused_when_motion_is_required_and_passes_with_one_that_shows_change(run):
    conversation(run, '- [declared] Q9 Feel? - kinetic type\n')
    make(run)                                                                # the brief asks for motion; the fixtures capture it
    assert diverge.brief(run, TASK)["motion"] == "required" and problems(run) == ""
    manifest = run / ".lapis" / "renders" / f"{TASK}-C2.motion.json"
    manifest.unlink()
    found = problems(run)
    assert "C2 has no motion capture, and the shared brief requires motion" in found
    assert f"lapis-design render motion .lapis/diverge/{TASK}/C2/index.html --task {TASK}-C2" in found and "C1 has no motion" not in found
    write_motion(run, TASK, "C2", moving=False)                              # captured, and the page stood still
    assert "C2's motion capture shows no change" in problems(run) and "0.00% of their pixels at most" in problems(run)
    write_motion(run, TASK, "C2")
    assert problems(run) == ""
    rough = diverge.folder(run, TASK) / "C2" / "index.html"
    later = manifest.stat().st_mtime + 10
    os.utime(rough, (later, later))
    assert "C2's motion capture is older than its index.html" in problems(run)


def test_a_rough_needs_no_motion_capture_when_the_brief_says_none(run):
    make(run)
    assert diverge.brief(run, TASK)["motion"] == "none" and problems(run) == ""
    assert not (run / ".lapis" / "renders" / f"{TASK}-C1.motion.json").exists()


# ---- 3. style answers

def test_a_style_item_the_card_leaves_out_is_refused_and_so_is_a_dropped_or_unknown_one(run):
    make(run)
    assert [i["id"] for i in rough_carries.style_items(run, TASK, {})] == ["S1", "K1"]       # K2 was dropped
    card = card_for(run, TASK, "C1")
    assert [r["id"] for r in card["style"]] == ["S1", "K1"] and problems(run) == ""
    write_rough(run, TASK, "C1", style=card["style"][:1])
    assert "C1's card leaves out K1 (full-bleed slabs with drawn line fields), which the owner answered at the first direction turn" in problems(run)
    write_rough(run, TASK, "C1", style=[*card["style"], {**card["style"][0], "id": "K2"}])
    assert "C1's card maps K2, which the owner dropped" in problems(run)
    write_rough(run, TASK, "C1", style=[*card["style"], {**card["style"][0], "id": "K7"}])
    assert "maps K7, which is no style item the owner answered" in problems(run)
    write_rough(run, TASK, "C1", style=[*card["style"], card["style"][0]])
    assert "C1's card maps S1 twice" in problems(run)
    write_rough(run, TASK, "C1", style=[{k: v for k, v in card["style"][0].items() if k != "shown"}, *card["style"][1:]])
    assert "card.schema.yaml" in problems(run) and "'shown' is a required property" in problems(run)


def test_a_selector_that_matches_nothing_in_the_roughs_markup_is_refused(run):
    make(run)
    card = card_for(run, TASK, "C1")
    for selector, text in ((".hero-marquee", "matches no element of C1's index.html"), ("section > .band", "matches no element"),
                           ("h1:has(b)", "cannot be read: :has is not read"), ("", "card.schema.yaml")):
        write_rough(run, TASK, "C1", style=[{**card["style"][0], "selector": selector}, card["style"][1]])
        assert text in problems(run), selector
    write_rough(run, TASK, "C1", style=[{**card["style"][0], "selector": "main > h1, .not-there"}, card["style"][1]])
    assert problems(run) == ""                                               # a list matches when any of it does


def test_a_capture_the_card_says_shows_an_element_has_to_hold_its_text(run):
    make(run)
    card = card_for(run, TASK, "C1")
    extract = diverge.extract_path(run, TASK, "C1")
    document = json.loads(extract.read_text(encoding="utf-8"))
    document["viewports"][1]["text"] = [r for r in document["viewports"][1]["text"] if r["type_role"] != "heading"]
    document["viewports"][1]["text"].append({**document["viewports"][0]["text"][1], "text": "elsewhere"})
    extract.write_text(json.dumps(document), encoding="utf-8")
    assert document["viewports"][1]["width"] == 390
    found = problems(run)
    assert "C1's card says the 390 capture shows S1 (`h1`), and that render has none of the element's text" in found
    write_rough(run, TASK, "C1", style=[{**r, "shown": [1440]} for r in card["style"]])
    extract.write_text(json.dumps(document), encoding="utf-8")
    assert "the 390 capture shows" not in problems(run)
    write_rough(run, TASK, "C1", style=[{**r, "shown": []} for r in card["style"]])
    assert "the 390 capture shows" not in problems(run)                      # claimed, not shown: the owner is told, nothing is refused


def test_the_owner_block_lists_the_items_carried_and_shown_and_the_items_claimed_but_not_shown_per_rough(run):
    make(run)
    card = card_for(run, TASK, "C1")
    write_rough(run, TASK, "C1", style=[card["style"][0], {**card["style"][1], "selector": ".s0", "shown": []}],
                type={"headline": {"family": FACES["headline"]}, "body": {"family": FACES["body"]}})
    assert problems(run) == ""
    diverge.seal(run, TASK)
    lines = diverge.owner_lines(run, TASK)
    c1 = next(line for line in lines if line.startswith("- Rough C1 style items"))
    c2 = next(line for line in lines if line.startswith("- Rough C2 style items"))
    assert "carried and shown: S1 `h1` (1440, 390)" in c1 and "claimed, not shown: K1 `.s0`" in c1
    assert "carried and shown: S1 `h1` (1440, 390); K1 `h1` (1440, 390)" in c2 and "claimed" not in c2
    assert f"- Rough C1 type, as rendered: headline {FACES['headline']}, body {FACES['body']}" in lines


def test_the_owner_block_names_the_type_answer_and_an_item_a_changed_card_no_longer_carries(run):
    conversation(run, '- [declared] Q9 Type? - 지오메트릭 산세리프로\n')
    answer = "geometric sans is not installed, so the locked humanist serif stands in for the owner's headline"
    make(run, **{c: {"type": {"headline": {"family": FACES["headline"]}, "body": {"family": FACES["body"]}, "answers": answer}}
                 for c in ("C1", "C2")})
    assert problems(run) == ""
    diverge.seal(run, TASK)
    assert any(f'answers the owner\'s type words: "{answer}"' in line for line in diverge.owner_lines(run, TASK))
    path = diverge.folder(run, TASK) / "C1" / "card.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["style"] = document["style"][:1]
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert any("not on the card: K1" in line for line in diverge.owner_lines(run, TASK))


def test_the_pick_question_tells_the_run_to_carry_each_roughs_shown_and_claimed_items(run):
    make(run)
    diverge.seal(run, TASK)
    owed = direction.owed(run, TASK, 2)
    assert "`Rough first views` section lists, per rough, the faces its headline and body render in" in owed
    assert "claimed, not shown" in owed and "paste it into the question unchanged" in owed


def sealed_with_a_claimed_item(run: Path) -> None:
    make(run)
    card = card_for(run, TASK, "C1")
    write_rough(run, TASK, "C1", style=[card["style"][0], {**card["style"][1], "selector": ".s0", "shown": []}],
                type={"headline": {"family": FACES["headline"]}, "body": {"family": FACES["body"]}})
    assert problems(run) == ""
    diverge.seal(run, TASK)


def test_the_summary_of_the_pick_question_carries_the_rough_views_and_the_questions_must_paste_them(run):
    from lapis_design import owner

    sealed_with_a_claimed_item(run)
    shown = owner.delivery(run, TASK, {"kind": "direction"})
    assert "## Rough first views" in shown.summary and "- Rough C1 style items" in shown.summary
    assert "claimed, not shown: K1 `.s0`" in shown.summary and "- Rough C2 type, as rendered: headline" in shown.summary
    assert shown.problems(shown.summary) == []
    cut = shown.summary.replace(next(l for l in shown.summary.splitlines() if l.startswith("- Rough C1 style items")), "")
    assert any("rough first view: - Rough C1 style items" in p for p in shown.problems(cut))
    assert "Rough first views" not in owner.delivery(run, TASK, {"kind": "approval"}).summary      # only the pick reads them
    assert "Rough first views" not in owner.delivery(run, TASK, {}).summary


def test_the_rough_views_of_the_summary_are_in_the_owners_language(run, monkeypatch):
    from lapis_design import owner, owner_text

    sealed_with_a_claimed_item(run)
    monkeypatch.setattr(owner_text, "language", lambda root, task: "ko")
    shown = owner.delivery(run, TASK, {"kind": "direction"})
    assert "## 러프 첫 화면" in shown.summary and "- 러프 C1 스타일 항목, 담고 보여 주는 것:" in shown.summary
    assert "카드에는 있지만 캡처에 안 보이는 것: K1 `.s0`" in shown.summary
    assert f"- 러프 C1 글자(화면에 그려진 대로): 제목 {FACES['headline']}, 본문 {FACES['body']}" in shown.summary
    assert "Rough C1" not in shown.summary and shown.problems(shown.summary) == []
    assert "- Rough C1 style items" in shown.block                                          # the full block stays English
