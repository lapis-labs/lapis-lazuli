"""Adobe Fonts are read through the operating system's font list, never through their files.

No test here reads a real Adobe font: `LAZULI_FONT_ROOTS` is set (it turns the Core Text listing off), a fake
font list stands in for Core Text, and the macOS tests register synthetic fonts built in code with the process
alone and narrow the provider to them. The folders Adobe's terms protect are faked under `tmp_path`, holding
decoy font files that would open if any code went there; a trap on the file system, Pillow, and fontTools
records every touch under them, since scan and measure catch ordinary exceptions and would hide an error.
"""
from __future__ import annotations

import builtins
import ctypes
import ctypes.util
import io
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

from lazuli import cli, coretext, db, doctor, local, lock, measure, scan
from fake_adobe import FakeAdobe
from synthetic_fonts import build

macos = pytest.mark.skipif(sys.platform != "darwin", reason="Core Text exists only on macOS")
REAL_PROVIDER = coretext.provider                       # fixtures replace the module attribute; this is the real one


class AdobeTouched(BaseException):
    """Not an Exception: scan and measure would swallow it as an unreadable font."""


def adobe_folder(tmp_path: Path) -> Path:
    return tmp_path / "Library" / "Application Support" / "Adobe"


def livetype(tmp_path: Path) -> Path:
    return adobe_folder(tmp_path) / "CoreSync" / "plugins" / "livetype" / ".r"


_resolving: list[bool] = []


def resolving() -> bool:
    """True while `real_location` runs: `os.path.realpath` calls `os.lstat` and `os.readlink`, which a trap wraps,
    so a trap lets those calls through."""
    return bool(_resolving)


def real_location(target, *, link_itself: bool = False) -> str | None:
    """Where the operating system ends up when it opens `target`: every link on the way followed and `..` taken
    from the folder reached so far (`os.path.realpath`; the name is never cleaned by text first, which would
    drop `link/..`). With `link_itself`, the last name is not followed: an lstat or a readlink looks at the link.
    None for a file descriptor."""
    try:
        name = os.fsdecode(os.fspath(target))
    except TypeError:
        return None
    _resolving.append(True)
    try:
        if link_itself and os.path.basename(name) not in ("", ".", ".."):
            return os.path.join(os.path.realpath(os.path.dirname(name) or "."), os.path.basename(name))
        return os.path.realpath(name)
    finally:
        _resolving.pop()


def under(place: str, roots) -> bool:
    return any(place == root or place.startswith(root + os.sep) for root in roots)


def install_trap(monkeypatch, subtree: Path) -> list[str]:
    """Record, and refuse, every look at `subtree` or below it: stat, lstat, scandir, listdir, open, access,
    readlink, Pillow's and FreeType's own open, and fontTools' (through open). A look is judged by where it ends
    up (a project link into the subtree, `link/..`), not by the name it was given; an lstat or a readlink of a
    link itself is not a look at where the link leads. Returns the record."""
    from PIL import ImageFont

    roots = {os.path.normpath(str(subtree)), real_location(subtree)}
    touched: list[str] = []

    def inside(target, link_itself: bool) -> bool:
        place = real_location(target, link_itself=link_itself)
        if place is None:                                  # a file descriptor
            return False
        return under(place, roots) or under(os.path.normpath(os.fsdecode(os.fspath(target))), roots)

    def guard(owner, attr, position=0):
        real = getattr(owner, attr)

        def wrapper(*args, **kwargs):
            target = args[position] if len(args) > position else next(iter(kwargs.values()), None)
            link_itself = attr in ("lstat", "readlink") or kwargs.get("follow_symlinks", True) is False
            if not resolving() and target is not None and inside(target, link_itself):
                touched.append(f"{attr}({target})")
                raise AdobeTouched(f"{attr}({target})")
            return real(*args, **kwargs)
        monkeypatch.setattr(owner, attr, wrapper)

    for name in ("stat", "lstat", "scandir", "listdir", "open", "access", "readlink"):
        guard(os, name)
    guard(builtins, "open")
    guard(io, "open")
    guard(ImageFont, "truetype")
    guard(ImageFont.FreeTypeFont, "__init__", 1)
    return touched


def test_the_trap_catches_what_it_guards(tmp_path, monkeypatch):
    from fontTools.ttLib import TTFont
    from PIL import ImageFont

    decoy = build(livetype(tmp_path) / ".10312.otf", family="Decoy")
    touched = install_trap(monkeypatch, adobe_folder(tmp_path))
    for look in (lambda: open(decoy, "rb"), decoy.stat, lambda: decoy.parent.is_dir(), lambda: os.listdir(decoy.parent),
                 lambda: os.scandir(decoy.parent), lambda: TTFont(str(decoy)), lambda: ImageFont.truetype(str(decoy), 20)):
        with pytest.raises(AdobeTouched):
            look()
    assert len(touched) == 7
    touched.clear()
    elsewhere = build(tmp_path / "elsewhere" / "Plain.ttf", family="Plain")
    assert elsewhere.stat().st_size and list(elsewhere.parent.iterdir()) and TTFont(str(elsewhere)) and touched == []


