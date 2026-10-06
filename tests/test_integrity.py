"""The change log over the plan's protected inputs (`integrity.py`): what is observed, what a row says, the chain that
keeps it honest, the commands that observe before they compute, and the hook that keeps an agent's edit tool away from
the records the CLI owns. Behavior only: each test drives the CLI or `observe` and reads the files it writes."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from lapis_design import next_step
from lapis_design.cli import main as cli_main
from procedure_support import BRIEF_RECORD, SHARED, TASK, make_project, record, report, save, update

PLAN = f".lapis/plans/{TASK}.yaml"
ANSWERS = f".lapis/answers/{TASK}.md"
OWNED = (".lapis/requirements", ".lapis/state", ".lapis/changes", ".lapis/owner")
RATIO = "/tokens/type/scale/ratio"


@pytest.fixture
def integrity():
    from lapis_design import integrity

    return integrity


@pytest.fixture(autouse=True)
def attended(monkeypatch):
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def project(tmp_path) -> Path:
    """A project whose plan is approved and whose brief record exists: the state of a run past its plan, before
    anything observed it (`make_project` sealed a slice in the state file for the procedure tests; this is not that)."""
    root = make_project(tmp_path)
    shutil.rmtree(root / ".lapis" / "state")
    return root


@pytest.fixture
def bare(tmp_path) -> Path:
    """Only a plan, with no approval and no brief record: nothing happened before the first observation."""
    plan = yaml.safe_load((SHARED / "plan/example.plan.yaml").read_text(encoding="utf-8"))
    plan.pop("approval")
    save(tmp_path, f"plans/{TASK}.yaml", plan)
    return tmp_path


def edit(root: Path, change) -> None:
    update(root, f"plans/{TASK}.yaml", change)


def set_ratio(value: float):
    return lambda plan: plan["tokens"]["type"]["scale"].update(ratio=value)


def observe(integrity, root: Path, by: str = "test") -> list[dict]:
    result = integrity.observe_task(root, TASK, by)
    assert result["error"] is None, result
    return result["rows"]


def log(root: Path) -> list[dict]:
    path = root / ".lapis" / "changes" / f"{TASK}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def state(root: Path) -> dict:
    return json.loads((root / ".lapis" / "state" / f"{TASK}.json").read_text(encoding="utf-8"))


def of(rows: list[dict], kind: str) -> list[dict]:
    return [row for row in rows if row["kind"] == kind]


def finding(rule: str, layer: str, **location) -> dict:
    return {"rule_id": rule, "class": "quality", "severity": {"create": "gate"}, "layer": layer,
            "observed": "an observed property", "blocking": True, "evidence": {"type": "plan"}, "status": "open",
            **({"location": location} if location else {})}


def open_in_lint(root: Path, *findings: dict) -> None:
    """A lint report on disk whose findings are open."""
    save(root, f"lint/{TASK}.json", {**report("slop_lint"), "findings": list(findings)})


def plan_check(root: Path, capsys) -> dict:
    cli_main(["plan", "check", str(root / PLAN), "--root", str(root), "--format", "json"])
    return json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------- 1. the baseline

def test_the_first_observation_writes_a_baseline_and_no_row_and_a_touch_writes_none(integrity, bare):
    assert observe(integrity, bare) == []
    assert state(bare)["values"][RATIO] == 1.25 and state(bare)["last_change"] is None
    assert not (bare / ".lapis" / "changes").exists()
    plan = bare / PLAN
    plan.write_bytes(plan.read_bytes())                              # the same bytes again
    os.utime(plan, (4_000_000_000, 4_000_000_000))                   # and a later modification time
    assert observe(integrity, bare) == [] and log(bare) == []


# ---------------------------------------------------------------- 2. a keep added while its finding is open

KEEP = {"id": "color.cream-base", "decision": "keep", "basis": "brief", "keep_when": "paper-material",
        "evidence": {"material": "firing log sheet"},
        "reason": "The field is the paper of the firing log sheet, one of the world materials"}


def test_a_keep_added_for_a_rule_that_is_open_in_the_last_plan_check_is_reactive(integrity, project, capsys):
    observe(integrity, project)
    edit(project, lambda plan: plan.update(defaults=[d for d in plan["defaults"] if d["id"] != KEEP["id"]]))
    checked = plan_check(project, capsys)
    assert any(f["rule_id"] == KEEP["id"] and f["status"] == "open" for f in checked["findings"])
    assert KEEP["id"] in [e["rule_id"] for e in state(project)["open"]]       # recorded by the plan check itself

    edit(project, lambda plan: plan["defaults"].append(KEEP))
    plan_check(project, capsys)
    rows = of(log(project), "protected")
    assert [(r["pointer"], r["reactive"], r["related_open"]) for r in rows[-1:]] == [
        ("/defaults[id=color.cream-base]", True, ["color.cream-base"])]
    assert rows[-1]["before"] is None and rows[-1]["after"] == KEEP and rows[-1]["by"] == "plan check"


def test_next_records_the_plan_findings_it_computes_so_a_later_keep_is_reactive(integrity, project, capsys):
    edit(project, lambda plan: plan.update(defaults=[d for d in plan["defaults"] if d["id"] != KEEP["id"]]))
    assert cli_main(["next", "--task", TASK, "--root", str(project)]) == 0
    assert KEEP["id"] in [e["rule_id"] for e in state(project)["open"]]
    edit(project, lambda plan: plan["defaults"].append(KEEP))
    assert cli_main(["next", "--task", TASK, "--root", str(project)]) == 0
    capsys.readouterr()
    row = of(log(project), "protected")[-1]
    assert (row["pointer"], row["reactive"], row["related_open"], row["by"]) == (
        "/defaults[id=color.cream-base]", True, ["color.cream-base"], "next")


def test_a_keep_for_a_rule_that_is_not_open_is_a_row_but_not_reactive(integrity, project):
    observe(integrity, project)
    other = {"id": "type.costume-monospace", "decision": "reject", "basis": "brief",
             "reason": "No code appears in the product, so the face stays out"}
    edit(project, lambda plan: plan["defaults"].append(other))
    (row,) = observe(integrity, project)
    assert (row["pointer"], row["reactive"], row["related_open"]) == ("/defaults[id=type.costume-monospace]", False, [])


# ---------------------------------------------------------------- 3. rules that read the pointer, by their own paths and by reads_plan

def test_a_type_scale_change_while_the_flat_hierarchy_finding_is_open_names_the_rule(integrity, project, capsys):
    observe(integrity, project)
    edit(project, set_ratio(1.05))
    checked = plan_check(project, capsys)
    assert any(f["rule_id"] == "type.flat-hierarchy" and f["status"] == "open" for f in checked["findings"])
    edit(project, set_ratio(1.25))
    plan_check(project, capsys)
    rows = [r for r in log(project) if r["pointer"] == RATIO]
    assert [(r["before"], r["after"], r["related_open"]) for r in rows] == [(1.25, 1.05, []),
                                                                            (1.05, 1.25, ["type.flat-hierarchy"])]


def test_a_space_scale_change_while_the_off_scale_finding_is_open_is_related_through_reads_plan(integrity, project):
    edit(project, lambda plan: plan["tokens"].update(space={"base_px": 8, "scale": [4, 8, 16]}))
    observe(integrity, project)
    open_in_lint(project, finding("system.off-scale-value", "source"), finding("copy.buzzwords", "render"))
    edit(project, lambda plan: plan["tokens"]["space"].update(scale=[4, 8, 12, 16]))
    (row,) = observe(integrity, project)
    assert (row["pointer"], row["before"], row["after"]) == ("/tokens/space/scale", [4, 8, 16], [4, 8, 12, 16])
    assert row["related_open"] == ["system.off-scale-value"]                  # the unrelated copy rule is not named


def test_related_rules_come_from_a_rules_own_path_and_from_the_reads_plan_of_its_detector(integrity):
    rules = yaml.safe_load((SHARED / "slop/rules.yaml").read_text(encoding="utf-8"))
    detectors = yaml.safe_load((SHARED / "slop/detectors.yaml").read_text(encoding="utf-8"))
    related = integrity.related_rules(rules, detectors)
    assert ("tokens", "type", "scale", "ratio") in related["type.flat-hierarchy"]
    assert ("tokens", "space", "scale") in related["system.off-scale-value"]
    assert ("tokens", "color", "roles") in related["system.off-scale-value"]
    for detector in detectors["detectors"]:                                   # without the declaration the link is gone
        detector.pop("reads_plan", None)
    assert "system.off-scale-value" not in integrity.related_rules(rules, detectors)


# ---------------------------------------------------------------- 4. a flow's end changed while a finding about the flow is open

def test_a_flow_done_change_while_a_finding_names_that_flow_is_related(integrity, project):
    flow = {"id": "f", "kind": "primary", "goal": "Reserve one piece", "start": "/", "done": {"text": "Reserved"}}
    edit(project, lambda plan: plan.update(flows=[flow]))
    observe(integrity, project)
    open_in_lint(project, finding("ux.excess-steps", "behavior", flow="f"),
                 finding("ux.dead-control", "behavior", flow="g"))
    edit(project, lambda plan: plan["flows"][0]["done"].update(text="Reservation complete"))
    (row,) = observe(integrity, project)
    assert (row["pointer"], row["before"], row["after"]) == ("/flows[id=f]/done/text", "Reserved", "Reservation complete")
    assert row["related_open"] == ["ux.excess-steps"]


# ---------------------------------------------------------------- 5. what is not protected, and a revert

def test_an_unprotected_field_gives_no_row_and_a_revert_gives_a_second_one(integrity, bare):
    observe(integrity, bare)
    edit(bare, lambda plan: plan["layout"].setdefault("procedure", {}).update(grid="twelve columns, no gutters"))
    assert observe(integrity, bare) == [] and log(bare) == []
    edit(bare, set_ratio(1.2))
    observe(integrity, bare)
    edit(bare, set_ratio(1.25))
    observe(integrity, bare)
    first, second = log(bare)
    assert (first["seq"], second["seq"]) == (1, 2)
    assert (second["before"], second["after"]) == (first["after"], first["before"]) == (1.2, 1.25)


# ---------------------------------------------------------------- 6. the answers headings

def test_renaming_an_answers_heading_is_a_row(integrity, project):
    observe(integrity, project)
    text = (project / ANSWERS).read_text(encoding="utf-8")
    assert "## Answers" in text
    (project / ANSWERS).write_text(text.replace("## Answers", "## Replies"), encoding="utf-8")
    rows = of(observe(integrity, project), "answers-headings")
    assert len(rows) == 1 and rows[0]["pointer"] == "answers:headings"
    assert rows[0]["before"] == [{"heading": "Found", "items": 1}, {"heading": "Answers", "items": 2}]
    assert rows[0]["after"] == [{"heading": "Found", "items": 1}, {"heading": "Replies", "items": 2}]


# ---------------------------------------------------------------- 7. every plan-reading command observes before it computes

def spy(monkeypatch, module, name: str, root: Path, seen: list) -> None:
    """Wrap `module.name`, the command's own computation, so the change log is read when the command starts it."""
    original = getattr(module, name)

    def wrapper(*args, **kwargs):
        seen.append(log(root))
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapper)


