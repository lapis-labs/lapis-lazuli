"""What the owner reads in the summary: no defects of a build before one is shown, a change named by its text, and the
fixed text in the owner's language (English, or Korean in 해요체; Japanese and Chinese get English), while the delivery check
still compares the summary verbatim, against the text of that language."""
from __future__ import annotations

import string

import pytest

from lapis_design import draft, gaps, integrity, next_step, owner, waiting
from procedure_support import TASK, ask, make_project, record, reply, save, seal_requirements, update
from test_owner_block import ids, judge, project  # noqa: F401  (a finished procedure with four sealed owner rows)
from test_owner_summary import ROLES, without
from test_slice_hold import CORE, declare

KO_BRIEF = """# 브리프

- 첫 화면에서 가마 불 때기 기록을 보여 주세요.
- 계정 없이 예약할 수 있는 버튼이 있어야 해요.
- 히어로에는 가격을 넣지 마세요.
- 스톡 사진은 쓰지 마세요.
"""
JA_BRIEF = """# ブリーフ

- 最初の画面に窯の焼成記録を表示してください。
- アカウントなしで予約できるボタンが必要です。
- ヒーローに価格を入れないでください。
"""


def owned(tmp_path, monkeypatch, brief: str):
    """`project` of test_owner_block, with the owner's brief in another language."""
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    (root / "brief.md").write_text(brief, encoding="utf-8")
    seal_requirements(root, TASK, "brief.md")
    return root


@pytest.fixture
def korean(tmp_path, monkeypatch):
    return owned(tmp_path, monkeypatch, KO_BRIEF)


def unbuilt(root):
    """The fixture's finished procedure, without the critic's report on a build: nothing was shown or built yet."""
    for name in (f"{TASK}.json", f"{TASK}.packet.json"):
        (root / ".lapis" / "critic" / name).unlink(missing_ok=True)


def shown_build(root, core=True):
    update(root, f"plans/{TASK}.yaml", lambda plan: plan["tokens"]["type"].update(roles=ROLES))
    declare(root, core=[CORE] if core else [])


# ---- 1. no defects of a build before a build

def test_before_anything_is_shown_or_built_the_summary_has_no_defects_and_asks_for_none(project):
    unbuilt(project)
    assert not draft.path(project, TASK).exists()
    for kind in ("direction", "approval"):
        delivery = owner.deliver(project, TASK, {"kind": kind})
        text = delivery.summary
        assert "Defects of the build shown" not in text and "not judged" not in text and "no critic report yet" not in text
        assert not any(what == "core defect" for what, _ in delivery.required)
        assert delivery.problems(text) == []
    assert "requirements not judged: no critic report yet" in delivery.block             # the full block keeps its detail


def test_a_link_in_the_questions_is_the_agents_word_and_builds_nothing(project):
    unbuilt(project)
    ask(project, "Which headline do you prefer? Look at http://127.0.0.1:4173/slice.html", 200, kind="direction")
    delivery = owner.deliver(project, TASK, {"kind": "direction"})
    assert draft.shown(project, TASK) and "Defects of the build shown" not in delivery.summary


def test_once_the_draft_record_names_a_page_the_defects_are_back_and_required(project):
    unbuilt(project)
    declare(project)                                                     # a page in the draft record, a critic report on it
    delivery = owner.deliver(project, TASK, {"kind": "approval"})
    assert "## Defects of the build shown" in delivery.summary
    assert "- requirements, the page http://127.0.0.1:4173/slice.html: not judged 4 of 4" in delivery.summary
    line = next(line for what, line in delivery.required if what == "core defect" and line.startswith("- not judged "))
    assert delivery.problems(without(delivery.summary, line))


def test_a_draft_record_with_no_critic_report_still_says_the_rows_are_not_judged(project):
    unbuilt(project)
    save(project, f"drafts/{TASK}.yaml", {"version": 0, "task": TASK, "pages": []})
    text = owner.deliver(project, TASK, {"kind": "approval"}).summary
    assert "## Defects of the build shown" in text and "- 4 requirement rows not judged: no critic report yet." in text


