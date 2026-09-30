"""tools/eval/run.py and evalkit.py: run planning, reading Codex output, skill isolation, the task file.
A fake `codex` script stands in for the harness; no model is ever started."""
import importlib.util
import json
import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "eval"))

import evalkit  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(f"eval_{name}", ROOT / "tools" / "eval" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module          # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


run = load("run")


def test_every_task_arm_pair_runs_in_each_replicate_with_a_random_arm_first():
    tasks = ["a", "b"]
    order = run.plan_runs(tasks, 3, seed=5)
    assert [r["order"] for r in order] == list(range(1, 13))
    for replicate in (1, 2, 3):
        block = order[(replicate - 1) * 4: replicate * 4]
        assert {r["replicate"] for r in block} == {replicate}
        for task in tasks:
            assert sorted(r["arm"] for r in block if r["task"] == task) == ["with", "without"]
    assert order == run.plan_runs(tasks, 3, seed=5)
    firsts = {run.plan_runs(tasks, 1, seed=s)[0]["arm"] for s in range(30)}
    assert firsts == {"with", "without"}


def test_events_sum_usage_and_report_skills_read_and_checks_run():
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        "not json",
        json.dumps({"type": "item.started", "item": {"id": "1", "type": "command_execution",
                    "command": "bash -lc 'sed -n 1,80p .agents/skills/lapis/SKILL.md'"}}),
        json.dumps({"type": "item.completed", "item": {"id": "1", "type": "command_execution",
                    "command": "bash -lc 'sed -n 1,80p .agents/skills/lapis/SKILL.md'"}}),
        json.dumps({"type": "item.completed", "item": {"id": "2", "type": "command_execution",
                    "command": "lapis-design plan check .lapis/plans/x.yaml && lazuli lock Foo"}}),
        json.dumps({"type": "item.completed", "item": {"id": "3", "type": "agent_message", "text": "done"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 60,
                                                        "output_tokens": 7, "reasoning_output_tokens": 0}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 3}}),
        json.dumps({"type": "error", "message": "stream closed\nretrying"}),
    ]
    parsed = run.parse_events(lines, ["lapis", "lps-copy"])
    assert parsed["usage"] == {"input_tokens": 150, "cached_input_tokens": 60, "output_tokens": 10,
                               "reasoning_output_tokens": 0}
    assert parsed["turns"] == 2 and parsed["commands"] == 2 and parsed["thread_id"] == "t1"
    assert parsed["skills_read"] == ["lapis"] and parsed["skills_not_read"] == ["lps-copy"]
    assert parsed["tools_run"] == {"lapis-design plan check": 1, "lazuli lock": 1}
    assert parsed["errors"] == ["stream closed"]
    assert run.parse_events([])["usage"] is None


def prompt_input(skills, roots, agents_md=True):
    block = "<skills_instructions>\n### Skill roots\n" + "".join(f"- `{k}` = `{v}`\n" for k, v in roots.items())
    block += "### Available skills\n" + "".join(
        f"- {name}: Does things: with a colon. (file: {path})\n" for name, path in skills) + "</skills_instructions>"
    items = [{"role": "developer", "content": [{"type": "input_text", "text": block}]},
             {"role": "user", "content": [{"type": "input_text", "text": "hello"}]}]
    if agents_md:
        items.insert(1, {"role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md instructions\n..."}]})
    return items


def test_prompt_input_resolves_skill_paths_through_the_roots_table(tmp_path):
    parsed = run.parse_prompt_input(prompt_input(
        [("lapis", "r1/lapis/SKILL.md"), ("imagegen", "r0/imagegen/SKILL.md"),
         ("latex:latex-doctor", "r0/latex/doctor/SKILL.md")],        # plugin skills are named plugin:skill
        {"r0": str(tmp_path / "sys"), "r1": str(tmp_path / "project" / ".agents" / "skills")}))
    assert parsed["agents_md"] is True and parsed["unparsed"] == 0
    assert {s["name"]: s["path"] for s in parsed["skills"]} == {
        "lapis": os.path.realpath(tmp_path / "project" / ".agents" / "skills" / "lapis" / "SKILL.md"),
        "imagegen": os.path.realpath(tmp_path / "sys" / "imagegen" / "SKILL.md"),
        "latex:latex-doctor": os.path.realpath(tmp_path / "sys" / "latex" / "doctor" / "SKILL.md")}
    assert run.parse_prompt_input([])["skills"] == []
    assert run.parse_prompt_input(prompt_input([], {}, agents_md=False))["agents_md"] is False


