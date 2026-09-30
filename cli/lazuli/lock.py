"""`lazuli lock`: pin a chosen font's source, license, and delivery path in the project's fonts lock.

The lock is `.lapis/fonts.lock.json` in the project (fonts/lock.schema.yaml): one per project, one entry
per family and role, each listing the plan tasks that use it (`used_by`). Locking a locked family and
role adds the task and replaces the facts that changed; the output is the difference.

Where each fact comes from, first match wins:
  postscript_names  --postscript; the installed faces (lazuli DB); the matched catalogs' fonts; the shipped
                    files' name ID 6; the lock
  scripts           the installed faces' coverage; the matched catalogs' `script:` labels; the shipped files'
                    coverage; the lock
  source            --source; the lock; the installed faces' origin (`user` is `user-installed`: provenance
                    unknown); the catalog that lists the family
  catalog_match     the best catalog match in the DB (source priority, then confidence); the lock
  license           license flags (`user-declared`, or the class --license-class names); a declared license
                    already in the lock (rights-holder, provider, user-declared); otherwise a hint, never
                    upgraded: the shipped files' license records (`file-metadata`), the catalog license label
                    resolved by source priority (`catalog-summary`), the installed files' license records
                    (`file-metadata`). Grants per use (`uses`) come only from --use. Without a URL, ofl and
                    apache point at their license text.
  delivery          --delivery; the lock; a default from the source (system-only for system,
                    adobe-web-project for adobe-sync, google-fonts-api for google-fonts, else not-deliverable)
  files, modified, notices, fallback   flags; the lock
  shipped_names     name IDs 1, 4, 6, 16 (every language) of the files `files` resolves to in the project
  notices_embedded  whether every shipped face has copyright (0) and license (13) name records
  reserved_names    --reserved-name; otherwise the names already locked plus the OFL "with Reserved Font
                    Name" declarations in the notices, the shipped files' name records, and the installed
                    files' name records. An OFL font that is subset, converted, or rebuilt needs them; "none
                    declared" is recorded only after reading a notice or a shipped file, never from an
                    installed copy alone. `permission` is --[no-]reserved-name-permission, else the lock's.

Shipped names and embedded notices are recorded only when every file resolved could be read (WOFF2 needs the
brotli module). The user's own class of the family (`lazuli class`, source `user`) is named in a note as a
hint for choosing; it is never a license fact, and nothing of it is written to the lock. An invalid lock is
never written. Exit codes: 0 written, unchanged, or a dry run; 1 the existing lock cannot be read or is
invalid; 2 usage or missing input, including a family the DB does not know when no facts are given.
"""
from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from lapis_design import shared_dir
from lazuli import coretext, db, paths, scan
from lazuli.catalog import labels, match, store

LOCK_FILE = Path(".lapis") / "fonts.lock.json"

# Coverage (scan.COVERAGE blocks) that marks a script: an alphabet's basic letters, or the KS X 1001 Hangul
# syllables, 150 kana, and 6,000 Han, the sets `lazuli local fonts` counts as support.
SCRIPT_COVERAGE = (("latn", "latin", 52), ("grek", "greek", 48), ("cyrl", "cyrillic", 64),
                   ("hebr", "hebrew", 27), ("arab", "arabic", 28), ("thai", "thai", 44),
                   ("hang", "hangul_syllables", 2350), ("kana", "kana", 150), ("hani", "han", 6000))

ORIGIN_SOURCES = {"adobe-sync": "adobe-sync", "system": "system", "user": "user-installed"}   # ties: first wins
CATALOG_SOURCES = {"google-fonts": "google-fonts", "fontsource": "fontsource", "fontshare": "fontshare",
                   "noonnu": "noonnu", "sandoll": "sandoll", "adobe-cjk": "adobe-sync",
                   "anshim": "open-source-other", "system-table": "system"}
DEFAULT_DELIVERY = {"system": "system-only", "adobe-sync": "adobe-web-project", "google-fonts": "google-fonts-api"}

