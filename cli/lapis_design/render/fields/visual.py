"""Capture screenshot-based palette, CSS paint layers, icons, and media."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from PIL import Image

from lapis_design.render.fields import media, paint, palette


@contextmanager
def own_capture(path) -> Iterator[Image.Image]:
    """The full-page screenshot this run wrote a moment ago. A tall page is a legitimate image (a scroll-driven page at
    1440 px passes the decompression-bomb limit of 89 million pixels, which warns on stderr and past twice that raises), and
    the limit guards against files from elsewhere, so it is lifted for this one open and put back."""
    limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None
    try:
        with Image.open(path) as screenshot:
            yield screenshot
    finally:
        Image.MAX_IMAGE_PIXELS = limit


def apply(view, vp: dict) -> None:
    with own_capture(view.screenshot_path) as screenshot:
        css = paint.apply(view, vp, screenshot)
        media.apply(view, vp, css, screenshot)
        palette.apply(view, vp, screenshot)
