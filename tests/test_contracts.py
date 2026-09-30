"""Contract tests: schemas are valid, examples pass, negative cases fail."""
import copy
import json
import re
import sqlite3
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator as V

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "src" / "shared"


def load(rel):
    return yaml.safe_load((SHARED / rel).read_text(encoding="utf-8"))


def validator(rel):
    schema = load(rel)
    V.check_schema(schema)
    return V(schema)


SCHEMAS = ["plan/schema.yaml", "render/extract.schema.yaml", "slop/rules.schema.yaml",
           "slop/finding.schema.yaml", "fonts/lock.schema.yaml", "behavior/session.schema.yaml",
           "assets/ledger.schema.yaml"]


@pytest.mark.parametrize("rel", SCHEMAS)
def test_schema_is_valid(rel):
    validator(rel)


def test_finding_report_accepts_optional_analyzers_by_locale():
    report = {"version": 0, "tool": {"name": "slop_lint", "version": "0.1"},
              "target": {}, "findings": [], "analyzers": {"ko": "kiwipiepy 0.24.0"}}
    v = validator("slop/finding.schema.yaml")
    assert list(v.iter_errors(report)) == []
    report["analyzers"]["ko"] = 24
    assert list(v.iter_errors(report))

def test_plan_example_passes():
    assert list(validator("plan/schema.yaml").iter_errors(load("plan/example.plan.yaml"))) == []


def test_plan_rejects_reuse_of_reference_only():
    plan = load("plan/example.plan.yaml")
    plan["references"][0]["mode"] = "reuse"
    assert list(validator("plan/schema.yaml").iter_errors(plan))


def test_plan_create_requires_world_materials():
    plan = load("plan/example.plan.yaml")
    del plan["world_materials"]
    assert list(validator("plan/schema.yaml").iter_errors(plan))


def test_plan_dials_are_fixed_names():
    plan = load("plan/example.plan.yaml")
    plan["direction"]["dials"]["expression"] = 3
    assert list(validator("plan/schema.yaml").iter_errors(plan))


def test_rules_example_passes():
    assert list(validator("slop/rules.schema.yaml").iter_errors(load("slop/rules.example.yaml"))) == []


def test_requirement_rules_cannot_be_waived():
    rules = load("slop/rules.example.yaml")
    req = next(r for r in rules["rules"] if r["class"] == "requirement")
    req["waiver"] = {"scope": "value"}
    assert list(validator("slop/rules.schema.yaml").iter_errors(rules))


RULE_FILES = ["slop/rules.yaml", "slop/rules.example.yaml"]


@pytest.mark.parametrize("rel", RULE_FILES)
def test_rule_detectors_are_registered_for_their_layer(rel):
    registry = {d["name"]: d for d in load("slop/detectors.yaml")["detectors"]}
    problems = []
    for r in load(rel)["rules"]:
        for layer, det in (r.get("detect") or {}).items():
            name = det.get("detector")
            if name not in registry:
                problems.append(f"{r['id']}: {name} is not registered")
            elif layer not in registry[name]["layers"]:
                problems.append(f"{r['id']}: {name} is not registered for layer {layer}")
            if layer not in r["layers"]:
                problems.append(f"{r['id']}: detect.{layer} is not in layers")
    assert problems == []


def test_detector_names_are_unique():
    names = [d["name"] for d in load("slop/detectors.yaml")["detectors"]]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------- rules.yaml

def rules_doc():
    return load("slop/rules.yaml")


def test_rules_pass_schema():
    assert list(validator("slop/rules.schema.yaml").iter_errors(rules_doc())) == []


def test_rule_ids_are_unique_and_prefixed_by_domain():
    rules = rules_doc()["rules"]
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids))
    assert [r["id"] for r in rules if r["id"].split(".")[0] != r["domain"]] == []


def test_severity_policy():
    bad = []
    for r in rules_doc()["rules"]:
        create, review = r["severity"]["create"], r["severity"]["review"]
        if r["class"] in ("requirement", "contract") and create != "gate":
            bad.append(r["id"])
        if r["class"] == "quality" and (review in ("P0", "P1")) != (create == "gate"):
            bad.append(r["id"])
    assert bad == []


