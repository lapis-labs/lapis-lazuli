"""lapis-design: the checks the LapisLazuli skills run, and the command their hooks and MCP entries call."""
from __future__ import annotations

import argparse
import importlib
import sys

from lapis_design import __version__
from lapis_design import hooks

# `lapis-design <noun> <verb> ARGS...` hands ARGS to the check's own parser unchanged
CHECKS = {
    ("plan", "check"): "lapis_design.plan_check",
    ("rights", "check"): "lapis_design.rights_check",
    ("render", "check"): "lapis_design.render",
    ("behavior", "check"): "lapis_design.behavior_check",
    ("stub", "serve"): "lapis_design.stub",
    ("slop", "lint"): "lapis_design.lint.cli",
    ("release", "check"): "lapis_design.release_check",
    ("draft", "check"): "lapis_design.draft",
    ("handoff", "export"): "lapis_design.handoff",
    ("handoff", "check"): "lapis_design.handoff",
    ("skill", "loaded"): "lapis_design.skill_load",
    ("requirements", "seal"): "lapis_design.requirements",
    ("requirements", "show"): "lapis_design.requirements",
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    module = CHECKS.get(tuple(argv[:2]))
    if module:
        return importlib.import_module(module).main(argv[2:], prog=f"lapis-design {argv[0]} {argv[1]}")
    if argv[:1] == ["next"]:
        return importlib.import_module("lapis_design.next_step").main(argv[1:], prog="lapis-design next")
    if argv[:1] == ["hook"]:
        return hooks.main(argv[1:])

    ap = argparse.ArgumentParser(prog="lapis-design", description=__doc__.split(":", 1)[1].strip())
    ap.add_argument("--version", action="version", version=f"lapis-design {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)
    for noun in dict.fromkeys(n for n, _ in CHECKS):
        verbs = sub.add_parser(noun, help=f"{noun} checks").add_subparsers(dest="verb", required=True)
        for n, verb in CHECKS:
            if n == noun:
                verbs.add_parser(verb, help=f"run {noun} {verb} (see `lapis-design {noun} {verb} -h`)")
    sub.add_parser("next", help="the next step of the procedure still to do (see `lapis-design next -h`)")
    sub.add_parser("hook", help="run a harness hook (reads the event JSON on stdin; version skew fails open)")
    sub.add_parser("mcp", help="serve the lapis-lazuli MCP server over stdio")
    args = ap.parse_args(argv)
    from lapis_design.mcp_server import serve   # the SDK loads only for the server, not for every hook
    serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
