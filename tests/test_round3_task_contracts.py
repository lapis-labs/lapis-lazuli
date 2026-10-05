"""Phone task acceptance, real booking alternatives, and authored media inventory."""
from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


import pytest
import yaml

from lapis_design import plan_check, shared_dir
from lapis_design.lint.engine import lint
from lapis_design.lint.types import Context

SHARED = shared_dir()
RULES = yaml.safe_load((SHARED / "slop/rules.yaml").read_text())
TASK_RULE = "layout.primary-task-first-view"


def plan(mode="operate"):
    return {"version": 0, "mode": "repair", "task": {"id": "transit", "title": "Transit"},
            "brief": {"subject": "City transit", "one_job": "Choose a route and read its first arrival",
                      "platform": ["web"], "locales": ["en"], "product_frame": "saas-dashboard-admin"},
            "direction": {"read": {"surface_mode": [mode], "style_frame": "subject-derived"}},
            "defaults": []}


def phone_task():
    return {"decision": "Choose a route and read the first arrival",
            "first_result": "#arrivals tbody tr:first-child",
            "before_result": ["Route selection", "Direction and stop label"],
            "acceptance": "The first arrival is visible in the first phone view after choosing a route."}


def check(tmp_path, value):
    file = tmp_path / "plan.yaml"
    file.write_text(yaml.safe_dump(value))
    return plan_check.run(file, SHARED / "slop/rules.yaml", None, SHARED / "plan/schema.yaml", tmp_path)


def findings(report, rule):
    return [f for f in report["findings"] if f["rule_id"] == rule and f["status"] == "open"]


def test_operating_plan_owes_phone_task_acceptance_not_a_universal_cta(tmp_path):
    value = plan()
    assert findings(check(tmp_path, value), TASK_RULE)
    value["layout"] = {"phone_task": phone_task()}
    report = check(tmp_path, value)
    assert not findings(report, TASK_RULE)
    assert not findings(report, "schema.invalid")
    for genre in ("read", "experience", "persuade"):
        value = plan(genre)
        value["brief"]["product_frame"] = "content-editorial-docs"
        assert not findings(check(tmp_path, value), TASK_RULE)
        value["direction"]["read"]["surface_mode"].append("operate")
        value["brief"]["one_job"] = "Understand the exhibition and choose a visit through booking"
        if genre in ("experience", "persuade"):
            assert not findings(check(tmp_path, value), TASK_RULE)


@pytest.mark.parametrize("top,fires", [(725, False), (843, False), (844, True), (983, True), (909, True)])
def test_first_task_result_surfaces_round3_transit_depth_without_card_ratio(top, fires):
    value = plan()
    value["layout"] = {"phone_task": phone_task()}
    extract = {"version": 1, "source": {"kind": "render", "task": "transit"}, "viewports": [
        {"width": 390, "height": 844, "theme": "light", "boxes": [], "text": [],
         "derived": {"primary_task": {"selector": "#arrivals tbody tr:first-child", "y": top,
                                      "h": 44, "before": ["Route selection", "City summary"]}}}]}
    result = lint(Context(rules=RULES, plan=value, extract=extract, mode="review"), ["render"], [TASK_RULE])
    opened = [f for f in result if f["status"] == "open"]
    assert bool(opened) is fires
    if fires:
        assert opened[0]["blocking"] and opened[0]["severity"]["review"] == "P1"
        assert "City summary" in opened[0]["observed"]


def test_booking_shortness_needs_matched_phone_fields_and_states(tmp_path):
    value = plan()
    value["mode"] = "create"
    value["brief"].update(subject="Clinic appointments", one_job="Book an appointment",
                           product_frame="forms-onboarding-checkout")
    value.update(world_materials=["Appointment availability record"], sources=[{"ref": "PRODUCT.md"}])
    value["layout"] = {"procedure": {"archetype": "form"}}
    entry = {"decision": "layout", "candidates": [
        {"name": "Task stages", "source": "own sketch"},
        {"name": "Continuous intake", "source": "own sketch"}],
        "compared_on": ["sketch"], "chosen": "Task stages",
        "runner_up_lost": "The continuous intake made the current choice harder to locate."}
    value["explorations"] = [entry]
    assert findings(check(tmp_path, value), "plan.uncompared-decision")
    for candidate, mode in zip(entry["candidates"], ("staged", "continuous")):
        candidate["form_mode"] = mode
    entry["comparisons"] = [{"viewport": {"width": 390, "theme": "light"},
                             "state": "Date selected; availability pending, then empty and available",
                             "fields": ["Doctor", "Visit date", "Available time", "Patient phone"],
                             "captures": {"Task stages": "staged.png", "Continuous intake": "continuous.png"}}]
    entry["compared_on"] = ["render"]
    for candidate in entry["candidates"]:
        name = candidate["form_mode"] + ".html"
        candidate["artifact"] = name
        (tmp_path / name).write_text("<main><section>" + candidate["name"] + "</section></main>")
    for capture in entry["comparisons"][0]["captures"].values():
        (tmp_path / capture).write_bytes(b"observed capture fixture")
    report = check(tmp_path, value)
    assert not findings(report, "schema.invalid")
    assert not findings(report, "plan.uncompared-decision")
    entry["comparisons"][0]["viewport"]["width"] = 1440
    assert findings(check(tmp_path, value), "plan.uncompared-decision")


