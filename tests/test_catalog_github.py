"""lazuli catalogs, GitHub foundries: the repository snapshot of a fixed account list from synthetic API responses
(tests/fixtures/catalog/github-foundries/). A fake transport serves them with GitHub's rate-limit headers and the
fake clock keeps the 3 s pace and the waits without sleeping; nothing here reaches the network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazuli import db, search, sources
from lazuli.catalog import cli as catalog_cli
from lazuli.catalog import github_foundries, net, store
from lazuli.catalog.github_foundries import Account

FIXTURES = Path(__file__).parent / "fixtures" / "catalog" / "github-foundries"
VELVETYNE = Account("velvetyne", "Velvetyne", ("latn",), True)
LEAGUE = Account("theleagueof", "The League of Moveable Type", ("latn",), False)
LXGW = Account("lxgw", "LXGW", ("hani",), True)
ACCOUNTS = [VELVETYNE, LEAGUE, LXGW]


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    def no_network(url, headers):
        raise AssertionError(f"a test reached for the network: {url}")

    fake = Clock()
    monkeypatch.setattr(net, "_clock", fake.time)
    monkeypatch.setattr(net, "_sleep", fake.sleep)
    monkeypatch.setattr(net, "_last_request", {})
    monkeypatch.setattr(net, "default_transport", no_network)
    return fake


API = github_foundries.API
ROUTES = {
    f"{API}/users/velvetyne/repos": "repos-velvetyne.json",
    f"{API}/users/theleagueof/repos": "repos-theleagueof.json",
    f"{API}/users/lxgw/repos": "repos-lxgw.json",
    f"{API}/repos/theleagueof/quill-gothic/license": "license-theleagueof-quill-gothic.json",
    f"{API}/repos/theleagueof/bold-text/license": "license-theleagueof-bold-text.json",
    f"{API}/repos/theleagueof/custom-face/license": "license-theleagueof-custom-face.json",
    f"{API}/repos/lxgw/LxgwTestKai/releases/latest": "release-lxgw-LxgwTestKai.json",
    f"{API}/repos/velvetyne/ember-grotesk/releases/latest": "release-velvetyne-ember-grotesk.json",
}


class GitHub:
    """The API as a fake transport: fixture JSON by URL (query ignored), 404 for the rest, and GitHub's quota headers
    counting down from `remaining`. `limited` is the request numbers (from 1, robots.txt first) answered 403 with the
    quota used up and a reset `reset_in` seconds away. A route may be a list of (file, Link header) answered in turn."""

    def __init__(self, clock: Clock, *, remaining: int = 60, limited=(), reset_in: float = 30, extra=None):
        self.clock, self.left, self.limited, self.reset_in = clock, remaining, set(limited), reset_in
        self.routes = {**ROUTES, **(extra or {})}
        self.log: list[tuple[str, float]] = []

    def __call__(self, url: str, headers: dict) -> net.Response:
        self.log.append((url, self.clock.now))
        reset = str(int(self.clock.now + self.reset_in))
        if len(self.log) in self.limited:
            return net.Response(url, 403, {"content-type": "application/json", "x-ratelimit-remaining": "0",
                                           "x-ratelimit-reset": reset}, b'{"message": "API rate limit exceeded"}')
        self.left = max(self.left - 1, 0)
        quota = {"x-ratelimit-remaining": str(self.left), "x-ratelimit-reset": reset}
        route = self.routes.get(url.split("?")[0])
        if route is None:
            return net.Response(url, 404, {"content-type": "application/json", **quota}, b'{"message": "Not Found"}')
        name, link = route.pop(0) if isinstance(route, list) else (route, None)
        return net.Response(url, 200, {"content-type": "application/json; charset=utf-8", **quota,
                                       **({"link": link} if link else {})}, (FIXTURES / name).read_bytes())

    def urls(self) -> list[str]:
        return [url.replace(API, "").split("?")[0] for url, _ in self.log]


def synced(site: GitHub, accounts=ACCOUNTS, conn=None):
    fetcher = net.Fetcher(github_foundries.NAME, min_interval_s=github_foundries.MIN_INTERVAL_S, conn=conn,
                          transport=site)
    return {f.source_key: f for f in github_foundries.fetch(fetcher, accounts)}


def license_of(family):
    return [(lb.raw, lb.mapped) for lb in family.labels if lb.kind == "license"]


def test_each_repository_is_a_family_with_its_license_as_found_and_where_it_was_read(clock):
    by_key = synced(GitHub(clock))
    # forks, collections, tooling, repositories that do not read as fonts, and a license-text repository are not families
    assert set(by_key) == {
        "velvetyne/ember-grotesk", "velvetyne/fold-mono", "velvetyne/quiet-serif", "velvetyne/loud-sans",
        "velvetyne/retired-slab", "theleagueof/quill-gothic", "theleagueof/bold-text", "theleagueof/custom-face",
        "theleagueof/lost-face", "lxgw/LxgwTestKai", "lxgw/lxgw-note-sans"}

    ember = by_key["velvetyne/ember-grotesk"]                         # SPDX says OFL-1.1
    assert (ember.family, ember.foundry, ember.license) == ("Ember Grotesk", "Velvetyne", "OFL-1.1")
    assert license_of(ember) == [("OFL-1.1", "OFL-1.1")]
    assert ember.details["license_source"] == "SPDX id OFL-1.1 reported by the GitHub API"
    assert ember.url == "https://github.com/velvetyne/ember-grotesk"
    assert ember.details["homepage"] == "https://foundry.example.test/ember"
    assert ember.details["description"] == "A grotesque for headlines"
    assert ember.signals == {"date_added": "2021-03-04", "last_modified": "2026-05-06"}   # no popularity: unknown familiarity

    assert license_of(by_key["velvetyne/fold-mono"]) == [("MIT", "free-other")]         # free, but none of the named licenses
    assert by_key["velvetyne/fold-mono"].license == "free-other"
    gpl = by_key["velvetyne/loud-sans"]                               # another SPDX id stays its own text, never open
    assert (gpl.license, license_of(gpl)) == ("GPL-3.0", [("GPL-3.0", None)])
    quiet = by_key["velvetyne/quiet-serif"]                           # GitHub reports none: unknown stays unknown
    assert quiet.license is None and license_of(quiet) == []
    assert quiet.details["license_source"] == "the GitHub API reports no license"
    assert by_key["velvetyne/retired-slab"].details["archived"] is True


def test_noassertion_falls_back_to_the_license_file_name_then_its_text_and_otherwise_stays_unknown(clock):
    by_key = synced(GitHub(clock))
    named = by_key["theleagueof/quill-gothic"]                        # OFL.md
    assert (named.license, license_of(named)) == ("OFL-1.1", [("OFL.md", "OFL-1.1")])
    assert named.details["license_source"] == (
        "license file OFL.md: its name is the OFL's (the GitHub API reports NOASSERTION)")
    texted = by_key["theleagueof/bold-text"]                          # LICENSE whose text is the OFL
    assert (texted.license, license_of(texted)) == ("OFL-1.1", [("LICENSE (text)", "OFL-1.1")])
    assert texted.details["license_source"].startswith("license file LICENSE: its text is the SIL Open Font License 1.1")
    custom = by_key["theleagueof/custom-face"]                        # a LICENSE that names no known license
    assert custom.license is None and license_of(custom) == []
    assert "does not name a license lazuli knows" in custom.details["license_source"]
    lost = by_key["theleagueof/lost-face"]                            # NOASSERTION and no license file at all
    assert lost.license is None and license_of(lost) == []
    assert "no license file was found" in lost.details["license_source"]


def test_scripts_come_from_the_description_and_topics_and_from_the_account_hint_and_say_which(clock):
    by_key = synced(GitHub(clock))
    mono = {lb.mapped: lb.raw for lb in by_key["velvetyne/fold-mono"].labels if lb.kind == "property"}
    assert mono == {"script:latn": "latin in the repository's description or topics",
                    "script:cyrl": "cyrillic in the repository's description or topics"}
    kai = {lb.mapped: lb.raw for lb in by_key["lxgw/LxgwTestKai"].labels if lb.kind == "property"}
    assert kai == {"script:hani": "chinese in the repository's description or topics"}      # the hint adds nothing new
    sans = {lb.mapped: lb.raw for lb in by_key["lxgw/lxgw-note-sans"].labels if lb.kind == "property"}
    assert sans == {"script:hani": "account hint in the source registry"}


def test_requests_one_per_account_license_only_for_noassertion_and_releases_only_for_marked_accounts(clock):
    site = GitHub(clock)
    synced(site)
    assert site.urls() == [
        "/robots.txt", "/users/velvetyne/repos", "/users/theleagueof/repos", "/users/lxgw/repos",
        "/repos/theleagueof/quill-gothic/license", "/repos/theleagueof/bold-text/license",
        "/repos/theleagueof/custom-face/license", "/repos/theleagueof/lost-face/license",
        # releases, most stars first, only velvetyne and lxgw ask for them
        "/repos/lxgw/LxgwTestKai/releases/latest", "/repos/velvetyne/ember-grotesk/releases/latest",
        "/repos/lxgw/lxgw-note-sans/releases/latest", "/repos/velvetyne/fold-mono/releases/latest",
        "/repos/velvetyne/quiet-serif/releases/latest", "/repos/velvetyne/loud-sans/releases/latest",
        "/repos/velvetyne/retired-slab/releases/latest"]
    times = [moment for _, moment in site.log]
    assert all(later - earlier >= 3 for earlier, later in zip(times, times[1:]))     # the 3 s pace


def test_download_is_the_latest_release_package_else_the_repository_archive(clock):
    by_key = synced(GitHub(clock))
    kai = by_key["lxgw/LxgwTestKai"]
    assert (kai.details["download_url"], kai.details["download_kind"], kai.details["release_tag"]) == (
        "https://downloads.example.test/LxgwTestKai-v1.2.0.zip", "release-asset", "v1.2.0")
    for key, branch in (("lxgw/lxgw-note-sans", "main"), ("velvetyne/ember-grotesk", "main"),   # no release, no assets
                        ("theleagueof/quill-gothic", "main")):                                   # account without releases
        family = by_key[key]
        assert (family.details["download_url"], family.details["download_kind"]) == (
            f"https://github.com/{key}/archive/refs/heads/{branch}.zip", "archive")


def test_a_nearly_used_quota_skips_the_optional_release_lookups_and_keeps_the_archive(clock):
    site = GitHub(clock, remaining=14)                  # 8 required requests leave 6: one lookup above the reserve of 5
    by_key = synced(site)
    releases = [url for url in site.urls() if url.endswith("/releases/latest")]
    assert releases == ["/repos/lxgw/LxgwTestKai/releases/latest"]
    assert by_key["lxgw/LxgwTestKai"].details["download_kind"] == "release-asset"
    assert by_key["velvetyne/ember-grotesk"].details["download_kind"] == "archive"
    assert len(by_key) == 11                            # the snapshot is whole


def test_a_used_up_quota_waits_for_the_reset_then_goes_on(clock):
    site = GitHub(clock, limited={3}, reset_in=30)      # the second account's list is refused once
    by_key = synced(site)
    assert len(by_key) == 11
    refused, retried = [t for url, t in site.log if url.startswith(f"{API}/users/theleagueof/repos")]
    assert retried - refused >= 30                      # it waited for the reset, not for the pace alone


def test_a_reset_too_far_away_stops_the_sync_and_keeps_the_previous_rows(clock, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(github_foundries, "accounts", lambda: ACCOUNTS)
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    conn = db.connect(tmp_path / "lazuli.db")
    first = GitHub(clock)
    monkeypatch.setattr(net, "default_transport", first)
    assert catalog_cli.sync(conn, ["github-foundries"], force=True) == 0
    kept = conn.execute("SELECT COUNT(*) FROM catalog_family").fetchone()[0]
    assert kept == 11 and "github-foundries: 11 families" in capsys.readouterr().out

    monkeypatch.setattr(net, "default_transport", GitHub(clock, limited={3}, reset_in=3600))
    assert catalog_cli.sync(conn, ["github-foundries"], force=True) == 1
    out = capsys.readouterr().out
    assert "github-foundries: failed: RateLimited" in out and "request quota" in out and "Previous rows kept" in out
    assert conn.execute("SELECT COUNT(*) FROM catalog_family").fetchone()[0] == kept
    assert conn.execute("SELECT status FROM source WHERE name = 'github-foundries'").fetchone()[0] == "failed"
    conn.close()


def test_a_forbidden_answer_without_the_quota_headers_is_a_block_not_a_rate_limit(clock):
    def forbidden(url, headers):
        return net.Response(url, 403, {"content-type": "application/json"}, b'{"message": "Forbidden"}')

    fetcher = net.Fetcher(github_foundries.NAME, min_interval_s=3.0, transport=forbidden)
    with pytest.raises(net.Blocked):
        github_foundries.fetch(fetcher, ACCOUNTS)


def test_a_longer_list_is_followed_through_the_link_header(clock):
    next_page = f'<{API}/users/velvetyne/repos?per_page=100&sort=pushed&page=2>; rel="next"'
    site = GitHub(clock, extra={f"{API}/users/velvetyne/repos": [("repos-velvetyne.json", next_page),
                                                                 ("repos-lxgw.json", None)]})
    fetcher = net.Fetcher(github_foundries.NAME, min_interval_s=3.0, transport=site)
    keys = {f.source_key for f in github_foundries.fetch(fetcher, [VELVETYNE])}
    assert "velvetyne/ember-grotesk" in keys and "lxgw/LxgwTestKai" in keys             # the second page's repositories
    assert site.urls().count("/users/velvetyne/repos") == 2


def test_a_response_that_names_no_font_never_becomes_an_empty_snapshot(clock):
    site = GitHub(clock, extra={f"{API}/users/velvetyne/repos": "repos-empty.json"})
    fetcher = net.Fetcher(github_foundries.NAME, min_interval_s=3.0, transport=site)
    with pytest.raises(ValueError, match="no font repositories found"):
        github_foundries.fetch(fetcher, [VELVETYNE])


def test_the_registry_lists_the_accounts_and_kept_responses_remap_to_the_same_snapshot(clock, tmp_path, monkeypatch):
    listed = github_foundries.accounts()
    assert [a.login for a in listed] == ["velvetyne", "collletttivo", "theleagueof", "Omnibus-Type", "jenskutilek", "lxgw",
                                         "atelier-anchor", "yuru7", "spoqa", "orioncactus"]
    assert (listed[5].scripts, listed[5].releases, listed[8].scripts) == (("hani",), True, ("hang", "latn"))
    assert {e["access"] for e in sources.load_registry() if e.get("adapter") == "github-foundries"} == {"adapter"}

    monkeypatch.setattr(github_foundries, "accounts", lambda: ACCOUNTS)
    conn = db.connect(tmp_path / "lazuli.db")
    store.ensure_source(conn, github_foundries)
    before = synced(GitHub(clock), conn=conn)
    assert {f.source_key: f for f in github_foundries.from_raw(conn)} == before
    conn.close()


# ---------------------------------------------------------------------------------------------- search
def test_families_flow_into_search_labeled_with_their_source_and_license_provenance(clock, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "lazuli.db"))
    conn = db.connect(tmp_path / "lazuli.db")
    store.replace_snapshot(conn, github_foundries, list(synced(GitHub(clock)).values()))
    conn.close()

    assert search.main(["--script", "hani", "--json"]) == 0
    found = {c["family"]: c for c in json.loads(capsys.readouterr().out)["candidates"]}
    assert set(found) == {"LxgwTestKai", "Lxgw Note Sans"}                    # hani by the repository text and by the hint
    kai = found["LxgwTestKai"]
    assert [c["source"] for c in kai["catalogs"]] == ["github-foundries"]
    assert kai["catalogs"][0]["details"]["download_kind"] == "release-asset"
    assert kai["license"]["id"] == "OFL-1.1" and kai["familiarity"] == {"tier": "unknown"}
    assert "license source, github-foundries: SPDX id OFL-1.1 reported by the GitHub API" in kai["evidence"]
    assert "download, github-foundries: https://downloads.example.test/LxgwTestKai-v1.2.0.zip (release-asset)" in kai["evidence"]

    assert search.main(["--license", "open", "--limit", "30", "--json"]) == 0
    open_names = {c["family"] for c in json.loads(capsys.readouterr().out)["candidates"]}
    # OFL by SPDX, by file name, and by file text are open; MIT, GPL, and the unknown ones are not
    assert open_names == {"Ember Grotesk", "Retired Slab", "Quill Gothic", "Bold Text", "LxgwTestKai", "Lxgw Note Sans"}

    assert search.main(["quill", "--limit", "5"]) == 0
    text = capsys.readouterr().out
    assert "catalog: github-foundries" in text and "license source, github-foundries: license file OFL.md" in text
