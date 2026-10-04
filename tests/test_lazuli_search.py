"""lazuli search (fonts): ranked candidates with evidence from local fonts and synced catalogs."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fontTools.ttLib import TTFont

from lazuli import cli, db, search
from lazuli.catalog import labels, match, net, store
from lazuli.catalog.store import CatalogFamily, CatalogLabel
from synthetic_fonts import build


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def no_network(url, headers):
        raise AssertionError(f"a test reached for the network: {url}")

    monkeypatch.setattr(net, "default_transport", no_network)


def family(name, genre, value, *, ko=None, license_id="OFL-1.1", scripts=("latn",), foundry=None, weights=(),
           also=None):
    extra = [CatalogLabel("license", license_id, labels.map_license(license_id) or license_id)] if license_id else []
    return CatalogFamily(name, name, names_i18n={"ko": ko} if ko else {}, foundry=foundry,
                         labels=labels.class_labels(genre, value) + (labels.class_labels(*also) if also else [])
                         + [CatalogLabel("property", s, f"script:{s}") for s in scripts]
                         + [CatalogLabel("property", str(w), f"weight:{w}") for w in weights] + extra)


def weight_class(path, weight: int):
    font = TTFont(str(path))
    font["OS/2"].usWeightClass = weight
    font.save(str(path))


@pytest.fixture
def fonts_db(tmp_path, monkeypatch, capsys):
    """Installed and measured: Test Sans (2 faces), Test Sans Twin (same shapes), Contrast Serif, Even Mono,
    Brush Hand, Pen Notes (a hand name hint only), Only Icons (no letters), Heavy Grotesk (one face, weight
    class 900), Fat Regular (weight class 400 with bold strokes). Google Fonts lists Test Sans, Brush Hand
    (handwriting), Gowun Batang, Plain Serif, Loud Display, Weighted Serif (weights 400 and 700), Loud Sans
    (sans, also display), and Mincho Test (jpan); Fontsource lists Plain Serif too, and Proprietary Serif
    with no license label."""
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={user}")
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    build(user / "TestSans-Regular.ttf", family="Test Sans")
    build(user / "TestSans-Bold.ttf", family="Test Sans", style="Bold", stem=160)
    build(user / "Twin.ttf", family="Test Sans Twin")
    build(user / "Serif.ttf", family="Contrast Serif", serif=True, contrast=True)
    build(user / "Mono.ttf", family="Even Mono", mono=True)
    build(user / "Hand.ttf", family="Brush Hand", stem=60, contrast=True)
    build(user / "Pen.ttf", family="Pen Notes", stem=140, serif=True)
    build(user / "Icons.ttf", family="Only Icons", latin=False, hangul=False)
    weight_class(build(user / "Heavy.ttf", family="Heavy Grotesk", style="Black", stem=180), 900)
    build(user / "Fat.ttf", family="Fat Regular", stem=180)
    assert cli.main(["local", "fonts"]) == 0
    conn = db.connect(tmp_path / "lazuli.db")
    snapshot = lambda name, priority: SimpleNamespace(NAME=name, KIND="snapshot", PRIORITY=priority,  # noqa: E731
                                                      TTL_DAYS=30, MIN_INTERVAL_S=3.0)
    store.replace_snapshot(conn, snapshot("google-fonts", 10), [
        family("Test Sans", "Sans Serif", "sans"), family("Brush Hand", "Handwriting", "hand"),
        family("Gowun Batang", "Serif", "bu-ri", ko="고운바탕", scripts=("hang", "latn"), foundry="Yanghee Ryu"),
        family("Plain Serif", "Serif", "serif"), family("Loud Display", "Display", "display"),
        family("Weighted Serif", "Serif", "serif", weights=(400, 700)),
        family("Loud Sans", "Sans Serif", "sans", also=("Display", "display")),
        family("Mincho Test", "Sans Serif", "sans", scripts=("jpan",))])
    store.replace_snapshot(conn, snapshot("fontsource", 20), [
        family("Plain Serif", "serif", "serif"), family("Proprietary Serif", "serif", "serif", license_id=None)])
    match.run(conn)
    conn.close()
    capsys.readouterr()


def found(capsys, *argv: str) -> dict:
    """The JSON of a search that lists every match unless the test names a --limit."""
    limit = [] if "--limit" in argv else ["--limit", "50"]
    assert search.main([*argv, *limit, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def families(result: dict) -> list[str]:
    return [c["family"] for c in result["candidates"]]


def test_a_search_lists_eight_by_default_and_says_how_many_more_match(fonts_db, capsys):
    assert search.main(["--role", "body", "--json"]) == 0
    default = json.loads(capsys.readouterr().out)
    everything = found(capsys, "--role", "body")
    hidden = len(everything["candidates"]) - search.DEFAULT_LIMIT
    assert search.DEFAULT_LIMIT == 8 and hidden > 0
    assert families(default) == families(everything)[:8]
    assert any(note.startswith(f"{hidden} more candidates match") for note in default["notes"])
    assert not any("more candidates match" in note for note in everything["notes"])


def test_text_query_ranks_names_first_and_says_why(fonts_db, capsys):
    result = found(capsys, "serif")
    names = families(result)
    assert names[:2] == ["Contrast Serif", "Plain Serif"]               # names first, installed before catalog
    assert set(names) >= {"Proprietary Serif", "Gowun Batang"}          # Gowun Batang by its genre label only
    by_name = {c["family"]: c for c in result["candidates"]}
    assert by_name["Plain Serif"]["catalogs"] == [
        {"source": "google-fonts", "family": "Plain Serif", "url": None},
        {"source": "fontsource", "family": "Plain Serif", "url": None}]       # one candidate for both catalogs
    assert "genre label 'Serif = bu-ri' (google-fonts)" in by_name["Gowun Batang"]["evidence"]
    assert by_name["Gowun Batang"]["score"] < by_name["Plain Serif"]["score"]
    assert "measured serif" in by_name["Contrast Serif"]["evidence"]
    test_sans = found(capsys, "test sans")["candidates"][0]
    assert test_sans["family"] == "Test Sans" and test_sans["installed"]
    assert test_sans["evidence"][0] == "name 'Test Sans'"
    assert "listed in google-fonts as 'Test Sans', exact_family" in test_sans["evidence"]
    assert families(found(capsys, "바탕")) == ["Gowun Batang"]            # Korean substring of the ko name
    assert families(found(capsys, "yanghee")) == ["Gowun Batang"]         # foundry


def test_filters_narrow_with_evidence(fonts_db, capsys):
    assert families(found(capsys, "--script", "hang")) == ["Gowun Batang"]   # synthetic fonts lack 2,350 syllables
    code = found(capsys, "--role", "code")
    assert families(code) == ["Even Mono"] and "role code: monospaced (measured)" in code["candidates"][0]["evidence"]
    body = found(capsys, "--role", "body")
    names = families(body)
    assert {"Test Sans", "Contrast Serif", "Even Mono", "Pen Notes", "Plain Serif"} <= set(names)
    assert not {"Brush Hand", "Loud Display", "Only Icons"} & set(names)   # catalog hand, display; no letters
    pen = next(c for c in body["candidates"] if c["family"] == "Pen Notes")
    assert any(e.startswith("role body: text class") and e.endswith("the name suggests hand") for e in pen["evidence"])
    assert "role body: text class sans (catalog)" in next(
        c for c in body["candidates"] if c["family"] == "Test Sans")["evidence"]
    assert set(families(found(capsys, "--category", "serif"))) == {"Contrast Serif", "Pen Notes", "Plain Serif",
                                                                     "Proprietary Serif", "Weighted Serif"}
    assert families(found(capsys, "--category", "bu-ri")) == ["Gowun Batang"]
    open_serif = found(capsys, "serif", "--license", "open")
    assert "Proprietary Serif" not in families(open_serif) and "Contrast Serif" not in families(open_serif)
    web = found(capsys, "--delivery", "web", "--installed")
    assert families(web) == ["Brush Hand", "Test Sans"]                   # the installed families a catalog lists
    assert "web via google-fonts-api, self-host" in web["candidates"][0]["evidence"]
    assert len(found(capsys, "--installed", "--limit", "2")["candidates"]) == 2


def test_script_codes_are_checked_and_composites_expand(fonts_db, capsys):
    kore = found(capsys, "--script", "Kore")
    assert families(kore) == families(found(capsys, "--script", "hang")) == ["Gowun Batang"]
    assert "script kore = hang (catalog subsets)" in kore["candidates"][0]["evidence"]
    assert families(found(capsys, "--script", "kana")) == ["Mincho Test"]   # a jpan subset has kana and hani
    jpan = found(capsys, "--script", "jpan")
    assert families(jpan) == ["Mincho Test"] and "script jpan = kana + hani (catalog subsets)" in \
        jpan["candidates"][0]["evidence"]
    for code in ("ko", "deva"):
        with pytest.raises(SystemExit) as stop:
            search.main(["--script", code])
        assert stop.value.code == 2
        err = capsys.readouterr().err
        assert f"unknown script code {code!r}" in err and "latn, cyrl, grek, hang" in err and "kore = hang" in err


def rank(result: dict, name: str) -> int:
    return families(result).index(name)


def evidence(result: dict, name: str) -> list[str]:
    return next(c for c in result["candidates"] if c["family"] == name)["evidence"]


def test_role_ranks_by_the_weights_the_family_has(fonts_db, capsys):
    body = found(capsys, "--role", "body", "--installed")
    assert rank(body, "Test Sans") < rank(body, "Heavy Grotesk") and rank(body, "Test Sans") < rank(body, "Fat Regular")
    assert "regular upright face 400 (installed)" in evidence(body, "Test Sans")
    assert "no regular upright face (only 900)" in evidence(body, "Heavy Grotesk")
    assert any(e.startswith("no regular upright face: the 400 face measures bold (weight ratio 3.")
               for e in evidence(body, "Fat Regular"))              # a 400 weight class drawn heavy
    assert rank(body, "Test Sans Twin") < rank(body, "Heavy Grotesk")
    display = found(capsys, "--role", "display", "--installed")          # Test Sans Twin: one regular face only
    assert rank(display, "Heavy Grotesk") < rank(display, "Test Sans Twin")
    assert rank(display, "Fat Regular") < rank(display, "Test Sans Twin")
    assert "role display: bold face available (900)" in evidence(display, "Heavy Grotesk")

    serif = found(capsys, "--role", "body", "--category", "serif")    # unknown weights never outrank a regular
    assert rank(serif, "Weighted Serif") < min(rank(serif, "Plain Serif"), rank(serif, "Proprietary Serif"))
    assert {"regular upright face 400 (google-fonts)", "2 weights (400–700)"} <= set(
        evidence(serif, "Weighted Serif"))
    assert "weights unknown" in evidence(serif, "Plain Serif")
    sans = found(capsys, "--role", "body", "--category", "sans")
    assert "the catalog also classifies it display" in evidence(sans, "Loud Sans")
    assert rank(sans, "Loud Sans") > rank(sans, "Mincho Test")        # both catalog-only with unknown weights


def test_similar_to_ranks_installed_families_by_measured_distance(fonts_db, capsys):
    result = found(capsys, "--similar-to", "Test Sans")
    names = families(result)
    assert names[0] == "Test Sans Twin" and "Test Sans" not in names
    distances = [c["distance"] for c in result["candidates"]]
    assert distances == sorted(distances) and distances[0] == 0
    assert names.index("Contrast Serif") > names.index("Test Sans Twin")
    assert all(c["installed"] for c in result["candidates"])
    assert any("catalog-only families have no measurements" in n for n in result["notes"])
    assert result["candidates"][0]["evidence"][0].startswith("distance 0.00 to Test Sans over")
    assert search.main(["--similar-to", "Gowun Batang"]) == 2               # catalog-only: nothing measured
    assert "not an installed family" in capsys.readouterr().err


def test_empty_database_and_usage(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    result = found(capsys, "anything")
    assert result["candidates"] == [] and len(result["notes"]) == 2       # scan and sync hints
    with pytest.raises(SystemExit) as stop:
        search.main([])
    assert stop.value.code == 2
    with pytest.raises(SystemExit) as stop:
        search.main(["--type", "asset", "x"])
    assert stop.value.code == 2
    assert search.split_type(["#c0ffee", "--type=color", "--json"]) == ("color", ["#c0ffee", "--json"])
