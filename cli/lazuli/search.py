"""`lazuli search`: ranked font candidates, with why each matched, from local fonts and synced catalogs.

`--type color` and `--type source` hand the other arguments to `lazuli.color.search_main` and
`lazuli.sources.search_main` unchanged (only the `--type` option is removed).

Fonts (the default type) come from the lazuli DB only; the command never scans or fetches. An installed
family carries the catalog families its faces matched; a catalog family no installed face matched is its
own candidate, merged across catalogs by normalized name. A name on the owned list (`lazuli owned`) that is not
installed is a candidate too when QUERY matches it, shown as `needs activation` with no scripts or classes (only a
name is known); an installed family on the list says so in its evidence. The user's own class of a family (`lazuli class`,
source `user`) replaces the catalogs' genre and subclass, and the evidence names it. QUERY matches,
strongest first: a family or i18n name (equal, prefix, substring), a PostScript name, a catalog or user
label (raw or mapped), a measured class, a foundry or designer. Filters:
  --script     an ISO 15924 code of the plan list (plan/schema.yaml: latn, cyrl, grek, hang, kana, hani, arab,
               hebr, thai) or a composite that stands for its parts: kore = hang, jpan = kana + hani, hans and
               hant = hani, hrkt = kana (a family needs every part). Other codes are refused (exit 2).
               Installed families by coverage (`lazuli.lock.coverage_scripts`), catalog families by their
               `script:` labels, whose composites expand the same way.
               A family counts only for a script it is designed for, its primary script: Google Fonts states one for
               families whose own script is not Latin (`primaryScript`, kept as `details.primary_script`; a Thai, Gujarati,
               or Korean-first family that merely has a Latin subset is no Latin candidate), and installed faces that
               cover a full Hangul, kana, Han, or Thai set count as made for those scripts. A family with no such
               statement counts for every script it covers. A note says how many families the rule left out.
  --secondary-scripts  count a family for --script when it merely covers the script, though its primary script is another.
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
               Equal scores are ordered by role-fit keys, best first, with the name only the last key. display: a catalog
               or user class of display, the heaviest known weight, the strongest `/Expressive/` tag weight (Google Fonts,
               0-100), the number of known weights; heading: the heaviest weight, the mean of the `/Quality/` Drawing,
               Spacing, and Wordspace tag weights, the number of weights; body, ui, data, caption: that quality mean, the
               number of weights. Then the more popular family (the less popular one among less-known), installed before
               catalog, the catalog's priority, and the name. Each result's evidence names the keys it has.
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
  --by-familiarity  list familiar and less-known candidates side by side, and some that no catalog ranks: a quarter
               of `--limit` (rounded down) for the unknown ones, then half of the rest for each of the other two
               tiers (familiar takes the odd one), a tier with fewer candidates giving its slots to less-known,
               then familiar, then unknown, grouped under a heading per tier. A candidate's familiarity is a tier
               plus its basis, whether or not this option is given (JSON `familiarity`): `familiar` is the top
               quarter of a catalog's ranked popularity (Google Fonts `popularity`, where a LOWER number is MORE
               popular) or a place on a chart such as 안심글꼴's 인기글꼴 TOP20; `less-known` is a ranked family
               below that. A family whose own catalog states no popularity (Fontsource, Fontshare, 안심글꼴, GitHub)
               takes the rank of the one Google Fonts family its name matches; with none, it is `unknown`: no
               catalog says how familiar it is, which is not the same as obscure, so it is never listed as
               less-known, and it has a share of its own so that catalogs with no popularity still reach the list.
               Among less-known candidates of equal rank the less popular comes first.
               Without --installed, uninstalled catalog families keep a share of the list: in each tier of two or more
               slots at least one when one matches; the unknown slots go to catalog families before installed ones,
               one catalog at a time (each catalog's best first, so GitHub foundries or 안심글꼴 reach a short list);
               without --by-familiarity a quarter of --limit (rounded down) is kept for them. Installed families fill
               the rest, and `--installed` lists installed families only, as before.
Exit codes: 0 searched (even with no candidates); 2 usage or missing input.
"""
from __future__ import annotations

import argparse
import bisect
import functools
import importlib
import itertools
import json
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict

import yaml