def test_prompt_input_counts_list_entries_it_cannot_read():
    items = prompt_input([("a", "/x/a/SKILL.md")], {})
    part = items[0]["content"][0]
    part["text"] = part["text"].replace("</skills_instructions>", "- an entry with no file\n</skills_instructions>")
    parsed = run.parse_prompt_input(items)
    assert parsed["unparsed"] == 1 and [s["name"] for s in parsed["skills"]] == ["a"]


FAKE_CODEX = textwrap.dedent('''\
    #!{python}
    """Stands in for `codex debug prompt-input`: lists the outside skills plus the project's, and honors
    skills.config overrides that name a SKILL.md path or its folder (unless IGNORE_OVERRIDES is set)."""
    import json, os, re, sys
    args = sys.argv[1:]
    off = set(re.findall(r'path="([^"]+)"', " ".join(a for a in args if a.startswith("skills.config="))))
    if os.environ.get("IGNORE_OVERRIDES"):
        off = set()
    outside = {outside}
    project = os.path.join(os.getcwd(), ".agents", "skills")
    skills = [(n, p) for n, p in outside.items()]
    if os.path.isdir(project):
        skills += [(n, os.path.join(project, n, "SKILL.md")) for n in sorted(os.listdir(project))]
    keep = [(n, p) for n, p in skills if p not in off and os.path.dirname(p) not in off]
    body = "<skills_instructions>\\n### Skill roots\\n### Available skills\\n"
    body += "".join(f"- {{n}}: d. (file: {{p}})\\n" for n, p in keep) + "</skills_instructions>"
    print(json.dumps([{{"role": "developer", "content": [{{"type": "input_text", "text": body}}]}}]))
''')


def fake_codex(tmp_path, outside):
    path = tmp_path / "codex"
    path.write_text(FAKE_CODEX.format(python=sys.executable, outside=repr(outside)))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def project_with(tmp_path, *skills):
    project = tmp_path / "project"
    for name in skills:
        (project / ".agents" / "skills" / name).mkdir(parents=True)
        (project / ".agents" / "skills" / name / "SKILL.md").write_text("x")
    project.mkdir(exist_ok=True)
    return project


def test_isolation_switches_off_outside_skills_and_verifies_the_arm_sees_only_its_own(tmp_path):
    codex = fake_codex(tmp_path, {"design-taste": str(tmp_path / "user" / "design-taste" / "SKILL.md")})
    with_arm = run.isolate_skills(codex, project_with(tmp_path, "lapis", "lps-copy"), dict(os.environ),
                                  ["lapis", "lps-copy"], disable_outside=True)
    assert with_arm["verified"] and with_arm["visible"] == ["lapis", "lps-copy"]
    assert with_arm["outside_before"] == ["design-taste"] and with_arm["disabled"]
    bare = tmp_path / "bare"
    bare.mkdir()
    without_arm = run.isolate_skills(codex, bare, dict(os.environ), [], disable_outside=True)
    assert without_arm["verified"] and without_arm["visible"] == []


def test_isolation_fails_when_a_skill_is_not_discovered_or_overrides_are_ignored(tmp_path):
    codex = fake_codex(tmp_path, {"design-taste": str(tmp_path / "user" / "design-taste" / "SKILL.md")})
    project = project_with(tmp_path, "lapis")
    missing = run.isolate_skills(codex, project, dict(os.environ), ["lapis", "lps-ux"], disable_outside=True)
    assert not missing["verified"] and "lps-ux" in missing["reason"]
    stubborn = run.isolate_skills(codex, project, {**os.environ, "IGNORE_OVERRIDES": "1"}, ["lapis"],
                                  disable_outside=True)
    assert not stubborn["verified"] and "design-taste" in stubborn["reason"]
    relaxed = run.isolate_skills(codex, project, {**os.environ, "IGNORE_OVERRIDES": "1"}, ["lapis"],
                                 disable_outside=False)
    assert relaxed["verified"]


def test_isolation_reports_a_probe_that_cannot_run(tmp_path):
    result = run.isolate_skills(str(tmp_path / "no-such-codex"), tmp_path, dict(os.environ), [], disable_outside=True)
    assert result["verified"] is False and result["reason"].startswith("probe failed")