def test_the_trap_judges_a_look_by_where_it_ends_up_not_by_the_name_it_was_given(tmp_path, monkeypatch):
    build(livetype(tmp_path) / ".10312.otf", family="Decoy")
    project = tmp_path / "project"
    project.mkdir()
    link = project / "link"
    try:
        link.symlink_to(adobe_folder(tmp_path) / "CoreSync")
    except OSError:
        pytest.skip("this platform cannot create symbolic links here")
    touched = install_trap(monkeypatch, adobe_folder(tmp_path))
    for look in (lambda: os.stat(link), lambda: os.stat(link / "plugins"),
                 lambda: os.stat(project / "link" / ".." / "CoreSync" / "plugins" / "livetype" / ".r" / ".10312.otf"),
                 lambda: os.lstat(link / "plugins"), lambda: os.listdir(link), lambda: os.lstat(link / ".." / "x")):
        with pytest.raises(AdobeTouched):
            look()
    assert len(touched) == 6
    touched.clear()
    assert os.readlink(link) == str(adobe_folder(tmp_path) / "CoreSync") and os.lstat(link) and touched == []


# ---------------------------------------------------------------- Adobe's folders, by name

@pytest.mark.parametrize("path, adobe", [
    ("/Users/me/Library/Application Support/Adobe/CoreSync/plugins/livetype/.r/.10312.otf", True),
    ("/Library/Application Support/Adobe/Fonts/Some.otf", True),
    ("/users/me/library/application support/ADOBE/x", True),
    ("C:/Users/me/AppData/Roaming/Adobe/CoreSync/plugins/livetype/r/x.otf", True),
    ("/home/me/.local/share/Adobe/CoreSync/x.otf", True),
    ("/Users/me/Library/Application Support/Other/Adobe Notes.otf", False),
    ("/Users/me/Library/Fonts/Adobe/Caslon.otf", False),
    ("/Users/me/Library/Application Support/Adobe Fonts/x", False),
    ("/Users/me/Adobe/CoreSyncing/x", False),
    ("/home/me/Adobe/CoreSync/../x.otf", True),                  # the names walked through count, whatever `..` leaves
    ("/Users/me/Library/Application Support/Adobe/../x", True),
    ("/Users/me/Library/Application Support/Other/../Adobe/x", True),
    ("Adobe/CoreSync/x.otf", True),
    ("../Adobe/CoreSync/x.otf", True),
    ("/Users/me/Library/Fonts/../Adobe/x", False),
    ("/Users/me/Adobe/../CoreSync/x", False),
    ("../../CoreSync/Adobe/x", False),
])
def test_adobe_folders_are_recognised_by_name(path, adobe):
    assert coretext.is_adobe_path(path) is adobe


def test_links_into_adobe_folders_are_followed_by_name_and_never_looked_at(tmp_path, monkeypatch):
    real = livetype(tmp_path)
    build(real / ".10312.otf", family="Decoy")
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    try:
        (fonts / "hop").symlink_to(real)
        (fonts / "hop-again").symlink_to(fonts / "hop")
        (fonts / "file").symlink_to(real / ".10312.otf")
    except OSError:
        pytest.skip("this platform cannot create symbolic links here")
    plain = build(fonts / "plain.ttf", family="Plain")
    touched = install_trap(monkeypatch, adobe_folder(tmp_path))
    assert [coretext.reaches_adobe(fonts / name) for name in ("hop", "hop-again", "file")] == [True] * 3
    assert coretext.reaches_adobe(fonts / "hop-again" / ".10312.otf") is True
    assert coretext.reaches_adobe(plain) is False
    with pytest.raises(coretext.AdobeFileRefused):
        coretext.refuse_adobe_file(fonts / "hop-again")
    assert touched == []


def test_a_link_loop_is_no_adobe_path(tmp_path):
    try:
        (tmp_path / "a").symlink_to(tmp_path / "b")
        (tmp_path / "b").symlink_to(tmp_path / "a")
    except OSError:
        pytest.skip("this platform cannot create symbolic links here")
    assert coretext.reaches_adobe(tmp_path / "a") is False


# ---------------------------------------------------------------- the scanner and LAZULI_FONT_ROOTS

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


def test_scan_never_enters_adobe_folders_below_a_root(env, tmp_path, monkeypatch):
    build(livetype(tmp_path) / ".10312.otf", family="Decoy Sans")
    build(livetype(tmp_path).parent / "w" / ".20001.otf", family="Decoy Serif")
    build(tmp_path / "Library" / "Fonts" / "Plain.ttf", family="Plain Sans")
    try:
        (tmp_path / "Library" / "Fonts" / "linked.otf").symlink_to(livetype(tmp_path) / ".10312.otf")
        (tmp_path / "Library" / "Fonts" / "linked-dir").symlink_to(livetype(tmp_path))
    except OSError:
        pass
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={tmp_path / 'Library'}")      # a root that holds Adobe's folder
    touched = install_trap(monkeypatch, adobe_folder(tmp_path))
    conn = connect(tmp_path)
    result = scan.scan(conn)
    measure.measure_pending(conn)
    assert touched == []
    assert [r["family"] for r in conn.execute("SELECT family FROM local_font")] == ["Plain Sans"]
    assert result.unreadable == []


