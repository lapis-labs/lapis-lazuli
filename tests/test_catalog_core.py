"""lazuli catalogs, core: polite fetching, the catalog store and search, matching, label priority,
the bundled system-fonts table, and `lazuli catalog sync|lookup|status` against fake adapters.

Nothing here reaches the network: every Fetcher gets a fake transport, and the default transport
fails the test if anything falls through to it.
"""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from lazuli import catalog, cli, db, scan
from lazuli.catalog import labels, match, net, store, system_table
from lazuli.catalog.store import CatalogFamily, CatalogFont, CatalogLabel
from synthetic_fonts import build
REAL_TRANSPORT = net.default_transport

FIXTURES = Path(__file__).parent / "fixtures" / "catalog" / "core"


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
    """A fake transport: fixed pages by URL, a log of (url, User-Agent, clock time), `default` or 404 for the rest."""

    def __init__(self, clock: Clock, pages: dict[str, net.Response | str], default: str | None = None):
        self.clock, self.pages, self.default, self.log = clock, pages, default, []

    def __call__(self, url: str, headers: dict) -> net.Response:
        self.log.append((url, headers.get("User-Agent"), self.clock.now))
        page = self.pages.get(url, None if url.endswith("/robots.txt") else self.default)
        if page is None:
            return net.Response(url, 404, {"content-type": "text/plain"}, b"not found")
        if isinstance(page, net.Response):
            return page
        kind = "text/plain" if url.endswith(".txt") else "application/json" if page.startswith("{") else "text/html"
        return net.Response(url, 200, {"content-type": f"{kind}; charset=utf-8"}, page.encode())

    def urls(self) -> list[str]:
        return [url for url, _, _ in self.log]


def page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "lazuli.db")
    yield connection
    connection.close()


def source(name: str, kind: str = "snapshot", priority: int = 10, ttl: int | None = 30, **extra) -> SimpleNamespace:
    return SimpleNamespace(NAME=name, KIND=kind, PRIORITY=priority, TTL_DAYS=ttl, MIN_INTERVAL_S=3.0, **extra)


def add_face(conn, family: str, *, ps: str | None = None, ko: str | None = None, hangul: int = 0) -> int:
    count = conn.execute("SELECT COUNT(*) FROM local_font").fetchone()[0]
    cursor = conn.execute(
        """INSERT INTO local_font (path, size, mtime, face_index, postscript_name, family, family_norm,
             names_i18n_json, coverage_json, origin) VALUES (?, 1, '2026-01-01', 0, ?, ?, ?, ?, ?, 'user')""",
        (f"/fonts/{count}.otf", ps, family, scan.norm(family), json.dumps({"ko": ko}, ensure_ascii=False) if ko else None,
         json.dumps({"hangul_syllables": hangul})))
    conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------------------------------- net

def test_robots_disallow_and_crawl_delay_are_obeyed(clock):
    site = Site(clock, {"https://cat.test/robots.txt": page("robots.txt"),
                        "https://cat.test/fonts": "{}", "https://cat.test/fonts?page=2": "{}"})
    fetcher = net.Fetcher("demo", min_interval_s=3, transport=site)
    fetcher.get("https://cat.test/fonts")
    fetcher.get("https://cat.test/fonts", params={"page": 2})
    with pytest.raises(net.Blocked, match="disallows /admin/users") as blocked:
        fetcher.get("https://cat.test/admin/users")
    assert "robots.txt" in blocked.value.reason
    assert site.urls() == ["https://cat.test/robots.txt", "https://cat.test/fonts", "https://cat.test/fonts?page=2"]
    times = [t for _, _, t in site.log]
    assert times[1] - times[0] >= 3 and times[2] - times[1] >= 7.5        # Crawl-delay 7.5 beats min_interval 3
    assert fetcher.interval("https://cat.test/fonts") == 7.5 and fetcher.requests == 3
    assert net.crawl_delay(["User-agent: *", "Crawl-delay: 4"]) == 4 and net.crawl_delay(["Disallow: /x"]) is None
    assert {agent for _, agent, _ in site.log} == {net.USER_AGENT}
    assert net.USER_AGENT.startswith("lazuli/") and "github.com/lapis-labs/lapis-lazuli" in net.USER_AGENT


def test_missing_robots_allows_and_refused_robots_blocks(clock):
    open_site = Site(clock, {"https://open.test/a": "{}"})                # robots.txt answers 404
    net.Fetcher("open", min_interval_s=1, transport=open_site).get("https://open.test/a")
    assert open_site.urls() == ["https://open.test/robots.txt", "https://open.test/a"]
    for status in (403, 429, 503):
        closed = Site(clock, {"https://closed.test/robots.txt": net.Response("https://closed.test/robots.txt", status, {}, b"")})
        with pytest.raises(net.Blocked, match=f"answered {status}"):
            net.Fetcher("closed", min_interval_s=1, transport=closed).get("https://closed.test/a")
        assert closed.urls() == ["https://closed.test/robots.txt"]            # the page itself is never requested


