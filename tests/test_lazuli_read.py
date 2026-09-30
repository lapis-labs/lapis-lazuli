"""lazuli read: the registry policy, polite fetching, sign-in walls, HTML to Markdown, the cache, and --render.

Most pages use a fake transport. Transport regressions use loopback-only HTTP servers; the
database and cache live in temporary folders.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest

from lazuli import paths, read, sources
from lazuli.catalog import net

REAL_TRANSPORT = net.default_transport


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class Site:
    """Fixed pages by URL (a str is served as UTF-8 HTML, or as text for .txt), 404 for the rest,
    and a log of (url, User-Agent)."""

    def __init__(self, pages: dict[str, net.Response | str]):
        self.pages, self.log = pages, []

    def __call__(self, url: str, headers: dict) -> net.Response:
        self.log.append((url, headers.get("User-Agent")))
        page = self.pages.get(url)
        if page is None:
            return net.Response(url, 404, {"content-type": "text/plain"}, b"not found")
        if isinstance(page, net.Response):
            return page
        kind = "text/plain" if url.endswith(".txt") else "text/html; charset=utf-8"
        return net.Response(url, 200, {"content-type": kind}, page.encode())

    def urls(self) -> list[str]:
        return [url for url, _ in self.log]


@pytest.fixture(autouse=True)
def clock(tmp_path, monkeypatch):
    def no_network(url, headers):
        raise AssertionError(f"a test reached for the network: {url}")

    fake = Clock()
    monkeypatch.setattr(net, "_clock", fake.time)
    monkeypatch.setattr(net, "_sleep", fake.sleep)
    monkeypatch.setattr(net, "_last_request", {})
    monkeypatch.setattr(net, "default_transport", no_network)
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    fake.real_render_transport = read._render_transport
    monkeypatch.setattr(read, "_render_transport", lambda url, headers: net.default_transport(url, headers))
    resolver = socket.getaddrinfo

    def local_only_resolver(host, port, *args, **kwargs):
        if isinstance(host, str) and host.endswith(".test"):
            return resolver("93.184.216.34", port, *args, **kwargs)
        return resolver(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", local_only_resolver)
    monkeypatch.setattr(read, "_clock", fake.time)
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    return fake


def serve(monkeypatch, pages: dict) -> Site:
    site = Site({"https://docs.test/robots.txt": "User-agent: *\nDisallow: /private/\n", **pages})
    monkeypatch.setattr(net, "default_transport", site)
    return site


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = read.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def cached_files(tmp_path) -> list:
    return sorted((tmp_path / "cache" / "read").glob("*.json"))


ARTICLE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Setting Hangul in Body Text &mdash; Type Notes</title>
<style>body { font: 16px serif }</style><script>window.tracker = 1</script></head>
<body>
<header class="site"><a href="/">Type Notes</a><nav><a href="/archive">Archive</a> <a href="/about">About</a></nav></header>
<main>
<article>
<h1>Setting Hangul in Body Text</h1>
<p class="byline">By <a href="/people/kim">Kim</a>, 2026-09-20</p>
<p>Hangul body text wants <strong>more leading</strong> than Latin text, and <em>word-break: keep-all</em>
   keeps words whole.<br>A second line after a break.</p>
<h2>What to check</h2>
<ul>
  <li>Line height between 1.6 and 1.8
  <li>Word breaking
    <ol><li>keep-all for prose</li><li>normal for <code>code</code></li></ol>
  </li>
</ul>
<blockquote><p>Measure before you choose.</p><p>Then measure again.</p></blockquote>
<table>
  <caption>Suggested values</caption>
  <thead><tr><th>Use</th><th>Size</th><th>Leading</th></tr></thead>
  <tbody><tr><td>Body</td><td>16px</td><td>1.7</td></tr>
  <tr><td>Caption | small</td><td colspan="2">13px</td></tr></tbody>
</table>
<pre><code class="language-css">p {
  word-break: keep-all;
}</code></pre>
<p hidden>Hidden draft note</p>
<div style="display: none">Invisible promo</div>
<aside>Related: other posts</aside>
<form action="/subscribe"><label>Email <input type="email"></label><button>Subscribe</button></form>
<p>See the <a href="spec.html#leading">spec section</a> and <a href="https://other.test/x (y)">an outside page</a>.
   <a href="#top"><img src="up.png" alt="Back to top"></a></p>
<dl><dt>Leading</dt><dd>The space between lines.</dd><dt>Tracking</dt><dd>The space between letters.</dd></dl>
</article>
</main>
<footer><p>&copy; 2026 Type Notes</p></footer>
<script>document.write("x")</script>
</body></html>"""

ARTICLE_MARKDOWN = """# Setting Hangul in Body Text

Source: <https://docs.test/notes/hangul>

By [Kim](https://docs.test/people/kim), 2026-09-20

Hangul body text wants **more leading** than Latin text, and *word-break: keep-all* keeps words whole.
A second line after a break.

## What to check

- Line height between 1.6 and 1.8
- Word breaking
  1. keep-all for prose
  2. normal for `code`

> Measure before you choose.
>
> Then measure again.

Suggested values

| Use | Size | Leading |
| --- | --- | --- |
| Body | 16px | 1.7 |
| Caption \\| small | 13px |  |

```css
p {
  word-break: keep-all;
}
```

See the [spec section](https://docs.test/notes/spec.html#leading) and [an outside page](https://other.test/x%20%28y%29).

Leading
: The space between lines.

Tracking
: The space between letters."""


# ------------------------------------------------------------------------------------------------ reading

def test_an_article_becomes_markdown_through_the_polite_fetcher(monkeypatch, capsys):
    site = serve(monkeypatch, {"https://docs.test/notes/hangul": ARTICLE})
    code, out, err = run(capsys, "https://docs.test/notes/hangul")
    assert code == 0 and err == ""
    assert out == ARTICLE_MARKDOWN + "\n"
    assert site.urls() == ["https://docs.test/robots.txt", "https://docs.test/notes/hangul"]
    assert {agent for _, agent in site.log} == {net.USER_AGENT}

    result = read.read("https://docs.test/notes/hangul")
    assert result["cached"] and result["title"] == "Setting Hangul in Body Text — Type Notes"
    assert (result["status"], result["final_url"], result["rendered"]) == ("ok", "https://docs.test/notes/hangul", False)


def test_legacy_markup_encodings_and_noscript_fallbacks(monkeypatch, capsys):
    legacy = ("<html><head><meta http-equiv='Content-Type' content='text/html; charset=euc-kr'>"
              "<title>옛 게시판</title></head><body>"
              "<table width=100%><tr><td><a href=/>처음</a><td>"
              "<p>똠방각하 본문<p>둘째 문단 <b>굵게</b>"
              "<ul><li>하나<ul><li>안쪽</ul><li>둘</ul>"
              "<table><tr><td>가<td>나<tr><td>다<td>라</table>"
              "</table><noscript>스크립트 없이 보이는 글</noscript></body></html>")
    serve(monkeypatch, {"https://docs.test/board": net.Response(
        "https://docs.test/board", 200, {"content-type": "text/html"}, legacy.encode("cp949"))})
    code, out, _ = run(capsys, "https://docs.test/board")
    assert code == 0
    assert out == ("# 옛 게시판\n\nSource: <https://docs.test/board>\n\n[처음](https://docs.test/)\n\n"
                   "똠방각하 본문\n\n둘째 문단 **굵게**\n\n- 하나\n  - 안쪽\n- 둘\n\n"
                   "| 가 | 나 |\n| --- | --- |\n| 다 | 라 |\n\n스크립트 없이 보이는 글\n")


