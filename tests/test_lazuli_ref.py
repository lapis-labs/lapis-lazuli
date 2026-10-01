"""`lazuli ref capture|profile|system`: reference profiles in the render extract format.

Nothing here reaches a live site. Non-browser tests give the polite fetcher a fake transport (the
default transport fails the test) and stand in for the browser; browser tests capture the loopback
`render_server` fixture pages. The lazuli cache and the signature key live in a temporary folder.
"""
from __future__ import annotations

import contextlib
import errno
import json
import os
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from lapis_design.render.color import to_oklch
from lapis_design.render.extract import validate
from lapis_design.text_sig import page_sig, run_sig
from lazuli import paths, ref, sources
from lazuli.catalog import net
from lazuli.ref import site
from lazuli.ref.common import Refused

COPY = "Hello reference world"
ALT = "A striped mountain"
NAME = "Buy the thing"
URL = "https://ref.invalid/work?utm=1"


@pytest.fixture(autouse=True)
def cache(monkeypatch, tmp_path) -> Path:
    folder = tmp_path / "cache"
    monkeypatch.setattr(paths, "cache_dir", lambda: folder)
    monkeypatch.setenv("LAPIS_SIG_KEY_FILE", str(tmp_path / "sig.key"))
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    monkeypatch.setattr(net, "_last_request", {})
    return folder


@pytest.fixture
def project(tmp_path) -> Path:
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


def files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file())


def run(project: Path, *argv: str) -> int:
    return ref.main([*argv, "--project", str(project)])


# ------------------------------------------------------------------ capture, without a browser

class Clock:
    def __init__(self):
        self.now = 1_000.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class Site:
    """A fake transport: fixed pages by URL and a log of (url, User-Agent, clock time); 404 for the rest."""

    def __init__(self, clock: Clock, pages: dict[str, net.Response | str]):
        self.clock, self.pages, self.log = clock, pages, []

    def __call__(self, url: str, headers: dict) -> net.Response:
        self.log.append((url, headers.get("User-Agent"), self.clock.now))
        page = self.pages.get(url)
        if page is None:
            return net.Response(url, 404, {"content-type": "text/plain"}, b"not found")
        if isinstance(page, net.Response):
            return page
        kind = "text/plain" if url.endswith(".txt") else "application/json" if page.startswith("{") else "text/html"
        return net.Response(url, 200, {"content-type": f"{kind}; charset=utf-8"}, page.encode())


class FakeBrowser:
    """Stands in for Chromium: capture() is replaced, so only the User-Agent probe reaches it."""

    def __init__(self):
        self.opened = 0

    def new_context(self, **options):
        return SimpleNamespace(new_page=lambda: SimpleNamespace(evaluate=lambda script: "TestBrowser/1.0"),
                               close=lambda: None)


def fake_viewport(width: int, key: bytes, *, text: bool = True) -> dict:
    """What the render capture returns for a page with a named button, an image with alt text, and copy."""
    button, image = "b" + "0" * 12, "b" + "1" * 12
    rect = {"x": 0, "y": 0, "w": 10, "h": 10}
    vp = {"width": width, "height": 844, "browser_chrome": False, "dpr": 2, "theme": "light",
          "reduced_motion": False, "scroll_width": width,
          "boxes": [{"id": button, "parent": None, "role": "button", "role_confidence": 1, "rect": rect,
                     "a11y": {"role": "button", "name": NAME, "name_source": "contents", "focusable": True}},
                    {"id": image, "parent": None, "role": "media", "role_confidence": 1, "rect": rect,
                     "media": {"kind": "img", "loaded": True, "alt": ALT, "decorative": False,
                               "phash": "0123456789abcdef"}}],
          "text": []}
    if text:
        vp["text"] = [{"id": f"{button}-t0", "box": button, "text": COPY, "text_sig": run_sig(COPY, "latn", key),
                       "chars": 19, "script": "latn", "font": {"requested": "Arial", "rendered": "Arial"},
                       "size_px": 16}]
        vp["text_sig"] = page_sig([(COPY, "latn")], key)
    return vp


@pytest.fixture
def fake_capture(monkeypatch):
    """Robots.txt with a crawl delay and one page on a fake site that answers every request; the
    browser capture is replaced. Like capture(), the replacement writes the screenshot it is given.
    `after_capture(named, width)` runs once that screenshot is written; `on_close()` runs when the
    browser closes."""
    clock = Clock()
    fake = SimpleNamespace(clock=clock, loads=[], browser=FakeBrowser(), page_text=True, png=b"\x89PNG first run",
                           named=None, after_capture=None, on_close=None,
                           site=Site(clock, {"https://ref.invalid/robots.txt": "User-agent: *\nCrawl-delay: 7\n",
                                             URL: "<html><title>Work</title></html>"}))
    monkeypatch.setattr(net, "_clock", clock.time)
    monkeypatch.setattr(net, "_sleep", clock.sleep)
    monkeypatch.setattr(net, "default_transport", fake.site)

    @contextlib.contextmanager
    def open_browser():
        fake.browser.opened += 1
        try:
            yield fake.browser
        finally:
            if fake.on_close:
                fake.on_close()

    def capture(browser, url, config, shot, key, *, check_document=None):
        fake.named = browser
        fake.loads.append({"url": url, "width": config["width"], "at": clock.now, "shot": shot,
                           "user_agent": browser.user_agent})
        clock.now += 2                                       # a page load takes time
        shot.parent.mkdir(parents=True, exist_ok=True)
        shot.write_bytes(fake.png)
        if fake.after_capture:
            fake.after_capture(browser, config["width"])
        return fake_viewport(config["width"], key, text=fake.page_text)

    monkeypatch.setattr(site, "_open_browser", open_browser)
    monkeypatch.setattr(site, "capture", capture)
    return fake



@pytest.mark.parametrize("rights", ["reference-only", "own"])
def test_capture_keeps_what_the_rights_allow(fake_capture, project, cache, rights):
    assert run(project, "capture", URL + "#top", "--rights", rights) == 0
    out = project / ".lapis" / "refs" / "ref-invalid-work.json"
    assert files(project) == [out]                           # screenshots never land in the project
    profile = json.loads(out.read_text(encoding="utf-8"))
    assert validate(profile) == []
    assert profile["source"] == {"kind": "site", "url": "https://ref.invalid/work"}
    assert profile["reference"] == {"rights": rights, "captured_by": "user-request"}
    assert profile["meta"]["extractor"]["name"] == "lazuli-ref"
    viewports = profile["viewports"]
    assert [vp["width"] for vp in viewports] == [390, 768, 1440]
    runs = [r for vp in viewports for r in vp["text"]]
    boxes = [b for vp in viewports for b in vp["boxes"]]
    assert all(len(r["text_sig"]) == 128 for r in runs) and all(len(vp["text_sig"]) == 1024 for vp in viewports)
    assert all(b["media"]["phash"] == "0123456789abcdef" for b in boxes if "media" in b)
    folder = cache / "refs" / "ref-invalid-work"
    shots = [str(folder / f"{w}.png") for w in (390, 768, 1440)]
    assert files(folder) == sorted(Path(shot) for shot in shots)   # moved out of the run's staging folder
    assert [p.name for p in (cache / "refs").iterdir()] == ["ref-invalid-work"]
    for load, shot in zip(fake_capture.loads, shots):              # written inside the cache, then moved
        staged = load["shot"]
        assert staged.name == Path(shot).name and staged.parent.parent == folder.parent
        assert staged.parent.name.startswith(".ref-invalid-work-") and not staged.parent.exists()
    if rights == "reference-only":
        written = out.read_text(encoding="utf-8")
        assert COPY not in written and ALT not in written and NAME not in written
        assert not any("text" in r for r in runs)
        assert not any("screenshot" in vp for vp in viewports)
        assert all("name" not in b.get("a11y", {}) and "alt" not in b.get("media", {}) for b in boxes)
    else:
        assert {r["text"] for r in runs} == {COPY}
        assert [vp["screenshot"] for vp in viewports] == shots
        assert all(b["media"]["alt"] == ALT for b in boxes if "media" in b)


