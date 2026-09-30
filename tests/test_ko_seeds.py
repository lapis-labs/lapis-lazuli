"""Korean list seeds and their lexical and optional morphological matching limits.

Positives must hit their list and negatives must not; KNOWN holds limits that remain after
analyzer installation. confirmshaming is checked as a substring of a decline label.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from lapis_design.lint.detectors.copy import _Seg, _find_terms, _fold, _ko_lemmas, _sentences, _term_regex
from lapis_design.lint.types import Context

LISTS = yaml.safe_load((Path(__file__).resolve().parents[1] / "src/shared/slop/rules.yaml")
                       .read_text(encoding="utf-8"))["lists"]


def _norm(text: str) -> str:
    return " ".join(text.replace("\u2019", "'").replace("\u2018", "'").casefold().split())


def hits(key: str, text: str) -> list[str]:
    values = LISTS[key]["values"].get("ko", [])
    if key == "confirmshaming":
        return [v for v in values if _norm(v) in _norm(text)]
    out = []
    for v in values:
        rx = _term_regex(v, key == "vague_cta")
        if rx is None:
            continue
        if key == "leftover_phrases":
            for sent in _sentences(_fold(text)):
                start = next((i for i, c in enumerate(sent) if c.isalnum()), 0)
                m = rx.search(sent)
                if m and (" " in v.strip() or m.start() == start):
                    out.append(v)
        elif rx.search(_fold(text)):
            out.append(v)
    return out


CASES = {   'buzzwords': (   [   '혁신적인 방식으로 일하세요',
                         '차별화된 경험',
                         '완벽하게 맞춰 드려요',
                         '원활하게 연결돼요',
                         '끊김 없이 이어져요',
                         '차세대 결제',
                         '새로운 차원의 편안함',
                         '특별한 경험을 선사합니다',
                         '효율을 극대화하세요',
                         '업무의 게임 체인저'],
                     [   '9월 소성분, 스물네 점이 나왔어요',
                         '예약하기',
                         '유약 번호 214번 청자',
                         '주문 후 3일 안에 보내요',
                         '차를 마시는 시간',
                         '완료',
                         '게임 채널']),
    'closing_formulas': (   [   '이제 시작할 때입니다',
                                '변화해야 할 때입니다',
                                '결론적으로 좋은 선택이에요',
                                '앞으로가 기대됩니다',
                                '귀추가 주목됩니다',
                                '이제 여러분의 차례입니다'],
                            [   '주문할 때 입력해요',
                                '배송 기간은 3일이에요',
                                '결론 페이지',
                                '포인트는 구매를 확정할 때입니다',
                                '교환은 받은 날부터 7일 안에 할 수 있어요']),
    'confirmshaming': (   ['아니요, 비싸게 살게요', '혜택을 놓칠게요', '할인을 놓칠게요', '손해를 감수할게요', '혜택을 포기할게요'],
                          ['아니요, 괜찮아요', '나중에 할게요', '할인 없이 계속', '이번 도전은 포기할게요', '다음에 볼게요', '닫기']),
    'intensifiers_hedges': (   [   '그야말로 최고의 선택',
                                   '단연코 가장 빠른',
                                   '굉장히 편해요',
                                   '혁신이라고 할 수 있습니다',
                                   '필수라고 해도 과언이 아닙니다',
                                   '도움이 될 수도 있을 것 같아요',
                                   '한층 더 가벼워졌어요'],
                               ['매우 가벼워요', '정말 좋아요', '진정제 복용 안내', '가구 배치', '정말로 삭제할까요?', '진정성 있는 공방']),
    'leftover_phrases': (   ['물론입니다! 아래에 정리했어요', '도움이 되었으면 좋겠습니다', '요청하신 대로 수정했어요', '좋은 질문이에요'],
                            ['물론 반품도 돼요', '배송이 늦어질 수 있어요', '질문 게시판']),
    'placeholder_entities': (   [   '홍길동 님의 후기',
                                    '김철수 고객',
                                    '가나다라마바사',
                                    '동해물과 백두산이 마르고 닳도록',
                                    '(주)가나다',
                                    '서울시 강남구 테헤란로 123'],
                                ['테헤란로 1번 출구', '예: 010-1234-5678']),
    'significance_markers': (   [   '업계의 새로운 장을 열었습니다',
                                    '역사적인 순간',
                                    '시장의 판도가 바뀝니다',
                                    '중요한 역할을 합니다',
                                    '핵심적인 역할을 해요',
                                    '큰 의미를 갖습니다',
                                    '한 획을 긋는 제품',
                                    '전환점이 될 거예요'],
                                ['가마 온도는 1,250도예요', '판매 도구', '역할을 나눠요', '상징 로고 파일', '판도라 음악']),
    'staging_phrases': (   [   '이번 글에서는 소성 과정에 대해 알아보겠습니다',
                               '함께 살펴볼까요?',
                               '결론부터 말하자면',
                               '결론부터 말씀드리면',
                               '핵심은 바로 유약이에요',
                               '여기서 중요한 점은',
                               '이것이 바로 수제 도자기의 힘입니다'],
                           ['가마를 살펴봐요', '핵심 기능', '중요한 공지', '바로 구매']),
    'vague_attribution': (   [   '전문가들은 이렇게 말해요',
                                 '연구에 따르면 효과가 있다고 해요',
                                 '건강에 좋다고 알려져 있습니다',
                                 '과학적으로 증명된 성분',
                                 '입증된 방법'],
                             ['2024년 서울대 연구팀 보고서(12쪽)', '알림을 받아요', '전문 상담', '많은 연구자들이 찾는 공방']),
    'vague_cta': (   ['제출', '제출하기', '계속', '클릭하세요', '자세한 내용은 여기를 클릭하세요', '바로가기', '→ 계속'],
                     [   '예약하기',
                         '청자 잔 예약하기',
                         '다음 소성 알림 받기',
                         '계속 쇼핑하기',
                         '장바구니로 계속',
                         '제출 서류 보기',
                         '알림을 껐어요',
                         '주문 내역 바로가기로 이동',
                         '다음',
                         '다음으로',
                         '이전',
                         '확인',
                         '취소',
                         '닫기',
                         '결제하기',
                         '배송지 저장',
                         '로그인',
                         '회원가입',
                         '장바구니 담기',
                         '더 보기'])}

KNOWN = {   'buzzwords': ['원활한 서비스 이용을 위해'],
    'placeholder_entities': ['김철수선 공방', '김철수 기자', '예) 홍길동'],
    'significance_markers': ['역사적 배경']}
ANALYZER_FIXED = ('placeholder_entities', '홍길동전 읽기')

POSITIVE = [(k, t) for k, (pos, _) in CASES.items() for t in pos]
NEGATIVE = [(k, t) for k, (_, neg) in CASES.items() for t in neg]


@pytest.mark.parametrize("key,text", POSITIVE)
def test_korean_value_hits(key, text):
    assert hits(key, text), f"{key} should match {text!r}"


@pytest.mark.parametrize("key,text", NEGATIVE)
def test_korean_value_does_not_hit(key, text):
    assert not hits(key, text), f"{key} should not match {text!r}: {hits(key, text)}"


@pytest.mark.parametrize("key,text", [(k, t) for k, ts in KNOWN.items() for t in ts])
def test_known_limits_that_remain_with_or_without_an_analyzer(key, text):
    assert hits(key, text)


def test_lexical_limit_without_an_analyzer():
    assert hits(*ANALYZER_FIXED)


@pytest.mark.cjk
def test_analyzer_excludes_an_embedded_placeholder_name():
    key, text = ANALYZER_FIXED
    ctx = Context(rules={"lists": LISTS})
    segment = _Seg(text, "ko", "hang", {"path": "content.key_copy[0].text"}, "plan headline")
    matches, _, _ = _find_terms(ctx, [segment], key)
    assert matches == []


@pytest.mark.cjk
@pytest.mark.parametrize("key,text", [(k, t) for k, (positives, _) in CASES.items()
                                      if k not in ("confirmshaming", "leftover_phrases")
                                      for t in positives])
def test_analyzer_keeps_all_positive_seed_matches(key, text):
    ctx = Context(rules={"lists": LISTS})
    segment = _Seg(text, "ko", "hang", {"path": "content.key_copy[0].text"}, "plan headline")
    matches, _, unjudged = _find_terms(ctx, [segment], key, whole=key == "vague_cta")
    assert not unjudged
    assert matches, f"{key} should match {text!r} with the analyzer"


@pytest.mark.cjk
@pytest.mark.parametrize("key,text", [(k, t) for k, (_, negatives) in CASES.items()
                                      if k not in ("confirmshaming", "leftover_phrases")
                                      for t in negatives])
def test_analyzer_keeps_all_negative_seed_matches_out(key, text):
    ctx = Context(rules={"lists": LISTS})
    segment = _Seg(text, "ko", "hang", {"path": "content.key_copy[0].text"}, "plan headline")
    matches, _, unjudged = _find_terms(ctx, [segment], key, whole=key == "vague_cta")
    assert not unjudged
    assert not matches, f"{key} should not match {text!r} with the analyzer: {matches}"


@pytest.mark.cjk
def test_korean_lemma_and_word_matching_count_one_span_once():
    ctx = Context(rules={"lists": {"verb": {"values": {"ko": ["새 역사를 쓰다"]}}}})
    segment = _Seg("새 역사를 쓰다 새 역사를 쓸", "ko", "hang",
                   {"path": "content.key_copy[0].text"}, "plan headline")
    matches, _, _ = _find_terms(ctx, [segment], "verb")
    assert [match.text for match in matches] == ["새 역사를 쓰다", "새 역사를 쓸"]


@pytest.mark.cjk
@pytest.mark.parametrize("key,text", [
    ("confirmshaming", "혜택을 놓치지 마세요"),
    ("intensifiers_hedges", "엄청난"),
])
def test_korean_list_does_not_infer_non_dictionary_endings(key, text):
    ctx = Context(rules={"lists": LISTS})
    segment = _Seg(text, "ko", "hang", {"path": "content.key_copy[0].text"}, "plan headline")
    matches, _, _ = _find_terms(ctx, [segment], key)
    assert matches == []


@pytest.mark.cjk
@pytest.mark.parametrize("text,count", [
    ("…새 역사를 쓰다", 1),
    ("㈜새 역사를 쓰다", 1),
    ("새 역사를 쓰다… 새 역사를 쓰다", 2),
])
def test_korean_lemma_and_word_matching_share_spans_after_nfkc_expansion(text, count):
    ctx = Context(rules={"lists": {"verb": {"values": {"ko": ["새 역사를 쓰다"]}}}})
    segment = _Seg(text, "ko", "hang", {"path": "content.key_copy[0].text"}, "plan headline")
    matches, _, _ = _find_terms(ctx, [segment], "verb")
    assert len(matches) == count
    assert len(_ko_lemmas(ctx, segment, "새 역사를 쓰다") or []) == count


@pytest.mark.cjk
def test_korean_distinct_terms_do_not_double_count_the_same_span():
    ctx = Context(rules={"lists": {"verb": {"values": {"ko": ["보다", "~보다"]}}}})
    segment = _Seg("보다", "ko", "hang", {"path": "content.key_copy[0].text"}, "plan headline")
    matches, _, _ = _find_terms(ctx, [segment], "verb")
    assert len(matches) == 1
