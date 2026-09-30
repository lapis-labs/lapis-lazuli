"""Optional, lazy morphological tokenizers. Offsets refer to the original input text.

Korean inflection can share or overlap source characters across morphemes; in that case
`surface` is the analyzer's morpheme, not necessarily `text[start:end]`.
"""
from __future__ import annotations

from functools import cache
from importlib import metadata
from typing import Callable

Token = tuple[str, str, str, int, int]  # surface, lemma, POS, start, end


@cache
def _adapter(locale: str) -> Callable[[str], list[Token]] | None:
    if locale == "ko":
        try:
            from kiwipiepy import Kiwi
        except ModuleNotFoundError as exc:
            if exc.name == "kiwipiepy":
                return None
            raise
        kiwi = Kiwi()

        def korean(text: str) -> list[Token]:
            return [(t.form, t.lemma, t.tag, t.start, t.start + t.len) for t in kiwi.tokenize(text)]

        return korean
    if locale == "ja":
        try:
            from sudachipy import dictionary
        except ModuleNotFoundError as exc:
            if exc.name == "sudachipy":
                return None
            raise
        tokenizer = dictionary.Dictionary().tokenizer()

        def japanese(text: str) -> list[Token]:
            return [(t.surface(), t.dictionary_form(), t.part_of_speech()[0], t.begin(), t.end())
                    for t in tokenizer.tokenize(text)]

        return japanese
    if locale == "zh":
        try:
            import rjieba
        except ModuleNotFoundError as exc:
            if exc.name == "rjieba":
                return None
            raise

        def chinese(text: str) -> list[Token]:
            out = []
            offset = 0
            for word, pos in rjieba.tag(text):
                start = text.index(word, offset)
                offset = start + len(word)
                out.append((word, word, pos, start, offset))
            return out

        return chinese
    return None


def tokens(text: str, locale: str | None) -> list[Token] | None:
    """Return analyzed tokens, or None if that locale's optional analyzer is absent."""
    adapter = _adapter(locale or "")
    return adapter(text) if adapter is not None else None


def analyzer_name(locale: str) -> str | None:
    """Identify a loaded adapter without importing one just to format a report."""
    package = {"ko": "kiwipiepy", "ja": "sudachipy", "zh": "rjieba"}.get(locale)
    return f"{package} {metadata.version(package)}" if package and _adapter(locale) is not None else None
