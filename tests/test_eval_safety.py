"""tools/eval safety: what a run record may hold (EV2), the agent's environment (EV3), what `--resume`
refuses (EV4, EV5), stopping a session on SIGTERM and SIGHUP (EV5), links that leave the project (EV6), and
where the blind review's answer key lives (EV8). A fake `codex` stands in for the harness; no model, network,
or browser is started."""
import importlib.util
import json
import os
import re
import signal
import stat
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

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
score = load("score")
review = load("review")

TASK = "kiln-landing-ko"

# A Codex stand-in. The agent's environment is an allow-list, so it takes its instructions from
# control.json beside it: `outside` (skills the user has of their own) and `mode` (`hang`).
FAKE_CODEX = textwrap.dedent('''\
    #!__PYTHON__
    import json, os, re, subprocess, sys, time
    args = sys.argv[1:]
    here = os.path.dirname(os.path.abspath(__file__))
    control_file = os.path.join(here, "control.json")
    control = json.load(open(control_file)) if os.path.exists(control_file) else {}
    if args[:1] == ["--version"]:
        print("codex-cli 0.0-test"); sys.exit(0)
    if args[:2] == ["login", "status"]:
        print("Logged in using test"); sys.exit(0)
    if args[:2] == ["debug", "prompt-input"]:
        off = set(re.findall(r'path="([^"]+)"', " ".join(a for a in args if a.startswith("skills.config="))))
        skills = list(control.get("outside", {}).items())
        project = os.path.join(os.getcwd(), ".agents", "skills")
        if os.path.isdir(project):
            skills += [(n, os.path.join(project, n, "SKILL.md")) for n in sorted(os.listdir(project))]
        keep = [(n, p) for n, p in skills if p not in off and os.path.dirname(p) not in off]
        body = "<skills_instructions>\\n### Skill roots\\n### Available skills\\n"
        body += "".join(f"- {n}: d. (file: {p})\\n" for n, p in keep) + "</skills_instructions>"
        print(json.dumps([{"role": "developer", "content": [{"type": "input_text", "text": body}]}]))
        sys.exit(0)
    if args[:1] == ["exec"]:
        with open(os.path.join(here, "exec.jsonl"), "a") as log:
            log.write(json.dumps({"env": dict(os.environ), "args": args}) + "\\n")
        sys.stdin.read()
        if control.get("mode") == "hang":
            grandchild = subprocess.Popen(["sleep", "300"])
            with open(os.path.join(here, "pids.json"), "w") as pids:
                json.dump({"codex": os.getpid(), "grandchild": grandchild.pid}, pids)
            time.sleep(300)
        open(os.path.join(args[args.index("-C") + 1], "index.html"), "w").write("<p>hi</p>")
        print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}))
        open(args[args.index("-o") + 1], "w").write("done")
        sys.exit(0)
    sys.exit(2)
''')


class Fake:
    def __init__(self, folder: Path):
        folder.mkdir(parents=True)
        self.path = folder / "codex"
        self.path.write_text(FAKE_CODEX.replace("__PYTHON__", sys.executable))
        self.path.chmod(self.path.stat().st_mode | stat.S_IEXEC)
        self.control = folder / "control.json"

    def configure(self, **control):
        self.control.write_text(json.dumps(control))

    def execs(self) -> list[dict]:
        log = self.path.parent / "exec.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.is_file() else []

    def start(self, out, *extra):
        return run.main(["--codex", str(self.path), "--model", "test-model", "--tasks", TASK,
                         "--replicates", "1", "--seed", "3", "--out", str(out), *extra])

    def resume(self, out, *extra):
        return run.main(["--codex", str(self.path), "--out", str(out), "--resume", *extra])


@pytest.fixture
def home(tmp_path, monkeypatch):
    """The operator's home: HOME points at it, the account is called opuser, and it holds the login and the
    user's own skills."""
    folder = tmp_path / "opuser"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("CODEX_HOME", str(folder / ".codex"))
    for variable in ("LOGNAME", "USER"):                    # what getpass.getuser reads before the password file
        monkeypatch.setenv(variable, "opuser")
    for variable in ("LNAME", "USERNAME"):
        monkeypatch.delenv(variable, raising=False)
    return folder


