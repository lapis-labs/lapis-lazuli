"""Optional morphology adapters return original-text spans and dictionary lemmas."""
from __future__ import annotations

import pytest

from lapis_design.lint import morph


def test_unsupported_locale_has_no_analyzer():
    assert morph.tokens("Kiln shop", "en") is None


@pytest.mark.cjk
@pytest.mark.parametrize("locale,text,surface,lemma", [
    ("ko", "판도를 바꿀", "바꾸", "바꾸다"),
    ("ja", "器を焼きます。", "焼き", "焼く"),
    ("zh", "我们制作陶器。", "制作", "制作"),
])
def test_adapters_return_lemmas_and_source_spans(locale, text, surface, lemma):
    tokens = morph.tokens(text, locale)
    assert tokens is not None
    assert (surface, lemma) in [(t[0], t[1]) for t in tokens]
    assert all(text[start:end] for _, _, _, start, end in tokens)
    if locale != "ko":
        assert all(text[start:end] == surface for surface, _, _, start, end in tokens)
    assert morph.analyzer_name(locale)
