"""The checks in assets/CHECKS.md, pinned with small cases."""
import copy
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from PIL import Image

from lapis_design.render.fields import media as media_field
from lapis_design.rights_check import check, check_entry, check_font, check_render, coverage, shipped_files

SHARED = Path(__file__).resolve().parents[1] / "src" / "shared"
TODAY = dt.date(2026, 9, 25)


def example(rel):
    return json.loads((SHARED / rel).read_text(encoding="utf-8"))


def entry(entry_id):
    return copy.deepcopy(next(e for e in example("assets/example.assets.ledger.json")["assets"] if e["id"] == entry_id))


def rules(hits):
    return sorted(h["rule_id"] for h in hits)

def render_with_media(source_url, media_host, addresses=None):
    source = {"kind": "render", "url": source_url}
    if addresses is not None:
        source["addresses"] = addresses
    return {"source": source, "viewports": [{"boxes": [
        {"id": "image", "role": "media", "media": {"kind": "img", "host": media_host, "loaded": True}}
    ]}]}


def test_own_origin_image_is_left_to_source_coverage():
    extract = render_with_media("http://127.0.0.1:8000/", "127.0.0.1")
    assert check_render(extract, {"assets": []}) == []


def test_private_image_at_another_port_is_left_to_source_coverage():
    source_url = "http://127.0.0.1:8000/"
    other_port_url = "http://127.0.0.1:8001/photo.jpg"
    extract = render_with_media(source_url, urlsplit(other_port_url).hostname)
    assert check_render(extract, {"assets": []}) == []
    for host in ("localhost", "assets.localhost", "192.168.0.12", "::1"):
        extract["viewports"][0]["boxes"][0]["media"]["host"] = host
        assert check_render(extract, {"assets": []}) == []


def test_public_source_own_image_still_requires_provenance():
    extract = render_with_media("https://public.invalid/", "public.invalid")
    assert rules(check_render(extract, {"assets": []})) == ["rights.no-provenance"]
    extract["viewports"][0]["boxes"][0]["media"]["host"] = "localhost"
    assert rules(check_render(extract, {"assets": []})) == ["rights.no-provenance"]


def test_remote_image_still_requires_provenance():
    extract = render_with_media("http://127.0.0.1:8000/", "cdn.example")
    assert rules(check_render(extract, {"assets": []})) == ["rights.no-provenance"]


def test_pinned_test_source_skips_local_but_not_remote_media():
    extract = render_with_media("http://app.test/", "app.test", ["127.0.0.1"])
    assert check_render(extract, {"assets": []}) == []
    extract["viewports"][0]["boxes"][0]["media"]["host"] = "cdn.example"
    assert rules(check_render(extract, {"assets": []})) == ["rights.no-provenance"]
    extract["viewports"][0]["boxes"][0]["media"]["host"] = "app.test"
    extract["source"]["addresses"] = ["127.0.0.1", "203.0.113.9"]
    assert rules(check_render(extract, {"assets": []})) == ["rights.no-provenance"]
    extract["source"].pop("addresses")
    extract["viewports"][0]["boxes"][0]["media"]["host"] = "app.test"
    assert rules(check_render(extract, {"assets": []})) == ["rights.no-provenance"]


def test_same_origin_image_proxy_keeps_inner_host_remote():
    source = "http://127.0.0.1:8000/_next/image?url=https%3A%2F%2Fcdn.example%2Fx.jpg&w=640"
    image = {"tag": "img", "class": "", "sprite": None, "module": "", "glyph": "",
             "svg": False, "iconImage": False, "iconOnly": False, "grid": None, "stroke": None,
             "source": source, "url": None, "alt": "Photo", "hidden": False, "natural_w": 32,
             "natural_h": 32, "intrinsic": True, "complete": True}
    box = {"id": "image", "role": "media", "paint_order": 0,
           "rect": {"x": 0, "y": 0, "w": 32, "h": 32}, "style": {}}
    view = SimpleNamespace(page=SimpleNamespace(url="http://127.0.0.1:8000/",
                                                evaluate=lambda _script: {"image": image}),
                           config={"dpr": 1})
    viewport = {"boxes": [box]}
    media_field.apply(view, viewport, {"image": {"backgroundImage": "none"}}, Image.new("RGB", (32, 32)))
    assert box["media"]["host"] == "cdn.example"
    extract = render_with_media(view.page.url, box["media"]["host"])
    assert rules(check_render(extract, {"assets": []})) == ["rights.no-provenance"]
    view.page.url = "https://other.invalid/"
    media_field.apply(view, viewport, {"image": {"backgroundImage": "none"}}, Image.new("RGB", (32, 32)))
    assert box["media"]["host"] == "127.0.0.1"


