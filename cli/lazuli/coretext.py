"""Adobe Fonts through the operating system's font API, never through their files (macOS Core Text).

Adobe's terms allow other software to list and use the fonts a subscription activates through the
operating system's font stack, and forbid reaching them any other way, the folders they are installed in
included. So lazuli never opens, stats, lists, copies, or passes to fontTools or Pillow anything under
Adobe's folders (`~/Library/Application Support/Adobe/`, `%APPDATA%\\Adobe\\CoreSync`). On macOS it asks
Core Text instead:

- Which faces are Adobe Fonts: the descriptor's URL attribute, read as a string and matched by name only
  (`is_adobe_path`). The URL is never opened; it classifies a face and nothing else. A face's identity in
  the database is `coretext:<PostScript name>`, which is not a path.
- Names, coverage, weight, and slant: descriptor attributes, `CTFontCopyName` and
  `CTFontCopyLocalizedName` (family, style, version, manufacturer, designer), and
  `CTFontGetGlyphsForCharacters`. `vendor_id` (OS/2) stays empty, since nothing here reads a table.
- Localized family names: the name-table language ids of file faces have no Core Text counterpart, and
  `CTFontCopyLocalizedName` answers in the preferred language of the process that asks, so the scan's own
  process learns one name, in the system language. For each of `ko`, `ja`, `zh-Hans`, and `zh-Hant`, a helper
  process (`python -m lazuli.coretext --names`, started with the extra argument `-AppleLanguages (xx)`,
  which sets that process's preferred language) is given the PostScript names of the faces the scan is
  describing, one process per language, and answers each face's family name in that language. The helper
  makes fonts from the same font list by PostScript name, never by path and never from a URL, binds only
  `ALLOWED_CALLS`, and opens no file. A name is kept only when Core Text reports the requested language for
  it, so a face with no name in that language has none, as a file face has none. The names go into
  `names_i18n_json` under the keys files use (`ko`, `ja`, `zh-Hans`, `zh-Hant`). A helper that fails or
  runs out of time leaves its language absent for that scan and is reported as one skipped line; it never
  fails the scan.
- Design metadata: `CTFontCopyVariationAxes` returns OS-derived axis identifiers and numeric limits, not fvar
  bytes. `CTFontCopyFeatures` returns OS-derived AAT feature/selector dictionaries, not GSUB/GPOS bytes;
  mapped OpenType tags are a partial list. Vertical Substitution Forms (type 4, selector 0) maps to `vert`,
  including fonts whose only substitution is `vrt2`; Optimized Kana (type 34, selector 2) maps to `vkna`.
  `vhal` is indistinguishable from horizontal `halt`, so it is not claimed. Missing Adobe tags are unknown,
  not proof of absence. `CTFontGetXHeight` and `CTFontGetCapHeight` return OS-derived metrics, normalized to
  font units using `CTFontGetUnitsPerEm` (already used for measurement); Core Text may estimate missing
  heights. The stylistic class is the OS-derived kCTFontClassMaskTrait bits of descriptor symbolic traits,
  not OS/2 bytes. Version comes from the existing `CTFontCopyName` version key. Supported languages use the
  same mapped-character rule as files (`languages.py`), not `CTFontCopySupportedLanguages`: its different,
  OS-dependent language claims would break cross-origin parity, so that additional API is not bound.
- Measurement: `CTFace` answers the questions `measure.Face` answers, from metrics Core Text gives in font
  units (`CTFontGetBoundingRectsForGlyphs`, `CTFontGetAdvancesForGlyphs`, `CTFontGetUnitsPerEm`) and from
  glyphs the system draws (`CTFontDrawGlyphs`) into an 8-bit grayscale bitmap that lives for one
  measurement and is discarded. Only derived numbers are stored. No call returns an outline, a table, or
  file data, and `ALLOWED_CALLS` is the whole list of symbols this module binds: `_Library.bind` refuses any
  other, so outlines (`CTFontCreatePathForGlyph`) and table bytes (`CTFontCopyTable`) cannot be added
  by accident.
- Optical size: Core Text sets an `opsz` axis from the point size, and `CTFace` makes its fonts at two sizes (one
  point per font unit for metrics, RASTER_PX for the raster), so its numbers would describe different optical
  sizes, and nothing here pins one. `ALLOWED_CALLS` is not widened to pin it. A face whose stored axes include
  `opsz` is therefore never opened as a `CTFace`: `measure.open_face` raises `OpticalSizeNotPinned`, and the
  face is recorded as unmeasured ("optical size not pinned"), never with numbers.

`LAZULI_FONT_ROOTS` (tests, evaluations) turns the listing off (`provider()` returns None), and starts no
helper (`run_names_helper`), so no Adobe data reaches a test or an evaluation. Adobe Fonts terms allow using
this data for inference only. Windows has no counterpart here: Adobe Fonts are absent from the inventory
there.
"""
from __future__ import annotations

import array
import json
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePath
from typing import TYPE_CHECKING, Callable, Iterable

if TYPE_CHECKING:
    import numpy as np

IDENTITY_PREFIX = "coretext:"
SYMLINK_LIMIT = 40
UNICODE_PLANES = (0, 1, 2, 3)            # planes that hold letters: BMP, SMP, SIP, TIP
NAMES_LANGUAGES = ("ko", "ja", "zh-Hans", "zh-Hant")    # the keys of `names_i18n_json`, one helper process each
NAMES_TIMEOUT = 30.0                     # seconds a helper process may run before it is killed