def test_plain_text_is_kept_and_other_types_are_not_read(monkeypatch, capsys):
    serve(monkeypatch, {"https://docs.test/notes.txt": "Line one\nLine two\n",
                        "https://docs.test/spec.pdf": net.Response(
                            "https://docs.test/spec.pdf", 200, {"content-type": "application/pdf"}, b"%PDF-1.7")})
    code, out, _ = run(capsys, "https://docs.test/notes.txt")
    assert code == 0 and out == "Source: <https://docs.test/notes.txt>\n\nLine one\nLine two\n"
    code, out, err = run(capsys, "https://docs.test/spec.pdf")
    assert code == 1 and out == "" and "is application/pdf, not a page lazuli reads" in err


def test_a_page_built_by_scripts_suggests_render(monkeypatch, capsys):
    serve(monkeypatch, {"https://docs.test/app": "<html><head><title>App</title></head><body><div id=root></div>"
                                                 "<script src=/app.js></script></body></html>"})
    code, _, err = run(capsys, "https://docs.test/app")
    assert code == 0 and "`--render` runs them" in err


@pytest.mark.parametrize("url", ["ftp://docs.test/a", "docs.test/a", "https://user:secret@docs.test/a"])
def test_unusable_urls_are_usage_errors(capsys, url):
    code, out, err = run(capsys, url)                     # the default transport would fail the test
    assert code == 2 and out == "" and err.startswith("lazuli read: ")

def test_malformed_input_host_is_a_usage_error(capsys):
    code, out, err = run(capsys, "http://[::1/x")
    assert code == 2 and out == ""
    assert "not an http or https URL" in err and "Traceback" not in err


@pytest.mark.parametrize("middle", ["..", "%2e%2e"])
def test_named_url_resolves_dots_before_robots_and_sends_no_private_request(monkeypatch, capsys, middle):
    site = serve(monkeypatch, {})
    code, out, err = run(capsys, f"https://docs.test/public/{middle}/private/x", "--json")
    result = json.loads(out)
    assert code == 1 and err == "" and result["status"] == "blocked"
    assert "disallows /private/x" in result["reason"]
    assert site.urls() == ["https://docs.test/robots.txt"]


def test_malformed_redirect_is_reported_as_blocked_without_traceback(monkeypatch, capsys):
    start = "https://docs.test/redirect"
    site = serve(monkeypatch, {start: net.Response(start, 302, {"location": "http://[::1/x"}, b"")})
    code, out, err = run(capsys, start)
    assert code == 1 and err == ""
    assert "redirect URL is malformed; request not sent" in out
    assert site.urls() == ["https://docs.test/robots.txt", start]

def test_corrupt_lazuli_database_is_one_line_input_error(tmp_path, capsys):
    (tmp_path / "lazuli.db").write_bytes(b"broken database")
    code, out, err = run(capsys, "https://docs.test/page")
    assert code == 2 and out == "" and err.startswith("lazuli read: could not open lazuli database:")
    assert len(err.splitlines()) == 1


def test_redirected_host_pace_persists_and_reference_preflight_shares_it(monkeypatch, capsys, clock):
    from lazuli.ref import common

    start, landing, next_page = "https://a.test/start", "https://b.test/landing", "https://b.test/next"
    site = serve(monkeypatch, {start: net.Response(start, 302, {"location": landing}, b""),
                               landing: "<html><body>Landing</body></html>",
                               next_page: "<html><body>Next</body></html>"})
    sent = []

    def tracked(url, headers):
        sent.append((url, clock.now))
        return site(url, headers)

    monkeypatch.setattr(net, "default_transport", tracked)
    assert run(capsys, start)[0] == 0
    arrival = next(at for url, at in sent if url == landing)
    net._last_request.clear()                 # emulate the next CLI process, retaining the DB
    clock.now = arrival + 1
    assert run(capsys, next_page)[0] == 0
    assert site.urls().count("https://b.test/robots.txt") == 2
    next_robots = [at for url, at in sent if url == "https://b.test/robots.txt"]
    assert next_robots[1] - arrival >= read.MIN_INTERVAL_S

    last_read = next(at for url, at in sent if url == next_page)
    net._last_request.clear()
    clock.now = last_read + 1
    _, response = common.fetch(next_page)
    assert response.url == next_page
    assert [at for url, at in sent if url == "https://b.test/robots.txt"][-1] - last_read >= common.MIN_INTERVAL_S


# ------------------------------------------------------------------------------------------------ refusals

REGISTRY = [
    {"id": "walled", "name": "Walled Type", "url": "https://walled.test/", "type": ["font"], "good_for": "x",
     "access": "refused", "terms_url": "https://walled.test/terms", "checked_at": "2026-09-26",
     "reason": "Its terms forbid automated access.", "clause": "Terms of Use, section 7"},
    {"id": "finder", "name": "Finder", "url": "https://finder.test/", "type": ["search"], "good_for": "x",
     "access": "browser-link", "terms_url": "https://finder.test/terms", "checked_at": "2026-09-26",
     "reason": "Search result pages are for people."},
]


@pytest.mark.parametrize("url, entry", [("https://www.walled.test/fonts/a", REGISTRY[0]),
                                        ("https://finder.test/search?q=serif", REGISTRY[1])], ids=["refused", "browser-link"])
def test_registry_refused_and_browser_link_sources_are_sent_nothing(monkeypatch, capsys, tmp_path, url, entry):
    monkeypatch.setattr(sources, "load_registry", lambda: REGISTRY)
    site = serve(monkeypatch, {})
    code, out, _ = run(capsys, url, "--json")
    result = json.loads(out)
    assert code == 1 and result["status"] == "refused" and result["browser_link"] == url
    assert result["reason"] == entry["reason"] and result["registry"]["access"] == entry["access"]
    code, out, _ = run(capsys, url, "--render")           # no browser is launched either
    assert code == 1 and f"open it in your browser: {url}" in out and f"terms: {entry['terms_url']}" in out
    assert ("(Terms of Use, section 7)" in out) == (entry["access"] == "refused")
    assert site.log == [] and cached_files(tmp_path) == []


