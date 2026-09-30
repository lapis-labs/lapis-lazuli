"""`lazuli ref capture URL`: capture the vetted page, leaving subrequests to Chromium.

The registry and robots.txt are checked by the paced preflight Fetcher before Chromium opens the
final URL. Only that page's main document is fetched by lazuli; subsequent main-frame destinations
are refused. Chromium has no proxy, cannot resolve refused or browser-link hosts, and sends permitted
subrequests itself under its own origin and private-network rules. Peer connections and service
workers are disabled. Pages load once per width (390, 768, 1440; light theme). Links are never
followed by the capture driver, and nothing is typed or submitted. Screenshots go to the lazuli
cache, written first to a temporary folder there. `capture_site` hands that folder to its caller with
the profile; the caller puts it in place of refs/<slug>/ together with the profile file, so a stopped
capture leaves none of its screenshots and a slug's profile and screenshots change together or not at
all. A reference-only profile keeps text only as keyed signatures, without alt text or names.
"""
from __future__ import annotations

import contextlib
import ipaddress
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import getproxies

from playwright.sync_api import Browser
from playwright.sync_api import Error as PlaywrightError

from lapis_design.render.capture import capture
from lapis_design.sig_key import load_key
from lapis_design.text_sig import key_id
from lazuli import db, paths, sources
from lazuli.catalog import net
from lazuli.ref.common import (MIN_INTERVAL_S, InputError, Profile, Refused, cache_folder, fetch, is_url,
                               new_document, page_url)

# (width, height) as in the render capture matrix; references need no dark, reduced-motion, or 320 px pass
VIEWPORTS = ((390, 844), (768, 1024), (1440, 900))


def _host_resolver_rules(registry: list[dict]) -> tuple[str, set[str]]:
    """Chromium DNS rules for every disallowed host, including canonical and dotted spellings."""
    blocked: set[str] = set()
    for entry in registry:
        if entry["access"] not in ("refused", "browser-link"):
            continue
        for name in (urlsplit(entry["url"]).hostname or "", *entry.get("hosts", ())):
            blocked.add(sources._host(name))
    rules = ", ".join(f"MAP {name} ~NOTFOUND"
                      for host in sorted(blocked)
                      for name in (host, host + ".", "www." + host, "www." + host + "."))
    return rules, blocked


def _launch_args(rules: str) -> list[str]:
    """Keep the capture browser direct even when the launch environment supplies a proxy."""
    return ["--proxy-server=direct://", "--no-proxy-server", f"--host-resolver-rules={rules}"]


@contextlib.contextmanager
def _open_browser() -> Iterator[Browser]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        rules, _ = _host_resolver_rules(sources.load_registry())
        browser = playwright.chromium.launch(args=_launch_args(rules))
        try:
            yield browser
        finally:
            browser.close()


