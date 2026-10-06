"""Release decisions from recorded project inputs, without live catalog requests."""
from __future__ import annotations

import copy
import json
import os
import re
import sqlite3
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from lapis_design import release_check, shared_dir
from lapis_design.cli import main as cli_main
from lazuli import db
from lazuli.catalog import net
from procedure_support import BRIEF_RECORD, record, refresh_critic, write_requirements

SHARED = shared_dir()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refused(url, headers):
        raise AssertionError(f"unexpected live request: {url}")
    monkeypatch.setattr(net, "default_transport", refused)


def save(root, name, document):
    path = root / ".lapis" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document) if path.suffix == ".yaml" else json.dumps(document), encoding="utf-8")
    return path


def finding(rule="example.rule", *, status="open", blocking=True, cls="requirement", observed="review required",
            location=None, skip_cause=None):
    return {"rule_id": rule, "class": cls, "severity": {"create": "gate", "review": "P0"},
            "layer": "review", "observed": observed, "blocking": blocking, "status": status,
            "evidence": {"type": "review", "refs": ["original"]},
            **({"skip_cause": skip_cause} if skip_cause else {}),
            **({"location": location} if location else {})}


def report(tool, task="kiln-shop-landing", findings=(), **target):
    return {"version": 0, "tool": {"name": tool, "version": "0.1.0"},
            "target": {"task": task, **target}, "findings": list(findings),
            **({"scope": {"layers": ["plan", "source", "render"]}} if tool == "slop_lint" else {})}


@pytest.fixture
def project(tmp_path, monkeypatch):
    task = "kiln-shop-landing"
    plan = yaml.safe_load((SHARED / "plan/example.plan.yaml").read_text())
    plan["flows"] = []
    plan["references"] = []
    plan["tokens"]["type"]["roles"] = []
    # The fixture extract records no dark theme, so its plan sets none either.
    color = plan["tokens"]["color"]
    color["themes"] = ["light"]
    color["roles"] = [role for role in color["roles"] if role.get("theme") != "dark"]
    save(tmp_path, f"plans/{task}.yaml", plan)
    extract = {"version": 1, "meta": {"extractor": {"name": "render_check", "version": "0.1.0"},
                                    "generated_at": "2026-09-27T00:00:00Z", "dark_theme": False},
               "source": {"kind": "render", "url": "http://localhost/", "task": task},
               "viewports": [{"width": w, "theme": "light", "boxes": [], "text": []} for w in (320, 390, 768, 1440)]}
    save(tmp_path, f"renders/{task}.json", extract)
    save(tmp_path, "fonts.lock.json", {"version": 0, "locked_at": "2026-09-27T00:00:00Z", "fonts": []})
    save(tmp_path, "assets.ledger.json", {"version": 0, "updated_at": "2026-09-27T00:00:00Z", "assets": []})
    lint_target = {"plan": f".lapis/plans/{task}.yaml", "extract": f".lapis/renders/{task}.json",
                   "ledger": ".lapis/assets.ledger.json", "lock": ".lapis/fonts.lock.json", "source": "."}
    save(tmp_path, f"lint/{task}.json", report("slop_lint", **lint_target))
    save(tmp_path, f"critic/{task}.json", report("critic", extract=f".lapis/renders/{task}.json"))
    for index, name in enumerate((f"plans/{task}.yaml", f"renders/{task}.json", "fonts.lock.json",
                                  "assets.ledger.json", f"lint/{task}.json", f"critic/{task}.json")):
        os.utime(tmp_path / ".lapis" / name, (100 + index, 100 + index))
    monkeypatch.setenv("LAZULI_DB", "")
    return tmp_path


def update(root, name, change):
    path = root / ".lapis" / name
    doc = yaml.safe_load(path.read_text()) if path.suffix == ".yaml" else json.loads(path.read_text())
    change(doc)
    save(root, name, doc)
    return path


def gate(root, *flags):
    code = cli_main(["release", "check", "--task", "kiln-shop-landing", "--root", str(root), "--offline", *flags])
    output = root / ".lapis/release/kiln-shop-landing.json"
    return code, json.loads(output.read_text()) if output.exists() else None


def ids(document):
    return [f["rule_id"] for f in document["findings"]]


def assert_gate_fields(item, layer, *, warning=False, license_fact=False):
    assert item["class"] == ("quality" if warning else "requirement")
    assert item["severity"] == ({"create": "warn", "review": "P2"} if warning else
                                {"create": "gate", "review": "P0"})
    assert item["blocking"] is not warning
    assert item["layer"] == layer
    assert item["evidence"]["type"] == ("source" if license_fact else "not-verified")


def test_static_clean_project_is_schema_valid_and_exits_zero(project):
    code, result = gate(project, "--static")
    assert code == 0
    assert result["summary"]["blocking"] == 0
    schema = yaml.safe_load((SHARED / "slop/finding.schema.yaml").read_text())
    assert not list(Draft202012Validator(schema).iter_errors(result))
    assert result["tool"]["name"] == "release_gate"


def test_static_refused_with_flows_writes_no_report(project):
    update(project, "plans/kiln-shop-landing.yaml", lambda p: p.update(flows=[{"id": "reserve", "kind": "primary", "goal": "Reserve a piece", "start": "/", "done": {"route": "/done"}}]))
    assert gate(project, "--static") == (2, None)


def test_missing_plan_is_exit_two_without_report(project):
    (project / ".lapis/plans/kiln-shop-landing.yaml").unlink()
    assert gate(project, "--static") == (2, None)


@pytest.mark.parametrize("rule, mutation, flags", [
    ("release.input-missing", lambda p: (p / ".lapis/renders/kiln-shop-landing.json").unlink(), ("--static",)),
    ("release.input-stale", lambda p: os.utime(p / ".lapis/lint/kiln-shop-landing.json", (1, 1)), ("--static",)),
    ("release.width-missing", lambda p: update(p, "renders/kiln-shop-landing.json", lambda d: d["viewports"].pop()), ("--static",)),
    ("release.theme-missing", lambda p: update(p, "renders/kiln-shop-landing.json", lambda d: d["meta"].update(dark_theme=True)), ("--static",)),
    ("release.theme-unchecked", lambda p: update(p, "plans/kiln-shop-landing.yaml", lambda d: d["tokens"]["color"].update(themes=["light", "high-contrast"])), ("--static",)),
    ("release.layer-missing", lambda p: update(p, "lint/kiln-shop-landing.json", lambda d: d["target"].pop("source")), ("--static",)),
    ("release.requirement-unverified", lambda p: update(p, "lint/kiln-shop-landing.json", lambda d: d["findings"].append(finding("ux.missing", status="skipped", blocking=False, observed="reviewer must decide"))), ("--static",)),
    ("release.critic-missing", lambda p: (p / ".lapis/critic/kiln-shop-landing.json").unlink(), ("--static",)),
    ("release.study-reference", lambda p: update(p, "plans/kiln-shop-landing.yaml", lambda d: d.update(references=[{"source": "https://example.com/", "kind": "site", "rights": "reference-only", "mode": "study", "take": ["layout rhythm"], "leave": ["copy"]}])), ("--static",)),
    ("release.license-unconfirmed", lambda p: update(p, "fonts.lock.json", lambda d: d["fonts"].append(font("noonnu"))), ("--static",)),
])
def test_gate_rule_fires_and_does_not_fire(project, rule, mutation, flags):
    baseline, clean = gate(project, *flags)
    assert baseline == 0 and rule not in ids(clean)
    mutation(project)
    code, result = gate(project, *flags)
    assert rule in ids(result)
    own = next(f for f in result["findings"] if f["rule_id"] == rule)
    assert code == (1 if own["blocking"] else 0) or code == 1
    layer = {"release.input-missing": "render", "release.width-missing": "render",
             "release.theme-missing": "render", "release.theme-unchecked": "render",
             "release.study-reference": "plan", "release.license-unconfirmed": "source"}.get(rule, "review")
    assert_gate_fields(own, layer, warning=rule in ("release.theme-unchecked", "release.license-unconfirmed"),
                       license_fact=rule == "release.license-unconfirmed")


def plan_sets_dark(root, how):
    def change(plan):
        color = plan["tokens"]["color"]
        if how == "themes":
            color["themes"] = ["light", "dark"]
        else:
            color["roles"].append({"name": "kiln-night", "role": "field", "oklch": [0.22, 0.01, 60], "theme": "dark"})
    os.utime(update(root, "plans/kiln-shop-landing.yaml", change), (100, 100))


def render_records_dark(root, value, *, captures=()):
    """Set meta.dark_theme (None removes it) and add dark captures at the given widths."""
    def change(extract):
        if value is None:
            extract["meta"].pop("dark_theme", None)
        else:
            extract["meta"]["dark_theme"] = value
        extract["viewports"] += [{"width": w, "theme": "dark", "boxes": [], "text": []} for w in captures]
    os.utime(update(root, "renders/kiln-shop-landing.json", change), (101, 101))


