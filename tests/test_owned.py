"""`lazuli owned`: fonts the owner has but has not installed, by name only, and how `lazuli search` shows them."""
from __future__ import annotations

import json

import pytest

from lazuli import cli, db, owned, paths, search
from synthetic_fonts import build

NAMES = "# Adobe Fonts I can activate\n- Zzyx Grotesk\n\nQqq Serif\n* Zzyx Grotesk\nBroken\x1b[31m Name\n"


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """One installed, measured family: Test Sans. Owned names are added by each test."""
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={user}")
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    build(user / "TestSans-Regular.ttf", family="Test Sans")
    build(user / "TestSerif.ttf", family="Test Serif", serif=True, contrast=True)
    assert cli.main(["local", "fonts"]) == 0


def add(tmp_path, text=NAMES, source="adobe"):
    file = tmp_path / "names.txt"
    file.write_text(text, encoding="utf-8")
    return cli.main(["owned", "add", "--from", str(file), "--source", source])


def candidates(capsys, *argv):
    assert search.main([*argv, "--limit", "50", "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_add_keeps_names_only_marked_not_installed_and_cleans_them(tmp_path, capsys):
    assert add(tmp_path) == 0
    out = capsys.readouterr().out
    assert "added 3 of 3 names" in out and "names only" in out
    rows = owned.load()
    assert [r["name"] for r in rows] == ["Zzyx Grotesk", "Qqq Serif", "Broken Name"]
    assert all(r["source"] == "adobe" and r["status"] == "not-installed" and r["added_at"].endswith("Z") for r in rows)
    assert set(rows[0]) == {"name", "source", "status", "added_at"}                       # nothing but a name and where it is held
    assert owned.owned_path().parent == paths.cache_dir() and not paths.db_path().exists()
    assert add(tmp_path) == 0 and "already listed: Zzyx Grotesk, Qqq Serif, Broken Name" in capsys.readouterr().out
    assert len(owned.load()) == 3


def test_add_takes_a_json_list_and_refuses_an_empty_file_an_unknown_source_and_a_missing_file(tmp_path, capsys):
    assert add(tmp_path, json.dumps(["Json Face", 7, "Other Face"])) == 0
    assert [r["name"] for r in owned.load()] == ["Json Face", "Other Face"]
    assert add(tmp_path, "# only a comment\n\n") == 2 and "holds no name" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        add(tmp_path, source="fontbase")
    assert cli.main(["owned", "add", "--from", str(tmp_path / "missing.txt"), "--source", "adobe"]) == 2


def test_list_marks_a_name_installed_once_the_database_lists_it(installed, tmp_path, capsys):
    assert add(tmp_path, "Test Sans\nQqq Serif\n") == 0
    capsys.readouterr()
    assert cli.main(["owned", "list", "--json"]) == 0
    rows = {r["name"]: r["installed"] for r in json.loads(capsys.readouterr().out)["fonts"]}
    assert rows == {"Test Sans": True, "Qqq Serif": False}
    assert cli.main(["owned", "list"]) == 0
    text = capsys.readouterr().out
    assert "Qqq Serif  [adobe; not installed, needs activation]" in text and "Test Sans  [adobe; installed]" in text


def test_remove_deletes_one_name(tmp_path, capsys):
    add(tmp_path, "Zzyx Grotesk\nQqq Serif\n")
    assert cli.main(["owned", "remove", "zzyx grotesk"]) == 0
    assert [r["name"] for r in owned.load()] == ["Qqq Serif"]
    assert cli.main(["owned", "remove", "Nope"]) == 1


def test_search_shows_an_owned_name_that_is_not_installed_as_needing_activation(installed, tmp_path, capsys):
    add(tmp_path)
    capsys.readouterr()
    result = candidates(capsys, "Zzyx")
    (cand,) = result["candidates"]
    assert cand["family"] == "Zzyx Grotesk" and cand["installed"] is False and cand["owned"] == {"source": "adobe", "name": "Zzyx Grotesk"}
    assert any("needs activation" in e for e in cand["evidence"]) and cand["scripts"] == [] and cand["classes"] == []
    assert search.main(["Zzyx"]) == 0
    assert "[owned (adobe): needs activation]" in capsys.readouterr().out


def test_an_owned_family_that_is_installed_says_so_and_is_not_listed_twice(installed, tmp_path, capsys):
    add(tmp_path, "Test Sans\nZzyx Grotesk\n")
    capsys.readouterr()
    result = candidates(capsys, "Test Sans")
    (cand,) = result["candidates"]
    assert cand["installed"] is True and cand["owned"]["name"] == "Test Sans" and "on your owned list (adobe)" in cand["evidence"]


def test_the_owned_list_never_changes_what_the_other_candidates_score(installed, tmp_path, capsys):
    before = candidates(capsys, "Test")
    add(tmp_path, "Test Sans\nTest Zzyx\nZzyx Grotesk\n")
    capsys.readouterr()
    after = candidates(capsys, "Test")
    mine = {c["family"]: c for c in after["candidates"]}
    assert mine["Test Sans"]["owned"]["source"] == "adobe" and mine["Test Zzyx"]["installed"] is False
    for old in before["candidates"]:
        new = mine[old["family"]]
        assert (new["score"], new["scripts"], new["classes"], new["genres"]) == (old["score"], old["scripts"], old["classes"], old["genres"])


def test_a_filter_leaves_the_names_out_and_says_so(installed, tmp_path, capsys):
    add(tmp_path)
    capsys.readouterr()
    result = candidates(capsys, "--role", "body")
    assert {c["family"] for c in result["candidates"]} == {"Test Sans", "Test Serif"}
    assert any("3 owned names that are not installed are left out" in n for n in result["notes"])
    assert candidates(capsys, "--installed", "Zzyx")["candidates"] == []
    assert "Zzyx Grotesk" not in {c["family"] for c in candidates(capsys, "--similar-to", "Test Sans")["candidates"]}


def test_the_owned_list_is_not_in_the_database(installed, tmp_path):
    add(tmp_path)
    conn = db.connect(paths.db_path())
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
        assert not any("owned" in t or "adobe" in t for t in tables)
        assert conn.execute("SELECT COUNT(*) FROM local_font WHERE family LIKE '%Zzyx%'").fetchone()[0] == 0
    finally:
        conn.close()
