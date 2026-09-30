"""lazuli sources: the source registry, its agreement with the catalog adapters, URL lookup, and the CLI."""
from __future__ import annotations

import json

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from lapis_design import shared_dir
from lazuli import catalog, cli, sources

SCHEMA = yaml.safe_load((shared_dir() / "sources" / "registry.schema.yaml").read_text(encoding="utf-8"))
VOCAB = yaml.safe_load((shared_dir() / "vocab" / "color.yaml").read_text(encoding="utf-8"))


def test_registry_passes_its_schema_with_unique_ids():
    Draft202012Validator.check_schema(SCHEMA)
    doc = yaml.safe_load((shared_dir() / "sources" / "registry.yaml").read_text(encoding="utf-8"))
    errors = [f"{list(e.path)}: {e.message}"
              for e in Draft202012Validator(SCHEMA, format_checker=FormatChecker()).iter_errors(doc)]
    assert errors == []
    ids = [e["id"] for e in doc["sources"]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("change", [{"access": "refused"}, {"access": "browser-link"}, {"adapter": "noonnu"}])
def test_schema_demands_the_why_of_every_restriction(change):
    """A refusal needs its reason and clause, a browser link its reason, and only adapters name an adapter."""
    entry = {"id": "x", "name": "X", "url": "https://example.com/", "type": ["font"], "good_for": "testing",
             "access": "read", "terms_url": "https://example.com/terms", "checked_at": "2026-09-26", **change}
    doc = {"version": 0, "sources": [entry]}
    assert list(Draft202012Validator(SCHEMA).iter_errors(doc))


def test_catalog_adapters_and_the_registry_agree():
    """Every network adapter has registry entries with its policy: REFUSED modules are `refused`, the rest
    `adapter`; and every adapter the registry names exists."""
    registry = sources.load_registry()
    modules = {m.NAME: m for m in catalog.SOURCES}
    problems = []
    for module in catalog.SOURCES:
        if module.KIND == "bundled":                        # shipped data; nothing to reach
            continue
        entries = [e for e in registry if e.get("adapter") == module.NAME]
        expected = "refused" if getattr(module, "REFUSED", None) else "adapter"
        if not entries:
            problems.append(f"{module.NAME}: no registry entry")
        problems += [f"{e['id']}: {e['access']}, but {module.NAME} is {expected}"
                     for e in entries if e["access"] != expected]
    problems += [f"{e['id']}: names unknown adapter {e['adapter']}" for e in registry
                 if "adapter" in e and e["adapter"] not in modules]
    assert problems == []


def test_each_code_system_has_exactly_one_reference_entry():
    code_systems = {s["id"] for s in VOCAB["systems"] if s["store"] != "name-and-value"}
    named = [e["color_system"] for e in sources.load_registry() if "color_system" in e]
    assert sorted(named) == sorted(code_systems)


def test_load_registry_rejects_an_access_the_schema_does_not_know(tmp_path):
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"version": 0, "sources": [
        {"id": "ok", "url": "https://ok.example/", "access": "read"},
        {"id": "typo", "url": "https://typo.example/", "access": "reed"}]}), encoding="utf-8")
    with pytest.raises(sources.RegistryError, match="typo: 'reed'"):
        sources.load_registry(path)


REGISTRY = [
    {"id": "repo-host", "url": "https://github.com/", "hosts": ["raw.githubusercontent.com"], "access": "read"},
    {"id": "one-repo", "url": "https://github.com/google/fonts", "access": "adapter"},
    {"id": "guide", "url": "https://developer.example.com/design/guide", "access": "refused"},
    {"id": "shop", "url": "https://www.shop.example/palettes", "access": "read"},
    {"id": "shop-app", "url": "https://shop.example/app", "access": "browser-link"},
    {"id": "odd", "url": "https://odd.example/listed", "access": "someday"},
]


