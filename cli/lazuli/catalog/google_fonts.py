"""Google Fonts: a snapshot of the whole collection in five requests (seven with the two robots.txt).

Requests, in order:
1. `https://fonts.google.com/metadata/fonts`: the family listing fonts.google.com itself loads, about
   2.7 MB of JSON for every family (category, stroke, classifications, designers, subsets, weights and
   italics, variable axes, primary script).
2. `tags/all/families.csv` of the google/fonts repository through the GitHub contents API: every
   family's tags with weights (0-100), some per variable-axis position.
3-5. The GitHub trees of the repository's `ofl`, `apache`, and `ufl` directories. The top directory
   is the license of every family in it, and family directories are named by the lowercased family
   name without spaces or punctuation, so a family gets a license only when exactly one directory
   has that name (a few renamed families keep an old directory name and get none).

PostScript names are only in each family's METADATA.pb, one request per family (about 1,950, over
1.5 hours at 3 s), so the snapshot has none: `fonts` stays empty and weights, italics, and axes are
`property` labels. The listing has no Korean, Japanese, or Chinese names either.

Checked 2026-09-26: fonts.google.com/robots.txt disallows only /license/ for every agent, and the
Google Terms of Service forbid automated access only against a page's machine-readable instructions
such as robots.txt. api.github.com has no robots.txt; GitHub's API terms (Terms of Service, section H)
allow API use within the rate limits, which are 60 requests an hour without signing in. Every
response is kept in `raw_payload` so the mapping can be re-applied with `families_from`.

Mapping: `category`, `stroke`, and `classifications` become genre labels (raw keeps the field);
for families whose primary script is Korean, Japanese, or Chinese, the category also names the
CJK class (Serif is 부리 as in 명조/明朝/宋, Sans Serif is 민부리 as in 고딕/ゴシック/黑). Tag groups become
subclass (Sans, Serif, Slab, Script, Monospace, Display, Theme, Not text), feel (Expressive), usage
(Purpose, Special use, Seasonal), or property (Quality) labels with the tag's weight, `mapped` null:
the type vocabulary has no Latin subclasses or feels, and a Latin tag such as /Sans/Rounded says
nothing sound about a family's Hangul. Subsets become `script:<ISO 15924>` property labels.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict

from lazuli.catalog import labels
from lazuli.catalog.net import Fetcher
from lazuli.catalog.store import CatalogFamily, CatalogLabel

NAME = "google-fonts"
KIND = "snapshot"
PRIORITY = 10
TTL_DAYS = 30
MIN_INTERVAL_S = 3.0

METADATA_URL = "https://fonts.google.com/metadata/fonts"
TAGS_URL = "https://api.github.com/repos/google/fonts/contents/tags/all/families.csv"
TREE_URL = "https://api.github.com/repos/google/fonts/git/trees/main:{}"
_GITHUB_API = {"X-GitHub-Api-Version": "2022-11-28"}
RAW_HEADERS = {**_GITHUB_API, "Accept": "application/vnd.github.raw+json"}      # a file's bytes
JSON_HEADERS = {**_GITHUB_API, "Accept": "application/vnd.github+json"}
LICENSE_DIRS = {"ofl": "OFL-1.1", "apache": "Apache-2.0", "ufl": "UFL-1.0"}
SPECIMEN_URL = "https://fonts.google.com/specimen/{}"
REPO_API = "https://api.github.com/repos/google/fonts"
REPO_PAGE = "https://github.com/google/fonts"

_CATEGORY = {"Sans Serif": "sans", "Serif": "serif", "Display": "display", "Handwriting": "hand", "Monospace": "mono"}
_STROKE = {"Sans Serif": "sans", "Serif": "serif", "Slab Serif": "slab"}
_CLASSIFICATION = {"Display": "display", "Handwriting": "hand", "Monospace": "mono"}
_CJK_SCRIPTS = frozenset({"Kore", "Hang", "Jpan", "Hira", "Kana", "Hrkt", "Hans", "Hant", "Hani"})
_CJK_CATEGORY = {"Serif": "bu-ri", "Sans Serif": "min-bu-ri"}   # Display and Handwriting share the Latin ids

_TAG_KINDS = {"Sans": "subclass", "Serif": "subclass", "Slab": "subclass", "Script": "subclass",
              "Monospace": "subclass", "Display": "subclass", "Theme": "subclass", "Not text": "subclass",
              "Expressive": "feel", "Purpose": "usage", "Special use": "usage", "Seasonal": "usage",
              "Quality": "property"}
_TAG_SKIP = frozenset({"quant", "Skip"})                     # computed metrics and tagging-tool switches

# Google Fonts subset (Unicode script name in kebab case) -> ISO 15924 code; Fontsource uses the same
# names. Subsets that are no script (menu, math, symbols, emoji, music, numerals, vietnamese as a
# language) are absent and keep only their raw text.
SUBSET_SCRIPTS = {
    "latin": "latn", "latin-ext": "latn", "cyrillic": "cyrl", "cyrillic-ext": "cyrl", "greek": "grek",
    "greek-ext": "grek", "korean": "hang", "japanese": "jpan", "chinese-simplified": "hans",
    "chinese-traditional": "hant", "chinese-hongkong": "hant", "arabic": "arab", "hebrew": "hebr",
    "armenian": "armn", "georgian": "geor", "thai": "thai", "lao": "laoo", "khmer": "khmr", "myanmar": "mymr",
    "tibetan": "tibt", "devanagari": "deva", "bengali": "beng", "gurmukhi": "guru", "gujarati": "gujr",
    "oriya": "orya", "tamil": "taml", "tamil-supplement": "taml", "telugu": "telu", "kannada": "knda",
    "malayalam": "mlym", "sinhala": "sinh", "ethiopic": "ethi", "syriac": "syrc", "thaana": "thaa",
    "mongolian": "mong", "cherokee": "cher", "canadian-aboriginal": "cans", "tifinagh": "tfng", "braille": "brai",
    "adlam": "adlm", "ahom": "ahom", "anatolian-hieroglyphs": "hluw", "avestan": "avst", "balinese": "bali",
    "bamum": "bamu", "bassa-vah": "bass", "batak": "batk", "beria-erfe": "berf", "bhaiksuki": "bhks",
    "brahmi": "brah", "buginese": "bugi", "buhid": "buhd", "carian": "cari", "caucasian-albanian": "aghb",
    "chakma": "cakm", "cham": "cham", "chorasmian": "chrs", "coptic": "copt", "cuneiform": "xsux",
    "cypriot": "cprt", "cypro-minoan": "cpmn", "deseret": "dsrt", "dives-akuru": "diak", "dogra": "dogr",
    "duployan": "dupl", "egyptian-hieroglyphs": "egyp", "elbasan": "elba", "elymaic": "elym", "glagolitic": "glag",
    "gothic": "goth", "grantha": "gran", "gunjala-gondi": "gong", "hanifi-rohingya": "rohg", "hanunoo": "hano",
    "hatran": "hatr", "imperial-aramaic": "armi", "inscriptional-pahlavi": "phli", "inscriptional-parthian": "prti",
    "javanese": "java", "kaithi": "kthi", "kawi": "kawi", "kayah-li": "kali", "kharoshthi": "khar",
    "khitan-small-script": "kits", "khojki": "khoj", "khudawadi": "sind", "kirat-rai": "krai", "lepcha": "lepc",
    "limbu": "limb", "linear-a": "lina", "linear-b": "linb", "lisu": "lisu", "lycian": "lyci", "lydian": "lydi",
    "mahajani": "mahj", "makasar": "maka", "mandaic": "mand", "manichaean": "mani", "marchen": "marc",
    "masaram-gondi": "gonm", "medefaidrin": "medf", "meetei-mayek": "mtei", "mende-kikakui": "mend",
    "meroitic-cursive": "merc", "meroitic-hieroglyphs": "mero", "miao": "plrd", "modi": "modi", "mro": "mroo",
    "multani": "mult", "nabataean": "nbat", "nag-mundari": "nagm", "nandinagari": "nand", "new-tai-lue": "talu",
    "newa": "newa", "nko": "nkoo", "nushu": "nshu", "nyiakeng-puachue-hmong": "hmnp", "ogham": "ogam",
    "ol-chiki": "olck", "old-hungarian": "hung", "old-italic": "ital", "old-north-arabian": "narb",
    "old-permic": "perm", "old-persian": "xpeo", "old-sogdian": "sogo", "old-south-arabian": "sarb",
    "old-turkic": "orkh", "old-uyghur": "ougr", "osage": "osge", "osmanya": "osma", "pahawh-hmong": "hmng",
    "palmyrene": "palm", "pau-cin-hau": "pauc", "phags-pa": "phag", "phoenician": "phnx", "psalter-pahlavi": "phlp",
    "rejang": "rjng", "runic": "runr", "samaritan": "samr", "saurashtra": "saur", "sharada": "shrd",
    "shavian": "shaw", "siddham": "sidd", "signwriting": "sgnw", "sogdian": "sogd", "sora-sompeng": "sora",
    "soyombo": "soyo", "sundanese": "sund", "sunuwar": "sunu", "syloti-nagri": "sylo", "tagalog": "tglg",
    "tagbanwa": "tagb", "tai-le": "tale", "tai-tham": "lana", "tai-viet": "tavt", "takri": "takr", "tangsa": "tnsa",
    "tangut": "tang", "tirhuta": "tirh", "todhri": "todr", "toto": "toto", "ugaritic": "ugar", "vai": "vaii",
    "vithkuqi": "vith", "wancho": "wcho", "warang-citi": "wara", "yezidi": "yezi", "yi": "yiii",
    "zanabazar-square": "zanb",
}
_NOT_COVERAGE = frozenset({"menu"})                          # the font picker's name-only subset


def subset_labels(subsets) -> list[CatalogLabel]:
    """One property label per subset: `script:<ISO 15924>` when the subset is a script, else raw only."""
    out = []
    for subset in subsets:
        if subset in _NOT_COVERAGE:
            continue
        script = SUBSET_SCRIPTS.get(subset)
        out.append(CatalogLabel("property", subset, f"script:{script}" if script else None))
    return out


def style_labels(weights, italic: bool) -> list[CatalogLabel]:
    """`weight:<n>` for every available weight and `style:italic` when italics exist."""
    out = [CatalogLabel("property", str(w), f"weight:{w}") for w in sorted(set(weights))]
    if italic:
        out.append(CatalogLabel("property", "italic", "style:italic"))
    return out


def axis_label(tag: str, low: float, high: float) -> CatalogLabel:
    return CatalogLabel("property", f"{tag} {low:g}-{high:g}", f"axis:{tag}")


def _slug(family: str) -> str:
    return re.sub(r"[^a-z0-9]", "", family.lower())


def repository_path(license_dir: str, family: str) -> str:
    """A family's folder in the google/fonts repository: its license directory and its slug."""
    return f"{license_dir}/{_slug(family)}"


