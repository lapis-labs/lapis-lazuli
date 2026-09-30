"""Design metadata from synthetic fonts only; no installed or Adobe font data is used here."""
from __future__ import annotations

import json
import sys
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.ttLib import TTFont

from lazuli import cli, coretext, db, scan
from fake_adobe import FakeAdobe
from synthetic_fonts import build
from test_coretext import register_for_process, scoped_to

macos = pytest.mark.skipif(sys.platform != "darwin", reason="Core Text metadata APIs exist only on macOS")
FRENCH = "àâæçéèêëîïôœùûüÿÀÂÆÇÉÈÊËÎÏÔŒÙÛÜŸ"
AXES = [{"tag": "wght", "min": 100.0, "default": 400.0, "max": 900.0},
        {"tag": "wdth", "min": 75.0, "default": 100.0, "max": 125.0}]
FEATURES = """
languagesystem DFLT dflt;
feature vert { sub H by S; } vert;
feature vrt2 { sub E by S; } vrt2;
feature vkna { sub O by S; } vkna;
feature smcp { sub x by S; } smcp;
feature liga { sub H E by S; } liga;
feature kern { pos H E -20; } kern;
feature vhal { pos H -50; } vhal;
"""


def rich_font(path: Path, *, family="Metadata Test", variable=True, features=FEATURES, extra_letters=FRENCH):
    build(path, family=family, hangul=False, extra_letters=extra_letters)
    with TTFont(path) as font:
        if features:
            addOpenTypeFeaturesFromString(font, features)
        if variable:
            FontBuilder(font=font).setupFvar([("wght", 100, 400, 900, "Weight"), ("wdth", 75, 100, 125, "Width")], [])
        font["OS/2"].sxHeight = 500
        font["OS/2"].sCapHeight = 700
        font["OS/2"].sFamilyClass = 0x0803
        # Deliberately claim every range: language support must come from cmap, not these declarations.
        for field in ("ulUnicodeRange1", "ulUnicodeRange2", "ulUnicodeRange3", "ulUnicodeRange4",
                      "ulCodePageRange1", "ulCodePageRange2"):
            setattr(font["OS/2"], field, 0xFFFFFFFF)
        for name_id, value in ((5, "Version 2.003"), (8, "Synthetic Maker"), (9, "Synthetic Designer")):
            font["name"].setName(value, name_id, 3, 1, 0x409)
        font.save(path)
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "fonts"
    root.mkdir()
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={root}")
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "cache.db"))
    return root


def test_file_metadata_is_stored_and_available_without_measurements(env, tmp_path, capsys):
    rich_font(env / "design.ttf")
    assert cli.main(["local", "fonts", "--json", "--no-measure"]) == 0
    family = json.loads(capsys.readouterr().out)[0]
    face = family["faces"][0]
    assert face["axes"] == AXES
    assert face["features"] == ["kern", "liga", "smcp", "vert", "vhal", "vkna", "vrt2"]
    assert face["vertical"] == ["vert", "vhal", "vkna", "vrt2"] == family["vertical"]
    assert face["languages"] == ["en", "fr"] == family["languages"]
    assert (face["version"], face["manufacturer"], face["designer"]) == (
        "Version 2.003", "Synthetic Maker", "Synthetic Designer")
    assert (face["x_height"], face["cap_height"], face["units_per_em"]) == (500, 700, 1000)
    assert (face["family_class"], face["class_id"], face["class_name"], face["class_source"]) == (
        0x0803, 8, "sans-serif", "os2")
    assert face["features_source"] == "opentype"
    assert face["os2_ranges"] == {"unicode": [0xFFFFFFFF] * 4, "codepage": [0xFFFFFFFF] * 2}
    with db.connect(tmp_path / "cache.db") as conn:
        row = conn.execute("SELECT * FROM local_font").fetchone()
        stored = json.loads(row["metadata_json"])
        assert {key: face[key] for key in stored} == stored
        assert row["designer"] == "Synthetic Designer" and row["manufacturer"] == "Synthetic Maker"
        assert conn.execute("SELECT COUNT(*) FROM measurement").fetchone()[0] == 0