def _commands(root: Path):
    from lapis_design import draft, handoff, plan_check as plan_check_module, release_check
    from lapis_design.lint import cli as lint_cli

    plan = str(root / PLAN)
    return {
        "plan check": (plan_check_module, "run", ["plan", "check", plan, "--root", str(root)]),
        "slop lint": (lint_cli, "run", ["slop", "lint", "--plan", plan]),
        "next": (next_step, "_evaluate", ["next", "--task", TASK, "--root", str(root)]),
        "draft check": (draft, "check", ["draft", "check", "--task", TASK, "--root", str(root)]),
        "release check": (release_check, "run", ["release", "check", "--task", TASK, "--root", str(root), "--offline"]),
        "handoff export": (handoff, "export", ["handoff", "export", "--plan", PLAN, "--root", str(root), "--scope", "s",
                                               "--role", "implementer"]),
    }


@pytest.mark.parametrize("command", ["plan check", "slop lint", "next", "draft check", "release check",
                                     "handoff export"])
def test_a_command_that_reads_the_plan_has_logged_its_edit_before_it_computes(integrity, project, monkeypatch, capsys,
                                                                             command):
    observe(integrity, project)
    edit(project, set_ratio(1.3))
    module, name, argv = _commands(project)[command]
    seen: list = []
    spy(monkeypatch, module, name, project, seen)
    assert cli_main(argv) in (0, 1, 2)
    assert seen, f"{command} never reached its computation"
    assert [(r["pointer"], r["by"]) for r in seen[0] if r["pointer"] == RATIO] == [(RATIO, command)]
    capsys.readouterr()


