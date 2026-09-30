"""Ordered capture field passes, executed while the Playwright page remains live.

Each registered module implements apply(view: RawView, vp: dict) -> None and may add
schema-defined viewport/box/text fields to vp; inspect view.elements for box metadata, and
find a box's element in the page as [data-lapis-box="<id>"]. Optional hooks:
  INIT_SCRIPT: str               added to the browser context before navigation
  observe_rest(view) -> None     called at rest after load, before the scroll pass
  after_scroll(view) -> None     called at the bottom of the page once the network has been idle
                                 for 1 s after the last scroll step, before returning to the top
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from lapis_design.render.fields import interaction, text, visual

if TYPE_CHECKING:
    from lapis_design.render.raw import RawView

# Order matters: each pass restores the page before the next one runs.
FIELD_MODULES: tuple[object, ...] = (text, visual, interaction)


def init_scripts() -> list[str]:
    return [script for module in FIELD_MODULES if (script := getattr(module, "INIT_SCRIPT", None))]


def observe_rest(view: RawView) -> None:
    """Optional pre-scroll observation; passes retain measurements in view.extra."""
    for module in FIELD_MODULES:
        if observer := getattr(module, "observe_rest", None):
            observer(view)


def after_scroll(view: RawView) -> None:
    """Optional observation that closes with the scroll pass (the layout-shift window)."""
    for module in FIELD_MODULES:
        if observer := getattr(module, "after_scroll", None):
            observer(view)


def apply_fields(view: RawView, vp: dict) -> None:
    for module in FIELD_MODULES:
        module.apply(view, vp)
