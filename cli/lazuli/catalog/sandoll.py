"""Sandoll Cloud (산돌구름): per-family lookup of classification and license, 10 s between requests.

A lookup is at most three requests after robots.txt: the site's own search page (`/font-finder?commonSearch=`,
the GET its search form sends) for each family name in the installed font's name table, Korean first (the
catalog lists families by it) and then English, stopping at the first search that lists a result whose
Korean or Latin name equals one of the local font's names; then that result's page. Other results are
never taken as a match, so a miss returns None after the searches.
The search-log call the site's script makes before searching is not made.

Checked 2026-09-26: www.sandollcloud.com/robots.txt allows every path except /mypage for all agents
and states `Crawl-delay: 10`. The member and service terms (/policyTermsUser, /policyTermsService)
have no rule against tools for browsing; they forbid commercial use or redistribution of the
site's information, and automated access only for ticket purchases. Answers stay in the local cache.

Mapping: the page's 분류 values follow the Sandoll taxonomy that `hangul_classes` in type.yaml copies,
so Korean class names map through `labels.KO_CLASSES`; 손글씨 is the `hand` class; the Latin primary
classes map to the Latin genres. Everything else (심볼, Symbol, 기타, and bare subclass names such as
둥근 or Humanist) keeps only its raw text. License: fonts under /font/ are sold through Sandoll Cloud
passes (`commercial`); fonts under /free-font/ are `OFL-1.1` when tagged or marked OFL, else
`free-other`, with every use the license table does not mark 사용 가능 kept in the raw note.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from lazuli.catalog import labels
from lazuli.catalog.net import Fetcher
from lazuli.catalog.store import CatalogFamily, CatalogLabel
from lazuli.scan import norm

NAME = "sandoll"
KIND = "lookup"
PRIORITY = 61
TTL_DAYS = 90
MIN_INTERVAL_S = 10.0
REQUESTS_PER_LOOKUP = 3              # at most: the Korean and English searches and the family page

BASE = "https://www.sandollcloud.com"
SEARCH_URL = BASE + "/font-finder"

_CLASSES = {**labels.KO_CLASSES, "손글씨": "hand",
            "Serif": "serif", "Sans": "sans", "Slab": "slab", "Display": "display", "Script": "hand"}
_FAMILY_PATH = re.compile(r"^/(font|free-font)/(\d+)/")
_HANGUL = re.compile(r"[가-힣]")
_ALLOWED, _APPLIES = "사용 가능", "해당"               # license table values that are no limit
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
                   "source", "track", "wbr"})


class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: dict[str, str]):
        self.tag, self.attrs, self.children = tag, attrs, []

    def classes(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    def text(self) -> str:
        parts = [c if isinstance(c, str) else c.text() for c in self.children]
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    def iter(self):
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.iter()

    def find_all(self, tag: str, cls: str | None = None) -> list[_Node]:
        return [n for n in self.iter() if n.tag == tag and (cls is None or cls in n.classes())]

    def find(self, tag: str, cls: str | None = None) -> _Node | None:
        found = self.find_all(tag, cls)
        return found[0] if found else None


class _Tree(HTMLParser):
    """A forgiving element tree: void tags never open, a stray end tag closes up to its opener."""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self._stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, {k: v or "" for k, v in attrs})
        self._stack[-1].children.append(node)
        if tag not in _VOID:
            self._stack.append(node)

    def handle_endtag(self, tag):
        for depth in range(len(self._stack) - 1, 0, -1):
            if self._stack[depth].tag == tag:
                del self._stack[depth:]
                return

    def handle_data(self, data):
        self._stack[-1].children.append(data)


def _candidates(root: _Node) -> list[dict]:
    """Search results: family links holding a name span with Korean and Latin names."""
    out, seen = [], set()
    for anchor in root.find_all("a"):
        path = anchor.attrs.get("href", "")
        if not _FAMILY_PATH.match(path) or path in seen:
            continue
        span = next((n for n in anchor.iter() if n.tag == "span" and "ko-fontname" in n.attrs), None)
        if span is None:
            continue
        seen.add(path)
        out.append({"path": path, "ko": span.attrs["ko-fontname"].strip(), "en": span.attrs.get("en-fontname", "").strip()})
    return out


def _class_labels(value: str) -> list[CatalogLabel]:
    out: list[CatalogLabel] = []
    for raw in (part.strip() for part in value.split(",")):
        if raw:
            out += [label for label in labels.class_labels(raw, _CLASSES.get(raw)) if label not in out]
    return out


def _info(root: _Node) -> dict[str, _Node]:
    """The product information list: label text -> the value element."""
    info: dict[str, _Node] = {}
    for item in root.find_all("ul", "font_info_list"):
        for li in item.find_all("li"):
            label, value = li.find("label"), li.find("span")
            if label is not None and value is not None:
                info.setdefault(label.text(), value)
    return info


def _license(root: _Node, free: bool) -> CatalogLabel:
    if not free:
        section = root.find("section", "font_product")
        passes = [h.text() for h in section.find_all("h4")] if section is not None else []
        note = "유료폰트: 산돌구름 이용권" + (f" ({', '.join(passes)})" if passes else "")
        return CatalogLabel("license", note, "commercial")
    tags = [span.text() for span in root.find_all("span", "tag-chk")]
    rows = []
    for table in root.find_all("table"):                   # the license summary: 카테고리, 사용범위, 허용여부
        if any(th.text() == "허용여부" for th in table.find_all("th")):
            for tr in table.find_all("tr"):
                cells = [td.text() for td in tr.find_all("td")]
                if len(cells) >= 3:
                    rows.append((cells[0], cells[-1]))
    ofl = "OFL" in tags or ("OFL", _APPLIES) in rows
    limits = [f"{category} {value}" for category, value in rows if value and value not in (_ALLOWED, _APPLIES)]
    note = "무료폰트" + (f": {', '.join(tags)}" if tags else "") + (f"; {', '.join(limits)}" if limits else "")
    return CatalogLabel("license", note, "OFL-1.1" if ofl else "free-other")


def parse_family(html: str, path: str, candidate: dict) -> CatalogFamily:
    root = _Tree(html).root
    kind, number = _FAMILY_PATH.match(path).groups()
    free = kind == "free-font"
    info = _info(root)
    heading = root.find("h1", "font_name")
    ko = candidate["ko"] or (heading.text() if heading is not None else "")
    family = candidate["en"] or ko
    header = root.find("div", "font-header-info-wrap")
    maker = info.get("제작사") or (header.find("p", "cpname") if header is not None else None)
    designers = [a.text() for a in info["디자이너"].find_all("a")] if "디자이너" in info else []
    classification = info["분류"].text() if "분류" in info else ""
    lic = _license(root, free)
    return CatalogFamily(
        source_key=f"{kind}/{number}", family=family,
        names_i18n={"ko": ko} if ko != family and _HANGUL.search(ko) else {},
        foundry=maker.text() or None if maker is not None else None,
        designers=[d for d in designers if d],
        license=lic.mapped, url=BASE + path,
        labels=_class_labels(classification) + [lic])


def _queries(family: str, names_i18n: dict[str, str] | None) -> list[str]:
    """The Korean family name, then the English one; a name equal to an earlier one is searched once."""
    out, seen = [], set()
    for name in ((names_i18n or {}).get("ko"), family):
        if name and (key := norm(name)) and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def lookup(fetcher: Fetcher, family: str, *, names_i18n: dict[str, str] | None = None,
           postscript_name: str | None = None) -> CatalogFamily | None:
    names = [family, *(names_i18n or {}).values()]
    wanted = {norm(n) for n in names if norm(n)}
    for query in _queries(family, names_i18n):
        results = _candidates(_Tree(fetcher.get(SEARCH_URL, params={"commonSearch": query}).text()).root)
        match = next((c for c in results if wanted & {norm(c["ko"]), norm(c["en"])}), None)
        if match is not None:
            return parse_family(fetcher.get(BASE + match["path"]).text(), match["path"], match)
    return None
