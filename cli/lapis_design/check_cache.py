"""One browser run per build and state: the identity of what a check loads, a stored result per identity, and a lock
that makes concurrent identical checks share one run.

A check of a page we serve ourselves (a local HTML file, or a folder `preview start` serves) runs against a tree of
files. Its result is a function of that tree, the request (path, query, widths, contexts, probes), the inputs the run
reads (plan, stub, values), the day, and the tool, so those make the key:

  build id   a hash of every file the server would answer for under the served folder: HTML, CSS, scripts, fonts,
             images. A hash of the HTML alone misses all of them.
  state key  the build id with the rest of the request, and the tool.

A key that cannot be established (an address we do not serve, a folder too large to hash, a backend we do not run) is
`None`: the check runs as it always did and the cache is `off`. A run whose page asked another origin for anything, or
whose tree changed while it ran, is not stored.

Stored results live under `.lapis/cache/checks/<kind>-<state key>/` and are copied back to the report path the check
was asked to write, so release and critic read the same files at the same paths. The report path is rewritten on a
reuse, as a rerun would, so freshness by modification time behaves as it does after a run.
"""
from __future__ import annotations

import contextlib
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import cache
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlsplit

from lapis_design import __version__, local_site, shared_dir

CACHE_DIR = Path(".lapis") / "cache" / "checks"
MAX_FILES = 20000                  # a served folder with more files, or more bytes, has no cheap identity: cache off
MAX_BYTES = 512 * 1024 * 1024
KEEP = {"render": 4, "behavior": 6, "lint": 6}
HEARTBEAT_S = 5.0                  # a holder touches its lock this often
STALE_S = 60.0                     # a lock untouched this long has no live holder, whatever its process id says
WIDTHS = (320, 390, 768, 1440)
LOOPBACK = ("127.0.0.1", "localhost", "[::1]")


# ---------------------------------------------------------------- the served tree

def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                                     default=str).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def tree_manifest(folder: Path) -> dict[str, str] | None:
    """`{relative path: sha256}` of every file the local server answers for under `folder`; None when the tree has
    too many files or bytes to hash on every check (the check then runs without a cache)."""
    found: list[tuple[str, Path]] = []
    total = 0
    for relative, real in local_site.served_files(folder):       # sizes first: a tree over the limits is not hashed at all
        try:
            total += real.stat().st_size
        except OSError:
            return None
        if len(found) >= MAX_FILES or total > MAX_BYTES:
            return None
        found.append((relative, real))
    manifest: dict[str, str] = {}
    for relative, real in found:
        digest = file_sha256(real)
        if digest is None:
            return None
        manifest[relative] = digest
    return manifest


def build_id(manifest: dict[str, str]) -> str:
    return _digest(manifest)[:16]


@dataclass(frozen=True)
class Served:
    """A page whose files we serve: the folder, the request path with its query, and the tree as hashed."""
    folder: Path
    request: str
    manifest: dict[str, str]
    css: dict[str, list]

    @property
    def build_id(self) -> str:
        return build_id(self.manifest)


def _preview_folder(url: str, project: Path) -> tuple[Path, str] | None:
    """`(folder, request)` when `url` is on the port of a preview `lapis-design preview start` recorded and that server
    still answers as the recorded process; None for any other address."""
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost") or parts.port is None:
        return None
    from lapis_design import preview

    folder = project / ".lapis" / "preview"
    if not folder.is_dir():
        return None
    for record_path in sorted(folder.glob("*.json")):
        record = preview.record(project, record_path.stem)
        if record is not None and record["port"] == parts.port and preview._alive(record):
            return Path(record["dir"]), parts.path + (f"?{parts.query}" if parts.query else "")
    return None


def served(target: str, project: Path) -> Served | None:
    """The identity of `target` (a path, a `file:` URL, or a URL of a preview we run), or None when we do not serve it."""
    found = local_site.served_target(target)
    if found is not None:
        folder, name, query = found
        request = "/" + name + (f"?{query}" if query else "")
    else:
        previewed = _preview_folder(target, project)
        if previewed is None:
            return None
        folder, request = previewed
    manifest = tree_manifest(folder)
    if manifest is None:
        return None
    return Served(folder, request, manifest, css_signatures(folder, manifest))


# ---------------------------------------------------------------- what a stylesheet change can reach

