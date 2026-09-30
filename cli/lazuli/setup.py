"""`lazuli setup`: choose, download, and verify an optional font style embedding model.

Embeddings are an optional signal on top of measurement and catalogs. Installing one needs a
published release manifest (files, checksums, dimensions, license) from lazuli-models. No model is
published and the manifest format is not defined yet, so setup reports that and installs nothing;
every other lazuli command works without a model.
"""
from __future__ import annotations

import argparse
import json

MISSING = ("no font style embedding model is published yet, and the release manifest that setup "
           "reads (files, checksums, dimensions, license) is not defined; nothing was installed. "
           "Every other lazuli command works without a model.")


def main(argv: list[str] | None = None, prog: str = "lazuli setup") -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args(argv)
    if args.json:
        print(json.dumps({"installed": None, "available": [], "reason": MISSING}))
    else:
        print(f"lazuli setup: {MISSING}")
    return 1
