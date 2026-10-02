"""tools/eval scoring: a site folder that is a link out of the project (G65), the evaluation font database
that pins what the checkers read (G52), and runs whose event log shows an Adobe tool call (G63)."""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from evallint_support import (FONT_DB, ROOT, TASK, evalkit, event_log, load, make_font_db, make_out, run_record,
                              unpin)

score = load("score")
review = load("review")
share = load("share")
RUN = evalkit.run_id(TASK, 1, "with")
NO_CHECKS = {"kiln-landing-ko": {"checks": {"render": False, "lint": False, "behavior": None}}}
LINT_ONLY = {"kiln-landing-ko": {"checks": {"render": False, "lint": True, "behavior": None}}}


# ------------------------------------------------------------------ G65: the site folder is a link out

@pytest.fixture
def linked_site(tmp_path):
    outside = tmp_path / "elsewhere" / "site"
    outside.mkdir(parents=True)
    (outside / "index.html").write_text("<p>someone else's page</p>")
    (outside / "secret.txt").write_text("TOP-SECRET")
    project = tmp_path / "project"
    project.mkdir()
    (project / "public").symlink_to(outside, target_is_directory=True)
    return project


def test_a_site_folder_that_is_a_link_out_of_the_project_is_not_the_site(linked_site):
    assert score.find_site_root(linked_site) is None
    assert score.skipped_site_roots(linked_site) == ["public"]
    (linked_site / "dist").mkdir()
    (linked_site / "dist" / "index.html").write_text("<p>ok</p>")
    assert score.find_site_root(linked_site) == linked_site / "dist"
    assert score.skipped_site_roots(linked_site) == ["public"]


def test_a_root_that_is_itself_a_link_out_is_reported_as_the_whole_root(linked_site):
    assert evalkit.links_outside(linked_site / "public", linked_site) == ["."]
    assert evalkit.links_outside(linked_site / "public") == []          # without a base the root is its own base


def test_the_review_copy_refuses_a_site_folder_that_is_itself_a_link_out(linked_site, tmp_path):
    with pytest.raises(evalkit.KitError, match="itself a link"):
        review._copy_site(linked_site / "public", tmp_path / "copy", linked_site)
    assert not (tmp_path / "copy").exists()


def test_a_review_of_a_score_that_recorded_a_linked_site_root_stops_before_writing_anything(tmp_path):
    out = make_out(tmp_path / "out")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "index.html").write_text("<p>x</p>")
    (outside / "secret.txt").write_text("TOP-SECRET")
    for arm in evalkit.ARMS:
        run_dir = out / "runs" / evalkit.run_id(TASK, 1, arm)
        if arm == "with":
            (run_dir / "project" / "public").symlink_to(outside, target_is_directory=True)   # as older score.py did
        else:
            (run_dir / "project" / "index.html").write_text("<p>hi</p>")
        evalkit.write_json(run_dir / "score.json", {"font_db": FONT_DB,
                                                    "site": {"root": "project/public" if arm == "with" else "project"}})
    with pytest.raises(evalkit.KitError, match="itself a link"):
        review.build(out, 1, evalkit.load_tasks())
    assert not (out / "review").exists() and not review.key_path(out).exists()


def test_scoring_a_project_whose_site_folder_is_a_link_out_says_no_site_and_names_the_folder(linked_site, tmp_path):
    out = tmp_path / "out"
    run_dir = out / "runs" / RUN
    run_dir.mkdir(parents=True)
    linked_site.rename(run_dir / "project")
    evalkit.write_json(run_dir / "run.json", run_record("with", 1))
    db = evalkit.evaluation_font_db(make_font_db(tmp_path / "eval.db"))
    result = score.score_run(run_dir, NO_CHECKS, font_db=db, sig_key=tmp_path / "sig.key")
    assert result["site"] == {"root": None, "refused_links": [], "skipped_roots": ["public"]}


# ------------------------------------------------------------------ G52: the evaluation font database

