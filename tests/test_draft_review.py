"""Approval waits require review of the page actually linked to the owner, not a release pass."""
import json

import pytest
from PIL import Image

from lapis_design import draft, gate, next_step
from procedure_support import TASK, ask, make_project, refresh_critic, save, update, write_requirements

URL = "http://127.0.0.1:4173/system.html?lang=ko"
CRITIC = ".lapis/critic/shown-page.json"
LINT = ".lapis/lint/shown-page.narrow.json"
EXTRACT = ".lapis/renders/shown-page.narrow.json"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    ask(root, f"Approve this draft? {URL}", 200)
    return root


def walks(*widths):
    return [{"task": "Find and reserve a piece", "viewport": w, "completed": "partly", "first_look": "Firing log",
             "read_or_scrolled_past": "one section", "stuck": "Reservation not built", "refs": [f"shown-{w}.png"]}
            for w in widths]


def critic(root, **extra):
    """The critic report of the shown page: built on a fresh packet of its captures and lint report."""
    return refresh_critic(root, task=TASK, extracts=[EXTRACT], lint=LINT, name="shown-page",
                          extra={"walkthroughs": walks(390, 1440), **extra})


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
            "target": {"task": "shown-page", "extract": EXTRACT},
            "scope": {"layers": ["source", "render"], "draft": {"task": TASK, "url": URL,
                      "sources": [".lapis/specimens/system.html"], "excluded_sources": [], "aliases": []}}, "findings": []}
    save(root, "lint/shown-page.narrow.json", lint)
    critic(root)
    record = {"version": 1, "task": TASK, "pages": [{"url": URL, "render_task": "shown-page",
              "sources": [".lapis/specimens/system.html"], "direction": "new", "area": "whole page",
              "widths": [390, 1440], "behavior_changed": False,
              "review": {"extracts": [EXTRACT], "lint": LINT, "handled": [], "critic": {"report": CRITIC}}}]}
    save(root, f"drafts/{TASK}.yaml", record)
    return record


def finding(rule, status="open", **more):
    return {"rule_id": rule, "class": "quality", "severity": {"create": "warn", "review": "P3"}, "layer": "review",
            "observed": "The core product explanation is absent; current settings are not actual product results",
            "blocking": False, "evidence": {"type": "review"}, "status": status, **more}


def disposed(report, disposition, finding_index=0):
    return {"report": report, "finding": finding_index, "disposition": disposition,
            "reason": "Only the current page settings are now shown", "refs": ["shown-390.png"]}


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
    [page] = result["draft_review"]
    assert set(page) == {"url", "area", "widths", "findings", "critic"}        # no maker prose reaches the summary
    assert page["critic"]["report"] == CRITIC
    assert page["critic"]["packet_sha256"] == json.loads((project / CRITIC).read_text())["target"]["packet"]["sha256"]
    assert (project / ".lapis/critic/shown-page.packet.json").is_file()
    assert gate.stop_output(project, "reviewed", unattended=True, task=TASK) is None


def test_a_v0_record_gets_an_explanation_and_is_not_read_as_v1(project):
    record = reviewed(project)
    page = record["pages"][0]
    page["review"].update(summary="The reservation path remains unresolved.", making_of="Copy describes the kiln studio.",
                          walkthroughs=walks(390, 1440))
    save(project, f"drafts/{TASK}.yaml", {**record, "version": 0})
    errors, summaries = draft.check(project, TASK)
    assert summaries == [] and len(errors) == 1
    assert "maker prose fields" in errors[0] and "rewrite it as version 1" in errors[0]
    assert next_step.evaluate(project, TASK)["step"]["id"] == "draft-review"


@pytest.mark.parametrize("field, value", [
    ("summary", "The reservation path remains unresolved."),
    ("making_of", "Copy describes the kiln studio, not the page's font or design decisions."),
    ("walkthroughs", walks(390, 1440)),
    ("claim_evidence", [{"requirement": "Let visitors see this firing's pieces", "kind": "product-output",
                         "state": "shown", "shown": ["shown-390.png"], "missing": ""}]),
])
def test_a_v1_review_carries_no_maker_prose_the_cli_cannot_verify(project, field, value):
    record = reviewed(project)
    record["pages"][0]["review"][field] = value
    save(project, f"drafts/{TASK}.yaml", record)
    errors, _ = draft.check(project, TASK)
    assert errors and "Additional properties" in errors[0] and field in errors[0]