def test_tree_digest_follows_names_and_bytes_not_times_or_finder_files(tmp_path):
    tree = tmp_path / "skill"
    (tree / "refs").mkdir(parents=True)
    (tree / "SKILL.md").write_text("a")
    (tree / "refs" / "x.md").write_text("b")
    first = evalkit.tree_digest(tree)
    os.utime(tree / "SKILL.md", (1, 1))
    (tree / ".DS_Store").write_text("junk")
    assert evalkit.tree_digest(tree) == first
    (tree / "refs" / "x.md").write_text("c")
    assert evalkit.tree_digest(tree) != first
    (tree / "refs" / "x.md").write_text("b")
    (tree / "refs" / "x.md").rename(tree / "refs" / "y.md")
    assert evalkit.tree_digest(tree) != first


def test_runs_never_go_inside_the_repository(tmp_path):
    with pytest.raises(evalkit.KitError):
        evalkit.ensure_outside_repo(ROOT / "eval-runs")
    assert evalkit.ensure_outside_repo(tmp_path / "runs") == (tmp_path / "runs").resolve()


def test_shipped_tasks_use_real_skills_prompts_with_their_id_and_valid_stubs():
    tasks = evalkit.load_tasks()
    assert {"kiln-landing-ko", "signup-recovery-ko"} <= set(tasks)
    schema = yaml.safe_load((ROOT / "src" / "shared" / "behavior" / "stub.schema.yaml").read_text())
    for task_id, task in tasks.items():
        for skill in task["skills"]:
            assert (ROOT / "src" / "skills" / skill / "SKILL.md").is_file(), (task_id, skill)
        stub = evalkit.stub_path(task)
        if stub:
            Draft202012Validator(schema).validate(yaml.safe_load(stub.read_text()))
    assert evalkit.stub_path(tasks["kiln-landing-ko"]) is None


def test_task_file_errors_name_the_task(tmp_path):
    bad = tmp_path / "tasks.yaml"
    bad.write_text(yaml.safe_dump({"version": 1, "tasks": {"t": {
        "prompt": "no id here", "skills": ["lapis"], "acceptance": [], "checks": {"render": True, "lint": True}}}}))
    with pytest.raises(evalkit.KitError, match="task t.*Task id: t"):
        evalkit.load_tasks(bad)


