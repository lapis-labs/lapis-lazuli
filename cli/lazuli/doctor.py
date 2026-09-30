"""`lazuli doctor`: check that this computer can run the LapisLazuli CLI.

Each check prints ok, warn, or fail. The exit code is 1 only when a check fails: something the CLI
cannot work around. Missing optional pieces (no inventory yet, no browser for render and behavior
checks) warn with the command that fixes them.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from lapis_design import __version__
from lazuli import coretext, db, paths, scan


def checks() -> list[tuple[str, str, str]]:
    out = [("ok", "cli", f"lapis-design and lazuli {__version__}, Python {sys.version.split()[0]}")]
    problem = db.check_sqlite()
    out.append(("fail", "sqlite", problem) if problem else
               ("ok", "sqlite", f"SQLite {sqlite3.sqlite_version} with FTS5 trigram"))
    cache = paths.cache_dir()
    try:
        cache.mkdir(parents=True, exist_ok=True)
        writable = os.access(cache, os.W_OK)
    except OSError:
        writable = False
    out.append(("ok", "cache", str(cache)) if writable else ("fail", "cache", f"{cache} is not writable"))
    database = paths.db_path()
    if not database.exists():
        out.append(("warn", "inventory", "no font inventory yet; run `lazuli local fonts`"))
    elif not problem:
        conn = sqlite3.connect(database)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            fonts = conn.execute("SELECT COUNT(*) FROM local_font").fetchone()[0]
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            labeled = conn.execute("SELECT COUNT(*) FROM user_label").fetchone()[0] if "user_label" in tables else None
        finally:
            conn.close()
        if version < db.latest_version():
            out.append(("warn", "inventory", f"database at migration {version}, CLI has {db.latest_version()}; "
                                              "run `lazuli local fonts` to migrate"))
        else:
            out.append(("ok", "inventory", f"{fonts} faces in {database}"))
        if labeled is not None:
            out.append(("ok", "user classes", f"{labeled} {'family' if labeled == 1 else 'families'} classified by you "
                                              "(`lazuli class list`); they outrank catalog classes"))
    try:
        present = [str(root.path) for root in scan.readable_roots()]
    except scan.RootsError as exc:
        out.append(("fail", "font folders", str(exc)))
    else:
        out.append(("ok", "font folders", f"{len(present)} readable: " + ", ".join(present)) if present
                   else ("warn", "font folders", "no font folder found"))
    if adobe := _adobe():
        out.append(adobe)
    out.append(_browser())
    out.append(("warn", "plugins", "plugin and CLI version match is not checked yet"))
    return out


def _adobe() -> tuple[str, str, str] | None:
    """Adobe Fonts faces seen through Core Text (macOS only): a count, or off while LAZULI_FONT_ROOTS is set.
    Nothing about Adobe elsewhere: their files are never read, and only macOS lists them."""
    if not coretext.supported():
        return None
    if os.environ.get("LAZULI_FONT_ROOTS"):
        return ("ok", "adobe fonts", "off while LAZULI_FONT_ROOTS is set")
    try:
        count = len(coretext.provider().identities())
    except Exception as exc:                      # Adobe Fonts are optional, so a failure is a warning
        return ("warn", "adobe fonts", f"Core Text is not usable ({type(exc).__name__})")
    return ("ok", "adobe fonts", f"{count} faces listed by the operating system (read through Core Text, "
                                 "never as files)")


def _browser() -> tuple[str, str, str]:
    """Chromium or the headless shell of the revision this Playwright expects."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            executable = Path(playwright.chromium.executable_path)
    except Exception as exc:                      # the browser is optional for everything but two checks
        return ("warn", "browser", f"Playwright is not usable ({type(exc).__name__})")
    revision_dir = next((p for p in executable.parents if p.name.startswith("chromium-")), None)
    shell = revision_dir.parent / revision_dir.name.replace("chromium-", "chromium_headless_shell-") if revision_dir else None
    if executable.exists() or (shell and shell.is_dir()):
        return ("ok", "browser", "Chromium for render and behavior checks is installed")
    return ("warn", "browser", "run `playwright install chromium-headless-shell` for render and behavior checks")


def main(argv: list[str] | None = None, prog: str = "lazuli doctor") -> int:
    argparse.ArgumentParser(prog=prog, description=__doc__.split("\n")[0]).parse_args(argv)
    results = checks()
    for status, name, detail in results:
        print(f"{status:4}  {name:12}  {detail}")
    return 1 if any(status == "fail" for status, _, _ in results) else 0
