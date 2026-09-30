"""The lazuli database: open it in the user cache and bring it to the newest migration.

Migrations are `migrations/NNNN_*.sql`; each ends by setting `PRAGMA user_version` to its number. A migration
runs in one transaction, one statement at a time: every statement ends with a semicolon at the end of its own
line, nothing in it needs to run outside a transaction (`VACUUM`, a journal-mode change), and nothing in it
begins, ends, or nests a transaction of its own (`BEGIN`, `COMMIT`, `END`, `ROLLBACK`, `SAVEPOINT`, `RELEASE`).
Everything in the database can be rebuilt by re-scanning fonts and re-syncing catalogs, except what the
user recorded: `color_record` (`lazuli color record`) and `user_label` (`lazuli class`).
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
MIN_SQLITE = (3, 34, 0)                       # FTS5 trigram tokenizer
WAL_WAIT = 5.0                                # seconds to keep retrying the switch to WAL on a new database
WAL_RETRY = 0.05                              # pause between tries, and the busy wait of each try
TRANSACTION_ACTIONS = (sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT)      # authorizer codes 22 and 32
SQL_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


def migrations() -> list[tuple[int, Path]]:
    found = []
    for path in MIGRATIONS.glob("*.sql"):
        if match := re.match(r"(\d{4})_", path.name):
            found.append((int(match.group(1)), path))
    return sorted(found)


def latest_version() -> int:
    return migrations()[-1][0]


def check_sqlite() -> str | None:
    """None when this SQLite can run lazuli, otherwise the reason it cannot."""
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        return f"SQLite {sqlite3.sqlite_version} is older than {'.'.join(map(str, MIN_SQLITE))}"
    try:
        probe = sqlite3.connect(":memory:")
        probe.execute("CREATE VIRTUAL TABLE t USING fts5(a, tokenize = 'trigram')")
        probe.close()
    except sqlite3.OperationalError as exc:
        return f"SQLite {sqlite3.sqlite_version} lacks the FTS5 trigram tokenizer ({exc})"
    return None


def enable_wal(conn: sqlite3.Connection) -> None:
    """Switch a new database to WAL, retrying for WAL_WAIT seconds. SQLite fails at once with "database is
    locked" when another connection holds the write lock (a migration's BEGIN IMMEDIATE), without calling the
    busy handler, so wait and retry. When another connection holds a read or exclusive lock it does call the
    busy handler, which waits Python's 5 seconds by default on every try; the busy wait is cut to the retry
    pause while retrying, so a late try cannot run past the deadline by seconds, and restored afterward."""
    busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    conn.execute(f"PRAGMA busy_timeout = {round(WAL_RETRY * 1000)}")
    deadline = time.monotonic() + WAL_WAIT
    try:
        while True:
            try:
                conn.execute("PRAGMA journal_mode = WAL")
                return
            except sqlite3.OperationalError as exc:
                if "database is locked" not in str(exc) or time.monotonic() >= deadline:
                    raise
                time.sleep(WAL_RETRY)
    finally:
        conn.execute(f"PRAGMA busy_timeout = {busy_timeout}")


def deny_transaction_statements(action: int, *_: object) -> int:
    return sqlite3.SQLITE_DENY if action in TRANSACTION_ACTIONS else sqlite3.SQLITE_OK


def run_migration(conn: sqlite3.Connection, number: int, migration: Path) -> None:
    """Run one migration inside the caller's transaction; raise, leaving the caller to roll back, unless every
    statement ran and the file set `user_version` to `number`. SQLite refuses every transaction and savepoint
    statement while the migration runs: a `COMMIT` in it would save half the migration before the checks below
    can stop it. The refusal also covers the connection's own commit and rollback, so it is lifted before this
    returns or raises."""
    conn.set_authorizer(deny_transaction_statements)
    try:
        statement = ""
        for line in migration.read_text(encoding="utf-8").splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                try:
                    conn.execute(statement)
                except sqlite3.DatabaseError as exc:
                    if exc.sqlite_errorcode != sqlite3.SQLITE_AUTH:
                        raise
                    raise RuntimeError(f"{migration.name} holds a transaction or savepoint statement, but it "
                                       f"already runs in one transaction: {statement.strip()[:60]!r}") from exc
                statement = ""
        if SQL_COMMENT.sub("", statement).strip():
            raise RuntimeError(f"{migration.name} ends with a statement that has no semicolon at the end of its "
                               f"line: {statement.strip()[:60]!r}")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != number:
            raise RuntimeError(f"{migration.name} leaves user_version at {version}, not {number}")
    finally:
        conn.set_authorizer(None)


def connect(path: Path) -> sqlite3.Connection:
    if problem := check_sqlite():
        raise RuntimeError(problem)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_database = not path.exists()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        if new_database:
            enable_wal(conn)
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for number, migration in migrations():
            if number <= current:
                continue
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            try:
                current = conn.execute("PRAGMA user_version").fetchone()[0]
                if current < number:
                    run_migration(conn, number, migration)
                    conn.commit()
                    current = number
                else:
                    conn.rollback()
            except Exception:
                conn.rollback()
                raise
    except Exception:
        conn.close()
        raise
    return conn