def test_a_critic_report_alone_is_a_build_and_so_is_done(project):
    unbuilt(project)
    judge(project, ["met", "met", "met", "met"])
    assert "- requirements, the whole page: met 4 of 4" in owner.deliver(project, TASK, {"kind": "direction"}).summary
    bare = owner.deliver(project, TASK, {"verdict": "the release gate's report has 0 blocking findings"})
    assert "## Defects of the build shown" in bare.summary


# ---- 2. what changed, in the owner's terms

def test_a_dropped_row_is_named_by_its_words_and_theirs_never_by_its_id(project):
    first = ids(project)[0]
    reply(project, f"- [declared] {first}: narrow — \"only on the home page\"\n", 260)
    integrity.observe_task(project, TASK, "test")
    text = owner.deliver(project, TASK, {"kind": "approval"}).summary
    section = text.split("## Changed since your last word\n", 1)[1].split("\n\n", 1)[0]
    assert section == '- you narrowed: "Show the firing log on the first screen." (only on the home page)'


def test_a_few_changed_rows_are_named_by_their_text(project):
    integrity.observe(project, TASK, None, "test", extra=[
        {"pointer": "/requirements/Rabc123", "before": None, "after": "Keep the kiln photos large."},
        {"pointer": "/requirements/Rdef456", "before": "Use no stock photos.", "after": None}])
    text = owner.deliver(project, TASK, {"kind": "direction"}).summary
    section = text.split("## Changed since your last word\n", 1)[1].split("\n\n", 1)[0]
    assert section.splitlines() == ['- now in your requirements: "Keep the kiln photos large."',
                                    '- no longer in your requirements: "Use no stock photos."']


def test_many_changed_rows_are_left_out_of_the_summary_and_never_counted(project):
    integrity.observe(project, TASK, None, "test", extra=[
        {"pointer": f"/requirements/R{n:06x}", "before": None, "after": f"A requirement the owner added, number {n}."}
        for n in range(13)])
    delivery = owner.deliver(project, TASK, {"kind": "direction"})
    assert "requirement record" not in delivery.summary and "rows added or changed" not in delivery.summary
    assert "Changed since your last word" not in delivery.summary
    assert "requirement record: " in delivery.block                                      # the full block lists them


# ---- 3. the summary in the owner's language

def test_an_english_owner_gets_an_english_summary(project):
    shown_build(project)
    delivery = owner.deliver(project, TASK, {"kind": "approval"})
    lines = delivery.summary.splitlines()
    assert delivery.language == "en" and lines[0] == f"# Owner summary: {TASK}" and lines[2].startswith("Decision: ")
    assert [line for line in lines if line.startswith("## ")] == [
        "## Decisions you have not made", "## Defects of the build shown", "## Fonts and rights", "## Shown"]


def test_a_korean_owner_gets_a_korean_summary_and_the_full_block_stays_english(korean):
    shown_build(korean)
    delivery = owner.deliver(korean, TASK, {"kind": "approval"})
    text, lines = delivery.summary, delivery.summary.splitlines()
    assert delivery.language == "ko" and lines[0] == f"# 확인 요약: {TASK}"
    assert lines[2] == ("결정: 지금 만든 화면을 승인하거나, 바꿀 점을 알려 주세요. 이 답으로 아래의 정하지 않으신 결정 "
                        f"{len(gaps.compute(korean, TASK))}개와 열려 있는 핵심 지적 1개도 함께 정해져요.")
    assert "- http://127.0.0.1:4173/slice.html (390, 1440 너비에서 확인)" in text
    assert [line for line in lines if line.startswith("## ")] == [
        "## 아직 정하지 않으신 결정", "## 보여 드린 화면의 문제", "## 폰트와 사용 권리", "## 보여 드린 것"]
    assert "Decision:" not in text and "Defects of the build" not in text and "Full block:" not in text
    assert "- copy.fabricated-proof: the page shows two invented customer quotes" in text      # a record, as written
    assert "- display (latn): Futura PT Cond — 출처 contract; fonts lock에 아직 항목이 없어서 기록된 라이선스가 없어요 — 사용자의 확인이 필요해요" in text
    assert "- 요구사항, 화면 http://127.0.0.1:4173/slice.html: 아직 판단 못 함 4 (전체 4개)" in text
    assert f"전체 기록: {delivery.artifact} (" in text and lines[-1] == delivery.marker
    assert delivery.block.startswith(f"# Owner block: {TASK}") and "## Requirements: what was shown" in delivery.block
    assert waiting.question_text(f"질문이에요.\n\n{text}").strip() == "질문이에요."          # a pasted Korean summary is not words


