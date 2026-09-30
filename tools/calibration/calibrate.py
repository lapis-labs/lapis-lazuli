"""Calibration report: lazuli's measured font classes against catalog labels, as Markdown.

    uv run python tools/calibration/calibrate.py [--db PATH] [-o REPORT.md]

The lazuli database is opened read-only (default: the user cache, or LAZULI_DB). Nothing is fetched and
no font file is opened: the report compares stored measurements (the current measurer version) with the
mapped labels of exact catalog matches (`exact_ps` or `exact_family`; fuzzy matches are too loose to count
as ground truth and are only counted). The report holds family names and numbers only: no paths, font
files, or catalog payloads.

Unit: one installed family, read on its representative face (the face nearest a regular upright weight,
as `lazuli search --similar-to` picks it) among the faces that have the measurement in question.

Comparisons:
  Latin form      measured serif / sans vs the serif/sans genres of google-fonts, fontsource, fontshare
  Monospace       measured monospaced vs catalog `mono`, per source with Latin genres
  Family kind     measured `hand` (name hints) vs catalog `hand`; letter-count distribution by kind
  Hangul classes  measured bu-ri / min-bu-ri (bu_ratio) vs anshim, sandoll, system-table, and google-fonts
  square_spread   the tal-nemo seed of vocab/type.yaml vs catalog classes, with a threshold sweep
  bu_ratio        the bu boundary of vocab/type.yaml swept against bu-ri / min-bu-ri labels

Threshold proposals follow one fixed rule (PROPOSAL_RULE) and are proposals only: this script never
changes vocab/type.yaml or the measurer.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from lapis_design import shared_dir
from lazuli import local, measure, paths
from lazuli.search import _representative as representative

KOREAN = re.compile(r"[가-힣]")

LATIN_SOURCES = ("google-fonts", "fontsource", "fontshare")
MONO_SOURCES = ("google-fonts", "fontsource", "fontshare", "system-table", "sandoll")
HANGUL_SOURCES = ("anshim", "sandoll", "system-table", "google-fonts")
LATIN_FORMS = ("serif", "sans")
HANGUL_TEXT = ("bu-ri", "min-bu-ri")
HANGUL_OTHER = ("display", "hand")
GENRES = frozenset({"serif", "sans", "slab", "mono", *HANGUL_TEXT, *HANGUL_OTHER})
TAL_NEMO = "display.tal-nemo"
EXACT = ("exact_ps", "exact_family")

MIN_SUPPORT = 10                    # labeled families needed on each side of a boundary
MIN_GAIN = 0.05
# Balanced accuracy (the mean of the recall on each side) rather than F1: F1 rewards flagging everything
# when the positive side is the larger one.
PROPOSAL_RULE = (f"a boundary change is proposed only when at least {MIN_SUPPORT} labeled families sit on each "
                 f"side and the best swept value raises balanced accuracy (the mean of the recall on each side) by "
                 f"{MIN_GAIN} or more over the current value (ties go to the value nearest the current one)")
SPREAD_SWEEP = [round(0.02 + 0.01 * i, 2) for i in range(19)]           # 0.02 .. 0.20
BU_SWEEP = [round(1.10 + 0.05 * i, 2) for i in range(13)]               # 1.10 .. 1.70


# ---------------------------------------------------------------- data

def connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise SystemExit(f"no lazuli database at {path}; run `lazuli local fonts` and `lazuli catalog sync` first")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def boundaries() -> dict[str, float]:
    """The current seeds, read from the contract: bu_ratio's `bu` class and square_spread's `tal-nemo`."""
    vocab = yaml.safe_load((shared_dir() / "vocab" / "type.yaml").read_text(encoding="utf-8"))
    items = {item["id"]: item for item in vocab["cjk_measurements"]}
    bu = items["bu_ratio"]["classes"]["bu"]                               # ">= 1.35"
    if not bu.startswith(">="):
        raise SystemExit(f"vocab bu_ratio class `bu` is {bu!r}; this script reads a `>= N` bound")
    try:
        spread = float(items["square_spread"]["thresholds"]["tal-nemo"])
    except KeyError:
        raise SystemExit("vocab square_spread has no `thresholds.tal-nemo` seed") from None
    return {"bu_ratio": float(bu[2:]), "square_spread": spread}


def exact_labels(conn) -> tuple[dict[str, dict[str, set[str]]], dict[str, dict[str, set[str]]]]:
    """({installed family: {source: mapped genre and subclass ids}}, the same for Hangul classes), over exact
    matches only. A source that names Hangul classes in Korean beside its Latin classes (sandoll: 손글씨 next to
    Display) gives the Hangul view only its Korean names; other sources give both views the same labels."""
    pairs: dict[str, dict[str, set[tuple[str, str]]]] = defaultdict(lambda: defaultdict(set))
    placeholders = ", ".join("?" * len(EXACT))
    for row in conn.execute(f"""
            SELECT DISTINCT lf.family, s.name AS source, cl.mapped, cl.raw
            FROM match m JOIN local_font lf ON lf.id = m.local_font_id JOIN source s ON s.id = m.source_id
            JOIN catalog_label cl ON cl.source_id = m.source_id AND cl.source_key = m.source_key
            WHERE m.method IN ({placeholders}) AND cl.kind IN ('genre', 'subclass') AND cl.mapped IS NOT NULL
              AND lf.family IS NOT NULL""", EXACT):
        pairs[row["family"]][row["source"]].add((row["mapped"], row["raw"]))
    every = {family: {source: {mapped for mapped, _ in found} for source, found in by_source.items()}
             for family, by_source in pairs.items()}
    hangul = {family: {source: {mapped for mapped, raw in found if KOREAN.search(raw)} or every[family][source]
                       for source, found in by_source.items()}
              for family, by_source in pairs.items()}
    return every, hangul


def source_rows(conn) -> list[dict]:
    """Per source: kind, priority, fetch date, catalog families, installed families matched exactly or only fuzzily."""
    matched: dict[str, dict[str, bool]] = defaultdict(dict)
    for row in conn.execute("""
            SELECT s.name AS source, lf.family, MIN(m.method = 'fuzzy') AS fuzzy_only
            FROM match m JOIN local_font lf ON lf.id = m.local_font_id JOIN source s ON s.id = m.source_id
            WHERE lf.family IS NOT NULL GROUP BY s.name, lf.family"""):
        matched[row["source"]][row["family"]] = bool(row["fuzzy_only"])
    out = []
    for row in conn.execute("""SELECT s.name, s.kind, s.priority, s.fetched_at, s.status,
                                      (SELECT COUNT(*) FROM catalog_family cf WHERE cf.source_id = s.id) AS families
                               FROM source s ORDER BY s.priority"""):
        found = matched.get(row["name"], {})
        out.append({"name": row["name"], "kind": row["kind"], "priority": row["priority"],
                    "fetched": (row["fetched_at"] or "")[:10] or "never", "status": row["status"] or "",
                    "families": row["families"], "exact": sum(not f for f in found.values()),
                    "fuzzy_only": sum(found.values())})
    return out


# ---------------------------------------------------------------- measured and catalog classes

def latin_form(face: dict) -> str | None:
    metrics = face.get("metrics") or {}
    if "serif" in metrics:
        return "serif" if metrics["serif"] else "sans"
    return None


def cjk_script(face: dict) -> str | None:
    return (face.get("cjk") or {}).get("script")


def cjk_class(face: dict, script: str) -> str | None:
    """bu-ri or min-bu-ri as the measurer's bu class says, for a face measured in `script` (hang or hani)."""
    cjk = face.get("cjk") or {}
    if cjk.get("script") != script or "bu_class" not in cjk:
        return None
    return "bu-ri" if cjk["bu_class"] == "bu" else "min-bu-ri"


