"""tools/eval/share.py builds every exported file from an allow-list of fields and field types: what a
record holds beyond it (unknown fields, text, names, keys) never leaves, reasons become codes, lists of
names become counts, and the summaries are built again from what was exported."""
import csv
import io

import pytest

from evallint_support import DIGEST, TASK, evalkit, load, make_out, score_record, unpin

share = load("share")
RUN = f"{TASK}.r1.with"
OTHER = f"{TASK}.r1.without"


@pytest.fixture
def account(tmp_path, monkeypatch):
    """Become `name` for one test: HOME, and the variables getpass reads, name that account."""
    def become(name: str):
        home = tmp_path / "homes" / name
        home.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        for variable in ("LOGNAME", "USER"):
            monkeypatch.setenv(variable, name)
        for variable in ("LNAME", "USERNAME"):
            monkeypatch.delenv(variable, raising=False)
        return home
    return become


def exported(dest, name, run=RUN):
    return evalkit.read_json(dest / "runs" / run / name)


def everything(dest) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(dest.rglob("*")) if p.is_file())


def edit(out, name, change, run=RUN):
    path = out / "runs" / run / name
    record = evalkit.read_json(path)
    change(record)
    evalkit.write_json(path, record)


@pytest.mark.parametrize("name", ["root", "runner", "copy", "site", "mark", "plan", "al"])
def test_an_account_named_like_a_key_a_code_word_or_two_letters_does_not_stop_the_export(tmp_path, account, name):
    account(name)
    out = make_out(tmp_path / "out")
    dest = tmp_path / "dest"
    share.export(out, dest)
    record = exported(dest, "score.json")
    assert record["site"] == {"root": "project", "refused_link_count": 0}          # `root` is a key here
    assert list(record["copy"]["rules"]) == ["copy.vague-cta"]                      # `copy` is a key too
    assert record["checkers"]["lint"]["code"] == "plan rejected"                    # `plan` is an ordinary word


# What each case plants in a record, and the markers that must not be in anything exported. A "text" case
# also writes files next to the records.
def unknown_fields(docs):
    docs["run.json"]["notes"] = "MODEL-SAID: the landing page I built for Kiln"
    docs["run.json"]["extra"] = {"deep": [{"transcript": ["USER-TURN: please fix", "ASSISTANT-TURN: done"]}]}
    docs["score.json"]["site"]["owner"] = "OWNER-NAME opuser"


def machine_ids(docs):
    docs["run.json"]["session"] = {"turns": 3, "errors": ["stream error: 401 from https://gw.corp-internal.example for carol@corp-internal.example"],
                                   "thread_id": "THREAD-ID-0199"}
    docs["run.json"]["pid"] = 424242
    docs["run.json"]["host"] = "alices-macbook-pro.local"
    docs["manifest.json"]["codex"] = {"version": "codex-cli 0.0", "bin": "/opt/acme-client-x/tools/bin/codex"}
    docs["manifest.json"]["shared_codex_files"] = {"AGENTS.md": "0123456789abcdef", "company-rules.md": "fedcba9876543210"}


def checker_text(docs):
    checkers = docs["score.json"]["checkers"]
    checkers["lint"]["reason"] = r"cannot read /mnt/c/Users/dana/x.yaml and C:\Users\erin\x.yaml and /root/.codex/auth.json"
    checkers["lint"]["plan_problem"] = "plan rejected: brief.subject 'MODEL-WROTE: Kiln, the oven' is too long"
    checkers["lint"]["layers"]["plan"]["reason"] = "see /private/var/folders/zz/T/gina-secret"
    docs["score.json"]["plan"] = {"status": "found", "path": "acme-q4-pricing-leak.yaml", "other_plans": ["acme-q4-pricing-leak.yaml"]}
    docs["score.json"]["site"]["refused_links"] = ["assets/passwd-of-box7.txt"]
    docs["score.json"]["site"]["skipped_roots"] = ["box7-site"]


def keys(docs):
    docs["run.json"]["session"] = {"tools_run": {"opuser did this": 1, "KEY-MARKER notes.txt": 2, "lapis-design plan check": 1}}
    docs["run.json"]["usage"] = {"input_tokens": 5, "KEY-MARKER-USAGE": 6}
    docs["score.json"]["copy"]["rules"] = {"copy.vague-cta": 1, "KEY-MARKER-RULE": 2}
    docs["manifest.json"]["skill_digests"] = {"lapis": DIGEST, "KEY-MARKER-SKILL": DIGEST}


def numbers_with_text(docs):
    docs["run.json"]["usage"] = {"input_tokens": "12,345 (SEE /srv/data/secretproj)", "output_tokens": "5"}
    docs["run.json"]["duration_s"] = "60 s at /srv/secretproj"
    docs["manifest.json"]["seed"] = "7 secretproj"