# Catalog license ids (catalog/labels.py) with a lock kind; UFL-1.0 and free-other have none
LICENSE_KINDS = {"OFL-1.1": "ofl", "Apache-2.0": "apache", "KOGL-1": "kogl-1", "system": "system"}
SUBSCRIPTION_CATALOGS = frozenset({"sandoll"})          # their `commercial` label is the subscription's license
LICENSE_TEXT_URLS = {"ofl": "https://openfontlicense.org", "apache": "https://www.apache.org/licenses/LICENSE-2.0"}
DECLARED_CLASSES = ("rights-holder", "provider", "user-declared")
MODIFIED_NEEDS_RFN = frozenset({"subset", "converted", "rebuilt"})   # schema: OFL + these need reserved_names

SHIPPED_NAME_IDS = (1, 4, 6, 16)
FIELD_ORDER = ("role", "used_by", "family", "postscript_names", "scripts", "source", "catalog_match", "license",
               "delivery", "files", "modified", "reserved_names", "shipped_names", "notices", "notices_embedded",
               "fallback")
LICENSE_ORDER = ("kind", "uses", "url", "checked_at", "source_class")


class MissingInput(Exception):
    """A fact the lock needs that neither the DB nor the flags give (exit 2)."""


@functools.lru_cache(maxsize=1)
def lock_schema() -> dict:
    """fonts/lock.schema.yaml (read once; callers never change it)."""
    return yaml.safe_load((shared_dir() / "fonts" / "lock.schema.yaml").read_text(encoding="utf-8"))


def validate(lock: dict, schema: dict | None = None) -> list[tuple[list, str]]:
    validator = Draft202012Validator(schema or lock_schema(), format_checker=FormatChecker())
    return [(list(e.absolute_path), e.message)
            for e in sorted(validator.iter_errors(lock), key=lambda e: list(map(str, e.absolute_path)))]


# ---------------------------------------------------------------- facts from the lazuli DB

def coverage_scripts(coverages) -> list[str]:
    """ISO 15924 codes (as in plan files) the coverage dicts reach, by the best face per block."""
    best: Counter = Counter()
    for coverage in coverages:
        for block, count in coverage.items():
            best[block] = max(best[block], count)
    return [code for code, block, least in SCRIPT_COVERAGE if best.get(block, 0) >= least]


def label_scripts(resolved: list[dict]) -> list[str]:
    """Script codes from catalog `script:<ISO 15924>` property labels, in label order."""
    out = []
    for label in resolved:
        mapped = label.get("mapped") or ""
        if label["kind"] == "property" and mapped.startswith("script:") and mapped[7:] not in out:
            out.append(mapped[7:])
    return out


def _norms(family: str | None, names_i18n_json: str | None) -> set[str]:
    names = [family, *json.loads(names_i18n_json or "{}").values()]
    return {key for name in names if name and (key := scan.norm(name))}


@dataclass
class Facts:
    family: str | None = None                                 # the DB's name; None when the DB does not know it
    faces: list[dict] = field(default_factory=list)           # installed faces of the family
    matches: list[dict] = field(default_factory=list)         # catalog families, best first
    labels: list[dict] = field(default_factory=list)          # catalog and user labels resolved by source priority
    catalog_fonts: list[str] = field(default_factory=list)    # PostScript names the matched catalogs list

    @property
    def known(self) -> bool:
        return self.family is not None


_FACE_COLUMNS = "id, path, face_index, postscript_name, family, subfamily, names_i18n_json, origin, coverage_json"


def _face_matches(conn: sqlite3.Connection, face_ids: list[int]) -> list[dict]:
    if not face_ids:
        return []
    marks = ",".join("?" * len(face_ids))
    # SQLite takes the bare `method` from the row that holds MAX(confidence)
    return [dict(r) for r in conn.execute(f"""
        SELECT s.id AS source_id, s.name AS source, s.priority, m.source_key AS key, cf.family, cf.url,
               m.method, MAX(m.confidence) AS confidence
        FROM match m JOIN source s ON s.id = m.source_id
        JOIN catalog_family cf ON cf.source_id = m.source_id AND cf.source_key = m.source_key
        WHERE m.local_font_id IN ({marks})
        GROUP BY m.source_id, m.source_key ORDER BY s.priority, confidence DESC, cf.family""", face_ids)]