def latin_truth(labels: set[str]) -> str | None:
    """Serif/sans from one source; `other` for mono-only, display, or hand, `mixed` for both forms.
    Slab counts as serif (measured serif means serifs are present)."""
    serif, sans = bool(labels & {"serif", "slab"}), "sans" in labels
    if serif and sans:
        return "mixed"
    if serif or sans:
        return "serif" if serif else "sans"
    return "other" if labels & {"mono", *HANGUL_OTHER} else None


def hangul_truth(labels: set[str]) -> str | None:
    """bu-ri or min-bu-ri when one source gives exactly one of them (`mixed` for both); otherwise display or hand."""
    text = sorted(labels & set(HANGUL_TEXT))
    if len(text) == 2:
        return "mixed"
    if text:
        return text[0]
    return next((c for c in HANGUL_OTHER if c in labels), None)


def pooled_hangul(sources: dict[str, set[str]], order: list[str]) -> tuple[str | None, set[str]]:
    """The Hangul labels of the highest-priority Hangul source that has any: (source, labels)."""
    for name in order:
        found = sources.get(name, set())
        if hangul_truth(found) is not None:
            return name, found
    return None, set()


# ---------------------------------------------------------------- statistics

def ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def fmt(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def prf(tp: int, fp: int, fn: int) -> tuple[float | None, float | None, float | None]:
    p, r = ratio(tp, tp + fp), ratio(tp, tp + fn)
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return p, r, f1


def quantiles(values: list[float]) -> list[float]:
    ordered = sorted(values)

    def at(q: float) -> float:
        pos = q * (len(ordered) - 1)
        low = int(pos)
        high = min(low + 1, len(ordered) - 1)
        return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)

    return [ordered[0], at(0.1), statistics.median(ordered), at(0.9), ordered[-1]]


