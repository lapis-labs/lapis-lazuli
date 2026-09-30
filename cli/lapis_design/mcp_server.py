"""`lapis-design mcp`: the lapis-lazuli MCP server over stdio.

Registered by the lazuli plugin's .mcp.json and by `hermes mcp add` (install/OUTPUTS.md, MCP). The
SDK serves both handshake-based and per-request protocol versions.

Tools
  slop_lint   `lapis-design slop lint` (cli/lapis_design/lint/cli.py): the findings report as a result
"""

from __future__ import annotations

import re

from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from lapis_design import __version__

NAME = "lapis-lazuli"


def slop_lint(plan: str | None = None, extract: str | None = None, session: str | None = None,
              source: str | None = None, ledger: str | None = None, lock: str | None = None,
              refs: list[str] | None = None, corpus: str | None = None, lazuli_db: str | None = None,
              rules: str | None = None, mode: str = "create", layers: list[str] | None = None,
              rule_ids: list[str] | None = None) -> dict[str, Any]:
    """Run the slop rules over the given files and return the findings report (finding.schema.yaml).

    Paths are files, except `source` (the project source tree) and `corpus` (a directory of corpus
    entries, or one entry). `mode` is create or review. `layers` defaults to every layer whose input
    is given; an explicitly selected layer without its input is an error. `rule_ids` takes rule ids
    or glob patterns. `lock` defaults to ./.lapis/fonts.lock.json when present; `lazuli_db` defaults
    to $LAZULI_DB, else the user cache database if present. Explicit paths win. Blocking findings
    have `blocking: true`; `summary.blocking` counts them.
    """
    from lapis_design.lint import cli   # the detectors load only when the tool runs

    def path(value: str | None) -> Path | None:
        return Path(value) if value else None

    try:
        return cli.run(rules=path(rules), plan=path(plan), extract=path(extract), session=path(session),
                       source=path(source), ledger=path(ledger), lock=path(lock),
                       refs=[Path(r) for r in refs or []], corpus=path(corpus),
                       lazuli_db=path(lazuli_db), mode=mode, layers=layers,
                       rule_ids=rule_ids or [])
    except cli.LintError as exc:        # an unusable input: the caller can fix it, so it reads the reason
        message = str(exc)
        if message.startswith("layer ") and " requires " in message:
            message = message.replace("--mode review", 'mode="review"')
            parameters = {"ref": "refs", "layer": "layers", "rule": "rule_ids", "lazuli-db": "lazuli_db"}
            message = re.sub(r"--([a-z][a-z-]*)\b",
                             lambda match: parameters.get(match[1], match[1]), message)
        raise ToolError(message) from exc


def build() -> MCPServer:
    server = MCPServer(name=NAME, version=__version__)
    server.add_tool(slop_lint, name="slop_lint")
    return server


def serve() -> None:
    build().run("stdio")
