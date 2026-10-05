"""Approval waits require review of the page actually linked to the owner, not a release pass."""
import json
from pathlib import Path

import pytest
from PIL import Image

from lapis_design import gate, next_step
from procedure_support import TASK, ask, make_project, save, update

URL = "http://127.0.0.1:4173/system.html?lang=ko"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    ask(root, f"Approve this draft? {URL}", 200)
    return root


def reviewed(root):
    source = root / ".lapis/specimens/system.html"
    source.parent.mkdir(parents=True)
    source.write_text("<h1>Kiln log</h1><button>Reserve</button>")
    extract = json.loads((root / f".lapis/renders/{TASK}.json").read_text())
    extract["source"] = {"kind": "render", "url": URL.split("?")[0], "task": "shown-page"}
    extract["viewports"] = [v for v in extract["viewports"] if v["width"] in (390, 1440)]
    for view in extract["viewports"]:
        name = f"shown-{view['width']}.png"
        Image.new("RGB", (4, 4), "white").save(root / name)
        view["screenshot"] = "../../" + name
    save(root, "renders/shown-page.narrow.json", extract)
    lint = {"version": 0, "tool": {"name": "slop_lint", "version": "0.1.0"},
            "target": {"task": "shown-page", "extract": ".lapis/renders/shown-page.narrow.json"},
            "scope": {"layers": ["source", "render"], "draft": {"task": TASK, "url": URL,
                      "sources": [".lapis/specimens/system.html"], "excluded_sources": [], "aliases": []}}, "findings": []}
    save(root, "lint/shown-page.narrow.json", lint)
    critic = {"version": 0, "tool": {"name": "critic", "version": "0.1.0"},
              "target": {"extract": ".lapis/renders/shown-page.narrow.json"}, "findings": []}
    save(root, "critic/shown-page.json", critic)
    record = {"version": 0, "task": TASK, "pages": [{"url": URL, "render_task": "shown-page",
              "sources": [".lapis/specimens/system.html"], "direction": "new", "area": "whole page",
              "widths": [390, 1440], "behavior_changed": False,
              "review": {"extracts": [".lapis/renders/shown-page.narrow.json"],
                         "lint": ".lapis/lint/shown-page.narrow.json", "handled": [],
                         "making_of": "Copy describes the kiln studio, not the page's font or design decisions.",
                         "critic": {"report": ".lapis/critic/shown-page.json", "context": "fresh critic session",
                                    "independent": True},
                         "walkthroughs": [{"task": "Find and reserve a piece", "viewport": w,
                                           "completed": "partly", "first_look": "Firing log",
                                           "read_or_scrolled_past": "one section", "stuck": "Reservation not built",
                                           "refs": [f"shown-{w}.png"]} for w in (390, 1440)],
                         "summary": "The reservation path remains unresolved; reviewed both widths."}}]}
    save(root, f"drafts/{TASK}.yaml", record)
    return record


def test_a_linked_draft_without_review_cannot_become_an_approval_wait(project):
    result = next_step.evaluate(project, TASK)
    assert result["state"] == "needs-step"
    assert result["step"]["id"] == "draft-review"
    assert gate.stop_output(project, "draft", unattended=True, task=TASK)["decision"] == "block"


def test_a_pure_question_without_a_draft_can_still_wait(project):
    ask(project, "Should we keep the existing contract?", 201)
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"
    assert gate.stop_output(project, "question", unattended=True, task=TASK) is None


def test_review_of_the_exact_page_allows_waiting_without_a_release_pass(project):
    reviewed(project)
    result = next_step.evaluate(project, TASK)
    assert result["state"] == "waiting-for-user"
    assert "reservation path" in result["draft_review"][0]["summary"]
    assert gate.stop_output(project, "reviewed", unattended=True, task=TASK) is None


@pytest.mark.parametrize("mutate", [
    lambda d: d["pages"][0]["review"]["walkthroughs"].pop(),
    lambda d: d["pages"][0]["review"].pop("critic"),
    lambda d: d["pages"][0]["review"]["critic"].update(independent=False),
    lambda d: d["pages"][0].update(url="http://127.0.0.1:4173/other.html"),
], ids=["missing-width-walk", "missing-critic", "self-critic", "different-page"])
def test_incomplete_or_unrelated_review_does_not_allow_an_approval_wait(project, mutate):
    reviewed(project)
    update(project, f"drafts/{TASK}.yaml", mutate)
    assert next_step.evaluate(project, TASK)["step"]["id"] == "draft-review"


def test_a_finding_must_be_disposed_and_unresolved_is_not_a_fake_pass(project):
    record = reviewed(project)
    finding = {"rule_id": "layout.card-everything", "class": "quality", "severity": {"create": "gate", "review": "P1"},
               "layer": "render", "observed": "The content is enclosed in repeated cards", "blocking": True,
               "evidence": {"type": "measurement"}, "status": "open"}
    update(project, "lint/shown-page.narrow.json", lambda d: d["findings"].append(finding))
    save(project, f"drafts/{TASK}.yaml", record)
    assert next_step.evaluate(project, TASK)["step"]["id"] == "draft-review"
    record["pages"][0]["review"]["handled"] = [{"report": ".lapis/lint/shown-page.narrow.json", "finding": 0,
        "disposition": "unresolved", "reason": "The boxed comparison still dominates", "refs": ["shown-390.png"]}]
    save(project, f"drafts/{TASK}.yaml", record)
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"


def test_a_source_edit_invalidates_the_review_and_attended_gate_records_the_warning(project):
    reviewed(project)
    (project / ".lapis/specimens/system.html").write_text("<h1>Changed draft</h1>")
    assert next_step.evaluate(project, TASK)["step"]["id"] == "draft-review"
    assert "draft-review" in gate.stop_output(project, "attended", unattended=False, task=TASK)["systemMessage"]
    assert gate.load(project, TASK)["unreviewed_draft"]["step"] == "draft-review"


def test_small_iteration_reviews_only_its_changed_area_and_affected_width(project):
    record = reviewed(project)
    page = record["pages"][0]
    page.update(direction="iteration", area="phone heading", widths=[390])
    page["review"].pop("critic")
    page["review"]["walkthroughs"] = page["review"]["walkthroughs"][:1]
    save(project, f"drafts/{TASK}.yaml", record)
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"
