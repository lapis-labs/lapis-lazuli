"""The page the owner is asked to open: `next` does not wait on a link that answers nothing, `preview start` keeps a
server alive after the command (and the process group) that started it, and the owner block lists the captures and a
file that open without a server."""
from __future__ import annotations

import contextlib
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from lapis_design import draft, local_site, next_step, owner, preview
from procedure_support import TASK, ask, make_project, save, unseal_slice

pytestmark = pytest.mark.usefixtures("real_previews")            # these tests mean what `preview.answers` says
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="process groups and sessions are POSIX")
CLI = [sys.executable, "-m", "lapis_design.cli", "preview"]


@contextlib.contextmanager
def serving(folder: Path, port: int = 0):
    """`folder` on 127.0.0.1 for the length of the block, as the server of `preview start` serves it."""
    server = local_site._Server(folder.resolve(), port)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    worker.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.fixture
def site(tmp_path) -> Path:
    folder = tmp_path / "site"
    folder.mkdir()
    (folder / "slice.html").write_text("<!doctype html><title>slice</title><p>A first view</p>", encoding="utf-8")
    return folder


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    """An attended create run whose owner has not approved a slice; the step after the slice does not show."""
    for name in ("LAPIS_UNATTENDED", "LAPIS_TASK", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAZULI_DB", "")
    (tmp_path / "project").mkdir()
    root = make_project(tmp_path / "project")
    unseal_slice(root)
    (root / ".lapis/fonts.lock.json").unlink()
    monkeypatch.setattr(draft, "check", lambda root, task, *, asked=None: ([], []))   # `draft check` has its own tests
    return root


# ---- 1. `next` and a link that is dead

def test_next_does_not_wait_on_a_link_that_answers_nothing_and_waits_once_it_answers(project, site):
    with serving(site) as port:
        pass                                                      # the port of a server that has since gone away
    url = f"http://127.0.0.1:{port}/slice.html"
    ask(project, f"Approve this slice? {url}", 200)
    result = next_step.evaluate(project, TASK)
    assert (result["state"], result["step"]["id"]) == ("needs-step", "draft-review")
    assert result["step"]["command"] == f"lapis-design preview start --task {TASK} --port {port}"
    assert url in result["step"]["why"] and "HTTP 200" in result["step"]["why"] and "outlives this turn" in result["step"]["why"]
    with serving(site, port):
        again = next_step.evaluate(project, TASK)
        assert (again["state"], again["then"]["id"]) == ("waiting-for-user", "slice")


def test_a_link_that_answers_something_but_not_200_is_not_a_wait_either(project, site):
    with serving(site) as port:
        url = f"http://127.0.0.1:{port}/not-there.html"
        ask(project, f"Approve this slice? {url}", 200)
        result = next_step.evaluate(project, TASK)
        assert (result["state"], result["step"]["id"]) == ("needs-step", "draft-review")
        assert url in result["step"]["why"]


def test_a_question_that_links_no_address_of_this_computer_is_not_asked_whether_it_answers(project):
    ask(project, "Approve this slice? ./slice.html and https://example.com/inspiration", 200)
    assert preview.unreachable(["./slice.html", "https://example.com/inspiration"]) == []
    assert next_step.evaluate(project, TASK)["state"] == "waiting-for-user"


def test_unreachable_names_the_dead_loopback_addresses_in_order(site):
    with serving(site) as port:
        live = f"http://127.0.0.1:{port}/slice.html"
        missing = f"http://127.0.0.1:{port}/missing.html"
    assert preview.unreachable([live, "https://example.com/", missing]) == [live, missing]
    with serving(site, port):
        assert preview.answers(live) and preview.unreachable([live]) == [] and not preview.answers(missing)


# ---- 2. a preview server that outlives the turn

def start_in_a_group(root: Path, *more: str) -> subprocess.Popen:
    """`preview start` as a harness runs a command: in a process group of its own, followed by more work that keeps
    the group alive until the harness ends it."""
    command = shlex.join([*CLI, "start", "--task", TASK, "--root", str(root), *more])
    return subprocess.Popen(["sh", "-c", f"{command} > /dev/null; sleep 60"], start_new_session=True)


def wait_for(condition, seconds: float = 20.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if found := condition():
            return found
        time.sleep(0.1)
    raise AssertionError("timed out")


@POSIX_ONLY
def test_a_preview_server_keeps_answering_after_its_command_and_that_commands_process_group_are_ended(tmp_path, site):
    root = tmp_path / "project"
    root.mkdir()
    group = start_in_a_group(root, "--dir", str(site))
    try:
        rec = wait_for(lambda: preview.record(root, TASK))
        url = f"http://127.0.0.1:{rec['port']}/slice.html"
        wait_for(lambda: preview.answers(url))
        assert os.getsid(rec["pid"]) != os.getsid(group.pid) and os.getpgid(rec["pid"]) != group.pid
        os.killpg(group.pid, signal.SIGKILL)                      # the harness cleans up after the command
        group.wait()
        assert preview.answers(url) and Path(rec["dir"]) == site.resolve()
        status = subprocess.run([*CLI, "status", "--task", TASK, "--root", str(root)], capture_output=True, text=True)
        assert status.returncode == 0 and json.loads(status.stdout)["running"] is True
    finally:
        subprocess.run([*CLI, "stop", "--task", TASK, "--root", str(root)], capture_output=True, text=True)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(group.pid, signal.SIGKILL)
    assert not preview.answers(url)
    assert preview.record(root, TASK) is None
    assert subprocess.run([*CLI, "status", "--task", TASK, "--root", str(root)], capture_output=True).returncode == 1


@POSIX_ONLY
def test_starting_again_keeps_a_server_that_answers_and_serves_the_same_port_again_after_it_died(tmp_path, site):
    root = tmp_path / "project"
    root.mkdir()

    def start() -> dict:
        done = subprocess.run([*CLI, "start", "--task", TASK, "--root", str(root), "--dir", str(site)],
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    first = start()
    try:
        again = start()
        assert (again["pid"], again["port"], again["started"]) == (first["pid"], first["port"], False)
        os.kill(first["pid"], signal.SIGKILL)                     # the server died between two turns
        wait_for(lambda: not preview.answers(first["url"] + "slice.html"))
        revived = start()
        assert revived["port"] == first["port"] and revived["pid"] != first["pid"] and revived["started"] is True
        assert preview.answers(first["url"] + "slice.html")      # the addresses of the draft record are true again
    finally:
        subprocess.run([*CLI, "stop", "--task", TASK, "--root", str(root)], capture_output=True, text=True)


@POSIX_ONLY
def test_stop_never_signals_a_process_that_is_not_a_preview_server(tmp_path, site):
    root = tmp_path / "project"
    root.mkdir()
    bystander = subprocess.Popen(["sleep", "60"])
    try:
        with serving(site) as port:                               # something of ours answers on the recorded port
            target = preview.path(root, TASK)
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({"pid": bystander.pid, "port": port, "dir": str(site)}), encoding="utf-8")
            assert preview.stop(root, TASK) == (f"process {bystander.pid}, recorded for {TASK}, is not a preview server, "
                                                "so nothing was signalled")
        assert bystander.poll() is None and not target.exists()
        assert preview.stop(root, TASK) == f"no preview is recorded for {TASK}"
    finally:
        bystander.kill()
        bystander.wait()


def test_start_names_a_port_that_is_taken_and_a_folder_that_is_not_one(tmp_path, site):
    with serving(site) as port:
        taken = subprocess.run([*CLI, "start", "--task", TASK, "--root", str(tmp_path), "--dir", str(site),
                                "--port", str(port)], capture_output=True, text=True)
        assert taken.returncode == 1 and f"port {port} is in use" in taken.stderr
    missing = subprocess.run([*CLI, "start", "--task", TASK, "--root", str(tmp_path), "--dir", str(tmp_path / "nope")],
                             capture_output=True, text=True)
    assert missing.returncode == 1 and "is not a folder" in missing.stderr
    assert preview.record(tmp_path, TASK) is None


# ---- 3. the owner block lists what opens without a server

def shot(folder: Path, name: str, width: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width // 10, 40), "white").save(folder / name)


def shown_page(root: Path, *, html: str, sources: tuple[str, ...] = ("index.html", "styles.css"), more: dict | None = None):
    """A draft record of one shown page, its extract with a screenshot at each shown width, and the page's files."""
    (root / "index.html").write_text(html, encoding="utf-8")
    (root / "styles.css").write_text("body { margin: 0; background: url(img/paper.png); }", encoding="utf-8")
    (root / "app.js").write_text("document.title = 'Kiln shop';", encoding="utf-8")
    for width in (390, 1440):
        shot(root / ".lapis/renders/shown.shots", f"{width}.png", width)
    shot(root / ".lapis/renders/shown.shots", "1440-dark.png", 1440)
    save(root, "renders/shown.narrow.json", {"version": 1, "viewports": [
        {"width": 1440, "theme": "dark", "screenshot": "shown.shots/1440-dark.png", "boxes": []},
        {"width": 1440, "theme": "light", "screenshot": "shown.shots/1440.png", "boxes": []},
        {"width": 390, "theme": "light", "screenshot": "shown.shots/390.png", "boxes": []},
        {"width": 768, "theme": "light", "screenshot": "shown.shots/768.png", "boxes": []}]})
    save(root, f"drafts/{TASK}.yaml", {"version": 1, "task": TASK, "pages": [
        {"url": "http://127.0.0.1:8765/index.html", "direction": "new", "widths": [390, 1440], "sources": list(sources),
         "review": {"extracts": [".lapis/renders/shown.narrow.json"]}, **(more or {})}]})


PLAIN = ('<!doctype html><link rel="stylesheet" href="styles.css"><script src="app.js"></script>'
         '<h1>Kiln shop</h1><a href="#log">Firing log</a>')


def shown_lines(root: Path) -> list[str]:
    text, _ = owner.block(root, TASK)
    lines = text.splitlines()
    start = lines.index("## What was shown")
    return lines[start + 1:lines.index("", start)]


def test_the_block_lists_the_screenshots_of_the_shown_widths_and_the_page_that_opens_without_a_server(project):
    shown_page(project, html=PLAIN, sources=("index.html", "styles.css", "app.js"))
    assert shown_lines(project) == [
        "- http://127.0.0.1:8765/index.html at 390, 1440; document height at 1440: not measured",
        "  - captures, which open without a server: .lapis/renders/shown.shots/390.png, .lapis/renders/shown.shots/1440.png",
        "  - the page as a file, which opens without a server: index.html"]
    text, _ = owner.block(project, TASK)
    assert str(project) not in text                               # the same files give the same digest anywhere


@pytest.mark.parametrize("html, js", [
    ('<link rel="stylesheet" href="/styles.css"><h1>Kiln shop</h1>', "document.title = 'x';"),          # from the site root
    ('<script type="module" src="app.js"></script><h1>Kiln shop</h1>', "document.title = 'x';"),        # a module script
    ('<script src="app.js"></script><h1>Kiln shop</h1>', "fetch('stock.json').then(r => r.json());"),   # a request of its own
    ('<script src="app.js"></script><h1>Kiln shop</h1>', "import { open } from './dialog.js';"),        # an import
    ('<h1>Kiln shop</h1><img src="/img/kiln.png" alt="">', "document.title = 'x';"),
], ids=["root-absolute", "module", "fetch", "import", "root-image"])
def test_a_page_that_needs_a_server_is_not_offered_as_a_file_but_its_captures_still_are(project, html, js):
    shown_page(project, html=html, sources=("index.html", "styles.css", "app.js"))
    (project / "app.js").write_text(js, encoding="utf-8")
    lines = shown_lines(project)
    assert len(lines) == 2 and lines[1].startswith("  - captures, which open without a server: ")
    assert not any("the page as a file" in line for line in lines)


def test_no_line_is_made_up_for_captures_that_are_not_files_or_a_page_the_project_does_not_hold(project):
    shown_page(project, html=PLAIN)
    for name in (project / ".lapis/renders/shown.shots").iterdir():
        name.unlink()
    (project / "index.html").unlink()
    assert shown_lines(project) == ["- http://127.0.0.1:8765/index.html at 390, 1440; document height at 1440: not measured"]