# ---------------------------------------------------------------- 8. a log or a state that was edited outside lapis-design

def grown_log(integrity, root: Path, ratios=(1.2, 1.3, 1.4)) -> None:
    observe(integrity, root)
    for value in ratios:
        edit(root, set_ratio(value))
        observe(integrity, root)
    assert [r["seq"] for r in log(root)] == list(range(1, len(ratios) + 1))


def test_a_tampered_middle_line_is_an_integrity_row_and_is_reported_once(integrity, bare):
    grown_log(integrity, bare)
    path = bare / ".lapis" / "changes" / f"{TASK}.jsonl"
    lines = path.read_bytes().split(b"\n")
    lines[1] = lines[1].replace(b'"after":1.3,', b'"after":1.31,')
    path.write_bytes(b"\n".join(lines))
    (row,) = observe(integrity, bare)
    assert (row["kind"], row["pointer"], row["before"]) == ("integrity", "changes", {"line": 3})
    assert "edited outside lapis-design" in row["after"]
    assert observe(integrity, bare) == []                                     # shown once, not on every command


def test_a_tampered_last_line_does_not_match_the_state(integrity, bare):
    grown_log(integrity, bare)
    path = bare / ".lapis" / "changes" / f"{TASK}.jsonl"
    path.write_bytes(path.read_bytes().replace(b'"after":1.4,', b'"after":1.45,'))
    (row,) = observe(integrity, bare)
    assert (row["kind"], row["pointer"]) == ("integrity", "changes") and "does not match its state" in row["after"]
    assert observe(integrity, bare) == []


