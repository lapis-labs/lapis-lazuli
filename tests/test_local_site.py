"""A local HTML file is served from its folder on loopback while a check runs, and from nowhere else."""
from __future__ import annotations

import http.client
import socket
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from lapis_design import local_site
from lapis_design.behavior_check import main as behavior_main
from lapis_design.render import main as render_main

OUTSIDE = "outside secret"


def request(base: str, path: str, method: str = "GET") -> tuple[int, dict[str, str], bytes]:
    """One request straight to the server (no proxy settings), the path sent as written."""
    parts = urlsplit(base)
    connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def refuses_connections(base: str) -> bool:
    parts = urlsplit(base)
    try:
        socket.create_connection((parts.hostname, parts.port), timeout=2).close()
    except ConnectionRefusedError:
        return True
    return False


@pytest.fixture
def site(tmp_path: Path) -> Path:
    """A page folder beside a file that is not part of the page, with every way out a request could try."""
    (tmp_path / "secret.txt").write_text(OUTSIDE)
    folder = tmp_path / "page"
    (folder / "sub").mkdir(parents=True)
    (folder / "empty").mkdir()
    (folder / ".git").mkdir()
    (folder / "index.html").write_text("<h1>home</h1>")
    (folder / "app.css").write_text("h1{}")
    (folder / "sub" / "index.html").write_text("<h1>sub</h1>")
    (folder / ".env").write_text("TOKEN=1")
    (folder / ".git" / "config").write_text("[core]")
    try:
        (folder / "link-in.txt").symlink_to(folder / "app.css")
        (folder / "link-out.txt").symlink_to(tmp_path / "secret.txt")
        (folder / "link-dir").symlink_to(tmp_path, target_is_directory=True)
        (folder / "link-hidden.txt").symlink_to(folder / ".env")
    except OSError:
        pytest.skip("this system cannot create symbolic links")
    return folder


def test_the_folder_is_served_and_the_run_starts_at_the_file(site: Path):
    with local_site.serve(site.joinpath("index.html").as_uri()) as url:
        parts = urlsplit(url)
        assert (parts.scheme, parts.hostname, parts.path) == ("http", "127.0.0.1", "/index.html")
        base = f"http://127.0.0.1:{parts.port}"
        status, headers, body = request(base, "/index.html")
        assert (status, body) == (200, b"<h1>home</h1>") and headers["Content-Type"] == "text/html"
        assert request(base, "/app.css")[2] == b"h1{}" and request(base, "/app.css")[1]["Content-Type"] == "text/css"
        assert request(base, "/")[2] == b"<h1>home</h1>"                        # a folder answers with its index
        assert request(base, "/sub/")[2] == b"<h1>sub</h1>"
        status, headers, _ = request(base, "/sub")                              # relative links need the slash
        assert (status, headers["Location"]) == (301, "/sub/")
        status, headers, body = request(base, "/index.html", "HEAD")
        assert (status, headers["Content-Length"], body) == (200, "13", b"")
        assert request(base, "/missing.html")[0] == 404
        assert request(base, "/index.html", "POST")[0] >= 400                   # read-only


def test_nothing_outside_the_folder_or_with_a_dotted_name_is_served(site: Path):
    with local_site.serve(str(site / "index.html")) as url:
        base = f"http://127.0.0.1:{urlsplit(url).port}"
        assert request(base, "/empty/")[0] == 404                               # no listing
        assert request(base, "/.env")[0] == 404
        assert request(base, "/.git/config")[0] == 404
        assert request(base, "/link-hidden.txt")[0] == 404                      # a link to a dotted name
        assert request(base, "/link-in.txt")[2] == b"h1{}"                      # a link that stays inside is a file
        for path in ("/link-out.txt", "/link-dir/secret.txt", "/../secret.txt", "/%2e%2e/secret.txt",
                     "/sub/../../secret.txt", "/..%2fsecret.txt", "/%5c..%5csecret.txt", "/sub/..\\..\\secret.txt"):
            status, _, body = request(base, path)
            assert status == 404 and OUTSIDE.encode() not in body, path
        assert request(base, "//evil.test/")[0] == 404
        status, headers, _ = request(base, "/sub//")
        assert status == 200 and "Location" not in headers
        status, headers, _ = request(base, "/%2f%2fevil.test")                  # a redirect never leaves the host
        assert status == 404


