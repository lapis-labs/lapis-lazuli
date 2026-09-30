"""One URL spelling for source policy, pacing, robots.txt, and the request on every hop."""
from __future__ import annotations

import json
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from lazuli import sources
from lazuli.catalog import net
from lazuli.ref import common


CASES = Path(__file__).parent / "fixtures" / "url-cases.json"


def test_browser_url_contrasts_all_63_kit_cases_with_headless_chromium(browser):
    inputs = json.loads(CASES.read_text(encoding="utf-8"))
    urls = inputs["review"] + inputs["added"]
    assert len(urls) == 63
    page = browser.new_page()
    try:
        hrefs = page.evaluate("""urls => urls.map(value => {
            try { return new URL(value).href.split('#', 1)[0]; }
            catch (error) { return null; }
        })""", urls)
        for url, href in zip(urls, hrefs, strict=True):
            try:
                spelling = net.browser_url(url)
            except ValueError:
                continue
            assert href is not None and spelling == href, (url, spelling, href)
    finally:
        page.close()


@pytest.mark.parametrize("url, expected", [
    ("http://%6eoonnu.cc/font_page/366", "noonnu"),
    ("http://127%2E0.0.1/x", "local"),
    ("http://%31%32%37.0.0.1/x", "local"),
    ("http://127.0.0.1./x", "local"),
])
def test_registry_refuses_the_host_the_request_would_reach(url, expected):
    registry = [{"id": "noonnu", "url": "http://noonnu.cc/", "access": "refused"},
                {"id": "local", "url": "http://127.0.0.1/", "access": "refused"}]
    assert sources.find(url, registry)["id"] == expected


@pytest.mark.parametrize("host", ["faß.de", "ς.example", "exa\u200cmple.com", "exa\u200dmple.com",
                                   "ex\u00adample.com", "exa\u200bmple.com", "exa\ufeffmple.com",
                                   "exa\ufe0fmple.com", "a%3Ab.com", "a%2Ab.com", "a%FFb.com",
                                   "a\u0378b.com", "a\u13a0b.com", "xn--ab-g4b.com",
                                   "1.2.3.4.5", "999.1.1.1", "foo.1", "1.2.3.0x", "foo.0xg"])
def test_unstable_and_noncanonical_hosts_are_rejected(host):
    with pytest.raises(ValueError):
        net.browser_url(f"http://{host}/")


def test_userinfo_and_fragment_do_not_leave_a_credential_or_fragment():
    with pytest.raises(ValueError):
        net.browser_url("https://user:pass@docs.test/a")
    assert net.browser_url("HTTPS://Docs.Test/a#top") == "https://docs.test/a"
    assert net.browser_url("http://[::FFFF:127.0.0.1]/") == "http://[::ffff:7f00:1]/"
    assert net.browser_url("http://1.2.3.4./") == "http://1.2.3.4/"
    assert net.browser_url("http://example.com./") == "http://example.com./"


def test_fetcher_appends_parameters_after_dropping_fragment(monkeypatch):
    sent = []

    def transport(url, headers):
        sent.append(url)
        return net.Response(url, 404 if url.endswith("/robots.txt") else 200, {}, b"OK")

    monkeypatch.setattr(sources, "load_registry", lambda: [])
    monkeypatch.setattr(net, "default_transport", transport)
    response = net.Fetcher("read:docs.test", min_interval_s=0).get(
        "https://DOCS.test/page#fragment", params={"key": "value"})
    assert response.url == "https://docs.test/page?key=value"
    assert sent == ["https://docs.test/robots.txt", "https://docs.test/page?key=value"]


@pytest.mark.parametrize("target", ["127.0.0.1", "%31%32%37.0.0.1", "127%2E0.0.1", "％３１％３２％３７.0.0.1"])
def test_real_redirect_to_refused_loopback_sends_no_target_request(monkeypatch, target):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.headers["Host"], self.path))
            self.send_response(302 if self.path == "/page" else 200)
            if self.path == "/page":
                location = f"http://{target}:{self.server.server_port}/landing"
                self.send_header("Location", location.encode("utf-8").decode("latin-1"))
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    registry = [{"id": "blocked", "url": "http://127.0.0.1/", "access": "refused",
                 "reason": "Local host refused"}]
    monkeypatch.setattr(sources, "load_registry", lambda: registry)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), net._NoRedirect())
    transport = lambda url, headers: net._transport(url, headers, opener)
    monkeypatch.setattr(net, "_last_request", {})
    try:
        with pytest.raises(net.Blocked):
            net.Fetcher("read:localhost", min_interval_s=0, transport=transport).get(
                f"http://localhost:{server.server_port}/page")
        assert [path for _, path in seen] == ["/robots.txt", "/page"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_percent_encoded_refused_name_is_never_requested(monkeypatch):
    requests = []
    monkeypatch.setattr(sources, "load_registry", lambda: [
        {"id": "noonnu", "url": "https://noonnu.cc/", "access": "refused", "reason": "Site refused"}])
    monkeypatch.setattr(net, "default_transport", lambda url, headers: requests.append(url))
    with pytest.raises(net.Blocked, match="Site refused"):
        net.Fetcher("read:noonnu.cc", min_interval_s=0).get("https://%6eoonnu.cc/x")
    assert requests == []


def test_robots_redirect_checks_a_percent_encoded_refused_host(monkeypatch):
    requests = []
    origin = "https://open.test/robots.txt"

    def transport(url, headers):
        requests.append(url)
        if url != origin:
            raise AssertionError(f"refused robots target was requested: {url}")
        return net.Response(url, 302, {"location": "https://%6eoonnu.cc/robots.txt"}, b"")

    monkeypatch.setattr(sources, "load_registry", lambda: [
        {"id": "noonnu", "url": "https://noonnu.cc/", "access": "refused", "reason": "Site refused"}])
    with pytest.raises(net.Blocked, match="Site refused"):
        net.Fetcher("read:open.test", min_interval_s=0, transport=transport).get("https://open.test/page")
    assert requests == [origin]


def test_first_url_uses_one_spelling_for_robots_pace_and_transport(monkeypatch):
    sent = []
    monkeypatch.setattr(sources, "load_registry", lambda: [])
    monkeypatch.setattr(net, "_last_request", {})

    def transport(url, headers):
        sent.append(url)
        return net.Response(url, 404 if url.endswith("/robots.txt") else 200, {}, b"OK")

    response = net.Fetcher("read:docs.test", min_interval_s=0, transport=transport).get(
        "https://%64ocs.test/public/../safe#fragment")
    assert response.url == "https://docs.test/safe"
    assert sent == ["https://docs.test/robots.txt", "https://docs.test/safe"]
    assert set(net._last_request) == {"read:docs.test"}


@pytest.mark.parametrize("middle", ["..", "%2e%2e"])
def test_reference_preflight_resolves_dot_segments_before_robots(monkeypatch, tmp_path, middle):
    sent = []
    url = f"https://docs.test/public/{middle}/private/x"

    def transport(target, headers):
        sent.append(target)
        if target == "https://docs.test/robots.txt":
            return net.Response(target, 200, {}, b"User-agent: *\nDisallow: /private/\n")
        raise AssertionError("robots did not block the private request")

    monkeypatch.setattr(sources, "load_registry", lambda: [])
    monkeypatch.setattr(net, "default_transport", transport)
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    with pytest.raises(common.Refused, match="disallows /private/x"):
        common.fetch(url)
    assert sent == ["https://docs.test/robots.txt"]
