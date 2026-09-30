"""Plan and exit-plan input boundaries at the public command surface."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

from lapis_design import hooks, plan_check
from lapis_design.lint import cli as lint_cli


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src/shared/plan/schema.yaml"
ENTRY = "from lapis_design.cli import main; raise SystemExit(main())"


def command(tmp_path: Path, *args: str, input: str | None = None, timeout: int = 12) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, LAZULI_DB="", HOME=str(tmp_path), XDG_CACHE_HOME=str(tmp_path))
    return subprocess.run([sys.executable, "-c", ENTRY, *args], cwd=tmp_path, input=input,
                          capture_output=True, text=True, timeout=timeout, env=env)


def input_plan(tmp_path: Path, text: str, markdown: bool) -> tuple[str, ...]:
    if markdown:
        path = tmp_path / "harness.md"
        path.write_text(f"```yaml lapis-plan\n{text}\n```\n", encoding="utf-8")
        return "--from-markdown", str(path)
    path = tmp_path / "plan.yaml"
    path.write_text(text, encoding="utf-8")
    return (str(path),)


@pytest.mark.parametrize("markdown", [False, True], ids=["file", "markdown"])
@pytest.mark.parametrize("text", [
    "brief: [oops\n",
    "brief: !unrecognized value\n",
    "brief: one\n---\nbrief: two\n",
    "? [unhashable]: value\n",
], ids=["syntax", "tag", "multiple-documents", "unhashable-key"])
def test_unreadable_plan_has_one_reason_and_no_traceback(tmp_path, markdown, text):
    result = command(tmp_path, "plan", "check", *input_plan(tmp_path, text, markdown))
    assert result.returncode == 2
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert "cannot be read" in result.stderr
    assert "Traceback" not in result.stderr

@pytest.mark.parametrize("markdown", [False, True], ids=["file", "markdown"])
def test_missing_plan_source_has_one_reason_and_no_traceback(tmp_path, markdown):
    path = tmp_path / ("missing.md" if markdown else "missing.yaml")
    args = ("--from-markdown", str(path)) if markdown else (str(path),)
    result = command(tmp_path, "plan", "check", *args)
    assert result.returncode == 2
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert str(path) in result.stderr and "cannot be read" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("markdown", [False, True], ids=["file", "markdown"])
def test_empty_document_is_schema_invalid(tmp_path, markdown):
    result = command(tmp_path, "plan", "check", *input_plan(tmp_path, "", markdown), "--format", "json")
    assert result.returncode == 1, result.stderr
    assert [(f["rule_id"], f["observed"]) for f in json.loads(result.stdout)["findings"]] == [
        ("schema.invalid", "None is not of type 'object'")]
    assert "Traceback" not in result.stderr


def test_deep_markdown_list_is_schema_invalid(tmp_path):
    text = (ROOT / "src/shared/plan/example.plan.yaml").read_text(encoding="utf-8")
    assert "subject: Online sales for a small pottery studio" in text
    text = text.replace("subject: Online sales for a small pottery studio",
                        "subject: " + "[" * 5000 + "leaf" + "]" * 5000, 1)
    result = command(tmp_path, "plan", "check", *input_plan(tmp_path, text, True), "--format", "json")
    assert result.returncode == 1, result.stderr
    assert [f["rule_id"] for f in json.loads(result.stdout)["findings"]] == ["schema.invalid"]
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("markdown", [False, True], ids=["file", "markdown"])
def test_oversized_hex_schema_message_has_no_traceback(tmp_path, markdown):
    text = (ROOT / "src/shared/plan/example.plan.yaml").read_text(encoding="utf-8")
    assert "subject: Online sales for a small pottery studio" in text
    text = text.replace("subject: Online sales for a small pottery studio",
                        "subject: 0x" + "f" * 6000, 1)
    result = command(tmp_path, "plan", "check", *input_plan(tmp_path, text, markdown), "--format", "json")
    assert result.returncode == 1, result.stderr
    assert [f["rule_id"] for f in json.loads(result.stdout)["findings"]] == ["schema.invalid"]
    assert "Traceback" not in result.stderr


def test_schema_message_conversion_failure_is_schema_invalid():
    oversized = int("f" * 6000, 16)
    schema = plan_check.load_yaml(SCHEMA)
    findings = plan_check.check_schema({"brief": {"subject": oversized}}, schema, "plan.yaml")
    assert len(findings) == 1 and findings[0]["rule_id"] == "schema.invalid"
    assert findings[0]["observed"] == "plan could not be validated against its schema"


def test_lint_schema_message_conversion_failure_is_problem():
    oversized = int("f" * 6000, 16)
    assert lint_cli.problems({"source": {"kind": oversized}}, "extract") == [
        "(root): document could not be validated against its schema"]


def test_empty_exit_plan_block_is_denied_as_schema_invalid(tmp_path):
    event = {"tool_input": {"plan": "```yaml lapis-plan\n\n```"}, "cwd": str(tmp_path)}
    stdout = io.StringIO()
    assert hooks.exit_plan(io.StringIO(json.dumps(event)), stdout) == 0
    decision = json.loads(stdout.getvalue())["hookSpecificOutput"]["decision"]
    assert decision["behavior"] == "deny"
    assert "schema.invalid" in decision["message"]
    assert "None is not of type 'object'" in decision["message"]


@pytest.mark.parametrize("with_block", [False, True])
def test_missing_contracts_denies_only_when_plan_block_exists(tmp_path, monkeypatch, with_block):
    def missing_contracts():
        raise FileNotFoundError("shared contracts unavailable")

    monkeypatch.setattr("lapis_design.shared_dir", missing_contracts)
    text = "```yaml lapis-plan\nversion: 0\n```" if with_block else "# A regular plan"
    event = {"tool_input": {"plan": text}, "cwd": str(tmp_path)}
    stdout = io.StringIO()
    assert hooks.exit_plan(io.StringIO(json.dumps(event)), stdout) == 0
    if with_block:
        decision = json.loads(stdout.getvalue())["hookSpecificOutput"]["decision"]
        assert decision["behavior"] == "deny"
        assert "shared contracts unavailable" in decision["message"]
    else:
        assert stdout.getvalue() == ""


def test_bad_event_with_block_marker_denies_instead_of_throwing():
    stdout = io.StringIO()
    assert hooks.exit_plan(io.StringIO('{"tool_input": {"plan": "lapis-plan"'), stdout) == 0
    assert json.loads(stdout.getvalue())["hookSpecificOutput"]["decision"]["behavior"] == "deny"


EXAMPLE = ROOT / "src/shared/plan/example.plan.yaml"


@pytest.mark.parametrize("summary", [False, True], ids=["check", "summary"])
@pytest.mark.parametrize("schema", ["missing", "unparsable", "directory"])
def test_unreadable_schema_has_one_reason_and_no_traceback(tmp_path, schema, summary):
    plan = tmp_path / "plan.yaml"
    plan.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    target = {"missing": tmp_path / "absent.yaml", "unparsable": tmp_path / "bad.yaml", "directory": tmp_path}[schema]
    if schema == "unparsable":
        target.write_text("brief: [oops\n", encoding="utf-8")
    result = command(tmp_path, "plan", "check", str(plan), "--schema", str(target),
                     *(["--summary"] if summary else []))
    assert result.returncode == 2
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert "schema" in result.stderr and str(target) in result.stderr and "cannot be read" in result.stderr
    assert "Traceback" not in result.stderr


def yaml_fault(text: str) -> tuple[str, str]:
    """PyYAML's problem and its context (the "while parsing ..." lead-in) for invalid YAML `text`."""
    with pytest.raises(yaml.MarkedYAMLError) as raised:
        yaml.load(text, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    return raised.value.problem, raised.value.context


@pytest.mark.parametrize("markdown", [False, True], ids=["file", "markdown"])
def test_yaml_error_names_its_problem_and_position(tmp_path, markdown):
    text = "brief: [oops\n"
    problem, context = yaml_fault(text)
    result = command(tmp_path, "plan", "check", *input_plan(tmp_path, text, markdown))
    assert result.returncode == 2
    assert len(result.stderr.splitlines()) == 1
    assert problem in result.stderr and re.search(r" at \d+:\d+$", result.stderr.strip())
    assert context not in result.stderr            # "while parsing a flow sequence" says nothing about the fault


def test_gate_yaml_error_names_its_problem_and_position(tmp_path):
    text = "brief: [oops\n"
    problem, context = yaml_fault(text)
    plan = tmp_path / ".lapis/plans/kiln-shop-landing.yaml"
    plan.parent.mkdir(parents=True)
    plan.write_text(text, encoding="utf-8")
    result = command(tmp_path, "release", "check", "--task", "kiln-shop-landing", "--offline")
    assert result.returncode == 2
    assert len(result.stderr.splitlines()) == 1
    assert problem in result.stderr and re.search(r" at \d+:\d+$", result.stderr.strip())
    assert context not in result.stderr


@pytest.mark.parametrize("via", ["project", "option"])
@pytest.mark.parametrize("lock", ['{"fonts": "x"}', "{not json", "[]"], ids=["wrong-type", "not-json", "not-object"])
def test_corrupt_fonts_lock_has_one_reason_and_no_traceback(tmp_path, lock, via):
    plan = tmp_path / "plan.yaml"
    plan.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    path = tmp_path / ".lapis/fonts.lock.json" if via == "project" else tmp_path / "lock.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(lock, encoding="utf-8")
    result = command(tmp_path, "plan", "check", str(plan), *(["--lock", str(path)] if via == "option" else []))
    assert result.returncode == 2
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert "lock" in result.stderr and (".lapis/fonts.lock.json" if via == "project" else str(path)) in result.stderr
    assert "Traceback" not in result.stderr
