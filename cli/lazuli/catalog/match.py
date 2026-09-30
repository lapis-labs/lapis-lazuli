"""Match every local face against every catalog, and find the families no snapshot matched.

Methods, best first: `exact_ps` (PostScript name, 1.0), `exact_family` (the normalized family or any
i18n name equals the catalog family or one of its i18n names, 0.9), and `fuzzy` (the same after
removing weight, width, style, and packaging words such as Pro, Std, VF, Variable, OTF, TTF, 0.6).
Per face and source only the best method's matches are kept. Matching is a pure function of the
tables, so it reruns in full after every sync, lookup, and scan.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict

from lazuli.scan import norm

CONFIDENCE = {"exact_ps": 1.0, "exact_family": 0.9, "fuzzy": 0.6}
_RANK = {method: rank for rank, method in enumerate(CONFIDENCE)}

WEIGHT_WORDS = {"hairline", "thin", "extralight", "ultralight", "light", "semilight", "demilight", "regular",
                "book", "normal", "medium", "semibold", "demibold", "bold", "extrabold", "ultrabold", "heavy",
                "black", "extrablack", "ultrablack", "extra", "ultra", "semi", "demi"}
WIDTH_WORDS = {"condensed", "semicondensed", "extracondensed", "cond", "compressed", "narrow", "extended",
               "semiextended", "expanded", "wide"}
STYLE_WORDS = {"italic", "oblique", "slanted"}
PACKAGING_WORDS = {"pro", "pron", "pr5", "pr5n", "pr6", "pr6n", "std", "stdn", "vf", "variable", "otf", "ttf",
                   "otc", "ttc", "web"}
_STRIP = WEIGHT_WORDS | WIDTH_WORDS | STYLE_WORDS | PACKAGING_WORDS
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+|[^\W\d_A-Za-z]+")


def fuzzy_key(name: str | None) -> str | None:
    """The normalized name without weight, width, style, and packaging words, or None when nothing is left.

    Whole words are checked first (SemiBold, ProN, Pr6N), then the parts of camel-case words
    (NanumGothicExtraBold -> Nanum Gothic).
    """
    if not name:
        return None
    kept = []
    for word in re.split(r"[\W_]+", name):
        if not word or word.casefold() in _STRIP:
            continue
        kept += [part for part in _CAMEL.findall(word) if part.casefold() not in _STRIP] or [word]
    return norm("".join(kept)) or None


def _names(family: str | None, names_i18n_json: str | None) -> list[str]:
    names = [family] if family else []
    names += [n for n in json.loads(names_i18n_json or "{}").values() if n]
    return names


def run(conn: sqlite3.Connection) -> dict:
    """Refill `match`; returns {"faces", "matched", "by_source": {name: faces}}."""
    by_ps: dict[str, set] = defaultdict(set)
    for sid, key, ps in conn.execute("SELECT source_id, source_key, postscript_name FROM catalog_font"):
        by_ps[ps.casefold()].add((sid, key))
    by_name: dict[str, set] = defaultdict(set)
    by_fuzzy: dict[str, set] = defaultdict(set)
    for sid, key, family, i18n in conn.execute("SELECT source_id, source_key, family, names_i18n_json FROM catalog_family"):
        for name in _names(family, i18n):
            if exact := norm(name):
                by_name[exact].add((sid, key))
            if loose := fuzzy_key(name):
                by_fuzzy[loose].add((sid, key))
    rows, faces = [], 0
    for face_id, ps, family, i18n in conn.execute(
            "SELECT id, postscript_name, family, names_i18n_json FROM local_font").fetchall():
        faces += 1
        names = _names(family, i18n)
        candidates = [(k, "exact_ps") for k in by_ps.get(ps.casefold(), ())] if ps else []
        candidates += [(k, "exact_family") for n in names for k in by_name.get(norm(n) or "", ())]
        candidates += [(k, "fuzzy") for n in names for k in by_fuzzy.get(fuzzy_key(n) or "", ())]
        best: dict[int, int] = {}
        for (sid, _), method in candidates:
            best[sid] = min(best.get(sid, len(_RANK)), _RANK[method])
        chosen: dict[tuple, str] = {}
        for (sid, key), method in candidates:
            if _RANK[method] == best[sid]:
                chosen.setdefault((sid, key), method)
        rows += [(face_id, sid, key, method, CONFIDENCE[method]) for (sid, key), method in chosen.items()]
    with conn:
        conn.execute("DELETE FROM match")
        conn.executemany("INSERT INTO match (local_font_id, source_id, source_key, method, confidence) "
                         "VALUES (?, ?, ?, ?, ?)", rows)
    by_source = {name: count for name, count in conn.execute(
        """SELECT s.name, COUNT(DISTINCT m.local_font_id) FROM match m JOIN source s ON s.id = m.source_id
           GROUP BY s.name ORDER BY MIN(s.priority)""")}
    return {"faces": faces, "matched": len({r[0] for r in rows}), "by_source": by_source}


def unmatched(conn: sqlite3.Connection, pattern: str | None = None) -> list[dict]:
    """Installed families none of whose faces a snapshot or bundled source matched (lookup candidates).

    One entry per family, with its i18n names and one PostScript name; families with Hangul come first.
    `pattern` keeps families whose name or i18n name contains it.
    """
    matched_kinds = "('snapshot', 'bundled')"
    rows = conn.execute(f"""
        SELECT lf.family, lf.names_i18n_json, lf.postscript_name, lf.coverage_json,
               EXISTS (SELECT 1 FROM local_font o JOIN match m ON m.local_font_id = o.id
                       JOIN source s ON s.id = m.source_id
                       WHERE o.family = lf.family AND s.kind IN {matched_kinds}) AS matched
        FROM local_font lf
        WHERE lf.family IS NOT NULL AND lf.family NOT LIKE '.%'
          AND (? IS NULL OR lf.family_norm LIKE '%' || ? || '%' OR lf.names_i18n_json LIKE '%' || ? || '%')
        ORDER BY lf.family, lf.subfamily""",
        (pattern and norm(pattern), pattern and norm(pattern), pattern)).fetchall()
    out: dict[str, dict] = {}
    for row in rows:
        if row["matched"]:
            continue
        entry = out.setdefault(row["family"], {"family": row["family"], "names_i18n": {}, "postscript_name": None,
                                               "faces": 0, "hangul": False})
        entry["faces"] += 1
        entry["names_i18n"] = entry["names_i18n"] or json.loads(row["names_i18n_json"] or "{}")
        entry["postscript_name"] = entry["postscript_name"] or row["postscript_name"]
        entry["hangul"] = entry["hangul"] or json.loads(row["coverage_json"] or "{}").get("hangul_syllables", 0) > 0
    return sorted(out.values(), key=lambda e: (not e["hangul"], e["family"].casefold()))