def sweep(pairs: list[tuple[float, bool]], values: list[float]) -> list[tuple[float, int, int, int, int]]:
    """(bound, tp, fp, fn, tn) for `value >= bound` predicting the positive side."""
    out = []
    for bound in values:
        tp = sum(1 for v, pos in pairs if v >= bound and pos)
        fp = sum(1 for v, pos in pairs if v >= bound and not pos)
        fn = sum(1 for v, pos in pairs if v < bound and pos)
        out.append((bound, tp, fp, fn, len(pairs) - tp - fp - fn))
    return out


def balanced(tp: int, fp: int, fn: int, tn: int) -> float | None:
    pos, neg = ratio(tp, tp + fn), ratio(tn, tn + fp)
    return (pos + neg) / 2 if pos is not None and neg is not None else None


def proposal(label: str, current: float, pairs: list[tuple[float, bool]], grid: list[float], what: str) -> str:
    positives = sum(1 for _, pos in pairs if pos)
    negatives = len(pairs) - positives
    if positives < MIN_SUPPORT or negatives < MIN_SUPPORT:
        return (f"- **{label} {current:g}: keep.** Too few labels to move it ({positives} {what} and "
                f"{negatives} other labeled families; {MIN_SUPPORT} each needed).")
    scored = [(row[0], balanced(*row[1:])) for row in sweep(pairs, sorted(set(grid) | {current}))]
    now = next(score for bound, score in scored if bound == current)
    top = max(score for _, score in scored)
    best = min((bound for bound, score in scored if score == top), key=lambda b: abs(b - current))
    if top - now < MIN_GAIN:
        return (f"- **{label} {current:g}: keep.** Balanced accuracy {now:.3f} at the current value; the best "
                f"swept value {best:g} reaches {top:.3f} ({positives} {what}, {negatives} other).")
    return (f"- **{label} {current:g} → {best:g} (proposal).** Balanced accuracy {now:.3f} → {top:.3f} over "
            f"{positives} {what} and {negatives} other labeled families (sweep table above).")


# ---------------------------------------------------------------- Markdown

def table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" if i == 0 else "---:" for i in range(len(header))) + "|"]
    out += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return out


def confusion(counts: Counter, rows: list[str], cols: list[str], extra_rows: list[str] = ()) -> list[str]:
    body = []
    for truth in [*rows, *extra_rows]:
        cells = [counts[(truth, col)] for col in cols]
        body.append([f"**{truth}**" if truth in rows else truth, *cells, sum(cells)])
    return table(["catalog \\ measured", *cols, "total"], body)


def class_scores(counts: Counter, classes: list[str]) -> list[str]:
    body = []
    for c in classes:
        tp = counts[(c, c)]
        fp = sum(counts[(t, c)] for t in classes if t != c)
        fn = sum(counts[(c, p)] for p in classes if p != c)
        p, r, f1 = prf(tp, fp, fn)
        body.append([c, tp + fn, tp + fp, fmt(p), fmt(r), fmt(f1)])
    return table(["class", "catalog n", "measured n", "precision", "recall", "F1"], body)


def names(entries: list[str]) -> list[str]:
    return [f"- {entry}" for entry in entries] if entries else ["- none"]


# ---------------------------------------------------------------- sections

def latin_section(families: list[dict], labels: dict) -> list[str]:
    out = ["## Latin form: serif, sans", "",
           "Measured: `serif` or `sans` from `metrics.serif` (serifs on H), including monospaced faces. "
           "Catalog: `serif` (including `slab`) or `sans`; mono-only, display-only, hand-only, or both "
           "serif and sans labels are shown below the matrix and excluded from form scores. "
           "`no Latin measurement` means no measured serif/sans form.", ""]
    for source in LATIN_SOURCES:
        counts: Counter = Counter()
        wrong = []
        for fam in families:
            truth = latin_truth(labels.get(fam["family"], {}).get(source, set()))
            if truth is None:
                continue
            face = representative([f for f in fam["faces"] if latin_form(f)])
            measured = latin_form(face) if face else "no Latin measurement"
            counts[(truth, measured)] += 1
            if truth in LATIN_FORMS and measured in LATIN_FORMS and truth != measured:
                wrong.append(f"{fam['family']}: catalog {truth}, measured {measured}")
        out += [f"### {source}", ""]
        out += confusion(counts, list(LATIN_FORMS), [*LATIN_FORMS, "no Latin measurement"], ["other", "mixed"])
        out += ["", *class_scores(counts, list(LATIN_FORMS)), "", "Misclassified families:", ""]
        out += names(sorted(wrong, key=str.casefold)) + [""]
    return out