# The Core Text, Core Foundation, and Core Graphics symbols this module may bind, and nothing else.
ALLOWED_CALLS = frozenset({
    # Core Foundation: values only
    "CFRelease", "CFArrayGetCount", "CFArrayGetValueAtIndex", "CFStringGetLength", "CFStringGetCString",
    "CFStringGetMaximumSizeForEncoding", "CFURLCopyFileSystemPath", "CFDictionaryGetValue", "CFNumberGetValue",
    # Core Text: enumeration, descriptor attributes, names, character mapping, metrics, drawing
    "CTFontCollectionCreateFromAvailableFonts", "CTFontCollectionCreateMatchingFontDescriptors",
    "CTFontDescriptorCopyAttribute", "CTFontCreateWithFontDescriptor",
    "CTFontCopyName", "CTFontCopyLocalizedName", "CTFontCopyPostScriptName", "CTFontGetUnitsPerEm",
    "CTFontGetGlyphsForCharacters", "CTFontGetBoundingRectsForGlyphs", "CTFontGetAdvancesForGlyphs",
    "CTFontDrawGlyphs",
    "CTFontCopyVariationAxes", "CTFontCopyFeatures", "CTFontGetXHeight", "CTFontGetCapHeight",
    # Core Graphics: an in-memory grayscale bitmap
    "CGColorSpaceCreateDeviceGray", "CGBitmapContextCreate", "CGContextSetGrayFillColor",
    "CGContextSetShouldAntialias", "CGContextSetAllowsFontSmoothing", "CGContextSetShouldSmoothFonts",
})


def require_allowed(name: str) -> None:
    """Refuse a symbol outside `ALLOWED_CALLS` (outline, table, or file-data calls among them)."""
    if name not in ALLOWED_CALLS:
        raise PermissionError(f"{name} is not one of the Core Text calls lazuli may use on Adobe Fonts")


# ---------------------------------------------------------------- Adobe's folders, by name

def is_adobe_path(path: str | os.PathLike) -> bool:
    """Whether `path` is inside Adobe's font folders, decided from its name alone (nothing is touched):
    `.../Application Support/Adobe/...` (macOS) or `.../Adobe/CoreSync/...` (Windows), any case."""
    parts = [part.casefold() for part in PurePath(os.path.normpath(os.fspath(path))).parts]
    pairs = set(zip(parts, parts[1:]))
    return ("application support", "adobe") in pairs or ("adobe", "coresync") in pairs


def reaches_adobe(path: str | os.PathLike) -> bool:
    """Whether `path` is in Adobe's folders by name, or a symbolic link on its way leads there. Links are
    followed one name at a time with `readlink`, and the walk stops at the first name that is Adobe's, so
    nothing under Adobe's folders is ever looked at."""
    target = PurePath(os.path.abspath(os.path.expanduser(os.fspath(path))))
    current = PurePath(target.anchor)
    pending = list(reversed(target.parts[1:]))
    links = 0
    while pending:
        part = pending.pop()
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        candidate = current / part
        if is_adobe_path(candidate):
            return True
        try:
            link = os.readlink(candidate)
        except OSError:                                  # not a link, or not there
            current = candidate
            continue
        links += 1
        if links > SYMLINK_LIMIT:
            return False                                 # a loop is no font
        destination = PurePath(link)
        if destination.is_absolute():
            current = PurePath(destination.anchor)
            pending.extend(reversed(destination.parts[1:]))
        else:
            pending.extend(reversed(destination.parts))
    return False


class AdobeFileRefused(ValueError):
    """A file inside Adobe's font folders was named. lazuli reads Adobe Fonts only through the operating
    system's font API."""


def refuse_adobe_file(path: str | os.PathLike) -> None:
    if reaches_adobe(path):
        raise AdobeFileRefused(f"{path}: inside Adobe's font folders, which lazuli never opens (macOS lists "
                               "Adobe Fonts through Core Text; Windows does not list them)")


# ---------------------------------------------------------------- what the scanner and measurer see

@dataclass(frozen=True)
class AdobeFace:
    """One Adobe Fonts face as the operating system lists it."""
    identity: str                                  # local_font.path: `coretext:<PostScript name>`, never a path
    token: str                                     # local_font.mtime: changes when the face is updated
    describe: Callable[[dict, frozenset[int]], dict]  # coverage blocks + wanted characters -> inventory and OS metadata


class Provider:
    """What the scanner and the measurer need from an operating system font list."""

    def identities(self) -> list[str]:
        raise NotImplementedError

    def faces(self) -> list[AdobeFace]:
        raise NotImplementedError

    def open(self, identity: str, raster_px: int):
        """A `measure.Face`-shaped adapter for one listed face; LookupError when it is no longer listed."""
        raise NotImplementedError

    def localized_names(self, identities: list[str]) -> tuple[dict[str, dict[str, str]], list[str]]:
        """({identity: {language key: family name}}, one line per language that could not be asked). A list
        with no localized names of its own (fakes, other platforms) has nothing to add."""
        return {}, []


def supported() -> bool:
    """Whether this platform lists Adobe Fonts through an operating system API lazuli uses (macOS only)."""
    return sys.platform == "darwin"


def provider() -> Provider | None:
    """The Core Text provider on macOS; None elsewhere, and None while `LAZULI_FONT_ROOTS` replaces the
    inventory, so tests and evaluations never see Adobe Fonts data."""
    if not supported() or os.environ.get("LAZULI_FONT_ROOTS"):
        return None
    return CoreText()


