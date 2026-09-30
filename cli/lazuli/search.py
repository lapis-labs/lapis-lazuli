"""`lazuli search`: ranked font candidates, with why each matched, from local fonts and synced catalogs.

`--type color` and `--type source` hand the other arguments to `lazuli.color.search_main` and
`lazuli.sources.search_main` unchanged (only the `--type` option is removed).

Fonts (the default type) come from the lazuli DB only; the command never scans or fetches. An installed
family carries the catalog families its faces matched; a catalog family no installed face matched is its
own candidate, merged across catalogs by normalized name. The user's own class of a family (`lazuli class`,
source `user`) replaces the catalogs' genre and subclass, and the evidence names it. QUERY matches,
strongest first: a family or i18n name (equal, prefix, substring), a PostScript name, a catalog or user
label (raw or mapped), a measured class, a foundry or designer. Filters:
  --script     an ISO 15924 code of the plan list (plan/schema.yaml: latn, cyrl, grek, hang, kana, hani, arab,
               hebr, thai) or a composite that stands for its parts: kore = hang, jpan = kana + hani, hans and
               hant = hani, hrkt = kana (a family needs every part). Other codes are refused (exit 2).
               Installed families by coverage (`lazuli.lock.coverage_scripts`), catalog families by their
               `script:` labels, whose composites expand the same way.
  --role       code needs a monospaced family; body, ui, data, and caption leave out families whose catalog
               or user classes are only display or hand, or, without such classes, whose measured kind is
               symbol (a `hand` kind from a name hint only warns); display and heading keep every family.
               The role also ranks, by the weights known from installed measured faces (OS/2 weight class,
               italic, and the PANOSE stroke weight measured on the regular face) and the catalogs' weight
               labels and wght axis ranges:
                 body, ui, data, caption: a regular upright face (weight class 350-500) +0.10; no regular
                 face because every weight is 700 or more or 250 or less, or because the regular face
                 measures bold or heavier (or light or lighter) -0.15; a catalog that also classifies the
                 family display or hand -0.10; +0.01 per extra weight, at most +0.04. Unknown weights add
                 nothing, so they never outrank a known regular face.
                 display, heading: a face of weight 600 or more, or bold measured strokes, +0.03; heavy
                 weights are never penalized.
  --category   a genre or class (serif, sans, slab, mono, display, hand, bu-ri, min-bu-ri) or a subclass
               (min-bu-ri.rounded), from catalog labels, user classes, or measurement
  --license    open: OFL-1.1, Apache-2.0, UFL-1.0, or KOGL-1 by the catalog license label (a hint)
  --delivery   a known path: web by google-fonts-api (Google Fonts lists it), self-host (open license), or
               adobe-web-project (Adobe sync or catalog); app by app-bundle (open license) or system-only
  --installed  installed families only
  --similar-to installed families ranked by distance over the target's measured features (`lazuli.measure`:
               Latin weight, contrast, x-height, proportion, serif, monospaced; CJK bu ratio, stroke
               contrast, square spread), each scaled to a typical step and compared on the face nearest a
               regular weight; a target feature the other family lacks counts one step. Catalog-only
               families have no measurements and are left out.
Exit codes: 0 searched (even with no candidates); 2 usage or missing input.
"""
from __future__ import annotations

import argparse
import functools
import importlib
import json
import math
import re
import sqlite3
import sys
from collections import defaultdict

import yaml

from lapis_design import shared_dir
from lazuli import db, local, paths
from lazuli.catalog import labels, store
from lazuli.lock import coverage_scripts, label_scripts
from lazuli.scan import norm

TYPES = ("font", "color", "source")
BACKENDS = {"color": "lazuli.color", "source": "lazuli.sources"}

OPEN_LICENSES = frozenset({"OFL-1.1", "Apache-2.0", "UFL-1.0", "KOGL-1"})
TEXT_CLASSES = frozenset({"serif", "sans", "slab", "mono", "bu-ri", "min-bu-ri"})
NON_TEXT_CLASSES = frozenset({"display", "hand", "symbol", "decorative"})
TEXT_ROLES = frozenset({"body", "ui", "data", "caption"})
DISPLAY_ROLES = frozenset({"display", "heading"})
ROLES = ("display", "heading", "body", "ui", "data", "code", "caption")
# ISO 15924 composites and the plan codes they stand for (a family needs every part)
COMPOSITE_SCRIPTS = {"kore": ("hang",), "jpan": ("kana", "hani"), "hans": ("hani",), "hant": ("hani",),
                     "hrkt": ("kana",)}
