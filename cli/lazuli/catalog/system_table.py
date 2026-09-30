"""System fonts table (bundled): `fonts/system-fonts.yaml` from the shared contracts, no network.

Each entry becomes a family keyed by its name, with genre and subclass labels from `class` and the
table's default license (`system`: usable only where the device has it). `class: generic` marks a CSS
generic keyword, not a genre, so its genre label keeps only the raw text.
"""
from __future__ import annotations

import re

import yaml

from lapis_design import shared_dir
from lazuli.catalog import labels
from lazuli.catalog.store import CatalogFamily, CatalogLabel

NAME = "system-table"
KIND = "bundled"
PRIORITY = 50
TTL_DAYS = None
MIN_INTERVAL_S = 0.0


def fetch(fetcher=None) -> list[CatalogFamily]:
    table = yaml.safe_load((shared_dir() / "fonts" / "system-fonts.yaml").read_text(encoding="utf-8"))
    license_id = table["defaults"]["license"]
    families = []
    for entry in table["fonts"]:
        cls = entry["class"]
        value = cls if cls in labels.GENRES or cls in labels.SUBCLASSES else None
        families.append(CatalogFamily(
            source_key=re.sub(r"[^a-z0-9]+", "-", entry["family"].lower()).strip("-"),
            family=entry["family"],
            license=license_id,
            labels=labels.class_labels(cls, value)
            + [CatalogLabel("license", license_id, license_id if license_id in labels.LICENSES else None)]))
    return families