from lapis_design import shared_dir
from lazuli import db, local, owned, paths
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
FAMILIAR_SHARE = 0.25               # the top quarter of a catalog's ranked families is familiar
TIERS = ("familiar", "less-known", "unknown")
# ISO 15924 composites and the plan codes they stand for (a family needs every part)
COMPOSITE_SCRIPTS = {"kore": ("hang",), "jpan": ("kana", "hani"), "hans": ("hani",), "hant": ("hani",),
                     "hrkt": ("kana",)}
CATALOG_HITS = 500                  # catalog families store.search may return for one query
DEFAULT_LIMIT = 8                   # candidates listed by default: an agent re-reads every line it prints

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

# Primary script and tie-breaking (see --script and --role in the module doc)
PRIMARY_PARTS = {**COMPOSITE_SCRIPTS, "hira": ("kana",)}     # Google Fonts' codes; Hira is a Japanese-first family's kana
NATIVE_FIRST = ("hang", "kana", "hani", "thai")              # a full measured set marks a face made for the script
TAG_QUALITY = ("/Quality/Drawing", "/Quality/Spacing", "/Quality/Wordspace")
NO_POSITION = 10 ** 9                                        # popularity position of a family no catalog ranks


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


def _license_evidence(cand: dict) -> str:
    """The license line of a candidate's evidence. A `custom-free` license is a listing's own free-text conditions,
    so the text itself is the evidence, verbatim, with the page it was read on."""
    lic = cand["license"]
    if lic["id"] != "custom-free":
        return f"license {lic['id'] or repr(lic['raw'])} ({lic['source']} summary, a hint; confirm the original)"
    page = next((c["details"]["conditions_url"] for c in cand["catalogs"]
                 if c["source"] == lic["source"] and (c.get("details") or {}).get("conditions_url")), None)
    return (f"license custom-free: the {lic['source']} listing's conditions, verbatim: " + " / ".join(lic["raw"].splitlines())
            + (f" ({page})" if page else "") + "; free of charge, not an open license")


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
               cf.foundry, cf.designers_json, cf.url, cf.signals_json, cf.details_json
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
        how = "installed coverage" if cand["installed"] else "catalog subsets"
        if primary := cand.get("primary"):
            own = f"{', '.join(primary['codes'])} ({primary['basis']})"
            if set(parts) <= primary["scripts"]:
                how += f"; primary script {own}"
            elif args.secondary_scripts:
                how += f"; secondary: its primary script is {own}"
            else:
                cand["off_primary"] = True
                return False, why
        why.append(f"script {shown} ({how})")
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


def _known_weights(cand: dict) -> tuple[list, list, set, dict, list]:
    """(measured faces, upright ones, installed upright weight classes, catalog weights, all known weights sorted)."""
    faces = cand["measured"]
    upright = [f for f in faces if not f.get("metrics", {}).get("italic")]
    installed = {w for f in upright if (w := f.get("metrics", {}).get("weight_class"))}
    catalog = catalog_weights(cand["labels"])
    return faces, upright, installed, catalog, sorted(installed | set(catalog))


def _row_details(row: dict) -> dict:
    return json.loads(row.get("details_json") or "{}")


def _primary(cand: dict, rows: list[dict]) -> dict | None:
    """The script(s) the family is designed for, {"codes", "scripts" (with composites' parts), "basis"}, or None when
    nothing says: a catalog's own statement first, else an installed face with a full Hangul, kana, Han, or Thai set."""
    stated: dict[str, str] = {}
    for row in rows:
        if code := _row_details(row).get("primary_script"):
            stated.setdefault(code, row["source"])
    if stated:
        scripts = {part for code in stated for part in (code, *PRIMARY_PARTS.get(code, ()))}
        return {"codes": list(stated), "scripts": scripts,
                "basis": f"{', '.join(dict.fromkeys(stated.values()))} primaryScript"}
    if cand["installed"] and (native := [s for s in cand["scripts"] if s in NATIVE_FIRST]):
        return {"codes": native, "scripts": set(native), "basis": f"measured: full {', '.join(native)} coverage"}
    return None