def test_robots_redirect_from_http_to_https_reads_final_rules(clock):
    origin = "http://first.test"
    redirect = "https://first.test/robots.txt"
    site = Site(clock, {
        origin + "/robots.txt": net.Response(origin + "/robots.txt", 302, {"location": redirect}, b""),
        redirect: "User-agent: *\nDisallow: /private\n",
        origin + "/allowed": "{}"})
    fetcher = net.Fetcher("demo", min_interval_s=1, transport=site)
    assert fetcher.get(origin + "/allowed").status == 200
    with pytest.raises(net.Blocked, match="disallows /private"):
        fetcher.get(origin + "/private")
    assert site.urls() == [origin + "/robots.txt", redirect, origin + "/allowed"]


def test_robots_redirect_limit_and_refused_target_never_send_final_hop(clock, monkeypatch):
    from lazuli import sources

    origin = "https://first.test"
    redirects = {origin + f"/robots{i}": net.Response(
        origin + f"/robots{i}", 302, {"location": f"/robots{i + 1}"}, b"") for i in range(1, 7)}
    site = Site(clock, {origin + "/robots.txt": net.Response(
        origin + "/robots.txt", 302, {"location": "/robots1"}, b""), **redirects})
    with pytest.raises(net.Blocked, match="redirect limit"):
        net.Fetcher("demo", min_interval_s=1, transport=site).get(origin + "/page")
    assert site.urls() == [origin + "/robots.txt", *(origin + f"/robots{i}" for i in range(1, 6))]

    refused = "https://closed.test/robots.txt"
    monkeypatch.setattr(sources, "load_registry", lambda: [
        {"id": "closed", "url": "https://closed.test/", "access": "refused",
         "reason": "no automated requests"}])
    site = Site(clock, {origin + "/robots.txt": net.Response(
        origin + "/robots.txt", 302, {"location": refused}, b"")})
    with pytest.raises(net.Blocked, match="no automated requests"):
        net.Fetcher("demo", min_interval_s=1, transport=site).get(origin + "/page")
    assert site.urls() == [origin + "/robots.txt"]


def test_robots_redirect_to_credentials_or_non_http_is_never_requested(clock):
    origin = "https://first.test"
    for location, expected in (("https://user:password@other.test/robots.txt", "credentials"),
                               ("file:///tmp/robots.txt", "non-HTTP")):
        site = Site(clock, {origin + "/robots.txt": net.Response(
            origin + "/robots.txt", 302, {"location": location}, b"")})
        with pytest.raises(net.Blocked, match=expected):
            net.Fetcher("demo", min_interval_s=1, transport=site).get(origin + "/page")
        assert site.urls() == [origin + "/robots.txt"]


def test_malformed_robots_redirect_does_not_send_next_request(clock):
    origin = "https://first.test"
    site = Site(clock, {origin + "/robots.txt": net.Response(
        origin + "/robots.txt", 302, {"location": "http://[::1/x"}, b"")})
    with pytest.raises(net.Blocked, match="redirect URL is malformed; request not sent"):
        net.Fetcher("demo", min_interval_s=1, transport=site).get(origin + "/page")
    assert site.urls() == [origin + "/robots.txt"]


def test_malformed_page_redirect_does_not_send_next_request(clock):
    start = "https://first.test/page"
    site = Site(clock, {start: net.Response(start, 302, {"location": "http://[::1/x"}, b"")})
    with pytest.raises(net.Blocked, match="redirect URL is malformed; request not sent"):
        net.Fetcher("demo", min_interval_s=1, transport=site).get(start)
    assert site.urls() == ["https://first.test/robots.txt", start]

def test_redirect_to_refused_host_never_sends_the_next_request(clock, monkeypatch):
    from lazuli import sources

    start = "http://127.0.0.1:8123/page"
    target = "http://localhost:8123/landing"
    monkeypatch.setattr(sources, "load_registry", lambda: [
        {"id": "blocked", "url": "http://localhost:8123/", "access": "refused",
         "reason": "No automated collection"}])
    site = Site(clock, {start: net.Response(start, 302, {"location": target}, b"")})
    with pytest.raises(net.Blocked, match="No automated collection") as blocked:
        net.Fetcher("demo", min_interval_s=1, transport=site).get(start)
    assert target in blocked.value.reason
    assert site.urls() == ["http://127.0.0.1:8123/robots.txt", start]


def test_redirect_checks_destination_robots_before_request(clock, monkeypatch):
    from lazuli import sources

    monkeypatch.setattr(sources, "load_registry", lambda: [])
    first, next_url = "https://first.test/a", "https://second.test/private"
    site = Site(clock, {
        first: net.Response(first, 302, {"location": next_url}, b""),
        "https://second.test/robots.txt": "User-agent: *\nDisallow: /private\n",
    })
    with pytest.raises(net.Blocked, match="disallows /private"):
        net.Fetcher("demo", min_interval_s=1, transport=site).get(first)
    assert site.urls() == ["https://first.test/robots.txt", first, "https://second.test/robots.txt"]


def test_redirect_to_allowed_host_fetches_after_its_robots(clock, monkeypatch):
    from lazuli import sources

    monkeypatch.setattr(sources, "load_registry", lambda: [])
    first, next_url = "https://first.test/a", "https://second.test/landing"
    site = Site(clock, {first: net.Response(first, 302, {"location": next_url}, b""),
                        next_url: "arrived"})
    response = net.Fetcher("demo", min_interval_s=1, transport=site).get(first)
    assert response.url == next_url and response.text() == "arrived"
    assert site.urls() == ["https://first.test/robots.txt", first, "https://second.test/robots.txt", next_url]