def test_list_and_family_references_exist():
    doc = rules_doc()
    lists = set(doc.get("lists", {}))
    refs = {(r["id"], det[k]) for r in doc["rules"] for det in (r.get("detect") or {}).values()
            for k in ("list", "family") if k in det}
    assert [ref for ref in refs if ref[1] not in lists] == []


def test_packages_and_members_agree():
    doc = rules_doc()
    by_id = {r["id"]: r for r in doc["rules"]}
    problems = []
    for name, pkg in doc["packages"].items():
        for m in pkg["members"]:
            if name not in (by_id.get(m) or {}).get("packages", []):
                problems.append(f"{name} lists {m}, which does not list the package")
    for r in doc["rules"]:
        for name in r.get("packages", []):
            if r["id"] not in doc["packages"].get(name, {}).get("members", []):
                problems.append(f"{r['id']} lists {name}, which does not list the rule")
        for det in (r.get("detect") or {}).values():
            if det.get("detector") == "package-hit" and det["params"]["package"] not in doc["packages"]:
                problems.append(f"{r['id']} points at an unknown package")
    assert problems == []


def _nulls(node, path=()):
    """Yield paths of null values; a comma inside a YAML flow collection creates these silently."""
    if isinstance(node, dict):
        for k, v in node.items():
            if v is None:
                yield path + (k,)
            yield from _nulls(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _nulls(v, path + (i,))


@pytest.mark.parametrize("rel", RULE_FILES + ["slop/detectors.yaml"])
def test_no_null_values(rel):
    assert list(_nulls(load(rel))) == []


FRAGMENT_STARTS = ("such as", "or ", "and ", "where ", "which ", "including ", "drawn ", "placed ")


def test_keep_when_items_are_whole_conditions():
    bad = [(r["id"], k) for r in rules_doc()["rules"] for k in r.get("keep_when", [])
           if k.lower().startswith(FRAGMENT_STARTS) or len(k) < 8]
    assert bad == []


def test_every_observed_layer_has_a_detector_except_review():
    bad = [(r["id"], layer) for r in rules_doc()["rules"] for layer in r["layers"]
           if layer != "review" and layer not in (r.get("detect") or {})]
    assert bad == []


STATISTICAL = {"typicality-distance", "image-embedding-region", "copy-family-rate", "rhetorical-shell",
               "construction-rate", "punctuation-density", "rhythm-variance", "formatting-residue",
               "separator-shape", "meta-text", "placeholder-genericness", "register-consistency"}


def test_defaults_on_statistical_detectors_only_warn():
    bad = [r["id"] for r in rules_doc()["rules"] if r["class"] == "default"
           and r["severity"]["create"] == "gate"
           and {d["detector"] for d in (r.get("detect") or {}).values()} & STATISTICAL]
    assert bad == []


def test_example_rules_match_rules():
    real = {r["id"]: r for r in rules_doc()["rules"]}
    for r in load("slop/rules.example.yaml")["rules"]:
        assert r["id"] in real, r["id"]
        for key in ("class", "domain", "severity"):
            assert r[key] == real[r["id"]][key], (r["id"], key)


def test_trace_covers_every_original_entry():
    trace = yaml.safe_load((ROOT / "tools/slop-id-trace.yaml").read_text(encoding="utf-8"))
    ids = {r["id"] for r in rules_doc()["rules"]}
    assert len(trace["checklist"]) == 73
    assert sum(len(rows) for rows in trace["anti_slop"].values()) == 107
    entries = {f"checklist#{k}": v["rules"] for k, v in trace["checklist"].items()}
    entries.update({f"anti-slop#{c}.{i}": v["rules"] for c, rows in trace["anti_slop"].items()
                    for i, v in rows.items()})
    assert [k for k, v in entries.items() if not v or not set(v) <= ids] == []
    from_provenance = {}
    for r in rules_doc()["rules"]:
        for p in r.get("provenance", []):
            if p["source"] in entries:
                from_provenance.setdefault(p["source"], []).append(r["id"])
    assert {k: sorted(v) for k, v in entries.items()} == {k: sorted(v) for k, v in from_provenance.items()}


def test_lock_example_passes():
    lock = json.loads((SHARED / "fonts/example.fonts.lock.json").read_text(encoding="utf-8"))
    assert list(validator("fonts/lock.schema.yaml").iter_errors(lock)) == []


def ledger_example():
    return json.loads((SHARED / "assets/example.assets.ledger.json").read_text(encoding="utf-8"))


def test_ledger_example_passes():
    assert list(validator("assets/ledger.schema.yaml").iter_errors(ledger_example())) == []


@pytest.mark.parametrize("field", ["mark", "generated"])
def test_ledger_requires_mark_and_generation_records(field):
    doc = ledger_example()
    entry = next(e for e in doc["assets"] if field in e)
    del entry[field]
    assert list(validator("assets/ledger.schema.yaml").iter_errors(doc))


def test_ledger_credit_needs_text_and_placement():
    doc = ledger_example()
    entry = next(e for e in doc["assets"] if (e.get("attribution") or {}).get("required"))
    del entry["attribution"]["placement"]
    assert list(validator("assets/ledger.schema.yaml").iter_errors(doc))


def test_ledger_entries_cover_something():
    doc = ledger_example()
    entry = next(e for e in doc["assets"] if "files" in e)
    del entry["files"]
    assert list(validator("assets/ledger.schema.yaml").iter_errors(doc))


def test_ledger_paths_stay_inside_the_repository():
    doc = ledger_example()
    doc["assets"][0]["files"][0]["path"] = "../elsewhere/logo.svg"
    assert list(validator("assets/ledger.schema.yaml").iter_errors(doc))


def test_user_content_entries_stay_narrow():
    doc = ledger_example()
    entry = next(e for e in doc["assets"] if e["id"] == "celadon-texture")
    entry["origin"] = "user-content"                                  # a stock host passed off as uploads
    entry["hosts"] = ["cdn.example.net"]
    assert list(validator("assets/ledger.schema.yaml").iter_errors(doc))
    del entry["files"]
    entry["rights"] = {"license": "user-terms", "source_class": "rights-holder",
                       "evidence": {"kind": "url", "ref": "https://example.com/terms"}}
    assert list(validator("assets/ledger.schema.yaml").iter_errors(doc)) == []


def test_rights_examples_are_clean():
    from lapis_design.rights_check import check
    import datetime as dt
    lock = json.loads((SHARED / "fonts/example.fonts.lock.json").read_text(encoding="utf-8"))
    extract = json.loads((SHARED / "render/example.extract.json").read_text(encoding="utf-8"))
    assert check(ledger_example(), lock, None, dt.date(2026, 9, 25), [extract]) == []


def test_detector_ledger_and_lock_reads_exist():
    ledger, lock = load("assets/ledger.schema.yaml"), load("fonts/lock.schema.yaml")
    lock.setdefault("$defs", {})
    missing = [(d["name"], p) for d in load("slop/detectors.yaml")["detectors"]
               for p in d.get("reads_ledger", []) if not _schema_path_exists(ledger, p)]
    missing += [(d["name"], p) for d in load("slop/detectors.yaml")["detectors"]
                for p in d.get("reads_lock", []) if not _schema_path_exists(lock, p)]
    assert missing == []


def test_rights_rules_use_checks_the_reference_code_emits():
    import re
    code = (ROOT / "cli/lapis_design/rights_check.py").read_text(encoding="utf-8")
    emitted = {f"rights.{m}" for m in re.findall(r'_hit\("([a-z-]+)"', code)}
    rules = {r["id"] for r in rules_doc()["rules"] if r["domain"] == "rights"}
    assert rules == emitted


def test_extract_reference_requires_rights():
    v = validator("render/extract.schema.yaml")
    doc = {"version": 1, "meta": {"extractor": {"name": "lazuli-ref", "version": "0"},
                                  "generated_at": "2026-09-24T00:00:00Z"},
           "source": {"kind": "image", "path": "ref.png"},
           "image": {"palette": [{"oklch": [0.6, 0.13, 40], "share": 0.2}]}}
    assert list(v.iter_errors(doc))
    doc["reference"] = {"rights": "reference-only"}
    assert list(v.iter_errors(doc)) == []


def test_index_paths_exist_unless_planned():
    for item in load("index.yaml")["items"]:
        if item.get("status") == "planned":
            continue
        assert (SHARED / item["path"]).exists(), item["id"]


def test_vocab_files_parse():
    for rel in ["vocab/type.yaml", "vocab/color.yaml", "vocab/glossary.yaml", "fonts/system-fonts.yaml"]:
        assert load(rel)["version"] == 0


def _type_vocab_values() -> dict[str, set]:
    """Feature key -> values a face can have: PANOSE classes, x_height_size, and the boolean metrics."""
    vocab = load("vocab/type.yaml")
    values = {d["id"]: set(d["values"].values()) for d in vocab["panose_latin_text"]}
    x_height = next(d for d in vocab["panose_latin_text"] if d["id"] == "x_height")
    values["x_height_size"] = set(x_height["thresholds"])
    values |= {key: {True, False} for key in ("serif", "italic", "monospaced")}
    return values


def test_font_feature_regions_use_measured_features_and_cover_every_listed_region():
    known = _type_vocab_values()
    regions = load("vocab/type.yaml")["font_feature_regions"]
    ids = [r["id"] for r in regions]
    assert len(ids) == len(set(ids))
    for region in regions:
        clauses = {k: region[k] for k in ("when", "unless", "when_any") if k in region}
        assert clauses and set(region) <= {"id", "means", "when", "unless", "when_any"}, region["id"]
        for clause in clauses.values():
            for key, value in clause.items():
                wanted = set(value) if isinstance(value, list) else {value}
                assert key in known and wanted <= known[key], (region["id"], key, wanted)
    rules = rules_doc()
    region_lists = {r["detect"][layer]["list"] for r in rules["rules"] for layer in r.get("detect", {})
                    if r["detect"][layer].get("detector") in ("plan-font-region", "rendered-family-region")}
    named = {name for key in region_lists for names in rules["lists"][key]["values"].values() for name in names}
    assert named and named <= set(ids)


def test_square_spread_bound_is_an_uncalibrated_seed():
    spread = next(m for m in load("vocab/type.yaml")["cjk_measurements"] if m["id"] == "square_spread")
    assert spread["thresholds"] == {"tal-nemo": 0.1, "square": 0}
    assert spread["calibration"] == "uncalibrated-seed"


def test_system_fonts_classes_and_license_come_from_the_type_vocabulary():
    vocab = load("vocab/type.yaml")
    classes = {g["id"] for g in vocab["latin_genres"]} | {c["id"] for c in vocab["hangul_classes"]} | {
        f"{c['id']}.{s['id']}" for c in vocab["hangul_classes"] for s in c.get("subclasses", ())}
    table = load("fonts/system-fonts.yaml")
    assert {f["class"] for f in table["fonts"]} - classes == {"generic"}          # CSS generic keywords
    assert table["defaults"]["license"] in {entry["id"] for entry in vocab["license_ids"]}


def test_system_fonts_verified_markers():
    fonts = load("fonts/system-fonts.yaml")["fonts"]
    marker = r"reviewed-\d{4}-\d{2}-\d{2}|scanned-\d{4}-\d{2}-\d{2}-[a-z0-9]+|unverified|keyword"
    assert [f["family"] for f in fonts if not re.fullmatch(marker, f["verified"])] == []
    # a keyword is not a font lazuli can find, so it is never waiting to be verified
    assert [f["family"] for f in fonts if f["verified"] == "keyword" and f["class"] != "generic"] == []
    assert [f["family"] for f in fonts if f["class"] == "generic" and f["verified"] == "unverified"] == []
    assert next(f for f in fonts if f["family"] == "ui-monospace")["verified"] == "keyword"


def test_lazuli_db_migration_runs():
    con = sqlite3.connect(":memory:")
    con.executescript((ROOT / "cli/lazuli/db/migrations/0001_init.sql").read_text(encoding="utf-8"))
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1


# ---------------------------------------------------------------- render extract v1

def extract_example():
    return json.loads((SHARED / "render/example.extract.json").read_text(encoding="utf-8"))


def test_extract_example_passes():
    assert list(validator("render/extract.schema.yaml").iter_errors(extract_example())) == []


def test_extract_example_covers_release_render_matrix():
    doc = extract_example()
    assert doc["meta"]["dark_theme"] is True
    captures = {(vp["width"], vp["theme"], vp["reduced_motion"], vp["browser_chrome"])
                for vp in doc["viewports"]}
    assert captures == {
        (320, "light", False, False), (390, "light", False, False),
        (390, "dark", False, False), (390, "light", True, False),
        (390, "light", False, True), (768, "light", False, False),
        (768, "dark", False, False), (1440, "light", False, False),
        (1440, "dark", False, False),
    }


def test_own_render_carries_text():
    doc = extract_example()
    del doc["viewports"][0]["text"][0]["text"]
    assert list(validator("render/extract.schema.yaml").iter_errors(doc))


def reference_only_profile():
    """The example render turned into a clean reference-only capture."""
    doc = extract_example()
    doc["source"] = {"kind": "site", "url": "https://example.com/archive"}
    doc["reference"] = {"rights": "reference-only", "captured_by": "user-request"}
    doc["meta"]["sig_key_id"] = "66687aad"
    for vp in doc["viewports"]:
        del vp["screenshot"]
        vp["text_sig"] = "0" * 1024
        for run in vp["text"]:
            del run["text"]
            run["text_sig"] = "0" * 128
        for box in vp["boxes"]:
            (box.get("a11y") or {}).pop("name", None)
            (box.get("media") or {}).pop("alt", None)
    return doc


def test_reference_only_capture_keeps_signatures_not_copy():
    v = validator("render/extract.schema.yaml")
    assert list(v.iter_errors(reference_only_profile())) == []
    leaks = {
        "text": lambda vp: vp["text"][0].__setitem__("text", "copy"),
        "unsigned run": lambda vp: vp["text"][0].pop("text_sig"),
        "accessible name": lambda vp: next(b for b in vp["boxes"] if "a11y" in b)["a11y"].__setitem__("name", "copy"),
        "alt text": lambda vp: next(b for b in vp["boxes"] if "media" in b)["media"].__setitem__("alt", "copy"),
        "screenshot": lambda vp: vp.__setitem__("screenshot", "ref.png"),
        "unsigned page": lambda vp: vp.pop("text_sig"),
    }
    for name, leak in leaks.items():
        doc = reference_only_profile()
        leak(doc["viewports"][0])
        assert list(v.iter_errors(doc)), name
    doc = reference_only_profile()
    del doc["meta"]["sig_key_id"]
    assert list(v.iter_errors(doc)), "signatures without a key id"


def test_signatures_need_a_key_id():
    doc = extract_example()
    del doc["meta"]["sig_key_id"]                     # the example's runs already carry signatures
    v = validator("render/extract.schema.yaml")
    assert list(v.iter_errors(doc))
    doc["meta"]["sig_key_id"] = "66687aad"
    assert list(v.iter_errors(doc)) == []


def test_own_render_cannot_claim_reference_rights():
    doc = extract_example()
    doc["reference"] = {"rights": "reference-only"}
    assert list(validator("render/extract.schema.yaml").iter_errors(doc))


def test_source_url_has_no_query():
    doc = extract_example()
    doc["source"]["url"] = "https://example.com/?utm_source=x"
    assert list(validator("render/extract.schema.yaml").iter_errors(doc))


def _schema_path_exists(schema, dotted):
    defs = schema["$defs"]
    first, *rest = dotted.split(".")
    node = defs.get(first) or schema["properties"].get(first)
    if node is None:
        return False
    for part in rest:
        while "$ref" in node or ("items" in node and "properties" not in node):
            node = defs[node["$ref"].split("/")[-1]] if "$ref" in node else node["items"]
        node = node.get("properties", {}).get(part)
        if node is None:
            return False
    return True


def test_detector_reads_exist_in_the_extract_schema():
    schema = load("render/extract.schema.yaml")
    missing = [(d["name"], path) for d in load("slop/detectors.yaml")["detectors"]
               for path in d.get("reads", []) if not _schema_path_exists(schema, path)]
    assert missing == []


def test_render_detectors_declare_reads_and_need_nothing():
    detectors = load("slop/detectors.yaml")["detectors"]
    assert [d["name"] for d in detectors if "render" in d["layers"] and "reads" not in d] == []
    assert [d["name"] for d in detectors if d.get("needs")] == []


def test_rule_roles_are_known_to_the_extract():
    schema = load("render/extract.schema.yaml")["$defs"]
    known = set(schema["text_run"]["properties"]["type_role"]["enum"]) | set(schema["box"]["properties"]["role"]["enum"])
    unknown = [(r["id"], role) for r in rules_doc()["rules"] for det in (r.get("detect") or {}).values()
               for key in ("roles", "roles_except") for role in (det.get("params") or {}).get(key, [])
               if role not in known]
    assert unknown == []


def test_rule_viewports_are_captured():
    widths = set(load("render/extract.schema.yaml")["$defs"]["viewport"]["properties"]["width"]["enum"])
    used = [(r["id"], w) for r in rules_doc()["rules"] for det in (r.get("detect") or {}).values()
            for w in ((det.get("params") or {}).get("viewports", []) + [(det.get("params") or {}).get("viewport")])
            if w is not None and w not in widths]
    assert used == []


# ---------------------------------------------------------------- behavior session v0

def session_example():
    return json.loads((SHARED / "behavior/example.session.json").read_text(encoding="utf-8"))


def session_schema():
    return load("behavior/session.schema.yaml")


def test_session_example_passes():
    assert list(validator("behavior/session.schema.yaml").iter_errors(session_example())) == []


def test_session_drives_our_own_renders_only():
    doc = session_example()
    doc["source"]["kind"] = "site"
    assert list(validator("behavior/session.schema.yaml").iter_errors(doc))


def test_session_entry_is_local():
    doc = session_example()
    for url in ("https://example.com/", "http://172.40.0.1/", "http://localhost:4173/?q=1"):
        doc["source"]["url"] = url
        assert list(validator("behavior/session.schema.yaml").iter_errors(doc)), url
    for url in ("http://127.0.0.1:3000/", "http://kiln.localhost/", "http://192.168.0.7:8080/shop"):
        doc["source"]["url"] = url
        assert list(validator("behavior/session.schema.yaml").iter_errors(doc)) == [], url


def test_session_example_keeps_one_disclosure_per_kind_and_templated_paths():
    import re
    doc = session_example()
    for run in doc["flows"]:
        kinds = [d["kind"] for d in run.get("disclosures", [])]
        assert len(kinds) == len(set(kinds)), run["id"]
    for s in _strings(doc):
        if s.startswith("/"):
            assert not any(re.search(r"\d{4}", seg.replace("-", "")) for seg in s.split("/")), s


def test_session_requests_keep_no_query():
    doc = session_example()
    doc["probes"]["controls"][0]["effect"]["requests"] = [
        {"method": "GET", "host": "localhost:4173", "path": "/api/works?page=2"}]
    assert list(validator("behavior/session.schema.yaml").iter_errors(doc))


def _strings(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)
    elif isinstance(node, str):
        yield node


def test_session_box_ids_are_described_in_nodes():
    import re
    doc = session_example()
    body = {k: v for k, v in doc.items() if k != "nodes"}
    used = {s for s in _strings(body) if re.fullmatch(r"b[0-9a-f]{12}", s)}
    for k in doc["probes"].get("keyboard", []):
        used |= set(k.get("containers", {}))
    assert used - set(doc["nodes"]) == set()


def test_local_dev_sessions_keep_commits_contained():
    v = validator("behavior/session.schema.yaml")
    doc = session_example()
    doc["meta"]["backend"] = "local-dev"
    assert list(v.iter_errors(doc)), "local-dev must state its outbound network"
    doc["meta"]["outbound"] = "none"
    assert list(v.iter_errors(doc)), "failure injection needs the stub"
    for c in doc["probes"]["commits"]:
        c["outcomes"] = [o for o in c["outcomes"] if o["injected"] == "none"]
    assert list(v.iter_errors(doc)) == []
    doc["meta"]["outbound"] = "restricted"
    assert list(v.iter_errors(doc)), "commits need a backend without outside network"


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v)