@pytest.mark.parametrize("dark_theme", [False, None], ids=["false", "absent"])
@pytest.mark.parametrize("how", ["themes", "role"])
def test_plan_dark_theme_the_render_did_not_find_blocks(project, how, dark_theme):
    plan_sets_dark(project, how)
    render_records_dark(project, dark_theme)
    code, result = gate(project, "--static")
    found = [f for f in result["findings"] if f["rule_id"] == "release.theme-missing"]
    assert code == 1 and len(found) == 1 and result["summary"]["blocking"] == 1
    assert_gate_fields(found[0], "render")
    assert found[0]["observed"] == "the plan set a dark theme and the render found none"


@pytest.mark.parametrize("dark_theme", [False, None], ids=["false", "absent"])
def test_plan_without_dark_needs_no_dark_theme(project, dark_theme):
    render_records_dark(project, dark_theme)
    code, result = gate(project, "--static")
    assert code == 0 and "release.theme-missing" not in ids(result)


def test_dark_theme_the_render_found_is_checked_for_its_captures(project):
    plan_sets_dark(project, "themes")
    render_records_dark(project, True, captures=(390, 768, 1440))
    code, result = gate(project, "--static")
    assert code == 0 and "release.theme-missing" not in ids(result)
    update(project, "renders/kiln-shop-landing.json",
           lambda d: d.update(viewports=[v for v in d["viewports"] if (v["theme"], v["width"]) != ("dark", 768)]))
    code, result = gate(project, "--static")
    assert code == 1
    assert [f["observed"] for f in result["findings"] if f["rule_id"] == "release.theme-missing"] == [
        "no dark capture at 768 px"]


@pytest.mark.parametrize("text", [
    "brief: [oops\n",
    "brief: !unrecognized value\n",
    "brief: one\n---\nbrief: two\n",
    "? [unhashable]: value\n",
], ids=["syntax", "tag", "multiple-documents", "unhashable-key"])
def test_unreadable_plan_yaml_is_one_reason_line(project, capsys, text):
    plan = project / ".lapis/plans/kiln-shop-landing.yaml"
    plan.write_text(text, encoding="utf-8")
    assert gate(project, "--static") == (2, None)
    error = capsys.readouterr().err
    assert len(error.splitlines()) == 1
    assert str(plan) in error and "cannot be read" in error and "Traceback" not in error


def font(source, license_kind="ofl", family="ABeeZee"):
    return {"role": "body", "used_by": ["kiln-shop-landing"], "family": family,
            "postscript_names": [family.replace(" ", "") + "-Regular"], "source": source,
            "license": {"kind": license_kind, "checked_at": "2026-09-27"}, "delivery": "self-host"}


def interactive(root):
    update(root, "plans/kiln-shop-landing.yaml",
           lambda d: d.update(flows=[{"id": "reserve", "kind": "primary", "goal": "Reserve one piece",
                                      "start": "/", "done": {"route": "/done"}}]))
    session = {"version": 0,
               "meta": {"driver": {"name": "behavior_check", "version": "0.1.0"},
                        "generated_at": "2026-09-27T00:00:00Z", "backend": "stub"},
               "source": {"kind": "render", "url": "http://localhost/", "task": "kiln-shop-landing"},
               "contexts": [{"id": "m", "width": 390, "height": 844, "theme": "light",
                             "pointer": "coarse", "network": "normal"}],
               "nodes": {}, "probes": {},
               "coverage": [{"probe": name, "status": "not-applicable"} for name in (
                   "controls", "commits", "keyboard", "dialogs", "choices", "forms", "states", "urgency",
                   "time_limits", "history", "pointer", "motion", "scroll", "permissions", "media", "flows", "console")]}
    path = save(root, "behavior/kiln-shop-landing.json", session)
    os.utime(path, (103, 103))
    update(root, "lint/kiln-shop-landing.json",
           lambda d: d["target"].update(session=".lapis/behavior/kiln-shop-landing.json"))


@pytest.mark.parametrize("rule, mutate", [
    ("release.probe-incomplete", lambda p: update(p, "behavior/kiln-shop-landing.json",
                                                  lambda s: s["coverage"][0].update(status="partial"))),
    ("release.backend-insufficient", lambda p: update(p, "behavior/kiln-shop-landing.json",
                                                      lambda s: s["meta"].update(backend="local-dev", outbound="none"))),
])
def test_interactive_gate_rules_fire_and_clear(project, rule, mutate):
    interactive(project)
    assert rule not in ids(gate(project)[1])
    mutate(project)
    code, result = gate(project)
    assert code == 1 and rule in ids(result)
    assert_gate_fields(next(f for f in result["findings"] if f["rule_id"] == rule), "behavior")


def test_stale_dependencies_are_reported_in_contract_order(project):
    interactive(project)
    paths = project / ".lapis"
    (paths / "stub.yaml").write_text("version: 0\n", encoding="utf-8")
    update(project, "behavior/kiln-shop-landing.json",
           lambda s: s["meta"].update(stub=".lapis/stub.yaml"))
    for name, time in (("plans/kiln-shop-landing.yaml", 90), ("renders/kiln-shop-landing.json", 92),
                       ("behavior/kiln-shop-landing.json", 89), ("stub.yaml", 95), ("fonts.lock.json", 93),
                       ("assets.ledger.json", 94), ("lint/kiln-shop-landing.json", 88),
                       ("critic/kiln-shop-landing.json", 87)):
        os.utime(paths / name, (time, time))
    code, result = gate(project)
    assert code == 1
    edges = [tuple(Path(p).parent.name for p in f["evidence"]["refs"])
             for f in result["findings"] if f["rule_id"] == "release.input-stale"]
    assert edges == [
        ("behavior", "plans"), ("behavior", ".lapis"), ("lint", "plans"), ("lint", "renders"),
        ("lint", "behavior"), ("lint", ".lapis"), ("lint", ".lapis"), ("critic", "lint"),
        ("critic", "renders")]


def test_in_process_plan_checks_copy_blocking_finding(project):
    interactive(project)
    update(project, "plans/kiln-shop-landing.yaml",
           lambda d: d["flows"].append(copy.deepcopy(d["flows"][0])))
    code, result = gate(project)
    assert code == 1
    problem = next(f for f in result["findings"] if f["rule_id"] == "flow.duplicate-id")
    assert problem["blocking"] and problem["evidence"]["type"] == "plan"
    assert problem["evidence"]["refs"][-1] == str(project / ".lapis/plans/kiln-shop-landing.yaml")


def test_copied_findings_keep_fields_and_append_origin(project):
    violation = finding("ux.action", location={"path": "tokens.color.roles[0]"})
    violation["fix"] = "Fix the actual behavior"
    update(project, "lint/kiln-shop-landing.json", lambda d: d["findings"].append(violation))
    update(project, "critic/kiln-shop-landing.json",
           lambda d: d["findings"].append(finding("review.counterfactual")))
    code, result = gate(project, "--static")
    assert code == 1 and result["summary"]["blocking"] == 2
    actual = {f["rule_id"]: f for f in result["findings"]}
    for rule, origin in (("ux.action", "lint"), ("review.counterfactual", "critic")):
        expected = copy.deepcopy(violation if rule == "ux.action" else finding("review.counterfactual"))
        expected["evidence"]["refs"].append(str(project / f".lapis/{origin}/kiln-shop-landing.json"))
        assert actual[rule] == expected


@pytest.mark.parametrize("cause, reason, verdict, location, resolved", [
    ("reviewer", "needs a reviewer's judgement", "earned", None, True),
    ("reviewer", "needs a reviewer's judgement", "unearned", None, True),
    ("reviewer", "needs a reviewer's judgement", "unknown", None, False),
    ("reviewer", "needs a reviewer's judgement", "earned", {"path": "another"}, False),
    ("probe", "whether a review step ran (probe did not record it)", "earned", None, False),
    ("layer", "reviewer must decide once the render layer ran", "earned", None, False),
    ("input", "not judged: reviewer needs a plan", "earned", None, False),
    (None, "needs a reviewer's judgement", "earned", None, False),
])
def test_critic_resolution_uses_skip_cause_not_wording(cause, reason, verdict, location, resolved, project):
    skipped = finding("ux.no-review-before-commit", status="skipped", blocking=False, cls="contract",
                      observed=reason, location={"path": "tokens.color"}, skip_cause=cause)
    update(project, "lint/kiln-shop-landing.json", lambda d: d["findings"].append(skipped))
    decision = finding("ux.no-review-before-commit", blocking=False,
                       cls="contract", location=location or {"path": "tokens.color"})
    decision["context"] = {"verdict": verdict}
    update(project, "critic/kiln-shop-landing.json", lambda d: d["findings"].append(decision))
    code, result = gate(project, "--static")
    assert ("release.requirement-unverified" not in ids(result)) == resolved
    assert ids(result).count("ux.no-review-before-commit") == (1 if resolved and verdict == "unearned" else 0)
    assert code == (0 if resolved else 1)


