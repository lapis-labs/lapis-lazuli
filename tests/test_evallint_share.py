"""tools/eval/share.py: what the export refuses and what it rewrites when the account name is an ordinary
word or a JSON key, and that the summaries are built again from the cleaned records."""
import csv
import io

import pytest

from evallint_support import TASK, evalkit, load, make_out, score_record

share = load("share")
RUN = f"{TASK}.r1.with"


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


def exported(dest, name):
    return evalkit.read_json(dest / "runs" / RUN / name)


@pytest.mark.parametrize("name", ["root", "runner", "copy", "site", "mark"])
def test_an_account_named_like_a_json_key_does_not_stop_the_export(tmp_path, account, name):
    account(name)
    out = make_out(tmp_path / "out", score=score_record(lint_code="no plan", lint_reason="the agent wrote no plan"))
    dest = tmp_path / "dest"
    share.export(out, dest)
    record = exported(dest, "score.json")
    assert record["site"] == {"root": "project", "refused_links": []}          # `root` is a key here
    assert list(record["copy"]["rules"]) == ["copy.vague-cta"]                  # `copy` is a key too
    assert record["checkers"]["lint"]["code"] == "no plan"


def test_a_user_name_that_is_an_ordinary_word_is_never_rewritten_inside_a_value(tmp_path, account):
    account("plan")
    out = make_out(tmp_path / "out")                # the lint code reads "plan rejected"
    dest = tmp_path / "dest"
    with pytest.raises(evalkit.KitError, match="user name"):
        share.export(out, dest)
    assert not dest.exists()                         # stopped, not exported as "<user> rejected"


def test_a_user_name_is_removed_from_a_path_and_from_a_value_that_is_only_the_name(tmp_path, account):
    account("opuser")
    reason = "cannot write /srv/opuser/cache/x"
    out = make_out(tmp_path / "out", score=score_record(lint_reason=reason))
    record = evalkit.read_json(out / "runs" / RUN / "score.json")
    record["site"]["owner"] = "opuser"
    evalkit.write_json(out / "runs" / RUN / "score.json", record)
    dest = tmp_path / "dest"
    share.export(out, dest)
    cleaned = exported(dest, "score.json")
    assert cleaned["checkers"]["lint"]["reason"] == "cannot write /srv/<user>/cache/x"
    assert cleaned["site"]["owner"] == "<user>"


def test_a_user_name_in_ordinary_text_stops_the_export(tmp_path, account):
    account("opuser")
    out = make_out(tmp_path / "out", score=score_record(lint_reason="denied to opuser by the sandbox"))
    with pytest.raises(evalkit.KitError, match="user name"):
        share.export(out, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()


def test_the_summaries_are_built_again_from_the_cleaned_records_and_name_no_private_skill(tmp_path, account):
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
    assert [r["run"] for r in rows if r["scope"] == "run"] == [f"{TASK}.r1.with", f"{TASK}.r1.without"]


def test_a_private_skill_name_in_a_value_stops_the_export(tmp_path, account):
    account("opuser")
    out = make_out(tmp_path / "out", skills_read=["lapis", "private-brand-voice"])
    record = evalkit.read_json(out / "runs" / RUN / "run.json")
    record["session"]["errors"] = ["private-brand-voice"]                 # a value that is only that name
    evalkit.write_json(out / "runs" / RUN / "run.json", record)
    with pytest.raises(evalkit.KitError, match="skill"):
        share.export(out, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()
