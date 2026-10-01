"""An Adobe Fonts face with an `opsz` axis is never measured through Core Text, which sets that axis from the
point size: it is recorded as unmeasurable with a reason and counted in one line. Synthetic fonts and a fake
font list only; no Adobe data is used here."""
from __future__ import annotations

import json

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.ttLib import TTFont

from lazuli import cli, coretext, db, measure, paths, scan
from fake_adobe import FakeAdobe
from synthetic_fonts import build

OPSZ = ("opsz", 8, 14, 72, "Optical size")
WGHT = ("wght", 100, 400, 900, "Weight")
REASON = "optical size not pinned"


class RecordingAdobe(FakeAdobe):
    """The fake font list, remembering which identities Core Text was asked to open for measurement."""

    def __init__(self, folder):
        super().__init__(folder)
        self.opened: list[str] = []

    def open(self, identity, raster_px):
        self.opened.append(identity)
        return super().open(identity, raster_px)


def with_axes(path, axes):
    with TTFont(path) as font:
        FontBuilder(font=font).setupFvar(list(axes), [])
        font.save(path)
    return path


@pytest.fixture
def adobe(tmp_path, monkeypatch):
    root = tmp_path / "user"
    root.mkdir()
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={root}")          # also keeps the real Core Text listing off
    fake = RecordingAdobe(tmp_path / "os-fonts")
    monkeypatch.setattr(coretext, "provider", lambda: fake)
    return fake


def add_face(fake, family, axes):
    identity = fake.add(family)
    with_axes(fake.entries[identity][0], axes)
    return identity


def stored(conn):
    """family -> (family_kind, metrics) of every stored measurement."""
    return {row["family"]: (row["family_kind"], json.loads(row["metrics_json"])) for row in conn.execute(
        "SELECT lf.family, m.family_kind, m.metrics_json FROM measurement m JOIN local_font lf ON lf.id = m.local_font_id")}


def test_adobe_faces_with_an_optical_size_axis_stay_unmeasured_with_one_reason_line(adobe, tmp_path):
    optical = add_face(adobe, "Sync Serif Display", [OPSZ, WGHT])
    add_face(adobe, "Sync Serif Text", [OPSZ])
    weight = add_face(adobe, "Sync Sans", [WGHT])
    conn = db.connect(paths.db_path())
    scan.scan(conn)
    measured, failures = measure.measure_pending(conn)
    assert measured == 1
    assert failures == [f"Adobe Fonts: 2 faces with an opsz axis not measured ({REASON})"]     # a count, no values
    assert adobe.opened == [weight]                                       # Core Text never opened the other two
    rows = stored(conn)
    assert rows["Sync Serif Display"] == rows["Sync Serif Text"] == (None, {"unmeasurable": REASON})
    numbers = conn.execute("SELECT panose_json, cjk_json FROM measurement m JOIN local_font lf ON lf.id = m.local_font_id "
                           "WHERE lf.path = ?", (optical,)).fetchone()
    assert tuple(numbers) == (None, None)


def test_one_optical_size_face_is_counted_in_the_singular(adobe):
    add_face(adobe, "Sync Serif Display", [OPSZ])
    conn = db.connect(paths.db_path())
    scan.scan(conn)
    assert measure.measure_pending(conn) == (0, [f"Adobe Fonts: 1 face with an opsz axis not measured ({REASON})"])


def test_an_unmeasured_optical_size_face_is_not_attempted_again(adobe):
    add_face(adobe, "Sync Serif Display", [OPSZ])
    conn = db.connect(paths.db_path())
    scan.scan(conn)
    measure.measure_pending(conn)
    assert measure.measure_pending(conn) == (0, [])                       # recorded once per measurer version
    assert scan.scan(conn).updated == 0
    assert measure.measure_pending(conn) == (0, [])
    assert adobe.opened == []


def test_local_fonts_says_it_once_and_lists_the_face_as_unmeasured(adobe, capsys):
    add_face(adobe, "Sync Serif Display", [OPSZ])
    add_face(adobe, "Sync Sans", [WGHT])
    assert cli.main(["local", "fonts", "--json"]) == 0
    first = capsys.readouterr()
    assert {f["family"]: f["measured"] for f in json.loads(first.out)} == {"Sync Serif Display": 0, "Sync Sans": 1}
    assert first.err.count("skipped") == 1
    assert f"  skipped Adobe Fonts: 1 face with an opsz axis not measured ({REASON})" in first.err
    assert "measured 1 faces" in first.err
    assert cli.main(["local", "fonts", "--json"]) == 0
    assert "skipped" not in capsys.readouterr().err


def test_a_face_measured_before_its_axes_were_stored_is_decided_again(adobe):
    """A database from before the axes were stored has numbers for a face the scan later reports as `opsz`."""
    add_face(adobe, "Sync Serif Display", [OPSZ, WGHT])
    conn = db.connect(paths.db_path())
    scan.scan(conn)
    axes = conn.execute("SELECT metadata_json FROM local_font").fetchone()[0]
    conn.execute("UPDATE local_font SET metadata_json = ?", (json.dumps({**json.loads(axes), "axes": []}),))
    assert measure.measure_pending(conn) == (1, [])                       # stored as not variable: numbers were made
    assert stored(conn)["Sync Serif Display"][0] == "text"
    conn.execute("UPDATE local_font SET metadata_json = ?", (axes,))      # the next scan fills them in
    assert measure.measure_pending(conn) == (0, [f"Adobe Fonts: 1 face with an opsz axis not measured ({REASON})"])
    assert stored(conn)["Sync Serif Display"] == (None, {"unmeasurable": REASON})
    assert measure.measure_pending(conn) == (0, [])


def test_files_with_an_optical_size_axis_are_still_measured(adobe, tmp_path):
    with_axes(build(tmp_path / "user" / "Plain.ttf", family="Plain Sans"), [OPSZ, WGHT])
    conn = db.connect(paths.db_path())
    scan.scan(conn)
    assert measure.measure_pending(conn) == (1, [])
    kind, metrics = stored(conn)["Plain Sans"]
    assert kind == "text" and metrics["method"] == "file" and metrics["variable"] is True


def test_measuring_an_optical_size_row_directly_is_refused_before_the_font_list_is_asked(adobe):
    identity = add_face(adobe, "Sync Serif Display", [OPSZ])
    conn = db.connect(paths.db_path())
    scan.scan(conn)
    row = dict(conn.execute("SELECT * FROM local_font").fetchone())
    with pytest.raises(measure.OpticalSizeNotPinned, match=REASON):
        measure.measure_face(identity, 0, row, {}, provider=adobe)
    assert adobe.opened == []
