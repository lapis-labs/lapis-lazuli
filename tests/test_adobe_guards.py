"""Adobe Fonts guards: data derived from them stays out of calibration, nothing of Adobe's is reached through a
project link, the Core Text binding list stays closed, and every test starts with no installed fonts."""
from __future__ import annotations

import ast
import builtins
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "calibration"))
import calibrate
from fake_adobe import FakeAdobe
from lazuli import cli, coretext, db, local, lock, measure, scan
from synthetic_fonts import build
from test_coretext import AdobeTouched, adobe_folder, install_trap, livetype, real_location, resolving, under


# ---------------------------------------------------------------- calibration leaves Adobe Fonts out

def calibration_db(tmp_path: Path):
    """A new database in a temporary folder: two files, one family in both a file and an Adobe Fonts face, and an
    Adobe Fonts face that the catalog labels serif while it is measured sans (it would show in the report)."""
    conn = db.connect(tmp_path / "calibration.db")
    conn.execute("INSERT INTO source (id, name, kind, priority) VALUES (1, 'google-fonts', 'snapshot', 10)")
    faces = [(1, "Plain Serif", "user", "serif", True), (2, "Plain Sans", "system", "sans", False),
             (3, "Zzyzx Synced", "adobe-sync", "serif", False), (4, "Shared Family", "user", "serif", True),
             (5, "Shared Family", "adobe-sync", "serif", False)]
    for font_id, family, origin, genre, serif in faces:
        key = family.replace(" ", "")
        conn.execute("INSERT OR IGNORE INTO catalog_family (source_id, source_key, family, family_norm) "
                     "VALUES (1, ?, ?, ?)", (key, family, key.lower()))
        conn.execute("INSERT OR IGNORE INTO catalog_label (source_id, source_key, kind, raw, mapped) "
                     "VALUES (1, ?, 'genre', ?, ?)", (key, genre.title(), genre))
        conn.execute("""INSERT INTO local_font (id, path, size, mtime, face_index, postscript_name, family, family_norm,
                          subfamily, coverage_json, origin, metadata_json)
                        VALUES (?, ?, 1, 'm', 0, ?, ?, ?, 'Regular', '{"latin": 60}', ?, '{"axes": []}')""",
                     (font_id, f"coretext:{key}" if origin == "adobe-sync" else f"/fonts/{font_id}.ttf",
                      f"{key}-Regular", family, key.lower(), origin))
        conn.execute("INSERT INTO match VALUES (?, 1, ?, 'exact_family', 1.0)", (font_id, key))
        conn.execute("INSERT INTO measurement VALUES (?, ?, 'text', '{}', NULL, ?, '2026-10-01')",
                     (font_id, measure.MEASURER_VERSION, json.dumps({"serif": serif, "monospaced": False})))
    conn.commit()
    return conn


def test_calibration_counts_no_adobe_fonts_face(tmp_path):
    conn = calibration_db(tmp_path)
    labels, hangul_labels = calibrate.exact_labels(conn)
    assert set(labels) == set(hangul_labels) == {"Plain Serif", "Plain Sans", "Shared Family"}
    google = next(row for row in calibrate.source_rows(conn) if row["name"] == "google-fonts")
    assert (google["exact"], google["fuzzy_only"]) == (3, 0)                     # not 5 faces, not 4 families
    shared = next(f for f in local._families(conn, exclude_origin="adobe-sync") if f["family"] == "Shared Family")
    assert (shared["origins"], len(shared["faces"])) == (["user"], 1)
    assert "Zzyzx Synced" not in {f["family"] for f in local._families(conn, exclude_origin="adobe-sync")}
    assert local._families(conn, origin="user", exclude_origin="user") == []
    text = calibrate.report(conn)
    assert "Zzyzx" not in text
    assert "3 installed families with a name, 3 faces, 3 measured" in text


# ---------------------------------------------------------------- a design metadata that is not stored yet is unknown

