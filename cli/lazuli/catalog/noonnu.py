"""noonnu (눈누): refused, because its terms forbid scraping and robots other than search engines.

Read 2026-09-26 at https://noonnu.cc/user_agreement, 제7조 (이용자의 의무): users must not copy,
distribute, or publish any part of the service through automated or manual "scraping"; must not use
robots, spiders, or offline readers to access it (only public search engines may copy material, and
only to build search indexes); and must not access its content by means other than those the service
provides. noonnu.cc/robots.txt alone would allow family pages (it disallows only admin and account
paths), but the terms decide. The license summary noonnu shows was meant only as a hint.

So the module declares REFUSED: the CLI never looks it up by default, and when the user names the
source it prints this module's per-family browser link; `lookup` sends no request and raises Blocked
with that link.
"""
from __future__ import annotations

import urllib.parse

from lazuli.catalog.net import Blocked, Fetcher
from lazuli.catalog.store import CatalogFamily

NAME = "noonnu"
KIND = "lookup"
PRIORITY = 60
TTL_DAYS = 90
MIN_INTERVAL_S = 3.0

SEARCH_URL = "https://noonnu.cc/index?search={}"          # the site's own search link format
REFUSED = ("noonnu's terms of use (제7조) forbid scraping and automated access, so lazuli does not "
           "read noonnu.cc; name the source (--source noonnu) to get browser links for your fonts")


def lookup(fetcher: Fetcher, family: str, *, names_i18n: dict[str, str] | None = None,
           postscript_name: str | None = None) -> CatalogFamily | None:
    query = (names_i18n or {}).get("ko") or family
    raise Blocked("noonnu's terms of use (제7조) forbid scraping and automated access, so lazuli does not "
                  f"read noonnu.cc; look the font up in your browser: {SEARCH_URL.format(urllib.parse.quote(query))}")