# ---------------------------------------------------------------- Core Text through ctypes

def _structures():
    import ctypes as C

    class Point(C.Structure):
        _fields_ = [("x", C.c_double), ("y", C.c_double)]

    class Size(C.Structure):
        _fields_ = [("width", C.c_double), ("height", C.c_double)]

    class Rect(C.Structure):
        _fields_ = [("x", C.c_double), ("y", C.c_double), ("width", C.c_double), ("height", C.c_double)]

    return Point, Size, Rect


UTF8 = 0x08000100                                # kCFStringEncodingUTF8
NUMBER_DOUBLE = 13                               # kCFNumberDoubleType
NUMBER_INT = 9                                   # kCFNumberIntType
ITALIC_TRAIT = 1                                 # kCTFontItalicTrait in the symbolic traits
CLASS_MASK_TRAIT = 0xF0000000                      # kCTFontClassMaskTrait, stored without collapsing to a file class
WEIGHT_ANCHORS = ((-0.8, 100), (-0.6, 200), (-0.4, 300), (0.0, 400), (0.23, 500), (0.3, 600), (0.4, 700),
                  (0.56, 800), (0.62, 900))      # kCTFontWeightTrait of the OS/2 weight classes
LOCALIZED_LANGUAGES = (("ko", "ko"), ("ja", "ja"), ("zh-hans", "zh-Hans"), ("zh-cn", "zh-Hans"),
                       ("zh-sg", "zh-Hans"), ("zh-hant", "zh-Hant"), ("zh-tw", "zh-Hant"), ("zh-hk", "zh-Hant"),
                       ("zh-mo", "zh-Hant"), ("zh", "zh-Hans"))


def weight_class(trait: float | None) -> int | None:
    """The OS/2 weight class nearest to a Core Text weight trait (-1 to 1)."""
    if trait is None:
        return None
    return min(WEIGHT_ANCHORS, key=lambda anchor: abs(anchor[0] - trait))[1]


def language_key(language: str | None) -> str | None:
    """`ko`, `ja`, `zh-Hans`, or `zh-Hant` for a language tag Core Text reports, else None."""
    tag = (language or "").casefold().replace("_", "-")
    for prefix, key in LOCALIZED_LANGUAGES:
        if tag == prefix or tag.startswith(prefix + "-"):
            return key
    return None


@lru_cache(maxsize=8)
def _utf16(first: int, count: int) -> array.array:
    """`count` consecutive code points from `first` as UTF-16 code units (surrogate pairs above U+FFFF), the
    input Core Text's character mapping takes. Read-only after it is made, so one copy serves every face."""
    if first + count <= 0x10000:
        return array.array("H", range(first, first + count))
    units = array.array("H")
    for code in range(first, first + count):
        value = code - 0x10000
        units.extend((0xD800 + (value >> 10), 0xDC00 + (value & 0x3FF)))
    return units


