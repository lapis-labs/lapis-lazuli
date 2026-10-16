"""How familiar a catalog says each family is: the Google Fonts popularity fields stored, re-mapped from kept
responses, and used by `lazuli search --by-familiarity`. Fixtures are the trimmed responses of
tests/fixtures/catalog (the popularity values in them are synthetic); nothing here reaches the network."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lazuli import db, search
from lazuli.catalog import cli as catalog_cli
from lazuli.catalog import google_fonts, net, store
from lazuli.catalog.store import CatalogFamily, CatalogLabel

FIXTURES = Path(__file__).parent / "fixtures" / "catalog" / "google-fonts"
RAW = {"metadata/fonts": "metadata-fonts.json", "tags/all/families.csv": "families.csv",
       **{f"trees/{d}": f"tree-{d}.json" for d in ("ofl", "apache", "ufl")}}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def no_network(url, headers):
        raise AssertionError(f"a test reached for the network: {url}")

    monkeypatch.setattr(net, "default_transport", no_network)


def fixture_families() -> list[CatalogFamily]:
    return google_fonts.families_from((FIXTURES / "metadata-fonts.json").read_text(),
                                      (FIXTURES / "families.csv").read_text(),
                                      {d: json.loads((FIXTURES / f"tree-{d}.json").read_text())
                                       for d in ("ofl", "apache", "ufl")})


def source(name: str, priority: int, kind: str = "snapshot"):
    return SimpleNamespace(NAME=name, KIND=kind, PRIORITY=priority, TTL_DAYS=30, MIN_INTERVAL_S=3.0)


def test_google_popularity_and_dates_are_kept_with_the_rank_direction_stated():
    families = {f.family: f for f in fixture_families()}
    assert families["ABeeZee"].signals == {
        "popularity": 107, "popularity_kind": "rank", "trending": 1111, "date_added": "2016-01-01",
        "last_modified": "2024-01-15", "is_noto": False, "is_brand_font": False}
    assert families["Roboto Slab"].signals["is_brand_font"] is True
    # a lower number is more popular: the listing's own order for the same families
    assert [f.family for f in sorted(families.values(), key=lambda f: f.signals["popularity"])] == [
        "ABeeZee", "AR One Sans", "Edu SA Hand", "Nanum Myeongjo", "Roboto Slab", "Ubuntu"]


def test_a_listing_without_the_fields_keeps_no_signals():
    listing = json.dumps({"familyMetadataList": [{"family": "Bare Sans", "category": "Sans Serif"}]})
    (family,) = google_fonts.families_from(listing, "", {})
    assert family.signals == {}


def test_signals_reach_the_database_and_a_remap_fills_rows_synced_before_them(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    conn = db.connect(tmp_path / "lazuli.db")
    store.ensure_source(conn, google_fonts)
    for key, name in RAW.items():
        store.save_raw(conn, google_fonts.NAME, key, (FIXTURES / name).read_bytes())
    old = fixture_families()
    for family in old:
        family.signals = {}                                      # a snapshot from before the signals were stored
    store.replace_snapshot(conn, google_fonts, old)
    conn.execute("UPDATE source SET fetched_at = '2026-09-01T00:00:00+00:00' WHERE name = 'google-fonts'")
    conn.commit()

    def stored(name):
        return conn.execute("SELECT signals_json FROM catalog_family WHERE family = ?", (name,)).fetchone()[0]

    assert stored("ABeeZee") is None
    assert catalog_cli.main(["remap"]) == 0
    out = capsys.readouterr().out
    assert "google-fonts: 6 families re-mapped from kept responses, 0 requests" in out
    assert json.loads(stored("ABeeZee"))["popularity"] == 107
    assert conn.execute("SELECT fetched_at FROM source WHERE name = 'google-fonts'").fetchone()[0] == \
        "2026-09-01T00:00:00+00:00"                              # no request was sent, so the snapshot is no fresher
    conn.close()


def test_remap_says_when_nothing_was_kept(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    conn = db.connect(tmp_path / "lazuli.db")
    store.replace_snapshot(conn, google_fonts, fixture_families())
    conn.close()
    assert catalog_cli.main(["remap"]) == 0
    assert "no kept responses to re-map; run `lazuli catalog sync --source google-fonts`" in capsys.readouterr().out
    assert catalog_cli.main(["remap", "--source", "fontshare"]) == 2


# ---------------------------------------------------------------------------------------------- search
RANKS = [2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987, 1597, 2584]      # sixteen families, with gaps
LETTERS = "ABCDEFGHIJKLMNOP"


def listed(name, signals=None, *, script="latn", license_id="OFL-1.1"):
    return CatalogFamily(name, name, signals=signals or {}, license=license_id,
                         labels=[CatalogLabel("genre", "Sans Serif", "sans"),
                                 CatalogLabel("property", script, f"script:{script}"),
                                 CatalogLabel("license", license_id, license_id)])


@pytest.fixture
def catalogs(tmp_path, monkeypatch, capsys):
    """Google Fonts ranks Sample A..P (A most popular) and Quiet Hangul; Fontsource lists Sample B again without
    a rank and Mystery Grotesk, which nobody ranks; 안심글꼴 has a chart family and an unlisted one."""
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    conn = db.connect(tmp_path / "lazuli.db")
    rank = lambda n: {"popularity": n, "popularity_kind": "rank"}                   # noqa: E731
    store.replace_snapshot(conn, source("google-fonts", 10), [
        *[listed(f"Sample {letter}", rank(n)) for letter, n in zip(LETTERS, RANKS)],
        listed("Quiet Hangul", rank(3000), script="hang")])
    store.replace_snapshot(conn, source("fontsource", 20), [listed("Sample B"), listed("Mystery Grotesk")])
    chart = {"popularity": 4, "popularity_kind": "chart", "popularity_list": "인기글꼴 TOP20"}
    store.replace_snapshot(conn, source("anshim", 40), [
        listed("차트 고딕", chart, script="hang", license_id="custom-free"),
        listed("조용한 바탕", None, script="hang", license_id="custom-free")])
    conn.close()
    capsys.readouterr()


def ran(capsys, *argv: str) -> dict:
    assert search.main([*argv, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def tiers(result: dict) -> dict[str, str]:
    return {c["family"]: c["familiarity"]["tier"] for c in result["candidates"]}


def test_the_top_quarter_of_the_ranking_is_familiar_by_position_and_the_rest_less_known(catalogs, capsys):
    result = ran(capsys, "--script", "latn", "--limit", "20")
    by_name = {c["family"]: c["familiarity"] for c in result["candidates"]}
    assert [n for n, f in by_name.items() if f["tier"] == "familiar"] == [f"Sample {x}" for x in "ABCD"]
    assert by_name["Sample D"] == {"tier": "familiar", "source": "google-fonts", "rank": 8, "position": 4, "of": 17,
                                   "basis": "google-fonts popularity 8 (position 4 of 17)"}
    assert by_name["Sample E"]["tier"] == "less-known" and by_name["Sample E"]["rank"] == 13
    assert by_name["Sample P"]["position"] == 16 and by_name["Sample P"]["tier"] == "less-known"


def test_by_familiarity_puts_a_less_known_candidate_beside_the_familiar_ones(catalogs, capsys):
    plain = ran(capsys, "--script", "latn", "--limit", "4")
    assert set(tiers(plain).values()) == {"familiar"}               # the ordinary order lists only well-known faces
    mixed = ran(capsys, "--script", "latn", "--limit", "4", "--by-familiarity")
    # half the slots each: the two most popular familiar, and of the less-known the least popular first
    assert list(tiers(mixed).items()) == [("Sample A", "familiar"), ("Sample B", "familiar"),
                                          ("Sample P", "less-known"), ("Sample O", "less-known")]
    assert any(n.startswith("familiarity of all") and "familiar 4, less-known 12, unknown 1" in n
               for n in mixed["notes"])


def test_a_family_in_two_catalogs_takes_the_rank_the_other_one_states(catalogs, capsys):
    result = ran(capsys, "sample b")
    (sample_b,) = [c for c in result["candidates"] if c["family"] == "Sample B"]
    assert [c["source"] for c in sample_b["catalogs"]] == ["google-fonts", "fontsource"]
    assert sample_b["familiarity"]["tier"] == "familiar" and sample_b["familiarity"]["rank"] == 3


def test_a_family_nobody_ranks_is_unknown_and_never_called_less_known(catalogs, capsys):
    result = ran(capsys, "mystery")
    assert tiers(result) == {"Mystery Grotesk": "unknown"}
    assert result["candidates"][0]["familiarity"] == {"tier": "unknown"}
    korean = ran(capsys, "--script", "hang", "--by-familiarity")
    assert tiers(korean) == {"차트 고딕": "familiar", "Quiet Hangul": "less-known", "조용한 바탕": "unknown"}
    assert korean["candidates"][0]["familiarity"]["basis"] == "anshim 인기글꼴 TOP20 no. 4"
    assert [c["family"] for c in korean["candidates"]] == ["차트 고딕", "Quiet Hangul", "조용한 바탕"]   # unknown listed apart


def test_text_output_groups_by_tier_and_says_unknown_is_not_obscure(catalogs, capsys):
    assert search.main(["--script", "hang", "--by-familiarity"]) == 0
    out = capsys.readouterr().out
    assert out.index("familiar (top quarter") < out.index("less-known (ranked below") < out.index("unknown familiarity")
    assert "not the same as obscure" in out
    assert "familiarity less-known (google-fonts popularity 3000 (position 17 of 17))" in out


def test_by_familiarity_needs_two_slots(catalogs, capsys):
    with pytest.raises(SystemExit) as exit_info:
        search.main(["--script", "latn", "--limit", "1", "--by-familiarity"])
    assert exit_info.value.code == 2
    assert "--limit 2 or more" in capsys.readouterr().err


def test_a_name_that_two_ranked_families_share_says_nothing():
    rows = [{"source": "google-fonts", "source_key": key, "family": "Twin Sans", "names_i18n_json": None,
             "signals_json": json.dumps({"popularity": n, "popularity_kind": "rank"})}
            for key, n in (("Twin Sans", 2), ("TwinSans", 900))]
    familiarity = search.Familiarity(rows)
    assert familiarity.of([], ["Twin Sans"]) == {"tier": "unknown"}
    (only,) = [row for row in rows if row["source_key"] == "Twin Sans"]
    single = search.Familiarity([only, {**rows[1], "family": "Other Sans", "source_key": "Other"}])
    assert single.of([], ["twin-sans"])["basis"].startswith("by name, 'Twin Sans': google-fonts popularity 2")
