"""A plan that cannot be read is never done, and page code comes after the brief, the references, and the plan:
the finding `release.procedure-order`, the step `plan-order`, and the pre-write hook that refuses an unattended run."""
from __future__ import annotations

import io
import json
import os
import shutil
from pathlib import Path

import pytest

from lapis_design import next_step, release_check
from lapis_design.cli import main as cli_main
from procedure_support import BRIEF_RECORD, TASK, finish, make_project, record, update, write_references

FIXTURES = Path(__file__).parent / "fixtures" / "plans"
PLAN = f".lapis/plans/{TASK}.yaml"
ANSWERS = f".lapis/answers/{TASK}.md"
REFERENCES = f".lapis/references/{TASK}.md"


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    return make_project(tmp_path)


def step_of(root: Path, task: str = TASK) -> str:
    result = next_step.evaluate(root, task)
    return result["step"]["id"] if result["step"] else "done"


# ---------------------------------------------------------------- a plan that cannot be read is never done

def test_the_plan_a_run_wrote_with_an_unquoted_question_mark_is_sent_back_with_its_position(tmp_path, monkeypatch, capsys):
    """brief-saas-1: libyaml reads `{ answers: What does this do for me? }`, the pure-Python loader (and every tool
    built on `yaml.safe_load`) refuses it, and `next` once went on to report the procedure done."""
    monkeypatch.setenv("LAZULI_DB", "")
    task = "brief-saas-1"
    plan = tmp_path / ".lapis" / "plans" / f"{task}.yaml"
    plan.parent.mkdir(parents=True)
    shutil.copy(FIXTURES / f"{task}.unquoted-question-mark.yaml", plan)
    record(tmp_path, "answers", BRIEF_RECORD, 50, task)
    write_references(tmp_path, 50, task)

    result = next_step.evaluate(tmp_path, task)
    assert result["step"]["id"] == "plan-fix"
    assert "found a `?` inside a plain scalar of a flow collection; quote the value at 160:95" in result["step"]["why"]
    assert "quote a string that holds `?`" in result["step"]["why"]
    assert cli_main(["plan", "check", str(plan)]) == 2
    assert "cannot be read: found a `?` inside a plain scalar of a flow collection; quote the value at 160:95" in \
        capsys.readouterr().err


def corrupt(text: str) -> str:
    return text + "x-note: { answers: What now? }\n"           # readable to libyaml only


UNREADABLE = {
    "libyaml-only": lambda path: path.write_text(corrupt(path.read_text(encoding="utf-8")), encoding="utf-8"),
    "syntax": lambda path: path.write_text("brief: [oops\n", encoding="utf-8"),
    "empty": lambda path: path.write_text("", encoding="utf-8"),
    "list": lambda path: path.write_text("- a\n- b\n", encoding="utf-8"),
    "not-utf8": lambda path: path.write_bytes(b"\xff\xfe\x00"),
}


@pytest.mark.parametrize("how", list(UNREADABLE))
def test_a_plan_that_cannot_be_read_is_not_done_even_when_every_report_is_fresh(project, how):
    assert finish(project, "--static") == 0
    assert step_of(project) == "done"
    plan = project / PLAN
    UNREADABLE[how](plan)
    os.utime(plan, (1, 1))                       # older than every report: only reading the plan can tell
    assert step_of(project) == "plan-fix"


# ---------------------------------------------------------------- page code before the records: the finding

def page(root: Path, at: int, name: str = "index.html") -> Path:
    path = root / name
    path.write_text("<!doctype html><title>Kiln</title><h1>Kiln shop</h1>\n", encoding="utf-8")
    os.utime(path, (at, at))
    return path


def order_findings(root: Path, unattended: bool) -> list[dict]:
    report = release_check.run(root, TASK, static=True, offline=True, unattended=unattended)
    return [f for f in report["findings"] if f["rule_id"] == "release.procedure-order"]


def cite_and_compare(plan: dict) -> None:
    plan["context"]["other"] = [ANSWERS]
    direction = next(e for e in plan["explorations"] if e["decision"] == "direction")
    direction["candidates"].append({"name": "the page as it was built first", "source": "existing-code"})


def test_page_code_older_than_the_brief_blocks_an_unattended_run_and_sends_next_back_to_the_direction(project, monkeypatch):
    page(project, 10)                                  # the brief and the references are from second 50
    [found] = order_findings(project, unattended=True)
    assert found["blocking"] and found["layer"] == "plan" and found["evidence"]["type"] == "source"
    assert "every page file is older than the brief record" in found["observed"] and "index.html" in found["observed"]
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    result = next_step.evaluate(project, TASK)
    assert result["step"]["id"] == "plan-order"
    assert f".lapis/answers/{TASK}.md" in result["step"]["why"] and "existing-code" in result["step"]["why"]


def test_a_persons_session_is_told_of_the_order_and_never_held_to_it(project):
    page(project, 10)
    [found] = order_findings(project, unattended=False)
    assert not found["blocking"] and found["class"] == "quality" and found["severity"]["create"] == "warn"
    assert step_of(project) != "plan-order"