def mono_section(families: list[dict], labels: dict) -> list[str]:
    out = ["## Monospace", "",
           "Binary: catalog `mono` against every other Latin genre of the same source; families without a "
           "measured Latin width are counted as not measured, not as negatives.", ""]
    body, wrong = [], []
    for source in MONO_SOURCES:
        tp = fp = fn = tn = missing = 0
        for fam in families:
            found = labels.get(fam["family"], {}).get(source, set())
            if not found & (GENRES - set(HANGUL_TEXT)):
                continue
            face = representative([f for f in fam["faces"] if "monospaced" in (f.get("metrics") or {})])
            if face is None:
                missing += 1
                continue
            truth, measured = "mono" in found, bool(face["metrics"]["monospaced"])
            tp, fp = tp + (truth and measured), fp + (measured and not truth)
            fn, tn = fn + (truth and not measured), tn + (not truth and not measured)
            if truth != measured:
                wrong.append(f"{fam['family']} ({source}): catalog {'mono' if truth else 'not mono'}, "
                             f"measured {'mono' if measured else 'not mono'}")
        p, r, f1 = prf(tp, fp, fn)
        body.append([source, tp + fp + fn + tn, tp + fn, tp, fp, fn, missing, fmt(p), fmt(r), fmt(f1)])
    out += table(["source", "families measured", "catalog mono", "TP", "FP", "FN", "not measured",
                  "precision", "recall", "F1"], body)
    out += ["", "Misclassified families:", "", *names(sorted(set(wrong), key=str.casefold)), ""]
    return out


def kind_section(families: list[dict], labels: dict) -> list[str]:
    out = ["## Family kind", "",
           "Measured `family_kind`: `symbol` with fewer than 20 Unicode letters in the cmap (excluding "
           "Private Use and Mathematical Alphanumeric Symbols), except when the most-represented Unicode "
           "Script has at least 90% of its assigned letters; otherwise `hand` when a word-based Latin or "
           "substring-based CJK name hint says so (vocab `name_hints.hand`), else `text`. "
           "Catalog, pooled over every source: `hand` when any says hand, else `display` when any says display, "
           "else a text genre (serif, sans, slab, mono, bu-ri, min-bu-ri). No catalog genre means symbol, so every "
           "labeled family measured `symbol` is misclassified.", ""]
    counts: Counter = Counter()
    wrong, symbols = [], []
    for fam in families:
        genres = set().union(*labels.get(fam["family"], {}).values()) & GENRES
        face = representative([f for f in fam["faces"] if f.get("kind")]) if genres else None
        if face is None:
            continue
        truth = "hand" if "hand" in genres else "display" if "display" in genres else "text genre"
        counts[(truth, face["kind"])] += 1
        if (truth == "hand") != (face["kind"] == "hand"):
            wrong.append(f"{fam['family']}: catalog {truth}, measured {face['kind']}")
        if face["kind"] == "symbol":
            symbols.append(fam["family"])
    kinds = ["hand", "text", "decorative", "symbol"]
    out += confusion(counts, ["hand", "display", "text genre"], kinds)
    tp = counts[("hand", "hand")]
    fp = counts[("display", "hand")] + counts[("text genre", "hand")]
    fn = sum(counts[("hand", k)] for k in kinds if k != "hand")
    p, r, f1 = prf(tp, fp, fn)
    out += ["", f"`hand`: precision {fmt(p)}, recall {fmt(r)}, F1 {fmt(f1)}.", "", "Misclassified as to hand:", ""]
    out += names(sorted(wrong, key=str.casefold))
    out += ["", f"Labeled families measured `symbol` ({len(symbols)}):", "", *names(sorted(symbols, key=str.casefold)), ""]
    groups = {"symbol": [], "other measured kinds": []}
    missing = 0
    for fam in families:
        face = representative([f for f in fam["faces"] if f.get("kind")])
        if face and "letter_count" in face["metrics"]:
            groups["symbol" if face["kind"] == "symbol" else "other measured kinds"].append(
                face["metrics"]["letter_count"])
        else:
            missing += 1
    out += ["### letter_count across installed families", "",
            f"One representative measured face per family; {missing} families not measured. "
            "The symbol seed is fewer than 20 letters without 90% coverage of the dominant script.", ""]
    out += table(["measured kind", "families", "min", "p10", "median", "p90", "max", "< 20"],
                 [[label, len(values), *(f"{v:g}" for v in quantiles(values)),
                   sum(v < 20 for v in values)] if values else [label, 0, "—", "—", "—", "—", "—", 0]
                  for label, values in groups.items()]) + [""]
    return out


