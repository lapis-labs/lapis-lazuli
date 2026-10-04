"""lazuli fetch: an open-licensed Google Fonts family's files and license text from the google/fonts repository.
A fake transport plays the GitHub API; nothing here reaches the network, and a fake clock keeps the 3 s pace."""
from __future__ import annotations

import hashlib
import json
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

from lapis_design import rights_check
from lazuli import db, fetch, lock
from lazuli.catalog import google_fonts, net, store
from lazuli.catalog.store import CatalogFamily, CatalogLabel
from synthetic_fonts import build

SHA = "0123456789abcdef0123456789abcdef01234567"
GRANT = ("Permission is hereby granted, free of charge, to any person obtaining a copy of the Font Software, to use, "
         "study, copy, merge, embed, modify, redistribute, and sell modified and unmodified copies of the Font Software")
OFL = f"Copyright 2026 Tests\n\nSIL OPEN FONT LICENSE Version 1.1 - 26 February 2007\n{GRANT}, subject to conditions.\n"


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(net, "_clock", fake.time)
    monkeypatch.setattr(net, "_sleep", fake.sleep)
    monkeypatch.setattr(net, "_last_request", {})
    return fake


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class GitHub:
    """The google/fonts repository as the contents, commits, and blobs endpoints answer for it."""

    def __init__(self, clock: Clock, tmp_path: Path, folder="ofl/testsans", files: dict[str, bytes] | None = None):
        font = build(tmp_path / "TestSans-Regular.ttf", family="Test Sans").read_bytes()
        self.clock, self.folder, self.log = clock, folder, []
        self.files = {"OFL.txt": OFL.encode(), "TestSans-Regular.ttf": font} if files is None else files
        self.answers: dict[str, net.Response | None] = {}          # url -> a canned response

    def listing(self) -> list[dict]:
        return [{"type": "file", "name": name, "sha": blob_id(data), "size": len(data)} for name, data in self.files.items()]

    def __call__(self, url: str, headers: dict) -> net.Response:
        self.log.append((url, headers, self.clock.now))
        if url in self.answers:
            return self.answers[url]
        base = google_fonts.REPO_API
        if url == base + "/commits/main":
            return net.Response(url, 200, {"content-type": "text/plain"}, SHA.encode())
        if url == f"{base}/contents/{self.folder}?ref={SHA}":
            return net.Response(url, 200, {"content-type": "application/json"}, json.dumps(self.listing()).encode())
        for data in self.files.values():
            if url == f"{base}/git/blobs/{blob_id(data)}":
                return net.Response(url, 200, {"content-type": "application/octet-stream"}, data)
        return net.Response(url, 404, {"content-type": "text/plain"}, b"not found")

    def urls(self) -> list[str]:
        return [url for url, _, _ in self.log]


def catalog(conn, **directories):
    """The google-fonts snapshot: each family by the repository directory its license sits in."""
    families = [CatalogFamily(name, name, license=google_fonts.LICENSE_DIRS[directory],
                              labels=[CatalogLabel("license", directory, google_fonts.LICENSE_DIRS[directory])])
                for name, directory in {"Test Sans": "ofl", **{k.replace("_", " "): v for k, v in directories.items()}}.items()]
    module = SimpleNamespace(NAME="google-fonts", KIND="snapshot", PRIORITY=10, TTL_DAYS=30, MIN_INTERVAL_S=3.0)
    store.replace_snapshot(conn, module, families)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "cache" / "lazuli.db"))
    connection = db.connect(tmp_path / "cache" / "lazuli.db")
    catalog(connection)
    yield connection
    connection.close()


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root


def run_fetch(conn, site, project, family="Test Sans", into="public/fonts/test-sans"):
    fetcher = net.Fetcher(google_fonts.NAME, min_interval_s=google_fonts.MIN_INTERVAL_S, conn=conn, transport=site)
    return fetch.fetch_family(conn, fetcher, family, project, Path(into))


def test_a_fetched_family_is_written_with_its_license_and_locks_clean(conn, clock, project, tmp_path, monkeypatch):
    """Acceptance: fetch the way the skill documents, lock what it prints, and the rights check passes."""
    site = GitHub(clock, tmp_path)
    result = run_fetch(conn, site, project)
    base = google_fonts.REPO_API
    assert site.urls() == [                                       # api.github.com has no robots.txt: it answers 404
        base.replace("/repos/google/fonts", "") + "/robots.txt", base + "/commits/main",
        f"{base}/contents/ofl/testsans?ref={SHA}",
        f"{base}/git/blobs/{blob_id(site.files['OFL.txt'])}",
        f"{base}/git/blobs/{blob_id(site.files['TestSans-Regular.ttf'])}"]
    times = [t for _, _, t in site.log]
    assert all(later - earlier >= 3.0 for earlier, later in zip(times, times[1:]))        # a human pace
    raw = {url: h for url, h, _ in site.log}
    assert raw[f"{base}/git/blobs/{blob_id(site.files['OFL.txt'])}"]["Accept"] == "application/vnd.github.raw+json"
    assert (project / "public/fonts/test-sans/OFL.txt").read_text() == OFL
    written = (project / "public/fonts/test-sans/TestSans-Regular.ttf").read_bytes()
    assert written == site.files["TestSans-Regular.ttf"]
    assert result["source_url"] == f"https://github.com/google/fonts/tree/{SHA}/ofl/testsans"
    assert result["license"] == {"kind": "ofl", "file": "public/fonts/test-sans/OFL.txt",
                                 "url": f"https://github.com/google/fonts/blob/{SHA}/ofl/testsans/OFL.txt"}
    assert result["files"] == [{"path": "public/fonts/test-sans/TestSans-Regular.ttf", "bytes": len(written),
                                "sha256": hashlib.sha256(written).hexdigest()}]
    assert "--research verified" in result["lock"] and "--files 'public/fonts/test-sans/*.ttf'" in result["lock"]

    # what the agent does next: read the license text, then lock the files with what it read
    code = lock.main(["Test Sans", "--role", "body", "--task", "demo", "--project", str(project),
                      "--source", "google-fonts", "--source-url", result["source_url"], "--delivery", "self-host",
                      "--files", "public/fonts/test-sans/*.ttf", "--modified", "none",
                      "--notice", result["license"]["file"], "--license-kind", result["license"]["kind"],
                      "--use", "web=allowed", "app=allowed-with-conditions", "--research", "verified",
                      "--evidence", "license-file", result["license"]["url"], "--quote", GRANT])
    assert code == 0
    written_lock = json.loads((project / ".lapis" / "fonts.lock.json").read_text())
    assert lock.validate(written_lock) == []
    assert rights_check.check(None, written_lock, project, __import__("datetime").date.today()) == []


