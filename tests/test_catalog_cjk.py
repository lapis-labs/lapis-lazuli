"""lazuli catalogs, Korean and CJK sources: the 안심글꼴 lists (anshim) and Sandoll Cloud lookups from
fixtures shaped like the live pages, and the two sources whose terms forbid tools (adobe-cjk, noonnu),
which refuse without sending a request.

Nothing here reaches the network: every Fetcher gets a fake transport, and the default transport
fails the test if anything falls through to it.
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import pytest

from lazuli import db, search
from lazuli.catalog import adobe_cjk, anshim, net, noonnu, sandoll, store
from lazuli.catalog.store import CatalogLabel

FIXTURES = Path(__file__).parent / "fixtures" / "catalog"


class Clock:
    def __init__(self):
        self.now = 1_000.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
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
    """A fake transport: fixed pages by URL, 404 for the rest, and a log of (url, clock time)."""

    def __init__(self, clock: Clock, pages: dict[str, str]):
        self.clock, self.pages, self.log = clock, pages, []

    def __call__(self, url: str, headers: dict) -> net.Response:
        self.log.append((url, self.clock.now))
        if url not in self.pages:
            return net.Response(url, 404, {"content-type": "text/plain"}, b"not found")
        kind = "text/plain" if url.endswith(".txt") else "text/html"
        return net.Response(url, 200, {"content-type": f"{kind};charset=UTF-8"}, self.pages[url].encode())

    def urls(self) -> list[str]:
        return [url for url, _ in self.log]


def page(source: str, name: str) -> str:
    return (FIXTURES / source / name).read_text(encoding="utf-8")


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "lazuli.db")
    yield connection
    connection.close()


# ------------------------------------------------------------------------------------------ anshim
PUBLIC, PRIVATE = anshim.BASE + "/freeFontEvent_KOGL.html", anshim.BASE + "/freeFontEvent.html"
BOARD = anshim.BASE + "/gongu/bbs/B0000018/list.do?menuNo=20019&bbsSeCd={}&pageIndex={}"
CHART = BOARD.format("01", 1)
FREE_1, FREE_2 = BOARD.format("04", 1), BOARD.format("04", 2)


def anshim_site(clock, **pages) -> Site:
    return Site(clock, {anshim.BASE + "/robots.txt": page("anshim", "robots.txt"),
                        PUBLIC: page("anshim", "freeFontEvent_KOGL.html"),
                        PRIVATE: page("anshim", "freeFontEvent.html"),
                        CHART: page("anshim", "board-01.html"),
                        FREE_1: page("anshim", "board-04-p1.html"), FREE_2: page("anshim", "board-04-p2.html"), **pages})


def test_anshim_lists_families_with_their_license_holder_and_work_page(clock, conn):
    store.ensure_source(conn, anshim)
    site = anshim_site(clock)
    families = anshim.fetch(net.Fetcher(anshim.NAME, min_interval_s=anshim.MIN_INTERVAL_S, conn=conn, transport=site))
    by_family = {f.family: f for f in families}
    # Weights fold into one family; the commented-out entry and the download-everything button are not fonts
    assert set(by_family) == {
        "생거진천체", "경기천년바탕체", "달서힐링체", "KoPub World돋움체", "전주완퐌본체 각", "전주완퐌본체 순",
        "Mapo마포나루", "KCC손기정체", "김정철고딕체", "가비아납작블럭체", "나눔스퀘어 라운드", "60's STRIPE", "I AM PLAYER",
        # the free-font board and the chart add these
        "샘플 드림체", "조건없는체", "Sample Latin Face", "예시 둥근체", "예시 문체체", "예시 손글씨체"}

    public = by_family["경기천년바탕체"]
    assert (public.license, public.foundry, public.names_i18n) == ("KOGL-1", "경기도", {"ko": "경기천년바탕체"})
    assert public.url == "https://gongu.copyright.or.kr/gongu/wrt/wrt/view.do?wrtSn=13288409&menuNo=200195"
    assert public.labels == [CatalogLabel("license", anshim.PAGES[0][1], "KOGL-1"),
                             CatalogLabel("property", "name in Hangul", "script:hang")]
    assert by_family["KoPub World돋움체"].foundry == "한국출판인회의"              # the organizations' credit is not the name
    private = by_family["KCC손기정체"]
    assert (private.license, private.foundry) == ("OFL-1.1", "한국저작권위원회")
    assert [label.mapped for label in private.labels] == ["OFL-1.1", "script:hang"]
    assert by_family["60's STRIPE"].names_i18n == {} and by_family["60's STRIPE"].labels[-1].kind == "license"   # no Hangul

    assert site.urls() == [anshim.BASE + "/robots.txt", PUBLIC, PRIVATE, CHART, FREE_1, FREE_2]
    assert store.load_raw(conn, "anshim", "freeFontEvent_KOGL.html") == page("anshim", "freeFontEvent_KOGL.html").encode()
    assert store.load_raw(conn, "anshim", "B0000018-04-p2.html") == page("anshim", "board-04-p2.html").encode()
    assert store.replace_snapshot(conn, anshim, families) == 19


def test_anshim_never_turns_a_changed_page_into_an_empty_snapshot(clock):
    site = anshim_site(clock, **{PUBLIC: "<html><body><p>점검 중입니다</p></body></html>"})
    with pytest.raises(ValueError, match="no fonts found at .*freeFontEvent_KOGL.html"):
        anshim.fetch(net.Fetcher(anshim.NAME, min_interval_s=anshim.MIN_INTERVAL_S, transport=site))


def fetched(clock, **pages) -> dict[str, "store.CatalogFamily"]:
    site = anshim_site(clock, **pages)
    families = anshim.fetch(net.Fetcher(anshim.NAME, min_interval_s=anshim.MIN_INTERVAL_S, transport=site))
    return {f.family: f for f in families}


def test_anshim_board_conditions_are_kept_verbatim_as_custom_free_and_never_mapped_to_a_named_license(clock):
    by_family = fetched(clock)
    dream = by_family["샘플 드림체"]                       # the R and B files are one family; the first one's text stays
    assert dream.license == "custom-free" and dream.foundry == "샘플마트"
    conditions = ("누구나 상업적 용도로 무료로 쓸 수 있어요\n수정과 판매는 할 수 없고, 내려받은 모양 그대로 써야 해요\n"
                  "CI, BI 제작은 안 돼요")                  # one line per <br/>; the page's close button is no text of it
    assert dream.labels[0] == CatalogLabel("license", conditions, "custom-free")
    assert dream.url == "https://provider.example.test/dream"          # the provider's own page
    assert dream.details == {"conditions_url": FREE_1}                # where the text was read
    assert dream.names_i18n == {"ko": "샘플 드림체"} and dream.labels[-1] == CatalogLabel("property", "name in Hangul", "script:hang")
    # text that names the OFL is still the listing's own sentence, not the OFL
    hand = by_family["예시 손글씨체"]
    assert hand.license == "custom-free" and hand.labels[0].mapped == "custom-free"
    assert hand.labels[0].raw == "OFL (Open Font License) 이라고 적혀 있어도 이 줄은 안내 문구일 뿐이에요\n재배포는 제공처에 물어보세요"
    assert by_family["예시 둥근체"].details == {"conditions_url": FREE_2}
    # an entry with no conditions has no license: unknown stays unknown
    bare = by_family["조건없는체"]
    assert bare.license is None and bare.details == {} and [lb.kind for lb in bare.labels] == ["property"]
    assert by_family["Sample Latin Face"].labels == [CatalogLabel("license", "개인 프로젝트에만 쓸 수 있어요", "custom-free")]


def test_anshim_chart_gives_familiarity_by_position_and_keeps_the_license_pages_license(clock):
    by_family = fetched(clock)
    chart = {"popularity_kind": "chart", "popularity_list": "인기글꼴 TOP20"}
    assert by_family["경기천년바탕체"].signals == {"popularity": 1, **chart}          # "경기천년바탕체 B" is the file
    assert by_family["경기천년바탕체"].license == "KOGL-1"                            # the license page decides, not the chart
    assert by_family["KCC손기정체"].signals == {"popularity": 2, **chart} and by_family["KCC손기정체"].license == "OFL-1.1"
    only = by_family["예시 문체체"]                        # on the chart only: its conditions are the chart's text
    assert only.signals == {"popularity": 3, **chart} and only.license == "custom-free"
    assert only.labels[0].raw == "출처를 적어 주세요\n글꼴 자체를 판매하지 마세요\n무단으로 나눠 주지 마세요"
    assert only.details == {"conditions_url": CHART}
    assert by_family["예시 손글씨체"].signals["popularity"] == 4
    assert by_family["샘플 드림체"].signals == {}               # not on the chart: nothing is said about how familiar it is
    assert by_family["달서힐링체"].signals == {}


def test_anshim_follows_the_pager_politely(clock):
    site = anshim_site(clock)
    anshim.fetch(net.Fetcher(anshim.NAME, min_interval_s=anshim.MIN_INTERVAL_S, transport=site))
    assert site.urls()[-3:] == [CHART, FREE_1, FREE_2]
    times = [moment for _, moment in site.log]
    assert all(later - earlier >= 3 for earlier, later in zip(times, times[1:]))


@pytest.mark.parametrize("broken", [CHART, FREE_1])
def test_anshim_never_turns_a_changed_board_into_an_empty_snapshot(clock, broken):
    site = anshim_site(clock, **{broken: "<html><body><p>점검 중입니다</p></body></html>"})
    with pytest.raises(ValueError, match="no fonts found at .*B0000018"):
        anshim.fetch(net.Fetcher(anshim.NAME, min_interval_s=anshim.MIN_INTERVAL_S, transport=site))


def test_search_shows_a_custom_free_listing_conditions_and_never_calls_it_open(clock, conn, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    store.replace_snapshot(conn, anshim, list(fetched(clock).values()))
    assert search.main(["--script", "hang", "--limit", "30", "--json"]) == 0
    found = {c["family"]: c for c in json.loads(capsys.readouterr().out)["candidates"]}
    dream = found["샘플 드림체"]
    assert dream["license"]["id"] == "custom-free"
    line = next(e for e in dream["evidence"] if e.startswith("license custom-free"))
    assert "수정과 판매는 할 수 없고, 내려받은 모양 그대로 써야 해요" in line and FREE_1 in line and "not an open license" in line
    assert dream["catalogs"][0]["details"] == {"conditions_url": FREE_1}
    assert found["경기천년바탕체"]["license"]["id"] == "KOGL-1"
    assert search.main(["--script", "hang", "--license", "open", "--limit", "30", "--json"]) == 0
    open_only = {c["family"] for c in json.loads(capsys.readouterr().out)["candidates"]}
    assert "경기천년바탕체" in open_only and "KCC손기정체" in open_only
    assert not open_only & {"샘플 드림체", "예시 문체체", "예시 손글씨체"}


# ----------------------------------------------------------------------------------------- sandoll
def sandoll_site(clock, query: str, family_path: str | None = None, fixture: str | None = None) -> Site:
    pages = {sandoll.BASE + "/robots.txt": page("sandoll", "robots.txt"),
             f"{sandoll.SEARCH_URL}?{urllib.parse.urlencode({'commonSearch': query})}": page("sandoll", "search.html")}
    if family_path:
        pages[sandoll.BASE + family_path] = page("sandoll", fixture)
    return Site(clock, pages)


def sandoll_fetcher(site: Site) -> net.Fetcher:
    return net.Fetcher(sandoll.NAME, min_interval_s=sandoll.MIN_INTERVAL_S, transport=site)


def test_sandoll_takes_only_the_result_whose_name_matches_and_keeps_ten_seconds(clock):
    site = sandoll_site(clock, "Sandoll GothicNeo1", "/font/8/Sandoll-GothicNeo1", "font-8.html")
    family = sandoll.lookup(sandoll_fetcher(site), "Sandoll GothicNeo1")
    # "A1" comes first and "Sandoll GothicNeo1Unicode" is close; neither is taken
    assert (family.source_key, family.family, family.names_i18n) == ("font/8", "Sandoll GothicNeo1", {"ko": "Sandoll 고딕Neo1"})
    assert (family.foundry, family.designers) == ("Sandoll", ["권경석", "이도경"])
    assert family.url == "https://www.sandollcloud.com/font/8/Sandoll-GothicNeo1"
    assert family.license == "commercial"
    assert family.labels == [CatalogLabel("genre", "Sans", "sans"), CatalogLabel("genre", "민부리", "min-bu-ri"),
                             CatalogLabel("license", "유료폰트: 산돌구름 이용권 (산돌 베이직)", "commercial")]
    assert [url.split("?")[0] for url in site.urls()] == [
        sandoll.BASE + "/robots.txt", sandoll.SEARCH_URL, sandoll.BASE + "/font/8/Sandoll-GothicNeo1"]
    times = [moment for _, moment in site.log]
    assert all(later - earlier >= 10 for earlier, later in zip(times, times[1:]))


def test_sandoll_free_fonts_are_ofl_only_when_marked(clock):
    site = sandoll_site(clock, "Gothic A1", "/free-font/17559/Gothic-A1", "free-font-17559.html")
    ofl = sandoll.lookup(sandoll_fetcher(site), "Gothic A1")
    assert (ofl.source_key, ofl.license, ofl.foundry, ofl.names_i18n) == ("free-font/17559", "OFL-1.1", "(주)한양정보통신", {})
    assert ofl.labels[-1] == CatalogLabel("license", "무료폰트: OFL, 상업용, 임베딩, 로고•CI", "OFL-1.1")

    # A Korean name is what the catalog lists first, so the search uses it
    site = sandoll_site(clock, "견본 둥근체", "/free-font/99001/Sample-Round", "free-font-99001.html")
    other = sandoll.lookup(sandoll_fetcher(site), "SampleRound", names_i18n={"ko": "견본 둥근체"})
    assert (other.family, other.names_i18n, other.foundry, other.designers) == (
        "Sample Round", {"ko": "견본 둥근체"}, "견본 글꼴 공방", ["김견본"])
    assert other.license == "free-other"
    assert other.labels == [
        CatalogLabel("genre", "Sans", "sans"),
        CatalogLabel("genre", "둥근 민부리", "min-bu-ri"), CatalogLabel("subclass", "둥근 민부리", "min-bu-ri.rounded"),
        CatalogLabel("genre", "심볼"),                                             # no sound mapping: raw only
        CatalogLabel("license", "무료폰트: 상업용, 임베딩; BI/CI 사용 불가", "free-other")]


def test_sandoll_miss_stops_after_the_search(clock):
    site = sandoll_site(clock, "Sandoll GothicNeo")
    assert sandoll.lookup(sandoll_fetcher(site), "Sandoll GothicNeo") is None
    assert [url.split("?")[0] for url in site.urls()] == [sandoll.BASE + "/robots.txt", sandoll.SEARCH_URL]


NO_RESULTS = "<html><body><div id=\"contents-all\"><p>검색 결과가 없습니다</p></div></body></html>"


def search_url(query: str) -> str:
    return f"{sandoll.SEARCH_URL}?{urllib.parse.urlencode({'commonSearch': query})}"


def test_sandoll_searches_the_english_name_when_the_korean_search_finds_nothing(clock):
    # The installed name table lists a Korean family name the catalog spells differently, so the
    # Korean search finds nothing; the English family name from the same table finds the family
    site = Site(clock, {sandoll.BASE + "/robots.txt": page("sandoll", "robots.txt"),
                        search_url("산돌고딕 네오1"): NO_RESULTS,
                        search_url("Sandoll GothicNeo1"): page("sandoll", "search.html"),
                        sandoll.BASE + "/font/8/Sandoll-GothicNeo1": page("sandoll", "font-8.html")})
    family = sandoll.lookup(sandoll_fetcher(site), "Sandoll GothicNeo1", names_i18n={"ko": "산돌고딕 네오1"})
    assert (family.source_key, family.family) == ("font/8", "Sandoll GothicNeo1")
    assert site.urls() == [sandoll.BASE + "/robots.txt", search_url("산돌고딕 네오1"),
                           search_url("Sandoll GothicNeo1"), sandoll.BASE + "/font/8/Sandoll-GothicNeo1"]
    times = [moment for _, moment in site.log]
    assert all(later - earlier >= 10 for earlier, later in zip(times, times[1:]))


def test_sandoll_adopts_only_an_exact_name_from_either_search(clock):
    # A Korean hit is taken without the English search
    site = Site(clock, {sandoll.BASE + "/robots.txt": page("sandoll", "robots.txt"),
                        search_url("견본 둥근체"): page("sandoll", "search.html"),
                        sandoll.BASE + "/free-font/99001/Sample-Round": page("sandoll", "free-font-99001.html")})
    assert sandoll.lookup(sandoll_fetcher(site), "SampleRound", names_i18n={"ko": "견본 둥근체"}).source_key == \
        "free-font/99001"
    assert search_url("SampleRound") not in site.urls()

    # Both searches list only near names ("Sandoll GothicNeo1", "...Unicode"): nothing is adopted
    site = Site(clock, {sandoll.BASE + "/robots.txt": page("sandoll", "robots.txt"),
                        search_url("산돌 고딕Neo"): page("sandoll", "search.html"),
                        search_url("Sandoll GothicNeo"): page("sandoll", "search.html")})
    assert sandoll.lookup(sandoll_fetcher(site), "Sandoll GothicNeo", names_i18n={"ko": "산돌 고딕Neo"}) is None
    assert site.urls() == [sandoll.BASE + "/robots.txt", search_url("산돌 고딕Neo"), search_url("Sandoll GothicNeo")]

    # A Korean name equal to the English one after normalization is searched once
    site = Site(clock, {sandoll.BASE + "/robots.txt": page("sandoll", "robots.txt"),
                        search_url("AppleGothic"): NO_RESULTS})
    assert sandoll.lookup(sandoll_fetcher(site), "AppleGothic", names_i18n={"ko": "AppleGothic"}) is None
    assert site.urls() == [sandoll.BASE + "/robots.txt", search_url("AppleGothic")]


# ------------------------------------------------------------------------ sources that refuse tools
def test_sources_whose_terms_forbid_tools_refuse_without_a_request(clock):
    site = Site(clock, {})
    with pytest.raises(net.Blocked, match=r"section 6\.18") as adobe:
        adobe_cjk.fetch(net.Fetcher(adobe_cjk.NAME, min_interval_s=adobe_cjk.MIN_INTERVAL_S, transport=site))
    assert "https://fonts.adobe.com/fonts" in adobe.value.reason

    with pytest.raises(net.Blocked, match="제7조") as refused:
        noonnu.lookup(net.Fetcher(noonnu.NAME, min_interval_s=noonnu.MIN_INTERVAL_S, transport=site),
                      "NanumGothic", names_i18n={"ko": "나눔고딕"})
    assert refused.value.reason.endswith("https://noonnu.cc/index?search=%EB%82%98%EB%88%94%EA%B3%A0%EB%94%95")
    assert site.log == []
