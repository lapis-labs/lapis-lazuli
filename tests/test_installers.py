"""install.sh, install.ps1, and INSTALLATION.md from tools/build/installers.py.

The scripts run against a temporary HOME and a PATH of stub commands that log their argv, plus a
few system tools; they never touch this machine's harnesses or reach the network.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "build"))

import installers  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"
SYSTEM_TOOLS = ("uname", "id", "mkdir", "rmdir", "rm", "mktemp", "cmp", "cat")
PLACEHOLDERS = re.compile(r"\{(repo|ref|catalog|plugin|skill|agent|sha|checkout)\}")
COMMAND = re.compile(r"^\s*(?:would (?:ask, then )?run|run|would check|check): (.*)$")
SHELLS = [s for s in ("sh", "dash", "bash") if shutil.which(s)]
PWSH = shutil.which("pwsh")

STUB = """#!{python}
import json, os, sys
name = os.path.basename(sys.argv[0])
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps([name, *sys.argv[1:]]) + "\\n")
if name == "git":
    print("{sha}\\trefs/heads/release")
elif name == "curl":
    with open(sys.argv[sys.argv.index("-o") + 1], "w", encoding="utf-8") as f:
        f.write("downloaded " + sys.argv[-1] + "\\n")
elif name == "lapis-design":
    print("lapis-design 0.1.0")