class _Library:
    """The Core Text, Core Foundation, and Core Graphics symbols this module uses, bound from
    `ALLOWED_CALLS` only."""

    def __init__(self) -> None:
        import ctypes
        import ctypes.util

        self.C = ctypes
        self.Point, self.Size, self.Rect = _structures()
        frameworks = {}
        for name in ("CoreFoundation", "CoreText", "CoreGraphics"):
            found = ctypes.util.find_library(name)
            if not found:
                raise OSError(f"the {name} framework is not available")
            frameworks[name] = ctypes.cdll.LoadLibrary(found)
        self.cf, self.ct, self.cg = frameworks["CoreFoundation"], frameworks["CoreText"], frameworks["CoreGraphics"]
        self.bound: set[str] = set()
        vp, c_long, c_double = ctypes.c_void_p, ctypes.c_long, ctypes.c_double
        self.CFRelease = self.bind(self.cf, "CFRelease", [vp])
        self.CFArrayGetCount = self.bind(self.cf, "CFArrayGetCount", [vp], c_long)
        self.CFArrayGetValueAtIndex = self.bind(self.cf, "CFArrayGetValueAtIndex", [vp, c_long], vp)
        self.CFStringGetLength = self.bind(self.cf, "CFStringGetLength", [vp], c_long)
        self.CFStringGetMaximumSizeForEncoding = self.bind(self.cf, "CFStringGetMaximumSizeForEncoding",
                                                           [c_long, ctypes.c_uint32], c_long)
        self.CFStringGetCString = self.bind(self.cf, "CFStringGetCString",
                                            [vp, ctypes.c_char_p, c_long, ctypes.c_uint32], ctypes.c_bool)
        self.CFURLCopyFileSystemPath = self.bind(self.cf, "CFURLCopyFileSystemPath", [vp, c_long], vp)
        self.CFDictionaryGetValue = self.bind(self.cf, "CFDictionaryGetValue", [vp, vp], vp)
        self.CFNumberGetValue = self.bind(self.cf, "CFNumberGetValue", [vp, c_long, vp], ctypes.c_bool)
        self.CTFontCollectionCreateFromAvailableFonts = self.bind(
            self.ct, "CTFontCollectionCreateFromAvailableFonts", [vp], vp)
        self.CTFontCollectionCreateMatchingFontDescriptors = self.bind(
            self.ct, "CTFontCollectionCreateMatchingFontDescriptors", [vp], vp)
        self.CTFontDescriptorCopyAttribute = self.bind(self.ct, "CTFontDescriptorCopyAttribute", [vp, vp], vp)
        self.CTFontCreateWithFontDescriptor = self.bind(self.ct, "CTFontCreateWithFontDescriptor",
                                                        [vp, c_double, vp], vp)
        self.CTFontCopyName = self.bind(self.ct, "CTFontCopyName", [vp, vp], vp)
        self.CTFontCopyLocalizedName = self.bind(self.ct, "CTFontCopyLocalizedName",
                                                 [vp, vp, ctypes.POINTER(vp)], vp)
        self.CTFontCopyPostScriptName = self.bind(self.ct, "CTFontCopyPostScriptName", [vp], vp)
        self.CTFontGetUnitsPerEm = self.bind(self.ct, "CTFontGetUnitsPerEm", [vp], ctypes.c_uint32)
        self.CTFontCopyVariationAxes = self.bind(self.ct, "CTFontCopyVariationAxes", [vp], vp)
        self.CTFontCopyFeatures = self.bind(self.ct, "CTFontCopyFeatures", [vp], vp)
        self.CTFontGetXHeight = self.bind(self.ct, "CTFontGetXHeight", [vp], c_double)
        self.CTFontGetCapHeight = self.bind(self.ct, "CTFontGetCapHeight", [vp], c_double)
        self.CTFontGetGlyphsForCharacters = self.bind(self.ct, "CTFontGetGlyphsForCharacters",
                                                      [vp, vp, vp, c_long], ctypes.c_bool)
        self.CTFontGetBoundingRectsForGlyphs = self.bind(
            self.ct, "CTFontGetBoundingRectsForGlyphs", [vp, ctypes.c_uint32, vp, vp, c_long], self.Rect)
        self.CTFontGetAdvancesForGlyphs = self.bind(self.ct, "CTFontGetAdvancesForGlyphs",
                                                    [vp, ctypes.c_uint32, vp, vp, c_long], c_double)
        self.CTFontDrawGlyphs = self.bind(self.ct, "CTFontDrawGlyphs", [vp, vp, vp, c_long, vp])
        self.CGColorSpaceCreateDeviceGray = self.bind(self.cg, "CGColorSpaceCreateDeviceGray", [], vp)
        self.CGBitmapContextCreate = self.bind(
            self.cg, "CGBitmapContextCreate",
            [vp, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, vp, ctypes.c_uint32], vp)
        self.CGContextSetGrayFillColor = self.bind(self.cg, "CGContextSetGrayFillColor", [vp, ctypes.c_double,
                                                                                          ctypes.c_double])
        for setting in ("CGContextSetShouldAntialias", "CGContextSetAllowsFontSmoothing",
                        "CGContextSetShouldSmoothFonts"):
            setattr(self, setting, self.bind(self.cg, setting, [vp, ctypes.c_bool]))
        self.keys = {name: vp.in_dll(self.ct, name).value for name in (
            "kCTFontURLAttribute", "kCTFontNameAttribute", "kCTFontTraitsAttribute", "kCTFontWeightTrait",
            "kCTFontSymbolicTrait", "kCTFontFamilyNameKey", "kCTFontStyleNameKey", "kCTFontVersionNameKey",
            "kCTFontManufacturerNameKey", "kCTFontDesignerNameKey",
            "kCTFontVariationAxisIdentifierKey", "kCTFontVariationAxisMinimumValueKey",
            "kCTFontVariationAxisDefaultValueKey", "kCTFontVariationAxisMaximumValueKey",
            "kCTFontFeatureTypeIdentifierKey", "kCTFontFeatureTypeSelectorsKey",
            "kCTFontFeatureSelectorIdentifierKey", "kCTFontOpenTypeFeatureTag")}
        self.gray = None

    def bind(self, framework, name: str, argtypes: list, restype=None):
        require_allowed(name)
        function = getattr(framework, name)
        function.argtypes = argtypes
        function.restype = restype
        self.bound.add(name)
        return function

    def string(self, ref) -> str | None:
        """A CFString as text; None for a null reference."""
        if not ref:
            return None
        size = self.CFStringGetMaximumSizeForEncoding(self.CFStringGetLength(ref), UTF8) + 1
        buffer = self.C.create_string_buffer(size)
        text = buffer.value.decode("utf-8", "replace") if self.CFStringGetCString(ref, buffer, size, UTF8) else None
        return text

    def number(self, ref, kind: int):
        if not ref:
            return None
        value = self.C.c_double() if kind == NUMBER_DOUBLE else self.C.c_int()
        return value.value if self.CFNumberGetValue(ref, kind, self.C.byref(value)) else None

    def attribute_string(self, descriptor, key: str) -> str | None:
        ref = self.CTFontDescriptorCopyAttribute(descriptor, self.keys[key])
        try:
            return self.string(ref)
        finally:
            if ref:
                self.CFRelease(ref)

    def url_path(self, descriptor) -> str | None:
        """The file URL a descriptor carries, as text. It is matched by name and never opened."""
        ref = self.CTFontDescriptorCopyAttribute(descriptor, self.keys["kCTFontURLAttribute"])
        if not ref:
            return None
        try:
            text = self.CFURLCopyFileSystemPath(ref, 0)     # kCFURLPOSIXPathStyle
            try:
                return self.string(text)
            finally:
                if text:
                    self.CFRelease(text)
        finally:
            self.CFRelease(ref)

    def traits(self, descriptor) -> tuple[float | None, int | None]:
        """(weight trait, symbolic traits) from a descriptor's trait dictionary."""
        ref = self.CTFontDescriptorCopyAttribute(descriptor, self.keys["kCTFontTraitsAttribute"])
        if not ref:
            return None, None
        try:
            weight = self.number(self.CFDictionaryGetValue(ref, self.keys["kCTFontWeightTrait"]), NUMBER_DOUBLE)
            symbolic = self.number(self.CFDictionaryGetValue(ref, self.keys["kCTFontSymbolicTrait"]), NUMBER_INT)
            return weight, symbolic
        finally:
            self.CFRelease(ref)

    def name(self, font, key: str) -> str | None:
        ref = self.CTFontCopyName(font, self.keys[key])
        try:
            return (self.string(ref) or "").strip() or None
        finally:
            if ref:
                self.CFRelease(ref)

    def localized_name(self, font, key: str) -> tuple[str | None, str | None]:
        language = self.C.c_void_p()
        ref = self.CTFontCopyLocalizedName(font, self.keys[key], self.C.byref(language))
        try:
            return (self.string(ref) or "").strip() or None, self.string(language)
        finally:
            for item in (ref, language):
                if item:
                    self.CFRelease(item)

    def axes(self, font) -> list[dict]:
        """OS-derived variation axis limits; no font table is obtained."""
        ref = self.CTFontCopyVariationAxes(font)
        try:
            out = []
            for position in range(self.CFArrayGetCount(ref) if ref else 0):
                axis = self.CFArrayGetValueAtIndex(ref, position)
                identifier = self.number(self.CFDictionaryGetValue(axis, self.keys["kCTFontVariationAxisIdentifierKey"]),
                                         NUMBER_INT)
                values = {field: self.number(self.CFDictionaryGetValue(axis, self.keys[key]), NUMBER_DOUBLE)
                          for field, key in (("min", "kCTFontVariationAxisMinimumValueKey"),
                                             ("default", "kCTFontVariationAxisDefaultValueKey"),
                                             ("max", "kCTFontVariationAxisMaximumValueKey"))}
                if identifier is not None and all(value is not None for value in values.values()):
                    tag = (identifier & 0xFFFFFFFF).to_bytes(4, "big").decode("latin-1")
                    out.append({"tag": tag, **values})
            return out
        finally:
            if ref:
                self.CFRelease(ref)

    def features(self, font) -> tuple[list[str], list[str]]:
        """Mapped OpenType tags and vertical-writing tags from OS-derived AAT feature dictionaries.

        Core Text folds vrt2 into vert and vhal into halt; neither original tag can be recovered.
        """
        ref = self.CTFontCopyFeatures(font)
        try:
            tags, vertical = set(), set()
            for position in range(self.CFArrayGetCount(ref) if ref else 0):
                feature = self.CFArrayGetValueAtIndex(ref, position)
                kind = self.number(self.CFDictionaryGetValue(feature, self.keys["kCTFontFeatureTypeIdentifierKey"]),
                                   NUMBER_INT)
                selectors = self.CFDictionaryGetValue(feature, self.keys["kCTFontFeatureTypeSelectorsKey"])
                for index in range(self.CFArrayGetCount(selectors) if selectors else 0):
                    selector = self.CFArrayGetValueAtIndex(selectors, index)
                    value = self.number(self.CFDictionaryGetValue(selector, self.keys["kCTFontFeatureSelectorIdentifierKey"]),
                                        NUMBER_INT)
                    tag = self.string(self.CFDictionaryGetValue(selector, self.keys["kCTFontOpenTypeFeatureTag"]))
                    if tag:
                        tags.add(tag)
                        if tag in ("vert", "vrt2", "vhal", "vkna"):
                            vertical.add(tag)
                    if kind == 4 and value == 0:
                        vertical.add("vert")
                    if kind == 34 and value == 2:
                        vertical.add("vkna")
            return sorted(tags), sorted(vertical)
        finally:
            if ref:
                self.CFRelease(ref)

    def glyph_array(self, font, first: int, count: int):
        """Glyph ids of `count` consecutive code points from `first` (a plane or a block), 0 where unmapped.
        Code points above U+FFFF go in as surrogate pairs; the glyph lands in the high surrogate's slot."""
        units = _utf16(first, count)
        glyphs = array.array("H", bytes(2 * len(units)))
        units_ref = (self.C.c_uint16 * len(units)).from_buffer(units)
        glyphs_ref = (self.C.c_uint16 * len(glyphs)).from_buffer(glyphs)
        self.CTFontGetGlyphsForCharacters(font, units_ref, glyphs_ref, len(units))
        if first + count > 0x10000:
            glyphs = glyphs[0::2]                       # one glyph per code point, from the high surrogate slot
        return glyphs


