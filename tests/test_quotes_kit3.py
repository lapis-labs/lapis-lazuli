"""`copy.fabricated-proof` and the name that follows a closing quotation mark: a name in brackets, after a middle
dot, bar, slash, comma, or blank, or after a speech verb is an attribution, so the quotation stays a lead in an
interface line; a Korean, Japanese, or Chinese letter right on the mark, or a lowercase Latin word that is not
a speech verb, is a sentence that goes on."""
from __future__ import annotations

import pytest

from lapis_design.lint.detectors import copy as copy_detector
from test_fabricated_proof_quotes import QUOTE, TYPE_ROLES, kinds
from test_lint_copy import dialog_title, doc, r


@pytest.mark.parametrize("lang, text", [
    ("en", "“Best studio ever” (Mina, Seoul)"),
    ("en", "“Best studio ever” · Mina K."),
    ("en", "“Best studio ever” Mina Kim, Seoul"),
    ("en", "“Best studio ever,” says Mina Kim"),
    ("en", "“Best studio ever,” wrote Mina Kim"),
    ("en", "“Best studio ever” / Mina Kim"),
    ("en", "“Best studio ever” | Mina Kim"),
    ("en", "“Best studio ever”, Mina Kim"),
    ("ko", "“최고의 공방이에요” 김민아 고객님"),
    ("ko", "“최고의 공방이에요” (김민아, 서울)"),
    ("ko", "“최고의 공방이에요” · 김민아"),
    ("ko", "“최고의 공방이에요” | 김민아"),
])
@pytest.mark.parametrize("role", TYPE_ROLES)
def test_a_name_after_the_closing_mark_keeps_the_quotation_a_lead_in_an_interface_line(lang, text, role):
    assert kinds(doc(("other", [r(text, role)]), lang=lang)) == [QUOTE]
    assert kinds(doc(("other", [dialog_title(role, text)]), lang=lang)) == [QUOTE]


@pytest.mark.parametrize("box_role", ["button", "input"])
def test_a_control_holding_a_quotation_and_a_bracketed_name_is_a_lead(box_role):
    extract = doc(("other", [r("“Best studio ever” (Mina, Seoul)", "ui", box_role=box_role)]))
    assert kinds(extract) == [QUOTE]


@pytest.mark.parametrize("lang, text", [
    ("ko", "“최고의 공방이에요”라는 김민아 고객님의 후기"),
    ("ko", "‘9월 소성 예약’을 취소할까요?"),
    ("ja", "「最高のスタジオ」という声をいただきました"),
    ("en", "“Best studio ever” is what Mina Kim wrote"),
    ("en", "“Best studio ever” and the shelves are full"),
    ("en", "“Best studio ever” (Mina Kim from the Seoul studio who ordered twice in a row this year)"),
])
def test_a_sentence_that_goes_on_after_the_closing_mark_is_not_a_lead_in_an_interface_line(lang, text):
    assert kinds(doc(("other", [r(text, "heading")]), lang=lang)) == []


@pytest.mark.parametrize("text, after", [
    ('"Best studio ever" (Mina, Seoul)', "attributed"),
    ('"Best studio ever" Mina Kim', "attributed"),
    ('"Best studio ever," says Mina Kim', "attributed"),
    ('"Best studio ever," said Mina', "attributed"),
    ('"Best studio ever" — mina', "attributed"),
    ('"최고예요" 김민아 고객님', "attributed"),
    ('"최고예요"라는 김민아 고객님', "continues"),
    ('"最高"という声', "continues"),
    ('"Best studio ever," she said', "continues"),
    ('"Best studio ever" is back', "continues"),
    ('"Best studio ever" 5 stars', "continues"),
    ('"Best studio ever" ★★★★★', "ends"),
    ('"Best studio ever" — ', "ends"),
    ('"Best studio ever"', "ends"),
    ('"Best studio ever', "ends"),
])
def test_after_the_closing_mark_a_line_ends_continues_or_names_someone(text, after):
    assert copy_detector._after_quotation(text) == after