def cjk_matrix(families: list[dict], truth_of, script: str) -> list[str]:
    """bu-ri / min-bu-ri confusion for families with a face measured in `script`, truth from `truth_of(family)`."""
    counts: Counter = Counter()
    wrong = []
    for fam in families:
        truth = truth_of(fam["family"])
        if truth is None or not any(cjk_script(f) == script for f in fam["faces"]):
            continue
        face = representative([f for f in fam["faces"] if cjk_class(f, script)])
        measured = cjk_class(face, script) if face else "not measured"
        counts[(truth, measured)] += 1
        if truth in HANGUL_TEXT and measured in HANGUL_TEXT and truth != measured:
            wrong.append(f"{fam['family']}: catalog {truth}, measured {measured} (bu_ratio {face['cjk']['bu_ratio']:g})")
    if not counts:
        return ["No installed family measured in this script has a class label here.", ""]
    out = confusion(counts, list(HANGUL_TEXT), [*HANGUL_TEXT, "not measured"], [*HANGUL_OTHER, "mixed"])
    out += ["", *class_scores(counts, list(HANGUL_TEXT)), "", "Misclassified families:", ""]
    return out + names(sorted(wrong, key=str.casefold)) + [""]


def hangul_section(families: list[dict], labels: dict, order: list[str]) -> list[str]:
    out = ["## Hangul classes: bu-ri, min-bu-ri", "",
           "Measured on faces measured as Hangul (`cjk.script` hang): `bu-ri` when `bu_ratio` reaches the bu "
           "boundary, else `min-bu-ri`. Catalog: bu-ri or min-bu-ri when the source gives exactly one; display or "
           "hand otherwise (no measured counterpart; shown, not scored). anshim is a license source and carries no "
           "class labels. google-fonts is added because it maps Korean families' categories to these classes.", ""]
    for source in HANGUL_SOURCES:
        out += [f"### {source}", ""]
        out += cjk_matrix(families, lambda family, s=source: hangul_truth(labels.get(family, {}).get(s, set())), "hang")
    out += ["### Han faces (no Hangul), pooled", "",
            "The same boundary on the vertical of 十, for Japanese and Chinese families; labels pooled as in the "
            "square_spread section.", ""]
    out += cjk_matrix(families, lambda family: hangul_truth(pooled_hangul(labels.get(family, {}), order)[1]), "hani")
    return out


def pooled(families: list[dict], labels: dict, order: list[str], key: str) -> list[dict]:
    """Hangul families with a measured `key` on their representative face, with pooled catalog labels: the class
    from the highest-priority Hangul source that has one, and the display, hand, and tal-nemo flags from any."""
    out = []
    for fam in families:
        face = representative([f for f in fam["faces"] if cjk_script(f) == "hang" and key in (f.get("cjk") or {})])
        if face is None:
            continue
        sources = labels.get(fam["family"], {})
        source, found = pooled_hangul(sources, order)
        anywhere = set().union(*(sources.get(name, set()) for name in order))
        display, hand = "display" in anywhere or TAL_NEMO in anywhere, "hand" in anywhere
        out.append({"family": fam["family"], "value": face["cjk"][key], "source": source, "truth": hangul_truth(found),
                    "display": display, "hand": hand, "non_text": display or hand, "tal_nemo": TAL_NEMO in anywhere})
    return out


def sweep_table(pairs: list[tuple[float, bool]], grid: list[float], current: float) -> list[str]:
    body = []
    for bound, tp, fp, fn, tn in sweep(pairs, sorted(set(grid) | {current})):
        p, r, f1 = prf(tp, fp, fn)
        mark = f"**{bound:g}** (current)" if bound == current else f"{bound:g}"
        body.append([mark, tp, fp, fn, tn, fmt(p), fmt(r), fmt(f1), fmt(balanced(tp, fp, fn, tn))])
    return table(["bound", "TP", "FP", "FN", "TN", "precision", "recall", "F1", "balanced accuracy"], body)


def distribution(groups: dict[str, list[float]], bound: float) -> list[str]:
    body = []
    for name, values in groups.items():
        if not values:
            body.append([name, 0, "—", "—", "—", "—", "—", "—"])
            continue
        q = quantiles(values)
        body.append([name, len(values), *(f"{v:.3f}" for v in q), sum(v >= bound for v in values)])
    return table(["catalog class", "families", "min", "p10", "median", "p90", "max", f">= {bound:g}"], body)