def test_capture_asks_only_for_the_named_page_at_the_site_pace(fake_capture, project):
    assert run(project, "capture", URL, "--rights", "reference-only") == 0
    log = fake_capture.site.log
    assert [url for url, _, _ in log] == ["https://ref.invalid/robots.txt", URL]
    assert {agent for _, agent, _ in log} == {net.USER_AGENT}
    assert all(load["url"] == URL for load in fake_capture.loads)
    assert all(load["user_agent"] == f"TestBrowser/1.0 {net.USER_AGENT}" for load in fake_capture.loads)
    loads = fake_capture.loads
    starts = [load["at"] for load in loads]
    previous_ends = [log[-1][2]] + [load["at"] + 2 for load in loads[:-1]]
    # each page load starts at least the robots.txt Crawl-delay after the previous request ended
    assert [start - end for start, end in zip(starts, previous_ends)] == [7, 7, 7]


def test_reference_fetch_paces_across_runs_using_the_database(fake_capture):
    from lazuli.ref import common

    common.fetch(URL)
    previous = fake_capture.site.log[-1][2]
    net._last_request.clear()                          # stand in for a new process
    fake_capture.clock.now = previous + 1
    common.fetch(URL)
    assert fake_capture.site.log[-2][2] - previous == common.MIN_INTERVAL_S


def test_page_loads_pace_the_next_capture_across_processes(fake_capture, project):
    assert run(project, "capture", URL, "--rights", "own") == 0
    last_page_load = fake_capture.clock.now
    net._last_request.clear()                          # a second process reads only the DB
    fake_capture.clock.now = last_page_load + 0.25
    before = len(fake_capture.site.log)
    assert run(project, "capture", URL, "--rights", "own") == 0
    first_request = fake_capture.site.log[before]
    assert first_request[0] == "https://ref.invalid/robots.txt"
    assert first_request[2] - last_page_load >= 3


def test_failed_page_load_still_records_its_request(fake_capture, project, monkeypatch):
    attempted = []

    def fail_capture(*args, **kwargs):
        attempted.append(fake_capture.clock.now)
        fake_capture.clock.sleep(1)
        raise OSError("page load failed")

    monkeypatch.setattr(site, "capture", fail_capture)
    assert run(project, "capture", URL, "--rights", "own") == 2
    assert len(attempted) == 1
    assert net._last_request["ref"] > attempted[0]


def blocked_navigation() -> Refused:
    return Refused("main-frame navigation to https://elsewhere.invalid/ was not preflighted; request not sent",
                   status="blocked", browser_link="https://elsewhere.invalid/")


@pytest.mark.parametrize("stop, code", [("blocked-at-768", 1), ("blocked-as-the-browser-closes", 1),
                                        ("failed-at-768", 2)])
def test_stopped_capture_leaves_no_screenshot_from_its_run(fake_capture, project, cache, stop, code):
    assert run(project, "capture", URL, "--rights", "own", "--slug", "kept") == 0
    folder = cache / "refs" / "kept"
    earlier = {p.name: p.read_bytes() for p in files(folder)}
    assert sorted(earlier) == ["1440.png", "390.png", "768.png"]

    def after_capture(named, width):
        if width == 768 and stop == "blocked-at-768":           # an aborted navigation, after the document check
            named.blocked = blocked_navigation()
        if width == 768 and stop == "failed-at-768":
            raise OSError("page load failed")

    fake_capture.png = b"\x89PNG second run"
    fake_capture.after_capture = after_capture
    if stop == "blocked-as-the-browser-closes":
        fake_capture.on_close = lambda: setattr(fake_capture.named, "blocked", blocked_navigation())
    assert run(project, "capture", URL, "--rights", "own", "--slug", "kept") == code
    assert {p.name: p.read_bytes() for p in files(folder)} == earlier    # nothing of the second run
    assert [p.name for p in (cache / "refs").iterdir()] == ["kept"]     # and no staging folder either
    assert files(project) == [project / ".lapis" / "refs" / "kept.json"]     # only the first run's profile


def stored(project: Path, cache: Path, slug: str = "kept") -> dict:
    """Everything one slug's capture leaves behind: the profile, each screenshot's bytes, the entries of
    the cache's refs folder (staging and set-aside folders included), and the project's files."""
    profile = project / ".lapis" / "refs" / f"{slug}.json"
    return {"profile": profile.read_bytes() if profile.exists() else None,
            "shots": {p.name: p.read_bytes() for p in files(cache / "refs" / slug)},
            "refs": sorted(p.name for p in (cache / "refs").iterdir()),
            "project": sorted(p.relative_to(project).as_posix() for p in project.rglob("*"))}


def second_capture(fake_capture, project) -> int:
    """Capture the slug `kept` again with other screenshots and another profile (its note)."""
    fake_capture.png = b"\x89PNG second run"
    return run(project, "capture", URL, "--rights", "own", "--slug", "kept", "--notes", "second run")


@pytest.fixture
def first_capture(fake_capture, project, cache) -> dict:
    assert run(project, "capture", URL, "--rights", "own", "--slug", "kept", "--notes", "first run") == 0
    first = stored(project, cache)
    assert sorted(first["shots"]) == ["1440.png", "390.png", "768.png"]
    return first


def unwritable_profile(document, path):
    raise OSError(errno.ENOSPC, "no space left on device", str(path))


@pytest.mark.parametrize("write_extract, message", [
    (lambda document, path: ["viewports: something is wrong"], "nothing was written"),
    (unwritable_profile, "no space left on device"),
], ids=["schema-problems", "disk-error"])
def test_profile_that_cannot_be_written_keeps_the_earlier_profile_and_screenshots(
        fake_capture, first_capture, project, cache, monkeypatch, capsys, write_extract, message):
    monkeypatch.setattr(ref, "write_extract", write_extract)
    assert second_capture(fake_capture, project) == 2
    assert message in capsys.readouterr().err
    assert stored(project, cache) == first_capture


def test_capture_over_a_folder_in_a_screenshot_place_does_not_mix_runs(
        fake_capture, first_capture, project, cache):
    shot = cache / "refs" / "kept" / "768.png"
    shot.unlink()
    shot.mkdir()                                           # what the old screenshot-by-screenshot move tripped on
    assert second_capture(fake_capture, project) == 0
    after = stored(project, cache)
    assert after["shots"] == dict.fromkeys(["1440.png", "390.png", "768.png"], b"\x89PNG second run")
    assert json.loads(after["profile"])["reference"]["notes"] == "second run"
    assert after["refs"] == ["kept"] and after["project"] == first_capture["project"]


FAILING_RENAMES = {       # which folder rename fails, given (source, destination, the slug's screenshot folder)
    "set-aside": lambda src, dst, kept: src == kept and dst.name.startswith(".kept-old-"),
    "put-in-place": lambda src, dst, kept: (dst == kept and src.name.startswith(".kept-")
                                            and not src.name.startswith(".kept-old-")),
}


@pytest.mark.parametrize("step", FAILING_RENAMES)
def test_failed_folder_rename_keeps_the_earlier_profile_and_screenshots(
        fake_capture, first_capture, project, cache, monkeypatch, capsys, step):
    real, kept = os.rename, cache / "refs" / "kept"

    def rename(src, dst, *args, **kwargs):
        if FAILING_RENAMES[step](Path(src), Path(dst), kept):
            raise PermissionError(errno.EACCES, "renaming is not allowed here", str(src))
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", rename)
    assert second_capture(fake_capture, project) == 2
    assert "renaming is not allowed here" in capsys.readouterr().err
    assert stored(project, cache) == first_capture


