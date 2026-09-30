"""The label vocabulary catalog adapters map to (`catalog_label.mapped`), and label resolution.

Hangul/CJK classes, their subclasses, the Latin genres, the license ids, and the Adobe CJK codes come
from `vocab/type.yaml` (found through `lapis_design.shared_dir()`). A catalog value with no sound
mapping keeps `mapped` None and its raw text: never guess.
"""
from __future__ import annotations

import re

import yaml

from lapis_design import shared_dir
from lazuli.catalog.store import CatalogLabel

KINDS = ("genre", "subclass", "usage", "feel", "property", "license")

_VOCAB = yaml.safe_load((shared_dir() / "vocab" / "type.yaml").read_text(encoding="utf-8"))

LATIN_GENRES = frozenset(g["id"] for g in _VOCAB["latin_genres"])              # serif, sans, slab, mono, display, hand
HANGUL_CLASSES = frozenset(c["id"] for c in _VOCAB["hangul_classes"])            # bu-ri, min-bu-ri, display, hand
SUBCLASSES = frozenset(f"{c['id']}.{s['id']}" for c in _VOCAB["hangul_classes"] for s in c.get("subclasses", ()))
GENRES = LATIN_GENRES | HANGUL_CLASSES
# OFL-1.1, Apache-2.0, KOGL-1, UFL-1.0, commercial, free-other, and system (usable only where the device has it)
LICENSES = frozenset(entry["id"] for entry in _VOCAB["license_ids"])

# Korean class names as used by Korean catalogs (부리, 둥근 민부리, ...) -> class or class.subclass id
KO_CLASSES = {c["ko"]: c["id"] for c in _VOCAB["hangul_classes"]} | {
    s["ko"]: f"{c['id']}.{s['id']}" for c in _VOCAB["hangul_classes"] for s in c.get("subclasses", ())}


def class_labels(raw: str, value: str | None) -> list[CatalogLabel]:
    """Labels for one catalog class: a genre label, plus a subclass label when `value` names one.

    `value` is a vocabulary id (`sans`, `min-bu-ri`, `min-bu-ri.rounded`) or None for a class with no
    sound mapping, which keeps only the raw text. Any other value is a bug in the caller's mapping table.
    """
    if value is None:
        return [CatalogLabel("genre", raw)]
    if value in GENRES:
        return [CatalogLabel("genre", raw, value)]
    if value in SUBCLASSES:
        return [CatalogLabel("genre", raw, value.split(".", 1)[0]), CatalogLabel("subclass", raw, value)]
    raise ValueError(f"{value!r} is not a genre or subclass of the type vocabulary")


_LICENSE_PATTERNS = (
    (re.compile(r"\bOFL\b(?!.*1\.0)|open font licen[cs]e(?!.*1\.0)", re.I), "OFL-1.1"),
    (re.compile(r"\bapache[\s-]*(licen[cs]e)?[\s,]*(version)?[\s-]*2(\.0)?\b|\bAPACHE2\b", re.I), "Apache-2.0"),
    (re.compile(r"\bUFL\b|ubuntu font licen[cs]e", re.I), "UFL-1.0"),
    (re.compile(r"공공누리\s*(제\s*)?1\s*유형|\bKOGL[\s-]*(type[\s-]*)?(I|1)\b", re.I), "KOGL-1"),
)


def map_license(raw: str | None) -> str | None:
    """The license id for a catalog's license text when the text names it unambiguously, else None.

    Only open licenses with a fixed text are recognized; `commercial` and `free-other` depend on the
    source's own terms, so the adapter that knows those terms sets them.
    """
    if not raw:
        return None
    for pattern, license_id in _LICENSE_PATTERNS:
        if pattern.search(raw):
            return license_id
    return None


def license_label(raw: str) -> CatalogLabel:
    return CatalogLabel("license", raw, map_license(raw))


# Genre and subclass resolve together, so a family never mixes one source's genre with another's subclass
_GROUPS = {"genre": "class", "subclass": "class"}


def resolve(rows) -> list[dict]:
    """Labels of one font or family resolved by source priority (rows shaped like `v_font_label`).

    Per kind (genre and subclass count as one), the labels come from a single source: the
    highest-priority matched source (lowest `priority`, then highest match confidence) that maps a
    label of that kind to the vocabulary; when no source maps one, the highest-priority source that
    has raw labels of that kind. Returns [{"kind", "mapped", "raw", "source"}] without duplicates.
    """
    ordered = sorted(rows, key=lambda r: (r["priority"], -r["confidence"], r["source"]))
    chosen: dict[str, str] = {}
    for group in {_GROUPS.get(r["kind"], r["kind"]) for r in ordered}:
        in_group = [r for r in ordered if _GROUPS.get(r["kind"], r["kind"]) == group]
        best = next((r for r in in_group if r["mapped"] is not None), in_group[0])
        chosen[group] = best["source"]
    out, seen = [], set()
    for r in ordered:
        if chosen[_GROUPS.get(r["kind"], r["kind"])] != r["source"]:
            continue
        key = (r["kind"], r["mapped"], r["raw"])
        if key not in seen:
            seen.add(key)
            out.append({"kind": r["kind"], "mapped": r["mapped"], "raw": r["raw"], "source": r["source"]})
    return sorted(out, key=lambda label: (KINDS.index(label["kind"]), label["mapped"] is None))


def by_family(conn) -> dict[str, dict]:
    """Per installed family: {"labels": resolved labels, "sources": the catalog families its faces matched}.

    Each source entry is the best match of that catalog family over the family's faces:
    {"source", "family", "method", "confidence", "url"}, highest-priority source first.
    """
    rows: dict[str, list] = {}
    for row in conn.execute("SELECT family, kind, mapped, raw, source, priority, confidence FROM v_font_label "
                            "WHERE family IS NOT NULL"):
        rows.setdefault(row["family"], []).append(row)
    out = {family: {"labels": resolve(found), "sources": []} for family, found in rows.items()}
    # SQLite takes the bare `method` from the row that holds MAX(confidence)
    for row in conn.execute("""
            SELECT lf.family, s.name AS source, cf.family AS catalog_family, cf.url, m.method, MAX(m.confidence) AS confidence
            FROM match m JOIN local_font lf ON lf.id = m.local_font_id JOIN source s ON s.id = m.source_id
            JOIN catalog_family cf ON cf.source_id = m.source_id AND cf.source_key = m.source_key
            WHERE lf.family IS NOT NULL
            GROUP BY lf.family, m.source_id, m.source_key ORDER BY lf.family, s.priority, confidence DESC"""):
        entry = out.setdefault(row["family"], {"labels": [], "sources": []})
        entry["sources"].append({"source": row["source"], "family": row["catalog_family"], "method": row["method"],
                                 "confidence": row["confidence"], "url": row["url"]})
    return out