@pytest.mark.parametrize("rel", ["slop/rules.yaml", "slop/detectors.yaml", "behavior/session.schema.yaml",
                                 "plan/schema.yaml", "plan/example.plan.yaml"])
def test_mapping_keys_are_strings(rel):
    """YAML 1.1 reads keys such as on, off, yes, and no as booleans."""
    assert [k for k in _keys(load(rel)) if not isinstance(k, str)] == []


def test_behavior_detectors_map_to_coverage_probes():
    probes = set(session_schema()["$defs"]["coverage_entry"]["properties"]["probe"]["enum"])
    detectors = load("slop/detectors.yaml")["detectors"]
    assert [d["name"] for d in detectors if "behavior" in d["layers"] and "probes" not in d] == []
    assert [(d["name"], p) for d in detectors for p in d.get("probes", []) if p not in probes] == []


def test_plan_flow_exemptions_need_a_reason():
    v = validator("plan/schema.yaml")
    plan = load("plan/example.plan.yaml")
    plan["flows"][0]["requires"] = ["account"]
    assert list(v.iter_errors(plan))
    plan["flows"][0]["requires_reason"] = "Reservations are tied to the member's kiln-club account"
    assert list(v.iter_errors(plan)) == []


def test_session_references_resolve():
    doc, plan = session_example(), load("plan/example.plan.yaml")
    contexts = {c["id"] for c in doc["contexts"]}
    used_contexts = set()
    for items in list(doc["probes"].values()) + [doc.get("flows", []), doc.get("console", [])]:
        for item in items:
            if "context" in item:
                used_contexts.add(item["context"])
            if "compare_to" in item:
                used_contexts.add(item["compare_to"])
    for c in doc["coverage"]:
        used_contexts.update(c.get("contexts", []))
    assert used_contexts <= contexts
    choice_ids = {c["id"] for c in doc["probes"].get("choices", [])}
    assert {d["choice_set"] for d in doc["probes"].get("dialogs", []) if "choice_set" in d} <= choice_ids
    flow_ids = {f["id"] for f in plan["flows"]}
    used_flows = {f["id"] for f in doc.get("flows", [])}
    for items in doc["probes"].values():
        used_flows |= {i["flow"] for i in items if "flow" in i}
    assert used_flows <= flow_ids
    assert {c["probe"] for c in doc["coverage"]} == set(session_schema()["$defs"]["coverage_entry"]["properties"]["probe"]["enum"])


