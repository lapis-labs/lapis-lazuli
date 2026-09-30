"""`lazuli catalog sync|lookup|status`: font catalogs, requested only on command and cached only locally.

sync     snapshot and bundled sources whose ttl expired (all of them with --force); a source that fails
         keeps its previous rows and is marked failed with the reason. A failed source is not requested
         again by a plain `sync`; name it with --source (or use --force) to try again.
lookup   on-request sources, only for installed families no snapshot or bundled source matched; fresh
         cached answers are reused. The plan (requests and time at the source's pace) is shown first,
         and more than 10 requests need confirmation unless --yes. A block stops the source and marks
         it failed; a failed source is skipped unless named with --source.
status   sources, fetch dates, ttl state, family counts, status and reason.
Matching reruns after sync and lookup (and after `lazuli local fonts` scans).
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta

from lazuli import catalog, db, paths
from lazuli.catalog import match, net, store
from lazuli.scan import norm

CONFIRM_ABOVE = 10                   # requests a lookup may send without asking
EARLY_REFRESH_DAYS = 1               # a snapshot missing installed fonts refreshes at most this often
YOON_DESIGN = ("yoon-design: no adapter. Yoon Design blocks tools; open the family page in your browser, "
               "or give the link to the task, and read its classification and license there.")


def _source_row(conn, name: str):
    return conn.execute("SELECT * FROM source WHERE name = ?", (name,)).fetchone()


def _fetched(row) -> datetime | None:
    return datetime.fromisoformat(row["fetched_at"]) if row is not None and row["fetched_at"] else None


def _not_retried(conn, module, retry: str) -> str | None:
    """Why a failed source is skipped by a run that did not name it, or None when it has not failed."""
    row = _source_row(conn, module.NAME)
    if row is None or row["status"] != "failed":
        return None
    return (f"failed earlier ({store.reason(conn, module.NAME) or 'no reason kept'}); not retried. "
            f"Run `{retry}` to try again")


def _due(conn, module, *, force: bool, named: bool) -> str | None:
    """None when the source should sync now, otherwise why it is skipped."""
    if force or module.KIND == "bundled":
        return None
    if (failed := _not_retried(conn, module, f"lazuli catalog sync --source {module.NAME}")) is not None:
        return None if named else failed
    fetched = _fetched(_source_row(conn, module.NAME))
    if fetched is None:
        return None
    expires = fetched + timedelta(days=module.TTL_DAYS)
    if expires <= store.now():
        return None
    missing = getattr(module, "missing_installed", None)
    if missing is not None and store.now() - fetched >= timedelta(days=EARLY_REFRESH_DAYS) and missing(conn):
        return None
    return f"fresh until {expires.date()}; use --force to sync anyway"


def _fetcher(conn, module) -> net.Fetcher:
    return net.Fetcher(module.NAME, min_interval_s=module.MIN_INTERVAL_S, conn=conn)


def _report_match(conn) -> None:
    stats = match.run(conn)
    detail = ", ".join(f"{name} {count}" for name, count in stats["by_source"].items())
    print(f"matched {stats['matched']} of {stats['faces']} installed faces" + (f" ({detail})" if detail else ""))


def sync(conn, names: list[str] | None, *, force: bool) -> int:
    known = {m.NAME: m for m in catalog.SOURCES}
    for name in names or ():
        if name not in known:
            print(f"unknown source {name!r}; sources: {', '.join(known)}", file=sys.stderr)
            return 2
        if known[name].KIND == "lookup":
            print(f"{name} is looked up on request; use `lazuli catalog lookup --source {name}`", file=sys.stderr)
            return 2
    modules = [m for m in catalog.SOURCES if m.KIND != "lookup" and (not names or m.NAME in names)]
    failed = synced = 0
    for module in modules:
        if refused := getattr(module, "REFUSED", None):   # the source's terms forbid collection
            _disable(conn, module, refused)
            print(f"{module.NAME}: disabled: {refused}")
            continue
        if (skip := _due(conn, module, force=force, named=bool(names))) is not None:
            print(f"{module.NAME}: {skip}")
            continue
        store.ensure_source(conn, module)
        conn.commit()
        fetcher = _fetcher(conn, module)
        started = time.monotonic()
        try:
            count = store.replace_snapshot(conn, module, module.fetch(fetcher))
        except net.Blocked as blocked:
            store.mark(conn, module, "failed", blocked.reason)
            print(f"{module.NAME}: blocked: {blocked.reason}. Previous rows kept; not retried.")
            failed += 1
            continue
        except Exception as exc:                          # a failed source keeps its previous rows
            reason = f"{type(exc).__name__}: {exc}"
            store.mark(conn, module, "failed", reason)
            print(f"{module.NAME}: failed: {reason}. Previous rows kept.")
            failed += 1
            continue
        synced += 1
        print(f"{module.NAME}: {count} families, {fetcher.requests} requests, {time.monotonic() - started:.1f} s")
    if synced:
        _report_match(conn)
    return 1 if failed else 0


def _disable(conn, module, reason: str) -> None:
    store.ensure_source(conn, module)
    store.mark(conn, module, "disabled", reason)
    conn.commit()


def _plan_line(module, pending: list[dict], cached: int) -> tuple[str, int]:
    per_family = getattr(module, "REQUESTS_PER_LOOKUP", 1)
    requests = len(pending) * per_family + 1 if pending else 0          # + robots.txt
    seconds = requests * module.MIN_INTERVAL_S
    line = (f"{module.NAME}: {len(pending)} families to look up, about {requests} requests "
            f"({per_family} per family + robots.txt), at least {_duration(seconds)} at "
            f"{module.MIN_INTERVAL_S:g} s between requests")
    if cached:
        line += f"; {cached} answered from the cache"
    return line, requests


def _duration(seconds: float) -> str:
    return f"{seconds:.0f} s" if seconds < 120 else f"{seconds / 60:.0f} min"


def lookup(conn, source: str | None, family: str | None, *, limit: int | None, yes: bool) -> int:
    modules = [m for m in catalog.SOURCES if m.KIND == "lookup"]
    if source is not None:
        if source not in {m.NAME for m in modules}:
            print(f"{source!r} is not a lookup source; lookup sources: {', '.join(m.NAME for m in modules)}",
                  file=sys.stderr)
            return 2
        modules = [m for m in modules if m.NAME == source]
    candidates = match.unmatched(conn, family)
    if family is not None and not candidates:
        installed = conn.execute("SELECT 1 FROM local_font WHERE family_norm LIKE '%' || ? || '%' "
                                 "OR names_i18n_json LIKE '%' || ? || '%' LIMIT 1", (norm(family), family)).fetchone()
        print(f"{family}: already matched by a snapshot catalog; nothing to look up" if installed
              else f"no installed family matches {family!r}", file=sys.stderr if not installed else sys.stdout)
        return 0 if installed else 1
    plans, total = [], 0
    for module in modules:
        if refused := getattr(module, "REFUSED", None):   # no request; links for the browser instead
            _disable(conn, module, refused)
            if source is None:
                print(f"{module.NAME}: disabled: {refused}")
                continue
            for entry in candidates[:limit] if limit is not None else candidates:
                try:
                    module.lookup(None, entry["family"], names_i18n=entry["names_i18n"] or None,
                                  postscript_name=entry["postscript_name"])
                except net.Blocked as blocked:
                    print(f"  {entry['family']}: {blocked.reason}")
            continue
        if source is None and (failed := _not_retried(
                conn, module, f"lazuli catalog lookup --source {module.NAME} ...")) is not None:
            print(f"{module.NAME}: {failed}")
            continue
        pending = [c for c in candidates if store.cached_lookup(conn, module, norm(c["family"])) == "miss"]
        cached = len(candidates) - len(pending)
        pending = pending[:limit] if limit is not None else pending
        line, requests = _plan_line(module, pending, cached)
        print(line)
        if pending:
            shown = ", ".join(c["family"] for c in pending[:10])
            print(f"  {shown}" + (f", and {len(pending) - 10} more" if len(pending) > 10 else ""))
        plans.append((module, pending))
        total += requests
    if not total:
        print("nothing to request")
        _report_match(conn)
        return 0
    if total > CONFIRM_ABOVE and not yes:
        try:
            answer = input(f"Send about {total} requests? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("nothing requested")
            return 1
    failed = 0
    for module, pending in plans:
        if not pending:
            continue
        store.ensure_source(conn, module)
        conn.commit()
        fetcher = _fetcher(conn, module)
        started, found, reason = time.monotonic(), 0, None
        for entry in pending:
            try:
                answer = module.lookup(fetcher, entry["family"], names_i18n=entry["names_i18n"] or None,
                                       postscript_name=entry["postscript_name"])
            except net.Blocked as blocked:
                reason = blocked.reason
                print(f"{module.NAME}: blocked: {reason}. Stopped; not retried.")
                break
            except Exception as exc:                      # stop this source; answers so far stay cached
                reason = f"{type(exc).__name__}: {exc}"
                print(f"{module.NAME}: failed: {reason}. Stopped.")
                break
            store.save_lookup(conn, module, norm(entry["family"]), answer, module.TTL_DAYS)
            found += answer is not None
            print(f"  {entry['family']}: " + (f"{answer.family} ({answer.url or answer.source_key})" if answer else "not found"))
        if reason is None:
            store.mark(conn, module, "ok")
        else:
            store.mark(conn, module, "failed", reason)
            failed += 1
        print(f"{module.NAME}: {found} found, {fetcher.requests} requests, {time.monotonic() - started:.1f} s")
    _report_match(conn)
    return 1 if failed else 0


def status(conn) -> int:
    print(f"{'source':14} {'kind':9} {'prio':>4}  {'fetched':10}  {'ttl':24} {'families':>8}  status")
    for module in catalog.SOURCES:
        row = _source_row(conn, module.NAME)
        fetched = _fetched(row)
        count = conn.execute("SELECT COUNT(*) FROM catalog_family WHERE source_id = ?", (row["id"],)).fetchone()[0] if row else 0
        if module.KIND == "bundled":
            ttl = "bundled, every sync"
        elif module.KIND == "lookup":
            answers, fresh = conn.execute("SELECT COUNT(*), COALESCE(SUM(expires_at > ?), 0) FROM lookup_cache WHERE source = ?",
                                          (store.now().isoformat(timespec="seconds"), module.NAME)).fetchone()
            ttl = f"{module.TTL_DAYS} d cache: {fresh}/{answers} fresh"
        elif fetched is None:
            ttl = "never synced"
        else:
            expires = fetched + timedelta(days=module.TTL_DAYS)
            ttl = f"{'fresh until' if expires > store.now() else 'expired'} {expires.date()}"
        state = row["status"] if row else "never"
        if row is not None and (why := store.reason(conn, module.NAME)):
            state += f": {why}"
        print(f"{module.NAME:14} {module.KIND:9} {module.PRIORITY:>4}  {fetched.date().isoformat() if fetched else '-':10}  "
              f"{ttl:24} {count:>8}  {state}")
    print(YOON_DESIGN)
    faces = conn.execute("SELECT COUNT(*) FROM local_font").fetchone()[0]
    matched = conn.execute("SELECT COUNT(DISTINCT local_font_id) FROM match").fetchone()[0]
    print(f"matched {matched} of {faces} installed faces")
    return 0


def main(argv: list[str] | None = None, prog: str = "lazuli catalog") -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n")[0].split(": ", 1)[1])
    sub = ap.add_subparsers(dest="command", required=True)
    p_sync = sub.add_parser("sync", help="refresh snapshot and bundled catalogs whose ttl expired")
    p_sync.add_argument("--source", nargs="+", action="extend", metavar="NAME", help="only these sources")
    p_sync.add_argument("--force", action="store_true", help="sync even when the ttl has not expired")
    p_lookup = sub.add_parser("lookup", help="ask on-request catalogs about installed families no snapshot matched")
    p_lookup.add_argument("--source", metavar="NAME", help="one lookup source (noonnu or sandoll); default: all")
    which = p_lookup.add_mutually_exclusive_group(required=True)
    which.add_argument("--family", metavar="NAME", help="installed families whose name contains NAME")
    which.add_argument("--unmatched", action="store_true", help="every installed family no snapshot matched")
    p_lookup.add_argument("--limit", type=int, metavar="N", help="at most N families per source")
    p_lookup.add_argument("--yes", action="store_true", help=f"no confirmation above {CONFIRM_ABOVE} requests")
    sub.add_parser("status", help="sources, fetch dates, ttl, family counts, and status")
    args = ap.parse_args(argv)
    conn = db.connect(paths.db_path())
    try:
        if args.command == "sync":
            return sync(conn, args.source, force=args.force)
        if args.command == "lookup":
            return lookup(conn, args.source, args.family, limit=args.limit, yes=args.yes)
        return status(conn)
    finally:
        conn.close()