"""


def load_doc():
    return yaml.safe_load((ROOT / "install/harnesses.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def doc():
    return load_doc()


@pytest.fixture(scope="module")
def generated(tmp_path_factory, doc):
    out = tmp_path_factory.mktemp("generated")
    for rel, text in installers.generate(doc, "0.1.0").items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return out


class Machine:
    """A temporary HOME and PATH: stub commands that log their argv, and the system tools the script uses."""

    def __init__(self, root: Path, scripts: Path, commands, dirs=()):
        self.root, self.scripts = root, scripts
        self.home, self.bin, self.sys, self.tmp = root / "home", root / "bin", root / "sys", root / "tmp"
        self.log = root / "calls.jsonl"
        for d in (self.home, self.bin, self.sys, self.tmp):
            d.mkdir(parents=True)
        for name in commands:
            stub = self.bin / name
            stub.write_text(STUB.replace("{python}", sys.executable).replace("{sha}", SHA), encoding="utf-8")
            stub.chmod(0o755)
        for tool in SYSTEM_TOOLS:
            (self.sys / tool).symlink_to(shutil.which(tool))
        for d in dirs:
            (self.home / d).mkdir(parents=True)

    def env(self):
        return {"HOME": str(self.home), "PATH": f"{self.bin}{os.pathsep}{self.sys}", "STUB_LOG": str(self.log),
                "TMPDIR": str(self.tmp), "LC_ALL": "C", "POWERSHELL_TELEMETRY_OPTOUT": "1",
                "POWERSHELL_UPDATECHECK": "Off"}

    def sh(self, *args, stdin="", shell="sh"):
        return subprocess.run([shutil.which(shell), str(self.scripts / "install/install.sh"), *args], input=stdin,
                              capture_output=True, text=True, env=self.env(), cwd=self.root, timeout=60)

    def pwsh(self, *args, stdin=""):
        return subprocess.run([PWSH, "-NoProfile", "-File", str(self.scripts / "install/install.ps1"), *args],
                              input=stdin, capture_output=True, text=True, env=self.env(), cwd=self.root, timeout=120)

    def pwsh_home(self):
        """Start pwsh once, so the files it keeps in HOME for itself exist before the script runs."""
        subprocess.run([PWSH, "-NoProfile", "-Command", "exit 0"], env=self.env(), cwd=self.root, check=True, timeout=120)
        return self.home_files()

    def calls(self, skip=("curl",)):
        if not self.log.exists():
            return []
        calls = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        return [c for c in calls if c[0] not in skip]

    def home_files(self):
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*"))


@pytest.fixture
def machine(tmp_path, generated):
    count = iter(range(100))

    def make(commands=("uv", "claude", "codex", "git"), dirs=()):
        return Machine(tmp_path / f"m{next(count)}", generated, commands, dirs)
    return make


def printed(out: str) -> list[list[str]]:
    """Commands the script says it runs or would run, as argv."""
    return [shlex.split(m.group(1)) for line in out.splitlines() if (m := COMMAND.match(line))]


def expected(doc, harness_ids, plugins, phase="install", verify=True):
    """Oracle: harnesses.yaml argv with placeholders filled by hand (plugin steps only; no skills or agents)."""
    repo = doc["repo"]
    static = {"repo": f"{repo['owner']}/{repo['name']}", "ref": repo["ref"], "catalog": repo["catalog"]}
    every = [p["name"] for p in doc["plugins"]]

    def fill(argv, **values):
        out = []
        for a in argv:
            for k, v in {**static, **values}.items():
                a = a.replace("{" + k + "}", v)
            assert not PLACEHOLDERS.search(a), a
            out.append(a)
        return out

    cmds = [fill(doc["cli"]["install"][0]["steps"][0]["run"])] if phase != "uninstall" else []
    for h in doc["harnesses"]:
        if h["id"] not in harness_ids:
            continue
        for st in h[phase]:
            if "run" not in st or (st.get("when") == "all-plugins" and plugins != every):
                continue
            if "{plugin}" in json.dumps(st["run"]):
                cmds += [fill(st["run"], plugin=p) for p in plugins]
            else:
                cmds.append(fill(st["run"]))
    if verify:
        cmds += [fill(s["run"]) for s in doc["cli"]["verify"]]
    return cmds


# --- generated text ------------------------------------------------------------------------------

def test_generator_fills_every_placeholder(doc):
    files = installers.generate(doc, "0.1.0")
    assert set(files) == {"install/install.sh", "install/install.ps1", "INSTALLATION.md"}
    for path, text in files.items():
        assert not PLACEHOLDERS.search(text), (path, PLACEHOLDERS.search(text).group(0))
        assert text.endswith("\n") and "\r" not in text
    assert files["install/install.sh"].isascii() and files["install/install.ps1"].isascii()
    assert "Invoke-Expression" not in files["install/install.ps1"].split("\n", 5)[-1]
    assert "eval " not in files["install/install.sh"]


def test_generator_rejects_unknown_placeholders(doc):
    bad = json.loads(json.dumps(doc))
    bad["harnesses"][0]["install"][0]["run"].append("{version}")
    with pytest.raises(ValueError, match="version"):
        installers.generate(bad, "0.1.0")


@pytest.mark.parametrize("shell", SHELLS)
def test_install_sh_parses(generated, shell):
    subprocess.run([shell, "-n", str(generated / "install/install.sh")], check=True)


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck is not installed")
def test_install_sh_passes_shellcheck(generated):
    subprocess.run(["shellcheck", "-s", "sh", str(generated / "install/install.sh")], check=True)


@pytest.mark.skipif(not PWSH, reason="pwsh is not installed")
def test_install_ps1_parses(generated):
    script = ("$e = $null; $t = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
              f"'{generated / 'install/install.ps1'}', [ref]$t, [ref]$e); @($e).Count")
    out = subprocess.run([PWSH, "-NoProfile", "-Command", script], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "0", out.stdout


# --- install.sh ----------------------------------------------------------------------------------

@pytest.mark.parametrize("shell", SHELLS)
def test_dry_run_runs_nothing_and_prints_the_filled_commands(doc, machine, shell):
    m = machine()
    r = m.sh("--dry-run", shell=shell)
    assert r.returncode == 0, r.stdout + r.stderr
    assert m.calls(skip=()) == [] and m.home_files() == []
    every = [p["name"] for p in doc["plugins"]]
    assert printed(r.stdout) == expected(doc, {"claude-code", "codex"}, every)
    assert "found: Claude Code (command claude)" in r.stdout and "found: OpenAI Codex CLI (command codex)" in r.stdout
    for absent in ("omp", "pi", "hermes", "npx", "Oh-My-Pi", "Hermes Agent"):
        assert not re.search(rf"(^|\s){re.escape(absent)}(\s|$)", "\n".join(
            line for line in r.stdout.splitlines() if COMMAND.match(line) or line.startswith("=="))), absent
    critic = f"{m.home}/.codex/agents/ulm-critic.toml"
    assert f"would ask, then copy: https://raw.githubusercontent.com/lapis-labs/lapis-lazuli/release/" \
           f"dist/codex/agents/ulm-critic.toml -> {critic}" in r.stdout
    assert "Open /hooks in Codex" in r.stdout and "dry run: nothing was changed" in r.stdout


def test_real_run_runs_the_same_commands_and_asks_before_copying(doc, machine):
    m = machine(("uv", "claude", "codex", "git", "curl", "lapis-design", "lazuli"))
    dry = printed(m.sh("--dry-run").stdout)
    r = m.sh(stdin="n\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert m.calls() == dry
    assert "Copy ulm-critic.toml to" in r.stdout and "[y/N] n" in r.stdout
    assert not (m.home / ".codex/agents/ulm-critic.toml").exists()
    assert "OpenAI Codex CLI (you declined): copy" in r.stdout
    assert "ran claude plugin marketplace add lapis-labs/lapis-lazuli@release" in r.stdout   # the change log
    assert list(m.tmp.iterdir()) == []


def test_yes_copies_the_critic_and_a_second_run_leaves_it(machine):
    m = machine(("uv", "claude", "codex", "git", "curl", "lapis-design", "lazuli"))
    r = m.sh("--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    critic = m.home / ".codex/agents/ulm-critic.toml"
    url = "https://raw.githubusercontent.com/lapis-labs/lapis-lazuli/release/dist/codex/agents/ulm-critic.toml"
    assert critic.read_text() == f"downloaded {url}\n"
    assert f"copied {url} to {critic}" in r.stdout
    again = m.sh(stdin="")
    assert again.returncode == 0 and f"unchanged: {critic}" in again.stdout and "[y/N]" not in again.stdout


def test_update_runs_the_update_steps_and_reinstalls_the_cli(doc, machine):
    m = machine()
    r = m.sh("--update", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert printed(r.stdout) == expected(doc, {"claude-code", "codex"}, [p["name"] for p in doc["plugins"]], "update")


def test_the_critic_comes_only_with_its_plugin(machine):
    m = machine()
    r = m.sh("--dry-run", "--plugin", "lapis")
    assert r.returncode == 0 and "ulm-critic" not in r.stdout
    assert ["codex", "plugin", "add", "lapis@lapis-lazuli"] in printed(r.stdout)
    assert ["codex", "plugin", "add", "lazuli@lapis-lazuli"] not in printed(r.stdout)


def test_partial_uninstall_keeps_catalogs_packages_and_the_cli(doc, machine):
    m = machine(("uv", "claude", "codex", "pi", "hermes", "git"))
    critic = m.home / ".codex/agents/ulm-critic.toml"
    critic.parent.mkdir(parents=True)
    critic.write_text("critic\n")
    r = m.sh("--uninstall", "--plugin", "lapis", "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    lapis = next(p for p in doc["plugins"] if p["name"] == "lapis")["skills"]
    assert m.calls() == [["claude", "plugin", "uninstall", "lapis@lapis-lazuli", "-s", "user"],
                         ["codex", "plugin", "remove", "lapis@lapis-lazuli"],
                         *[["hermes", "skills", "uninstall", s] for s in lapis]]
    assert critic.exists()
    for kept in ("claude plugin marketplace remove lapis-lazuli", "pi remove git:github.com/lapis-labs/lapis-lazuli",
                 "hermes plugins remove lapis-lazuli", "hermes mcp remove lapis-lazuli"):
        assert f"not now (only when every plugin is removed): {kept}" in r.stdout
    assert "kept: the CLI goes only with every plugin from every harness" in r.stdout


def test_full_uninstall_removes_catalogs_packages_and_the_cli(doc, machine):
    m = machine(("uv", "claude", "codex", "pi", "hermes", "git"))
    critic = m.home / ".codex/agents/ulm-critic.toml"
    critic.parent.mkdir(parents=True)
    critic.write_text("critic\n")
    r = m.sh("--uninstall", "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    calls = m.calls()
    every = [p["name"] for p in doc["plugins"]]
    assert calls[:len(every) + 1] == [*[["claude", "plugin", "uninstall", f"{p}@lapis-lazuli", "-s", "user"]
                                        for p in every], ["claude", "plugin", "marketplace", "remove", "lapis-lazuli"]]
    for call in (["codex", "plugin", "marketplace", "remove", "lapis-lazuli"],
                 ["pi", "remove", "git:github.com/lapis-labs/lapis-lazuli"],
                 ["hermes", "plugins", "remove", "lapis-lazuli"], ["hermes", "mcp", "remove", "lapis-lazuli"]):
        assert call in calls
    assert calls[-1] == ["uv", "tool", "uninstall", "lapis-design"]
    assert not critic.exists() and f"removed: {critic}" in r.stdout


RUNNERS = ["sh", pytest.param("pwsh", marks=pytest.mark.skipif(not PWSH, reason="pwsh is not installed"))]

@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize("state", ["empty", "nonempty", "absent"])
def test_codex_uninstall_removes_only_an_empty_cache_folder_and_still_removes_a_file(machine, runner, state):
    m = machine(("codex",))
    cache = m.home / ".codex/plugins/cache/lapis-lazuli"
    if state != "absent":
        cache.mkdir(parents=True)
    if state == "nonempty":
        (cache / ".hidden").write_text("hidden\n")
    critic = m.home / ".codex/agents/ulm-critic.toml"
    critic.parent.mkdir(parents=True)
    critic.write_text("critic\n")

    r = getattr(m, runner)("--uninstall", "--harness", "codex", "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not critic.exists() and f"removed: {critic}" in r.stdout
    assert m.calls() == [
        *[["codex", "plugin", "remove", f"{p}@lapis-lazuli"] for p in ("lapis", "ultramarine", "lazuli")],
        ["codex", "plugin", "marketplace", "remove", "lapis-lazuli"],
    ]
    if state == "empty":
        assert not cache.exists()
        assert f"removed empty folder: {cache}{os.sep}" in r.stdout
    elif state == "nonempty":
        assert (cache / ".hidden").read_text() == "hidden\n"
        assert f"kept (not empty): {cache}{os.sep}" in r.stdout
        assert f"- OpenAI Codex CLI: remove folder if empty: {cache}{os.sep}" in r.stdout
        assert "  failed:" not in r.stdout
    else:
        assert f"already absent: {cache}{os.sep}" in r.stdout


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize("state", ["file", "symlink", "dangling-symlink", "unreadable"])
def test_codex_empty_folder_rule_keeps_non_directories_and_unreadable_folders(machine, runner, state):
    m = machine(("codex",))
    cache = m.home / ".codex/plugins/cache/lapis-lazuli"
    cache.parent.mkdir(parents=True)
    if state == "file":
        cache.write_text("keep this file\n")
        reason = "not a folder"
    elif state in ("symlink", "dangling-symlink"):
        target = m.root / "external-cache"
        if state == "symlink":
            target.mkdir()
            (target / "keep").write_text("keep this file\n")
        cache.symlink_to(target, target_is_directory=True)
        reason = "symbolic link"
    else:
        cache.mkdir()
        cache.chmod(0)
        if os.access(cache, os.R_OK):          # root reads a mode-000 folder, so nothing is unreadable
            cache.chmod(0o700)
            pytest.skip("a mode-000 folder is still readable here (running as root)")
        reason = "unreadable"
    try:
        r = getattr(m, runner)("--uninstall", "--harness", "codex", "--yes")
        assert r.returncode == 0, r.stdout + r.stderr
        assert f"kept ({reason}): {cache}{os.sep}" in r.stdout
        assert f"- OpenAI Codex CLI: remove folder if empty: {cache}{os.sep}" in r.stdout
        assert "  failed:" not in r.stdout
        if state == "file":
            assert cache.read_text() == "keep this file\n"
        elif state == "symlink":
            assert cache.is_symlink() and (target / "keep").read_text() == "keep this file\n"
        elif state == "dangling-symlink":
            assert cache.is_symlink()
        else:
            assert cache.is_dir()
    finally:
        if state == "unreadable" and cache.is_dir():
            cache.chmod(0o700)


@pytest.mark.parametrize("runner", RUNNERS)
def test_codex_cache_folder_is_kept_on_partial_uninstall(machine, runner):
    m = machine(("codex",))
    cache = m.home / ".codex/plugins/cache/lapis-lazuli"
    cache.mkdir(parents=True)
    r = getattr(m, runner)("--uninstall", "--harness", "codex", "--plugin", "lapis")
    assert r.returncode == 0, r.stdout + r.stderr
    assert cache.is_dir()
    assert f"not now (only when every plugin is removed): remove folder if empty: " \
           f"~/.codex/plugins/cache/lapis-lazuli/" in r.stdout
    assert ["codex", "plugin", "marketplace", "remove", "lapis-lazuli"] not in m.calls()


@pytest.mark.parametrize("runner", RUNNERS)
def test_codex_cache_folder_dry_run_and_manual_mode_do_not_remove_it(machine, runner):
    for manual in (False, True):
        m = machine(() if manual else ("codex",))
        cache = m.home / ".codex/plugins/cache/lapis-lazuli"
        cache.mkdir(parents=True)
        r = getattr(m, runner)("--uninstall", "--harness", "codex", *(["--dry-run"] if not manual else []))
        assert r.returncode == 0, r.stdout + r.stderr
        assert cache.is_dir()
        line = f"remove folder if empty: {cache}{os.sep}"
        if manual:
            assert "not on PATH: codex" in r.stdout
            assert f"- OpenAI Codex CLI: {line}" in r.stdout
        else:
            assert f"would {line}" in r.stdout


def test_codex_cache_folder_uninstall_is_documented(generated):
    md = (generated / "INSTALLATION.md").read_text(encoding="utf-8")
    assert ("The installer removes `~/.codex/plugins/cache/lapis-lazuli/` only when it is an empty "
            "directory; otherwise it lists the path for manual review.") in md
    assert "\nRemove `~/.codex/plugins/cache/lapis-lazuli/` if empty.\n" not in md


@pytest.mark.parametrize("runner", RUNNERS)
def test_hermes_installs_each_skill_and_pins_the_commit(doc, machine, runner):
    m = machine(("uv", "hermes", "git", "lapis-design", "lazuli"))
    r = getattr(m, runner)("--harness", "hermes", "--plugin", "lazuli", "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    lazuli = next(p for p in doc["plugins"] if p["name"] == "lazuli")["skills"]
    assert m.calls() == [
        ["uv", "tool", "install", "--force", "git+https://github.com/lapis-labs/lapis-lazuli@release"],
        *[["hermes", "skills", "install", f"lapis-labs/lapis-lazuli/dist/skills/{s}", "--yes"] for s in lazuli],
        ["git", "ls-remote", "https://github.com/lapis-labs/lapis-lazuli", "refs/heads/release"],
        ["hermes", "plugins", "install", "lapis-labs/lapis-lazuli/plugins/hermes/lapis-lazuli", "--ref", SHA, "--enable"],
        ["hermes", "mcp", "add", "lapis-lazuli", "--command", "lapis-design", "--args", "mcp"],
        ["lapis-design", "--version"], ["lazuli", "doctor"]]


CLONE = ["git", "clone", "--depth", "1", "--branch", "release", "https://github.com/lapis-labs/lapis-lazuli"]
PLUGINS = ["lapis", "ultramarine", "lazuli"]


@pytest.mark.parametrize("runner", RUNNERS)
def test_antigravity_dry_run_names_one_clone_and_installs_each_plugin_from_it(machine, runner):
    m = machine(("uv", "agy", "git", "lapis-design", "lazuli"))
    before = m.pwsh_home() if runner == "pwsh" else []
    r = getattr(m, runner)("--harness", "antigravity", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert m.calls(skip=()) == [] and m.home_files() == before and list(m.tmp.iterdir()) == []
    run = [c for c in printed(r.stdout) if c[0] in ("git", "agy")]
    assert run == [["git", "clone", "--depth", "1", "--branch", "release", "https://github.com/lapis-labs/lapis-lazuli",
                    "<checkout>"],
                   *[["agy", "plugin", "install", f"<checkout>/dist/antigravity/{p}"] for p in PLUGINS]]
    assert "dry run: nothing was changed" in r.stdout


@pytest.mark.parametrize("runner", RUNNERS)
def test_antigravity_installs_from_a_temporary_clone_and_deletes_it(machine, runner):
    m = machine(("uv", "agy", "git", "lapis-design", "lazuli"))
    r = getattr(m, runner)("--harness", "antigravity", "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    clones = [c for c in m.calls() if c[:2] == ["git", "clone"]]
    assert len(clones) == 1 and clones[0][:-1] == CLONE
    folder = Path(clones[0][-1])
    assert folder.parent == m.tmp and folder.name.startswith("lapis-lazuli-checkout")
    assert [c for c in m.calls() if c[0] == "agy"] == [
        ["agy", "plugin", "install", f"{folder}/dist/antigravity/{p}"] for p in PLUGINS]
    assert not folder.exists() and list(m.tmp.iterdir()) == []             # the clone is deleted when the script ends


@pytest.mark.parametrize("runner", RUNNERS)
def test_antigravity_update_installs_again_and_a_partial_run_keeps_to_its_plugin(machine, runner):
    m = machine(("uv", "agy", "git", "lapis-design", "lazuli"))
    r = getattr(m, runner)("--harness", "antigravity", "--update", "--plugin", "lazuli", "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    folder = Path(next(c for c in m.calls() if c[:2] == ["git", "clone"])[-1])
    assert [c for c in m.calls() if c[0] == "agy"] == [["agy", "plugin", "install", f"{folder}/dist/antigravity/lazuli"]]


@pytest.mark.parametrize("runner", RUNNERS)
def test_antigravity_uninstall_removes_each_plugin_and_clones_nothing(machine, runner):
    m = machine(("uv", "agy", "git", "lapis-design", "lazuli"))
    r = getattr(m, runner)("--harness", "antigravity", "--uninstall", "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert [c for c in m.calls() if c[0] in ("agy", "git")] == [["agy", "plugin", "uninstall", p] for p in PLUGINS]


@pytest.mark.parametrize("runner", RUNNERS)
def test_antigravity_without_git_installs_nothing_and_says_why(machine, runner):
    m = machine(("uv", "agy", "lapis-design", "lazuli"))
    r = getattr(m, runner)("--harness", "antigravity", "--yes")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "could not clone release" in r.stdout and "needs a clone of release" in r.stdout
    assert [c for c in m.calls() if c[0] == "agy"] == [] and list(m.tmp.iterdir()) == []


@pytest.mark.parametrize("runner", RUNNERS)
def test_antigravity_with_a_failing_clone_installs_nothing_and_leaves_no_folder(machine, runner):
    m = machine(("uv", "agy", "git", "lapis-design", "lazuli"))
    if os.name == "nt":
        pytest.skip("the failing git stub is a sh script")
    (m.bin / "git").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    r = getattr(m, runner)("--harness", "antigravity", "--yes")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "could not clone release" in r.stdout
    assert [c for c in m.calls() if c[0] == "agy"] == [] and list(m.tmp.iterdir()) == []


@pytest.mark.parametrize("runner", RUNNERS)
def test_antigravity_found_by_its_folder_alone_gets_the_to_do_list_without_a_clone(machine, runner):
    m = machine(("uv", "git", "lapis-design", "lazuli"), dirs=(".gemini/antigravity-cli",))
    r = getattr(m, runner)("--harness", "antigravity", "--plugin", "lazuli")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "found: Antigravity CLI (folder ~/.gemini/antigravity-cli)" in r.stdout and "not on PATH: agy" in r.stdout
    assert "- Antigravity CLI: agy plugin install <checkout>/dist/antigravity/lazuli" in r.stdout.replace("'", "")
    assert [c[0] for c in m.calls()] == ["uv", "lapis-design", "lazuli"] and list(m.tmp.iterdir()) == []


def test_the_guide_explains_the_clone_the_antigravity_commands_install_from(generated):
    md = (generated / "INSTALLATION.md").read_text(encoding="utf-8")
    section = md.split("\n### Antigravity CLI\n", 1)[1].split("\n### ", 1)[0]
    assert "agy plugin install '<checkout>/dist/antigravity/lapis'" in section or \
        "agy plugin install <checkout>/dist/antigravity/lapis" in section
    assert "`<checkout>` is a clone of the `release` branch: " \
           "`git clone --depth 1 --branch release https://github.com/lapis-labs/lapis-lazuli.git <checkout>`" in section
    assert "Sources (checked 2026-10-06)" in section
    assert "agy plugin uninstall lapis" in section


def test_a_named_harness_that_is_missing_stops_before_any_change(doc, machine):
    name = next(h["name"] for h in doc["harnesses"] if h["id"] == "hermes")
    m = machine()
    r = m.sh("--harness", "hermes")
    assert r.returncode == 1
    assert f"{name} is not installed here: found no command hermes or folder ~/.hermes" in r.stderr
    assert f"INSTALLATION.md#{installers._slug(name)}" in r.stderr
    assert m.calls(skip=()) == [] and m.home_files() == []


def test_a_harness_without_its_command_gets_a_to_do_list(doc, machine):
    name = next(h["name"] for h in doc["harnesses"] if h["id"] == "hermes")
    m = machine(("uv", "git", "lapis-design", "lazuli"), dirs=(".hermes",))
    r = m.sh("--harness", "hermes", "--plugin", "lapis")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"found: {name} (folder ~/.hermes)" in r.stdout and "not on PATH: hermes" in r.stdout
    assert f"- {name}: hermes skills install lapis-labs/lapis-lazuli/dist/skills/lps-ux --yes" in r.stdout
    assert f"--ref {SHA} --enable" in r.stdout
    assert [c[0] for c in m.calls()] == ["uv", "git", "lapis-design", "lazuli"]


def test_other_agents_install_the_flat_skills_and_show_the_snippet(machine):
    m = machine(("uv", "npx"), dirs=(".cursor", ".kiro"))
    r = m.sh("--dry-run", "--plugin", "lapis")
    assert r.returncode == 0, r.stdout + r.stderr
    url = "https://github.com/lapis-labs/lapis-lazuli/tree/release/dist/skills"
    assert [c for c in printed(r.stdout) if c[0] == "npx"] == [
        ["npx", "-y", "skills", "add", url, "-g", "-y", "-a", "cursor"],
        ["npx", "-y", "skills", "add", url, "-g", "-y", "-a", "kiro-cli"]]
    assert "Other Agent Skills harnesses takes every plugin at once; --plugin does not narrow it" in r.stdout
    assert "would show: https://raw.githubusercontent.com/lapis-labs/lapis-lazuli/release/dist/AGENTS.snippet.md" \
        in r.stdout


@pytest.mark.parametrize("args", [["--bogus"], ["--harness", "nope"], ["--plugin", "nope"], ["--harness"],
                                  ["--update", "--uninstall"], ["--plugin", "lapis ultramarine"]])
def test_unknown_options_fail_with_usage(machine, args):
    m = machine()
    r = m.sh(*args)
    assert r.returncode == 2 and "Usage: install.sh" in r.stderr, r.stderr
    assert m.calls(skip=()) == []


# --- install.ps1 (only where pwsh is installed) --------------------------------------------------

@pytest.mark.skipif(not PWSH, reason="pwsh is not installed")
def test_ps1_dry_run_prints_the_same_commands(doc, machine):
    m = machine()
    before = m.pwsh_home()
    r = m.pwsh("--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert m.calls(skip=()) == [] and m.home_files() == before
    assert printed(r.stdout) == expected(doc, {"claude-code", "codex"}, [p["name"] for p in doc["plugins"]])
    assert "would ask, then copy:" in r.stdout and "dry run: nothing was changed" in r.stdout


@pytest.mark.skipif(not PWSH, reason="pwsh is not installed")
def test_ps1_real_run_runs_the_dry_run_commands(doc, machine):
    m = machine(("uv", "claude", "codex", "git", "lapis-design", "lazuli"))
    dry = printed(m.pwsh("--dry-run", "--plugin", "lapis").stdout)
    r = m.pwsh("--plugin", "lapis")
    assert r.returncode == 0, r.stdout + r.stderr
    assert m.calls() == dry == expected(doc, {"claude-code", "codex"}, ["lapis"])
    partial = m.pwsh("--uninstall", "--plugin", "lapis")
    assert partial.returncode == 0 and "not now (only when every plugin is removed)" in partial.stdout
    assert m.calls()[len(dry):] == expected(doc, {"claude-code", "codex"}, ["lapis"], "uninstall", verify=False)


@pytest.mark.skipif(not PWSH, reason="pwsh is not installed")
def test_ps1_asks_before_removing_the_critic(machine):
    m = machine()
    critic = m.home / ".codex/agents/ulm-critic.toml"
    critic.parent.mkdir(parents=True)
    critic.write_text("critic\n")
    args = ("--uninstall", "--plugin", "ultramarine", "--harness", "codex")
    no = m.pwsh(*args, stdin="n\n")
    assert no.returncode == 0 and critic.exists() and "OpenAI Codex CLI (you declined): remove" in no.stdout
    yes = m.pwsh(*args, stdin="y\n")
    assert yes.returncode == 0 and not critic.exists(), yes.stdout
    assert m.calls() == [["codex", "plugin", "remove", "ultramarine@lapis-lazuli"]] * 2


@pytest.mark.skipif(not PWSH, reason="pwsh is not installed")
@pytest.mark.parametrize("args, code", [(["--bogus"], 2), (["--harness", "nope"], 2), (["--harness", "hermes"], 1)])
def test_ps1_rejects_bad_options_and_missing_harnesses(machine, args, code):
    m = machine()
    r = m.pwsh(*args)
    assert r.returncode == code, r.stdout + r.stderr
    assert m.calls(skip=()) == []


# --- INSTALLATION.md -----------------------------------------------------------------------------

def test_installation_guide_covers_every_harness(doc, generated):
    md = (generated / "INSTALLATION.md").read_text(encoding="utf-8")
    for h in doc["harnesses"]:
        assert f"\n### {h['name']}\n" in md
        for item in h.get("unverified", []) + h.get("trust", []) + h.get("conflicts", []):
            assert f"- {item.replace('<', chr(92) + '<')}\n" in md, item
    assert md.count("**Not yet confirmed**") == sum(1 for h in doc["harnesses"] if h.get("unverified"))
    raw = "https://raw.githubusercontent.com/lapis-labs/lapis-lazuli/release/install/"
    assert f'sh -c "$(curl -fsSL {raw}install.sh)" install.sh --dry-run' in md
    assert f"& ([scriptblock]::Create((Invoke-RestMethod {raw}install.ps1))) --dry-run" in md
    for section in ("## Quick install", "## Identify your harness", "## CLI and optional components",
                    "## Update and uninstall", "## Troubleshooting", "## Instructions for agents"):
        assert f"\n{section}\n" in md
    assert "playwright install chromium-headless-shell" in md


def test_installation_guide_runs_the_cli_name_only_from_the_installed_tool(generated):
    """`lapis-design` is not a PyPI name this project owns: an online `uv tool run` of it would resolve
    whatever package holds the name when no such tool is installed. `--offline` keeps it to the
    installed tool environment and makes uv fail otherwise."""
    md = (generated / "INSTALLATION.md").read_text(encoding="utf-8")
    runs = [line for line in md.splitlines() if line.startswith(("uv tool run ", "uvx "))]
    assert runs and all(line.startswith("uv tool run --offline --from lapis-design ") for line in runs)


def test_installation_guide_shows_the_commands_the_script_runs(machine):
    m = machine()
    r = m.sh("--dry-run")
    md = (m.scripts / "INSTALLATION.md").read_text(encoding="utf-8")
    md_lines = set(md.splitlines())
    lines = [COMMAND.match(line).group(1) for line in r.stdout.splitlines() if COMMAND.match(line)]
    assert lines and [line for line in lines if line not in md_lines and f"`{line}`" not in md] == []
