"""Live capture context for independent measured-field passes."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import CDPSession, Page


@dataclass
class RawView:
    """A live viewport, passed to each registered field module before the page closes.

    config: capture settings (width, layout_height, visible height, theme, reduced motion,
        browser chrome, DPR); page: live Playwright page (at rest before scrolling, then
        scroll-reset for field application); cdp: live CDP session; elements: box-id keyed
        metadata (tag, allowed attrs, DOM-order child box ids, rect, normalized style
        and raw computed_style subset), empty during the optional pre-scroll observe_rest
        hook and populated before apply;
    screenshot_path: absolute path to the full-page PNG (not yet written at rest);
    extra: mutable scratchpad shared between hooks and field passes, kept off the extract.
    """

    config: dict[str, Any]
    page: Page
    cdp: CDPSession
    elements: dict[str, dict[str, Any]]
    screenshot_path: Path
    extra: dict[str, Any] = field(default_factory=dict)
