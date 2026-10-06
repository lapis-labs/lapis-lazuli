"""The critic packet: what a critic is given, that nothing the maker wrote to justify itself reaches it, that any input
change makes a critic report stale, and what makes a report hold against its packet."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
import yaml
from PIL import Image

import lapis_design
from lapis_design import critic_packet, shared_dir, summary
from lapis_design.cli import main as cli_main
from procedure_support import TASK, make_project, refresh_critic, row_id, save, update, write_requirements

SHARED = shared_dir()
ROWS = ("Show which pieces are in this firing", "Let a visitor reserve one without an account")
PRODUCT = "# Kiln shop\nThe studio fires once a month.\nEvery piece is glazed by hand in the studio.\nPickup is on Saturdays.\n"
REASONS = ("Body text favors mobile readability, so a neutral sans stays",
           "Noto Serif KR held the title evenly but read as a newspaper",
           "Not a sales page but the record of one firing",
           "Pretendard won the body specimen on a phone against Noto Sans KR")
PLAN = f"plans/{TASK}.yaml"
REPORT = f".lapis/critic/{TASK}.json"
INPUTS = {"extracts": [f".lapis/renders/{TASK}.json"], "lint": f".lapis/lint/{TASK}.json", "session": None}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("LAZULI_DB", "")
    root = make_project(tmp_path)
    shot = root / "shot.png"
    Image.new("RGB", (4, 4), "white").save(shot)
    update(root, f"renders/{TASK}.json", lambda d: d["viewports"][1].update(screenshot="../../shot.png"))
    (root / "PRODUCT.md").write_text(PRODUCT, encoding="utf-8")
    update(root, PLAN, lambda p: p["context"].update(product="PRODUCT.md"))
    write_requirements(root, ROWS)
    return root


def packet(root: Path, **inputs) -> dict:
    return json.loads(critic_packet.build(root, TASK, {**INPUTS, **inputs}))


def digest(root: Path, **inputs) -> str:
    return critic_packet.digest(critic_packet.build(root, TASK, {**INPUTS, **inputs}))


def judged(root: Path, **extra) -> dict:
    return refresh_critic(root, extra=extra)


def problems(root: Path) -> list[str]:
    return critic_packet.verify(root, root / REPORT)


def change_row(seq: int, **more) -> dict:
    return {"seq": seq, "at": "2026-10-06T00:00:00Z", "by": "next", "kind": "protected", "pointer": "/brief",
            "before": None, "after": None, "related_open": [], "reactive": False, "after_slice": False,
            "prev": None, **more}


def log(root: Path, *rows: dict) -> None:
    path = root / f".lapis/changes/{TASK}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def dispute(root: Path, reason: str = "The finding reads a box that is hidden on phones") -> None:
    save(root, f"disputes/{TASK}.yaml", {"version": 0, "task": TASK, "disputes": [{
        "report": f".lapis/lint/{TASK}.json", "rule_id": "layout.card-everything", "observed": "Every section is a card",
        "reason": reason, "refs": ["shot.png"]}]})


def test_the_packet_leaves_out_what_the_maker_wrote_to_justify_itself_and_gives_the_rules_own_case_text(project):
    dispute(project, "DISPUTE-REASON the box is hidden on phones")
    log(project, change_row(1, pointer="/defaults[id=type.single-neutral-sans]", reactive=True,
                            related_open=["type.single-neutral-sans"],
                            before=None, after={"id": "type.single-neutral-sans", "decision": "keep",
                                                "keep_when": "platform-body-readability",
                                                "reason": "CHANGE-REASON keep it", "evidence": {"brief": "EVIDENCE-LINE"}}),
        change_row(2, pointer="/approval/reason", after_slice=True, before="APPROVAL-REASON before",
                   after="APPROVAL-REASON the owner said go ahead"))
    raw = critic_packet.build(project, TASK, INPUTS).decode()
    for reason in (*REASONS, "DISPUTE-REASON", "CHANGE-REASON", "EVIDENCE-LINE", "APPROVAL-REASON"):
        assert reason not in raw
    doc = json.loads(raw)
    rules = yaml.safe_load((SHARED / "slop/rules.yaml").read_text(encoding="utf-8"))["rules"]
    case = next(c for r in rules if r["id"] == "type.single-neutral-sans" for c in r["keep_when"]
                if c["id"] == "platform-body-readability")
    assert {d["id"]: d for d in doc["plan"]["defaults"]}["type.single-neutral-sans"] == {
        "id": "type.single-neutral-sans", "decision": "keep", "keep_when": "platform-body-readability",
        "case_when": case["when"]}
    assert not any(key in d for d in doc["plan"]["defaults"] for key in ("reason", "evidence", "basis"))
    assert all("runner_up_lost" not in e and "reason" not in e for e in doc["plan"]["explorations"])
    assert "concept" not in raw and doc["plan"]["explorations"][0]["chosen"]
    assert doc["disputes"] == [{"index": 0, "report": f".lapis/lint/{TASK}.json", "rule_id": "layout.card-everything",
                                "observed": "Every section is a card"}]
    assert doc["changes"][0]["after"] == {"id": "type.single-neutral-sans", "decision": "keep",
                                          "keep_when": "platform-body-readability"}
    assert doc["changes"][1] == {"seq": 2, "kind": "protected", "pointer": "/approval/reason", "before": None,
                                 "after": None, "related_open": [], "reactive": False, "after_slice": True}


def test_the_packet_carries_the_rows_the_inputs_and_the_changes_that_matter(project):
    log(project, change_row(1), change_row(2, reactive=True), change_row(3, related_open=["type.flat-hierarchy"]),
        change_row(4, after_slice=True))
    doc = packet(project)
    assert [r["text"] for r in doc["requirements"]["rows"]] == list(ROWS)
    assert [r["id"] for r in doc["requirements"]["rows"]] == [row_id(t) for t in ROWS]
    assert [c["seq"] for c in doc["changes"]] == [2, 3, 4]             # a change that touched nothing open is not asked about
    assert {"at", "by", "prev"} & set(doc["changes"][0]) == set()       # nothing that differs between two observes
    kinds = {i["path"]: i["kind"] for i in doc["inputs"]}
    assert kinds[f".lapis/renders/{TASK}.json"] == "extract" and kinds["shot.png"] == "screenshot"
    assert kinds[f".lapis/lint/{TASK}.json"] == "lint" and kinds["PRODUCT.md"] == "product"
    assert kinds[f".lapis/references/{TASK}.md"] == "references-record"
    assert not any(path.startswith((".lapis/plans", ".lapis/answers", ".lapis/drafts", ".lapis/questions"))
                   for path in kinds)


def test_the_same_inputs_give_the_same_bytes(project):
    first = critic_packet.build(project, TASK, INPUTS)
    for path in project.rglob("*"):
        if path.is_file():
            path.touch()
    assert critic_packet.build(project, TASK, INPUTS) == first


def lint_finding(root):
    update(root, f"lint/{TASK}.json", lambda d: d["findings"].append({
        "rule_id": "layout.card-everything", "class": "quality", "severity": {"create": "warn", "review": "P2"},
        "layer": "render", "observed": "Every section is a card", "blocking": False, "status": "open",
        "evidence": {"type": "measurement"}}))


def screenshot(root):
    Image.new("RGB", (4, 4), "black").save(root / "shot.png")


MOVING = [
    ("lint-finding", lint_finding, "findings"),
    ("screenshot-bytes", screenshot, "inputs shot.png"),
    ("requirement-row", lambda r: write_requirements(r, (*ROWS, "A third thing the owner asked for")), "requirements"),
    ("protected-plan-value", lambda r: update(r, PLAN, lambda p: p["brief"].update(one_job="Let visitors reserve")),
     "plan brief"),
    ("kept-default", lambda r: update(r, PLAN, lambda p: p["defaults"][0].update(keep_when="real-category")),
     "plan defaults"),
    ("change-row", lambda r: log(r, change_row(1, reactive=True)), "changes"),
    ("dispute", dispute, "disputes"),
    ("product-document", lambda r: (r / "PRODUCT.md").write_text(PRODUCT + "One more line.\n"), "inputs PRODUCT.md"),
    ("taste", lambda r: (r / ".lapis/taste.md").write_text("# Taste\n"), "inputs .lapis/taste.md"),
    ("reference-capture", lambda r: next((r / f".lapis/references/{TASK}").glob("*.png")).write_bytes(b"x"),
     "inputs .lapis/references"),
]


@pytest.mark.parametrize("change, expected", [(m[1], m[2]) for m in MOVING], ids=[m[0] for m in MOVING])
def test_any_input_change_changes_the_digest_and_makes_a_judged_report_stale(project, change, expected):
    judged(project)
    assert problems(project) == []
    before = digest(project)
    change(project)
    assert digest(project) != before
    [stale] = critic_packet.check(project, project / REPORT).stale
    assert stale.startswith("critic report was made from another packet") and expected in stale


@pytest.mark.parametrize("change", [
    lambda r: update(r, PLAN, lambda p: p["direction"].update(concept="A different tension, said differently")),
    lambda r: update(r, PLAN, lambda p: p["defaults"][0].update(reason="A different reason, written after the finding")),
    lambda r: update(r, PLAN, lambda p: p["explorations"][0].update(runner_up_lost="A reason the runner-up lost, again")),
    lambda r: update(r, PLAN, lambda p: p["layout"]["procedure"].update(grid="a different grid, said differently")),
    lambda r: [p.touch() for p in r.rglob("*") if p.is_file()],
], ids=["concept", "default-reason", "runner-up-reason", "unread-layout-field", "touch"])
def test_what_the_packet_does_not_carry_cannot_make_a_report_stale(project, change):
    judged(project)
    before = digest(project)
    change(project)
    assert digest(project) == before
    assert problems(project) == []


def test_a_report_that_judges_everything_holds(project):
    write_requirements(project, ROWS)
    log(project, change_row(1, reactive=True))
    dispute(project)
    judged(project)
    assert problems(project) == []


def reported(project) -> dict:
    write_requirements(project, ROWS)
    log(project, change_row(1, reactive=True, related_open=["layout.card-everything"]))
    dispute(project)
    return judged(project)


def edit(project, change):
    path = project / REPORT
    document = json.loads(path.read_text())
    change(document)
    path.write_text(json.dumps(document), encoding="utf-8")


FAULTS = [
    ("names-no-packet", lambda d: d["target"].pop("packet"), "names none", "stale"),
    ("wrong-digest", lambda d: d["target"]["packet"].update(sha256="1" * 64), "was rebuilt after the critic named it", "stale"),
    ("missing-packet-file", lambda d: d["target"]["packet"].update(path=".lapis/critic/gone.packet.json"),
     "is not a file in the project", "stale"),
    ("missing-row", lambda d: d["requirements"].pop(), "`requirements` has no entry for " + row_id(ROWS[1]), "gaps"),
    ("no-requirements-at-all", lambda d: d.pop("requirements"), "`requirements` has no entry for", "gaps"),
    ("unknown-row", lambda d: d["requirements"].append({"id": "R000000", "state": "met", "refs": []}),
     "`requirements` names R000000, which the packet does not list", "gaps"),
    ("row-judged-twice", lambda d: d["requirements"].append(d["requirements"][0]),
     "`requirements` judges " + row_id(ROWS[0]) + " more than once", "gaps"),
    ("missing-change", lambda d: d["changes"].pop(), "`changes` has no entry for change 1", "gaps"),
    ("unknown-change", lambda d: d["changes"].append({"seq": 9, "verdict": "unclear", "rows": [], "why": "no such change"}),
     "`changes` names change 9, which the packet does not list", "gaps"),
    ("change-names-an-unknown-row", lambda d: d["changes"][0].update(rows=["R000000"]),
     "change 1 names R000000, which are not requirement rows of the packet", "gaps"),
    ("missing-dispute", lambda d: d["disputes"].pop(), "`disputes` has no entry for dispute 0", "gaps"),
    ("ref-to-a-file-that-does-not-exist", lambda d: d["requirements"][0].update(refs=["missing-capture.png"]),
     "the ref missing-capture.png is not a file in the project", "gaps"),
    ("ref-to-the-plan", lambda d: d["disputes"][0].update(refs=[f".lapis/plans/{TASK}.yaml"]),
     f"the ref .lapis/plans/{TASK}.yaml is a file the critic does not read", "gaps"),
    ("fact-quote-absent-from-its-lines", lambda d: d.update(facts=[
        {"text": "The studio is old", "refs": [], "source": "PRODUCT.md#L2-L3", "quote": "The studio is a hundred years old"}]),
     "fact 0: the quote is not in PRODUCT.md lines 2-3", "gaps"),
    ("fact-quote-outside-the-cited-lines", lambda d: d.update(facts=[
        {"text": "Pickup", "refs": [], "source": "PRODUCT.md#L2-L3", "quote": "Pickup is on Saturdays."}]),
     "fact 0: the quote is not in PRODUCT.md lines 2-3", "gaps"),
    ("fact-from-a-file-the-packet-does-not-list", lambda d: d.update(facts=[
        {"text": "x y z", "refs": [], "source": f".lapis/plans/{TASK}.yaml#L1", "quote": "task"}]),
     "is not a file the packet lists", "gaps"),
    ("fact-lines-out-of-range", lambda d: d.update(facts=[
        {"text": "x y z", "refs": [], "source": "PRODUCT.md#L40-L41", "quote": "x"}]),
     "fact 0: lines 40-41 are outside PRODUCT.md (4 lines)", "gaps"),
    ("fact-source-that-is-no-path", lambda d: d.update(facts=[
        {"text": "x y z", "refs": [], "source": "the readme", "quote": "x"}]),
     "fact 0: the source 'the readme' is neither `none` nor `path#Lx-Ly`", "gaps"),
]


@pytest.mark.parametrize("fault, expected, kind", [f[1:] for f in FAULTS], ids=[f[0] for f in FAULTS])
def test_a_report_that_does_not_hold_against_its_packet_says_where(project, fault, expected, kind):
    reported(project)
    assert problems(project) == []
    edit(project, fault)
    verdict = critic_packet.check(project, project / REPORT)
    assert any(expected in line for line in getattr(verdict, kind)), verdict.problems
    assert (verdict.stale == []) == (kind == "gaps")                    # a stale report is not judged for coverage


def test_facts_with_a_quote_in_their_lines_or_no_source_hold(project):
    reported(project)
    edit(project, lambda d: d.update(facts=[
        {"text": "The studio fires monthly", "refs": ["shot.png", "b0123456789ab"], "source": "PRODUCT.md#L2",
         "quote": "THE STUDIO   fires once a month."},
        {"text": "Pieces are glazed by hand", "refs": [], "source": "PRODUCT.md#L2-L3",
         "quote": "every piece is glazed by hand in the studio"},
        {"text": "The shop opened in 1998", "refs": [], "source": "none", "quote": ""}]))
    assert problems(project) == []


def test_a_box_id_or_a_session_step_in_a_ref_is_not_a_file(project):
    reported(project)
    edit(project, lambda d: d["requirements"][0].update(refs=["b0123456789ab", "step 3", "shot.png#b0123456789ab"]))
    assert problems(project) == []


@pytest.fixture
def observed(monkeypatch):
    """`integrity.observe` is another lane's module: a stand-in that records when `critic packet` calls it."""
    calls = []

    def observe(root, task, plan, by, **more):
        calls.append({"task": task, "by": by, "plan_is_a_mapping": isinstance(plan, dict),
                      "packet_existed": (Path(root) / f".lapis/critic/{task}.packet.json").exists()})
        return {"rows": [], "error": None}

    fake = types.ModuleType("lapis_design.integrity")
    fake.observe = observe
    monkeypatch.setitem(sys.modules, "lapis_design.integrity", fake)
    monkeypatch.setattr(lapis_design, "integrity", fake, raising=False)
    return calls


