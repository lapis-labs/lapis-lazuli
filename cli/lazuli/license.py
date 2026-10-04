"""`lazuli license FAMILY`: what a font says about its own license, and where to look for the governing one.

Read-only; no request is sent. For each installed file of the family (the lazuli inventory, `lazuli local
fonts`) it prints the name records that bear on a license (copyright, license text, license URL, trademark,
manufacturer, designer, vendor and designer URLs), where the file sits and what that suggests installed it,
and the license-looking files in its folder (names only). An Adobe Fonts activation (`adobe-sync`) has no
file lazuli opens: the command says so and prints no file record. Catalog license labels and the project's
recorded research for the family come next, then the search phrases and places to try.

Everything printed is a lead. A name record, a catalog badge, and a folder name are hints (`font-metadata`
in the lock), never the grant; the governing document is the license that came with the files, the rights
holder's page, the delivering service's terms, or the terms of what installed the font. Record what you find
with `lazuli lock --research`.

Exit codes: 0 printed; 2 usage or an unknown family.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from lapis_design import font_license
from lazuli import db, paths, scan
from lazuli import lock as fonts_lock

LICENSE_LOOKING = re.compile(r"(?i)^(ofl|license|licence|copying|eula|notice|terms|fontlog|readme)\b[^/]*$")
# Folder-name tokens of font managers, matched against each segment of the path (an inference, said so)
MANAGERS = (("fontbase", "FontBase"), ("rightfont", "RightFont"), ("monotype", "Monotype Fonts"),
            ("fontstand", "Fontstand"), ("typekit", "Adobe Fonts"), ("adobe", "Adobe"))
HOME_FOLDERS = ("library/fonts", "appdata/local/microsoft/windows/fonts", ".fonts", ".local/share/fonts")


def installer(origin: str, path: str | None) -> dict:
    """What installed or delivered a font, inferred from its origin and where it sits."""
    if origin == "adobe-sync":
        return {"kind": "adobe-fonts", "note": "an Adobe Fonts activation: its terms are the subscription's, and a "
                "synced desktop font never ships as web files; lazuli opens no file of it"}
    if origin == "system":
        return {"kind": "operating-system", "note": "shipped with the operating system: the system's license "
                "agreement governs its use, and it is not a font to ship"}
    text = (path or "").replace("\\", "/").casefold()
    for token, name in MANAGERS:
        if any(token in segment for segment in text.split("/")):
            return {"kind": "font-manager", "name": name, "note": f"the path names {name}: its terms and the font's "
                    "own license both apply (inferred from the path)"}
    if any(folder in text for folder in HOME_FOLDERS):
        return {"kind": "user-folder", "note": "the user's own font folder: something or someone put the file there, "
                "so the file's own license decides (ask where it came from)"}
    return {"kind": "other-folder", "note": "a project or company font folder: ask the user where the files came from"}


def _license_files(path: Path) -> list[str]:
    folder = path.parent
    if not fonts_lock._enterable(folder):
        return []
    try:
        return sorted(e.name for e in os.scandir(folder) if e.is_file() and LICENSE_LOOKING.match(e.name))
    except OSError:
        return []


def _said(item: dict) -> dict:
    """What a file's records say about the license; a trademark line names the style, so it does not tell two
    files of one release apart."""
    return {k: v for k, v in item.get("records", {}).items() if k != "trademark"}


def _file(path: Path, origin: str) -> dict:
    records = fonts_lock.read_file(path)
    out = {"origin": origin, "folder": str(path.parent), "files": [path.name],
           "installer": installer(origin, str(path)), "license_files": _license_files(path)}
    if records.error:
        out["error"] = records.error
        return out
    out["records"] = {key: getattr(records, key) for key in ("copyright", "license", "license_url", "trademark",
                                                             "manufacturer", "designer", "vendor_url", "designer_url")
                      if getattr(records, key)}
    return out


def collect(conn, family: str, project: Path) -> dict:
    facts = fonts_lock.find_family(conn, family)
    if not facts.known:
        raise LookupError(f"{family!r} is unknown to the lazuli DB ({paths.db_path()}): run `lazuli local fonts` "
                          "(installed fonts) or `lazuli catalog sync` (catalogs)")
    seen: set[str] = set()
    installed: list[dict] = []
    for face in facts.faces:
        if face["origin"] == "adobe-sync":
            if "adobe-sync" not in seen:
                seen.add("adobe-sync")
                installed.append({"origin": "adobe-sync", "folder": None, "files": [],
                                  "installer": installer("adobe-sync", None), "license_files": []})
        elif face["path"] not in seen and Path(face["path"]).is_file():
            seen.add(face["path"])
            item = _file(Path(face["path"]), face["origin"])
            same = next((i for i in installed if (i["origin"], i["folder"], i.get("error"), _said(i)) ==
                         (item["origin"], item["folder"], item.get("error"), _said(item))), None)
            if same:
                same["files"] += item["files"]               # files that say the same thing are shown once
            else:
                installed.append(item)
    catalog = [{"source": lb["source"], "raw": lb["raw"], "license": lb["mapped"]}
               for lb in facts.labels if lb["kind"] == "license"]
    recorded = []
    try:
        lock = fonts_lock.load_lock(project / fonts_lock.LOCK_FILE)
    except (ValueError, OSError):
        lock = None
    for entry in (lock or {}).get("fonts", []):
        if scan.norm(entry.get("family")) == scan.norm(facts.family):
            research = (entry.get("license") or {}).get("research") or {}
            recorded.append({"role": entry["role"], "state": font_license.state(entry),
                             "outcome": research.get("outcome"), "evidence": len(research.get("evidence", []))})
    maker = next((v for rec in installed for key in ("manufacturer", "designer") for v in rec.get("records", {}).get(key, [])), None)
    search = [f'"{facts.family}" font license', f'"{facts.family}" {maker} license' if maker else None,
              f'"{facts.family}" EULA OR "open font license" OR "end user license"']
    return {"family": facts.family, "installed": installed, "catalog": catalog, "lock": recorded,
            "search": [q for q in search if q],
            "catalog_pages": [m["url"] for m in facts.matches if m.get("url")]}


def render(found: dict) -> str:
    lines = [f"license facts for {found['family']} (hints until a document is read)"]
    if not found["installed"]:
        lines.append("installed: no file of this family is installed; only catalog hints below")
    for item in found["installed"]:
        if item["folder"]:
            names = ", ".join(item["files"][:4]) + (", ..." if len(item["files"]) > 4 else "")
            where = f"{item['folder']} ({len(item['files'])} files: {names})"
        else:
            where = "no file (read through the system font list)"
        lines.append(f"installed ({item['origin']}): {where}")
        lines.append(f"  installer: {item['installer']['note']}")
        if item.get("error"):
            lines.append(f"  records: {item['error']}")
        for key, values in item.get("records", {}).items():
            lines.append(f"  {key.replace('_', ' ')}: " + " | ".join(values))
        if item.get("records") is not None and not item["records"]:
            lines.append("  records: the file names no copyright, license, or maker")
        if item["license_files"]:
            lines.append("  license-looking files in its folder (it may belong to another font): "
                         + ", ".join(item["license_files"]))
    for label in found["catalog"]:
        lines.append(f"catalog {label['source']}: license {label['raw']!r} (maps to {label['license']}) - a hint")
    for page in found["catalog_pages"]:
        lines.append(f"catalog page: {page}")
    for entry in found["lock"]:
        detail = f", outcome {entry['outcome']}, {entry['evidence']} evidence" if entry["outcome"] else ""
        lines.append(f"fonts lock ({entry['role']}): research state {entry['state']}{detail}")
    lines.append("search for the governing document (a lead, not a fact): " + "; ".join(found["search"]))
    lines.append("then record it: lazuli lock <family> --role R --task T --license-kind K --research "
                 "verified|restricted|unknown-after-research --evidence VIA URL --quote TEXT (lzl-fonts, License research)")
    return "\n".join(lines)


def main(argv: list[str] | None = None, prog: str = "lazuli license") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Print what a font says about its own license and where to "
                                 "look for the governing one (read-only, sends nothing).")
    ap.add_argument("family", metavar="FAMILY", help="family or i18n name as the lazuli DB knows it")
    ap.add_argument("--project", type=Path, default=Path("."), metavar="DIR",
                    help="project folder whose fonts lock shows the recorded research (default: .)")
    ap.add_argument("--json", action="store_true", help="machine output")
    args = ap.parse_args(argv)
    conn = db.connect(paths.db_path())
    try:
        found = collect(conn, args.family, args.project)
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        conn.close()
    if args.json:
        json.dump(found, sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        print(render(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
