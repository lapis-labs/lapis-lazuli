"""lazuli local fonts: the database, the read-only scanner, measurement, summary, and doctor."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from lapis_design import cli as lapis_cli
from lazuli import cli, db, measure, scan
from synthetic_fonts import build, collection


@pytest.fixture
def env(tmp_path, monkeypatch):
    roots = {"system": tmp_path / "system", "user": tmp_path / "user"}
    for path in roots.values():
        path.mkdir(parents=True)
    monkeypatch.setenv("LAZULI_FONT_ROOTS", os.pathsep.join(f"{origin}={path}" for origin, path in roots.items()))
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "cache" / "lazuli.db"))
    return roots


def connect(tmp_path):
    return db.connect(tmp_path / "cache" / "lazuli.db")


def measured(conn, family):
    row = conn.execute("""SELECT m.* FROM measurement m JOIN local_font lf ON lf.id = m.local_font_id
                          WHERE lf.family = ?""", (family,)).fetchone()
    return {"kind": row["family_kind"], "panose": json.loads(row["panose_json"] or "{}"),
            "cjk": json.loads(row["cjk_json"] or "{}"), "metrics": json.loads(row["metrics_json"])}


def test_migrations_create_the_schema_once(tmp_path):
    path = tmp_path / "lazuli.db"
    conn = db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.latest_version()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
    conn = db.connect(path)                                             # reopening applies nothing twice
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} >= {
        "local_font", "measurement", "embedding", "catalog_family", "meta"}

def test_failed_migration_rolls_back_every_table_and_version(tmp_path):
    path = tmp_path / "lazuli.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    with pytest.raises(sqlite3.OperationalError, match="meta already exists"):
        db.connect(path)

    with sqlite3.connect(path) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )}
        assert tables == {"meta"}
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0


def test_upgrade_preserves_existing_delete_journal_mode(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript((db.MIGRATIONS / "0001_init.sql").read_text(encoding="utf-8"))
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    conn = db.connect(path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.latest_version()
    finally:
        conn.close()


def open_together(path, count):
    """Failures (stderr text) of `count` processes that open the database at `path` at the same moment."""
    script = ("import sys\n"
              "from pathlib import Path\n"
              "from lazuli import db\n"
              "sys.stdin.buffer.read(1)\n"
              "with db.connect(Path(sys.argv[1])) as conn:\n"
              "    assert conn.execute('PRAGMA user_version').fetchone()[0] == db.latest_version()\n")
    children = [subprocess.Popen([sys.executable, "-c", script, str(path)], stdin=subprocess.PIPE,
                                 stderr=subprocess.PIPE, stdout=subprocess.PIPE) for _ in range(count)]
    failures = []
    try:
        for child in children:
            child.stdin.write(b"x")
            child.stdin.close()
        for child in children:
            child.wait(timeout=20)
            if child.returncode:
                failures.append(child.stderr.read().decode())
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()
    return failures


def test_concurrent_upgrade_of_existing_database(tmp_path):
    failures = []
    for attempt in range(8):
        path = tmp_path / f"old-{attempt}.db"
        with sqlite3.connect(path) as conn:
            conn.executescript((db.MIGRATIONS / "0001_init.sql").read_text(encoding="utf-8"))
        failures += open_together(path, 3)
        with sqlite3.connect(path) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == db.latest_version()
    assert failures == []


# An intermittent regression test: without the WAL wait, 3 of 150 runs under load failed (seen at 1ab612b).
def test_concurrent_creation_of_new_database(tmp_path):
    failures = []
    for attempt in range(8):
        path = tmp_path / f"new-{attempt}.db"
        failures += open_together(path, 4)
        with sqlite3.connect(path) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == db.latest_version()
    assert failures == []


def connect_as_new(monkeypatch, path):
    """`db.connect(path)` on an existing file that it takes for a new database, so it switches the file to WAL."""
    with monkeypatch.context() as patch:
        real_exists = Path.exists
        patch.setattr(Path, "exists", lambda self: False if self == path else real_exists(self))
        return db.connect(path)


def test_new_database_waits_for_another_connection_holding_the_write_lock(tmp_path, monkeypatch):
    path = tmp_path / "lazuli.db"
    holder = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    holder.execute("CREATE TABLE held (a)")
    holder.execute("BEGIN IMMEDIATE")                               # SQLite refuses the switch to WAL at once
    release = threading.Timer(0.3, holder.execute, ("ROLLBACK",))
    release.start()
    try:
        conn = connect_as_new(monkeypatch, path)
    finally:
        release.join()
        holder.close()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.latest_version()
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000        # the retries' short wait is undone
    finally:
        conn.close()


def hold_read_lock(path):
    """A connection in a rollback-journal database with a read transaction open: SQLite calls the busy handler
    of anyone who then asks for WAL, and the handler waits Python's default 5 seconds."""
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("CREATE TABLE held (a)")
    holder.execute("BEGIN")
    holder.execute("SELECT * FROM held").fetchall()
    return holder