def run(project, *args) -> int:
    return cli_main(["critic", "packet", "--task", TASK, "--root", str(project), *args])


def test_the_command_observes_first_then_writes_the_packet_the_critic_report_names(project, observed, capsys):
    (project / f".lapis/critic/{TASK}.packet.json").unlink()            # the fixture's own packet: none exists yet
    assert run(project) == 0
    assert observed == [{"task": TASK, "by": "critic packet", "plan_is_a_mapping": True, "packet_existed": False}]
    out = capsys.readouterr().out
    file = project / f".lapis/critic/{TASK}.packet.json"
    sha = critic_packet.digest(file.read_bytes())
    assert f".lapis/critic/{TASK}.packet.json (sha256 {sha}): 2 requirement rows, 0 changes, 0 disputes" in out
    assert f"target.packet: {{path: .lapis/critic/{TASK}.packet.json, sha256: {sha}}}" in out
    assert file.read_bytes() == critic_packet.build(project, TASK, INPUTS)


def test_an_unrecorded_integrity_check_is_one_line_on_standard_error_and_does_not_stop_the_packet(project, observed,
                                                                                                    monkeypatch, capsys):
    monkeypatch.setattr(sys.modules["lapis_design.integrity"], "observe", lambda *a, **k: {"rows": [], "error": "disk full"})
    assert run(project) == 0
    assert "critic packet: integrity not recorded: disk full" in capsys.readouterr().err


