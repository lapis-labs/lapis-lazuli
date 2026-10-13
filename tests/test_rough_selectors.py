"""The selectors a card names its style elements by (`rough_selectors.py`): which elements of a page's markup they match, and the
selectors it refuses to read rather than miss."""
from __future__ import annotations

import re

import pytest

from lapis_design import rough_selectors as sel

PAGE = ("<!doctype html><html lang='ko'><body><header class='hero big' id='top'><h1>Plan <b>first</b></h1><p>one</p><p>two</p>"
        "</header><div data-x='a-b' class='tw:p-4'><span class='a:b'>t</span></div><script>var a = '<b>x</b>'</script></body></html>")
TREE = sel.parse(PAGE)


def tags(selector: str) -> list[str]:
    return [node.tag for node in sel.select(TREE, selector)]


@pytest.mark.parametrize("selector, found", [
    ("h1", ["h1"]), ("header.hero.big", ["header"]), ("#top > h1", ["h1"]), ("header p + p", ["p"]), ("header p ~ p", ["p"]),
    ("header > p:last-child", ["p"]), ("p:not(:first-child)", ["p", "p"]), ("h1, span", ["h1", "span"]), ("p:nth-child(2)", ["p"]),
    ("[data-x^=a]", ["div"]), ("[data-x='a-b']", ["div"]), ("[DATA-X|=a]", ["div"]), ("[class*='big' i]", ["header"]),
    ("div [class='a:b']", ["span"]), (".a\\:b", ["span"]), (".tw\\:p-4", ["div"]), ("html", ["html"]), (":root", ["html"]),
    ("body > p", []), (".missing", []), ("h1 > p", []), ("script b", []),
    (".hero::before", ["header"]), (".hero:hover", ["header"]), ("a.hero:focus-visible::after", []),
])
def test_a_selector_matches_the_elements_it_names(selector, found):
    assert tags(selector) == found


def test_script_content_is_text_not_markup_and_an_element_reads_its_text_without_it():
    assert tags("b") == ["b"]
    assert sel.select(TREE, "h1")[0].strings() == ["Plan", "first"]
    assert sel.select(TREE, "body")[0].strings() == ["Plan", "first", "one", "two", "t"]


@pytest.mark.parametrize("selector, why", [
    ("a:has(b)", ":has is not read"), ("a:nth-of-type(2)", ":nth-of-type is not read"), ("a::foo", "::foo is not read"),
    ("a >", "ends where"), ("> a", "combinator `>`"), ("", "empty"), ("a,,b", "comma"), ("a !b", "where a selector part was expected"),
    ("p:nth-child(2n+1)", "nth-child(2n+1) is not read")])
def test_a_selector_it_cannot_read_is_an_error_and_never_a_silent_miss(selector, why):
    with pytest.raises(sel.SelectorError, match=re.escape(why)):
        sel.select(TREE, selector)


def test_markup_left_open_or_with_void_elements_still_gives_a_tree():
    tree = sel.parse("<main><img src=x><br><section class=s><h2>one<h3>two</section><p>after</main>")
    assert [n.tag for n in sel.select(tree, "main > *")] == ["img", "br", "section", "p"]
    assert [n.tag for n in sel.select(tree, ".s h3")] == ["h3"]