CATALOG_HITS = 500                  # catalog families store.search may return for one query

# (measurement part, key, typical step, compare logarithms): distance counts steps of this size
FEATURES = (("metrics", "weight_rat", 0.5, True), ("metrics", "con_rat", 0.3, False),
            ("metrics", "x_rat", 0.1, False), ("metrics", "o_rat", 0.2, False),
            ("metrics", "prop_rat", 0.1, False), ("metrics", "serif", 1.0, False),
            ("metrics", "monospaced", 1.0, False), ("cjk", "bu_ratio", 0.3, False),
            ("cjk", "cjk_contrast", 0.5, True), ("cjk", "square_spread", 0.05, False))
MIN_SHARED_FEATURES = 2
MISSING_STEP = 1.0                  # a target feature the other face lacks (e.g. no CJK) counts one step apart
REGULAR_NAMES = frozenset({"regular", "book", "normal", "roman"})

# Role fit (see --role in the module doc)
REGULAR_WEIGHTS = (350, 500)        # OS/2 weight classes that count as a regular face
HEAVY_ONLY, LIGHT_ONLY = 700, 250   # every known weight at or above / at or below: no regular face
HEAVY_STROKES = frozenset({"bold", "heavy", "black", "extra-black"})   # PANOSE weight measured on the face
LIGHT_STROKES = frozenset({"very-light", "light"})
FIT_REGULAR, FIT_NO_REGULAR, FIT_CLASSED = 0.10, -0.15, -0.10
FIT_PER_WEIGHT, FIT_WEIGHTS_MAX = 0.01, 0.04
FIT_BOLD = 0.03                     # display and heading: a bold or heavier face is available
_WGHT_AXIS = re.compile(r"wght\s+(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)")


# ---------------------------------------------------------------- dispatch

def split_type(argv: list[str]) -> tuple[str, list[str]]:
    """The --type value (default font) and the arguments without it."""
    kind, rest, i = "font", [], 0
    while i < len(argv):
        token = argv[i]
        if token == "--":
            rest += argv[i:]
            break
        if token in ("--type", "-t") and i + 1 < len(argv):
            kind, i = argv[i + 1], i + 2
            continue
        if token.startswith("--type="):
            kind, i = token.split("=", 1)[1], i + 1
            continue
        rest.append(token)
        i += 1
    return kind, rest


# ---------------------------------------------------------------- candidates

@functools.lru_cache(maxsize=1)
def plan_scripts() -> tuple[str, ...]:
    """The script codes plan files may use (plan/schema.yaml, type roles)."""
    schema = yaml.safe_load((shared_dir() / "plan" / "schema.yaml").read_text(encoding="utf-8"))
    roles = schema["$defs"]["type_tokens"]["properties"]["roles"]["items"]
    return tuple(roles["properties"]["scripts"]["items"]["enum"])


def script_parts(code: str) -> tuple[str, ...]:
    """The plan codes a --script code stands for; ValueError for a code outside the plan list and composites."""
    code = code.lower()
    if code in COMPOSITE_SCRIPTS:
        return COMPOSITE_SCRIPTS[code]
    if code in plan_scripts():
        return (code,)
    composites = "; ".join(f"{c} = {' + '.join(parts)}" for c, parts in COMPOSITE_SCRIPTS.items())
    raise ValueError(f"unknown script code {code!r}: use one of {', '.join(plan_scripts())}, "
                     f"or a composite ({composites})")


def _expand_scripts(codes) -> list[str]:
    """A candidate's script codes with every composite's parts added."""
    out = []
    for code in codes:
        for c in [code, *COMPOSITE_SCRIPTS.get(code, ())]:
            if c not in out:
                out.append(c)
    return out


def _license(resolved: list[dict]) -> dict | None:
    lic = next((lb for lb in resolved if lb["kind"] == "license" and lb["mapped"]), None) or \
        next((lb for lb in resolved if lb["kind"] == "license"), None)
    if lic is None:
        return None
    return {"id": lic["mapped"], "raw": lic["raw"], "source": lic["source"], "source_class": "catalog-summary"}


