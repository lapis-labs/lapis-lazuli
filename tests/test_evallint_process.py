"""tools/eval/run.py: a Codex process that has ended but was not collected yet (a zombie) does not block
`--resume`, and a group that outlived its leader is named by the kill command the refusal suggests."""
import os
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from evallint_support import evalkit, load

run = load("run")
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX processes")


def state_of(pid: int) -> str:
    return subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()[:1]


def ended_but_not_collected(argv, **kwargs) -> subprocess.Popen:
    """A child that has exited and is still in the process table (state Z): nothing collects it here."""
    child = subprocess.Popen(argv, **kwargs)
    deadline = time.monotonic() + 30
    while state_of(child.pid) != "Z":
        assert time.monotonic() < deadline, "the child did not end"
        time.sleep(0.02)
    return child


def test_a_process_that_has_ended_but_is_not_collected_is_not_alive():
    child = ended_but_not_collected([sys.executable, "-c", "pass"])
    try:
        os.kill(child.pid, 0)                      # the table still has it: a plain signal check says "alive"
        assert run.live_target(child.pid) is None and run.pid_alive(child.pid) is False
    finally:
        child.wait()


def test_a_running_process_is_alive_until_it_ends():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert run.live_target(child.pid) == "process" and run.pid_alive(child.pid)
    finally:
        child.kill()
        child.wait()
    assert run.live_target(child.pid) is None


def test_a_group_that_outlived_its_leader_is_alive_and_resume_names_the_group_kill(tmp_path):
    leader = ended_but_not_collected(["sh", "-c", "sleep 300 & exit 0"], start_new_session=True)
    try:
        assert run.live_target(leader.pid) == "group" and run.pid_alive(leader.pid)
        out = tmp_path / "out"
        evalkit.write_json(out / "runs" / "t.r1.with" / "run.json", {"status": "running", "pid": leader.pid})
        args = SimpleNamespace(model=None, effort=None, sandbox=None, network=None)
        with pytest.raises(evalkit.KitError) as refused:
            run._check_resume(args, {}, out, [{"id": "t.r1.with"}])
        assert f"kill -- -{leader.pid}" in str(refused.value) and "kill %d)" % leader.pid not in str(refused.value)
    finally:
        os.killpg(leader.pid, signal.SIGKILL)
        leader.wait()


def test_resume_names_a_plain_kill_while_the_process_itself_runs(tmp_path):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        out = tmp_path / "out"
        evalkit.write_json(out / "runs" / "t.r1.with" / "run.json", {"status": "running", "pid": child.pid})
        args = SimpleNamespace(model=None, effort=None, sandbox=None, network=None)
        with pytest.raises(evalkit.KitError, match=r"\(kill %d\)" % child.pid):
            run._check_resume(args, {}, out, [{"id": "t.r1.with"}])
    finally:
        child.kill()
        child.wait()


def test_the_process_table_reads_proc_state_and_group_even_when_the_command_name_holds_parentheses(tmp_path):
    proc = tmp_path / "proc"
    for pid, line in {
        "self": "42 (python) R 1 42 42 0 -1 4194560 100 0 0 0",
        "100": "100 (sh) Z 1 100 100 0 -1 4194560 0 0 0 0",
        "101": "101 (a) b) c) S 100 100 100 0 -1 4194560 0 0 0 0",       # a name with spaces and a closing parenthesis
        "junk": "not a process",
    }.items():
        (proc / pid).mkdir(parents=True)
        (proc / pid / "stat").write_text(line)
    assert sorted(run._process_table(proc)) == [(100, 100, "Z"), (101, 100, "S")]
