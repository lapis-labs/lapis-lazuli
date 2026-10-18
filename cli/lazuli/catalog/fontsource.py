"""Fontsource: a snapshot of every family Fontsource packages, in one request (two with robots.txt).

`GET https://api.fontsource.org/v1/fonts` is the documented list endpoint of the public, read-only
Fontsource API (fontsource.org/docs/api/fonts): id, family, subsets, weights, styles, variable,
category, license (an SPDX id), and type (`google` for Google Fonts families, `other` for the rest),
about 0.5 MB of JSON. It has no designers, foundries, PostScript names, or CJK names, and neither has
the per-family endpoint, so `fonts` stays empty and weights and italics are `property` labels.
Fontsource is a supplement: it snapshots everything, and matching prefers google-fonts by priority.

Checked 2026-09-26: api.fontsource.org has no robots.txt (404). The API docs
(fontsource.org/docs/api/introduction) say any HTTP client may read it, ask users to sponsor the
project, and reserve throttling under fair use above a hard limit of 2500 requests per 10 seconds.
The response is kept in `raw_payload` so the mapping can be re-applied with `families_from`.

Mapping: category sans-serif, serif, display, handwriting, monospace to the Latin genres (other and
icons keep only the raw text); OFL-1.1, Apache-2.0, and UFL-1.0 as they are; other free SPDX
licenses (CC0-1.0, MIT, Unlicense) to `free-other`; subsets to `script:<ISO 15924>` like Google Fonts.

Primary script (`details.primary_scripts`, `primary_basis`): the list keeps `defSubset`, the subset the family opens
with, and `subsets`. A `defSubset` that is a script other than Latin (checked 2026-10-18 on the kept list: khmer for
Chenla and Siemreap, tamil, lao, myanmar; `emoji` is no script) is the family's primary script; a family with
subsets of scripts but no Latin subset is primary for those scripts. A `latin` default says nothing: 2,087 of the
2,100 families have it, Noto Sans KR and Pretendard among them, so a Latin default with a Korean subset is not read
as Latin-first or Korean-first, and the family stays unknown, counted as covering every script it lists. The `type`
field (`google` or `other`) is no script statement; a Fontsource family that is also in Google Fonts takes Google's
`primaryScript` through its merged candidate. The category `icons` names a purpose, not a script (`lazuli search
--role` reads it); `remap` re-applies all of this from the kept list with no request.
"""
from __future__ import annotations

import json

from lazuli.catalog import labels, store
from lazuli.catalog.google_fonts import SUBSET_SCRIPTS, style_labels, subset_labels
from lazuli.catalog.net import Fetcher
from lazuli.catalog.store import CatalogFamily, CatalogLabel

NAME = "fontsource"
KIND = "snapshot"
PRIORITY = 20
TTL_DAYS = 30
MIN_INTERVAL_S = 3.0

LIST_URL = "https://api.fontsource.org/v1/fonts"
FAMILY_URL = "https://fontsource.org/fonts/{}"

_CATEGORY = {"sans-serif": "sans", "serif": "serif", "display": "display", "handwriting": "hand", "monospace": "mono"}


def _primary(entry: dict) -> tuple[list[str], str] | None:
    """(scripts, basis) when the entry says what script the family opens with, else None (module doc)."""
    default = entry.get("defSubset")
    if (code := SUBSET_SCRIPTS.get(default or "")) and code != "latn":
        return [code], f"default subset {default}"
    codes = list(dict.fromkeys(code for subset in entry.get("subsets") or () if (code := SUBSET_SCRIPTS.get(subset))))
    if codes and "latn" not in codes:
        return codes, "no Latin subset"
    return None


def _family(entry: dict) -> CatalogFamily:
    raw_license = entry.get("license")
    mapped_license = labels.map_spdx(raw_license)
    family = CatalogFamily(source_key=entry["id"], family=entry["family"],
                           license=mapped_license or raw_license, url=FAMILY_URL.format(entry["id"]))
    if primary := _primary(entry):
        family.details["primary_scripts"], family.details["primary_basis"] = primary
    if category := entry.get("category"):
        family.labels += labels.class_labels(category, _CATEGORY.get(category))
    family.labels += subset_labels(entry.get("subsets") or ())
    family.labels += style_labels([w for w in entry.get("weights") or () if isinstance(w, int)],
                                  "italic" in (entry.get("styles") or ()))
    if entry.get("variable"):
        family.labels.append(CatalogLabel("property", "variable"))
    if raw_license:
        family.labels.append(CatalogLabel("license", raw_license, mapped_license))
    return family


def families_from(listing: str) -> list[CatalogFamily]:
    """The snapshot from the kept list response."""
    families: dict[str, CatalogFamily] = {}
    for entry in json.loads(listing):
        if entry.get("id") and entry.get("family") and entry["id"] not in families:
            families[entry["id"]] = _family(entry)
    return list(families.values())


def fetch(fetcher: Fetcher) -> list[CatalogFamily]:
    return families_from(fetcher.get(LIST_URL, store_as="v1/fonts").text())


def from_raw(conn) -> list[CatalogFamily] | None:
    """The snapshot re-mapped from the kept list response (no request), or None when it was not kept."""
    listing = store.load_raw(conn, NAME, "v1/fonts")
    return None if listing is None else families_from(listing.decode())
