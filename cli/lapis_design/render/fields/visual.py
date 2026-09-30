"""Capture screenshot-based palette, CSS paint layers, icons, and media."""
from __future__ import annotations

from PIL import Image

from lapis_design.render.fields import media, paint, palette


def apply(view, vp: dict) -> None:
    with Image.open(view.screenshot_path) as screenshot:
        css = paint.apply(view, vp, screenshot)
        media.apply(view, vp, css, screenshot)
        palette.apply(view, vp, screenshot)