@pytest.fixture
def fake(tmp_path, home):
    return Fake(tmp_path / "fake")


def record(out, run_id, name="run.json"):
    return evalkit.read_json(out / "runs" / run_id / name)


# ------------------------------------------------------------------ EV2: what a record holds

OWN_SKILLS = ("private-brand-voice", "client-acme-style")


def test_records_hold_a_count_of_the_users_own_skills_and_no_home_or_skill_paths(fake, home):
    own = {name: str(home / ".agents" / "skills" / name / "SKILL.md") for name in OWN_SKILLS}
    fake.configure(outside=own)
    out = home / ".cache" / "lapis-eval" / "x"                         # the default place: under the home folder
    assert fake.start(out) == 0
    for arm in evalkit.ARMS:
        run_id = f"{TASK}.r1.{arm}"
        assert record(out, run_id)["isolation"]["outside_before"] == 2
        assert record(out, run_id, "isolation.json")["outside_before"] == 2
        assert record(out, run_id)["isolation"]["disabled_count"] == 4    # each SKILL.md and its folder
        for name in ("run.json", "isolation.json", "command.txt"):
            text = (out / "runs" / run_id / name).read_text()
            assert str(home) not in text and "opuser" not in text, name
            assert not any(skill in text for skill in OWN_SKILLS), name
    command = (out / "runs" / f"{TASK}.r1.with" / "command.txt").read_text()
    assert "exec" in command and "-C project" in command and "skills.config=[... 4 paths switched off ...]" in command


def test_a_failed_isolation_names_no_skill_of_the_users_own_in_what_is_written():
    isolation = {"verified": False, "expected": ["lapis"], "visible": ["lapis", "private-brand-voice"],
                 "outside_before": ["private-brand-voice"], "disabled": ["/x/private-brand-voice/SKILL.md"],
                 "reason": "skills still visible after switching off the outside ones: private-brand-voice"}
    written = evalkit.public_isolation(isolation)
    assert "private-brand-voice" not in json.dumps(written) and "/x/" not in json.dumps(written)
    assert written["visible"] == ["lapis"] and written["visible_other"] == 1
    assert written["outside_before"] == 1 and written["disabled_count"] == 1
    assert evalkit.public_isolation(written) == written          # an older record is cleaned the same way


def test_probe_errors_do_not_carry_the_home_directory_into_a_record(home):
    isolation = {"verified": False, "expected": [], "visible": [], "disabled": [],
                 "reason": f"probe failed: cannot read {home}/.codex/config.toml"}
    assert str(home) not in evalkit.public_isolation(isolation)["reason"]


# ------------------------------------------------------------------ EV2: the share export