@pytest.mark.parametrize("location, expected", [
    ("/page?q=it's", "https://first.test/page?q=it%27s"),
    ("https://FIRST.test:443/page", "https://first.test/page"),
    ("/한글", "https://first.test/%ED%95%9C%EA%B8%80"),
    ("/한글".encode().decode("latin-1"), "https://first.test/%ED%95%9C%EA%B8%80"),  # UTF-8 bytes as http.client reads them
    ("/a b", "https://first.test/a%20b"),
    ("https://first.test/a/../b/./c", "https://first.test/b/c"),
])
def test_redirect_targets_are_sent_in_the_browsers_spelling(clock, location, expected):
    start = "https://first.test/a"
    site = Site(clock, {start: net.Response(start, 302, {"location": location}, b""), expected: "arrived"})
    response = net.Fetcher("demo", min_interval_s=1, transport=site).get(start)
    assert response.url == expected and response.text() == "arrived"
    assert site.urls() == ["https://first.test/robots.txt", start, expected]


def test_robots_redirect_target_is_sent_in_the_browsers_spelling(clock):
    origin, target = "https://first.test", "https://first.test/%ED%95%9C%EA%B8%80/robots.txt"
    site = Site(clock, {
        origin + "/robots.txt": net.Response(origin + "/robots.txt", 302, {"location": "/한글/robots.txt"}, b""),
        target: "User-agent: *\nDisallow: /private\n", origin + "/allowed": "{}"})
    fetcher = net.Fetcher("demo", min_interval_s=1, transport=site)
    assert fetcher.get(origin + "/allowed").status == 200
    with pytest.raises(net.Blocked, match="disallows /private"):
        fetcher.get(origin + "/private")
    assert site.urls() == [origin + "/robots.txt", target, origin + "/allowed"]


def test_redirect_to_an_invalid_port_does_not_send_the_next_request(clock):
    start = "https://first.test/page"
    site = Site(clock, {start: net.Response(start, 302, {"location": "https://first.test:99999/x"}, b"")})
    with pytest.raises(net.Blocked, match="redirect URL is malformed; request not sent"):
        net.Fetcher("demo", min_interval_s=1, transport=site).get(start)
    assert site.urls() == ["https://first.test/robots.txt", start]


def test_redirect_to_credential_url_and_redirect_loop_stop_without_sending(clock, monkeypatch):
    from lazuli import sources

    monkeypatch.setattr(sources, "load_registry", lambda: [])
    first = "https://first.test/a"
    secret = "https://user:password@second.test/private"
    site = Site(clock, {first: net.Response(first, 302, {"location": secret}, b"")})
    with pytest.raises(net.Blocked, match="credentials") as blocked:
        net.Fetcher("demo", min_interval_s=1, transport=site).get(first)
    assert secret not in blocked.value.reason and site.urls() == ["https://first.test/robots.txt", first]

    site = Site(clock, {first: net.Response(first, 302, {"location": "/a"}, b"")})
    with pytest.raises(net.Blocked, match="redirect limit") as blocked:
        net.Fetcher("demo", min_interval_s=1, transport=site).get(first)
    assert first in blocked.value.reason
    assert site.urls() == ["https://first.test/robots.txt", *([first] * (net.MAX_REDIRECTS + 1))]


