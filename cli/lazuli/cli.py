"""lazuli: local fonts and colors, catalogs, and references for the LapisLazuli skills."""
from __future__ import annotations

import argparse
import importlib
import sys

from lapis_design import __version__

# `lazuli <words> ARGS...` hands ARGS to the command's own parser unchanged
COMMANDS = {
    ("local", "fonts"): "lazuli.local",
    ("catalog",): "lazuli.catalog.cli",
    ("doctor",): "lazuli.doctor",
    ("class",): "lazuli.user_class",
    ("lock",): "lazuli.lock",
    ("fetch",): "lazuli.fetch",
    ("license",): "lazuli.license",
    ("search",): "lazuli.search",
    ("sources",): "lazuli.sources",
    ("hints",): "lazuli.hints",
    ("color",): "lazuli.color",
    ("read",): "lazuli.read",
    ("ref",): "lazuli.ref",
    ("setup",): "lazuli.setup",
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for words, module in COMMANDS.items():
        if tuple(argv[:len(words)]) == words:
            return importlib.import_module(module).main(argv[len(words):], prog="lazuli " + " ".join(words))
    ap = argparse.ArgumentParser(prog="lazuli", description=__doc__.split(":", 1)[1].strip())
    ap.add_argument("--version", action="version", version=f"lazuli {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)
    local = sub.add_parser("local", help="what is installed on this computer")
    local.add_subparsers(dest="what", required=True).add_parser(
        "fonts", help="scan (read-only), measure, and list local fonts (see `lazuli local fonts -h`)")
    sub.add_parser("catalog", help="font catalogs: `lazuli catalog sync|lookup|status` (see `lazuli catalog -h`)")
    sub.add_parser("doctor", help="check that this computer can run the CLI")
    sub.add_parser("class", help="record your own class for a font: `lazuli class set|list|remove` (outranks catalogs)")
    sub.add_parser("lock", help="pin a chosen font's source, license, and delivery in .lapis/fonts.lock.json")
    sub.add_parser("fetch", help="fetch an open-licensed Google Fonts family's files and license text into the project")
    sub.add_parser("license", help="print what a font says about its own license and where to look for the governing one")
    sub.add_parser("search", help="find fonts, colors, or sources for a role and constraints (`--type`)")
    sub.add_parser("sources", help="list the source registry with each source's access policy")
    sub.add_parser("hints", help="list reference fields, modes, and media, or record rotating starting points per axis for a task")
    sub.add_parser("color", help="color system codes: `lazuli color lookup|record` (Pantone codes and links)")
    sub.add_parser("read", help="read one requested web page as Markdown, within its access policy")
    sub.add_parser("ref", help="reference profiles: `lazuli ref capture|profile|system`")
    sub.add_parser("setup", help="install an optional font style embedding model")
    ap.parse_args(argv)
    return 2


if __name__ == "__main__":
    sys.exit(main())
