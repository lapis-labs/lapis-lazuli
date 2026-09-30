"""`copy.fabricated-proof` on lines that open with a quotation mark: which interface lines are not a customer quote.

Only a sentence that carries on after the closing mark (‘9월 소성 예약’을 취소할까요?) and a button or input are
not. A line that is only a quotation stays a lead in a heading, display run, label, UI line, or dialog, with or
without a dash and a name after it, and nothing is left out inside a testimonial section."""
from __future__ import annotations

import pytest

from test_lint_copy import dialog_title, doc, lint, r

QUOTE = "testimonial quotation"
ATTRIBUTION = "customer attribution"
TYPE_ROLES = ["heading", "display", "label", "ui"]


def kinds(extract: dict) -> list[str]:
    return sorted(h.observed.split(" in the ")[0] for h in lint("copy.fabricated-proof", extract=extract).hits)


# ---------------------------------------------------------------- what stays a lead

@pytest.mark.parametrize("role", TYPE_ROLES)
def test_a_quotation_and_a_name_in_a_heading_display_label_or_ui_line_is_a_lead(role):
    extract = doc(("other", [r("“Best studio ever” — Mina", role)]))
    assert kinds(extract) == [QUOTE]


@pytest.mark.parametrize("role", TYPE_ROLES)
def test_a_quotation_alone_in_a_heading_display_label_or_ui_line_is_a_lead(role):
    extract = doc(("other", [r("“Best studio ever”", role, box_role="text")]))
    assert kinds(extract) == [QUOTE]


@pytest.mark.parametrize("role", ["heading", "body"])
@pytest.mark.parametrize("text", ["“Best studio ever” — Mina", "“Best studio ever”"])
def test_a_quotation_alone_in_a_dialog_is_a_lead(role, text):
    extract = doc(("other", [dialog_title(role, text)]))
    assert kinds(extract) == [QUOTE]


@pytest.mark.parametrize("box_role", ["button", "input"])
def test_a_control_holding_a_quotation_is_a_lead_only_with_a_dash_and_a_name(box_role):
    with_name = doc(("other", [r("“Best studio ever” — Mina", "ui", box_role=box_role)]))
    assert kinds(with_name) == [QUOTE]
    alone = doc(("other", [r("“Best studio ever”", "ui", box_role=box_role)]))
    assert kinds(alone) == []


def test_a_large_quotation_and_its_customer_line_in_a_testimonial_section_are_leads():
    extract = doc(("testimonial", [r("“도자기가 이렇게 따뜻할 줄 몰랐어요”", "display"), r("— 김민아 고객님", "caption")]),
                  lang="ko")
    assert kinds(extract) == [ATTRIBUTION, QUOTE]


@pytest.mark.parametrize("role", TYPE_ROLES)
def test_nothing_is_left_out_of_a_testimonial_section(role):
    sentence = doc(("testimonial", [r("“Blue Celadon” is back for September", role)]))
    assert kinds(sentence) == [QUOTE]
    in_dialog = doc(("testimonial", [dialog_title(role, "“Blue Celadon” is back for September")]))
    assert kinds(in_dialog) == [QUOTE]


def test_a_single_quote_inside_a_word_does_not_close_the_quotation():
    extract = doc(("other", [r("‘I’ve never owned better bowls’ — Mina", "heading")]))
    assert kinds(extract) == [QUOTE]


@pytest.mark.parametrize("text", ["“Best studio ever — Mina", "“Best studio ever” —", "「最高のスタジオ」 — ミナ"])
def test_an_unclosed_bare_dash_or_bracketed_quotation_is_a_lead(text):
    assert kinds(doc(("other", [r(text, "heading")]))) == [QUOTE]


# ---------------------------------------------------------------- what is not a quote

@pytest.mark.parametrize("role", TYPE_ROLES)
@pytest.mark.parametrize("text", [
    "‘9월 소성 예약’을 취소할까요?",
    "“Blue Celadon” is back for September",
    "‘Chef’s special’ is back for September",
    "«Blue Celadon» est de retour en septembre",
])
def test_an_interface_sentence_that_goes_on_after_the_quotation_is_not_a_lead(role, text):
    assert kinds(doc(("other", [r(text, role), r("Firing closes Sept 20", "caption")]))) == []
    assert kinds(doc(("other", [dialog_title(role, text), r("Close", "ui")]))) == []


def test_a_quotation_that_goes_on_in_running_copy_outside_a_dialog_is_still_a_lead():
    extract = doc(("other", [r("“Blue Celadon” is back for September, and the shelves are full", "body")]))
    assert kinds(extract) == [QUOTE]
