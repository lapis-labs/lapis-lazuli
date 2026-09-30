"""CI splits the browser tests across runners with `--shard K/N` (tests/conftest.py, tests/shards.py). The parts
must cover every selected test exactly once, weigh about the same, and not undo the browser marker that `-m` reads."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from shards import hash_part, load_durations, partition

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


def test_parts_are_exact_and_follow_from_the_ids_alone():
    durations = {f"t{i}": float(i % 9 + 1) for i in range(60)}
    ids = [*durations, *(f"unlisted{i}" for i in range(6))]
    parts = partition(ids, 4, durations)
    assert sorted(parts) == sorted(ids) and set(parts.values()) <= {1, 2, 3, 4}
    assert partition(reversed(ids), 4, durations) == parts                        # the order the ids arrive in is no input
    assert {i: parts[i] for i in ids if i.startswith("unlisted")} == {i: hash_part(i, 4) for i in ids if i.startswith("unlisted")}
    assert {i: p for i, p in parts.items() if i in durations} == partition(list(durations), 4, durations)   # new tests move no listed one


def test_listed_tests_are_packed_so_no_part_outweighs_the_average_by_more_than_one_test():
    durations = {"a": 300.0, "b": 140.0, "c": 140.0, "d": 100.0, "e": 100.0, "f": 100.0, "g": 60.0, "h": 60.0, "i": 10.0}
    parts = partition(durations, 4, durations)
    loads = [sum(seconds for test, seconds in durations.items() if parts[test] == part) for part in (1, 2, 3, 4)]
    assert max(loads) <= sum(durations.values()) / 4 + max(durations.values())
    assert max(loads) == 300.0                                                     # the longest test alone is the floor here


def test_committed_durations_keep_the_browser_parts_even_and_name_tests_that_exist():
    durations = load_durations()
    assert durations and all(test.startswith("tests/") and seconds > 0 for test, seconds in durations.items())
    loads = [0.0] * 4
    for test, part in partition(durations, 4, durations).items():
        loads[part - 1] += durations[test]
    assert max(loads) <= 1.1 * sum(loads) / 4                                      # every part within a tenth of the average
    existing = set(collected("-m", "browser")[1])
    known = sum(seconds for test, seconds in durations.items() if test in existing)
    assert known >= 0.8 * sum(durations.values()), (
        "tests/shard_durations.json lists tests that no longer exist; refresh it as tests/shards.py explains")