@pytest.fixture
def adobe(tmp_path, monkeypatch):
    fake = FakeAdobe(tmp_path / "os-fonts")
    monkeypatch.setattr(coretext, "provider", lambda: fake)
    return fake


@pytest.mark.parametrize("stored", [None, "", "{}", "null", "[]", "not json"])
def test_an_adobe_row_whose_metadata_is_not_stored_waits_instead_of_being_measured(adobe, tmp_path, stored):
    adobe.add("Sync Sans")
    conn = db.connect(tmp_path / "cache" / "lazuli.db")
    scan.scan(conn)
    kept = conn.execute("SELECT metadata_json FROM local_font").fetchone()[0]
    assert json.loads(kept)["axes"] == []                                       # a scan always stores the axes
    conn.execute("UPDATE local_font SET metadata_json = ?", (stored,))
    conn.execute("DELETE FROM measurement")
    conn.commit()
    assert measure.measure_pending(conn) == (0, [])                              # its optical size is not known
    assert conn.execute("SELECT COUNT(*) FROM measurement").fetchone()[0] == 0   # and nothing says "unmeasurable"
    conn.execute("UPDATE local_font SET metadata_json = ?", (kept,))
    conn.commit()
    assert measure.measure_pending(conn) == (1, [])                              # decided once the scan stored it


@pytest.mark.parametrize("stored", ["", "{}", "null", "[]", "not json"])
def test_an_ordinary_scan_stores_the_design_metadata_a_row_lacks(adobe, tmp_path, stored):
    adobe.add("Sync Sans")
    conn = db.connect(tmp_path / "cache" / "lazuli.db")
    scan.scan(conn)
    kept = conn.execute("SELECT metadata_json FROM local_font").fetchone()[0]
    conn.execute("UPDATE local_font SET metadata_json = ?", (stored,))
    conn.execute("DELETE FROM measurement")
    conn.commit()
    assert scan.scan(conn).updated == 1                                          # stale: no --rescan needed
    assert conn.execute("SELECT metadata_json FROM local_font").fetchone()[0] == kept
    assert measure.measure_pending(conn) == (1, [])                              # and measured now, not waiting forever
    assert scan.scan(conn).updated == 0                                          # a row with `axes` is not stale


@pytest.mark.parametrize("stored", ["null", "[]", "not json"])
def test_a_measured_adobe_row_whose_metadata_is_no_object_does_not_stop_the_measuring(adobe, tmp_path, stored):
    adobe.add("Sync Sans")
    conn = db.connect(tmp_path / "cache" / "lazuli.db")
    scan.scan(conn)
    assert measure.measure_pending(conn) == (1, [])
    conn.execute("UPDATE local_font SET metadata_json = ?", (stored,))
    conn.commit()
    assert measure.measure_pending(conn) == (0, [])                              # no AttributeError, no new measurement


@pytest.mark.parametrize("stored", [None, "", "{}", "null", "[]", "not json"])
def test_the_family_listing_reads_a_row_without_design_metadata_as_having_none(adobe, tmp_path, stored):
    """None, '' and '{}' only pin what the listing already does; the others made it fail."""
    adobe.add("Sync Sans")
    conn = db.connect(tmp_path / "cache" / "lazuli.db")
    scan.scan(conn)
    conn.execute("UPDATE local_font SET metadata_json = ?", (stored,))
    conn.commit()
    (family,) = local._families(conn)
    (face,) = family["faces"]
    assert (family["languages"], family["vertical"], face["class_name"]) == ([], [], None)
    assert "axes" not in face


# ---------------------------------------------------------------- the helper takes a language tag, nothing else

@pytest.mark.parametrize("language", ["ko) (en", "ko\n", "", "KO", "zh-hans", "zh-Hans-CN", "-AppleLanguages", "ko -x",
                                      "k", "ko-Hang)"])