FAKE_HARNESS = textwrap.dedent('''\
    #!{python}
    """A Codex stand-in: answers --version, login status, debug prompt-input, and exec without a model."""
    import json, os, sys, time
    args = sys.argv[1:]
    here = os.path.dirname(os.path.abspath(__file__))
    if args[:1] == ["--version"]:
        print("codex-cli 0.0-test"); sys.exit(0)
    if args[:2] == ["login", "status"]:
        print("Logged in using test"); sys.exit(0)
    if args[:2] == ["debug", "prompt-input"]:
        project = os.path.join(os.getcwd(), ".agents", "skills")
        names = [] if os.path.exists(os.path.join(here, "hide")) else sorted(os.listdir(project)) if os.path.isdir(project) else []
        body = "<skills_instructions>\\n### Skill roots\\n### Available skills\\n" + "".join(
            f"- {{n}}: d. (file: {{project}}/{{n}}/SKILL.md)\\n" for n in names) + "</skills_instructions>"
        print(json.dumps([{{"role": "developer", "content": [{{"type": "input_text", "text": body}}]}}]))
        sys.exit(0)
    if args[:1] == ["exec"]:
        with open(os.path.join(here, "exec-calls.txt"), "a") as log:
            log.write(os.getcwd() + "\\n")
        prompt = sys.stdin.read()
        with open(os.path.join(here, "prompts.txt"), "a") as log:
            log.write(json.dumps(prompt) + "\\n")
        if os.path.exists(os.path.join(here, "hang")):
            time.sleep(60)
        project = args[args.index("-C") + 1]
        open(os.path.join(project, "index.html"), "w").write("<p>hi</p>")
        print(json.dumps({{"type": "thread.started", "thread_id": "T"}}))
        print(json.dumps({{"type": "item.completed", "item": {{"id": "1", "type": "command_execution",
              "command": "cat .agents/skills/lapis/SKILL.md"}}}}))
        print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 10, "output_tokens": 5}}}}))
        open(args[args.index("-o") + 1], "w").write("done")
        sys.exit(0)
    sys.exit(2)
''')


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """A fake codex on disk, and the environment the runner reads Codex's home from."""
    folder = tmp_path / "fake"
    folder.mkdir()
    path = folder / "codex"
    path.write_text(FAKE_HARNESS.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    return path


def calls(harness_path, name="exec-calls.txt"):
    file = harness_path.parent / name
    return file.read_text().splitlines() if file.is_file() else []


def start(harness_path, out, *extra):
    return run.main(["--codex", str(harness_path), "--model", "test-model", "--tasks", "kiln-landing-ko",
                     "--replicates", "1", "--seed", "3", "--out", str(out), *extra])


def test_a_real_run_records_what_the_session_did_and_gives_both_arms_the_same_prompt(harness, tmp_path):
    out = tmp_path / "out"
    assert start(harness, out) == 0
    runs = {arm: evalkit.read_json(out / "runs" / f"kiln-landing-ko.r1.{arm}" / "run.json") for arm in evalkit.ARMS}
    assert {r["status"] for r in runs.values()} == {"completed"}
    assert runs["with"]["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert runs["with"]["session"]["skills_read"] == ["lapis"]
    assert runs["with"]["session"]["skills_not_read"] == ["lps-copy", "lps-system"]
    assert runs["with"]["output"]["has_index"] and runs["without"]["output"]["has_index"]
    assert runs["with"]["skill_digest"] and runs["without"]["skill_digest"] is None
    assert runs["with"]["skill_digests"]["lapis"] == evalkit.tree_digest(ROOT / "dist" / "skills" / "lapis")
    assert not (out / "runs" / "kiln-landing-ko.r1.without" / "project" / ".agents").exists()
    prompts = calls(harness, "prompts.txt")
    assert len(prompts) == 2 and prompts[0] == prompts[1]
    assert json.loads(prompts[0]) == evalkit.load_tasks()["kiln-landing-ko"]["prompt"]
    assert all(Path(cwd).name == "project" for cwd in calls(harness))
    manifest = evalkit.read_json(out / "manifest.json")
    assert manifest["finished_at"] and len(manifest["order"]) == 2


def test_a_dry_run_prepares_folders_and_never_starts_the_agent(harness, tmp_path):
    out = tmp_path / "out"
    assert start(harness, out, "--dry-run") == 0
    assert calls(harness) == []
    record = evalkit.read_json(out / "runs" / "kiln-landing-ko.r1.with" / "run.json")
    assert record["status"] == "prepared" and record["isolation"]["verified"]
    assert not (out / "runs" / "kiln-landing-ko.r1.with" / "events.jsonl").exists()


def test_nothing_starts_when_an_arm_would_see_the_wrong_skills(harness, tmp_path, capsys):
    (harness.parent / "hide").touch()          # the agent's environment is an allow-list, so the fake reads marker files
    assert start(harness, tmp_path / "out") == 2
    assert calls(harness) == []
    assert "isolation not verified" in capsys.readouterr().err


def test_a_session_past_its_timeout_is_stopped_and_recorded(harness, tmp_path):
    (harness.parent / "hang").touch()
    out = tmp_path / "out"
    assert start(harness, out, "--timeout", "1") == 1        # results are recorded, but not every run completed
    for arm in evalkit.ARMS:
        record = evalkit.read_json(out / "runs" / f"kiln-landing-ko.r1.{arm}" / "run.json")
        assert record["status"] == "timed_out" and record["timed_out"] is True and record["duration_s"] < 30


def test_resume_skips_finished_runs_and_repeats_an_interrupted_one(harness, tmp_path):
    out = tmp_path / "out"
    assert start(harness, out) == 0
    assert len(calls(harness)) == 2
    assert run.main(["--codex", str(harness), "--out", str(out), "--resume"]) == 0
    assert len(calls(harness)) == 2
    path = out / "runs" / "kiln-landing-ko.r1.with" / "run.json"
    evalkit.write_json(path, {**evalkit.read_json(path), "status": "interrupted"})
    assert run.main(["--codex", str(harness), "--out", str(out), "--resume"]) == 0
    assert len(calls(harness)) == 3
    assert evalkit.read_json(path)["status"] == "completed"


def test_an_existing_out_folder_is_not_overwritten_without_resume(harness, tmp_path, capsys):
    out = tmp_path / "out"
    assert start(harness, out, "--dry-run") == 0
    assert start(harness, out, "--dry-run") == 2
    assert "already holds a manifest" in capsys.readouterr().err