def synthetic_out(tmp_path, home):
    """A run folder in the shape older versions wrote: global skill names and paths, a transcript."""
    out = home / ".cache" / "lapis-eval" / "old"
    run_dir = out / "runs" / f"{TASK}.r1.with"
    for folder in (run_dir / "project", run_dir / "home"):
        folder.mkdir(parents=True)
    own = [str(home / ".agents" / "skills" / "private-brand-voice" / "SKILL.md")]
    own += [os.path.dirname(own[0])]
    digest = "ab" * 32
    evalkit.write_json(out / "manifest.json", {
        "version": 1, "model": "m", "codex": {"bin": str(home / "bin" / "codex"), "version": "0.0"},
        "skill_digests": {"lapis": digest}, "tasks": {TASK: {"skills": ["lapis"]}}})
    evalkit.write_json(run_dir / "run.json", {
        "id": f"{TASK}.r1.with", "task": TASK, "arm": "with", "replicate": 1, "order": 1,
        "usage": {"input_tokens": 7},
        "isolation": {"verified": True, "reason": None, "expected": ["lapis"], "visible": ["lapis"],
                      "outside_before": ["private-brand-voice"], "disabled_count": 2},
        "session": {"skills_read": ["lapis", "private-brand-voice"],
                    "errors": [f"cannot write {run_dir}/project/x in /srv/opuser/cache"]}})
    evalkit.write_json(run_dir / "isolation.json", {
        "verified": True, "reason": None, "expected": ["lapis"], "visible": ["lapis"],
        "outside_before": ["private-brand-voice"], "disabled": own})
    evalkit.write_json(run_dir / "score.json", {
        "font_db": {"sha256": digest, "faces": 2, "families": 2},
        "site": {"root": "project"},
        "checkers": {"render_check": {"status": "ok"},
                     "behavior_check": {"status": "not scored", "code": "n/a", "reason": "no behavior check"},
                     "lint": {"summary": {"blocking": 3}, "reason": f"{run_dir}/project failed"}},
        "copy": {"status": "not scored", "code": "no render", "reason": "x"}})
    cmd = run.codex_command(str(home / "bin" / "codex"), run_dir / "project", run_dir / "last-message.txt", model="m",
                            effort=None, sandbox="workspace-write", network=False, add_dirs=[run_dir / "home"],
                            disabled=own)
    (run_dir / "command.txt").write_text(
        run.command_header(out / "bin", run_dir) + run.format_command(cmd, elide=True, run_dir=run_dir)
        + " \\\n  < prompt.txt\n")
    (run_dir / "prompt.txt").write_text(evalkit.load_tasks()[TASK]["prompt"])
    (run_dir / "events.jsonl").write_text(json.dumps({"text": f"I looked at {home}/.agents/skills/x"}) + "\n")
    (run_dir / "stderr.log").write_text(f"{home}\n")
    (run_dir / "last-message.txt").write_text("done")
    (out / "summary.md").write_text(f"| run | reason |\n| {TASK} | see {run_dir}/score |\n")      # never copied
    return out


def tree_text(folder: Path) -> str:
    return "\n".join(p.read_text(errors="ignore") for p in sorted(folder.rglob("*")) if p.is_file())


def test_the_share_export_keeps_numbers_and_drops_paths_names_and_transcripts(tmp_path, home):
    share = load("share")
    out = synthetic_out(tmp_path, home)
    dest = tmp_path / "shared"
    written = share.export(out, dest)
    text = tree_text(dest)
    for secret in (str(home), "opuser", "private-brand-voice", str(out)):
        assert secret not in text, secret
    exported = dest / "runs" / f"{TASK}.r1.with"
    assert not (exported / "events.jsonl").exists() and not (exported / "project").exists()
    assert not any(name.endswith(("events.jsonl", "stderr.log", "last-message.txt")) for name in written)
    run_record = evalkit.read_json(exported / "run.json")
    assert run_record["usage"] == {"input_tokens": 7}
    assert run_record["isolation"]["outside_before"] == 1
    assert run_record["session"]["skills_read"] == ["lapis", "<other-skill>"]
    assert evalkit.read_json(exported / "score.json")["checkers"]["lint"]["summary"] == {"blocking": 3}
    assert "disabled" not in evalkit.read_json(exported / "isolation.json")
    assert "skills.config=[... 2 paths switched off ...]" in (exported / "command.txt").read_text()
    assert (exported / "prompt.txt").read_text() == f"Task id: {TASK}\n"


def test_the_share_export_refuses_a_destination_that_is_not_new_or_not_apart(tmp_path, home):
    share = load("share")
    out = synthetic_out(tmp_path, home)
    (tmp_path / "taken").mkdir()
    (tmp_path / "taken" / "x").write_text("x")
    for dest in (tmp_path / "taken", out / "shared", ROOT / "shared"):
        with pytest.raises(evalkit.KitError):
            share.export(out, dest)


def test_a_dry_run_folder_exports_the_settings_the_runner_wrote(fake, home, tmp_path):
    share = load("share")
    out = tmp_path / "out"
    assert fake.start(out, "--dry-run", "--effort", "high", "--network") == 0
    dest = tmp_path / "shared"
    written = share.export(out, dest)
    for arm in ("with", "without"):
        name = f"{TASK}.r1.{arm}"
        assert {f"runs/{name}/{f}" for f in ("run.json", "isolation.json", "command.txt", "prompt.txt")} <= set(written)
        exported = evalkit.read_json(dest / "runs" / name / "run.json")
        assert (exported["arm"], exported["model"], exported["effort"], exported["sandbox"], exported["network"]) == \
            (arm, "test-model", "high", "workspace-write", True)
        command = (dest / "runs" / name / "command.txt").read_text()
        assert command.splitlines()[2] == "codex \\" and "  -c features.apps=false \\" in command.splitlines()
        assert (dest / "runs" / name / "prompt.txt").read_text() == f"Task id: {TASK}\n"
    manifest = evalkit.read_json(dest / "manifest.json")
    assert manifest["model"] == "test-model" and manifest["codex"] == {"version": "codex-cli 0.0-test"}
    assert "opuser" not in tree_text(dest) and str(out) not in tree_text(dest)