def test_a_helper_language_that_is_not_a_tag_starts_no_process(language, monkeypatch):
    monkeypatch.delenv("LAZULI_FONT_ROOTS", raising=False)                      # else no process would start anyway
    started = []

    def trap(*args, **kwargs):
        started.append(args)
        raise AssertionError("a helper process was started")

    monkeypatch.setattr(subprocess, "run", trap)
    with pytest.raises(ValueError, match="not a language tag"):
        coretext.run_names_helper(language, ["Menlo-Regular"])
    assert started == []


def test_the_languages_lazuli_asks_for_are_language_tags():
    assert all(coretext.LANGUAGE_TAG.fullmatch(language) for language in coretext.NAMES_LANGUAGES)
    assert coretext.run_names_helper("zh-Hans", ["Menlo-Regular"]) == {}         # LAZULI_FONT_ROOTS is set: no process


# ---------------------------------------------------------------- the Core Text binding list stays closed

def binding_findings(source: str, allowed: frozenset[str]) -> tuple[list[str], set[str]]:
    """(what breaks the closed list, the names bound) in the source of `lazuli.coretext`: every name given to
    `bind` must be a literal (or a loop over literals) inside `allowed`, and no function of a framework handle
    (`.ct`, `.cf`, `.cg`) may be called except through `bind`."""
    tree = ast.parse(source)
    loops: dict[str, list] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name) and isinstance(node.iter, (ast.Tuple, ast.List)):
            loops.setdefault(node.target.id, []).extend(e.value for e in node.iter.elts if isinstance(e, ast.Constant))
    findings: list[str] = []
    bound: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        func = node.func
        if func.attr == "bind" and len(node.args) >= 2:
            name = node.args[1]
            names = ([name.value] if isinstance(name, ast.Constant)
                     else loops.get(name.id) if isinstance(name, ast.Name) else None)
            if not names:
                findings.append(f"line {node.lineno}: bind() is given a name that is not a literal")
            for symbol in names or ():
                bound.add(symbol)
                if symbol not in allowed:
                    findings.append(f"line {node.lineno}: bind({symbol!r}) is not an allowed call")
        elif isinstance(func.value, ast.Attribute) and func.value.attr in ("cf", "ct", "cg"):
            findings.append(f"line {node.lineno}: {func.value.attr}.{func.attr}() is called directly, not through bind()")
    return findings, bound


def test_the_checker_finds_a_binding_outside_the_list_and_a_direct_call():
    source = '''
class Library:
    def __init__(self):
        self.a = self.bind(self.ct, "CTFontCopyTable", [])
        self.ok = self.bind(self.cf, "CFRelease", [])
        for setting in ("CGContextSetShouldAntialias", "CGBitmapContextCreateImage"):
            setattr(self, setting, self.bind(self.cg, setting, []))
        self.ct.CTFontCreatePathForGlyph(1)
        self.cf.CFURLCreateWithFileSystemPath()
        self.bind(self.cf, some_variable, [])
'''
    findings, bound = binding_findings(source, frozenset({"CFRelease", "CGContextSetShouldAntialias"}))
    assert sorted(f.split(": ", 1)[1] for f in findings) == sorted([
        "bind('CTFontCopyTable') is not an allowed call",
        "bind('CGBitmapContextCreateImage') is not an allowed call",
        "ct.CTFontCreatePathForGlyph() is called directly, not through bind()",
        "cf.CFURLCreateWithFileSystemPath() is called directly, not through bind()",
        "bind() is given a name that is not a literal"])
    assert bound == {"CTFontCopyTable", "CFRelease", "CGContextSetShouldAntialias", "CGBitmapContextCreateImage"}


def test_the_module_binds_exactly_the_allowed_calls_and_calls_nothing_else_of_a_framework():
    findings, bound = binding_findings(Path(coretext.__file__).read_text(encoding="utf-8"), coretext.ALLOWED_CALLS)
    assert findings == []
    assert bound == coretext.ALLOWED_CALLS                                       # the list is the whole list


@pytest.mark.parametrize("prefix", ["CGBitmapContextCreateImage", "CGImageDestination", "CGDataProvider",
                                    "CTFontCreatePath", "CTFontCopyTable", "CGFontCopyTable"])
