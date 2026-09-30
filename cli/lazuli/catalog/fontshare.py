"""Fontshare: a snapshot of every family, one request per 100 families (two requests today, with robots.txt).

`GET https://api.fontshare.com/v2/fonts?offset=0&limit=100` is the JSON the fontshare.com site loads
(no API documentation is published): `fonts` with name, slug, category, script, languages, native
name, publisher, designers, tags, license type, variable axes, and styles (weight, italic,
variable), plus `count_total` and `has_more`. On 2026-09-26 it had 100 families, all Latin; pages
continue while `has_more` is true and a page adds families not seen before. Styles carry no
PostScript names, so `fonts` stays empty and weights and italics are `property` labels.

Checked 2026-09-26: neither api.fontshare.com nor www.fontshare.com has a robots.txt (404 on the API
host; the site answers every path with its app shell). The site publishes no terms of service; its
Licenses page (fontshare.com/licenses/itf-ffl) holds the font licenses only: closed-source fonts
under the ITF Free Font License (free for personal and commercial use; no modification or
redistribution of the font software) and open-source fonts under the SIL OFL. Only metadata is read,
never font files. Responses are kept in `raw_payload` so the mapping can be re-applied with
`families_from`.

Mapping: comma-separated categories Sans, Serif, Slab, Display, Script, Handwritten to the Latin
genres (Script and Handwritten are `hand`; Blackletter keeps only the raw text). `license_type`
itf_ffl is the ITF Free Font License, `free-other`; sil_ofl is OFL-1.1. Tags ("Tags / Keywords" on the
site) are usage labels, except adjectives of character (feel) and form words (subclass); none maps to
the vocabulary. The script is a `script:<ISO 15924>` property label; the language list is one raw
property label. A native name in Hangul or kana becomes the ko or ja name.
"""
from __future__ import annotations

import json
import re

from lazuli.catalog import labels
from lazuli.catalog.google_fonts import SUBSET_SCRIPTS, axis_label, style_labels
from lazuli.catalog.net import Fetcher
from lazuli.catalog.store import CatalogFamily, CatalogLabel

NAME = "fontshare"
KIND = "snapshot"
PRIORITY = 21
TTL_DAYS = 30
MIN_INTERVAL_S = 3.0

LIST_URL = "https://api.fontshare.com/v2/fonts"
PAGE_SIZE = 100
FAMILY_URL = "https://www.fontshare.com/fonts/{}"

_CATEGORY = {"sans": "sans", "serif": "serif", "slab": "slab", "display": "display", "script": "hand",
             "handwritten": "hand", "handwriting": "hand", "mono": "mono", "monospace": "mono"}
# license_type -> (the license's own name, vocabulary id)
_LICENSES = {"itf_ffl": ("ITF Free Font License", "free-other"), "sil_ofl": ("OFL-1.1", "OFL-1.1")}
_FEEL_TAGS = frozenset({"bold", "clean", "compact", "experimental", "friendly", "fun", "funny", "grunge", "informal",
                        "luxury", "modern", "soft", "tech", "tight", "workhorse"})
_FORM_TAGS = frozenset({"calligraphy", "handwriting", "handwritten", "monospaced", "pen"})
_HANGUL = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]")
_KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")


def _tag_kind(tag: str) -> str:
    key = tag.strip().lower()
    return "feel" if key in _FEEL_TAGS else "subclass" if key in _FORM_TAGS else "usage"


def _names_i18n(native: str | None) -> dict[str, str]:
    if not native:
        return {}
    if _HANGUL.search(native):
        return {"ko": native}
    if _KANA.search(native):
        return {"ja": native}
    return {}


def _family(entry: dict) -> CatalogFamily:
    license_type = entry.get("license_type")
    license_name, license_id = _LICENSES.get(license_type, (license_type, labels.map_license(license_type)))
    publisher = (entry.get("publisher") or {}).get("name")
    family = CatalogFamily(
        source_key=entry["slug"], family=entry["name"], names_i18n=_names_i18n(entry.get("native_name")),
        foundry=publisher, designers=[d["name"] for d in entry.get("designers") or () if d.get("name")],
        license=license_name, url=FAMILY_URL.format(entry["slug"]))
    for category in (entry.get("category") or "").split(","):
        if category := category.strip():
            family.labels += labels.class_labels(category, _CATEGORY.get(category.lower()))
    for tag in entry.get("font_tags") or ():
        if name := (tag.get("name") or "").strip():
            family.labels.append(CatalogLabel(_tag_kind(name), name))
    if script := entry.get("script"):
        mapped = SUBSET_SCRIPTS.get(script.lower())
        family.labels.append(CatalogLabel("property", script, f"script:{mapped}" if mapped else None))
    if languages := (entry.get("languages") or "").strip():
        family.labels.append(CatalogLabel("property", languages))
    styles = entry.get("styles") or ()
    family.labels += style_labels([s["weight"]["weight"] for s in styles if (s.get("weight") or {}).get("weight")],
                                  any(s.get("is_italic") for s in styles))
    family.labels += [axis_label(a["property"], a["range_left"], a["range_right"]) for a in entry.get("axes") or ()]
    if license_type:
        family.labels.append(CatalogLabel("license", license_type, license_id))
    return family


def families_from(pages: list[str]) -> list[CatalogFamily]:
    """The snapshot from the kept page responses, in order; a family seen twice is kept once."""
    families: dict[str, CatalogFamily] = {}
    for page in pages:
        for entry in json.loads(page).get("fonts") or ():
            if entry.get("slug") and entry.get("name") and entry["slug"] not in families:
                families[entry["slug"]] = _family(entry)
    return list(families.values())


def fetch(fetcher: Fetcher) -> list[CatalogFamily]:
    pages, seen, offset = [], set(), 0
    while True:
        text = fetcher.get(LIST_URL, params={"offset": offset, "limit": PAGE_SIZE},
                           store_as=f"v2/fonts?offset={offset}").text()
        pages.append(text)
        page = json.loads(text)
        slugs = {entry.get("slug") for entry in page.get("fonts") or ()} - {None}
        if not page.get("has_more") or not slugs - seen:
            break
        seen |= slugs
        offset += PAGE_SIZE
    return families_from(pages)