@pytest.mark.parametrize("earlier", [True, False], ids=["replacing", "first-capture"])
def test_failed_profile_replace_puts_the_earlier_folder_back(
        fake_capture, project, cache, monkeypatch, capsys, earlier):
    before = None
    if earlier:
        assert run(project, "capture", URL, "--rights", "own", "--slug", "kept", "--notes", "first run") == 0
        before = stored(project, cache)
    real, out = os.replace, project / ".lapis" / "refs" / "kept.json"

    def replace(src, dst, *args, **kwargs):
        if Path(dst) == out:
            raise PermissionError(errno.EACCES, "the profile is locked", str(dst))
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)      # the folders are already swapped when this step fails
    assert second_capture(fake_capture, project) == 2
    assert "the profile is locked" in capsys.readouterr().err
    after = stored(project, cache)
    if earlier:
        assert after == before
    else:
        assert after["profile"] is None and after["shots"] == {} and after["refs"] == []
        assert after["project"] == [".lapis", ".lapis/refs"]


def test_exception_after_a_block_ends_the_run_as_blocked(fake_capture, project, cache, capsys):
    def after_capture(named, width):
        if width == 768:                                         # the block, then whatever the passes trip over
            named.blocked = blocked_navigation()
            raise KeyError("box the error page does not have")

    fake_capture.after_capture = after_capture
    assert run(project, "capture", URL, "--rights", "own", "--slug", "crashed", "--json") == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked" and "https://elsewhere.invalid/" in report["reason"]
    assert files(project) == [] and list((cache / "refs").iterdir()) == []


def test_exception_without_a_block_still_surfaces(fake_capture, project, cache):
    def after_capture(named, width):
        if width == 768:
            raise KeyError("a bug in a pass")

    fake_capture.after_capture = after_capture
    with pytest.raises(KeyError, match="a bug in a pass"):
        run(project, "capture", URL, "--rights", "own", "--slug", "crashed")
    assert files(project) == [] and list((cache / "refs").iterdir()) == []       # and nothing stays behind


def test_reference_reports_unreadable_database_without_fetching(fake_capture, project, tmp_path, capsys):
    (tmp_path / "lazuli.db").write_bytes(b"not a sqlite database")
    assert run(project, "capture", URL, "--rights", "reference-only", "--json") == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "error" and "database" in result["reason"]
    assert fake_capture.site.log == [] and files(project) == []


@pytest.mark.parametrize("pages, url, reason", [
    ({"https://ref.invalid/robots.txt": "User-agent: *\nDisallow: /work\n"}, URL, "robots.txt"),
    ({URL: net.Response(URL, 403, {"content-type": "text/html"}, b"<html>no</html>")}, URL, "403 Forbidden"),
    ({"https://ref.invalid/login": "<html><title>Sign in</title><input type=password></html>"},
     "https://ref.invalid/login", "sign-in"),
], ids=["robots-disallow", "403", "sign-in"])
def test_capture_stops_at_site_blocks(fake_capture, project, capsys, pages, url, reason):
    fake_capture.site.pages = pages
    assert run(project, "capture", url, "--rights", "reference-only", "--json") == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "blocked" and reason in result["reason"] and result["browser_link"] == url
    assert fake_capture.browser.opened == 0 and not fake_capture.loads
    assert files(project) == []


REGISTRY = [
    {"id": "closed-fonts", "name": "Closed Fonts", "url": "https://closed.invalid/", "type": ["font"],
     "access": "refused", "reason": "the terms forbid automated collection", "clause": "section 6.18",
     "terms_url": "https://closed.invalid/terms"},
    {"id": "gallery", "name": "Gallery", "url": "https://gallery.invalid/", "type": ["search"],
     "access": "browser-link", "reason": "its pages sit behind a sign-in"},
    {"id": "odd", "name": "Odd Source", "url": "https://odd.invalid/", "type": ["asset"], "access": "someday"},
    {"id": "ref", "name": "Ref", "url": "https://ref.invalid/", "type": ["search"], "access": "read"},
]


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(sources, "load_registry", lambda path=None: REGISTRY)


@pytest.mark.parametrize("command, url, lines, access", [
    ("capture", "https://closed.invalid/fonts/sans",
     ["Closed Fonts is `refused` in the source registry: the terms forbid automated collection",
      "terms: https://closed.invalid/terms (section 6.18)"], "refused"),
    ("capture", "https://gallery.invalid/shots/1",
     ["Gallery is `browser-link` in the source registry: its pages sit behind a sign-in"], "browser-link"),
    ("capture", "https://odd.invalid/a", ["Odd Source is `someday` in the source registry"], "someday"),
    ("system", "https://closed.invalid/tokens.json",
     ["Closed Fonts is `refused` in the source registry", "terms: https://closed.invalid/terms"], "refused"),
], ids=["refused", "browser-link", "unknown-access-fails-closed", "system-refused"])
def test_registry_refuses_before_any_request(fake_capture, registry, project, capsys, command, url, lines, access):
    assert run(project, command, url, "--rights", "reference-only") == 1
    out = capsys.readouterr().out
    assert all(line in out for line in lines) and f"open it in your browser: {url}" in out
    assert run(project, command, url, "--rights", "reference-only", "--json") == 1
    result = json.loads(capsys.readouterr().out)
    assert (result["status"], result["browser_link"], result["registry"]["access"]) == ("refused", url, access)
    assert fake_capture.site.log == []                      # not even robots.txt
    assert fake_capture.browser.opened == 0 and files(project) == []


def test_capture_launch_args_disable_proxies_and_keep_resolver_rules():
    rules = "MAP refused.test ~NOTFOUND"
    assert site._launch_args(rules) == [
        "--proxy-server=direct://", "--no-proxy-server", f"--host-resolver-rules={rules}"]


def test_host_resolver_rules_cover_all_refused_and_link_hosts(registry):
    rules, hosts = site._host_resolver_rules(sources.load_registry())
    assert hosts == {"closed.invalid", "gallery.invalid"}
    assert rules.split(", ") == [
        f"MAP {host} ~NOTFOUND"
        for host in ("closed.invalid", "closed.invalid.", "www.closed.invalid", "www.closed.invalid.",
                     "gallery.invalid", "gallery.invalid.", "www.gallery.invalid", "www.gallery.invalid.")
    ]


def test_host_resolver_rules_cover_real_registry():
    rules, hosts = site._host_resolver_rules(sources.load_registry())
    assert len(hosts) == 32
    assert len(rules.split(", ")) == 128
    assert "github.com" not in hosts


def test_host_resolver_rules_cover_aliases_and_strictest_host():
    rules, hosts = site._host_resolver_rules([
        {"url": "https://www.Allowed.Example/fonts", "hosts": ["WWW.Extra.Example."], "access": "read"},
        {"url": "https://allowed.example/other", "hosts": ["WWW.Extra.Example."], "access": "refused"},
    ])
    assert hosts == {"allowed.example", "extra.example"}
    assert "MAP www.extra.example. ~NOTFOUND" in rules.split(", ")


def test_malformed_capture_url_is_input_error(project, capsys):
    assert run(project, "capture", "http://[::1/x", "--rights", "own") == 2
    assert "Traceback" not in capsys.readouterr().out


def test_capture_stops_when_the_page_redirects_into_a_refused_source(fake_capture, registry, project, capsys):
    target = "https://closed.invalid/landing"
    fake_capture.site.pages[URL] = net.Response(URL, 302, {"location": target}, b"")
    assert run(project, "capture", URL, "--rights", "reference-only") == 1
    output = capsys.readouterr().out
    assert "the terms forbid automated collection" in output and target in output
    assert [url for url, _, _ in fake_capture.site.log] == ["https://ref.invalid/robots.txt", URL]
    assert fake_capture.browser.opened == 0 and files(project) == []