def _normalized_url(url: str) -> str | None:
    """Compare browser and preflight spellings without weakening the main-document boundary."""
    try:
        parts = urlsplit(url)
        if not parts.hostname or parts.username is not None or parts.password is not None:
            return None
        host = sources.ascii_host(parts.hostname)
        port = parts.port
    except (UnicodeError, ValueError):
        return None
    scheme = parts.scheme.lower()
    if (scheme, port) in (("http", 80), ("https", 443)):
        port = None
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc += f":{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def _is_loopback(url: str) -> bool:
    host = sources.ascii_host(urlsplit(url).hostname or "")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _NamedBrowser:
    """Provide registry-checked contexts and guard the capturing page's document."""

    def __init__(self, browser: Browser, allowed_url: str, given_url: str):
        self._browser = browser
        self.allowed_url = allowed_url
        self.blocked: Refused | None = None
        self.load_error: InputError | None = None
        self.unsent: set[str] = set()
        self.registry = sources.load_registry()
        _, self.blocked_hosts = _host_resolver_rules(self.registry)
        vetted = urlsplit(_normalized_url(allowed_url) or allowed_url)
        self._loopback_origin = (f"{vetted.scheme}://{vetted.netloc}"
                                 if _is_loopback(given_url) and _is_loopback(allowed_url) else None)
        context = browser.new_context(service_workers="block")
        try:
            default = context.new_page().evaluate("navigator.userAgent")
        finally:
            context.close()
        self.user_agent = f"{default} {net.USER_AGENT}"

    def _blocked_host(self, url: str) -> bool:
        try:
            return sources._host(urlsplit(url).hostname or "") in self.blocked_hosts
        except (ValueError, UnicodeError):
            return False

    def _subrequest(self, route) -> None:
        url = route.request.url
        try:
            entry = sources.find(url, self.registry)
            disallowed = self._blocked_host(url) or (entry is not None
                                                       and entry.get("access") in ("refused", "browser-link"))
        except (ValueError, UnicodeError):
            disallowed = True
        if disallowed:
            with contextlib.suppress(PlaywrightError):
                route.abort("blockedbyclient")
                if self._blocked_host(url):
                    self.unsent.add(url)
        else:
            with contextlib.suppress(PlaywrightError):
                route.continue_()

    def _failed_request(self, request) -> None:
        if request.failure == "net::ERR_NAME_NOT_RESOLVED" and self._blocked_host(request.url):
            self.unsent.add(request.url)

    def _check_document(self, page) -> None:
        """The navigation entry identifies the actual document even after a history-only URL change."""
        document_url = page.evaluate(
            "() => performance.getEntriesByType('navigation')[0]?.name ?? null")
        if _normalized_url(document_url or "") != _normalized_url(self.allowed_url):
            self.blocked = Refused(
                f"main-frame document at {document_url or '(unknown)'} was not preflighted; capture blocked",
                status="blocked", browser_link=document_url or self.allowed_url)
            raise self.blocked

    def _route(self, route, context) -> None:
        request = route.request
        try:
            frame = request.frame
        except PlaywrightError:                         # a popup's first navigation may have no frame
            frame = None
        if (frame is None or not request.is_navigation_request() or frame.parent_frame is not None
                or frame.page != context.pages[0]):
            self._subrequest(route)
            return
        url = request.url
        normalized = _normalized_url(url)
        if normalized is None or normalized != _normalized_url(self.allowed_url):
            try:
                parts = urlsplit(url)
                credentials = parts.username is not None or parts.password is not None
            except ValueError:
                credentials = False
            if credentials:
                self.blocked = Refused("main-frame navigation URL carries credentials; request not sent",
                                       status="blocked", browser_link=self.allowed_url)
            else:
                self.blocked = Refused(f"main-frame navigation to {url} was not preflighted; request not sent",
                                       status="blocked", browser_link=url)
            with contextlib.suppress(PlaywrightError):
                route.abort("blockedbyclient")
            return
        try:
            response = route.fetch(max_redirects=0)
        except PlaywrightError as exc:
            reason = f"could not load the page: {exc}"
            proxies = getproxies()
            if "http" in proxies or "https" in proxies:
                reason += (" (the capture browser has no proxy; networks requiring a proxy "
                           "cannot reach internet pages)")
            self.load_error = InputError(reason)
            with contextlib.suppress(PlaywrightError):
                route.abort("failed")
            return
        if 300 <= response.status < 400:
            try:
                target = urljoin(url, response.headers.get("location", url))
            except ValueError:
                self.blocked = Refused("main-frame redirect URL is malformed; request not sent",
                                       status="blocked")
                with contextlib.suppress(PlaywrightError):
                    route.abort("blockedbyclient")
                return
            if urlsplit(target).username is not None or urlsplit(target).password is not None:
                self.blocked = Refused("main-frame redirect URL carries credentials; request not sent",
                                       status="blocked", browser_link=self.allowed_url)
            else:
                self.blocked = Refused(f"main-frame redirect to {target} was not preflighted; request not sent",
                                       status="blocked", browser_link=target)
            with contextlib.suppress(PlaywrightError):
                route.abort("blockedbyclient")
            return
        with contextlib.suppress(PlaywrightError):
            route.fulfill(response=response)

    def new_context(self, **options):
        context = self._browser.new_context(user_agent=self.user_agent, service_workers="block", **options)
        if self._loopback_origin:
            # Chromium requires this for a user-named loopback page's loopback WebSockets.
            context.grant_permissions(["local-network-access"], origin=self._loopback_origin)
        context.add_init_script("""
            delete globalThis.RTCPeerConnection;
            delete globalThis.webkitRTCPeerConnection;
            delete globalThis.RTCDataChannel;
        """)
        context.route("**/*", lambda route: self._route(route, context))
        context.on("requestfailed", self._failed_request)
        return context


