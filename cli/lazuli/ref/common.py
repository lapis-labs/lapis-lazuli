"""Shared pieces of `lazuli ref`: outcomes, slugs, the reference document, and the cache folder."""
from __future__ import annotations

import http.client
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urldefrag, urlsplit, urlunsplit

from lapis_design import __version__
from lazuli import db, paths, sources
from lazuli.catalog import net
from lazuli.read import UsageError, normalize, refusal

RIGHTS = ("own", "licensed", "reference-only")
# Seconds between requests to the site (the preflight, then each page load), or its Crawl-delay if longer
MIN_INTERVAL_S = 3.0
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# File names that say nothing about the system; the folder name goes in front of them
_GENERIC_STEMS = {"design", "tokens", "design-tokens", "index", "theme", "variables", "readme"}


class Refused(Exception):
    """The registry, the site, or the rights rule out the profile; the user has to act (exit 1).

    status: `refused` (the source registry or the rights) or `blocked` (the site refused tools);
    browser_link: the page to open in a browser instead; registry: the registry entry that decided."""

    def __init__(self, reason: str, *, status: str = "refused", browser_link: str | None = None,
                 registry: dict | None = None):
        super().__init__(reason)
        self.reason, self.status, self.browser_link, self.registry = reason, status, browser_link, registry


class InputError(Exception):
    """Unreadable, unsupported, or unreachable input (exit 2)."""


@dataclass
class Profile:
    document: dict
    summary: dict                                                   # what the report shows
    omitted: list[tuple[str, str]] = field(default_factory=list)    # (field, why it is left out)
    notes: list[str] = field(default_factory=list)                  # also written to reference.notes


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:64].rstrip("-") or "ref"


def is_url(value: str) -> bool:
    try:
        return urlsplit(value).scheme in ("http", "https")
    except ValueError as exc:
        raise InputError(f"not an http(s) URL: {value}") from exc


def url_slug(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise InputError(f"not an http(s) URL: {url}") from exc
    return slugify(f"{(parts.hostname or '').removeprefix('www.')} {parts.path}")


def path_slug(path: Path) -> str:
    stem = slugify(path.name.split(".")[0])
    parent = path.resolve().parent.name
    return slugify(f"{parent} {stem}") if stem in _GENERIC_STEMS and parent else stem


def page_url(url: str) -> str:
    """The URL as stored: no query or fragment."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def cache_folder(slug: str) -> Path:
    """Screenshots and image copies of one reference, in the lazuli cache and never in a project."""
    return paths.cache_dir() / "refs" / slug


def _check_registry(url: str, link: str) -> None:
    """Refuse a URL the source registry marks `refused` or `browser-link` (or anything but `read` or
    `adapter`), with the same policy as `lazuli read`; an unlisted source may be fetched. `link` is
    the page the user named, to open in a browser instead."""
    entry = sources.find(url)
    if reason := refusal(entry):
        raise Refused(reason, browser_link=link, registry={
            key: entry[key] for key in ("id", "name", "access", "terms_url", "clause") if entry.get(key)})


def fetch(url: str) -> tuple[float, net.Response]:
    """GET the named URL through the registry and paced transport; keep the last request in the user DB.
    The fragment never leaves this computer. Return the robots-adjusted pacing interval for site captures."""
    try:
        url = normalize(url)
    except UsageError as exc:
        raise InputError(str(exc)) from exc
    except UnicodeError as exc:
        _check_registry(url, url)
        raise Refused("the URL host cannot be converted to an IDNA name; request not sent",
                      browser_link=url) from exc
    _check_registry(url, url)
    try:
        conn = db.connect(paths.db_path())
    except (sqlite3.Error, OSError, RuntimeError) as exc:
        raise InputError(f"could not open lazuli database: {exc}") from exc
    try:
        fetcher = net.Fetcher("ref", min_interval_s=MIN_INTERVAL_S, conn=conn)
        try:
            response = fetcher.get(url)
        except net.Blocked as exc:
            raise Refused(exc.reason, status="blocked", browser_link=url) from exc
        except net.FetchError as exc:
            raise InputError(str(exc)) from exc
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise InputError(f"could not load {url}: {exc}") from exc
        except sqlite3.Error as exc:
            raise InputError(f"lazuli database error: {exc}") from exc
        return fetcher.interval(response.url), response
    finally:
        conn.close()


def new_document(kind: str, rights: str) -> dict:
    return {
        "version": 1,
        "meta": {"extractor": {"name": "lazuli-ref", "version": __version__},
                 "generated_at": datetime.now(timezone.utc).isoformat()},
        "source": {"kind": kind},
        "reference": {"rights": rights, "captured_by": "user-request"},
    }
