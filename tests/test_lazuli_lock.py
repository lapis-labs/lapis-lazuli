"""lazuli lock: the fonts lock from the lazuli DB, flags, and shipped files, as plan_check and rights_check read it."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fontTools.ttLib import TTFont

from lapis_design import plan_check, rights_check, shared_dir
from lazuli import cli, db, lock
from lazuli.catalog import labels, match, net, store
from lazuli.catalog.store import CatalogFamily, CatalogFont, CatalogLabel
from synthetic_fonts import build

SHARED = shared_dir()
OFL_BODY = ("SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007\n"
            '"Reserved Font Name" refers to any names specified as such after the copyright statement(s).\n'
            "No Modified Version of the Font Software may use the Reserved Font Name(s) unless explicit written "
            "permission is granted by the corresponding Copyright Holder.\n")
GRANT = ("Permission is hereby granted, free of charge, to any person obtaining a copy of the Font Software, to use, "
         "study, copy, merge, embed, modify, redistribute, and sell modified and unmodified copies of the Font Software")
OFL_URL = "https://github.com/google/fonts/blob/0123456789abcdef0123456789abcdef01234567/ofl/testsans/OFL.txt"
SOURCE_URL = "https://github.com/google/fonts/tree/0123456789abcdef0123456789abcdef01234567/ofl/testsans"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def no_network(url, headers):
        raise AssertionError(f"a test reached for the network: {url}")

    monkeypatch.setattr(net, "default_transport", no_network)


@pytest.fixture
def env(tmp_path, monkeypatch):
    user = tmp_path / "fonts" / "user"
    system = tmp_path / "fonts" / "system"
    user.mkdir(parents=True)
    system.mkdir(parents=True)
    monkeypatch.setenv("LAZULI_FONT_ROOTS", os.pathsep.join([f"user={user}", f"system={system}"]))
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "cache" / "lazuli.db"))
    project = tmp_path / "project"
    project.mkdir()
    return SimpleNamespace(user=user, system=system, project=project, db=tmp_path / "cache" / "lazuli.db")


def with_records(path: Path, records: dict[int, str]) -> Path:
    font = TTFont(str(path))
    for name_id, text in records.items():
        font["name"].setName(text, name_id, 3, 1, 0x409)
    font.save(str(path))
    return path


def google_fonts(conn, *families: CatalogFamily) -> None:
    module = SimpleNamespace(NAME="google-fonts", KIND="snapshot", PRIORITY=10, TTL_DAYS=30, MIN_INTERVAL_S=3.0)
    store.replace_snapshot(conn, module, list(families))
    match.run(conn)


def ofl_family(name: str, *, ko: str | None = None, fonts=(), scripts=("latn",), genre=("Sans Serif", "sans")):
    return CatalogFamily(name, name, names_i18n={"ko": ko} if ko else {}, license="OFL-1.1",
                         fonts=[CatalogFont(ps) for ps in fonts],
                         labels=labels.class_labels(*genre)
                         + [CatalogLabel("property", s, f"script:{s}") for s in scripts]
                         + [CatalogLabel("license", "ofl", "OFL-1.1")])


@pytest.fixture
def fonts_db(env, capsys):
    """Installed Test Sans (user) and System Serif (system); Google Fonts lists Test Sans and Gowun Batang."""
    build(env.user / "TestSans-Regular.ttf", family="Test Sans")
    build(env.user / "TestSans-Bold.ttf", family="Test Sans", style="Bold", stem=160)
    build(env.system / "SystemSerif.ttf", family="System Serif", serif=True)
    assert cli.main(["local", "fonts", "--no-measure"]) == 0
    conn = db.connect(env.db)
    google_fonts(conn, ofl_family("Test Sans"),
                 ofl_family("Gowun Batang", ko="고운바탕", fonts=("GowunBatang-Regular", "GowunBatang-Bold"),
                            scripts=("hang", "latn"), genre=("Serif", "bu-ri")))
    conn.close()
    capsys.readouterr()
    return env


def run(env, *argv: str, capsys=None):
    code = lock.main([*argv, "--project", str(env.project), "--json"])
    out = json.loads(capsys.readouterr().out) if capsys and code == 0 else None
    return code, out


def read_lock(env) -> dict:
    return json.loads((env.project / ".lapis" / "fonts.lock.json").read_text(encoding="utf-8"))


def test_lock_from_the_db_validates_and_keeps_hints_as_hints(fonts_db, capsys):
    code, out = run(fonts_db, "test sans", "--role", "body", "--task", "demo", capsys=capsys)
    assert code == 0 and out["action"] == "added" and out["written"]
    written = read_lock(fonts_db)
    assert lock.validate(written) == []
    entry = written["fonts"][0]
    assert entry["family"] == "Test Sans"                                 # the DB's name, not the typed one
    assert entry["postscript_names"] == ["TestSans-Bold", "TestSans-Regular"]
    assert entry["scripts"] == ["latn"]
    assert entry["source"] == "user-installed"                            # installed copy, provenance unknown
    assert entry["catalog_match"] == {"catalog": "google-fonts", "key": "Test Sans", "method": "exact_family",
                                      "confidence": 0.9}
    assert entry["license"]["kind"] == "ofl" and entry["license"]["source_class"] == "catalog-summary"
    assert "uses" not in entry["license"]                                 # a catalog never grants a use
    assert entry["delivery"] == "not-deliverable"
    assert any("--source google-fonts" in note for note in out["notes"])

    code, out = run(fonts_db, "System Serif", "--role", "heading", "--task", "demo", capsys=capsys)
    entry = out["entry"]
    assert (entry["source"], entry["delivery"], entry["license"]["kind"]) == ("system", "system-only", "unknown")
    assert "source_class" not in entry["license"]

    code, out = run(fonts_db, "고운바탕", "--role", "heading", "--task", "demo", capsys=capsys)
    entry = out["entry"]                                                  # in a catalog only, found by its ko name
    assert entry["family"] == "Gowun Batang" and entry["source"] == "google-fonts"
    assert entry["postscript_names"] == ["GowunBatang-Bold", "GowunBatang-Regular"]
    assert entry["scripts"] == ["hang", "latn"] and entry["delivery"] == "google-fonts-api"
    assert len(read_lock(fonts_db)["fonts"]) == 3 and lock.validate(read_lock(fonts_db)) == []


def test_relocking_adds_the_task_replaces_changed_facts_and_never_downgrades_a_declaration(fonts_db, capsys):
    run(fonts_db, "Test Sans", "--role", "body", "--task", "landing", capsys=capsys)
    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "checkout", "--source", "google-fonts",
                    "--delivery", "self-host", "--license-kind", "ofl", "--use", "web=allowed", capsys=capsys)
    assert code == 0 and out["action"] == "updated"
    changed = {c["field"]: (c["old"], c["new"]) for c in out["changes"]}
    assert changed["used_by"] == (["landing"], ["landing", "checkout"])
    assert changed["source"] == ("user-installed", "google-fonts")
    assert changed["license.source_class"] == ("catalog-summary", "user-declared")
    assert changed["license.uses.web"] == (None, "allowed")
    assert changed["delivery"] == ("not-deliverable", "self-host")

    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "landing", capsys=capsys)
    assert out["action"] == "unchanged" and not out["written"]          # the catalog hint does not replace it
    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "landing", "--use", "app=not-allowed",
                    capsys=capsys)
    assert out["entry"]["license"]["uses"] == {"web": "allowed", "app": "not-allowed"}
    code, out = run(fonts_db, "Test Sans", "--role", "ui", "--task", "landing", capsys=capsys)
    assert out["action"] == "added"                                      # family + role is the key
    fonts = read_lock(fonts_db)["fonts"]
    assert [(f["role"], f["used_by"]) for f in fonts] == [("body", ["landing", "checkout"]), ("ui", ["landing"])]


def test_unknown_family_needs_facts(env, capsys):
    code, _ = run(env, "Private Grotesk", "--role", "body", "--task", "demo", capsys=capsys)
    assert code == 2 and "unknown to the lazuli DB" in capsys.readouterr().err
    assert not (env.project / ".lapis").exists()
    code, _ = run(env, "Private Grotesk", "--role", "body", "--task", "demo", "--source", "foundry-purchase",
                  capsys=capsys)
    assert code == 2 and "--postscript" in capsys.readouterr().err       # facts, but not the required ones
    code, out = run(env, "Private Grotesk", "--role", "body", "--task", "demo", "--source", "foundry-purchase",
                    "--postscript", "PrivateGrotesk-Regular", "--license-kind", "commercial-perpetual",
                    "--use", "web=allowed-with-conditions", "--delivery", "self-host", capsys=capsys)
    assert code == 0
    entry = out["entry"]
    assert entry["license"] == {"kind": "commercial-perpetual", "uses": {"web": "allowed-with-conditions"},
                                "checked_at": entry["license"]["checked_at"], "source_class": "user-declared"}
    assert "catalog_match" not in entry and lock.validate(read_lock(env)) == []
    code, _ = run(env, "Private Grotesk", "--role", "body", "--task", "demo", "--use", "web=allowed", capsys=capsys)
    assert code == 0                                                     # builds on the declared license


def test_shipped_files_give_names_notices_and_reserved_names(fonts_db, capsys):
    shipped = fonts_db.project / "public" / "fonts"
    build(shipped / "TestSans-Regular.ttf", family="Test Sans")
    with_records(shipped / "TestSans-Regular.ttf", {
        0: 'Copyright 2026 LapisLazuli tests, with Reserved Font Name "Test Sans".',
        13: "This Font Software is licensed under the SIL Open Font License, Version 1.1.",
        14: "https://openfontlicense.org"})
    build(shipped / "TestSans-Bold.ttf", family="Test Sans", style="Bold")
    with_records(shipped / "TestSans-Bold.ttf", {0: "Copyright 2026 LapisLazuli tests"})     # no license record
    (shipped / "OFL.txt").write_text(OFL_BODY, encoding="utf-8")
    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", "--source", "google-fonts",
                    "--delivery", "self-host", "--files", "public/fonts/*.ttf", "--modified", "subset",
                    "--notice", "public/fonts/OFL.txt", capsys=capsys)
    assert code == 0
    entry = out["entry"]
    assert entry["license"]["kind"] == "ofl" and entry["license"]["source_class"] == "file-metadata"
    assert entry["reserved_names"] == {"names": ["Test Sans"], "permission": False}
    assert {"Test Sans", "TestSans-Regular", "TestSans-Bold"} <= set(entry["shipped_names"])
    assert entry["notices_embedded"] is False                            # the Bold file lacks a license record
    assert lock.validate(read_lock(fonts_db)) == []
    hits = {h["rule_id"]: h["observed"] for h in rights_check.check_font(entry, root=fonts_db.project)}
    assert hits["rights.reserved-font-name"] == "modified font keeps reserved Test Sans"

    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", "--reserved-name-permission",
                    capsys=capsys)
    assert out["entry"]["reserved_names"] == {"names": ["Test Sans"], "permission": True}
    assert "rights.reserved-font-name" not in {h["rule_id"] for h in rights_check.check_font(out["entry"])}
    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", "--no-reserved-name-permission",
                    capsys=capsys)
    assert [c["field"] for c in out["changes"]] == ["reserved_names.permission"]
    assert "rights.reserved-font-name" in {h["rule_id"] for h in rights_check.check_font(out["entry"])}


def test_a_modified_ofl_font_needs_evidence_for_its_reserved_names(fonts_db, capsys):
    args = ["Test Sans", "--role", "body", "--task", "demo", "--license-kind", "ofl", "--files", "dist/*.woff",
            "--modified", "converted"]
    code, _ = run(fonts_db, *args, capsys=capsys)
    assert code == 2 and "reserved font names" in capsys.readouterr().err
    assert not (fonts_db.project / ".lapis").exists()
    (fonts_db.project / "OFL.txt").write_text("Copyright 2026 Tests\n\n" + OFL_BODY, encoding="utf-8")
    code, out = run(fonts_db, *args, "--notice", "OFL.txt", capsys=capsys)
    assert code == 0 and out["entry"]["reserved_names"] == {"names": [], "permission": False}  # read: none declared
    assert any("no local file matches 'dist/*.woff'" in note for note in out["notes"])
    assert "shipped_names" not in out["entry"]
    code, _ = run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", "--files", "fonts/*.ttf", capsys=capsys)
    assert code == 0                                                     # --modified stays from the lock


@pytest.mark.skipif(importlib.util.find_spec("brotli") is not None, reason="brotli is installed here")
def test_woff2_without_brotli_records_no_partial_names(fonts_db, capsys):
    (fonts_db.project / "web").mkdir()
    (fonts_db.project / "web" / "TestSans.woff2").write_bytes(b"wOF2" + b"\0" * 44)
    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", "--files", "web/*.woff2",
                    "--modified", "woff-unchanged", capsys=capsys)
    assert code == 0 and "shipped_names" not in out["entry"] and "notices_embedded" not in out["entry"]
    assert any("brotli" in note for note in out["notes"])


def test_usage_errors_and_dry_run(fonts_db, capsys):
    with pytest.raises(SystemExit) as stop:
        lock.main(["Test Sans", "--role", "body", "--task", "demo", "--files", "/abs/font.ttf"])
    assert stop.value.code == 2
    with pytest.raises(SystemExit) as stop:
        lock.main(["Test Sans", "--role", "body", "--task", "demo", "--use", "web=maybe"])
    assert stop.value.code == 2
    code = lock.main(["Test Sans", "--role", "body", "--task", "demo", "--project", str(fonts_db.project),
                      "--dry-run"])
    assert code == 0 and "would add Test Sans (body)" in capsys.readouterr().out
    assert not (fonts_db.project / ".lapis").exists()
    lockfile = fonts_db.project / ".lapis" / "fonts.lock.json"
    lockfile.parent.mkdir()
    lockfile.write_text('{"version": 0, "locked_at": "2026-09-26T00:00:00Z", "fonts": [{"family": "Broken"}]}')
    code = lock.main(["Test Sans", "--role", "body", "--task", "demo", "--project", str(fonts_db.project)])
    assert code == 1 and "nothing written" in capsys.readouterr().err  # another entry is invalid: never written
    assert json.loads(lockfile.read_text())["fonts"] == [{"family": "Broken"}]


def test_reserved_font_name_declarations():
    assert lock.reserved_font_names('Copyright 2010 The Authors, with Reserved Font Name "Source".') == ["Source"]
    assert lock.reserved_font_names("Copyright (c) 2014 X,\nwith Reserved Font Names “Noto” and “Arimo”.") == [
        "Noto", "Arimo"]
    assert lock.reserved_font_names("Copyright 2003 SIL, with Reserved Font Name Gentium.\n") == ["Gentium"]
    assert lock.reserved_font_names("Copyright 2020 A, with Reserved Font Name\n'Nanum'.") == ["Nanum"]
    assert lock.reserved_font_names("Reserved Font Names: Alpha, Beta") == ["Alpha", "Beta"]
    assert lock.reserved_font_names(OFL_BODY) == []                         # the definition, not a declaration


def test_a_generated_lock_satisfies_plan_check(fonts_db, capsys):
    """Acceptance: a lock written by `lazuli lock` from a synthetic-font DB validates and passes check_fonts."""
    shipped = fonts_db.project / "public" / "fonts"
    build(shipped / "TestSans-Regular.ttf", family="Test Sans")
    (shipped / "OFL.txt").write_text("Copyright 2026 Tests\n\n" + OFL_BODY, encoding="utf-8")
    assert run(fonts_db, "Gowun Batang", "--role", "heading", "--task", "demo", capsys=capsys)[0] == 0
    assert run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", "--source", "google-fonts",
               "--delivery", "self-host", "--files", "public/fonts/*.ttf", "--modified", "none",
               "--notice", "public/fonts/OFL.txt", "--license-kind", "ofl", "--use", "web=allowed",
               "--fallback", "system-ui", "sans-serif", capsys=capsys)[0] == 0
    lock_path = fonts_db.project / ".lapis" / "fonts.lock.json"
    assert lock.validate(json.loads(lock_path.read_text())) == []
    plan = yaml.safe_load((SHARED / "plan" / "example.plan.yaml").read_text(encoding="utf-8"))
    plan["task"]["id"] = "demo"
    plan["brief"]["platform"] = ["web"]
    plan["tokens"]["type"]["roles"] = [{"role": "heading", "family": "Gowun Batang", "scripts": ["hang"]},
                                       {"role": "body", "family": "Test Sans", "scripts": ["latn"]}]
    plan_path = fonts_db.project / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    # no slop rules: the schema, contract, fonts, references, and flows checks read the plan and the lock
    report = plan_check.run(plan_path, None, lock_path, SHARED / "plan" / "schema.yaml", fonts_db.project)
    assert report["summary"]["blocking"] == 0
    fonts = [(f["rule_id"], f["location"]["path"], f["blocking"]) for f in report["findings"]
             if f["rule_id"].startswith("font.")]
    # the hosted catalog font keeps its two hint warnings; the declared self-hosted font has none
    assert sorted(fonts) == [("font.license-hint-only", "tokens.type.roles[0]", False),
                             ("font.use-unknown", "tokens.type.roles[0]", False)]
    assert rights_check.check_font(json.loads(lock_path.read_text())["fonts"][1], root=fonts_db.project) == []

    # a DB-only lock of an installed font gets no web delivery path by default, and plan_check gates it
    plan["tokens"]["type"]["roles"].append({"role": "ui", "family": "System Serif"})
    plan_path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    assert run(fonts_db, "System Serif", "--role", "ui", "--task", "demo", capsys=capsys)[0] == 0
    report = plan_check.run(plan_path, None, lock_path, SHARED / "plan" / "schema.yaml", fonts_db.project)
    assert [f["rule_id"] for f in report["findings"] if f["blocking"]] == ["font.no-web-delivery"]


def bundle_test_sans(env) -> None:
    shipped = env.project / "public" / "fonts" / "test-sans"
    build(shipped / "TestSans-Regular.ttf", family="Test Sans")
    (shipped / "OFL.txt").write_text(f"Copyright 2026 Tests\n\n{OFL_BODY}\n{GRANT}, subject to the following "
                                     "conditions:\n", encoding="utf-8")


VERIFIED = ["--source", "google-fonts", "--source-url", SOURCE_URL, "--delivery", "self-host",
            "--files", "public/fonts/test-sans/*.ttf", "--modified", "none",
            "--notice", "public/fonts/test-sans/OFL.txt", "--license-kind", "ofl",
            "--use", "web=allowed", "app=allowed-with-conditions", "--research", "verified",
            "--evidence", "license-file", OFL_URL, "--quote", GRANT]


def test_a_bundled_open_font_is_locked_with_its_source_license_text_and_evidence(fonts_db, capsys):
    """Acceptance: files, license file, and a lock written by `lazuli lock` pass the rights and font checks."""
    bundle_test_sans(fonts_db)
    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", *VERIFIED, capsys=capsys)
    assert code == 0
    entry = read_lock(fonts_db)["fonts"][0]
    assert lock.validate(read_lock(fonts_db)) == []
    assert entry["source_url"] == SOURCE_URL
    license_record = entry["license"]
    assert license_record["source_class"] == "rights-holder"                    # implied by the evidence
    assert license_record["url"] == OFL_URL                                     # the document that was read
    research = license_record["research"]
    assert research["outcome"] == "verified"
    assert research["evidence"] == [{"via": "license-file", "url": OFL_URL, "quote": GRANT,
                                     "checked_at": license_record["checked_at"]}]
    assert rights_check.check_font(entry, root=fonts_db.project) == []
    plan = yaml.safe_load((SHARED / "plan" / "example.plan.yaml").read_text(encoding="utf-8"))
    plan["task"]["id"] = "demo"
    plan["brief"]["platform"] = ["web"]
    plan["tokens"]["type"]["roles"] = [{"role": "body", "family": "Test Sans", "scripts": ["latn"]}]
    plan_path = fonts_db.project / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    report = plan_check.run(plan_path, None, fonts_db.project / ".lapis" / "fonts.lock.json",
                            SHARED / "plan" / "schema.yaml", fonts_db.project)
    assert [f["rule_id"] for f in report["findings"] if f["rule_id"].startswith("font.")] == []


def test_a_quote_the_license_file_does_not_hold_is_refused(fonts_db, capsys):
    bundle_test_sans(fonts_db)
    args = [a if a != GRANT else "Fonts may be used for anything, no conditions" for a in VERIFIED]
    code, _ = run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", *args, capsys=capsys)
    assert code == 2 and "is not in any --notice file" in capsys.readouterr().err
    assert not (fonts_db.project / ".lapis").exists()


def test_research_that_contradicts_itself_is_never_written(fonts_db, capsys):
    bundle_test_sans(fonts_db)
    base = ["Test Sans", "--role", "body", "--task", "demo"]
    a_search_only = ["--evidence", "web-search", "--evidence-note", "searched: Test Sans font license"]
    cases = {
        "does not contain": [*VERIFIED[:-5], *a_search_only],                        # a search is no document
        "'restrictions' is a required property": [*VERIFIED[:-6], "restricted", *VERIFIED[-5:]],
        "'user-declared' is not one of": [*VERIFIED, "--license-class", "user-declared"],
        "'outcome' is a required property": [a for a in VERIFIED if a not in ("--research", "verified")],
        "'notices' is a required property": [a for a in VERIFIED       # the license file's copy is the notice
                                             if a not in ("--notice", "public/fonts/test-sans/OFL.txt")],
    }
    for message, flags in cases.items():
        code, _ = run(fonts_db, *base, *flags, capsys=capsys)
        assert code == 2 and message in capsys.readouterr().err, message
    assert not (fonts_db.project / ".lapis").exists()
    with pytest.raises(SystemExit) as stop:                                          # --quote needs its evidence
        lock.main([*base, "--quote", "words", "--project", str(fonts_db.project)])
    assert stop.value.code == 2


def test_unknown_after_research_is_recorded_kept_and_replaced_by_a_later_finding(fonts_db, capsys):
    searched = ["--research", "unknown-after-research", "--evidence", "web-search", "--evidence-note",
                "searched: Test Sans font license", "--research-note", "no license in its folder, none on the maker page"]
    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", *searched, capsys=capsys)
    assert code == 0
    license_record = out["entry"]["license"]
    assert license_record["kind"] == "unknown" and "source_class" not in license_record
    assert license_record["research"]["outcome"] == "unknown-after-research"
    assert license_record["research"]["evidence"][0]["via"] == "web-search"
    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", capsys=capsys)
    assert out["action"] == "unchanged"                                              # the research is kept
    bundle_test_sans(fonts_db)
    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", *VERIFIED, capsys=capsys)
    assert code == 0 and out["entry"]["license"]["research"]["outcome"] == "verified"
    assert out["entry"]["license"]["uses"]["web"] == "allowed"


def test_installed_files_ship_only_once_the_real_source_and_license_are_recorded(fonts_db, capsys):
    """A locally installed font is usable here; its copy ships when its license was verified and its source named."""
    bundle_test_sans(fonts_db)
    flags = [a for a in VERIFIED if a not in ("--source", "google-fonts", "--source-url", SOURCE_URL)]
    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", *flags, capsys=capsys)
    assert code == 0 and out["entry"]["source"] == "user-installed"
    assert any("user-installed files do not ship" in note for note in out["notes"])
    assert [h["rule_id"] for h in rights_check.check_font(out["entry"], root=fonts_db.project)] == [
        "rights.use-outside-license"]
    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", "--source", "open-source-other",
                    "--source-url", "https://foundry.example/test-sans", capsys=capsys)
    assert code == 0 and rights_check.check_font(out["entry"], root=fonts_db.project) == []


def test_a_bundled_font_nobody_researched_is_flagged_where_it_is_locked(fonts_db, capsys):
    bundle_test_sans(fonts_db)
    code, out = run(fonts_db, "Test Sans", "--role", "body", "--task", "demo", "--source", "open-source-other",
                    "--delivery", "self-host", "--files", "public/fonts/test-sans/*.ttf", "--modified", "none",
                    capsys=capsys)
    assert code == 0
    entry = out["entry"]                                                   # the catalog's OFL label is a hint only
    assert entry["license"]["source_class"] == "catalog-summary" and "research" not in entry["license"]
    assert {h["rule_id"] for h in rights_check.check_font(entry, root=fonts_db.project)} == {
        "rights.license-hint-only", "rights.license-unknown", "rights.notice-missing"}
