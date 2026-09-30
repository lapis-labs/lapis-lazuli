"""lazuli class: the classes the user gave for a family, kept only in the user cache DB. A user class outranks
every catalog in `local fonts`, `search`, and `lock`, which show its source as `user`; `doctor` counts them.

Nothing here reaches the network: the catalog transport, urllib, and sockets all fail the test.
"""
from __future__ import annotations

import json
import socket
import sqlite3
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from lazuli import catalog, cli, coretext, db, doctor, lock, search, user_class
from lazuli.catalog import adobe_cjk, labels, match, net, store
from lazuli.catalog.store import CatalogFamily, CatalogLabel
from fake_adobe import FakeAdobe
from synthetic_fonts import build

ADOBE_PAGE = "https://fonts.adobe.com/fonts/mystery-myeongjo"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"a test reached for the network: {args[:2]}")

    monkeypatch.setattr(net, "default_transport", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def ofl(name: str, genre: str, value: str, *, scripts=("latn",)) -> CatalogFamily:
    return CatalogFamily(name, name, license="OFL-1.1",
                         labels=labels.class_labels(genre, value)
                         + [CatalogLabel("property", s, f"script:{s}") for s in scripts]
                         + [CatalogLabel("license", "OFL", "OFL-1.1")])


@pytest.fixture
def env(tmp_path, monkeypatch, capsys):
    """Installed: Mystery Myeongjo (an Adobe Fonts face from a stand-in for the system font list, ko 미스터리명조)
    and Test Sans (user). Google Fonts lists both, Mystery Myeongjo as sans, and Gowun Batang (not installed) as
    bu-ri, all OFL. The working folder is an empty project."""
    user = tmp_path / "fonts" / "user"
    user.mkdir(parents=True)
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={user}")
    database = tmp_path / "cache" / "lazuli.db"
    monkeypatch.setenv("LAZULI_DB", str(database))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    adobe = FakeAdobe(tmp_path / "os-fonts")
    adobe.add("Mystery Myeongjo", names_ko="미스터리명조", bu=True)
    monkeypatch.setattr(coretext, "provider", lambda: adobe)
    build(user / "TestSans-Regular.ttf", family="Test Sans")
    assert cli.main(["local", "fonts", "--no-measure"]) == 0
    conn = db.connect(database)
    google = SimpleNamespace(NAME="google-fonts", KIND="snapshot", PRIORITY=10, TTL_DAYS=30, MIN_INTERVAL_S=3.0)
    store.replace_snapshot(conn, google, [ofl("Mystery Myeongjo", "Sans Serif", "sans", scripts=("hang", "latn")),
                                          ofl("Test Sans", "Sans Serif", "sans"),
                                          ofl("Gowun Batang", "Serif", "bu-ri", scripts=("hang", "latn"))])
    match.run(conn)
    conn.close()
    capsys.readouterr()
    return SimpleNamespace(root=tmp_path, project=project, db=database)


def run_class(capsys, *argv: str) -> tuple[int, str, str]:
    code = user_class.main(list(argv), prog="lazuli class")
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def listed(capsys) -> list[dict]:
    code, out, _ = run_class(capsys, "list", "--json")
    assert code == 0
    return json.loads(out)["classes"]


def files_outside_the_cache(root: Path) -> set[Path]:
    return {p for p in root.rglob("*") if p.is_file() and "cache" not in p.relative_to(root).parts}


def test_set_list_and_remove_keep_only_the_given_values_in_the_user_cache(env, capsys):
    before = files_outside_the_cache(env.root)
    code, out, _ = run_class(capsys, "set", "미스터리명조", "--genre", "bu-ri", "--subclass", "new", "--url", ADOBE_PAGE)
    assert code == 0
    assert "Mystery Myeongjo: genre bu-ri, subclass bu-ri.new (user)" in out     # the DB's name for the ko name
    [row] = listed(capsys)
    assert row.pop("recorded_at")
    assert row == {"family": "Mystery Myeongjo", "genre": "bu-ri", "subclass": "bu-ri.new", "url": ADOBE_PAGE,
                   "installed": True}
    conn = sqlite3.connect(env.db)
    stored = conn.execute("SELECT * FROM user_label").fetchall()
    conn.close()
    assert [row[:5] for row in stored] == [("mysterymyeongjo", "Mystery Myeongjo", "bu-ri", "bu-ri.new", ADOBE_PAGE)]
    assert len(stored[0]) == 6                                              # and the time it was recorded

    code, out, _ = run_class(capsys, "set", "mystery myeongjo", "--genre", "min-bu-ri")
    assert code == 0 and out.startswith("replaced")
    [row] = listed(capsys)                                                  # a new label replaces all of the old one
    assert (row["genre"], row["subclass"], row["url"]) == ("min-bu-ri", None, None)
    code, out, _ = run_class(capsys, "list")
    assert "Mystery Myeongjo  genre min-bu-ri  installed" in out

    assert files_outside_the_cache(env.root) == before                     # nothing in the project or elsewhere
    assert run_class(capsys, "remove", "미스터리명조")[0] == 0
    assert listed(capsys) == []
    code, out, err = run_class(capsys, "remove", "Mystery Myeongjo")
    assert code == 1 and "no user class" in err
    assert "no user classes yet" in run_class(capsys, "list")[1]


def test_set_takes_only_the_type_vocabulary_and_a_plain_link(env, capsys):
    code, _, err = run_class(capsys, "set", "Test Sans", "--genre", "gothic")
    assert code == 2 and "'gothic' is not a genre" in err and "min-bu-ri" in err
    code, _, err = run_class(capsys, "set", "Test Sans", "--genre", "sans", "--subclass", "rounded")
    assert code == 2 and "sans has no subclasses" in err
    code, _, err = run_class(capsys, "set", "Test Sans", "--genre", "bu-ri", "--subclass", "min-bu-ri.rounded")
    assert code == 2 and "not a subclass of bu-ri" in err and "bu-ri.new" in err
    for url in ("ftp://fonts.example/test-sans", "fonts.adobe.com/fonts/x", "https://me:secret@fonts.adobe.com/x"):
        code, _, err = run_class(capsys, "set", "Test Sans", "--genre", "sans", "--url", url)
        assert code == 2 and "--url" in err, url
    assert listed(capsys) == []                                             # a refused label stores nothing

    code, out, err = run_class(capsys, "set", "Nowhere Grotesk", "--genre", "sans")
    assert code == 0 and "not installed and in no synced catalog" in err     # kept: it applies once the family is
    assert [(r["family"], r["installed"]) for r in listed(capsys)] == [("Nowhere Grotesk", False)]


def local_fonts(capsys) -> dict[str, dict]:
    assert cli.main(["local", "fonts", "--json", "--no-measure"]) == 0
    return {f["family"]: f for f in json.loads(capsys.readouterr().out)}


def triples(family: dict) -> set[tuple]:
    return {(lb["kind"], lb["mapped"], lb["source"]) for lb in family["catalog"]["labels"]}


def test_a_user_label_outranks_the_catalogs_in_local_fonts(env, capsys):
    assert store.USER_PRIORITY < min(module.PRIORITY for module in catalog.SOURCES)   # every adapter, by priority
    assert ("genre", "sans", "google-fonts") in triples(local_fonts(capsys)["Mystery Myeongjo"])
    assert run_class(capsys, "set", "Mystery Myeongjo", "--genre", "bu-ri", "--subclass", "bu-ri.new",
                     "--url", ADOBE_PAGE)[0] == 0
    fonts = local_fonts(capsys)
    mystery = fonts["Mystery Myeongjo"]
    assert triples(mystery) == {("genre", "bu-ri", "user"), ("subclass", "bu-ri.new", "user"),
                                ("property", "script:hang", "google-fonts"), ("property", "script:latn", "google-fonts"),
                                ("license", "OFL-1.1", "google-fonts")}   # the class from one source; the rest stays
    assert mystery["user_class"] == {"genre": "bu-ri", "subclass": "bu-ri.new", "url": ADOBE_PAGE,
                                     "recorded_at": mystery["user_class"]["recorded_at"]}
    assert ("genre", "sans", "google-fonts") in triples(fonts["Test Sans"]) and "user_class" not in fonts["Test Sans"]

    assert cli.main(["local", "fonts", "--family", "mystery", "--no-measure"]) == 0
    out = capsys.readouterr().out
    assert f"    user: genre bu-ri, subclass bu-ri.new  (your class; {ADOBE_PAGE})" in out
    assert "    catalog: license OFL-1.1  (google-fonts: Mystery Myeongjo, exact_family)" in out

    assert run_class(capsys, "remove", "Mystery Myeongjo")[0] == 0
    assert ("genre", "sans", "google-fonts") in triples(local_fonts(capsys)["Mystery Myeongjo"])


def found(capsys, *argv: str) -> dict:
    assert search.main([*argv, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def by_family(result: dict) -> dict[str, dict]:
    return {c["family"]: c for c in result["candidates"]}


def test_search_filters_by_the_user_label_and_names_it(env, capsys):
    assert "Mystery Myeongjo" not in by_family(found(capsys, "--category", "bu-ri"))   # the catalog says sans
    run_class(capsys, "set", "Mystery Myeongjo", "--genre", "bu-ri", "--subclass", "bu-ri.new")
    mystery = by_family(found(capsys, "--category", "bu-ri"))["Mystery Myeongjo"]
    assert mystery["genres"] == ["bu-ri", "bu-ri.new"]
    assert "category bu-ri (user class)" in mystery["evidence"]
    assert "class bu-ri, bu-ri.new (user class)" in mystery["evidence"]
    assert "subclass label 'bu-ri.new' (user)" in by_family(found(capsys, "bu-ri.new"))["Mystery Myeongjo"]["evidence"]
    assert "Mystery Myeongjo" not in by_family(found(capsys, "--category", "sans"))

    assert "role body: text class sans (catalog)" in by_family(found(capsys, "--role", "body"))["Test Sans"]["evidence"]
    run_class(capsys, "set", "Test Sans", "--genre", "hand")
    body = by_family(found(capsys, "--role", "body"))
    assert "Test Sans" not in body                                          # the user's hand beats the catalog's sans
    assert "role body: text class bu-ri (user class)" in body["Mystery Myeongjo"]["evidence"]

    run_class(capsys, "set", "Gowun Batang", "--genre", "display")        # a catalog family nothing installed matched
    gowun = by_family(found(capsys, "--category", "display"))["Gowun Batang"]
    assert not gowun["installed"] and "category display (user class)" in gowun["evidence"]
    assert "Gowun Batang" not in by_family(found(capsys, "--category", "bu-ri"))

    assert search.main(["--category", "bu-ri"]) == 0
    assert "class bu-ri, bu-ri.new (user class)" in capsys.readouterr().out


def test_lock_names_the_user_label_as_a_hint_and_writes_it_nowhere(env, capsys):
    run_class(capsys, "set", "Mystery Myeongjo", "--genre", "bu-ri", "--subclass", "bu-ri.new", "--url", ADOBE_PAGE)
    assert lock.main(["미스터리명조", "--role", "body", "--task", "demo", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    hint = [n for n in out["notes"] if "(user)" in n]
    assert hint == ["class bu-ri, bu-ri.new comes from your class (user): a hint for choosing, not a license fact; "
                    "it stays in the lazuli DB and is not written to the lock"]
    entry = out["entry"]
    assert entry["source"] == "adobe-sync" and entry["catalog_match"]["catalog"] == "google-fonts"
    assert (entry["license"]["kind"], entry["license"]["source_class"]) == ("ofl", "catalog-summary")
    written = (env.project / ".lapis" / "fonts.lock.json").read_text(encoding="utf-8")
    assert lock.validate(json.loads(written)) == []
    assert "bu-ri" not in written and "fonts.adobe.com" not in written

    assert lock.main(["Test Sans", "--role", "ui", "--task", "demo", "--dry-run"]) == 0
    assert "(user)" not in capsys.readouterr().out                         # only the labeled family


def test_doctor_counts_user_labels(env, capsys, monkeypatch):
    monkeypatch.setattr(doctor, "_browser", lambda: ("ok", "browser", "not checked here"))
    assert cli.main(["doctor"]) == 0
    assert "ok    user classes  0 families classified by you" in capsys.readouterr().out
    run_class(capsys, "set", "Mystery Myeongjo", "--genre", "bu-ri")
    assert cli.main(["doctor"]) == 0
    assert "ok    user classes  1 family classified by you (`lazuli class list`)" in capsys.readouterr().out


def test_labeling_an_adobe_font_sends_nothing_to_adobe(env, capsys):
    """The user reads the class on the Adobe Fonts page and gives it; lazuli only records it. The link is
    stored, never opened, and the refused adapter stays disabled without a request (sockets fail the test)."""
    assert run_class(capsys, "set", "Mystery Myeongjo", "--genre", "bu-ri", "--url", ADOBE_PAGE)[0] == 0
    assert cli.main(["catalog", "sync", "--source", "adobe-cjk"]) == 0
    assert "adobe-cjk: disabled: Adobe's General Terms of Use (section 6.18)" in capsys.readouterr().out
    asked = []
    with pytest.raises(net.Blocked, match=r"section 6\.18"):
        adobe_cjk.fetch(net.Fetcher(adobe_cjk.NAME, min_interval_s=adobe_cjk.MIN_INTERVAL_S,
                                    transport=lambda url, headers: asked.append(url)))
    assert asked == []
    assert ("genre", "bu-ri", "user") in triples(local_fonts(capsys)["Mystery Myeongjo"])
    assert "Mystery Myeongjo" in by_family(found(capsys, "--category", "bu-ri"))


def test_the_label_command_is_gone_and_class_takes_its_place(capsys):
    with pytest.raises(SystemExit) as gone:
        cli.main(["label", "list"])
    assert gone.value.code == 2 and "invalid choice: 'label'" in capsys.readouterr().err
    assert cli.main(["class", "list"]) == 0