def test_an_evaluation_database_is_described_by_its_hash_and_counts(tmp_path):
    path = make_font_db(tmp_path / "eval.db")
    record = evalkit.evaluation_font_db(path)
    assert record["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (record["faces"], record["families"]) == (2, 2) and record["path"] == path.resolve()


def garbage(tmp: Path) -> Path:
    (tmp / "d.db").write_bytes(b"this is not a database")
    return tmp / "d.db"


@pytest.mark.parametrize("problem,build", [
    ("Adobe Fonts face", lambda tmp: make_font_db(tmp / "d.db", ("Some Face",), origin="adobe-sync")),
    ("Adobe Fonts face", lambda tmp: make_font_db(tmp / "d.db", ("Some Face",), file_prefix="coretext:")),
    ("no fonts", lambda tmp: make_font_db(tmp / "d.db", ())),
    ("cannot be read", garbage),
    ("not a file", lambda tmp: tmp / "missing.db"),
])
def test_a_database_that_is_not_an_evaluation_database_is_refused(tmp_path, problem, build):
    with pytest.raises(evalkit.KitError, match=problem):
        evalkit.evaluation_font_db(build(tmp_path))


def test_a_database_with_writes_that_are_not_in_the_file_is_refused(tmp_path):
    path = make_font_db(tmp_path / "eval.db")
    path.with_name("eval.db-wal").write_bytes(b"pending")
    with pytest.raises(evalkit.KitError, match="wal"):
        evalkit.evaluation_font_db(path)


def test_a_database_inside_the_repository_is_refused():
    with pytest.raises(evalkit.KitError, match="inside the repository"):
        evalkit.evaluation_font_db(ROOT / "eval-fonts.db")


def test_the_checkers_environment_points_every_per_user_path_at_scratch_or_the_evaluation_database(
        tmp_path, monkeypatch):
    user_home = tmp_path / "user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(user_home / ".cache"))
    monkeypatch.setenv("LAZULI_DB", str(user_home / "own.db"))
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={user_home}")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    eval_db = make_font_db(tmp_path / "eval.db")
    env = score.checker_env(scratch, eval_db, tmp_path / "sig.key")
    assert env["LAZULI_DB"] == str(eval_db)
    where = subprocess.run(
        [sys.executable, "-c", "from lazuli import paths, scan; from lapis_design import sig_key; "
         "print(paths.cache_dir()); print(paths.db_path()); print(sig_key.key_path()); "
         "print([(r.origin, str(r.path)) for r in scan.roots()])"],
        env=env, capture_output=True, text=True, timeout=60)
    cache, db_path, _, roots, *_ = where.stdout.split("\n")
    assert where.returncode == 0, where.stderr
    assert db_path == str(eval_db)
    assert str(user_home) not in cache and cache.startswith(str(scratch))
    assert roots == str([("user", str(scratch / "fonts"))])                      # not the operator's folders, not the OS's
    assert list((scratch / "fonts").iterdir()) == []


def poison_user_caches(home):
    """Garbage where lazuli keeps its database on macOS and on Linux, so a checker that looked would say so."""
    for path in (home / "Library" / "Caches" / "lazuli" / "lazuli.db", home / ".cache" / "lazuli" / "lazuli.db"):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"this is not a database")


def test_no_checker_looks_for_the_users_own_database(tmp_path, monkeypatch):
    user_home = tmp_path / "user"
    poison_user_caches(user_home)
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(user_home / ".cache"))
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<p>hi</p>")
    # the control: without the pin the same lint does look, finds the garbage, and says so
    control = subprocess.run([sys.executable, "-m", "lapis_design.cli", "slop", "lint", "--source", str(site)],
                             capture_output=True, text=True, timeout=120, env=dict(os.environ))
    assert "cannot be opened" in control.stderr, control.stderr
    out = tmp_path / "out"
    run_dir = out / "runs" / RUN
    (run_dir / "project").mkdir(parents=True)
    (run_dir / "project" / "index.html").write_text("<p>hi</p>")
    evalkit.write_json(run_dir / "run.json", run_record("with", 1))
    db = evalkit.evaluation_font_db(make_font_db(tmp_path / "eval.db"))
    result = score.score_run(run_dir, LINT_ONLY, font_db=db, sig_key=tmp_path / "sig.key")
    assert result["checkers"]["lint"]["status"] == "ok", result["checkers"]["lint"]
    log = (run_dir / "score" / "logs" / "lint.txt").read_text()
    assert "cannot be opened" not in log and "warning" not in log, log
    assert result["font_db"] == {key: db[key] for key in ("sha256", "faces", "families")}


