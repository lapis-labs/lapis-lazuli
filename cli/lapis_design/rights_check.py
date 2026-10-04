"""rights_check v0 — reference implementation of the asset-ledger detector (assets/CHECKS.md).

Reads the asset ledger (.lapis/assets.ledger.json), the fonts lock (.lapis/fonts.lock.json), the
shipped files under the scan roots, and optionally a render extract. Returns hits as
{rule_id, layer, subject, observed}; severity, waivers, and blocking come from rules.yaml.

Usage:
  lapis-design rights check [--ledger L] [--lock L] [--root ROOT] [--extract E ...]
                            [--today YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from lapis_design import font_license
from lapis_design.ours import literal_ours, source_is_ours

DEFAULT_ROOTS = ["public", "static", "assets", "src/assets", "app", "src/app", "ios", "android/app/src/main/res",
                 "android/app/src/main/assets"]
DEFAULT_EXCLUDE = ["**/node_modules/**", "**/.*/**", "**/Pods/**", "**/build/**"]
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico", ".bmp", ".tif", ".tiff",
             ".mp4", ".webm", ".mov", ".m4v", ".mp3", ".wav", ".ogg", ".m4a", ".flac",
             ".glb", ".gltf", ".usdz", ".hdr", ".exr", ".ktx2", ".lottie"}
FONT_EXT = {".woff", ".woff2", ".ttf", ".otf", ".ttc", ".eot"}

NOTICE_LICENSES = {"mit", "isc", "bsd", "apache", "ofl"}           # notices travel with distributed files
FILE_NOTICE_LICENSES = {"apache"}                                   # a copy of the license text must ship as a file
ATTRIBUTION_LICENSES = {"cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nd", "cc-by-nc-sa", "cc-by-nc-nd"}
PUBLIC_PLACEMENTS = {"adjacent", "credits-page", "about-screen"}   # where a viewer can see a credit
IMPLIED_RESTRICTIONS = {
    "cc-by-sa": {"share-alike"},
    "cc-by-nc": {"non-commercial"},
    "cc-by-nd": {"no-derivatives"},
    "cc-by-nc-sa": {"non-commercial", "share-alike"},
    "cc-by-nc-nd": {"non-commercial", "no-derivatives"},
    "editorial": {"editorial-only"},
}
DOCUMENTED_LICENSES = {"commissioned", "permission", "stock-standard", "stock-extended", "editorial", "proprietary",
                       "provider-terms", "user-terms"}
DERIVATIVE_CHANGES = {"edited", "composited"}                       # resizing, cropping, converting are not counted
MARKED_CHANGES = {"cropped", "edited", "composited"}                # changes a credit must mention
HINT_CLASSES = {"catalog-summary", "file-metadata"}
PLATFORM_CHANNELS = {"web", "ios", "android", "desktop", "email", "embedded"}
CLAIMED_RELATIONSHIPS = {"customer", "partner", "press"}            # need confirmed authorization
RELEASE_KINDS = {"photo", "video"}
FONT_NOTICE_KINDS = {"ofl": "open font license", "apache": "apache license"}   # the name a notice holding the text bears
FONT_MODIFIED = {"subset", "converted", "rebuilt"}
NON_SHIPPABLE_SOURCES = {"adobe-sync", "sandoll", "system", "user-installed"}   # as in plan_check
SHIPPING_DELIVERY = {"self-host": "web", "app-bundle": "app"}      # deliveries that hand out the files
PHASH_MAX_DISTANCE = 6                                              # of 64 bits; resized or re-encoded copies
SYMBOLS = {"\u00ae": "registered", "\u2122": "trademark"}


def _hit(rule: str, layer: str, subject: str, observed: str) -> dict:
    return {"rule_id": f"rights.{rule}", "layer": layer, "subject": subject, "observed": observed}


def _match(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


def _phash_close(a: str, b: str) -> bool:
    return bin(int(a, 16) ^ int(b, 16)).count("1") <= PHASH_MAX_DISTANCE


# ---------------------------------------------------------------- shipped files

def shipped_files(root: Path, ledger: dict | None) -> list[dict]:
    """Media and font files under the scan roots, with their sha256 (CHECKS.md, Coverage)."""
    scan = (ledger or {}).get("scan") or {}
    roots = scan.get("roots", DEFAULT_ROOTS)
    exclude = DEFAULT_EXCLUDE + scan.get("exclude", [])
    out = []
    for r in roots:
        base = root / r
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in MEDIA_EXT | FONT_EXT:
                continue
            rel = f.relative_to(root).as_posix()
            if _match(rel, exclude):
                continue
            out.append({"path": rel, "sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
    return out


def coverage(shipped: list[dict], ledger: dict | None, lock: dict | None) -> list[dict]:
    """Shipped files that no ledger entry (media) or fonts lock entry (fonts) covers."""
    entries = (ledger or {}).get("assets", [])
    globs = [f["path"] for e in entries for f in e.get("files", [])]
    hashes = {f["sha256"] for e in entries for f in e.get("files", []) if f.get("sha256")}
    font_globs = [p for e in (lock or {}).get("fonts", []) for p in e.get("files", [])]
    out = []
    for f in shipped:
        if Path(f["path"]).suffix.lower() in FONT_EXT:
            if not _match(f["path"], font_globs):
                out.append(_hit("no-provenance", "source", f["path"], "font file not in the fonts lock"))
        elif not (_match(f["path"], globs) or f.get("sha256") in hashes):
            out.append(_hit("no-provenance", "source", f["path"], "media file not in the asset ledger"))
    return out


# ---------------------------------------------------------------- ledger entries

def restrictions(entry: dict) -> set[str]:
    rights = entry["rights"]
    return set(rights.get("restrictions", [])) | IMPLIED_RESTRICTIONS.get(rights["license"], set())


def use_conflicts(entry: dict) -> list[str]:
    """Where the recorded use exceeds what the license allows (CHECKS.md, Use)."""
    r, use = restrictions(entry), entry["use"]
    out = []
    if "non-commercial" in r and use["commercial"]:
        out.append("non-commercial license in commercial use")
    if "editorial-only" in r and (use["promotional"] or not use.get("editorial")):
        out.append("editorial-only license outside editorial use")
    if "no-derivatives" in r:
        if "modified" not in entry:
            out.append("no-derivatives license; modification not recorded")
        elif entry["modified"] in DERIVATIVE_CHANGES:
            out.append(f"no-derivatives license on a {entry['modified']} file")
    if "platform-bound" in r:
        outside = sorted(set(use["channels"]) & PLATFORM_CHANNELS - set(entry["rights"].get("platforms", [])))
        if outside:
            out.append("platform-bound license used on " + ", ".join(outside))
    return out


def _attribution(entry: dict) -> list[str]:
    lic, att = entry["rights"]["license"], entry.get("attribution") or {}
    if lic in ATTRIBUTION_LICENSES:
        if not att.get("required"):
            return [f"{lic} requires credit; none recorded"]
        missing = [k for k in ("text", "placement", "license_url") if not att.get(k)]
        if missing:
            return ["credit lacks " + ", ".join(missing)]
        if att["placement"] not in PUBLIC_PLACEMENTS:
            return [f"credit placed in {att['placement']}, where viewers do not see it"]
        if entry.get("modified") in MARKED_CHANGES and not att.get("indicates_changes"):
            return [f"credit does not say the work was {entry['modified']}"]
        return []
    if att.get("required") and not (att.get("text") and att.get("placement")):
        return ["credit text or placement missing"]
    return []


def check_entry(entry: dict, today: dt.date, root: Path | None = None, ledger: dict | None = None) -> list[dict]:
    aid, rights, use = entry["id"], entry["rights"], entry["use"]
    lic, origin, out = rights["license"], entry["origin"], []
    if lic == "unknown" or origin == "unknown":
        out.append(_hit("license-unknown", "source", aid, "license or origin is unknown"))
    elif lic in DOCUMENTED_LICENSES and not rights.get("evidence"):
        out.append(_hit("license-unknown", "source", aid, f"{lic}: the governing document is not recorded"))
    elif rights.get("source_class") in HINT_CLASSES:
        out.append(_hit("license-hint-only", "source", aid, f"license taken from a {rights['source_class']}"))
    for c in use_conflicts(entry):
        out.append(_hit("use-outside-license", "source", aid, c))
    if rights.get("expires") and dt.date.fromisoformat(rights["expires"]) < today:
        out.append(_hit("license-expired", "source", aid, f"rights ended {rights['expires']}"))
    for problem in _attribution(entry):
        out.append(_hit("attribution-missing", "source", aid, problem))
    if lic in NOTICE_LICENSES and (entry.get("files") or entry.get("library")):
        out += _notices(aid, entry.get("notices", []), entry.get("notices_embedded", False), root, lic)
    mark = entry.get("mark")
    if mark and mark["relationship"] != "own":
        if mark["authorization"] == "unknown":
            out.append(_hit("unverified-mark", "source", aid, f"{mark['relationship']} mark without authorization"))
        elif mark["relationship"] in CLAIMED_RELATIONSHIPS and mark["authorization"] != "confirmed":
            out.append(_hit("unverified-mark", "source", aid,
                            f"{mark['relationship']} relationship claimed without confirmed authorization"))
    gen = entry.get("generated")
    if gen:
        out += _generated(entry, gen, ledger)
    if entry["kind"] in RELEASE_KINDS and origin != "user-content" and (use["commercial"] or use["promotional"]):
        rel = entry.get("releases") or {}
        passing = {"none-depicted", "obtained"} | ({"synthetic"} if origin == "generated" else set())
        missing = [k for k in ("people", "property") if rel.get(k, "unknown") not in passing]
        if missing:
            out.append(_hit("release-missing", "source", aid, "release status open for " + " and ".join(missing)))
    return out


def _generated(entry: dict, gen: dict, ledger: dict | None) -> list[dict]:
    aid, out = entry["id"], []
    if entry["role"] == "evidentiary":
        out.append(_hit("generated-as-evidence", "source", aid, "generated media shown as evidence"))
    if "reference-only" in gen["inputs"]:
        out.append(_hit("generated-from-reference", "source", aid, "generator input includes reference-only material"))
    if not gen["reviewed"]:
        out.append(_hit("generated-unreviewed", "source", aid, "generated media not reviewed"))
    by_id = {e["id"]: e for e in (ledger or {}).get("assets", [])}
    for ref in gen.get("input_assets", []):
        source = by_id.get(ref)
        if source is None:
            out.append(_hit("no-provenance", "source", aid, f"generator input {ref} is not in the asset ledger"))
        elif "no-generator-input" in restrictions(source):
            out.append(_hit("use-outside-license", "source", ref, f"used as generator input for {aid}"))
    return out


def _notices(subject: str, notices: list[str], embedded: bool, root: Path | None, lic: str) -> list[dict]:
    if not notices:
        if embedded and lic not in FILE_NOTICE_LICENSES:
            return []
        return [_hit("notice-missing", "source", subject, f"{lic} files ship without license notices")]
    if root is None:
        return []
    absent = [n for n in notices if not (root / n).is_file()]
    return [_hit("notice-missing", "source", subject, f"notice file absent: {n}") for n in absent]


# ---------------------------------------------------------------- fonts lock entries

def _license_text(subject: str, notices: list[str], root: Path | None, kind: str) -> list[dict]:
    """A notice file that exists must hold the license text it stands for: an empty file, a page that was
    not found, or a README is no license evidence."""
    if root is None:
        return []
    texts = [" ".join((root / n).read_bytes()[:400_000].decode("utf-8", errors="replace").lower().split())
             for n in notices if (root / n).is_file()]
    if texts and not any(FONT_NOTICE_KINDS[kind] in text for text in texts):
        return [_hit("notice-missing", "source", subject, f"no notice file holds the {kind} license text")]
    return []


def check_font(entry: dict, root: Path | None = None) -> list[dict]:
    """Release-time checks for a locked font. A font with `files` ships its files."""
    fam, lic, out = entry["family"], entry.get("license", {}), []
    ships = bool(entry.get("files"))
    if ships:
        if entry.get("source") in NON_SHIPPABLE_SOURCES:
            out.append(_hit("use-outside-license", "source", fam, f"files from source {entry['source']} ship"))
        if lic.get("kind") == "unknown":
            if font_license.state(entry) == "unknown":
                out.append(_hit("license-unknown", "source", fam, "font license unknown after research (" +
                                lic["research"].get("note", "no note") + "); it ships only after the user decides"))
            else:
                out.append(_hit("license-unresearched", "source", fam,
                                "font license is unknown and no research is recorded"))
        elif entry.get("delivery") in SHIPPING_DELIVERY:
            use = SHIPPING_DELIVERY[entry["delivery"]]
            grant = (lic.get("uses") or {}).get(use, "unknown")
            if grant == "not-allowed":
                out.append(_hit("use-outside-license", "source", fam, f"{entry['delivery']} files without a {use} grant"))
            elif grant == "unknown":
                out.append(_hit("license-unknown", "source", fam, f"no recorded {use} grant for {entry['delivery']} files"))
        if lic.get("source_class") in font_license.HINT_CLASSES:
            out.append(_hit("license-hint-only", "source", fam, f"license taken from a {lic['source_class']}"))
        if lic.get("kind") in FONT_NOTICE_KINDS:
            notices = entry.get("notices", [])
            out += _notices(fam, notices, entry.get("notices_embedded", False), root, lic["kind"])
            out += _license_text(fam, notices, root, lic["kind"])
    if lic.get("kind") == "ofl" and entry.get("modified") in FONT_MODIFIED:
        rfn = entry.get("reserved_names")
        if rfn is None:
            out.append(_hit("reserved-font-name", "source", fam, "modified font; reserved names not recorded"))
        elif rfn["names"] and not rfn["permission"]:
            shipped = entry.get("shipped_names")
            if shipped is None:
                out.append(_hit("reserved-font-name", "source", fam, "modified font with reserved names; shipped names not recorded"))
            else:
                kept = sorted({n for n in rfn["names"] for s in shipped if n.casefold() in s.casefold()})
                if kept:
                    out.append(_hit("reserved-font-name", "source", fam, "modified font keeps reserved " + ", ".join(kept)))
    return out


# ---------------------------------------------------------------- render extract

def _symbol_allowed(text: str, pos: int, name: str, entries: list[dict]) -> bool:
    before = text[:pos].rstrip()
    return any(before.casefold().endswith(e["mark"]["name"].casefold())
               for e in entries if e.get("mark", {}).get("name") and name in e["mark"].get("symbols", [])
               and (e["mark"]["relationship"] == "own" or e["mark"]["authorization"] == "confirmed"))


def check_render(extract: dict, ledger: dict | None) -> list[dict]:
    """Remote media and icon libraries without a ledger entry; mark symbols without approved guidance.
    Only our own renders are checked; reference captures are skipped."""
    if (extract.get("source") or {}).get("kind") != "render":
        return []
    source = extract["source"]
    source_host = urlsplit(source["url"]).hostname or ""
    own_source = source_is_ours(source_host, source.get("addresses"))
    entries = (ledger or {}).get("assets", [])
    user_hosts = {h for e in entries if e["origin"] == "user-content" for h in e.get("hosts", [])}
    fallback_hosts = {h for e in entries for h in e.get("hosts", [])}
    phashes = [p for e in entries for p in e.get("phashes", [])]
    libraries = {e["library"].casefold() for e in entries if e.get("library")}
    out, seen = [], set()

    def add(key: tuple, hit: dict) -> None:                        # one hit per subject across viewports
        if key not in seen:
            seen.add(key)
            out.append(hit)

    for vp in extract.get("viewports", []):
        for box in vp.get("boxes", []):
            media, icon = box.get("media") or {}, box.get("icon") or {}
            host = media.get("host")
            if (host and not media.get("placeholder") and host not in user_hosts
                    and not (own_source and (host == source_host or literal_ours(host)))):
                ph = media.get("phash")
                covered = any(_phash_close(ph, p) for p in phashes) if ph else host in fallback_hosts
                if not covered:
                    add(("media", ph or host), _hit("no-provenance", "render", box["id"],
                                                    f"media from {host} matches no asset ledger entry"))
            if icon.get("library") and icon["library"].casefold() not in libraries:
                add(("library", icon["library"].casefold()), _hit("no-provenance", "render", box["id"],
                                                                  f"icons from {icon['library']} not in the asset ledger"))
        for run in vp.get("text", []):
            text = run.get("text", "")
            for ch, name in SYMBOLS.items():
                for i, c in enumerate(text):
                    if c == ch and not _symbol_allowed(text, i, name, entries):
                        add(("symbol", run.get("box"), name), _hit("unapproved-mark-symbol", "render", run.get("box") or run["id"],
                                                                   f"{name} symbol without approved guidance for that mark"))
    return out


# ---------------------------------------------------------------- entry point

def check(ledger: dict | None, lock: dict | None, root: Path | None, today: dt.date,
          extracts: list[dict] | None = None, shipped: list[dict] | None = None) -> list[dict]:
    if shipped is None:
        shipped = shipped_files(root, ledger) if root else []
    hits = coverage(shipped, ledger, lock)
    for e in (ledger or {}).get("assets", []):
        hits += check_entry(e, today, root, ledger)
    for f in (lock or {}).get("fonts", []):
        hits += check_font(f, root)
    for x in extracts or []:
        hits += check_render(x, ledger)
    return hits


def main(argv: list[str] | None = None, prog: str = "lapis-design rights check") -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", type=Path, default=Path(".lapis/assets.ledger.json"))
    ap.add_argument("--lock", type=Path, default=Path(".lapis/fonts.lock.json"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--extract", type=Path, action="append", default=[])
    ap.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    args = ap.parse_args(argv)

    def load(p: Path) -> dict | None:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    hits = check(load(args.ledger), load(args.lock), args.root, args.today,
                 [json.loads(p.read_text(encoding="utf-8")) for p in args.extract])
    json.dump(hits, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