def test_a_korean_direction_summary_before_a_build_has_no_defects_in_korean_either(korean):
    unbuilt(korean)
    delivery = owner.deliver(korean, TASK, {"kind": "direction"})
    assert delivery.summary.splitlines()[2].startswith("결정: 방향 항목에 적힌 것 중에서 고르거나 바꿔 주세요.")
    assert "보여 드린 화면의 문제" not in delivery.summary and "판단" not in delivery.summary and "아래의 정하지 않으신 결정" in delivery.summary
    assert delivery.problems(delivery.summary) == []


def test_the_korean_summary_is_held_to_its_own_text_and_a_dropped_line_is_refused(korean):
    shown_build(korean)
    delivery = owner.deliver(korean, TASK, {"kind": "approval"})
    assert delivery.problems(delivery.summary) == [] and delivery.problems(f"어느 쪽이 좋으세요?\n\n{delivery.summary}") == []
    for what in ("core gap", "core defect", "font fact"):
        line = next(line for kind, line in delivery.required if kind == what)
        problems = delivery.problems(without(delivery.summary, line))
        assert len(problems) == 1 and "drops 1 line the owner must see" in problems[0] and f"{what}: " in problems[0]
    decision = next(line for line in delivery.summary.splitlines() if line.startswith("결정:"))
    assert "exactly one `결정:` line, and this one has 0" in delivery.problems(
        without(delivery.summary, decision).replace("\n\n\n", "\n\n"))[0]
    english = delivery.summary.replace(delivery.heading, f"# Owner summary: {TASK}")
    assert "not the owner summary above it" in delivery.problems(english)[0]               # the wrong language's heading


def test_next_waits_on_the_korean_summary_and_sends_back_one_that_drops_a_line(korean):
    update(korean, f"plans/{TASK}.yaml", lambda plan: plan["tokens"]["type"].update(roles=ROLES))
    delivery = owner.deliver(korean, TASK, {"kind": "approval"})
    line = next(line for kind, line in delivery.required if kind == "core gap")
    record(korean, "questions", f"lapis-questions: approval\n어느 헤드라인이 좋으세요?\n\n{without(delivery.summary, line)}", 200)
    result = next_step.evaluate(korean, TASK)
    assert result["step"]["id"] == "draft-review" and "drops 1 line the owner must see" in result["step"]["why"]
    assert result["owner_summary"].startswith(f"# 확인 요약: {TASK}")
    record(korean, "questions", f"lapis-questions: approval\n어느 헤드라인이 좋으세요?\n\n{result['owner_summary']}", 200)
    assert next_step.evaluate(korean, TASK)["state"] == "waiting-for-user"


def test_a_japanese_owner_gets_the_english_text_the_known_limit(tmp_path, monkeypatch):
    root = owned(tmp_path, monkeypatch, JA_BRIEF)
    delivery = owner.deliver(root, TASK, {"kind": "direction"})
    assert delivery.language == "en" and delivery.summary.startswith(f"# Owner summary: {TASK}")


def test_the_two_catalogs_have_the_same_keys_and_the_same_fields():
    from lapis_design import owner_text

    fields = lambda text: {name for _, name, _, _ in string.Formatter().parse(text) if name}   # noqa: E731
    assert set(owner_text.EN) == set(owner_text.KO)
    assert {key: fields(text) for key, text in owner_text.EN.items()} == {key: fields(text) for key, text in owner_text.KO.items()}
