"""The pre-show review and the slice seal take the critic's report on a delta packet together with the full report it
follows, and read the whole as one report; a draft record never gets there by editing a report."""
from __future__ import annotations

import json

from lapis_design import critic_packet, draft, next_step, owner
from lapis_design.cli import main as cli_main
from procedure_support import TASK, report, save, write_requirements
from test_draft_review import CRITIC, EXTRACT, finding, project, reviewed  # noqa: F401  (a project that asked about URL)

DELTA_PACKET = ".lapis/critic/shown-delta.packet.json"
DELTA = ".lapis/critic/shown-delta.json"
NEW_ROW = "Say what a firing costs before the visitor reserves"


def delta_report(root, **more) -> dict:
    data = (root / DELTA_PACKET).read_bytes()
    packet = json.loads(data)
    document = {**report("critic", extract=EXTRACT, packet={"path": DELTA_PACKET, "sha256": critic_packet.digest(data)}),
                "requirements": [{"id": r["id"], "state": "partly", "refs": []} for r in packet["requirements"]["changed"]],
                "findings": [{**finding("review.world-materials"), "supersedes": f["index"], "approval_impact":
                              "core-product-explanation"} for f in packet["prior_findings"] if f["rejudge"]], **more}
    save(root, DELTA.removeprefix(".lapis/"), document)
    return document


def delta_for(root, record) -> dict:
    """The page after the owner added a row: a delta packet on the full report it was shown with, its report, and the
    record naming that report."""
    write_requirements(root, (NEW_ROW,))
    assert cli_main(["critic", "packet", "--task", TASK, "--root", str(root), "--prior", CRITIC, "--out", DELTA_PACKET]) == 0
    delta_report(root)
    record["pages"][0]["review"]["critic"]["report"] = DELTA
    save(root, f"drafts/{TASK}.yaml", record)
    return record


def test_a_report_made_stale_by_an_owner_row_is_told_the_delta_command_the_page_can_use(project):
    record = reviewed(project)
    write_requirements(project, (NEW_ROW,))
    errors, _ = draft.check(project, TASK)
    assert len(errors) == 1 and f"--prior {CRITIC}" in errors[0] and "a delta review is enough" in errors[0]


def test_the_page_is_reviewed_by_the_prior_report_and_the_delta_as_one(project):
    record = reviewed(project)
    delta_for(project, record)
    errors, summaries = draft.check(project, TASK)
    assert errors == []
    [page] = summaries
    assert page["critic"] == {"report": DELTA, "packet_sha256": json.loads((project / DELTA).read_text())["target"]["packet"]["sha256"]}
    whole = critic_packet.effective(project, project / DELTA)
    assert len(whole["requirements"]) == len(json.loads((project / DELTA_PACKET).read_text())["requirements"]["ids"])
    assert {w["viewport"] for w in whole["walkthroughs"]} == {390, 1440}          # the walks of the full report still count


def test_an_open_core_finding_of_the_prior_report_stays_the_owners_decision_through_the_delta(project):
    record = reviewed(project)
    core = {**finding("review.world-materials"), "approval_impact": "core-product-explanation"}
    from test_draft_review import critic

    critic(project, findings=[core])
    record["pages"][0]["review"]["handled"] = [{"report": CRITIC, "finding": 0, "disposition": "justified-keep",
                                               "reason": "Only the page settings are shown", "refs": ["shown-390.png"]}]
    save(project, f"drafts/{TASK}.yaml", record)
    assert [c["rule_id"] for c in draft.check(project, TASK)[1][0]["core_open"]] == ["review.world-materials"]
    write_requirements(project, (NEW_ROW,))
    assert cli_main(["critic", "packet", "--task", TASK, "--root", str(project), "--prior", CRITIC, "--out", DELTA_PACKET]) == 0
    delta_report(project)
    record["pages"][0]["review"]["critic"]["report"] = DELTA
    record["pages"][0]["review"]["handled"][0]["report"] = DELTA
    save(project, f"drafts/{TASK}.yaml", record)
    errors, summaries = draft.check(project, TASK)
    assert errors == [] and [c["rule_id"] for c in summaries[0]["core_open"]] == ["review.world-materials"]
    assert owner.core_findings(project, TASK) == [("review.world-materials", finding("review.world-materials")["observed"])]


def test_a_delta_report_that_leaves_the_core_finding_out_does_not_review_the_page(project):
    record = reviewed(project)
    from test_draft_review import critic

    critic(project, findings=[{**finding("review.world-materials"), "approval_impact": "core-product-explanation"}])
    record["pages"][0]["review"]["handled"] = [{"report": CRITIC, "finding": 0, "disposition": "justified-keep",
                                               "reason": "Only the page settings are shown", "refs": ["shown-390.png"]}]
    save(project, f"drafts/{TASK}.yaml", record)
    write_requirements(project, (NEW_ROW,))
    assert cli_main(["critic", "packet", "--task", TASK, "--root", str(project), "--prior", CRITIC, "--out", DELTA_PACKET]) == 0
    delta_report(project, findings=[])
    record["pages"][0]["review"]["critic"]["report"] = DELTA
    save(project, f"drafts/{TASK}.yaml", record)
    errors, _ = draft.check(project, TASK)
    assert len(errors) == 1 and "does not re-judge the open core finding 0 (review.world-materials)" in errors[0]


def test_the_owner_block_reads_the_delta_as_one_report_and_the_summary_counts_every_row(project):
    record = reviewed(project)
    delta_for(project, record)
    delivery = owner.deliver(project, TASK, {"kind": "approval"})
    rows = [i for i in json.loads((project / DELTA_PACKET).read_text())["requirements"]["ids"] if not i.startswith("G:")]   # the summary counts the owner's rows
    assert f"requirements, the page http://127.0.0.1:4173/system.html?lang=ko: " in delivery.summary
    assert f"of {len(rows)}" in delivery.summary and "partly" in delivery.summary
    assert "does not judge" not in delivery.block and "critic report was made from another packet" not in delivery.block
    assert next_step.evaluate(project, TASK)["step"] is not None