def test_scoring_needs_the_evaluation_database_and_summaries_do_not(tmp_path, capsys):
    out = make_out(tmp_path / "out")
    for arm in evalkit.ARMS:
        (out / "runs" / evalkit.run_id(TASK, 1, arm) / "score.json").unlink()
    assert score.main([str(out)]) == 2
    assert "--font-db is required" in capsys.readouterr().err
    assert score.main([str(out), "--summary-only"]) == 0


# ------------------------------------------------------------------ G63: Adobe tool calls

MCP_CALL = {"type": "item.completed", "item": {"id": "item_2", "type": "mcp_tool_call", "server": "codex_apps",
                                                 "tool": "adobe_font_search", "arguments": {"query": "serif"},
                                                 "status": "completed"}}
PREFIXED_CALL = {"type": "item.started", "item": {"id": "item_3", "type": "tool_call",
                                                    "name": "mcp__codex_apps__adobe_font_details"}}
NOT_CALLS = [
    {"type": "item.completed", "item": {"type": "agent_message", "text": "I will not use Adobe Fonts here."}},
    {"type": "item.completed", "item": {"type": "command_execution", "command": "lazuli local fonts --origin adobe-sync",
                                          "aggregated_output": "adobe-sync 0"}},
    {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "docs", "tool": "lookup",
                                          "arguments": {"name": "Adobe Caslon"}, "result": {"text": "Adobe"}}},
    {"type": "item.completed", "item": {"type": "web_search", "query": "adobe fonts terms"}},
]


