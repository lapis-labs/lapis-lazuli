"""The preview: a page the owner is asked to open answers when the question is shown, and a server it needs outlives
the turn that started it.

`lapis-design preview start --task T [--dir DIR] [--port N]` serves DIR (the project folder by default) on 127.0.0.1
with the read-only server of `local_site`, in a process of its own: a new session on POSIX, a detached process on
Windows, no terminal input, its output in `.lapis/preview/T.log`. A harness that ends a turn by ending the shell
command that started a server, or that command's process group, does not end this one. The process and the address
are recorded in `.lapis/preview/T.json` (`pid`, `port`, `dir`); a later `start` serves the same port again, so the
addresses of the draft record stay true, and `stop` ends the recorded process. `status` says whether it answers. The
server names its own process id in its `Server` header, which is how `stop` and `status` know the recorded process
from another one that took its id; no process table is read (`ps` cuts a long command line at the terminal width).

`answers(url)` is what `next` asks of every address the approval questions link: one GET, no proxy, that returns HTTP
200. A question whose link does not answer is not a wait (`next_step`), so the owner is not sent to a dead address.
A server cannot be known to survive the turn from inside it, which is why the owner block also lists the capture
files and a file to open without a server (`owner.py`).
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlsplit

from lapis_design import local_site

SERVER_NAME = local_site.SERVER_NAME                       # the `Server` header's first word names our server
LOOPBACK = ("localhost", "127.0.0.1", "::1")
TIMEOUT_S = 3.0                                            # one probe; a refused connection answers at once
READY_S = 10.0                                             # how long `start` waits for the new server
STOP_S = 3.0


class PreviewError(RuntimeError):
    """The preview cannot be started or stopped; the message says why."""


def path(root: Path, task: str) -> Path:
    return root / ".lapis" / "preview" / f"{task}.json"


def log_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "preview" / f"{task}.log"


def url_of(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def record(root: Path, task: str) -> dict | None:
    """The recorded preview of `task`, or None when none is recorded or the file is not a record."""
    try:
        found = json.loads(path(root, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok = (isinstance(found, dict) and isinstance(found.get("pid"), int) and isinstance(found.get("port"), int)
          and isinstance(found.get("dir"), str) and not isinstance(found["pid"], bool))
    return found if ok else None


# ---------------------------------------------------------------- asking an address

def _opener() -> urllib.request.OpenerDirector:
    """No proxy, and no certificate check: the question is whether anything answers on this computer, not whom."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))


def _fetch(url: str, timeout: float) -> tuple[int, str] | None:
    """The status and the `Server` header one GET of `url` gets, or None when nothing answers."""
    request = urllib.request.Request(url, headers={"User-Agent": "lapis-design preview"})
    try:
        with _opener().open(request, timeout=timeout) as response:
            return response.status, response.headers.get("Server", "")
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.headers.get("Server", "") if exc.headers else "")
    except (OSError, ValueError, http.client.HTTPException):          # refused, timed out, not an address
        return None


def answers(url: str, timeout: float = TIMEOUT_S) -> bool:
    """Whether a GET of `url` ends in HTTP 200."""
    found = _fetch(url, timeout)
    return found is not None and found[0] == 200


def unreachable(urls: Iterable[str]) -> list[str]:
    """The loopback http(s) addresses among `urls` that do not answer HTTP 200 now, in order. Anything else a question
    names (a file path, a host that is not this computer) is not asked."""
    dead = []
    for url in urls:
        parts = urlsplit(url)
        if parts.scheme in ("http", "https") and parts.hostname in LOOPBACK and not answers(url):
            dead.append(url)
    return dead


def command(task: str, dead: list[str]) -> str:
    """The command that serves the project folder again on the port of the first dead address that names one."""
    port = next((p for p in map(_port, dead) if p), None)
    return f"lapis-design preview start --task {task}" + (f" --port {port}" if port else "")


def _port(url: str) -> int | None:
    try:
        return urlsplit(url).port
    except ValueError:
        return None


def why(task: str, dead: list[str]) -> str:
    return ("The questions link " + ", ".join(dead) + (", which does" if len(dead) == 1 else ", which do")
            + " not answer HTTP 200 now, so the owner would open a dead link. Serve the page so the server outlives "
            f"this turn with `{command(task, dead)}` (it detaches the server, records it in .lapis/preview/{task}.json, "
            f"and prints the address; `lapis-design preview stop --task {task}` ends it), or start your own server the "
            f"same way, then run `lapis-design next --task {task}` again. The pasted owner block lists the capture "
            "files, which need no server.")


# ---------------------------------------------------------------- the server process

def _reported_pid(header: str) -> int | None:
    """The process id a preview server names in its `Server` header (`lapis-local-site/pid-<pid> Python/...`), else None."""
    found = re.match(re.escape(SERVER_NAME) + r"/pid-(\d+)(?:\s|$)", header)
    return int(found.group(1)) if found else None


def _server_pid(port: int, timeout: float = TIMEOUT_S) -> int | None:
    """The process id of the preview server that answers on `port` now, or None when nothing of ours does."""
    found = _fetch(url_of(port), timeout)
    return _reported_pid(found[1]) if found is not None else None