@pytest.mark.parametrize("alias", ["lºcalhost", "LOCALHOST."])
def test_real_urllib_transport_does_not_follow_idna_alias_redirect(monkeypatch, alias):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from lazuli import sources

    requested = []

    class SiteHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append((self.headers["Host"], self.path))
            self.send_response(302 if self.path == "/page" else 200)
            if self.path == "/page":
                self.send_header("Location", f"http://{alias}:{self.server.server_port}/landing")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SiteHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(sources, "load_registry", lambda: [
        {"id": "closed", "url": "http://localhost/", "access": "refused", "reason": "Local host refused"}])
    try:
        with pytest.raises(net.Blocked, match="Local host refused"):
            net.Fetcher("loopback", min_interval_s=0, transport=REAL_TRANSPORT).get(
                f"http://127.0.0.1:{server.server_port}/page")
        assert [path for _, path in requested] == ["/robots.txt", "/page"]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_real_urllib_transport_does_not_follow_a_refused_redirect(monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from lazuli import sources

    requested = []

    class LocalSite(BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append((self.headers["Host"], self.path))
            if self.path == "/robots.txt":
                body = b"User-agent: *\nAllow: /\n"
                self.send_response(200)
            elif self.path == "/page":
                body = b""
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{self.server.server_port}/landing")
            else:
                body = b"SHOULD NOT FETCH"
                self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalSite)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(sources, "load_registry", lambda: [
        {"id": "local-refused", "url": "http://localhost/", "access": "refused",
         "reason": "Local host refused"}])
    try:
        with pytest.raises(net.Blocked, match="Local host refused") as blocked:
            net.Fetcher("loopback", min_interval_s=0, transport=REAL_TRANSPORT).get(
                f"http://127.0.0.1:{server.server_port}/page")
        assert f"http://localhost:{server.server_port}/landing" in blocked.value.reason
        assert [path for _, path in requested] == ["/robots.txt", "/page"]
        assert all(host.startswith("127.0.0.1:") for host, _ in requested)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_pacing_holds_across_fetchers_of_one_source_through_meta(clock, conn):
    site = Site(clock, {"https://cat.test/a": "{}", "https://other.test/a": "{}"})
    net.Fetcher("demo", min_interval_s=5, conn=conn, transport=site).get("https://cat.test/a")
    first_end = clock.now
    assert float(store.get_meta(conn, "last_request.demo")) == first_end
    net._last_request.clear()                                              # a new process: only the database remembers
    clock.now += 2
    later = net.Fetcher("demo", min_interval_s=5, conn=conn, transport=site)
    later.get("https://cat.test/a")
    assert site.log[2][2] - first_end == 5 and clock.slept[-2:] == [3, 5]   # its robots.txt waits too
    before = clock.now
    net.Fetcher("another", min_interval_s=5, conn=conn, transport=site).get("https://other.test/a")
    assert site.log[4][2] == before                                        # another source has its own pace


@pytest.mark.parametrize("response, expected", [
    (net.Response("https://cat.test/p", 401, {}, b""), "401 Unauthorized"),
    (net.Response("https://cat.test/p", 403, {"content-type": "text/html"}, b"<html>denied</html>"), "403 Forbidden"),
    (net.Response("https://cat.test/p", 429, {"retry-after": "60"}, b""), "429 Too Many Requests"),
    (net.Response("https://cat.test/p", 503, {"content-type": "text/html"}, page("challenge.html").encode()), "CAPTCHA"),
    (net.Response("https://cat.test/p", 200, {"content-type": "text/html"}, page("captcha.html").encode()), "CAPTCHA"),
    (net.Response("https://cat.test/users/sign_in", 200, {"content-type": "text/html"}, b"<html><body>Welcome</body></html>"), "sign-in"),
    (net.Response("https://cat.test/p", 200, {"content-type": "text/html"}, page("signin.html").encode()), "sign-in"),
], ids=["401", "403", "429", "challenge", "captcha-widget", "redirected-to-sign-in", "sign-in-form"])
def test_blocked_responses(clock, conn, response, expected):
    demo = source("demo")
    store.ensure_source(conn, demo)
    site = Site(clock, {"https://cat.test/p": response})
    fetcher = net.Fetcher("demo", min_interval_s=1, conn=conn, transport=site)
    with pytest.raises(net.Blocked, match=expected):
        fetcher.get("https://cat.test/p", store_as="p")
    assert store.load_raw(conn, "demo", "p") is None                       # a block keeps nothing


def test_ordinary_pages_pass_and_other_errors_raise(clock):
    site = Site(clock, {"https://cat.test/family": page("ordinary.html"),
                        "https://cat.test/down": net.Response("https://cat.test/down", 500, {}, b"")})
    fetcher = net.Fetcher("demo", min_interval_s=1, transport=site)
    assert "나눔고딕" in fetcher.get("https://cat.test/family").text()         # sign-in link and invisible reCAPTCHA script
    with pytest.raises(net.FetchError) as error:
        fetcher.get("https://cat.test/down")
    assert error.value.status == 500


def test_raw_payload_round_trip(clock, conn):
    store.ensure_source(conn, source("demo"))
    body = json.dumps({"families": [{"name": "Nanum Gothic", "ko": "나눔고딕"}] * 50}, ensure_ascii=False).encode()
    site = Site(clock, {"https://cat.test/list.json": net.Response("https://cat.test/list.json", 200,
                                                                    {"content-type": "application/json"}, body)})
    response = net.Fetcher("demo", min_interval_s=1, conn=conn, transport=site).get("https://cat.test/list.json",
                                                                                    store_as="list.json")
    assert response.json()["families"][0]["ko"] == "나눔고딕"
    assert store.load_raw(conn, "demo", "list.json") == body
    kept = conn.execute("SELECT body_gz FROM raw_payload").fetchone()[0]
    assert gzip.decompress(kept) == body and len(kept) < len(body) / 5


# ---------------------------------------------------------------------------------------------- store

def families(*names: str, prefix: str = "") -> list[CatalogFamily]:
    return [CatalogFamily(source_key=f"{prefix}{name.lower().replace(' ', '-')}", family=name,
                          labels=[CatalogLabel("genre", "Sans Serif", "sans")]) for name in names]


def test_replace_snapshot_is_atomic_and_replaces_everything(conn):
    demo = source("demo")
    nanum = CatalogFamily("nanum-gothic", "Nanum Gothic", names_i18n={"ko": "나눔고딕"}, foundry="Sandoll",
                          designers=["Designer One"], license="OFL-1.1",
                          fonts=[CatalogFont("NanumGothic-Regular", "normal", 400)],
                          labels=[CatalogLabel("genre", "Sans Serif", "sans"), CatalogLabel("license", "OFL", "OFL-1.1")])
    assert store.replace_snapshot(conn, demo, [nanum, *families("Plain Serif")]) == 2
    broken = families("Fresh One") + [CatalogFamily("bad", "Bad", labels=[CatalogLabel("mood", "x")])]
    with pytest.raises(sqlite3.IntegrityError):                            # kind outside the schema CHECK
        store.replace_snapshot(conn, demo, broken)
    assert {r[0] for r in conn.execute("SELECT family FROM catalog_family")} == {"Nanum Gothic", "Plain Serif"}
    assert [r["family"] for r in store.search(conn, "나눔고딕")] == ["Nanum Gothic"]      # search rows survived too
    assert store.replace_snapshot(conn, demo, families("Fresh One")) == 1
    assert {r[0] for r in conn.execute("SELECT family FROM catalog_family")} == {"Fresh One"}
    for table in ("catalog_font", "catalog_label"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE source_key = 'nanum-gothic'").fetchone()[0] == 0
    assert store.search(conn, "나눔고딕") == [] and conn.execute("SELECT COUNT(*) FROM catalog_search").fetchone()[0] == 1
    row = conn.execute("SELECT status, fetched_at FROM source WHERE name = 'demo'").fetchone()
    assert row["status"] == "ok" and row["fetched_at"]


def test_catalog_search_uses_trigrams_and_like_for_short_text(conn):
    store.replace_snapshot(conn, source("demo"), [
        CatalogFamily("nanum-gothic", "Nanum Gothic", names_i18n={"ko": "나눔고딕"}, foundry="Naver",
                      labels=[CatalogLabel("genre", "고딕", "min-bu-ri")]),
        CatalogFamily("gowun-batang", "Gowun Batang", names_i18n={"ko": "고운바탕"},
                      labels=[CatalogLabel("genre", "명조", "bu-ri")])])
    store.replace_snapshot(conn, source("other", priority=20), families("Plain Serif"))
    found = lambda text: [r["family"] for r in store.search(conn, text)]    # noqa: E731
    assert found("눔고딕") == ["Nanum Gothic"]                                  # Korean substring, 3 characters
    assert found("anum goth") == ["Nanum Gothic"] and found("NAVER") == ["Nanum Gothic"]
    assert sorted(found("bu-ri")) == ["Gowun Batang", "Nanum Gothic"]         # mapped labels: bu-ri, min-bu-ri
    assert found("고운") == ["Gowun Batang"]                                    # 2 characters: LIKE
    assert found("Go") == ["Gowun Batang", "Nanum Gothic"]                     # LIKE, ordered by priority then name
    assert found("%") == [] and found("") == []
    assert found("serif") == ["Plain Serif"]


# ---------------------------------------------------------------------------------------------- matching

def matches(conn) -> dict[str, list[tuple]]:
    out: dict[str, list[tuple]] = {}
    for row in conn.execute("""SELECT lf.family, s.name, m.source_key, m.method, m.confidence FROM match m
                               JOIN local_font lf ON lf.id = m.local_font_id JOIN source s ON s.id = m.source_id
                               ORDER BY lf.family, s.name, m.source_key"""):
        out.setdefault(row[0], []).append(tuple(row)[1:])
    return out


def test_matching_methods_and_lookup_candidates(conn):
    store.replace_snapshot(conn, source("demo"), [
        CatalogFamily("nanum-gothic", "Nanum Gothic", names_i18n={"ko": "나눔고딕"},
                      fonts=[CatalogFont("NanumGothic-Regular")]),
        CatalogFamily("pretendard", "Pretendard"),
        CatalogFamily("hiragino-mincho", "Hiragino Mincho ProN")])
    add_face(conn, "Renamed Export", ps="NanumGothic-Regular")
    add_face(conn, "Nanum Gothic OTF", ko="나눔고딕", ps="NanumGothicOTF-Bold")
    add_face(conn, "Pretendard Variable")
    add_face(conn, "PretendardVF SemiBold")
    add_face(conn, "Pretendard Pro ExtraBold Italic")
    add_face(conn, "Hiragino Mincho Pr6N")
    add_face(conn, "Unknown Hand", hangul=2350)
    add_face(conn, "Plain Latin")
    add_face(conn, ".Hidden System")
    stats = match.run(conn)
    assert stats["faces"] == 9 and stats["matched"] == 6 and stats["by_source"] == {"demo": 6}
    found = matches(conn)
    assert found["Renamed Export"] == [("demo", "nanum-gothic", "exact_ps", 1.0)]
    assert found["Nanum Gothic OTF"] == [("demo", "nanum-gothic", "exact_family", 0.9)]      # Korean i18n name; fuzzy dropped
    for name in ("Pretendard Variable", "PretendardVF SemiBold", "Pretendard Pro ExtraBold Italic"):
        assert found[name] == [("demo", "pretendard", "fuzzy", 0.6)]
    assert found["Hiragino Mincho Pr6N"] == [("demo", "hiragino-mincho", "fuzzy", 0.6)]
    assert match.fuzzy_key("Pretendard") == "pretendard" and match.fuzzy_key("Bold Italic") is None
    # lookups only for families no snapshot matched: Hangul first, hidden families never
    store.save_lookup(conn, source("look", kind="lookup", priority=60, ttl=90), "plainlatin",
                      CatalogFamily("plain-latin", "Plain Latin"), 90)
    match.run(conn)
    assert "Plain Latin" in matches(conn)                                  # a lookup answer is matched too ...
    assert [c["family"] for c in match.unmatched(conn)] == ["Unknown Hand", "Plain Latin"]  # ... but is no snapshot
    assert match.unmatched(conn, "pretendard") == []


def test_labels_resolve_by_source_priority(conn):
    snapshot = json.loads(page("snapshot.json"))["families"]
    early = source("early", priority=10)
    store.replace_snapshot(conn, early, [
        CatalogFamily(f["id"], f["name"], labels=labels.class_labels(f["category"], f["category"])
                      + [labels.license_label(f["license"])]) for f in snapshot])
    store.replace_snapshot(conn, system_table, system_table.fetch(None))
    store.replace_snapshot(conn, source("vague", priority=5), [
        CatalogFamily("asdgn", "Apple SD Gothic Neo", labels=[CatalogLabel("genre", "Gothic?")])])
    face = add_face(conn, "Apple SD Gothic Neo")
    match.run(conn)
    rows = conn.execute("SELECT * FROM v_font_label WHERE local_font_id = ?", (face,)).fetchall()
    assert {r["source"] for r in rows} == {"vague", "early", "system-table"}
    resolved = {(label["kind"], label["mapped"], label["source"]) for label in labels.resolve(rows)}
    # genre: `vague` (priority 5) maps nothing, so `early` (10) wins over system-table (50); no subclass from
    # system-table rides along. license: early's "proprietary" is unmapped, so system-table's mapped one wins.
    assert resolved == {("genre", "sans", "early"), ("license", "system", "system-table")}
    family = labels.by_family(conn)["Apple SD Gothic Neo"]
    assert [s["source"] for s in family["sources"]] == ["vague", "early", "system-table"]
    assert {s["method"] for s in family["sources"]} == {"exact_family"}


def test_label_vocabulary_helpers():
    assert {"serif", "sans", "slab", "mono", "display", "hand", "bu-ri", "min-bu-ri"} == labels.GENRES
    assert "min-bu-ri.rounded" in labels.SUBCLASSES and "display.tal-nemo" in labels.SUBCLASSES
    assert labels.KO_CLASSES["둥근 민부리"] == "min-bu-ri.rounded" and labels.KO_CLASSES["부리"] == "bu-ri"
    assert [(lb.kind, lb.mapped) for lb in labels.class_labels("Gulim", "min-bu-ri.rounded")] == [
        ("genre", "min-bu-ri"), ("subclass", "min-bu-ri.rounded")]
    assert labels.class_labels("UD", None) == [CatalogLabel("genre", "UD")]
    with pytest.raises(ValueError):
        labels.class_labels("Gothic", "gothic")
    assert [labels.map_license(text) for text in ("OFL", "SIL Open Font License, Version 1.1", "APACHE2",
                                                   "Ubuntu Font Licence", "공공누리 제1유형", "KOGL Type II",
                                                   "OFL-1.0", "proprietary", None)] == [
        "OFL-1.1", "OFL-1.1", "Apache-2.0", "UFL-1.0", "KOGL-1", None, None, None, None]


def test_system_table_source(conn):
    by_family = {f.family: f for f in system_table.fetch(None)}
    assert (system_table.NAME, system_table.KIND, system_table.PRIORITY, system_table.TTL_DAYS) == (
        "system-table", "bundled", 50, None)
    apple = by_family["Apple SD Gothic Neo"]
    assert apple.source_key == "apple-sd-gothic-neo" and apple.license == "system"
    assert [(lb.kind, lb.raw, lb.mapped) for lb in apple.labels] == [
        ("genre", "min-bu-ri", "min-bu-ri"), ("license", "system", "system")]
    assert [(lb.kind, lb.mapped) for lb in by_family["Gulim"].labels][:2] == [("genre", "min-bu-ri"),
                                                                              ("subclass", "min-bu-ri.rounded")]
    assert by_family["Menlo"].labels[0].mapped == "mono"
    assert by_family["system-ui"].labels[0] == CatalogLabel("genre", "generic")      # a CSS keyword, no genre
    assert store.replace_snapshot(conn, system_table, list(by_family.values())) == len(by_family)


# ---------------------------------------------------------------------------------------------- CLI

@pytest.fixture
def env(tmp_path, monkeypatch):
    roots = {"system": tmp_path / "system", "user": tmp_path / "user"}
    for path in roots.values():
        path.mkdir()
    monkeypatch.setenv("LAZULI_FONT_ROOTS", os.pathsep.join(f"{origin}={path}" for origin, path in roots.items()))
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "cache" / "lazuli.db"))
    return SimpleNamespace(roots=roots, db=tmp_path / "cache" / "lazuli.db")


