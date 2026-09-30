"""`lazuli class set|list|remove`: font classes the user gives, kept in the lazuli DB in the user cache.

A user class is one family's genre (a Latin genre or Hangul class id of vocab/type.yaml, as
`lazuli.catalog.labels` gives them) and optionally a subclass of that genre, with an optional link to
where the user read it, such as an Adobe Fonts page, which lazuli never collects from. It holds only
those values: no font files and no page content, and the link is never opened. User classes never go into a
project or the repository.

The user class outranks every catalog: `v_font_label` and `store.user_label_rows` give it as source `user`
ahead of all catalog priorities, so `lazuli local fonts`, `search`, and `lock` take the family's genre
and subclass from it and show `user` as their source. It replaces the catalogs' genre and subclass
together and leaves their other labels (license, scripts, weights) in place. `lock` names it as a hint
and writes none of it into the lock.

FAMILY is found as `lazuli lock` finds it: an installed or catalog family by its name or an i18n name
(normalized), and the class keeps the lazuli DB's name. A family the DB does not know yet keeps the name
given and gets the class once a family of that name is installed or synced.

set     record the class of FAMILY, replacing all of an earlier one: --genre ID [--subclass ID] [--url URL]
list    every user class, or FAMILY's
remove  delete FAMILY's user class
Exit codes: 0 done; 1 remove found no user class; 2 usage (a genre or subclass outside the vocabulary, a bad link).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from datetime import datetime, timezone

from lazuli import db, lock, paths, scan
from lazuli.catalog import labels, store


class ClassError(ValueError):
    """A value the class cannot take (exit 2)."""


def check_genre(value: str) -> str:
    genre = value.strip().lower()
    if genre not in labels.GENRES:
        raise ClassError(f"{value!r} is not a genre of the type vocabulary; use one of: "
                         f"{', '.join(sorted(labels.GENRES))}")
    return genre


def check_subclass(genre: str, value: str | None) -> str | None:
    """The `genre.subclass` id for a full or short subclass id (`min-bu-ri.rounded` or `rounded`)."""
    if value is None:
        return None
    own = sorted(s for s in labels.SUBCLASSES if s.startswith(genre + "."))
    if not own:
        raise ClassError(f"{genre} has no subclasses in the type vocabulary")
    text = value.strip().lower()
    subclass = text if "." in text else f"{genre}.{text}"
    if subclass not in own:
        raise ClassError(f"{value!r} is not a subclass of {genre}; use one of: {', '.join(own)}")
    return subclass


def check_url(value: str | None) -> str | None:
    if value is None:
        return None
    parts = urllib.parse.urlsplit(value.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ClassError("--url takes a plain http(s) link to the page where you read the class, without a user "
                         "name or password")
    return value.strip()


def resolve_family(conn, name: str) -> tuple[str, str]:
    """(the family name to classify, where lazuli knows it: `installed`, `catalog`, or `unknown`)."""
    facts = lock.find_family(conn, name)
    if not facts.known:
        return name.strip(), "unknown"
    return facts.family, "installed" if any(f["family"] == facts.family for f in facts.faces) else "catalog"


def _keys(conn, name: str) -> list[str]:
    """The normalized names a user class of `name` may be kept under: the name given and the lazuli DB's name."""
    return list(dict.fromkeys(k for k in (scan.norm(name), scan.norm(resolve_family(conn, name)[0])) if k))


def _installed(conn) -> set[str]:
    return {row[0] for row in conn.execute("SELECT DISTINCT family_norm FROM local_font WHERE family_norm IS NOT NULL")}


def _classes(label: dict) -> str:
    return f"genre {label['genre']}" + (f", subclass {label['subclass']}" if label["subclass"] else "")


