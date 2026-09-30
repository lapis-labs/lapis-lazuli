"""A font list standing in for Core Text, so tests can have Adobe Fonts faces without any Adobe data.

Each face is a synthetic font built in code (`synthetic_fonts.build`) in a folder that is not Adobe's. Install
it with `monkeypatch.setattr(coretext, "provider", lambda: fake)`, which also works where `LAZULI_FONT_ROOTS`
would turn the real listing off (it always is, in tests).
"""
from __future__ import annotations

import json
from pathlib import Path

from lazuli import coretext, measure, scan
from synthetic_fonts import build


class FileBackedFace(measure.Face):
    """What a Core Text face answers, from a synthetic file that is not Adobe's."""
    method = "coretext"

    def font_metrics(self) -> dict:
        return {"upm": self.upm}


class FakeAdobe(coretext.Provider):
    """identity -> a synthetic font file and a version name. `broken` makes `faces()` fail like a lost font list."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.entries: dict[str, tuple[Path, str]] = {}
        self.broken = False

    def add(self, family: str, version: str = "Version 1.000", **kwargs) -> str:
        path = build(self.folder / f"{family}.ttf", family=family, **kwargs)
        identity = coretext.IDENTITY_PREFIX + f"{family.replace(' ', '')}-Regular"
        self.entries[identity] = (path, version)
        return identity

    def identities(self) -> list[str]:
        return sorted(self.entries)

    def faces(self) -> list[coretext.AdobeFace]:
        if self.broken:
            raise OSError("the font list is gone")
        return [coretext.AdobeFace(identity, coretext.IDENTITY_PREFIX + version,
                                   lambda blocks, wanted, path=path, version=version: self._describe(path, wanted, version))
                for identity, (path, version) in sorted(self.entries.items())]

    @staticmethod
    def _describe(path: Path, wanted: frozenset[int], version: str) -> dict:
        with scan.faces(path)[0][1] as font:
            info = scan.describe(font)
            mapped = {cp for cp in wanted if cp in (font.getBestCmap() or {})}
        metadata = json.loads(info["metadata_json"])
        metadata.update(version=version, features_source="coretext", class_source="coretext", os2_ranges=None)
        metadata["family_class"] = (metadata["class_id"] << 28) if metadata["class_id"] is not None else None
        return {**{key: info[key] for key in ("postscript_name", "family", "subfamily", "manufacturer", "designer")},
                "names_i18n": json.loads(info["names_i18n_json"] or "{}"), "coverage": json.loads(info["coverage_json"]),
                "mapped": mapped, "metadata": metadata}

    def open(self, identity: str, raster_px: int):
        if identity not in self.entries:
            raise LookupError(identity)
        return FileBackedFace(str(self.entries[identity][0]), 0)
