"""CI splits the browser tests across runners with `--shard K/N` (tests/conftest.py). The parts must
cover every selected test exactly once, and sharding must not undo the browser marker that `-m` reads."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def collected(*args: str) -> tuple[int, list[str]]:
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                             "-p", "no:xdist", *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
    return result.returncode, sorted(line for line in result.stdout.splitlines() if "::" in line)


def test_shards_cover_every_selected_test_once():
    # A browser module and a plain module, so both the marker and -m take part.
    files = ["tests/test_behavior_core.py", "tests/test_build.py"]
    code, everything = collected(*files, "-m", "browser")
    assert code == 0 and everything
    parts = [collected(*files, "-m", "browser", "--shard", f"{k}/3")[1] for k in (1, 2, 3)]
    assert sorted(sum(parts, [])) == everything                       # no test lost, none run twice
    assert all(test.startswith("tests/test_behavior_core.py") for test in everything)   # -m still applies


def test_a_shard_outside_its_count_is_a_usage_error():
    code, _ = collected("tests/test_build.py", "--shard", "4/3")
    assert code != 0
