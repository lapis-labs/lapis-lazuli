"""Polite HTTP for catalog adapters: robots.txt, human pace, the lazuli User-Agent, and stop on a block.

Rules (binding for every source):
- robots.txt is read once per host per Fetcher; a disallowed path, or a robots.txt answered with 401,
  403, or a server error, raises Blocked. Other 4xx answers mean there is no robots.txt.
- Catalog adapters keep their source id as the pace key. `read` uses `read:<hop host>` for each
  request, including redirects and robots.txt. `ref` uses both `ref` and `read:<hop host>`. Requests
  are at least max(min_interval_s, Crawl-delay, Request-rate) apart, measured from the end of the
  last request on each key. Last-request times are kept per process and, with a database, in `meta`
  so the pace also holds across runs.
- 401, 403, 429, a CAPTCHA or bot-challenge page, and a sign-in page raise Blocked; the caller marks
  the source failed and never retries around it. Other HTTP errors raise FetchError.
- Redirects are followed by hand (at most five): before each hop the source registry and that host's
  robots.txt decide whether the request may be sent. Refused/browser-link hosts, blocked paths, and
  credential-bearing redirect URLs are never requested.
- No cookies, no credentials, no sign-in. Response bodies are kept (gzip) in `raw_payload` only when
  the adapter asks with `store_as`.
"""
from __future__ import annotations

import json
import re
import sqlite3
import stringprep
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from typing import Callable

from lapis_design import __version__
from lazuli import sources
from lazuli.catalog import store

USER_AGENT = f"lazuli/{__version__} (+https://github.com/lapis-labs/lapis-lazuli)"
TIMEOUT_S = 30
MAX_REDIRECTS = 5


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def http_error_301(self, request, fp, code, msg, headers):
        return None

    http_error_302 = http_error_303 = http_error_307 = http_error_308 = http_error_301


_opener = urllib.request.build_opener(_NoRedirect)



# Replaced by tests (fake clock); Fetcher reads them at call time
_clock = time.time
_sleep = time.sleep
_last_request: dict[str, float] = {}          # per process, for Fetchers without a database


