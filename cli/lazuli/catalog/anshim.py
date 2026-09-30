"""안심글꼴 (safe font files) of the Korea Copyright Commission's Gongu site: a license source.

Two public pages list the fonts: public-sector fonts under 공공누리 (KOGL) and private fonts under
the OFL. Each font is a download button whose image alt text reads "<name> ,저작권자 : <holder>"
and whose `wrt-sn` attribute is the Gongu work number (its work page states the license per font).
A full run is three requests: robots.txt and the two pages. Buttons are never followed (they are
file downloads), and the view-count call the page makes on click is not made.

Checked 2026-09-26: gongu.copyright.or.kr/robots.txt disallows only /upload/ and the my-page path
for all agents; the Gongu terms (/gongu/main/contents.do?menuNo=200174) have no rule against tools
and forbid only copying the site's information for purposes other than the user's own use.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from lazuli.catalog.net import Fetcher
from lazuli.catalog.store import CatalogFamily, CatalogLabel

NAME = "anshim"
KIND = "snapshot"
PRIORITY = 40
TTL_DAYS = 90
MIN_INTERVAL_S = 3.0

BASE = "https://gongu.copyright.or.kr"
WORK_URL = BASE + "/gongu/wrt/wrt/view.do?wrtSn={}&menuNo=200195"
# (page, raw license text, license id). The pages' copyright notice
# (/static/freefontevent/copyrightinfo.html) gives the public fonts 공공누리 with attribution as the only
# condition, commercial use and changes allowed: that is KOGL type 1 by definition.
PAGES = (
    ("/freeFontEvent_KOGL.html", "공공 안심글꼴: 공공누리 출처표시 (상업적 이용·변경 가능)", "KOGL-1"),
    ("/freeFontEvent.html", "민간 안심글꼴: OFL (Open Font License)", "OFL-1.1"),
)

_ALT = re.compile(r"^\s*(?P<name>.+?)\s*,\s*저작권자\s*:\s*(?P<holder>.+?)\s*$")
# Weight suffixes the list appends to one family's files: "경기천년바탕체 B", "달서힐링체M", "전주완퐌본체 각R"
_WEIGHT = re.compile(r"(?:(?<=\s)|(?<=[가-힣]))(?:Thin|Light|Regular|Medium|Bold|ExtraBold|Black|Heavy"
                     r"|UL|EL|L|R|M|SB|B|EB|XB|VB|H)$")
# Organization credits written before a name, joined by commas: "문체부,한국출판인회의 KoPub World돋움체"
_CREDIT = re.compile(r"^[^\s,]+(?:,[^\s,]+)+\s+")
_HANGUL = re.compile(r"[가-힣]")


class _FontLinks(HTMLParser):
    """(wrt-sn or None, image alt) for every `a.fontLink` button; commented-out markup is skipped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str | None, str]] = []
        self._current: dict | None = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and "fontLink" in (attributes.get("class") or "").split():
            self._current = attributes
        elif tag == "img" and self._current is not None and attributes.get("alt"):
            self.links.append((self._current.get("wrt-sn"), attributes["alt"]))

    def handle_endtag(self, tag):
        if tag == "a":
            self._current = None


def family_name(name: str) -> str:
    """The family a listed font file belongs to: credits and a trailing weight removed."""
    name = _CREDIT.sub("", re.sub(r"\s+", " ", name).strip())
    return _WEIGHT.sub("", name).strip()


def parse(html: str, license_raw: str, license_id: str) -> list[CatalogFamily]:
    parser = _FontLinks()
    parser.feed(html)
    families: dict[str, CatalogFamily] = {}
    for wrt_sn, alt in parser.links:
        match = _ALT.match(alt)
        if not match:                                       # e.g. the "download everything" button
            continue
        family = family_name(match["name"])
        entry = families.get(family)
        if entry is None:
            entry = families[family] = CatalogFamily(
                source_key=family, family=family,
                names_i18n={"ko": family} if _HANGUL.search(family) else {},
                foundry=match["holder"], license=license_id,
                labels=[CatalogLabel("license", license_raw, license_id)])
        if entry.url is None and wrt_sn:
            entry.url = WORK_URL.format(wrt_sn)
    return list(families.values())


def fetch(fetcher: Fetcher) -> list[CatalogFamily]:
    families: dict[str, CatalogFamily] = {}
    for path, license_raw, license_id in PAGES:
        url = BASE + path
        found = parse(fetcher.get(url, store_as=path.lstrip("/")).text(), license_raw, license_id)
        if not found:
            # Never replace the snapshot with an empty list because the page layout changed
            raise ValueError(f"no fonts found at {url}; the page layout may have changed")
        for family in found:
            families.setdefault(family.source_key, family)
    return list(families.values())