def _statements(text: str) -> list[str]:
    """The top-level rules and at-rules of a stylesheet, comments removed and whitespace collapsed."""
    out: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    end = len(text)
    while index < end:
        char = text[index]
        if text.startswith("/*", index):
            close = text.find("*/", index + 2)
            index = end if close < 0 else close + 2
            current.append(" ")
            continue
        if char in "\"'":
            quote, start = char, index
            index += 1
            while index < end and text[index] != quote:
                index += 2 if text[index] == "\\" else 1
            index += 1
            current.append(text[start:index])
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(depth - 1, 0)
            if depth == 0:
                current.append(char)
                out.append(" ".join("".join(current).split()))
                current = []
                index += 1
                continue
        elif char == ";" and depth == 0:
            current.append(char)
            out.append(" ".join("".join(current).split()))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    if (rest := " ".join("".join(current).split())):
        out.append(rest)
    return out


_LENGTH = re.compile(r"^\(\s*(min|max)-width\s*:\s*([0-9]*\.?[0-9]+)\s*(px|em|rem)\s*\)$", re.I)


def media_widths(condition: str) -> frozenset[int] | None:
    """The capture widths a top-level `@media` condition can match: a comma list of `[only] screen|all and (min-width: N)
    and (max-width: N)` terms in px, em, or rem. None when it cannot be proven (any other feature, `not`, a range
    syntax): the block is then taken to reach every width."""
    matched: set[int] = set()
    for part in condition.split(","):
        low, high = 0.0, float("inf")
        for term in re.split(r"\s+and\s+", part.strip(), flags=re.I):
            term = re.sub(r"^only\s+", "", term.strip(), flags=re.I)
            if term.lower() in ("screen", "all"):
                continue
            found = _LENGTH.match(term)
            if not found:
                return None
            size = float(found.group(2)) * (1 if found.group(3).lower() == "px" else 16)
            if found.group(1).lower() == "min":
                low = max(low, size)
            else:
                high = min(high, size)
        matched.update(width for width in WIDTHS if low <= width <= high)
    return frozenset(matched)


def stylesheet_signature(text: str) -> list[list]:
    """One `[condition, sha256]` per top-level statement: `condition` is the width set of a plain `@media` block as a
    sorted list, or None for every other statement (a rule, `@font-face`, `@supports`, `@import`, a custom property:
    all of them can reach any width)."""
    out = []
    for statement in _statements(text):
        widths = None
        if statement[:6].lower() == "@media" and "{" in statement:
            found = media_widths(statement[6:statement.index("{")].strip())
            widths = None if found is None else sorted(found)
        out.append([widths, hashlib.sha256(statement.encode("utf-8")).hexdigest()])
    return out


def css_signatures(folder: Path, manifest: dict[str, str]) -> dict[str, list]:
    signatures: dict[str, list] = {}
    for relative in manifest:
        if relative.lower().endswith(".css"):
            with contextlib.suppress(OSError, UnicodeDecodeError):
                signatures[relative] = stylesheet_signature((folder / relative).read_text(encoding="utf-8"))
                continue
            signatures[relative] = [[None, manifest[relative]]]       # unreadable as text: any width
    return signatures