def test_unlisted_file_under_scan_root_remains_source_finding(tmp_path):
    (tmp_path / "public").mkdir()
    (tmp_path / "public/unlisted.jpg").write_bytes(b"fixture image")
    ledger = {"assets": [], "scan": {"roots": ["public"]}}
    extract = render_with_media("http://127.0.0.1:8000/", "127.0.0.1")
    hits = check(ledger, None, tmp_path, TODAY, [extract])
    assert [(hit["layer"], hit["subject"], hit["rule_id"]) for hit in hits] == [
        ("source", "public/unlisted.jpg", "rights.no-provenance")
    ]


def test_shipped_files_need_a_record(tmp_path):
    (tmp_path / "public/images/archive").mkdir(parents=True)
    (tmp_path / "public/fonts/pretendard").mkdir(parents=True)
    (tmp_path / "public/images/kiln-hero-1600.jpg").write_bytes(b"hero")
    (tmp_path / "public/images/stray.png").write_bytes(b"stray")
    (tmp_path / "public/fonts/pretendard/Pretendard-Regular.woff2").write_bytes(b"font")
    (tmp_path / "public/fonts/cached.woff2").write_bytes(b"cache")
    (tmp_path / "public/robots.txt").write_text("")
    ledger, lock = example("assets/example.assets.ledger.json"), example("fonts/example.fonts.lock.json")
    shipped = shipped_files(tmp_path, ledger)
    assert [f["path"] for f in shipped] == ["public/fonts/cached.woff2", "public/fonts/pretendard/Pretendard-Regular.woff2",
                                            "public/images/kiln-hero-1600.jpg", "public/images/stray.png"]
    assert [h["subject"] for h in coverage(shipped, ledger, lock)] == ["public/fonts/cached.woff2", "public/images/stray.png"]


def test_a_matching_hash_covers_a_renamed_file():
    ledger = {"assets": [{"id": "x", "files": [{"path": "public/a.png", "sha256": "ab" * 32}]}]}
    assert coverage([{"path": "public/b.png", "sha256": "ab" * 32}], ledger, None) == []


def test_unknown_and_hinted_licenses():
    e = entry("celadon-texture")
    e["rights"]["source_class"] = "catalog-summary"
    assert rules(check_entry(e, TODAY)) == ["rights.license-hint-only"]
    e["origin"] = "unknown"
    assert rules(check_entry(e, TODAY)) == ["rights.license-unknown"]


def test_use_beyond_the_license():
    e = entry("kiln-1978")                                              # cc-by, commercial, not promotional
    assert check_entry(e, TODAY) == []
    e["rights"]["license"] = "cc-by-nc"
    assert rules(check_entry(e, TODAY)) == ["rights.use-outside-license"]
    e["rights"]["license"] = "editorial"
    e.pop("attribution")
    assert rules(check_entry(e, TODAY)) == ["rights.use-outside-license"]   # a shop page is not editorial use
    e["use"]["editorial"] = True
    assert check_entry(e, TODAY) == []                                  # reporting inside a commercial site
    e["use"]["promotional"] = True
    assert rules(check_entry(e, TODAY)) == ["rights.use-outside-license"]
    e = entry("kiln-1978")
    e["rights"]["license"] = "cc-by-nd"
    assert check_entry(e, TODAY) == []                                  # cropping is not a derivative here
    e["modified"] = "composited"
    assert rules(check_entry(e, TODAY)) == ["rights.use-outside-license"]
    del e["modified"]
    assert rules(check_entry(e, TODAY)) == ["rights.use-outside-license"]   # not recorded


def test_documented_licenses_need_their_document():
    e = entry("courier-mark")
    del e["rights"]["evidence"]
    hits = check_entry(e, TODAY)
    assert rules(hits) == ["rights.license-unknown"] and "document" in hits[0]["observed"]