def fake_snapshot(clock, *, fail: Exception | None = None):
    site = Site(clock, {"https://snap.test/families.json": page("snapshot.json")})
    calls = []

    def fetch(fetcher):
        calls.append(fetcher)
        if fail is not None:
            raise fail
        data = fetcher.get("https://snap.test/families.json", store_as="families.json").json()
        return [CatalogFamily(f["id"], f["name"], names_i18n={"ko": f["ko"]} if "ko" in f else {},
                              fonts=[CatalogFont(ps) for ps in f["fonts"]],
                              labels=labels.class_labels(f["category"], f["category"]) + [labels.license_label(f["license"])])
                for f in data["families"]]

    return source("fake-snap", fetch=fetch, calls=calls, site=site)


def fake_lookup(clock, known: dict[str, str]):
    site = Site(clock, {}, default="{}")
    asked = []

    def lookup(fetcher, family, *, names_i18n=None, postscript_name=None):
        asked.append(family)
        fetcher.get("https://look.test/search", params={"q": family})
        if family not in known:
            return None
        return CatalogFamily(family.lower().replace(" ", "-"), family, url=f"https://look.test/{family}",
                             labels=labels.class_labels(known[family], known[family]))

    return source("fake-look", kind="lookup", priority=60, ttl=90, REQUESTS_PER_LOOKUP=1, lookup=lookup, asked=asked,
                  site=site)