def test_the_server_stops_when_the_block_ends_and_when_it_fails(site: Path):
    with local_site.serve(str(site / "index.html")) as url:
        assert request(url, "/index.html")[0] == 200
    assert refuses_connections(url)
    with pytest.raises(RuntimeError, match="boom"):
        with local_site.serve(str(site / "index.html")) as failing:
            assert request(failing, "/index.html")[0] == 200
            raise RuntimeError("boom")
    assert refuses_connections(failing)


@pytest.mark.parametrize("target", ["http://localhost:3000/", "https://app.test/shop?x=1", "http://[::1]:8000/a",
                                    "localhost:3000", "app.test/index", "about:blank"])
def test_other_targets_pass_through_untouched(target: str):
    with local_site.serve(target) as url:
        assert url == target


def test_a_url_a_path_and_a_relative_path_name_the_same_page(site: Path, tmp_path: Path, monkeypatch):
    spaced = tmp_path / "my pages"
    spaced.mkdir()
    (spaced / "a b.html").write_text("<p>spaced</p>")
    monkeypatch.chdir(tmp_path)
    for target in (spaced.joinpath("a b.html").as_uri(), "file://localhost" + spaced.joinpath("a b.html").as_uri()[7:],
                   str(spaced / "a b.html"), "my pages/a b.html", "./my pages/../my pages/a b.html"):
        with local_site.serve(target) as url:
            assert urlsplit(url).path == "/a%20b.html", target
            assert request(url, urlsplit(url).path)[2] == b"<p>spaced</p>"
    with local_site.serve(spaced.joinpath("a b.html").as_uri() + "?tab=2#top") as url:           # the page gets its query and fragment
        assert (urlsplit(url).query, urlsplit(url).fragment) == ("tab=2", "top")


@pytest.mark.parametrize("target, message", [
    ("file:///no/such/page.html", "no such file"),
    ("missing/page.html", "no such file"),
    ("file://server/share/page.html", "host"),
])
def test_a_target_that_names_no_servable_file_is_refused(tmp_path: Path, monkeypatch, target: str, message: str):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(local_site.NotServable, match=message), local_site.serve(target):
        pass


def test_a_folder_a_dotted_file_and_an_outward_link_are_refused(site: Path, tmp_path: Path):
    (site / ".hidden.html").write_text("x")
    (site / "escape.html").symlink_to(tmp_path / "secret.txt")
    for target, message in ((site.as_uri(), "folder"), ((site / ".hidden.html").as_uri(), "dot"),
                            (str(site / "escape.html"), "outside its folder")):
        with pytest.raises(local_site.NotServable, match=message), local_site.serve(target):
            pass


@pytest.mark.parametrize("command, argv", [
    (behavior_main, ["--task", "t", "--stub", "missing.stub.yaml", "--out", "unused.json"]),     # the run fails
    (behavior_main, ["--task", "t", "--stub", "missing.stub.yaml", "--timezone", "Mars/Olympus"]),   # a usage error
    (render_main, ["--plan", "missing.plan.yaml", "--out", "unused.json"]),                  # the run fails
])
def test_a_check_that_ends_early_leaves_no_server_behind(site: Path, tmp_path: Path, monkeypatch, command, argv):
    seen: list[str] = []
    real = local_site.serve

    @contextmanager
    def watched(target: str):
        with real(target) as url:
            seen.append(url)
            yield url

    monkeypatch.setattr(local_site, "serve", watched)
    monkeypatch.chdir(tmp_path)
    try:
        code = command([(site / "index.html").as_uri(), *argv])
    except SystemExit as exit_:
        code = exit_.code
    assert code == 2 and len(seen) == 1
    assert refuses_connections(seen[0])
    assert not (tmp_path / "unused.json").exists()


def test_a_check_given_a_missing_file_stops_before_any_run(tmp_path: Path, capsys):
    with pytest.raises(SystemExit) as exit_:
        behavior_main(["file:///no/such/page.html", "--task", "t", "--stub", "missing.stub.yaml"])
    assert exit_.value.code == 2 and "no such file" in capsys.readouterr().err