def test_platform_bound_licenses():
    e = entry("ui-icons")
    e["rights"]["restrictions"] = ["platform-bound"]
    e["rights"]["platforms"] = ["ios"]
    hits = check_entry(e, TODAY)
    assert rules(hits) == ["rights.use-outside-license"] and "web" in hits[0]["observed"]


def test_expiry():
    e = entry("courier-mark")
    assert check_entry(e, TODAY) == []
    assert rules(check_entry(e, dt.date(2027, 4, 1))) == ["rights.license-expired"]


def test_credit_and_notices_are_separate():
    e = entry("kiln-1978")
    e["attribution"] = {"required": False}
    assert rules(check_entry(e, TODAY)) == ["rights.attribution-missing"]
    icons = entry("ui-icons")
    icons["notices"] = []
    assert rules(check_entry(icons, TODAY)) == ["rights.notice-missing"]
    icons["notices_embedded"] = True
    assert check_entry(icons, TODAY) == []                              # notices kept inside the files
    icons["rights"]["license"] = "apache"
    assert rules(check_entry(icons, TODAY)) == ["rights.notice-missing"]   # needs a copy of the license text


def test_open_license_credit_details():
    e = entry("kiln-1978")
    del e["attribution"]["license_url"]
    assert rules(check_entry(e, TODAY)) == ["rights.attribution-missing"]
    e = entry("kiln-1978")
    e["attribution"]["placement"] = "docs"
    assert rules(check_entry(e, TODAY)) == ["rights.attribution-missing"]   # viewers never see it
    e = entry("kiln-1978")
    e["attribution"]["indicates_changes"] = False
    assert rules(check_entry(e, TODAY)) == ["rights.attribution-missing"]   # the crop goes unmentioned


def test_notice_files_must_exist(tmp_path):
    icons = entry("ui-icons")
    assert rules(check_entry(icons, TODAY, tmp_path)) == ["rights.notice-missing"]
    (tmp_path / "public/licenses").mkdir(parents=True)
    (tmp_path / "public/licenses/icons.txt").write_text("ISC")
    assert check_entry(icons, TODAY, tmp_path) == []


def test_marks():
    e = entry("courier-mark")
    e["mark"]["authorization"] = "unknown"
    assert rules(check_entry(e, TODAY)) == ["rights.unverified-mark"]
    e["mark"].update(relationship="partner", authorization="not-needed")
    assert rules(check_entry(e, TODAY)) == ["rights.unverified-mark"]   # a claimed relationship needs confirmation
    e["mark"].update(relationship="compatibility")
    assert check_entry(e, TODAY) == []


def test_generated_media():
    e = entry("notice-illustration")
    e["role"] = "evidentiary"
    e["generated"].update(inputs=["reference-only"], reviewed=False)
    assert rules(check_entry(e, TODAY)) == ["rights.generated-as-evidence", "rights.generated-from-reference",
                                            "rights.generated-unreviewed"]


def test_releases_for_people_and_property():
    e = entry("kiln-hero")
    e["releases"] = {"people": "obtained"}                             # property not recorded
    assert rules(check_entry(e, TODAY)) == ["rights.release-missing"]
    e["use"].update(commercial=False, promotional=False)
    assert check_entry(e, TODAY) == []
    e = entry("kiln-hero")
    e["releases"] = {"people": "synthetic", "property": "none-depicted"}
    assert rules(check_entry(e, TODAY)) == ["rights.release-missing"]  # only generated media can be synthetic
    g = entry("notice-illustration")
    g["kind"] = "photo"
    g["releases"] = {"people": "synthetic", "property": "synthetic"}
    assert check_entry(g, TODAY) == []


def test_generator_inputs_follow_their_own_licenses():
    ledger = example("assets/example.assets.ledger.json")
    g = next(e for e in ledger["assets"] if e["id"] == "notice-illustration")
    g["generated"].update(inputs=["licensed"], input_assets=["celadon-texture", "missing-id"])
    texture = next(e for e in ledger["assets"] if e["id"] == "celadon-texture")
    texture["rights"]["restrictions"] = ["no-generator-input"]
    hits = check_entry(g, TODAY, None, ledger)
    assert sorted((h["rule_id"], h["subject"]) for h in hits) == [
        ("rights.no-provenance", "notice-illustration"), ("rights.use-outside-license", "celadon-texture")]


