"""Shared by the narrowed-run tests: a four-button page, a stub, and the CLIs run from a project folder."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from lapis_design.render.ids import box_id

STUB = """version: 0
clock: {start: '2026-10-01T00:00:00Z'}
collections: {}
variants: {empty: {}, partial: {}}
routes: []
values: {}
"""
# Four buttons with stable ids, so their box ids can be computed; the first two reveal a sibling note on hover.
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Buttons</title>
<style>body{margin:0;font:16px/1.4 sans-serif} button{font:inherit} .tip{display:none}
.has-tip:hover + .tip{display:block}</style></head>
<body><main><h1>Buttons</h1>
<button id="b1" type="button" class="has-tip" onclick="this.textContent='One!'">One</button><span class="tip">Tip one</span>
<button id="b2" type="button" class="has-tip" onclick="this.textContent='Two!'">Two</button><span class="tip">Tip two</span>
<button id="b3" type="button" onclick="this.textContent='Three!'">Three</button>
<button id="b4" type="button" onclick="this.textContent='Four!'">Four</button>
</main></body></html>
"""
BUTTONS = {name: box_id([("html", 0, None), ("body", 0, None), ("main", 0, None), ("button", index, name)])
           for index, name in enumerate(("b1", "b2", "b3", "b4"))}


def make_project(folder: Path) -> Path:
    """A folder to run the checks from (reports go to its `.lapis/`), with the page and a stub in it."""
    (folder / "site").mkdir()
    (folder / "site" / "index.html").write_text(PAGE)
    (folder / "stub.yaml").write_text(STUB)
    return folder


def run(project: Path, command: str, *argv: str) -> subprocess.CompletedProcess:
    script = f"import sys\nfrom lapis_design.{command} import main\nraise SystemExit(main(sys.argv[1:]))"
    env = {**os.environ, "LAPIS_SIG_KEY_FILE": str(project / "sig.key")}
    return subprocess.run([sys.executable, "-c", script, *argv], capture_output=True, text=True, cwd=project,
                          env=env, timeout=600)


def behavior(project: Path, *argv: str) -> subprocess.CompletedProcess:
    return run(project, "behavior_check", "site/index.html", "--task", "t", "--stub", "stub.yaml", *argv)


def render(project: Path, *argv: str) -> subprocess.CompletedProcess:
    return run(project, "render", "site/index.html", "--task", "t", *argv)


def digest(folder: Path) -> dict[str, str]:
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file()}