def affected_widths(before: dict, after: Served) -> tuple[frozenset[int] | None, str]:
    """`(widths, why)`: the capture widths a change since `before` (a stored entry's meta) can reach. An empty set
    when the tree is the same, or when every changed statement is an `@media` block no capture width matches; a set
    of widths when the only files that differ are stylesheets and every changed statement is an `@media` block
    bounded by widths; None (every width) for anything else. None is the answer whenever the dependency cannot be
    proven: a changed page, script, font, or image, or a stylesheet rule outside a width query."""
    old, new = before.get("tree") or {}, after.manifest
    changed = sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))
    if not changed:
        return frozenset(), "no served file changed"
    reached: set[int] = set()
    structural = False
    for name in changed:
        if not name.lower().endswith(".css") or name not in old or name not in new:
            return None, f"{name} changed, and only a stylesheet's width-bounded @media blocks can be tied to widths"
        before_signature = (before.get("css") or {}).get(name)
        after_signature = after.css.get(name)
        if before_signature is None or after_signature is None:
            return None, f"{name} changed and has no stored stylesheet signature"
        matcher = difflib.SequenceMatcher(None, [row[1] for row in before_signature],
                                          [row[1] for row in after_signature], autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            structural = True
            for row in (*before_signature[i1:i2], *after_signature[j1:j2]):
                if row[0] is None:
                    return None, f"{name} changed outside a width-bounded @media block (it can reach every width)"
                reached.update(row[0])
    if not structural:
        return frozenset(), f"{', '.join(changed[:3])} changed only in comments or whitespace"
    return frozenset(reached), f"{', '.join(changed[:3])} changed only inside width-bounded @media blocks"


# ---------------------------------------------------------------- keys

@cache
def tool_digest() -> str:
    """Hash of the CLI's own code and the packaged contracts: a change to either invalidates every stored result."""
    digest = hashlib.sha256(__version__.encode())
    package = Path(__file__).parent
    for root in (package, shared_dir()):
        for path in sorted(root.rglob("*")):
            if path.suffix in (".py", ".yaml", ".json", ".md") and "__pycache__" not in path.parts and path.is_file():
                digest.update(path.relative_to(root).as_posix().encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _playwright_version() -> str:
    from importlib import metadata

    try:
        return metadata.version("playwright")
    except metadata.PackageNotFoundError:
        return "none"


@dataclass(frozen=True)
class Key:
    kind: str
    build_id: str
    state_key: str                  # 32 hex: names the stored entry
    params: dict                    # the request, without the tree, the day, and the widths or contexts selected
    selection: object               # the widths, contexts, and probes selected
    served: Served | None = None


def make_key(kind: str, served_page: Served, params: dict, selection: object = None) -> Key:
    """The key of a browser check: the served tree, the request, what the run selects, the day, the tool, the browser."""
    fixed = {**params, "page": served_page.request, "tool": tool_digest(), "playwright": _playwright_version(),
             "platform": sys.platform}
    whole = {"kind": kind, "tree": served_page.build_id, "params": fixed, "selection": selection,
             "day": date.today().isoformat()}
    return Key(kind, served_page.build_id, _digest(whole)[:32], fixed, selection, served_page)


def file_params(**paths: Path | None) -> dict:
    """`name: {path, sha256}` for each input file a check reads, so editing one changes the key."""
    out: dict = {}
    for name, path in paths.items():
        if path is not None:
            out[name] = {"path": path.as_posix(), "sha256": file_sha256(path)}
    return out


# ---------------------------------------------------------------- entries

def _root(project: Path) -> Path:
    return project / CACHE_DIR


def _entry(project: Path, key: Key) -> Path:
    return _root(project) / f"{key.kind}-{key.state_key}"


def _load_meta(entry: Path) -> dict | None:
    try:
        meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) and (entry / "report.json").is_file() else None


def _copy_report(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _replace_dir(source: Path, destination: Path) -> None:
    temporary = destination.with_name(f"{destination.name}.{os.getpid()}.tmp")
    shutil.rmtree(temporary, ignore_errors=True)
    shutil.copytree(source, temporary)
    shutil.rmtree(destination, ignore_errors=True)
    os.replace(temporary, destination)


def _restore(entry: Path, out: Path, shots: Path | None) -> bool:
    """Copy the stored report (and screenshots) to where the check writes them. False when the entry is incomplete."""
    stored_shots = entry / "shots"
    if shots is not None and not stored_shots.is_dir():
        return False
    _copy_report(entry / "report.json", out)
    if shots is not None:
        _replace_dir(stored_shots, shots)
    return True


def _index_path(project: Path, out: Path) -> Path:
    return _root(project) / "index" / (hashlib.sha1(str(out.resolve()).encode()).hexdigest()[:20] + ".json")


def _store(project: Path, key: Key, out: Path, shots: Path | None, run_seconds: float) -> None:
    root = _root(project)
    entry = _entry(project, key)
    temporary = root / f"{entry.name}.{os.getpid()}.tmp"
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True)
    try:
        shutil.copyfile(out, temporary / "report.json")
        if shots is not None and shots.is_dir():
            shutil.copytree(shots, temporary / "shots")
        meta = {"kind": key.kind, "state_key": key.state_key, "build_id": key.build_id, "params": key.params,
                "selection": key.selection, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "run_seconds": round(run_seconds, 2), "out_name": out.name,
                "report_sha256": file_sha256(out), "tree": key.served.manifest if key.served else None,
                "css": key.served.css if key.served else None}
        (temporary / "meta.json").write_text(json.dumps(meta, ensure_ascii=False) + "\n", encoding="utf-8")
        shutil.rmtree(entry, ignore_errors=True)
        os.replace(temporary, entry)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    note_report(project, key, out)
    _prune(project, key.kind, keep_name=entry.name)


def note_report(project: Path, key: Key, out: Path) -> None:
    """Remember which stored entry the report at `out` came from, so a later `--changed-since` can find its tree."""
    path = _index_path(project, out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entry": f"{key.kind}-{key.state_key}", "out": out.as_posix(),
                                "report_sha256": file_sha256(out)}) + "\n", encoding="utf-8")


