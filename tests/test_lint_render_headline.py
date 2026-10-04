"""headline-emphasis (cli/lapis_design/lint/detectors/render_type.py) and the accent-share bound of the headline
gradient rule, run through the registry with the shipped rules."""
from __future__ import annotations

from layout_support import box, extract, lint, observed, run, viewport

FORMULA = "type.headline-emphasis-formula"
ACCENT = "color.gradient-headline"
SANS = {"requested": "Inter", "rendered": "Inter"}
SERIF = {"requested": "Newsreader", "rendered": "Newsreader"}


def headline(parts, width=1440, stacked=True, size=64):
    """A headline of (text, style, font, script, color) parts: one heading box per part, one under the other,
    as the extract holds a headline broken into lines."""
    boxes, text, y = [box(1, "section", 0, 0, width, 600)], [], 80
    for k, (words, style, font, script, color) in enumerate(parts):
        n = 10 + k
        boxes.append(box(n, "heading", 72, y if stacked else 72, 640, size * 1.1, parent=1))
        extra = {"style": style, "font": font, "script": script}
        if color:
            extra["color"] = color
        text.append(run(n, n, words, "display", size, **extra))
        y += size * 1.1
    return extract(viewport(width, boxes, text))


def part(words, style="normal", font=SANS, script="latn", color=None):
    return (words, style, font, script, color)


def test_a_line_then_a_closing_phrase_in_italic_is_the_formula():
    doc = headline([part("The last"), part("impression.", style="italic")])
    hits = observed(lint(FORMULA, extract=doc))
    assert len(hits) == 1 and "heading 'The last' sets 'impression.' apart in italic" in hits[0]


def test_italic_and_a_serif_switch_are_both_named():
    doc = headline([part("Your work."), part("Safe and sound.", style="italic", font=SERIF)])
    assert "apart in italic and a second typeface (Newsreader)" in observed(lint(FORMULA, extract=doc))[0]


def test_a_second_typeface_without_italic_counts():
    doc = headline([part("Good stories."), part("At their own pace.", font=SERIF)])
    assert "apart in a second typeface (Newsreader)" in observed(lint(FORMULA, extract=doc))[0]


def test_an_italic_word_inside_the_line_counts_too():
    doc = headline([part("A calmer kind of visit.")]) if False else extract(viewport(1440, [
        box(1, "heading", 72, 80, 800, 70)], [
        run(1, 1, "Good dental care. A ", "display", 64), run(2, 1, "calmer", "display", 64, style="italic"),
        run(3, 1, " kind of visit.", "display", 64)]))
    assert "sets 'calmer' apart in italic" in observed(lint(FORMULA, extract=doc))[0]


def test_one_voice_is_left_alone():
    assert observed(lint(FORMULA, extract=headline([part("The last"), part("impression.")]))) == []


def test_a_headline_set_wholly_in_italic_is_not_a_switch():
    doc = headline([part("The last", style="italic"), part("impression.", style="italic")])
    assert observed(lint(FORMULA, extract=doc)) == []


def test_a_bilingual_title_in_two_scripts_is_not_a_typeface_switch():
    doc = headline([part("Where Light Lingers"), part("빛이 머무는 자리", font={"requested": "Inter", "rendered": "Noto Sans CJK KR"}, script="hang")])
    assert observed(lint(FORMULA, extract=doc)) == []


def test_kana_and_kanji_set_in_one_japanese_face_are_not_a_switch():
    doc = headline([part("みずのおと", script="kana", font={"requested": "x", "rendered": "Noto Serif CJK JP"}),
                    part("水の音", script="hani", font={"requested": "x", "rendered": "Noto Serif CJK JP"})])
    assert observed(lint(FORMULA, extract=doc)) == []


def test_small_headings_are_not_judged():
    doc = headline([part("The last"), part("impression.", style="italic")], size=18)
    assert observed(lint(FORMULA, extract=doc)) == []


def test_a_set_apart_part_over_the_share_bound_is_a_headline_in_two_voices_not_an_emphasis():
    doc = headline([part("Hi"), part("a much longer closing phrase in italic", style="italic")])
    assert observed(lint(FORMULA, extract=doc)) == []
    assert len(observed(lint(FORMULA, extract=doc, threshold={"emphasis_share_max": 0.99}))) == 1


# ---------------------------------------------------------------- gradient-headline, accent share

ACCENT_RED = [0.55, 0.17, 30]
INK = [0.2, 0.01, 90]


def accent_headline(lead, tail):
    return headline([part(lead, color=INK), part(tail, color=ACCENT_RED)])


def test_a_closing_phrase_in_the_accent_color_under_the_bound_is_found():
    doc = accent_headline("The last", "impression.")                      # 11 of 18 characters
    hits = observed(lint(ACCENT, extract=doc))
    assert len(hits) == 1 and "sets" in hits[0] and "apart with the accent color" in hits[0]


def test_the_old_half_bound_missed_it_and_the_rules_bound_is_the_change():
    doc = accent_headline("The last", "impression.")
    assert observed(lint(ACCENT, extract=doc, threshold={"accent_share_max": 0.5})) == []


def test_an_accent_over_most_of_the_headline_is_not_one_emphasized_part():
    doc = accent_headline("The", "last impression of the coast.")
    assert observed(lint(ACCENT, extract=doc)) == []