def spread_section(entries: list[dict], bound: float) -> tuple[list[str], list[str]]:
    out = ["## square_spread and the tal-nemo seed", "",
           f"Seed: `square_spread` >= {bound:g} is tal-nemo (vocab/type.yaml, uncalibrated). Catalog labels per "
           "family: the class from the highest-priority Hangul source that gives one (lazuli's source priority), "
           "and display, hand, or tal-nemo when any Hangul source says so. (a) scores the seed against the tal-nemo "
           "subclass. (b) scores it against hand (not display) versus bu-ri or min-bu-ri (neither display nor hand): "
           "the vocabulary note says high spread suggests tal-nemo or hand-drawn forms, and the seed came from hand "
           "families. Display is left out of (b): it covers square-frame designs as well.", ""]
    groups = {
        "bu-ri": [e["value"] for e in entries if e["truth"] == "bu-ri" and not e["non_text"]],
        "min-bu-ri": [e["value"] for e in entries if e["truth"] == "min-bu-ri" and not e["non_text"]],
        "display (not tal-nemo)": [e["value"] for e in entries if e["display"] and not e["tal_nemo"]],
        "display.tal-nemo": [e["value"] for e in entries if e["tal_nemo"]],
        "hand (not display)": [e["value"] for e in entries if e["hand"] and not e["display"]],
        "no class label": [e["value"] for e in entries if e["truth"] is None and not e["non_text"]],
    }
    out += distribution(groups, bound) + [""]
    labeled = [e for e in entries if e["truth"] in (*HANGUL_TEXT, *HANGUL_OTHER) or e["non_text"]]
    tal = [(e["value"], e["tal_nemo"]) for e in labeled]
    text_or_hand = [e for e in labeled if not e["display"] and (e["hand"] or e["truth"] in HANGUL_TEXT)]
    hand = [(e["value"], e["hand"]) for e in text_or_hand]
    out += ["### (a) tal-nemo against every other labeled Hangul family", "", *sweep_table(tal, SPREAD_SWEEP, bound), ""]
    out += ["### (b) hand against bu-ri or min-bu-ri", "", *sweep_table(hand, SPREAD_SWEEP, bound), ""]
    text_over = [f"{e['family']}: {e['truth']} ({e['source']}), square_spread {e['value']:g}" for e in labeled
                 if not e["non_text"] and e["value"] >= bound]
    tal_under = [f"{e['family']}: square_spread {e['value']:g}" for e in labeled if e["tal_nemo"] and e["value"] < bound]
    hand_under = [f"{e['family']}: square_spread {e['value']:g}" for e in text_or_hand if e["hand"] and e["value"] < bound]
    unlabeled = [f"{e['family']}: {e['value']:g}" for e in entries
                 if e["truth"] is None and not e["non_text"] and e["value"] >= bound]
    out += [f"Text-class families at or above {bound:g} (false tal-nemo):", "", *names(sorted(text_over, key=str.casefold)), ""]
    out += [f"tal-nemo families below {bound:g}:", "", *names(sorted(tal_under, key=str.casefold)), ""]
    out += [f"Hand families (not display) below {bound:g}:", "", *names(sorted(hand_under, key=str.casefold)), ""]
    out += [f"Families without a class label at or above {bound:g}:", "", *names(sorted(unlabeled, key=str.casefold)), ""]
    return out, [proposal("`square_spread` tal-nemo, reading (a)", bound, tal, SPREAD_SWEEP, "tal-nemo"),
                 proposal("`square_spread` tal-nemo, reading (b)", bound, hand, SPREAD_SWEEP, "hand")]


def bu_section(entries: list[dict], bound: float) -> tuple[list[str], str]:
    out = ["## bu_ratio and the bu boundary", "",
           f"Boundary: `bu_ratio` >= {bound:g} is bu-ri (vocab/type.yaml `cjk_measurements.bu_ratio`). Pooled labels "
           "as above; only families labeled bu-ri or min-bu-ri, without display or hand, are scored.", ""]
    text = [e for e in entries if e["truth"] in HANGUL_TEXT and not e["non_text"]]
    groups = {c: [e["value"] for e in text if e["truth"] == c] for c in HANGUL_TEXT}
    out += distribution(groups, bound) + [""]
    pairs = [(e["value"], e["truth"] == "bu-ri") for e in text]
    out += ["### bu-ri against min-bu-ri", "", *sweep_table(pairs, BU_SWEEP, bound), ""]
    return out, proposal("`bu_ratio` bu", bound, pairs, BU_SWEEP, "bu-ri")