def test_the_command_defaults_to_the_release_inputs_and_a_draft_names_its_own(project, observed):
    session = project / f".lapis/behavior/{TASK}.json"
    session.parent.mkdir(parents=True)
    session.write_text("{}", encoding="utf-8")
    assert run(project) == 0
    assert json.loads((project / f".lapis/critic/{TASK}.packet.json").read_text())["args"] == {
        "extracts": [f".lapis/renders/{TASK}.json"], "lint": f".lapis/lint/{TASK}.json",
        "session": f".lapis/behavior/{TASK}.json"}
    narrow = save(project, "renders/shown.narrow.json", json.loads((project / f".lapis/renders/{TASK}.json").read_text()))
    assert run(project, "--extract", ".lapis/renders/shown.narrow.json", "--out", ".lapis/critic/shown.packet.json") == 0
    assert json.loads((project / ".lapis/critic/shown.packet.json").read_text())["args"] == {
        "extracts": [".lapis/renders/shown.narrow.json"], "lint": f".lapis/lint/{TASK}.json"}
    assert narrow.is_file()


@pytest.mark.parametrize("args", [
    ["--out", "packet.json"],
    ["--out", ".lapis/plans/packet.json"],
    ["--out", ".lapis/critic/packet.txt"],
    ["--out", "../outside.json"],
    ["--extract", "../outside.json"],
    ["--lint", ".lapis/lint/missing.json"],
])
def test_the_command_refuses_what_it_cannot_build_from_and_writes_nothing(project, observed, args, capsys):
    files = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    assert run(project, *args) == 2
    assert capsys.readouterr().err.startswith("critic packet: ")
    assert {p: p.read_bytes() for p in project.rglob("*") if p.is_file()} == files
    assert not (project.parent / "outside.json").exists()