def _listing(text: str) -> list[dict]:
    if text.startswith(")]}'"):                              # an anti-JSON-hijacking prefix, when present
        text = text.split("\n", 1)[1]
    return json.loads(text)["familyMetadataList"]


def _tags(text: str) -> dict[str, list[tuple[str, str, float]]]:
    """family -> [(tag, axis position or "", weight)] from families.csv (family,position,tag,weight)."""
    out: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for row in csv.reader(io.StringIO(text)):
        if len(row) == 4 and row[2].startswith("/"):
            try:
                out[row[0]].append((row[2], row[1], float(row[3])))
            except ValueError:
                continue
    return out


def _licenses(trees: dict[str, dict]) -> dict[str, str | None]:
    """Family directory name -> license directory, None when the name is in more than one."""
    found: dict[str, set[str]] = defaultdict(set)
    for directory, tree in trees.items():
        for entry in tree.get("tree", ()):
            if entry.get("type") == "tree":
                found[entry["path"]].add(directory)
    return {name: next(iter(dirs)) if len(dirs) == 1 else None for name, dirs in found.items()}


def _tag_labels(tags) -> list[CatalogLabel]:
    out = []
    for tag, position, weight in tags:
        group = tag.strip("/").split("/", 1)[0]
        if group in _TAG_SKIP:
            continue
        raw = f"{tag} {position}" if position else tag
        out.append(CatalogLabel(_TAG_KINDS.get(group, "property"), raw, None, weight))
    return out