# ------------------------------------------------------------------ EV3: the agent's environment

# __CF_USER_TEXT_ENCODING is added by macOS to every process, not passed on by the runner
ALLOWED = {"PATH", "LANG", "TERM", "HOME", "TMPDIR", "CODEX_HOME", "LAZULI_FONT_ROOTS", "PLAYWRIGHT_BROWSERS_PATH",
           "__CF_USER_TEXT_ENCODING"}


def test_the_agent_gets_an_allow_listed_environment_and_a_scratch_home(fake, home, tmp_path, monkeypatch):
    for name, value in {"OPENAI_API_KEY": "sk-secret", "GITHUB_TOKEN": "ghp_secret", "AWS_SECRET_ACCESS_KEY": "aws",
                        "HTTPS_PROXY": "http://user:pw@proxy.test:3128", "SSH_AUTH_SOCK": "/tmp/agent.sock",
                        "USER": "opuser", "LOGNAME": "opuser", "SHELL": "/bin/zsh", "EDITOR": "vi",
                        "LC_ALL": "C.UTF-8", "LANG": "en_US.UTF-8", "TERM": "xterm-256color"}.items():
        monkeypatch.setenv(name, value)
    out = tmp_path / "out"
    assert fake.start(out) == 0
    assert len(fake.execs()) == 2
    for call in fake.execs():
        env = call["env"]
        assert {k for k in env if not k.startswith("LC_")} <= ALLOWED, sorted(set(env) - ALLOWED)
        assert env["LC_ALL"] == "C.UTF-8" and env["LANG"] == "en_US.UTF-8" and env["TERM"] == "xterm-256color"
        assert env["CODEX_HOME"] == str(home / ".codex")                  # the login still works
        assert Path(env["HOME"]).parent.parent == out.resolve() / "runs"
        assert Path(env["TMPDIR"]).parent == Path(env["HOME"])
        assert Path(env["TMPDIR"]).is_dir()
        assert env["PATH"].split(os.pathsep)[0] == str(out.resolve() / "bin")


def test_every_run_switches_the_accounts_apps_off_in_both_arms_and_says_so_in_its_command(fake, tmp_path):
    out = tmp_path / "out"
    assert fake.start(out) == 0
    calls = fake.execs()
    assert len(calls) == 2
    for call in calls:
        args = call["args"]
        assert args[args.index("features.apps=false") - 1] == "-c"
    for arm in ("with", "without"):
        assert "  -c features.apps=false \\" in (out / "runs" / f"{TASK}.r1.{arm}" / "command.txt").read_text().splitlines()


# ------------------------------------------------------------------ EV4: --resume against the manifest

def test_resume_refuses_a_model_effort_sandbox_or_network_the_manifest_does_not_have(fake, tmp_path):
    out = tmp_path / "out"
    assert fake.start(out, "--dry-run", "--sandbox", "danger-full-access", "--effort", "high") == 0
    manifest = (out / "manifest.json").read_bytes()
    marker = out / "runs" / f"{TASK}.r1.with" / "project" / "marker"
    marker.write_text("x")
    for option in (["--sandbox", "workspace-write"], ["--model", "other-model"], ["--effort", "low"], ["--network"]):
        assert fake.resume(out, *option) == 2, option
        assert (out / "manifest.json").read_bytes() == manifest and marker.exists()
    assert fake.execs() == []


def test_resume_takes_a_setting_it_is_not_given_from_the_manifest_and_accepts_a_matching_one(fake, tmp_path):
    out = tmp_path / "out"
    assert fake.start(out, "--dry-run", "--network", "--effort", "high") == 0
    assert fake.resume(out, "--sandbox", "workspace-write", "--model", "test-model", "--effort", "high") == 0
    for call in fake.execs():
        assert "sandbox_workspace_write.network_access=true" in call["args"]
        assert 'model_reasoning_effort="high"' in call["args"]
    assert record(out, f"{TASK}.r1.with")["network"] is True