def _set(args) -> int:
    try:
        genre = check_genre(args.genre)
        subclass = check_subclass(genre, args.subclass)
        url = check_url(args.url)
    except ClassError as exc:
        print(f"{args.prog} set: {exc}", file=sys.stderr)
        return 2
    conn = db.connect(paths.db_path())
    try:
        family, known = resolve_family(conn, args.family)
        key = scan.norm(family)
        if not key:
            print(f"{args.prog} set: give a family name", file=sys.stderr)
            return 2
        replaced = conn.execute("SELECT 1 FROM user_label WHERE family_norm = ?", (key,)).fetchone() is not None
        recorded = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute("""INSERT INTO user_label (family_norm, family, genre, subclass, url, recorded_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT (family_norm) DO UPDATE SET family = excluded.family, genre = excluded.genre,
                          subclass = excluded.subclass, url = excluded.url, recorded_at = excluded.recorded_at""",
                     (key, family, genre, subclass, url, recorded))
        conn.commit()
    finally:
        conn.close()
    out = {"family": family, "genre": genre, "subclass": subclass, "url": url, "recorded_at": recorded,
           "replaced": replaced, "known": known, "database": str(paths.db_path())}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"{'replaced' if replaced else 'classified'} {family}: {_classes(out)} ({store.USER_SOURCE})")
        print("it outranks catalog classes in `lazuli local fonts`, `search`, and `lock`; kept in the lazuli "
              f"database ({out['database']}), a user cache that never goes into a project")
    if known == "unknown":
        print(f"note: {family!r} is not installed and in no synced catalog; the class applies once a family of "
              "that name is (check the name with `lazuli local fonts --family`)", file=sys.stderr)
    return 0


def _list(args) -> int:
    rows: list[dict] = []
    path = paths.db_path()
    if path.exists():                                   # listing never creates the database
        conn = db.connect(path)
        try:
            mine = store.user_labels(conn)
            if args.family is not None:
                wanted = set(_keys(conn, args.family))
                mine = {k: v for k, v in mine.items() if k in wanted}
            installed = _installed(conn)
        finally:
            conn.close()
        rows = [{**label, "installed": key in installed} for key, label in mine.items()]
    if args.json:
        print(json.dumps({"database": str(path), "classes": rows}, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("no user classes yet" + (f" for {args.family!r}" if args.family else "")
              + "; add one with `lazuli class set FAMILY --genre ID`")
        return 0
    print(f"{len(rows)} user class{'es' if len(rows) != 1 else ''} in {path}")
    for row in rows:
        print(f"  {row['family']}  {_classes(row)}  {'installed' if row['installed'] else 'not installed'}  "
              f"{row['recorded_at'][:10]}" + (f"  {row['url']}" if row["url"] else ""))
    return 0


def _remove(args) -> int:
    removed: str | None = None
    path = paths.db_path()
    if path.exists():
        conn = db.connect(path)
        try:
            for key in _keys(conn, args.family):
                row = conn.execute("SELECT family FROM user_label WHERE family_norm = ?", (key,)).fetchone()
                if row is not None:
                    removed = row[0]
                    conn.execute("DELETE FROM user_label WHERE family_norm = ?", (key,))
            conn.commit()
        finally:
            conn.close()
    if args.json:
        print(json.dumps({"family": removed or args.family, "removed": removed is not None, "database": str(path)},
                         ensure_ascii=False, indent=2))
    elif removed is not None:
        print(f"removed the user class of {removed}; its catalog classes apply again")
    if removed is None:
        print(f"no user class for {args.family!r}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None, prog: str = "lazuli class") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Font classes you give for a family (for example read on "
                                 "a catalog page lazuli does not collect from), kept in the lazuli database in the "
                                 "user cache. They outrank catalog classes.")
    sub = ap.add_subparsers(dest="command", required=True)
    put = sub.add_parser("set", help="record a family's genre and subclass (replaces an earlier class)")
    put.add_argument("family", metavar="FAMILY", help="family or i18n name as the lazuli DB knows it")
    put.add_argument("--genre", required=True, metavar="ID", help=f"one of: {', '.join(sorted(labels.GENRES))}")
    put.add_argument("--subclass", metavar="ID", help="a subclass of the genre, e.g. rounded or min-bu-ri.rounded")
    put.add_argument("--url", help="where you read the class (kept as a link, never opened)")
    put.add_argument("--json", action="store_true")
    show = sub.add_parser("list", help="the classes you gave")
    show.add_argument("family", nargs="?", metavar="FAMILY")
    show.add_argument("--json", action="store_true")
    drop = sub.add_parser("remove", help="delete a family's class")
    drop.add_argument("family", metavar="FAMILY")
    drop.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    args.prog = prog
    return {"set": _set, "list": _list, "remove": _remove}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
