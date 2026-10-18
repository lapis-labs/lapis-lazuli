"""lazuli search role fit and dual-script families: purpose and optical-size cuts a role contradicts, families made
for Latin and a CJK script together, and primary scripts of the catalogs beyond Google Fonts. Synthetic rows only;
nothing reaches the network."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from lazuli import db, scan, search
from lazuli.catalog import cli as catalog_cli
from lazuli.catalog import fontshare, fontsource, github_foundries, match, net, store
from lazuli.catalog.github_foundries import Account
from lazuli.catalog.store import CatalogFamily, CatalogLabel
from lazuli.measure import MEASURER_VERSION


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def no_network(url, headers):
        raise AssertionError(f"a test reached for the network: {url}")

    monkeypatch.setattr(net, "default_transport", no_network)


def source(name: str, priority: int):
    return SimpleNamespace(NAME=name, KIND="snapshot", PRIORITY=priority, TTL_DAYS=30, MIN_INTERVAL_S=3.0)


def listed(name, *, genre="sans", scripts=("latn",), weights=(400, 700), tags=(), extra=(), details=None,
           signals=None):
    """A catalog family with an OFL license, the scripts and weights given, Google-style tags, and extra labels."""
    return CatalogFamily(
        name, name, license="OFL-1.1", details=details or {}, signals=signals or {},
        labels=[CatalogLabel("genre", genre, genre), CatalogLabel("license", "OFL-1.1", "OFL-1.1"),
                *[CatalogLabel("property", s, f"script:{s}") for s in scripts],
                *[CatalogLabel("property", str(w), f"weight:{w}") for w in weights],
                *[CatalogLabel("usage", tag, None, 100.0) for tag in tags], *extra])


def install(conn, family, *, weights=(400,), coverage=None, features=(), axes=(), kind="text"):
    """An installed family: one measured face per weight, with the coverage, OpenType features, and axes given."""
    coverage = {"latin": 52} if coverage is None else coverage
    for weight in weights:
        face = conn.execute(
            "INSERT INTO local_font (path, size, mtime, family, family_norm, subfamily, coverage_json, origin, "
            "metadata_json) VALUES (?, 1, '2026-10-18', ?, ?, ?, ?, 'user', ?)",
            (f"/fonts/{family}-{weight}.otf", family, scan.norm(family), f"W{weight}", json.dumps(coverage),
             json.dumps({"axes": list(axes), "features": list(features)}))).lastrowid
        conn.execute("INSERT INTO measurement (local_font_id, measurer_version, family_kind, panose_json, cjk_json, "
                     "metrics_json, measured_at) VALUES (?, ?, ?, '{}', '{}', ?, '2026-10-18')",
                     (face, MEASURER_VERSION, kind, json.dumps({"weight_class": weight, "italic": False})))


HANGUL = {"latin": 52, "hangul_syllables": 11172}


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    conn = db.connect(tmp_path / "lazuli.db")
    yield conn
    conn.close()


def found(capsys, *argv: str) -> dict:
    limit = [] if "--limit" in argv else ["--limit", "200"]
    assert search.main([*argv, *limit, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def names(result: dict) -> list[str]:
    return [c["family"] for c in result["candidates"]]


# ------------------------------------------------------------------------------------------- role fit: cuts
def cuts_catalog(conn):
    store.replace_snapshot(conn, source("google-fonts", 10), [
        listed("Plain Sans", weights=(400, 700)),
        listed("PT Serif Caption", genre="serif"),                     # name word: a caption cut
        listed("Red Hat Text"),                                        # name word: a text cut
        listed("STIX Two Math", genre="serif"),                        # name word: math
        listed("Micro 5", genre="display"),                            # first word only: no cut
        listed("Text Me One", genre="hand"),                           # first word only: no cut
        listed("Space Mono", genre="mono"),                            # catalog class: mono
        listed("Scan Face", tags=("/Special use/Barcode",)),           # Google tag: a barcode font
        listed("Glyph Set", extra=[CatalogLabel("genre", "classification:Symbols", None)]),   # Google classification
        listed("Small Print", weights=(400, 700),
               extra=[CatalogLabel("property", "opsz 6-12", "axis:opsz")]),     # an optical-size axis for small sizes
        listed("Wide Range", weights=(400, 700),
               extra=[CatalogLabel("property", "opsz 8-144", "axis:opsz")])])
    store.replace_snapshot(conn, source("fontsource", 20), [
        CatalogFamily("wing-set", "Wing Set", labels=[CatalogLabel("genre", "icons", None),
                                                      CatalogLabel("property", "latin", "script:latn"),
                                                      CatalogLabel("license", "OFL-1.1", "OFL-1.1")])])
    conn.commit()


def test_a_small_size_cut_is_no_display_or_heading_face_and_the_name_words_count_after_the_first(database, capsys):
    cuts_catalog(database)
    for role in ("display", "heading"):
        result = found(capsys, "--role", role)
        assert not {"PT Serif Caption", "Red Hat Text", "Small Print"} & set(names(result)), role
        assert {"Plain Sans", "Micro 5", "Text Me One", "Wide Range"} <= set(names(result)), role
    note = next(n for n in found(capsys, "--role", "display")["notes"] if "cuts are left out" in n)
    assert "role display contradicts them" in note and "caption 2" in note and "text 1" in note
    assert "--include-cuts" in note


def test_a_caption_or_text_cut_is_fine_for_body_and_caption_and_says_so(database, capsys):
    cuts_catalog(database)
    caption = found(capsys, "--role", "caption")
    by_name = {c["family"]: c for c in caption["candidates"]}
    assert {"PT Serif Caption", "Red Hat Text", "Small Print"} <= set(by_name)
    assert "caption cut (name word 'caption') suits role caption" in by_name["PT Serif Caption"]["evidence"]
    assert "caption cut (optical-size axis 6-12, small sizes only) suits role caption" in \
        by_name["Small Print"]["evidence"]
    assert "PT Serif Caption" in names(found(capsys, "--role", "body"))


def test_math_symbol_barcode_and_icon_cuts_suit_no_role(database, capsys):
    cuts_catalog(database)
    gone = {"STIX Two Math", "Scan Face", "Glyph Set", "Wing Set"}
    for role in ("display", "heading", "body", "ui", "data", "code", "caption"):
        assert not gone & set(names(found(capsys, "--role", role))), role
    kept = found(capsys, "--role", "display", "--include-cuts")
    by_name = {c["family"]: c for c in kept["candidates"]}
    assert gone <= set(by_name)
    assert "math cut (name word 'math'), which role display contradicts; listed because of --include-cuts" in \
        by_name["STIX Two Math"]["evidence"]
    assert any("tag /Special use/Barcode" in e for e in by_name["Scan Face"]["evidence"])
    assert any("classification:Symbols" in e for e in by_name["Glyph Set"]["evidence"])
    assert any("category icons" in e for e in by_name["Wing Set"]["evidence"])


def test_a_mono_is_for_code_or_when_asked(database, capsys):
    cuts_catalog(database)
    for role in ("display", "heading", "body", "ui", "data", "caption"):
        assert "Space Mono" not in names(found(capsys, "--role", role)), role
    assert "Space Mono" in names(found(capsys, "--role", "code"))
    for role in ("ui", "data", "body"):
        asked = found(capsys, "--role", role, "--category", "mono")
        assert names(asked) == ["Space Mono"], role
    assert "Space Mono" in names(found(capsys, "--role", "ui", "--include-cuts"))


def test_measured_data_marks_a_math_face_a_symbol_face_and_a_small_size_axis(database, capsys):
    install(database, "Maths Face", features=("kern", "ssty"))                       # OpenType math style alternates
    install(database, "Dingbat Set", kind="symbol", coverage={"latin": 3})            # no text letters at all
    install(database, "Fine Print", axes=[{"tag": "opsz", "min": 6.0, "default": 9.0, "max": 12.0}])
    install(database, "Normal Face", features=("kern",))
    database.commit()
    for role in ("display", "body"):
        assert set(names(found(capsys, "--role", role))) == (
            {"Normal Face"} | ({"Fine Print"} if role == "body" else set())), role
    why = {c["family"]: c["evidence"] for c in found(capsys, "--role", "display", "--include-cuts")["candidates"]}
    assert any("measured: OpenType math style alternates (ssty)" in e for e in why["Maths Face"])
    assert any("measured: no text letters" in e for e in why["Dingbat Set"])
    assert any("optical-size axis 6-12, small sizes only" in e for e in why["Fine Print"])


def test_a_catalog_class_outranks_a_mono_name_word_which_decides_only_without_one(database, capsys):
    classless = CatalogFamily("Loud Mono", "Loud Mono", license="OFL-1.1", labels=[
        CatalogLabel("property", "latin", "script:latn"), CatalogLabel("license", "OFL-1.1", "OFL-1.1")])
    store.replace_snapshot(database, source("google-fonts", 10), [listed("Quiet Mono", genre="sans"), classless])
    database.commit()
    body = found(capsys, "--role", "body")
    assert "Quiet Mono" in names(body) and "Loud Mono" not in names(body)       # the catalog says sans; the name says mono
    assert names(found(capsys, "--role", "code")) == ["Loud Mono"]
    loud = found(capsys, "--role", "body", "--include-cuts")["candidates"]
    assert any("name word 'mono'" in e for c in loud if c["family"] == "Loud Mono" for e in c["evidence"])


# ------------------------------------------------------------------------------------------- dual-script families
def cjk_first(conn):
    """Installed Hangul families with the Latin alphabet in every face; Google Fonts says Korean for Plex-like ones."""
    install(conn, "Pretend Sans", weights=(100, 200, 300, 400, 500, 600, 700, 800, 900), coverage=HANGUL)
    install(conn, "Sunny Gothic", weights=(300, 500, 700), coverage=HANGUL)            # three weights: a fallback
    install(conn, "Acme Hangul", weights=(400,), coverage=HANGUL)                           # a name that adds Hangul
    install(conn, "Brush Hand KR", weights=(400, 500, 600, 700, 800, 900),
            coverage={"latin": 40, "hangul_syllables": 11172})                              # no whole alphabet
    install(conn, "Source Han Sans KR", weights=(100, 200, 300, 400, 500, 600, 700),
            coverage={**HANGUL, "han": 8000})                                               # a borrowed Latin
    install(conn, "Latin Only", weights=(400, 700))
    store.replace_snapshot(conn, source("google-fonts", 10), [
        listed("Plex Like KR", scripts=("latn", "hang"), weights=(100, 200, 300, 400, 500, 600, 700),
               details={"primary_scripts": ["kore"], "primary_basis": "primaryScript"}),
        listed("Short Batang", genre="serif", scripts=("latn", "hang"), weights=(400, 700),
               details={"primary_scripts": ["kore"], "primary_basis": "primaryScript"}),
        listed("Noto Like KR", scripts=("latn", "hang"), weights=tuple(range(100, 1000, 100)),
               details={"primary_scripts": ["kore"], "primary_basis": "primaryScript"}, signals={"is_noto": True})])
    store.replace_snapshot(conn, source("github-foundries", 22), [
        listed("Spoqa Like", scripts=("hang", "latn"), weights=(),
               details={"primary_scripts": ["hang", "latn"], "primary_basis": "registry scripts hint"}),
        listed("Han Only Mono", scripts=("hani",), weights=(), details={"primary_scripts": ["hani"]})])
    conn.commit()
    match.run(conn)


def test_a_family_whose_latin_is_a_designed_part_is_primary_for_both_scripts(database, capsys):
    cjk_first(database)
    latin = found(capsys, "--script", "latn")
    assert {"Latin Only", "Pretend Sans", "Acme Hangul", "Plex Like KR", "Spoqa Like"} <= set(names(latin))
    assert not {"Sunny Gothic", "Brush Hand KR", "Source Han Sans KR", "Short Batang", "Noto Like KR",
                "Han Only Mono"} & set(names(latin))
    by_name = {c["family"]: c for c in latin["candidates"]}
    assert by_name["Pretend Sans"]["primary_scripts"] == ["hang", "latn"]
    assert "9 upright weights (100–900) with the Latin alphabet in each" in "; ".join(by_name["Pretend Sans"]["evidence"])
    assert "adds Hangul to a Latin family" in "; ".join(by_name["Acme Hangul"]["evidence"])
    assert "7 upright weights (100–700)" in "; ".join(by_name["Plex Like KR"]["evidence"])
    assert "github-foundries registry scripts hint" in "; ".join(by_name["Spoqa Like"]["evidence"])
    note = next(n for n in latin["notes"] if "left out" in n)
    assert "not their primary script" in note and "--secondary-scripts" in note


def test_the_same_families_stay_in_the_hangul_list_and_a_fallback_latin_is_still_a_secondary_script(database, capsys):
    cjk_first(database)
    hangul = found(capsys, "--script", "hang")
    assert {"Pretend Sans", "Sunny Gothic", "Acme Hangul", "Plex Like KR", "Short Batang", "Spoqa Like"} <= \
        set(names(hangul))
    both = found(capsys, "--script", "latn", "--secondary-scripts")
    assert {"Sunny Gothic", "Short Batang", "Source Han Sans KR"} <= set(names(both))
    sunny = next(c for c in both["candidates"] if c["family"] == "Sunny Gothic")
    assert any("secondary: its primary script is hang" in e for e in sunny["evidence"])


def test_a_cjk_family_with_one_weight_and_a_deep_latin_is_not_widened_by_depth_alone(database, capsys):
    install(database, "Deep Latin Brush", weights=(400,),
            coverage={"latin": 52, "latin_ext": 300, "han": 8000, "kana": 200})
    database.commit()
    assert "Deep Latin Brush" not in names(found(capsys, "--script", "latn"))


def test_only_cjk_primaries_are_widened(database, capsys):
    store.replace_snapshot(database, source("google-fonts", 10), [
        listed("Many Weights Thai", scripts=("latn", "thai"), weights=tuple(range(100, 1000, 100)),
               details={"primary_scripts": ["thai"], "primary_basis": "primaryScript"})])
    database.commit()
    assert "Many Weights Thai" not in names(found(capsys, "--script", "latn"))


def test_two_catalogs_that_name_different_primary_scripts_for_one_family_state_both(database, capsys):
    store.replace_snapshot(database, source("google-fonts", 10), [
        listed("Twin Script", scripts=("latn", "hang"), weights=(400, 700),
               details={"primary_scripts": ["kore"], "primary_basis": "primaryScript"})])
    store.replace_snapshot(database, source("fontshare", 21), [
        listed("Twin Script", weights=(), details={"primary_scripts": ["latn"], "primary_basis": "script field"})])
    database.commit()
    latin = found(capsys, "--script", "latn")
    twin = next(c for c in latin["candidates"] if c["family"] == "Twin Script")
    assert twin["primary_scripts"] == ["kore", "latn"]
    assert any("google-fonts primaryScript, fontshare script field" in e for e in twin["evidence"])


# ------------------------------------------------------------------------------------------- primary scripts beyond Google
def fontsource_entry(id_, family, subsets, default="latin"):
    return {"id": id_, "family": family, "subsets": subsets, "weights": [400, 700], "styles": ["normal"],
            "defSubset": default, "variable": False, "category": "sans-serif", "license": "OFL-1.1", "type": "other"}


def test_fontsource_primary_script_is_a_non_latin_default_subset_or_no_latin_subset_at_all():
    entries = [fontsource_entry("khmer-face", "Khmer Face", ["khmer", "latin"], default="khmer"),
               fontsource_entry("cyr-only", "Cyr Only", ["cyrillic"]),
               fontsource_entry("korean-and-latin", "Korean And Latin", ["korean", "latin"]),
               fontsource_entry("latin-only", "Latin Only", ["latin", "latin-ext", "vietnamese"]),
               fontsource_entry("emoji-set", "Emoji Set", ["emoji"], default="emoji")]
    by_id = {f.source_key: f for f in fontsource.families_from(json.dumps(entries))}
    assert by_id["khmer-face"].details == {"primary_scripts": ["khmr"], "primary_basis": "default subset khmer"}
    assert by_id["cyr-only"].details == {"primary_scripts": ["cyrl"], "primary_basis": "no Latin subset"}
    assert by_id["korean-and-latin"].details == {}              # a Latin default is no statement: unknown stays unknown
    assert by_id["latin-only"].details == {}
    assert by_id["emoji-set"].details == {}


def fontshare_page(*entries):
    return json.dumps({"fonts": list(entries), "has_more": False})


def fontshare_entry(slug, name, script):
    return {"slug": slug, "name": name, "script": script, "category": "Sans", "license_type": "itf_ffl",
            "styles": [], "axes": [], "font_tags": []}


def test_fontshare_primary_script_is_its_script_field_when_it_names_one():
    families = {f.source_key: f for f in fontshare.families_from([fontshare_page(
        fontshare_entry("a", "A", "latin"), fontshare_entry("b", "B", None), fontshare_entry("c", "C", "unknown"))])}
    assert families["a"].details == {"primary_scripts": ["latn"], "primary_basis": "script field"}
    assert families["b"].details == {} and families["c"].details == {}


def repo(name, description="", topics=(), owner="acct"):
    return {"name": name, "full_name": f"{owner}/{name}", "description": description, "topics": list(topics),
            "fork": False, "disabled": False, "license": {"spdx_id": "OFL-1.1"},
            "html_url": f"https://github.com/{owner}/{name}"}


def github_family(account, **kwargs):
    (family,) = github_foundries.families_from([account], {account.login: [repo(**kwargs)]}, {}, {})
    return family


def scripts_of(family):
    return [lb.mapped for lb in family.labels if (lb.mapped or "").startswith("script:")]


def test_github_primary_scripts_are_what_the_repository_states_else_the_account_hint():
    han = Account("acct", "Han Foundry", ("hani",))
    korean = github_family(han, name="wenkai-kr", description="Korean Version of LXGW WenKai, a font")
    assert korean.details["primary_scripts"] == ["hang"]
    assert korean.details["primary_basis"] == "repository description or topics"
    assert scripts_of(korean) == ["script:hang", "script:hani"]           # coverage keeps the account's hint too
    latin = github_family(han, name="slab-mod", description="A Latin font derived from Slabo")
    assert latin.details["primary_scripts"] == ["latn"]
    hint = github_family(Account("acct", "Hangul Foundry", ("hang", "latn")), name="pretty-sans",
                         description="A system-ui alternative font")
    assert hint.details["primary_scripts"] == ["hang", "latn"]
    assert hint.details["primary_basis"] == "registry scripts hint"
    topic = github_family(Account("acct", "Latin Foundry", ("latn",)), name="plain-face", description="A font",
                          topics=["korean-font"])
    assert topic.details["primary_scripts"] == ["hang"]
    assert github_family(Account("acct", "Unhinted", ()), name="plain", description="A font").details.get(
        "primary_scripts") is None


def test_an_influence_phrase_names_a_model_not_a_script_the_family_covers():
    latin = Account("acct", "Velvetyne", ("latn",))
    inspired = github_family(latin, name="hangul", description="Geometric sans inspired by korean writing system.")
    assert scripts_of(inspired) == ["script:latn"] and inspired.details["primary_scripts"] == ["latn"]
    based = github_family(latin, name="greek-ish", description="A serif font based on Greek lettering, with Cyrillic")
    assert based.details["primary_scripts"] == ["cyrl"]


def test_remap_gives_fontsource_and_fontshare_rows_their_primary_scripts_with_no_request(database, capsys):
    store.ensure_source(database, fontsource)
    store.ensure_source(database, fontshare)
    entries = [fontsource_entry("khmer-face", "Khmer Face", ["khmer"], default="khmer")]
    store.save_raw(database, fontsource.NAME, "v1/fonts", json.dumps(entries).encode())
    store.save_raw(database, fontshare.NAME, "v2/fonts?offset=0",
                   fontshare_page(fontshare_entry("a", "A", "latin")).encode())
    old = fontsource.families_from(json.dumps(entries))
    old[0].details = {}                                                  # a snapshot from before the field
    store.replace_snapshot(database, fontsource, old)
    store.replace_snapshot(database, fontshare, [CatalogFamily("a", "A")])
    database.commit()
    assert catalog_cli.main(["remap", "--source", "fontsource", "fontshare"]) == 0
    out = capsys.readouterr().out
    assert "fontsource: 1 families re-mapped from kept responses, 0 requests" in out
    assert "fontshare: 1 families re-mapped from kept responses, 0 requests" in out
    stored = dict(database.execute("SELECT family, details_json FROM catalog_family").fetchall())
    assert json.loads(stored["Khmer Face"])["primary_scripts"] == ["khmr"]
    assert json.loads(stored["A"])["primary_scripts"] == ["latn"]