def test_a_deleted_state_file_is_an_integrity_row_and_a_deleted_log_is_one_too(integrity, bare):
    grown_log(integrity, bare)
    (bare / ".lapis" / "state" / f"{TASK}.json").unlink()
    (row,) = observe(integrity, bare)
    assert (row["kind"], row["pointer"]) == ("integrity", "state") and "state file is missing" in row["after"]
    assert row["prev"] == hashlib.sha256(json.dumps(log(bare)[-2], ensure_ascii=False, separators=(",", ":"))
                                         .encode("utf-8")).hexdigest()       # the chain goes on from the old log
    (bare / ".lapis" / "changes" / f"{TASK}.jsonl").unlink()
    (row,) = observe(integrity, bare)
    assert (row["kind"], row["pointer"], row["prev"]) == ("integrity", "changes", None)


def test_a_first_observation_that_finds_an_approved_plan_and_a_brief_says_history_starts_here(integrity, project):
    (row,) = observe(integrity, project)
    assert (row["kind"], row["pointer"], row["seq"], row["prev"]) == ("integrity", "history", 1, None)
    assert row["after"] == "history starts here; earlier changes were not observed"
    assert observe(integrity, project) == []


def test_a_first_observation_of_an_approved_plan_alone_says_it_too(integrity, bare):
    edit(bare, lambda plan: plan.update(approval={"state": "approved"}))
    assert [r["pointer"] for r in observe(integrity, bare)] == ["history"]


# ---------------------------------------------------------------- 9. the pre-write hook

def hook(monkeypatch, capsys, root: Path, tool: str, tool_input: dict, **env: str) -> dict | None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    event = {"hook_event_name": "PreToolUse", "cwd": str(root), "session_id": "s1", "tool_name": tool,
             "tool_input": tool_input}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    assert cli_main(["hook", "pre-write"]) == 0
    out = capsys.readouterr().out
    return json.loads(out) if out else None