def comparison_section(families: list[dict], labels: dict, hangul_labels: dict) -> list[str]:
    """Compare kind with 1497d3f and preserve the older 13ba6c5 comparison for other metrics."""
    form_counts: dict[str, Counter] = {source: Counter() for source in LATIN_SOURCES}
    mono_counts: dict[str, Counter] = {source: Counter() for source in MONO_SOURCES}
    symbol = Counter()
    hand = Counter()
    sandoll = Counter()
    for fam in families:
        name = fam["family"]
        genres = labels.get(name, {})
        pooled_genres = set().union(*genres.values())
        form_face = representative([f for f in fam["faces"] if latin_form(f)])
        form = latin_form(form_face) if form_face else None
        width_face = representative([f for f in fam["faces"] if "monospaced" in (f.get("metrics") or {})])
        for source, counts in form_counts.items():
            truth = latin_truth(genres.get(source, set()))
            if truth in LATIN_FORMS:
                counts[(truth, form)] += 1
        for source, counts in mono_counts.items():
            genre = genres.get(source, set())
            if genre & (GENRES - set(HANGUL_TEXT)):
                if width_face is None:
                    counts["missing"] += 1
                else:
                    counts[("mono" in genre, bool(width_face["metrics"]["monospaced"]))] += 1
        if pooled_genres & GENRES:
            kind_face = representative([f for f in fam["faces"] if f.get("kind")])
            if kind_face is None:
                symbol["missing"] += 1
                hand["missing"] += 1
            else:
                symbol["wrong" if kind_face["kind"] == "symbol" else "other"] += 1
                if kind_face["kind"] == "hand":
                    hand["tp" if "hand" in pooled_genres else "fp"] += 1
        if hangul_truth(hangul_labels.get(name, {}).get("sandoll", set())) == "bu-ri" and any(
                cjk_script(f) == "hang" for f in fam["faces"]):
            hangul_face = representative([f for f in fam["faces"] if cjk_class(f, "hang")])
            sandoll["missing" if hangul_face is None else
                    "right" if cjk_class(hangul_face, "hang") == "bu-ri" else "wrong"] += 1

    rows = [
        ["Symbol misclassifications", "105; not measured 1",
         f"{symbol['wrong']}; not measured {symbol['missing']}"],
        ["Sandoll Hangul bu-ri recall", "0.667; not measured 0",
         f"{fmt(ratio(sandoll['right'], sandoll['right'] + sandoll['wrong']))}; "
         f"not measured {sandoll['missing']}"],
    ]
    baseline_forms = {
        "google-fonts": {"serif": ("0.952 / 0.952", 6), "sans": ("1.000 / 0.944", 102)},
        "fontsource": {"serif": ("0.952 / 0.952", 6), "sans": ("1.000 / 0.931", 102)},
        "fontshare": {"serif": ("— / —", 0), "sans": ("— / 0.000", 0)},
    }
    for source, counts in form_counts.items():
        for form in LATIN_FORMS:
            baseline, missing = baseline_forms[source][form]
            tp = counts[(form, form)]
            other = next(c for c in LATIN_FORMS if c != form)
            p, r, _ = prf(tp, counts[(other, form)], counts[(form, other)])
            rows.append([f"Latin {form} ({source})", f"{baseline}; not measured {missing}",
                         f"{fmt(p)} / {fmt(r)}; not measured {counts[(form, None)]}"])
    baseline_mono = {
        "google-fonts": ("0.600 / 1.000", 110), "fontsource": ("0.600 / 1.000", 110),
        "fontshare": ("0.000 / —", 0), "system-table": ("1.000 / 1.000", 0),
        "sandoll": ("— / —", 3),
    }
    for source, counts in mono_counts.items():
        baseline, missing = baseline_mono[source]
        p, r, _ = prf(counts[(True, True)], counts[(False, True)], counts[(True, False)])
        rows.append([f"Monospace ({source})", f"{baseline}; not measured {missing}",
                     f"{fmt(p)} / {fmt(r)}; not measured {counts['missing']}"])
    # This fixed baseline is the exact-labeled cohort in the 14a985c calibration report.
    previous = {
        "Symbol misclassifications": "1; not measured 1",
        "Hand precision": "1.000; not measured 1",
        "Sandoll Hangul bu-ri recall": "1.000; not measured 3",
        "Latin serif (google-fonts)": "0.955 / 1.000; not measured 6",
        "Latin sans (google-fonts)": "1.000 / 0.972; not measured 102",
        "Latin serif (fontsource)": "0.955 / 1.000; not measured 6",
        "Latin sans (fontsource)": "1.000 / 0.966; not measured 102",
        "Latin serif (fontshare)": "— / —; not measured 0",
        "Latin sans (fontshare)": "1.000 / 1.000; not measured 0",
        "Monospace (google-fonts)": "0.600 / 1.000; not measured 110",
        "Monospace (fontsource)": "0.600 / 1.000; not measured 110",
        "Monospace (fontshare)": "0.000 / —; not measured 0",
        "Monospace (system-table)": "1.000 / 1.000; not measured 0",
        "Monospace (sandoll)": "— / —; not measured 3",
    }
    measured_now = {name: current for name, _, current in rows}
    measured_now["Hand precision"] = (f"{fmt(ratio(hand['tp'], hand['tp'] + hand['fp']))}; "
                                       f"not measured {hand['missing']}")
    latest = [
        "## Comparison with 14a985c", "",
        "Baseline: the 14a985c calibration report, for the same exact-labeled family cohorts. "
        "Form and monospace cells are precision / recall; the other cells are a count, recall, "
        "or precision. Not-measured families are excluded from scored denominators.", "",
        *table(["metric", "14a985c", "current"],
               [[name, baseline, measured_now[name]] for name, baseline in previous.items()]), "",
    ]
    current = [
        "## Comparison with 1497d3f", "",
        "Baseline: the 1497d3f calibration report, for the same exact-labeled family cohort. "
        "Symbol misclassifications count labeled families measured as symbol; hand precision scores "
        "measured hand families against catalog hand labels. Not-measured families are outside both denominators.", "",
        *table(["metric", "1497d3f", "current"], [
            ["Symbol misclassifications", "7; not measured 1",
             f"{symbol['wrong']}; not measured {symbol['missing']}"],
            ["Hand precision", "0.500; not measured 1",
             f"{fmt(ratio(hand['tp'], hand['tp'] + hand['fp']))}; not measured {hand['missing']}"],
        ]), "", "## Comparison with 13ba6c5", "",
    ]
    return latest + current + [
            "Baseline: the 13ba6c5 calibration report. Current: the same exact-match catalog cohorts "
            "on this inventory. Form and monospace cells are precision / recall; the other cells are a "
            "count or recall. Each cell states its not-measured count, excluded from scored denominators. "
            "The baseline's symbol count covers only labeled families included in its measured-kind matrix; "
            "its one not-measured family is the 268-family exact-labeled cohort minus 267 matrix rows. "
            "The script-coverage exception to the 20-letter seed and the pixel exclusion affect different "
            "measurements; missing and correct predictions are distinct. "
            "Sandoll bu-ri had 6 correct predictions and 3 false negatives in the "
            f"baseline; now it has {sandoll['right']} correct predictions, {sandoll['wrong']} false negatives, "
            f"and {sandoll['missing']} not measured. Excluding pixel faces does not turn them into correct hits.", "",
            *table(["metric", "13ba6c5", "current"], rows), ""]