def tag_weights(conn: sqlite3.Connection) -> dict[tuple[int, str], dict[str, float]]:
    """{(source_id, source_key): {tag: weight}} of the Google Fonts /Expressive and /Quality tags (0-100), the
    largest over a tag's axis positions."""
    out: dict[tuple[int, str], dict[str, float]] = defaultdict(dict)
    for r in conn.execute("SELECT source_id, source_key, raw, weight FROM catalog_label WHERE weight IS NOT NULL "
                          "AND (raw LIKE '/Expressive/%' OR raw LIKE '/Quality/%')"):
        tag, mine = r["raw"].split(" ", 1)[0], out[(r["source_id"], r["source_key"])]
        mine[tag] = max(mine.get(tag, 0.0), r["weight"])
    return out


def role_fit_key(cand: dict, role: str, tags: dict) -> tuple[tuple, list[str]]:
    """(keys, evidence): the role-fit keys that order equal scores, larger first (module doc, --role)."""
    if role not in TEXT_ROLES and role not in DISPLAY_ROLES:
        return (), []
    weights = _known_weights(cand)[4]
    mine: dict[str, float] = {}
    for row in cand["rows"]:
        for tag, weight in tags.get((row["source_id"], row["source_key"]), {}).items():
            mine[tag] = max(mine.get(tag, 0.0), weight)
    expressive = max((w for t, w in mine.items() if t.startswith("/Expressive/")), default=0.0)
    quality = [mine[t] for t in TAG_QUALITY if t in mine]
    quality = sum(quality) / len(quality) if quality else 0.0
    heaviest, count = (max(weights) if weights else 0), len(weights)
    classed = int(role == "display" and "display" in {g.split(".", 1)[0] for g in cand["genres"]})
    named = {"display class": (classed, "display class" if classed else ""),
             "heaviest weight": (heaviest // 100, f"heaviest weight {heaviest}" if heaviest else ""),
             "expressive tag": (expressive, f"expressive tag {expressive:g}" if expressive else ""),
             "quality tags": (quality, f"quality tags {quality:.0f}" if quality else ""),
             "weights": (count, f"{count} weights" if count else "")}
    order = {"display": ("display class", "heaviest weight", "expressive tag", "weights"),
             "heading": ("heaviest weight", "quality tags", "weights")}.get(role, ("quality tags", "weights"))
    shown = [named[name][1] for name in order if named[name][1]]
    return tuple(named[name][0] for name in order), ([f"tie-break keys: {', '.join(shown)}"] if shown else [])


def role_fit(cand: dict, role: str) -> tuple[float, list[str]]:
    """How the family's known weights suit the role: a score adjustment and its evidence (module doc, --role)."""
    if role not in TEXT_ROLES and role not in DISPLAY_ROLES:
        return 0.0, []
    faces, upright, installed, catalog, weights = _known_weights(cand)
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


# ---------------------------------------------------------------- familiarity

TIER_HEADINGS = {"familiar": "familiar (top quarter of a catalog's popularity ranking, or on a chart)",
                 "less-known": "less-known (ranked below the top quarter)",
                 "unknown": "unknown familiarity (no synced catalog says how familiar they are; not the same as obscure)"}


def _row_signals(row: dict) -> dict:
    return json.loads(row.get("signals_json") or "{}")


def _row_names(row: dict) -> list[str]:
    return [n for n in [row["family"], *json.loads(row["names_i18n_json"] or "{}").values()] if n]


class Familiarity:
    """How familiar a family is, from the popularity the catalogs state (`CatalogFamily.signals`).

    A `rank` source (Google Fonts) gives every family a number where lower is more popular; the top
    FAMILIAR_SHARE of its ranked families, by position, is familiar and the rest less-known. A `chart`
    source lists only its top N, so a listed family is familiar and an unlisted one says nothing. A family
    whose own rows state nothing takes the verdict of the one ranked catalog family its name matches
    (several matches say nothing). No verdict is `unknown`, never less-known.
    """

    def __init__(self, rows):
        self.ranks: dict[str, list[int]] = defaultdict(list)
        self.by_name: dict[str, dict[tuple[str, str], dict]] = defaultdict(dict)
        for row in rows:
            signals = _row_signals(row)
            if signals.get("popularity_kind") == "rank" and isinstance(signals.get("popularity"), int):
                self.ranks[row["source"]].append(signals["popularity"])
                for name in _row_names(row):
                    if key := norm(name):
                        self.by_name[key][(row["source"], row["source_key"])] = row
        for ranks in self.ranks.values():
            ranks.sort()

    def _verdict(self, row: dict, via: str = "") -> dict | None:
        signals = _row_signals(row)
        popularity, source = signals.get("popularity"), row["source"]
        if not isinstance(popularity, int):
            return None
        if signals.get("popularity_kind") == "chart":
            return {"tier": "familiar", "source": source, "rank": popularity,
                    "basis": f"{via}{source} {signals.get('popularity_list') or 'chart'} no. {popularity}"}
        if signals.get("popularity_kind") != "rank":
            return None
        ranks = self.ranks[source]
        position = bisect.bisect_left(ranks, popularity) + 1
        tier = "familiar" if position / len(ranks) <= FAMILIAR_SHARE else "less-known"
        return {"tier": tier, "source": source, "rank": popularity, "position": position, "of": len(ranks),
                "basis": f"{via}{source} popularity {popularity}, position {position} of {len(ranks)}"}

    def of(self, rows: list[dict], names: list[str]) -> dict:
        """{"tier", and for a known tier "basis", "source", "rank", and for a rank "position" and "of"} from the
        candidate's own catalog rows, else from the ranked family its names match."""
        found = [v for row in rows if (v := self._verdict(row))]
        if not found:
            matches: dict[tuple[str, str], dict] = {}
            for name in [*names, *(n for row in rows for n in _row_names(row))]:
                if key := norm(name):
                    matches.update(self.by_name.get(key, {}))
            if len(matches) == 1:
                (row,) = matches.values()
                found = [self._verdict(row, f"by name, {row['family']!r}: ")]
        if not found:
            return {"tier": "unknown"}
        return min(found, key=lambda v: (TIERS.index(v["tier"]), v.get("position", 0)))


def _is_catalog(cand: dict) -> bool:
    return not cand["installed"] and not cand.get("owned")


def _popularity(cand: dict) -> int:
    """Position in the popularity ranking, smaller is more popular; a chart family counts as the most popular and a
    family no catalog ranks as the least."""
    familiarity = cand["familiarity"]
    return familiarity.get("position", 0 if familiarity["tier"] == "familiar" else NO_POSITION)


def _order(cand: dict, less_popular_first: bool = False) -> tuple:
    """The sort key: distance, score, role-fit keys (larger first), popularity, installed before catalog, the catalog's
    priority, and the name last."""
    popularity = _popularity(cand)
    return (cand.get("distance", 0), -round(cand["rank"], 3), *(-key for key in cand["fit"]),
            -popularity if less_popular_first else popularity, not cand["installed"], cand["order_priority"],
            cand["family"].casefold())


def _with_catalog(pool: list[dict], take: int, want: int) -> list[dict]:
    """The first `take` of the ranked POOL, with at least `want` uninstalled catalog candidates: the best ones beyond
    the first `take` replace the lowest installed ones, and the pool's order is kept."""
    chosen = list(range(min(take, len(pool))))
    have = sum(_is_catalog(pool[i]) for i in chosen)
    extra = [i for i in range(len(chosen), len(pool)) if _is_catalog(pool[i])][:max(0, want - have)]
    drop = [i for i in reversed(chosen) if not _is_catalog(pool[i])][:len(extra)]
    return [pool[i] for i in sorted((set(chosen) - set(drop)) | set(extra))]


def _spread(pool: list[dict]) -> list[dict]:
    """POOL with the uninstalled catalog candidates first, one catalog at a time (each catalog's best first, the
    catalogs in the order of their best), then the installed ones, so that a catalog with few or weaker candidates
    still reaches a short list."""
    by_catalog: dict[str, list[dict]] = defaultdict(list)
    for cand in pool:
        if _is_catalog(cand):
            by_catalog[cand["catalogs"][0]["source"]].append(cand)
    spread = [c for round_ in itertools.zip_longest(*by_catalog.values()) for c in round_ if c is not None]
    return spread + [c for c in pool if not _is_catalog(c)]


def _balanced(out: list[dict], limit: int) -> list[dict]:
    """`limit` candidates with familiar and less-known ones side by side, and some no catalog ranks
    (`--by-familiarity`): a quarter of the slots (rounded down) for unknown ones, then half of the rest for each
    of the other two (the odd one to familiar); a tier with fewer candidates gives its slots to less-known, then
    familiar, then unknown. Candidates keep their rank order inside a tier, except that among less-known ones of
    equal rank the less popular comes first. A tier of two or more slots holds at least one uninstalled catalog
    candidate when one matches, and the unknown slots go to catalog candidates before installed ones, one catalog at
    a time."""
    tiers = {t: [c for c in out if c["familiarity"]["tier"] == t] for t in TIERS}
    tiers["less-known"].sort(key=lambda c: _order(c, less_popular_first=True))
    tiers["unknown"] = _spread(tiers["unknown"])
    unknown = min(len(tiers["unknown"]), limit // 4)
    rest = limit - unknown
    take = {"familiar": min(len(tiers["familiar"]), -(-rest // 2)), "less-known": min(len(tiers["less-known"]), rest // 2),
            "unknown": unknown}
    free = limit - sum(take.values())
    for tier in ("less-known", "familiar", "unknown"):
        extra = min(free, len(tiers[tier]) - take[tier])
        take[tier] += extra
        free -= extra
    return [c for tier in TIERS for c in _with_catalog(tiers[tier], take[tier], 1 if take[tier] >= 2 else 0)]


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
    familiarity = Familiarity(rows.values())
    by_installed: dict[str, list[dict]] = defaultdict(list)    # an installed family's matched catalog rows
    for key, families in matched.items():
        for family in families & installed.keys() if key in rows else ():
            by_installed[family].append(rows[key])
    details_by = {(r["source"], r["family"]): json.loads(r["details_json"]) for r in rows.values() if r["details_json"]}
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
    candidates += owned.candidates(conn, installed, candidates, args, notes)

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
    priority = {name: p for name, p in conn.execute("SELECT name, priority FROM source")}
    loose = argparse.Namespace(**{**vars(args), "secondary_scripts": True})
    off_primary: Counter = Counter()
    tags = tag_weights(conn) if args.role else {}
    for cand in candidates:
        cand["delivery"] = _delivery(cand)
        own = by_installed.get(cand["family"], []) if cand["installed"] else []
        cand["rows"] = own + cand["text_rows"]                 # the catalog rows that speak for the candidate
        cand["primary"] = _primary(cand, cand["rows"])
        if cand["primary"]:
            cand["primary_scripts"] = cand["primary"]["codes"]
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
            if cand.pop("off_primary", False) and _filters(cand, loose)[0]:
                off_primary["/".join(cand["primary"]["codes"])] += 1
            continue
        evidence += why
        cand["fit"] = ()
        if args.role:                                  # under --similar-to, distance alone ranks
            fit, fit_why = role_fit(cand, args.role)
            strength += fit
            evidence += fit_why
            cand["fit"], tie_why = role_fit_key(cand, args.role, tags)
            evidence += tie_why
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
        if cand.get("owned"):
            evidence.append(owned.evidence(cand["owned"], cand["installed"]))
        for c in cand["catalogs"][:3]:
            how = f", {c['method']}" if c.get("method") else ""
            evidence.append(f"listed in {c['source']} as {c['family']!r}{how}")
        for c in cand["catalogs"]:
            if details := details_by.get((c["source"], c["family"])):
                c["details"] = details
                if details.get("license_source"):
                    evidence.append(f"license source, {c['source']}: {details['license_source']}")
                if details.get("download_url"):
                    evidence.append(f"download, {c['source']}: {details['download_url']} ({details['download_kind']})")
        if cand["license"] and args.license != "open":
            evidence.append(_license_evidence(cand))
        cand["familiarity"] = familiarity.of(cand["rows"], [cand["family"], *cand["names_i18n"].values()])
        cand["rank"] = strength                        # uncapped, so bonuses still order capped scores
        cand["score"] = round(max(0.0, min(strength, 1.0)), 3)
        cand["evidence"] = list(dict.fromkeys(evidence))
        cand["order_priority"] = min((priority.get(s["source"], 99) for s in cand["catalogs"]), default=99)
        out.append(cand)
    out.sort(key=_order)
    shown = _balanced(out, args.limit) if args.by_familiarity else _with_catalog(out, args.limit, args.limit // 4)
    if off_primary:
        left = ", ".join(f"{code} {n}" for code, n in off_primary.most_common(6))
        notes.append(f"{sum(off_primary.values())} families cover {args.script} but are left out: it is not their "
                     f"primary script (primary: {left}); --secondary-scripts lists them")
    google = [r for r in rows.values() if r["source"] == "google-fonts"]
    if args.script and google and not any("primary_script" in _row_details(r) for r in google):
        notes.append("the Google Fonts rows carry no primary script yet, so --script counts every family that covers "
                     "it; `lazuli catalog remap --source google-fonts` adds it with no request")
    if args.by_familiarity:
        counts = ", ".join(f"{t} {sum(c['familiarity']['tier'] == t for c in out)}" for t in TIERS)
        notes.append(f"familiarity of all {len(out)} matches: {counts}")
    if len(out) > len(shown):
        notes.append(f"{len(out) - len(shown)} more candidates match; --limit {len(out)} lists them")
    return shown, notes


# ---------------------------------------------------------------- output

PUBLIC_FIELDS = ("family", "names_i18n", "installed", "origins", "faces", "scripts", "primary_scripts", "classes",
                 "genres", "license", "catalogs", "delivery", "familiarity", "owned", "score", "distance", "evidence")


def _familiarity_fact(familiarity: dict) -> str:
    return f"familiarity {familiarity['tier']}" + (f" ({familiarity['basis']})" if "basis" in familiarity else "")


def _public(cand: dict) -> dict:
    return {k: cand[k] for k in PUBLIC_FIELDS if k in cand}


def _text(candidates: list[dict], args, notes: list[str]) -> str:
    what = f"{args.query!r}" if args.query else "the filters"
    if args.similar_to:
        what += f", nearest to {args.similar_to!r}" if args.query else f" nearest to {args.similar_to!r}"
    lines = [f"{len(candidates)} font candidate{'s' if len(candidates) != 1 else ''} for {what}"]
    for i, c in enumerate(candidates, 1):
        where = (f"installed: {', '.join(c['origins'])}, {_faces(c['faces'])}" if c["installed"]
                 else f"owned ({c['owned']['source']}): needs activation" if c.get("owned")
                 else "catalog, not installed: " + ", ".join(dict.fromkeys(s["source"] for s in c["catalogs"])))
        if args.by_familiarity and (i == 1 or c["familiarity"]["tier"] != candidates[i - 2]["familiarity"]["tier"]):
            lines.append(TIER_HEADINGS[c["familiarity"]["tier"]])
        lines.append(f"{i:2}. {c['family']}  [{where}]  score {c['score']:.2f}")
        lines.append("    why: " + "; ".join(c["evidence"]))
        facts = [_familiarity_fact(c["familiarity"])]
        if c["scripts"]:
            facts.append("scripts " + ", ".join(c["scripts"]))
        if c.get("primary_scripts"):
            facts.append("primary script " + ", ".join(c["primary_scripts"]))
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
    ap.add_argument("--secondary-scripts", action="store_true",
                    help="count a family for --script when it merely covers the script, though its primary script "
                         "(Google Fonts primaryScript, or a full measured CJK or Thai set) is another")
    ap.add_argument("--similar-to", metavar="FAMILY", help="rank installed families by measured-feature distance")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, metavar="N",
                    help=f"candidates to list (default {DEFAULT_LIMIT}); a note says how many more match")
    ap.add_argument("--by-familiarity", action="store_true",
                    help="list familiar and less-known candidates side by side, and some no catalog ranks (a quarter "
                         "of --limit unknown, the rest split between the two); an unranked family is listed apart as "
                         "unknown, never as less-known")
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
    if args.by_familiarity and args.limit < 2:
        ap.error("--by-familiarity needs --limit 2 or more: one slot cannot show familiar and less-known side by side")
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
                                                 "secondary_scripts", "similar_to", "by_familiarity", "limit")}
        json.dump({"type": "font", "query": args.query, "filters": filters,
                   "candidates": [_public(c) for c in candidates], "notes": notes},
                  sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        print(_text(candidates, args, notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