def test_an_adobe_tool_call_is_found_in_either_event_shape_and_nothing_else_is(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert evalkit.adobe_tool_calls(run_dir) == []                          # no log
    (run_dir / "events.jsonl").write_text("not json\n" + event_log(*NOT_CALLS), encoding="utf-8")
    assert evalkit.adobe_tool_calls(run_dir) == []
    (run_dir / "events.jsonl").write_text(event_log(*NOT_CALLS, MCP_CALL, PREFIXED_CALL), encoding="utf-8")
    assert evalkit.adobe_tool_calls(run_dir) == ["adobe_font_search", "mcp__codex_apps__adobe_font_details"]


def called_out(tmp_path, **kwargs):
    return make_out(tmp_path / "out", events={"with": event_log(*NOT_CALLS, MCP_CALL)}, **kwargs)


def test_score_and_summary_refuse_a_run_that_called_an_adobe_tool_before_touching_anything(tmp_path, capsys):
    out = called_out(tmp_path)
    db = make_font_db(tmp_path / "eval.db")
    run_dir = out / "runs" / RUN
    (run_dir / "score.json").write_text("{}")                                 # --rescore would replace it
    assert score.main([str(out), "--font-db", str(db), "--rescore"]) == 2
    assert "Adobe tool" in capsys.readouterr().err
    assert (run_dir / "score.json").read_text() == "{}" and not (run_dir / "score").exists()
    (out / "summary.md").write_text("old")
    assert score.main([str(out), "--summary-only"]) == 2
    assert (out / "summary.md").read_text() == "old"
    with pytest.raises(evalkit.KitError, match="Adobe tool"):
        score.score_run(run_dir, LINT_ONLY, font_db=evalkit.evaluation_font_db(db))


def test_the_export_and_the_review_refuse_a_run_that_called_an_adobe_tool(tmp_path):
    out = called_out(tmp_path)
    with pytest.raises(evalkit.KitError, match="Adobe tool"):
        share.export(out, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()
    with pytest.raises(evalkit.KitError, match="Adobe tool"):
        review.build(out, 1, evalkit.load_tasks())
    assert not (out / "review").exists()


def test_a_run_whose_log_only_talks_about_adobe_is_still_summarized(tmp_path):
    out = make_out(tmp_path / "out", events={"with": event_log(*NOT_CALLS)})
    (out / "summary.md").unlink()
    assert score.main([str(out), "--summary-only"]) == 0
    assert (out / "summary.md").is_file()


# ------------------------------------------------------------------ G99: a score without a font_db record is not a score

def test_a_score_without_a_font_db_record_is_scored_again_and_needs_the_database(tmp_path, capsys):
    out = unpin(make_out(tmp_path / "out"))
    assert score.main([str(out)]) == 2
    assert "--font-db is required" in capsys.readouterr().err


def test_scoring_again_with_the_database_pins_every_score_it_replaces(tmp_path, capsys):
    out = unpin(make_out(tmp_path / "out"))
    db = evalkit.evaluation_font_db(make_font_db(tmp_path / "eval.db"))
    assert score.main([str(out), "--font-db", str(db["path"])]) == 0       # the folder has no site: nothing runs
    for run_dir in evalkit.list_runs(out):
        assert evalkit.read_json(run_dir / "score.json")["font_db"]["sha256"] == db["sha256"]
    assert "skip" not in capsys.readouterr().out


def test_scores_that_record_the_database_are_kept_without_it(tmp_path, capsys):
    out = make_out(tmp_path / "out")
    assert score.main([str(out)]) == 0
    assert "skip" in capsys.readouterr().out


def test_summaries_the_review_and_the_export_refuse_a_score_without_a_font_db_record(tmp_path, capsys):
    out = unpin(make_out(tmp_path / "out"))
    (out / "summary.md").write_text("old")
    assert score.main([str(out), "--summary-only"]) == 2
    assert "font_db" in capsys.readouterr().err and (out / "summary.md").read_text() == "old"
    with pytest.raises(evalkit.KitError, match="font_db"):
        review.build(out, 1, evalkit.load_tasks())
    assert not (out / "review").exists() and not review.key_path(out).exists()
    with pytest.raises(evalkit.KitError, match="font_db"):
        share.export(out, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()


# ------------------------------------------------------------------ G108: inputs that leave the project, unread links

@pytest.fixture
def linked_inputs(tmp_path):
    """A project whose plan and fonts lock are links to files elsewhere."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "plan.yaml").write_text("version: 0\nSECRET_KEY: v\n")
    (outside / "fonts.lock.json").write_text('{"SECRET": 1}')
    project = tmp_path / "project"
    (project / ".lapis" / "plans").mkdir(parents=True)
    (project / "index.html").write_text("<p>hi</p>")
    (project / ".lapis" / "plans" / f"{TASK}.yaml").symlink_to(outside / "plan.yaml")
    (project / ".lapis" / "fonts.lock.json").symlink_to(outside / "fonts.lock.json")
    return project


def test_a_plan_or_lock_that_is_a_link_out_of_the_project_is_not_used(linked_inputs):
    assert score.find_plan(linked_inputs, TASK) == (None, [])
    assert score.find_lock(linked_inputs) is None
    assert score.outside_inputs(linked_inputs, TASK) == {"plan": True, "lock": True}


def test_a_plan_or_lock_that_is_a_link_inside_the_project_is_used(linked_inputs):
    (linked_inputs / "own-plan.yaml").write_text("version: 0\n")
    (linked_inputs / "own-lock.json").write_text("{}")
    for name, target in ((f".lapis/plans/{TASK}.yaml", "own-plan.yaml"), (".lapis/fonts.lock.json", "own-lock.json")):
        (linked_inputs / name).unlink()
        (linked_inputs / name).symlink_to(linked_inputs / target)
    assert score.find_plan(linked_inputs, TASK)[0] == linked_inputs / ".lapis" / "plans" / f"{TASK}.yaml"
    assert score.find_lock(linked_inputs) == linked_inputs / ".lapis" / "fonts.lock.json"
    assert score.outside_inputs(linked_inputs, TASK) == {"plan": False, "lock": False}


def scored_project(tmp_path, project):
    run_dir = tmp_path / "out" / "runs" / RUN
    run_dir.mkdir(parents=True)
    project.rename(run_dir / "project")
    evalkit.write_json(run_dir / "run.json", run_record("with", 1))
    db = evalkit.evaluation_font_db(make_font_db(tmp_path / "eval.db"))
    return run_dir, score.score_run(run_dir, LINT_ONLY, font_db=db, sig_key=tmp_path / "sig.key")


def test_lint_is_given_neither_a_plan_nor_a_lock_that_leave_the_project(linked_inputs, tmp_path):
    run_dir, result = scored_project(tmp_path, linked_inputs)
    assert result["plan"]["status"] == "outside" and result["lock"] == {"status": "outside"}
    assert result["checkers"]["lint"]["status"] == "ok"
    assert result["checkers"]["lint"]["layers"]["plan"]["code"] == "plan outside"
    command = (run_dir / "score" / "logs" / "lint.txt").read_text().splitlines()[0]
    assert "--plan" not in command and "--lock" not in command and "elsewhere" not in command


@pytest.fixture
def source_with_links(tmp_path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "index.html").write_text("<p>hi</p>")
    (project / "src" / "card.css").write_text(".card { background: #1F2937; }\n")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "secret.css").write_text(".secret { color: #AB12CD; }\n")
    return project


def test_a_source_layer_whose_links_lint_did_not_read_is_not_scored_and_adds_no_count(source_with_links, tmp_path):
    (source_with_links / "src" / "secret.css").symlink_to(tmp_path / "elsewhere" / "secret.css")
    _, result = scored_project(tmp_path, source_with_links)
    lint = result["checkers"]["lint"]
    assert lint["unread_links"] == {"source": ["src/secret.css"]}
    assert lint["layers"]["source"]["status"] == "not scored" and lint["layers"]["source"]["code"] == "source links unread"
    row = score.row_from(run_record("with", 1), result)
    assert row["source_status"] == "source links unread" and row["source_blocking"] is None and row["lint_total"] is None


def test_a_source_layer_with_every_link_read_is_scored(source_with_links, tmp_path):
    (source_with_links / "src" / "alias.css").symlink_to("card.css")      # relative: the folder moves
    _, result = scored_project(tmp_path, source_with_links)
    assert "unread_links" not in result["checkers"]["lint"]
    assert result["checkers"]["lint"]["layers"]["source"]["status"] == "ok"


# ------------------------------------------------------------------ G112: the checkers' environment is the agents' allow-list

def test_the_checkers_take_only_the_allow_listed_variables_of_the_operators_environment(tmp_path, monkeypatch):
    for name, value in {"OPENAI_API_KEY": "sk-secret", "GITHUB_TOKEN": "ghp_secret", "HTTPS_PROXY": "http://u:pw@proxy.test:3128",
                        "SSH_AUTH_SOCK": "/tmp/agent.sock", "LAZULI_SANDOLL_SETTING": "x", "LAPIS_OPERATOR_SETTING": "y",
                        "XDG_CONFIG_HOME": "/home/u/.config", "PYTHONPATH": "/home/u/lib",
                        "LC_ALL": "C.UTF-8", "LANG": "en_US.UTF-8", "TERM": "xterm-256color"}.items():
        monkeypatch.setenv(name, value)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env = score.checker_env(scratch, make_font_db(tmp_path / "eval.db"), tmp_path / "sig.key")
    own = {"HOME", "XDG_CACHE_HOME", "LAZULI_DB", "LAZULI_FONT_ROOTS", "LAPIS_SIG_KEY_FILE", "PLAYWRIGHT_BROWSERS_PATH"}
    assert {name for name in env if not name.startswith("LC_")} <= {"PATH", "LANG", "TERM"} | own
    assert env["LC_ALL"] == "C.UTF-8" and env["LANG"] == "en_US.UTF-8" and env["TERM"] == "xterm-256color"
    assert env["PATH"] == os.environ["PATH"]