def _named_catalog_families(conn: sqlite3.Connection, key: str) -> list[dict]:
    rows = conn.execute("""
        SELECT s.id AS source_id, s.name AS source, s.priority, cf.source_key AS key, cf.family, cf.url,
               cf.names_i18n_json
        FROM catalog_family cf JOIN source s ON s.id = cf.source_id
        WHERE cf.family_norm = ? OR cf.names_i18n_json IS NOT NULL ORDER BY s.priority, cf.family""", (key,))
    out = []
    for row in rows:
        if key in _norms(row["family"], row["names_i18n_json"]):
            entry = {k: row[k] for k in ("source_id", "source", "priority", "key", "family", "url")}
            out.append({**entry, "method": "exact_family", "confidence": match.CONFIDENCE["exact_family"]})
    return out


def _resolved_labels(conn: sqlite3.Connection, matches: list[dict], family: str) -> list[dict]:
    """The matched catalogs' labels and the user's label of the family (source `user`), resolved by priority."""
    rows = [{"kind": kind, "raw": raw, "mapped": mapped, "source": m["source"], "priority": m["priority"],
             "confidence": m["confidence"]}
            for m in matches
            for kind, raw, mapped in conn.execute(
                "SELECT kind, raw, mapped FROM catalog_label WHERE source_id = ? AND source_key = ?",
                (m["source_id"], m["key"]))]
    rows += store.user_label_rows(store.user_labels(conn).get(scan.norm(family)))
    return labels.resolve(rows) if rows else []


def find_family(conn: sqlite3.Connection, name: str) -> Facts:
    """What the DB knows about a family named `name` (family or i18n name, normalized).

    Installed families come first; otherwise a catalog family of that name, with the installed faces that
    matched it (an installed family may carry another name, such as a variable-font suffix).
    """
    key = scan.norm(name)
    if not key:
        return Facts()
    groups: dict[str, list[dict]] = {}
    for row in conn.execute(f"SELECT {_FACE_COLUMNS} FROM local_font WHERE family IS NOT NULL "
                            "AND family NOT LIKE '.%' ORDER BY family, subfamily, postscript_name, id"):
        if key in _norms(row["family"], row["names_i18n_json"]):
            groups.setdefault(row["family"], []).append(dict(row))
    if groups:
        family = min(groups, key=lambda f: (f != name, scan.norm(f) != key, -len(groups[f]), f))
        faces = groups[family]
        matches = _face_matches(conn, [f["id"] for f in faces])
    else:
        named = _named_catalog_families(conn, key)
        if not named:
            return Facts()
        family = named[0]["family"]
        best = named[0]
        by_family: dict[str, list[dict]] = {}
        for row in conn.execute(f"""
                SELECT {', '.join('lf.' + c.strip() for c in _FACE_COLUMNS.split(','))}
                FROM local_font lf JOIN match m ON m.local_font_id = lf.id
                WHERE m.source_id = ? AND m.source_key = ?
                ORDER BY lf.family, lf.subfamily, lf.postscript_name, lf.id""", (best["source_id"], best["key"])):
            by_family.setdefault(row["family"], []).append(dict(row))
        faces = max(by_family.values(), key=len) if by_family else []
        matches = _face_matches(conn, [f["id"] for f in faces]) or named
    catalog_fonts: list[str] = []
    for m in matches:
        found = [r[0] for r in conn.execute(
            "SELECT postscript_name FROM catalog_font WHERE source_id = ? AND source_key = ? "
            "ORDER BY weight, style, postscript_name", (m["source_id"], m["key"]))]
        if found:
            catalog_fonts = found
            break
    return Facts(family, faces, matches, _resolved_labels(conn, matches, family), catalog_fonts)


# ---------------------------------------------------------------- facts from font files and notices

_RFN = re.compile(r"(?:\bwith\s+(?:the\s+)?Reserved\s+Font\s+Names?|\bReserved\s+Font\s+Names?[ \t]*:)"
                  r"[ \t]*\n?[ \t]*(?P<tail>[^\n]*)", re.I)
_QUOTED = re.compile(r'"([^"]+)"|“([^”]+)”|‘([^’]+)’|\'([^\']+)\'')


def reserved_font_names(text: str) -> list[str]:
    """Names an OFL "with Reserved Font Name(s) ..." or "Reserved Font Name(s): ..." declaration gives.

    The license's own definition ("Reserved Font Name" refers to ...) and clauses that mention the reserved
    names are not declarations and are not matched.
    """
    found: list[str] = []
    for hit in _RFN.finditer(text):
        tail = re.split(r"\.(?:\s|$)", hit.group("tail"), maxsplit=1)[0]
        quoted = [next(g for g in groups if g) for groups in _QUOTED.findall(tail)]
        names = quoted or [part.strip(" \t\"'“”‘’()") for part in re.split(r",|\band\b", tail)]
        for name in (n.strip() for n in names):
            if name and len(name) <= 64 and name not in found:
                found.append(name)
    return found


