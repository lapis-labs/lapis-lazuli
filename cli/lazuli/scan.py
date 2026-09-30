"""Read-only inventory of the fonts installed on this computer.

Font files are opened for reading only; nothing is copied, moved, or written next to them, and the
inventory stays in the user's lazuli database. Roots per platform, with their `origin`:

- macOS: /System/Library/Fonts and downloadable system fonts under
  /System/Library/AssetsV2/com_apple_MobileAsset_Font* (system); /Library/Fonts and ~/Library/Fonts (user).
- Windows: %WINDIR%\\Fonts (system); %LOCALAPPDATA%\\Microsoft\\Windows\\Fonts (user).
- Linux: /usr/share/fonts and /usr/local/share/fonts (system); ~/.local/share/fonts and ~/.fonts (user).

Adobe Fonts (origin `adobe-sync`) are never read from files, because Adobe's terms allow reaching them only
through the operating system's font API. Adobe's folders (`~/Library/Application Support/Adobe/`,
`%APPDATA%\\Adobe\\CoreSync`) are skipped wherever a root would lead into them, links included, and nothing
in them is opened, stat'ed, or listed. On macOS the faces Core Text lists from those folders are added as
rows whose path is `coretext:<PostScript name>` (an identity, not a path), whose size is 0, and whose mtime
is `coretext:<version name>` (the change detector). Names, coverage, and design metadata come from Core Text,
and vendor_id stays empty (see `coretext`). Korean, Japanese, and Chinese family names of the faces a scan
describes come from one helper process per language, started once for all of them, and are stored under
the keys file faces use; a language whose helper fails is skipped with one line. Faces Core Text stops
listing are removed with their measurements at the next scan. On Windows and Linux Adobe Fonts are absent
from the inventory.

`LAZULI_FONT_ROOTS` replaces the roots (tests, evaluations) and turns the Core Text listing off, so no Adobe
data reaches them: entries separated by the OS path separator, each `system=path` or `user=path` (any other
origin, `adobe-sync` included, or a path inside Adobe's folders is a `RootsError`). A file is a font when its
first four bytes are an sfnt or collection signature, whatever its name. Unchanged files (same size and mtime)
are not reopened except when a migration marks their metadata for refresh; that alone keeps measurements.

`metadata_json` records supported languages, variation axes, feature availability, version, heights (font
units), units per em, and stylistic class. File faces use fontTools only: fvar axes, GSUB/GPOS FeatureList
tags, name ID 5, head.unitsPerEm, and OS/2 sxHeight/sCapHeight/sFamilyClass. Missing or zero OS/2 heights are
unknown (null). OS/2 Unicode/code-page range words are retained as declarations, not evidence of support.
Languages use the same mapped-character rule for both origins (`languages.py`), reusing the scripts in
COVERAGE rather than trusting those declarations or an OS language list. `vertical` contains the available
vert/vrt2/vhal/vkna tags for files; Core Text reports mapped AAT features, which fold vrt2 into vert and may
hide vhal. Thus an absent Adobe feature is not proof that the font lacks it. Metadata is local, inference-only
for Adobe faces, like coverage and measurements.
"""
from __future__ import annotations

import hashlib
import logging
import json
import os
import re
import sqlite3
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lazuli import coretext, languages

logging.getLogger("fontTools").setLevel(logging.ERROR)

