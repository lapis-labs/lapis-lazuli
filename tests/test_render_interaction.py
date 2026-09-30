"""Measured interaction, accessibility, motion, clipping and scroll behavior."""
from __future__ import annotations

from pathlib import Path

import pytest

from lapis_design.render import _configs, fields
from lapis_design.render.capture import capture
from lapis_design.render.extract import assemble, validate
from lapis_design.render.fields import interaction


@pytest.fixture
def measured(browser, render_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(fields, "FIELD_MODULES", (interaction,))
    url = f"{render_server}/interaction-fields.html"
    key = bytes(range(32))
    vp = capture(browser, url, _configs(False, [390])[0], tmp_path / "interaction.png", key=key)
    assert not validate(assemble(url, "interaction", [vp], key, dark_theme=False))
    return {box["id"]: box for box in vp["boxes"]}, vp


def test_accessibility_and_focus(measured):
    boxes, _ = measured
    # Fixture IDs are on the original DOM nodes, so their hashed box IDs are stable.
    from lapis_design.render.ids import box_id

    def get(tag, ident):
        return boxes[box_id([("html", 0, None), ("body", 0, None),
                             ("main", 0, "content"), (tag, 0, ident)])]

    cursor = get("div", "cursor-handler")["a11y"]
    assert cursor["pointer_handler"] is True
    assert cursor["pointer_cursor"] is True
    assert cursor["focusable"] is False
    assert get("button", "no-focus")["a11y"]["focus_indicator"] is False
    assert get("button", "focus-visible")["a11y"]["focus_indicator"] is True
    assert get("button", "focus-background")["a11y"]["focus_indicator"] is True
    for ident in ("listener", "framework-props"):
        assert get("div", ident)["a11y"]["pointer_handler"] is True
        assert get("div", ident)["a11y"]["keyboard_handler"] is True
    placeholder = get("input", "placeholder")["a11y"]
    assert placeholder["name"] == "Only placeholder"
    assert placeholder["name_source"] == "placeholder"
    assert get("input", "labeled")["a11y"]["name_source"] == "label"
    wrapped = boxes[box_id([("html", 0, None), ("body", 0, None), ("main", 0, "content"),
                            ("label", 1, None), ("input", 0, "wrapped")])]["a11y"]
    assert (wrapped["name"].strip(), wrapped["name_source"]) == ("Wrapped", "label")
    assert get("svg", "hidden-icon")["a11y"]["hidden"] is True


def test_motion_scroll_clipping_and_layout_shift(measured):
    boxes, vp = measured
    from lapis_design.render.ids import box_id

    def get(tag, ident):
        return boxes[box_id([("html", 0, None), ("body", 0, None),
                             ("main", 0, "content"), (tag, 0, ident)])]

    card = get("div", "card")["motion"]
    assert any(entry["property"] == "all" and entry["duration_ms"] == 300
               for entry in card["transitions"])
    assert "transform" in card["hover_changes"]
    marquee = get("div", "marquee")["motion"]
    assert marquee["moves_at_rest"] is True
    assert any(entry["iterations"] == "infinite" and "transform" in entry["properties"]
               for entry in marquee["animations"])
    assert get("section", "reveal")["motion"]["hidden_until_scroll"] is True
    assert get("section", "timer-only")["motion"]["hidden_until_scroll"] is False
    expanded = {entry["property"] for entry in get("div", "cursor-handler")["motion"]["transitions"]}
    assert {"margin-top", "margin-right", "margin-bottom", "margin-left"} <= expanded
    assert "margin" not in expanded
    assert "background-color" in get("div", "hover-only")["motion"]["hover_changes"]
    assert get("div", "blink")["motion"]["animations"][0]["stepped"] is True
    carousel = get("div", "carousel")["scroll"]
    assert carousel["axis"] == "x"
    assert carousel["items"] == 3
    assert carousel["content_px"] > 180
    assert carousel["inset_start_px"] == pytest.approx(12)
    assert carousel["inset_end_px"] == pytest.approx(12)
    long_list = get("ul", "long-list")["scroll"]
    assert long_list["axis"] == "page" and long_list["items"] == 2
    assert get("p", "ellipsis")["clipped"] == "ellipsis"
    assert get("p", "clamp")["clipped"] == "line-clamp"
    assert get("div", "overflow")["clipped"] == "overflow"
    assert vp["metrics"]["cls"] > 0
    moved = {get("div", "cursor-handler")["id"], get("button", "no-focus")["id"],
             get("div", "card")["id"], box_id([("html", 0, None), ("body", 0, None),
                                               ("main", 0, "content")])}
    assert moved.intersection(vp["metrics"]["shift_sources"])


def test_layout_shift_window_ends_one_idle_second_after_the_last_scroll_step(
        browser, render_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(fields, "FIELD_MODULES", (interaction,))
    vp = capture(browser, f"{render_server}/lazy-shift.html", _configs(False, [390])[0],
                 tmp_path / "lazy.png", key=bytes(range(32)))
    from lapis_design.render.ids import box_id
    below = box_id([("html", 0, None), ("body", 0, None), ("main", 0, "page"), ("section", 1, "below")])
    assert vp["metrics"]["cls"] > 0                              # lazy content placed after the last step
    assert vp["metrics"]["shift_sources"] == [below]             # not the banner added back at the top


def test_reduced_motion_uses_the_page_computed_state(browser, render_server: str,
                                                      tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(fields, "FIELD_MODULES", (interaction,))
    config = next(config for config in _configs(False, [390]) if config["reduced_motion"])
    vp = capture(browser, f"{render_server}/interaction-fields.html", config,
                 tmp_path / "reduced.png", key=bytes(range(32)))
    from lapis_design.render.ids import box_id
    marquee_id = box_id([("html", 0, None), ("body", 0, None),
                         ("main", 0, "content"), ("div", 0, "marquee")])
    marquee = next(box for box in vp["boxes"] if box["id"] == marquee_id)
    assert "animations" not in marquee.get("motion", {})
    assert marquee.get("motion", {}).get("moves_at_rest") is not True


def test_scroll_driven_animation_is_recorded_without_a_time_duration(browser, render_server: str,
                                                                     tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # animation-timeline: view() computes animation-duration as `auto`; the capture used to stop on it.
    monkeypatch.setattr(fields, "FIELD_MODULES", (interaction,))
    url = f"{render_server}/scroll-driven.html"
    key = bytes(range(32))
    vp = capture(browser, url, _configs(False, [390])[0], tmp_path / "scroll.png", key=key)
    assert not validate(assemble(url, "scroll", [vp], key, dark_theme=False))
    from lapis_design.render.ids import box_id
    settle_id = box_id([("html", 0, None), ("body", 0, None), ("main", 0, "page"), ("section", 0, "settle")])
    settle = next(box for box in vp["boxes"] if box["id"] == settle_id)
    (animation,) = settle["motion"]["animations"]
    assert animation["name"] == "settle" and "duration_ms" not in animation
    assert {"opacity", "transform"} <= set(animation["properties"])
