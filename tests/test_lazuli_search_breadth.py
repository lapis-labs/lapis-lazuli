"""lazuli search breadth: a family counts for the script it is designed for, equal scores are ordered by role-fit
keys, and uninstalled catalog families keep a share of the list beside installed ones. Nothing reaches the network."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lazuli import cli, db, search
from lazuli.catalog import google_fonts, match, net, store
from lazuli.catalog.store import CatalogFamily, CatalogLabel
from synthetic_fonts import build

FIXTURES = Path(__file__).parent / "fixtures" / "catalog" / "google-fonts"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def no_network(url, headers):
        raise AssertionError(f"a test reached for the network: {url}")

    monkeypatch.setattr(net, "default_transport", no_network)


def source(name: str, priority: int):
    return SimpleNamespace(NAME=name, KIND="snapshot", PRIORITY=priority, TTL_DAYS=30, MIN_INTERVAL_S=3.0)


def listed(name, *, scripts=("latn",), weights=(), signals=None, details=None, tags=(), genre="sans"):
    """A catalog family: an OFL license, the scripts and weights given, and Google-style tags (tag, weight)."""
    return CatalogFamily(
        name, name, license="OFL-1.1", signals=signals or {}, details=details or {},
        labels=[CatalogLabel("genre", genre, genre), CatalogLabel("license", "OFL-1.1", "OFL-1.1"),
                *[CatalogLabel("property", s, f"script:{s}") for s in scripts],
                *[CatalogLabel("property", str(w), f"weight:{w}") for w in weights],
                *[CatalogLabel("feel" if tag.startswith("/Expressive/") else "property", tag, None, weight)
                  for tag, weight in tags]])


def stated(*codes: str) -> dict:
    """What Google Fonts' `primaryScript` becomes in a row's details."""
    return {"primary_scripts": list(codes), "primary_basis": "primaryScript"}


def run(capsys, *argv: str) -> dict:
    assert search.main([*argv, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def names(result: dict) -> list[str]:
    return [c["family"] for c in result["candidates"]]


# ------------------------------------------------------------------------------------------- primary script
@pytest.fixture
def scripts_db(tmp_path, monkeypatch, capsys):
    """Google Fonts lists Latin Display, and three families that have a Latin subset but are designed for
    Gujarati, Thai, and Korean; Fontsource lists Noted Latin with no statement."""
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    conn = db.connect(tmp_path / "lazuli.db")
    store.replace_snapshot(conn, source("google-fonts", 10), [
        listed("Latin Display", weights=(700,)),
        listed("Gujarati Display", scripts=("latn", "gujr"), weights=(700,), details=stated("gujr")),
        listed("Thai Display", scripts=("latn", "thai"), weights=(700,), details=stated("thai")),
        listed("Korean Display", scripts=("latn", "hang"), weights=(700,), details=stated("kore"))])
    store.replace_snapshot(conn, source("fontsource", 20), [listed("Noted Latin", weights=(700,))])
    conn.close()
    capsys.readouterr()


def test_a_family_designed_for_another_script_is_no_latin_candidate_by_default(scripts_db, capsys):
    latin = run(capsys, "--script", "latn", "--role", "display")
    assert sorted(names(latin)) == ["Latin Display", "Noted Latin"]
    (left,) = [n for n in latin["notes"] if "left out" in n]
    assert "3 families cover latn" in left and "gujr 1" in left and "thai 1" in left and "kore 1" in left
    assert "--secondary-scripts" in left


def test_secondary_scripts_lists_them_and_says_the_primary_script(scripts_db, capsys):
    every = run(capsys, "--script", "latn", "--secondary-scripts")
    assert sorted(names(every)) == ["Gujarati Display", "Korean Display", "Latin Display", "Noted Latin", "Thai Display"]
    thai = next(c for c in every["candidates"] if c["family"] == "Thai Display")
    assert any("secondary: its primary script is thai (google-fonts primaryScript)" in e for e in thai["evidence"])
    assert thai["primary_scripts"] == ["thai"]
    assert not [n for n in every["notes"] if "left out" in n]
    assert every["filters"]["secondary_scripts"] is True


def test_the_script_a_family_is_designed_for_still_finds_it(scripts_db, capsys):
    thai = run(capsys, "--script", "thai")
    assert names(thai) == ["Thai Display"]
    assert any("primary script thai (google-fonts primaryScript)" in e for e in thai["candidates"][0]["evidence"])
    korean = run(capsys, "--script", "kore")                    # kore stands for hang; the primary kore expands the same
    assert names(korean) == ["Korean Display"]


def test_installed_faces_with_a_full_cjk_or_thai_set_are_made_for_those_scripts():
    cjk = {"installed": True, "scripts": ["latn", "grek", "hang", "kana"]}
    assert search._primary(cjk, [])["scripts"] == {"hang", "kana"}
    assert search._primary({"installed": True, "scripts": ["latn", "cyrl"]}, []) is None
    assert search._primary({"installed": False, "scripts": ["latn", "hang"]}, []) is None


def test_google_fonts_keeps_primary_script_in_details_only_when_it_states_one():
    families = {f.family: f for f in google_fonts.families_from(
        (FIXTURES / "metadata-fonts.json").read_text(), (FIXTURES / "families.csv").read_text(),
        {d: json.loads((FIXTURES / f"tree-{d}.json").read_text()) for d in ("ofl", "apache", "ufl")})}
    assert families["Nanum Myeongjo"].details == {"primary_scripts": ["kore"], "primary_basis": "primaryScript"}
    assert families["ABeeZee"].details == {}                    # empty in the listing: nothing is stated, not "Latin"


def test_a_database_without_primary_scripts_says_how_to_add_them(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    conn = db.connect(tmp_path / "lazuli.db")
    store.replace_snapshot(conn, source("google-fonts", 10), [listed("Old Row", weights=(700,))])
    conn.close()
    notes = run(capsys, "--script", "latn")["notes"]
    assert any("`lazuli catalog remap`" in n and "no primary scripts yet" in n for n in notes)


# ------------------------------------------------------------------------------------------- role-fit keys
@pytest.fixture
def ties_db(tmp_path, monkeypatch, capsys):
    """Four catalog-only families that score the same for a display request (each has a bold face), named so that
    the alphabet would put the weakest first."""
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    conn = db.connect(tmp_path / "lazuli.db")
    store.replace_snapshot(conn, source("google-fonts", 10), [
        listed("Alpha Bold", weights=(400, 700), tags=[("/Expressive/Loud", 10.0)]),
        listed("Beta Black", weights=(700, 900), tags=[("/Expressive/Loud", 10.0)]),
        listed("Gamma Black", weights=(700, 900), tags=[("/Expressive/Loud", 80.0)]),
        listed("Delta Display", weights=(700,), genre="display", tags=[("/Expressive/Loud", 5.0)])])
    conn.close()
    capsys.readouterr()


def test_equal_scores_are_ordered_by_role_fit_not_by_the_alphabet(ties_db, capsys):
    result = run(capsys, "--role", "display", "--script", "latn")
    assert {c["score"] for c in result["candidates"]} == {0.53}          # one score for all four
    # display class, then the heaviest weight, then the expressive tag weight, then the number of weights
    assert names(result) == ["Delta Display", "Gamma Black", "Beta Black", "Alpha Bold"]
    gamma = next(c for c in result["candidates"] if c["family"] == "Gamma Black")
    assert "tie-break keys: heaviest weight 900, expressive tag 80, 2 weights" in gamma["evidence"]


def test_without_a_role_equal_scores_end_at_the_name(ties_db, capsys):
    assert names(run(capsys, "--script", "latn")) == ["Alpha Bold", "Beta Black", "Delta Display", "Gamma Black"]


# ------------------------------------------------------------------------------------------- catalog share
INSTALLED = ["Famous Inst A", "Famous Inst B", "Famous Inst C", "Quiet Inst E", "Quiet Inst F", "Quiet Inst G",
             "Unranked Inst U"]
RANKS = {"Famous Inst A": 2, "Famous Inst B": 3, "Famous Inst C": 5, "Famous Cat D": 8, "Quiet Inst E": 13,
         "Quiet Inst F": 21, "Quiet Inst G": 34, "Quiet Cat H": 55, "Quiet Cat I": 89,
         **{f"Filler {n}": 1000 + n for n in range(1, 9)}}


@pytest.fixture
def share_db(tmp_path, monkeypatch, capsys):
    """Seven installed families (three familiar, three less-known, one nobody ranks) against catalog families on
    the same lists: Famous Cat D, the Quiet and Filler ones, Unranked Cat V (Fontsource), and Foundry Gh W (GitHub)."""
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={user}")
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    for name in INSTALLED:
        build(user / f"{name.replace(' ', '')}.ttf", family=name)
    assert cli.main(["local", "fonts"]) == 0
    conn = db.connect(tmp_path / "lazuli.db")
    rank = lambda n: {"popularity": n, "popularity_kind": "rank"}                        # noqa: E731
    store.replace_snapshot(conn, source("google-fonts", 10), [listed(n, signals=rank(p)) for n, p in RANKS.items()])
    store.replace_snapshot(conn, source("fontsource", 20), [listed("Unranked Inst U"), listed("Unranked Cat V")])
    store.replace_snapshot(conn, source("github-foundries", 22), [listed("Foundry Gh W")])
    match.run(conn)
    conn.close()
    capsys.readouterr()


def installed_of(result: dict) -> list[bool]:
    return [c["installed"] for c in result["candidates"]]


def test_a_plain_list_keeps_a_quarter_of_its_slots_for_uninstalled_families(share_db, capsys):
    result = run(capsys, "--script", "latn", "--role", "display", "--limit", "4")
    assert installed_of(result).count(False) == 1
    assert "Famous Cat D" in names(result)                                  # the most popular uninstalled one
    wide = run(capsys, "--script", "latn", "--role", "display", "--limit", "8")
    assert installed_of(wide).count(False) == 2


def test_installed_families_alone_are_listed_as_before(share_db, capsys):
    only = run(capsys, "--script", "latn", "--role", "display", "--installed", "--limit", "4")
    assert all(installed_of(only)) and len(names(only)) == 4
    everything = run(capsys, "--script", "latn", "--role", "display", "--installed", "--limit", "50")
    assert sorted(names(everything)) == sorted(INSTALLED)
    assert names(only) == names(everything)[:4]
    by_tier = run(capsys, "--script", "latn", "--role", "display", "--installed", "--by-familiarity", "--limit", "8")
    assert all(installed_of(by_tier))


def test_each_familiarity_tier_holds_an_uninstalled_family_and_the_unknown_slots_spread_over_catalogs(share_db, capsys):
    result = run(capsys, "--script", "latn", "--role", "display", "--by-familiarity", "--limit", "8")
    tiers = {}
    for c in result["candidates"]:
        tiers.setdefault(c["familiarity"]["tier"], []).append(c)
    assert set(tiers) == {"familiar", "less-known", "unknown"}
    for tier in ("familiar", "less-known"):
        assert [c for c in tiers[tier] if not c["installed"]], tier
    # the two unknown slots: Fontsource's best catalog family, then GitHub's, before the installed Unranked Inst U
    assert [c["family"] for c in tiers["unknown"]] == ["Unranked Cat V", "Foundry Gh W"]
    assert [c["catalogs"][0]["source"] for c in tiers["unknown"]] == ["fontsource", "github-foundries"]


def test_the_list_says_installed_or_catalog_not_installed_and_the_license_needs_confirming(share_db, capsys):
    assert search.main(["--script", "latn", "--role", "display", "--license", "open", "--by-familiarity",
                        "--limit", "8"]) == 0
    out = capsys.readouterr().out
    assert "[installed: user, 1 face]" in out and "[catalog, not installed: github-foundries]" in out
    assert out.count("summary; confirm the original") >= 8
    assert search.main(["--script", "latn", "--role", "display", "--limit", "8"]) == 0
    assert "summary, a hint; confirm the original" in capsys.readouterr().out
