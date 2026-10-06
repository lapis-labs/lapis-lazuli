"""Experimental harnesses (`status: experimental` in install/harnesses.yaml) in the install scripts
and INSTALLATION.md.

Finding a harness's command or folder is not a request to install it: an experimental harness is
installed only when --harness names it. The scripts run against a temporary HOME and a PATH of stub
commands (`Machine` from test_installers). The synthetic cases use the shipped definitions with
claude-code marked experimental, so the generator stays covered when no shipped harness is
experimental any more.
"""
import re
import sys
from pathlib import Path

import pytest

from test_installers import PWSH, Machine, load_doc, printed

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "build"))

import installers  # noqa: E402

RUNNERS = ["sh", pytest.param("pwsh", marks=pytest.mark.skipif(not PWSH, reason="pwsh is not installed"))]


def experimental_ids(doc):
    return [h["id"] for h in doc["harnesses"] if h.get("status") == "experimental"]


CASES = [pytest.param("synthetic", "claude-code", id="synthetic-claude-code")] + [
    pytest.param("shipped", i, id=f"shipped-{i}") for i in experimental_ids(load_doc())]


def mentions(line: str, name: str) -> bool:
    """Whether the line names the harness as a word (`pi` is inside `lapis-lazuli`)."""
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", line) is not None


def write_scripts(out: Path, doc: dict) -> Path:
    for rel, text in installers.generate(doc, "0.1.0").items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return out


@pytest.fixture(scope="module")
def sources(tmp_path_factory):
    """Case name -> (folder with the generated scripts, the definitions they came from)."""
    marked = load_doc()
    next(h for h in marked["harnesses"] if h["id"] == "claude-code")["status"] = "experimental"
    return {name: (write_scripts(tmp_path_factory.mktemp(name), doc), doc)
            for name, doc in (("shipped", load_doc()), ("synthetic", marked))}


@pytest.fixture
def make(tmp_path, sources):
    count = iter(range(100))

    def build(case, harness, *, command=True, folder=False):
        scripts, doc = sources[case]
        h = next(h for h in doc["harnesses"] if h["id"] == harness)
        commands = ["uv", "git", "lapis-design", "lazuli"] + ([h["detect"]["commands"][0]] if command else [])
        dirs = [h["detect"]["dirs"][0][2:]] if folder else []
        return Machine(tmp_path / f"m{next(count)}", scripts, commands, dirs), h
    return build


def sharing_the_folder(doc: dict, h: dict) -> list[str]:
    """Other harnesses that the folder detecting `h` also detects, because their own detection folder holds it
    (Gemini CLI's ~/.gemini holds Antigravity's ~/.gemini/antigravity-cli); they install as usual."""
    own = h["detect"].get("dirs", [])
    return [o["id"] for o in doc["harnesses"] if o is not h and any(
        mine.startswith(d.rstrip("/") + "/") for mine in own
        for d in [*o.get("detect", {}).get("dirs", []), *(x for a in o.get("agents", []) for x in a["dirs"])])]


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize("found_by", ["command", "folder"])
@pytest.mark.parametrize("case, harness", CASES)
def test_detection_alone_never_installs_an_experimental_harness(make, sources, case, harness, found_by, runner):
    m, h = make(case, harness, command=found_by == "command", folder=found_by == "folder")
    r = getattr(m, runner)("--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    found = [line for line in lines if line.startswith("  found:") and mentions(line, h["name"])]
    assert len(found) == 1 and "experimental" in found[0] and f"--harness {harness}" in found[0], found
    assert [line for line in lines if mentions(line, h["name"]) and line not in found] == []
    assert [c for c in m.calls() if c[0] == h["detect"]["commands"][0]] == []
    if found_by == "folder" and sharing_the_folder(sources[case][1], h):
        assert "no harness to install" not in r.stdout          # the harness that shares the folder installs as usual
    else:
        assert "no harness to install" in r.stdout


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize("case, harness", CASES)
def test_naming_an_experimental_harness_installs_it(make, case, harness, runner):
    m, h = make(case, harness)
    r = getattr(m, runner)("--harness", harness, "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    first = next(st["run"][0] for st in h["install"] if "run" in st)
    assert first in [c[0] for c in m.calls()]
    assert not [line for line in r.stdout.splitlines() if line.startswith("  found:") and "experimental" in line]


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize("case, harness", CASES)
def test_a_named_experimental_harness_found_by_folder_gets_the_to_do_list(make, case, harness, runner):
    m, h = make(case, harness, command=False, folder=True)
    r = getattr(m, runner)("--harness", harness, "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"- {h['name']}: " in r.stdout
    assert [c for c in m.calls() if c[0] == h["detect"]["commands"][0]] == []


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize("mode", ["--update", "--uninstall"])
@pytest.mark.parametrize("case, harness", CASES)
def test_update_and_uninstall_treat_a_found_experimental_harness_like_any_other(make, case, harness, mode, runner):
    m, h = make(case, harness)
    r = getattr(m, runner)(mode, "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert h["detect"]["commands"][0] in [c[0] for c in printed(r.stdout)]
    assert "experimental" not in r.stdout


@pytest.mark.parametrize("case, harness", CASES)
def test_the_guide_marks_an_experimental_harness_under_its_plain_name(sources, case, harness):
    scripts, doc = sources[case]
    md = (scripts / "INSTALLATION.md").read_text(encoding="utf-8")
    h = next(h for h in doc["harnesses"] if h["id"] == harness)
    assert "experimental" not in h["name"].lower()
    assert f"\n### {h['name']}\n\nExperimental: " in md
    assert f"| {h['name']} (`{harness}`) | Experimental |" in md
    assert md.count("\nExperimental: ") == len(experimental_ids(doc))
    for other in doc["harnesses"]:
        if other["id"] not in experimental_ids(doc) and other.get("detect"):
            assert f"| {other['name']} (`{other['id']}`) | - |" in md