def test_session_derived_values_match_the_reference():
    from lapis_design.behavior import derive_session
    doc = session_example()
    assert derive_session(doc, load("plan/example.plan.yaml")["flows"]) == doc


def test_behavior_detectors_declare_session_reads():
    schema = session_schema()
    detectors = load("slop/detectors.yaml")["detectors"]
    assert [d["name"] for d in detectors if "behavior" in d["layers"] and "reads_session" not in d] == []
    missing = [(d["name"], p) for d in detectors for p in d.get("reads_session", [])
               if not _schema_path_exists(schema, p)]
    assert missing == []


def _enum(schema, *path):
    node = schema["$defs"][path[0]]
    for part in path[1:]:
        while "$ref" in node or ("items" in node and "properties" not in node):
            node = schema["$defs"][node["$ref"].split("/")[-1]] if "$ref" in node else node["items"]
        node = node["properties"][part]
    while "$ref" in node:
        node = schema["$defs"][node["$ref"].split("/")[-1]]
    if "items" in node:
        node = node["items"]
    return set(node["enum"])


def test_behavior_rule_params_use_the_session_vocabulary():
    sch = session_schema()
    vocab = {
        ("choice-analysis", "purposes"): sch["$defs"]["purpose"]["enum"],
        ("dialog-usage", "purposes"): sch["$defs"]["purpose"]["enum"],
        ("choice-analysis", "field_purposes"): _enum(sch, "field", "purpose"),
        ("choice-analysis", "kinds"): _enum(sch, "option", "kind"),
        ("dialog-usage", "triggers"): _enum(sch, "dialog_probe", "trigger"),
        ("flow-analysis", "kinds"): sch["$defs"]["flow_kind"]["enum"],
        ("flow-analysis", "gates"): _enum(sch, "gate", "kind"),
        ("pointer-alternatives", "kinds"): _enum(sch, "pointer_probe", "kind"),
        ("state-coverage", "states"): _enum(sch, "state_probe", "state"),
        ("state-coverage", "state"): _enum(sch, "state_probe", "state"),
        ("form-behavior", "after"): _enum(sch, "form_probe", "preservation", "after"),
        ("permission-requests", "apis"): _enum(sch, "permission_request", "api"),
        ("history-behavior", "restores"): set(sch["$defs"]["history_probe"]["properties"]["restored"]["properties"]),
        ("status-announcement", "sources"): set(sch["properties"]["probes"]["properties"]),
    }
    bad = []
    for r in rules_doc()["rules"]:
        det = (r.get("detect") or {}).get("behavior")
        if not det:
            continue
        for key, value in (det.get("params") or {}).items():
            allowed = vocab.get((det["detector"], key))
            values = value if isinstance(value, list) else [value]
            if allowed is not None and not set(values) <= set(allowed):
                bad.append((r["id"], key, sorted(set(values) - set(allowed))))
    assert bad == []