SFNT_MAGIC = {b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"}
COLLECTION_MAGIC = b"ttcf"

# Unicode blocks counted for coverage (code points present in the best cmap)
COVERAGE = {
    "latin": [(0x41, 0x5A), (0x61, 0x7A)],
    "latin_ext": [(0xC0, 0x24F)],
    "greek": [(0x370, 0x3FF)],
    "cyrillic": [(0x400, 0x4FF)],
    "hebrew": [(0x590, 0x5FF)],
    "arabic": [(0x600, 0x6FF)],
    "thai": [(0xE00, 0xE7F)],
    "hangul_syllables": [(0xAC00, 0xD7A3)],
    "hangul_jamo": [(0x1100, 0x11FF), (0x3130, 0x318F)],
    "kana": [(0x3040, 0x30FF)],
    "han": [(0x4E00, 0x9FFF)],
    "digits": [(0x30, 0x39)],
}

VERTICAL_FEATURES = frozenset({"vert", "vrt2", "vhal", "vkna"})

# name-table language ids for the CJK names kept in names_i18n_json
WINDOWS_LANGS = {0x412: "ko", 0x411: "ja", 0x804: "zh-Hans", 0x1004: "zh-Hans", 0x404: "zh-Hant",
                 0xC04: "zh-Hant", 0x1404: "zh-Hant"}
MAC_LANGS = {23: "ko", 11: "ja", 33: "zh-Hans", 19: "zh-Hant"}


@dataclass(frozen=True)
class Root:
    origin: str                     # system | user
    path: Path


class RootsError(ValueError):
    """`LAZULI_FONT_ROOTS` names an origin or a folder lazuli does not read."""


ROOT_ORIGINS = ("system", "user")


def roots() -> list[Root]:
    if spec := os.environ.get("LAZULI_FONT_ROOTS"):
        out = []
        for entry in spec.split(os.pathsep):
            origin, _, path = entry.partition("=")
            if origin == "adobe-sync":
                raise RootsError("LAZULI_FONT_ROOTS: adobe-sync is not a root origin; Adobe Fonts are read only "
                                 "through the operating system's font list (macOS), never from files")
            if origin not in ROOT_ORIGINS:
                raise RootsError(f"LAZULI_FONT_ROOTS: {entry!r} does not start with system= or user=")
            root = Path(path).expanduser()
            if coretext.reaches_adobe(root):
                raise RootsError(f"LAZULI_FONT_ROOTS: {path} is inside Adobe's font folders, which lazuli never "
                                 "reads")
            out.append(Root(origin, root))
        return out
    home = Path.home()
    if sys.platform == "darwin":
        return ([Root("system", Path("/System/Library/Fonts"))]
                + [Root("system", p) for p in sorted(Path("/System/Library/AssetsV2").glob("com_apple_MobileAsset_Font*"))]
                + [Root("user", Path("/Library/Fonts")), Root("user", home / "Library/Fonts")])
    if os.name == "nt":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        return [Root("system", windir / "Fonts"), Root("user", local / "Microsoft/Windows/Fonts")]
    return [Root("system", Path("/usr/share/fonts")), Root("system", Path("/usr/local/share/fonts")),
            Root("user", home / ".local/share/fonts"), Root("user", home / ".fonts")]


def _candidates(top: Path):
    """Paths of the files under `top`. Adobe's font folders are never entered, and nothing under them is
    named to the file system: entries are matched by name (or by the link they point at) before any call
    that would look at them."""
    pending = [str(top)]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as listing:
                entries = list(listing)
        except OSError:
            continue
        for entry in entries:
            if coretext.is_adobe_path(entry.path):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(entry.path)
                    continue
                if entry.is_symlink() and coretext.reaches_adobe(entry.path):
                    continue
            except OSError:
                continue
            yield Path(entry.path)


def readable_roots() -> list[Root]:
    """The roots that exist as folders and do not lead into Adobe's font folders (no file is looked at in them)."""
    return [root for root in roots() if not coretext.reaches_adobe(root.path) and root.path.is_dir()]


def font_files() -> list[tuple[Root, Path, os.stat_result]]:
    """Every font file under the roots, first root wins for a path seen twice. Adobe's folders are skipped,
    named by a root or not: Adobe Fonts come from `coretext`, never from files."""
    seen: set[Path] = set()
    out = []
    for root in readable_roots():
        for path in _candidates(root.path):
            if path in seen:
                continue
            try:
                with path.open("rb") as stream:
                    magic = stream.read(4)
                stat = path.stat()
            except OSError:
                continue
            if magic in SFNT_MAGIC or magic == COLLECTION_MAGIC:
                seen.add(path)
                out.append((root, path, stat))
    return out


def adobe_identities() -> list[str]:
    """The Adobe Fonts faces the operating system lists now: none where it is not consulted, and none when
    it cannot be asked (the next scan reports that)."""
    try:
        provider = coretext.provider()
        return provider.identities() if provider else []
    except Exception:
        return []


def fingerprint(files: list[tuple[Root, Path, os.stat_result]], adobe: Iterable[str] = ()) -> str:
    """One hash of everything a scan looks at: files by path, size, and mtime, and Adobe Fonts faces by
    identity (a face's version is checked by the scan itself, since reading it costs a font per face)."""
    digest = hashlib.sha256()
    for _, path, stat in sorted(files, key=lambda item: str(item[1])):
        digest.update(f"{path}\0{stat.st_size}\0{int(stat.st_mtime)}\n".encode())
    for identity in sorted(adobe):
        digest.update(f"{identity}\n".encode())
    return digest.hexdigest()


def current_fingerprint() -> str:
    """The fingerprint of the inventory as it is now, for comparing with the stored one."""
    return fingerprint(font_files(), adobe_identities())


def norm(name: str | None) -> str | None:
    return re.sub(r"[\W_]+", "", name.casefold()) if name else None


def _name(table, *ids: int) -> str | None:
    for name_id in ids:
        for platform, encoding, lang in ((3, 1, 0x409), (3, 10, 0x409), (1, 0, 0)):
            record = table.getName(name_id, platform, encoding, lang)
            if record is not None and (text := record.toUnicode().strip()):
                return text
        if (text := table.getDebugName(name_id)) and text.strip():
            return text.strip()
    return None


def _i18n(table) -> dict[str, str]:
    names: dict[str, str] = {}
    for name_id in (16, 1):
        for record in table.names:
            if record.nameID != name_id:
                continue
            lang = (WINDOWS_LANGS if record.platformID == 3 else MAC_LANGS if record.platformID == 1 else {}).get(record.langID)
            if lang and lang not in names:
                try:
                    names[lang] = record.toUnicode().strip()
                except UnicodeDecodeError:
                    continue
    return names


def feature_tags(font) -> list[str]:
    """All GSUB/GPOS feature tags, sorted; reading FeatureList leaves unrelated lazy subtables alone."""
    tags = set()
    for name in ("GSUB", "GPOS"):
        if name in font:
            features = font[name].table.FeatureList
            if features:
                tags.update(record.FeatureTag for record in features.FeatureRecord)
    return sorted(tags)


def variation_axes(font) -> list[dict]:
    """fvar axes in the font's order, including hidden axes; names are not needed to identify a tag."""
    return [{"tag": axis.axisTag, "min": axis.minValue, "default": axis.defaultValue, "max": axis.maxValue}
            for axis in font["fvar"].axes] if "fvar" in font else []


def _file_metadata(font, cmap, os2) -> dict:
    features = feature_tags(font)
    family_class = os2.sFamilyClass if os2 is not None else None
    return {"languages": languages.of_cmap(cmap), "axes": variation_axes(font), "features": features,
            "features_source": "opentype", "vertical": sorted(VERTICAL_FEATURES.intersection(features)),
            "version": _name(font["name"], 5), "units_per_em": font["head"].unitsPerEm,
            "x_height": getattr(os2, "sxHeight", 0) or None, "cap_height": getattr(os2, "sCapHeight", 0) or None,
            "family_class": family_class, "class_id": ((family_class & 0xFF00) >> 8) if family_class is not None else None,
            "class_source": "os2",
            "os2_ranges": {"unicode": [getattr(os2, f"ulUnicodeRange{i}", 0) for i in range(1, 5)],
                           "codepage": [getattr(os2, f"ulCodePageRange{i}", 0) for i in range(1, 3)]}
                          if os2 is not None else None}


def describe(font) -> dict:
    """The inventory fields of one face (a fontTools TTFont)."""
    table = font["name"]
    cmap = font.getBestCmap() or {}
    coverage = {}
    for block, ranges in COVERAGE.items():
        count = sum(1 for cp in cmap if any(lo <= cp <= hi for lo, hi in ranges))
        if count:
            coverage[block] = count
    os2 = font["OS/2"] if "OS/2" in font else None
    family = _name(table, 16, 1)
    i18n = _i18n(table)
    return {"postscript_name": _name(table, 6), "family": family, "family_norm": norm(family),
            "subfamily": _name(table, 17, 2), "names_i18n_json": json.dumps(i18n, ensure_ascii=False) if i18n else None,
            "manufacturer": _name(table, 8), "designer": _name(table, 9),
            "vendor_id": (os2.achVendID.strip("\x00 ") or None) if os2 is not None else None,
            "coverage_json": json.dumps(coverage), "metadata_json": json.dumps(_file_metadata(font, cmap, os2))}


def faces(path: Path):
    """(face_index, TTFont) for every face in a file, opened lazily and read-only."""
    from fontTools.ttLib import TTCollection, TTFont

    coretext.refuse_adobe_file(path)
    with path.open("rb") as stream:
        magic = stream.read(4)
    if magic == COLLECTION_MAGIC:
        collection = TTCollection(str(path), lazy=True)
        return list(enumerate(collection.fonts))
    return [(0, TTFont(str(path), lazy=True))]


def describe_adobe(face: coretext.AdobeFace, localized: dict[str, str] | None = None) -> dict:
    """Inventory and design metadata from OS-derived values only, never an Adobe font's tables or files.
    `localized` holds the family names the helper processes found ({language key: name}); the name in the
    system language, which the scan's own process learns, stays as it is."""
    info = face.describe(COVERAGE, languages.wanted())
    i18n, coverage = info.pop("names_i18n"), info.pop("coverage")
    i18n = {**i18n, **{language: name for language, name in (localized or {}).items() if language not in i18n}}
    metadata = info.pop("metadata")
    metadata["languages"] = languages.supported(info.pop("mapped"))
    return {**info, "family_norm": norm(info["family"]),
            "names_i18n_json": json.dumps(i18n, ensure_ascii=False) if i18n else None,
            "vendor_id": None, "coverage_json": json.dumps(coverage), "metadata_json": json.dumps(metadata)}


@dataclass
class ScanResult:
    files: int
    added: int
    updated: int
    removed: int
    unreadable: list[str]
    fingerprint: str
    adobe: int = 0                  # Adobe Fonts faces the operating system lists (counted in added/updated/removed)


def _store(conn: sqlite3.Connection, key: str, size: int, mtime: str, origin: str, rows: list[tuple[int, dict]],
           changed: bool) -> None:
    """Write a file's faces (or an Adobe identity); only a changed font loses its measurements."""
    conn.execute("DELETE FROM local_font WHERE path = ? AND face_index >= ?", (key, len(rows)))
    for index, info in rows:
        conn.execute(
            """INSERT INTO local_font (path, size, mtime, face_index, postscript_name, family, family_norm,
                 subfamily, names_i18n_json, manufacturer, vendor_id, designer, coverage_json, metadata_json, origin)
               VALUES (:path, :size, :mtime, :face_index, :postscript_name, :family, :family_norm, :subfamily,
                 :names_i18n_json, :manufacturer, :vendor_id, :designer, :coverage_json, :metadata_json, :origin)
               ON CONFLICT (path, face_index) DO UPDATE SET size = excluded.size, mtime = excluded.mtime,
                 postscript_name = excluded.postscript_name, family = excluded.family,
                 family_norm = excluded.family_norm, subfamily = excluded.subfamily,
                 names_i18n_json = excluded.names_i18n_json, manufacturer = excluded.manufacturer,
                 vendor_id = excluded.vendor_id, designer = excluded.designer,
                 coverage_json = excluded.coverage_json, metadata_json = excluded.metadata_json, origin = excluded.origin""",
            {"path": key, "size": size, "mtime": mtime, "face_index": index, "origin": origin, **info})
        if changed:                                   # changed font: old measurements no longer apply
            conn.execute("""DELETE FROM measurement WHERE local_font_id =
                            (SELECT id FROM local_font WHERE path = ? AND face_index = ?)""", (key, index))


def scan(conn: sqlite3.Connection, *, rescan: bool = False) -> ScanResult:
    """Bring the inventory up to date: font files under the roots, and on macOS the Adobe Fonts faces Core
    Text lists (`origin` adobe-sync, path `coretext:<PostScript name>`, no file read). A face the system no
    longer lists is removed with its measurements. When the listing fails, the Adobe rows already stored stay."""
    files = font_files()
    adobe: list[coretext.AdobeFace] = []
    provider = None
    unreadable = []
    keep_adobe = False
    try:
        provider = coretext.provider()
        adobe = provider.faces() if provider else []
    except Exception as exc:                          # no listing is not the same as no Adobe Fonts
        unreadable.append(f"Adobe Fonts: the font list is not readable ({type(exc).__name__})")
        keep_adobe = True
    known = {(row["path"]): (row["size"], row["mtime"]) for row in
             conn.execute("SELECT DISTINCT path, size, mtime FROM local_font")}
    stale = {row[0] for row in conn.execute("SELECT DISTINCT path FROM local_font WHERE metadata_json IS NULL")}
    present = set()
    added = updated = 0
    for root, path, stat in files:
        key = str(path)
        present.add(key)
        mtime = datetime.fromtimestamp(int(stat.st_mtime), timezone.utc).isoformat()
        unchanged = known.get(key) == (stat.st_size, mtime)
        if not rescan and unchanged and key not in stale:
            continue
        try:
            opened = faces(path)
            rows = [(index, describe(font)) for index, font in opened]
        except Exception as exc:                      # a broken file must not stop the inventory
            unreadable.append(f"{path}: {type(exc).__name__}")
            continue
        existed = key in known
        _store(conn, key, stat.st_size, mtime, root.origin, rows, existed and (rescan or not unchanged))
        if existed:
            updated += 1
        else:
            added += 1
    present.update(face.identity for face in adobe)
    changed = [face for face in adobe
               if rescan or known.get(face.identity) != (0, face.token) or face.identity in stale]
    localized, problems = provider.localized_names([face.identity for face in changed]) if changed else ({}, [])
    unreadable.extend(problems)                       # a language nobody could ask leaves that name absent
    for face in changed:
        unchanged = known.get(face.identity) == (0, face.token)
        try:
            info = describe_adobe(face, localized.get(face.identity))
        except Exception as exc:
            unreadable.append(f"{face.identity}: {type(exc).__name__}")
            continue
        existed = face.identity in known
        _store(conn, face.identity, 0, face.token, "adobe-sync", [(0, info)], existed and (rescan or not unchanged))
        if existed:
            updated += 1
        else:
            added += 1
    if keep_adobe:
        present.update(row[0] for row in conn.execute("SELECT DISTINCT path FROM local_font WHERE origin = 'adobe-sync'"))
    gone = [path for path in known if path not in present]
    conn.executemany("DELETE FROM local_font WHERE path = ?", [(path,) for path in gone])
    current = fingerprint(files, [face.identity for face in adobe])
    conn.execute("INSERT INTO meta (key, value) VALUES ('inventory_fingerprint', ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (current,))
    conn.execute("INSERT INTO meta (key, value) VALUES ('inventory_scanned_at', ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                 (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
    conn.commit()
    return ScanResult(len(files), added, updated, len(gone), unreadable, current, len(adobe))