def _genres(resolved: list[dict]) -> list[str]:
    return list(dict.fromkeys(lb["mapped"] for lb in resolved if lb["kind"] in ("genre", "subclass") and lb["mapped"]))


def _user_classed(cand: dict) -> bool:
    """Whether the candidate's genres come from the user's own class (`lazuli class`), which outranks catalogs."""
    return any(lb["source"] == store.USER_SOURCE for lb in cand["labels"] if lb["kind"] in ("genre", "subclass"))


def _installed(conn: sqlite3.Connection) -> dict[str, dict]:
    """Installed families keyed by family name, with faces, measurements, classes, catalog labels, and user classes."""
    extra: dict[str, dict] = defaultdict(lambda: {"i18n": {}, "coverage": [], "postscript": [], "makers": set()})
    for row in conn.execute("SELECT family, names_i18n_json, coverage_json, postscript_name, designer, manufacturer "
                            "FROM local_font WHERE family IS NOT NULL AND family NOT LIKE '.%'"):
        e = extra[row["family"]]
        e["i18n"] = {**json.loads(row["names_i18n_json"] or "{}"), **e["i18n"]}
        e["coverage"].append(json.loads(row["coverage_json"] or "{}"))
        if row["postscript_name"]:
            e["postscript"].append(row["postscript_name"])
        e["makers"].update(m for m in (row["designer"], row["manufacturer"]) if m)
    catalog = labels.by_family(conn)
    out = {}
    for fam in local._families(conn):
        name, e = fam["family"], extra[fam["family"]]
        found = catalog.get(name, {"labels": [], "sources": []})
        out[name] = {
            "family": name, "names_i18n": e["i18n"], "installed": True, "origins": fam["origins"],
            "faces": len(fam["faces"]), "postscript": e["postscript"], "makers": sorted(e["makers"]),
            "scripts": coverage_scripts(e["coverage"]), "classes": fam["classes"],
            "labels": found["labels"], "genres": _genres(found["labels"]), "license": _license(found["labels"]),
            "catalogs": [{"source": s["source"], "family": s["family"], "method": s["method"],
                          "confidence": s["confidence"], "url": s["url"]} for s in found["sources"]],
            "measured": [f for f in fam["faces"] if f.get("kind")], "text_rows": []}
    return out


def _catalog_rows(conn: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    return {(r["source"], r["source_key"]): dict(r) for r in conn.execute("""
        SELECT s.name AS source, s.priority, cf.source_id, cf.source_key, cf.family, cf.names_i18n_json,
               cf.foundry, cf.designers_json, cf.url
        FROM catalog_family cf JOIN source s ON s.id = cf.source_id""")}


def _catalog_labels(conn: sqlite3.Connection, rows: list[dict], everything: bool) -> dict[tuple[int, str], list]:
    out: dict[tuple[int, str], list] = defaultdict(list)
    if everything:
        for r in conn.execute("SELECT source_id, source_key, kind, raw, mapped FROM catalog_label"):
            out[(r["source_id"], r["source_key"])].append(r)
        return out
    for row in rows:
        key = (row["source_id"], row["source_key"])
        out[key] = conn.execute("SELECT source_id, source_key, kind, raw, mapped FROM catalog_label "
                                "WHERE source_id = ? AND source_key = ?", key).fetchall()
    return out


def _catalog_only(conn: sqlite3.Connection, rows: list[dict], everything: bool) -> dict[str, dict]:
    """Catalog families no installed face matched, merged across catalogs by normalized name, with the user's
    label of that name."""
    by_key = _catalog_labels(conn, rows, everything)
    mine = store.user_labels(conn)
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: (r["priority"], r["family"])):
        groups[norm(row["family"]) or row["family"]].append(row)
    out = {}
    for key, group in groups.items():
        label_rows = [{"kind": lb["kind"], "raw": lb["raw"], "mapped": lb["mapped"], "source": row["source"],
                       "priority": row["priority"], "confidence": 1.0}
                      for row in group for lb in by_key.get((row["source_id"], row["source_key"]), ())]
        label_rows += store.user_label_rows(mine.get(key))
        resolved = labels.resolve(label_rows) if label_rows else []
        i18n: dict = {}
        for row in group:
            i18n = {**json.loads(row["names_i18n_json"] or "{}"), **i18n}
        makers = [m for row in group for m in [row["foundry"], *json.loads(row["designers_json"] or "[]")] if m]
        out["catalog:" + key] = {
            "family": group[0]["family"], "names_i18n": i18n, "installed": False, "origins": [], "faces": 0,
            "postscript": [], "makers": list(dict.fromkeys(makers)), "scripts": label_scripts(resolved),
            "classes": [], "labels": resolved, "genres": _genres(resolved), "license": _license(resolved),
            "catalogs": [{"source": r["source"], "family": r["family"], "url": r["url"]} for r in group],
            "measured": [], "text_rows": group}
    return out


