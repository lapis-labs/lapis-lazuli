"""Reference implementation of the keyed text signatures in render/DERIVED.md (extract v1).

render_check and lazuli ref must produce identical signatures so that our renders can be compared
with reference-only captures, which store signatures instead of copy. The hash is keyed with a
per-user secret kept in the local cache, so a signature cannot be reversed by enumerating short
strings, and only signatures made with the same key (same `sig_key_id`) are comparable.

    run_sig(text, script, key)    -> 128 hex characters (16 values)
    page_shingles(runs)           -> the shingles page_sig hashes; runs = [(text, script), ...]
    page_sig(runs, key)           -> 1,024 hex characters (128 values)
    similarity(sig_a, sig_b)      -> estimated Jaccard similarity in [0, 1]
    key_id(key)                   -> 8 hex characters identifying the key
"""
from __future__ import annotations

import hashlib
import hmac
import unicodedata

SPACED_SCRIPTS = {"latn", "cyrl", "grek", "arab", "hebr"}
RUN_VALUES = 16
PAGE_VALUES = 128
# Unicode White_Space characters (explicit, so every implementation agrees)
WHITE_SPACE = set(map(chr, [*range(0x09, 0x0E), 0x20, 0x85, 0xA0, 0x1680, *range(0x2000, 0x200B),
                            0x2028, 0x2029, 0x202F, 0x205F, 0x3000]))


def normalize(text: str) -> str:
    """NFKC, case folding, format characters removed, whitespace collapsed, trimmed."""
    t = unicodedata.normalize("NFKC", text).casefold()
    t = "".join(" " if c in WHITE_SPACE else c for c in t if unicodedata.category(c) != "Cf")
    return " ".join(part for part in t.split(" ") if part)


def shingle_size(script: str) -> int:
    return 5 if script in SPACED_SCRIPTS else 2


def shingles(text: str, script: str) -> set[str]:
    """Code-point shingles of the normalized text. Raises ValueError for text with nothing to sign."""
    t = normalize(text)
    if not t:
        raise ValueError("no visible characters to sign")
    k = shingle_size(script)
    if len(t) <= k:
        return {t}
    return {t[i:i + k] for i in range(len(t) - k + 1)}


def _h(key: bytes, i: int, shingle: str) -> int:
    digest = hmac.new(key, f"{i}:{shingle}".encode("utf-8"), hashlib.sha256).digest()
    return int.from_bytes(digest[:4], "big")


def _minhash(grams: set[str], key: bytes, values: int) -> str:
    return "".join(f"{min(_h(key, i, g) for g in grams):08x}" for i in range(1, values + 1))


def run_sig(text: str, script: str, key: bytes) -> str:
    return _minhash(shingles(text, script), key, RUN_VALUES)


SCRIPT_ORDER = ["latn", "cyrl", "grek", "arab", "hebr", "hang", "kana", "hani", "thai", "mixed", "other"]


def chars(text: str) -> int:
    """Code points excluding whitespace, as in the extract's `chars`."""
    return sum(1 for c in text if c not in WHITE_SPACE)


def page_shingles(runs: list[tuple[str, str]]) -> set[str]:
    """Shingles of all visible text in reading order; the shingle size follows the dominant script
    (the script whose runs have the most chars; ties go to the earlier script in SCRIPT_ORDER)."""
    weight: dict[str, int] = {}
    for text, script in runs:
        weight[script] = weight.get(script, 0) + chars(text)
    order = {s: i for i, s in enumerate(SCRIPT_ORDER)}
    dominant = min(weight, key=lambda s: (-weight[s], order.get(s, len(order)))) if weight else "other"
    joined = " ".join(normalize(t) for t, _ in runs)
    return shingles(joined, dominant)


def page_sig(runs: list[tuple[str, str]], key: bytes) -> str:
    return _minhash(page_shingles(runs), key, PAGE_VALUES)


def similarity(a: str, b: str) -> float:
    if len(a) != len(b):
        raise ValueError("signatures of different lengths are not comparable")
    pa = [a[i:i + 8] for i in range(0, len(a), 8)]
    pb = [b[i:i + 8] for i in range(0, len(b), 8)]
    return sum(x == y for x, y in zip(pa, pb)) / len(pa)


def key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:8]