@pytest.mark.parametrize("path, value", [
    (("critic", "context"), "fresh critic session"),
    (("critic", "independent"), True),
])
def test_a_critic_is_no_longer_attested_by_the_maker(project, path, value):
    record = reviewed(project)
    record["pages"][0]["review"][path[0]][path[1]] = value
    save(project, f"drafts/{TASK}.yaml", record)
    errors, _ = draft.check(project, TASK)
    assert errors and "Additional properties" in errors[0] and path[1] in errors[0]


def test_resolution_kind_is_no_longer_a_disposition_field(project):
    record = reviewed(project)
    update(project, CRITIC.removeprefix(".lapis/"), lambda d: d["findings"].append(finding("review.world-materials")))
    record["pages"][0]["review"]["handled"] = [{**disposed(CRITIC, "fixed"), "resolution_kind": "product-output"}]
    save(project, f"drafts/{TASK}.yaml", record)
    errors, _ = draft.check(project, TASK)
    assert errors and "Additional properties" in errors[0] and "resolution_kind" in errors[0]


def test_a_new_direction_needs_a_critic_report(project):
    record = reviewed(project)
    record["pages"][0]["review"].pop("critic")
    save(project, f"drafts/{TASK}.yaml", record)
    errors, _ = draft.check(project, TASK)
    assert errors and "needs a critic report built on `lapis-design critic packet`" in errors[0]
    assert next_step.evaluate(project, TASK)["step"]["id"] == "draft-review"


def test_a_new_direction_needs_the_critics_own_walkthrough_at_every_shown_width(project):
    reviewed(project)
    update(project, CRITIC.removeprefix(".lapis/"), lambda d: d["walkthroughs"].pop())
    errors, _ = draft.check(project, TASK)
    assert errors and "no walkthrough at 1440" in errors[0]
    update(project, CRITIC.removeprefix(".lapis/"), lambda d: d.pop("walkthroughs"))
    errors, _ = draft.check(project, TASK)
    assert errors and "no walkthrough at 390, 1440" in errors[0]


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d["target"].pop("packet"), "names none"),
    (lambda d: d["target"]["packet"].update(sha256="0" * 64), "was rebuilt after the critic named it"),
    (lambda d: d["target"]["packet"].update(path=".lapis/critic/missing.packet.json"), "is not a file in the project"),
], ids=["names-no-packet", "wrong-digest", "missing-packet-file"])
def test_a_critic_report_that_does_not_name_the_current_packet_does_not_count(project, mutate, expected):
    reviewed(project)
    update(project, CRITIC.removeprefix(".lapis/"), mutate)
    errors, _ = draft.check(project, TASK)
    assert errors and "critic report was made from another packet" in errors[0] and expected in errors[0]
    assert next_step.evaluate(project, TASK)["step"]["id"] == "draft-review"


def test_a_capture_or_lint_change_after_the_critic_ran_makes_its_report_stale(project):
    record = reviewed(project)
    update(project, "lint/shown-page.narrow.json", lambda d: d["findings"].append(finding("layout.card-everything")))
    record["pages"][0]["review"]["handled"] = [disposed(LINT, "unresolved", 0)]
    save(project, f"drafts/{TASK}.yaml", record)
    errors, _ = draft.check(project, TASK)
    assert errors and "critic report was made from another packet" in errors[0] and "inputs" in errors[0]
    critic(project)
    save(project, f"drafts/{TASK}.yaml", record)
    assert draft.check(project, TASK)[0] == []


def test_a_critic_packet_built_from_other_captures_than_the_page_reviewed_does_not_count(project):
    reviewed(project)
    save(project, "lint/other.narrow.json", json.loads((project / LINT).read_text()))
    refresh_critic(project, task=TASK, extracts=[EXTRACT], lint=".lapis/lint/other.narrow.json", name="shown-page",
                   extra={"walkthroughs": walks(390, 1440)})
    errors, _ = draft.check(project, TASK)
    assert errors and "another lint report than this page's review" in errors[0]


def test_a_critic_report_must_judge_every_requirement_row_of_its_packet(project):
    write_requirements(project, ("Show which pieces are in this firing", "Let a visitor reserve one"))
    reviewed(project)
    assert draft.check(project, TASK)[0] == []
    update(project, CRITIC.removeprefix(".lapis/"), lambda d: d["requirements"].pop())
    errors, _ = draft.check(project, TASK)
    assert errors and "`requirements` has no entry for" in errors[0]


