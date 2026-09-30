"""Which languages a font can set: one rule, read from the characters the font maps.

`supported()` gives the language tags whose whole character set a face maps to glyphs, and nothing else counts:
not the OS/2 code-page and Unicode-range bits a font declares, and not the language list an operating system
keeps. So the same face gets the same tags from a font file (fontTools) and from Core Text, on every OS.

A language needs every character of its set, capitals included (the capital of each letter, when it is a
single character). These are conservative repertoire hints, not a complete language catalog or proof of
shaping. General punctuation and digits are not checked; Thai's script-essential vowel/tone marks are.
Plain A-Z is labeled `en`; other languages with that same alphabet are not separately enumerated.

- Latin-script languages: the 52 letters A-Z and a-z, plus `LATIN_EXTRA` (Polish `ąćęłńóśźż`).
- Cyrillic and Greek languages: their alphabet, in `ALPHABETS`.
- Hebrew, Arabic, Persian, Thai: the script character ranges in `SPANS`.
- Korean: the 2,350 Hangul syllables of KS X 1001. Japanese: the 169 hiragana and katakana of JIS X 0208 and its
  2,965 level 1 kanji. Simplified Chinese: the 3,755 level 1 hanzi of GB 2312. Traditional Chinese: the 5,401
  most frequent hanzi of Big5. Each set is decoded from the legacy encoding's own byte range by Python's codec
  (`_decoded`), so no character list is kept here.

Every character is in the Basic Multilingual Plane, so Core Text's BMP character mapping answers for all of them.
"""
from __future__ import annotations

import functools
from collections.abc import Iterable

BASIC_LATIN = "abcdefghijklmnopqrstuvwxyz"

# tag: (letters every face must map, lowercase; the capital of each is required too). Latin-script languages
# list the letters beyond A-Z; the 52 letters of BASIC_LATIN are added to them.
LATIN_EXTRA = {
    "en": "",
    "fr": "àâæçéèêëîïôœùûüÿ",
    "de": "äöüß",
    "es": "áéíñóúü",
    "it": "àèéìòù",
    "pt": "áâãàçéêíóôõú",
    "sv": "åäö",
    "fi": "åäö",
    "da": "æøå",
    "nb": "æøå",
    "is": "áðéíóúýþæö",
    "pl": "ąćęłńóśźż",
    "cs": "áčďéěíňóřšťúůýž",
    "sk": "áäčďéíĺľňóôŕšťúýž",
    "hu": "áéíóöőúüű",
    "ro": "ăâîșț",
    "hr": "čćđšž",
    "sl": "čšž",
    "tr": "çğıöşüİ",
    "lt": "ąčęėįšųūž",
    "lv": "āčēģīķļņšūž",
    "et": "äõöüšž",
    "vi": "àáâãèéêìíòóôõùúýăđĩũơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ",
}

# tag: the alphabet, lowercase; the capital of each letter is required too when it is one character.
ALPHABETS = {
    "el": "αβγδεζηθικλμνξοπρςστυφχψωάέήίόύώϊϋΐΰ",
    "ru": "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    "uk": "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя",
    "bg": "абвгдежзийклмнопрстуфхцчшщъьюя",
    "sr-Cyrl": "абвгдђежзијклљмнњопрстћуфхцчџш",
}

# tag: inclusive code point spans of scripts without case
SPANS = {
    "he": ((0x05D0, 0x05EA),),
    "ar": ((0x0621, 0x063A), (0x0641, 0x064A)),
    "fa": ((0x0621, 0x063A), (0x0641, 0x064A), (0x067E, 0x067E), (0x0686, 0x0686), (0x0698, 0x0698),
           (0x06A9, 0x06A9), (0x06AF, 0x06AF), (0x06CC, 0x06CC)),
    "th": ((0x0E01, 0x0E3A), (0x0E40, 0x0E4E)),
}


def _decoded(codec: str, leads: range, trails: Iterable[int]) -> frozenset[int]:
    """The characters a legacy double-byte encoding gives for the byte pairs in these ranges."""
    trails = tuple(trails)
    found = set()
    for lead in leads:
        for trail in trails:
            try:
                text = bytes((lead, trail)).decode(codec)
            except UnicodeDecodeError:
                continue
            if len(text) == 1:
                found.add(ord(text))
    return frozenset(found)


def _letters(text: str) -> set[int]:
    out = set()
    for letter in text:
        out.add(ord(letter))
        capital = letter.upper()
        if len(capital) == 1:                     # ß has none as one character
            out.add(ord(capital))
    return out


@functools.cache
def requirements() -> dict[str, frozenset[int]]:
    """language tag -> the code points a face must map to support it, in the order the tags are defined."""
    table = {tag: frozenset(_letters(BASIC_LATIN + extra)) for tag, extra in LATIN_EXTRA.items()}
    table.update({tag: frozenset(_letters(text)) for tag, text in ALPHABETS.items()})
    table.update({tag: frozenset(cp for lo, hi in spans for cp in range(lo, hi + 1)) for tag, spans in SPANS.items()})
    euc = range(0xA1, 0xFF)
    table["ko"] = _decoded("euc_kr", range(0xB0, 0xC9), euc)                              # KS X 1001 Hangul
    table["ja"] = _decoded("euc_jp", range(0xA4, 0xA6), euc) | _decoded("euc_jp", range(0xB0, 0xD0), euc)
    table["zh-Hans"] = _decoded("gb2312", range(0xB0, 0xD8), euc)                         # GB 2312 level 1
    big5_trails = (*range(0x40, 0x7F), *euc)
    table["zh-Hant"] = (_decoded("big5", range(0xA4, 0xC6), big5_trails)                  # Big5 0xA440-0xC67E
                        | _decoded("big5", range(0xC6, 0xC7), range(0x40, 0x7F)))
    return table


@functools.cache
def wanted() -> frozenset[int]:
    """Every code point any language needs: what a caller asks a face about, once."""
    return frozenset().union(*requirements().values())


def supported(mapped: Iterable[int]) -> list[str]:
    """The language tags, sorted, whose whole set is among `mapped` (the code points of `wanted()` a face maps)."""
    have = mapped if isinstance(mapped, (set, frozenset)) else set(mapped)
    return sorted(tag for tag, needs in requirements().items() if needs <= have)


def of_cmap(cmap) -> list[str]:
    """`supported` for a character map (code point -> glyph)."""
    return supported({cp for cp in wanted() if cp in cmap})
