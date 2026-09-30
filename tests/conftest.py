"""Shared test fixtures: isolated user cache, browser loopback server, and browser/CJK markers."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

BROWSER_MODULES = re.compile(r"test_(render_(core|interaction|text|visual)|behavior_\w+)\.py$")


def _installed_browsers() -> str:
    """Where Playwright installed its browsers, read before the cache is isolated.

    On Linux Playwright looks under $XDG_CACHE_HOME (on every platform, under the home folder), so a
    CLI subprocess started with the isolated cache would not find the browser. A relative path that is
    already set (not "0", which means the browsers inside the package) becomes absolute, because
    subprocesses run in other folders."""
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured:
        return configured if configured == "0" or os.path.isabs(configured) else os.path.abspath(configured)
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Caches"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    return str(base / "ms-playwright")


INSTALLED_BROWSERS = _installed_browsers()


@pytest.fixture(autouse=True)
def isolated_lazuli_cache(tmp_path, monkeypatch):
    from lazuli import paths

    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.delenv("LAZULI_DB", raising=False)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", INSTALLED_BROWSERS)
    # macOS and Windows use platform cache directories rather than XDG_CACHE_HOME.
    monkeypatch.setattr(paths, "cache_dir", lambda: cache / "lazuli")


def pytest_collection_modifyitems(items):
    for item in items:
        if "browser" in item.fixturenames or BROWSER_MODULES.search(item.path.name):
            item.add_marker(pytest.mark.browser)
        if item.get_closest_marker("cjk") and any(
            importlib.util.find_spec(name) is None for name in ("kiwipiepy", "sudachipy", "sudachidict_core", "rjieba")
        ):
            item.add_marker(pytest.mark.skip(reason="requires the cjk optional extra"))


def pytest_addoption(parser):
    parser.addoption("--shard", metavar="K/N", help="run only the Kth of N disjoint parts of the selected tests "
                     "(CI splits the browser tests across runners); parts are fixed by each test's id")


def shard_of(nodeid: str, count: int) -> int:
    """The part (1..count) a test belongs to: stable across runs, machines, and Python versions."""
    return int.from_bytes(hashlib.sha256(nodeid.encode()).digest()[:8], "big") % count + 1


class _Shard:
    """Keeps only this shard's tests. A plugin of its own, registered after the built-in `-m` filter,
    so `trylast` puts it after markers and `-m` have chosen the tests."""

    def __init__(self, part: int, count: int):
        self.part, self.count = part, count

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config, items):
        keep = [item for item in items if shard_of(item.nodeid, self.count) == self.part]
        config.hook.pytest_deselected(items=[item for item in items if shard_of(item.nodeid, self.count) != self.part])
        items[:] = keep


def pytest_configure(config):
    spec = config.getoption("--shard")
    if not spec:
        return
    match = re.fullmatch(r"([1-9]\d*)/([1-9]\d*)", spec)
    if not match or int(match[1]) > int(match[2]):
        raise pytest.UsageError(f"--shard wants K/N with 1 <= K <= N, not {spec!r}")
    config.pluginmanager.register(_Shard(int(match[1]), int(match[2])), "lapis-shard")


@pytest.fixture(scope="session")
def render_server():
    directory = Path(__file__).parent / "fixtures" / "render"
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()