@pytest.mark.parametrize("change,lifted", [
    (cite_and_compare, True),
    (lambda plan: plan["context"].update(other=[ANSWERS]), False),                          # cites the brief only
    (lambda plan: cite_and_compare(plan) or plan["context"].update(other=[]), False),       # compares the code only
    (lambda plan: (cite_and_compare(plan), plan["explorations"][-1]["candidates"].append(
        plan["explorations"][0]["candidates"].pop())), True),
], ids=["cites-and-compares", "cites-only", "compares-only", "unrelated-moves-do-not-matter"])
def test_a_plan_that_cites_the_brief_and_compares_the_existing_code_answers_the_finding(project, change, lifted):
    page(project, 10)
    update(project, f"plans/{TASK}.yaml", change)
    assert bool(order_findings(project, unattended=True)) is (not lifted)


def test_page_code_written_after_the_brief_and_references_is_in_order_whatever_happens_to_the_plan(project):
    page(project, 80)                                  # after the records (50), before the plan's last revision (100)
    assert order_findings(project, unattended=True) == []


def test_a_redesign_is_not_held_to_the_order_of_a_new_surface(project):
    page(project, 10)
    update(project, f"plans/{TASK}.yaml", lambda plan: plan.update(mode="redesign"))
    assert order_findings(project, unattended=True) == []


# ---------------------------------------------------------------- the pre-write hook

def hook_text(monkeypatch, root: Path, tool_input: dict, tool: str = "Write", **env: str) -> None:
    """Point stdin at a PreToolUse event for `tool` in `root`."""
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    event = {"hook_event_name": "PreToolUse", "cwd": str(root), "session_id": "s1", "tool_name": tool,
             "tool_input": tool_input}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))


def run_hook(monkeypatch, capsys, root: Path, tool_input: dict, tool: str = "Write", **env: str) -> dict | None:
    hook_text(monkeypatch, root, tool_input, tool, **env)
    assert cli_main(["hook", "pre-write"]) == 0
    out = capsys.readouterr().out
    return json.loads(out) if out else None


def write(monkeypatch, capsys, root: Path, name: str, **env: str) -> dict | None:
    return run_hook(monkeypatch, capsys, root, {"file_path": str(root / name), "content": "x"}, **env)


UNATTENDED = {"LAPIS_UNATTENDED": "1", "LAPIS_TASK": TASK}      # a design run an operator started: the task is named