# ---------------------------------------------------------------- the provider

class CoreText(Provider):
    """Adobe Fonts faces as Core Text lists them (see the module doc for what is read). `is_adobe` decides from
    a face's URL, as text, whether it is an Adobe Fonts face; tests narrow it to their own synthetic fonts so
    that no real Adobe face is ever read. `names_runner` stands in for `run_names_helper` in tests."""

    def __init__(self, is_adobe: Callable[[str], bool] = is_adobe_path, names_runner: Runner | None = None) -> None:
        self.is_adobe = is_adobe
        self.names_runner = names_runner
        self.lib = _Library()
        self._collection = None
        self._descriptors = None
        self._index: dict[str, int] | None = None

    def __del__(self) -> None:
        if getattr(self, "_descriptors", None):
            self.lib.CFRelease(self._descriptors)
        if getattr(self, "_collection", None):
            self.lib.CFRelease(self._collection)

    def _list(self) -> dict[str, int]:
        """identity -> position in the descriptor array, for the Adobe faces, first listing of a name wins."""
        if self._index is not None:
            return self._index
        lib = self.lib
        self._collection = lib.CTFontCollectionCreateFromAvailableFonts(None)
        self._descriptors = lib.CTFontCollectionCreateMatchingFontDescriptors(self._collection)
        index: dict[str, int] = {}
        for position in range(lib.CFArrayGetCount(self._descriptors) if self._descriptors else 0):
            descriptor = lib.CFArrayGetValueAtIndex(self._descriptors, position)
            path = lib.url_path(descriptor)
            if path is None or not self.is_adobe(path):
                continue
            postscript = lib.attribute_string(descriptor, "kCTFontNameAttribute")
            if postscript:
                index.setdefault(IDENTITY_PREFIX + postscript, position)
        self._index = index
        return index

    def _descriptor(self, identity: str):
        position = self._list().get(identity)
        if position is None:
            raise LookupError(f"Core Text does not list {identity}")
        return self.lib.CFArrayGetValueAtIndex(self._descriptors, position)

    def identities(self) -> list[str]:
        return sorted(self._list())

    def faces(self) -> list[AdobeFace]:
        out = []
        for identity in self.identities():
            descriptor = self._descriptor(identity)
            font = self.lib.CTFontCreateWithFontDescriptor(descriptor, 12.0, None)
            try:
                version = self.lib.name(font, "kCTFontVersionNameKey") or ""
            finally:
                self.lib.CFRelease(font)
            out.append(AdobeFace(identity, IDENTITY_PREFIX + version,
                                 lambda blocks, wanted, identity=identity: self._describe(identity, blocks, wanted)))
        return out

    def _describe(self, identity: str, blocks: dict[str, list[tuple[int, int]]], wanted: frozenset[int]) -> dict:
        """Names, coverage, and OS-derived metadata; `wanted` is the BMP character set the language rule needs."""
        lib = self.lib
        descriptor = self._descriptor(identity)
        font = lib.CTFontCreateWithFontDescriptor(descriptor, 12.0, None)
        try:
            ps_ref = lib.CTFontCopyPostScriptName(font)
            try:
                postscript = (lib.string(ps_ref) or "").strip() or None
            finally:
                if ps_ref:
                    lib.CFRelease(ps_ref)
            family = lib.name(font, "kCTFontFamilyNameKey")
            local, language = lib.localized_name(font, "kCTFontFamilyNameKey")
            key = language_key(language)
            glyphs = lib.glyph_array(font, 0, 0x10000)
            coverage = {}
            for block, ranges in blocks.items():
                count = sum((hi - lo + 1) - glyphs[lo:hi + 1].count(0) for lo, hi in ranges)
                if count:
                    coverage[block] = count
            upm = int(lib.CTFontGetUnitsPerEm(font))
            _, symbolic = lib.traits(descriptor)
            family_class = symbolic & CLASS_MASK_TRAIT if symbolic is not None else None
            features, vertical = lib.features(font)
            metadata = {"axes": lib.axes(font), "features": features, "features_source": "coretext",
                        "vertical": vertical, "version": lib.name(font, "kCTFontVersionNameKey"),
                        "units_per_em": upm, "x_height": round(lib.CTFontGetXHeight(font) * upm / 12.0),
                        "cap_height": round(lib.CTFontGetCapHeight(font) * upm / 12.0),
                        "family_class": family_class, "class_id": family_class >> 28 if family_class is not None else None,
                        "class_source": "coretext", "os2_ranges": None}
            return {"postscript_name": postscript, "family": family, "subfamily": lib.name(font, "kCTFontStyleNameKey"),
                    "names_i18n": {key: local} if key and local else {},
                    "manufacturer": lib.name(font, "kCTFontManufacturerNameKey"),
                    "designer": lib.name(font, "kCTFontDesignerNameKey"), "coverage": coverage,
                    "mapped": {cp for cp in wanted if glyphs[cp]}, "metadata": metadata}
        finally:
            lib.CFRelease(font)

    def open(self, identity: str, raster_px: int) -> CTFace:
        return CTFace(self.lib, self._descriptor(identity), raster_px)

    def localized_names(self, identities: list[str]) -> tuple[dict[str, dict[str, str]], list[str]]:
        """Family names in Korean, Japanese, and both Chinese scripts, from one helper process per language
        (see the module doc); {} while `LAZULI_FONT_ROOTS` is set. Faces are named to the helpers by PostScript
        name, the tail of their identity."""
        identity_of = {identity[len(IDENTITY_PREFIX):]: identity for identity in identities
                       if identity.startswith(IDENTITY_PREFIX)}
        names, problems = localized_names(identity_of, self.names_runner)
        return {identity_of[postscript]: found for postscript, found in names.items()}, problems