def _genre_labels(entry: dict) -> list[CatalogLabel]:
    """Genre labels from category, stroke, and classifications; a vocabulary id appears once."""
    out, seen = [], set()

    def add(raw: str, value: str | None) -> None:
        if value is not None and value in seen:
            return
        seen.add(value)
        out.extend(labels.class_labels(raw, value))

    if category := entry.get("category"):
        add(f"category:{category}", _CATEGORY.get(category))
        if entry.get("primaryScript") in _CJK_SCRIPTS and category in _CJK_CATEGORY:
            add(f"category:{category}", _CJK_CATEGORY[category])
    if stroke := entry.get("stroke"):
        add(f"stroke:{stroke}", _STROKE.get(stroke))
    for classification in entry.get("classifications") or ():
        add(f"classification:{classification}", _CLASSIFICATION.get(classification))
    return out


def _family(entry: dict, tags, licenses: dict[str, str | None]) -> CatalogFamily:
    name = entry["family"]
    directory = licenses.get(_slug(name))
    family = CatalogFamily(source_key=name, family=name, designers=list(entry.get("designers") or ()),
                           license=LICENSE_DIRS.get(directory), url=SPECIMEN_URL.format(name.replace(" ", "+")))
    family.labels += _genre_labels(entry)
    family.labels += _tag_labels(tags)
    family.labels += subset_labels(entry.get("subsets") or ())
    keys = list(entry.get("fonts") or ())
    family.labels += style_labels([int(k.rstrip("i")) for k in keys if k.rstrip("i").isdigit()],
                                  any(k.endswith("i") for k in keys))
    family.labels += [axis_label(a["tag"], a["min"], a["max"]) for a in entry.get("axes") or ()]
    if directory is not None:
        family.labels.append(CatalogLabel("license", directory, LICENSE_DIRS[directory]))
    return family


def families_from(listing: str, tags_csv: str, trees: dict[str, dict]) -> list[CatalogFamily]:
    """The snapshot from the three kept payloads: the listing, the tags CSV, and {directory: tree JSON}."""
    tags = _tags(tags_csv)
    licenses = _licenses(trees)
    families: dict[str, CatalogFamily] = {}
    for entry in _listing(listing):
        if entry.get("family") and entry["family"] not in families:
            families[entry["family"]] = _family(entry, tags.get(entry["family"], ()), licenses)
    return list(families.values())


def fetch(fetcher: Fetcher) -> list[CatalogFamily]:
    listing = fetcher.get(METADATA_URL, store_as="metadata/fonts").text()
    tags_csv = fetcher.get(TAGS_URL, headers=RAW_HEADERS, store_as="tags/all/families.csv").text()
    trees = {directory: fetcher.get(TREE_URL.format(directory), headers=JSON_HEADERS,
                                    store_as=f"trees/{directory}").json()
             for directory in LICENSE_DIRS}
    return families_from(listing, tags_csv, trees)