def use_sources(monkeypatch, *modules):
    """The CLI sees only these adapters, and every Fetcher it makes talks to its adapter's fake site."""
    monkeypatch.setattr(catalog, "SOURCES", tuple(modules))
    sites = {module.NAME: module.site for module in modules if hasattr(module, "site")}
    real = net.Fetcher.__init__

    def init(self, name, *, min_interval_s, conn=None, transport=None):
        real(self, name, min_interval_s=min_interval_s, conn=conn, transport=transport or sites.get(name))

    monkeypatch.setattr(net.Fetcher, "__init__", init)


def test_sync_status_and_local_fonts_show_labels(env, clock, monkeypatch, capsys):
    snap = fake_snapshot(clock)
    use_sources(monkeypatch, snap, system_table)
    build(env.roots["system"] / "AppleSD.ttf", family="Apple SD Gothic Neo")
    build(env.roots["user"] / "Nanum.ttf", family="NanumGothicOTF", names_ko="나눔고딕")
    assert cli.main(["local", "fonts", "--no-measure"]) == 0
    capsys.readouterr()
    assert cli.main(["catalog", "sync"]) == 0
    out = capsys.readouterr().out
    assert "fake-snap: 3 families, 2 requests" in out and "system-table: 26 families, 0 requests" in out
    assert "matched 2 of 2 installed faces" in out
    assert snap.site.urls() == ["https://snap.test/robots.txt", "https://snap.test/families.json"]
    assert cli.main(["catalog", "sync"]) == 0                              # within ttl: only the bundled table
    out = capsys.readouterr().out
    assert "fake-snap: fresh until" in out and "system-table: 26 families" in out and len(snap.calls) == 1
    assert cli.main(["catalog", "sync", "--source", "fake-snap", "--force"]) == 0 and len(snap.calls) == 2
    capsys.readouterr()
    assert cli.main(["catalog", "status"]) == 0
    out = capsys.readouterr().out
    assert "fake-snap" in out and "fresh until" in out and "system-table" in out and "bundled" in out
    assert "Yoon Design blocks tools" in out
    assert cli.main(["local", "fonts", "--json", "--no-measure"]) == 0
    listed = {f["family"]: f["catalog"] for f in json.loads(capsys.readouterr().out)}
    apple = listed["Apple SD Gothic Neo"]
    assert [s["source"] for s in apple["sources"]] == ["fake-snap", "system-table"]
    assert {(lb["kind"], lb["mapped"], lb["source"]) for lb in apple["labels"]} == {
        ("genre", "sans", "fake-snap"), ("license", "system", "system-table")}
    assert listed["NanumGothicOTF"]["sources"][0]["method"] == "exact_family"
    assert cli.main(["local", "fonts", "--family", "nanum", "--no-measure"]) == 0
    out = capsys.readouterr().out
    assert "catalog: genre sans, license OFL-1.1  (fake-snap: Nanum Gothic, exact_family)" in out
    assert cli.main(["local", "fonts", "--summary", "--no-measure"]) == 0
    assert "Catalog labels: 2 of 2 families matched (fake-snap 2, system-table 1)" in capsys.readouterr().out


