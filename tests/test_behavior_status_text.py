"""Real browser check of `status_changed` (DERIVED.md, Settle window): a changed box is status when it sits in a
status, alert, or live region or an output, or when the text it gained names a result or a count. A label the
box always showed, and a number that changes alone, are not."""
from __future__ import annotations

import contextlib
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.session import Session

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"></head><body><main>
<p id="items">Items: 72 pieces in 4 firings</p>
<p id="page">Results: page 1</p>
<p id="note">Waiting</p>
<p id="cart-line">Cart</p>
<button type="button" onclick="items.textContent='Items: 73 pieces in 4 firings';page.textContent='Results: page 2'">More</button>
<button type="button" onclick="note.textContent='저장했어요'">Save</button>
<button type="button" onclick="note.textContent='검색 결과 12개'">Search</button>
<button type="button" onclick="note.textContent='Added'">Add</button>
<button type="button" onclick="note.textContent='Cart 3'">Count</button>
<button type="button" onclick="region.textContent='Anything at all'">Announce</button>
<button type="button" onclick="out.value='whatever'">Compute</button>
<div id="region" role="status"></div>
<output id="out" style="display:block">idle</output>
</main></body></html>"""


@pytest.fixture
def served(tmp_path):
    (tmp_path / "index.html").write_text(PAGE)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@contextlib.contextmanager
def _driver(browser, url):
    driver = Driver(browser, Session(url, "status"), "d")
    driver.open()
    try:
        yield driver
    finally:
        driver.close()


def _status_after(driver, button):
    box = next(item["id"] for item in driver.boxes() if item["name"] == button and item["role"] == "button")
    effect = driver.act({"kind": "click", "target": box})
    return sorted(driver.page.locator(f'[data-lapis-box="{bid}"]').evaluate("el => el.id") for bid in effect["status_changed"])


@pytest.mark.parametrize("button, status", [
    ("More", []),                         # numbers that change inside a line whose label was always there
    ("Save", ["note"]),                   # 저장했어요
    ("Search", ["note"]),                 # 검색 결과 12개
    ("Add", ["note"]),                    # Added
    ("Count", ["note"]),                  # Cart 3
    ("Announce", ["region"]),             # whatever a status region gains
    ("Compute", ["out"]),                 # an output
])
def test_a_changed_box_is_status_by_where_it_sits_or_what_it_gained(browser, served, button, status):
    with _driver(browser, served) as driver:
        assert _status_after(driver, button) == status