class Blocked(Exception):
    """The source refused tools: 401/403/429, a CAPTCHA or sign-in page, or a robots.txt disallow."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class FetchError(Exception):
    """Any other HTTP error status."""

    def __init__(self, url: str, status: int):
        super().__init__(f"HTTP {status} from {url}")
        self.url = url
        self.status = status


@dataclass
class Response:
    url: str                       # the final URL, after redirects
    status: int
    headers: dict[str, str]        # names lowercased
    body: bytes

    def text(self) -> str:
        charset = re.search(r"charset=([\w-]+)", self.headers.get("content-type", ""), re.I)
        try:
            return self.body.decode(charset.group(1) if charset else "utf-8", errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text())


def _transport(url: str, headers: dict[str, str], opener: urllib.request.OpenerDirector) -> Response:
    request = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(request, timeout=TIMEOUT_S) as reply:
            headers_out = {k.lower(): v for k, v in reply.headers.items()}
            origins = reply.headers.get_all("Access-Control-Allow-Origin", [])
            if origins:
                headers_out["access-control-allow-origin"] = origins[0].strip() if len(origins) == 1 else ""
            return Response(reply.geturl(), reply.status, headers_out, reply.read())
    except urllib.error.HTTPError as error:
        headers_out = {k.lower(): v for k, v in error.headers.items()} if error.headers else {}
        origins = error.headers.get_all("Access-Control-Allow-Origin", []) if error.headers else []
        if origins:
            headers_out["access-control-allow-origin"] = origins[0].strip() if len(origins) == 1 else ""
        return Response(error.geturl() or url, error.code, headers_out, error.read() or b"")


def default_transport(url: str, headers: dict[str, str]) -> Response:
    """urllib GET without cookies or automatic redirects; Fetcher checks each next URL."""
    return _transport(url, headers, _opener)


# What Chromium percent-encodes when it parses a special-scheme URL (checked against Chromium 153).
_PATH_ESCAPED = frozenset(' "<>^`{|}')
_QUERY_ESCAPED = frozenset(" \"'<>")


class InvalidURL(ValueError):
    """`browser_url` refuses a URL. `kind` is `scheme` (not http or https, or no host), `credentials`,
    `malformed` (a bad bracket or port), or `host` (a host lazuli never requests); `detail` finishes
    "the URL host ..." for a host and names the bad part of a malformed URL."""

    def __init__(self, kind: str, detail: str = ""):
        self.kind, self.detail = kind, detail
        super().__init__({"scheme": "not an http or https URL",
                          "credentials": "the URL carries a user name or password",
                          "malformed": f"the URL is malformed ({detail})",
                          "host": f"the URL host {detail}"}[kind])


def _escape(text: str, escaped: frozenset[str]) -> str:
    return "".join(
        "".join(f"%{byte:02X}" for byte in char.encode("utf-8"))
        if ord(char) <= 0x20 or ord(char) >= 0x7F or char in escaped else char
        for char in text)


def _resolve_dots(path: str) -> str:
    segments = path.replace("\\", "/").split("/")[1:]
    resolved: list[str] = []
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment.lower() in ("..", ".%2e", "%2e.", "%2e%2e"):
            if resolved:
                resolved.pop()
            if last:
                resolved.append("")
        elif segment.lower() in (".", "%2e"):
            if last:
                resolved.append("")
        else:
            resolved.append(segment)
    return "/" + "/".join(resolved)


# Characters the host-name conversions treat differently from the browser: ß and ς (the old IDNA rules
# fold them, the browser keeps them), ZWNJ and ZWJ (dropped here, refused by the browser), and every
# character stringprep table B.1 maps to nothing (soft hyphen, zero-width space, word joiner, byte order
# mark, variation selectors, and a few more). A host that holds one is refused, not spelled two ways.
_UNSTABLE_HOST_CHARS = frozenset("\u00df\u03c2\u200c\u200d")
_IDNA_DOTS = re.compile("[\u002e\u3002\uff0e\uff61]")            # the dots Python's IDNA codec splits on
_C0_AND_SPACE = "".join(map(chr, range(0x21)))                      # what the browser trims from a URL
_IPV4_NUMBER_LABEL = re.compile(r"[0-9]+|0x[a-z0-9_-]*")
_IPV4_PART = re.compile(r"0|[1-9][0-9]{0,2}")


def _stable_idna_char(char: str) -> bool:
    """Only name characters for which Python's IDNA2003 and the browser's UTS46 agree.

    Old IDNA accepts unassigned code points and maps some scripts differently (including some
    Cherokee letters); testing only the ASCII output is not enough. Until both use the same IDNA
    version, accept common stable Latin, CJK, and Hangul ranges plus the IDNA dot variants; other
    Unicode host names are refused, including when hidden in an ASCII punycode label.
    """
    code = ord(char)
    return (code < 0x80 or 0xA0 <= code <= 0x024F or code == 0x3002
            or 0x4E00 <= code <= 0x9FFF or 0xAC00 <= code <= 0xD7A3
            or 0xFF10 <= code <= 0xFF5A or code in (0xFF0E, 0xFF61))


def _dotted_quad(labels: list[str]) -> list[int] | None:
    """The four numbers of a canonical IPv4 address (decimal, no leading zeros, at most 255), or None."""
    if len(labels) == 4 and all(_IPV4_PART.fullmatch(label) and int(label) <= 255 for label in labels):
        return [int(label) for label in labels]
    return None


def _ipv6_pieces(text: str) -> list[int]:
    """The eight 16-bit pieces of an IPv6 address: hex digits, colons, and one embedded canonical IPv4
    address at the end."""
    def refused() -> InvalidURL:
        return InvalidURL("host", "is not a valid IPv6 address")

    def parse(part: str, may_end_in_ipv4: bool) -> list[int]:
        groups = part.split(":") if part else []
        pieces: list[int] = []
        for index, group in enumerate(groups):
            if "." in group and may_end_in_ipv4 and index == len(groups) - 1:
                if (numbers := _dotted_quad(group.split("."))) is None:
                    raise refused()
                pieces += [numbers[0] << 8 | numbers[1], numbers[2] << 8 | numbers[3]]
            elif re.fullmatch(r"[0-9A-Fa-f]{1,4}", group):
                pieces.append(int(group, 16))
            else:
                raise refused()
        return pieces

    head, gap, tail = text.partition("::")
    if "::" in tail or not re.fullmatch(r"[0-9A-Fa-f:.]+", text):
        raise refused()
    if not gap:
        pieces = parse(head, True)
        if len(pieces) != 8:
            raise refused()
        return pieces
    left, right = parse(head, False), parse(tail, True)
    if len(left) + len(right) > 7:
        raise refused()
    return left + [0] * (8 - len(left) - len(right)) + right


def _ipv6(text: str) -> str:
    """The address as the browser writes it: lowercase, the first longest run of two or more zero
    pieces as `::`, an embedded IPv4 address as two hex pieces (`::ffff:7f00:1`). Python's ipaddress
    module writes the last one differently from version to version, so it is not used."""
    pieces = _ipv6_pieces(text)
    best, best_length, start = -1, 1, 0
    for index in range(9):                                          # index 8 closes a run at the end
        if index < 8 and pieces[index] == 0:
            continue
        if index - start > best_length:
            best, best_length = start, index - start
        start = index + 1
    out, skipping = "", False
    for index, piece in enumerate(pieces):
        if skipping and piece == 0:
            continue
        skipping = False
        if index == best:
            out += "::" if index == 0 else ":"
            skipping = True
        else:
            out += f"{piece:x}" + (":" if index != 7 else "")
    return f"[{out}]"


def _domain(text: str) -> str:
    """A host name or IPv4 address as the browser writes it, or InvalidURL.

    The percent-encoding is decoded as strict UTF-8, then IDNA turns the name into ASCII. What remains
    must be labels of [a-z0-9_-]. A last label that is a number (or starts with 0x) makes the host an
    IPv4 address, which must then be a canonical dotted quad. As in the browser, a name keeps one
    trailing dot and an IPv4 address loses it.
    """
    try:
        decoded = urllib.parse.unquote_to_bytes(text).decode("utf-8")
    except UnicodeError:
        raise InvalidURL("host", "is not valid UTF-8 once percent-decoded") from None
    for char in decoded:
        if char in _UNSTABLE_HOST_CHARS or stringprep.in_table_b1(char):
            raise InvalidURL("host", f"holds U+{ord(char):04X}, which host-name conversions handle "
                                     "differently from the browser")
    if any(not _stable_idna_char(char) for char in decoded):
        raise InvalidURL("host", "uses characters Python and the browser do not convert alike")
    try:
        name = decoded.encode("idna").decode("ascii").lower()
        unicode_name = name.encode("ascii").decode("idna")       # a punycode label must round-trip
    except UnicodeError:
        raise InvalidURL("host", "cannot be converted to an IDNA name") from None
    if any(not _stable_idna_char(char) or char in _UNSTABLE_HOST_CHARS
           or stringprep.in_table_b1(char) for char in unicode_name):
        raise InvalidURL("host", "uses a punycode label Python and the browser do not convert alike")
    if len(name.split(".")) != len(_IDNA_DOTS.split(decoded)):
        raise InvalidURL("host", "changes its number of labels when converted to an IDNA name")
    labels = name.removesuffix(".").split(".")
    for label in labels:
        bad = re.search(r"[^a-z0-9_-]", label)
        if bad or not label:
            raise InvalidURL("host", "holds a character other than a letter, digit, hyphen, or underscore "
                                     f"once converted (U+{ord(bad.group()):04X})" if bad else "has an empty label")
    if _IPV4_NUMBER_LABEL.fullmatch(labels[-1]):
        if _dotted_quad(labels) is None:
            raise InvalidURL("host", "ends in a number but is not a dotted-quad IPv4 address")
        return ".".join(labels)
    return name


def browser_url(url: str) -> str:
    """The one URL function lazuli uses: an http(s) URL as the browser requests it, or InvalidURL
    (a ValueError) when lazuli refuses to send it.

    The result has a lowercase ASCII host, no default port, no fragment, no dot segments, and a
    percent-encoded path and query. A host is a bracketed IPv6 address, a canonical dotted-quad IPv4
    address, or a name (see `_domain`); every other spelling, and a URL with a user name or password,
    is refused. The registry check, the pace key, robots.txt, and the request all use this result, so
    the URL lazuli fetches is the URL the browser requests.
    """
    text = url.strip(_C0_AND_SPACE).replace("\t", "").replace("\n", "").replace("\r", "")
    scheme, colon, rest = text.partition(":")
    if not colon or scheme.lower() not in ("http", "https") or not rest.startswith("//"):
        raise InvalidURL("scheme")
    scheme = scheme.lower()
    authority, tail = re.fullmatch(r"([^/\\?#]*)(.*)", rest[2:], re.S).groups()
    if "@" in authority:
        raise InvalidURL("credentials")
    if authority.startswith("["):
        close = authority.find("]")
        if close < 0 or authority[close + 1:close + 2] not in ("", ":"):
            raise InvalidURL("malformed", "a bracket without its pair")
        host, port = _ipv6(authority[1:close]), authority[close + 2:]
    else:
        name, _, port = authority.partition(":")
        if not name:
            raise InvalidURL("scheme")
        host = _domain(name)
    number = None
    if port:
        if not re.fullmatch(r"[0-9]+", port) or len(port.lstrip("0")) > 5 or (number := int(port)) > 65535:
            raise InvalidURL("malformed", "a bad port")
        if number != (80 if scheme == "http" else 443):
            host += f":{number}"
    path, question, query = tail.split("#", 1)[0].partition("?")
    try:
        result = f"{scheme}://{host}{_escape(_resolve_dots(path or '/'), _PATH_ESCAPED)}"
        return result + ("?" + _escape(query, _QUERY_ESCAPED) if question else "")
    except UnicodeEncodeError:
        raise InvalidURL("malformed", "text that is not Unicode") from None


def _next_hop(url: str, location: str) -> str:
    """The URL a redirect from `url` leads to, in the browser's spelling and without a fragment.

    http.client reads header bytes as latin-1, so a UTF-8 Location arrives as mojibake; it is read back
    as UTF-8 when the bytes are valid UTF-8 (a str that holds other characters is already text).
    """
    try:
        location = location.encode("latin-1").decode("utf-8")
    except UnicodeError:
        pass
    return browser_url(urllib.parse.urljoin(url, location))


def _blocked(error: ValueError, subject: str) -> Blocked:
    """Blocked for a URL `browser_url` (or the join before it) refused; `subject` names it for the reader."""
    kind = error.kind if isinstance(error, InvalidURL) else "malformed"
    if kind == "credentials":
        return Blocked(f"{subject} carries credentials; no request was sent")
    if kind == "scheme":
        return Blocked(f"{subject} is a non-HTTP URL; no request was sent")
    if kind == "host":
        return Blocked(f"{subject} host {error.detail}; request not sent")
    return Blocked(f"{subject} is malformed; request not sent")


# A page that asks a person to prove they are human. Only rendered widgets and challenge pages count, not a
# site-wide invisible reCAPTCHA script, which many ordinary pages load.
_CAPTCHA = re.compile(
    rb"class=[\"'][^\"']*\b(g-recaptcha|h-captcha|cf-turnstile)\b|challenges\.cloudflare\.com/turnstile"
    rb"|/cdn-cgi/challenge-platform/|\bcf-chl-|<title>\s*(just a moment|attention required|captcha)"
    rb"|verify (that )?you are (a )?human|are you a robot", re.I)
_SIGN_IN_PATH = re.compile(r"/(log-?in|sign-?in|sign_in|auth/login|account/login|member/login|users?/sign_in)(/|$|\.)", re.I)
_PASSWORD_INPUT = re.compile(rb"<input[^>]+type=[\"']?password", re.I)
_SIGN_IN_TITLE = re.compile(rb"<title>[^<]*(log ?in|sign ?in|\xeb\xa1\x9c\xea\xb7\xb8\xec\x9d\xb8)", re.I)  # 로그인


def blocked_reason(response: Response) -> str | None:
    """Why a response means the source refuses tools, or None."""
    if response.status in (401, 403, 429):
        names = {401: "401 Unauthorized", 403: "403 Forbidden", 429: "429 Too Many Requests"}
        return f"{names[response.status]} from {response.url}"
    is_html = "html" in response.headers.get("content-type", "") or response.body.lstrip()[:1] == b"<"
    if not is_html:
        return None
    head = response.body[:200_000]
    if _CAPTCHA.search(head):
        return f"a CAPTCHA or bot-challenge page at {response.url}"
    if _SIGN_IN_PATH.search(urllib.parse.urlsplit(response.url).path) or (
            _PASSWORD_INPUT.search(head) and _SIGN_IN_TITLE.search(head)):
        return f"a sign-in page at {response.url}"
    return None


class Fetcher:
    def __init__(self, source: str, *, min_interval_s: float, conn: sqlite3.Connection | None = None,
                 transport=None):
        self.source = source
        self.min_interval_s = min_interval_s
        self.conn = conn
        self.transport = transport or default_transport
        self.requests = 0                                   # requests sent, robots.txt included
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._delays: dict[str, float] = {}                 # Crawl-delay per origin

    # -------------------------------------------------------------- pace
    def interval(self, url: str) -> float:
        """Seconds between this source's requests to `url`'s host (after its robots.txt is read)."""
        seconds = max(self.min_interval_s, self._delays.get(_origin(url), 0.0))
        robots = self._robots.get(_origin(url))
        if robots is not None and (rate := robots.request_rate(USER_AGENT)):
            seconds = max(seconds, rate.seconds / max(rate.requests, 1))
        return seconds

    def _keys(self, url: str) -> tuple[str, ...]:
        if self.source == "ref" or self.source.startswith("read:"):
            host = sources._host(urllib.parse.urlsplit(url).hostname or "")
            key = f"read:{host}"
            return ("ref", key) if self.source == "ref" else (key,)
        return (self.source,)

    def _last(self, key: str) -> float | None:
        times = [_last_request.get(key)]
        if self.conn is not None:
            row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (f"last_request.{key}",)).fetchone()
            times.append(float(row[0]) if row else None)
        known = [t for t in times if t is not None]
        return max(known) if known else None

    def record(self, url: str) -> None:
        """Record an actual request (including a browser page load) under every applicable pace key."""
        moment = _clock()
        keys = self._keys(url)
        if self.conn is not None:
            with self.conn:
                self.conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?) "
                                      "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                                      [(f"last_request.{key}", f"{moment:.3f}") for key in keys])
        for key in keys:
            _last_request[key] = moment

    def _send(self, url: str, headers: dict[str, str], interval: float) -> Response:
        lasts = (self._last(key) for key in self._keys(url))
        if (last := max((t for t in lasts if t is not None), default=None)) is not None:
            if (wait := last + interval - _clock()) > 0:
                _sleep(wait)
        try:
            return self.transport(url, {**headers, "User-Agent": USER_AGENT})
        finally:
            self.requests += 1
            self.record(url)

    # -------------------------------------------------------------- robots.txt
    def _robots_for(self, url: str, check: Callable[[str], None] | None = None) -> urllib.robotparser.RobotFileParser:
        origin = _origin(url)
        if origin in self._robots:
            return self._robots[origin]
        robots_url = origin + "/robots.txt"
        current = robots_url
        for hop in range(MAX_REDIRECTS + 1):
            # `current` is the one canonical spelling used by the registry, pace, robots, and transport.
            entry = sources.find(current)
            if entry is not None and entry.get("access") not in ("read", "adapter"):
                reason = entry.get("reason") or f"source registry marks {entry.get('name') or entry['id']} `{entry['access']}`"
                raise Blocked(f"{reason}; request not sent: {current}")
            if check is not None:
                check(current)
            response = self._send(current, {}, self.interval(current) if hop else self.min_interval_s)
            if not 300 <= response.status < 400:
                break
            location = response.headers.get("location")
            if not location:
                raise Blocked(f"robots.txt at {current} answered {response.status} without Location")
            try:
                next_url = _next_hop(current, location)
            except ValueError as exc:
                raise _blocked(exc, "robots.txt redirect URL") from None
            if hop == MAX_REDIRECTS:
                raise Blocked(f"robots.txt redirect limit ({MAX_REDIRECTS}) reached; next link not sent: {next_url}")
            current = next_url
        parser = urllib.robotparser.RobotFileParser(robots_url)
        if response.status in (401, 403, 429):
            raise Blocked(f"robots.txt at {origin} answered {response.status}; the site does not allow tools")
        if response.status >= 500:
            raise Blocked(f"robots.txt at {origin} answered {response.status}; an unreachable robots.txt "
                          "disallows everything")
        if response.status >= 400:
            parser.allow_all = True                        # no robots.txt: everything is allowed
        elif (reason := blocked_reason(response)) is not None:
            raise Blocked(reason)
        else:
            lines = response.text().splitlines()
            parser.parse(lines)
            if (delay := crawl_delay(lines)) is not None:
                self._delays[origin] = delay
        self._robots[origin] = parser
        return parser

    # -------------------------------------------------------------- GET
    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None,
            store_as: str | None = None, check: Callable[[str], None] | None = None) -> Response:
        """GET with an optional guard called before each page and robots.txt redirect hop is sent."""
        # Canonicalize before appending parameters: a fragment must not swallow the added query.
        request_headers = dict(headers or {})
        for hop in range(MAX_REDIRECTS + 1):
            try:
                url = browser_url(url)
            except ValueError as exc:
                raise _blocked(exc, "redirect URL" if hop else "URL") from None
            if hop == 0 and params:
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
            parts = urllib.parse.urlsplit(url)
            entry = sources.find(url)
            if entry is not None and entry.get("access") not in ("read", "adapter"):
                reason = entry.get("reason") or f"source registry marks {entry.get('name') or entry['id']} `{entry['access']}`"
                raise Blocked(f"{reason}; request not sent: {url}")
            robots = self._robots_for(url, check)
            if not robots.can_fetch(USER_AGENT, url):
                raise Blocked(f"robots.txt at {_origin(url)} disallows {parts.path or '/'}; request not sent: {url}")
            if check is not None:
                check(url)
            response = self._send(url, request_headers, self.interval(url))
            if 300 <= response.status < 400:
                location = response.headers.get("location")
                if not location:
                    raise Blocked(f"HTTP {response.status} redirect at {url} has no Location")
                try:
                    next_url = _next_hop(url, location)
                except ValueError as exc:
                    raise _blocked(exc, "redirect URL") from None
                if hop == MAX_REDIRECTS:
                    raise Blocked(f"redirect limit ({MAX_REDIRECTS}) reached; next link not sent: {next_url}")
                url = next_url
                continue
            if (reason := blocked_reason(response)) is not None:
                raise Blocked(reason)
            if response.status >= 400:
                raise FetchError(response.url, response.status)
            if store_as and self.conn is not None:
                store.save_raw(self.conn, self.source, store_as, response.body)
            return response
        raise AssertionError("redirect loop must terminate")


def _origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def crawl_delay(lines: list[str], agent: str = "lazuli") -> float | None:
    """The Crawl-delay for `agent`: from groups naming it, else from the `*` group; decimals allowed.

    urllib.robotparser keeps only whole-number delays, so a stated 2.5 would otherwise be ignored.
    Like robotparser, a group applies when its user-agent token is part of our product name.
    """
    delays: dict[str, float] = {}
    agents: list[str] = []
    in_rules = False
    for raw in lines:
        key, _, value = raw.split("#", 1)[0].partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                agents, in_rules = [], False
            agents.append(value.lower())
        elif key:
            in_rules = True
            if key == "crawl-delay":
                try:
                    seconds = float(value)
                except ValueError:
                    continue
                for name in agents:
                    delays[name] = max(delays.get(name, 0.0), seconds)
    ours = [seconds for name, seconds in delays.items() if name and name != "*" and name in agent]
    return max(ours) if ours else delays.get("*")
