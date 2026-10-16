"""안심글꼴 (safe font files) of the Korea Copyright Commission's Gongu site: a license source, and a chart.

Two public pages list the fonts: public-sector fonts under 공공누리 (KOGL) and private fonts under
the OFL. Each font is a download button whose image alt text reads "<name> ,저작권자 : <holder>"
and whose `wrt-sn` attribute is the Gongu work number (its work page states the license per font).
Buttons are never followed (they are file downloads), and the view-count call the page makes on click
is not made.

Two tabs of the free-font board (`/gongu/bbs/B0000018/list.do?menuNo=20019`) add to them. Each of its
entries is a `div.font_box` with the font's name (`span.tit`), its provider (`p.font_source`), a link to
the provider's own page (`a.fontLink`), and the usage conditions the Gongu staff wrote (`div.txt_link`,
lines separated by `<br/>`):
- `bbsSeCd=04` 민간 무료글꼴 정보, free fonts of companies and organizations, nine pages of 16 on
  2026-10-16, followed through the pager's last-page link (at most MAX_BOARD_PAGES pages). The
  conditions are free text, so a family from here is `custom-free` with the text kept verbatim as the
  license label's raw value (whitespace collapsed as a browser shows it, one line per `<br/>`) and the
  page it came from in `details["conditions_url"]`. The text is never mapped to a named license, even when it
  names the OFL: whether a condition fits a use is the reader's decision. The provider's own page is the
  family's URL.
- `bbsSeCd=01` 인기글꼴TOP20, one page of 20 in the page's order (it prints no number, so the position is
  the rank). A listed family gets the `popularity_kind: chart` signal, which says familiar and nothing about
  the families it does not list. A listed family no other page knows becomes a `custom-free` family like the
  above; one the two license pages already list keeps their license.
A family whose name is Hangul also gets a `script:hang` label derived from the name (raw "name in Hangul"):
the pages give no coverage, and a family named in Hangul by a Korean provider is a Hangul family.

A full run is robots.txt, the two license pages, the chart, and the board's pages: 13 requests at 3 s on
2026-10-16.

Checked 2026-10-16: gongu.copyright.or.kr/robots.txt disallows only /upload/ and the my-page path for
all agents (it names a few crawlers by their user agent; lazuli is none of them), so the board pages are
open to it. The Gongu terms (/gongu/main/contents.do?menuNo=200174) have no rule against tools; they
forbid a member to copy the site's information for a purpose other than the member's own use or to give it to
a third party, and lazuli keeps what it reads only in the user's own cache, never in the repository or a
shipped file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
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
BOARD_URL = BASE + "/gongu/bbs/B0000018/list.do?menuNo=20019&bbsSeCd={board}&pageIndex={page}"
CHART_BOARD, FREE_BOARD = "01", "04"
CHART_LIST = "인기글꼴 TOP20"
MAX_BOARD_PAGES = 20
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
_LAST_PAGE = re.compile(r"title=['\"]마지막 목록['\"]\s+href=['\"][^'\"]*pageIndex=(\d+)")


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


@dataclass
class BoardEntry:
    name: str
    holder: str
    link: str | None
    conditions: str                 # the Gongu staff's text, one line per `<br/>`, "" when the entry has none


class _Board(HTMLParser):
    """The `div.font_box` entries of a free-font board page. The conditions' hidden close button is not text of them."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries: list[BoardEntry] = []
        self._entry: dict | None = None
        self._depth = 0                      # open divs inside the entry, the entry's own included
        self._field: str | None = None       # name | holder | lines
        self._lines_depth = 0                # depth of the conditions div
        self._skip = 0                       # depth of a close-button div inside the conditions, else 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if self._entry is None:
            if tag == "div" and "font_box" in classes:
                self._entry, self._depth = {"name": "", "holder": "", "link": None, "lines": [""]}, 1
            return
        if tag == "div":
            self._depth += 1
            if "txt_link" in classes:
                self._field, self._lines_depth = "lines", self._depth
            elif self._field == "lines" and "btnClose" in classes:
                self._skip = self._depth
        elif tag == "span" and "tit" in classes:
            self._field = "name"
        elif tag == "p" and "font_source" in classes:
            self._field = "holder"
        elif tag == "a" and "fontLink" in classes:
            self._entry["link"] = attributes.get("href")
        elif tag == "br" and self._field == "lines":
            self._entry["lines"].append("")

    def handle_endtag(self, tag):
        if self._entry is None:
            return
        if tag == "div":
            if self._skip == self._depth:
                self._skip = 0
            if self._field == "lines" and self._depth == self._lines_depth:
                self._field = None
            self._depth -= 1
            if self._depth == 0:
                self._finish()
        elif tag in ("span", "p") and self._field in ("name", "holder"):
            self._field = None

    def handle_data(self, data):
        if self._entry is None or self._skip:
            return
        if self._field in ("name", "holder"):
            self._entry[self._field] += data
        elif self._field == "lines":
            self._entry["lines"][-1] += data

    def _finish(self) -> None:
        entry, self._entry = self._entry, None
        name = re.sub(r"\s+", " ", entry["name"]).strip()
        if not name:
            return
        lines = [line for line in (re.sub(r"\s+", " ", raw).strip() for raw in entry["lines"]) if line]
        self.entries.append(BoardEntry(name, re.sub(r"\s+", " ", entry["holder"]).strip(), entry["link"],
                                       "\n".join(lines)))