def skill_names(docs):
    docs["run.json"]["skills"] = ["lapis", "client-acme-style"]
    docs["run.json"]["session"] = {"skills_read": ["lapis", "private-brand-voice"], "skills_not_read": ["client-acme-style"]}
    docs["run.json"]["isolation"] = {"verified": False, "expected": ["lapis"], "visible": ["lapis", "client-acme-style"],
                                     "outside_before": ["private-brand-voice"], "disabled": ["/h/.agents/skills/private-brand-voice"],
                                     "reason": "skills still visible after switching off the outside ones: client-acme-style"}
    docs["manifest.json"]["tasks"] = {TASK: {"skills": ["lapis", "client-acme-style"]}}


CASES = {
    "unknown fields": (unknown_fields, ["MODEL-SAID", "USER-TURN", "ASSISTANT-TURN", "OWNER-NAME"]),
    "machine ids and errors": (machine_ids, ["corp-internal", "carol@", "THREAD-ID", "424242", "alices-macbook", "acme-client-x",
                                              "company-rules", "0123456789abcdef"]),
    "checker text and file names": (checker_text, ["dana", "erin", "/root", "gina-secret", "MODEL-WROTE", "acme-q4", "box7"]),
    "keys": (keys, ["opuser did this", "KEY-MARKER"]),
    "numbers carrying text": (numbers_with_text, ["secretproj"]),
    "skill names": (skill_names, ["client-acme-style", "private-brand-voice"]),
}


@pytest.mark.parametrize("case", CASES)
def test_nothing_a_record_holds_beyond_the_allow_list_reaches_the_export(tmp_path, account, case):
    account("opuser")
    mutate, markers = CASES[case]
    out = make_out(tmp_path / "out")
    docs = {name: evalkit.read_json(path) for name, path in (
        ("run.json", out / "runs" / RUN / "run.json"), ("score.json", out / "runs" / RUN / "score.json"),
        ("manifest.json", out / "manifest.json"))}
    mutate(docs)
    evalkit.write_json(out / "runs" / RUN / "run.json", docs["run.json"])
    evalkit.write_json(out / "runs" / RUN / "score.json", docs["score.json"])
    evalkit.write_json(out / "manifest.json", docs["manifest.json"])
    dest = tmp_path / "dest"
    share.export(out, dest)
    text = everything(dest)
    assert [m for m in markers if m in text] == []
    assert "opuser" not in text


def test_text_files_carry_only_the_command_lines_and_the_task_id(tmp_path, account):
    account("opuser")
    out = make_out(tmp_path / "out")
    run_dir = out / "runs" / RUN
    (run_dir / "command.txt").write_text(
        "# run from /Users/opuser/x\nSECRET-LINE opuser host=buildbox-17.corp\ncodex exec --profile opuser\n", encoding="utf-8")
    (run_dir / "prompt.txt").write_text(f"Task id: {TASK}\nPROMPT-TEXT written for opuser\n", encoding="utf-8")
    dest = tmp_path / "dest"
    notes = []
    written = share.export(out, dest, notes)
    text = everything(dest)
    assert "opuser" not in text and "buildbox" not in text and "PROMPT-TEXT" not in text and "SECRET-LINE" not in text
    assert f"runs/{RUN}/prompt.txt" not in written and f"runs/{RUN}/command.txt" not in written
    assert len(notes) == 1 and RUN in notes[0]


def test_the_command_and_the_prompt_keep_what_the_kit_wrote_and_show_the_executable_as_codex(tmp_path, account):
    run = load("run")
    account("opuser")
    out = make_out(tmp_path / "out")
    run_dir = out / "runs" / RUN
    cmd = run.codex_command("/opt/acme-client-x/bin/codex", run_dir / "project", run_dir / "last-message.txt",
                            model="test-model", effort="high", sandbox="workspace-write", network=True,
                            add_dirs=[run_dir / "home"], disabled=["/h/.agents/skills/a/SKILL.md", "/h/.agents/skills/a"])
    written = (run.command_header(out / "bin", run_dir) + run.format_command(cmd, elide=True, run_dir=run_dir)
               + " \\\n  < prompt.txt\n")
    (run_dir / "command.txt").write_text(written, encoding="utf-8")
    (run_dir / "prompt.txt").write_text(evalkit.load_tasks()[TASK]["prompt"], encoding="utf-8")
    dest = tmp_path / "dest"
    share.export(out, dest)
    assert (dest / "runs" / RUN / "command.txt").read_text(encoding="utf-8") == \
        written.replace("/opt/acme-client-x/bin/codex", "codex")
    assert "-c features.apps=false" in written and "skills.config=[... 2 paths switched off ...]" in written
    assert (dest / "runs" / RUN / "prompt.txt").read_text(encoding="utf-8") == f"Task id: {TASK}\n"