def test_a_failed_source_keeps_its_rows_and_is_not_retried(env, clock, monkeypatch, capsys):
    snap = fake_snapshot(clock)
    use_sources(monkeypatch, snap)
    assert cli.main(["catalog", "sync"]) == 0
    blocked = fake_snapshot(clock, fail=net.Blocked("403 Forbidden from https://snap.test/families.json"))
    use_sources(monkeypatch, blocked)
    assert cli.main(["catalog", "sync", "--force"]) == 1
    assert "fake-snap: blocked: 403 Forbidden" in capsys.readouterr().out
    conn = db.connect(env.db)
    assert conn.execute("SELECT COUNT(*) FROM catalog_family").fetchone()[0] == 3        # previous rows kept
    conn.execute("UPDATE source SET fetched_at = '2020-01-01T00:00:00+00:00'")            # ttl long expired
    conn.commit()
    conn.close()
    assert cli.main(["catalog", "sync"]) == 0 and len(blocked.calls) == 1                # failed: not retried
    assert "not retried" in capsys.readouterr().out
    assert cli.main(["catalog", "status"]) == 0
    assert "failed: 403 Forbidden from https://snap.test/families.json" in capsys.readouterr().out
    assert cli.main(["catalog", "sync", "--source", "fake-snap"]) == 1 and len(blocked.calls) == 2  # asked by name


