"""Text on the CLI's picture sheets (`references sheet`, the diverge contact sheet), in a font that has its characters.

Pillow's built-in font draws Latin only: a Korean, Japanese, or Chinese label comes out as the .notdef box (tofu).
So each string is drawn with the first face that covers every character of it:

1. the built-in font, when it draws all of the string (a Latin sheet looks as it always did, and no file is read);
2. otherwise a face of the platform's own fonts, in a fixed order that puts the string's language first: macOS
   `/System/Library/Fonts`, Windows `%SystemRoot%\\Fonts`, Linux what `fc-match` names for the language and the
   usual Noto/Nanum/WenQuanYi paths. Coverage is the face's cmap (fontTools), so no glyph is drawn to find out;
3. when no such face covers the whole string, the face that covers most of it (or the built-in font, when nothing
   beats it), and the characters left over are recorded: `Pen.limits`, which the commands print, and a last line
   on the sheet itself. Tofu is never drawn without saying so.

Only platform fonts are listed. A path that reaches Adobe's font folders is refused by name before any file is
opened (`lazuli.coretext.reaches_adobe`), so a face synced from Adobe Fonts can never be picked.

The choice is cached for the life of the process: the faces and their cmaps, and the face chosen for each set of
characters.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

# A noncharacter: no font maps it, so every font draws its .notdef box for it.
NOTDEF = "\U0010fffe"
FALLBACK_LINE_SIZE = 13
LANGUAGES = ("ko", "ja", "zh")

_DARWIN_DIR = Path("/System/Library/Fonts")
_DARWIN = {
    "ko": ("AppleSDGothicNeo.ttc", "Supplemental/AppleGothic.ttf"),
    "ja": ("ヒラギノ角ゴシック W3.ttc", "ヒラギノ角ゴシック W4.ttc", "ヒラギノ丸ゴ ProN W4.ttc", "ヒラギノ明朝 ProN.ttc"),
    "zh": ("PingFang.ttc", "STHeiti Light.ttc", "Hiragino Sans GB.ttc", "Supplemental/Songti.ttc"),
    "any": ("Supplemental/Arial Unicode.ttf",),
}
_WINDOWS = {
    "ko": ("malgun.ttf", "gulim.ttc"),
    "ja": ("YuGothM.ttc", "YuGothR.ttc", "meiryo.ttc", "msgothic.ttc"),
    "zh": ("msyh.ttc", "msyh.ttf", "simsun.ttc", "mingliu.ttc"),
    "any": ("arialuni.ttf",),
}
_LINUX = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)
_FC_LANGUAGES = {"ko": "ko", "ja": "ja", "zh": "zh-cn"}


@dataclass(frozen=True)
class Face:
    path: str
    index: int = 0


def _hangul(code: int) -> bool:
    return 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F


def _kana(code: int) -> bool:
    return 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9F


def _language_order(chars: frozenset[str]) -> tuple[str, ...]:
    """The languages whose fonts to look in first: Hangul says Korean, kana says Japanese, Han alone says Chinese."""
    codes = [ord(c) for c in chars]
    first = "ko" if any(_hangul(c) for c in codes) else "ja" if any(_kana(c) for c in codes) else "zh"
    return (first, *(lang for lang in LANGUAGES if lang != first), "any")


def _fc_match(language: str) -> list[Face]:
    exe = shutil.which("fc-match")
    if exe is None:
        return []
    try:
        done = subprocess.run([exe, "-f", "%{file}\n%{index}", f"sans:lang={_FC_LANGUAGES[language]}"],
                              capture_output=True, encoding="utf-8", timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        return []
    path, _, index = done.stdout.partition("\n")
    return [Face(path, int(index))] if path and index.strip().isdigit() and _allowed(path) else []


def _allowed(path: str) -> bool:
    """False for a path that reaches Adobe's font folders; decided from names alone, before anything is opened."""
    from lazuli import coretext

    return not coretext.reaches_adobe(path)


@lru_cache(maxsize=None)
def _files(language: str) -> tuple[str, ...]:
    """The platform's font files for `language` (`any` for the broad pan-Unicode ones), the ones that exist."""
    if sys.platform == "darwin":
        names = [str(_DARWIN_DIR / name) for name in _DARWIN.get(language, ())]
    elif sys.platform == "win32":
        folder = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Fonts"
        names = [str(folder / name) for name in _WINDOWS.get(language, ())]
    else:
        names = list(_LINUX) if language == "any" else []
    return tuple(name for name in names if _allowed(name) and os.path.isfile(name))


@lru_cache(maxsize=None)
def _faces(language: str) -> tuple[Face, ...]:
    """Every face of the platform's files for `language`, then (on Linux) what fontconfig names for it."""
    from fontTools.ttLib import TTCollection, TTLibError

    found: list[Face] = []
    for path in _files(language):
        try:
            with TTCollection(path, lazy=True) as collection:
                found += [Face(path, index) for index in range(len(collection.fonts))]
        except TTLibError:                                   # one font, not a collection
            found.append(Face(path, 0))
        except OSError:
            continue
    if sys.platform.startswith("linux") and language in _FC_LANGUAGES:
        found += _fc_match(language)
    return tuple(found)