def parse_board(html: str) -> list[BoardEntry]:
    parser = _Board()
    parser.feed(html)
    return parser.entries


def last_page(html: str) -> int:
    """The board's last page number from the pager, 1 when the page has no pager."""
    return int(match[1]) if (match := _LAST_PAGE.search(html)) else 1


def family_name(name: str) -> str:
    """The family a listed font file belongs to: credits and a trailing weight removed."""
    name = _CREDIT.sub("", re.sub(r"\s+", " ", name).strip())
    return _WEIGHT.sub("", name).strip()


def _script_labels(family: str) -> list[CatalogLabel]:
    return [CatalogLabel("property", "name in Hangul", "script:hang")] if _HANGUL.search(family) else []


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
                labels=[CatalogLabel("license", license_raw, license_id), *_script_labels(family)])
        if entry.url is None and wrt_sn:
            entry.url = WORK_URL.format(wrt_sn)
    return list(families.values())


def _board_family(entry: BoardEntry, page_url: str) -> CatalogFamily:
    """A family from a board entry: `custom-free` with the conditions text verbatim, or no license when the entry has none."""
    family = family_name(entry.name)
    labels = [CatalogLabel("license", entry.conditions, "custom-free")] if entry.conditions else []
    return CatalogFamily(
        source_key=family, family=family, names_i18n={"ko": family} if _HANGUL.search(family) else {},
        foundry=entry.holder or None, license="custom-free" if entry.conditions else None, url=entry.link,
        labels=[*labels, *_script_labels(family)],
        details={"conditions_url": page_url} if entry.conditions else {})


def add_board(families: dict[str, CatalogFamily], chart: list[BoardEntry], chart_url: str,
              free: list[tuple[str, list[BoardEntry]]]) -> None:
    """Add the free-font board's families to `families` (the license pages' ones keep their license), then the
    chart's positions as `popularity` signals; `free` is [(page URL, entries)]."""
    for url, entries in free:
        for entry in entries:
            families.setdefault(family_name(entry.name), _board_family(entry, url))
    for position, entry in enumerate(chart, 1):
        family = families.setdefault(family_name(entry.name), _board_family(entry, chart_url))
        family.signals = {"popularity": position, "popularity_kind": "chart", "popularity_list": CHART_LIST}


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

    chart_url = BOARD_URL.format(board=CHART_BOARD, page=1)
    chart = parse_board(fetcher.get(chart_url, store_as=f"B0000018-{CHART_BOARD}.html").text())
    first_url = BOARD_URL.format(board=FREE_BOARD, page=1)
    first = fetcher.get(first_url, store_as=f"B0000018-{FREE_BOARD}-p1.html").text()
    free = [(first_url, parse_board(first))]
    for url, entries in [(chart_url, chart), free[0]]:
        if not entries:
            raise ValueError(f"no fonts found at {url}; the page layout may have changed")
    for page in range(2, min(last_page(first), MAX_BOARD_PAGES) + 1):
        url = BOARD_URL.format(board=FREE_BOARD, page=page)
        free.append((url, parse_board(fetcher.get(url, store_as=f"B0000018-{FREE_BOARD}-p{page}.html").text())))
    add_board(families, chart, chart_url, free)
    return list(families.values())
