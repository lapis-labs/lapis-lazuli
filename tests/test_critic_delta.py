"""The delta critic: after the owner's rows change on a shown build a full critic report already judged, a delta packet
holds only what changed, the report on it counts with the prior report as one review, and nothing else does."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from lapis_design import critic_packet, release_check, workers
from lapis_design.cli import main as cli_main
from procedure_support import TASK, make_project, refresh_critic, report, row_id, save, update, write_requirements

ROWS = ("Show which pieces are in this firing", "Let a visitor reserve one without an account")
NEW = "Say what a firing costs before the visitor reserves"
PRIOR = ".lapis/critic/slice.json"
DELTA = ".lapis/critic/slice-delta.json"
DELTA_PACKET = ".lapis/critic/slice-delta.packet.json"
CORE = {"rule_id": "review.world-materials", "class": "default", "severity": {"create": "warn", "review": "P3"},
        "layer": "review", "observed": "only the naming story shows as such", "blocking": False,
        "evidence": {"type": "review", "refs": []}, "status": "open", "approval_impact": "core-product-explanation"}
ORDINARY = {**CORE, "rule_id": "review.wording", "observed": "two headlines read as one narrator",
            "approval_impact": "ordinary"}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    Image.new("RGB", (4, 4), "white").save(root / "shot.png")
    update(root, f"renders/{TASK}.json", lambda d: d["viewports"][1].update(screenshot="../../shot.png"))
    (root / "PRODUCT.md").write_text("# Kiln shop\nThe studio fires once a month.\n", encoding="utf-8")
    update(root, f"plans/{TASK}.yaml", lambda p: p["context"].update(product="PRODUCT.md"))
    write_requirements(root, ROWS)
    return root


@pytest.fixture(autouse=True)
def observed(monkeypatch):
    """`integrity.observe` writes records another lane owns: the packet command's call of it is a no-op here."""
    from lapis_design import integrity

    monkeypatch.setattr(integrity, "observe", lambda root, task, plan, by, **more: {"rows": [], "error": None})


def sealed(root: Path, *findings: dict) -> str:
    """A full critic report on the packet of the shown build, judging all of it: the review a delta follows."""
    refresh_critic(root, name="slice", extra={"findings": list(findings)})
    return PRIOR


def packet_cmd(root: Path, *args: str) -> int:
    return cli_main(["critic", "packet", "--task", TASK, "--root", str(root), *args])


def delta_packet(root: Path) -> dict:
    assert packet_cmd(root, "--prior", PRIOR, "--out", DELTA_PACKET) == 0
    return json.loads((root / DELTA_PACKET).read_text(encoding="utf-8"))


def delta_report(root: Path, *, skip_row: bool = False, skip_core: bool = False, redo: dict | None = None,
                 extra: dict | None = None, name: str = DELTA) -> dict:
    """The report of a critic that judged exactly what the delta packet lists."""
    data = (root / DELTA_PACKET).read_bytes()
    packet = json.loads(data)
    document = {
        **report("critic", extract=f".lapis/renders/{TASK}.json",
                 packet={"path": DELTA_PACKET, "sha256": critic_packet.digest(data)}),
        "requirements": [{"id": row["id"], "state": "met", "refs": []}
                         for row in packet["requirements"]["changed"][int(skip_row):]],
        "changes": [{"seq": c["seq"], "verdict": "repair", "rows": [], "why": "the change repairs the finding"}
                    for c in packet["changes"]["changed"]],
        "disputes": [{"index": d["index"], "verdict": "finding-holds", "why": "the capture shows the finding", "refs": []}
                     for d in packet["disputes"]["changed"]],
        "findings": [] if skip_core else [{**(redo or CORE), "supersedes": item["index"]}
                                          for item in packet["prior_findings"] if item["rejudge"]],
        **(extra or {})}
    save(root, name.removeprefix(".lapis/"), document)
    return document


def verdict(root: Path, name: str = DELTA, **more):
    return critic_packet.check(root, root / name, **more)


# ---------------------------------------------------------------- a delta exists only for owner rows on the same build