def test_capture_opens_only_the_final_preflight_url(fake_capture, registry, project):
    final = "https://ref.invalid/finished"
    fake_capture.site.pages[URL] = net.Response(URL, 302, {"location": final}, b"")
    fake_capture.site.pages[final] = "<html><title>Finished</title></html>"
    assert run(project, "capture", URL, "--rights", "own") == 0
    assert [entry["url"] for entry in fake_capture.loads] == [final] * 3
    assert [url for url, _, _ in fake_capture.site.log] == ["https://ref.invalid/robots.txt", URL, final]


def test_reference_only_capture_needs_text_to_sign(fake_capture, project, capsys):
    fake_capture.page_text = False
    assert run(project, "capture", URL, "--rights", "reference-only") == 1
    assert "no text at 390 px" in capsys.readouterr().out
    assert files(project) == []
    assert run(project, "capture", URL, "--rights", "licensed") == 0


# ------------------------------------------------------------------ profile IMAGE

BLUE, ORANGE = (0x22, 0x51, 0xCC), (0xE0, 0x70, 0x20)


def synthetic_image(path: Path) -> Path:
    """512 x 20: 256 px blue, 152 px orange, 52 px white, 52 px transparent; halving keeps edges exact."""
    image = Image.new("RGBA", (512, 20), (0, 0, 0, 0))
    for x0, x1, rgb in ((0, 256, BLUE), (256, 408, ORANGE), (408, 460, (255, 255, 255))):
        image.paste((*rgb, 255), (x0, 0, x1, 20))
    image.save(path)
    return path


def test_image_profile_palette(project, cache, tmp_path, capsys):
    image = synthetic_image(tmp_path / "Hero Shot.png")
    assert run(project, "profile", str(image), "--rights", "reference-only", "--json") == 0
    result = json.loads(capsys.readouterr().out)
    assert [item["field"] for item in result["omitted"]] == ["composition", "type_impressions", "similar_fonts"]
    out = project / ".lapis" / "refs" / "hero-shot.json"
    assert files(project) == [out]
    profile = json.loads(out.read_text(encoding="utf-8"))
    assert validate(profile) == []
    assert profile["source"] == {"kind": "image", "path": str(image)}
    copy = cache / "refs" / "hero-shot" / "image.png"
    assert profile["image"]["path"] == str(copy) and copy.read_bytes() == image.read_bytes()
    assert set(profile["image"]) == {"path", "palette"}          # no composition, impressions, or fonts
    palette = profile["image"]["palette"]
    # shares of the 460 covered pixels; the transparent strip counts for nothing
    assert [(item["share"], item.get("exact", False)) for item in palette] == [
        (round(256 / 460, 4), False), (round(152 / 460, 4), False), (round(52 / 460, 4), True)]
    for item, rgb in zip(palette, (BLUE, ORANGE, (255, 255, 255))):
        assert item["oklch"] == pytest.approx(to_oklch(f"rgb{rgb}"), abs=2e-3)
    assert run(project, "profile", str(image), "--rights", "reference-only") == 0
    assert json.loads(out.read_text(encoding="utf-8"))["image"]["palette"] == palette      # deterministic


# ------------------------------------------------------------------ system PATH_OR_URL

DTCG = {
    "color": {
        "$type": "color",
        "brand": {"$value": {"colorSpace": "srgb", "components": [0.1333, 0.3176, 0.8], "hex": "#2251CC"}},
        "surface": {"$value": "#FFFFFF"},
        "accent": {"$value": {"colorSpace": "oklch", "components": [0.7, 0.15, 40]}},
        "print": {"$value": {"colorSpace": "cmyk", "components": [0, 0, 0], "hex": "#15171A"}},
        "button": {
            "primary": {"$root": {"$value": "{color.brand}"},
                        "hover": {"$value": {"$ref": "#/color/accent/$value"}},
                        "focusVisible": {"$value": "{color.accent}"}},
            "primary-disabled": {"$value": "{color.surface}"},
        },
    },
    "font": {"size": {"$type": "dimension", "body": {"$value": {"value": 1, "unit": "rem"}}}},
    "typography": {
        "$type": "typography",
        "caption": {"$value": {"fontFamily": "Inter", "fontSize": {"value": 12.8, "unit": "px"}}},
        "body-md": {"$value": {"fontFamily": "Inter", "fontSize": "{font.size.body}"}},
        "h3": {"$value": {"fontFamily": "Inter", "fontSize": {"value": 20, "unit": "px"}}},
        "h2": {"$value": {"fontFamily": "Inter", "fontSize": {"value": 25, "unit": "px"}}},
        "h1": {"$value": {"fontFamily": "Inter", "fontSize": {"value": 31.25, "unit": "px"}}},
        "quote": {"$value": {"fontFamily": "Inter", "fontSize": {"value": 1.2, "unit": "em"}}},
    },
}


def load_profile(project: Path, name: str) -> dict:
    profile = json.loads((project / ".lapis" / "refs" / f"{name}.json").read_text(encoding="utf-8"))
    assert validate(profile) == []
    return profile


def test_system_from_dtcg_tokens(project, tmp_path, capsys):
    tokens = tmp_path / "acme" / "tokens.json"
    tokens.parent.mkdir()
    tokens.write_text(json.dumps(DTCG), encoding="utf-8")
    assert run(project, "system", str(tokens), "--rights", "reference-only", "--json") == 0
    assert json.loads(capsys.readouterr().out)["summary"]["skipped"] == ["typography.quote (font size)"]   # em
    system = load_profile(project, "acme-tokens")["system"]
    assert system["tokens_path"] == str(tokens)
    assert system["type_scale"] == {"base_px": 16.0, "ratio": 1.25, "steps_px": [12.8, 16.0, 20.0, 25.0, 31.25]}
    roles = {role["role"]: role["oklch"] for role in system["color_roles"]}
    assert list(roles) == ["color.brand", "color.surface", "color.accent", "color.print", "color.button.primary",
                           "color.button.primary.hover", "color.button.primary.focusVisible",
                           "color.button.primary-disabled"]
    assert roles["color.brand"] == pytest.approx(to_oklch("rgb(34 81 204)"), abs=2e-3)
    assert roles["color.accent"] == [0.7, 0.15, 40.0]
    assert roles["color.print"] == pytest.approx(to_oklch("rgb(21 23 26)"), abs=1e-4)      # hex fallback
    assert roles["color.button.primary"] == roles["color.brand"]                            # alias
    assert roles["color.button.primary.hover"] == roles["color.accent"]                     # $ref
    assert system["states"] == ["color.button.primary: disabled, focus-visible, hover"]


GOOGLE_MD = """---
version: alpha
name: Acme
colors:
  primary: "#2251CC"
  primary-hover: "{colors.accent}"
  accent: "oklch(0.7 0.15 40)"
  on-surface: "#15171A"
  mystery: "rebeccapurple"
typography:
  body-md: {fontFamily: Inter, fontSize: 1rem}
  body-lg: {fontFamily: Inter, fontSize: 18px}
  headline: {fontFamily: Inter, fontSize: 2rem}
components:
  button-primary: {backgroundColor: "{colors.primary}"}
  button-primary-hover: {backgroundColor: "{colors.accent}"}
  button-primary-disabled: {backgroundColor: "{colors.on-surface}"}
---
## Overview
The prose explains intent; the tokens above are the contract.
"""