def test_reasons_become_codes_and_lists_of_names_become_counts(tmp_path, account):
    account("opuser")
    out = make_out(tmp_path / "out")

    def planted(record):
        record["plan"] = {"status": "found", "other_plans": ["a.yaml", "b.yaml"]}
        record["site"]["refused_links"] = ["x", "y", "z"]
        record["site"]["skipped_roots"] = ["public"]
        record["checkers"]["lint"].update(reason="cannot read /srv/x", plan_problem="plan invalid: x",
                                          unread_links={"source": ["src/a.css", "pages/"], "corpus": []})
        record["checkers"]["behavior_check"] = {"status": "not scored", "code": "a code score.py never wrote",
                                                "reason": "boom", "exit": 2, "seconds": 1.5}
        record["checkers"]["render_check"] = {"status": "ok", "plan_ignored": "plan invalid: x", "viewports": 9}
    edit(out, "score.json", planted)
    edit(out, "run.json", lambda r: r.update(session={"errors": ["a", "b"], "thread_id": "t", "turns": 4, "commands": 7,
                                                      "tools_run": {"lapis-design plan check": 2, "lapis-design render check": 1,
                                                                    "lazuli local fonts": 1, "lapis-design nonsense words": 4,
                                                                    "rm -rf": 1}}))
    dest = tmp_path / "dest"
    share.export(out, dest)
    score = exported(dest, "score.json")
    assert score["plan"] == {"status": "found", "other_plan_count": 2}
    assert score["site"] == {"root": "project", "refused_link_count": 3, "skipped_root_count": 1}
    lint = score["checkers"]["lint"]
    assert "reason" not in lint and lint["plan_problem"] is True and lint["unread_links"] == {"source": 2, "corpus": 0}
    assert score["checkers"]["behavior_check"] == {"status": "not scored", "code": "other", "exit": 2, "seconds": 1.5}
    assert score["checkers"]["render_check"] == {"status": "ok", "viewports": 9, "plan_ignored": True}
    assert exported(dest, "run.json")["session"] == {
        "turns": 4, "commands": 7, "error_count": 2,
        "tools_run": {"lapis-design plan": 2, "lapis-design render": 1, "lazuli local": 1, "other": 5}}


def test_the_manifest_shows_the_settings_and_hashes_and_counts_the_shared_codex_files(tmp_path, account):
    account("opuser")
    out = make_out(tmp_path / "out")
    evalkit.write_json(out / "manifest.json", {
        "version": 1, "created_at": "2026-10-02T09:06:08Z", "dry_run": False, "seed": 7, "model": "gpt-test", "effort": "high",
        "sandbox": "workspace-write", "network": False, "timeout_s": 2400,
        "codex": {"bin": "/opt/x/codex", "version": "codex-cli 0.159.3"}, "shared_codex_files": {"AGENTS.md": "0123456789abcdef"},
        "repo": {"commit": "a" * 40, "dirty_sources": False}, "lapis_design": "lapis-design 0.1.4",
        "tasks": {TASK: {"prompt_sha256": DIGEST, "skills": ["lapis"]}}, "tasks_file_sha256": DIGEST,
        "skill_digests": {"lapis": DIGEST}, "order": [{"task": TASK, "replicate": 1, "arm": "with", "order": 1, "id": RUN}],
        "finished_at": "2026-10-02T10:00:00Z"})
    dest = tmp_path / "dest"
    share.export(out, dest)
    manifest = evalkit.read_json(dest / "manifest.json")
    assert manifest["codex"] == {"version": "codex-cli 0.159.3"} and manifest["shared_codex_file_count"] == 1
    assert manifest["model"] == "gpt-test" and manifest["seed"] == 7 and manifest["repo"]["commit"] == "a" * 40
    assert manifest["order"] == [{"task": TASK, "replicate": 1, "arm": "with", "order": 1, "id": RUN}]
    assert "AGENTS" not in everything(dest)


def test_a_model_name_that_holds_the_account_name_stops_the_export_and_writes_nothing(tmp_path, account):
    account("opuser")
    out = make_out(tmp_path / "out")
    edit(out, "run.json", lambda r: r.update(model="opuser-finetune-2"))
    dest = tmp_path / "dest"
    with pytest.raises(evalkit.KitError, match="account"):
        share.export(out, dest)
    assert not dest.exists()


def test_a_score_made_before_the_font_database_was_pinned_is_not_exported(tmp_path, account):
    account("opuser")
    out = unpin(make_out(tmp_path / "out"))
    dest = tmp_path / "dest"
    with pytest.raises(evalkit.KitError, match="font_db"):
        share.export(out, dest)
    assert not dest.exists()


def test_the_summaries_are_built_again_from_the_exported_records_and_name_no_private_skill(tmp_path, account):
    account("opuser")
    out = make_out(tmp_path / "out", skills_read=["lapis", "private-brand-voice"])
    (out / "summary.md").write_text("COPIED-AS-IS private-brand-voice", encoding="utf-8")
    (out / "summary.csv").write_text("COPIED-AS-IS private-brand-voice", encoding="utf-8")
    dest = tmp_path / "dest"
    written = share.export(out, dest)
    assert "summary.md" in written and "summary.csv" in written
    for name in ("summary.md", "summary.csv"):
        text = (dest / name).read_text(encoding="utf-8")
        assert "private-brand-voice" not in text and "COPIED-AS-IS" not in text
        assert "lapis,<other-skill>" in text
    rows = list(csv.DictReader(io.StringIO((dest / "summary.csv").read_text(encoding="utf-8"))))
    assert [r["run"] for r in rows if r["scope"] == "run"] == [RUN, OTHER]
