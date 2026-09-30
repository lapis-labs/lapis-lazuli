"""`lazuli read URL`: one page the user asked for, as readable Markdown.

Rules:
- The source registry decides first (`lazuli.sources.find`): a source marked `refused` or `browser-link`
  is never requested; the answer is the registry's reason, the terms, and the browser link.
- Every request goes through `catalog/net.py`: robots.txt, the lazuli User-Agent, a human pace per host
  kept across runs in the lazuli database (source `read:<host>`), and a stop on 401/403/429, CAPTCHA, or
  sign-in pages. A page that is only a sign-in form (a password field and little else to read) is a
  sign-in wall too. Blocks are reported with the browser link; lazuli never signs in or gets around one.
- Without --render the HTML as served is converted and nothing runs. With --render a headless browser runs
  the page's own scripts, and every request it makes still goes through a paced Fetcher: GET only, the
  page document, scripts, XHR, and fetch. Images, fonts, media, stylesheets, frames, popups, service
  workers, websockets, and peer connections (WebRTC, WebTransport) are never loaded. CORS responses are
  checked for requests with Origin and for XHR/fetch; every page and redirect hop must resolve
  exclusively to global unicast addresses.
- The Markdown keeps the title, headings, paragraphs, lists, tables, quotes, code, and links, taken from
  the page's one main or article element when it has one. Navigation, asides, footers, forms, dialogs,
  and hidden elements are dropped.
- Answers are cached in the user cache (`<cache>/read/`, never a project) for CACHE_TTL_S; expired
  entries are deleted on every run. Blocks, refusals, and failures are never cached.

Exit codes: 0 read; 1 refused, blocked, or failed (open the browser link, or try again later);
2 usage (not an http(s) URL, a URL with credentials, no browser for --render).
"""
from __future__ import annotations

import argparse
import codecs
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from lazuli import db, paths, sources
from lazuli.catalog import net

MIN_INTERVAL_S = 3.0              # between page requests to one host, the catalog adapters' pace
RENDER_INTERVAL_S = 1.0           # between the requests of a render (page, scripts, data) to one host
CACHE_TTL_S = 24 * 3600
RENDER_TIMEOUT_MS = 120_000       # the navigation, with every request paced
SETTLE_TIMEOUT_MS = 30_000        # waiting for the page's own requests to stop
LOGIN_WALL_MAX_CHARS = 400        # a password field with fewer readable characters than this is a wall
SCRIPT_HINT_MAX_CHARS = 200       # fewer characters than this from a page with scripts suggests --render
ACCEPT = "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.8"
READABLE_ACCESS = ("read", "adapter")
RENDER_TYPES = ("document", "script", "xhr", "fetch")

_clock = time.time                # replaced by tests (fake clock)


class UsageError(Exception):
    """Input lazuli cannot use: exit 2."""


class ReadError(Exception):
    """The page could not be read: exit 1."""


# ------------------------------------------------------------------------------------------------ url

def normalize(url: str) -> str:
    """The URL the browser requests, with its fragment dropped; refuse unusable command URLs."""
    try:
        return net.browser_url(url)
    except net.InvalidURL as exc:
        if exc.kind == "host":
            # Registry refusals remain a refused (exit 1) result, not a malformed command (exit 2).
            raise UnicodeError(str(exc)) from exc
        if exc.kind == "credentials":
            raise UsageError("the URL carries a user name or password; lazuli never signs in, so remove it") from exc
        if exc.kind == "malformed" and exc.detail == "a bad port":
            raise UsageError(f"bad port in {url}") from exc
        raise UsageError(f"not an http or https URL: {url}") from exc


def _origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


_NAT64_PREFIX = ipaddress.IPv6Network("64:ff9b::/96")


def _restricted_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        elif address in _NAT64_PREFIX or (int(address) >> 32) in (0, 0xffff, 0xffff0000):
            address = ipaddress.IPv4Address(int(address) & 0xffffffff)
    return not address.is_global or address.is_multicast


def _restricted_host(host: str) -> bool:
    """Whether a host is or resolves to a non-global unicast address."""
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(answer[4][0])
                         for answer in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]
        except OSError:
            raise net.Blocked(f"could not resolve {host}; request not sent") from None
    return any(_restricted_address(address) for address in addresses)



class _PeerCheckedConnection:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        create_connection = self._create_connection

        def checked_connection(*connect_args, **connect_kwargs):
            sock = create_connection(*connect_args, **connect_kwargs)
            try:
                if _restricted_address(ipaddress.ip_address(sock.getpeername()[0])):
                    raise net.Blocked("request to a local or private address is not allowed; request not sent")
            except Exception:
                sock.close()
                raise
            return sock

        self._create_connection = checked_connection


class _CheckedHTTPConnection(_PeerCheckedConnection, http.client.HTTPConnection):
    pass


class _CheckedHTTPSConnection(_PeerCheckedConnection, http.client.HTTPSConnection):
    pass