# ------------------------------------------------------------------ EV5: signals and a live child

def wait_for(condition, seconds=60):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("timed out waiting")


def process_state(pid):
    """The state letter of a process (`Z` is a zombie), from /proc where there is one, else from ps."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0]
    except (OSError, IndexError):
        pass
    try:
        return subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()[:1]
    except OSError:
        return ""


def gone(pid):
    """Ended: not in the process table, or a zombie that nothing has collected yet (a process whose parent
    is gone and whose new parent is slow to collect it stays one for a while under load)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return process_state(pid) == "Z"


def read_json_or_none(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):            # not there yet, or half written
        return None


def spawn_runner(fake, out, *, hup_ignored=False):
    """`run.py` as its own process (a signal must not reach pytest), with the fake Codex hanging."""
    fake.configure(mode="hang")
    argv = [sys.executable, str(ROOT / "tools" / "eval" / "run.py"), "--codex", str(fake.path), "--model", "m",
            "--tasks", TASK, "--replicates", "1", "--seed", "3", "--out", str(out)]
    if hup_ignored:                        # what `nohup` does: SIGHUP stays ignored across the exec
        argv = ["sh", "-c", 'trap "" HUP; exec "$@"', "sh", *argv]
    return subprocess.Popen(argv, env=os.environ, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def clean_up(runner, pids):
    if runner.poll() is None:
        runner.kill()
    for pid in pids.values():
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP])
def test_a_terminated_runner_stops_codex_and_its_children_and_records_the_run(fake, tmp_path, sig):
    out = tmp_path / "out"
    runner = spawn_runner(fake, out)
    pids = {}
    try:
        pids = wait_for(lambda: read_json_or_none(fake.path.parent / "pids.json"))
        runner.send_signal(sig)
        code = runner.wait(timeout=60)
        assert code == 128 + sig, runner.stderr.read()
        for pid in pids.values():
            wait_for(lambda pid=pid: gone(pid), seconds=10)
    finally:
        clean_up(runner, pids)
    ran = [r for r in (record(out, f"{TASK}.r1.{arm}") for arm in evalkit.ARMS) if r["status"] != "prepared"]
    assert len(ran) == 1 and ran[0]["status"] == "interrupted" and ran[0]["pid"] == pids["codex"]


def test_a_runner_started_with_sighup_ignored_keeps_ignoring_it(fake, tmp_path):
    runner = spawn_runner(fake, tmp_path / "out", hup_ignored=True)
    pids = {}
    try:
        pids = wait_for(lambda: read_json_or_none(fake.path.parent / "pids.json"))
        runner.send_signal(signal.SIGHUP)
        time.sleep(1)
        assert runner.poll() is None and not gone(pids["codex"])
        runner.send_signal(signal.SIGTERM)
        assert runner.wait(timeout=60) == 128 + signal.SIGTERM
    finally:
        clean_up(runner, pids)


def test_resume_refuses_while_the_recorded_codex_process_is_alive_and_deletes_nothing(fake, tmp_path):
    out = tmp_path / "out"
    assert fake.start(out, "--dry-run") == 0
    run_dir = out / "runs" / f"{TASK}.r1.with"
    marker = run_dir / "project" / "marker"
    marker.write_text("x")
    sleeper = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        evalkit.write_json(run_dir / "run.json", {**record(out, run_dir.name), "status": "running", "pid": sleeper.pid})
        assert fake.resume(out) == 2
        assert marker.exists() and fake.execs() == []
    finally:
        sleeper.kill()
        sleeper.wait()
    assert fake.resume(out) == 0                       # once the process is gone the run is repeated
    assert not marker.exists() and record(out, run_dir.name)["status"] == "completed"


# ------------------------------------------------------------------ EV6: links that leave the project

def fetch(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=10) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