@pytest.mark.parametrize("url, expected", [
    ("https://github.com/google/fonts/tree/main/ofl", "one-repo"),          # longest path prefix wins
    ("https://github.com/google/fontsx", "repo-host"),                      # a prefix ends at a segment
    ("https://GitHub.com/someone/else", "repo-host"),
    ("https://raw.githubusercontent.com/a/b/main/x.md", "repo-host"),       # an extra host of the entry
    ("https://developer.example.com/design/guide/colors", "guide"),
    ("https://developer.example.com/documentation/x", "guide"),              # terms cover the whole host
    ("https://shop.example/palettes/42", "shop"),                           # www. is ignored both ways
    ("https://www.shop.example/checkout", "shop-app"),                      # uncovered path: strictest entry
    ("https://odd.example/elsewhere", "odd"),                               # unknown access fails closed
    ("https://sub.github.com/x", None),                                     # subdomains are not implied
    ("https://example.org/", None),
    ("not a url", None),
])
def test_find_matches_by_host_then_path(url, expected):
    found = sources.find(url, REGISTRY)
    assert (found and found["id"]) == expected


def test_find_fails_closed_on_an_unknown_access_among_known_ones():
    registry = [{"id": "open", "url": "https://mixed.example/a", "access": "read"},
                {"id": "odd", "url": "https://mixed.example/b", "access": "someday"}]
    assert sources.find("https://mixed.example/c", registry)["id"] == "odd"


@pytest.mark.parametrize("host", ["LOCALHOST.", "localhost。", "localhost．", "localhost｡", "lºcalhost"])
def test_idna_host_forms_obey_the_same_registry_refusal(host):
    registry = [{"id": "closed", "url": "http://localhost/", "access": "refused"}]
    assert sources.find(f"http://{host}/", registry)["id"] == "closed"


def test_unconvertible_request_host_is_refused_and_invalid_registry_hosts_are_skipped():
    invalid = "x" * 64 + ".test"
    registry = [{"id": "invalid", "url": f"https://{invalid}/", "access": "refused"},
                {"id": "invalid-extra", "url": "https://elsewhere.test/", "hosts": [invalid],
                 "access": "refused"},
                {"id": "valid", "url": "https://valid.test/", "access": "read"}]
    refused = sources.find(f"https://{invalid}/", registry)
    assert refused["access"] == "refused" and len(refused["reason"].splitlines()) == 1
    assert sources.find("https://valid.test/", registry)["id"] == "valid"
    assert sources.find("https://elsewhere.test/", registry)["id"] == "invalid-extra"

def test_malformed_url_host_is_refused_without_registry_lookup():
    refused = sources.find("http://[::1/x", [])
    assert refused["access"] == "refused"
    assert refused["id"] == "invalid-host"
    assert "request not sent" in refused["reason"]


def test_registry_unicode_host_is_normalized_even_when_request_is_ascii():
    assert sources.find("https://localhost/", [
        {"id": "closed", "url": "https://lºcalhost。/", "access": "refused"}])["id"] == "closed"

def test_shipped_registry_refuses_the_sites_whose_terms_forbid_tools():
    for url in ("https://noonnu.cc/font_page/366", "https://fonts.adobe.com/fonts/source-han-sans-korean",
                "https://color.adobe.com/explore"):
        assert sources.find(url)["access"] == "refused", url


def test_sources_lists_by_type_with_reasons(capsys):
    assert cli.main(["sources", "--type", "color", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed and all("color" in e["type"] for e in listed)
    assert {e["color_system"] for e in listed if "color_system" in e} >= {"pantone", "hlc", "ral-design-plus"}
    assert cli.main(["sources", "--type", "font"]) == 0
    out = capsys.readouterr().out
    assert "noonnu" in out and "refused: noonnu's terms" in out and "제7조" in out
    assert "adapter:sandoll" in out and "color-hunt" not in out


def test_sources_rejects_an_unknown_type():
    with pytest.raises(SystemExit) as exit_:
        cli.main(["sources", "--type", "sound"])
    assert exit_.value.code == 2


def test_source_search_ranks_entries_matching_more_words_first(capsys):
    assert sources.search_main(["data", "palettes", "--kind", "color", "--json"]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert hits[0]["id"] in {"colorbrewer", "cartocolors", "hcl-wizard"}
    assert all("color" in h["type"] for h in hits)
    assert sources.search_main(["korean", "--access", "refused", "--json"]) == 0
    assert [h["id"] for h in json.loads(capsys.readouterr().out)] == ["noonnu"]
    assert sources.search_main(["zzzz-nothing"]) == 0
    assert "no source matches" in capsys.readouterr().out
