"""`lazuli fetch FAMILY --into DIR`: an open-licensed family's files and license text from their official source.

The one source is the google/fonts repository, where every family sits in the folder of its license
(`ofl/<name>`, `apache/<name>`) with the license text beside its font files; the google-fonts catalog in the
lazuli database says which family is there and under which license. For a family from another official
release (a foundry's repository, a release archive) the skill `lzl-fonts` describes the same steps by hand.

Requests, in order, all through `catalog/net.py` (robots.txt, the lazuli User-Agent, the google-fonts pace kept
across runs, a stop on 401/403/429, a challenge page, or a sign-in page, and the source registry):
1. `commits/main`: the commit the files are read at, so the record names files that stay what they are.
2. the family folder's listing at that commit.
3. one request per file: the license text first, then each top-level `.ttf` or `.otf`, as the git blob the
   listing names.

Nothing is written until every file is in memory and checked: each blob must hash to the id the listing gives,
each font must start like a font file (a page that was not found or a block page is not one), and the license
file must name the license the catalog gives. A file that exists in DIR and differs is never overwritten. The
command prints the facts for `lazuli lock`; it records nothing in the lock, and the license grants stay for
you to read in the file it wrote. Static instances kept in a `static/` subfolder are not fetched.

Exit codes: 0 fetched; 1 refused, blocked, or failed (nothing written); 2 usage or missing input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
import urllib.parse
from pathlib import Path

from lazuli import db, paths
from lazuli import lock as fonts_lock
from lazuli.catalog import google_fonts, net

LICENSE_FILES = {"ofl": "OFL.txt", "apache": "LICENSE.txt"}          # the names the repository keeps them under
LICENSE_NAMES = {"ofl": "open font license", "apache": "apache license"}
LOCK_KINDS = {"ofl": "ofl", "apache": "apache"}                       # the repository's UFL has no lock kind
FONT_SUFFIXES = (".ttf", ".otf")
FONT_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf")        # TrueType, OpenType CFF, Apple, collection
COMMIT_URL = google_fonts.REPO_API + "/commits/main"
CONTENTS_URL = google_fonts.REPO_API + "/contents/{path}"
BLOB_URL = google_fonts.REPO_API + "/git/blobs/{sha}"


class Usage(Exception):
    """Missing or wrong input, or a family this command cannot fetch (exit 2)."""


class Failed(Exception):
    """The source answered, but not with what the listing promised (exit 1, nothing written)."""


def _blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _relative(project: Path, into: Path) -> str:
    target = (project / into).resolve()
    try:
        return target.relative_to(project.resolve()).as_posix()
    except ValueError:
        raise Usage(f"--into {str(into)!r} is outside the project {str(project)!r}; the files and their license "
                    "text belong inside it") from None


def _catalog_entry(conn, family: str) -> tuple[str, str, str]:
    """(the catalog's family name, the repository folder, the lock kind) of a Google Fonts family."""
    facts = fonts_lock.find_family(conn, family)
    if not facts.known:
        raise Usage(f"{family!r} is not in the lazuli DB ({paths.db_path()}): run `lazuli catalog sync`")
    listed = next((m for m in facts.matches if m["source"] == google_fonts.NAME), None)
    if listed is None:
        raise Usage(f"{facts.family!r} is not in the google-fonts catalog, and this command reads only the "
                    "google/fonts repository; for another official release take the steps in `lzl-fonts`, "
                    "Open fonts: fetching by hand")
    raw = conn.execute("SELECT raw FROM catalog_label WHERE source_id = ? AND source_key = ? AND kind = 'license'",
                       (listed["source_id"], listed["key"])).fetchone()
    directory = raw[0] if raw else None
    if directory not in google_fonts.LICENSE_DIRS:
        raise Usage(f"the repository folder of {listed['family']!r} is not known (the catalog found its name in "
                    "no license directory or in more than one): fetch it by hand")
    if directory not in LOCK_KINDS:
        raise Usage(f"{listed['family']!r} is under {google_fonts.LICENSE_DIRS[directory]}, which the fonts lock "
                    "has no kind for, so its files could not be locked")
    return listed["family"], google_fonts.repository_path(directory, listed["family"]), LOCK_KINDS[directory]


def _safe_name(name: str) -> bool:
    return bool(name) and not name.startswith(".") and not re.search(r"[/\\\x00]", name)


def fetch_family(conn, fetcher: net.Fetcher, family: str, project: Path, into: Path, log=lambda text: None) -> dict:
    name, folder, kind = _catalog_entry(conn, family)
    rel = _relative(project, into)
    prefix = "" if rel == "." else rel + "/"
    sha = fetcher.get(COMMIT_URL, headers={**google_fonts.JSON_HEADERS, "Accept": "application/vnd.github.sha"}).text().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise Failed(f"{COMMIT_URL} did not answer with a commit id")
    try:
        listing = fetcher.get(CONTENTS_URL.format(path=urllib.parse.quote(folder)), params={"ref": sha},
                              headers=google_fonts.JSON_HEADERS).json()
    except net.FetchError as exc:
        if exc.status != 404:
            raise
        raise Failed(f"{folder} is not in the repository at {sha[:10]}: the catalog may be out of date "
                     "(`lazuli catalog sync --force`), or the folder has another name; fetch it by hand") from None
    files = [e for e in listing if isinstance(e, dict) and e.get("type") == "file" and _safe_name(e.get("name", ""))]
    notice = next((e for e in files if e["name"] == LICENSE_FILES[kind]), None)
    fonts = [e for e in files if e["name"].lower().endswith(FONT_SUFFIXES)]
    if notice is None:
        raise Failed(f"{folder} holds no {LICENSE_FILES[kind]}; without the license text nothing is fetched")
    if not fonts:
        raise Failed(f"{folder} holds no top-level .ttf or .otf file (static instances may sit in a subfolder); "
                     "fetch them by hand")
    fetched: dict[str, bytes] = {}
    for entry in [notice, *fonts]:
        log(f"fetching {entry['name']}")
        data = fetcher.get(BLOB_URL.format(sha=entry["sha"]), headers=google_fonts.RAW_HEADERS).body
        if _blob_id(data) != entry["sha"]:
            raise Failed(f"{entry['name']} does not hash to the id the listing names; nothing written")
        if entry is notice:
            text = " ".join(data[:400_000].decode("utf-8", errors="replace").lower().split())
            if LICENSE_NAMES[kind] not in text:
                raise Failed(f"{entry['name']} does not name the {kind} license; nothing written")
        elif data[:4] not in FONT_MAGIC:
            raise Failed(f"{entry['name']} is not a font file; nothing written")
        fetched[entry["name"]] = data
    target = (project / rel)
    clashes = [n for n, data in fetched.items()
               if (target / n).is_symlink() or ((target / n).exists() and (target / n).read_bytes() != data)]
    if clashes:
        raise Usage(f"{', '.join(clashes)} already exist in {rel} as a link or with other content; choose another "
                    "--into or remove them first")
    target.mkdir(parents=True, exist_ok=True)
    for file_name, data in fetched.items():
        (target / file_name).write_bytes(data)
    suffixes = sorted({Path(e["name"]).suffix.lower() for e in fonts})
    source_url = f"{google_fonts.REPO_PAGE}/tree/{sha}/{folder}"
    license_url = f"{google_fonts.REPO_PAGE}/blob/{sha}/{folder}/{notice['name']}"
    result = {
        "family": name, "source": google_fonts.NAME, "source_url": source_url, "into": rel,
        "license": {"kind": kind, "url": license_url, "file": f"{prefix}{notice['name']}"},
        "files": [{"path": f"{prefix}{e['name']}", "bytes": len(fetched[e["name"]]),
                   "sha256": hashlib.sha256(fetched[e["name"]]).hexdigest()} for e in fonts],
    }
    glob_args = " ".join(shlex.quote(f"{prefix}*{suffix}") for suffix in suffixes)
    result["lock"] = (f"lazuli lock {shlex.quote(name)} --role ROLE --task TASK --source {google_fonts.NAME} "
                      f"--source-url {source_url} --delivery self-host --files {glob_args} --modified none "
                      f"--notice {shlex.quote(result['license']['file'])} --license-kind {kind} "
                      "--use web=GRANT app=GRANT --research verified "
                      f"--evidence license-file {license_url} --quote 'THE WORDS THAT GRANT THE USE'")
    return result


def render(result: dict) -> str:
    lines = [f"fetched {result['family']} ({result['source']}, {result['license']['kind']}) into {result['into']}"]
    lines += [f"  {f['path']}  {f['bytes']} bytes  sha256 {f['sha256']}" for f in result["files"]]
    lines += [f"  {result['license']['file']}  the license text",
              f"source: {result['source_url']}",
              f"license text: {result['license']['url']}",
              "next: read the license text and the font's name records (`lazuli license`), then lock the files with "
              "what you read in place of GRANT and THE WORDS:",
              f"  {result['lock']}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None, prog: str = "lazuli fetch") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Fetch an open-licensed Google Fonts family's font files "
                                 "and license text from the google/fonts repository into the project.")
    ap.add_argument("family", metavar="FAMILY", help="family or i18n name as the lazuli DB knows it")
    ap.add_argument("--into", type=Path, required=True, metavar="DIR", help="folder in the project for the files")
    ap.add_argument("--project", type=Path, default=Path("."), metavar="DIR", help="project folder (default: .)")
    ap.add_argument("--json", action="store_true", help="machine output")
    args = ap.parse_args(argv)
    if not args.project.is_dir():
        ap.error(f"--project {str(args.project)!r} is not a folder")
    conn = db.connect(paths.db_path())
    try:
        fetcher = net.Fetcher(google_fonts.NAME, min_interval_s=google_fonts.MIN_INTERVAL_S, conn=conn)
        result = fetch_family(conn, fetcher, args.family, args.project, args.into,
                              log=lambda text: print(text, file=sys.stderr))
    except Usage as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except net.Blocked as exc:
        print(f"blocked: {exc.reason}; nothing written. Open the source in your browser instead, "
              f"{google_fonts.REPO_PAGE}", file=sys.stderr)
        return 1
    except (Failed, net.FetchError) as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    if args.json:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        print(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
