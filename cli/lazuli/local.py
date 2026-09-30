"""`lazuli local fonts`: scan, measure, list, and summarize the fonts on this computer."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict

from lazuli import db, measure, paths, scan

# Script coverage, not language: Korean sets carry kana and 4,620 Hanja (KS X 1001), and GB 2312 carries
# kana too, so kana alone does not mark a Japanese font. 2,350 syllables is the KS X 1001 Hangul set;
# 6,000 Han covers JIS X 0208 and GB 2312 but not the Hanja of Korean sets.
SCRIPT_GROUPS = [("Hangul", "Hangul 2,350+ syllables"), ("Kana+Han", "kana + 6,000+ Han"),
                 ("Han", "6,000+ Han")]

LATIN_CLASSES = ("serif", "sans", "hand", "decorative", "symbol")


def _scripts(coverage: dict) -> set[str]:
    out = set()
    if coverage.get("latin", 0) >= 52:
        out.add("Latin")
    if coverage.get("hangul_syllables", 0) >= 2350:
        out.add("Hangul")
    if coverage.get("han", 0) >= 6000:
        out.add("Han")
        if coverage.get("kana", 0) >= 150:
            out.add("Kana+Han")
    return out


def _families(conn: sqlite3.Connection, pattern: str | None = None) -> list[dict]:
    """One entry per family: origins, faces, scripts, and the measured classes of its faces."""
    rows = conn.execute(
        """SELECT lf.family, lf.origin, lf.subfamily, lf.postscript_name, lf.coverage_json,
                  m.family_kind, m.panose_json, m.cjk_json, m.metrics_json
           FROM local_font lf LEFT JOIN measurement m
             ON m.local_font_id = lf.id AND m.measurer_version = ?
           WHERE lf.family IS NOT NULL AND lf.family NOT LIKE '.%'
             AND (? IS NULL OR lf.family_norm LIKE '%' || ? || '%' OR lf.names_i18n_json LIKE '%' || ? || '%')
           ORDER BY lf.family, lf.subfamily""",
        (measure.MEASURER_VERSION, pattern and scan.norm(pattern), pattern and scan.norm(pattern), pattern)).fetchall()
    out: dict[str, dict] = {}
    for row in rows:
        entry = out.setdefault(row["family"], {"family": row["family"], "origins": set(), "faces": [],
                                               "scripts": set(), "classes": Counter(), "measured": 0})
        entry["origins"].add(row["origin"])
        coverage = json.loads(row["coverage_json"] or "{}")
        entry["scripts"].update(_scripts(coverage))
        face = {"subfamily": row["subfamily"], "postscript_name": row["postscript_name"]}
        if row["family_kind"]:
            entry["measured"] += 1
            panose = json.loads(row["panose_json"] or "{}")
            cjk = json.loads(row["cjk_json"] or "{}")
            metrics = json.loads(row["metrics_json"] or "{}")
            face.update(kind=row["family_kind"], panose=panose, cjk=cjk, metrics=metrics)
            if cjk.get("bu_class"):
                entry["classes"]["bu-ri" if cjk["bu_class"] == "bu" else "min-bu-ri"] += 1
            if metrics.get("monospaced"):
                entry["classes"]["mono"] += 1
            if "serif" in metrics:
                entry["classes"]["serif" if metrics["serif"] else "sans"] += 1
            if metrics.get("pixel_outline"):
                entry["classes"]["pixel"] += 1
            if row["family_kind"] != "text":
                entry["classes"][row["family_kind"]] += 1
        entry["faces"].append(face)
    return [{**e, "origins": sorted(e["origins"]), "scripts": sorted(e["scripts"]),
             "classes": [name for name, _ in e["classes"].most_common()]} for e in out.values()]


def summary(conn: sqlite3.Connection, *, changed: bool) -> str:
    families = _families(conn)
    files = conn.execute("SELECT COUNT(DISTINCT path) FROM local_font WHERE origin != 'adobe-sync'").fetchone()[0]
    adobe = conn.execute("SELECT COUNT(*) FROM local_font WHERE origin = 'adobe-sync'").fetchone()[0]
    scanned = conn.execute("SELECT value FROM meta WHERE key = 'inventory_scanned_at'").fetchone()
    by_origin = Counter(origin for f in families for origin in f["origins"])
    where = f"{files} files" + (f" and {adobe} Adobe Fonts faces" if adobe else "")
    lines = [f"lazuli: {len(families)} font families in {where} "
             f"({', '.join(f'{o} {n}' for o, n in sorted(by_origin.items()))})"
             + (f", scanned {scanned[0][:10]}" if scanned else "")]
    for script, label in SCRIPT_GROUPS:
        group = [f for f in families if script in f["scripts"]]
        if not group:
            continue
        classes = Counter(c for f in group for c in f["classes"] if c in ("bu-ri", "min-bu-ri", "hand", "pixel"))
        unmeasured = sum(1 for f in group if not f["measured"])
        detail = ", ".join(f"{c} {n}" for c, n in classes.most_common())
        lines.append(f"  {label}: {len(group)} families" + (f" ({detail}" + (f", unmeasured {unmeasured})" if unmeasured else ")") if detail else ""))
    latin = [f for f in families if f["scripts"] == ["Latin"]]
    if latin:
        forms = Counter(next((c for c in f["classes"] if c in LATIN_CLASSES), "unmeasured") for f in latin)
        attributes = Counter(c for f in latin for c in ("mono", "pixel") if c in f["classes"])
        detail = [*(f"{c} {n}" for c, n in forms.most_common()),
                  *(f"{c} {attributes[c]}" for c in ("mono", "pixel"))]
        lines.append(f"  Latin without a CJK set: {len(latin)} families ({', '.join(detail)})")
    if catalog := _catalog_line(conn):
        lines.append(catalog)
    if changed:
        lines.append("  Fonts changed since the last scan: run `lazuli local fonts` to update the inventory.")
    lines.append("  Details: `lazuli local fonts --family NAME` (use installed fonts for local tests only).")
    return "\n".join(lines)


def _catalog_line(conn: sqlite3.Connection) -> str | None:
    """Matched family counts per catalog source, or None before any catalog sync. Plain SQL: the hook runs it."""
    if conn.execute("SELECT 1 FROM catalog_family LIMIT 1").fetchone() is None:
        return None
    visible = "lf.family IS NOT NULL AND lf.family NOT LIKE '.%'"
    families = conn.execute(f"SELECT COUNT(DISTINCT family) FROM local_font lf WHERE {visible}").fetchone()[0]
    rows = conn.execute(f"""SELECT s.name, COUNT(DISTINCT lf.family) FROM match m JOIN local_font lf ON lf.id = m.local_font_id
                            JOIN source s ON s.id = m.source_id WHERE {visible} GROUP BY s.name ORDER BY MIN(s.priority)""").fetchall()
    matched = conn.execute(f"SELECT COUNT(DISTINCT lf.family) FROM match m JOIN local_font lf ON lf.id = m.local_font_id "
                           f"WHERE {visible}").fetchone()[0]
    detail = ", ".join(f"{name} {count}" for name, count in rows)
    return (f"  Catalog labels: {matched} of {families} families matched" + (f" ({detail})" if detail else "")
            + "; `lazuli catalog status` for sources")


def inventory_changed(conn: sqlite3.Connection) -> bool:
    stored = conn.execute("SELECT value FROM meta WHERE key = 'inventory_fingerprint'").fetchone()
    return stored is None or stored[0] != scan.current_fingerprint()


def session_summary() -> str | None:
    """The session-start text, or None when there is nothing to say. Never scans or creates the DB."""
    path = paths.db_path()
    if not path.exists():
        return "lazuli: no font inventory yet. Run `lazuli local fonts` once (a read-only scan) to list local fonts."
    conn = db.connect(path)
    try:
        return summary(conn, changed=inventory_changed(conn))
    finally:
        conn.close()


# Label kinds shown in the table; JSON carries every kind. Labels carry their source: `user` is the user's own
# class (`lazuli class`), which outranks the catalogs and gets its own line.
TABLE_LABEL_KINDS = ("genre", "subclass", "usage", "feel", "license")


def _catalog_text(catalog: dict) -> str | None:
    shown = [f"{label['kind']} {label['mapped'] or repr(label['raw'])}" for label in catalog["labels"]
             if label["kind"] in TABLE_LABEL_KINDS and label["source"] != "user"]
    sources = [f"{s['source']}: {s['family']}, {s['method']}" for s in catalog["sources"]]
    if not shown and not sources:
        return None
    return "    catalog: " + (", ".join(shown) or "no labels") + (f"  ({'; '.join(sources)})" if sources else "")


def _user_text(label: dict) -> str:
    return (f"    user: genre {label['genre']}" + (f", subclass {label['subclass']}" if label["subclass"] else "")
            + "  (your class" + (f"; {label['url']}" if label["url"] else "") + ")")


def _table(families: list[dict]) -> str:
    lines = []
    for f in families:
        weights = sorted({face["panose"].get("weight") for face in f["faces"] if face.get("panose", {}).get("weight")})
        lines.append(f"{f['family']}  [{', '.join(f['origins'])}]  {len(f['faces'])} faces  "
                     f"{'/'.join(f['scripts']) or '-'}  {', '.join(f['classes']) or 'unmeasured'}"
                     + (f"  weights: {', '.join(weights)}" if weights else ""))
        if "user_class" in f:
            lines.append(_user_text(f["user_class"]))
        if catalog := _catalog_text(f["catalog"]):
            lines.append(catalog)
    return "\n".join(lines)


def main(argv: list[str] | None = None, prog: str = "lazuli local fonts") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Scan (read-only), measure, and list local fonts.")
    ap.add_argument("--family", help="only families whose name contains this text")
    ap.add_argument("--summary", action="store_true", help="short inventory summary, as printed at session start")
    ap.add_argument("--json", action="store_true", help="families with faces and measurements as JSON")
    ap.add_argument("--rescan", action="store_true",
                    help="re-read every file and Adobe Fonts face, not only changed ones")
    ap.add_argument("--no-measure", action="store_true", help="scan without measuring new faces")
    args = ap.parse_args(argv)
    try:
        scan.roots()                                         # a bad LAZULI_FONT_ROOTS is a usage error
    except scan.RootsError as exc:
        ap.error(str(exc))
    conn = db.connect(paths.db_path())
    try:
        result = scan.scan(conn, rescan=args.rescan)
        measured, failures = (0, []) if args.no_measure else measure.measure_pending(conn)
        from lazuli.catalog import labels, match, store          # not at import: the session hook imports this module
        if result.added or result.updated or result.removed:
            match.run(conn)
        if args.summary:
            print(summary(conn, changed=False))
            return 0
        families = _families(conn, args.family)
        catalog = labels.by_family(conn)
        mine = store.user_labels(conn)
        for family in families:
            family["catalog"] = catalog.get(family["family"], {"labels": [], "sources": []})
            if label := mine.get(scan.norm(family["family"])):
                family["user_class"] = {k: v for k, v in label.items() if k != "family"}
        if args.json:
            json.dump(families, sys.stdout, ensure_ascii=False, indent=1)
            print()
        else:
            print(_table(families))
        print(f"scanned {result.files} files{f' and {result.adobe} Adobe Fonts faces' if result.adobe else ''}: "
              f"{result.added} new, {result.updated} changed, {result.removed} gone; "
              f"measured {measured} faces", file=sys.stderr)
        for problem in result.unreadable + failures:
            print(f"  skipped {problem}", file=sys.stderr)
        return 0
    finally:
        conn.close()
