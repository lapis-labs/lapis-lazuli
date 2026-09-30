"""Which hosts `render check` may capture (render/DERIVED.md, Capture, **Target hosts.**).

Literal local hosts and a verified starting `.test` name are ours. A public host needs `--public`;
public source-registry and plan-reference hosts stay refused. The same policy holds for every document
request of the captured page's main frame (including redirects and script navigations), and for
pages it opens before their first request. Refused opened pages are closed and noted without ending
the capture. Pages that are not ours are captured only with `lazuli ref capture`.
"""
from __future__ import annotations

import contextlib
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from lapis_design import ours
from lapis_design.plan_check import read_plan_or_raise
from lazuli import sources
from lazuli.catalog.net import InvalidURL

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page

# A reference written without a scheme ("example.com/archive") still names a host.
_BARE_HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}(?::\d+)?(?:/\S*)?", re.I)


class Refused(Exception):
    """render check may not capture this page; the message names `lazuli ref capture` instead."""

    def __init__(self, url: str, reason: str):
        super().__init__(f"refused {url}: {reason}. Pages that are not ours are captured only with "
                         f"`lazuli ref capture {url} --rights <own|licensed|reference-only>`")
        self.url, self.reason = url, reason


def plan_path(plan: Path | None, task: str | None) -> Path | None:
    """The plan `--plan` names; else `.lapis/plans/<task>.yaml` when it exists; else None."""
    if plan is not None:
        return plan
    if not task or "/" in task or "\\" in task or task in (".", ".."):
        return None
    found = Path(".lapis") / "plans" / f"{task}.yaml"
    return found if found.is_file() else None


def load_plan(path: Path | None) -> dict | None:
    if path is None:
        return None
    plan = read_plan_or_raise(path)
    if not isinstance(plan, dict):
        raise ValueError(f"{path}: a plan is a YAML mapping")
    return plan


def _reference_url(source: str) -> str | None:
    source = source.strip()
    if "://" in source:
        parts = urlsplit(source)
        return source if parts.scheme.lower() in ("http", "https") and parts.hostname else None
    return f"https://{source}" if _BARE_HOST.fullmatch(source) else None


class HostPolicy:
    """One run's target-host rule. A pinned .test name is exact; registry and reference hosts
    compare through `sources.find`, which normalizes hosts to IDNA ASCII."""

    def __init__(self, *, public: bool, plan: dict | None, registry: list[dict] | None = None,
                 pins: list[ours.SourcePin] | None = None):
        self.public = public
        self.pins = {pin.host: pin for pin in (pins or [])}
        self.registry = sources.load_registry() if registry is None else registry
        references = (plan or {}).get("references") or []
        if not isinstance(references, list):
            raise ValueError("the plan's references must be a list")
        self.references = [{"id": f"references[{i}]", "url": url} for i, ref in enumerate(references)
                           if isinstance(ref, dict) and isinstance(ref.get("source"), str)
                           and (url := _reference_url(ref["source"]))]

    def refusal(self, url: str) -> str | None:
        """Why the page at `url` may not be captured, or None when it may."""
        host = urlsplit(url).hostname
        if not host:
            return None
        try:
            host = sources.ascii_host(host)
        except ValueError as exc:
            return str(exc) if isinstance(exc, InvalidURL) else "the URL host cannot be converted to an IDNA name"
        pin = self.pins.get(host)
        if ours.source_is_ours(host, list(pin.addresses) if pin else None):
            return None
        if not self.public:
            return (f"{host} is a public host; render check captures hosts that are ours "
                    "(including verified local .test sources), and a public host only with --public")
        if entry := sources.find(url, self.registry):
            return (f"{host} is in the source registry ({entry.get('name') or entry['id']}, access "
                    f"`{entry['access']}`)")
        if ref := sources.find(url, self.references):
            return f"{host} is a host in the plan's references ({ref['id']}: {ref['url']})"
        return None

    def check(self, url: str) -> None:
        if reason := self.refusal(url):
            raise Refused(url, reason)


class GuardedBrowser:
    """Guard every document before its first request; only main-page refusal ends the run."""

    def __init__(self, browser: Browser, policy: HostPolicy):
        self._browser, self.policy = browser, policy
        self.refused: Refused | None = None

    def new_context(self, **options) -> _GuardedContext:
        return _GuardedContext(self, self._browser.new_context(**options))

    def check(self) -> None:
        if self.refused is not None:
            raise self.refused

    def watch(self, context: BrowserContext, page: Page) -> None:
        """Guard `page` before anything navigates it; a blocked navigation fails with
        net::ERR_BLOCKED_BY_CLIENT, or leaves an error page, and `refused` says why."""
        from playwright.sync_api import Error as PlaywrightError
        cdp = context.new_cdp_session(page)
        main_frame = cdp.send("Page.getFrameTree")["frameTree"]["frame"]["id"]

        def paused(event: dict) -> None:
            url = event["request"]["url"]
            reason = self.policy.refusal(url) if event.get("frameId") == main_frame else None
            if reason and self.refused is None:
                self.refused = Refused(url, reason)
            with contextlib.suppress(PlaywrightError):     # the page may close while a request waits
                if reason:
                    cdp.send("Fetch.failRequest", {"requestId": event["requestId"], "errorReason": "BlockedByClient"})
                else:
                    cdp.send("Fetch.continueRequest", {"requestId": event["requestId"]})

        cdp.on("Fetch.requestPaused", paused)
        cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "resourceType": "Document",
                                                "requestStage": "Request"}]})

        # A context route also pauses a popup's first request, before Playwright emits "page".
        def popup_request(route, request):
            if request.resource_type != "document":
                route.continue_()
                return
            try:
                main = request.frame.page == page
            except PlaywrightError:
                main = False
            if main:
                route.continue_()  # CDP checks main-frame document requests and redirect hops
                return
            reason = self.policy.refusal(request.url)
            if reason:
                print(f"render check: {Refused(request.url, reason)} (opened page)", file=sys.stderr)
                route.abort("blockedbyclient")
            else:
                route.continue_()

        context.route("**/*", popup_request)

        def close_popup(other: Page) -> None:
            if other != page:
                with contextlib.suppress(PlaywrightError):
                    other.close()

        context.on("page", close_popup)


class _GuardedContext:
    """A browser context whose new pages are guarded before new_page() returns; everything else is the
    context's own."""

    def __init__(self, guard: GuardedBrowser, context: BrowserContext):
        self._guard, self._context = guard, context

    def new_page(self) -> Page:
        page = self._context.new_page()
        try:
            self._guard.watch(self._context, page)
        except BaseException:
            page.close()
            raise
        return page

    def __getattr__(self, name: str):
        return getattr(self._context, name)