def test_static_face_and_missing_metrics_are_distinct_from_variable_metadata(env, capsys):
    path = build(env / "plain.ttf", hangul=False)
    with TTFont(path) as font:
        font["OS/2"].version = 0
        font.save(path)
    assert cli.main(["local", "fonts", "--json", "--no-measure"]) == 0
    face = json.loads(capsys.readouterr().out)[0]["faces"][0]
    assert face["axes"] == [] and face["features"] == [] and face["vertical"] == []
    assert face["languages"] == ["en"] and face["family_class"] == 0 and face["class_name"] == "unclassified"
    assert face["version"] is None and face["designer"] is None
    assert face["x_height"] is None and face["cap_height"] is None and face["units_per_em"] == 1000


def test_languages_require_all_letters_and_do_not_use_declared_os2_ranges(env, capsys):
    rich_font(env / "full.ttf", family="Full French")
    path = rich_font(env / "partial.ttf", family="Partial French")
    with TTFont(path) as font:
        for table in font["cmap"].tables:
            if table.isUnicode():
                table.cmap.pop(ord("œ"), None)
        font.save(path)
    assert cli.main(["local", "fonts", "--json", "--no-measure"]) == 0
    families = {family["family"]: family for family in json.loads(capsys.readouterr().out)}
    assert families["Full French"]["languages"] == ["en", "fr"]
    assert families["Partial French"]["languages"] == ["en"]


def _korean_syllables():
    return "".join(bytes((lead, trail)).decode("euc_kr") for lead in range(0xB0, 0xC9)
                   for trail in range(0xA1, 0xFF))


def test_korean_support_needs_the_required_syllables_not_just_their_count(env, capsys):
    syllables = _korean_syllables()
    build(env / "complete.ttf", family="Complete Korean", hangul=False, extra_letters=syllables)
    missing = syllables[1:]
    # Replace one required syllable with a modern Hangul syllable outside KS X 1001: count stays 2,350.
    replacement = next(chr(cp) for cp in range(0xAC00, 0xD7A4) if chr(cp) not in syllables)
    build(env / "incomplete.ttf", family="Incomplete Korean", hangul=False, extra_letters=missing + replacement)
    assert cli.main(["local", "fonts", "--json", "--no-measure"]) == 0
    families = {family["family"]: family for family in json.loads(capsys.readouterr().out)}
    assert families["Complete Korean"]["languages"] == ["en", "ko"]
    assert families["Incomplete Korean"]["languages"] == ["en"]



def test_migration_0005_refreshes_both_origins_without_discarding_user_or_measurement_data(env, tmp_path, monkeypatch):
    path = rich_font(env / "file.ttf", family="File Metadata")
    fake = FakeAdobe(tmp_path / "synthetic-os-fonts")
    identity = fake.add("OS Metadata")
    monkeypatch.setattr(coretext, "provider", lambda: fake)
    database = tmp_path / "v4.db"
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    for number, migration in db.migrations():
        if number <= 4:
            conn.executescript(migration.read_text(encoding="utf-8"))
    mtime = datetime.fromtimestamp(int(path.stat().st_mtime), timezone.utc).isoformat()
    for key, size, token, origin in ((str(path), path.stat().st_size, mtime, "user"),
                                     (identity, 0, "coretext:Version 1.000", "adobe-sync")):
        conn.execute("INSERT INTO local_font (path, size, mtime, origin) VALUES (?, ?, ?, ?)", (key, size, token, origin))
    for font_id in (1, 2):
        conn.execute("INSERT INTO measurement (local_font_id, measurer_version, metrics_json, measured_at) "
                     "VALUES (?, 'old', '{\"saved\": true}', 't')", (font_id,))
        conn.execute("INSERT INTO embedding VALUES (?, 'm', '1', 's', 's', 1, x'00', 't')", (font_id,))
    conn.execute("INSERT INTO user_label (family_norm, family, genre, recorded_at) VALUES ('mine', 'Mine', 'sans', 't')")
    conn.execute("INSERT INTO color_record (system, code, source_class, use, l, c, recorded_at) "
                 "VALUES ('ral-classic', 'RAL 3020', 'provider', 'spec', .5, .2, 't')")
    conn.execute("INSERT INTO meta VALUES ('inventory_fingerprint', 'stale')")
    conn.commit()
    conn.close()
    with db.connect(database) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
        assert conn.execute("SELECT value FROM meta WHERE key = 'inventory_fingerprint'").fetchone() is None
        result = scan.scan(conn)
        assert (result.updated, result.added, result.removed, result.unreadable) == (2, 0, 0, [])
        rows = list(conn.execute("SELECT * FROM local_font ORDER BY id"))
        assert [row["id"] for row in rows] == [1, 2]
        assert json.loads(rows[0]["metadata_json"])["axes"] == AXES
        assert json.loads(rows[1]["metadata_json"])["languages"] == ["en"]
        assert [row[0] for row in conn.execute("SELECT metrics_json FROM measurement ORDER BY local_font_id")] == [
            '{"saved": true}', '{"saved": true}']
        for table, count in (("user_label", 1), ("color_record", 1), ("embedding", 2)):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == count
        assert scan.scan(conn).updated == 0


