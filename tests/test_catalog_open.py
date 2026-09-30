"""lazuli catalogs, open sources: Google Fonts, Fontsource, and Fontshare snapshots from recorded,
trimmed responses (tests/fixtures/catalog/<source>/). A fake transport serves them; nothing here
reaches the network, and the fake clock keeps the 3 s pace without sleeping.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazuli import db
from lazuli.catalog import fontshare, fontsource, google_fonts, net, store

FIXTURES = Path(__file__).parent / "fixtures" / "catalog"


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    def no_network(url, headers):
        raise AssertionError(f"a test reached for the network: {url}")

    fake = Clock()
    monkeypatch.setattr(net, "_clock", fake.time)
    monkeypatch.setattr(net, "_sleep", fake.sleep)
    monkeypatch.setattr(net, "_last_request", {})
    monkeypatch.setattr(net, "default_transport", no_network)
    return fake


class Site:
    """Fixture files by URL; robots.txt and anything else unknown answer 404. Logs (url, headers, time)."""

    def __init__(self, clock: Clock, pages: dict[str, str]):
        self.clock, self.pages, self.log = clock, pages, []

    def __call__(self, url: str, headers: dict) -> net.Response:
        self.log.append((url, headers, self.clock.now))
        if url not in self.pages:
            return net.Response(url, 404, {"content-type": "text/plain"}, b"not found")
        body = (FIXTURES / self.pages[url]).read_bytes()
        kind = "text/plain" if url.endswith(".csv") else "application/json"
        return net.Response(url, 200, {"content-type": f"{kind}; charset=utf-8"}, body)

    def urls(self) -> list[str]:
        return [url for url, _, _ in self.log]


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "lazuli.db")
    yield connection
    connection.close()


GOOGLE_PAGES = {
    google_fonts.METADATA_URL: "google-fonts/metadata-fonts.json",
    google_fonts.TAGS_URL: "google-fonts/families.csv",
    **{google_fonts.TREE_URL.format(d): f"google-fonts/tree-{d}.json" for d in ("ofl", "apache", "ufl")},
}


def labels_of(family, kind=None) -> list[tuple]:
    return [(lb.kind, lb.raw, lb.mapped, lb.weight) for lb in family.labels if kind is None or lb.kind == kind]


def mapped(family, kind) -> list[str]:
    return [lb.mapped for lb in family.labels if lb.kind == kind and lb.mapped is not None]


def test_google_fonts_snapshot_in_five_requests_at_human_pace(clock):
    site = Site(clock, GOOGLE_PAGES)
    fetcher = net.Fetcher(google_fonts.NAME, min_interval_s=google_fonts.MIN_INTERVAL_S, transport=site)
    families = {f.family: f for f in google_fonts.fetch(fetcher)}
    assert site.urls() == [
        "https://fonts.google.com/robots.txt", google_fonts.METADATA_URL,
        "https://api.github.com/robots.txt", google_fonts.TAGS_URL,
        *(google_fonts.TREE_URL.format(d) for d in ("ofl", "apache", "ufl"))]
    assert fetcher.requests == 7
    times = [t for _, _, t in site.log]
    assert all(later - earlier >= 3.0 for earlier, later in zip(times, times[1:]))
    assert all(h["User-Agent"].startswith("lazuli/") for _, h, _ in site.log)
    tags_headers = next(h for url, h, _ in site.log if url == google_fonts.TAGS_URL)
    assert tags_headers["Accept"] == "application/vnd.github.raw+json"          # the file, not its JSON wrapper
    assert set(families) == {"ABeeZee", "AR One Sans", "Edu SA Hand", "Nanum Myeongjo", "Roboto Slab", "Ubuntu"}
    assert all(f.fonts == [] for f in families.values())                         # no PostScript names in bulk


def test_google_fonts_maps_genres_cjk_classes_tags_scripts_and_styles(clock):
    fetcher = net.Fetcher(google_fonts.NAME, min_interval_s=3.0, transport=Site(clock, GOOGLE_PAGES))
    families = {f.family: f for f in google_fonts.fetch(fetcher)}

    myeongjo = families["Nanum Myeongjo"]
    assert myeongjo.designers == ["Example Type Studio"]
    assert myeongjo.url == "https://fonts.google.com/specimen/Nanum+Myeongjo"
    assert mapped(myeongjo, "genre") == ["serif", "bu-ri"]                      # a Korean-primary serif is 부리
    assert ("property", "korean", "script:hang", None) in labels_of(myeongjo)
    assert mapped(myeongjo, "property") == ["script:hang", "script:latn", "weight:400", "weight:700", "weight:800"]
    assert "menu" not in [lb.raw for lb in myeongjo.labels]                     # the picker subset is no coverage
    assert ("subclass", "/Serif/Old Style Garalde", None, 30.0) in labels_of(myeongjo)

    slab = families["Roboto Slab"]
    assert mapped(slab, "genre") == ["serif", "slab"]                          # category Serif, stroke Slab Serif
    assert ("property", "wght 100-900", "axis:wght", None) in labels_of(slab)
    assert ("property", "vietnamese", None, None) in labels_of(slab)            # a language, not a script

    abeezee = families["ABeeZee"]
    assert mapped(abeezee, "genre") == ["sans"]                                # stroke repeats the category once
    assert ("property", "italic", "style:italic", None) in labels_of(abeezee)
    assert ("feel", "/Expressive/Calm", None, 15.0) in labels_of(abeezee)
    assert ("usage", "/Purpose/Easy Reading", None, 35.0) in labels_of(abeezee)
    assert ("property", "/Quality/Spacing", None, 65.0) in labels_of(abeezee)
    assert all(lb.mapped is None for lb in abeezee.labels if lb.kind in ("subclass", "feel", "usage"))

    ar_one = families["AR One Sans"]
    business = [lb for lb in labels_of(ar_one, "feel") if lb[1].startswith("/Expressive/Business")]
    assert business == [("feel", "/Expressive/Business wght@400", None, 65.0),
                        ("feel", "/Expressive/Business wght@700", None, 100.0)]  # per axis position, as tagged
    assert ("property", "ARRR 10-60", "axis:ARRR", None) in labels_of(ar_one)

    assert mapped(families["Edu SA Hand"], "genre") == ["hand"]


def test_google_fonts_license_comes_from_one_repository_directory_or_none(clock):
    fetcher = net.Fetcher(google_fonts.NAME, min_interval_s=3.0, transport=Site(clock, GOOGLE_PAGES))
    families = {f.family: f for f in google_fonts.fetch(fetcher)}
    assert {name: f.license for name, f in families.items()} == {
        "ABeeZee": "OFL-1.1", "Nanum Myeongjo": "OFL-1.1", "Roboto Slab": "Apache-2.0", "Ubuntu": "UFL-1.0",
        "AR One Sans": None,             # the fixture puts its directory under both ofl/ and apache/
        "Edu SA Hand": None}             # its directory kept an older name: never guessed
    assert labels_of(families["Roboto Slab"], "license") == [("license", "apache", "Apache-2.0", None)]
    assert labels_of(families["Edu SA Hand"], "license") == []


def test_google_fonts_snapshot_is_stored_and_its_raw_payloads_rebuild_it(clock, conn):
    store.ensure_source(conn, google_fonts)
    fetcher = net.Fetcher(google_fonts.NAME, min_interval_s=3.0, conn=conn, transport=Site(clock, GOOGLE_PAGES))
    families = google_fonts.fetch(fetcher)
    assert store.replace_snapshot(conn, google_fonts, families) == 6
    raw = {key: store.load_raw(conn, google_fonts.NAME, key).decode()
           for key in ("metadata/fonts", "tags/all/families.csv", "trees/ofl", "trees/apache", "trees/ufl")}
    rebuilt = google_fonts.families_from(raw["metadata/fonts"], raw["tags/all/families.csv"],
                                         {d: json.loads(raw[f"trees/{d}"]) for d in ("ofl", "apache", "ufl")})
    assert rebuilt == families
    row = conn.execute("SELECT * FROM catalog_family WHERE family = 'Nanum Myeongjo'").fetchone()
    assert (row["family_norm"], row["license"]) == ("nanummyeongjo", "OFL-1.1")
    assert [r["family"] for r in store.search(conn, "Old Style Garalde")] == ["Nanum Myeongjo"]


def test_fontsource_snapshot_in_one_request_maps_category_license_and_subsets(clock, conn):
    site = Site(clock, {fontsource.LIST_URL: "fontsource/v1-fonts.json"})
    store.ensure_source(conn, fontsource)
    fetcher = net.Fetcher(fontsource.NAME, min_interval_s=fontsource.MIN_INTERVAL_S, conn=conn, transport=site)
    families = {f.source_key: f for f in fontsource.fetch(fetcher)}
    assert site.urls() == ["https://api.fontsource.org/robots.txt", fontsource.LIST_URL]
    assert store.load_raw(conn, fontsource.NAME, "v1/fonts") is not None

    dot = families["42dot-sans"]
    assert (dot.family, dot.license, dot.url) == ("42dot Sans", "OFL-1.1", "https://fontsource.org/fonts/42dot-sans")
    assert labels_of(dot, "genre") == [("genre", "sans-serif", "sans", None)]
    assert mapped(dot, "property")[:2] == ["script:hang", "script:latn"]
    assert ("property", "variable", None, None) in labels_of(dot)
    assert dot.fonts == [] and dot.designers == []

    assert families["comic-mono"].license == "free-other"                      # MIT: free, none of the named licenses
    assert labels_of(families["comic-mono"], "license") == [("license", "mit", "free-other", None)]
    assert labels_of(families["dseg7-classic"], "genre") == [("genre", "other", None, None)]
    assert ("property", "italic", "style:italic", None) in labels_of(families["abeezee"])
    assert "Pretendard" in [f.family for f in families.values()]               # `other` families too


def test_fontshare_pages_until_has_more_ends_and_keeps_each_family_once(clock, conn):
    first = fontshare.LIST_URL + "?offset=0&limit=100"
    second = fontshare.LIST_URL + "?offset=100&limit=100"
    site = Site(clock, {first: "fontshare/v2-fonts-offset-0.json", second: "fontshare/v2-fonts-offset-100.json"})
    store.ensure_source(conn, fontshare)
    fetcher = net.Fetcher(fontshare.NAME, min_interval_s=fontshare.MIN_INTERVAL_S, conn=conn, transport=site)
    families = fontshare.fetch(fetcher)
    assert site.urls() == ["https://api.fontshare.com/robots.txt", first, second]
    assert [f.source_key for f in families] == ["kihim", "general-sans", "aktura", "dancing-script"]
    by = {f.source_key: f for f in families}

    kihim = by["kihim"]
    assert (kihim.license, kihim.foundry, kihim.designers) == (
        "ITF Free Font License", "Example Type Foundry", ["Example Designer One"])
    assert kihim.url == "https://www.fontshare.com/fonts/kihim"
    assert labels_of(kihim, "license") == [("license", "itf_ffl", "free-other", None)]
    assert [(lb.kind, lb.raw) for lb in kihim.labels if lb.kind in ("usage", "feel")] == [
        ("usage", "Signage"), ("usage", "Menus"), ("feel", "Bold"), ("usage", "Labels")]

    general = by["general-sans"]
    assert mapped(general, "property") == ["script:latn", "weight:200", "weight:300", "weight:400", "weight:500",
                                            "weight:600", "weight:700", "style:italic", "axis:wght"]
    assert ("property", "English, French, German, Spanish", None, None) in labels_of(general)

    assert labels_of(by["aktura"], "genre") == [("genre", "Serif", "serif", None), ("genre", "Blackletter", None, None),
                                                ("genre", "Display", "display", None)]
    script = by["dancing-script"]
    assert (script.license, script.foundry) == ("OFL-1.1", None)
    assert labels_of(script, "genre") == [("genre", "Script", "hand", None)]
    assert ("feel", "soft", None, None) in labels_of(script)
    assert [store.load_raw(conn, fontshare.NAME, f"v2/fonts?offset={o}") is not None for o in (0, 100)] == [True, True]


def test_fontshare_stops_when_a_page_brings_no_new_family(clock):
    same = fontshare.LIST_URL + "?offset={}&limit=100"
    pages = {same.format(offset): "fontshare/v2-fonts-offset-0.json" for offset in (0, 100, 200)}  # has_more: true
    site = Site(clock, pages)
    families = fontshare.fetch(net.Fetcher(fontshare.NAME, min_interval_s=3.0, transport=site))
    assert len(site.urls()) == 3                                               # robots.txt and two pages
    assert [f.source_key for f in families] == ["kihim", "general-sans", "aktura"]


def test_fontshare_native_name_in_hangul_or_kana_is_the_cjk_name():
    def page(native):
        return json.dumps({"has_more": False, "fonts": [{"slug": "x", "name": "X", "native_name": native}]})

    assert fontshare.families_from([page("가나 산스")])[0].names_i18n == {"ko": "가나 산스"}
    assert fontshare.families_from([page("かなサンス")])[0].names_i18n == {"ja": "かなサンス"}
    assert fontshare.families_from([page("हिन्दी")])[0].names_i18n == {}          # no CJK language to name
