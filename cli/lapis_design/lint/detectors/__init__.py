"""Detector modules, one per slice. Importing a module registers its detectors in lint.types.DETECTORS.
`load(layer)` imports only the modules with detectors at that layer, so a plan-layer run (the
exit-plan hook) never loads the render modules or what they import; `load()` imports every module."""
from __future__ import annotations

import importlib

# Each module and the layers it registers detectors at. A module missing a layer here only costs
# speed: the engine loads every module before it calls a name unregistered.
MODULES: dict[str, tuple[str, ...]] = {
    "font_regions": ("plan",),
    "plan_candidates": ("plan",),
    "copy": ("plan", "render", "review"),
    "source": ("source",),
    "render_type": ("render",),
    "render_layout": ("render", "behavior"),
    "render_visual": ("render",),
    "behavior": ("behavior",),
}


def load(layer: str | None = None) -> None:
    for name, layers in MODULES.items():
        if layer is None or layer in layers:
            importlib.import_module(f"{__name__}.{name}")