def test_system_from_google_design_md(project, tmp_path, capsys):
    design = tmp_path / "acme" / "DESIGN.md"
    design.parent.mkdir()
    design.write_text(GOOGLE_MD, encoding="utf-8")
    assert run(project, "system", str(design), "--rights", "licensed", "--json") == 0
    summary = json.loads(capsys.readouterr().out)["summary"]
    assert summary["format"] == "google" and summary["skipped"] == ["colors.mystery"]
    profile = load_profile(project, "acme-design")
    assert "notes" not in profile["reference"]
    system = profile["system"]
    assert system["type_scale"] == {"base_px": 16.0, "ratio": 1.451, "steps_px": [16.0, 18.0, 32.0]}
    roles = {role["role"]: role["oklch"] for role in system["color_roles"]}
    assert list(roles) == ["primary", "primary-hover", "accent", "on-surface"]
    assert roles["primary-hover"] == roles["accent"] == [0.7, 0.15, 40.0]
    assert system["states"] == ["colors.primary: hover", "components.button-primary: disabled, hover"]


STITCH_MD = """# Acme

## Visual Theme & Atmosphere
Calm and exact.

## Color Palette & Roles
- **Primary Blue** (#2251CC): main actions
- Warm accent `#E07020` for highlights
| Surface | #FFFFFF | page |
A long descriptive sentence that runs on for a while before the color #111111 finally appears.

## Typography Rules
A modular scale with a ratio of 1.25.
- Display: 48px, line-height 56px
- Body: 16px / 1.5, letter-spacing 0.2px

### Headings
Second-level headings at 2rem.

## Component Stylings
Buttons show a hover tint and a visible focus ring; disabled buttons fade.

## Layout Principles
Twelve columns.
"""
OPENDESIGN_MD = STITCH_MD.replace("## Visual", "## 1. Visual").replace("## Color", "## 2. Color") \
    .replace("## Typography Rules", "## 3. Typography").replace("## Component Stylings", "## 5. Components") \
    .replace("## Layout Principles", "## 4. Layout & Spacing")


@pytest.mark.parametrize("text, dialect", [(STITCH_MD, "stitch-legacy"), (OPENDESIGN_MD, "opendesign")])
def test_system_from_prose_design_md_gives_candidates(project, tmp_path, text, dialect):
    design = tmp_path / "prose.md"
    design.write_text(text, encoding="utf-8")
    assert run(project, "system", str(design), "--rights", "reference-only") == 0
    profile = load_profile(project, "prose")
    assert dialect in profile["reference"]["notes"] and "candidates for review" in profile["reference"]["notes"]
    system = profile["system"]
    assert [role["role"] for role in system["color_roles"]] == ["primary-blue", "warm-accent", "surface", "color-4"]
    # stated ratio wins; line height and letter spacing are not font sizes
    assert system["type_scale"] == {"base_px": 16.0, "ratio": 1.25, "steps_px": [16.0, 32.0, 48.0]}
    assert system["states"] == ["component prose mentions: disabled, focus, hover"]
    assert "calm" not in json.dumps(profile).lower()                  # no prose is quoted


def test_system_from_url_goes_through_the_polite_fetcher(fake_capture, project):
    url = "https://ref.invalid/tokens.json?v=3"
    fake_capture.site.pages = {url: json.dumps(DTCG)}
    assert run(project, "system", url, "--rights", "reference-only") == 0
    profile = load_profile(project, "ref-invalid-tokens-json")
    assert profile["source"] == {"kind": "system", "url": "https://ref.invalid/tokens.json"}
    assert "tokens_path" not in profile["system"]
    assert [u for u, _, _ in fake_capture.site.log] == ["https://ref.invalid/robots.txt", url]
    fake_capture.site.pages = {"https://ref.invalid/robots.txt": "User-agent: lazuli\nDisallow: /\n"}
    assert run(project, "system", "https://ref.invalid/other.json", "--rights", "reference-only") == 1


@pytest.mark.parametrize("name, text", [
    ("notes.md", "# Notes\n\nSome thoughts about #2251CC and 16px.\n"),
    ("empty.json", json.dumps({"color": {"brand": {"value": "#2251CC"}}})),
], ids=["unknown-dialect", "no-dtcg-tokens"])
def test_system_refuses_to_guess(project, tmp_path, capsys, name, text):
    source = tmp_path / name
    source.write_text(text, encoding="utf-8")
    assert run(project, "system", str(source), "--rights", "own") == 2
    assert capsys.readouterr().err
    assert files(project) == []


@pytest.mark.parametrize("argv", [
    ["profile", "missing.png", "--rights", "own"],
    ["system", "missing.json", "--rights", "own"],
    ["profile", "image.png", "--rights", "own", "--project", "no-such-folder"],
], ids=["missing-image", "missing-tokens", "missing-project"])
def test_missing_input_exits_2(project, monkeypatch, argv):
    monkeypatch.chdir(project)
    Image.new("RGB", (4, 4)).save(project / "image.png")
    assert ref.main(argv) == 2


def test_rights_are_required(project):
    with pytest.raises(SystemExit) as exit_:
        ref.main(["system", "tokens.json", "--project", str(project)])
    assert exit_.value.code == 2


@pytest.mark.parametrize("slug", ["kept\n", "kept ", "Kept", "-kept", "k" * 65])
def test_slug_must_match_whole(project, slug):
    with pytest.raises(SystemExit) as exit_:
        ref.main(["system", "tokens.json", "--rights", "own", "--slug", slug, "--project", str(project)])
    assert exit_.value.code == 2
    assert files(project) == []


# ------------------------------------------------------------------ capture in Chromium

@pytest.fixture
def real_browser(monkeypatch, browser):
    """Launch with current registry DNS rules once local fixtures have installed their policies."""
    @contextlib.contextmanager
    def open_browser():
        rules, _ = site._host_resolver_rules(sources.load_registry())
        isolated = browser.browser_type.launch(args=site._launch_args(rules))
        try:
            yield isolated
        finally:
            isolated.close()

    monkeypatch.setattr(site, "_open_browser", open_browser)
    monkeypatch.setattr(net, "_sleep", lambda seconds: None)