def test_new_database_gives_up_soon_when_another_connection_never_lets_go(tmp_path, monkeypatch):
    path = tmp_path / "lazuli.db"
    holder = hold_read_lock(path)
    monkeypatch.setattr(db, "WAL_WAIT", 0.5)                        # the bound is the wait plus a second, whatever the wait
    started = time.monotonic()
    try:
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            connect_as_new(monkeypatch, path)
        elapsed = time.monotonic() - started
    finally:
        holder.close()
    assert elapsed < db.WAL_WAIT + 1


def test_enable_wal_restores_the_busy_wait_when_it_gives_up(tmp_path, monkeypatch):
    path = tmp_path / "lazuli.db"
    holder = hold_read_lock(path)
    monkeypatch.setattr(db, "WAL_WAIT", 0.2)
    conn = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            db.enable_wal(conn)
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conn.close()
        holder.close()


def migration_folder(tmp_path, monkeypatch, **files):
    folder = tmp_path / "migrations"
    folder.mkdir()
    for name, text in files.items():
        (folder / f"{name}.sql").write_text(text, encoding="utf-8")
    monkeypatch.setattr(db, "MIGRATIONS", folder)


FIRST_MIGRATION = "CREATE TABLE first_table (a);\nPRAGMA user_version = 1;\n"


@pytest.mark.parametrize("second", [
    "CREATE TABLE second_table (b);\nPRAGMA user_version = 2",             # the last statement has no semicolon
    "CREATE TABLE second_table (b);\n",                                    # the version is never set
    "CREATE TABLE second_table (b);\nPRAGMA user_version = 5;\n",          # the version is another number
], ids=["no-final-semicolon", "version-unset", "version-other"])
def test_migration_that_does_not_end_at_its_number_rolls_back_and_stops(tmp_path, monkeypatch, second):
    migration_folder(tmp_path, monkeypatch, **{"0001_first": FIRST_MIGRATION, "0002_second": second})
    path = tmp_path / "lazuli.db"
    for _ in range(2):                                                  # the second open must not hit "already exists"
        with pytest.raises(RuntimeError, match="0002_second.sql"):
            db.connect(path)
        with sqlite3.connect(path) as conn:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
            assert tables == {"first_table"}
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


@pytest.mark.parametrize("statement", [
    "COMMIT;", "END;", "ROLLBACK;", "BEGIN;", "SAVEPOINT inner;", "RELEASE inner;",
], ids=["commit", "end", "rollback", "begin", "savepoint", "release"])
def test_migration_with_a_transaction_statement_stops_and_leaves_no_half_migration(tmp_path, monkeypatch, statement):
    second = f"CREATE TABLE second_table (b);\n{statement}\nPRAGMA user_version = 2;\n"
    migration_folder(tmp_path, monkeypatch, **{"0001_first": FIRST_MIGRATION, "0002_second": second})
    path = tmp_path / "lazuli.db"
    for _ in range(2):                                                  # the second open must not hit "already exists"
        with pytest.raises(RuntimeError, match="0002_second.sql holds a transaction or savepoint statement"):
            db.connect(path)
        with sqlite3.connect(path) as conn:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
            assert tables == {"first_table"}
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_migration_may_mention_transaction_words_in_comments_and_values(tmp_path, monkeypatch):
    migration_folder(tmp_path, monkeypatch, **{
        "0001_first": "-- COMMIT; and BEGIN; are only words here\nCREATE TABLE first_table (a);\n"
                      "INSERT INTO first_table VALUES ('COMMIT;');\nPRAGMA user_version = 1;\n"})
    conn = db.connect(tmp_path / "lazuli.db")
    try:
        assert conn.execute("SELECT a FROM first_table").fetchone()[0] == "COMMIT;"
        conn.execute("INSERT INTO first_table VALUES ('later')")        # the refusal is lifted for the caller's own use
        conn.commit()
    finally:
        conn.close()



def test_migration_may_end_with_comments_after_its_last_statement(tmp_path, monkeypatch):
    migration_folder(tmp_path, monkeypatch, **{
        "0001_first": FIRST_MIGRATION + "\n-- the last note\n/* and a block\n   comment */\n"})
    conn = db.connect(tmp_path / "lazuli.db")
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        conn.close()