@dataclass
class FileRecords:
    """Name records and coverage of one font file (every face of a collection)."""
    path: Path
    names: list[str] = field(default_factory=list)            # IDs 1, 4, 6, 16
    postscript: list[str] = field(default_factory=list)       # ID 6
    copyright: list[str] = field(default_factory=list)        # ID 0
    license: list[str] = field(default_factory=list)          # ID 13
    license_url: list[str] = field(default_factory=list)      # ID 14
    coverage: list[dict] = field(default_factory=list)
    notices_embedded: bool = True                             # every face has IDs 0 and 13
    error: str | None = None


def _records(table, *ids: int) -> list[str]:
    out = []
    for record in table.names:
        if record.nameID in ids:
            try:
                text = record.toUnicode().strip()
            except UnicodeDecodeError:
                continue
            if text and text not in out:
                out.append(text)
    return out


def read_file(path: Path, face_index: int | None = None) -> FileRecords:
    out = FileRecords(path)
    faces = []
    try:
        coretext.refuse_adobe_file(path)
        with path.open("rb") as stream:
            magic = stream.read(4)
        if magic == b"wOF2" and importlib.util.find_spec("brotli") is None:
            out.error = "WOFF2 needs the brotli module, which is not installed"
            return out
        faces = scan.faces(path)
        for index, font in faces:
            if face_index is not None and index != face_index:
                continue
            table = font["name"]
            for target, ids in ((out.names, SHIPPED_NAME_IDS), (out.postscript, (6,)), (out.copyright, (0,)),
                                (out.license, (13,)), (out.license_url, (14,))):
                target += [t for t in _records(table, *ids) if t not in target]
            out.notices_embedded &= bool(_records(table, 0)) and bool(_records(table, 13))
            out.coverage.append(json.loads(scan.describe(font)["coverage_json"]))
    except Exception as exc:                                   # an unreadable file is reported, not fatal
        out.error = f"cannot read it as a font ({type(exc).__name__})"
    finally:
        for _, font in faces:
            font.close()
    return out


def resolve_files(project: Path, patterns: list[str]) -> tuple[list[Path], list[str]]:
    """Local files the `files` globs match under the project, and the globs that match none."""
    found: list[Path] = []
    empty = []
    for pattern in patterns:
        hits = sorted(p for p in project.glob(pattern) if not coretext.reaches_adobe(p) and p.is_file())
        if not hits:
            empty.append(pattern)
        found += [p for p in hits if p not in found]
    return found, empty


# ---------------------------------------------------------------- the entry

def lock_kind(license_id: str | None, catalog: str | None = None) -> str | None:
    if license_id == "commercial" and catalog in SUBSCRIPTION_CATALOGS:
        return "commercial-subscription"
    return LICENSE_KINDS.get(license_id or "")


def _file_license_hint(records: list[FileRecords]) -> tuple[str | None, str | None, str | None]:
    """(kind, url, raw text) from license name records, or Nones when none names a known license."""
    for rec in records:
        for text in rec.license:
            license_id = labels.map_license(text)
            if license_id:
                url = next((u for u in rec.license_url if re.fullmatch(r"https?://[^?#\s]*", u)), None)
                return lock_kind(license_id), url, license_id
    return None, None, None


def _license_hint(facts: Facts, shipped: list[FileRecords], installed: list[FileRecords],
                  notes: list[str]) -> dict | None:
    """The license a hint gives, without grants: shipped records, then catalogs, then installed records."""
    today = date.today().isoformat()
    kind, url, raw = _file_license_hint(shipped)
    if kind:
        return {"kind": kind, "url": url or LICENSE_TEXT_URLS.get(kind), "checked_at": today,
                "source_class": "file-metadata", "_from": f"the shipped files' license records ({raw})"}
    catalog = next((lb for lb in facts.labels if lb["kind"] == "license" and lb["mapped"]), None)
    if catalog:
        kind = lock_kind(catalog["mapped"], catalog["source"])
        if kind:
            return {"kind": kind, "url": LICENSE_TEXT_URLS.get(kind), "checked_at": today,
                    "source_class": "catalog-summary", "_from": f"{catalog['source']} ({catalog['raw']})"}
        notes.append(f"{catalog['source']} gives the license {catalog['mapped']} ({catalog['raw']!r}), which has no "
                     "lock kind; recorded as unknown")
    kind, url, raw = _file_license_hint(installed)
    if kind:
        return {"kind": kind, "url": url or LICENSE_TEXT_URLS.get(kind), "checked_at": today,
                "source_class": "file-metadata", "_from": f"the installed files' license records ({raw})"}
    return None