def _delivery(cand: dict) -> dict[str, list[str]]:
    lic = (cand["license"] or {}).get("id")
    catalogs = {c["source"] for c in cand["catalogs"]}
    web, app = [], []
    if "google-fonts" in catalogs:
        web.append("google-fonts-api")
    if lic in OPEN_LICENSES:
        web.append("self-host")
        app.append("app-bundle")
    if "adobe-sync" in cand["origins"] or "adobe-cjk" in catalogs:
        web.append("adobe-web-project")
    if "system" in cand["origins"] or lic == "system":
        app.append("system-only")
    return {"web": web, "app": app}


# ---------------------------------------------------------------- matching and filters

def _text_match(query: str, cand: dict) -> tuple[float, list[str]]:
    """(strength, evidence) of QUERY against a candidate's names, labels, classes, and makers."""
    q_norm, q_fold = norm(query) or "", query.strip().casefold()
    hits: list[tuple[float, str]] = []
    names = [cand["family"], *cand["names_i18n"].values()]
    for row in cand["text_rows"]:
        names += [row["family"], *json.loads(row["names_i18n_json"] or "{}").values()]
    for name in dict.fromkeys(n for n in names if n):
        key = norm(name) or ""
        if q_norm and key == q_norm:
            hits.append((1.0, f"name {name!r}"))
        elif q_norm and key.startswith(q_norm):
            hits.append((0.85, f"name {name!r} starts with {query!r}"))
        elif q_norm and q_norm in key:
            hits.append((0.7, f"name {name!r} contains {query!r}"))
    for ps in cand["postscript"]:
        if q_norm and q_norm in (norm(ps) or ""):
            hits.append((0.6, f"PostScript name {ps!r}"))
            break
    for lb in cand["labels"]:
        mapped = (lb["mapped"] or "").casefold()
        if q_fold and (q_fold in lb["raw"].casefold() or (mapped and q_fold in mapped)):
            shown = lb["raw"] + (f" = {lb['mapped']}" if lb["mapped"] and lb["mapped"] != lb["raw"] else "")
            hits.append((0.5, f"{lb['kind']} label {shown!r} ({lb['source']})"))
    for cls in cand["classes"]:
        if q_fold == cls:
            hits.append((0.45, f"measured {cls}"))
    makers = cand["makers"] + [m for row in cand["text_rows"]
                               for m in [row["foundry"], *json.loads(row["designers_json"] or "[]")] if m]
    for maker in dict.fromkeys(makers):
        if q_fold and q_fold in maker.casefold():
            hits.append((0.4, f"foundry or designer {maker!r}"))
    hits.sort(key=lambda h: -h[0])
    return (hits[0][0] if hits else 0.0), list(dict.fromkeys(text for _, text in hits))