# ---------------------------------------------------------------- report

def report(conn) -> str:
    bounds = boundaries()
    from fontTools import unicodedata as unicode_data
    families = local._families(conn)
    labels, hangul_labels = exact_labels(conn)
    sources = source_rows(conn)
    priority = [s["name"] for s in sources if s["name"] in HANGUL_SOURCES]
    faces = sum(len(f["faces"]) for f in families)
    measured = sum(f["measured"] for f in families)
    lines = ["# lazuli measurement calibration", "",
             f"Measurer {measure.MEASURER_VERSION}; Unicode {unicode_data.unidata_version}. "
             f"{len(families)} installed families with a name, {faces} faces, "
             f"{measured} measured. Labels come from exact catalog matches only; per family, the representative face "
             f"(nearest a regular upright weight) carries the measurement. Family names and numbers only.", "",
             *comparison_section(families, labels, hangul_labels),
             "## Sources", ""]
    lines += table(["source", "kind", "priority", "fetched", "status", "catalog families", "installed families (exact)",
                    "fuzzy only (left out)", "with class labels"],
                   [[s["name"], s["kind"], s["priority"], s["fetched"], s["status"], s["families"], s["exact"],
                     s["fuzzy_only"], sum(1 for f in labels.values() if f.get(s["name"]))] for s in sources])
    lines.append("")
    lines += latin_section(families, labels)
    lines += mono_section(families, labels)
    lines += kind_section(families, labels)
    lines += hangul_section(families, hangul_labels, priority)
    spread_lines, spread_proposals = spread_section(pooled(families, hangul_labels, priority, "square_spread"),
                                                    bounds["square_spread"])
    bu_lines, bu_proposal = bu_section(pooled(families, hangul_labels, priority, "bu_ratio"), bounds["bu_ratio"])
    lines += spread_lines + bu_lines
    lines += ["## Threshold proposals", "", f"Rule: {PROPOSAL_RULE}. Proposals only; vocab/type.yaml is unchanged.",
              "", *spread_proposals, bu_proposal, ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", type=Path, default=None, help="lazuli database (default: the user cache, or LAZULI_DB)")
    ap.add_argument("-o", "--output", type=Path, help="write the report here instead of standard output")
    args = ap.parse_args(argv)
    conn = connect(args.db or paths.db_path())
    try:
        text = report(conn)
    finally:
        conn.close()
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