# ---------------------------------------------------------------- localized names: one helper process per language

Runner = Callable[[str, list[str]], object]      # (language key, PostScript names) -> the helper's decoded answer


def run_names_helper(language: str, postscripts: list[str]) -> object:
    """Ask `python -m lazuli.coretext --names` for the family names of `postscripts` in `language`: a new
    process whose extra argument `-AppleLanguages (language)` sets the preferred language Core Text answers in.
    The names go in as a JSON list on stdin and come out as JSON on stdout: {PostScript name: {"name",
    "language"}}, the language Core Text reports for that name. Raises when the process fails, is killed after
    `NAMES_TIMEOUT` seconds, or answers something that is not JSON. `-P` keeps the working directory off the
    helper's import path, so a folder named `lazuli` in a project is never run in its place. While
    `LAZULI_FONT_ROOTS` is set no process is started and the answer is empty."""
    if os.environ.get("LAZULI_FONT_ROOTS"):
        return {}
    import subprocess

    done = subprocess.run([sys.executable, "-P", "-m", "lazuli.coretext", "--names", "-AppleLanguages", f"({language})"],
                          input=json.dumps(postscripts), capture_output=True, encoding="utf-8",
                          timeout=NAMES_TIMEOUT, check=True)
    return json.loads(done.stdout)