def _prune(project: Path, kind: str, *, keep_name: str) -> None:
    root = _root(project)
    referenced = set()
    for index in (root / "index").glob("*.json"):
        with contextlib.suppress(OSError, ValueError):
            referenced.add(json.loads(index.read_text(encoding="utf-8")).get("entry"))
    entries = []
    for path in root.glob(f"{kind}-*"):
        if path.is_dir() and not path.name.endswith(".tmp"):
            meta = _load_meta(path) or {}
            entries.append((meta.get("created") or "", path))
    entries.sort(reverse=True)
    for _, path in entries[KEEP.get(kind, 6):]:
        if path.name not in referenced and path.name != keep_name:
            shutil.rmtree(path, ignore_errors=True)


def previous(project: Path, out: Path) -> dict | None:
    """The meta of the stored entry whose report is the file now at `out`, or None when the file is not one the cache
    wrote and has not changed since (a different report, an edited one, a pruned entry)."""
    try:
        index = json.loads(_index_path(project, out).read_text(encoding="utf-8"))
        meta = _load_meta(_root(project) / index["entry"])
    except (OSError, ValueError, KeyError):
        return None
    if meta is None or index.get("report_sha256") != file_sha256(out) or meta.get("report_sha256") != index["report_sha256"]:
        return None
    return meta


# ---------------------------------------------------------------- the lock