@pytest.mark.parametrize("verdict, blocking, expected", [
    ("unearned", True, True), ("unearned", False, False),
    ("earned", True, False), ("earned", False, False),
])
def test_resolving_critic_finding_is_copied_once_with_own_blocking(project, verdict, blocking, expected):
    skip = finding("contract.gap", status="skipped", blocking=False, cls="contract",
                   skip_cause="reviewer")
    update(project, "lint/kiln-shop-landing.json", lambda d: d["findings"].append(skip))
    decision = finding("contract.gap", cls="contract", blocking=blocking)
    decision["context"] = {"verdict": verdict}
    update(project, "critic/kiln-shop-landing.json", lambda d: d["findings"].append(decision))
    code, result = gate(project, "--static")
    copied = [f for f in result["findings"] if f["rule_id"] == "contract.gap"]
    assert len(copied) == (1 if verdict == "unearned" else 0)
    if copied:
        assert copied[0]["blocking"] == expected
        assert copied[0]["evidence"]["refs"][-1] == str(project / ".lapis/critic/kiln-shop-landing.json")
    assert "release.requirement-unverified" not in ids(result)
    assert code == (1 if expected else 0)

@pytest.mark.parametrize("verdicts", [("earned", "unearned", "unearned"),
                                     ("unearned", "earned", "unearned")])
def test_every_matching_unearned_critic_finding_wins_regardless_of_order(project, verdicts):
    skipped = finding("contract.gap", status="skipped", blocking=False, cls="contract",
                      location={"path": "task/id"}, skip_cause="reviewer")
    update(project, "lint/kiln-shop-landing.json", lambda d: d["findings"].extend([skipped, skipped]))
    decisions = []
    for index, verdict in enumerate(verdicts):
        decision = finding("contract.gap", cls="contract", blocking=False,
                           observed=f"decision {index}", location={"path": "task/id"})
        decision["context"] = {"verdict": verdict}
        decisions.append(decision)
    update(project, "critic/kiln-shop-landing.json", lambda d: d["findings"].extend(decisions))
    code, result = gate(project, "--static")
    copied = [f for f in result["findings"] if f["rule_id"] == "contract.gap"]
    assert code == 0 and result["summary"]["blocking"] == 0
    assert [f["observed"] for f in copied] == [
        decision["observed"] for decision in decisions if decision["context"]["verdict"] == "unearned"]
    assert all(f["evidence"]["refs"][-1] == str(project / ".lapis/critic/kiln-shop-landing.json")
               for f in copied)
    assert "release.requirement-unverified" not in ids(result)


def online(root):
    os.utime(root / ".lapis/fonts.lock.json", (103, 103))
    code = cli_main(["release", "check", "--task", "kiln-shop-landing", "--root", str(root), "--static"])
    return code, json.loads((root / ".lapis/release/kiln-shop-landing.json").read_text())