@pytest.fixture
def fake_proxy():
    from socketserver import BaseRequestHandler, ThreadingTCPServer
    from threading import Thread

    requests = []

    class Proxy(ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    class Handler(BaseRequestHandler):
        def handle(self):
            self.request.settimeout(5)
            line = self.request.makefile("rb").readline().decode("ascii", errors="replace").strip()
            requests.append(line)

    server = Proxy(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(url=f"http://127.0.0.1:{server.server_address[1]}", requests=requests)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture
def proxied_browser(monkeypatch, browser, capture_server, fake_proxy):
    """Pass proxy variables to Chromium itself, not the already-running Playwright driver."""
    registry = sources.load_registry()
    monkeypatch.setattr(sources, "load_registry", lambda path=None: [
        *registry, {"id": "refused-test", "url": "https://refused.test/", "access": "refused"}])
    environment = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        environment[key] = fake_proxy.url
    for key in ("NO_PROXY", "no_proxy"):
        environment.pop(key, None)

    @contextlib.contextmanager
    def open_browser():
        rules, _ = site._host_resolver_rules(sources.load_registry())
        isolated = browser.browser_type.launch(args=site._launch_args(rules), env=environment)
        try:
            yield isolated
        finally:
            isolated.close()

    monkeypatch.setattr(site, "_open_browser", open_browser)
    monkeypatch.setattr(net, "_sleep", lambda seconds: None)


def test_page_redirects_cannot_reach_refused_host_via_environment_proxy(
        proxied_browser, capture_server, fake_proxy, project):
    capture_server.html = (
        "<html><body>Reference page"
        "<img src='https://refused.test/x.png'>"
        "<iframe src='http://refused.test/'></iframe>"
        "<img src='/redirect-http'>"
        "<img src='/redirect-https'>"
        "</body></html>"
    )
    capture_server.redirects.update({
        "/redirect-http": "http://refused.test/",
        "/redirect-https": "https://refused.test/",
    })
    assert run(project, "capture", capture_server.url + "/page", "--rights", "own",
               "--slug", "no-proxy") == 0
    assert sum(path == "/redirect-http" for _, path, _ in capture_server.seen) == 3
    assert sum(path == "/redirect-https" for _, path, _ in capture_server.seen) == 3
    assert fake_proxy.requests == []


@pytest.mark.parametrize("credentialed", [False, True])
def test_browser_redirect_is_blocked_before_the_other_host_is_requested(real_browser, project, capsys, credentialed):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    seen = []

    class RedirectSite(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.headers["Host"], self.path))
            if self.path == "/robots.txt":
                self.send_response(200)
                body = b"User-agent: *\nAllow: /\n"
            elif self.path == "/page" and sum(path == "/page" for _, path in seen) == 1:
                self.send_response(200)                  # preflight
                body = b"<html><body>Preflight page</body></html>"
            elif self.path == "/page":
                self.send_response(302)                  # browser navigation
                host = "user:password@localhost" if credentialed else "localhost"
                self.send_header("Location", f"http://{host}:{self.server.server_port}/landing")
                body = b""
            else:
                self.send_response(200)
                body = b"<html><body>Should not be fetched</body></html>"
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectSite)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        target = f"http://localhost:{server.server_port}/landing"
        original = f"http://127.0.0.1:{server.server_port}/page"
        assert run(project, "capture", original, "--rights", "own", "--json") == 1
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "blocked"
        if credentialed:
            assert result["browser_link"] == original and "credentials" in result["reason"]
            assert "password" not in json.dumps(result)
        else:
            assert result["browser_link"] == target
            assert target in result["reason"] and "not preflighted" in result["reason"]
        assert [path for _, path in seen] == ["/robots.txt", "/page", "/page"]
        assert all(host.startswith("127.0.0.1:") for host, _ in seen)
        assert files(project) == []
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture
def malformed_redirect_server():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    state = SimpleNamespace(seen=[], browser_only=False)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state.seen.append(self.path)
            if self.path == "/robots.txt":
                body = b"User-agent: *\nAllow: /\n"
                self.send_response(200)
            elif self.path == "/page" and (not state.browser_only or state.seen.count("/page") > 1):
                body = b""
                self.send_response(302)
                self.send_header("Location", "http://[::1/x")
            else:
                body = b"<html><body>Browser page</body></html>"
                self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        state.url = f"http://127.0.0.1:{server.server_port}/page"
        yield state
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_preflight_malformed_main_redirect_is_blocked(malformed_redirect_server, project, capsys):
    assert run(project, "capture", malformed_redirect_server.url, "--rights", "own", "--json") == 1
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["status"] == "blocked"
    assert "redirect URL is malformed; request not sent" in result["reason"]
    assert "Traceback" not in output.out + output.err
    assert malformed_redirect_server.seen == ["/robots.txt", "/page"]


def test_browser_malformed_main_redirect_is_blocked(
        real_browser, malformed_redirect_server, project, capsys):
    malformed_redirect_server.browser_only = True

    def too_slow(signum, frame):
        raise AssertionError("browser navigation did not finish within 45 seconds")

    previous_handler = signal.signal(signal.SIGALRM, too_slow)
    signal.alarm(45)
    try:
        exit_code = run(project, "capture", malformed_redirect_server.url, "--rights", "own", "--json")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
    output = capsys.readouterr()
    assert exit_code == 1
    result = json.loads(output.out)
    assert result["status"] == "blocked"
    assert result["reason"] == "main-frame redirect URL is malformed; request not sent"
    assert "Traceback" not in output.out + output.err
    assert malformed_redirect_server.seen == ["/robots.txt", "/page", "/page"]


@pytest.mark.parametrize("proxies, mentions_proxy", [
    ({}, False), ({"ftp": "http://127.0.0.1:1"}, False),
    ({"http": "http://127.0.0.1:1"}, True), ({"https": "http://127.0.0.1:1"}, True),
])
def test_browser_load_failure_mentions_proxy_only_when_configured(monkeypatch, proxies, mentions_proxy):
    from playwright.sync_api import Error as PlaywrightError

    monkeypatch.setattr(site, "getproxies", lambda: proxies, raising=False)
    allowed = "https://example.test/page"
    named = site._NamedBrowser(FakeBrowser(), allowed, allowed)
    page = SimpleNamespace()
    frame = SimpleNamespace(parent_frame=None, page=page)
    request = SimpleNamespace(frame=frame, url=allowed, is_navigation_request=lambda: True)

    def unavailable(**kwargs):
        raise PlaywrightError("synthetic network failure")

    route = SimpleNamespace(request=request, fetch=unavailable, abort=lambda reason: None)
    named._route(route, SimpleNamespace(pages=[page]))
    assert named.load_error is not None
    assert ("proxy" in str(named.load_error)) is mentions_proxy
    assert "synthetic network failure" in str(named.load_error)


def test_reference_only_capture_of_a_local_page(real_browser, render_server, project, cache):
    fixture = (Path(__file__).parent / "fixtures" / "render" / "visual-fields.html").read_text(encoding="utf-8")
    copy = ["Striped mountain", "Mountain with overlay", "Gradient text", "Continue"]
    assert all(text in fixture for text in copy)
    assert run(project, "capture", f"{render_server}/visual-fields.html", "--rights", "reference-only",
               "--slug", "visual") == 0
    out = project / ".lapis" / "refs" / "visual.json"
    assert files(project) == [out]
    written = out.read_text(encoding="utf-8")
    assert not any(text in written for text in copy)
    profile = json.loads(written)
    assert validate(profile) == []
    assert profile["source"]["kind"] == "site" and profile["reference"]["captured_by"] == "user-request"
    assert [vp["width"] for vp in profile["viewports"]] == [390, 768, 1440]
    for vp in profile["viewports"]:
        assert "screenshot" not in vp and len(vp["text_sig"]) == 1024
        assert vp["text"] and all("text" not in r and len(r["text_sig"]) == 128 for r in vp["text"])
        media = [b["media"] for b in vp["boxes"] if "media" in b]
        assert any("phash" in m for m in media) and not any("alt" in m for m in media)
        a11y = [b["a11y"] for b in vp["boxes"] if "a11y" in b]
        assert any(a.get("name_source") in ("alt", "aria-label") for a in a11y)       # names existed ...
        assert not any("name" in a for a in a11y)                                     # ... and were not kept
    assert sorted(p.name for p in files(cache / "refs" / "visual")) == ["1440.png", "390.png", "768.png"]


def test_own_capture_keeps_text_and_names_the_cached_screenshots(real_browser, render_server, project, cache):
    assert run(project, "capture", f"{render_server}/light.html", "--rights", "own", "--slug", "light") == 0
    profile = load_profile(project, "light")
    for vp in profile["viewports"]:
        assert {r["text"] for r in vp["text"]} >= {"Light only", "Readable content."}
        shot = Path(vp["screenshot"])
        assert shot.parent == cache / "refs" / "light" and shot.read_bytes()[:4] == b"\x89PNG"
    assert [p.name for p in (cache / "refs").iterdir()] == ["light"]         # no staging folder left behind
    assert [p.name for p in files(cache / "refs")] == ["1440.png", "390.png", "768.png"]


