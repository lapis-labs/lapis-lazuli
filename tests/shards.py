"""Which part of `pytest --shard K/N` a test belongs to, and how the committed durations are refreshed.

CI runs the browser tests on several runners, each with its own `--shard K/N`; a run is as slow as its
slowest part. Tests listed in `shard_durations.json` (seconds, from a past run) are packed longest
first onto the lightest part, so the parts weigh about the same. A test the file does not list goes
to the part its id hashes to, which is stable on every machine and Python version and needs no
upkeep: a new test is still run exactly once, only its weight is unknown until the file is refreshed.

Refresh after adding or splitting slow tests, from the JUnit files of a full browser run (one file,
or the files of all parts of one run):

    uv run --no-sync pytest -q -m browser -n auto --junitxml=/tmp/browser.xml
    uv run --no-sync python tests/shards.py /tmp/browser.xml
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DURATIONS_FILE = Path(__file__).with_name("shard_durations.json")
# Shorter tests are left out of the file: they change no part's weight noticeably, and the hash
# spreads them evenly.
MIN_SECONDS = 1.0


def hash_part(nodeid: str, count: int) -> int:
    """The part (1..count) a test id hashes to: stable across runs, machines, and Python versions."""
    return int.from_bytes(hashlib.sha256(nodeid.encode()).digest()[:8], "big") % count + 1


def load_durations(path: Path = DURATIONS_FILE) -> dict[str, float]:
    return {nodeid: float(seconds) for nodeid, seconds in json.loads(path.read_text(encoding="utf-8"))["seconds"].items()}


def partition(nodeids: Iterable[str], count: int, durations: Mapping[str, float]) -> dict[str, int]:
    """Every test id's part (1..count). The answer depends only on the set of ids, not their order.

    Listed tests are placed longest first (ties by id) on the lightest part so far (ties to the lowest
    part number), which keeps the heaviest part within one test of the average. Unlisted tests are
    placed by hash, so a new test never moves a listed one."""
    ids = sorted(set(nodeids))
    parts = {nodeid: hash_part(nodeid, count) for nodeid in ids if nodeid not in durations}
    loads = [0.0] * count
    for nodeid in sorted((nodeid for nodeid in ids if nodeid in durations), key=lambda nodeid: (-durations[nodeid], nodeid)):
        lightest = loads.index(min(loads))
        loads[lightest] += durations[nodeid]
        parts[nodeid] = lightest + 1
    return parts


def _nodeid(classname: str, name: str) -> str:
    """`tests.test_mod.TestClass` + `test_x[p]` -> `tests/test_mod.py::TestClass::test_x[p]`: the longest leading run of
    dotted names that is a module file is the file, what follows is the class nesting."""
    parts = classname.split(".")
    for end in range(len(parts), 0, -1):
        module = "/".join(parts[:end]) + ".py"
        if (ROOT / module).is_file():
            return "::".join([module, *parts[end:], name])
    raise SystemExit(f"no test module for JUnit classname {classname!r}; run from a checkout with its tests/ folder")


def durations_from_junit(*files: Path) -> dict[str, float]:
    """Seconds per test id from JUnit files (setup, call, and teardown together); a test in several files keeps its slowest time."""
    seconds: dict[str, float] = {}
    for file in files:
        for case in ElementTree.parse(file).getroot().iter("testcase"):
            nodeid = _nodeid(case.get("classname", ""), case.get("name", ""))
            seconds[nodeid] = max(seconds.get(nodeid, 0.0), float(case.get("time", 0)))
    return seconds


def write_durations(durations: Mapping[str, float], path: Path = DURATIONS_FILE) -> int:
    kept = {nodeid: round(time, 1) for nodeid, time in sorted(durations.items()) if time >= MIN_SECONDS}
    document = {"comment": "Seconds per browser test from one run; tests/shards.py explains the refresh.", "seconds": kept}
    path.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(kept)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rewrite the committed shard durations from JUnit files.")
    parser.add_argument("junit", nargs="+", type=Path, help="JUnit XML of a full browser run (all parts of one run)")
    parser.add_argument("-o", "--out", type=Path, default=DURATIONS_FILE)
    args = parser.parse_args(argv)
    kept = write_durations(durations_from_junit(*args.junit), args.out)
    print(f"{kept} tests of {MIN_SECONDS:g} s or more -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
