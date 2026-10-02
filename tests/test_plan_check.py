"""plan_check v0 behavior on the example plan and targeted variations."""
import copy
import io
import json
import shlex
import shutil
from pathlib import Path
import sqlite3
import time

import pytest
import yaml
from jsonschema import Draft202012Validator as V

from lapis_design import cli, hooks, plan_check, release_check
from lazuli import db

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "src" / "shared"
SCHEMA = SHARED / "plan/schema.yaml"
RULES = SHARED / "slop/rules.example.yaml"
LOCK = SHARED / "fonts/example.fonts.lock.json"


def write_plan(tmp_path, plan):
    p = tmp_path / "plan.yaml"
    p.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    return p


def base_plan():
    return yaml.safe_load((SHARED / "plan/example.plan.yaml").read_text(encoding="utf-8"))


def run(tmp_path, plan, lock=LOCK):
    return plan_check.run(write_plan(tmp_path, plan), RULES, lock, SCHEMA, tmp_path)


def ids(report, blocking=None):
    return {f["rule_id"] for f in report["findings"] if blocking is None or f["blocking"] == blocking}


def test_report_matches_finding_schema(tmp_path):
    report = run(tmp_path, base_plan())
    schema = yaml.safe_load((SHARED / "slop/finding.schema.yaml").read_text(encoding="utf-8"))
    assert list(V(schema).iter_errors(report)) == []


def test_example_plan_has_no_blocking_findings(tmp_path):
    report = run(tmp_path, base_plan())
    assert report["summary"]["blocking"] == 0
    assert "reference.profile-missing" in ids(report)          # the profile file is not in tmp_path
    assert "type.overused-neutral-grotesque" in ids(report)    # skipped until lazuli measures fonts

