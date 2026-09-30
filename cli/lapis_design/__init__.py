"""lapis-design CLI package (v0 draft)."""
from __future__ import annotations

import os
from pathlib import Path

__version__ = "0.1.0"


def shared_dir() -> Path:
    """The full shared contracts the CLI checks against (never a skill's reduced view).

    Order: $LAPIS_SHARED; the copy packaged with the CLI (lapis_design/shared, added by the build as
    package data); the repository checkout (src/shared next to cli/).
    """
    env = os.environ.get("LAPIS_SHARED")
    candidates = [Path(env)] if env else []
    here = Path(__file__).resolve().parent
    candidates += [here / "shared", here.parents[1] / "src" / "shared"]
    for c in candidates:
        if (c / "plan" / "schema.yaml").is_file():
            return c
    raise FileNotFoundError("LapisLazuli shared contracts not found; reinstall the CLI or set LAPIS_SHARED")
