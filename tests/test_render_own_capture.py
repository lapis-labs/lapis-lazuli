"""The screenshot a render run wrote itself is opened past the decompression-bomb limit: a scroll-driven page at 1440 px is
legitimately tens of millions of pixels, and Pillow warns past 89 million and raises past twice that."""
from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from PIL import Image

from lapis_design.render.fields import visual


def test_a_tall_own_screenshot_opens_without_the_bomb_warning_and_the_limit_is_put_back(tmp_path: Path, monkeypatch):
    shot = tmp_path / "tall.png"
    Image.new("RGB", (20, 20), "white").save(shot)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)                  # 400 pixels: past the limit, and past twice it
    with pytest.raises(Image.DecompressionBombError):
        Image.open(shot)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with visual.own_capture(shot) as image:
            assert image.size == (20, 20)
    assert Image.MAX_IMAGE_PIXELS == 100
    with pytest.raises(Image.DecompressionBombError):                    # the guard against other files is back
        Image.open(shot)
    with pytest.raises(RuntimeError), visual.own_capture(shot):
        raise RuntimeError("a field pass failed")
    assert Image.MAX_IMAGE_PIXELS == 100