@pytest.fixture
def linked_project(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("TOP-SECRET")
    project = tmp_path / "project"
    (project / "dist").mkdir(parents=True)
    (project / "dist" / "index.html").write_text("<p>ok</p>")
    (project / "shared.txt").write_text("shared")
    (project / "dist" / "same.html").symlink_to("index.html")
    (project / "dist" / "shared.txt").symlink_to("../shared.txt")           # inside the project, outside dist
    (project / "dist" / "leak.txt").symlink_to(outside / "secret.txt")
    (project / "dist" / "leakdir").symlink_to(outside, target_is_directory=True)
    return project


def test_serve_answers_a_link_only_while_its_target_stays_in_the_project(linked_project):
    with score.serve(linked_project / "dist", linked_project) as url:
        assert fetch(url + "same.html") == (200, "<p>ok</p>")
        assert fetch(url + "shared.txt") == (200, "shared")
        for path in ("leak.txt", "leakdir/secret.txt", "leakdir/"):
            status, body = fetch(url + path)
            assert status == 403 and "TOP-SECRET" not in body, path


def test_serve_without_a_project_keeps_links_inside_the_served_folder(linked_project):
    with score.serve(linked_project / "dist") as url:
        assert fetch(url + "same.html")[0] == 200
        assert fetch(url + "shared.txt")[0] == 403
        assert fetch(url + "leak.txt")[0] == 403


def test_the_site_copy_keeps_links_as_links_and_refuses_one_that_leaves_the_project(linked_project, tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<p>ok</p>")
    (site / "same.html").symlink_to("index.html")
    (site / ".cache").mkdir()
    (site / ".cache" / "hidden").symlink_to(tmp_path / "outside" / "secret.txt")     # not copied, not judged
    review._copy_site(site, tmp_path / "copy")
    assert (tmp_path / "copy" / "same.html").is_symlink() and not (tmp_path / "copy" / ".cache").exists()
    (site / "leak.txt").symlink_to(tmp_path / "outside" / "secret.txt")
    with pytest.raises(evalkit.KitError, match="leak.txt"):
        review._copy_site(site, tmp_path / "copy2")
    assert not (tmp_path / "copy2").exists()


def scored_run(out, arm, order, *, leak_to=None):
    run_id = evalkit.run_id(TASK, 1, arm)
    run_dir = out / "runs" / run_id
    (run_dir / "project").mkdir(parents=True)
    (run_dir / "project" / "index.html").write_text("<p>hi</p>")
    if leak_to:
        (run_dir / "project" / "leak.txt").symlink_to(leak_to)
    evalkit.write_json(run_dir / "run.json", {"id": run_id, "task": TASK, "arm": arm, "replicate": 1,
                                              "order": order, "project": "project"})
    evalkit.write_json(run_dir / "score.json", {"font_db": {"sha256": "ab" * 32, "faces": 2, "families": 2},
                                                "site": {"root": "project"}})
    return run_id


def test_a_review_with_a_link_out_of_a_project_stops_before_writing_anything(tmp_path):
    (tmp_path / "secret.txt").write_text("TOP-SECRET")
    out = tmp_path / "out"
    scored_run(out, "with", 1)
    scored_run(out, "without", 2, leak_to=tmp_path / "secret.txt")
    with pytest.raises(evalkit.KitError, match="leak.txt"):
        review.build(out, 1, evalkit.load_tasks())
    assert not (out / "review").exists() and not review.key_path(out).exists()


# ------------------------------------------------------------------ EV8: the answer key

def test_the_answer_key_is_written_beside_the_review_folder_never_in_it(tmp_path):
    out = tmp_path / "out"
    run_ids = [scored_run(out, "with", 1), scored_run(out, "without", 2)]
    stale = out / "review"
    stale.mkdir()
    (stale / "key.json").write_text("{}")                  # what an older version left in the folder
    review.build(out, 1, evalkit.load_tasks())
    assert not list((out / "review").rglob("key*.json"))
    shown = tree_text(out / "review")
    assert not any(run_id in shown or re.search(r"\.(with|without)\b", shown) for run_id in run_ids)
    key = evalkit.read_json(review.key_path(out))
    assert out / "review" not in review.key_path(out).parents
    assert sorted(c["arm"] for c in key["candidates"].values()) == ["with", "without"]