def _filters(cand: dict, args) -> tuple[bool, list[str]]:
    """Whether the candidate passes every filter, and the evidence for the ones it passes."""
    why = []
    classes = set(cand["genres"]) | set(cand["classes"]) | {g.split(".", 1)[0] for g in cand["genres"]}
    kinds = {f.get("kind") for f in cand["measured"]} - {None, "text"}
    if args.installed and not cand["installed"]:
        return False, why
    if args.script:
        parts = script_parts(args.script)
        if not set(parts) <= set(_expand_scripts(cand["scripts"])):
            return False, why
        code = args.script.lower()
        shown = code if parts == (code,) else f"{code} = {' + '.join(parts)}"
        why.append(f"script {shown} (" + ("installed coverage" if cand["installed"] else "catalog subsets") + ")")
    user = _user_classed(cand)
    labeled = "user class" if user else "catalog"
    if args.category:
        wanted = args.category.lower()
        if wanted not in classes and not any(g.startswith(wanted + ".") for g in cand["genres"]):
            return False, why
        how = ("user class" if user else "catalog label") \
            if wanted in cand["genres"] or any(g.startswith(wanted + ".") for g in cand["genres"]) else "measured"
        why.append(f"category {wanted} ({how})")
    if args.role:
        # catalog classes are curated and the user's label outranks them, so they decide when present; measured
        # serif/sans is coarse, and a measured `hand` kind comes only from a name hint, which never excludes a
        # family on its own
        top = {g.split(".", 1)[0] for g in cand["genres"]}
        basis, known = (labeled, top) if top else ("measured", (set(cand["classes"]) | kinds) - {"hand"})
        if args.role == "code":
            if "mono" not in top | set(cand["classes"]):
                return False, why
            why.append("role code: monospaced (" + (labeled if "mono" in top else "measured") + ")")
        elif args.role in TEXT_ROLES:
            text = known & TEXT_CLASSES
            if not text and known & NON_TEXT_CLASSES:
                return False, why
            why.append(f"role {args.role}: " + (f"text class {', '.join(sorted(text))} ({basis})" if text
                                                 else "class not known")
                       + ("; the name suggests hand" if basis == "measured" and "hand" in kinds else ""))
    lic = cand["license"]
    if args.license == "open":
        if not lic or lic["id"] not in OPEN_LICENSES:
            return False, why
        why.append(f"license {lic['id']} ({lic['source']} summary; confirm the original)")
    if args.delivery:
        paths_known = cand["delivery"][args.delivery]
        if not paths_known:
            return False, why
        why.append(f"{args.delivery} via {', '.join(paths_known)}")
    return True, why


def _span(weights) -> str:
    low, high = min(weights), max(weights)
    return str(low) if low == high else f"{low}–{high}"


def catalog_weights(resolved: list[dict]) -> dict[int, str]:
    """Upright weights the catalog labels give, {weight: source}: `weight:<n>` labels and, for a wght axis
    range, every hundred inside it."""
    out: dict[int, str] = {}
    for lb in resolved:
        mapped = lb.get("mapped") or ""
        if mapped.startswith("weight:") and mapped[7:].isdigit():
            out.setdefault(int(mapped[7:]), lb["source"])
        elif mapped == "axis:wght" and (hit := _WGHT_AXIS.fullmatch(lb["raw"].strip())):
            low, high = float(hit[1]), float(hit[2])
            for weight in range(math.ceil(low / 100) * 100, int(high) + 1, 100):
                out.setdefault(weight, lb["source"])
    return out


def _stroke(face: dict) -> str | None:
    return (face.get("panose") or {}).get("weight")