def catalog_responses(monkeypatch, root, pages):
    from lazuli import db
    from lazuli.catalog import net
    dbfile = root / "lazuli.db"
    db.connect(dbfile).close()
    monkeypatch.setenv("LAZULI_DB", str(dbfile))
    monkeypatch.setattr(net, "_last_request", {})
    clock = [10000.]
    monkeypatch.setattr(net, "_clock", lambda: clock[0])
    monkeypatch.setattr(net, "_sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    requested = []

    def transport(url, headers):
        requested.append(url)
        if url not in pages:
            return net.Response(url, 404, {"content-type": "text/plain"}, b"not found")
        body = pages[url]
        if isinstance(body, int):
            return net.Response(url, body, {"content-type": "text/plain"}, b"blocked")
        return net.Response(url, 200, {"content-type": "application/json"}, body.encode())
    monkeypatch.setattr(net, "default_transport", transport)
    return requested


@pytest.mark.parametrize("license_id,kind,changed", [
    ("OFL-1.1", "ofl", False), ("Apache-2.0", "apache", False),
    ("KOGL-1", "kogl-1", False), ("system", "system", False),
    ("commercial", "commercial-subscription", False),
    ("commercial", "commercial-perpetual", False),
    ("UFL-1.0", "unknown", False), ("OFL-1.1", "apache", True),
])
def test_recorded_catalog_license_kind_table(project, monkeypatch, license_id, kind, changed):
    from lazuli.catalog import fontsource
    entries = json.loads((Path(__file__).parent / "fixtures/release/fontsource-licenses.json").read_text())
    entry = next(e for e in entries if e["license"] == license_id)
    update(project, "fonts.lock.json",
           lambda d: d["fonts"].append(font("fontsource", kind, entry["family"])))
    requested = catalog_responses(monkeypatch, project,
                                  {fontsource.LIST_URL: json.dumps(entries)})
    code, result = online(project)
    assert ("release.license-changed" in ids(result)) == changed
    assert "release.license-unchecked" not in ids(result)
    if changed:
        assert_gate_fields(next(f for f in result["findings"] if f["rule_id"] == "release.license-changed"),
                           "source", license_fact=True)
    assert code == (1 if changed else 0)
    assert requested == ["https://api.fontsource.org/robots.txt", fontsource.LIST_URL]


def test_offline_and_blocked_and_unknown_family_do_not_use_stale_license(project, monkeypatch):
    from lazuli.catalog import fontsource
    update(project, "fonts.lock.json",
           lambda d: d["fonts"].append(font("fontsource", family="Not In Snapshot")))
    code, result = gate(project, "--static")
    assert code == 1 and "release.license-unchecked" in ids(result)
    requested = catalog_responses(monkeypatch, project, {fontsource.LIST_URL: 403})
    code, result = online(project)
    assert code == 1 and "release.license-unchecked" in ids(result)
    assert requested[-1] == fontsource.LIST_URL
    requested.clear()
    entries = (Path(__file__).parent / "fixtures/release/fontsource-licenses.json").read_text()
    catalog_responses(monkeypatch, project, {fontsource.LIST_URL: entries})
    code, result = online(project)
    assert code == 1 and "release.license-unchecked" in ids(result)


def test_blocked_lookup_source_does_not_retry_another_family(project, monkeypatch):
    from lazuli.catalog import sandoll

    update(project, "fonts.lock.json", lambda d: d["fonts"].extend([
        font("sandoll", family="Gothic A1"), font("sandoll", family="견본 둥근체")]))
    requested = catalog_responses(monkeypatch, project, {sandoll.BASE + "/robots.txt": 403})
    code, result = online(project)
    assert code == 1
    assert ids(result).count("release.license-unchecked") == 2
    assert requested == [sandoll.BASE + "/robots.txt"]


def test_unconfirmed_sources_never_send_a_request(project, monkeypatch):
    fonts = [font(source, family=source) for source in (
        "adobe-sync", "user-installed", "foundry-purchase", "open-source-other", "noonnu")]
    update(project, "fonts.lock.json", lambda d: d["fonts"].extend(fonts))
    requested = catalog_responses(monkeypatch, project, {})
    code, result = online(project)
    assert code == 0 and ids(result).count("release.license-unconfirmed") == 5
    assert requested == []


@pytest.mark.parametrize("source,family,kind", [
    ("google-fonts", "ABeeZee", "ofl"),
    ("fontshare", "Dancing Script", "ofl"),
    ("sandoll", "Gothic A1", "ofl"),
])
def test_each_catalog_adapter_refreshes_recorded_family(project, monkeypatch, source, family, kind):
    from lazuli.catalog import fontshare, google_fonts, sandoll
    fixture = Path(__file__).parent / "fixtures/catalog"
    if source == "google-fonts":
        pages = {google_fonts.METADATA_URL: (fixture / "google-fonts/metadata-fonts.json").read_text(),
                 google_fonts.TAGS_URL: (fixture / "google-fonts/families.csv").read_text(),
                 **{google_fonts.TREE_URL.format(d): (fixture / f"google-fonts/tree-{d}.json").read_text()
                    for d in ("ofl", "apache", "ufl")}}
        expected = 7
    elif source == "fontshare":
        pages = {f"{fontshare.LIST_URL}?offset={offset}&limit=100":
                 (fixture / f"fontshare/v2-fonts-offset-{offset}.json").read_text()
                 for offset in (0, 100)}
        expected = 3
    else:
        pages = {sandoll.BASE + "/robots.txt": (fixture / "sandoll/robots.txt").read_text(),
                 sandoll.SEARCH_URL + "?commonSearch=Gothic+A1": (fixture / "sandoll/search.html").read_text(),
                 sandoll.BASE + "/free-font/17559/Gothic-A1": (fixture / "sandoll/free-font-17559.html").read_text()}
        expected = 3
    update(project, "fonts.lock.json", lambda d: d["fonts"].append(font(source, kind, family)))
    requested = catalog_responses(monkeypatch, project, pages)
    code, result = online(project)
    assert code == 0
    assert [rule for rule in ids(result) if rule.startswith("release.license-")] == (
        ["release.license-unconfirmed"] if source == "sandoll" else [])
    assert len(requested) == expected
    assert source == "sandoll" or requested[0].endswith("/robots.txt")


def test_catalog_snapshot_fetches_only_once_per_source(project, monkeypatch):
    from lazuli.catalog import fontsource
    entries = (Path(__file__).parent / "fixtures/release/fontsource-licenses.json").read_text()
    update(project, "fonts.lock.json", lambda d: d["fonts"].extend([
        font("fontsource", "ofl", "OFL Family"), font("fontsource", "apache", "Apache Family")]))
    requested = catalog_responses(monkeypatch, project, {fontsource.LIST_URL: entries})
    assert online(project)[0] == 0
    assert requested.count(fontsource.LIST_URL) == 1


def test_example_inputs_generate_lint_then_gate_release(project, monkeypatch):
    import shutil
    from lapis_design.lint.cli import main as lint_main

    root = project
    task = "kiln-shop-landing"
    sources = {"plans": ("plan/example.plan.yaml", f"plans/{task}.yaml"),
               "renders": ("render/example.extract.json", f"renders/{task}.json"),
               "stub": ("behavior/example.stub.yaml", "stub.yaml"),
               "behavior": ("behavior/example.session.json", f"behavior/{task}.json"),
               "lock": ("fonts/example.fonts.lock.json", "fonts.lock.json"),
               "ledger": ("assets/example.assets.ledger.json", "assets.ledger.json")}
    for original, dest in sources.values():
        (root / ".lapis" / dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(SHARED / original, root / ".lapis" / dest)
    monkeypatch.setenv("LAZULI_DB", "")
    paths = root / ".lapis"
    command = ["--plan", str(paths / f"plans/{task}.yaml"), "--extract", str(paths / f"renders/{task}.json"),
               "--session", str(paths / f"behavior/{task}.json"), "--lock", str(paths / "fonts.lock.json"),
               "--ledger", str(paths / "assets.ledger.json"), "--source", str(root),
               "-o", str(paths / f"lint/{task}.json")]
    assert lint_main(command) in (0, 1)
    critic_finding = finding("review.counterfactual")
    save(root, f"critic/{task}.json",
         report("critic", extract=f".lapis/renders/{task}.json", findings=[critic_finding]))
    critic = paths / f"critic/{task}.json"
    now = critic.stat().st_mtime
    os.utime(critic, (now + 2, now + 2))
    code, document = gate(root)
    assert code == 1
    assert not {"release.width-missing", "release.theme-missing"} & set(ids(document))
    assert "release.license-unchecked" in ids(document)
    assert "release.license-unconfirmed" in ids(document)
    assert ids(document)[0] == "release.license-unconfirmed"
    assert "review.counterfactual" in ids(document)
    assert document["summary"]["blocking"] == sum(f["blocking"] for f in document["findings"])


def test_wrong_task_or_malformed_extract_is_missing_input(project):
    update(project, "renders/kiln-shop-landing.json",
           lambda d: d["source"].update(task="another-task"))
    code, result = gate(project, "--static")
    assert code == 1 and "release.input-missing" in ids(result)
    path = project / ".lapis/renders/kiln-shop-landing.json"
    path.write_text("{not-json", encoding="utf-8")
    code, result = gate(project, "--static")
    assert code == 1 and "release.input-missing" in ids(result)


def test_critic_targeting_another_extract_is_a_missing_critic(project):
    update(project, "critic/kiln-shop-landing.json",
           lambda d: d["target"].update(extract=".lapis/renders/another.json"))
    skipped = finding("contract.gap", status="skipped", blocking=False, cls="contract",
                      observed="reviewer must decide")
    update(project, "lint/kiln-shop-landing.json", lambda d: d["findings"].append(skipped))
    decision = finding("contract.gap", blocking=False, cls="contract")
    decision["context"] = {"verdict": "earned"}
    update(project, "critic/kiln-shop-landing.json", lambda d: d["findings"].append(decision))
    code, result = gate(project, "--static")
    assert code == 1 and "release.critic-missing" in ids(result)
    assert "release.requirement-unverified" in ids(result)


def test_no_session_without_static_is_missing_input(project):
    code, result = gate(project)
    assert code == 1 and "release.input-missing" in ids(result)


def test_missing_asset_ledger_is_missing_source_evidence(project):
    (project / ".lapis/assets.ledger.json").unlink()
    code, document = gate(project, "--static")
    assert code == 1
    item = next(f for f in document["findings"] if f["rule_id"] == "release.input-missing")
    assert_gate_fields(item, "source")


def test_local_stub_session_records_path_and_gate_checks_its_mtime(project):
    from lapis_design.behavior_check.session import Session

    interactive(project)
    stub = project / ".lapis/stub.yaml"
    stub.write_text("version: 0\n", encoding="utf-8")
    session = Session("http://localhost/", "kiln-shop-landing", stub_path=".lapis/stub.yaml")
    assert session.document()["meta"]["stub"] == ".lapis/stub.yaml"
    update(project, "behavior/kiln-shop-landing.json",
           lambda document: document["meta"].update(stub=".lapis/stub.yaml"))
    os.utime(project / ".lapis/behavior/kiln-shop-landing.json", (103, 103))
    os.utime(stub, (110, 110))
    code, result = gate(project)
    assert code == 1
    stale = [f for f in result["findings"] if f["rule_id"] == "release.input-stale"]
    assert any(f["evidence"]["refs"] == [
        str(project / ".lapis/behavior/kiln-shop-landing.json"), str(stub)] for f in stale)


def test_missing_recorded_stub_cannot_prove_session_freshness(project):
    interactive(project)
    session = update(project, "behavior/kiln-shop-landing.json",
                     lambda d: d["meta"].update(stub=".lapis/missing.stub.yaml"))
    os.utime(session, (103, 103))
    code, report = gate(project)
    assert code == 1
    missing = [f for f in report["findings"] if f["rule_id"] == "release.input-missing"]
    assert any("missing.stub.yaml" in f["observed"] and f["layer"] == "behavior" for f in missing)


def test_session_without_local_stub_still_checks_plan_freshness(project):
    interactive(project)
    plan = project / ".lapis/plans/kiln-shop-landing.yaml"
    session = project / ".lapis/behavior/kiln-shop-landing.json"
    os.utime(plan, (104, 104))
    os.utime(session, (103, 103))
    os.utime(project / ".lapis/lint/kiln-shop-landing.json", (105, 105))
    os.utime(project / ".lapis/critic/kiln-shop-landing.json", (106, 106))
    code, report = gate(project)
    assert code == 1
    stale = [f for f in report["findings"] if f["rule_id"] == "release.input-stale"]
    assert [f["evidence"]["refs"] for f in stale] == [[str(session), str(plan)]]
    assert "release.input-missing" not in ids(report)


@pytest.mark.parametrize("scope", [None, {"layers": ["plan", "source"]},
                                   {"layers": ["plan", "source", "render"], "rules": ["ux.*"]},
                                   {"layers": ["plan", "source", "render"], "rules_file": "custom.yaml"},
                                   {"layers": ["plan", "source", "render"], "draft": {"task": "kiln-shop-landing",
                                    "url": "http://localhost/", "sources": ["index.html"],
                                    "excluded_sources": [], "aliases": []}}])
def test_lint_scope_is_a_release_requirement(project, scope):
    if scope is None:
        update(project, "lint/kiln-shop-landing.json", lambda d: d.pop("scope"))
    else:
        update(project, "lint/kiln-shop-landing.json", lambda d: d.update(scope=scope))
    os.utime(project / ".lapis/lint/kiln-shop-landing.json", (104, 104))
    os.utime(project / ".lapis/critic/kiln-shop-landing.json", (105, 105))
    code, result = gate(project, "--static")
    assert code == 1 and "release.layer-missing" in ids(result)
    update(project, "lint/kiln-shop-landing.json",
           lambda d: d.update(scope={"layers": ["plan", "source", "render"]}))
    os.utime(project / ".lapis/lint/kiln-shop-landing.json", (104, 104))
    os.utime(project / ".lapis/critic/kiln-shop-landing.json", (105, 105))
    assert gate(project, "--static")[0] == 0


def test_narrowed_cli_lint_is_blocked_at_release_gate(project):
    from lapis_design.lint.cli import main as lint_main
    root = project / ".lapis"
    out = root / "lint/kiln-shop-landing.json"
    assert lint_main(["--plan", str(root / "plans/kiln-shop-landing.yaml"),
                      "--extract", str(root / "renders/kiln-shop-landing.json"),
                      "--source", str(project), "--ledger", str(root / "assets.ledger.json"),
                      "--lock", str(root / "fonts.lock.json"), "--layer", "render",
                      "--rule", "copy.buzzwords", "-o", str(out)]) in (0, 1)
    assert json.loads(out.read_text())["scope"] == {"layers": ["render"], "rules": ["copy.buzzwords"]}
    code, result = gate(project, "--static")
    assert code == 1 and "release.layer-missing" in ids(result)

def test_all_rules_pattern_does_not_narrow_release_gate(project):
    from lapis_design.lint.cli import main as lint_main

    root = project / ".lapis"
    output = root / "lint/kiln-shop-landing.json"
    assert lint_main(["--plan", str(root / "plans/kiln-shop-landing.yaml"),
                      "--extract", str(root / "renders/kiln-shop-landing.json"),
                      "--source", str(project), "--ledger", str(root / "assets.ledger.json"),
                      "--lock", str(root / "fonts.lock.json"), "--rule", "*", "-o", str(output)]) in (0, 1)
    assert "rules" not in json.loads(output.read_text(encoding="utf-8"))["scope"]
    code, result = gate(project, "--static")
    assert code in (0, 1)
    assert "release.layer-missing" not in ids(result)



def test_invalid_mapping_plan_writes_only_schema_findings(project):
    update(project, "plans/kiln-shop-landing.yaml",
           lambda p: (p["task"].pop("title"), p.update(flows=[{"id": "incomplete"}])))
    code, result = gate(project, "--static")
    assert code == 1 and result is not None
    assert set(ids(result)) == {"schema.invalid"}
    assert all(f["blocking"] for f in result["findings"])

def test_non_string_plan_key_is_schema_finding_in_gate_plan_hook_and_lint(project, capsys):
    from lapis_design import hooks, mcp_server
    from mcp.server.mcpserver.exceptions import ToolError

    path = project / ".lapis/plans/kiln-shop-landing.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "\nyes: 1\n", encoding="utf-8")
    code, result = gate(project, "--static")
    assert code == 1
    assert {f["rule_id"] for f in result["findings"]} == {"schema.invalid"}
    assert any("True" in f["location"]["path"] for f in result["findings"])
    assert cli_main(["plan", "check", str(path), "--root", str(project)]) == 1
    assert "schema.invalid" in capsys.readouterr().out
    event = {"tool_input": {"plan": "```yaml lapis-plan\n" + path.read_text(encoding="utf-8") + "```"}}
    decision = hooks.exit_plan_decision(event, project, SHARED)
    assert decision["hookSpecificOutput"]["decision"]["behavior"] == "deny"
    assert "schema.invalid" in decision["hookSpecificOutput"]["decision"]["message"]
    assert cli_main(["slop", "lint", "--plan", str(path)]) == 2
    assert "True" in capsys.readouterr().err
    with pytest.raises(ToolError, match="True"):
        mcp_server.slop_lint(plan=str(path))

def test_nested_non_string_plan_key_locations_include_list_indices(project):
    def corrupt(plan):
        plan["task"][True] = 1
        plan["references"] = [{42: "bad reference"}]

    update(project, "plans/kiln-shop-landing.yaml", corrupt)
    code, result = gate(project, "--static")
    assert code == 1
    assert {f["location"]["path"] for f in result["findings"]} == {
        "task/True", "references/0/42"}
    assert all(f["rule_id"] == "schema.invalid" for f in result["findings"])



def test_unexpected_gate_error_clears_previous_report(project, monkeypatch, capsys):
    from lapis_design import release_check

    old = project / ".lapis/release/kiln-shop-landing.json"
    assert gate(project, "--static")[0] == 0 and old.exists()
    monkeypatch.setattr(release_check, "run", lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("unexpected gate failure")))
    assert gate(project, "--static") == (2, None)
    assert "unexpected gate failure" in capsys.readouterr().err
    assert not old.exists()


def test_mismatched_plan_task_is_exit_two_and_clears_old_report(project):
    old = project / ".lapis/release/kiln-shop-landing.json"
    assert gate(project, "--static")[0] == 0 and old.exists()
    update(project, "plans/kiln-shop-landing.yaml", lambda p: p["task"].update(id="different-task"))
    assert gate(project, "--static") == (2, None)
    assert not old.exists()



def test_exit_two_clears_only_valid_task_report(project):
    old = project / ".lapis/release/kiln-shop-landing.json"
    assert gate(project, "--static")[0] == 0 and old.exists()
    update(project, "plans/kiln-shop-landing.yaml",
           lambda p: p.update(flows=[{"id": "reserve", "kind": "primary", "goal": "Reserve a piece",
                                     "start": "/", "done": {"route": "/done"}}]))
    assert cli_main(["release", "check", "--task", "kiln-shop-landing", "--root", str(project),
                     "--static"]) == 2
    assert not old.exists()
    sentinel = project / ".lapis/lint/x.json"
    sentinel.write_text("protected", encoding="utf-8")
    assert cli_main(["release", "check", "--task", "../lint/x", "--root", str(project)]) == 2
    assert sentinel.read_text() == "protected"


def test_invalid_option_clears_previous_report_for_valid_task(project):
    old = project / ".lapis/release/kiln-shop-landing.json"
    assert gate(project, "--static")[0] == 0 and old.exists()
    with pytest.raises(SystemExit) as exc:
        cli_main(["release", "check", "--task", "kiln-shop-landing", "--root", str(project),
                  "--unexpected-option"])
    assert exc.value.code == 2
    assert not old.exists()


def test_invalid_final_task_on_parser_error_never_clears_another_report(project):
    old = project / ".lapis/release/kiln-shop-landing.json"
    assert gate(project, "--static")[0] == 0 and old.exists()
    with pytest.raises(SystemExit) as exc:
        cli_main(["release", "check", "--task", "kiln-shop-landing", "--task", "../lint/x",
                  "--root", str(project), "--unexpected-option"])
    assert exc.value.code == 2
    assert old.exists()

def test_abbreviated_root_does_not_select_other_project_for_error_cleanup(project, tmp_path, monkeypatch):
    other = tmp_path / "other"
    old = project / ".lapis/release/kiln-shop-landing.json"
    foreign = other / ".lapis/release/kiln-shop-landing.json"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("other project", encoding="utf-8")
    assert gate(project, "--static")[0] == 0 and old.exists()
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit) as error:
        cli_main(["release", "check", "--task", "kiln-shop-landing", "--ro", str(other), "--bogus"])
    assert error.value.code == 2
    assert not old.exists()
    assert foreign.read_text(encoding="utf-8") == "other project"