def test_scan_reads_faces_names_and_coverage_without_touching_files(env, tmp_path):
    sans = build(env["user"] / "TestSans-Regular.ttf", names_ko="테스트 산스")
    a = build(tmp_path / "parts" / "a.ttf", family="Pair One")
    b = build(tmp_path / "parts" / "b.ttf", family="Pair Two")
    collection(env["system"] / "Pair.ttc", [a, b])
    (env["user"] / "notes.ttf").write_text("not a font")                # a font extension is not enough
    (env["user"] / ".hidden-font").write_bytes(build(tmp_path / "parts" / "c.ttf", family="No Extension").read_bytes())
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file() and "cache" not in p.parts}
    conn = connect(tmp_path)
    result = scan.scan(conn)
    assert (result.files, result.added, result.unreadable) == (3, 3, [])            # the TTC is one file
    assert conn.execute("SELECT COUNT(*) FROM local_font").fetchone()[0] == 4      # with two faces
    rows = {(r["family"], r["face_index"]): r for r in conn.execute("SELECT * FROM local_font")}
    assert {key[0] for key in rows} == {"Test Sans", "Pair One", "Pair Two", "No Extension"}
    assert rows[("Pair Two", 1)]["origin"] == "system"                  # both faces of the collection
    test_sans = rows[("Test Sans", 0)]
    assert json.loads(test_sans["names_i18n_json"]) == {"ko": "테스트 산스"}
    assert test_sans["family_norm"] == "testsans" and test_sans["vendor_id"] == "LLTS"
    coverage = json.loads(test_sans["coverage_json"])
    assert coverage["latin"] == 52 and coverage["hangul_syllables"] == 13
    after = {p: p.stat().st_mtime_ns for p in before}
    assert before == after                                              # read-only


def test_rescans_skip_unchanged_files_and_follow_changes(env, tmp_path):
    font = build(env["user"] / "A.ttf", family="Alpha")
    build(env["user"] / "B.ttf", family="Beta")
    conn = connect(tmp_path)
    first = scan.scan(conn)
    measure.measure_pending(conn)
    assert (scan.scan(conn).added, scan.scan(conn).updated) == (0, 0)
    build(font, family="Alpha", stem=160)                               # same path, new content
    os.utime(font, (font.stat().st_atime, font.stat().st_mtime + 10))
    (env["user"] / "B.ttf").unlink()
    second = scan.scan(conn)
    assert (second.updated, second.removed) == (1, 1)
    assert second.fingerprint != first.fingerprint
    assert conn.execute("SELECT COUNT(*) FROM measurement").fetchone()[0] == 0      # both measurements gone
    assert measure.measure_pending(conn) == (1, [])
    assert measured(conn, "Alpha")["panose"]["weight"] == "bold"                     # 700 / 160 = 4.4


def _ring_con_rat(outer, inner):
    """ConRat as defined: 5th / 95th percentile of the radial thickness of the O every 5 degrees."""
    import numpy as np

    def radius(axes, angle):
        a, b = axes
        return 1 / np.sqrt((np.cos(angle) / a) ** 2 + (np.sin(angle) / b) ** 2)
    angles = np.deg2rad(np.arange(0, 360, 5))
    thickness = radius(outer, angles) - radius(inner, angles)
    return float(np.percentile(thickness, 5) / np.percentile(thickness, 95))


def test_latin_measurement_recovers_known_geometry(env, tmp_path):
    build(env["user"] / "Sans.ttf", family="Plain Sans", stem=100)
    build(env["user"] / "Serif.ttf", family="Contrast Serif", stem=100, serif=True, contrast=True)
    build(env["user"] / "Mono.ttf", family="Even Mono", mono=True)
    build(env["user"] / "Black.ttf", family="Heavy Sans", stem=250)
    conn = connect(tmp_path)
    scan.scan(conn)
    assert measure.measure_pending(conn) == (4, [])
    sans = measured(conn, "Plain Sans")
    assert sans["kind"] == "text"
    assert sans["metrics"]["weight_rat"] == pytest.approx(7.0, abs=0.25)             # CapH 700 / stem 100
    assert sans["panose"]["weight"] == "medium"
    assert sans["panose"]["contrast"] == "none" and sans["metrics"]["serif"] is False
    assert sans["metrics"]["x_rat"] == pytest.approx(500 / 700, abs=0.01)
    assert sans["metrics"]["x_height_size"] == "large"
    serif = measured(conn, "Contrast Serif")
    assert serif["metrics"]["serif"] is True
    expected = _ring_con_rat(outer=(300, 350), inner=(100, 310))                    # sides 200, top 40: 0.246
    assert serif["metrics"]["con_rat"] == pytest.approx(expected, abs=0.02)
    assert serif["panose"]["contrast"] == "medium"                                   # 0.20 <= ConRat < 0.30
    assert measured(conn, "Even Mono")["panose"]["proportion"] == "monospaced"
    assert measured(conn, "Heavy Sans")["panose"]["weight"] == "heavy"               # 700 / 250 = 2.8