def refusal(answer: dict | None) -> str | None:
    """The reason of a PreToolUse refusal, or None when the write goes on."""
    if answer is None:
        return None
    output = answer["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse" and output["permissionDecision"] == "deny"
    assert set(answer) == {"hookSpecificOutput"}
    return output["permissionDecisionReason"]


def owe(root: Path) -> dict[str, bytes]:
    """Take the brief, the references, and the plan away; returns them to put back one at a time."""
    saved = {}
    for rel in (ANSWERS, REFERENCES, PLAN):
        saved[rel] = (root / rel).read_bytes()
        (root / rel).unlink()
    return saved


def give(root: Path, saved: dict[str, bytes], rel: str) -> None:
    (root / rel).write_bytes(saved[rel])


def test_an_unattended_create_run_may_not_write_the_page_until_the_brief_references_and_plan_exist(
        project, monkeypatch, capsys):
    saved = owe(project)
    reason = refusal(write(monkeypatch, capsys, project, "index.html", **UNATTENDED))
    assert ANSWERS in reason and f"lapis-design next --task {TASK}" in reason
    give(project, saved, ANSWERS)
    assert REFERENCES in refusal(write(monkeypatch, capsys, project, "styles.css"))
    give(project, saved, REFERENCES)
    assert PLAN in refusal(write(monkeypatch, capsys, project, "src/app.js"))
    give(project, saved, PLAN)
    assert write(monkeypatch, capsys, project, "index.html") is None             # the plan stands: code may start


def test_a_plan_that_does_not_pass_its_check_is_still_a_plan_to_fix_before_code(project, monkeypatch, capsys):
    update(project, f"plans/{TASK}.yaml", lambda plan: plan.pop("brief"))
    assert "plan check" in refusal(write(monkeypatch, capsys, project, "index.html", **UNATTENDED))


@pytest.mark.parametrize("name", [".lapis/answers/other.md", ".lapis/specimens/kiln.html", "README.md", "notes.txt",
                                  "data/prices.json", "dist/index.html", "node_modules/pkg/index.js", "app.min.js",
                                  "vite.config.js", ".hidden/page.html"])
def test_the_hook_never_refuses_what_is_not_page_code_of_the_project(project, monkeypatch, capsys, name):
    owe(project)
    assert write(monkeypatch, capsys, project, name, **UNATTENDED) is None


def test_the_hook_does_not_stand_in_the_way_of_a_file_outside_the_project(project, monkeypatch, capsys, tmp_path_factory):
    owe(project)
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    assert write(monkeypatch, capsys, project, str(elsewhere / "index.html"), **UNATTENDED) is None


@pytest.mark.parametrize("tool,tool_input", [
    ("apply_patch", {"command": "*** Begin Patch\n*** Add File: notes/log.md\n+x\n*** Add File: pages/home.css\n+x\n"
                                "*** End Patch"}),                                  # Codex: the patch names its files
    ("edit", {"input": "[src/page.tsx#4F2A]\n- old\n+ new\n"}),                    # Oh-My-Pi: a hashline edit
    ("write", {"path": "index.html", "content": "x"}),                              # Oh-My-Pi and pi: `path`
    ("MultiEdit", {"file_path": "index.html", "edits": []}),                       # Claude Code
], ids=["codex-patch", "omp-hashline", "omp-write", "claude-multiedit"])
def test_every_harness_names_its_files_in_its_own_way_and_the_hook_reads_them(project, monkeypatch, capsys, tool, tool_input):
    owe(project)
    answer = run_hook(monkeypatch, capsys, project, tool_input, tool, **UNATTENDED)
    assert refusal(answer) is not None


def test_a_patch_of_records_alone_is_not_refused(project, monkeypatch, capsys):
    owe(project)
    patch = f"*** Begin Patch\n*** Add File: {ANSWERS}\n+x\n*** End Patch"
    assert run_hook(monkeypatch, capsys, project, {"command": patch}, "apply_patch", **UNATTENDED) is None


def test_a_refusal_repeats_three_times_for_one_step_then_the_write_goes_through_and_is_found_after(
        project, monkeypatch, capsys):
    saved = owe(project)
    (project / ANSWERS).write_bytes(saved[ANSWERS])
    (project / REFERENCES).write_bytes(saved[REFERENCES])                    # only the plan is owed
    answers = [refusal(write(monkeypatch, capsys, project, "index.html", **UNATTENDED)) for _ in range(4)]
    assert [bool(a) for a in answers] == [True, True, True, False]
    state = json.loads((project / f".lapis/order/{TASK}.json").read_text(encoding="utf-8"))
    assert state["first_page_write"]["step"] == "plan" and state["first_page_write"]["path"] == "index.html"

    give(project, saved, PLAN)
    [found] = order_findings(project, unattended=True)
    assert found["blocking"] and "index.html was written before the plan was done" in found["observed"]
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    assert step_of(project) == "plan-order"
    update(project, f"plans/{TASK}.yaml", cite_and_compare)
    assert order_findings(project, unattended=True) == [] and step_of(project) != "plan-order"


def test_a_person_is_told_once_that_the_page_came_first_and_is_never_refused(project, monkeypatch, capsys):
    (project / ANSWERS).unlink()                      # the plan stands in create mode, and its brief is owed
    first = write(monkeypatch, capsys, project, "index.html")
    assert set(first) == {"systemMessage"} and ANSWERS not in first["systemMessage"] and "brief record" in first["systemMessage"]
    assert write(monkeypatch, capsys, project, "styles.css") is None
    state = json.loads((project / f".lapis/order/{TASK}.json").read_text(encoding="utf-8"))
    assert "denied" not in state and state["first_page_write"]["step"] == "brief"


def test_a_run_that_is_not_making_a_new_surface_is_not_refused(project, monkeypatch, capsys):
    saved = owe(project)
    (project / "about.html").write_text("<h1>About</h1>", encoding="utf-8")        # page code, and no plan: unknown mode
    assert write(monkeypatch, capsys, project, "index.html", **UNATTENDED) is None
    (project / "about.html").unlink()
    give(project, saved, PLAN)
    update(project, f"plans/{TASK}.yaml", lambda plan: (plan.update(mode="repair"), plan.pop("brief")))
    assert write(monkeypatch, capsys, project, "index.html", **UNATTENDED) is None   # a repair needs no brief


def test_the_hook_says_nothing_and_lets_the_write_go_on_when_it_fails_itself(project, monkeypatch, capsys):
    owe(project)

    def broken(*args, **kwargs):
        raise RuntimeError("the state cannot be read")

    monkeypatch.setattr(next_step, "evaluate", broken)
    hook_text(monkeypatch, project, {"file_path": str(project / "index.html")}, **UNATTENDED)
    assert cli_main(["hook", "pre-write"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and "lapis-design hook pre-write: RuntimeError" in captured.err
    assert not (project / f".lapis/order/{TASK}.json").exists()


@pytest.mark.parametrize("stdin", ["", "not json", "[]", '{"cwd": 5}', '{"cwd": "/nowhere", "tool_input": "x"}'])
def test_the_hook_says_nothing_to_an_event_it_cannot_read(monkeypatch, capsys, tmp_path, stdin):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LAPIS_UNATTENDED", "1")
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    assert cli_main(["hook", "pre-write"]) == 0
    assert capsys.readouterr().out == ""