def test_fonts_that_ship_need_a_grant_and_a_clean_channel():
    font = copy.deepcopy(example("fonts/example.fonts.lock.json")["fonts"][0])
    font["source"] = "adobe-sync"
    assert rules(check_font(font)) == ["rights.use-outside-license"]
    font = copy.deepcopy(example("fonts/example.fonts.lock.json")["fonts"][0])
    font["license"]["uses"] = {}
    assert rules(check_font(font)) == ["rights.license-unknown"]


LICENSE_TEXT = ("Copyright 2021 The Gowun Batang Project Authors\n\nThis Font Software is licensed under the SIL Open "
                "Font License, Version 1.1.\n\nSIL OPEN FONT LICENSE Version 1.1 - 26 February 2007\n")


def bundled(tmp_path, notice_text=LICENSE_TEXT):
    """The example's first font, with its notice file written under a project root."""
    font = copy.deepcopy(example("fonts/example.fonts.lock.json")["fonts"][0])
    notice = tmp_path / font["notices"][0]
    notice.parent.mkdir(parents=True, exist_ok=True)
    if notice_text is not None:
        notice.write_text(notice_text, encoding="utf-8")
    return font


def test_a_bundled_open_font_with_its_license_text_and_research_is_accepted(tmp_path):
    assert check_font(bundled(tmp_path), root=tmp_path) == []
    apache = bundled(tmp_path, "Apache License\nVersion 2.0, January 2004\n")
    apache["license"]["kind"] = "apache"
    assert check_font(apache, root=tmp_path) == []


def test_a_bundled_font_whose_notice_is_not_the_license_text_is_flagged(tmp_path):
    for text in ("", "404: Not Found", "Gowun Batang, a Korean serif.\nSee the website for terms.\n"):
        hits = check_font(bundled(tmp_path, text), root=tmp_path)
        assert [(h["rule_id"], h["observed"]) for h in hits] == [
            ("rights.notice-missing", "no notice file holds the ofl license text")]
    apache = bundled(tmp_path)                                         # the OFL text is not the Apache License
    apache["license"]["kind"] = "apache"
    assert rules(check_font(apache, root=tmp_path)) == ["rights.notice-missing"]
    bare = tmp_path / "bare"
    assert rules(check_font(bundled(bare, None), root=bare)) == ["rights.notice-missing"]   # no file at all


def test_a_bundled_font_with_only_a_hint_for_its_license_is_flagged(tmp_path):
    for hint in ("catalog-summary", "file-metadata"):
        font = bundled(tmp_path)
        font["license"]["source_class"] = hint
        del font["license"]["research"]
        assert rules(check_font(font, root=tmp_path)) == ["rights.license-hint-only"]
    font = bundled(tmp_path)
    del font["files"], font["modified"], font["notices"]                # not shipped: nothing to evidence yet
    font["license"]["source_class"] = "catalog-summary"
    assert check_font(font, root=tmp_path) == []


def test_an_unknown_license_is_never_researched_or_unknown_after_research(tmp_path):
    font = bundled(tmp_path)
    font["license"] = {"kind": "unknown", "checked_at": "2026-10-04"}
    [never] = check_font(font, root=tmp_path)
    assert never["rule_id"] == "rights.license-unresearched" and "no research is recorded" in never["observed"]
    font["license"]["research"] = {
        "outcome": "unknown-after-research", "note": "no license in the folder, none on the foundry page",
        "evidence": [{"via": "web-search", "note": "searched: Gowun Batang font license", "checked_at": "2026-10-04"}]}
    [searched] = check_font(font, root=tmp_path)
    assert searched["rule_id"] == "rights.license-unknown"
    assert "no license in the folder, none on the foundry page" in searched["observed"]
    del font["files"], font["modified"], font["notices"]                # a candidate that does not ship is no hit
    assert check_font(font, root=tmp_path) == []


def test_app_bundled_fonts_need_an_app_grant():
    font = copy.deepcopy(example("fonts/example.fonts.lock.json")["fonts"][0])
    font["delivery"] = "app-bundle"
    font["license"]["uses"] = {"web": "allowed"}
    assert rules(check_font(font)) == ["rights.license-unknown"]
    font["license"]["uses"]["app"] = "not-allowed"
    assert rules(check_font(font)) == ["rights.use-outside-license"]


