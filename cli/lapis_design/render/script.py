"""Classify rendered text using the precedence and proportions in render/DERIVED.md."""
from __future__ import annotations

import unicodedata
from collections import Counter


def _script(character: str) -> str | None:
    if not unicodedata.category(character).startswith("L"):
        return None
    cp = ord(character)
    if 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF or 0x3130 <= cp <= 0x318F:
        return "hang"
    if 0x3040 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF or 0xFF66 <= cp <= 0xFF9F:
        return "kana"
    if any(a <= cp <= b for a, b in ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
                                      (0x20000, 0x323AF))):
        return "hani"
    name = unicodedata.name(character, "")
    for prefix, script in (("LATIN", "latn"), ("CYRILLIC", "cyrl"), ("GREEK", "grek"),
                           ("ARABIC", "arab"), ("HEBREW", "hebr"), ("THAI", "thai")):
        if name.startswith(prefix):
            return script
    return "other"


def script_of(text: str) -> str:
    counts = Counter(s for c in text if (s := _script(c)) is not None)
    total = sum(counts.values())
    if not total:
        return "other"
    if counts["hang"] and (counts["hang"] + counts["hani"]) * 2 >= total:
        return "hang"
    if counts["kana"] and (counts["kana"] + counts["hani"]) * 2 >= total:
        return "kana"
    if counts["hani"] * 2 >= total:
        return "hani"
    for script in ("latn", "cyrl", "grek", "arab", "hebr", "thai", "other"):
        if counts[script] * 5 >= total * 4:
            return script
    return "mixed"