def _kept(language: str, wanted: list[str], answer: object) -> dict[str, str]:
    """{PostScript name: family name} for the entries of a helper's answer that name a face asked for, in the
    language asked for: `language_key` of the reported language must be `language`, so a fallback (English,
    or another script) is dropped, and `zh-Hans` and `zh-Hant` are told apart."""
    if not isinstance(answer, dict):
        raise ValueError("the helper's answer is not an object")
    kept = {}
    for postscript in wanted:
        entry = answer.get(postscript)
        if not isinstance(entry, dict):
            continue
        name, reported = entry.get("name"), entry.get("language")
        if isinstance(name, str) and isinstance(reported, str) and name.strip() and language_key(reported) == language:
            kept[postscript] = name.strip()
    return kept


def localized_names(postscripts: Iterable[str], runner: Runner | None = None,
                    languages: Iterable[str] = NAMES_LANGUAGES) -> tuple[dict[str, dict[str, str]], list[str]]:
    """({PostScript name: {language key: family name}}, problems): the helper for each language gets every
    name in one process, one language after another, from the calling thread (helpers started from threads
    of a process that has Core Text loaded measured 7 times slower for 20 faces and ran into a 60 s timeout
    for 942). A helper that fails or times out leaves its language out and adds one line to the problems
    (the scan reports them and goes on)."""
    wanted = sorted(set(postscripts))
    names: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    if not wanted:
        return names, problems
    run = runner or run_names_helper
    for language in languages:
        try:
            kept = _kept(language, wanted, run(language, wanted))
        except Exception as exc:                  # a language that cannot be asked stays absent
            problems.append(f"Adobe Fonts: {language} names not read ({type(exc).__name__})")
            continue
        for postscript, name in kept.items():
            names.setdefault(postscript, {})[language] = name
    return names, problems


def names_in_this_process(postscripts: Iterable[str]) -> dict[str, dict[str, str]]:
    """What the helper does: {PostScript name: {"name", "language"}} for the listed faces among `postscripts`,
    family names in the language this process prefers. Only `ALLOWED_CALLS` are bound. The font list is walked
    for descriptors named as asked (the first of a name wins, as in `CoreText._list`); no URL is read, so
    nothing here can tell where a font lives, let alone open it. A face with no name is left out."""
    wanted = set(postscripts)
    lib = _Library()
    collection = lib.CTFontCollectionCreateFromAvailableFonts(None)
    descriptors = lib.CTFontCollectionCreateMatchingFontDescriptors(collection)
    answers: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    try:
        for position in range(lib.CFArrayGetCount(descriptors) if descriptors else 0):
            if len(seen) == len(wanted):
                break
            descriptor = lib.CFArrayGetValueAtIndex(descriptors, position)
            postscript = lib.attribute_string(descriptor, "kCTFontNameAttribute")
            if postscript not in wanted or postscript in seen:
                continue
            seen.add(postscript)
            font = lib.CTFontCreateWithFontDescriptor(descriptor, 12.0, None)
            try:
                name, language = lib.localized_name(font, "kCTFontFamilyNameKey")
            finally:
                lib.CFRelease(font)
            if name and language:
                answers[postscript] = {"name": name, "language": language}
    finally:
        for ref in (descriptors, collection):
            if ref:
                lib.CFRelease(ref)
    return answers


def main(argv: list[str] | None = None) -> int:
    """`python -m lazuli.coretext --names`: read a JSON list of PostScript names on stdin, write the JSON
    answer of `names_in_this_process` on stdout. Anything after `--names` (the `-AppleLanguages (xx)` pair) is
    for Core Text, which reads it from the process's arguments; it is not parsed here."""
    args = sys.argv[1:] if argv is None else argv
    if args[:1] != ["--names"]:
        print("usage: python -m lazuli.coretext --names   (a JSON list of PostScript names on stdin; the language "
              "comes from the extra arguments -AppleLanguages '(xx)')", file=sys.stderr)
        return 2
    try:
        postscripts = json.load(sys.stdin)
        if not isinstance(postscripts, list) or not all(isinstance(name, str) for name in postscripts):
            raise ValueError("not a list of names")
    except ValueError as exc:
        print(f"--names: stdin is not a JSON list of PostScript names ({exc})", file=sys.stderr)
        return 2
    json.dump(names_in_this_process(postscripts), sys.stdout)          # ASCII-only, whatever the pipe's encoding
    return 0


# ---------------------------------------------------------------- measurement adapter