def test_abbreviated_root_alone_is_invalid(project, tmp_path, monkeypatch):
    other = tmp_path / "other"
    old = project / ".lapis/release/kiln-shop-landing.json"
    foreign = other / ".lapis/release/kiln-shop-landing.json"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("other project", encoding="utf-8")
    assert gate(project, "--static")[0] == 0 and old.exists()
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit) as error:
        cli_main(["release", "check", "--task", "kiln-shop-landing", "--ro", str(other)])
    assert error.value.code == 2
    assert not old.exists()
    assert foreign.read_text(encoding="utf-8") == "other project"

def test_root_without_a_value_keeps_default_root_for_error_cleanup(project, monkeypatch):
    old = project / ".lapis/release/kiln-shop-landing.json"
    assert gate(project, "--static")[0] == 0 and old.exists()
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit) as error:
        cli_main(["release", "check", "--task", "kiln-shop-landing", "--root", "--bogus"])
    assert error.value.code == 2
    assert not old.exists()




def test_abbreviated_task_option_is_rejected(project):
    with pytest.raises(SystemExit) as error:
        cli_main(["release", "check", "--tas", "kiln-shop-landing", "--root", str(project)])
    assert error.value.code == 2


def test_folder_at_report_path_is_one_error_line_not_a_traceback(project, capsys):
    output = project / ".lapis/release/kiln-shop-landing.json"
    output.mkdir(parents=True)
    assert cli_main(["release", "check", "--task", "kiln-shop-landing", "--root", str(project),
                     "--static", "--offline"]) == 2
    error = capsys.readouterr().err
    assert len(error.splitlines()) == 1
    assert "release check:" in error and "Traceback" not in error
    assert output.is_dir()

def test_message_less_error_names_its_exception(project, monkeypatch, capsys):
    from lapis_design import release_check

    def failed(*args, **kwargs):
        raise RuntimeError()

    monkeypatch.setattr(release_check, "run", failed)
    assert cli_main(["release", "check", "--task", "kiln-shop-landing",
                     "--root", str(project)]) == 2
    assert capsys.readouterr().err.strip() == "release check: RuntimeError"


def test_release_report_replaces_symlink_without_modifying_target(project):
    report_path = project / ".lapis/release/kiln-shop-landing.json"
    report_path.parent.mkdir(parents=True)
    other = project / "user-notes.txt"
    other.write_text("leave my notes unchanged", encoding="utf-8")
    report_path.symlink_to(other)
    code, report = gate(project, "--static")
    assert code == 0 and report["summary"]["blocking"] == 0
    assert other.read_text(encoding="utf-8") == "leave my notes unchanged"
    assert not report_path.is_symlink()
    assert json.loads(report_path.read_text(encoding="utf-8")) == report



def test_color_role_high_contrast_needs_manual_check(project):
    assert "release.theme-unchecked" not in ids(gate(project, "--static")[1])
    update(project, "plans/kiln-shop-landing.yaml",
           lambda p: p["tokens"]["color"]["roles"].append(
               {"name": "contrast-paper", "role": "field", "oklch": [0.97, 0.01, 85],
                "theme": "high-contrast"}))
    os.utime(project / ".lapis/plans/kiln-shop-landing.yaml", (100, 100))
    code, result = gate(project, "--static")
    assert ids(result).count("release.theme-unchecked") == 1
    assert "schema.invalid" not in ids(result)


