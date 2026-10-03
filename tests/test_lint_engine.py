"""slop_lint engine: how detector results become findings, and the `slop lint` command.

Fake detectors are registered under test-only names (or swapped in for one test) so these tests do
not depend on the detector slices.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from lapis_design.lint import cli as lint_cli
from lapis_design.lint import engine
from lapis_design.lint.types import DETECTORS, Context, Detector, Hit, Result, detector

SHARED = Path(__file__).resolve().parents[1] / "src" / "shared"
FINDING_SCHEMA = yaml.safe_load((SHARED / "slop/finding.schema.yaml").read_text(encoding="utf-8"))


def echo(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    """Reports the hits and skip reason its params describe."""
    params = det.get("params") or {}
    hits = [Hit(observed=h["observed"], location=h.get("location", {}), evidence=h.get("evidence", "measurement"),
                refs=h.get("refs", []), distance=h.get("distance"), conditions=frozenset(h.get("conditions", ())))
            for h in params.get("hits", [])]
    return Result(hits=hits, skipped=params.get("skipped"))


def boom(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    raise RuntimeError("extract field missing")


def corpus_names(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    names = sorted(e["_corpus"] for e in ctx.corpus)
    return Result(hits=[Hit(observed="corpus " + ", ".join(names))])


@pytest.fixture(autouse=True)
def fake_detectors():
    added = []
    for name, layers, fn in (("test-echo", engine.LAYERS, echo), ("test-boom", ("render",), boom),
                             ("test-render-only", ("render",), echo), ("test-corpus", ("render",), corpus_names)):
        detector(name, layers=layers)(fn)
        added.append(name)
    yield
    for name in added:
        DETECTORS.pop(name, None)


def det(name: str = "test-echo", *observed: str, skipped: str | None = None, hits: list[dict] | None = None,
        **params) -> dict:
    hits = list(hits or []) + [{"observed": o} for o in observed]
    return {"detector": name, "params": {**params, "hits": hits, **({"skipped": skipped} if skipped else {})}}


def rule(rid: str, detect: dict, *, cls: str = "default", create: str = "gate", review: str = "P2",
         adjust: list[dict] | None = None, **extra) -> dict:
    r = {"id": rid, "class": cls, "domain": "layout", "layers": list(detect),
         "severity": {"create": create, "review": review, **({"adjust": adjust} if adjust else {})},
         "detect": detect, "why": "The test says this reads as a default", "better": "Do the specific thing", **extra}
    if cls == "requirement":
        r["waiver"] = {"scope": "none"}
    return r


def lint(rules: list[dict], layers=("render",), *, mode: str = "create", probes=None, only=None, packages=None,
         **inputs) -> list[dict]:
    doc = {"version": 0, "as_of": "2026-09", "packages": packages or {}, "rules": rules}
    return engine.lint(Context(rules=doc, mode=mode, **inputs), layers, only, probes=probes or {})


def by_id(findings: list[dict], rid: str) -> list[dict]:
    return [f for f in findings if f["rule_id"] == rid]


# ---------------------------------------------------------------- results to findings

def test_a_skipped_result_is_one_unverified_nonblocking_finding():
    [f] = lint([rule("layout.a", {"render": det(skipped="no render extract given")})])
    assert (f["status"], f["evidence"], f["blocking"], f["observed"], f["skip_cause"]) == \
        ("skipped", {"type": "not-verified"}, False, "no render extract given", "input")

def test_missing_probe_coverage_has_different_cause_from_detector_input():
    rules = [rule("contract.input", {"behavior": det(skipped="no control field")}, cls="contract")]
    found = lint(rules, ("behavior",), session={"coverage": []}, probes={"test-echo": ("controls",)})
    assert [(f["skip_cause"], f["observed"]) for f in found] == [
        ("input", "no control field"),
        ("probe", "not verified: controls probe has no coverage entry, so it did not run")]


def test_cli_records_effective_scope_and_narrowing(tmp_path):
    plan = SHARED / "plan/example.plan.yaml"
    rules = write_rules(tmp_path, [rule("layout.plan", {"plan": det()}),
                                   rule("type.other", {"plan": det()})])
    full = lint_cli.run(plan=plan, source=tmp_path)
    assert full["scope"] == {"layers": ["plan", "source"]}
    packaged = lint_cli.run(rules=SHARED / "slop/rules.yaml", plan=plan, source=tmp_path)
    assert packaged["scope"] == {"layers": ["plan", "source"]}
    narrow = lint_cli.run(rules=rules, plan=plan, source=tmp_path,
                          layers=["plan", "plan"], rule_ids=["layout.*"])
    assert narrow["scope"] == {"layers": ["plan"], "rules": ["layout.*"], "rules_file": str(rules)}
    with pytest.raises(lint_cli.LintError, match="render.*extract"):
        lint_cli.run(rules=rules, plan=plan, source=tmp_path,
                     layers=["render", "plan", "render"], rule_ids=["layout.*"])


def test_mcp_lint_rejects_requested_layer_without_input(tmp_path):
    from mcp.server.mcpserver.exceptions import ToolError
    from lapis_design.mcp_server import slop_lint

    with pytest.raises(ToolError, match="render.*extract"):
        slop_lint(plan=str(SHARED / "plan/example.plan.yaml"), source=str(tmp_path),
                  layers=["render", "plan"], rule_ids=["ux.*"])

@pytest.mark.parametrize("layer,expected", [
    ("source", "source"), ("render", "extract"), ("behavior", "session"), ("review", "mode")
])
def test_mcp_layer_errors_name_tool_parameters_not_cli_options(layer, expected):
    from mcp.server.mcpserver.exceptions import ToolError
    from lapis_design.mcp_server import slop_lint

    with pytest.raises(ToolError) as error:
        slop_lint(plan=str(SHARED / "plan/example.plan.yaml"), layers=[layer])
    assert expected in str(error.value)
    assert "--" not in str(error.value)


def test_mcp_review_error_names_mode_parameter_and_value():
    from mcp.server.mcpserver.exceptions import ToolError
    from lapis_design.mcp_server import slop_lint

    with pytest.raises(ToolError) as error:
        slop_lint(layers=["review"])
    assert 'mode="review"' in str(error.value)
    assert "--mode review" not in str(error.value)


def test_cli_requested_layers_require_inputs_and_default_layers_still_follow_inputs(tmp_path, capsys):
    plan = SHARED / "plan/example.plan.yaml"
    assert lint_cli.main(["--plan", str(plan), "--layer", "render"]) == 2
    error = capsys.readouterr().err
    assert "render" in error and "extract" in error
    assert lint_cli.main(["--plan", str(plan), "--layer", "review"]) == 2
    error = capsys.readouterr().err
    assert "review" in error and "review mode" in error
    report = lint_cli.run(plan=plan)
    assert report["scope"]["layers"] == ["plan"]
    review = lint_cli.run(plan=plan, mode="review", layers=["review"])
    assert review["scope"]["layers"] == ["review"]


def test_all_rules_pattern_does_not_narrow_scope():
    plan = SHARED / "plan/example.plan.yaml"
    report = lint_cli.run(plan=plan, rule_ids=["*"])
    assert report["scope"] == {"layers": ["plan"]}


def test_each_hit_is_one_open_finding_and_a_partial_skip_adds_one_more():
    hit = {"observed": "hero is centered", "location": {"viewport": 390, "box": "b1"}, "refs": ["b1"],
           "distance": 0.12, "evidence": "measurement"}
    findings = lint([rule("layout.a", {"render": det(hits=[hit, {"observed": "cards nest twice"}],
                                                     skipped="dark theme not captured")})])
    assert [f["status"] for f in findings] == ["open", "open", "skipped"]
    first = findings[0]
    assert first["location"] == {"viewport": 390, "box": "b1"}
    assert first["evidence"] == {"type": "measurement", "refs": ["b1"]}
    assert first["distance"] == 0.12
    assert first["fix"] == "Do the specific thing"
    assert first["consequence"] == "The test says this reads as a default"


def test_create_mode_blocks_on_gate_rules_only():
    findings = lint([rule("layout.gate", {"render": det("test-echo", "seen here")}),
                     rule("layout.warn", {"render": det("test-echo", "seen here")}, create="warn")])
    assert {f["rule_id"]: f["blocking"] for f in findings} == {"layout.gate": True, "layout.warn": False}


def test_review_mode_takes_the_first_adjust_the_hit_satisfies():
    primary, secondary = "the primary task is blocked", "a secondary task is blocked"
    adjust = [{"when": primary, "review": "P0"}, {"when": secondary, "review": "P1"}]
    hits = [{"observed": "both conditions", "conditions": [secondary, primary]},
            {"observed": "second condition", "conditions": [secondary]},
            {"observed": "no condition"}]
    findings = lint([rule("ux.a", {"render": det(hits=hits)}, create="warn", review="P2", adjust=adjust)],
                    mode="review")
    assert [(f["severity"]["review"], f["blocking"]) for f in findings] == [("P0", True), ("P1", True), ("P2", False)]
    assert all(f["severity"]["create"] == "warn" for f in findings)


# ---------------------------------------------------------------- plan defaults

def plan_with(*defaults: dict) -> dict:
    return {"brief": {"locales": ["en"]}, "defaults": list(defaults)}


CREAM_CASES = [{"id": "paper-material", "when": "the subject's material is paper"},
               {"id": "brand-field", "when": "an approved brand field"}]


def test_a_keep_decision_waives_hits_that_name_a_case_of_the_rule_but_never_a_requirement():
    keep = {"decision": "keep", "basis": "brief", "keep_when": "paper-material", "reason": "The subject's paper is cream"}
    plan = plan_with({"id": "color.cream", **keep}, {"id": "a11y.contrast", **keep})
    findings = lint([rule("color.cream", {"render": det("test-echo", "cream field")}, keep_when=CREAM_CASES),
                     rule("a11y.contrast", {"render": det("test-echo", "contrast 2.1:1")}, cls="requirement",
                          keep_when=CREAM_CASES)],
                    plan=plan)
    cream, contrast = findings
    assert (cream["status"], cream["blocking"]) == ("waived", False)
    assert cream["waiver"] == "keep (brief): The subject's paper is cream"
    assert (contrast["status"], contrast["blocking"]) == ("open", True)


@pytest.mark.parametrize("named", [{}, {"keep_when": "cream-everywhere"}], ids=["no id", "an id the rule does not list"])
def test_a_keep_that_names_no_case_of_the_rule_leaves_the_hit_open_and_lists_the_cases(named):
    plan = plan_with({"id": "color.cream", "decision": "keep", "basis": "brief", **named,
                      "reason": "The subject's paper is cream"})
    [f] = lint([rule("color.cream", {"render": det("test-echo", "cream field")}, keep_when=CREAM_CASES)], plan=plan)
    assert (f["status"], f["blocking"], f["context"]["verdict"]) == ("open", True, "unearned")
    assert "paper-material, brand-field" in f["context"]["basis"]


def test_a_keep_on_a_rule_that_lists_no_case_leaves_the_hit_open():
    plan = plan_with({"id": "color.cream", "decision": "keep", "basis": "brief", "keep_when": "paper-material",
                      "reason": "The subject's paper is cream"})
    [f] = lint([rule("color.cream", {"render": det("test-echo", "cream field")})], plan=plan)
    assert (f["status"], f["blocking"]) == ("open", True) and "lists no keep_when case" in f["context"]["basis"]

# The rules that gate in create mode and had no keep case; each lists one. A keep that names it waives once it
# holds what that case lists, given per rule here: a design file and the token cited in it, a line of the brief,
# or a platform the brief lists.
GATING_CASES = {
    "type.tight-leading": ("single-line-text", {}),
    "type.flat-hierarchy": ("contract-scale", {"design": ("DESIGN.md#typography.scale", "typography:\n  scale: 1.25\n")}),
    "color.gray-on-color": ("contract-pair", {"design": ("DESIGN.md#components.button", "components:\n  button: {}\n")}),
    "color.inverted-dark-theme": ("contract-two-color-swap", {"design": ("DESIGN.md#colors.ink", "colors:\n  ink: '#111'\n")}),
    "layout.bento-filler": ("data-cells", {}),
    "ux.lost-input": ("cleared-secret", {}),
    "ux.dead-end": ("host-owns-navigation", {"platform": ["embedded"]}),
    "motion.hover-zoom-everything": ("inspection-zoom", {}),
    "copy.error-without-recovery": ("cause-withheld-for-security", {}),
    "imagery.jagged-clip": ("content-contour", {}),
    "code.mobile-100vh": ("dvh-fallback", {}),
    "code.unvirtualized-list": ("measured-within-budget", {"brief": "The full list renders in 100 ms on a mid-range phone"}),
}


def real_rule_that_hits(rule_id: str) -> dict:
    """The rule as rules.yaml writes it (class, severity, waiver, keep_when), with a detector that always hits."""
    real = next(r for r in yaml.safe_load((SHARED / "slop/rules.yaml").read_text(encoding="utf-8"))["rules"]
                if r["id"] == rule_id)
    return rule(rule_id, {"render": det("test-echo", "seen here")}, cls=real["class"], waiver=real["waiver"],
                create=real["severity"]["create"], review=real["severity"]["review"],
                **({"keep_when": real["keep_when"]} if "keep_when" in real else {}))


@pytest.mark.parametrize("rule_id, case_and_support", GATING_CASES.items())
def test_a_gating_rule_is_waived_by_a_keep_naming_its_case_and_not_by_another_rules_case(rule_id, case_and_support):
    case, support = case_and_support
    other_rules_case = next(c for other, (c, _) in GATING_CASES.items() if other != rule_id)

    def finding(named: str) -> dict:
        keep = {"id": rule_id, "decision": "keep", "basis": "brief", "keep_when": named, "reason": "The brief fixes it"}
        plan, inputs = plan_with(keep), {}
        if "design" in support:
            anchor, inputs["design_text"] = support["design"]
            keep["evidence"] = {"design": anchor}
            plan["context"] = {"design": {"path": "DESIGN.md", "dialect": "google"}}
        if "brief" in support:
            keep["evidence"] = {"brief": support["brief"]}
            plan["brief"]["constraints"] = [support["brief"]]
        if "platform" in support:
            plan["brief"]["platform"] = support["platform"]
        [f] = lint([real_rule_that_hits(rule_id)], plan=plan, **inputs)
        return f

    kept = finding(case)
    assert (kept["status"], kept["blocking"]) == ("waived", False)
    unfit = finding(other_rules_case)
    assert (unfit["status"], unfit["blocking"]) == ("open", True)
    assert case in unfit["context"]["basis"]


def test_a_reject_decision_leaves_the_hit_open():
    plan = plan_with({"id": "color.cream", "decision": "reject", "basis": "brief", "reason": "Competes with glazes"})
    [f] = lint([rule("color.cream", {"render": det("test-echo", "cream field")})], plan=plan)
    assert (f["status"], f["blocking"], f["context"]["verdict"]) == ("open", True, "unearned")


# ---------------------------------------------------------------- locales

def run_(script: str, lang: str | None = None) -> dict:
    return {"id": "t1", "box": "b1", "chars": 4, "script": script, "font": {"requested": "X", "rendered": "X"},
            "size_px": 16, "text": "text", **({"lang": lang} if lang else {})}


def extract_with(*runs: dict) -> dict:
    return {"viewports": [{"width": 390, "theme": "light", "boxes": [], "text": list(runs)}]}


@pytest.mark.parametrize("inputs, applies", [
    ({"extract": extract_with(run_("latn", "en"))}, False),
    ({"extract": extract_with(run_("latn", "en"), run_("hang", "ko"))}, True),
    ({"plan": {"brief": {"locales": ["en-US"]}}}, False),
    ({"plan": {"brief": {"locales": ["ko-KR"]}}}, True),
    ({}, True),                                               # content locales unknown: the rule runs
])
def test_rule_locales_limit_the_rule_to_matching_content(inputs, applies):
    findings = lint([rule("type.ko.a", {"render": det("test-echo", "tracking -0.02em")}, locales=["ko"])], **inputs)
    assert bool(findings) is applies


@pytest.mark.parametrize("run, locales, expected", [
    (run_("hani", "ja"), ["ja"], True),                      # Han in Japanese text is Japanese
    (run_("hani", "ja"), ["zh"], False),
    (run_("hani"), ["zh"], True),
    (run_("latn", "ko"), ["latin"], True),                   # Latin words in Korean text are Latin script
    (run_("latn", "ko"), ["ko"], True),
    (run_("cyrl", "ru"), ["latin", "grek"], False),
    (run_("other", "hi"), ["latin"], False),
    (run_("mixed", "sr-Latn"), ["latin"], True),
    (run_("hang", "ko"), None, True),
    (run_("hang", "ko"), ["all"], True),
])
def test_in_locales(run, locales, expected):
    assert engine.in_locales(run, locales) is expected


# ---------------------------------------------------------------- packages

PACKAGES = {"warm": {"members": ["color.cream", "color.clay", "type.serif"], "hit_when": {"min_members": 2}}}


def package_rules(cream: dict, clay: dict, serif: dict) -> list[dict]:
    return [rule("color.warm", {"render": {"detector": "package-hit", "params": {"package": "warm"}}}),
            rule("color.cream", {"render": cream}, create="warn"),
            rule("color.clay", {"render": clay}, create="warn"),
            rule("type.serif", {"plan": serif, "render": det()}, create="warn")]


def test_a_package_hits_when_enough_members_hit_at_the_same_layer():
    findings = lint(package_rules(det("test-echo", "cream field"), det("test-echo", "clay accent"), det()),
                    packages=PACKAGES)
    [pkg] = by_id(findings, "color.warm")
    assert (pkg["package"], pkg["status"], pkg["blocking"]) == ("warm", "open", True)
    assert pkg["evidence"]["refs"] == ["color.cream", "color.clay"]


def test_member_hits_at_another_layer_do_not_count():
    findings = lint(package_rules(det("test-echo", "cream field"), det(), det("test-echo", "serif display")),
                    ("plan", "render"), packages=PACKAGES)
    assert by_id(findings, "color.warm") == []


def test_a_package_that_could_still_hit_is_skipped():
    findings = lint(package_rules(det("test-echo", "cream field"), det(skipped="no palette"), det()),
                    packages=PACKAGES)
    [pkg] = by_id(findings, "color.warm")
    assert pkg["status"] == "skipped" and "color.clay" in pkg["observed"]


def test_a_rule_filter_still_evaluates_package_members():
    findings = lint(package_rules(det("test-echo", "cream field"), det("test-echo", "clay accent"), det()),
                    packages=PACKAGES, only=["color.warm"])
    assert [f["rule_id"] for f in findings] == ["color.warm"]


# ---------------------------------------------------------------- behavior coverage

def test_probes_that_did_not_fully_run_add_one_skipped_finding_each():
    session = {"coverage": [{"probe": "keyboard", "status": "ran"},
                            {"probe": "forms", "status": "partial", "contexts": ["m"], "reason": "no fixture value"},
                            {"probe": "dialogs", "status": "not-applicable"}]}
    findings = lint([rule("ux.a", {"behavior": det("test-echo", "focus lost after submit")}, cls="requirement")],
                    ("behavior",), session=session, probes={"test-echo": ("keyboard", "forms", "dialogs", "states")})
    assert [f["status"] for f in findings] == ["open", "skipped", "skipped"]
    forms, states = findings[1:]
    assert "forms probe partial in m: no fixture value" in forms["observed"]
    assert "states probe has no coverage entry" in states["observed"]
    assert not forms["blocking"] and forms["evidence"]["type"] == "not-verified"
    assert forms["skip_cause"] == states["skip_cause"] == "probe"


# ---------------------------------------------------------------- leads

def swap(monkeypatch, name: str, layers: tuple[str, ...]) -> None:
    monkeypatch.setitem(DETECTORS, name, Detector(name, layers, echo))


@pytest.mark.parametrize("render, layers, expected", [
    (det("test-echo", "transition on width"), ("source", "render"), [("source", "open"), ("render", "open")]),
    (det(), ("source", "render"), []),                                   # render judged it: refuted
    (det(skipped="no motion captured"), ("source", "render"),
     [("source", "skipped"), ("render", "skipped")]),
    (det(), ("source",), [("source", "skipped")]),                       # render did not run
])
def test_source_pattern_hits_are_leads_for_later_layers(monkeypatch, render, layers, expected):
    swap(monkeypatch, "source-pattern", ("source",))
    source = det("source-pattern", hits=[{"observed": "transition: width in app.css", "location": {"file": "app.css"}}])
    findings = lint([rule("motion.a", {"source": source, "render": render})], layers)
    assert [(f["layer"], f["status"]) for f in findings] == expected
    if expected and expected[0] == ("source", "skipped"):
        assert findings[0]["observed"].startswith("lead not confirmed at render")
        assert findings[0]["location"] == {"file": "app.css"}
        assert findings[0]["skip_cause"] == "layer"


def test_leads_without_a_later_layer_stay_open_with_an_unknown_verdict(monkeypatch):
    swap(monkeypatch, "separator-shape", ("render",))
    [f] = lint([rule("copy.a", {"render": det("separator-shape", "label — tail in 5 cards")}, create="warn")])
    assert (f["status"], f["context"]["verdict"]) == ("open", "unknown")


# ---------------------------------------------------------------- dispatch

def test_a_failing_detector_is_reported_not_raised():
    [f] = lint([rule("layout.a", {"render": {"detector": "test-boom"}})])
    assert f["status"] == "skipped" and "RuntimeError: extract field missing" in f["observed"]
    assert f["skip_cause"] == "input"


def test_a_detector_used_at_a_layer_it_does_not_serve_is_skipped():
    [f] = lint([rule("layout.a", {"source": det("test-render-only", "seen")})], ("source",))
    assert f["status"] == "skipped" and "does not run at the source layer" in f["observed"]


def test_an_unregistered_detector_is_skipped():
    [f] = lint([rule("layout.a", {"render": {"detector": "test-never-registered"}})])
    assert f["status"] == "skipped" and "not registered" in f["observed"]


def test_plan_check_detectors_run_at_the_plan_layer():
    rules = [rule("type.flat", {"plan": {"detector": "plan-value-range", "path": "tokens.type.scale.ratio",
                                         "threshold": {"min": 1.125}}}, cls="quality")]
    [f] = lint(rules, ("plan",), plan={"tokens": {"type": {"scale": {"ratio": 1.05}}}}, plan_path="p.yaml")
    assert f["status"] == "open" and f["location"] == {"file": "p.yaml", "path": "tokens.type.scale.ratio"}
    assert lint(rules, ("plan",), plan={"tokens": {"type": {"scale": {"ratio": 1.2}}}}) == []


def test_asset_ledger_rules_run_through_the_rights_check(tmp_path):
    ledger = {"assets": [{"id": "hero-photo", "kind": "icon", "origin": "unknown", "rights": {"license": "unknown"},
                          "use": {"commercial": True, "promotional": False, "channels": ["web"]}}]}
    rules = [rule("rights.license-unknown", {"source": {"detector": "asset-ledger", "params": {"check": "license"}}},
                  cls="requirement")]
    [f] = lint(rules, ("source",), ledger=ledger, source_root=tmp_path)
    assert (f["status"], f["location"], f["blocking"]) == ("open", {"asset": "hero-photo"}, True)
    [skip] = lint(rules, ("source",), source_root=tmp_path)
    assert skip["status"] == "skipped" and "ledger" in skip["observed"]


# ---------------------------------------------------------------- the command

def write_rules(tmp_path: Path, rules: list[dict]) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump({"version": 0, "as_of": "2026-09", "rules": rules}), encoding="utf-8")
    return path


def test_the_command_writes_a_schema_valid_report_and_exits_1_on_blocking(tmp_path, capsys):
    rules = write_rules(tmp_path, [rule("layout.plan", {"plan": det("test-echo", "hero outranks the task")}),
                                   rule("layout.render", {"render": det("test-echo", "centered hero")})])
    out = tmp_path / "out" / "lint.json"
    code = lint_cli.main(["--rules", str(rules), "--plan", str(SHARED / "plan/example.plan.yaml"), "-o", str(out)])
    report = json.loads(out.read_text(encoding="utf-8"))
    assert code == 1
    assert list(Draft202012Validator(FINDING_SCHEMA).iter_errors(report)) == []
    assert report["tool"]["name"] == "slop_lint" and report["target"]["task"] == "kiln-shop-landing"
    assert [f["rule_id"] for f in report["findings"]] == ["layout.plan"]    # no extract: no render layer
    assert report["summary"] == {"blocking": 1, "total": 1, "skipped": 0}
    assert "1 blocking" in capsys.readouterr().out


def test_lint_report_records_source_tree_and_font_lock(tmp_path):
    rules = write_rules(tmp_path, [rule("layout.plan", {"plan": det()})])
    lock = tmp_path / ".lapis/fonts.lock.json"
    lock.parent.mkdir()
    lock.write_text(json.dumps({"version": 0, "locked_at": "2026-09-27T00:00:00Z", "fonts": []}))
    report = lint_cli.run(rules=rules, plan=SHARED / "plan/example.plan.yaml", source=tmp_path, lock=lock)
    assert report["target"]["source"] == str(tmp_path)
    assert report["target"]["lock"] == str(lock)


def test_the_command_exits_0_without_blocking_findings(tmp_path, capsys):
    rules = write_rules(tmp_path, [rule("layout.plan", {"plan": det("test-echo", "hero outranks the task")},
                                        create="warn")])
    assert lint_cli.main(["--rules", str(rules), "--plan", str(SHARED / "plan/example.plan.yaml")]) == 0
    assert json.loads(capsys.readouterr().out)["summary"] == {"blocking": 0, "total": 1, "skipped": 0}


def test_the_summary_counts_skipped_findings_and_the_printed_line_says_they_were_not_judged(tmp_path, capsys):
    rules = write_rules(tmp_path, [rule("layout.a", {"plan": det("test-echo", "hero outranks the task")}),
                                   rule("layout.b", {"plan": det(skipped="no extract given")}),
                                   rule("layout.c", {"plan": det(skipped="no lock given")})])
    out = tmp_path / "lint.json"
    assert lint_cli.main(["--rules", str(rules), "--plan", str(SHARED / "plan/example.plan.yaml"),
                          "-o", str(out)]) == 1
    assert json.loads(out.read_text(encoding="utf-8"))["summary"] == {"blocking": 1, "total": 3, "skipped": 2}
    assert capsys.readouterr().out.splitlines() == [
        f"slop_lint: 1 blocking, 3 findings, 2 skipped: not judged -> {out}"]


def test_the_printed_line_leaves_out_skipped_when_nothing_was_skipped(tmp_path, capsys):
    rules = write_rules(tmp_path, [rule("layout.a", {"plan": det("test-echo", "hero outranks the task")})])
    out = tmp_path / "lint.json"
    lint_cli.main(["--rules", str(rules), "--plan", str(SHARED / "plan/example.plan.yaml"), "-o", str(out)])
    assert capsys.readouterr().out.splitlines() == [f"slop_lint: 1 blocking, 1 findings -> {out}"]


def test_unusable_inputs_exit_2(tmp_path, capsys):
    rules = write_rules(tmp_path, [rule("layout.render", {"render": det()})])
    bad = tmp_path / "extract.json"
    bad.write_text(json.dumps({"version": 1}), encoding="utf-8")
    assert lint_cli.main(["--rules", str(rules), "--extract", str(bad)]) == 2
    assert "does not match its schema" in capsys.readouterr().err
    assert lint_cli.main(["--rules", str(rules), "--extract", str(tmp_path / "absent.json")]) == 2
    assert lint_cli.main(["--rules", str(rules)]) == 2                      # nothing to lint
    assert lint_cli.main(["--rules", str(rules), "--extract", str(SHARED / "render/example.extract.json"),
                          "--rule", "layout.nothing-*"]) == 2


def test_corpus_entries_carry_their_corpus_name(tmp_path):
    example = SHARED / "render/example.extract.json"
    for rel in ("starter-themes/a.json", "starter-themes/nested/b.json", "defaults/c.json", "d.json"):
        (tmp_path / "corpus" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(example, tmp_path / "corpus" / rel)
    rules = write_rules(tmp_path, [rule("layout.typical", {"render": {"detector": "test-corpus"}})])
    report = lint_cli.run(rules=rules, extract=example, corpus=tmp_path / "corpus")
    assert report["findings"][0]["observed"] == "corpus corpus, defaults, starter-themes, starter-themes"
    single = lint_cli.run(rules=rules, extract=example, corpus=tmp_path / "corpus" / "defaults" / "c.json")
    assert single["findings"][0]["observed"] == "corpus defaults"


def test_every_implemented_detector_runs_at_each_listed_layer_and_nothing_else_is_registered():
    from lapis_design import plan_check
    from lapis_design.lint import detectors

    detectors.load()
    spec = yaml.safe_load((SHARED / "slop/detectors.yaml").read_text(encoding="utf-8"))
    listed = {d["name"]: set(d["layers"]) for d in spec["detectors"]}
    missing = []
    for d in spec["detectors"]:
        if d.get("status") != "implemented":
            continue
        for layer in d["layers"]:
            runs = (d["name"] in ("package-hit", "asset-ledger")
                    or (layer == "plan" and d["name"] in plan_check.PLAN_DETECTORS)
                    or (d["name"] in DETECTORS and layer in DETECTORS[d["name"]].layers))
            if not runs:
                missing.append(f"{d['name']}@{layer}")
    assert missing == []
    shipped = {name: set(det.layers) for name, det in DETECTORS.items()
               if det.fn.__module__.startswith("lapis_design.lint.detectors.")}
    assert {n: layers - listed.get(n, set()) for n, layers in shipped.items() if layers - listed.get(n, set())} == {}