def test_no_allowed_call_turns_the_bitmap_or_a_font_into_an_image_a_file_or_a_table(prefix):
    assert [name for name in coretext.ALLOWED_CALLS if name.startswith(prefix)] == []


# ---------------------------------------------------------------- lock reaches nothing of Adobe's through the project

def guard_links(monkeypatch, links: list[Path], touched: list[str]) -> None:
    """Record, and refuse, going into a link in the project that leads into Adobe's folders: a stat that follows it,
    a listing, an open, an access. A look is judged by where it ends up, so reaching the link's target through
    `link/..` is the same look as going in by the link's name. A name's own lstat and readlink are the look by
    name that is allowed."""
    roots = {os.path.normpath(str(link)) for link in links} | {real_location(link) for link in links}

    def inside(target) -> bool:
        place = real_location(target)
        if place is None:                                  # a file descriptor
            return False
        return under(place, roots) or under(os.path.normpath(os.fsdecode(os.fspath(target))), roots)

    def guard(owner, attr):
        real = getattr(owner, attr)

        def wrapper(*args, **kwargs):
            if not resolving() and args and kwargs.get("follow_symlinks", True) and inside(args[0]):
                touched.append(f"{attr}({args[0]})")
                raise AdobeTouched(f"{attr}({args[0]})")
            return real(*args, **kwargs)
        monkeypatch.setattr(owner, attr, wrapper)

    for owner, attr in ((os, "stat"), (os, "scandir"), (os, "listdir"), (os, "access"), (builtins, "open"), (io, "open")):
        guard(owner, attr)


def project_with_links(tmp_path: Path) -> tuple[Path, list[Path]]:
    """A project holding one font of its own and links to Adobe's folder (and to a decoy file in it), by name
    and one level down; returns it and the links."""
    decoy = build(livetype(tmp_path) / ".10312.otf", family="Decoy Sans")
    project = tmp_path / "project"
    build(project / "public" / "fonts" / "Own.ttf", family="Own Sans")
    (project / "sub").mkdir()
    links = [project / "fonts", project / "sub" / "deep", project / "file.otf"]
    links[0].symlink_to(livetype(tmp_path))
    links[1].symlink_to(livetype(tmp_path))
    links[2].symlink_to(decoy)
    return project, links


@pytest.mark.parametrize("pattern, expected", [
    ("public/fonts/*.ttf", ["public/fonts/Own.ttf"]),
    ("*/*/*.ttf", ["public/fonts/Own.ttf"]),                  # fonts/* and sub/deep/* are links into Adobe's folder
    ("**/*.ttf", ["public/fonts/Own.ttf"]),
    ("fonts/*.otf", []), ("fonts/.10312.otf", []), ("*/.10312.otf", []), ("sub/*/*.otf", []),
    ("**/*.otf", []), ("file.otf", []), ("*.otf", [])])
def test_lock_globs_never_enter_a_link_that_leads_into_adobe_folders(tmp_path, monkeypatch, pattern, expected):
    project, links = project_with_links(tmp_path)
    touched = install_trap(monkeypatch, adobe_folder(tmp_path))
    guard_links(monkeypatch, links, touched)
    found, empty = lock.resolve_files(project, [pattern])
    assert touched == []
    assert [str(path.relative_to(project)) for path in found] == expected
    assert empty == ([] if expected else [pattern])