@pytest.mark.parametrize("source,kind,source_class", [
    ("fontsource", "unknown", None), ("fontsource", "ofl", "user-declared"),
    ("sandoll", "ofl", None),
])
def test_license_unconfirmed_also_covers_unknown_user_declarations_and_sandoll(
        project, monkeypatch, source, kind, source_class):
    from lazuli.catalog import fontsource, sandoll
    entry = font(source, kind, "OFL Family" if source == "fontsource" else "Gothic A1")
    if source_class:
        entry["license"]["source_class"] = source_class
    update(project, "fonts.lock.json", lambda d: d["fonts"].append(entry))
    if source == "fontsource":
        records = json.loads((Path(__file__).parent / "fixtures/release/fontsource-licenses.json").read_text())
        if kind == "unknown":
            next(row for row in records if row["family"] == "OFL Family")["license"] = "UFL-1.0"
        catalog_responses(monkeypatch, project, {fontsource.LIST_URL: json.dumps(records)})
    else:
        fixture = Path(__file__).parent / "fixtures/catalog/sandoll"
        catalog_responses(monkeypatch, project, {
            sandoll.BASE + "/robots.txt": (fixture / "robots.txt").read_text(),
            sandoll.SEARCH_URL + "?commonSearch=Gothic+A1": (fixture / "search.html").read_text(),
            sandoll.BASE + "/free-font/17559/Gothic-A1": (fixture / "free-font-17559.html").read_text()})
    code, result = online(project)
    assert code == 0
    warnings = [f for f in result["findings"] if f["rule_id"] == "release.license-unconfirmed"]
    assert len(warnings) == 1 and not warnings[0]["blocking"]
    assert "release.license-unchecked" not in ids(result)

def test_system_font_with_user_declared_license_is_left_to_plan_checks(project):
    entry = font("system", "system", "Installed System Face")
    entry["license"]["source_class"] = "user-declared"
    update(project, "fonts.lock.json", lambda d: d["fonts"].append(entry))
    os.utime(project / ".lapis/fonts.lock.json", (103, 103))
    code, result = gate(project, "--static")
    assert code == 0
    assert "release.license-unconfirmed" not in ids(result)


def researched_font(source, outcome, family):
    entry = font(source, family=family)
    entry["license"].update(source_class="rights-holder", research={
        "outcome": outcome, "evidence": [{"via": "rights-holder-page", "url": "https://foundry.example/license",
                                          "checked_at": "2026-09-27"}], **(
            {"restrictions": ["one domain only"]} if outcome == "restricted" else {})})
    return entry


def test_a_license_read_from_its_own_document_is_not_listed_but_a_restricted_one_is(project, monkeypatch):
    fonts = [researched_font("open-source-other", "verified", "Read Open"),
             researched_font("noonnu", "verified", "Read Korean"),
             researched_font("open-source-other", "restricted", "Limited"),
             researched_font("foundry-purchase", "verified", "Bought"),
             font("open-source-other", family="Never Read")]
    update(project, "fonts.lock.json", lambda d: d["fonts"].extend(fonts))
    requested = catalog_responses(monkeypatch, project, {})
    code, result = online(project)
    listed = {f["location"]["asset"]: f["observed"] for f in result["findings"]
              if f["rule_id"] == "release.license-unconfirmed"}
    assert sorted(listed) == ["Bought", "Limited", "Never Read"]          # the purchase and the unread one stay listed
    assert "one domain only" in listed["Limited"] and requested == []



def test_second_sandoll_refresh_error_invalidates_first_family_too(project, monkeypatch):
    from lazuli.catalog import sandoll
    fixture = Path(__file__).parent / "fixtures/catalog/sandoll"
    update(project, "fonts.lock.json", lambda d: d["fonts"].extend([
        font("sandoll", family="Gothic A1"), font("sandoll", family="Second Family")]))
    catalog_responses(monkeypatch, project, {
        sandoll.BASE + "/robots.txt": (fixture / "robots.txt").read_text(),
        sandoll.SEARCH_URL + "?commonSearch=Gothic+A1": (fixture / "search.html").read_text(),
        sandoll.BASE + "/free-font/17559/Gothic-A1": (fixture / "free-font-17559.html").read_text(),
        sandoll.SEARCH_URL + "?commonSearch=Second+Family": 500})
    code, result = online(project)
    assert code == 1
    assert {f["location"]["asset"] for f in result["findings"]
            if f["rule_id"] == "release.license-unchecked"} == {"Gothic A1", "Second Family"}
    assert ids(result).count("release.license-unconfirmed") == 2


def test_unexpected_200_json_shape_is_reported_for_every_font_in_source(project, monkeypatch):
    from lazuli.catalog import fontsource
    update(project, "fonts.lock.json", lambda d: d["fonts"].extend([
        font("fontsource", family="OFL Family"), font("fontsource", family="Apache Family")]))
    unexpected = (Path(__file__).parent / "fixtures/release/fontsource-unexpected-shape.json").read_text()
    requested = catalog_responses(monkeypatch, project, {fontsource.LIST_URL: unexpected})
    code, result = online(project)
    unchecked = [f for f in result["findings"] if f["rule_id"] == "release.license-unchecked"]
    assert code == 1 and len(unchecked) == 2
    assert {f["location"]["asset"] for f in unchecked} == {"OFL Family", "Apache Family"}
    assert requested.count(fontsource.LIST_URL) == 1


@pytest.mark.parametrize("mask,expected", [(0o022, 0o644), (0o077, 0o600)])
def test_release_report_obeys_new_file_permissions(project, mask, expected):
    previous = os.umask(mask)
    try:
        assert gate(project, "--static")[0] == 0
    finally:
        os.umask(previous)
    report_path = project / ".lapis/release/kiln-shop-landing.json"
    assert report_path.stat().st_mode & 0o777 == expected


def test_older_user_cache_does_not_upgrade_during_offline_gate(project, tmp_path, monkeypatch, capsys):
    from lazuli import paths

    monkeypatch.delenv("LAZULI_DB")
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    database = paths.db_path()
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as conn:
        conn.executescript((Path(__file__).resolve().parents[1] /
                             "cli/lazuli/db/migrations/0001_init.sql").read_text(encoding="utf-8"))
    before = (database.stat().st_mtime_ns, database.read_bytes())
    code, gate_document = gate(project, "--static")
    assert code == 0
    assert gate_document["findings"] == []
    assert (database.stat().st_mtime_ns, database.read_bytes()) == before
    with sqlite3.connect(database) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert len(capsys.readouterr().err.splitlines()) == 1