def test_nothing_is_written_when_a_file_is_not_what_the_listing_promised(conn, clock, project, tmp_path):
    html = b"<!doctype html><title>Not found</title>"
    bad_font = GitHub(clock, tmp_path, files={"OFL.txt": OFL.encode(), "TestSans-Regular.ttf": html})
    with pytest.raises(fetch.Failed, match="not a font file"):
        run_fetch(conn, bad_font, project)
    not_ofl = GitHub(clock, tmp_path, files={"OFL.txt": b"Fonts are free.\n",
                                             "TestSans-Regular.ttf": build(tmp_path / "x.ttf").read_bytes()})
    with pytest.raises(fetch.Failed, match="does not name the ofl license"):
        run_fetch(conn, not_ofl, project)
    swapped = GitHub(clock, tmp_path)
    blob = f"{google_fonts.REPO_API}/git/blobs/{blob_id(swapped.files['TestSans-Regular.ttf'])}"
    swapped.answers[blob] = net.Response(blob, 200, {}, swapped.files["TestSans-Regular.ttf"] + b"\0")
    with pytest.raises(fetch.Failed, match="does not hash to the id the listing names"):
        run_fetch(conn, swapped, project)
    nothing = GitHub(clock, tmp_path, files={"OFL.txt": OFL.encode()})
    with pytest.raises(fetch.Failed, match="no top-level .ttf or .otf"):
        run_fetch(conn, nothing, project)
    no_license = GitHub(clock, tmp_path, files={"TestSans-Regular.ttf": build(tmp_path / "y.ttf").read_bytes()})
    with pytest.raises(fetch.Failed, match="holds no OFL.txt"):
        run_fetch(conn, no_license, project)
    assert not (project / "public").exists()


def test_what_this_command_cannot_fetch_is_refused_before_any_request(conn, clock, project, tmp_path):
    site = GitHub(clock, tmp_path)
    catalog(conn, Ubuntu_Test="ufl")
    fontsource = SimpleNamespace(NAME="fontsource", KIND="snapshot", PRIORITY=20, TTL_DAYS=30, MIN_INTERVAL_S=3.0)
    store.replace_snapshot(conn, fontsource, [CatalogFamily("Pretendard", "Pretendard", license="OFL-1.1")])
    for family, message in (("Private Grotesk", "not in the lazuli DB"), ("Ubuntu Test", "has no kind for"),
                            ("Pretendard", "not in the google-fonts catalog")):
        with pytest.raises(fetch.Usage, match=message):
            run_fetch(conn, site, project, family=family)
    with pytest.raises(fetch.Usage, match="outside the project"):
        run_fetch(conn, site, project, into="../elsewhere")
    assert site.log == []
    (project / "public/fonts/test-sans").mkdir(parents=True)
    (project / "public/fonts/test-sans/OFL.txt").write_text("my own notes", encoding="utf-8")
    with pytest.raises(fetch.Usage, match="already exist .* with other content"):
        run_fetch(conn, site, project)
    assert (project / "public/fonts/test-sans/OFL.txt").read_text() == "my own notes"
    assert not (project / "public/fonts/test-sans/TestSans-Regular.ttf").exists()


def test_a_second_fetch_of_the_same_files_changes_nothing(conn, clock, project, tmp_path):
    site = GitHub(clock, tmp_path)
    first = run_fetch(conn, site, project)
    assert run_fetch(conn, site, project) == first


def test_a_block_or_a_missing_folder_stops_the_fetch(conn, clock, project, tmp_path):
    site = GitHub(clock, tmp_path)
    listing = f"{google_fonts.REPO_API}/contents/ofl/testsans?ref={SHA}"
    site.answers[listing] = net.Response(listing, 403, {}, b"")
    with pytest.raises(net.Blocked, match="403"):
        run_fetch(conn, site, project)
    missing = GitHub(clock, tmp_path, folder="ofl/elsewhere")
    with pytest.raises(fetch.Failed, match="is not in the repository"):
        run_fetch(conn, missing, project)
    assert not (project / "public").exists()
    assert urllib.parse.urlsplit(site.urls()[-1]).path.endswith("/contents/ofl/testsans")