def test_a_new_owner_row_on_the_same_build_gets_a_delta_packet_of_that_row_alone(project, capsys):
    prior = sealed(project)
    write_requirements(project, (*ROWS, NEW))
    capsys.readouterr()
    doc = delta_packet(project)
    out = capsys.readouterr().out
    assert doc["kind"] == "delta" and doc["task"] == TASK
    assert [r["id"] for r in doc["requirements"]["changed"]] == [row_id(NEW)]
    assert doc["requirements"]["changed"][0]["change"] == "new" and doc["requirements"]["removed"] == []
    assert [i for i in doc["requirements"]["ids"] if not i.startswith("G:")] == [row_id(t) for t in (*ROWS, NEW)]
    full = critic_packet.build(project, TASK, {"extracts": [f".lapis/renders/{TASK}.json"],
                                               "lint": f".lapis/lint/{TASK}.json", "session": None})
    assert doc["prior"]["report"]["sha256"] == critic_packet.digest((project / prior).read_bytes())
    assert doc["prior"]["packet"]["sha256"] == json.loads((project / prior).read_text())["target"]["packet"]["sha256"]
    assert "inputs" not in doc and "plan" not in doc and doc["unchanged"]["inputs"]["count"] > 0
    assert len((project / DELTA_PACKET).read_bytes()) < len(full)
    assert "critic packet (delta)" in out and f"against {len(full)} for the full packet" in out
    line = json.loads((project / ".lapis/telemetry/checks.jsonl").read_text().splitlines()[-1])
    assert (line["command"], line["scope"], line["exit"]) == ("critic packet", "delta", 0)
    assert line["output_chars"] == len(out) and line["packet_chars"] == len((project / DELTA_PACKET).read_bytes())


def test_a_changed_row_and_a_dropped_row_are_listed_with_what_the_critic_must_judge(project):
    sealed(project)
    (project / "owner-brief.md").write_text(f"- {ROWS[0]}\n- {NEW}\n", encoding="utf-8")
    write_requirements(project, (ROWS[0], NEW))
    doc = delta_packet(project)
    assert doc["requirements"]["removed"] == [row_id(ROWS[1])]
    assert [r["id"] for r in doc["requirements"]["changed"]] == [row_id(NEW)]
    assert [i for i in doc["requirements"]["ids"] if not i.startswith("G:")] == [row_id(ROWS[0]), row_id(NEW)]


def test_no_change_since_the_prior_review_gives_no_delta(project, capsys):
    sealed(project)
    assert packet_cmd(project, "--prior", PRIOR, "--out", DELTA_PACKET) == 2
    assert "nothing changed since the prior review" in capsys.readouterr().err
    assert not (project / DELTA_PACKET).exists()


def _shot(root):
    Image.new("RGB", (4, 4), "black").save(root / "shot.png")


def _locale(root):
    update(root, f"renders/{TASK}.json",
           lambda d: d["viewports"][0].update(text=[{"text": "안녕", "lang": "ko", "font_size": 16}]))


def _lint(root):
    update(root, f"lint/{TASK}.json", lambda d: d["findings"].append(
        {"rule_id": "layout.card-everything", "class": "quality", "severity": {"create": "warn", "review": "P3"},
         "layer": "render", "observed": "Every section is a card", "blocking": False, "status": "open",
         "evidence": {"type": "measurement", "refs": []}}))


def _plan(root):
    update(root, f"plans/{TASK}.yaml", lambda p: p["layout"].update(signature="a different signature, as art direction"))


def _rules(root, monkeypatch):
    monkeypatch.setattr(workers, "rules", lambda: "Other worker rules.\n")


@pytest.mark.parametrize("change, named", [
    (_shot, "shot.png"), (_locale, f".lapis/renders/{TASK}.json"), (_lint, f".lapis/lint/{TASK}.json"),
    (_plan, "plan"), (_rules, "the worker rules")], ids=["screenshot", "locale-and-state", "lint", "art-direction", "rules"])
def test_a_change_of_capture_state_locale_implementation_or_rules_forces_a_full_review(project, monkeypatch, capsys,
                                                                                         change, named):
    sealed(project)
    write_requirements(project, (*ROWS, NEW))                           # the owner's rows changed as well
    change(project, monkeypatch) if change is _rules else change(project)
    found = critic_packet.delta(project, TASK, PRIOR)
    assert found.document is None and "more than the owner's rows changed" in found.reasons[0] and named in found.reasons[0]
    assert packet_cmd(project, "--prior", PRIOR, "--out", DELTA_PACKET) == 2
    assert "a full independent one" in capsys.readouterr().err
    assert not (project / DELTA_PACKET).exists()


def test_a_prior_report_that_did_not_judge_its_own_packet_gives_no_delta(project):
    sealed(project)
    update(project, "critic/slice.json", lambda d: d["requirements"].pop())
    write_requirements(project, (*ROWS, NEW))
    found = critic_packet.delta(project, TASK, PRIOR)
    assert found.document is None and "does not judge its own packet" in found.reasons[0]


def test_a_delta_never_follows_another_delta(project):
    sealed(project)
    write_requirements(project, (*ROWS, NEW))
    delta_packet(project)
    delta_report(project)
    found = critic_packet.delta(project, TASK, DELTA)
    assert found.document is None and "never another delta" in found.reasons[0]


# ---------------------------------------------------------------- the seal's acceptance of prior + delta