def test_recursive_yaml_alias_does_not_change_example_findings(tmp_path, monkeypatch, capsys):
    from lapis_design.lint import cli as lint_cli
    from lazuli import paths

    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "empty-cache")
    monkeypatch.delenv("LAZULI_DB", raising=False)
    plan = base_plan()
    cycle = []
    cycle.append(cycle)
    plan["x-notes"] = cycle
    expected = run_real(tmp_path, base_plan())["findings"]
    lint_expected = lint_cli.run(plan=tmp_path / "plan.yaml")["findings"]
    path = write_plan(tmp_path, plan)
    checked = plan_check.run(path, REAL_RULES, LOCK, SCHEMA, tmp_path)
    assert checked["findings"] == expected
    assert lint_cli.run(plan=path)["findings"] == lint_expected
    assert cli.main(["plan", "check", str(path), "--rules", str(REAL_RULES),
                     "--lock", str(LOCK), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["findings"] == expected
    assert cli.main(["slop", "lint", "--plan", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["findings"] == lint_expected
    event = {"tool_input": {"plan": harness_md(plan)}, "cwd": str(tmp_path)}
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    assert cli.main(["hook", "exit-plan"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["hookSpecificOutput"]["decision"]["behavior"] == "deny"
    assert "Traceback" not in output.err


def test_wide_shared_aliases_are_visited_once(tmp_path):
    plan = base_plan()
    shared = ["leaf"]
    for _ in range(8):
        shared = [shared] * 10
    plan["x-notes"] = shared
    plan_check.run(write_plan(tmp_path, base_plan()), REAL_RULES, LOCK, SCHEMA, tmp_path)
    path = write_plan(tmp_path, plan)
    start = time.perf_counter()
    result = plan_check.run(path, REAL_RULES, LOCK, SCHEMA, tmp_path)
    assert time.perf_counter() - start < 1
    assert result["summary"]["blocking"] == 0


def test_unrecorded_default_blocks(tmp_path):
    plan = base_plan()
    plan["tokens"]["color"]["roles"].append({"name": "clay", "role": "identity", "oklch": [0.61, 0.13, 41]})
    report = run(tmp_path, plan)
    assert "color.terracotta-accent" in ids(report, blocking=True)


def test_recorded_keep_waives_the_default(tmp_path):
    plan = base_plan()
    plan["tokens"]["color"]["roles"].append({"name": "clay", "role": "identity", "oklch": [0.61, 0.13, 41]})
    plan["defaults"].append({"id": "color.terracotta-accent", "decision": "keep", "basis": "brief",
                             "reason": "The studio's clay body is this color"})
    report = run(tmp_path, plan)
    assert "color.terracotta-accent" not in ids(report, blocking=True)
    assert any(f["rule_id"] == "color.terracotta-accent" and f["status"] == "waived" for f in report["findings"])


def test_template_sequence_is_detected(tmp_path):
    plan = base_plan()
    plan["layout"]["sections"] = [{"id": s, "archetype": s, "answers": "placeholder question"}
                                  for s in ["hero", "feature-grid", "pricing", "cta"]]
    report = run(tmp_path, plan)
    assert "layout.template-section-sequence" in ids(report)


REAL_RULES = SHARED / "slop/rules.yaml"


def run_real(tmp_path, plan):
    return plan_check.run(write_plan(tmp_path, plan), REAL_RULES, LOCK, SCHEMA, tmp_path)


def test_example_plan_is_clean_under_real_rules(tmp_path):
    report = run_real(tmp_path, base_plan())
    assert report["summary"]["blocking"] == 0
    assert any(f["rule_id"] == "color.cream-base" and f["status"] == "waived" for f in report["findings"])


def test_example_keeps_measured_neutral_grotesque_without_a_block(tmp_path, monkeypatch, capsys):
    from lazuli import cli as lazuli_cli
    from synthetic_fonts import build

    fonts = tmp_path / "fonts"
    fonts.mkdir()
    build(fonts / "Pretendard.ttf", family="Pretendard", stem=100)
    database = tmp_path / "lazuli.db"
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={fonts}")
    monkeypatch.setenv("LAZULI_DB", str(database))
    assert lazuli_cli.main(["local", "fonts"]) == 0
    capsys.readouterr()
    report = plan_check.run(write_plan(tmp_path, base_plan()), REAL_RULES, LOCK, SCHEMA, tmp_path,
                            lazuli_db=database)
    font = next(f for f in report["findings"] if f["rule_id"] == "type.overused-neutral-grotesque")
    assert font["status"] == "waived"
    assert report["summary"]["blocking"] == 0


def test_cli_uses_real_rules_and_project_lock_without_options(tmp_path, monkeypatch, capsys):
    from lazuli import paths

    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "empty-cache")
    monkeypatch.delenv("LAZULI_DB", raising=False)
    lock = tmp_path / ".lapis" / "fonts.lock.json"
    lock.parent.mkdir()
    shutil.copy(LOCK, lock)
    plan = write_plan(tmp_path, base_plan())
    monkeypatch.chdir(tmp_path)
    assert cli.main(["plan", "check", str(plan)]) == 0
    result = capsys.readouterr().out
    assert "0 blocking" in result
    assert "font.no-lock" not in result
    assert "color.cream-base" in result


def test_explicit_lock_overrides_project_lock(tmp_path, monkeypatch, capsys):
    from lazuli import paths

    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "empty-cache")
    monkeypatch.delenv("LAZULI_DB", raising=False)
    lock = tmp_path / ".lapis" / "fonts.lock.json"
    lock.parent.mkdir()
    shutil.copy(LOCK, lock)
    plan = write_plan(tmp_path, base_plan())
    assert cli.main(["plan", "check", str(plan), "--root", str(tmp_path),
                     "--lock", str(tmp_path / "missing.json"), "--format", "json"]) == 1
    assert "font.no-lock" in ids(json.loads(capsys.readouterr().out), blocking=True)


def test_cli_uses_cached_lazuli_db_and_explicit_db_overrides_env(tmp_path, monkeypatch, capsys):
    from lazuli import db, paths

    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.delenv("LAZULI_DB", raising=False)
    database = paths.db_path()
    conn = db.connect(database)
    conn.close()
    plan = write_plan(tmp_path, base_plan())
    args = ["plan", "check", str(plan), "--format", "json"]
    assert cli.main(args) == 1  # no project lock
    report = json.loads(capsys.readouterr().out)
    font = next(f for f in report["findings"] if f["rule_id"] == "type.overused-neutral-grotesque")
    assert "not among the measured local fonts" in font["observed"]
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "missing.db"))
    with pytest.raises(SystemExit) as missing_env_db:
        cli.main(args)
    assert missing_env_db.value.code == 2
    assert str(tmp_path / "missing.db") in capsys.readouterr().err
    assert cli.main([*args, "--lazuli-db", str(database)]) == 1
    assert "not among the measured local fonts" in next(
        f["observed"] for f in json.loads(capsys.readouterr().out)["findings"]
        if f["rule_id"] == "type.overused-neutral-grotesque"
    )


def test_corrupt_user_cache_db_is_ignored_once_but_explicit_and_env_databases_error(
        tmp_path, monkeypatch, capsys):
    from lapis_design import mcp_server
    from mcp.server.mcpserver.exceptions import ToolError
    from lazuli import paths

    plan = write_plan(tmp_path, base_plan())
    args = ["plan", "check", str(plan), "--format", "json"]
    lint_args = ["slop", "lint", "--plan", str(plan), "--layer", "plan"]
    baseline_code = cli.main(args)
    baseline = json.loads(capsys.readouterr().out)
    database = paths.db_path()
    database.parent.mkdir(parents=True)
    database.write_text("not a database", encoding="utf-8")

    assert cli.main(args) == baseline_code
    output = capsys.readouterr()
    assert json.loads(output.out) == baseline
    assert len(output.err.splitlines()) == 1 and "lazuli database" in output.err
    assert cli.main(lint_args) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["summary"]["blocking"] == 0
    assert len(output.err.splitlines()) == 1 and "lazuli database" in output.err
    report = mcp_server.slop_lint(plan=str(plan), layers=["plan"])
    assert report["summary"]["blocking"] == 0
    assert len(capsys.readouterr().err.splitlines()) == 1

    for db_args in (["--lazuli-db", str(database)], []):
        monkeypatch.setenv("LAZULI_DB", str(database))
        if db_args:
            monkeypatch.delenv("LAZULI_DB")
        with pytest.raises(SystemExit) as error:
            cli.main([*args, *db_args])
        assert error.value.code == 2
        assert "Traceback" not in capsys.readouterr().err
        assert cli.main([*lint_args, *db_args]) == 2
        assert "cannot be opened" in capsys.readouterr().err
        with pytest.raises(ToolError, match="cannot be opened"):
            mcp_server.slop_lint(plan=str(plan), layers=["plan"],
                                 lazuli_db=str(database) if db_args else None)
    monkeypatch.delenv("LAZULI_DB")


def test_exit_plan_uses_default_cache_and_warns_when_corrupt(tmp_path, capsys):
    from lazuli import paths

    event = {"tool_input": {"plan": harness_md(base_plan())}}
    expected = hooks.exit_plan_decision(event, tmp_path, SHARED)
    capsys.readouterr()
    database = paths.db_path()
    database.parent.mkdir(parents=True)
    database.write_text("not a database", encoding="utf-8")
    assert hooks.exit_plan_decision(event, tmp_path, SHARED) == expected
    assert len(capsys.readouterr().err.splitlines()) == 1

def _old_lazuli_database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript((ROOT / "cli/lazuli/db/migrations/0001_init.sql").read_text(encoding="utf-8"))
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    return path


def test_old_user_cache_warns_without_upgrading_plan_lint_and_hook(tmp_path, monkeypatch, capsys):
    from lazuli import paths

    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache #?.dir")
    plan = write_plan(tmp_path, base_plan())
    args = ["plan", "check", str(plan), "--format", "json"]
    baseline_code = cli.main(args)
    baseline = json.loads(capsys.readouterr().out)
    event = {"tool_input": {"plan": harness_md(base_plan())}}
    baseline_hook = hooks.exit_plan_decision(event, tmp_path, SHARED)
    capsys.readouterr()
    database = _old_lazuli_database(paths.db_path())
    before = (database.stat().st_mtime_ns, database.read_bytes())
    # The old file has no measured font features and must be treated like an absent cache.
    assert cli.main(args) == baseline_code
    output = capsys.readouterr()
    assert json.loads(output.out)["summary"] == baseline["summary"]
    assert len(output.err.splitlines()) == 1
    guidance = f"lazuli database {database} is at migration 1; this lapis-design needs {db.latest_version()}; " \
               "upgrade it with `lazuli local fonts`; this run checks without font measurements"
    assert output.err.strip() == f"warning: {guidance}"
    assert cli.main(["slop", "lint", "--plan", str(plan), "--layer", "plan"]) == 0
    assert len(capsys.readouterr().err.splitlines()) == 1
    assert hooks.exit_plan_decision(event, tmp_path, SHARED) == baseline_hook
    assert len(capsys.readouterr().err.splitlines()) == 1
    assert (database.stat().st_mtime_ns, database.read_bytes()) == before


def test_half_migrated_user_cache_warns_and_preserves_original_findings(tmp_path, monkeypatch, capsys):
    from lazuli import paths

    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    plan = write_plan(tmp_path, base_plan())
    command = ["plan", "check", str(plan), "--format", "json"]
    original_code = cli.main(command)
    original_report = json.loads(capsys.readouterr().out)
    database = paths.db_path()
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE source (id INTEGER PRIMARY KEY)")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    before = database.read_bytes()
    assert cli.main(command) == original_code
    output = capsys.readouterr()
    assert json.loads(output.out)["findings"] == original_report["findings"]
    assert output.err.strip() == (
        f"warning: lazuli database {database} is at migration 0; this lapis-design needs {db.latest_version()}; "
        "upgrade it with `lazuli local fonts`; this run checks without font measurements")
    assert database.read_bytes() == before


@pytest.mark.parametrize("selection", ["env", "option"])
def test_old_selected_database_exits_two_with_upgrade_guidance(tmp_path, monkeypatch, capsys, selection):
    database = _old_lazuli_database(tmp_path / "cache" /
                                    ("lazuli with space.db" if selection == "option" else "lazuli.db"))
    options = ["--lazuli-db", str(database)] if selection == "option" else []
    if selection == "env":
        monkeypatch.setenv("LAZULI_DB", str(database))
    else:
        monkeypatch.setenv("LAZULI_DB", str(tmp_path / "other.db"))
    plan = write_plan(tmp_path, base_plan())
    assert cli.main(["plan", "check", str(plan), *options]) == 2
    upgrade = (f"LAZULI_DB={shlex.quote(str(database))} lazuli local fonts" if selection == "option"
               else "lazuli local fonts")
    expected = (f"lazuli database {database} is at migration 1; this lapis-design needs {db.latest_version()}; "
                f"upgrade it with `{upgrade}`")
    assert capsys.readouterr().err.strip() == expected
    assert cli.main(["slop", "lint", "--plan", str(plan), "--layer", "plan", *options]) == 2
    assert capsys.readouterr().err.strip() == f"slop lint: {expected}"
    if selection == "env":
        event = {"tool_input": {"plan": harness_md(base_plan())}}
        assert hooks.exit_plan_decision(event, tmp_path, SHARED) is not None
        warning = capsys.readouterr().err
        assert warning.strip() == f"warning: {expected}; this run checks without font measurements"
    with sqlite3.connect(database) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_user_cache_directory_warns_once_and_remains_optional(tmp_path, monkeypatch, capsys):
    from lazuli import paths

    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    database = paths.db_path()
    database.mkdir(parents=True)
    plan = write_plan(tmp_path, base_plan())
    assert cli.main(["plan", "check", str(plan), "--format", "json"]) == 1
    warning = capsys.readouterr().err.splitlines()
    assert len(warning) == 1 and str(database) in warning[0] and "cannot be opened" in warning[0]


def test_cached_lazuli_db_probe_is_read_only_and_skips_invalid_bytes(tmp_path, monkeypatch, capsys):
    from lazuli import paths

    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache #?.dir")
    database = paths.db_path()
    database.parent.mkdir(parents=True)
    from lazuli import db
    db.connect(database).close()
    before = (database.read_bytes(), database.stat().st_mtime_ns)
    assert plan_check.default_lazuli_db(None) == (database, True)
    assert (database.read_bytes(), database.stat().st_mtime_ns) == before
    assert capsys.readouterr().err == ""

    database.write_bytes(b"random non-SQLite bytes")
    before = (database.read_bytes(), database.stat().st_mtime_ns)
    assert plan_check.default_lazuli_db(None) == (None, False)
    assert (database.read_bytes(), database.stat().st_mtime_ns) == before
    warning = capsys.readouterr().err.splitlines()
    assert len(warning) == 1 and "cannot be opened" in warning[0]



def test_exit_plan_denies_blocking_plan_when_env_database_is_corrupt(tmp_path, monkeypatch, capsys):
    database = tmp_path / "broken.db"
    database.write_bytes(b"random non-SQLite bytes")
    monkeypatch.setenv("LAZULI_DB", str(database))
    plan = base_plan()
    plan["tokens"]["color"]["roles"].append({"name": "clay", "role": "identity", "oklch": [0.61, 0.13, 41]})
    event = {"tool_input": {"plan": harness_md(plan)}, "cwd": str(tmp_path)}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    assert cli.main(["hook", "exit-plan"]) == 0
    output = capsys.readouterr()
    assert len(output.err.splitlines()) == 1 and "lazuli database" in output.err
    decision = json.loads(output.out)["hookSpecificOutput"]["decision"]
    assert "this run checks without font measurements" in output.err
    assert decision["behavior"] == "deny" and "color.terracotta-accent" in decision["message"]


def test_cli_documents_its_optional_inputs(capsys):
    with pytest.raises(SystemExit) as exit_status:
        cli.main(["plan", "check", "--help"])
    assert exit_status.value.code == 0
    help_text = capsys.readouterr().out
    assert "slop/rules.yaml" in help_text
    assert ".lapis/fonts.lock.json" in help_text
    assert "LAZULI_DB" in help_text and "user cache" in help_text


def test_slop_and_mcp_share_plan_check_project_lock_and_cached_db_defaults(
        tmp_path, monkeypatch, capsys):
    from lapis_design import mcp_server
    from lazuli import cli as lazuli_cli, paths
    from synthetic_fonts import build

    fonts = tmp_path / "fonts"
    fonts.mkdir()
    build(fonts / "Pretendard.ttf", family="Pretendard")
    cache = tmp_path / "cache"
    monkeypatch.setattr(paths, "cache_dir", lambda: cache)
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={fonts}")
    monkeypatch.delenv("LAZULI_DB", raising=False)
    assert lazuli_cli.main(["local", "fonts"]) == 0
    capsys.readouterr()

    project_lock = tmp_path / ".lapis" / "fonts.lock.json"
    project_lock.parent.mkdir()
    shutil.copy(LOCK, project_lock)
    plan = write_plan(tmp_path, base_plan())
    monkeypatch.chdir(tmp_path)
    assert cli.main(["plan", "check", str(plan), "--format", "json"]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert cli.main(["slop", "lint", "--plan", str(plan), "--layer", "plan"]) == 0
    linted = json.loads(capsys.readouterr().out)
    defaults = {r["id"] for r in yaml.safe_load(REAL_RULES.read_text())["rules"]
                if r["class"] == "default" and "plan" in r.get("layers", [])}
    def relevant(report):
        return {(f["rule_id"], f["status"], f["blocking"]) for f in report["findings"]
                if f["rule_id"] in defaults}
    assert relevant(linted) == relevant(checked)
    assert ("type.overused-neutral-grotesque", "waived", False) in relevant(linted)
    assert relevant(mcp_server.slop_lint(plan=str(plan), layers=["plan"])) == relevant(checked)

    # A malformed project lock must be read by both slop entry points, but explicit paths win.
    project_lock.write_text("not a lock", encoding="utf-8")
    assert cli.main(["slop", "lint", "--plan", str(plan), "--layer", "plan"]) == 2
    capsys.readouterr()
    assert cli.main(["slop", "lint", "--plan", str(plan), "--layer", "plan",
                     "--lock", str(LOCK), "--lazuli-db", str(paths.db_path())]) == 0
    assert relevant(json.loads(capsys.readouterr().out)) == relevant(checked)
    assert relevant(mcp_server.slop_lint(plan=str(plan), layers=["plan"], lock=str(LOCK),
                                         lazuli_db=str(paths.db_path()))) == relevant(checked)

    # The environment overrides cache discovery, but an explicit DB overrides the environment.
    cached_db = paths.db_path()
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "missing.db"))
    assert cli.main(["slop", "lint", "--plan", str(plan), "--layer", "plan",
                     "--lock", str(LOCK)]) == 2
    assert "missing.db" in capsys.readouterr().err
    assert cli.main(["slop", "lint", "--plan", str(plan), "--layer", "plan",
                     "--lock", str(LOCK), "--lazuli-db", str(cached_db)]) == 0
    assert relevant(json.loads(capsys.readouterr().out)) == relevant(checked)
    assert relevant(mcp_server.slop_lint(plan=str(plan), layers=["plan"], lock=str(LOCK),
                                         lazuli_db=str(cached_db))) == relevant(checked)


def test_slop_help_documents_the_default_lock_and_database(capsys):
    with pytest.raises(SystemExit) as exit_status:
        cli.main(["slop", "lint", "--help"])
    assert exit_status.value.code == 0
    help_text = capsys.readouterr().out
    assert ".lapis/fonts.lock.json" in help_text
    assert "LAZULI_DB" in help_text and "user cache" in help_text


def test_package_hit_needs_a_decision(tmp_path):
    plan = base_plan()
    plan["tokens"]["color"]["roles"].append({"name": "clay", "role": "identity", "oklch": [0.61, 0.13, 41]})
    plan["defaults"] = [d for d in plan["defaults"] if d["id"] != "color.warm-editorial"]
    report = run_real(tmp_path, plan)
    assert "color.warm-editorial" in ids(report, blocking=True)


def test_single_family_is_detected(tmp_path):
    plan = base_plan()
    for role in plan["tokens"]["type"]["roles"]:
        role["family"] = "Pretendard"
    plan["defaults"] = [d for d in plan["defaults"] if d["id"] != "type.single-neutral-sans"]
    report = run_real(tmp_path, plan)
    assert "type.single-neutral-sans" in ids(report, blocking=True)


@pytest.mark.parametrize("families", [("system-ui", "sans-serif", "-apple-system"), ("System-UI", "system-ui"),
                                      ("Pretendard", "pretendard")])
def test_single_family_counts_letter_case_and_platform_sans_names_as_one_value(tmp_path, families):
    plan = base_plan()
    plan["tokens"]["type"]["roles"] = [{"role": role, "family": family}
                                       for role, family in zip(("heading", "body", "ui"), families)]
    plan["defaults"] = [d for d in plan["defaults"] if d["id"] != "type.single-neutral-sans"]
    assert "type.single-neutral-sans" in ids(run_real(tmp_path, plan), blocking=True)


@pytest.mark.parametrize("families", [("system-ui", "ui-monospace"), ("system-ui", "Pretendard")])
def test_single_family_keeps_other_generic_keywords_and_named_faces_apart(tmp_path, families):
    plan = base_plan()
    plan["tokens"]["type"]["roles"] = [{"role": role, "family": family}
                                       for role, family in zip(("body", "code"), families)]
    plan["defaults"] = [d for d in plan["defaults"] if d["id"] != "type.single-neutral-sans"]
    assert "type.single-neutral-sans" not in ids(run_real(tmp_path, plan))


def test_single_family_reads_the_platform_sans_names_from_the_font_table(tmp_path, house_generics):
    plan = base_plan()
    plan["tokens"]["type"]["roles"] = [{"role": "heading", "family": house_generics["sans"]},
                                       {"role": "body", "family": "system-ui"}]
    plan["defaults"] = [d for d in plan["defaults"] if d["id"] != "type.single-neutral-sans"]
    assert "type.single-neutral-sans" in ids(run_real(tmp_path, plan), blocking=True)


def test_web_plan_with_every_text_role_on_the_platform_sans_blocks_without_a_font_database(tmp_path):
    plan = base_plan()
    plan["tokens"]["type"]["roles"] = [{"role": role, "family": "system-ui"} for role in ("heading", "body", "ui")]
    plan["defaults"] = [d for d in plan["defaults"] if not d["id"].startswith("type.")]
    report = run_real(tmp_path, plan)
    for rule_id in ("type.overused-neutral-grotesque", "type.single-neutral-sans"):
        [finding] = [f for f in report["findings"] if f["rule_id"] == rule_id]
        assert finding["status"] == "open" and finding["blocking"] and finding["evidence"] == {"type": "plan"}
    assert [f["rule_id"] for f in report["findings"] if f["rule_id"].startswith("type.") and f["status"] == "skipped"] == []
    plan["defaults"] = [{"id": "type.overused-neutral-grotesque", "decision": "keep", "basis": "brief",
                         "reason": "An operate screen takes the platform's own face"}]
    waived = [f for f in run_real(tmp_path, plan)["findings"] if f["rule_id"] == "type.overused-neutral-grotesque"]
    assert [(f["status"], f["blocking"]) for f in waived] == [("waived", False)]


def test_flat_scale_is_detected(tmp_path):
    plan = base_plan()
    plan["tokens"]["type"]["scale"]["ratio"] = 1.05
    report = run_real(tmp_path, plan)
    assert "type.flat-hierarchy" in ids(report, blocking=True)


def test_missing_signature_warns_in_create_mode(tmp_path):
    plan = base_plan()
    del plan["layout"]["signature"]
    report = run_real(tmp_path, plan)
    assert "layout.missing-signature" in ids(report, blocking=False)


@pytest.mark.parametrize("family", ["system-ui", "ui-monospace", "System-UI", "sans-serif", "-apple-system",
                                    "BLINKMACSYSTEMFONT"])
def test_web_generic_font_needs_no_lock_or_delivery(tmp_path, family):
    plan = base_plan()
    plan["tokens"]["type"]["roles"] = [
        {"role": "body", "family": family, "weights": [400], "scripts": ["latn"], "source": "inventory"}
    ]
    report = run(tmp_path, plan, lock=tmp_path / "absent.json")
    assert [f for f in report["findings"] if f["rule_id"].startswith("font.") and f["blocking"]] == []


@pytest.mark.parametrize("family", ["system-ui", "ui-monospace", "System-UI"])
def test_web_generic_font_with_lock_needs_no_web_delivery(tmp_path, family):
    plan = base_plan()
    plan["tokens"]["type"]["roles"] = [
        {"role": "body", "family": family, "weights": [400], "scripts": ["latn"], "source": "inventory"}
    ]
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    lock["fonts"][0]["family"] = family
    lock["fonts"][0]["delivery"] = "system-only"
    lock_path = tmp_path / "generic.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    report = run(tmp_path, plan, lock=lock_path)
    assert [f for f in report["findings"] if f["rule_id"].startswith("font.") and f["blocking"]] == []


def test_named_system_font_still_needs_web_delivery(tmp_path):
    plan = base_plan()
    plan["tokens"]["type"]["roles"] = [
        {"role": "body", "family": "Menlo", "weights": [400], "scripts": ["latn"], "source": "inventory"}
    ]
    named = json.loads(LOCK.read_text(encoding="utf-8"))
    named["fonts"][0]["family"] = "Menlo"
    named["fonts"][0]["delivery"] = "system-only"
    lock_path = tmp_path / "named.json"
    lock_path.write_text(json.dumps(named), encoding="utf-8")
    assert "font.no-web-delivery" in ids(run(tmp_path, plan, lock=lock_path), blocking=True)


def test_unlocked_font_blocks(tmp_path):
    plan = base_plan()
    plan["tokens"]["type"]["roles"][0]["family"] = "Unknown Serif"
    report = run(tmp_path, plan)
    assert "font.not-locked" in ids(report, blocking=True)


def test_missing_lock_blocks(tmp_path):
    report = run(tmp_path, base_plan(), lock=tmp_path / "absent.json")
    assert "font.no-lock" in ids(report, blocking=True)


def test_missing_lock_fix_names_the_faces_to_lock_not_the_generic_keyword(tmp_path):
    plan = base_plan()
    plan["tokens"]["type"]["roles"] = [{"role": "heading", "family": "Gowun Batang"},
                                       {"role": "body", "family": "Pretendard"},
                                       {"role": "ui", "family": "System-UI"},
                                       {"role": "code", "family": "Pretendard"}]
    report = run(tmp_path, plan, lock=tmp_path / "absent.json")
    [finding] = [f for f in report["findings"] if f["rule_id"] == "font.no-lock"]
    assert "Gowun Batang, Pretendard" in finding["fix"]
    assert "system-ui" not in finding["fix"].casefold()


def test_generic_family_table_decides_which_roles_need_a_lock(tmp_path, house_generics):
    plan = base_plan()
    plan["tokens"]["type"]["roles"] = [{"role": "body", "family": house_generics["generic"].upper()}]
    report = run(tmp_path, plan, lock=tmp_path / "absent.json")
    assert [f for f in report["findings"] if f["rule_id"].startswith("font.")] == []


def edited_lock(tmp_path, **changes):
    import json
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if key == "uses":
            lock["fonts"][0]["license"]["uses"] = value
        else:
            lock["fonts"][0][key] = value
    path = tmp_path / "fonts.lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    return path


def test_synced_or_installed_files_cannot_ship(tmp_path):
    report = run(tmp_path, base_plan(), lock=edited_lock(tmp_path, source="adobe-sync"))
    assert "font.channel-mismatch" in ids(report, blocking=True)
    report = run(tmp_path, base_plan(), lock=edited_lock(tmp_path, source="adobe-sync", delivery="adobe-web-project"))
    assert "font.channel-mismatch" not in ids(report)                  # the provider serves its own files


def test_font_use_grants(tmp_path):
    report = run(tmp_path, base_plan(), lock=edited_lock(tmp_path, uses={"web": "not-allowed"}))
    assert "font.use-not-granted" in ids(report, blocking=True)
    report = run(tmp_path, base_plan(), lock=edited_lock(tmp_path, uses={}))
    assert "font.use-unknown" in ids(report, blocking=True)            # self-hosted files ship
    report = run(tmp_path, base_plan(), lock=edited_lock(tmp_path, uses={}, delivery="google-fonts-api"))
    assert "font.use-unknown" in ids(report, blocking=False)
    assert "font.use-unknown" not in ids(report, blocking=True)


def test_an_unknown_license_overrides_recorded_grants(tmp_path):
    import json
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    lock["fonts"][0]["license"]["kind"] = "unknown"
    path = tmp_path / "fonts.lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    assert "font.use-unknown" in ids(run(tmp_path, base_plan(), lock=path), blocking=True)


def test_app_platforms_need_an_app_grant(tmp_path):
    plan = base_plan()
    plan["brief"]["platform"] = ["ios"]
    report = run(tmp_path, plan, lock=edited_lock(tmp_path, uses={"web": "allowed"}))
    assert "font.use-unknown" in ids(report, blocking=True)


def test_contract_values_must_come_from_design_md(tmp_path):
    (tmp_path / "DESIGN.md").write_text("colors:\n  paper: '#f7f5f0'\n", encoding="utf-8")
    plan = base_plan()
    plan["context"]["design"] = {"path": "DESIGN.md", "dialect": "google"}
    report = run(tmp_path, plan)
    assert "contract.value-outside-contract" in ids(report, blocking=True)


def test_path_grammar():
    doc = {"a": {"b": [{"k": "x", "v": 1}, {"k": "y", "v": 2}, {"k": "z", "v": 3}]}}
    assert plan_check.resolve(doc, "a.b[*].v") == [1, 2, 3]
    assert plan_check.resolve(doc, "a.b[?k=x|z].v") == [1, 3]
    assert plan_check.resolve(doc, "a.b[1].k") == ["y"]
    assert plan_check.resolve(doc, "a.missing[*]") == []


# ---------------------------------------------------------------- harness plan modes

HARNESS_MD = """# Plan: kiln shop landing

Some workflow notes.

```yaml lapis-plan
{block}
```

## Steps
1. Write the block to .lapis/plans/kiln-shop-landing.yaml
"""


def harness_md(plan):
    return HARNESS_MD.format(block=yaml.safe_dump(plan, allow_unicode=True).rstrip())


def test_extract_block_by_info_string():
    md = harness_md(base_plan())
    assert yaml.safe_load(plan_check.extract_lapis_block(md))["task"]["id"] == "kiln-shop-landing"


def test_extract_block_by_first_line_marker():
    md = "```yaml\n# lapis-plan: .lapis/plans/x.yaml\nversion: 0\n```\n"
    assert plan_check.extract_lapis_block(md).startswith("# lapis-plan")


def test_other_yaml_blocks_are_ignored():
    assert plan_check.extract_lapis_block("```yaml\nfoo: 1\n```\n") is None


def test_summary_lists_decisions():
    text = plan_check.summarize(base_plan())
    assert "kiln-shop-landing" in text and "type.single-neutral-sans" in text and "Signature" in text


def test_summary_command_prints_the_summary_of_a_plan_mapping(tmp_path, capsys):
    assert cli.main(["plan", "check", str(write_plan(tmp_path, base_plan())), "--summary"]) == 0
    assert capsys.readouterr().out.startswith("### Design decisions — ")


@pytest.mark.parametrize("markdown", [False, True], ids=["file", "markdown"])
@pytest.mark.parametrize("text", ["", "- brief\n- direction\n", "just words\n"], ids=["empty", "sequence", "scalar"])
def test_summary_of_a_plan_that_is_not_a_mapping_is_schema_invalid(tmp_path, capsys, text, markdown):
    if markdown:
        source = tmp_path / "harness.md"
        source.write_text(f"```yaml lapis-plan\n{text}\n```\n", encoding="utf-8")
        args = ["--from-markdown", str(source)]
    else:
        source = tmp_path / "plan.yaml"
        source.write_text(text, encoding="utf-8")
        args = [str(source)]
    assert cli.main(["plan", "check", *args, "--summary", "--format", "json"]) == 1
    output = capsys.readouterr()
    assert [f["rule_id"] for f in json.loads(output.out)["findings"]] == ["schema.invalid"]
    assert "Traceback" not in output.err


TASK = "kiln-shop-landing"
WRONG_TYPED_SECTIONS = ("task", "brief", "direction", "tokens", "layout", "references", "defaults",
                        "world_materials", "flows", "content", "claims", "context", "sources",
                        "proposed_design_changes", "output_condition")
ARRAY_SECTIONS = {"references", "defaults", "world_materials", "flows", "sources", "proposed_design_changes"}


def wrong_typed_plan(section, kind):
    """The example plan with one section replaced by a value of the wrong type."""
    plan = base_plan()
    if kind == "container":       # the other container: a list for an object section, a mapping for an array
        plan[section] = {} if section in ARRAY_SECTIONS else []
    else:
        plan[section] = {"str": "hi", "int": 5, "null": None}[kind]
    return plan


@pytest.mark.parametrize("entry", ["check", "summary", "markdown", "hook", "gate"])
@pytest.mark.parametrize("section", WRONG_TYPED_SECTIONS)
@pytest.mark.parametrize("kind", ["str", "int", "null", "container"])
def test_wrong_typed_section_is_schema_invalid_at_every_entry_point(tmp_path, capsys, entry, section, kind):
    plan = wrong_typed_plan(section, kind)
    if entry == "hook":
        decision = hooks.exit_plan_decision({"tool_input": {"plan": harness_md(plan)}}, tmp_path, SHARED)
        message = decision["hookSpecificOutput"]["decision"]["message"]
        assert "schema.invalid" in message and "could not be checked" not in message
        return
    if entry == "gate":
        stored = tmp_path / ".lapis/plans" / f"{TASK}.yaml"
        stored.parent.mkdir(parents=True)
        stored.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
        findings = release_check.run(tmp_path, TASK, offline=True)["findings"]
    else:
        if entry == "markdown":
            source = tmp_path / "harness.md"
            source.write_text(harness_md(plan), encoding="utf-8")
            args = ["--from-markdown", str(source)]
        else:
            args = [str(write_plan(tmp_path, plan))] + (["--summary"] if entry == "summary" else [])
        assert cli.main(["plan", "check", *args, "--format", "json"]) == 1
        findings = json.loads(capsys.readouterr().out)["findings"]
    assert {f["rule_id"] for f in findings} == {"schema.invalid"}
    assert section in {f["location"]["path"] for f in findings}


@pytest.mark.parametrize("task", ["hi", 5, [], None, {"title": "no id"}, {"id": 5, "title": "wrong id"}],
                         ids=["str", "int", "list", "null", "no-id", "int-id"])
def test_report_of_a_plan_without_a_usable_task_id_names_no_task(tmp_path, task):
    plan = base_plan()
    plan["task"] = task
    report = run(tmp_path, plan)
    schema = yaml.safe_load((SHARED / "slop/finding.schema.yaml").read_text(encoding="utf-8"))
    assert list(V(schema).iter_errors(report)) == []
    assert ids(report) == {"schema.invalid"}
    assert "task" not in report["target"]


def test_report_names_the_task_of_a_valid_plan(tmp_path):
    assert run(tmp_path, base_plan())["target"]["task"] == TASK


def test_summary_does_not_expand_an_alias_bomb(tmp_path, capsys):
    aliases = ('x-aliases:\n  leaf: &a0 "' + "x" * 200_000 + '"\n'
               "  level1: &a1 [" + ", ".join(["*a0"] * 9) + "]\n")
    text = aliases + yaml.safe_dump(base_plan(), allow_unicode=True).replace(
        "one_job: Let visitors see this firing's pieces and reserve one", "one_job: *a1")
    source = tmp_path / "plan.yaml"
    source.write_text(text, encoding="utf-8")
    assert cli.main(["plan", "check", str(source), "--summary", "--format", "json"]) == 1
    output = capsys.readouterr().out
    assert len(output) < 10_000
    assert [f["rule_id"] for f in json.loads(output)["findings"]] == ["schema.invalid"]


def test_hook_is_silent_without_block(tmp_path):
    assert hooks.exit_plan_decision({"tool_input": {"plan": "# plain plan"}}, tmp_path, SHARED) is None


def test_hook_is_silent_for_a_clean_block(tmp_path):
    (tmp_path / ".lapis").mkdir()
    shutil.copy(LOCK, tmp_path / ".lapis" / "fonts.lock.json")
    assert hooks.exit_plan_decision({"tool_input": {"plan": harness_md(base_plan())}}, tmp_path, SHARED) is None


def test_hook_finds_contracts_without_a_plugin_root(tmp_path, monkeypatch):
    from lapis_design import shared_dir
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "plugins" / "lapis"))
    monkeypatch.delenv("LAPIS_SHARED", raising=False)
    assert (shared_dir() / "slop" / "rules.yaml").is_file()          # full rules, not a skill view
    monkeypatch.setenv("LAPIS_SHARED", str(tmp_path / "nowhere"))
    assert shared_dir() == SHARED                                     # a bad override falls through