def test_read_redirect_to_registry_refusal_never_fetches_target(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(sources, "load_registry", lambda: REGISTRY)
    start, target = "https://docs.test/start", "https://walled.test/landing"
    site = serve(monkeypatch, {start: net.Response(start, 302, {"location": target}, b"")})
    code, out, _ = run(capsys, start, "--json")
    result = json.loads(out)
    assert code == 1 and result["status"] == "blocked"
    assert target in result["reason"] and REGISTRY[0]["reason"] in result["reason"]
    assert result["browser_link"] == start
    assert site.urls() == ["https://docs.test/robots.txt", start]
    assert cached_files(tmp_path) == []

def test_read_redirect_to_unicode_registry_alias_never_sends_the_next_hop(monkeypatch, capsys):
    monkeypatch.setattr(sources, "load_registry", lambda: [
        {"id": "local", "url": "http://localhost/", "access": "refused", "reason": "Local host refused"}])
    start, target = "https://docs.test/start", "http://localhost。/landing"
    site = serve(monkeypatch, {start: net.Response(start, 302, {"location": target}, b"")})
    code, out, _ = run(capsys, start, "--json")
    assert code == 1 and json.loads(out)["status"] == "blocked"
    assert site.urls() == ["https://docs.test/robots.txt", start]


def test_read_unconvertible_host_is_refused_before_any_request(monkeypatch, capsys):
    site = serve(monkeypatch, {})
    url = "https://" + "x" * 64 + ".test/page"
    for render in ((), ("--render",)):
        code, out, _ = run(capsys, url, "--json", *render)
        result = json.loads(out)
        assert code == 1 and result["status"] == "refused" and "IDNA" in result["reason"]
    assert site.log == []


@pytest.mark.parametrize("url", ["https://noonnu.cc/font_page/366", "https://fonts.adobe.com/fonts/source-han-sans-korean"])
def test_the_shipped_registry_refuses_the_refused_catalogs(monkeypatch, capsys, url):
    site = serve(monkeypatch, {})
    code, out, _ = run(capsys, url, "--json")
    assert code == 1 and json.loads(out)["registry"]["access"] == "refused" and site.log == []


def test_a_robots_disallow_is_reported_with_the_browser_link(monkeypatch, capsys, tmp_path):
    site = serve(monkeypatch, {"https://docs.test/private/draft": ARTICLE})
    code, out, _ = run(capsys, "https://docs.test/private/draft")
    assert code == 1
    assert "blocked: robots.txt at https://docs.test disallows /private/draft" in out
    assert "open it in your browser: https://docs.test/private/draft" in out
    assert site.urls() == ["https://docs.test/robots.txt"] and cached_files(tmp_path) == []


SIGN_IN_FORM = ("<html><head><title>Members' notes</title></head><body><nav><a href=/>Home</a></nav>"
                "<main><h1>Members' notes</h1><p>Sign in to keep reading.</p>"
                "<form method=post><input name=user><input type=password name=pw><button>Go</button></form>"
                "</main></body></html>")


@pytest.mark.parametrize("page, reason", [
    (net.Response("https://docs.test/users/sign_in?next=%2Fnotes%2Fmembers", 200, {"content-type": "text/html"},
                  b"<html><body>Welcome back</body></html>"), "a sign-in page at https://docs.test/users/sign_in"),
    (SIGN_IN_FORM, "a sign-in form with little else to read at https://docs.test/notes/members"),
    (net.Response("https://docs.test/notes/members", 401, {}, b""), "401 Unauthorized"),
], ids=["redirected-to-sign-in", "sign-in-form-only", "401"])
def test_sign_in_walls_are_reported_not_read(monkeypatch, capsys, tmp_path, page, reason):
    serve(monkeypatch, {"https://docs.test/notes/members": page})
    code, out, _ = run(capsys, "https://docs.test/notes/members", "--json")
    result = json.loads(out)
    assert code == 1 and result["status"] == "blocked" and result["reason"].startswith(reason)
    assert result["browser_link"] == "https://docs.test/notes/members" and cached_files(tmp_path) == []


def test_a_sign_in_form_beside_an_article_is_not_a_wall(monkeypatch, capsys):
    page = SIGN_IN_FORM.replace("<p>Sign in to keep reading.</p>", "<p>Readable text for everyone. </p>" * 20)
    serve(monkeypatch, {"https://docs.test/notes/members": page})
    code, out, _ = run(capsys, "https://docs.test/notes/members")
    assert code == 0 and out.startswith("# Members' notes\n") and "Readable text for everyone." in out


# ------------------------------------------------------------------------------------------------ cache

def test_the_cache_answers_within_its_ttl_and_drops_expired_pages(monkeypatch, capsys, clock, tmp_path):
    site = serve(monkeypatch, {"https://docs.test/notes/hangul": ARTICLE, "https://docs.test/notes/other": ARTICLE})
    assert run(capsys, "https://docs.test/notes/hangul")[0] == 0
    [first] = cached_files(tmp_path)
    assert "Setting Hangul" in first.read_text(encoding="utf-8")

    clock.now += read.CACHE_TTL_S / 2
    code, out, err = run(capsys, "https://docs.test/notes/hangul")
    assert code == 0 and out == ARTICLE_MARKDOWN + "\n" and "from the cache" in err
    assert len(site.log) == 2                                   # robots.txt and the page, once

    clock.now += read.CACHE_TTL_S
    assert run(capsys, "https://docs.test/notes/other")[0] == 0
    assert not first.exists() and len(cached_files(tmp_path)) == 1  # the expired page is gone
    result = read.read("https://docs.test/notes/hangul")
    assert not result["cached"] and site.urls()[-1] == "https://docs.test/notes/hangul"


# ------------------------------------------------------------------------------------------------ --render

SHELL = ("<html><head><title>App</title><link rel=stylesheet href=/style.css></head><body>"
         "<div id=root><noscript>Turn on scripts</noscript></div><img src=/hero.png>"
         "<script src=https://cdn.test/lib.js></script><script src=/app.js></script>"
         "<script src=/private/track.js></script><script src=https://walled.test/widget.js></script></body></html>")
APP_JS = """
fetch('/api/log', {method: 'POST', body: 'seen'}).catch(() => {});
fetch('/api/post.json').then(r => r.json()).then(post => {
  document.getElementById('root').innerHTML =
    '<main><h1>' + post.title + '</h1><p>' + post.body + ' ' + window.libVersion + '</p></main>';
});
"""


def _script(url: str, text: str) -> net.Response:
    return net.Response(url, 200, {"content-type": "text/javascript"}, text.encode())


def test_render_runs_scripts_but_every_request_goes_through_the_fetcher(monkeypatch, browser):
    monkeypatch.setattr(sources, "load_registry", lambda: REGISTRY)
    site = serve(monkeypatch, {
        "https://docs.test/app": SHELL,
        "https://docs.test/app.js": _script("https://docs.test/app.js", APP_JS),
        "https://cdn.test/lib.js": _script("https://cdn.test/lib.js", "window.libVersion = 'lib 2';"),
        "https://docs.test/private/track.js": _script("https://docs.test/private/track.js", "window.tracked = 1;"),
        "https://docs.test/api/post.json": net.Response("https://docs.test/api/post.json", 200,
                                                        {"content-type": "application/json"},
                                                        b'{"title": "Built by scripts", "body": "Rendered body."}'),
        "https://docs.test/members": "<html><body><script>location.href = '/login'</script></body></html>",
        "https://docs.test/login": SIGN_IN_FORM})
    result = read.read("https://docs.test/app", render=True, browser=browser)
    assert result["status"] == "ok" and result["rendered"]
    assert result["markdown"] == ("# App\n\nSource: <https://docs.test/app>\n\n"
                                  "# Built by scripts\n\nRendered body. lib 2")
    assert sorted(site.urls()) == ["https://cdn.test/lib.js", "https://cdn.test/robots.txt", "https://docs.test/api/post.json",
                                   "https://docs.test/app", "https://docs.test/app.js", "https://docs.test/robots.txt"]
    assert {agent for _, agent in site.log} == {net.USER_AGENT}
    [note] = result["notes"]
    assert note.startswith("2 of the page's requests were not sent: ")
    assert "robots.txt at https://docs.test disallows /private/track.js" in note and REGISTRY[0]["reason"] in note

    walled = read.read("https://docs.test/members", render=True, browser=browser)
    assert walled["status"] == "blocked" and walled["reason"] == "a sign-in page at https://docs.test/login"


def test_render_redirected_script_host_shares_read_pace(monkeypatch, browser, clock):
    app = "https://docs.test/render-host"
    script, target = "https://asset.test/redirect.js", "https://asset.test/lib.js"
    next_page = "https://asset.test/next"
    site = serve(monkeypatch, {
        app: f"<html><body><main><h1>App</h1></main><script src='{script}'></script></body></html>",
        script: net.Response(script, 302, {"location": target}, b""),
        target: _script(target, "window.loaded = true"),
        next_page: "<html><body><main><h1>Next</h1></main></body></html>",
    })
    sent = []

    def tracked(url, headers):
        sent.append((url, clock.now))
        return site(url, headers)

    monkeypatch.setattr(net, "default_transport", tracked)
    result = read.read(app, render=True, browser=browser)
    assert result["status"] == "ok" and target in site.urls()
    previous = next(at for url, at in sent if url == target)
    net._last_request.clear()
    clock.now = previous + 1
    assert read.read(next_page)["status"] == "ok"
    assert next(at for url, at in sent if url == "https://asset.test/robots.txt" and at > previous) - previous >= (
        read.MIN_INTERVAL_S)

def test_render_public_page_cannot_read_private_fetch_even_with_cors(monkeypatch, browser):
    page = "http://pub.test:8123/page"
    secret = "http://127.0.0.1:8124/private"
    marker = "PRIVATE RESPONSE SHOULD NOT APPEAR"
    site = serve(monkeypatch, {
        page: ("<html><body><main><h1>Page</h1><div id='result'></div></main>"
               f"<script>fetch('{secret}').then(r => r.text()).then(t => "
               "document.getElementById('result').textContent = t).catch(() => {})</script></body></html>"),
        secret: net.Response(secret, 200, {"content-type": "text/plain",
                                           "access-control-allow-origin": "*"}, marker.encode()),
    })
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok"
    assert marker not in result["markdown"]
    assert all(not url.startswith("http://127.0.0.1:8124") for url in site.urls())

def test_render_redirect_hop_cannot_reach_private_address(monkeypatch, browser):
    page = "http://pub.test:8123/page"
    redirect = "http://pub.test:8123/redirect"
    secret = "http://127.0.0.1:8124/private"
    site = serve(monkeypatch, {
        page: ("<html><body><main><h1>Page</h1><div id='result'></div></main>"
               f"<script>fetch('{redirect}').then(r => r.text()).then(t => "
               "document.getElementById('result').textContent = t).catch(() => {})</script></body></html>"),
        redirect: net.Response(redirect, 302, {"location": secret}, b""),
        secret: net.Response(secret, 200, {"content-type": "text/plain",
                                           "access-control-allow-origin": "*"}, b"REDIRECTED PRIVATE RESPONSE"),
    })
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok" and "REDIRECTED PRIVATE RESPONSE" not in result["markdown"]
    assert redirect in site.urls()
    assert all(not url.startswith("http://127.0.0.1:8124") for url in site.urls())

def test_render_robots_redirect_hop_cannot_reach_private_address(monkeypatch, browser):
    page = "http://pub.test:8123/page"
    secret = "http://127.0.0.1:8124/robots.txt"
    site = serve(monkeypatch, {
        "http://pub.test:8123/robots.txt": net.Response(
            "http://pub.test:8123/robots.txt", 302, {"location": secret}, b""),
        page: "<html><body><main><h1>Page</h1></main></body></html>",
        secret: "User-agent: *\nAllow: /\n",
    })
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "blocked" and "local or private address" in result["reason"]
    assert site.urls() == ["http://pub.test:8123/robots.txt"]

def test_render_resolved_private_host_is_never_requested(monkeypatch, browser):
    page = "http://pub.test:8123/page"
    secret = "http://internal.test:8124/private"
    site = serve(monkeypatch, {
        page: ("<html><body><main><h1>Page</h1><div id='result'></div></main>"
               f"<script>fetch('{secret}').then(r => r.text()).then(t => "
               "document.getElementById('result').textContent = t).catch(() => {})</script></body></html>"),
        secret: net.Response(secret, 200, {"content-type": "text/plain",
                                           "access-control-allow-origin": "*"}, b"RESOLVED PRIVATE RESPONSE"),
    })
    resolve = socket.getaddrinfo

    def test_resolver(host, port, *args, **kwargs):
        return resolve("127.0.0.1" if host == "internal.test" else host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", test_resolver)
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok" and "RESOLVED PRIVATE RESPONSE" not in result["markdown"]
    assert all(not url.startswith("http://internal.test:8124") for url in site.urls())


def test_render_cross_origin_response_needs_cors_but_allowed_and_same_origin_work(monkeypatch, browser):
    page = "http://pub.test:8123/page"
    other = "http://other.test:8124"
    script = ("const root = document.getElementById('result');"
              "Promise.allSettled(["
              "fetch('/local').then(r => r.text()).then(t => root.append(t)),"
              f"fetch('{other}/denied').then(r => r.text()).then(t => root.append(t)),"
              f"fetch('{other}/allowed').then(r => r.text()).then(t => root.append(t))"
              "]);"
              "const xhr = new XMLHttpRequest();"
              "xhr.onload = () => root.append(xhr.responseText);"
              f"xhr.open('GET', '{other}/xhr-denied'); xhr.send();")
    site = serve(monkeypatch, {
        page: f"<html><body><main><h1>Page</h1><div id='result'></div></main><script>{script}</script></body></html>",
        "http://pub.test:8123/local": "SAME ORIGIN",
        other + "/denied": "CROSS ORIGIN LEAK",
        other + "/xhr-denied": "XHR CROSS ORIGIN LEAK",
        other + "/allowed": net.Response(other + "/allowed", 200, {"content-type": "text/plain",
                                                              "access-control-allow-origin": page.rsplit("/", 1)[0]},
                                          b"ALLOWED CROSS ORIGIN"),
    })
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok"
    assert "SAME ORIGIN" in result["markdown"] and "ALLOWED CROSS ORIGIN" in result["markdown"]
    assert "CROSS ORIGIN LEAK" not in result["markdown"]
    assert "XHR CROSS ORIGIN LEAK" not in result["markdown"]
    assert {other + "/denied", other + "/xhr-denied", other + "/allowed"} <= set(site.urls())

def test_render_cors_uses_final_response_origin_after_redirect(monkeypatch, browser):
    page = "http://pub.test:8123/page"
    redirect = "http://pub.test:8123/redirect"
    target = "http://other.test:8124/corsless"
    site = serve(monkeypatch, {
        page: ("<html><body><main><h1>Page</h1><div id='result'></div></main>"
               " <script>fetch('/redirect').then(r => r.text()).then(t => "
               "document.getElementById('result').textContent = t).catch(() => {})</script></body></html>"),
        redirect: net.Response(redirect, 302, {"location": target}, b""),
        target: "REDIRECTED CORS LEAK",
    })
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok" and "REDIRECTED CORS LEAK" not in result["markdown"]
    assert redirect in site.urls() and target in site.urls()


@pytest.mark.parametrize("module_kind", ["json", "dynamic", "redirect"])
@pytest.mark.parametrize("allowed", [False, True])
def test_render_module_imports_obey_cors_after_redirects(monkeypatch, browser, module_kind, allowed):
    page = "http://pub.test:8123/page"
    other = "http://other.test:8124"
    start = page.rsplit("/", 1)[0] + "/module.json"
    target = other + "/module.json"
    if module_kind == "dynamic":
        start, target = other + "/module.js", other + "/module.js"
    elif module_kind == "json":
        start = target
    if module_kind == "dynamic":
        script = f"import('{start}').then(m => document.querySelector('#result').textContent = m.default)"
        body, content_type = b"export default 'MODULE SECRET'", "text/javascript"
    else:
        script = (f"import data from '{start}' with {{type: 'json'}};"
                  "document.querySelector('#result').textContent = data.value")
        body, content_type = b'{"value": "MODULE SECRET"}', "application/json"
    headers = {"content-type": content_type}
    if allowed:
        headers["access-control-allow-origin"] = "*"
    site = serve(monkeypatch, {
        page: f"<html><body><main><h1>Page</h1><div id=result></div></main>"
              f"<script type=module>{script}</script></body></html>",
        start: net.Response(start, 302, {"location": target}, b"") if start != target else
               net.Response(start, 200, headers, body),
        target: net.Response(target, 200, headers, body),
    })
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok"
    assert ("MODULE SECRET" in result["markdown"]) is (allowed and module_kind != "redirect")
    assert target in site.urls()


@pytest.mark.parametrize("allowed", [False, True])
def test_render_crossorigin_classic_script_requires_cors(monkeypatch, browser, allowed):
    page = "http://pub.test:8123/page"
    script = "http://other.test:8124/widget.js"
    headers = {"content-type": "text/javascript"}
    if allowed:
        headers["access-control-allow-origin"] = "*"
    site = serve(monkeypatch, {
        page: (f"<html><body><main><h1>Page</h1><div id=result></div></main>"
               f"<script src='{script}' crossorigin=anonymous></script></body></html>"),
        script: net.Response(script, 200, headers, b"document.querySelector('#result').textContent='SCRIPT SECRET'"),
    })
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok"
    assert ("SCRIPT SECRET" in result["markdown"]) is allowed
    assert script in site.urls()


def test_render_refuses_given_private_page_before_launch(monkeypatch):
    site = serve(monkeypatch, {"http://127.0.0.1:8123/go": "<h1>PRIVATE</h1>"})
    monkeypatch.setattr(read, "_render_in_new_browser", lambda *args: pytest.fail("browser launched"))
    result = read.read("http://127.0.0.1:8123/go", render=True)
    assert result["status"] == "blocked"
    assert "lapis-design render check" in result["reason"]
    assert site.urls() == []


@pytest.mark.parametrize("address", [
    "100.64.0.1", "100.100.100.200", "::ffff:127.0.0.1", "::ffff:0:127.0.0.1",
    "::127.0.0.1", "64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe",
    "0.0.0.0", "::", "169.254.169.254", "224.0.0.1", "ff02::1",
])
def test_render_restricts_non_global_unicast_addresses(address):
    assert read._restricted_host(address)


def test_render_allows_public_unicast_address():
    assert not read._restricted_host("8.8.8.8")


@contextmanager
def loopback_site(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@contextmanager
def trap(kind: int):
    """A loopback socket that keeps what reaches it: TCP connections accepted or UDP datagrams received."""
    listener = socket.socket(socket.AF_INET, kind)
    listener.bind(("127.0.0.1", 0))
    if kind == socket.SOCK_STREAM:
        listener.listen(16)
    listener.settimeout(0.05)
    received, stop = [], Event()

    def collect():
        while not stop.is_set():
            try:
                received.append(listener.accept()[0] if kind == socket.SOCK_STREAM else listener.recvfrom(65535)[0])
            except socket.timeout:
                continue
            except OSError:
                return

    thread = Thread(target=collect, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1], received
    finally:
        stop.set()
        thread.join()
        listener.close()
        for item in received:
            if isinstance(item, socket.socket):
                item.close()


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_render_rebinding_is_blocked_after_connect(monkeypatch, clock, scheme):
    requested = []

    class Site(BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"SECRET REBIND RESPONSE")

        def log_message(self, *args):
            pass

    resolver = socket.getaddrinfo

    def rebinding(host, port, *args, **kwargs):
        if host == "rebind.test":
            host = "93.184.216.34" if port is None else "127.0.0.1"
        return resolver(host, port, *args, **kwargs)

    with loopback_site(Site) as base:
        monkeypatch.setattr(socket, "getaddrinfo", rebinding)
        monkeypatch.setattr(read, "_render_transport", clock.real_render_transport)
        assert not read._restricted_host("rebind.test")
        url = base.replace("127.0.0.1", "rebind.test").replace("http://", scheme + "://") + "/secret"
        with pytest.raises(net.Blocked, match="local or private address"):
            read._render_transport(url, {})
    assert requested == []


def test_render_rebinding_cannot_read_loopback_response(monkeypatch, clock, browser):
    requested = []

    class Site(BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append(self.path)
            self.send_response(404 if self.path == "/robots.txt" else 200)
            self.end_headers()
            if self.path != "/robots.txt":
                self.wfile.write(b"<html><body><main><h1>REBIND SECRET</h1></main></body></html>")

        def log_message(self, *args):
            pass

    resolver = socket.getaddrinfo

    def rebinding(host, port, *args, **kwargs):
        if host == "rebind.test":
            host = "93.184.216.34" if port is None else "127.0.0.1"
        return resolver(host, port, *args, **kwargs)

    with loopback_site(Site) as base:
        monkeypatch.setattr(socket, "getaddrinfo", rebinding)
        monkeypatch.setattr(net, "default_transport", REAL_TRANSPORT)
        monkeypatch.setattr(read, "_render_transport", clock.real_render_transport)
        result = read.read(base.replace("127.0.0.1", "rebind.test") + "/secret", render=True, browser=browser)
    assert result["status"] == "blocked" and "local or private address" in result["reason"]
    assert requested == []


@pytest.mark.parametrize("proxy", ["HTTPS_PROXY", "ALL_PROXY"])
def test_render_refuses_configured_proxy_before_launch(monkeypatch, capsys, proxy):
    monkeypatch.setenv(proxy, "http://127.0.0.1:1")
    monkeypatch.setattr(urllib.request, "getproxies", urllib.request.getproxies_environment)
    monkeypatch.setattr(read, "_render_in_new_browser", lambda *args: pytest.fail("browser launched"))
    code, out, err = run(capsys, "http://pub.test:8123/page", "--render")
    assert code == 2 and out == ""
    assert len(err.splitlines()) == 1 and "proxy" in err and "--render" in err


@pytest.mark.parametrize("render", [False, True])
def test_real_read_malformed_location_is_blocked_without_traceback(tmp_path, render):
    requested = []
    class Site(BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append(self.path)
            self.send_response(404 if self.path == "/robots.txt" else 302)
            if self.path != "/robots.txt":
                self.send_header("Location", "http://[::1/x")
            self.end_headers()

        def log_message(self, *args):
            pass

    with loopback_site(Site) as base:
        environment = {key: value for key, value in os.environ.items() if key.lower() not in
                       ("http_proxy", "https_proxy", "all_proxy")}
        environment["NO_PROXY"] = "127.0.0.1"
        environment["no_proxy"] = "127.0.0.1"
        environment["LAZULI_DB"] = str(tmp_path / "db.sqlite")
        command = [sys.executable, "-c", "from lazuli import read; raise SystemExit(read.main())",
                   base + "/page", *(["--render"] if render else [])]
        completed = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=12)
    assert completed.returncode == 1
    if render:
        assert requested == []
        assert len(completed.stdout.splitlines()) == 2
        assert completed.stdout.count("lapis-design render check") == 1
    else:
        assert "blocked: redirect URL is malformed; request not sent" in completed.stdout
    assert "Traceback" not in completed.stderr


@pytest.mark.parametrize("rule", ["prefetch", "prerender"])
def test_render_speculation_cannot_load_loopback_document(monkeypatch, browser, rule):
    requests = []
    marker = "SPECULATION PRIVATE CONTENT"

    class Site(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"<main><h1>{marker}</h1></main>".encode())

        def log_message(self, *args):
            pass

    with loopback_site(Site) as target:
        page = "https://pub.test/page"
        serve(monkeypatch, {page: (
            f"<main><h1>Public</h1></main><script type=speculationrules>"
            f'{{"{rule}":[{{"source":"list","urls":["{target}/private"]}}]}}'
            f"</script><script>setTimeout(() => location.href='{target}/private', 400)</script>")})
        result = read.read(page, render=True, browser=browser)
    assert requests == []
    assert result["status"] == "blocked"
    assert marker not in result.get("markdown", "")


def test_render_history_change_keeps_served_document(monkeypatch, browser):
    page = "https://pub.test/page"
    serve(monkeypatch, {page: "<main><h1>Original content</h1></main>"
                              "<script>history.replaceState(null, '', '/page?from=home')</script>"})
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok"
    assert "Original content" in result["markdown"]


SPOOFED_DOCUMENT = {
    "outerHTML": "<!doctype html><title>Real title</title><main><h1>Real heading</h1></main><script>"
                 "Object.defineProperty(Element.prototype, 'outerHTML', "
                 "{get() { return '<main><h1>Spoofed heading</h1></main>'; }});</script>",
    "serializer": "<!doctype html><title>Real title</title><main><h1>Real heading</h1></main><script>"
                  "XMLSerializer.prototype.serializeToString = () => '<title>Spoofed title</title>';</script>",
    "navigation-entry": "<title>Real title</title><main><h1>Real heading</h1></main><script>"
                        "performance.getEntriesByType = () => [{name: {href: 'https://pub.test/page'}}];</script>",
}


@pytest.mark.parametrize("spoof", SPOOFED_DOCUMENT)
def test_render_reads_the_document_beyond_the_reach_of_the_page_scripts(monkeypatch, browser, spoof):
    page = "https://pub.test/page"
    serve(monkeypatch, {page: SPOOFED_DOCUMENT[spoof]})
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok"
    assert "Real heading" in result["markdown"] and "Spoofed heading" not in result["markdown"]
    assert result["title"] == "Real title"


@pytest.mark.parametrize("value", [
    {"url": {"href": "https://pub.test/page"}, "html": "<main><h1>Not read</h1></main>"},
    {"url": "https://pub.test/page", "html": 7},
    "https://pub.test/page",
], ids=["address-is-an-object", "html-is-a-number", "not-an-object"])
def test_render_result_that_is_not_text_is_a_one_line_error(monkeypatch, browser, value):
    from playwright.sync_api import CDPSession

    page = "https://pub.test/page"
    serve(monkeypatch, {page: "<main><h1>Real heading</h1></main>"})
    send = CDPSession.send

    def send_with_another_answer(self, method, params=None):
        answer = send(self, method, params)
        return {**answer, "result": {"type": "object", "value": value}} if method == "Runtime.evaluate" else answer

    monkeypatch.setattr(CDPSession, "send", send_with_another_answer)
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "error" and "\n" not in result["reason"]
    assert "address and HTML" in result["reason"] and "Not read" not in json.dumps(result)


# A page keeps its network busy for about a second, so what the browser does on the side has time to
# reach a trap before the render reads the page.
_TICKS = """
let ticks = 0;
const tick = () => fetch('/tick').then(() => {
  if (++ticks < 5) setTimeout(tick, 250); else finish();
});
tick();
"""
PEER_PAGE = """<main><h1>Public</h1><p id=result></p></main><script>
const report = {types: [], candidates: 0, error: 'none'};
try {
  const realm = __REALM__;
  for (const name of ['RTCPeerConnection', 'webkitRTCPeerConnection', 'RTCDataChannel', 'WebTransport']) {
    report.types.push(name + ':' + typeof realm[name]);
  }
  const Peer = realm.RTCPeerConnection || realm.webkitRTCPeerConnection;
  if (Peer) {
    const peer = new Peer({iceCandidatePoolSize: 2, iceServers: __SERVERS__});
    peer.onicecandidate = event => { if (event.candidate) report.candidates++; };
    peer.createDataChannel('probe');
    peer.createOffer().then(offer => peer.setLocalDescription(offer));
  }
} catch (error) { report.error = error.name; }
const finish = () => document.querySelector('#result').textContent =
  'REPORT ' + report.types.join(' ') + ' candidates:' + report.candidates + ' error:' + report.error;
""" + _TICKS + "</script>"
PEER_REALMS = {
    "main": "window",
    "iframe": "(() => { const f = document.createElement('iframe'); document.body.appendChild(f); "
              "return f.contentWindow; })()",
    "popup": "window.open('about:blank')",
}
NO_PEER_API = {"RTCPeerConnection": "undefined", "webkitRTCPeerConnection": "undefined",
               "RTCDataChannel": "undefined", "WebTransport": "undefined", "candidates": "0", "error": "none"}


def _peer_report(result: dict) -> dict[str, str]:
    line = next(line for line in result["markdown"].splitlines() if line.startswith("REPORT "))
    return dict(token.split(":") for token in line.removeprefix("REPORT ").split())


def _render_peer_page(monkeypatch, browser, realm: str, servers: list[dict]) -> dict:
    page = "https://pub.test/page"
    serve(monkeypatch, {
        page: PEER_PAGE.replace("__REALM__", PEER_REALMS[realm]).replace("__SERVERS__", json.dumps(servers)),
        "https://pub.test/tick": "tick"})
    return read.read(page, render=True, browser=browser)


@pytest.mark.parametrize("realm", ["main", "iframe", "popup"])
def test_render_peer_connections_send_no_udp(monkeypatch, browser, realm):
    with trap(socket.SOCK_DGRAM) as (port, datagrams):
        result = _render_peer_page(monkeypatch, browser, realm, [
            {"urls": [f"stun:127.0.0.1:{port}"]},
            {"urls": [f"turn:127.0.0.1:{port}", f"turn:127.0.0.1:{port}?transport=udp"],
             "username": "user", "credential": "secret"}])
    assert result["status"] == "ok"
    assert datagrams == [], f"{len(datagrams)} datagrams reached the loopback UDP trap"
    assert _peer_report(result) == NO_PEER_API


@pytest.mark.parametrize("realm", ["main", "iframe", "popup"])
def test_render_turn_over_tcp_connects_to_nothing(monkeypatch, browser, realm):
    # A pin: TURN over TCP already reached no connection before peer connections were removed.
    with trap(socket.SOCK_STREAM) as (port, connections):
        result = _render_peer_page(monkeypatch, browser, realm, [
            {"urls": [f"turn:127.0.0.1:{port}?transport=tcp", f"turns:127.0.0.1:{port}?transport=tcp"],
             "username": "user", "credential": "secret"}])
    assert result["status"] == "ok"
    assert _peer_report(result) == NO_PEER_API          # the page's script ran and found nothing to connect with
    assert connections == []


WORKER_TRANSPORT_PAGE = """<main><h1>Public</h1><p id=result></p></main><script>
const worker = new Worker(__SOURCE__);
worker.onmessage = event => { document.querySelector('#result').textContent = 'REPORT ' + event.data; };
const finish = () => {};
""" + _TICKS + "</script>"


def _render_worker_transport(monkeypatch, browser, source: str) -> list:
    """Render a page whose dedicated worker opens a WebTransport session to a loopback UDP trap; a worker
    runs no init script, so its WebTransport constructor stays. Returns the datagrams the trap received."""
    with trap(socket.SOCK_DGRAM) as (port, datagrams):
        code = ("const report = {WebTransport: typeof WebTransport, error: 'none'};"
                f"try {{ const transport = new WebTransport('https://127.0.0.1:{port}/');"
                "transport.ready.catch(() => {}); transport.closed.catch(() => {}); }"
                "catch (error) { report.error = error.name; }"
                "postMessage('WebTransport:' + report.WebTransport + ' error:' + report.error);")
        address = {"url": "'https://pub.test/transport.js'",
                   "blob": f"URL.createObjectURL(new Blob([{json.dumps(code)}], {{type: 'text/javascript'}}))"}[source]
        page = "https://pub.test/page"
        serve(monkeypatch, {page: WORKER_TRANSPORT_PAGE.replace("__SOURCE__", address),
                            "https://pub.test/transport.js": _script("https://pub.test/transport.js", code),
                            "https://pub.test/tick": "tick"})
        result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok"
    assert _peer_report(result) == {"WebTransport": "function", "error": "none"}    # the worker made its attempt
    return datagrams


@pytest.mark.parametrize("source", ["url", "blob"])
def test_render_worker_webtransport_sends_no_udp(monkeypatch, browser, source):
    datagrams = _render_worker_transport(monkeypatch, browser, source)
    assert datagrams == [], f"{len(datagrams)} datagrams reached the loopback UDP trap"


@pytest.fixture
def browser_without_network_checks(browser):
    """A browser that applies no local-network or cross-origin checks of its own, so nothing but the
    render's proxy stands between a page and the loopback trap."""
    unchecked = browser.browser_type.launch(args=["--disable-web-security"])
    try:
        yield unchecked
    finally:
        unchecked.close()


@pytest.mark.parametrize("source", ["url", "blob"])
def test_render_proxy_alone_keeps_worker_webtransport_from_udp(monkeypatch, browser_without_network_checks, source):
    datagrams = _render_worker_transport(monkeypatch, browser_without_network_checks, source)
    assert datagrams == [], f"{len(datagrams)} datagrams reached the loopback UDP trap"


REDIRECT_SPELLINGS = [  # Location, the URL lazuli's join gave before, the URL the browser requests
    ("/page?q=it's", "https://pub.test/page?q=it's", "https://pub.test/page?q=it%27s"),
    ("https://PUB.test/page", "https://PUB.test/page", "https://pub.test/page"),
    ("/한글", "https://pub.test/한글", "https://pub.test/%ED%95%9C%EA%B8%80"),
    ("https://pub.test:443/page", "https://pub.test:443/page", "https://pub.test/page"),
    ("/a b", "https://pub.test/a b", "https://pub.test/a%20b"),
    pytest.param("/%ED%95%9C%EA%B8%80", "https://pub.test/%ED%95%9C%EA%B8%80",
                 "https://pub.test/%ED%95%9C%EA%B8%80", id="pre-encoded-pin"),
]


@pytest.mark.parametrize("location, joined, requested", REDIRECT_SPELLINGS)
def test_render_given_page_redirect_reads_the_final_page_once_in_any_spelling(
        monkeypatch, browser, location, joined, requested):
    start, final = "https://pub.test/go", "<main><h1>Final page</h1></main>"
    site = serve(monkeypatch, {start: net.Response(start, 302, {"location": location}, b""),
                               joined: final, requested: final})
    result = read.read(start, render=True, browser=browser)
    assert result["status"] == "ok" and "Final page" in result["markdown"]
    assert sum(url in (joined, requested) for url in site.urls()) == 1


def _redirecting_site(location: str, served: str, requested: list[str]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append(self.path)
            if self.path == "/go":  # the Location goes out as UTF-8 bytes, as servers send it
                self.wfile.write(b"HTTP/1.1 302 Found\r\nLocation: " + location.encode()
                                 + b"\r\nContent-Length: 0\r\n\r\n")
                return
            body = b"<html><body><main><h1>Final page</h1></main></body></html>"
            self.send_response(200 if self.path == served else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return Handler


def _wire_transport(base: str, host: str | None = None):
    """The real urllib/http.client transport; `host` (a URL prefix) is served from `base`."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), net._NoRedirect())

    def transport(url, headers):
        wire = net._transport(url.replace(host, base) if host else url, headers, opener)
        return net.Response(url, wire.status, wire.headers, wire.body)

    return transport


UNENCODED_LOCATIONS = [("/한글", "/%ED%95%9C%EA%B8%80"), ("/a b", "/a%20b")]


@pytest.mark.parametrize("location, served", UNENCODED_LOCATIONS)
def test_real_read_follows_an_unencoded_location(monkeypatch, capsys, location, served):
    requested = []
    with loopback_site(_redirecting_site(location, served, requested)) as base:
        monkeypatch.setattr(net, "default_transport", _wire_transport(base))
        code, out, err = run(capsys, base + "/go")
    assert code == 0 and "Final page" in out, (out, err)
    assert requested.count(served) == 1


@pytest.mark.parametrize("location, served", UNENCODED_LOCATIONS)
def test_real_render_follows_an_unencoded_location(monkeypatch, browser, location, served):
    requested = []
    monkeypatch.setattr(read, "RENDER_TIMEOUT_MS", 20_000)  # a failing run ends in seconds, not two minutes
    with loopback_site(_redirecting_site(location, served, requested)) as base:
        monkeypatch.setattr(net, "default_transport", _wire_transport(base, "https://pub.test"))
        result = read.read("https://pub.test/go", render=True, browser=browser)
    assert result["status"] == "ok" and "Final page" in result["markdown"]
    assert requested.count(served) == 1


def test_render_notes_a_same_origin_redirect_that_starts_after_the_page_settled(monkeypatch, browser):
    from playwright.sync_api import BrowserContext

    page, late, landing = "https://pub.test/page", "https://pub.test/late", "https://pub.test/landing"
    serve(monkeypatch, {page: "<main><h1>Settled document</h1></main>",
                        late: net.Response(late, 302, {"location": "/landing"}, b""),
                        landing: "<main><h1>Landing</h1></main>"})
    new_cdp_session, started = BrowserContext.new_cdp_session, []

    def session_after_a_late_navigation(self, target):
        if not started:  # the render's one read of the final document opens a session: a navigation starts just before
            started.append(True)
            target.evaluate("location.href = '/late'")
            target.wait_for_timeout(300)
        return new_cdp_session(self, target)

    monkeypatch.setattr(BrowserContext, "new_cdp_session", session_after_a_late_navigation)
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok" and "Settled document" in result["markdown"]
    assert any(landing in note for note in result["notes"])


SHARED_WORKER_PAGE = """<main><h1>Public</h1><p id=result></p></main><script>
const realm = __FRAME__ === 'iframe' ? (() => {
  const frame = document.createElement('iframe');
  document.body.appendChild(frame);
  return frame.contentWindow;
})() : window;
const out = document.querySelector('#result');
try {
  const worker = new realm.SharedWorker(__SOURCE__);
  worker.port.onmessage = event => { out.textContent += ' ' + event.data; };
  out.textContent = 'attempt: constructed';
} catch (error) { out.textContent = 'attempt: ' + error.name; }
const finish = () => {};
""" + _TICKS + "</script>"


@pytest.mark.parametrize("frame", ["main", "iframe"])
@pytest.mark.parametrize("source", ["url", "blob", "data"])
def test_render_shared_worker_cannot_connect_to_loopback(monkeypatch, browser, source, frame):
    with trap(socket.SOCK_STREAM) as (port, connections):
        code = ("const ports = [];"  # onconnect first, so a worker that got out could hand back what it read
                "self.onconnect = event => { ports.push(event.ports[0]); event.ports[0].postMessage('connected'); };"
                f"fetch('http://127.0.0.1:{port}/secret').then(r => r.text())"
                ".then(text => ports.forEach(p => p.postMessage(text)), () => {});")
        address = {"url": "'https://pub.test/sw.js'",
                   "blob": f"URL.createObjectURL(new Blob([{json.dumps(code)}], {{type: 'text/javascript'}}))",
                   "data": f"'data:text/javascript,' + encodeURIComponent({json.dumps(code)})"}[source]
        page = "https://pub.test/page"
        serve(monkeypatch, {
            page: SHARED_WORKER_PAGE.replace("__FRAME__", json.dumps(frame)).replace("__SOURCE__", address),
            "https://pub.test/sw.js": _script("https://pub.test/sw.js", code),
            "https://pub.test/tick": "tick"})
        result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok" and "attempt:" in result["markdown"]  # the page ran its attempt
    assert connections == [], f"{len(connections)} connections reached the loopback TCP trap"


@pytest.mark.parametrize("script_kind", ["classic", "worker", "module-worker"])
def test_render_redirected_executable_is_not_served_cross_origin(monkeypatch, browser, script_kind):
    page = "https://pub.test/page"
    script, other = "https://pub.test/code.js", "https://other.test/secret.js"
    payload = ("document.querySelector('#result').textContent='EXECUTED REDIRECT'"
               if script_kind == "classic" else "self.postMessage('EXECUTED REDIRECT')")
    options = ', {type: "module"}' if script_kind == "module-worker" else ""
    snippet = (f"<script src='{script}'></script>" if script_kind == "classic" else
               f"<script>let w=new Worker('{script}'{options});"
               "w.onmessage=e=>document.querySelector('#result').textContent=e.data</script>")
    site = serve(monkeypatch, {
        page: f"<main><h1>Page</h1><p id=result></p></main>{snippet}",
        script: net.Response(script, 302, {"location": other}, b""),
        other: _script(other, payload)})
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok"
    assert "EXECUTED REDIRECT" not in result["markdown"]
    assert script in site.urls() and other in site.urls()
    assert any("redirect leaves the requested origin" in note for note in result["notes"])


def test_render_given_page_redirect_runs_under_final_origin(monkeypatch, browser):
    start, final, data = "https://pub.test/go", "https://other.test/page", "https://pub.test/data"
    site = serve(monkeypatch, {
        start: net.Response(start, 302, {"location": final}, b""),
        final: ("<main><h1>Page</h1><p id=origin></p><p id=result></p></main><script>"
                "document.querySelector('#origin').textContent=location.origin;"
                f"fetch('{data}').then(r=>r.text()).then(t=>"
                "document.querySelector('#result').textContent=t).catch(()=>{})</script>"),
        data: "UNAUTHORIZED CROSS ORIGIN CONTENT"})
    result = read.read(start, render=True, browser=browser)
    assert result["status"] == "ok"
    assert "https://other.test" in result["markdown"]
    assert "UNAUTHORIZED CROSS ORIGIN CONTENT" not in result["markdown"]
    assert site.urls().count(final) == 1


def test_render_given_scheme_and_host_redirect_keeps_relative_fetch(monkeypatch, browser):
    start, final = "http://pub.test/", "https://www.pub.test/"
    serve(monkeypatch, {
        start: net.Response(start, 301, {"location": final}, b""),
        final: ("<main><h1>Page</h1><p id=result></p></main><script>"
                "fetch('/api').then(r=>r.text()).then(t=>document.querySelector('#result').textContent=t)"
                "</script>"),
        "https://www.pub.test/api": "RELATIVE DATA"})
    result = read.read(start, render=True, browser=browser)
    assert result["status"] == "ok" and "RELATIVE DATA" in result["markdown"]


def test_render_later_same_origin_redirect_uses_final_document_url(monkeypatch, browser):
    start, moved, final = "https://pub.test/nav", "https://pub.test/moved", "https://pub.test/dir/landing"
    site = serve(monkeypatch, {
        start: ("<main><h1>Original</h1></main>"
                "<script>setTimeout(() => location.href='/moved', 100)</script>"),
        moved: net.Response(moved, 302, {"location": final}, b""),
        final: ("<main><h1>Landing</h1><p id=result></p></main><script>"
                "fetch('api').then(r=>r.text()).then(t=>document.querySelector('#result').textContent="
                "location.pathname + ' ' + t)</script>"),
        "https://pub.test/dir/api": "FINAL RELATIVE DATA",
    })
    result = read.read(start, render=True, browser=browser)
    assert result["status"] == "ok"
    assert "/dir/landing FINAL RELATIVE DATA" in result["markdown"]
    assert site.urls().count(final) == 1


def test_render_later_navigation_cross_origin_redirect_is_aborted(monkeypatch, browser):
    start, moved, landing = "https://pub.test/nav", "https://pub.test/moved", "https://other.test/landing"
    data = "https://pub.test/data"
    site = serve(monkeypatch, {
        start: ("<main><h1>Original</h1></main>"
                "<script>setTimeout(() => location.href='/moved', 100)</script>"),
        moved: net.Response(moved, 302, {"location": landing}, b""),
        landing: ("<main><h1>Landing</h1><p id=result></p></main><script>"
                  f"fetch('{data}').then(r=>r.text()).then(t=>"
                  "document.querySelector('#result').textContent=t)</script>"),
        data: "LEAK AFTER NAVIGATION"})
    result = read.read(start, render=True, browser=browser)
    assert "LEAK AFTER NAVIGATION" not in result.get("markdown", "")
    assert landing in site.urls() and data not in site.urls()


@pytest.mark.browser
def test_render_websocket_completes_without_deadlock(tmp_path):
    script = """
from lazuli import read
from lazuli.catalog import net
import socket
real = socket.getaddrinfo
socket.getaddrinfo = lambda host, port, *args, **kwargs: real(
    "93.184.216.34" if isinstance(host, str) and host.endswith(".test") else host, port, *args, **kwargs)
def transport(url, headers):
    if url.endswith("/robots.txt"):
        return net.Response(url, 404, {"content-type": "text/plain"}, b"")
    return net.Response(url, 200, {"content-type": "text/html"},
                        b"<main><h1>Socket page</h1></main><script>new WebSocket('wss://pub.test/ws')</script>")
read._render_transport = transport
result = read.read("https://pub.test/page", render=True)
assert result["status"] == "ok", result
"""
    environment = {key: value for key, value in os.environ.items() if key.lower() not in
                   ("http_proxy", "https_proxy", "all_proxy")}
    environment["LAZULI_DB"] = str(tmp_path / "db.sqlite")
    result = subprocess.run([sys.executable, "-c", script], env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_render_resolved_private_given_page_is_blocked_before_launch(monkeypatch):
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *args, **kwargs: (
        real("127.0.0.1", port, *args, **kwargs) + real("93.184.216.34", port, *args, **kwargs)
        if host == "private.test" else real(host, port, *args, **kwargs)))
    monkeypatch.setattr(read, "_render_in_new_browser", lambda *args: pytest.fail("browser launched"))
    result = read.read("https://private.test/page", render=True)
    assert result["status"] == "blocked" and "lapis-design render check" in result["reason"]


def test_render_malformed_redirect_location_is_blocked_in_process(monkeypatch, browser):
    page = "https://pub.test/page"
    serve(monkeypatch, {page: net.Response(page, 302, {"location": "http://[::1/x"}, b"")})
    result = read.read(page, render=True, browser=browser)
    assert result["status"] == "blocked" and "redirect URL is malformed" in result["reason"]
@pytest.mark.parametrize("duplicate", [False, True])
def test_render_cors_header_must_be_one_trimmed_value(monkeypatch, browser, duplicate):
    page, data = "https://pub.test/page", "https://other.test/data"

    class Site(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", " https://pub.test ")
            if duplicate:
                self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"CORS RESPONSE CONTENT")

        def log_message(self, *args):
            pass

    with loopback_site(Site) as server:
        recorded = serve(monkeypatch, {
            page: ("<main><h1>Public</h1><p id=result></p></main>"
                   f"<script>fetch('{data}').then(r=>r.text()).then(t=>"
                   "document.querySelector('#result').textContent=t).catch(()=>{})</script>")})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), net._NoRedirect())

        def transport(url, headers):
            if url == data:
                wire = net._transport(server + "/data", headers, opener)
                return net.Response(url, wire.status, wire.headers, wire.body)
            return recorded(url, headers)

        monkeypatch.setattr(net, "default_transport", transport)
        result = read.read(page, render=True, browser=browser)
    assert result["status"] == "ok"
    assert ("CORS RESPONSE CONTENT" in result["markdown"]) is not duplicate




def test_read_encodes_apostrophe_in_query_for_browser_capture():
    assert read.normalize("http://127.0.0.1:8123/?q=it's").endswith("/?q=it%27s")
