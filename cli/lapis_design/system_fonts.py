"""The generic families of fonts/system-fonts.yaml, read in one place.

A family listed there with `class: generic` is a CSS generic keyword or a vendor alias for the system
UI face. It names no face: it needs no fonts lock entry, is never looked up in the lazuli database, and
is never a font a page failed to load. `platform_sans` is the subset that resolves to a sans the
platform or browser picks. Names are compared without letter case.

The plan check and the lint detectors that must not treat such a name as a face all read this table,
so a name added to it is generic everywhere.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from lapis_design import shared_dir


@lru_cache(maxsize=None)
def _read(path: Path) -> tuple[frozenset[str], frozenset[str]]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    generic = frozenset(str(font["family"]).casefold() for font in doc.get("fonts") or ()
                        if font.get("class") == "generic" and font.get("family"))
    sans = frozenset(str(name).casefold() for name in doc.get("platform_sans") or ())
    return generic, sans


def _table() -> tuple[frozenset[str], frozenset[str]]:
    return _read(shared_dir() / "fonts" / "system-fonts.yaml")


def generic_families() -> frozenset[str]:
    """Case-folded names of the generic families."""
    return _table()[0]


def platform_sans() -> frozenset[str]:
    """Case-folded generic names that resolve to a sans the platform or browser picks."""
    return _table()[1]


def is_generic(family: str) -> bool:
    return family.strip().casefold() in generic_families()