def test_plan_flows_and_session_share_vocabulary():
    from lapis_design.behavior import EXIT_KINDS
    from lapis_design.plan_check import EXIT_PAIRS
    plan_flow = load("plan/schema.yaml")["properties"]["flows"]["items"]["properties"]
    sch = session_schema()
    kinds = set(sch["$defs"]["flow_kind"]["enum"])
    assert set(plan_flow["kind"]["enum"]) == kinds
    assert set(plan_flow["requires"]["items"]["enum"]) <= _enum(sch, "gate", "kind")
    assert set(EXIT_PAIRS) == EXIT_KINDS
    assert set(EXIT_PAIRS) | {k for v in EXIT_PAIRS.values() for k in v} <= kinds


def test_behavior_rules_detect_only_at_behavior_or_review():
    rules = {r["id"]: r for r in rules_doc()["rules"]}
    for pkg in ("subscription-trap", "pressure-selling", "consent-steering"):
        for m in rules_doc()["packages"][pkg]["members"]:
            assert set(rules[m]["layers"]) <= {"behavior", "review"}, m


def test_rule_keys_are_declared_by_their_detector():
    """Every params or threshold key a rule sets, at any layer, is declared by its detector."""
    detectors = {d["name"]: d for d in load("slop/detectors.yaml")["detectors"]}
    undeclared = []
    for r in rules_doc()["rules"]:
        for layer, det in (r.get("detect") or {}).items():
            if not isinstance(det, dict) or "detector" not in det:
                continue
            spec = detectors[det["detector"]]
            for kind in ("params", "threshold"):
                declared = spec.get(kind) or {}
                undeclared += [(r["id"], layer, kind, k) for k in (det.get(kind) or {}) if k not in declared]
    assert undeclared == []


def test_threshold_keys_follow_the_min_max_convention():
    """`<metric>_max` hits above the bound and `<metric>_min` below it; bare min/max are allowed."""
    import re
    bad = [
        (d["name"], k)
        for d in load("slop/detectors.yaml")["detectors"]
        for k in (d.get("threshold") or {})
        if not re.fullmatch(r"(min|max|[a-z0-9_]+_(min|max))", k)
    ]
    assert bad == []