@macos
def test_core_text_metadata_and_languages_match_the_same_synthetic_file(env, tmp_path, request, monkeypatch, capsys):
    family = "Synthetic Metadata " + uuid.uuid4().hex[:8]
    path = rich_font(env / "variable.ttf", family=family, extra_letters=FRENCH + _korean_syllables())
    register_for_process([path], request)
    provider = coretext.CoreText(is_adobe=scoped_to(env))
    monkeypatch.setattr(coretext, "provider", lambda: provider)
    assert cli.main(["local", "fonts", "--json", "--no-measure"]) == 0
    reported = json.loads(capsys.readouterr().out)[0]
    file_face = next(face for face in reported["faces"] if face["features_source"] == "opentype")
    os_face = next(face for face in reported["faces"] if face["features_source"] == "coretext")
    for key in ("axes", "languages", "version", "manufacturer", "designer", "units_per_em", "x_height", "cap_height", "class_id"):
        assert os_face[key] == file_face[key], key
    assert os_face["languages"] == ["en", "fr", "ko"]
    assert os_face["axes"] == AXES and os_face["vertical"] == ["vert", "vkna"]
    assert {"liga", "smcp", "vert", "vkna"} <= set(os_face["features"])
    assert os_face["family_class"] == 0x80000000 and os_face["class_source"] == "coretext"
    assert os_face["os2_ranges"] is None and os_face["class_name"] == "sans-serif"
    with db.connect(tmp_path / "cache.db") as conn:
        row = conn.execute("SELECT metadata_json FROM local_font WHERE origin = 'adobe-sync'").fetchone()
        assert json.loads(row[0])["axes"] == AXES


@macos
@pytest.mark.parametrize("feature, expected", [("vrt2", ["vert"]), ("vhal", []), (None, [])])
def test_core_text_vertical_mapping_does_not_claim_indistinguishable_tags(env, request, monkeypatch, capsys, feature, expected):
    family = "Synthetic Vertical " + uuid.uuid4().hex[:8]
    rule = ("sub H by S;" if feature == "vrt2" else "pos H -50;") if feature else None
    features = f"languagesystem DFLT dflt; feature {feature} {{ {rule} }} {feature};" if feature else None
    path = rich_font(env / "vertical.ttf", family=family, variable=False, features=features)
    register_for_process([path], request)
    provider = coretext.CoreText(is_adobe=scoped_to(env))
    monkeypatch.setattr(coretext, "provider", lambda: provider)
    assert cli.main(["local", "fonts", "--json", "--no-measure"]) == 0
    face = next(face for face in json.loads(capsys.readouterr().out)[0]["faces"] if face["features_source"] == "coretext")
    assert face["vertical"] == expected and face["axes"] == []
