"""Where lazuli keeps its per-user state: the user cache, never a project or a synced folder."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def cache_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "lazuli"
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "lazuli" / "Cache"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "lazuli"


def db_path() -> Path:
    """The lazuli database; `LAZULI_DB` overrides it (tests always set it)."""
    if path := os.environ.get("LAZULI_DB"):
        return Path(path).expanduser()
    return cache_dir() / "lazuli.db"