def role_fit(cand: dict, role: str) -> tuple[float, list[str]]:
    """How the family's known weights suit the role: a score adjustment and its evidence (module doc, --role)."""
    if role not in TEXT_ROLES and role not in DISPLAY_ROLES:
        return 0.0, []
    faces = cand["measured"]
    upright = [f for f in faces if not f.get("metrics", {}).get("italic")]
    installed = {w for f in upright if (w := f.get("metrics", {}).get("weight_class"))}
    catalog = catalog_weights(cand["labels"])
    weights = sorted(installed | set(catalog))
    if role in DISPLAY_ROLES:
        if bold := [w for w in weights if w >= 600]:
            return FIT_BOLD, [f"role {role}: bold face available ({_span(bold)})"]
        if heavy := next((s for f in upright if (s := _stroke(f)) in HEAVY_STROKES), None):
            return FIT_BOLD, [f"role {role}: {heavy} strokes measured"]
        return 0.0, []
    adjust, why = 0.0, []
    low, high = REGULAR_WEIGHTS
    regular_faces = [f for f in upright if low <= (f.get("metrics", {}).get("weight_class") or 0) <= high]
    strokes = [s for f in regular_faces if (s := _stroke(f))]
    regular = sorted((w for w in weights if low <= w <= high), key=lambda w: abs(w - 400))
    if strokes and (all(s in HEAVY_STROKES for s in strokes) or all(s in LIGHT_STROKES for s in strokes)):
        face = next(f for f in regular_faces if _stroke(f))       # the regular weight class, not the regular look
        ratio = face["metrics"].get("weight_rat")
        adjust += FIT_NO_REGULAR
        why.append(f"no regular upright face: the {face['metrics']['weight_class']} face measures {_stroke(face)}"
                   + (f" (weight ratio {ratio:g})" if ratio else ""))
    elif regular:
        adjust += FIT_REGULAR
        why.append(f"regular upright face {regular[0]} "
                   f"({'installed' if regular[0] in installed else catalog[regular[0]]})")
    elif weights and (weights[0] >= HEAVY_ONLY or weights[-1] <= LIGHT_ONLY):
        adjust += FIT_NO_REGULAR
        why.append(f"no regular upright face (only {_span(weights)})")
    elif weights:
        why.append(f"no regular upright face ({', '.join(map(str, weights))})")
    elif faces and not upright:
        why.append("no regular upright face (italic only)")
    else:
        why.append("weights unknown")
    if len(weights) > 1:
        adjust += min(FIT_PER_WEIGHT * (len(weights) - 1), FIT_WEIGHTS_MAX)
        why.append(f"{len(weights)} weights ({_span(weights)})")
    if classed := sorted({g.split(".", 1)[0] for g in cand["genres"]} & {"display", "hand"}):
        adjust += FIT_CLASSED
        why.append(f"the catalog also classifies it {' and '.join(classed)}")
    return adjust, why



def _faces(count: int) -> str:
    return f"{count} face{'s' if count != 1 else ''}"


def _representative(faces: list[dict]) -> dict | None:
    """The measured face nearest a regular upright weight (OS/2 class, then a Regular-like subfamily)."""
    if not faces:
        return None
    return min(faces, key=lambda f: (bool(f.get("metrics", {}).get("italic")),
                                     abs((f.get("metrics", {}).get("weight_class") or 400) - 400),
                                     (f.get("subfamily") or "").casefold() not in REGULAR_NAMES))


def features(face: dict) -> dict[str, tuple[float, float]]:
    """{feature: (scaled value, raw value)} for the measured features a face has."""
    out = {}
    for part, key, step, logarithm in FEATURES:
        raw = (face.get(part) or {}).get(key)
        if raw is None:
            continue
        value = float(raw)
        if logarithm:
            if value <= 0:
                continue
            value = math.log(value)
        out[key] = (value / step, float(raw))
    return out


def distance(target: dict, other: dict) -> tuple[float, list[tuple[str, float]], list[str]] | None:
    """Root mean square difference in steps over the target's features, the per-feature differences of the
    shared ones, and the target features the other face lacks (each counts MISSING_STEP)."""
    shared = [k for k in target if k in other]
    if len(shared) < MIN_SHARED_FEATURES:
        return None
    missing = [k for k in target if k not in other]
    diffs = sorted(((k, abs(target[k][0] - other[k][0])) for k in shared), key=lambda d: d[1])
    total = sum(d * d for _, d in diffs) + MISSING_STEP ** 2 * len(missing)
    return math.sqrt(total / len(target)), diffs, missing


def _similarity_evidence(target: str, d: float, diffs, missing: list[str], mine: dict, theirs: dict) -> str:
    closest = ", ".join(k for k, delta in diffs[:3] if delta < 0.5) or "none within half a step"
    far = [f"{k} {theirs[k][1]:g} vs {mine[k][1]:g}" for k, delta in reversed(diffs[-2:]) if delta >= 0.5]
    return (f"distance {d:.2f} to {target} over {len(diffs)} measured features; close: {closest}"
            + (f"; apart: {'; '.join(far)}" if far else "")
            + (f"; not measured here: {', '.join(missing)}" if missing else ""))