def test_sources_whose_terms_forbid_tools_are_disabled_without_requests(env, clock, monkeypatch, capsys):
    from lazuli.catalog import adobe_cjk, noonnu

    snap = fake_snapshot(clock)
    use_sources(monkeypatch, snap, adobe_cjk, noonnu)                  # net.default_transport fails the test
    build(env.roots["user"] / "Mystery.ttf", family="Mystery Myeongjo", names_ko="미스터리명조")
    assert cli.main(["local", "fonts", "--no-measure"]) == 0
    capsys.readouterr()
    assert cli.main(["catalog", "sync"]) == 0                           # disabled is not a failure
    out = capsys.readouterr().out
    assert "adobe-cjk: disabled: Adobe's General Terms of Use (section 6.18)" in out
    assert cli.main(["catalog", "lookup", "--unmatched", "--yes"]) == 0
    assert "noonnu: disabled:" in capsys.readouterr().out
    assert cli.main(["catalog", "lookup", "--source", "noonnu", "--unmatched"]) == 0
    assert "https://noonnu.cc/index?search=%EB%AF%B8%EC%8A%A4%ED%84%B0%EB%A6%AC%EB%AA%85%EC%A1%B0" in capsys.readouterr().out
    assert cli.main(["catalog", "status"]) == 0
    out = capsys.readouterr().out
    assert "adobe-cjk" in out and "disabled: Adobe's" in out and "disabled: noonnu's terms" in out


def test_lookup_plans_confirms_and_reuses_cached_answers(env, clock, monkeypatch, capsys):
    snap = fake_snapshot(clock)
    look = fake_lookup(clock, {"Mystery Myeongjo": "bu-ri"})
    use_sources(monkeypatch, snap, look)
    assert cli.main(["catalog", "sync"]) == 0
    conn = db.connect(env.db)
    add_face(conn, "Nanum Gothic")                                         # matched by the snapshot: never looked up
    add_face(conn, "Mystery Myeongjo", hangul=2350)
    for n in range(10):
        add_face(conn, f"Other {n:02}")
    match.run(conn)                                                        # as a scan would
    conn.close()
    capsys.readouterr()
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert cli.main(["catalog", "lookup", "--unmatched"]) == 1
    out = capsys.readouterr().out
    assert "fake-look: 11 families to look up, about 12 requests" in out and "at least 36 s at 3 s" in out
    assert "nothing requested" in out and look.asked == []
    assert cli.main(["catalog", "lookup", "--unmatched", "--limit", "3"]) == 0        # 4 requests: no question
    assert look.asked == ["Mystery Myeongjo", "Other 00", "Other 01"]
    out = capsys.readouterr().out
    assert "Mystery Myeongjo: Mystery Myeongjo (https://look.test/Mystery Myeongjo)" in out and "Other 00: not found" in out
    assert look.site.urls()[0] == "https://look.test/robots.txt" and len(look.site.urls()) == 4
    assert all(b - a >= 3 for a, b in zip([t for *_, t in look.site.log], [t for *_, t in look.site.log][1:]))
    assert cli.main(["catalog", "lookup", "--family", "mystery"]) == 0                 # cached within ttl
    assert "nothing to request" in capsys.readouterr().out and len(look.asked) == 3
    assert cli.main(["catalog", "lookup", "--family", "nanum"]) == 0
    assert "already matched by a snapshot" in capsys.readouterr().out
    assert cli.main(["catalog", "lookup", "--family", "nowhere"]) == 1
    conn = db.connect(env.db)
    row = conn.execute("""SELECT s.name, m.method FROM match m JOIN local_font lf ON lf.id = m.local_font_id
                          JOIN source s ON s.id = m.source_id WHERE lf.family = 'Mystery Myeongjo'""").fetchone()
    assert tuple(row) == ("fake-look", "exact_family")
    assert store.cached_lookup(conn, look, "other00") is None and store.cached_lookup(conn, look, "other05") == "miss"
    conn.close()
    assert cli.main(["catalog", "sync", "--source", "fake-look"]) == 2                 # lookups never sync


def test_lookup_stops_a_blocked_source(env, clock, monkeypatch, capsys):
    look = fake_lookup(clock, {})
    look.site.pages["https://look.test/search?q=First"] = net.Response(
        "https://look.test/search?q=First", 429, {}, b"")
    use_sources(monkeypatch, look)
    conn = db.connect(env.db)
    add_face(conn, "First")
    add_face(conn, "Second")
    conn.close()
    assert cli.main(["catalog", "lookup", "--unmatched"]) == 1
    assert "blocked: 429 Too Many Requests" in capsys.readouterr().out and look.asked == ["First"]
    conn = db.connect(env.db)
    assert conn.execute("SELECT status FROM source WHERE name = 'fake-look'").fetchone()[0] == "failed"
    assert store.reason(conn, "fake-look").startswith("429 Too Many Requests")
    assert store.cached_lookup(conn, look, "first") == "miss"             # a block caches no answer
    conn.close()
    assert cli.main(["catalog", "lookup", "--unmatched"]) == 0
    assert "fake-look: failed earlier (429 Too Many Requests" in capsys.readouterr().out and look.asked == ["First"]