def _ordered(entry: dict) -> dict:
    out = {k: entry[k] for k in FIELD_ORDER if entry.get(k) is not None}
    if "license" in out:
        out["license"] = {k: out["license"][k] for k in LICENSE_ORDER if out["license"].get(k) is not None}
    return out


def build_entry(old: dict | None, facts: Facts, args, project: Path, notes: list[str]) -> dict:
    """The new lock entry from the old one, the DB facts, and the flags (see the module doc for precedence)."""
    old = old or {}
    today = date.today().isoformat()
    entry: dict = {"role": args.role, "family": facts.family or old.get("family") or args.family}
    entry["used_by"] = list(old.get("used_by", [])) + ([args.task] if args.task not in old.get("used_by", []) else [])

    # shipped files and notices
    files = args.files if args.files is not None else old.get("files")
    shipped: list[FileRecords] = []
    shipped_complete = False
    if files:
        paths_found, empty = resolve_files(project, files)
        for pattern in empty:
            notes.append(f"no local file matches {pattern!r} in {project}; shipped names and embedded notices "
                         "come only from files that exist")
        shipped = [read_file(p) for p in paths_found]
        for rec in shipped:
            if rec.error:
                notes.append(f"{rec.path.relative_to(project)}: {rec.error}")
        shipped_complete = bool(shipped) and not empty and not any(rec.error for rec in shipped)
        shipped = [rec for rec in shipped if not rec.error]
    notices = args.notice if args.notice is not None else old.get("notices")
    notice_texts = []
    for notice in notices or ():
        path = project / notice
        if path.is_file():
            notice_texts.append(path.read_text(encoding="utf-8", errors="replace"))
        else:
            notes.append(f"notice {notice!r} is not in {project} yet; the release check looks for it")
    installed = [read_file(Path(f["path"]), f["face_index"]) for f in facts.faces
                 if f["origin"] != "adobe-sync" and Path(f["path"]).is_file()]      # an Adobe identity is no file
    installed = [rec for rec in installed if not rec.error]

    # names and scripts
    face_names = list(dict.fromkeys(f["postscript_name"] for f in facts.faces if f["postscript_name"]))
    shipped_ps = list(dict.fromkeys(n for rec in shipped for n in rec.postscript))
    entry["postscript_names"] = (args.postscript or face_names or facts.catalog_fonts or shipped_ps
                                 or old.get("postscript_names"))
    if not entry["postscript_names"]:
        raise MissingInput(f"no PostScript names are known for {entry['family']!r}; give --postscript NAME, or "
                           "--files with font files in the project")
    scripts = (coverage_scripts(json.loads(f["coverage_json"] or "{}") for f in facts.faces) if facts.faces
               else label_scripts(facts.labels))
    entry["scripts"] = (scripts or coverage_scripts(c for rec in shipped for c in rec.coverage)
                        or old.get("scripts"))

    # source and catalog match
    db_source = None
    if facts.faces:
        counts = Counter(f["origin"] for f in facts.faces)
        origin = max(counts, key=lambda o: (counts[o], -list(ORIGIN_SOURCES).index(o)))
        db_source = ORIGIN_SOURCES[origin]
        if len(counts) > 1:
            notes.append("installed faces come from several origins (" + ", ".join(sorted(counts)) + f"); "
                         f"the source follows the most faces ({origin})")
    elif facts.matches:
        db_source = next((CATALOG_SOURCES[m["source"]] for m in facts.matches if m["source"] in CATALOG_SOURCES),
                         None)
    entry["source"] = args.source or old.get("source") or db_source
    if not entry["source"]:
        raise MissingInput(f"the source of {entry['family']!r} is not known; give --source")
    if not args.source and old.get("source") and db_source and db_source != old["source"]:
        notes.append(f"the DB now suggests source {db_source}; the lock keeps {old['source']} "
                     f"(pass --source {db_source} to change it)")
    if entry["source"] == "user-installed":
        upstream = next((m["source"] for m in facts.matches if m["source"] in ("google-fonts", "fontsource",
                                                                               "fontshare")), None)
        if upstream:
            notes.append(f"the installed files' provenance is unknown (user-installed); {upstream} lists the "
                         f"family, so pass --source {upstream} if the files you ship come from there")
    best = facts.matches[0] if facts.matches else None
    entry["catalog_match"] = ({"catalog": best["source"], "key": best["key"], "method": best["method"],
                               "confidence": best["confidence"]} if best else old.get("catalog_match"))

    # license
    old_license = old.get("license") or {}
    declared_before = old_license.get("source_class") in DECLARED_CLASSES
    if args.license_kind or args.use or args.license_url or args.license_class:
        base = old_license if declared_before else {}
        kind = args.license_kind or base.get("kind")
        if not kind:
            raise MissingInput("give --license-kind with the other license flags (no declared license is locked "
                               "yet, and a catalog or file hint is never promoted to a declaration)")
        same_kind = kind == base.get("kind")
        uses = {**(base.get("uses") or {}), **dict(args.use or ())} if same_kind else dict(args.use or ())
        entry["license"] = {"kind": kind, "uses": uses or None,
                            "url": args.license_url or (base.get("url") if same_kind else None)
                            or LICENSE_TEXT_URLS.get(kind),
                            "checked_at": today, "source_class": args.license_class or "user-declared"}
    elif declared_before:
        entry["license"] = dict(old_license)
    else:
        hint = _license_hint(facts, shipped, installed, notes)
        if hint:
            notes.append(f"license {hint['kind']} is a hint from {hint.pop('_from')}; read the governing license "
                         "and record it (and each use) with --license-kind and --use")
            entry["license"] = hint
        else:
            entry["license"] = {"kind": "unknown", "checked_at": today}
            notes.append("no license is known; read the governing license and record it with --license-kind "
                         "and --use")
        same = {k: v for k, v in entry["license"].items() if v is not None and k != "checked_at"}
        if old_license and same == {k: v for k, v in old_license.items() if k != "checked_at"}:
            entry["license"]["checked_at"] = old_license["checked_at"]           # the same hint keeps its date

    # delivery and files
    default_delivery = DEFAULT_DELIVERY.get(entry["source"], "not-deliverable")
    entry["delivery"] = args.delivery or old.get("delivery") or default_delivery
    if not args.delivery and not old.get("delivery"):
        notes.append(f"delivery {default_delivery} is the default for source {entry['source']}; set it with "
                     "--delivery")
    entry["files"] = files or None
    entry["modified"] = args.modified or old.get("modified")
    if entry["files"] and not entry["modified"]:
        raise MissingInput("give --modified with --files: none, woff-unchanged, subset, converted, or rebuilt")
    entry["notices"] = notices or None
    entry["fallback"] = args.fallback if args.fallback is not None else old.get("fallback")

    # names inside the shipped files
    same_files = files == old.get("files")
    if shipped_complete:
        entry["shipped_names"] = list(dict.fromkeys(n for rec in shipped for n in rec.names))
        entry["notices_embedded"] = all(rec.notices_embedded for rec in shipped)
    elif same_files:
        entry["shipped_names"] = old.get("shipped_names")
        entry["notices_embedded"] = old.get("notices_embedded")

    # reserved font names
    evidence = notice_texts + [t for rec in shipped for t in rec.copyright + rec.license]
    declared = list(dict.fromkeys(n for text in evidence + [t for rec in installed for t in rec.copyright + rec.license]
                                  for n in reserved_font_names(text)))
    old_rfn = old.get("reserved_names") or {}
    permission = (args.reserved_name_permission if args.reserved_name_permission is not None
                  else old_rfn.get("permission", False))
    if args.reserved_name:
        names = list(dict.fromkeys(args.reserved_name))
    elif old_rfn or declared or evidence:              # names already locked stay: more names only add checks
        names = list(dict.fromkeys([*old_rfn.get("names", []), *declared]))
    else:
        names = None
    needs = entry["license"]["kind"] == "ofl" and entry["modified"] in MODIFIED_NEEDS_RFN
    if names or (needs and names is not None):
        entry["reserved_names"] = {"names": names, "permission": permission}
    elif needs:
        raise MissingInput(f"{entry['family']!r} is an OFL font {entry['modified']}: its reserved font names must be "
                           "recorded; give --notice with its license text, --files with the shipped fonts, or "
                           "--reserved-name NAME")

    # the user's own class (`lazuli class`): a hint for choosing, kept in the user cache only
    mine = [lb["mapped"] for lb in facts.labels if lb["source"] == store.USER_SOURCE]
    if mine:
        notes.append(f"class {', '.join(mine)} comes from your class ({store.USER_SOURCE}): a hint for choosing, "
                     "not a license fact; it stays in the lazuli DB and is not written to the lock")
    return _ordered(entry)


