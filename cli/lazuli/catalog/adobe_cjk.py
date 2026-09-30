"""Adobe Fonts CJK classification: refused, because Adobe's terms forbid collecting its site's data.

The planned snapshot (the fonts.adobe.com listing by its CJK classification facets) is data
gathering from an Adobe website. Adobe General Terms of Use (published and
effective 2025-10-03; read 2026-09-26 at https://www.adobe.com/legal/terms.html), section 6.18: you
must not "use any data mining or similar data gathering and extraction methods in connection with the
Services and Software", and the Services include Adobe's websites. fonts.adobe.com/robots.txt alone
would allow the listing (it disallows only /variations/*/eula and /login), but the terms decide.

So the module declares REFUSED: the CLI skips it and marks it disabled with the reason, and
`fetch` still raises Blocked without a request if it is ever called.
Installed Adobe fonts are still labeled by measurement and by any other catalog that matches them.
"""
from __future__ import annotations

from lazuli.catalog.net import Blocked, Fetcher
from lazuli.catalog.store import CatalogFamily

NAME = "adobe-cjk"
KIND = "snapshot"
PRIORITY = 30
TTL_DAYS = 30
MIN_INTERVAL_S = 3.0

# No closing period: the CLI appends its own sentence after the reason
REASON = ("Adobe's General Terms of Use (section 6.18) forbid data gathering and extraction on Adobe "
          "websites, so lazuli does not collect the Adobe Fonts listing; check a font's CJK "
          "classification at https://fonts.adobe.com/fonts in your browser; installed Adobe fonts are "
          "still classified by measurement")

REFUSED = REASON


def fetch(fetcher: Fetcher) -> list[CatalogFamily]:
    raise Blocked(REASON)
