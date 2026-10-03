"""A page that changes while it is measured: what is recorded for a node that left the document.

The capture reads the page once, then field passes read it again, a screenshot and a few CDP calls
apart. A page that rebuilds itself in between (a live clock, a ticker, a feed) takes nodes out of the
document that the passes still hold. A pass skips such a node, never reads a value for it, and the
extract says so with `unmeasured` on the box or text run (render/DERIVED.md).
"""
from __future__ import annotations

import re

from playwright.sync_api import Error as PlaywrightError

DETACHED = "detached-during-capture"

# What the DevTools protocol says of a node id whose node the page has removed since the id was taken.
_NODE_GONE = re.compile(r"(?:Could not find|No) node with given id")


def mark(item: dict) -> None:
    """Record on a box or text run that a field pass found its node gone from the page."""
    item["unmeasured"] = DETACHED


def send(cdp, method: str, params: dict) -> dict | None:
    """A DevTools command about one node, or None when the page has removed that node since its id was
    taken; every other protocol error is raised."""
    try:
        return cdp.send(method, params)
    except PlaywrightError as exc:
        if _NODE_GONE.search(str(exc)):
            return None
        raise
