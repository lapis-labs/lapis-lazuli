"""lazuli license: what an installed font says about its own license, and where to look next. Read-only."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fontTools.ttLib import TTFont

from lazuli import cli, db, license as license_command, lock
from synthetic_fonts import build


def with_records(path: Path, records: dict[int, str]) -> Path:
    font = TTFont(str(path))
    for name_id, text in records.items():
        font["name"].setName(text, name_id, 3, 1, 0x409)
    font.save(str(path))
    return path


@pytest.fixture
def installed(tmp_path, monkeypatch, capsys):
    """Test Sans in a user folder with a license file beside it, and System Serif in the system folder."""
    user, system = tmp_path / "fonts" / "FontBase" / "user", tmp_path / "fonts" / "system"
    user.mkdir(parents=True)
    system.mkdir(parents=True)
    monkeypatch.setenv("LAZULI_FONT_ROOTS", os.pathsep.join([f"user={user}", f"system={system}"]))
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "cache" / "lazuli.db"))
    records = {0: "Copyright 2026 Test Foundry", 13: "Licensed under the SIL Open Font License, Version 1.1.",
               14: "https://openfontlicense.org", 8: "Test Foundry", 9: "A. Designer", 11: "https://foundry.example"}
    for style in ("Regular", "Bold"):
        with_records(build(user / f"TestSans-{style}.ttf", family="Test Sans", style=style), records)
    (user / "OFL.txt").write_text("SIL OPEN FONT LICENSE", encoding="utf-8")
    (user / "notes.md").write_text("not about licenses", encoding="utf-8")
    build(system / "SystemSerif.ttf", family="System Serif", serif=True)
    assert cli.main(["local", "fonts", "--no-measure"]) == 0
    capsys.readouterr()
    return SimpleNamespace(user=user, project=tmp_path / "project")


def collected(env, family):
    conn = db.connect(Path(os.environ["LAZULI_DB"]))
    try:
        return license_command.collect(conn, family, env.project)
    finally:
        conn.close()


def test_an_installed_font_shows_its_own_records_its_folder_and_what_installed_it(installed):
    found = collected(installed, "test sans")
    [group] = found["installed"]                                    # both faces say the same: shown once
    assert group["origin"] == "user" and sorted(group["files"]) == ["TestSans-Bold.ttf", "TestSans-Regular.ttf"]
    assert group["records"]["license"] == ["Licensed under the SIL Open Font License, Version 1.1."]
    assert group["records"]["license_url"] == ["https://openfontlicense.org"]
    assert "Test Foundry" in group["records"]["manufacturer"]
    assert group["records"]["vendor_url"] == ["https://foundry.example"]
    assert group["license_files"] == ["OFL.txt"]                    # a license-looking name, not notes.md
    assert group["installer"]["kind"] == "font-manager" and group["installer"]["name"] == "FontBase"
    assert len(found["search"]) == 3 and all(found["family"] in query for query in found["search"])   # a maker is named
    text = license_command.render(found)
    assert "hints until a document is read" in text and "OFL.txt" in text


def test_a_system_font_is_the_operating_systems_to_license_and_not_a_font_to_ship(installed):
    [group] = collected(installed, "System Serif")["installed"]
    assert group["installer"]["kind"] == "operating-system" and "not a font to ship" in group["installer"]["note"]


def test_an_adobe_activation_has_no_file_and_none_is_opened(installed, monkeypatch):
    face = {"origin": "adobe-sync", "path": "coretext:Whatever-Regular", "face_index": 0}
    monkeypatch.setattr(lock, "find_family", lambda conn, name: lock.Facts("Whatever", [face], [], [], []))
    monkeypatch.setattr(lock, "read_file", lambda *a, **k: pytest.fail("a file of an Adobe font was opened"))
    [group] = collected(installed, "Whatever")["installed"]
    assert group["files"] == [] and group["folder"] is None and "records" not in group
    assert group["installer"]["kind"] == "adobe-fonts" and "lazuli opens no file" in group["installer"]["note"]


def test_the_folder_of_a_font_and_its_path_tell_what_installed_it():
    assert license_command.installer("user", "/Users/me/Library/Fonts/A.ttf")["kind"] == "user-folder"
    assert license_command.installer("user", "/work/brand/fonts/A.ttf")["kind"] == "other-folder"
    managed = license_command.installer("user", "/Users/me/Library/Application Support/Fontstand/A.otf")
    assert (managed["kind"], managed["name"]) == ("font-manager", "Fontstand")


def test_the_recorded_research_of_the_family_is_shown(installed):
    installed.project.mkdir()
    code = lock.main(["Test Sans", "--role", "body", "--task", "demo", "--project", str(installed.project),
                      "--research", "unknown-after-research", "--evidence", "web-search", "--evidence-note",
                      "searched: Test Sans font license", "--research-note", "no license found"])
    assert code == 0
    assert collected(installed, "Test Sans")["lock"] == [
        {"role": "body", "state": "unknown", "outcome": "unknown-after-research", "evidence": 1}]
    lock.main(["System Serif", "--role", "ui", "--task", "demo", "--project", str(installed.project)])
    assert collected(installed, "System Serif")["lock"] == [
        {"role": "ui", "state": "unresearched", "outcome": None, "evidence": 0}]


def test_an_unknown_family_exits_2_and_sends_nothing(installed, capsys, monkeypatch):
    from lazuli.catalog import net

    monkeypatch.setattr(net, "default_transport", lambda url, headers: pytest.fail("a request was sent"))
    assert license_command.main(["No Such Family"]) == 2
    assert "unknown to the lazuli DB" in capsys.readouterr().err
    assert license_command.main(["Test Sans", "--json", "--project", str(installed.project)]) == 0
    assert json.loads(capsys.readouterr().out)["family"] == "Test Sans"