def test_an_iteration_needs_no_critic_and_a_new_direction_is_the_only_one_that_does(project):
    record = reviewed(project)
    page = record["pages"][0]
    page.update(direction="iteration", area="phone heading", widths=[390])
    page["review"].pop("critic")
    save(project, f"drafts/{TASK}.yaml", record)
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"


@pytest.mark.parametrize("mutate", [
    lambda d: d["pages"][0]["review"].pop("critic"),
    lambda d: d["pages"][0].update(url="http://127.0.0.1:4173/other.html"),
], ids=["missing-critic", "different-page"])
def test_incomplete_or_unrelated_review_does_not_allow_an_approval_wait(project, mutate):
    reviewed(project)
    update(project, f"drafts/{TASK}.yaml", mutate)
    assert next_step.evaluate(project, TASK)["step"]["id"] == "draft-review"


def test_a_finding_must_be_disposed_and_unresolved_is_not_a_fake_pass(project):
    record = reviewed(project)
    lint_finding = {"rule_id": "layout.card-everything", "class": "quality", "severity": {"create": "gate", "review": "P1"},
                    "layer": "render", "observed": "The content is enclosed in repeated cards", "blocking": True,
                    "evidence": {"type": "measurement"}, "status": "open"}
    update(project, "lint/shown-page.narrow.json", lambda d: d["findings"].append(lint_finding))
    critic(project)
    save(project, f"drafts/{TASK}.yaml", record)
    assert next_step.evaluate(project, TASK)["step"]["id"] == "draft-review"
    record["pages"][0]["review"]["handled"] = [{"report": LINT, "finding": 0, "disposition": "unresolved",
        "reason": "The boxed comparison still dominates", "refs": ["shown-390.png"]}]
    save(project, f"drafts/{TASK}.yaml", record)
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"


def test_a_source_edit_invalidates_the_review_and_attended_gate_records_the_warning(project):
    reviewed(project)
    (project / ".lapis/specimens/system.html").write_text("<h1>Changed draft</h1>")
    assert next_step.evaluate(project, TASK)["step"]["id"] == "draft-review"
    assert "draft-review" in gate.stop_output(project, "attended", unattended=False, task=TASK)["systemMessage"]
    assert gate.load(project, TASK)["unreviewed_draft"]["step"] == "draft-review"


@pytest.mark.parametrize("disposition", ["fixed", "justified-keep", "unresolved"])
@pytest.mark.parametrize("rule, more", [
    ("review.world-materials", {}),
    ("review.product-proof", {"approval_impact": "core-product-explanation"}),
], ids=["world-materials", "marked-core"])
def test_an_open_core_product_finding_in_the_current_critic_blocks_the_wait_whatever_the_disposition(
        project, rule, more, disposition):
    record = reviewed(project)
    update(project, CRITIC.removeprefix(".lapis/"), lambda d: d["findings"].append(finding(rule, **more)))
    record["pages"][0]["review"]["handled"] = [disposed(CRITIC, disposition)]
    save(project, f"drafts/{TASK}.yaml", record)
    result = next_step.evaluate(project, TASK)
    assert result["step"]["id"] == "draft-review"
    state = result["draft_review"][0]["findings"][0]
    assert state["approval_blocking"] is True
    assert (state["status"], state["disposition"], state["reported_disposition"]) == ("open", "unresolved", disposition)


def test_a_fresh_critic_that_no_longer_reports_the_gap_open_closes_it(project):
    record = reviewed(project)
    update(project, CRITIC.removeprefix(".lapis/"),
           lambda d: d["findings"].append(finding("review.world-materials", status="fixed")))
    record["pages"][0]["review"]["handled"] = [disposed(CRITIC, "fixed")]
    save(project, f"drafts/{TASK}.yaml", record)
    result = next_step.evaluate(project, TASK)
    assert result["state"] == "waiting-for-user"
    assert result["draft_review"][0]["findings"][0]["approval_blocking"] is False


def test_a_world_materials_finding_the_critic_scopes_as_ordinary_does_not_block(project):
    record = reviewed(project)
    update(project, CRITIC.removeprefix(".lapis/"), lambda d: d["findings"].append(
        finding("review.world-materials", approval_impact="ordinary", observed="A secondary example is not shown")))
    record["pages"][0]["review"]["handled"] = [disposed(CRITIC, "unresolved")]
    save(project, f"drafts/{TASK}.yaml", record)
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"