class _CheckedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self):
        super().__init__()
        self.connection = _CheckedHTTPConnection

    def http_open(self, req):
        return self.do_open(self.connection, req)


class _CheckedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self):
        super().__init__()
        self.connection = _CheckedHTTPSConnection

    def https_open(self, req):
        return self.do_open(self.connection, req)


def _render_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), net._NoRedirect(), _CheckedHTTPHandler(),
        _CheckedHTTPSHandler())


_render_checked_opener = _render_opener()


def _render_transport(url: str, headers: dict[str, str]) -> net.Response:
    """Fetch directly, checking the connected peer before HTTP bytes or TLS are sent."""
    return net._transport(url, headers, _render_checked_opener)


def _frame_origin(frame_url: str, page_url: str) -> str:
    if frame_url.startswith(("about:blank", "about:srcdoc", "blob:", "data:")):
        return _origin(page_url)
    return _origin(frame_url)


def _same_document_url(first: str, second: str) -> bool:
    """Whether two spellings of an http(s) URL are the one URL the browser requests."""
    try:
        return net.browser_url(first) == net.browser_url(second)
    except ValueError:
        return False


def refusal(entry: dict | None) -> str | None:
    """Why the registry keeps lazuli from requesting a source, or None when it may be read."""
    if entry is None or entry.get("access") in READABLE_ACCESS:
        return None
    return entry.get("reason") or f"the source registry marks {entry.get('name') or entry['id']} `{entry['access']}`"


# ------------------------------------------------------------------------------------------------ fetch

@dataclass
class Fetched:
    url: str                      # the final URL, after redirects
    kind: str                     # html | text
    text: str


_CHARSET_ALIASES = {  # labels browsers read as a wider encoding (WHATWG Encoding)
    "euc-kr": "cp949", "ks_c_5601-1987": "cp949", "iso-8859-1": "cp1252", "latin1": "cp1252",
    "us-ascii": "cp1252", "ascii": "cp1252", "shift_jis": "cp932", "gb2312": "gbk"}