def test_hook_denies_blocking_findings(tmp_path):
    plan = base_plan()
    plan["tokens"]["color"]["roles"].append({"name": "clay", "role": "identity", "oklch": [0.61, 0.13, 41]})
    out = hooks.exit_plan_decision({"tool_input": {"plan": harness_md(plan)}}, tmp_path, SHARED)
    assert out["hookSpecificOutput"]["decision"]["behavior"] == "deny"
    assert "color.terracotta-accent" in out["hookSpecificOutput"]["decision"]["message"]


def test_hook_command_reads_the_event_and_prints_the_decision(tmp_path, monkeypatch, capsys):
    plan = base_plan()
    plan["tokens"]["color"]["roles"].append({"name": "clay", "role": "identity", "oklch": [0.61, 0.13, 41]})
    event = {"hook_event_name": "PermissionRequest", "tool_name": "ExitPlanMode",
             "tool_input": {"plan": harness_md(plan)}, "cwd": str(tmp_path)}
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    assert cli.main(["hook", "exit-plan"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["decision"]["behavior"] == "deny"


def test_check_subcommands_forward_their_arguments(tmp_path, capsys):
    plan = base_plan()
    plan["tokens"]["color"]["roles"].append({"name": "clay", "role": "identity", "oklch": [0.61, 0.13, 41]})
    md = tmp_path / "harness-plan.md"
    md.write_text(harness_md(plan), encoding="utf-8")
    assert cli.main(["plan", "check", "--from-markdown", str(md), "--rules", str(RULES), "--lock", str(LOCK)]) == 1
    assert "[BLOCK] color.terracotta-accent" in capsys.readouterr().out
    assert cli.main(["rights", "check", "--ledger", str(tmp_path / "none.json"), "--lock", str(tmp_path / "none.json"),
                     "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == []


# ---------------------------------------------------------------- flows

def test_example_flows_pass(tmp_path):
    report = run(tmp_path, base_plan())
    assert {i for i in ids(report) if i.startswith("flow.")} == set()


def test_flow_pairs_are_checked(tmp_path):
    plan = base_plan()
    plan["flows"][2]["pair"] = "nowhere"
    assert "flow.pair-unknown" in ids(run(tmp_path, plan), blocking=True)
    plan = base_plan()
    plan["flows"][2]["pair"] = "reserve-piece"                 # withdrawing consent does not reverse a reservation
    assert "flow.pair-kind" in ids(run(tmp_path, plan), blocking=True)
    plan = base_plan()
    plan["flows"][0]["pair"] = "firing-notices"
    assert "flow.pair-unexpected" in ids(run(tmp_path, plan), blocking=True)
    plan = base_plan()
    del plan["flows"][2]["pair"]
    assert "flow.pair-missing" in ids(run(tmp_path, plan), blocking=False)
    plan = base_plan()
    plan["flows"][1]["id"] = "reserve-piece"
    assert "flow.duplicate-id" in ids(run(tmp_path, plan), blocking=True)


def check_text(tmp_path, monkeypatch, capsys, *options):
    from lazuli import paths

    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "empty-cache")
    monkeypatch.delenv("LAZULI_DB", raising=False)
    monkeypatch.chdir(tmp_path)
    plan = write_plan(tmp_path, base_plan())
    code = cli.main(["plan", "check", str(plan), "--lock", str(LOCK), *options])
    return code, capsys.readouterr().out


def test_summary_counts_skipped_findings_and_the_text_line_says_they_were_not_judged(tmp_path, monkeypatch, capsys):
    code, text = check_text(tmp_path, monkeypatch, capsys, "--format", "json")
    report = json.loads(text)
    skipped = [f for f in report["findings"] if f["status"] == "skipped"]
    assert skipped and report["summary"]["skipped"] == len(skipped)
    assert all(not f["blocking"] for f in skipped)
    code, text = check_text(tmp_path, monkeypatch, capsys)
    summary = report["summary"]
    assert text.splitlines()[0] == (f"plan_check {plan_check.VERSION}: {summary['blocking']} blocking, "
                                    f"{summary['total']} total, {len(skipped)} skipped: not judged")


def test_text_line_leaves_out_skipped_when_no_finding_was_skipped(tmp_path, monkeypatch, capsys):
    rules = tmp_path / "rules.yaml"
    rules.write_text(yaml.safe_dump({"version": 0, "as_of": "2026-09", "rules": []}), encoding="utf-8")
    code, text = check_text(tmp_path, monkeypatch, capsys, "--rules", str(rules), "--format", "json")
    summary = json.loads(text)["summary"]
    assert summary["skipped"] == 0 and summary["total"] > 0
    code, text = check_text(tmp_path, monkeypatch, capsys, "--rules", str(rules))
    assert text.splitlines()[0] == (f"plan_check {plan_check.VERSION}: {summary['blocking']} blocking, "
                                    f"{summary['total']} total")