def _keep_signatures_only(vp: dict) -> None:
    """What a reference-only profile may hold: no copy, alt text, or accessible names (and, as capture()
    returns no screenshot path, no screenshot)."""
    for run in vp["text"]:
        run.pop("text", None)
    for box in vp["boxes"]:
        box.get("a11y", {}).pop("name", None)
        box.get("media", {}).pop("alt", None)
    if "text_sig" not in vp:
        raise Refused(f"the page shows no text at {vp['width']} px, and a reference-only profile keeps "
                      "text only as signatures, one per viewport; nothing was written. Capture it with "
                      "--rights own or licensed if you hold those rights")


@contextlib.contextmanager
def _staging_folder(shots: Path) -> Iterator[Path]:
    """A folder inside the lazuli cache, beside `shots`, for the screenshots of one run. Removed if
    the block fails; when it ends normally the folder is the caller's. Never the system temp folder:
    screenshots exist only in the cache."""
    shots.parent.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix=f".{shots.name}-", dir=shots.parent))
    try:
        yield folder
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


@dataclass
class Capture:
    """A finished capture that is not yet in place: its profile, and the screenshots waiting in
    `staging` to take the place of `shots` together with the profile file."""
    profile: Profile
    staging: Path
    shots: Path

    def discard(self) -> None:
        """Remove what is left of the staging folder (nothing, once it has been put in place)."""
        shutil.rmtree(self.staging, ignore_errors=True)


def capture_site(url: str, rights: str, slug: str) -> Capture:
    """Capture the named page at every width into a staging folder and return it with the profile.
    Nothing reaches refs/<slug>/ here: the caller publishes the folder together with the profile and
    then calls `discard()`. A capture that stops as blocked or fails leaves no staging folder."""
    if not is_url(url):
        raise InputError(f"not an http(s) URL: {url}")
    interval, response = fetch(url)
    final_url = response.url
    shots = cache_folder(slug)
    key = load_key()
    viewports = []
    named = None
    last = net._clock()
    try:
        conn = db.connect(paths.db_path())
    except (sqlite3.Error, OSError, RuntimeError) as exc:
        raise InputError(f"could not open lazuli database: {exc}") from exc
    try:
        with contextlib.closing(conn), _staging_folder(shots) as staging:
            with _open_browser() as browser:
                recorder = net.Fetcher("ref", min_interval_s=MIN_INTERVAL_S, conn=conn)
                named = _NamedBrowser(browser, final_url, url)
                for width, height in VIEWPORTS:
                    if (wait := last + interval - net._clock()) > 0:
                        net._sleep(wait)
                    config = {"width": width, "layout_height": height, "height": height, "theme": "light",
                              "reduced_motion": False, "browser_chrome": False, "dpr": 2}
                    name = f"{width}.png"
                    try:
                        vp = capture(named, final_url, config, staging / name, key,
                                     check_document=named._check_document)
                    except Exception as exc:
                        if named.blocked is not None:       # the page left the named document; what the
                            raise named.blocked from exc    # passes then tripped over (an error page) is no result
                        raise
                    finally:
                        recorder.record(final_url)
                    if named.blocked is not None:
                        raise named.blocked
                    if named.load_error is not None:
                        raise named.load_error
                    last = net._clock()
                    if rights == "reference-only":
                        _keep_signatures_only(vp)
                    else:
                        vp["screenshot"] = str(shots / name)    # where the caller publishes it
                    viewports.append(vp)
            if named.blocked is not None:                       # a navigation seen while the browser closed
                raise named.blocked
    except sqlite3.Error as exc:
        raise InputError(f"lazuli database error: {exc}") from exc
    except (PlaywrightError, ValueError, OSError) as exc:
        if named is not None:
            if named.blocked is not None:
                raise named.blocked from exc
            if named.load_error is not None:
                raise named.load_error from exc
        raise InputError(f"could not capture {final_url}: {exc}") from exc
    document = new_document("site", rights)
    document["meta"]["sig_key_id"] = key_id(key)
    document["source"]["url"] = page_url(final_url)
    document["viewports"] = viewports
    reference_only = rights == "reference-only"
    summary = {
        "viewports": [vp["width"] for vp in viewports],
        "boxes": sum(len(vp["boxes"]) for vp in viewports),
        "text_runs": sum(len(vp["text"]) for vp in viewports),
        "text_kept_as": "keyed signatures only" if reference_only else "text and signatures",
        "screenshots": str(shots),
        "screenshots_in_profile": not reference_only,
    }
    profile = Profile(document, summary)
    if named is not None and named.unsent:
        profile.notes.append(f"at least {len(named.unsent)} page requests to refused or browser-link "
                             "hosts were blocked")
    return Capture(profile, staging, shots)