def test_font_notices_and_reserved_names():
    font = copy.deepcopy(example("fonts/example.fonts.lock.json")["fonts"][0])
    assert check_font(font) == []
    font["notices"] = []
    assert rules(check_font(font)) == ["rights.notice-missing"]
    font["notices_embedded"] = True
    assert check_font(font) == []                                       # name records inside the files
    font["notices"] = ["public/fonts/OFL.txt"]
    font["modified"] = "subset"
    assert rules(check_font(font)) == ["rights.reserved-font-name"]    # reserved names not recorded
    font["reserved_names"] = {"names": ["Gowun"], "permission": False}
    font["modified"] = "woff-unchanged"
    assert check_font(font) == []                                       # woff-unchanged is not a modification
    font["modified"] = "subset"
    assert rules(check_font(font)) == ["rights.reserved-font-name"]    # shipped names not recorded
    font["shipped_names"] = ["GowunBatang-Regular"]
    assert rules(check_font(font)) == ["rights.reserved-font-name"]
    font["shipped_names"] = ["KilnSerif-Regular"]
    assert check_font(font) == []
    font["shipped_names"] = ["GowunBatang-Regular"]
    font["reserved_names"]["permission"] = True
    assert check_font(font) == []


def test_render_media_libraries_and_symbols():
    ledger = example("assets/example.assets.ledger.json")
    extract = example("render/example.extract.json")
    vp = extract["viewports"][0]
    vp["boxes"].append({"id": "b0000000000aa", "role": "media",
                        "media": {"kind": "img", "host": "cdn.example.net", "loaded": True, "phash": "00000000000000ff"}})
    vp["boxes"].append({"id": "b0000000000ab", "role": "icon", "icon": {"kind": "svg", "library": "other-icons"}})
    vp["text"].append({"id": "t99", "box": "b0000000000ac", "text": "Kiln shop\u00ae and Other\u00ae"})
    assert rules(check_render(extract, ledger)) == ["rights.no-provenance", "rights.no-provenance",
                                                    "rights.unapproved-mark-symbol"]
    hero = next(e for e in ledger["assets"] if e["id"] == "kiln-hero")
    hero["phashes"] = ["00000000000000f0"]                             # 4 bits away: a resized copy
    next(e for e in ledger["assets"] if e["id"] == "studio-logo")["mark"]["symbols"] = ["registered"]
    assert rules(check_render(extract, ledger)) == ["rights.no-provenance", "rights.unapproved-mark-symbol"]
    vp["text"][-1]["text"] = "Kiln shop\u00ae"                         # the approved mark only
    assert rules(check_render(extract, ledger)) == ["rights.no-provenance"]
    extract["source"]["kind"] = "site"                                  # reference captures are not checked
    assert check_render(extract, ledger) == []


def test_user_content_hosts_cover_every_item():
    ledger = example("assets/example.assets.ledger.json")
    extract = example("render/example.extract.json")
    extract["viewports"][0]["boxes"].append({"id": "b0000000000ad", "role": "media", "media": {
        "kind": "img", "host": "uploads.example.net", "loaded": True, "phash": "1234567890abcdef"}})
    assert rules(check_render(extract, ledger)) == ["rights.no-provenance"]
    ledger["assets"].append({
        "id": "member-uploads", "kind": "photo", "role": "informative", "origin": "user-content",
        "hosts": ["uploads.example.net"],
        "rights": {"license": "user-terms", "source_class": "rights-holder",
                   "evidence": {"kind": "url", "ref": "https://example.com/terms"}},
        "use": {"channels": ["web"], "commercial": True, "promotional": False},
        "used_by": ["kiln-shop-landing"], "checked_at": "2026-09-24"})
    assert check_render(extract, ledger) == []
    assert check_entry(ledger["assets"][-1], TODAY) == []               # releases are not asked of user uploads


def test_check_runs_everything(tmp_path):
    ledger = example("assets/example.assets.ledger.json")
    lock = example("fonts/example.fonts.lock.json")
    hits = check(ledger, lock, tmp_path, TODAY)
    assert {h["rule_id"] for h in hits} == {"rights.notice-missing"}   # notice files absent from an empty tree
