"""Font catalogs: adapters that label installed fonts with what catalogs say about them.

SOURCES is every adapter module in priority order (lower PRIORITY wins when labels disagree). Each
module has NAME, KIND (snapshot | lookup | bundled), PRIORITY, TTL_DAYS, MIN_INTERVAL_S, and `fetch`
(snapshot, bundled) or `lookup` (lookup). Yoon Design blocks tools and has no adapter.
"""
from __future__ import annotations

from lazuli.catalog import (adobe_cjk, anshim, fontshare, fontsource, google_fonts, noonnu, sandoll,
                            system_table)

SOURCES = (google_fonts, fontsource, fontshare, adobe_cjk, anshim, system_table, noonnu, sandoll)