@pytest.mark.parametrize("entry, message", [
    ("adobe-sync={adobe}", "adobe-sync is not a root origin"),
    ("user={adobe}", "inside Adobe's font folders"),
    ("system={adobe}/plugins", "inside Adobe's font folders"),
    ("fonts={plain}", "does not start with system= or user="),
    ("{plain}", "does not start with system= or user="),
])
def test_font_roots_name_neither_adobe_nor_an_unknown_origin(env, tmp_path, monkeypatch, capsys, entry, message):
    monkeypatch.setenv("LAZULI_FONT_ROOTS", entry.format(adobe=livetype(tmp_path), plain=tmp_path / "plain"))
    with pytest.raises(scan.RootsError, match=message):
        scan.roots()
    with pytest.raises(SystemExit) as stop:
        cli.main(["local", "fonts"])
    assert stop.value.code == 2 and message in capsys.readouterr().err
    assert not (tmp_path / "cache" / "lazuli.db").exists()                     # refused before anything is created


@pytest.fixture
def adobe(env, tmp_path, monkeypatch):
    fake = FakeAdobe(tmp_path / "os-fonts")
    monkeypatch.setattr(coretext, "provider", lambda: fake)
    return fake


def measurement(conn, family):
    row = conn.execute("""SELECT m.* FROM measurement m JOIN local_font lf ON lf.id = m.local_font_id
                          WHERE lf.family = ?""", (family,)).fetchone()
    return None if row is None else {"kind": row["family_kind"], "metrics": json.loads(row["metrics_json"]),
                                     "panose": json.loads(row["panose_json"] or "{}")}


def test_scan_adds_the_faces_the_font_list_gives_as_identities_not_paths(adobe, env, tmp_path):
    identity = adobe.add("Sync Sans", names_ko="싱크 산스")
    build(env["user"] / "Plain.ttf", family="Plain Sans")
    conn = connect(tmp_path)
    result = scan.scan(conn)
    assert (result.files, result.adobe, result.added, result.unreadable) == (1, 1, 2, [])
    row = conn.execute("SELECT * FROM local_font WHERE origin = 'adobe-sync'").fetchone()
    assert (row["path"], row["size"], row["mtime"], row["face_index"]) == (identity, 0, "coretext:Version 1.000", 0)
    assert not os.path.exists(row["path"])                                      # an identity, not a path
    assert (row["family"], row["family_norm"], row["postscript_name"], row["subfamily"]) == (
        "Sync Sans", "syncsans", "SyncSans-Regular", "Regular")
    assert row["manufacturer"] == "LapisLazuli tests" and row["vendor_id"] is None
    assert json.loads(row["names_i18n_json"]) == {"ko": "싱크 산스"}
    coverage = json.loads(row["coverage_json"])
    assert coverage["latin"] == 52 and coverage["hangul_syllables"] == 13
    assert conn.execute("SELECT origin FROM local_font WHERE family = 'Plain Sans'").fetchone()[0] == "user"
    assert "in 1 files and 1 Adobe Fonts faces (adobe-sync 1, user 1)" in local.summary(conn, changed=False)


def test_rescans_follow_a_face_by_its_version_and_drop_a_face_the_system_stops_listing(adobe, env, tmp_path):
    first_id = adobe.add("First Sans")
    second_id = adobe.add("Second Sans")
    conn = connect(tmp_path)
    first = scan.scan(conn)
    assert measure.measure_pending(conn) == (2, [])
    again = scan.scan(conn)
    assert (again.added, again.updated, again.removed, again.fingerprint) == (0, 0, 0, first.fingerprint)
    assert conn.execute("SELECT COUNT(*) FROM measurement").fetchone()[0] == 2
    adobe.entries[first_id] = (adobe.entries[first_id][0], "Version 2.000")     # an update: same face, new version
    changed = scan.scan(conn)
    assert (changed.updated, changed.removed) == (1, 0)
    assert conn.execute("SELECT mtime FROM local_font WHERE path = ?", (first_id,)).fetchone()[0] == "coretext:Version 2.000"
    assert measurement(conn, "First Sans") is None and measurement(conn, "Second Sans") is not None
    conn.execute("INSERT INTO source (id, name, kind, priority) VALUES (1, 'google-fonts', 'snapshot', 10)")
    for table, values in (("match", "1, 'k', 'exact_ps', 1"), ("embedding", "'m', '1', 's', 's', 1, x'00', 't'")):
        conn.execute(f"INSERT INTO {table} SELECT id, {values} FROM local_font WHERE path = ?", (second_id,))
    del adobe.entries[second_id]                                                # unsubscribed or deactivated
    gone = scan.scan(conn)
    assert gone.removed == 1
    assert [r["family"] for r in conn.execute("SELECT family FROM local_font")] == ["First Sans"]
    for table in ("measurement", "match", "embedding"):                         # everything went with the face
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert gone.fingerprint != changed.fingerprint