def test_the_report_on_a_delta_counts_with_the_prior_as_one_review_of_the_whole(project):
    sealed(project, CORE, ORDINARY)
    write_requirements(project, (*ROWS, NEW))
    doc = delta_packet(project)
    assert [(f["index"], f["rejudge"]) for f in doc["prior_findings"]] == [(0, True)]      # the ordinary one is not affected
    delta_report(project)
    assert verdict(project, allow_delta=True).problems == []
    whole = critic_packet.effective(project, project / DELTA)
    assert [r["id"] for r in whole["requirements"] if not r["id"].startswith("G:")] == [row_id(t) for t in (*ROWS, NEW)]
    assert sum(r["id"].startswith("G:") for r in whole["requirements"]) == 20      # the prior report judged them, and they carry over
    assert [f["rule_id"] for f in whole["findings"]] == ["review.world-materials", "review.wording"]
    assert "supersedes" not in whole["findings"][0] and whole["target"]["packet"]["path"] == DELTA_PACKET


def test_the_report_on_a_delta_that_leaves_out_a_changed_row_does_not_count(project):
    sealed(project)
    write_requirements(project, (*ROWS, NEW))
    delta_packet(project)
    delta_report(project, skip_row=True)
    problems = verdict(project, allow_delta=True).problems
    assert problems == [f"`requirements` has no entry for {row_id(NEW)}"]


def test_the_report_on_a_delta_that_judges_a_row_the_delta_does_not_list_does_not_count(project):
    sealed(project)
    write_requirements(project, (*ROWS, NEW))
    delta_packet(project)
    delta_report(project, extra={"requirements": [{"id": row_id(t), "state": "met", "refs": []} for t in (*ROWS, NEW)]})
    assert any("names" in p and "which the packet does not list" in p for p in verdict(project, allow_delta=True).problems)


def test_the_report_on_a_delta_that_does_not_re_judge_an_open_core_finding_does_not_count(project):
    sealed(project, CORE)
    write_requirements(project, (*ROWS, NEW))
    delta_packet(project)
    delta_report(project, skip_core=True)
    problems = verdict(project, allow_delta=True).problems
    assert len(problems) == 1 and "does not re-judge the open core finding 0 (review.world-materials)" in problems[0]


def test_a_core_finding_re_judged_open_but_not_core_or_as_another_rule_does_not_count(project):
    sealed(project, CORE)
    write_requirements(project, (*ROWS, NEW))
    delta_packet(project)
    delta_report(project, redo={**CORE, "approval_impact": "ordinary"})
    assert any("open but not core" in p for p in verdict(project, allow_delta=True).problems)
    delta_report(project, redo={**CORE, "rule_id": "review.wording"})
    assert any("re-judged as review.wording, not as review.world-materials" in p for p in verdict(project, allow_delta=True).problems)
    delta_report(project, redo={**CORE, "status": "fixed"})
    assert verdict(project, allow_delta=True).problems == []
    assert critic_packet.effective(project, project / DELTA)["findings"][0]["status"] == "fixed"


def test_a_prior_report_edited_after_the_delta_named_it_makes_the_delta_stale(project):
    sealed(project)
    write_requirements(project, (*ROWS, NEW))
    delta_packet(project)
    delta_report(project)
    update(project, "critic/slice.json", lambda d: d["requirements"][0].update(state="partly", note="edited by the maker"))
    stale = verdict(project, allow_delta=True).stale
    assert len(stale) == 1 and "the prior report" in stale[0] and "no review" in stale[0]


def test_a_capture_that_changes_after_the_delta_made_it_stale_and_needs_a_full_review(project):
    sealed(project)
    write_requirements(project, (*ROWS, NEW))
    delta_packet(project)
    delta_report(project)
    _shot(project)
    stale = verdict(project, allow_delta=True).stale
    assert len(stale) == 1 and "can no longer be a delta" in stale[0] and "shot.png" in stale[0]


def test_a_stale_full_report_after_an_owner_row_change_points_to_the_delta_command(project):
    sealed(project)
    write_requirements(project, (*ROWS, NEW))
    hinted = critic_packet.check(project, project / PRIOR, allow_delta=True).stale[0]
    assert f"--prior {PRIOR}" in hinted and "a delta review is enough" in hinted
    plain = critic_packet.check(project, project / PRIOR).stale[0]            # the release's critic is never offered one
    assert "delta" not in plain


def test_a_report_on_a_delta_is_not_the_release_critic(project, tmp_path):
    sealed(project)
    write_requirements(project, (*ROWS, NEW))
    delta_packet(project)
    release = delta_report(project, name=f".lapis/critic/{TASK}.json")
    assert verdict(project, f".lapis/critic/{TASK}.json", allow_delta=True).problems == []     # fine for the pre-show review
    stale = verdict(project, f".lapis/critic/{TASK}.json").stale
    assert len(stale) == 1 and "delta review never counts where a full independent review is required" in stale[0]
    result = release_check.run(project, TASK, static=True, offline=True)
    findings = [f for f in result["findings"] if f["rule_id"] in ("release.input-stale", "release.critic-missing")]
    assert findings and any("delta" in f["observed"] for f in findings) and release["requirements"]