def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stale(lock: Path) -> bool:
    """A lock whose holder is gone: a dead process, or no sign of life for `STALE_S` (a reused process id)."""
    try:
        age = time.time() - lock.stat().st_mtime
    except FileNotFoundError:
        return False
    except OSError:
        return False
    try:
        holder = json.loads(lock.read_text(encoding="utf-8"))
        pid = int(holder.get("pid") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return age > 5.0                      # a lock file that never got its content: its writer died or is about to
    return age > STALE_S or not _alive(pid)


def _break(lock: Path) -> None:
    """Remove a stale lock under a short mutex, so two waiters cannot each remove the other's fresh lock."""
    mutex = lock.with_suffix(".break")
    try:
        descriptor = os.open(mutex, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        with contextlib.suppress(OSError):
            if time.time() - mutex.stat().st_mtime > 10:
                mutex.unlink()
        return
    os.close(descriptor)
    try:
        if _stale(lock):
            lock.unlink(missing_ok=True)
    finally:
        mutex.unlink(missing_ok=True)


class _Lease:
    def __init__(self, path: Path):
        self.path = path
        self._stop = threading.Event()
        self._beat = threading.Thread(target=self._run, name="lapis-check-lock", daemon=True)
        self._beat.start()

    def _run(self) -> None:
        while not self._stop.wait(HEARTBEAT_S):
            with contextlib.suppress(OSError):
                os.utime(self.path)

    def release(self) -> None:
        self._stop.set()
        self._beat.join()
        self.path.unlink(missing_ok=True)


def _try_lock(path: Path, info: dict | None = None) -> _Lease | None:
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return None
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({**(info or {}), "pid": os.getpid(), "started": time.time()}))
    return _Lease(path)


def _out_name(project: Path, out: Path) -> str:
    """`out` as a path under `project` when it is one, else as given: how a lock names the report its run writes."""
    try:
        return (out if out.is_absolute() else Path.cwd() / out).resolve().relative_to(project.resolve()).as_posix()
    except (OSError, ValueError):
        return out.as_posix()


def running(project: Path) -> list[dict]:
    """The browser checks running now, one per lock with a live holder, oldest first: `{kind, build_id, state_key, out,
    pid, started}` (`started` is epoch seconds). A lock whose holder is gone, and one not yet written, is not listed.
    This is how a checkpoint and `next` tell a check that has not finished from one that has."""
    found = []
    for lock in sorted((_root(project) / "locks").glob("*.lock")):
        if _stale(lock):
            continue
        try:
            holder = json.loads(lock.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(holder, dict) and holder.get("kind") and holder.get("out"):
            found.append({k: holder.get(k) for k in ("kind", "build_id", "state_key", "out", "pid", "started")})
    return sorted(found, key=lambda row: row["started"] or 0)


def is_full(meta: dict) -> bool:
    """Whether a stored entry is a run of every width (render) or of both contexts and every probe (behavior): the run a
    release reads, not a narrowed one."""
    selection = meta.get("selection") or {}
    if meta.get("kind") == "render":
        return sorted(selection.get("widths") or []) == sorted(WIDTHS)
    if meta.get("kind") == "behavior":
        return (sorted(selection.get("contexts") or []) == ["d", "m"] and not selection.get("probes")
                and not selection.get("boxes") and selection.get("limit") is None)
    return False


def stored_full(project: Path, kind: str, build_id: str, out_name: str) -> dict | None:
    """The newest stored full run of `kind` that wrote a report named `out_name` for the build `build_id`, or None."""
    best = None
    for entry in sorted((_root(project)).glob(f"{kind}-*")):
        meta = _load_meta(entry)
        if (meta and meta.get("build_id") == build_id and meta.get("out_name") == out_name and is_full(meta)
                and (best is None or (meta.get("created") or "") > (best.get("created") or ""))):
            best = meta
    return best


# ---------------------------------------------------------------- one run per key

@dataclass
class Outcome:
    exit: int
    cache: str                       # hit | join | miss | off
    reason: str | None = None        # why a run was not stored or not cacheable
    run_seconds: float | None = None  # how long the run that produced the result took (this one on a miss)
    created: str | None = None       # when the reused result was made
    waited: float = 0.0
    build_id: str | None = None
    state_key: str | None = None


def _announce_join(kind: str, lock: Path) -> None:
    """One line on stderr when a check finds the identical run in progress and waits for it, so the caller knows it did
    not start a second run and that the result comes when that one ends."""
    try:
        started = float(json.loads(lock.read_text(encoding="utf-8")).get("started"))
        since = time.strftime("%H:%M:%S", time.localtime(started))
        when = f" (started {since}, {int(time.time() - started)} s ago)"
    except (OSError, ValueError, TypeError, AttributeError):
        when = ""
    print(f"{kind} check: the identical run is still going{when}; waiting for it and sharing its result, not starting "
          "another.", file=sys.stderr)


def run(project: Path, key: Key | None, *, out: Path, shots: Path | None, fresh: bool,
        produce: Callable[[], int], stable: Callable[[], str | None] = lambda: None,
        poll: float = 0.2) -> Outcome:
    """Run `produce()` (which writes `out`, and `shots` when given, and returns an exit code) once per `key`.

    A stored result for the key is copied to `out` (`hit`). A run in progress for the same key is waited for and its
    result shared (`join`). Otherwise `produce()` runs under a lock and, when it exits 0 and `stable()` returns None, its
    result is stored (`miss`). `stable()` returns a reason when the run cannot be trusted for the key (the tree changed
    underneath it, the page asked another origin for something): the result is then not stored and the cache is `off`.
    With `fresh` nothing is reused, and the new result replaces the stored one. No key: `produce()` alone, `off`."""
    if key is None:
        started = time.monotonic()
        code = produce()
        return Outcome(code, "off", "no identity: the address is not one this CLI serves", time.monotonic() - started)
    ident = {"build_id": key.build_id, "state_key": key.state_key}
    entry = _entry(project, key)

    def ready() -> dict | None:
        meta = _load_meta(entry)
        return meta if meta and (shots is None or (entry / "shots").is_dir()) else None

    if not fresh and (meta := ready()) and _restore(entry, out, shots):
        note_report(project, key, out)
        return Outcome(0, "hit", None, meta.get("run_seconds"), meta.get("created"), **ident)
    lock = _root(project) / "locks" / f"{key.kind}-{key.state_key}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    waited_from = time.monotonic()
    waited = False
    info = {"kind": key.kind, "build_id": key.build_id, "state_key": key.state_key, "out": _out_name(project, out)}
    while True:
        lease = _try_lock(lock, info)
        if lease is not None:
            break
        if not waited and not fresh and not _stale(lock):
            _announce_join(key.kind, lock)
        waited = True
        if _stale(lock):
            _break(lock)
            continue
        if not fresh and (meta := ready()) and _restore(entry, out, shots):
            note_report(project, key, out)
            return Outcome(0, "join", None, meta.get("run_seconds"), meta.get("created"),
                           time.monotonic() - waited_from, **ident)
        time.sleep(poll)
    try:
        if not fresh and (meta := ready()) and _restore(entry, out, shots):        # it finished while we took the lock
            note_report(project, key, out)
            return Outcome(0, "join" if waited else "hit", None, meta.get("run_seconds"), meta.get("created"),
                           time.monotonic() - waited_from, **ident)
        started = time.monotonic()
        code = produce()
        seconds = time.monotonic() - started
        outcome = Outcome(code, "off" if fresh else "miss", "--fresh" if fresh else None, seconds,
                          waited=time.monotonic() - waited_from if waited else 0.0, **ident)
        if code == 0:
            unstable = stable()
            if unstable:
                outcome.cache, outcome.reason = "off", unstable
            else:
                _store(project, key, out, shots, seconds)
        return outcome
    finally:
        lease.release()


def foreign_origins(seen: Iterable[str], page: str) -> list[str]:
    """Origins a page asked for other than its own, sorted: what a stored result cannot account for."""
    return sorted(set(seen) - {page})



# ---------------------------------------------------------------- lint: a report reused for the same inputs

def folder_digest(root: Path, skip: Iterable[str] = ()) -> str | None:
    """A hash of every file under `root` (names and bytes), leaving out folders whose name starts with a dot or is in
    `skip`; None when the folder has too many files or bytes to hash on every run, or cannot be read."""
    skipped = set(skip)
    digest = hashlib.sha256()
    files = total = 0
    try:
        for folder, names, files_here in os.walk(root):
            names[:] = sorted(name for name in names if not name.startswith(".") and name not in skipped)
            for name in sorted(files_here):
                path = Path(folder) / name
                files += 1
                total += path.stat().st_size
                if files > MAX_FILES or total > MAX_BYTES:
                    return None
                found = file_sha256(path)
                if found is None:
                    return None
                digest.update(f"{path.relative_to(root).as_posix()}\0{found}\0".encode("utf-8"))
    except OSError:
        return None
    return digest.hexdigest()


def referenced_files(documents: Iterable[object], bases: Iterable[Path]) -> dict[str, str | None] | None:
    """`{path: sha256}` of every existing file a string in `documents` names, relative to any of `bases` or absolute:
    the files a plan, ledger, or lock points at (a design contract, a capture, an asset), which a check may read
    without being handed them. None when they total more than `MAX_BYTES`."""
    found: dict[str, str | None] = {}
    total = 0
    pending = list(documents)
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str) and 0 < len(item) <= 300 and "\n" not in item and item not in found:
            candidates = [Path(item)] if Path(item).is_absolute() else [base / item for base in bases]
            for candidate in candidates:
                try:
                    if candidate.is_file():
                        total += candidate.stat().st_size
                        if total > MAX_BYTES:
                            return None
                        found[item] = file_sha256(candidate)
                        break
                except (OSError, ValueError):
                    continue
    return dict(sorted(found.items()))


def lint_index_path(project: Path, out: Path) -> Path:
    return _root(project) / "lint" / (hashlib.sha1(str(out.resolve()).encode()).hexdigest()[:20] + ".json")


def lint_reusable(project: Path, out: Path, digest: str) -> bool:
    """Whether the lint report at `out` was written for inputs that hash to `digest` and is the file written then."""
    try:
        index = json.loads(lint_index_path(project, out).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    written = file_sha256(out)
    return written is not None and index.get("inputs") == digest and index.get("report_sha256") == written


def lint_note(project: Path, out: Path, digest: str) -> None:
    path = lint_index_path(project, out)
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"inputs": digest, "out": out.as_posix(), "report_sha256": file_sha256(out)}) + "\n",
                        encoding="utf-8")


def inputs_digest(parts: dict) -> str:
    """The key of a lint run: what it reads, the day (rights notices expire), and the tool and its rules."""
    return _digest({"parts": parts, "day": date.today().isoformat(), "tool": tool_digest()})[:32]