@lru_cache(maxsize=None)
def _cmap(face: Face) -> frozenset[int]:
    from fontTools.ttLib import TTFont

    try:
        with TTFont(face.path, fontNumber=face.index, lazy=True) as font:
            return frozenset(font.getBestCmap() or ())
    except Exception:                                         # a damaged or unreadable file lists no characters
        return frozenset()


@lru_cache(maxsize=None)
def _truetype(face: Face, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(face.path, size, index=face.index)


@lru_cache(maxsize=None)
def _default(size: int):
    from PIL import ImageFont

    return ImageFont.load_default(size=size)


@lru_cache(maxsize=None)
def _default_draws(char: str) -> bool:
    """Whether Pillow's built-in font has a glyph for `char`."""
    return draws_glyph(_default(20), char)


def _needed(text: str) -> frozenset[str]:
    return frozenset(c for c in text if not c.isspace())


@lru_cache(maxsize=None)
def _choose(chars: frozenset[str]) -> tuple[Face | None, frozenset[str]]:
    """The face for a set of characters (None: the built-in font) and the characters it leaves undrawn."""
    left = frozenset(c for c in chars if not _default_draws(c))
    if not left:
        return None, frozenset()
    codes = {c: ord(c) for c in chars}
    best, best_missing = None, left                          # the built-in font leaves `left`
    for language in _language_order(chars):
        for face in _faces(language):
            cmap = _cmap(face)
            missing = frozenset(c for c, code in codes.items() if code not in cmap)
            if not missing:
                return face, missing
            if len(missing) < len(best_missing):
                best, best_missing = face, missing
    return best, best_missing


def font_for(text: str, size: int):
    """`(font, missing)`: a font at `size` that draws `text` and the characters of it no font on this machine has."""
    face, missing = _choose(_needed(text))
    return (_default(size) if face is None else _truetype(face, size)), missing


def draws_glyph(font: Any, char: str) -> bool:
    """Whether `font` draws `char` as a glyph and not as the .notdef box (a rendering compared with a known-missing one)."""
    mask, notdef = font.getmask(char), font.getmask(NOTDEF)
    return mask.size != notdef.size or bytes(mask) != bytes(notdef)


def wrap(text: str, size: int, width: int) -> list[str]:
    """`text` broken into lines no wider than `width` pixels at `size`: at a space when the line has one, else between
    two characters (Korean, Japanese, and Chinese run on with few or no spaces, and a full-width glyph is about twice
    a Latin one, so a count of characters does not say how wide a line is)."""
    font, _ = font_for(text, size)
    lines: list[str] = []
    line = ""
    for char in text:
        if line and font.getlength(line + char) > width:
            cut = line.rfind(" ")
            if char.isspace() or cut < 1:
                lines.append(line.rstrip())
                line = "" if char.isspace() else char
                continue
            lines.append(line[:cut].rstrip())
            line = line[cut + 1:] + char
            continue
        line += char
    if line.strip():
        lines.append(line.strip())
    return lines


def fit(text: str, size: int, width: int) -> str:
    """`text` cut to the characters that fit in `width` pixels at `size`."""
    font, _ = font_for(text, size)
    while text and font.getlength(text) > width:
        text = text[:-1]
    return text


class Pen:
    """Draws strings on one sheet in a font that covers them, and records the strings no font could."""

    def __init__(self, draw: Any) -> None:
        self.draw = draw
        self.limits: dict[str, str] = {}                     # string -> its characters that will show as boxes

    def text(self, xy: tuple[int, int], text: str, *, fill: Any, size: int) -> None:
        font, missing = font_for(text, size)
        if missing:
            self.limits.setdefault(text, "".join(sorted(missing)))
        self.draw.text(xy, text, fill=fill, font=font)

    def characters(self) -> str:
        return " ".join(f"U+{ord(c):04X}" for c in sorted({c for chars in self.limits.values() for c in chars}))

    def report(self) -> list[str]:
        """What could not be drawn, for the command to print: empty when every string was drawn."""
        if not self.limits:
            return []
        strings = ", ".join(repr(s) for s in list(self.limits)[:8]) + (", ..." if len(self.limits) > 8 else "")
        return [f"no font on this machine has {self.characters()}; {len(self.limits)} strings of the sheet show boxes "
                f"for them instead of letters: {strings}"]

    def limit_line(self) -> str | None:
        """The same, as a plain-ASCII line for the foot of the sheet (a boxed string cannot say which it is)."""
        if not self.limits:
            return None
        return f"limit: no font on this machine has {self.characters()}; {len(self.limits)} strings show boxes"


def with_limit_line(sheet: Any, pen: Pen, background: Any, ink: Any, pad: int) -> Any:
    """`sheet`, with the limit line under it when the pen recorded one; the sheet itself otherwise."""
    line = pen.limit_line()
    if line is None:
        return sheet
    from PIL import Image, ImageDraw

    height = FALLBACK_LINE_SIZE + 2 * pad
    taller = Image.new("RGB", (sheet.width, sheet.height + height), background)
    taller.paste(sheet, (0, 0))
    ImageDraw.Draw(taller).text((pad, sheet.height + pad // 2), line, fill=ink, font=_default(FALLBACK_LINE_SIZE))
    return taller