def test_a_dispute_file_that_does_not_match_its_schema_stops_the_packet(project, observed, capsys):
    save(project, f"disputes/{TASK}.yaml", {"version": 0, "task": TASK, "disputes": [{
        "report": "r.json", "rule_id": "layout.card-everything", "observed": "Every section", "reason": "short", "refs": []}]})
    assert run(project) == 2
    assert f".lapis/disputes/{TASK}.yaml" in capsys.readouterr().err


def test_an_extract_that_is_not_there_is_named_and_lists_no_capture(project):
    (project / f".lapis/renders/{TASK}.json").unlink()
    doc = packet(project)
    assert doc["args"]["extracts"] == [f".lapis/renders/{TASK}.json"]
    assert not [i for i in doc["inputs"] if i["kind"] in ("extract", "screenshot")]


def test_plan_check_and_slop_lint_end_with_the_dispute_footer(project, capsys):
    plan = str(project / f".lapis/plans/{TASK}.yaml")
    cli_main(["plan", "check", plan, "--root", str(project)])
    plan_lines = capsys.readouterr().out.splitlines()
    cli_main(["slop", "lint", "--plan", plan])
    lint_lines = capsys.readouterr().out.splitlines()
    assert plan_lines[-1] == lint_lines[-1] == summary.DISPUTE_FOOTER
    assert ".lapis/disputes/<task>.yaml" in summary.DISPUTE_FOOTER and "does not clear the finding" in summary.DISPUTE_FOOTER
    assert "--json" not in summary.DISPUTE_FOOTER and "\n" not in summary.DISPUTE_FOOTER


def test_the_footer_stays_out_of_the_json_a_tool_reads(project, capsys):
    cli_main(["plan", "check", str(project / f".lapis/plans/{TASK}.yaml"), "--root", str(project), "--json"])
    assert summary.DISPUTE_FOOTER not in capsys.readouterr().out