def search_fonts(conn: sqlite3.Connection, args) -> tuple[list[dict], list[str]]:
    notes = []
    installed = _installed(conn)
    rows = _catalog_rows(conn)
    if not installed:
        notes.append("no installed fonts in the lazuli DB yet; run `lazuli local fonts`")
    if not rows:
        notes.append("no catalog is synced yet; run `lazuli catalog sync`")
    matched: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in conn.execute("""SELECT DISTINCT s.name AS source, m.source_key, lf.family FROM match m
                             JOIN source s ON s.id = m.source_id JOIN local_font lf ON lf.id = m.local_font_id
                             WHERE lf.family IS NOT NULL"""):
        matched[(r["source"], r["source_key"])].add(r["family"])
    if args.query:
        keys = {(r["source"], r["source_key"]) for r in store.search(conn, args.query, limit=CATALOG_HITS)}
        in_scope = [rows[k] for k in keys if k in rows]
    else:
        in_scope = list(rows.values())
    for row in in_scope:                               # a matched catalog family speaks for the installed one
        for family in matched.get((row["source"], row["source_key"]), ()):
            if family in installed:
                installed[family]["text_rows"].append(row)
    unmatched = [] if args.installed else [r for r in in_scope if (r["source"], r["source_key"]) not in matched]
    candidates = list(installed.values()) + list(_catalog_only(conn, unmatched, not args.query).values())

    target = None
    if args.similar_to:
        key = norm(args.similar_to)
        target = next((c for c in installed.values()
                       if key in {norm(n) for n in [c["family"], *c["names_i18n"].values()] if n}), None)
        if target is None:
            raise LookupError(f"{args.similar_to!r} is not an installed family in the lazuli DB; --similar-to "
                              "compares measurements, which only installed fonts have")
        face = _representative(target["measured"])
        if face is None or len(features(face)) < MIN_SHARED_FEATURES:
            raise LookupError(f"{target['family']!r} has no measurements yet; run `lazuli local fonts`")
        mine = features(face)
        if any(not c["installed"] for c in candidates):
            notes.append("catalog-only families have no measurements and are left out of --similar-to")

    out = []
    for cand in candidates:
        cand["delivery"] = _delivery(cand)
        evidence: list[str] = []
        if args.query:
            strength, text = _text_match(args.query, cand)
            if not strength:
                if not cand["text_rows"]:                 # store.search hit a phrase across two labels
                    continue
                strength, text = 0.3, [f"catalog text contains {args.query!r}"]
            evidence += text
        else:
            strength = 0.5
        passes, why = _filters(cand, args)
        if not passes:
            continue
        evidence += why
        if args.role:                                  # under --similar-to, distance alone ranks
            fit, fit_why = role_fit(cand, args.role)
            strength += fit
            evidence += fit_why
        if target is not None:
            if cand is target or not cand["installed"]:
                continue
            face = _representative(cand["measured"])
            theirs = features(face) if face else {}
            measured = distance(mine, theirs)
            if measured is None:
                continue
            cand["distance"] = round(measured[0], 3)
            strength = 1 / (1 + measured[0])
            evidence.insert(0, _similarity_evidence(target["family"], *measured, mine, theirs))
        if _user_classed(cand):
            evidence.append(f"class {', '.join(cand['genres'])} (user class)")
        if cand["installed"]:
            evidence.append(f"installed ({', '.join(cand['origins'])}; {_faces(cand['faces'])})")
            strength += 0.05 if target is None else 0
        for c in cand["catalogs"][:3]:
            how = f", {c['method']}" if c.get("method") else ""
            evidence.append(f"listed in {c['source']} as {c['family']!r}{how}")
        if cand["license"] and args.license != "open":
            lic = cand["license"]
            evidence.append(f"license {lic['id'] or repr(lic['raw'])} ({lic['source']} summary, a hint)")
        cand["rank"] = strength                        # uncapped, so bonuses still order capped scores
        cand["score"] = round(max(0.0, min(strength, 1.0)), 3)
        cand["evidence"] = list(dict.fromkeys(evidence))
        out.append(cand)
    priority = {name: p for name, p in conn.execute("SELECT name, priority FROM source")}
    out.sort(key=lambda c: (c.get("distance", 0), -c["rank"], not c["installed"],
                            min((priority.get(s["source"], 99) for s in c["catalogs"]), default=99),
                            c["family"].casefold()))
    return out[:args.limit], notes


# ---------------------------------------------------------------- output