# ---------------------------------------------------------------- the lock file

def _flatten(value, prefix: str = "") -> dict:
    if isinstance(value, dict) and value:
        out = {}
        for key, item in value.items():
            out.update(_flatten(item, f"{prefix}.{key}" if prefix else key))
        return out
    return {prefix: value}


def diff(old: dict | None, new: dict) -> list[dict]:
    """[{"field", "old", "new"}] over dotted field paths; a missing side is None."""
    before, after = (_flatten(old) if old else {}), _flatten(new)
    keys = list(after) + [k for k in before if k not in after]
    return [{"field": k, "old": before.get(k), "new": after.get(k)} for k in keys if before.get(k) != after.get(k)]


def _show(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _change_line(change: dict) -> str:
    if change["old"] is None:
        return f"  + {change['field']}: {_show(change['new'])}"
    if change["new"] is None:
        return f"  - {change['field']}: {_show(change['old'])}"
    return f"  ~ {change['field']}: {_show(change['old'])} -> {_show(change['new'])}"


def load_lock(path: Path) -> dict | None:
    if not path.exists():
        return None
    lock = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(lock, dict) or lock.get("version") != 0:
        raise ValueError(f"{path} is not a version 0 fonts lock")
    return lock


def write_lock(path: Path, lock: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _use(text: str) -> tuple[str, str]:
    schema = lock_schema()
    uses = list(schema["properties"]["fonts"]["items"]["properties"]["license"]["properties"]["uses"]["properties"])
    grants = schema["$defs"]["grant"]["enum"]
    use, _, grant = text.partition("=")
    if use not in uses or grant not in grants:
        raise argparse.ArgumentTypeError(f"expected USE=GRANT with USE in {', '.join(uses)} and GRANT in "
                                         f"{', '.join(grants)}, not {text!r}")
    return use, grant


def _parser(prog: str, schema: dict) -> argparse.ArgumentParser:
    props = schema["properties"]["fonts"]["items"]["properties"]
    ap = argparse.ArgumentParser(prog=prog, description="Write or update the project's fonts lock "
                                 "(.lapis/fonts.lock.json) for one family and role.")
    ap.add_argument("family", metavar="FAMILY", help="family or i18n name as the lazuli DB knows it")
    ap.add_argument("--role", required=True, choices=props["role"]["enum"])
    ap.add_argument("--task", required=True, metavar="ID", help="the plan task that uses the font (used_by)")
    ap.add_argument("--project", type=Path, default=Path("."), metavar="DIR", help="project folder (default: .)")
    ap.add_argument("--source", choices=props["source"]["enum"], help="where the shipped files come from")
    ap.add_argument("--delivery", choices=props["delivery"]["enum"])
    ap.add_argument("--postscript", nargs="+", action="extend", metavar="NAME",
                    help="PostScript names, for a family the DB does not know")
    ap.add_argument("--files", nargs="+", action="extend", metavar="GLOB",
                    help="font files that ship, relative to the project (globs allowed)")
    ap.add_argument("--modified", choices=props["modified"]["enum"],
                    help="how the shipped files differ from the release")
    ap.add_argument("--notice", nargs="+", action="extend", metavar="PATH",
                    help="license and copyright texts that ship with the files, relative to the project")
    lic = props["license"]["properties"]
    ap.add_argument("--license-kind", choices=lic["kind"]["enum"], help="the license, as read by you")
    ap.add_argument("--license-url", metavar="URL", help="the governing license text")
    ap.add_argument("--use", nargs="+", action="extend", type=_use, metavar="USE=GRANT",
                    help="what the license grants per use, e.g. web=allowed app=allowed-with-conditions")
    ap.add_argument("--license-class", choices=DECLARED_CLASSES,
                    help="who states the license facts you give (default: user-declared)")
    ap.add_argument("--reserved-name", nargs="+", action="extend", metavar="NAME",
                    help="reserved font names the license declares")
    ap.add_argument("--reserved-name-permission", action=argparse.BooleanOptionalAction, default=None,
                    help="whether you hold written permission to keep the reserved names on a modified version")
    ap.add_argument("--fallback", nargs="+", action="extend", metavar="FAMILY", help="fallback stack")
    ap.add_argument("--dry-run", action="store_true", help="show the difference without writing")
    ap.add_argument("--json", action="store_true", help="machine output")
    return ap


FACT_FLAGS = ("source", "delivery", "postscript", "files", "modified", "notice", "license_kind", "license_url",
              "use", "license_class", "reserved_name", "fallback")


def main(argv: list[str] | None = None, prog: str = "lazuli lock") -> int:
    schema = lock_schema()
    ap = _parser(prog, schema)
    args = ap.parse_args(argv)
    pattern = schema["properties"]["fonts"]["items"]["properties"]["files"]["items"]["pattern"]
    for glob in args.files or ():
        if not re.match(pattern, glob):
            ap.error(f"--files {glob!r}: give paths relative to the project, without '..'")
    project = args.project
    if not project.is_dir():
        ap.error(f"--project {str(project)!r} is not a folder")
    lock_path = project / LOCK_FILE
    try:
        lock = load_lock(lock_path)
    except (ValueError, OSError) as exc:
        print(f"cannot read the fonts lock: {exc}", file=sys.stderr)
        return 1
    conn = db.connect(paths.db_path())
    try:
        facts = find_family(conn, args.family)
    finally:
        conn.close()
    if not facts.known and not any(getattr(args, flag) for flag in FACT_FLAGS):
        print(f"{args.family!r} is unknown to the lazuli DB ({paths.db_path()}), and no facts were given. Run "
              "`lazuli local fonts` (installed fonts) or `lazuli catalog sync` (catalogs), or give the facts "
              "with flags such as --postscript, --source, --license-kind, and --delivery.", file=sys.stderr)
        return 2
    family = facts.family or args.family
    fonts = list((lock or {}).get("fonts", []))
    index = next((i for i, f in enumerate(fonts) if f.get("role") == args.role and f.get("family") == family), None)
    if index is None:
        index = next((i for i, f in enumerate(fonts) if f.get("role") == args.role
                      and scan.norm(f.get("family")) == scan.norm(family)), None)
    old = fonts[index] if index is not None else None
    notes: list[str] = []
    try:
        entry = build_entry(old, facts, args, project, notes)
    except MissingInput as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if index is None:
        fonts.append(entry)
        index = len(fonts) - 1
    else:
        fonts[index] = entry
    changes = diff(old, entry)
    new_lock = {"version": 0, "locked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "fonts": fonts}
    errors = validate(new_lock, schema)
    if errors:
        ours = any(path[:2] == ["fonts", index] for path, _ in errors)
        for path, message in errors:
            print(f"invalid lock at {'/'.join(map(str, path)) or '(root)'}: {message}", file=sys.stderr)
        print("nothing written", file=sys.stderr)
        return 2 if ours else 1
    action = "added" if old is None else "updated" if changes else "unchanged"
    written = bool(changes) and not args.dry_run
    if written:
        write_lock(lock_path, new_lock)
    if args.json:
        json.dump({"lock": str(lock_path), "action": action, "written": written, "entry": entry,
                   "changes": changes, "notes": notes}, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0
    label = f"{entry['family']} ({entry['role']})"
    if action == "unchanged":
        print(f"unchanged: {label} is locked in {lock_path} with these facts")
    else:
        verb = {"added": "add", "updated": "update"}[action]
        print(f"{'would ' + verb if args.dry_run else action} {label} in {lock_path}")
        print("\n".join(_change_line(c) for c in changes))
    if family != args.family:
        print(f"locked as {family!r}, the lazuli DB's name for {args.family!r}")
    for note in notes:
        print(f"note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