def test_a_failed_listing_keeps_the_faces_already_stored_and_says_so(adobe, env, tmp_path):
    adobe.add("Kept Sans")
    conn = connect(tmp_path)
    scan.scan(conn)
    adobe.broken = True
    result = scan.scan(conn)
    assert result.removed == 0 and result.adobe == 0
    assert [r["family"] for r in conn.execute("SELECT family FROM local_font")] == ["Kept Sans"]
    assert result.unreadable == ["Adobe Fonts: the font list is not readable (OSError)"]


def test_a_scan_that_does_not_ask_the_system_drops_the_adobe_rows(adobe, env, tmp_path, monkeypatch):
    adobe.add("Gone Sans")
    build(env["user"] / "Plain.ttf", family="Plain Sans")
    conn = connect(tmp_path)
    scan.scan(conn)
    monkeypatch.setattr(coretext, "provider", REAL_PROVIDER)                    # LAZULI_FONT_ROOTS is set: no listing
    result = scan.scan(conn)
    assert (result.adobe, result.removed) == (0, 1)
    assert [r["family"] for r in conn.execute("SELECT family FROM local_font")] == ["Plain Sans"]


def test_font_roots_turn_the_core_text_listing_off(env, monkeypatch):
    built = []

    class Recorder:
        def __init__(self):
            built.append(self)

    monkeypatch.setattr(coretext, "supported", lambda: True)                    # as on macOS
    monkeypatch.setattr(coretext, "CoreText", Recorder)
    assert coretext.provider() is None and built == []                          # LAZULI_FONT_ROOTS is set
    monkeypatch.delenv("LAZULI_FONT_ROOTS")
    assert isinstance(coretext.provider(), Recorder) and len(built) == 1
    monkeypatch.setattr(coretext, "supported", lambda: False)                   # Windows, Linux
    assert coretext.provider() is None and len(built) == 1


def test_measure_reaches_adobe_faces_only_through_the_adapter(adobe, env, tmp_path):
    adobe.add("Sync Sans")
    build(env["user"] / "Plain.ttf", family="Plain Sans")
    conn = connect(tmp_path)
    scan.scan(conn)
    assert measure.measure_pending(conn) == (2, [])
    sync, plain = measurement(conn, "Sync Sans"), measurement(conn, "Plain Sans")
    assert sync["metrics"]["method"] == "coretext" and plain["metrics"]["method"] == "file"
    assert "variable" not in sync["metrics"] and "pixel_outline" not in sync["metrics"]
    assert plain["metrics"]["variable"] is False and plain["metrics"]["pixel_outline"] is False
    assert sync["panose"] == plain["panose"]                                    # same outlines, same classes


def test_adobe_faces_wait_unmeasured_while_the_system_list_is_unavailable(adobe, env, tmp_path, monkeypatch):
    adobe.add("Sync Sans")
    conn = connect(tmp_path)
    scan.scan(conn)
    monkeypatch.setattr(coretext, "provider", lambda: None)
    assert measure.measure_pending(conn) == (0, [])                             # no failure, no record
    assert conn.execute("SELECT COUNT(*) FROM measurement").fetchone()[0] == 0
    monkeypatch.setattr(coretext, "provider", lambda: adobe)
    assert measure.measure_pending(conn) == (1, [])


def test_an_adobe_row_is_never_opened_as_a_file(tmp_path):
    decoy = build(tmp_path / "Library" / "Application Support" / "Adobe" / "CoreSync" / "d.otf", family="Decoy")
    with pytest.raises(LookupError):                                   # no font list here, and no file fallback
        measure.measure_face(str(decoy), 0, {"origin": "adobe-sync", "path": str(decoy)}, {})
    with pytest.raises(coretext.AdobeFileRefused):
        measure.Face(str(decoy), 0)
    with pytest.raises(coretext.AdobeFileRefused):
        scan.faces(decoy)
    assert lock.read_file(decoy).error == "cannot read it as a font (AdobeFileRefused)"


def test_scan_and_measure_never_touch_adobe_folders_whatever_the_font_list_says(adobe, env, tmp_path, monkeypatch):
    """The font list names an Adobe face; Adobe's folders (a decoy file in each, links to them, and a root that
    holds them) are never opened, stat'ed, or listed while the inventory is scanned and measured."""
    decoy = build(livetype(tmp_path) / ".10312.otf", family="Decoy Sans")
    build(livetype(tmp_path).parent / "w" / ".20001.otf", family="Decoy Serif")
    identity = adobe.add("Sync Sans")
    build(env["user"] / "Plain.ttf", family="Plain Sans")
    try:
        (env["user"] / "linked.otf").symlink_to(decoy)
        (env["user"] / "linked-dir").symlink_to(livetype(tmp_path))
    except OSError:
        pass
    monkeypatch.setenv("LAZULI_FONT_ROOTS", os.pathsep.join([f"user={env['user']}", f"system={tmp_path / 'Library'}"]))
    monkeypatch.setattr(doctor, "_browser", lambda: ("ok", "browser", "not started"))
    touched = install_trap(monkeypatch, adobe_folder(tmp_path))
    conn = connect(tmp_path)
    result = scan.scan(conn)
    assert measure.measure_pending(conn) == (2, [])
    doctor.checks()
    local.inventory_changed(conn)
    assert touched == []
    assert result.unreadable == []
    rows = {r["family"]: r["origin"] for r in conn.execute("SELECT family, origin FROM local_font")}
    assert rows == {"Plain Sans": "user", "Sync Sans": "adobe-sync"}
    assert conn.execute("SELECT path FROM local_font WHERE family = 'Sync Sans'").fetchone()[0] == identity