def test_cjk_measurement_separates_bu_ri_contrast_and_square_frames(env, tmp_path):
    build(env["user"] / "Myeongjo.ttf", family="Nub Myeongjo", bu=True)
    build(env["user"] / "Gothic.ttf", family="Plain Gothic")
    build(env["user"] / "Reverse.ttf", family="Reverse Gothic", reverse=True)
    build(env["user"] / "Loose.ttf", family="Loose Hand", spread=True, latin=False)
    conn = connect(tmp_path)
    scan.scan(conn)
    measure.measure_pending(conn)
    nub = measured(conn, "Nub Myeongjo")["cjk"]
    assert nub["bu_ratio"] == pytest.approx(130 / 80, abs=0.1) and nub["bu_class"] == "bu"
    plain = measured(conn, "Plain Gothic")["cjk"]
    assert plain["bu_ratio"] == pytest.approx(1.0, abs=0.05) and plain["bu_class"] == "min_bu"
    assert plain["cjk_contrast"] == pytest.approx(0.5, abs=0.05) and plain["reverse_contrast"] is False
    assert plain["square_spread"] == 0
    assert plain["weight_ratio_cjk_latin"] == pytest.approx((700 / 80) / 7.0, abs=0.3)
    assert measured(conn, "Reverse Gothic")["cjk"]["reverse_contrast"] is True
    loose = measured(conn, "Loose Hand")
    assert loose["cjk"]["square_spread"] > 0.1 and loose["panose"] == {}             # no Latin to measure


def test_failures_are_recorded_once_and_symbols_are_kinded(env, tmp_path, monkeypatch):
    build(env["user"] / "Icons.ttf", family="Only Icons", latin=False, hangul=False)
    build(env["user"] / "Broken.ttf", family="Breaks")
    conn = connect(tmp_path)
    scan.scan(conn)
    real = measure.measure_face

    def flaky(path, index, row, vocab):
        if row["family"] == "Breaks":
            raise OSError("cannot rasterize")
        return real(path, index, row, vocab)
    monkeypatch.setattr(measure, "measure_face", flaky)
    count, failures = measure.measure_pending(conn)
    assert count == 1 and failures == ["Broken.ttf#0: OSError"]
    assert measured(conn, "Only Icons")["kind"] == "symbol"
    assert measured(conn, "Breaks")["metrics"] == {"unmeasurable": "OSError"}
    assert measure.measure_pending(conn) == (0, [])                                  # not retried


def test_local_fonts_command_summary_and_session_hook(env, tmp_path, capsys):
    assert lapis_cli.main(["hook", "session-start"]) == 0
    assert "no font inventory yet" in capsys.readouterr().out
    assert not (tmp_path / "cache" / "lazuli.db").exists()                          # the hook never scans
    build(env["user"] / "Myeongjo.ttf", family="Nub Myeongjo", bu=True, serif=True)
    build(env["system"] / "Gothic.ttf", family="Plain Gothic")
    assert cli.main(["local", "fonts", "--json"]) == 0
    families = {f["family"]: f for f in json.loads(capsys.readouterr().out)}
    assert families["Nub Myeongjo"]["classes"][:1] == ["bu-ri"] and families["Nub Myeongjo"]["origins"] == ["user"]
    assert lapis_cli.main(["hook", "session-start"]) == 0
    text = capsys.readouterr().out
    assert "2 font families in 2 files" in text and "Hangul" not in text              # 13 syllables is no Hangul set
    assert "changed since the last scan" not in text
    build(env["user"] / "New.ttf", family="Newcomer")
    assert lapis_cli.main(["hook", "session-start"]) == 0
    assert "changed since the last scan" in capsys.readouterr().out


def test_doctor_reports_and_fails_only_on_blockers(env, tmp_path, capsys, monkeypatch):
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "warn  inventory" in out and "ok    sqlite" in out
    monkeypatch.setattr(db, "check_sqlite", lambda: "SQLite 3.30.0 is older than 3.34.0")
    assert cli.main(["doctor"]) == 1
    assert "fail  sqlite" in capsys.readouterr().out


def test_old_sqlite_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 31, 1))
    monkeypatch.setattr(sqlite3, "sqlite_version", "3.31.1")
    with pytest.raises(RuntimeError, match="older than 3.34.0"):
        db.connect(tmp_path / "lazuli.db")