class CTFace:
    """`measure.Face` for a face Core Text lists: the same questions, answered from Core Text metrics in font
    units and from glyphs the system draws into a bitmap that lives for one call. `pixel_outline` is not
    checked (it needs contours, and no outline is ever read), so it stays unmeasured."""

    method = "coretext"

    def __init__(self, lib: _Library, descriptor, raster_px: int) -> None:
        self.lib = lib
        self.raster_px = raster_px
        probe = lib.CTFontCreateWithFontDescriptor(descriptor, 1000.0, None)
        self.upm = int(lib.CTFontGetUnitsPerEm(probe))
        lib.CFRelease(probe)
        self.font = lib.CTFontCreateWithFontDescriptor(descriptor, float(self.upm), None)     # one point per unit
        self.raster_font = lib.CTFontCreateWithFontDescriptor(descriptor, float(raster_px), None)
        self.weight_trait, self.symbolic = lib.traits(descriptor)
        self._cmap: dict[int, int] | None = None
        self._bounds: dict[str, tuple | None] = {}

    def __del__(self) -> None:
        for name in ("font", "raster_font"):
            if getattr(self, name, None):
                self.lib.CFRelease(getattr(self, name))

    @property
    def cmap(self) -> dict[int, int]:
        """code point -> glyph id for the planes that hold letters."""
        if self._cmap is None:
            cmap = {}
            for plane in UNICODE_PLANES:
                first = plane * 0x10000
                glyphs = self.lib.glyph_array(self.font, first, 0x10000)
                cmap.update((first + offset, glyph) for offset, glyph in enumerate(glyphs) if glyph)
            self._cmap = cmap
        return self._cmap

    def font_metrics(self) -> dict:
        """The face-level numbers the measurer records; weight class and italic come from Core Text traits."""
        metrics = {"upm": self.upm}
        if (weight := weight_class(self.weight_trait)) is not None:
            metrics["weight_class"] = weight
        if self.symbolic is not None:
            metrics["italic"] = bool(self.symbolic & ITALIC_TRAIT)
        return metrics

    def has(self, ch: str) -> bool:
        return ord(ch) in self.cmap

    def _glyph(self, ch: str):
        glyph = self.lib.C.c_uint16(self.cmap[ord(ch)])
        return glyph

    def _rect(self, font, ch: str):
        lib = self.lib
        rect = lib.Rect()
        lib.CTFontGetBoundingRectsForGlyphs(font, 0, lib.C.byref(self._glyph(ch)), lib.C.byref(rect), 1)
        return rect

    def bounds(self, ch: str) -> tuple[float, float, float, float] | None:
        """(xMin, yMin, xMax, yMax) in font units."""
        if ch not in self._bounds:
            if not self.has(ch):
                self._bounds[ch] = None
            else:
                rect = self._rect(self.font, ch)
                self._bounds[ch] = (None if rect.width <= 0 and rect.height <= 0 else
                                    (rect.x, rect.y, rect.x + rect.width, rect.y + rect.height))
        return self._bounds[ch]

    def height(self, ch: str) -> float | None:
        b = self.bounds(ch)
        return b[3] - b[1] if b else None

    def width(self, ch: str) -> float | None:
        b = self.bounds(ch)
        return b[2] - b[0] if b else None

    def advance(self, ch: str) -> int | None:
        if not self.has(ch):
            return None
        lib = self.lib
        size = lib.Size()
        lib.CTFontGetAdvancesForGlyphs(self.font, 0, lib.C.byref(self._glyph(ch)), lib.C.byref(size), 1)
        return round(size.width)

    def raster(self, ch: str) -> np.ndarray | None:
        """Ink mask of one glyph, cropped to its ink; rows run top to bottom. The system draws the glyph white
        on black into a bitmap that is dropped when this returns."""
        import math

        import numpy as np

        if not self.has(ch):
            return None
        lib = self.lib
        rect = self._rect(self.raster_font, ch)
        if rect.width <= 0 or rect.height <= 0:
            return None
        pad = 8
        left, bottom = math.floor(rect.x), math.floor(rect.y)
        width = math.ceil(rect.x + rect.width) - left + 2 * pad
        height = math.ceil(rect.y + rect.height) - bottom + 2 * pad
        pixels = (lib.C.c_ubyte * (width * height))()
        if lib.gray is None:
            lib.gray = lib.CGColorSpaceCreateDeviceGray()
        context = lib.CGBitmapContextCreate(pixels, width, height, 8, width, lib.gray, 0)   # kCGImageAlphaNone
        if not context:
            return None
        try:
            lib.CGContextSetShouldAntialias(context, True)
            lib.CGContextSetAllowsFontSmoothing(context, False)
            lib.CGContextSetShouldSmoothFonts(context, False)
            lib.CGContextSetGrayFillColor(context, 1.0, 1.0)
            position = lib.Point(pad - left, pad - bottom)
            lib.CTFontDrawGlyphs(self.raster_font, lib.C.byref(self._glyph(ch)), lib.C.byref(position), 1, context)
        finally:
            lib.CFRelease(context)
        ink = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width) > 127     # row 0 is the top
        rows, cols = np.where(ink)
        if not len(rows):
            return None
        return ink[rows.min():rows.max() + 1, cols.min():cols.max() + 1]

    def units(self, px: float) -> float:
        return px * self.upm / self.raster_px


if __name__ == "__main__":
    raise SystemExit(main())