def test_the_session_fingerprint_follows_the_adobe_faces_without_measuring_them(adobe, env, tmp_path):
    adobe.add("Sync Sans")
    conn = connect(tmp_path)
    scan.scan(conn)
    assert local.inventory_changed(conn) is False
    adobe.add("Second Sans")
    assert local.inventory_changed(conn) is True
    scan.scan(conn)
    assert local.inventory_changed(conn) is False


def test_local_fonts_reports_the_adobe_faces_it_listed(adobe, env, tmp_path, capsys):
    adobe.add("Sync Sans")
    build(env["user"] / "Plain.ttf", family="Plain Sans")
    assert cli.main(["local", "fonts", "--json"]) == 0
    captured = capsys.readouterr()
    families = {f["family"]: f for f in json.loads(captured.out)}
    assert families["Sync Sans"]["origins"] == ["adobe-sync"]
    assert "scanned 1 files and 1 Adobe Fonts faces: 2 new" in captured.err


def test_local_fonts_origin_keeps_only_the_faces_that_came_from_it(adobe, env, tmp_path, capsys):
    adobe.add("Sync Sans")
    adobe.add("Sync Serif")
    build(env["user"] / "Plain.ttf", family="Plain Sans")
    build(env["user"] / "SyncBold.ttf", family="Sync Sans", style="Bold")          # same family, another origin
    build(env["system"] / "Gothic.ttf", family="Plain Gothic")

    def listed(origin):
        assert cli.main(["local", "fonts", "--json", "--origin", origin]) == 0
        out = capsys.readouterr().out
        return {f["family"]: f for f in json.loads(out)}, out

    synced, out = listed("adobe-sync")
    assert set(synced) == {"Sync Sans", "Sync Serif"}
    assert synced["Sync Sans"]["origins"] == ["adobe-sync"]
    assert [face["postscript_name"] for face in synced["Sync Sans"]["faces"]] == ["SyncSans-Regular"]
    assert "coretext:" not in out and str(tmp_path / "os-fonts") not in out            # no identity, no file path
    mine, _ = listed("user")
    assert set(mine) == {"Plain Sans", "Sync Sans"} and mine["Sync Sans"]["origins"] == ["user"]
    assert [face["subfamily"] for face in mine["Sync Sans"]["faces"]] == ["Bold"]
    assert set(listed("system")[0]) == {"Plain Gothic"}


