"""`lazuli owned add|list|remove`: fonts the owner has a right to use but has not installed, by name only.

A name is all that is kept: a family or a PostScript name the owner gives in a text file (one per line, `#`
comments allowed) or a JSON list of strings, and the source they say it comes from (`adobe`: a subscription
whose fonts they can activate). No catalog is asked, no file is read, and nothing is measured, so an owned
name has no class, script, or weight until the font is installed and `lazuli local fonts` measures it. The list
lives in the user cache (`owned.json`), never in the lazuli database, and no measurement, calibration, or
evaluation path reads it.

`lazuli search QUERY` shows an owned name that matches the query and is not installed as a candidate that
`needs activation`: the owner activates it (or has the agent propose `lazuli adobe activate` and says yes in
words that can be quoted), then `lazuli local fonts` lists the installed face and measures it. An installed
family that is on the list says so in its evidence.

add     --from FILE --source adobe: add the names the file holds
list    the names, each marked not installed or installed (as the lazuli database lists it now)
remove  NAME: delete one name
Exit codes: 0 done; 1 remove found no such name; 2 usage (an unreadable file, no name in it, a source that is not known).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from lazuli import db, paths
from lazuli.adobe import clean, config
from lazuli.scan import norm

SOURCES = ("adobe",)
MAX_NAMES = 500
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")


def owned_path() -> Path:
    return paths.cache_dir() / "owned.json"


def load() -> list[dict]:
    try:
        data = json.loads(owned_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get("fonts") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("name"), str)] if isinstance(rows, list) else []


def _save(rows: list[dict]) -> None:
    path = owned_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "fonts": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def parse_names(text: str) -> list[str]:
    """The names in a file's text: a JSON list of strings, or one name per line (bullets, blank lines, and `#`
    comments dropped). Each name is cleaned to one line; a name that is nothing after cleaning is dropped."""
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    raw = data if isinstance(data, list) else [_BULLET.sub("", line) for line in text.splitlines()
                                               if line.strip() and not line.lstrip().startswith("#")]
    names = [n for item in raw if (n := clean.text(item if isinstance(item, str) else None, 80))]
    return list(dict.fromkeys(names))


def installed_keys(conn) -> set[str]:
    """Normalized family and PostScript names of every installed face the database lists."""
    keys: set[str] = set()
    for row in conn.execute("SELECT family, postscript_name FROM local_font"):
        keys.update(k for k in (norm(row["family"]), norm(row["postscript_name"])) if k)
    return keys


def add(names: list[str], source: str) -> tuple[list[dict], list[str]]:
    """Add `names` from `source`; returns (the rows now on the list, the names that were already there)."""
    rows = load()
    have = {(norm(r["name"]), r.get("source")) for r in rows}
    repeated = []
    for name in names:
        key = (norm(name), source)
        if key in have:
            repeated.append(name)
            continue
        rows.append({"name": name, "source": source, "status": "not-installed", "added_at": config.now()})
        have.add(key)
    if len(rows) > MAX_NAMES:
        raise ValueError(f"the owned list holds at most {MAX_NAMES} names")
    _save(rows)
    return rows, repeated


def remove(name: str) -> bool:
    rows = load()
    kept = [r for r in rows if norm(r["name"]) != norm(name)]
    if len(kept) == len(rows):
        return False
    _save(kept)
    return True


def evidence(mark: dict, installed: bool) -> str:
    """The evidence line of a candidate that is on the owned list."""
    source = mark.get("source", "?")
    if installed:
        return f"on your owned list ({source})"
    return (f"owned ({source}), not installed: needs activation (a name only; its scripts, class, and weights are "
            "unknown until it is installed and `lazuli local fonts` measures it)")


def candidates(conn, installed: dict, existing: list[dict], args, notes: list[str]) -> list[dict]:
    """Search's owned-list part: mark the installed families that are on the list (`owned` on the candidate), and return
    one candidate per owned name that is not installed, when the search has a QUERY and no filter (a name carries no
    script, class, or license to filter by; with a filter the names are left out and a note says how many)."""
    rows = [r for r in load() if norm(r["name"])]
    if not rows:
        return []
    listed = {}
    for r in rows:
        listed.setdefault(norm(r["name"]), r)
    for family in installed.values():
        hit = next((listed[k] for name in (family["family"], *family["postscript"]) if (k := norm(name)) in listed), None)
        if hit:
            family["owned"] = {"source": hit.get("source"), "name": hit["name"]}
    present = installed_keys(conn)
    missing = [r for r in rows if norm(r["name"]) not in present]
    narrowed = (args.script or args.role or args.category or args.license == "open" or args.delivery or args.installed
                or args.similar_to)
    if narrowed:
        if missing:
            notes.append(f"{len(missing)} owned names that are not installed are left out of a filtered search: only a name is "
                         "known, so no script, class, or license can be filtered (`lazuli owned list`)")
        return []
    return [{"family": r["name"], "names_i18n": {}, "installed": False, "origins": [], "faces": 0, "postscript": [r["name"]],
             "makers": [], "scripts": [], "classes": [], "labels": [], "genres": [], "license": None, "catalogs": [],
             "measured": [], "text_rows": [], "owned": {"source": r.get("source"), "name": r["name"]}} for r in missing]


def status(rows: list[dict], keys: set[str]) -> list[dict]:
    """Each row with `installed` set by what the database lists now."""
    return [{**r, "installed": (norm(r["name"]) or "") in keys} for r in rows]


def _parser(prog: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    add_p = sub.add_parser("add", help="add the names a file holds")
    add_p.add_argument("--from", dest="source_file", metavar="FILE", required=True, type=Path,
                       help="a text file with one name per line, or a JSON list of names")
    add_p.add_argument("--source", choices=SOURCES, required=True, help="where the owner holds the fonts")
    list_p = sub.add_parser("list", help="the names on the list")
    list_p.add_argument("--json", action="store_true")
    rm = sub.add_parser("remove", help="delete one name")
    rm.add_argument("name")
    return ap


def main(argv: list[str] | None = None, prog: str = "lazuli owned") -> int:
    ap = _parser(prog)
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if args.verb == "add":
        try:
            names = parse_names(args.source_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            print(f"cannot read {args.source_file}: {exc}", file=sys.stderr)
            return 2
        if not names:
            print(f"{args.source_file} holds no name (one per line, `#` comments allowed)", file=sys.stderr)
            return 2
        try:
            rows, repeated = add(names, args.source)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"added {len(names) - len(repeated)} of {len(names)} names from {args.source} (not installed); "
              f"{len(rows)} on the list: {owned_path()}")
        if repeated:
            print(f"already listed: {', '.join(repeated)}")
        print("names only: nothing was read from a font or asked of a catalog; `lazuli search` shows them as needing "
              "activation until the font is installed")
        return 0
    if args.verb == "remove":
        if remove(args.name):
            print(f"removed {args.name!r}")
            return 0
        print(f"{args.name!r} is not on the owned list", file=sys.stderr)
        return 1
    conn = db.connect(paths.db_path())
    try:
        rows = status(load(), installed_keys(conn))
    finally:
        conn.close()
    if args.json:
        json.dump({"fonts": rows}, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0
    print(f"{len(rows)} owned font name{'s' if len(rows) != 1 else ''} ({owned_path()})")
    for r in rows:
        print(f"  {r['name']}  [{r.get('source', '?')}; {'installed' if r['installed'] else 'not installed, needs activation'}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