PUBLIC_FIELDS = ("family", "names_i18n", "installed", "origins", "faces", "scripts", "classes", "genres",
                 "license", "catalogs", "delivery", "score", "distance", "evidence")


def _public(cand: dict) -> dict:
    return {k: cand[k] for k in PUBLIC_FIELDS if k in cand}


def _text(candidates: list[dict], args, notes: list[str]) -> str:
    what = f"{args.query!r}" if args.query else "the filters"
    if args.similar_to:
        what += f", nearest to {args.similar_to!r}" if args.query else f" nearest to {args.similar_to!r}"
    lines = [f"{len(candidates)} font candidate{'s' if len(candidates) != 1 else ''} for {what}"]
    for i, c in enumerate(candidates, 1):
        where = (f"installed: {', '.join(c['origins'])}, {_faces(c['faces'])}" if c["installed"]
                 else "catalog: " + ", ".join(dict.fromkeys(s["source"] for s in c["catalogs"])))
        lines.append(f"{i:2}. {c['family']}  [{where}]  score {c['score']:.2f}")
        lines.append("    why: " + "; ".join(c["evidence"]))
        facts = []
        if c["scripts"]:
            facts.append("scripts " + ", ".join(c["scripts"]))
        for use in ("web", "app"):
            if c["delivery"][use]:
                facts.append(f"{use} " + ", ".join(c["delivery"][use]))
        if facts:
            lines.append("    " + " · ".join(facts))
    lines += [f"note: {n}" for n in notes]
    return "\n".join(lines)


def _parser(prog: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=prog, description="Ranked font candidates with the evidence for each, from "
                                 "local fonts and synced catalogs (--type color|source for the other searches).")
    ap.add_argument("--type", choices=TYPES, default="font", help="what to search (default: font)")
    ap.add_argument("query", nargs="?", metavar="QUERY", help="name, label, class, foundry, or designer text")
    ap.add_argument("--script", metavar="CODE", help=f"ISO 15924 code of the plan list ({', '.join(plan_scripts())}) "
                                                     f"or a composite ({', '.join(COMPOSITE_SCRIPTS)})")
    ap.add_argument("--role", choices=ROLES)
    ap.add_argument("--category", metavar="CLASS", help="serif, sans, slab, mono, display, hand, bu-ri, min-bu-ri, "
                                                        "or a subclass such as min-bu-ri.rounded")
    ap.add_argument("--license", choices=("open", "any"), default="any")
    ap.add_argument("--delivery", choices=("web", "app"), help="only families with a known delivery path there")
    ap.add_argument("--installed", action="store_true", help="installed families only")
    ap.add_argument("--similar-to", metavar="FAMILY", help="rank installed families by measured-feature distance")
    ap.add_argument("--limit", type=int, default=20, metavar="N")
    ap.add_argument("--json", action="store_true", help="machine output")
    return ap


def main(argv: list[str] | None = None, prog: str = "lazuli search") -> int:
    argv = sys.argv[1:] if argv is None else argv
    kind, rest = split_type(argv)
    ap = _parser(prog)
    if kind not in TYPES:
        ap.error(f"argument --type: invalid choice: {kind!r} (choose from {', '.join(TYPES)})")
    if kind in BACKENDS:
        backend = importlib.import_module(BACKENDS[kind])        # at dispatch: the font path never needs it
        return backend.search_main(rest, prog=f"{prog} --type {kind}")
    args = ap.parse_args(rest)
    if args.limit < 1:
        ap.error("--limit must be at least 1")
    if args.script:
        try:
            script_parts(args.script)
        except ValueError as exc:
            ap.error(f"argument --script: {exc}")
        args.script = args.script.lower()
    if not args.query and not (args.script or args.role or args.category or args.license == "open"
                               or args.delivery or args.installed or args.similar_to):
        ap.error("give QUERY or at least one filter")
    conn = db.connect(paths.db_path())
    try:
        candidates, notes = search_fonts(conn, args)
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        conn.close()
    if args.json:
        filters = {k: getattr(args, k) for k in ("script", "role", "category", "license", "delivery", "installed",
                                                 "similar_to", "limit")}
        json.dump({"type": "font", "query": args.query, "filters": filters,
                   "candidates": [_public(c) for c in candidates], "notes": notes},
                  sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        print(_text(candidates, args, notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