def test_local_fonts_origin_narrows_the_table_and_composes_with_family(adobe, env, tmp_path, capsys):
    adobe.add("Sync Sans")
    build(env["user"] / "Plain.ttf", family="Plain Sans")
    assert cli.main(["local", "fonts", "--origin", "adobe-sync", "--family", "sans"]) == 0
    table = capsys.readouterr().out
    assert "Sync Sans  [adobe-sync]" in table and "Plain Sans" not in table
    assert cli.main(["local", "fonts", "--json", "--origin", "user", "--family", "sync"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_local_fonts_origin_is_refused_for_the_summary_and_for_an_unknown_origin(env, tmp_path, capsys):
    for argv, message in ((["--summary", "--origin", "user"], "--origin does not apply to --summary"),
                          (["--origin", "adobe"], "invalid choice: 'adobe'")):
        with pytest.raises(SystemExit) as stop:
            cli.main(["local", "fonts", *argv])
        assert stop.value.code == 2 and message in capsys.readouterr().err
    assert not (tmp_path / "cache" / "lazuli.db").exists()                             # refused before any scan


def test_doctor_counts_adobe_faces_on_macos_only_and_never_lists_their_folders(adobe, env, tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_browser", lambda: ("ok", "browser", "not started"))
    adobe.add("Sync Sans")
    adobe.add("Second Sans")
    monkeypatch.setattr(coretext, "supported", lambda: True)
    monkeypatch.delenv("LAZULI_FONT_ROOTS")
    monkeypatch.setattr(scan, "roots", lambda: [scan.Root("user", env["user"]),
                                               scan.Root("user", livetype(tmp_path))])   # a link into Adobe's folder
    checks = {name: (status, detail) for status, name, detail in doctor.checks()}
    assert checks["adobe fonts"][0] == "ok" and checks["adobe fonts"][1].startswith("2 faces listed by the operating system")
    assert str(livetype(tmp_path)) not in checks["font folders"][1] and str(env["user"]) in checks["font folders"][1]
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={env['user']}")
    assert {name: detail for _, name, detail in doctor.checks()}["adobe fonts"] == "off while LAZULI_FONT_ROOTS is set"
    monkeypatch.setattr(coretext, "supported", lambda: False)                          # Windows, Linux
    assert "adobe fonts" not in {name for _, name, _ in doctor.checks()}


def test_doctor_warns_when_core_text_cannot_be_asked(env, monkeypatch):
    monkeypatch.setattr(doctor, "_browser", lambda: ("ok", "browser", "not started"))
    monkeypatch.setattr(coretext, "supported", lambda: True)
    monkeypatch.delenv("LAZULI_FONT_ROOTS")

    def unusable():
        raise OSError("no framework")
    monkeypatch.setattr(coretext, "provider", unusable)
    checks = {name: (status, detail) for status, name, detail in doctor.checks()}
    assert checks["adobe fonts"] == ("warn", "Core Text is not usable (OSError)")


@pytest.mark.parametrize("name", ["CTFontCreatePathForGlyph", "CTFontCopyTable", "CTFontCopyAvailableTables",
                                  "CGFontCopyTableForTag", "CTFontCopyGraphicsFont", "CTFontManagerCreateFontDescriptorsFromURL",
                                  # the bitmap the drawing goes into must not come out as an image or a file
                                  "CGBitmapContextCreateImage", "CGImageDestinationCreateWithURL",
                                  "CGImageDestinationAddImage", "CGImageDestinationFinalize",
                                  "CGDataProviderCreateWithURL", "CGDataProviderCopyData"])
def test_outline_table_and_file_calls_cannot_be_bound(name):
    with pytest.raises(PermissionError, match="not one of the Core Text calls"):
        coretext.require_allowed(name)
    assert name not in coretext.ALLOWED_CALLS


@pytest.mark.parametrize("trait, weight", [(-0.8, 100), (-0.4, 300), (0.0, 400), (0.1, 400), (0.15, 500), (0.23, 500),
                                           (0.31, 600), (0.4, 700), (0.62, 900), (1.0, 900), (None, None)])
def test_a_weight_trait_maps_to_the_nearest_weight_class(trait, weight):
    assert coretext.weight_class(trait) == weight


@pytest.mark.parametrize("tag, key", [("ko", "ko"), ("ko-KR", "ko"), ("ja_JP", "ja"), ("zh-Hans-CN", "zh-Hans"),
                                      ("zh-Hant-TW", "zh-Hant"), ("zh-TW", "zh-Hant"), ("zh", "zh-Hans"),
                                      ("en", None), ("kok", None), ("zhx", None), (None, None)])
def test_a_localized_name_is_kept_only_for_the_languages_the_database_holds(tag, key):
    assert coretext.language_key(tag) == key


# ---------------------------------------------------------------- migration 0004

def _database_at_version_3(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    for number in (1, 2, 3):
        conn.executescript(next(p for n, p in db.migrations() if n == number).read_text(encoding="utf-8"))
    return conn


def test_migration_0004_deletes_adobe_rows_with_their_data_and_keeps_the_rest(tmp_path):
    path = tmp_path / "v3.db"
    conn = _database_at_version_3(path)
    conn.execute("INSERT INTO source (id, name, kind, priority) VALUES (1, 'google-fonts', 'snapshot', 10)")
    conn.execute("INSERT INTO catalog_family (source_id, source_key, family, family_norm) VALUES (1, 'k', 'F', 'f')")
    for font_path, family, origin in (("/Adobe/.r/.1.otf", "One", "adobe-sync"), ("/Adobe/.w/.2.otf", "Two", "adobe-sync"),
                                      ("/System/A.otf", "Three", "system"), ("/Users/x/B.otf", "Four", "user")):
        conn.execute("INSERT INTO local_font (path, size, mtime, family, family_norm, origin) VALUES (?, 1, 'm', ?, ?, ?)",
                     (font_path, family, family.lower(), origin))
    for font_id in range(1, 5):
        conn.execute("INSERT INTO measurement (local_font_id, measurer_version, measured_at) VALUES (?, '0.3.1', 't')", (font_id,))
        conn.execute("INSERT INTO match VALUES (?, 1, 'k', 'exact_ps', 1)", (font_id,))
        conn.execute("INSERT INTO embedding VALUES (?, 'm', '1', 's', 's', 1, x'00', 't')", (font_id,))
    conn.execute("INSERT INTO color_record (system, code, source_class, use, l, c, recorded_at) "
                 "VALUES ('ral-classic', 'RAL 3020', 'provider', 'spec', .5, .2, 't')")
    conn.execute("INSERT INTO user_label (family_norm, family, genre, recorded_at) VALUES ('a.otf', 'A', 'sans', 't')")
    conn.execute("INSERT INTO meta VALUES ('inventory_fingerprint', 'old')")
    conn.execute("INSERT INTO meta VALUES ('last_sync.google-fonts', 'kept')")
    conn.commit()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    conn.close()

    conn = db.connect(path)
    try:
        assert [r["origin"] for r in conn.execute("SELECT origin FROM local_font ORDER BY id")] == ["system", "user"]
        for table in ("measurement", "match", "embedding"):
            assert [r[0] for r in conn.execute(f"SELECT local_font_id FROM {table} ORDER BY 1")] == [3, 4], table
        assert conn.execute("SELECT COUNT(*) FROM color_record").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM user_label").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM catalog_family").fetchone()[0] == 1
        assert {r["key"] for r in conn.execute("SELECT key FROM meta")} == {"last_sync.google-fonts"}
    finally:
        conn.close()


# ---------------------------------------------------------------- macOS: the real Core Text

def register_for_process(paths: list[Path], request) -> None:
    """Register synthetic fonts with Core Text for this process only, and unregister them afterwards."""
    cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
    ct = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreText"))
    vp = ctypes.c_void_p
    cf.CFURLCreateFromFileSystemRepresentation.argtypes = [vp, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
    cf.CFURLCreateFromFileSystemRepresentation.restype = vp
    for name in ("CTFontManagerRegisterFontsForURL", "CTFontManagerUnregisterFontsForURL"):
        getattr(ct, name).argtypes = [vp, ctypes.c_uint32, vp]
        getattr(ct, name).restype = ctypes.c_bool
    for path in paths:
        raw = os.fsencode(path)
        url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)
        assert ct.CTFontManagerRegisterFontsForURL(url, 1, None), f"Core Text refused {path.name}"   # scope: process
        request.addfinalizer(lambda url=url: ct.CTFontManagerUnregisterFontsForURL(url, 1, None))


def scoped_to(folder: Path):
    """Which Core Text URLs count as Adobe's for a test: only faces under `folder`, so no real Adobe face is read.
    Compared by name only (macOS spells one folder as /var/... and /private/var/...), so the folder is not touched."""
    def canonical(path: str) -> str:
        return path[len("/private"):] if path.startswith("/private/") else path
    prefix = canonical(str(folder))
    return lambda url: canonical(url).startswith(prefix)


# Synthetic faces: stems 30 to 250 (thin to heavy), serif, contrast, monospace, bu-ri, reverse contrast.
# 30 to 250 units at 512 px is 15 to 128 pixels, and the weights sit inside their classes, not on an edge.
PARITY = {
    "Light": dict(stem=30), "Thin": dict(stem=60), "Plain": dict(stem=100), "Heavy": dict(stem=250),
    "Serif": dict(stem=100, serif=True), "Contrast": dict(stem=100, serif=True, contrast=True),
    "Mono": dict(mono=True), "Nub": dict(bu=True, serif=True), "Reverse": dict(reverse=True),
    "Loose": dict(spread=True, latin=False), "Icons": dict(latin=False, hangul=False),
}
CONTRAST_ORDER = ["none", "very-low", "low", "medium-low", "medium", "medium-high", "high", "very-high"]
# Tolerances. Pillow's FreeType autohints the instruction-less synthetic fonts, which rounds stems and heights to
# whole pixels; Core Text does not. One pixel of a stroke of 15 to 40 pixels is up to 1/15 (stem ratios: weight,
# CJK contrast, CJK weight). Bounds and advances come in font units from both, so they agree to rounding.
# ConRat is the 5th percentile of 64 or 65 ray samples: one ray more or less on the hairline of the sharpest test
# ring moves it by about 0.1 (measured 0.263 with FreeType, 0.353 with Core Text; the ring's own value is 0.246),
# which is one class step there and nowhere else.
STEM_REL, BOUNDS_REL, CON_ABS, SPREAD_ABS = 0.08, 0.005, 0.11, 0.002


def parity_pair(tmp_path, request, **faces):
    """{name: (file measurement, Core Text measurement, file row, Core Text row)} for synthetic faces registered
    with Core Text, measured both ways from the same font file."""
    tag = uuid.uuid4().hex[:8]
    paths = {name: build(tmp_path / "fonts" / f"{name}{tag}.ttf", family=f"Parity {name} {tag}",
                         extra_letters="\u00c1\U00020000\U0001E900", **kwargs) for name, kwargs in faces.items()}
    register_for_process(list(paths.values()), request)
    provider = coretext.CoreText(is_adobe=scoped_to(tmp_path / "fonts"))
    listed = {face.identity: face for face in provider.faces()}
    vocab = measure._vocab()
    out = {}
    for name, path in paths.items():
        family = f"Parity {name} {tag}"
        file_row = {**scan.describe(scan.faces(path)[0][1]), "origin": "user", "path": str(path), "face_index": 0}
        identity = f"coretext:{family.replace(' ', '')}-Regular"
        ct_row = {**scan.describe_adobe(listed[identity]), "origin": "adobe-sync", "path": identity, "face_index": 0}
        out[name] = (measure.measure_face(str(path), 0, file_row, vocab),
                     measure.measure_face(identity, 0, ct_row, vocab, provider=provider), file_row, ct_row)
    return out


def loaded(values):
    return {key: json.loads(values[key]) if values[key] and key != "family_kind" else values[key]
            for key in ("family_kind", "panose_json", "cjk_json", "metrics_json")}


# What reads stroke shapes is not measured on a face with only straight contours (a pixel face); Core Text
# faces never learn that, so those keys are compared only where the file method measured them.
PIXEL_UNMEASURED = ("con_rat", "bu_ratio", "bu_class", "cjk_contrast", "contrast_class", "reverse_contrast")


@macos
def test_core_text_measurements_match_the_file_method_on_the_same_faces(tmp_path, request):
    for name, (file_values, ct_values, file_row, ct_row) in parity_pair(tmp_path, request, **PARITY).items():
        f, c = loaded(file_values), loaded(ct_values)
        # inventory fields: identical except the OS/2 vendor, which Core Text faces never have
        for key in ("postscript_name", "family", "family_norm", "subfamily", "manufacturer", "designer", "coverage_json"):
            assert ct_row[key] == file_row[key], (name, key)
        assert file_row["vendor_id"] == "LLTS" and ct_row["vendor_id"] is None
        assert json.loads(ct_row["names_i18n_json"] or "{}").items() <= json.loads(file_row["names_i18n_json"] or "{}").items()
        assert f["family_kind"] == c["family_kind"], name
        fm, cm = f["metrics_json"], c["metrics_json"]
        assert (fm["method"], cm["method"]) == ("file", "coretext")
        assert cm["upm"] == fm["upm"] and cm["letter_count"] == fm["letter_count"]
        assert cm["weight_class"] == fm["weight_class"] and cm["italic"] == fm["italic"]
        assert cm["unicode_version"] == fm["unicode_version"]
        assert {"variable", "width_class"} <= set(fm) - set(cm) and "pixel_outline" not in cm, name    # no table is read
        pixel = fm.get("pixel_outline") is True
        fp, cp = f["panose_json"] or {}, c["panose_json"] or {}
        fc, cc = f["cjk_json"] or {}, c["cjk_json"] or {}
        # classes: weight, proportion, x-height, serif, monospace, contrast, and the CJK classes
        for digit in ("weight", "proportion", "x_height"):
            assert cp.get(digit) == fp.get(digit), (name, digit)
        assert cm.get("serif") == fm.get("serif") and cm.get("monospaced") == fm.get("monospaced"), name
        if not pixel:
            slack = 1 if name == "Contrast" else 0                   # the sharpest ring, see the tolerances
            assert ("contrast" in cp) == ("contrast" in fp), name
            if "contrast" in fp:
                assert abs(CONTRAST_ORDER.index(cp["contrast"]) - CONTRAST_ORDER.index(fp["contrast"])) <= slack, name
        for key in ("script", "bu_class", "contrast_class", "reverse_contrast", "name_hints"):
            if not (pixel and key in PIXEL_UNMEASURED):
                assert cc.get(key) == fc.get(key), (name, key)
        # numbers
        for key in ("o_rat", "prop_rat", "x_rat"):
            assert cm.get(key) == pytest.approx(fm.get(key), rel=BOUNDS_REL), (name, key)
        assert cm.get("weight_rat") == pytest.approx(fm.get("weight_rat"), rel=STEM_REL), name
        if "con_rat" in fm:
            assert cm["con_rat"] == pytest.approx(fm["con_rat"], abs=CON_ABS), name
        assert cc.get("square_spread") == pytest.approx(fc.get("square_spread"), abs=SPREAD_ABS), name
        for key in ("bu_ratio", "cjk_contrast", "weight_ratio_cjk_latin"):
            if not (pixel and key in PIXEL_UNMEASURED):
                assert cc.get(key) == pytest.approx(fc.get(key), rel=STEM_REL), (name, key)


@macos
def test_a_pixel_face_is_not_marked_pixel_through_core_text(tmp_path, request):
    file_values, ct_values, *_ = parity_pair(tmp_path, request, Pixel=dict(square_pixel=True))["Pixel"]
    f, c = loaded(file_values), loaded(ct_values)
    assert f["metrics_json"]["pixel_outline"] is True and "bu_ratio" not in f["cjk_json"]
    assert "pixel_outline" not in c["metrics_json"]                       # contours are never read via Core Text,
    assert {"bu_ratio", "cjk_contrast"} <= set(c["cjk_json"])              # so stroke shapes are measured on it


@macos
def test_the_real_provider_classifies_by_url_name_and_never_opens_the_files(tmp_path, monkeypatch, request):
    """Synthetic fonts registered from a folder named like Adobe's are listed as adobe-sync by the URL Core Text
    gives, and scan and measure touch nothing there (Core Text itself reads them, outside this process's Python)."""
    family = f"Fake Adobe {uuid.uuid4().hex[:8]}"
    font = build(livetype(tmp_path) / ".10312.otf", family=family, extra_letters="\u00c1")
    register_for_process([font], request)
    in_tmp = scoped_to(tmp_path)                                         # real Adobe faces stay unread
    scoped = coretext.CoreText(is_adobe=lambda url: coretext.is_adobe_path(url) and in_tmp(url))
    monkeypatch.setattr(coretext, "provider", lambda: scoped)
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={tmp_path / 'user'}")
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "cache" / "lazuli.db"))
    (tmp_path / "user").mkdir()
    touched = install_trap(monkeypatch, adobe_folder(tmp_path))
    conn = connect(tmp_path)
    result = scan.scan(conn)
    assert measure.measure_pending(conn) == (1, [])
    assert touched == [] and result.unreadable == []
    row = conn.execute("SELECT * FROM local_font").fetchone()
    assert (row["origin"], row["path"], row["family"], row["size"]) == (
        "adobe-sync", f"coretext:{family.replace(' ', '')}-Regular", family, 0)
    assert row["mtime"].startswith("coretext:") and row["vendor_id"] is None and result.adobe == 1
    assert measurement(conn, family)["metrics"]["method"] == "coretext"
    assert measurement(conn, family)["panose"]["weight"] == "medium"