def test_standard_genre_sequence_can_be_kept_by_reader_questions(tmp_path):
    value = plan("persuade")
    value["brief"].update(one_job="Evaluate backup capability, recovery and cost", product_frame="marketing-landing")
    value["layout"] = {"sections": [
        {"id": "intro", "archetype": "hero", "answers": "What is backed up?"},
        {"id": "features", "archetype": "feature-grid", "answers": "How do I recover my files?"},
        {"id": "plans", "archetype": "pricing", "answers": "What will it cost?"},
        {"id": "questions", "archetype": "faq", "answers": "What limits remain?"},
        {"id": "start", "archetype": "cta", "answers": "How do I start?"}]}
    value["defaults"] = [{"id": "layout.template-section-sequence", "decision": "keep", "basis": "brief",
                          "keep_when": "reader-question-order",
                          "reason": "390 and 1440 captures follow capability, recovery, cost, limits and start; each section answers the buyer's question."}]
    assert not findings(check(tmp_path, value), "layout.template-section-sequence")
    assert not findings(check(tmp_path, value), TASK_RULE)


def test_image_inventory_records_roles_and_no_photo_is_a_real_candidate(tmp_path):
    value = plan("experience")
    value["brief"]["product_frame"] = "portfolio-personal"
    value["explorations"] = [{"decision": "layout", "candidates": [
        {"name": "Visit facts without photos", "source": "own sketch", "images": []},
        {"name": "Works and visit facts", "source": "materials inventory", "images": [
            {"source": "materials/plaster.jpg", "role": "evidence", "reason": "The actual exhibit surface supports its material description."}]}],
        "compared_on": ["sketch"], "chosen": "Works and visit facts",
        "runner_up_lost": "The no-photo version could not show the exhibition's material differences."}]
    report = check(tmp_path, value)
    assert not findings(report, "schema.invalid")
    del value["explorations"][0]["candidates"][1]["images"][0]["role"]
    assert findings(check(tmp_path, value), "schema.invalid")


@pytest.mark.parametrize("selector,hidden,measured", [("#eta", False, True), ("#eta", True, False),
                                                    ("#missing", False, False), ("[", False, False)])
def test_render_measures_result_not_the_already_visible_route_control(browser, tmp_path, selector, hidden, measured):
    from lapis_design.render import _configs
    from lapis_design.render.capture import capture
    from lapis_design.render.extract import assemble, validate

    (tmp_path / "index.html").write_text(
        '<!doctype html><html lang=en><meta name=viewport content="width=device-width,initial-scale=1">'
        '<style>body{margin:0}#eta{position:absolute;top:983px;height:44px;margin:0}</style>'
        '<main><h1>City summary</h1><label>Route<select><option>Green line</option></select></label>'
        f'<p id=eta style="display:{"none" if hidden else "block"}">First arrival: 2 min</p></main>')

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    value = plan()
    value["layout"] = {"phone_task": {**phone_task(), "first_result": selector}}
    try:
        vp = capture(browser, url, next(c for c in _configs(False, [390])), tmp_path / "phone.png",
                     bytes(range(32)), phone_task=value["layout"]["phone_task"])
        document = assemble(url, "transit", [vp], bytes(range(32)), dark_theme=False)
        assert validate(document) == []
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    fact = vp["derived"]["primary_task"]
    result = lint(Context(rules=RULES, plan=value, extract=document, mode="review"), ["render"], [TASK_RULE])
    if measured:
        assert fact["y"] == 983 and "City summary" in fact["before"]
        assert any(f["status"] == "open" and f["blocking"] for f in result)
    else:
        assert "y" not in fact and fact["unmeasured"]
        assert any(f["status"] == "skipped" for f in result)
        assert not any(f["status"] == "open" for f in result)
