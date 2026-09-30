"""Plan alias, size, and depth limits and fail-closed exit-plan decisions at the public command boundary."""
from __future__ import annotations

import functools
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
import yaml

from lapis_design import shared_dir
from lapis_design.lint import cli as lint_cli

SHARED = shared_dir()
TASK = "kiln-shop-landing"


def example() -> dict:
    return yaml.safe_load((SHARED / "plan/example.plan.yaml").read_text(encoding="utf-8"))


def write_plan(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "plan.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# Speed attack tests time only the call, inside the child process after it has imported what the call
# uses, so a slow interpreter start or a busy machine cannot fail them; `HANG_GUARD` only stops a hang.
# On Linux the child also gets `MEMORY_HEADROOM` beyond what its imports already map, so an alias that
# expands fails with a MemoryError; macOS does not enforce `RLIMIT_AS`.
HANG_GUARD = 60
CALL_LIMIT = 2
MEMORY_HEADROOM = 512 * 2**20

CHILD = """
import importlib, json, sys, time

job = json.loads(sys.argv[1])
if job["mcp"]:
    from lapis_design.mcp_server import slop_lint, ToolError

    def call():
        try:
            slop_lint(plan=job["mcp"], layers=["plan"])
        except ToolError as error:
            print(str(error))
            return 0
        return 1
else:
    from lapis_design import cli

    argv = job["argv"]
    if argv[:1] == ["hook"]:
        importlib.import_module("lapis_design.plan_check")     # the hook imports it after reading its input
    elif tuple(argv[:2]) in cli.CHECKS:
        importlib.import_module(cli.CHECKS[tuple(argv[:2])])   # `main` imports the check it names

    def call():
        return cli.main(argv)

if sys.platform.startswith("linux"):
    import resource

    with open("/proc/self/statm") as statm:
        mapped = int(statm.read().split()[0]) * resource.getpagesize()
    hard = resource.getrlimit(resource.RLIMIT_AS)[1]
    soft = mapped + job["headroom"]
    resource.setrlimit(resource.RLIMIT_AS, (soft if hard == resource.RLIM_INFINITY else min(soft, hard), hard))

start = time.perf_counter()
code = call()
elapsed = time.perf_counter() - start
with open(job["stamp"], "w") as stamp:
    stamp.write(repr(elapsed))
sys.exit(code)
"""


def child_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    cache = tmp_path / "cache"
    home.mkdir(exist_ok=True)
    cache.mkdir(exist_ok=True)
    return dict(os.environ, LAZULI_DB="", HOME=str(home), XDG_CACHE_HOME=str(cache))


def call(tmp_path: Path, *args: str, input: str | None = None) -> subprocess.CompletedProcess[str]:
    """A command whose result is checked; nothing about its speed is."""
    return subprocess.run([sys.executable, "-c", "from lapis_design.cli import main; raise SystemExit(main())", *args],
                          cwd=tmp_path, input=input, capture_output=True, text=True, timeout=HANG_GUARD,
                          env=child_env(tmp_path))


def timed(tmp_path: Path, job: dict, input: str | None, limit: float) -> subprocess.CompletedProcess[str]:
    stamp = tmp_path / "elapsed.txt"
    stamp.unlink(missing_ok=True)
    job = {"mcp": None, "argv": [], "stamp": str(stamp), "headroom": MEMORY_HEADROOM, **job}
    result = subprocess.run([sys.executable, "-c", CHILD, json.dumps(job)], cwd=tmp_path, input=input,
                            capture_output=True, text=True, timeout=HANG_GUARD, env=child_env(tmp_path))
    assert stamp.exists(), f"the call did not finish (exit {result.returncode}): {result.stderr[-600:]}"
    elapsed = float(stamp.read_text())
    assert elapsed < limit, f"the call took {elapsed:.2f} s, over {limit} s"
    return result


def timed_call(tmp_path: Path, *args: str, input: str | None = None,
               limit: float = CALL_LIMIT) -> subprocess.CompletedProcess[str]:
    """A command whose call must finish within `limit` seconds; its result is checked too."""
    return timed(tmp_path, {"argv": list(args)}, input, limit)


def timed_mcp(tmp_path: Path, plan: Path, limit: float = CALL_LIMIT) -> subprocess.CompletedProcess[str]:
    """The MCP `slop_lint` tool on a plan; exit 0 and one line on stdout when it refuses with a ToolError."""
    return timed(tmp_path, {"mcp": str(plan)}, None, limit)


def yaml_plan(prefix: str) -> str:
    return prefix + yaml.safe_dump(example(), allow_unicode=True)


def branching_alias(depth: int, width: int, value: str = "leaf") -> str:
    rows = ["x-aliases:", f"  leaf: &a0 {json.dumps(value)}"]
    for level in range(1, depth + 1):
        rows.append(f"  level{level}: &a{level} [{', '.join([f'*a{level - 1}'] * width)}]")
    return "\n".join(rows) + "\n"


def hook_event(block: str) -> str:
    return json.dumps({"tool_input": {"plan": f"```yaml lapis-plan\n{block}\n```"}})


def decision(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)["hookSpecificOutput"]["decision"]
    assert out["behavior"] == "deny"
    return out["message"]


def test_cycle_before_copy_does_not_hide_vague_cta(tmp_path):
    plan = example()
    plan["content"]["key_copy"].append({"slot": "cta", "text": "Click here", "locale": "en"})
    path = write_plan(tmp_path, "x-notes: &a [*a]\n" +
                      yaml.safe_dump(plan, allow_unicode=True))
    found = lint_cli.run(plan=path, rule_ids=["copy.vague-cta"])["findings"]
    assert any(f["rule_id"] == "copy.vague-cta" and f["blocking"] and
               f["location"]["path"].endswith(".text") for f in found)


def test_wide_alias_before_copy_finishes_in_one_second(tmp_path):
    plan = example()
    plan["content"]["key_copy"].append({"slot": "cta", "text": "Click here", "locale": "en"})
    path = write_plan(tmp_path, yaml.safe_dump(plan, allow_unicode=True))
    lint_cli.run(plan=path)
    path = write_plan(tmp_path, branching_alias(7, 9) + yaml.safe_dump(plan, allow_unicode=True))
    start = time.perf_counter()
    result = lint_cli.run(plan=path)
    assert time.perf_counter() - start < 1
    assert any(f["rule_id"] == "copy.vague-cta" for f in result["findings"])


@pytest.mark.parametrize("kind", ["values", "characters"])
@pytest.mark.parametrize("command", ["plan", "lint", "hook", "gate"])
def test_expanding_plan_is_stopped_before_schema(tmp_path, kind, command):
    value = "x" * 200_000 if kind == "characters" else "leaf"
    prefix = branching_alias(1 if kind == "characters" else 9, 9, value)
    plan = yaml_plan(prefix).replace("subject: Online sales for a small pottery studio",
                                     "subject: *a1" if kind == "characters" else "subject: *a9")
    path = write_plan(tmp_path, plan)
    if command == "plan":
        result = timed_call(tmp_path, "plan", "check", str(path), "--format", "json")
        assert result.returncode == 1, result.stderr
        findings = json.loads(result.stdout)["findings"]
        assert [f["rule_id"] for f in findings] == ["schema.invalid"]
    elif command == "lint":
        result = timed_call(tmp_path, "slop", "lint", "--plan", str(path))
        assert result.returncode == 2 and result.stdout == ""
        assert len(result.stderr.splitlines()) == 1 and "does not match its schema" in result.stderr
    elif command == "hook":
        result = timed_call(tmp_path, "hook", "exit-plan", input=hook_event(plan))
        message = decision(result)
        assert message.count("schema.invalid") == 1
    else:
        dest = tmp_path / ".lapis/plans" / f"{TASK}.yaml"
        dest.parent.mkdir(parents=True)
        dest.write_text(plan, encoding="utf-8")
        result = timed_call(tmp_path, "release", "check", "--task", TASK, "--offline")
        assert result.returncode == 1, result.stderr
        report = json.loads((tmp_path / ".lapis/release" / f"{TASK}.json").read_text(encoding="utf-8"))
        assert [f["rule_id"] for f in report["findings"]] == ["schema.invalid"]


@pytest.mark.parametrize("block,expected", [
    ("brief: [oops\n", "ParserError"),
    ("? [a]: b\n", "ConstructorError"),
])
def test_uncheckable_hook_block_is_denied(tmp_path, block, expected):
    result = call(tmp_path, "hook", "exit-plan", input=hook_event(block))
    message = decision(result)
    assert "lapis-plan block could not be checked:" in message
    assert expected in message and "\n" not in message


def test_deep_list_yields_schema_finding_and_hook_denial(tmp_path):
    text = yaml_plan("").replace("subject: Online sales for a small pottery studio",
                                  "subject: " + "[" * 5000 + "leaf" + "]" * 5000)
    path = write_plan(tmp_path, text)
    plan = timed_call(tmp_path, "plan", "check", str(path), "--format", "json", limit=10)
    assert plan.returncode == 1, plan.stderr
    assert [f["rule_id"] for f in json.loads(plan.stdout)["findings"]] == ["schema.invalid"]
    lint = timed_call(tmp_path, "slop", "lint", "--plan", str(path), limit=10)
    assert lint.returncode == 2 and "does not match its schema" in lint.stderr
    assert "schema.invalid" in decision(timed_call(tmp_path, "hook", "exit-plan", input=hook_event(text), limit=10))


def test_top_level_extension_cycle_does_not_change_plan_findings(tmp_path):
    path = write_plan(tmp_path, yaml_plan(""))
    original = timed_call(tmp_path, "plan", "check", str(path), "--format", "json", limit=10)
    path = write_plan(tmp_path, yaml_plan("x-notes: &a [*a]\n"))
    extended = timed_call(tmp_path, "plan", "check", str(path), "--format", "json", limit=10)
    assert original.returncode == extended.returncode
    assert json.loads(original.stdout)["findings"] == json.loads(extended.stdout)["findings"]


def test_extension_padding_cannot_delay_hook_denial(tmp_path):
    plan = example()
    plan["brief"]["locales"] = ["en"]
    plan["content"]["key_copy"] = [{"slot": "cta", "text": "A handmade piece"} for _ in range(60)]
    plan["content"]["key_copy"].append({"slot": "cta", "text": "Click here"})
    text = "x-pad: [" + "[], " * 199_999 + "[]]\n" + yaml.safe_dump(plan, allow_unicode=True)
    message = decision(timed_call(tmp_path, "hook", "exit-plan", input=hook_event(text), limit=10))
    assert "copy.vague-cta" in message


def test_many_key_copy_items_still_reach_copy_rules(tmp_path):
    plan = example()
    plan["brief"]["locales"] = ["en"]
    plan["content"]["key_copy"] = [{"slot": "cta", "text": "A handmade piece"} for _ in range(1849)]
    plan["content"]["key_copy"].append({"slot": "cta", "text": "Click here"})
    path = write_plan(tmp_path, yaml.safe_dump(plan, allow_unicode=True))
    result = timed_call(tmp_path, "slop", "lint", "--plan", str(path), limit=5)
    assert result.returncode == 1, result.stderr
    findings = json.loads(result.stdout)["findings"]
    assert any(f["rule_id"] == "copy.vague-cta" and f["location"]["path"] ==
               "content.key_copy[1849].text" for f in findings)


def hostile_plan(kind: str) -> str:
    if kind == "deep-key":
        rows = ["x-aliases:", '  key: &k "' + "k" * 100_000 + '"',
                "  level0: &a0 {? *k : leaf}"]
        rows.extend(f"  level{i}: &a{i} {{? *k : *a{i - 1}}}" for i in range(1, 3000))
        return yaml_plan("\n".join(rows) + "\n").replace(
            "subject: Online sales for a small pottery studio", "subject: *a2999")
    if kind == "wide-key":
        prefix = 'x-key: &k "' + "k" * 990_000 + '"\n'
        return yaml_plan(prefix).replace(
            "subject: Online sales for a small pottery studio",
            "subject: [" + ", ".join(["{? *k : leaf}"] * 4800) + "]")
    if kind == "binary":
        data = "YWFh" * 133_333 + "YQ=="
        prefix = "x-binary: &b !!binary |\n  " + data + "\n"
        return yaml_plan(prefix).replace(
            "subject: Online sales for a small pottery studio",
            "subject: [" + ", ".join(["*b"] * 4000) + "]")
    prefix = branching_alias(9, 9) + "x-pairs: &p !!pairs [a: *a9]\n"
    return yaml_plan(prefix).replace("subject: Online sales for a small pottery studio", "subject: *p")


@pytest.mark.parametrize("kind", ["deep-key", "wide-key", "binary", "pairs"])
@pytest.mark.parametrize("command", ["plan", "markdown", "lint", "hook", "gate", "mcp"])
def test_hostile_aliases_fail_closed_quickly(tmp_path, kind, command):
    text = hostile_plan(kind)
    path = write_plan(tmp_path, text)
    if command == "plan":
        result = timed_call(tmp_path, "plan", "check", str(path), "--format", "json")
        assert result.returncode == 1, result.stderr
        assert [f["rule_id"] for f in json.loads(result.stdout)["findings"]] == ["schema.invalid"]
    elif command == "markdown":
        result = timed_call(tmp_path, "plan", "check", "--from-markdown", "-", "--format", "json",
                            input=f"```yaml lapis-plan\n{text}\n```")
        assert result.returncode == 1, result.stderr
        assert [f["rule_id"] for f in json.loads(result.stdout)["findings"]] == ["schema.invalid"]
    elif command == "lint":
        result = timed_call(tmp_path, "slop", "lint", "--plan", str(path))
        assert result.returncode == 2 and result.stdout == ""
        assert len(result.stderr.splitlines()) == 1 and "does not match its schema" in result.stderr
    elif command == "hook":
        assert decision(timed_call(tmp_path, "hook", "exit-plan", input=hook_event(text))).count("schema.invalid") == 1
    elif command == "gate":
        dest = tmp_path / ".lapis/plans" / f"{TASK}.yaml"
        dest.parent.mkdir(parents=True)
        dest.write_text(text, encoding="utf-8")
        result = timed_call(tmp_path, "release", "check", "--task", TASK, "--offline")
        assert result.returncode == 1, result.stderr
        report = json.loads((tmp_path / ".lapis/release" / f"{TASK}.json").read_text(encoding="utf-8"))
        assert [f["rule_id"] for f in report["findings"]] == ["schema.invalid"]
    else:
        result = timed_mcp(tmp_path, path)
        assert result.returncode == 0, result.stderr
        assert len(result.stdout.splitlines()) == 1 and "does not match its schema" in result.stdout


@pytest.mark.parametrize("value", [
    "!!binary YWFh", "!!timestamp 2026-09-28", "!!timestamp 2026-09-28T12:00:00Z",
    "!!set {a: null}", "!!omap [a: b]", "!!pairs [a: b]",
    ".nan", ".inf", "-.inf", "0x" + "f" * 3600,
], ids=["bytes", "date", "datetime", "set", "omap", "pairs", "nan", "inf", "negative-inf", "large-int"])
def test_non_json_yaml_values_are_rejected_before_schema_formatting(tmp_path, value):
    text = yaml_plan("").replace("subject: Online sales for a small pottery studio", f"subject: {value}")
    result = call(tmp_path, "plan", "check", str(write_plan(tmp_path, text)), "--format", "json")
    assert result.returncode == 1, result.stderr
    findings = json.loads(result.stdout)["findings"]
    assert len(findings) == 1 and findings[0]["rule_id"] == "schema.invalid"
    assert "unsupported YAML value" in findings[0]["observed"]


def test_extension_with_non_string_key_and_binary_value_is_exempt(tmp_path):
    original = write_plan(tmp_path, yaml_plan(""))
    before = call(tmp_path, "plan", "check", str(original), "--format", "json")
    write_plan(tmp_path, yaml_plan("x-special:\n  ? 1\n  : !!binary YWFh\n"))
    after = call(tmp_path, "plan", "check", str(original), "--format", "json")
    assert before.returncode == after.returncode
    assert json.loads(before.stdout)["findings"] == json.loads(after.stdout)["findings"]


@pytest.mark.parametrize("value,unsupported", [
    (10**4299, False), (-10**4299, False), (10**4300, True), (-10**4300, True),
    (3.125, False), (float("inf"), True),
], ids=["positive-boundary", "negative-boundary", "too-large", "too-negative", "finite-float", "infinite-float"])
def test_numeric_expansion_boundary(value, unsupported):
    from lapis_design.plan_check import expansion_problem

    problem = expansion_problem({"brief": {"subject": value}})
    assert (problem is not None) is unsupported


def test_non_string_key_reports_its_nested_location(tmp_path):
    plan = example()
    plan["content"]["key_copy"][0][7] = "invalid key"
    path = write_plan(tmp_path, yaml.safe_dump(plan, allow_unicode=True))
    result = call(tmp_path, "plan", "check", str(path), "--format", "json")
    assert result.returncode == 1, result.stderr
    findings = json.loads(result.stdout)["findings"]
    assert [(f["rule_id"], f["location"]["path"]) for f in findings] == [
        ("schema.invalid", "content/key_copy/0/7")]


# A plan over 1,000,000 bytes, or nested more than 100 levels, is refused before it is parsed (GATE.md).

@functools.cache
def seventeen_megabytes() -> str:
    """900,000 top-level extension keys; the plan follows them."""
    return "".join(f"x-{i:07d}: padding\n" for i in range(900_000))


def nested_extension(shape: str, depth: int) -> str:
    """A top-level `x-nest` extension that makes the plan `depth` collections deep (its own mapping counts
    as the first), nested in one of three ways."""
    if shape == "flow":
        return "x-nest: " + "[" * (depth - 1) + "]" * (depth - 1) + "\n"
    if shape == "block-mapping":
        rows = ["x-nest:"] + [" " * (2 * (level - 1)) + "a:" for level in range(2, depth + 1)]
        rows[-1] += " leaf"
        return "\n".join(rows) + "\n"
    # An indentless list: each `- ` sits at the column of its key, so the scanner makes no token per level.
    rows = ["x-nest:"]
    for level in range(2, depth + 1, 2):        # a list at `level`, a mapping inside its item at level + 1
        item = "a:" if level + 1 < depth else ("a: leaf" if level + 1 == depth else "leaf")
        rows.append(" " * (level - 2) + "- " + item)
    return "\n".join(rows) + "\n"


def plan_check_json(tmp_path: Path, text: str) -> tuple[int, list[dict]]:
    result = call(tmp_path, "plan", "check", str(write_plan(tmp_path, text)), "--format", "json")
    return result.returncode, json.loads(result.stdout)["findings"]


@pytest.mark.parametrize("shape", ["flow", "block-mapping", "indentless-list"])
def test_depth_limit_is_one_hundred_levels(tmp_path, shape):
    baseline = plan_check_json(tmp_path, yaml_plan(""))
    assert "schema.invalid" not in {f["rule_id"] for f in baseline[1]}
    assert plan_check_json(tmp_path, yaml_plan("") + nested_extension(shape, 100)) == baseline
    wrong = (yaml_plan("") + nested_extension(shape, 100)).replace(
        "subject: Online sales for a small pottery studio", "subject: 5")
    code, findings = plan_check_json(tmp_path, wrong)          # a plan at the limit is still schema-checked
    assert code == 1
    assert [(f["rule_id"], f["location"]["path"]) for f in findings] == [("schema.invalid", "brief/subject")]
    code, findings = plan_check_json(tmp_path, yaml_plan("") + nested_extension(shape, 101))
    assert code == 1 and [f["rule_id"] for f in findings] == ["schema.invalid"]
    assert "nested more than 100 levels" in findings[0]["observed"]


def oversized_plan(kind: str) -> str:
    if kind == "big":
        return seventeen_megabytes() + yaml_plan("")
    if kind == "deep-flow":                                     # about 100 KB; a segfault in the C loader
        return yaml_plan("") + "x-nest: " + "[" * 50_000 + "]" * 50_000 + "\n"
    return yaml_plan("") + "x-nest:\n  " + "- " * 50_000 + "leaf\n"


@pytest.mark.parametrize("kind", ["deep-flow", "deep-list", "big"])
@pytest.mark.parametrize("command", ["plan", "markdown", "lint", "hook", "gate", "mcp"])
def test_plan_over_the_size_or_depth_limit_is_refused_before_parsing(tmp_path, kind, command):
    text = oversized_plan(kind)
    expected = "larger than 1,000,000 bytes" if kind == "big" else "nested more than 100 levels"
    path = write_plan(tmp_path, text)
    if command == "plan":
        result = timed_call(tmp_path, "plan", "check", str(path), "--format", "json")
        assert result.returncode == 1, result.stderr
        findings = json.loads(result.stdout)["findings"]
        assert [f["rule_id"] for f in findings] == ["schema.invalid"] and expected in findings[0]["observed"]
    elif command == "markdown":
        markdown = tmp_path / "harness.md"
        markdown.write_text(f"```yaml lapis-plan\n{text}\n```\n", encoding="utf-8")
        result = timed_call(tmp_path, "plan", "check", "--from-markdown", str(markdown), "--format", "json")
        assert result.returncode == 1, result.stderr
        findings = json.loads(result.stdout)["findings"]
        assert [f["rule_id"] for f in findings] == ["schema.invalid"] and expected in findings[0]["observed"]
    elif command == "lint":
        result = timed_call(tmp_path, "slop", "lint", "--plan", str(path), "--layer", "plan")
        assert result.returncode == 2 and result.stdout == ""
        assert len(result.stderr.splitlines()) == 1
        assert "does not match its schema" in result.stderr and expected in result.stderr
    elif command == "hook":
        message = decision(timed_call(tmp_path, "hook", "exit-plan", input=hook_event(text)))
        assert message.count("schema.invalid") == 1 and expected in message
    elif command == "gate":
        dest = tmp_path / ".lapis/plans" / f"{TASK}.yaml"
        dest.parent.mkdir(parents=True)
        dest.write_text(text, encoding="utf-8")
        result = timed_call(tmp_path, "release", "check", "--task", TASK, "--offline")
        assert result.returncode == 1, result.stderr
        report = json.loads((tmp_path / ".lapis/release" / f"{TASK}.json").read_text(encoding="utf-8"))
        assert [f["rule_id"] for f in report["findings"]] == ["schema.invalid"]
        assert expected in report["findings"][0]["observed"]
    else:
        result = timed_mcp(tmp_path, path)
        assert result.returncode == 0, result.stderr
        assert len(result.stdout.splitlines()) == 1
        assert "does not match its schema" in result.stdout and expected in result.stdout


def test_render_check_reads_its_plan_through_the_limits(tmp_path):
    from lapis_design.render import hosts

    path = write_plan(tmp_path, "x-nest: " + "[" * 2000 + "]" * 2000 + "\n")
    with pytest.raises(ValueError, match="nested more than 100 levels"):
        hosts.load_plan(path)


def test_behavior_check_reads_its_plan_through_the_limits(tmp_path, capsys):
    from lapis_design import behavior_check

    path = write_plan(tmp_path, "x-nest: " + "[" * 2000 + "]" * 2000 + "\n")
    assert behavior_check.main(["http://127.0.0.1:9/", "--task", "t", "--plan", str(path),
                                "--backend", "local-dev", "--outbound", "none"]) == 2
    error = capsys.readouterr().err
    assert len(error.splitlines()) == 1 and "nested more than 100 levels" in error