_META_CHARSET = re.compile(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([\w.:-]+)", re.I)


def _decode(response: net.Response) -> str:
    """The body as text: a UTF-8 BOM, then the header charset, then a <meta> charset, then UTF-8."""
    body = response.body
    if body.startswith(codecs.BOM_UTF8):
        return body[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace")
    header = re.search(r"charset=\s*[\"']?([\w.:-]+)", response.headers.get("content-type", ""), re.I)
    meta = _META_CHARSET.search(body[:4096])
    for label in (header and header.group(1), meta and meta.group(1).decode("ascii")):
        if label:
            try:
                return body.decode(_CHARSET_ALIASES.get(label.lower(), label), errors="replace")
            except LookupError:
                continue
    return body.decode("utf-8", errors="replace")


def _kind(response: net.Response) -> str:
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type in ("text/html", "application/xhtml+xml") or (
            not content_type and response.body.lstrip()[:1] == b"<"):
        return "html"
    if content_type.startswith("text/"):
        return "text"
    raise ReadError(f"{response.url} is {content_type or 'an unknown type'}, not a page lazuli reads "
                    "(HTML or plain text)")


def _fetch(url: str, conn) -> Fetched:
    host = urllib.parse.urlsplit(url).hostname
    response = net.Fetcher(f"read:{host}", min_interval_s=MIN_INTERVAL_S, conn=conn).get(
        url, headers={"Accept": ACCEPT})
    return Fetched(response.url, _kind(response), _decode(response))


# Removed in every frame and popup: SharedWorker (its requests bypass the route handler), and the peer
# connections (STUN and TURN over UDP do not use the proxy). A dedicated worker runs no init script and
# keeps WebTransport; the proxy alone stops it.
_RENDER_INIT_SCRIPT = """
    delete globalThis.SharedWorker;
    delete globalThis.RTCPeerConnection;
    delete globalThis.webkitRTCPeerConnection;
    delete globalThis.RTCDataChannel;
    delete globalThis.WebTransport;
"""
# The final document's URL and HTML, evaluated in one expression so both come from the same document.
# The address is the navigation entry's name, which `history.replaceState` does not change.
_FINAL_DOCUMENT = """(() => ({
    url: performance.getEntriesByType('navigation')[0]?.name || '',
    html: (document.doctype ? new XMLSerializer().serializeToString(document.doctype) : '')
        + (document.documentElement ? document.documentElement.outerHTML : '')}))()"""


def _read_final_document(context, page) -> tuple[str, str]:
    """The main frame's address and HTML in one evaluation inside an isolated world: the page's scripts
    run in another world and cannot change `outerHTML`, `XMLSerializer`, or `performance` for it."""
    cdp = context.new_cdp_session(page)
    frame = cdp.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
    world = cdp.send("Page.createIsolatedWorld", {"frameId": frame, "worldName": "lazuli-read"})
    result = cdp.send("Runtime.evaluate", {"expression": _FINAL_DOCUMENT, "returnByValue": True,
                                           "contextId": world["executionContextId"]})
    value = result.get("result", {}).get("value")
    fields = value if isinstance(value, dict) else {}
    address, html = fields.get("url"), fields.get("html")
    if "exceptionDetails" in result or not isinstance(address, str) or not isinstance(html, str):
        raise ReadError("the browser did not return the rendered page's address and HTML as text")
    return address, html


def _render(browser, url: str, conn, notes: list[str]) -> Fetched:
    """Run the page's scripts in `browser`, sending each request through a paced Fetcher per host."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    registry = sources.load_registry()            # every host the page reaches is checked, not only its own
    fetchers: dict[str, net.Fetcher] = {}
    state: dict = {"page": None, "blocked": None, "failed": None, "redirect": None, "first_navigation": True}
    skipped: list[str] = []

    def check_hop(hop_url: str) -> None:
        if _restricted_host(urllib.parse.urlsplit(hop_url).hostname or ""):
            raise net.Blocked(f"request to a local or private address is not allowed; request not sent: {hop_url}")

    def fetch(request_url: str) -> net.Response:
        if reason := refusal(sources.find(request_url, registry)):
            raise net.Blocked(reason)
        origin = _origin(request_url)
        if origin not in fetchers:
            host = urllib.parse.urlsplit(request_url).hostname
            fetchers[origin] = net.Fetcher(f"read:{host}", min_interval_s=RENDER_INTERVAL_S, conn=conn,
                                           transport=_render_transport)
        return fetchers[origin].get(request_url, check=check_hop)

    def handle(route, request) -> None:
        try:
            frame = request.frame
        except PlaywrightError:
            # Some worker requests have no frame; without a page association, do not serve them.
            route.abort()
            return
        main = frame.parent_frame is None and request.is_navigation_request()
        if (frame.page is not page or request.method != "GET" or request.resource_type not in RENDER_TYPES
                or (request.resource_type == "document" and not main)):
            route.abort()
            return
        initial_request = main and state["first_navigation"]
        if main:
            state["first_navigation"] = False
        try:
            if main and state["redirect"] is not None and _same_document_url(request.url, state["redirect"].url):
                pending = state["redirect"]
                # Served under the URL the browser asked for, so it is not taken for a redirect again.
                response = net.Response(request.url, pending.status, pending.headers, pending.body)
                state["redirect"] = None
            else:
                response = fetch(request.url)
            kind = _kind(response) if main else None
        except net.Blocked as exc:
            if main:
                state["blocked"] = exc.reason
            else:
                skipped.append(exc.reason)
            route.abort("aborted" if main else "blockedbyclient")
            return
        except (ReadError, net.FetchError, OSError, http.client.HTTPException) as exc:
            if main:
                state["failed"] = str(exc)
            route.abort()
            return
        if response.url != request.url and initial_request:
            state["redirect"] = response
            route.abort("aborted")
            return
        if response.url != request.url and main:
            if _origin(response.url) != _origin(request.url):
                skipped.append(f"main-frame redirect leaves the requested origin: {request.url}")
            else:
                state["redirect"] = response
            route.abort("aborted")
            return
        if not main and _origin(response.url) != _origin(request.url):
            skipped.append(f"redirect leaves the requested origin: {request.url}")
            route.abort()
            return
        # Chromium associates worker requests with a frame too; the request Origin, when
        # present, takes precedence over the frame's URL for CORS checks.
        origin_header = request.headers.get("origin")
        cors_request = origin_header is not None or request.resource_type in ("xhr", "fetch")
        request_origin = (origin_header if origin_header is not None else
                          _frame_origin(frame.url, state["page"][0].url if state["page"] else url))
        allow_origin = response.headers.get("access-control-allow-origin")
        if (cors_request and request_origin != _origin(response.url)
                and allow_origin not in (request_origin, "*")):
            route.abort()
            return
        if main:
            state["page"] = (response, kind)
        headers = {key: response.headers[key] for key in ("content-type", "access-control-allow-origin")
                   if key in response.headers}
        route.fulfill(status=response.status, headers=headers, body=response.body)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as guard:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: no other process may share this port
                guard.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            guard.bind(("127.0.0.1", 0))  # No listener: browser-only requests fail immediately.
            port = guard.getsockname()[1]
            context = browser.new_context(
                user_agent=net.USER_AGENT, service_workers="block", accept_downloads=False,
                proxy={"server": f"http://127.0.0.1:{port}", "bypass": "<-loopback>"})
            try:
                context.route("**/*", handle)
                context.route_web_socket("**/*", lambda ws: None)
                context.add_init_script(_RENDER_INIT_SCRIPT)
                page = context.new_page()
                try:
                    page.goto(url, wait_until="commit", timeout=RENDER_TIMEOUT_MS)
                    navigation_error = None
                except PlaywrightError as exc:  # an aborted initial redirect or a script navigation
                    navigation_error = str(exc).splitlines()[0]
                for _ in range(net.MAX_REDIRECTS + 2):
                    if state["redirect"] is not None:
                        pending = state["redirect"]
                        try:
                            page.goto(pending.url, wait_until="commit", timeout=RENDER_TIMEOUT_MS)
                            navigation_error = None
                        except PlaywrightError as exc:
                            navigation_error = str(exc).splitlines()[0]
                            if state["redirect"] is pending:
                                if state["blocked"]:
                                    raise net.Blocked(state["blocked"])
                                raise ReadError(state["failed"] or navigation_error)
                    try:
                        page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
                    except PlaywrightTimeout:
                        notes.append(f"the page was still loading after {SETTLE_TIMEOUT_MS // 1000} s; "
                                     "this is what it showed by then")
                    if state["redirect"] is None:
                        break
                else:
                    raise net.Blocked("main-frame redirect limit reached; no result was read")
                if state["blocked"]:
                    raise net.Blocked(state["blocked"])
                if state["page"] is None:
                    raise ReadError(state["failed"] or navigation_error or f"the browser showed no page for {url}")
                response, kind = state["page"]
                final_url, html = _read_final_document(context, page)
                if urllib.parse.urldefrag(final_url).url != urllib.parse.urldefrag(response.url).url:
                    raise net.Blocked("the main frame did not finish on the document lazuli served")
                fetched = Fetched(response.url, kind, html if kind == "html" else _decode(response))
                if state["redirect"] is not None:
                    notes.append(f"the page started a navigation to {state['redirect'].url} after it settled; "
                                 "lazuli did not follow it, so this is the document before it")
            finally:
                context.close()
    except PlaywrightError as exc:
        raise ReadError(f"the browser failed: {str(exc).splitlines()[0]}") from None
    if skipped:
        notes.append(f"{len(skipped)} of the page's requests were not sent: " + "; ".join(dict.fromkeys(skipped)))
    if fetched.kind == "html" and (reason := net.blocked_reason(
            net.Response(fetched.url, 200, {"content-type": "text/html"}, fetched.text.encode()))):
        raise net.Blocked(reason)
    return fetched


def _render_in_new_browser(url: str, conn, notes: list[str]) -> Fetched:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except PlaywrightError as exc:
            raise UsageError(f"no browser for --render ({str(exc).splitlines()[0]}); run "
                             "`uv run playwright install chromium-headless-shell`") from None
        try:
            return _render(browser, url, conn, notes)
        finally:
            browser.close()


# ------------------------------------------------------------------------------------------------ html

VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
HEADINGS = frozenset(f"h{n}" for n in range(1, 7))
BLOCKS = HEADINGS | frozenset(
    """address article aside blockquote body caption center dd details dialog dir div dl dt fieldset
    figcaption figure footer form header hgroup hr html legend li main menu nav ol p pre section summary
    table tbody td tfoot th thead tr ul""".split())
SKIP = frozenset(
    """aside audio button canvas datalist dialog embed footer form frame frameset head iframe input map
    math nav noscript object option script select style svg template textarea video""".split())
SKIP_ROLES = frozenset("alertdialog complementary contentinfo dialog menu menubar navigation search toolbar".split())
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)

# Tree building: the parts of the HTML parsing rules that shape readable text (implied end tags, scopes)
_SCOPE = frozenset("applet caption html marquee object table td template th".split())
_CLOSES_P = HEADINGS | frozenset(
    """address article aside blockquote center dd details dialog dir div dl dt fieldset figcaption figure
    footer form header hgroup hr li main menu nav ol p pre section summary table ul""".split())
_TABLE_TAGS = frozenset("caption table tbody td tfoot th thead tr".split())
_IMPLIED = {  # start tag: (open elements it closes, elements that stop the search)
    "li": ({"li"}, _SCOPE | {"ol", "ul", "menu"}),
    "dt": ({"dt", "dd"}, _SCOPE | {"dl"}),
    "dd": ({"dt", "dd"}, _SCOPE | {"dl"}),
    "tr": ({"tr"}, {"table", "thead", "tbody", "tfoot", "html"}),
    "td": ({"td", "th"}, {"tr", "table", "html"}),
    "th": ({"td", "th"}, {"tr", "table", "html"}),
    "thead": ({"thead", "tbody", "tfoot"}, {"table", "html"}),
    "tbody": ({"thead", "tbody", "tfoot"}, {"table", "html"}),
    "tfoot": ({"thead", "tbody", "tfoot"}, {"table", "html"}),
    "a": ({"a"}, _SCOPE),
}


class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: dict[str, str]):
        self.tag, self.attrs, self.children = tag, attrs, []


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#document", {})
        self.stack = [self.root]

    def _close(self, tags, boundary) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            tag = self.stack[index].tag
            if tag in tags:
                del self.stack[index:]
                return
            if tag in boundary:
                return

    def _open(self, tag: str, attrs) -> _Node:
        if tag in _CLOSES_P:
            self._close({"p"}, _SCOPE | {"button"})
        if tag in HEADINGS and self.stack[-1].tag in HEADINGS:
            self.stack.pop()
        if rule := _IMPLIED.get(tag):
            self._close(*rule)
        node = _Node(tag, {name: value or "" for name, value in attrs})
        self.stack[-1].children.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        node = self._open(tag, attrs)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ("body", "html"):                 # content after </body> still belongs to the body
            return
        for index in range(len(self.stack) - 1, 0, -1):
            open_tag = self.stack[index].tag
            if open_tag == tag:
                del self.stack[index:]
                return
            if open_tag in _SCOPE and not (tag in _TABLE_TAGS and open_tag in ("td", "th", "caption")):
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _walk(node: _Node, prune: frozenset[str] = frozenset()):
    """Elements under `node` in document order, not descending into `prune` tags."""
    stack = list(reversed(node.children))
    while stack:
        child = stack.pop()
        if isinstance(child, _Node):
            yield child
            if child.tag not in prune:
                stack.extend(reversed(child.children))


def _space(text: str) -> str:
    return re.sub(r"[ \t\n\r\f\u00a0]+", " ", text)


def _clean(text: str) -> str:
    """Inline text as lines: spaces collapsed, lines trimmed, at most one empty line in a row."""
    lines: list[str] = []
    for line in text.split("\n"):
        line = re.sub(r" {2,}", " ", line).strip()
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip("\n")


def _keep_space(inner: str, markdown: str) -> str:
    return (" " if inner[:1].isspace() else "") + markdown + (" " if inner[-1:].isspace() else "")


def _wrap(inner: str, mark: str) -> str:
    core = inner.strip()
    return _keep_space(inner, f"{mark}{core}{mark}") if core else inner


def _code(inner: str) -> str:
    core = inner.strip()
    if not core:
        return inner
    ticks = "`" * (max((len(run) for run in re.findall(r"`+", core)), default=0) + 1)
    pad = " " if core.startswith("`") or core.endswith("`") else ""
    return _keep_space(inner, f"{ticks}{pad}{core}{pad}{ticks}")


def _quote(blocks: list[str]) -> list[str]:
    text = "\n\n".join(blocks)
    return ["\n".join(f"> {line}" if line else ">" for line in text.split("\n"))] if text else []


def _int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        return min(max(int((value or "").strip()), low), high)
    except ValueError:
        return default


def _raw_text(node: _Node) -> str:
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag == "br":
            parts.append("\n")
        elif child.tag not in ("script", "style", "template"):
            parts.append(_raw_text(child))
    return "".join(parts).replace("\r\n", "\n").replace("\u00a0", " ")


class _Markdown:
    def __init__(self, base: str, skip: frozenset[str]):
        self.base, self.skip = base, skip

    def skipped(self, node: _Node) -> bool:
        attrs = node.attrs
        return (node.tag in self.skip or "hidden" in attrs or attrs.get("aria-hidden", "").strip() == "true"
                or attrs.get("role", "").strip().lower() in SKIP_ROLES
                or bool(_HIDDEN_STYLE.search(attrs.get("style", ""))))

    # -------------------------------------------------------------- blocks
    def blocks(self, node: _Node) -> list[str]:
        out: list[str] = []
        run: list[str] = []

        def flush():
            if text := _clean("".join(run)):
                out.append(text)
            run.clear()

        for child in node.children:
            if isinstance(child, str):
                run.append(_space(child))
            elif self.skipped(child):
                continue
            elif child.tag in BLOCKS:
                flush()
                out.extend(self.block(child))
            else:
                run.append(self.inline(child))
        flush()
        return out

    def block(self, node: _Node) -> list[str]:
        tag = node.tag
        if tag in HEADINGS:
            text = " ".join(self.inline_children(node).split())
            return [f"{'#' * int(tag[1])} {text}"] if text else []
        if tag in ("ul", "ol", "menu", "dir"):
            return self.list(node, ordered=tag == "ol")
        if tag == "pre":
            return self.pre(node)
        if tag == "blockquote":
            return _quote(self.blocks(node))
        if tag == "table":
            return self.table(node)
        if tag == "dl":
            return self.definitions(node)
        if tag == "hr":
            return ["---"]
        return self.blocks(node)

    def list(self, node: _Node, *, ordered: bool) -> list[str]:
        items: list[tuple[_Node, bool]] = []          # (item, loose): loose items gather what sits outside <li>
        for child in node.children:
            if isinstance(child, _Node) and child.tag == "li":
                items.append((child, False))
            else:
                if not items or not items[-1][1]:
                    items.append((_Node("li", {}), True))
                items[-1][0].children.append(child)
        number = _int(node.attrs.get("start"), 1, -10**9, 10**9) if ordered else 0
        lines: list[str] = []
        pad = ""
        for item, loose in items:
            if self.skipped(item) or not (content := self.blocks(item)):
                continue
            text = "\n".join(content).split("\n")
            if loose and lines and all((isinstance(c, str) and not c.strip()) or (
                    isinstance(c, _Node) and c.tag in ("ul", "ol")) for c in item.children):
                lines.extend(pad + line if line else "" for line in text)   # a list nested without its <li>
                continue
            marker = f"{number}." if ordered else "-"
            number += 1
            pad = " " * (len(marker) + 1)
            lines.append(f"{marker} {text[0]}")
            lines.extend(pad + line if line else "" for line in text[1:])
        return ["\n".join(lines)] if lines else []

    def pre(self, node: _Node) -> list[str]:
        text = _raw_text(node).strip("\n").rstrip()
        if not text.strip():
            return []
        language = ""
        for candidate in (node, *(c for c in node.children if isinstance(c, _Node) and c.tag == "code")):
            if found := re.search(r"\b(?:language|lang)-([\w+#.-]+)", candidate.attrs.get("class", "")):
                language = found.group(1)
                break
        fence = "`" * max(3, max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
        return [f"{fence}{language}\n{text}\n{fence}"]

    def table(self, node: _Node) -> list[str]:
        caption: list[str] = []
        rows: list[list[_Node]] = []

        def collect(parent: _Node) -> None:
            for child in parent.children:
                if not isinstance(child, _Node) or self.skipped(child):
                    continue
                if child.tag == "caption":
                    caption.extend(self.blocks(child))
                elif child.tag in ("thead", "tbody", "tfoot"):
                    collect(child)
                elif child.tag == "tr":
                    cells = [c for c in child.children
                             if isinstance(c, _Node) and c.tag in ("td", "th") and not self.skipped(c)]
                    if cells:
                        rows.append(cells)

        collect(node)
        width = max((sum(_int(c.attrs.get("colspan"), 1, 1, 50) for c in row) for row in rows), default=0)
        if width < 2 or len(rows) < 2 or any(
                d.tag == "table" for row in rows for cell in row for d in _walk(cell)):
            out = list(caption)                      # a layout table: its cells in reading order
            for row in rows:
                for cell in row:
                    out.extend(self.blocks(cell))
            return out
        lines = []
        for index, row in enumerate(rows):
            cells: list[str] = []
            for cell in row:
                cells.append(" ".join(" ".join(self.blocks(cell)).split()).replace("|", "\\|"))
                cells.extend([""] * (_int(cell.attrs.get("colspan"), 1, 1, 50) - 1))
            cells.extend([""] * (width - len(cells)))
            lines.append("| " + " | ".join(cells) + " |")
            if index == 0:
                lines.append("|" + " --- |" * width)
        return [*caption, "\n".join(lines)]

    def definitions(self, node: _Node) -> list[str]:
        lines: list[str] = []
        last = None
        terms = (c for child in node.children if isinstance(child, _Node) and not self.skipped(child)
                 for c in (child.children if child.tag == "div" else [child]))   # <dl><div><dt>…
        for child in terms:
            if not isinstance(child, _Node) or child.tag not in ("dt", "dd") or self.skipped(child):
                continue
            if not (text := " ".join(" ".join(self.blocks(child)).split())):
                continue
            if child.tag == "dt":
                if last == "dd":
                    lines.append("")
                lines.append(text)
            else:
                lines.append(f": {text}")
            last = child.tag
        return ["\n".join(lines)] if lines else []

    # -------------------------------------------------------------- inline
    def inline_children(self, node: _Node, in_link: bool = False) -> str:
        parts = []
        for child in node.children:
            if isinstance(child, str):
                parts.append(_space(child))
            elif not self.skipped(child):
                part = self.inline(child, in_link)
                parts.append(f" {part} " if child.tag in BLOCKS else part)
        return "".join(parts)

    def inline(self, node: _Node, in_link: bool = False) -> str:
        tag = node.tag
        if tag == "br":
            return "\n"
        if tag == "img":
            return _space(node.attrs.get("alt", "")) if in_link else ""
        if tag == "a" and not in_link:
            return self.link(node)
        inner = self.inline_children(node, in_link)
        if tag in ("strong", "b"):
            return _wrap(inner, "**")
        if tag in ("em", "i"):
            return _wrap(inner, "*")
        if tag in ("del", "s", "strike"):
            return _wrap(inner, "~~")
        if tag in ("code", "kbd", "samp", "tt"):
            return _code(inner)
        return inner

    def link(self, node: _Node) -> str:
        href = self.href(node.attrs.get("href"))
        if href is None:                                # not a link to another page: its text only
            return self.inline_children(node)
        inner = self.inline_children(node, in_link=True)
        label = " ".join(inner.split()) or " ".join(
            (node.attrs.get("aria-label") or node.attrs.get("title") or "").split())
        if not label:
            return ""
        if label == href:
            return _keep_space(inner, f"<{href}>")
        return _keep_space(inner, "[" + label.replace("[", "\\[").replace("]", "\\]") + f"]({href})")

    def href(self, value: str | None) -> str | None:
        value = (value or "").strip()
        if not value or value.startswith("#"):
            return None
        try:
            url = urllib.parse.urljoin(self.base, value)
            scheme = urllib.parse.urlsplit(url).scheme.lower()
        except ValueError:
            return None
        if scheme not in ("http", "https", "mailto", "tel"):
            return None
        for raw, encoded in ((" ", "%20"), ("(", "%28"), (")", "%29"), ("<", "%3C"), (">", "%3E")):
            url = url.replace(raw, encoded)
        return url


@dataclass
class Document:
    title: str | None             # the <title>
    markdown: str
    chars: int                    # letters and digits a reader sees, link targets excluded
    sign_in_form: bool            # a password field anywhere on the page
    scripts: bool


def convert(html: str, url: str, *, scripted: bool = False) -> Document:
    """Readable Markdown from `html` served at `url`. `scripted`: the HTML came from a browser that ran
    scripts, so <noscript> content is not shown; without scripts it is."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    root = builder.root
    elements = list(_walk(root, prune=frozenset({"svg", "math", "template"})))
    title = next((" ".join(_raw_text(e).split()) for e in elements if e.tag == "title"), None) or None
    base = next((urllib.parse.urljoin(url, e.attrs["href"]) for e in elements
                 if e.tag == "base" and e.attrs.get("href")), url)
    mains = [e for e in elements if e.tag == "main" or e.attrs.get("role", "").strip().lower() == "main"]
    articles = [e for e in elements if e.tag == "article"]
    content = (mains[0] if len(mains) == 1 else articles[0] if len(articles) == 1
               else next((e for e in elements if e.tag == "body"), root))
    renderer = _Markdown(base, SKIP if scripted else SKIP - {"noscript"})
    try:
        blocks = renderer.blocks(content)
    except RecursionError:
        raise ReadError(f"{url} nests its elements too deeply to read") from None
    heading = None
    if blocks and blocks[0].startswith("# "):
        first = blocks[0][2:].strip()
        if not title or first.casefold() in title.casefold() or title.casefold() in first.casefold():
            heading, blocks = first, blocks[1:]
    body = "\n\n".join(blocks)
    markdown = f"# {heading or title or url}\n\nSource: <{url}>" + (f"\n\n{body}" if body else "")
    return Document(
        title=title,
        markdown="\n".join(line.rstrip() for line in markdown.split("\n")),
        chars=len(re.findall(r"\w", re.sub(r"\]\([^)\s]*\)|<[a-z]+:[^>\s]*>", "]", body))),
        sign_in_form=any(e.tag == "input" and e.attrs.get("type", "").strip().lower() == "password"
                         for e in elements),
        scripts=any(e.tag == "script" for e in elements))


# ------------------------------------------------------------------------------------------------ cache

def _cache_path(url: str, rendered: bool) -> Path:
    key = hashlib.sha256(f"{'render' if rendered else 'static'} {url}".encode()).hexdigest()
    return paths.cache_dir() / "read" / f"{key}.json"


def _prune(now: float) -> None:
    """Delete every expired or unreadable cache entry, so copied page text never outlives its ttl."""
    folder = paths.cache_dir() / "read"
    if not folder.is_dir():
        return
    for path in folder.glob("*.json"):
        try:
            expires = float(json.loads(path.read_text(encoding="utf-8"))["expires"])
        except (OSError, ValueError, KeyError, TypeError):
            expires = 0.0
        if expires <= now:
            path.unlink(missing_ok=True)


def _cached(url: str, rendered: bool, now: float) -> dict | None:
    try:
        entry = json.loads(_cache_path(url, rendered).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return entry["result"] if entry.get("expires", 0) > now else None


def _store(url: str, rendered: bool, result: dict, expires: float) -> None:
    path = _cache_path(url, rendered)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.stem}.{os.getpid()}.tmp")
    partial.write_text(json.dumps({"expires": expires, "result": result}, ensure_ascii=False), encoding="utf-8")
    os.replace(partial, path)


def _iso(moment: float) -> str:
    return datetime.fromtimestamp(moment, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ------------------------------------------------------------------------------------------------ read

def read(url: str, *, render: bool = False, browser=None) -> dict:
    """Read one page. The result's `status` is ok, refused (registry), blocked (the site), or error.

    `browser`: a Playwright browser for --render; one is launched when it is None.
    """
    try:
        target = normalize(url)
    except UnicodeError:
        target = url  # sources.find refuses hosts that cannot convert to IDNA.
    if render and any(scheme in urllib.request.getproxies() for scheme in ("http", "https", "all")):
        raise UsageError("a configured proxy prevents --render from checking connected addresses; "
                         "disable the proxy or read without --render")
    entry = sources.find(target)
    if reason := refusal(entry):
        return {"status": "refused", "url": target, "reason": reason, "browser_link": target,
                "registry": {key: entry[key] for key in ("id", "name", "access", "terms_url", "clause") if entry.get(key)}}
    if render:
        try:
            if _restricted_host(urllib.parse.urlsplit(target).hostname or ""):
                return {"status": "blocked", "url": target, "browser_link": target,
                        "reason": "a local or private page cannot be rendered; use `lapis-design render check` "
                                  "to render your own page"}
        except net.Blocked as exc:
            return {"status": "blocked", "url": target, "browser_link": target, "reason": exc.reason}
    now = _clock()
    _prune(now)
    if (hit := _cached(target, render, now)) is not None:
        return {**hit, "cached": True}
    notes: list[str] = []
    if entry and entry.get("adapter"):
        notes.append(f"lazuli's `{entry['adapter']}` catalog adapter covers {entry.get('name') or entry['id']}; "
                     "`lazuli catalog` keeps its data in the local database")
    try:
        conn = db.connect(paths.db_path())
    except (sqlite3.Error, OSError, RuntimeError) as exc:
        raise UsageError(f"could not open lazuli database: {exc}") from exc
    try:
        if not render:
            fetched = _fetch(target, conn)
        elif browser is not None:
            fetched = _render(browser, target, conn, notes)
        else:
            fetched = _render_in_new_browser(target, conn, notes)
    except net.Blocked as exc:
        return {"status": "blocked", "url": target, "reason": exc.reason, "browser_link": target}
    except (ReadError, net.FetchError, OSError, http.client.HTTPException) as exc:
        return {"status": "error", "url": target, "reason": str(exc)}
    except sqlite3.Error as exc:
        raise UsageError(f"lazuli database error: {exc}") from exc
    finally:
        conn.close()
    if fetched.kind == "html":
        try:
            document = convert(fetched.text, fetched.url, scripted=render)
        except ReadError as exc:
            return {"status": "error", "url": target, "reason": str(exc)}
        if document.sign_in_form and document.chars < LOGIN_WALL_MAX_CHARS:
            return {"status": "blocked", "url": target, "browser_link": target,
                    "reason": f"a sign-in form with little else to read at {fetched.url}"}
        if not render and document.scripts and document.chars < SCRIPT_HINT_MAX_CHARS:
            notes.append("the page shows little text without its scripts; `--render` runs them")
        title, markdown = document.title, document.markdown
    else:
        title, markdown = None, f"Source: <{fetched.url}>\n\n{fetched.text.strip()}"
    fetched_at = _clock()
    result = {"status": "ok", "url": target, "final_url": fetched.url, "title": title, "markdown": markdown,
              "rendered": render, "registry": {"id": entry["id"], "access": entry["access"]} if entry else None,
              "notes": notes, "fetched_at": _iso(fetched_at), "expires_at": _iso(fetched_at + CACHE_TTL_S)}
    _store(target, render, result, fetched_at + CACHE_TTL_S)
    return {**result, "cached": False}


def _report(result: dict, prog: str, *, as_json: bool) -> int:
    status = result["status"]
    code = {"ok": 0, "usage": 2}.get(status, 1)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    if status == "ok":
        print(result["markdown"])
        for note in result["notes"]:
            print(f"{prog}: note: {note}", file=sys.stderr)
        if result["cached"]:
            print(f"{prog}: from the cache: fetched {result['fetched_at']}, kept until {result['expires_at']}",
                  file=sys.stderr)
    elif status == "refused":
        registry = result["registry"]
        print(f"{prog}: {registry.get('name') or registry['id']} is `{registry['access']}` in the source registry: "
              f"{result['reason']}")
        if terms := registry.get("terms_url"):
            print(f"terms: {terms}" + (f" ({registry['clause']})" if registry.get("clause") else ""))
        print(f"open it in your browser: {result['browser_link']}")
    elif status == "blocked":
        print(f"{prog}: blocked: {result['reason']}")
        print(f"lazuli does not get around blocks or sign in; open it in your browser: {result['browser_link']}")
    else:
        print(f"{prog}: {result['reason']}", file=sys.stderr)
    return code


def main(argv: list[str] | None = None, prog: str = "lazuli read") -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n")[0].split(": ", 1)[1])
    ap.add_argument("url", help="the page to read (http or https)")
    ap.add_argument("--render", action="store_true",
                    help="run the page's own scripts in a headless browser first, for pages built by scripts")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    try:
        result = read(args.url, render=args.render)
    except UsageError as exc:
        result = {"status": "usage", "url": args.url, "reason": str(exc)}
    return _report(result, prog, as_json=args.json)