def _alive(rec: Mapping) -> bool:
    """Whether the recorded port is answered by the recorded process. The process says who it is over HTTP, so no
    process table is read: `ps` cuts a long command line at the terminal width (COLUMNS), and a reused process id
    answers nothing."""
    return _server_pid(rec["port"]) == rec["pid"]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _busy(port: int) -> bool:
    """Whether something listens on `port`. A closed connection's TIME_WAIT is not that: the server reuses the address."""
    with socket.socket() as probe:
        if os.name != "nt":                  # on Windows the option would let the probe bind beside a listener
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return True
        return False


def _spawn(folder: Path, port: int, log: Path) -> subprocess.Popen:
    log.parent.mkdir(parents=True, exist_ok=True)
    detach: dict = ({"creationflags": 0x00000008 | 0x00000200 | 0x08000000} if os.name == "nt"   # DETACHED_PROCESS,
                    else {"start_new_session": True})                      # CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW
    with log.open("wb") as out:
        return subprocess.Popen([sys.executable, "-m", "lapis_design.preview", "--dir", str(folder), "--port", str(port)],
                                stdin=subprocess.DEVNULL, stdout=out, stderr=out, close_fds=True, **detach)


def _tail(log: Path) -> str:
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        return ""
    return " ".join(lines[-3:])


def start(root: Path, task: str, directory: Path | None = None, port: int | None = None) -> dict:
    """Serve `directory` (default: `root`) for `task` and record it. A preview that already answers for the same folder
    and port is kept as it is. Returns `{"task", "url", "pid", "port", "dir", "started"}`."""
    root = Path(root).resolve()
    folder = (directory or root).resolve()
    if not folder.is_dir():
        raise PreviewError(f"{folder} is not a folder")
    kept = record(root, task)
    if kept is not None and _alive(kept):
        if Path(kept["dir"]) == folder and port in (None, kept["port"]):
            return {"task": task, "url": url_of(kept["port"]), **kept, "started": False}
        stop(root, task)
    chosen = port if port is not None else (kept["port"] if kept and not _busy(kept["port"]) else _free_port())
    if _busy(chosen):
        raise PreviewError(f"port {chosen} is in use; name another with --port")
    log = log_path(root, task)
    process = _spawn(folder, chosen, log)
    deadline = time.monotonic() + READY_S
    reported = None
    while time.monotonic() < deadline:
        reported = _server_pid(chosen, 1.0)
        if process.poll() is None and reported is not None:
            break
        if process.poll() is not None:
            raise PreviewError(f"the preview server stopped at once (exit {process.returncode}): {_tail(log)}")
        time.sleep(0.1)
    else:
        process.terminate()
        raise PreviewError(f"the preview server did not answer within {READY_S:g} s: {_tail(log)}")
    rec = {"pid": reported, "port": chosen, "dir": str(folder)}   # the pid it names: a venv launcher's child is not process.pid
    target = path(root, task)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return {"task": task, "url": url_of(chosen), **rec, "started": True}


def stop(root: Path, task: str) -> str:
    """End the recorded preview of `task` and forget it. Only the process that answers on the recorded port as the
    recorded pid is signalled, never a process id that was reused; the record is dropped either way. Returns what
    happened."""
    root = Path(root).resolve()
    rec = record(root, task)
    if rec is None:
        return f"no preview is recorded for {task}"
    outcome = f"the preview of {task} was not running"
    found = _fetch(url_of(rec["port"]), TIMEOUT_S)
    if found is not None and found[1].startswith(SERVER_NAME):
        if _reported_pid(found[1]) != rec["pid"]:
            outcome = (f"the server on port {rec['port']} is not process {rec['pid']}, recorded for {task}, so nothing "
                       "was signalled")
        else:
            try:
                os.kill(rec["pid"], signal.SIGTERM)
            except OSError:
                pass
            deadline = time.monotonic() + STOP_S
            while time.monotonic() < deadline and _alive(rec):
                time.sleep(0.1)
            outcome = f"the preview of {task} was stopped"
    try:
        path(root, task).unlink()
    except OSError:
        pass
    return outcome


def main(argv: list[str] | None = None, prog: str = "lapis-design preview serve") -> int:
    verb = prog.rsplit(" ", 1)[-1]
    ap = argparse.ArgumentParser(prog=prog, description=__doc__)
    if verb == "serve":                       # the detached process `start` spawns: `python -m lapis_design.preview`
        ap.add_argument("--dir", type=Path, required=True)
        ap.add_argument("--port", type=int, required=True)
        args = ap.parse_args(argv)
        local_site._Handler.server_version = f"{SERVER_NAME}/pid-{os.getpid()}"   # how `stop` and `status` know this process
        server = local_site._Server(args.dir.resolve(), args.port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    ap.add_argument("--task", required=True)
    ap.add_argument("--root", type=Path, default=Path("."), help="the project folder (default: .)")
    if verb == "start":
        ap.add_argument("--dir", type=Path, help="the folder to serve (default: the project folder)")
        ap.add_argument("--port", type=int, help="the port (default: the recorded one, else a free one)")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    try:
        if verb == "start":
            print(json.dumps(start(root, args.task, args.dir, args.port), indent=2))
            return 0
        if verb == "stop":
            print(stop(root, args.task))
            return 0
    except PreviewError as exc:
        print(f"lapis-design preview: {exc}", file=sys.stderr)
        return 1
    rec = record(root, args.task)
    running = rec is not None and _alive(rec)
    print(json.dumps({"task": args.task, "running": running,
                      **({"url": url_of(rec["port"]), **rec} if rec else {})}, indent=2))
    return 0 if running else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