def test_gate_warns_about_this_runs_measurements_before_license_refresh_upgrades_cache(
        project, tmp_path, monkeypatch, capsys):
    from lazuli import paths
    from lazuli.catalog import fontsource

    monkeypatch.delenv("LAZULI_DB")
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    database = paths.db_path()
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as conn:
        conn.executescript((Path(__file__).resolve().parents[1] /
                            "cli/lazuli/db/migrations/0001_init.sql").read_text(encoding="utf-8"))
    update(project, "fonts.lock.json", lambda lock: lock["fonts"].append(font("fontsource", family="OFL Family")))
    entries = (Path(__file__).parent / "fixtures/release/fontsource-licenses.json").read_text()
    monkeypatch.setattr(net, "_last_request", {})
    monkeypatch.setattr(net, "_clock", lambda: 10000.)
    monkeypatch.setattr(net, "_sleep", lambda seconds: None)

    def transport(url, headers):
        if url.endswith("/robots.txt"):
            return net.Response(url, 200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /\n")
        assert url == fontsource.LIST_URL
        return net.Response(url, 200, {"content-type": "application/json"}, entries.encode())

    monkeypatch.setattr(net, "default_transport", transport)
    code, report = online(project)
    assert code == 0 and report["findings"] == []
    assert capsys.readouterr().err.strip() == (
        f"warning: lazuli database {database} is at migration 1; this lapis-design needs {db.latest_version()}; "
        "upgrade it with `lazuli local fonts`; this run checks without font measurements")
    with sqlite3.connect(database) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.latest_version()


def test_old_env_database_gate_exits_two_with_one_upgrade_reason(project, monkeypatch, tmp_path, capsys):
    database = tmp_path / "old.db"
    with sqlite3.connect(database) as conn:
        conn.executescript((Path(__file__).resolve().parents[1] /
                            "cli/lazuli/db/migrations/0001_init.sql").read_text(encoding="utf-8"))
    monkeypatch.setenv("LAZULI_DB", str(database))
    assert gate(project, "--static") == (2, None)
    assert capsys.readouterr().err.strip() == (
        f"release check: lazuli database {database} is at migration 1; this lapis-design needs {db.latest_version()}; "
        "upgrade it with `lazuli local fonts`")


def test_explicit_unopenable_lazuli_db_is_exit_two_and_clears_report(project, monkeypatch, tmp_path, capsys):
    db = tmp_path / "corrupt.sqlite3"
    db.write_text("not a sqlite database")
    old = project / ".lapis/release/kiln-shop-landing.json"
    assert gate(project, "--static")[0] == 0 and old.exists()
    monkeypatch.setenv("LAZULI_DB", str(db))
    assert gate(project, "--static") == (2, None)
    assert not old.exists()
    assert "cannot be opened" in capsys.readouterr().err


def test_unopenable_user_cache_lazuli_db_warns_once_and_continues(project, monkeypatch, tmp_path, capsys):
    from lazuli import paths

    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    db = paths.db_path()
    db.parent.mkdir(parents=True)
    db.write_text("not a sqlite database")
    monkeypatch.delenv("LAZULI_DB", raising=False)
    code, result = gate(project, "--static")
    assert code == 0 and result["findings"] == []
    error = capsys.readouterr().err
    assert len(error.splitlines()) == 1 and "lazuli database" in error


def test_behavior_stub_path_is_empty_when_relpath_cannot_be_computed(monkeypatch, tmp_path):
    from lapis_design.behavior_check import _stub_reference
    assert _stub_reference(tmp_path / "stub.yaml") == Path(
        os.path.relpath(tmp_path / "stub.yaml", Path.cwd())).as_posix()
    monkeypatch.setattr(os.path, "relpath", lambda *args: (_ for _ in ()).throw(ValueError("different drive")))
    assert _stub_reference(tmp_path / "stub.yaml") is None


def settle(root):
    """Put the inputs' modification times back in dependency order after a test edited them."""
    names = ("plans/kiln-shop-landing.yaml", "renders/kiln-shop-landing.json", "fonts.lock.json",
             "assets.ledger.json", "behavior/kiln-shop-landing.json", "lint/kiln-shop-landing.json",
             "critic/kiln-shop-landing.json")
    for index, name in enumerate(names):
        if (root / ".lapis" / name).exists():
            os.utime(root / ".lapis" / name, (100 + index, 100 + index))


def set_unread_links(root, **links):
    update(root, "lint/kiln-shop-landing.json", lambda d: d["scope"].update(unread_links=links))
    settle(root)


def test_unread_source_links_in_the_lint_scope_are_a_missing_layer(project):
    set_unread_links(project, source=["pages/", "src/secret.css"])
    code, result = gate(project, "--static")
    [missing] = [f for f in result["findings"] if f["rule_id"] == "release.layer-missing"]
    assert code == 1
    assert "pages/" in missing["observed"] and "src/secret.css" in missing["observed"]
    assert_gate_fields(missing, "review")
    update(project, "lint/kiln-shop-landing.json", lambda d: d["scope"].pop("unread_links"))
    settle(project)
    assert gate(project, "--static")[0] == 0


def test_unread_corpus_links_alone_do_not_block_the_gate(project):
    set_unread_links(project, corpus=["defaults/x.json"])
    code, result = gate(project, "--static")
    assert code == 0 and result["findings"] == []


def test_cli_lint_that_passed_over_a_folder_link_is_blocked_at_release_gate(project, tmp_path_factory):
    from lapis_design.lint.cli import main as lint_main

    outside = tmp_path_factory.mktemp("outside")
    (project / "pages").symlink_to(outside, target_is_directory=True)
    root = project / ".lapis"
    out = root / "lint/kiln-shop-landing.json"
    assert lint_main(["--plan", str(root / "plans/kiln-shop-landing.yaml"),
                      "--extract", str(root / "renders/kiln-shop-landing.json"),
                      "--source", str(project), "--ledger", str(root / "assets.ledger.json"),
                      "--lock", str(root / "fonts.lock.json"), "-o", str(out)]) in (0, 1)
    assert json.loads(out.read_text(encoding="utf-8"))["scope"]["unread_links"] == {"source": ["pages/"]}
    settle(project)
    code, result = gate(project, "--static")
    [missing] = [f for f in result["findings"] if f["rule_id"] == "release.layer-missing"]
    assert code == 1 and "pages/" in missing["observed"]
    assert result["summary"]["not_run"]["layers"] == 1


@pytest.mark.parametrize("rule, key, mutate, flags", [
    ("release.input-missing", "inputs", lambda p: (p / ".lapis/renders/kiln-shop-landing.json").unlink(), ("--static",)),
    ("release.input-stale", "stale", lambda p: os.utime(p / ".lapis/lint/kiln-shop-landing.json", (1, 1)), ("--static",)),
    ("release.width-missing", "widths", lambda p: update(p, "renders/kiln-shop-landing.json", lambda d: d["viewports"].pop()), ("--static",)),
    ("release.theme-missing", "themes", lambda p: update(p, "renders/kiln-shop-landing.json", lambda d: d["meta"].update(dark_theme=True)), ("--static",)),
    ("release.layer-missing", "layers", lambda p: update(p, "lint/kiln-shop-landing.json", lambda d: d["target"].pop("source")), ("--static",)),
    ("release.requirement-unverified", "requirements", lambda p: update(p, "lint/kiln-shop-landing.json", lambda d: d["findings"].append(finding("ux.missing", status="skipped", blocking=False, observed="reviewer must decide"))), ("--static",)),
    ("release.critic-missing", "critic", lambda p: (p / ".lapis/critic/kiln-shop-landing.json").unlink(), ("--static",)),
    ("release.license-unchecked", "licenses", lambda p: update(p, "fonts.lock.json", lambda d: d["fonts"].append(font("fontsource", family="Not In Snapshot"))), ("--static",)),
    ("release.probe-incomplete", "probes", lambda p: update(p, "behavior/kiln-shop-landing.json", lambda s: s["coverage"][0].update(status="partial")), ()),
    ("release.backend-insufficient", "backend", lambda p: update(p, "behavior/kiln-shop-landing.json", lambda s: s["meta"].update(backend="local-dev", outbound="none")), ()),
])
def test_a_check_that_did_not_run_is_counted_without_evidence_under_its_own_key(project, rule, key, mutate, flags):
    if not flags:
        interactive(project)
    mutate(project)
    code, result = gate(project, *flags)
    summary = result["summary"]
    assert code == 1 and rule in ids(result)
    assert summary["not_run"][key] == ids(result).count(rule)
    assert summary["no_evidence"] == sum(summary["not_run"].values())
    assert summary["blocking"] == summary["defects"] + summary["no_evidence"]
    assert summary["total"] == summary["blocking"] + summary["to_confirm"]
    assert 0 not in summary["not_run"].values()


@pytest.mark.parametrize("rule, mutate", [
    ("release.study-reference", lambda p: update(p, "plans/kiln-shop-landing.yaml", lambda d: d.update(references=[{"source": "https://example.com/", "kind": "site", "rights": "reference-only", "mode": "study", "take": ["layout rhythm"], "leave": ["copy"]}]))),
    ("ux.example", lambda p: update(p, "lint/kiln-shop-landing.json", lambda d: d["findings"].append(finding("ux.example")))),
    ("review.counterfactual", lambda p: update(p, "critic/kiln-shop-landing.json", lambda d: d["findings"].append(finding("review.counterfactual")))),
    ("schema.invalid", lambda p: update(p, "plans/kiln-shop-landing.yaml", lambda d: d["task"].pop("title"))),
])
def test_a_blocking_finding_that_is_not_missing_evidence_is_a_defect(project, rule, mutate):
    mutate(project)
    settle(project)
    code, result = gate(project, "--static")
    summary = result["summary"]
    assert code == 1 and rule in ids(result)
    assert summary["no_evidence"] == 0 and summary["not_run"] == {}
    assert summary["defects"] == summary["blocking"] == sum(f["blocking"] for f in result["findings"])


@pytest.mark.parametrize("rule, mutate", [
    ("release.license-unconfirmed", lambda p: update(p, "fonts.lock.json", lambda d: d["fonts"].append(font("noonnu")))),
    ("release.theme-unchecked", lambda p: update(p, "plans/kiln-shop-landing.yaml", lambda d: d["tokens"]["color"].update(themes=["light", "high-contrast"]))),
])
def test_a_finding_that_does_not_block_is_to_confirm(project, rule, mutate):
    mutate(project)
    settle(project)
    code, result = gate(project, "--static")
    assert code == 0 and rule in ids(result)
    assert result["summary"] == {"blocking": 0, "total": 1, "defects": 0, "no_evidence": 0, "to_confirm": 1,
                                 "not_run": {}}


def mixed_project(root):
    """Two defects, thirteen blocking findings without evidence, two findings to confirm."""
    interactive(root)
    update(root, "behavior/kiln-shop-landing.json", lambda s: (
        s["coverage"][0].update(status="partial"), s["coverage"][1].update(status="skipped"),
        s["meta"].update(backend="local-dev", outbound="none")))
    update(root, "renders/kiln-shop-landing.json",
           lambda d: (d["viewports"].pop(), d["meta"].update(dark_theme=True)))
    update(root, "plans/kiln-shop-landing.yaml", lambda d: (
        d.update(references=[{"source": "https://example.com/", "kind": "site", "rights": "reference-only",
                              "mode": "study", "take": ["layout rhythm"], "leave": ["copy"]}]),
        d["tokens"]["color"].update(themes=["light", "high-contrast"])))
    update(root, "lint/kiln-shop-landing.json", lambda d: (
        d["findings"].extend([finding("ux.example"), finding("ux.missing", status="skipped", blocking=False,
                                                              observed="reviewer must decide")]),
        d["scope"].update(layers=["plan", "source", "render", "behavior"],
                          unread_links={"source": ["pages/", "src/a.css"]})))
    update(root, "fonts.lock.json", lambda d: d["fonts"].extend(
        [font("noonnu"), font("fontsource", family="Not In Snapshot")]))
    (root / ".lapis/critic/kiln-shop-landing.json").unlink()
    (root / ".lapis/assets.ledger.json").unlink()
    settle(root)
    os.utime(root / ".lapis/behavior/kiln-shop-landing.json", (99, 99))     # older than the plan


def test_summary_gives_defects_and_missing_evidence_apart_with_each_cause(project):
    mixed_project(project)
    code, result = gate(project)
    assert code == 1
    assert result["summary"] == {
        "blocking": 15, "total": 17, "defects": 2, "no_evidence": 13, "to_confirm": 2,
        "not_run": {"inputs": 1, "stale": 1, "widths": 1, "themes": 3, "probes": 2, "backend": 1, "layers": 1,
                    "requirements": 1, "critic": 1, "licenses": 1}}
    defects = [f["rule_id"] for f in result["findings"] if f["blocking"] and not f["rule_id"] in (
        "release.input-missing", "release.input-stale", "release.width-missing", "release.theme-missing",
        "release.probe-incomplete", "release.backend-insufficient", "release.layer-missing",
        "release.requirement-unverified", "release.critic-missing", "release.license-unchecked")]
    assert sorted(defects) == ["release.study-reference", "ux.example"]
    assert sorted(f["rule_id"] for f in result["findings"] if not f["blocking"]) == [
        "release.license-unconfirmed", "release.theme-unchecked"]


def test_printed_result_gives_both_parts_then_names_what_did_not_run(project, capsys):
    mixed_project(project)
    capsys.readouterr()
    gate(project)
    output = project / ".lapis/release/kiln-shop-landing.json"
    assert capsys.readouterr().out.splitlines()[:2] == [
        f"release_gate: 15 blocking = 2 defects + 13 without evidence, 17 findings -> {output}",
        "  without evidence: 1 inputs missing, 1 inputs stale, 1 widths not captured, 3 themes not captured, "
        "2 probes incomplete, 1 backend insufficient, 1 lint layers not run, 1 requirements not verified, "
        "1 critic reports missing, 1 licenses unchecked"]


def test_printed_result_lists_every_finding_by_kind_and_the_report_holds_the_rest(project, capsys):
    mixed_project(project)
    capsys.readouterr()
    code, report = gate(project)
    printed = capsys.readouterr().out
    assert code == 1
    marks = {}
    for line in printed.splitlines():
        if match := re.match(r"  \[(BLOCK|NOT RUN|CONFIRM)\] (\S+)", line):
            marks.setdefault(match[2], match[1])
    for finding in report["findings"]:
        kind = ("CONFIRM" if not finding["blocking"] else
                "NOT RUN" if finding["rule_id"] in release_check.NO_EVIDENCE else "BLOCK")
        assert marks[finding["rule_id"]] == kind, finding["rule_id"]
    assert "ux.example" in printed and "release.study-reference" in printed
    assert "reviewer must decide" in printed                             # the skipped finding the gate carries


def test_json_prints_the_report_the_gate_wrote(project, capsys):
    mixed_project(project)
    capsys.readouterr()
    code, report = gate(project, "--json")
    assert code == 1 and json.loads(capsys.readouterr().out) == report


def test_printed_result_without_missing_evidence_names_only_what_to_confirm(project, capsys):
    update(project, "plans/kiln-shop-landing.yaml", lambda d: d["tokens"]["color"].update(themes=["light", "high-contrast"]))
    settle(project)
    capsys.readouterr()
    gate(project, "--static")
    output = project / ".lapis/release/kiln-shop-landing.json"
    assert capsys.readouterr().out.splitlines() == [
        f"release_gate: 0 blocking = 0 defects + 0 without evidence, 1 findings -> {output}",
        "  [CONFIRM] release.theme-unchecked high-contrast theme needs a manual check",
        "  no blocking findings; not judged: genre fit, information choice, the visitor's task at phone and desktop width"]


ROWS = ("Show which pieces are in this firing", "Let a visitor reserve one without an account")


@pytest.fixture
def judged(project):
    """A project with a requirement record and a critic report that judges the current packet of its inputs."""
    record(project, "answers", BRIEF_RECORD, 50)                        # the brief record the requirement record is sealed from
    write_requirements(project, ROWS)
    refresh_critic(project)
    settle(project)
    return project


def rules_of(document, rule):
    return [f for f in document["findings"] if f["rule_id"] == rule]


def test_with_a_requirement_record_a_critic_report_that_judges_the_current_packet_counts(judged):
    code, result = gate(judged, "--static")
    assert code == 0 and result["summary"]["blocking"] == 0
    assert not rules_of(result, "release.input-stale") and not rules_of(result, "release.critic-missing")


@pytest.mark.parametrize("change", [
    lambda r: update(r, "lint/kiln-shop-landing.json", lambda d: d["findings"].append(
        finding("ux.example", blocking=False, status="open"))),
    lambda r: update(r, "plans/kiln-shop-landing.yaml", lambda d: d["brief"].update(one_job="Let visitors reserve")),
    lambda r: write_requirements(r, (*ROWS, "A third thing the owner asked for")),
    lambda r: (r / ".lapis/taste.md").write_text("# Taste\n", encoding="utf-8"),
], ids=["lint-finding", "protected-plan-value", "requirement-row", "taste"])
def test_a_critic_report_made_from_another_packet_is_stale_whatever_the_file_times_say(judged, change):
    change(judged)
    settle(judged)                                                         # every report is newer than what it read
    code, result = gate(judged, "--static")
    [stale] = rules_of(result, "release.input-stale")
    assert code == 1 and stale["blocking"] and stale["layer"] == "review"
    assert stale["observed"].startswith("critic report was made from another packet")
    assert stale["evidence"]["refs"] == [str(judged / ".lapis/critic/kiln-shop-landing.json"),
                                         str(judged / ".lapis/critic/kiln-shop-landing.packet.json")]
    assert result["summary"]["not_run"] == {"stale": 1}                     # no evidence, not a defect: `next` returns critic
    assert not rules_of(result, "release.critic-missing")


def test_a_critic_report_that_names_no_packet_does_not_count_once_a_record_exists(judged):
    update(judged, "critic/kiln-shop-landing.json", lambda d: d["target"].pop("packet"))
    settle(judged)
    code, result = gate(judged, "--static")
    [stale] = rules_of(result, "release.input-stale")
    assert code == 1 and "names none" in stale["observed"]


def test_a_stale_critic_reports_findings_do_not_count_for_the_gate_and_a_current_ones_do(judged):
    update(judged, "critic/kiln-shop-landing.json", lambda d: d["findings"].append(finding("review.example")))
    settle(judged)
    code, result = gate(judged, "--static")
    assert code == 1 and [f["rule_id"] for f in result["findings"]] == ["review.example"]       # current: a defect
    (judged / ".lapis/taste.md").write_text("# Taste\n", encoding="utf-8")
    settle(judged)
    code, result = gate(judged, "--static")
    assert [f["rule_id"] for f in result["findings"]] == ["release.input-stale"]                  # stale: not judged


@pytest.mark.parametrize("fault, expected", [
    (lambda d: d["requirements"].pop(), "`requirements` has no entry for "),
    (lambda d: d["requirements"].append({"id": "R000000", "state": "met", "refs": []}),
     "`requirements` names R000000, which the packet does not list"),
    (lambda d: d["requirements"][0].update(refs=["missing-capture.png"]), "the ref missing-capture.png is not a file"),
    (lambda d: d.update(facts=[{"text": "The studio is old", "refs": [], "source": "none", "quote": ""},
                               {"text": "x y z", "refs": [], "source": "PRODUCT.md#L1", "quote": "x"}]),
     "fact 1: PRODUCT.md is not a file the packet lists"),
], ids=["missing-row", "unknown-row", "missing-ref", "fact-source"])
def test_a_critic_report_that_leaves_a_row_unjudged_or_cites_what_is_not_there_is_missing(judged, fault, expected):
    update(judged, "critic/kiln-shop-landing.json", fault)
    settle(judged)
    code, result = gate(judged, "--static")
    [missing] = rules_of(result, "release.critic-missing")
    assert code == 1 and missing["blocking"] and expected in missing["observed"]
    assert missing["observed"].startswith("critic report does not judge every requirement row, change, and dispute")
    assert result["summary"]["not_run"] == {"critic": 1} and not rules_of(result, "release.input-stale")


def test_a_packet_built_from_another_lint_report_than_the_releases_is_not_the_releases(judged):
    save(judged, "lint/other.json", json.loads((judged / ".lapis/lint/kiln-shop-landing.json").read_text()))
    refresh_critic(judged, lint=".lapis/lint/other.json")
    settle(judged)
    code, result = gate(judged, "--static")
    [missing] = rules_of(result, "release.critic-missing")
    assert code == 1 and "another lint report than the release's" in missing["observed"]


def test_without_a_requirement_record_a_critic_report_needs_no_packet(judged):
    (judged / ".lapis/requirements/kiln-shop-landing.json").unlink()
    update(judged, "critic/kiln-shop-landing.json", lambda d: d["target"].pop("packet"))
    settle(judged)
    code, result = gate(judged, "--static")
    assert code == 0 and result["summary"]["total"] == 0
