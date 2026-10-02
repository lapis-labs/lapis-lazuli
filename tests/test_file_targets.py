"""`behavior check` and `render check` take an HTML file (path or file:// URL) and run it from a loopback server."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml

from lapis_design import shared_dir

FIXTURE = Path(__file__).parent / "fixtures" / "behavior" / "shop" / "shop.stub.yaml"
LOOPBACK_PAGE = re.compile(r"http://127\.0\.0\.1:\d+/index\.html")

pytestmark = pytest.mark.browser

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Shop</title><link rel="stylesheet" href="/site.css"></head>
<body><main><h1>Shop</h1><button id="load" type="button">Load products</button><ul id="list"></ul>
<a href="other.html">Other page</a></main>
<script>document.getElementById('load').addEventListener('click', async () => {
  const items = await (await fetch('/api/products')).json();
  document.getElementById('list').innerHTML = items.map(item => '<li>' + item.name + '</li>').join('');
});</script></body></html>
"""


@pytest.fixture
def page(tmp_path: Path) -> Path:
    """A plain-file page whose stylesheet is linked from the site root, and whose products come from the stub."""
    folder = tmp_path / "my site"
    folder.mkdir()
    (folder / "index.html").write_text(PAGE)
    (folder / "site.css").write_text("h1{font-size:40px}")
    (folder / "other.html").write_text("<!doctype html><html lang='en'><title>Other</title><main><h1>Other</h1></main>")
    return folder / "index.html"


def run_check(command: str, *argv: str) -> subprocess.CompletedProcess:
    script = f"import sys\nfrom lapis_design.{command} import main\nraise SystemExit(main(sys.argv[1:]))"
    return subprocess.run([sys.executable, "-c", script, *argv], capture_output=True, text=True, timeout=240)


@pytest.mark.parametrize("form", ["url", "path"])
def test_behavior_check_runs_an_html_file_and_the_stub_still_answers(page: Path, tmp_path: Path, form: str):
    target = page.as_uri() if form == "url" else str(page)
    output = tmp_path / "session.json"
    result = run_check("behavior_check", target, "--task", "shop", "--stub", str(FIXTURE), "--probe", "controls",
                       "--context", "d", "--out", str(output))
    assert result.returncode == 0, result.stderr
    text = output.read_text()
    document = json.loads(text)
    schema = yaml.safe_load((shared_dir() / "behavior" / "session.schema.yaml").read_text())
    jsonschema.Draft202012Validator(schema).validate(document)
    assert LOOPBACK_PAGE.fullmatch(document["source"]["url"])
    assert str(tmp_path) not in text                                          # the session names no path on this computer
    requests = [request for control in document["probes"]["controls"] for request in control["effect"]["requests"]]
    assert any(request["path"] == "/api/products" and request["status"] == 200 for request in requests)   # the stub answered
    assert any(request["path"] == "/other.html" and request["status"] == 200 for request in requests)     # the folder did


def test_render_check_runs_an_html_file_with_its_site_root_stylesheet(page: Path, tmp_path: Path):
    output = tmp_path / "render.json"
    result = run_check("render", page.as_uri(), "--task", "shop", "--width", "390", "--out", str(output))
    assert result.returncode == 0, result.stderr
    document = json.loads(output.read_text())
    assert LOOPBACK_PAGE.fullmatch(document["source"]["url"]) and "addresses" not in document["source"]
    heading = next(run for run in document["viewports"][0]["text"] if run["text"] == "Shop")
    assert heading["size_px"] == 40.0                                         # /site.css loaded, as it would from a server
