"""Shared test fixtures: isolated user cache, no installed fonts, a font table with extra generic families, browser loopback server, and browser/CJK markers."""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from shards import load_durations, partition

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


@pytest.fixture(autouse=True)
def no_installed_fonts(tmp_path_factory, monkeypatch):
    """One empty font folder instead of this computer's fonts for every test. `LAZULI_FONT_ROOTS` replaces the
    roots and turns the Core Text listing off, so no test reads an installed or an Adobe Fonts face unless it
    sets its own roots (over this) or removes the variable (and then fakes the font list)."""
    empty = tmp_path_factory.mktemp("no-fonts")
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={empty}")


@pytest.fixture
def real_previews():
    """Asked for by a test that serves a page itself and wants `preview.answers` to mean what it says."""


@pytest.fixture(autouse=True)
def previews_answer(request, monkeypatch):
    """The procedure tests link pages on 127.0.0.1:4173 that nothing serves, and ask `next` about waiting, not about
    whether the link is alive: `preview.answers` says yes to every address unless the test asks for `real_previews`."""
    if "real_previews" not in request.fixturenames:
        from lapis_design import preview

        monkeypatch.setattr(preview, "answers", lambda url, timeout=preview.TIMEOUT_S: True)


@pytest.fixture
def house_generics(tmp_path, monkeypatch):
    """The shared contracts with one more generic family (`house-stack`) and one more name the platform
    answers with its own sans (`house-sans`) in fonts/system-fonts.yaml, set as $LAPIS_SHARED. A check
    that treats them as generic reads the table; one that keeps its own list does not."""
    import shutil

    import yaml

    shared = tmp_path / "shared-with-house-families"
    shutil.copytree(Path(__file__).resolve().parents[1] / "src" / "shared", shared)
    table = shared / "fonts" / "system-fonts.yaml"
    doc = yaml.safe_load(table.read_text(encoding="utf-8"))
    for family in ("house-stack", "house-sans"):
        doc["fonts"].append({"family": family, "platforms": ["all"], "scripts": ["all"], "class": "generic",
                             "verified": "keyword", "note": "test keyword"})
    doc["platform_sans"].append("house-sans")
    table.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("LAPIS_SHARED", str(shared))
    return {"generic": "house-stack", "sans": "house-sans"}


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
                     "(CI splits the browser tests across runners); parts are weighed by tests/shard_durations.json")


class _Shard:
    """Keeps only this shard's tests. A plugin of its own, registered after the built-in `-m` filter,
    so `trylast` puts it after markers and `-m` have chosen the tests."""

    def __init__(self, part: int, count: int):
        self.part, self.count = part, count

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config, items):
        parts = partition((item.nodeid for item in items), self.count, load_durations())
        keep = [item for item in items if parts[item.nodeid] == self.part]
        config.hook.pytest_deselected(items=[item for item in items if parts[item.nodeid] != self.part])
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