def test_lock_globs_find_what_pathlib_finds_in_a_tree_without_links(tmp_path):
    for name in ("a.ttf", "b.ttf", "c.woff2", "x/y/z.ttf", "x/w.woff2", "x/y/.hidden.ttf", "x/y/Z.TTF", "p/q.txt"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0")
    for pattern in ("*.ttf", "?.ttf", "[ab].ttf", "**/*.ttf", "x/**/*.ttf", "x/*/*.ttf", "**/*.woff2", "x/w.woff2",
                    "*/*.woff2", "**/*", "missing/*.ttf", "x/**/z.ttf"):
        found, empty = lock.resolve_files(tmp_path, [pattern])
        expected = sorted(p for p in tmp_path.glob(pattern) if p.is_file())
        assert found == expected, pattern
        assert empty == ([] if expected else [pattern]), pattern


@pytest.mark.parametrize("flags, note", [
    (["--files", "fonts/*.otf", "sub/*/*.otf", "--modified", "none"], "no local file matches 'fonts/*.otf' in"),
    (["--notice", "fonts/.10312.otf"],
     "notice 'fonts/.10312.otf' is inside Adobe's font folders, which lazuli never opens"),
    (["--notice", "fonts/../.r/.10312.otf"],
     "notice 'fonts/../.r/.10312.otf' is inside Adobe's font folders, which lazuli never opens")])
def test_lock_reads_no_file_in_adobe_folders_through_a_project_link_and_says_so(tmp_path, monkeypatch, capsys, flags, note):
    user = tmp_path / "fonts-user"
    build(user / "TestSans-Regular.ttf", family="Test Sans")
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={user}")
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "cache" / "lazuli.db"))
    assert cli.main(["local", "fonts", "--no-measure"]) == 0
    capsys.readouterr()
    project, links = project_with_links(tmp_path)
    touched = install_trap(monkeypatch, adobe_folder(tmp_path))
    guard_links(monkeypatch, links, touched)
    code = lock.main(["Test Sans", "--role", "body", "--task", "demo", *flags, "--project", str(project),
                      "--dry-run", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and touched == []
    assert any(note in line for line in out["notes"])
    assert not (project / ".lapis").exists()


@pytest.mark.parametrize("leads_to, spelled", [
    ("Library/Application Support/Adobe/CoreSync", "link/../CoreSync/plugins/livetype/.r/.10312.otf"),
    ("Library/Application Support/Other/deep", "link/../../Adobe/Fonts/Some.otf")])
def test_a_dotdot_after_a_link_is_taken_from_where_the_link_leads(tmp_path, monkeypatch, leads_to, spelled):
    """`link/..` is the folder above where `link` leads, which the text cannot show: the first link leads into
    Adobe's folders itself, the second one beside them, and only the `..` after it gets in (cleaned by text, its
    path would read `<tmp>/Adobe/Fonts/Some.otf`, which names no folder of Adobe's)."""
    build(livetype(tmp_path) / ".10312.otf", family="Decoy Sans")
    build(adobe_folder(tmp_path) / "Fonts" / "Some.otf", family="Other Decoy")
    target = tmp_path / leads_to
    target.mkdir(parents=True, exist_ok=True)
    project = tmp_path / "project"
    project.mkdir()
    try:
        (project / "link").symlink_to(target)
    except OSError:
        pytest.skip("this platform cannot create symbolic links here")
    via = project / spelled                                   # pathlib keeps the `..`
    assert via.is_file()                                      # the operating system opens a decoy by this name
    touched = install_trap(monkeypatch, adobe_folder(tmp_path))
    assert coretext.reaches_adobe(via) is True
    with pytest.raises(coretext.AdobeFileRefused):
        coretext.refuse_adobe_file(via)
    assert lock.read_file(via).postscript == []               # refused, not read
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={via.parent}")
    with pytest.raises(scan.RootsError, match="inside Adobe's font folders"):
        scan.roots()
    assert touched == []


# ---------------------------------------------------------------- every test starts with no installed fonts

def test_every_test_starts_with_one_empty_font_folder_and_no_adobe_listing(tmp_path):
    origin, _, folder = os.environ["LAZULI_FONT_ROOTS"].partition("=")
    assert origin == "user" and Path(folder).is_dir() and list(Path(folder).iterdir()) == []
    assert coretext.provider() is None                                          # the real one, on any platform
    result = scan.scan(db.connect(tmp_path / "lazuli.db"))
    assert (result.files, result.adobe) == (0, 0)
