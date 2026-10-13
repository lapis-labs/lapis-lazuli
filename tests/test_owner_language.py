"""The questions are asked in the owner's language.

The CLI reads the request only where it holds it (the requirement record's rows, the brief record's `[declared]` items): a
Korean, Japanese, or Chinese request with a plainly Latin questions file goes back to the run, and a request with no clear
script is not checked."""
from __future__ import annotations

from pathlib import Path

import pytest

from lapis_design import direction, next_step, owner_language
from procedure_support import BRIEF_RECORD, TASK, ask, make_project, record, reply, seal_requirements
from test_question_kinds import open_item

KOREAN_REQUEST = ("# 도자기 공방 소개 페이지\n\n- 한 달에 한 번 굽는 공방의 가마 일정과 예약을 보여주는 페이지를 만들어 주세요.\n"
                  "- 방문하는 사람은 지금 남은 작품을 한눈에 보고 예약할 수 있어야 해요.\n")
JAPANESE_REQUEST = "- 月に一度だけ窯を焼く工房のために、残っている作品を一目で見て予約できるページを作ってください。\n"
ENGLISH_REQUEST = "- Build a page for a studio that fires its kiln once a month, so visitors can reserve a piece.\n"
ENGLISH_QUESTIONS = ("Before I plan, here is what I took from your request and the folder.\n\nQuestions\n"
                     "1. Who visits the kiln shop page, and what has just happened to them?\n"
                     "   Why: sets the first screen.\n   If you skip it, I assume: a buyer on a phone.\n")
KOREAN_QUESTIONS = ("계획을 세우기 전에, 요청과 폴더에서 읽은 내용을 먼저 적어요. 틀린 곳이 있으면 알려 주세요.\n\n질문\n"
                    "1. 이 페이지를 여는 사람은 누구이고, 직전에 어떤 일이 있었나요?\n"
                    "   이유: 첫 화면의 주제를 정해요.\n   건너뛰면 가정할 내용: 휴대폰으로 보는 구매자예요.\n"
                    "2. 가마 일정은 `PRODUCT.md`와 https://example.com/kiln 에 있는 대로 고정인가요?\n")


@pytest.fixture(autouse=True)
def attended(monkeypatch):
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")


def owner_file(root: Path, text: str) -> None:
    """The owner's brief file, sealed into the requirement record the way `requirements seal --from` does, after the
    first round of the brief (the record is sealed only once a brief record stands)."""
    if not (root / ".lapis/answers" / f"{TASK}.md").exists():
        record(root, "answers", BRIEF_RECORD, 100)
    (root / "BRIEF.md").write_text(text, encoding="utf-8")
    seal_requirements(root, TASK, "BRIEF.md")


def evaluated(root: Path) -> dict:
    return next_step.evaluate(root, TASK)


def refused(result: dict, language: str) -> bool:
    return result["state"] == "needs-step" and "waiting" not in result and \
        f"(kind brief) do not wait: the owner's request is in {language} and the questions are in Latin script" \
        in result["step"]["why"]


def test_a_korean_request_with_an_english_questions_file_is_sent_back(tmp_path):
    owner_file(tmp_path, KOREAN_REQUEST)
    ask(tmp_path, ENGLISH_QUESTIONS, 200)
    result = evaluated(tmp_path)
    assert refused(result, "Korean")
    assert "questions.md is a shape to fill, not text to copy" in result["step"]["why"]


def test_a_korean_questions_file_for_a_korean_request_waits(tmp_path):
    owner_file(tmp_path, KOREAN_REQUEST)
    ask(tmp_path, KOREAN_QUESTIONS, 200)
    result = evaluated(tmp_path)
    assert (result["state"], result["waiting"]["kind"], result["then"]["id"]) == ("waiting-for-user", "brief", "references")


def test_a_japanese_request_is_read_as_japanese(tmp_path):
    owner_file(tmp_path, JAPANESE_REQUEST)
    ask(tmp_path, ENGLISH_QUESTIONS, 200)
    assert refused(evaluated(tmp_path), "Japanese")


def test_the_declared_answers_of_the_brief_record_are_the_request_of_a_second_round(tmp_path):
    reply(tmp_path, "## Found\n\nPRODUCT.md read: the studio fires monthly.\n\n## Answers\n\n"
          "- [declared] Q1 누가 방문하나요? — 한 달에 한 번 굽는 공방의 단골 구매자들이 휴대폰으로 방문해요.\n", 100)
    ask(tmp_path, ENGLISH_QUESTIONS, 200)
    assert refused(evaluated(tmp_path), "Korean")
    ask(tmp_path, KOREAN_QUESTIONS, 210)
    assert evaluated(tmp_path)["state"] == "waiting-for-user"


@pytest.mark.parametrize("case, request_text", [
    ("an English request", ENGLISH_REQUEST),
    ("a request with a few Korean words among English text",
     "- Build the kiln studio page with the title 도자기 공방 and the booking flow, the firing calendar, and the price list.\n"),
    ("a request too short to have a script", "- 가마\n"),
])
def test_a_request_with_no_clear_script_is_not_checked(tmp_path, case, request_text):
    owner_file(tmp_path, request_text)
    ask(tmp_path, ENGLISH_QUESTIONS, 200)
    assert evaluated(tmp_path)["state"] == "waiting-for-user", case


def test_a_request_the_cli_does_not_hold_is_not_checked(tmp_path):
    ask(tmp_path, ENGLISH_QUESTIONS, 200)
    assert evaluated(tmp_path)["state"] == "waiting-for-user"


def test_a_questions_file_that_is_mostly_code_and_paths_is_read_by_its_words(tmp_path):
    owner_file(tmp_path, KOREAN_REQUEST)
    ask(tmp_path, "1. 가마 일정은 `kiln_schedule_final_v2` 와 src/pages/kiln/schedule.html 에 적힌 대로 고정인가요?\n"
        "2. 예약 버튼은 https://example.com/reserve/kiln/monthly 로 이동해도 되나요?\n", 200)
    assert evaluated(tmp_path)["state"] == "waiting-for-user"


def test_the_direction_questions_of_a_korean_request_are_asked_in_korean(tmp_path):
    root = make_project(tmp_path)
    (root / ".lapis/fonts.lock.json").unlink()
    item = open_item(root)
    owner_file(root, KOREAN_REQUEST)
    assert direction.asked(root, TASK) == ["G1"]                 # `item` names it, in parentheses
    ask(root, "Which of the options? " + item + "Why: it sets the opening. I assume the first option, a ledger.\n", 210,
        kind="direction")
    result = evaluated(root)
    assert result["state"] != "waiting-for-user"
    assert "do not wait: the owner's request is in Korean and the questions are in Latin script" in result["step"]["why"]
    ask(root, "어느 쪽이 더 가까운가요? " + item + " 이유: 첫 화면을 정해요. 첫 번째 안인 장부를 가정해요.\n", 220, kind="direction")
    result = evaluated(root)
    assert (result["state"], result["waiting"]["kind"]) == ("waiting-for-user", "direction")


def test_the_script_of_a_text_is_read_without_its_code_and_links():
    assert owner_language.request_language([KOREAN_REQUEST]) == "Korean"
    assert owner_language.request_language(["한국어 `very_long_identifier_in_code` https://example.com/very/long/path"]) is None
    assert owner_language.mostly_latin(ENGLISH_QUESTIONS) and not owner_language.mostly_latin(KOREAN_QUESTIONS)
    assert not owner_language.mostly_latin("lapis-questions: brief\n1. Ok?\n")          # too few letters to say