def reason(answer: dict | None) -> str | None:
    if answer is None:
        return None
    assert set(answer) == {"hookSpecificOutput"}
    output = answer["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse" and output["permissionDecision"] == "deny"
    return output["permissionDecisionReason"]


SESSIONS = {"attended": {}, "unattended": {"LAPIS_UNATTENDED": "1", "LAPIS_TASK": TASK}}
TOOLS = {
    "claude-write": ("Write", lambda root, rel: {"file_path": str(root / rel), "content": "x"}),
    "codex-patch": ("apply_patch", lambda root, rel: {
        "command": f"*** Begin Patch\n*** Add File: notes/log.md\n+x\n*** Update File: {rel}\n+x\n*** End Patch"}),
    "omp-hashline": ("edit", lambda root, rel: {"input": f"[{rel}#4F2A]\n- old\n+ new\n"}),
    "omp-write": ("write", lambda root, rel: {"path": rel, "content": "x"}),
}


@pytest.mark.parametrize("session", list(SESSIONS))
@pytest.mark.parametrize("tool", list(TOOLS))
def test_the_hook_refuses_an_edit_tools_write_to_each_record_the_cli_owns(project, monkeypatch, capsys, tool, session):
    name, build = TOOLS[tool]
    for folder in OWNED:
        rel = f"{folder}/{TASK}.json"
        message = reason(hook(monkeypatch, capsys, project, name, build(project, rel), **SESSIONS[session]))
        assert message and rel in message and "lapis-design" in message


@pytest.mark.parametrize("session", list(SESSIONS))
def test_the_hook_leaves_every_other_write_as_it_was(project, monkeypatch, capsys, session):
    for rel in (ANSWERS, PLAN, f".lapis/critic/{TASK}.json", f".lapis/stateless/{TASK}.json", "index.html",
                "README.md", ".lapis/statement.md"):
        assert hook(monkeypatch, capsys, project, "Write", {"file_path": str(project / rel), "content": "x"},
                    **SESSIONS[session]) is None, rel


def test_the_hook_refuses_the_records_before_any_plan_exists(tmp_path, monkeypatch, capsys):
    record(tmp_path, "answers", BRIEF_RECORD, 50)                    # a `.lapis` folder with no plan: a run's first records
    for folder in OWNED:
        assert reason(hook(monkeypatch, capsys, tmp_path, "Write",
                           {"file_path": str(tmp_path / folder / f"{TASK}.json"), "content": "x"}))


def test_a_patch_that_names_a_page_and_a_record_is_refused_for_the_record(project, monkeypatch, capsys):
    patch = f"*** Begin Patch\n*** Update File: index.html\n+x\n*** Add File: .lapis/changes/{TASK}.jsonl\n+x\n*** End Patch"
    assert ".lapis/changes" in reason(hook(monkeypatch, capsys, project, "apply_patch", {"command": patch}))


def test_the_hook_does_not_refuse_the_same_name_outside_the_project(project, tmp_path_factory, monkeypatch, capsys):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    assert hook(monkeypatch, capsys, project, "Write",
                {"file_path": str(elsewhere / ".lapis" / "state" / "x.json"), "content": "x"}) is None


# ---------------------------------------------------------------- 10. concurrent observations

WORKER = """
import json, sys
from pathlib import Path
from lapis_design import integrity

root, task, worker, plans = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), json.loads(Path(sys.argv[4]).read_text())
for step in range(8):
    result = integrity.observe(root, task, plans[(worker + step) % len(plans)], f"worker-{worker}")
    assert result["error"] is None, result
"""


def test_two_observations_at_once_leave_the_chain_intact(integrity, bare, tmp_path_factory):
    plan = yaml.safe_load((bare / PLAN).read_text(encoding="utf-8"))
    plans = []
    for ratio in (1.2, 1.3, 1.4):
        variant = json.loads(json.dumps(plan))
        variant["tokens"]["type"]["scale"]["ratio"] = ratio
        plans.append(variant)
    observe(integrity, bare)
    holder = tmp_path_factory.mktemp("plans") / "plans.json"
    holder.write_text(json.dumps(plans), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(Path(integrity.__file__).resolve().parents[1])}
    workers = [subprocess.Popen([sys.executable, "-c", WORKER, str(bare), TASK, str(n), str(holder)], env=env)
               for n in range(6)]
    assert [w.wait(timeout=120) for w in workers] == [0] * 6
    path = bare / ".lapis" / "changes" / f"{TASK}.jsonl"
    lines = path.read_bytes().split(b"\n")[:-1]
    rows = [json.loads(line) for line in lines]
    assert len(rows) > 1 and [r["seq"] for r in rows] == list(range(1, len(rows) + 1))
    assert [r["prev"] for r in rows] == [None] + [hashlib.sha256(line).hexdigest() for line in lines[:-1]]
    assert state(bare)["last_change"] == hashlib.sha256(lines[-1]).hexdigest()
    assert not of(rows, "integrity") and not of(observe(integrity, bare), "integrity")   # the file's ratio is back to 1.25


# ---------------------------------------------------------------- failure semantics

def test_a_lock_that_stays_held_makes_observe_fail_open_and_the_command_still_runs(integrity, project, monkeypatch,
                                                                                   capsys):
    monkeypatch.setattr(integrity, "LOCK_WAIT_S", 0.2)
    lock = project / ".lapis" / "state" / f"{TASK}.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("1", encoding="utf-8")
    result = integrity.observe_task(project, TASK, "test")
    assert result["rows"] == [] and "held by another lapis-design command" in result["error"]
    capsys.readouterr()
    assert cli_main(["plan", "check", str(project / PLAN), "--root", str(project)]) in (0, 1)
    out, err = capsys.readouterr()
    assert out.startswith("plan_check ") and err.count("integrity not recorded") == 1


def test_a_lock_left_by_a_process_that_died_is_taken_over(integrity, bare):
    lock = bare / ".lapis" / "state" / f"{TASK}.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("1", encoding="utf-8")
    os.utime(lock, (time.time() - 3600, time.time() - 3600))
    assert observe(integrity, bare) == [] and not lock.exists()


def test_an_unwritable_state_folder_is_reported_not_raised(integrity, bare, capsys):
    (bare / ".lapis" / "state").write_text("in the way", encoding="utf-8")
    result = integrity.observe_task(bare, TASK, "test")
    assert result["rows"] == [] and result["error"]
    assert capsys.readouterr().err == f"lapis-design: integrity not recorded: {result['error']}\n"


# ---------------------------------------------------------------- what is protected, and the contract's shape

PROTECTED_PLAN = {
    "brief": {"subject": "s", "constraints": ["a"]}, "claims": {"known": ["k"]}, "approval": {"state": "approved"},
    "sources": [{"ref": "a.md"}, {"ref": "a.md", "note": "again"}],
    "references": [{"source": "https://x.test/", "take": ["t"], "leave": ["l"], "mode": "study"}],
    "defaults": [{"id": "type.x", "decision": "reject", "reason": "no reason needed"}],
    "explorations": [{"decision": "type", "covers": ["display", "heading"], "chosen": "A", "fixed_by": "contract",
                      "candidates": [{"name": "A"}, {"name": "B"}], "reason": "A won"}],
    "flows": [{"id": "f", "kind": "primary", "goal": "g", "start": "/", "done": {"text": "T"},
               "reach": {"forward": "Next", "selections": ["a"]}}],
    "tokens": {"space": {"base_px": 8, "scale": [4, 8]}, "type": {"scale": {"base_px": 16, "ratio": 1.25},
                                                                 "roles": [{"role": "body", "family": "F"}]},
               "shape": {"radius": {"scale": [4], "by_role": {"control": 4}}},
               "color": {"roles": [{"name": "ink", "role": "foreground", "theme": "light"}]}},
    "layout": {"phone_task": {"decision": "d", "first_result": "#r", "before_result": [], "acceptance": "a task"},
               "procedure": {"grid": "g"}},
    "content": {"key_copy": [{"slot": "nav", "text": "A"}, {"slot": "nav", "text": "B"},
                             {"slot": "headline", "text": "H", "locale": "ko-KR"}], "voice": {"notes": "x"}},
    "world_materials": ["clay"], "direction": {"concept": "c"}, "task": {"id": TASK, "title": "t"},
}


def test_the_protected_pointers_are_keyed_by_the_item_they_address(integrity):
    assert list(integrity.protected_values(PROTECTED_PLAN)) == sorted([
        "/brief/subject", "/brief/constraints", "/claims/known", "/approval/state",
        "/sources[ref=a.md,n=1]", "/sources[ref=a.md,n=2]",
        "/references[source=https://x.test/]/take", "/references[source=https://x.test/]/leave",
        "/defaults[id=type.x]",
        "/explorations[decision=type,covers=display|heading]/chosen",
        "/explorations[decision=type,covers=display|heading]/fixed_by",
        "/explorations[decision=type,covers=display|heading]/candidates/*/name",
        "/flows[id=f]/goal", "/flows[id=f]/kind", "/flows[id=f]/done/text", "/flows[id=f]/reach/forward",
        "/flows[id=f]/reach/selections",
        "/tokens/space/base_px", "/tokens/space/scale", "/tokens/type/scale/base_px", "/tokens/type/scale/ratio",
        "/tokens/shape/radius/scale", "/tokens/shape/radius/by_role/control",
        "/tokens/color/roles[name=ink,theme=light]",
        "/layout/phone_task/decision", "/layout/phone_task/first_result", "/layout/phone_task/before_result",
        "/layout/phone_task/acceptance",
        "/content/key_copy[slot=nav,n=1]", "/content/key_copy[slot=nav,n=2]",
        "/content/key_copy[slot=headline,locale=ko-KR,n=1]"])
    assert integrity.protected_values(PROTECTED_PLAN)["/explorations[decision=type,covers=display|heading]"
                                                      "/candidates/*/name"] == ["A", "B"]


def test_a_plan_that_cannot_be_read_keeps_the_last_values_and_the_next_good_read_is_diffed_against_them(
        integrity, bare):
    observe(integrity, bare)
    (bare / PLAN).write_text("brief: { subject: What now? }\n", encoding="utf-8")        # libyaml reads it, we refuse it
    assert observe(integrity, bare) == [] and state(bare)["values"][RATIO] == 1.25
    edit_text = (SHARED / "plan/example.plan.yaml").read_text(encoding="utf-8").replace("ratio: 1.25", "ratio: 1.5")
    (bare / PLAN).write_text(edit_text, encoding="utf-8")
    assert [(r["pointer"], r["before"], r["after"]) for r in observe(integrity, bare)
            if r["pointer"] == RATIO] == [(RATIO, 1.25, 1.5)]


def test_a_plan_whose_aliases_expand_past_the_plan_checks_limits_is_not_walked(integrity, bare):
    levels = ["version: 0", "claims:", "  known: &l0 [a, b, c, d, e, f, g, h, i, j]"]
    levels += [f"  {name}: &l{n + 1} [{', '.join(f'*l{n}' for _ in range(10))}]"
               for n, name in enumerate(("declared", "proposed", "unresolved", "other"))]
    (bare / PLAN).write_text("\n".join(levels) + "\n", encoding="utf-8")
    started = time.monotonic()
    assert observe(integrity, bare) == []
    assert time.monotonic() - started < 2 and state(bare)["values"] == {}


def test_the_state_and_the_rows_match_the_integrity_schema(integrity, project):
    schema = yaml.safe_load((SHARED / "integrity/schema.yaml").read_text(encoding="utf-8"))
    validator = lambda name: Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": schema["$defs"]})  # noqa: E731
    observe(integrity, project)
    edit(project, set_ratio(1.3))
    observe(integrity, project)
    integrity.seal_slice(project, TASK, {"url": "http://localhost/", "draft_sha256": None, "packet_sha256": None,
                                         "questions_sha256": "0" * 64, "answers_sha256": "1" * 64,
                                         "requirements_sha256": None})
    assert list(validator("state").iter_errors(state(project))) == []
    rows = log(project)
    assert len(rows) == 2 and all(list(validator("change").iter_errors(row)) == [] for row in rows)


# ---------------------------------------------------------------- the seams the other lanes use

def test_a_sealed_slice_is_recorded_without_touching_the_chain_and_later_rows_say_so(integrity, project):
    observe(integrity, project)
    before = log(project)
    integrity.seal_slice(project, TASK, {"url": "http://localhost/", "candidates": ["http://localhost/a"],
                                         "draft_sha256": None, "packet_sha256": None, "questions_sha256": None,
                                         "answers_sha256": None, "requirements_sha256": None})
    sealed = integrity.read_state(project, TASK)["slice"]
    assert sealed["url"] == "http://localhost/" and sealed["protected_sha256"] == integrity.digest(state(project)["values"])
    assert log(project) == before
    edit(project, set_ratio(1.3))
    (row,) = observe(integrity, project)
    assert row["after_slice"] is True and row["pointer"] == RATIO
    assert integrity.read_state(project, TASK)["slice"] == sealed


def test_rows_the_caller_made_itself_go_into_the_same_chain(integrity, bare):
    observe(integrity, bare)
    edit(bare, set_ratio(1.3))
    result = integrity.observe(bare, TASK, None, "requirements seal", extra=[
        {"pointer": "/requirements/R3f2a1c", "before": None, "after": "Main preview: a fader"}])
    assert [(r["kind"], r["pointer"], r["by"]) for r in result["rows"]] == [
        ("requirements", "/requirements/R3f2a1c", "requirements seal")]
    assert [(r["kind"], r["by"]) for r in observe(integrity, bare, "next")] == [("protected", "next")]
    assert [r["seq"] for r in log(bare)] == [1, 2]
    assert integrity.changes(bare, TASK) == log(bare)


def test_a_path_outside_the_plans_folder_is_not_a_task_plan(integrity, tmp_path):
    assert integrity.locate(tmp_path / "plan.yaml") is None
    assert integrity.locate(tmp_path / ".lapis" / "plans" / f"{TASK}.yaml") == (tmp_path, TASK)
    assert integrity.locate(Path(PLAN), tmp_path) == (tmp_path, TASK)