@pytest.fixture
def capture_server(monkeypatch):
    """A single loopback listener exposes two hostname policies without external traffic."""
    import base64
    import hashlib
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from io import BytesIO
    from threading import Thread

    png = BytesIO()
    Image.new("RGB", (24, 24), "blue").save(png, format="PNG")
    state = SimpleNamespace(seen=[], request_headers=[], html="<html><body>Reference page</body></html>",
                            pages={}, redirects={}, redirect_status={}, denied_access="refused")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state.seen.append((self.headers["Host"], self.path, self.headers.get("Upgrade")))
            state.request_headers.append((self.headers["Host"], self.path,
                                          self.headers.get("Authorization"), self.headers.get("Cookie")))
            if self.headers.get("Upgrade", "").lower() == "websocket":
                accept = base64.b64encode(hashlib.sha1(
                    (self.headers["Sec-WebSocket-Key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                ).digest()).decode()
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()
                return
            if self.path in state.redirects:
                self.send_response(state.redirect_status.get(self.path, 302))
                self.send_header("Location", state.redirects[self.path])
                body, content_type = b"", "text/plain"
            elif self.path == "/robots.txt":
                body, content_type = b"User-agent: *\nAllow: /\n", "text/plain"
                self.send_response(200)
            elif self.path == "/img.png":
                body, content_type = png.getvalue(), "image/png"
                self.send_response(200)
            else:
                body, content_type = state.pages.get(self.path, state.html).encode(), "text/html"
                self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


        def do_POST(self):
            self.do_GET()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_port}"
    state.localhost = f"http://localhost:{server.server_port}"
    monkeypatch.setattr(sources, "load_registry", lambda path=None: [
        {"id": "loopback", "url": state.url, "access": "read"},
        {"id": "denied", "url": state.localhost, "access": state.denied_access, "reason": "test refusal"},
    ])
    try:
        yield state
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.parametrize("scheme", ["http", "HTTP"])
def test_browser_captures_bare_loopback_url(real_browser, capture_server, project, scheme):
    assert run(project, "capture", f"{scheme}://127.0.0.1:{capture_server.url.rsplit(':', 1)[1]}",
               "--rights", "own", "--slug", "bare") == 0
    assert {vp["width"] for vp in load_profile(project, "bare")["viewports"]} == {390, 768, 1440}


def test_browser_captures_page_with_quote_in_query(real_browser, capture_server, project):
    assert run(project, "capture", capture_server.url + "/?q=it's", "--rights", "own",
               "--slug", "quote") == 0
    assert [path for _, path, _ in capture_server.seen] == [
        "/robots.txt", "/?q=it%27s", "/?q=it%27s", "/?q=it%27s", "/?q=it%27s"]


@pytest.mark.parametrize("access", ["refused", "browser-link"])
def test_browser_refuses_one_image_once_across_widths(real_browser, capture_server, project, access):
    capture_server.denied_access = access
    capture_server.html = (f"<html><body>Reference page"
                           f"<img src='{capture_server.localhost}/blocked.png'></body></html>")
    assert run(project, "capture", capture_server.url + "/page", "--rights", "own", "--slug", "one") == 0
    assert not any(host.startswith("localhost:") for host, _, _ in capture_server.seen)
    assert sum(path == "/robots.txt" for _, path, _ in capture_server.seen) == 1
    assert load_profile(project, "one")["reference"]["notes"] == (
        "at least 1 page requests to refused or browser-link hosts were blocked")


def test_browser_refuses_image_and_redirect_into_denied_host(real_browser, capture_server, project):
    capture_server.html = (f"<html><body>Reference page<img src='{capture_server.localhost}/blocked.png'>"
                           f"<img src='{capture_server.url}/redirect.png'>"
                           "<img src='/allowed.png'></body></html>")
    capture_server.redirects["/redirect.png"] = capture_server.localhost + "/redirected.png"
    capture_server.redirects["/allowed.png"] = capture_server.url + "/img.png"
    assert run(project, "capture", capture_server.url + "/page", "--rights", "own", "--slug", "blocked") == 0
    assert not any(host.startswith("localhost:") for host, _, _ in capture_server.seen)
    assert sum(path == "/redirect.png" for _, path, _ in capture_server.seen) == 3
    assert not any(path in ("/blocked.png", "/redirected.png") for _, path, _ in capture_server.seen)
    assert sum(path == "/img.png" for _, path, _ in capture_server.seen) == 3
    profile = load_profile(project, "blocked")
    assert all(any(box.get("media", {}).get("loaded") for box in vp["boxes"]) for vp in profile["viewports"])
    assert profile["reference"]["notes"] == (
        "at least 2 page requests to refused or browser-link hosts were blocked")


def test_browser_blocks_frame_and_websocket_but_connects_allowed_socket(real_browser, capture_server, project):
    capture_server.html = (
        "<html><body>Reference page"
        f"<iframe src='{capture_server.localhost}/frame'></iframe>"
        "<script>"
        f"new WebSocket('ws://localhost:{capture_server.url.rsplit(':', 1)[1]}/blocked');"
        f"new WebSocket('ws://127.0.0.1:{capture_server.url.rsplit(':', 1)[1]}/allowed');"
        "</script></body></html>"
    )
    assert run(project, "capture", capture_server.url + "/page", "--rights", "own", "--slug", "frame") == 0
    assert not any(host.startswith("localhost:") for host, _, _ in capture_server.seen)
    assert sum(path == "/allowed" and upgrade == "websocket" for _, path, upgrade in capture_server.seen) == 3
    assert not any(path in ("/frame", "/blocked") for _, path, _ in capture_server.seen)
    assert load_profile(project, "frame")["reference"]["notes"] == (
        "at least 1 page requests to refused or browser-link hosts were blocked")


def test_browser_stops_unsupported_redirects_before_next_hop(real_browser, capture_server, project):
    capture_server.html = "<html><body>Reference page<img src='/hop0'></body></html>"
    capture_server.redirects.update({f"/hop{hop}": f"/hop{hop + 1}" for hop in range(5)})
    capture_server.redirects["/hop5"] = capture_server.localhost + "/hop6"
    assert run(project, "capture", capture_server.url + "/page", "--rights", "own",
               "--slug", "limits") == 0
    assert all(sum(path == f"/hop{hop}" for _, path, _ in capture_server.seen) == 3 for hop in range(6))
    assert not any(host.startswith("localhost:") for host, _, _ in capture_server.seen)
    assert load_profile(project, "limits")["reference"]["notes"] == (
        "at least 1 page requests to refused or browser-link hosts were blocked")


@pytest.fixture
def corsless_server():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"cross-origin private answer"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.parametrize("redirect", [False, True], ids=["direct", "same-origin-redirect"])
def test_page_cannot_read_cross_origin_corsless_response(real_browser, capture_server, corsless_server,
                                                         project, redirect):
    target = corsless_server + "/private"
    if redirect:
        capture_server.redirects["/via"] = target
        target = "/via"
    capture_server.html = (
        "<html><body>Reference page<div id='answer'>pending</div><script>"
        f"fetch({json.dumps(target)}).then(r => r.text()).then(text => answer.textContent = text)"
        ".catch(() => answer.textContent = 'CORS blocked');"
        "</script></body></html>"
    )
    assert run(project, "capture", capture_server.url + "/page", "--rights", "own",
               "--slug", "cors") == 0
    text = [item["text"] for vp in load_profile(project, "cors")["viewports"] for item in vp["text"]]
    assert "cross-origin private answer" not in text
    assert "CORS blocked" in text


def test_unreachable_image_does_not_abort_capture(real_browser, capture_server, project):
    capture_server.html = "<html><body>Reference page<img src='http://127.0.0.1:1/x.png'></body></html>"
    assert run(project, "capture", capture_server.url + "/page", "--rights", "own",
               "--slug", "unreachable") == 0

@pytest.mark.parametrize("prefetch", [
    '<script type="speculationrules">{"prefetch":[{"source":"list","urls":["/other"]}]}</script>',
    '<link rel="prefetch" href="/other">',
], ids=["speculationrules", "link-prefetch"])
def test_prefetched_main_document_is_blocked(
        real_browser, capture_server, project, cache, capsys, prefetch):
    capture_server.pages["/page"] = (
        f"<html><head>{prefetch}</head><body>Named document"
        "<script>setTimeout(() => { location.href = '/other'; }, 300)</script></body></html>"
    )
    capture_server.pages["/other"] = "<html><body>Unvetted second document</body></html>"

    assert run(project, "capture", capture_server.url + "/page", "--rights", "own",
               "--slug", "prefetched", "--json") == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert "Unvetted second document" not in json.dumps(report)
    assert files(project) == []
    assert files(cache / "refs") == []                       # nothing of the run stays in the cache
    assert any(path == "/other" for _, path, _ in capture_server.seen)


@pytest.mark.parametrize("threshold, reached", [(600, 2), (1000, 3)], ids=["at-768", "at-1440"])
def test_capture_blocked_at_a_later_width_leaves_no_screenshot(
        real_browser, capture_server, project, cache, capsys, threshold, reached):
    # The narrow widths pass; the wide one starts a navigation that is aborted after the document check.
    capture_server.pages["/page"] = (
        "<html><body>Named document<script>"
        f"if (innerWidth > {threshold}) setTimeout(() => {{ location.href = '/other'; }}, 100);"
        "</script></body></html>"
    )
    assert run(project, "capture", capture_server.url + "/page", "--rights", "own",
               "--slug", "later", "--json") == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked" and f"{capture_server.url}/other" in report["reason"]
    assert [path for _, path, _ in capture_server.seen] == ["/robots.txt", "/page"] + ["/page"] * reached
    assert files(project) == [] and files(cache / "refs") == []
    assert not list((cache / "refs").glob(".*"))                 # no staging folder either


def test_capture_blocked_after_the_field_passes_leaves_no_screenshot(
        real_browser, capture_server, project, cache, capsys, monkeypatch):
    from lapis_design.render import capture as render_capture

    apply_fields = render_capture.apply_fields

    def navigate_after_the_fields(view, vp):
        apply_fields(view, vp)
        if vp["width"] == 768:                                   # after the shot and every read of the page
            view.page.evaluate("location.href = '/other'")
            view.page.wait_for_timeout(300)

    monkeypatch.setattr(render_capture, "apply_fields", navigate_after_the_fields)
    assert run(project, "capture", capture_server.url + "/page", "--rights", "own",
               "--slug", "late", "--json") == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert [path for _, path, _ in capture_server.seen] == ["/robots.txt", "/page", "/page", "/page"]
    assert files(project) == [] and files(cache / "refs") == []
    assert not list((cache / "refs").glob(".*"))


def test_capture_blocked_before_the_field_passes_is_a_block_not_a_traceback(
        real_browser, capture_server, project, cache, capsys, monkeypatch):
    from lapis_design.render import capture as render_capture

    apply_fields = render_capture.apply_fields

    def navigate_before_the_fields(view, vp):
        if vp["width"] == 768:                                   # the last document check has passed; the
            view.page.evaluate("location.href = '/other'")       # aborted navigation leaves Chromium's error page
            view.page.wait_for_timeout(300)
        apply_fields(view, vp)

    monkeypatch.setattr(render_capture, "apply_fields", navigate_before_the_fields)
    assert run(project, "capture", capture_server.url + "/page", "--rights", "own",
               "--slug", "early", "--json") == 1
    output = capsys.readouterr()
    assert "Traceback" not in output.out + output.err
    report = json.loads(output.out)
    assert report["status"] == "blocked" and f"{capture_server.url}/other" in report["reason"]
    assert files(project) == [] and files(cache / "refs") == []
    assert not list((cache / "refs").glob(".*"))


def test_capture_checks_the_document_again_after_the_screenshot_and_field_passes(
        browser, render_server, tmp_path, monkeypatch):
    from lapis_design.render import capture as render_capture

    shot = tmp_path / "shot.png"
    fields = []
    apply_fields = render_capture.apply_fields

    def recording_apply_fields(view, vp):
        apply_fields(view, vp)
        fields.append(True)

    monkeypatch.setattr(render_capture, "apply_fields", recording_apply_fields)
    checks = []                                               # (screenshot exists, fields applied) at each check
    config = {"width": 390, "layout_height": 844, "height": 844, "theme": "light", "reduced_motion": False,
              "browser_chrome": False, "dpr": 2}
    render_capture.capture(browser, f"{render_server}/light.html", config, shot, bytes(range(32)),
                           check_document=lambda page: checks.append((shot.exists(), bool(fields))))
    assert checks[-1] == (True, True)                          # the last check sees the screenshot and the fields
    assert len(checks) > 1 and set(checks[:-1]) == {(False, False)}


def test_history_url_change_keeps_the_same_capture_document(real_browser, capture_server, project, cache):
    capture_server.pages["/page"] = (
        "<html><body>Named document"
        "<script>history.replaceState(null, '', '/page?from=home')</script></body></html>"
    )
    assert run(project, "capture", capture_server.url + "/page", "--rights", "own",
               "--slug", "same-document") == 0
    profile = load_profile(project, "same-document")
    assert {vp["width"] for vp in profile["viewports"]} == {390, 768, 1440}
    assert all("Named document" in {text["text"] for text in vp["text"]} for vp in profile["viewports"])
    assert sorted(p.name for p in files(cache / "refs" / "same-document")) == [
        "1440.png", "390.png", "768.png"]


def test_popup_can_navigate_twice_without_blocking_main_page(real_browser, capture_server, project):
    capture_server.html = (
        "<html><body>Reference page<script>"
        "if(location.pathname === '/page') {"
        "const popup = window.open('/popup0');"
        "setTimeout(() => { if (popup) popup.location='/popup1'; }, 100);"
        "setTimeout(() => { if (popup) popup.location='/popup2'; }, 200);"
        "}</script></body></html>"
    )
    assert run(project, "capture", capture_server.url + "/page", "--rights", "own",
               "--slug", "popup") == 0
    assert sum(path == "/popup2" for _, path, _ in capture_server.seen) == 3


def test_capture_normalizes_braces_in_path(real_browser, capture_server, project):
    assert run(project, "capture", capture_server.url + "/a{b}", "--rights", "own",
               "--slug", "braces") == 0
    assert any(path == "/a%7Bb%7D" for _, path, _ in capture_server.seen)


def test_peer_connections_send_no_stun_packet(real_browser, capture_server, project):
    import socket

    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(0.3)
    try:
        capture_server.html = (
            "<html><body>Reference page<script>"
            "try { const pc = new RTCPeerConnection({iceServers: [{urls: "
            f"'stun:127.0.0.1:{receiver.getsockname()[1]}'"
            "}]}); pc.createDataChannel('check');"
            "pc.createOffer().then(offer => pc.setLocalDescription(offer)); } catch(e) {}"
            "</script></body></html>"
        )
        assert run(project, "capture", capture_server.url + "/page", "--rights", "own",
                   "--slug", "webrtc") == 0
        with pytest.raises(socket.timeout):
            receiver.recvfrom(2048)
    finally:
        receiver.close()


@pytest.mark.parametrize("given, vetted, expected", [
    ("https://public.example/page", "https://public.example/page", None),
    ("https://public.example/page", "http://127.0.0.1:7777/page", None),
    ("http://localhost:7777/page", "http://127.0.0.1:7777/page", "http://127.0.0.1:7777"),
])
def test_only_user_named_loopback_page_gets_network_permission(given, vetted, expected):
    named = site._NamedBrowser(FakeBrowser(), vetted, given)
    assert named._loopback_origin == expected


