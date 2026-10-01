"""slop lint reads only inside the folders it is given: a source or corpus file that is a link resolving
outside its folder is not read, and a warning on stderr says so."""
import json
from pathlib import Path

import pytest
import yaml

import lapis_design.lint.detectors.source  # noqa: F401  (registers the source detectors)
from lapis_design import shared_dir
from lapis_design.lint import cli as lint_cli
from lapis_design.lint.types import DETECTORS, Context

RULES = yaml.safe_load((shared_dir() / "slop" / "rules.yaml").read_text(encoding="utf-8"))
RULE = next(r for r in RULES["rules"] if r["id"] == "system.literal-color")


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "card.css").write_text(".card { background: #1F2937; }\n", encoding="utf-8")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "secret.css").write_text(".secret { color: #AB12CD; }\n", encoding="utf-8")
    (outside / "package.json").write_text(json.dumps({"dependencies": {"lucide-react": "1"}}), encoding="utf-8")
    return root


def literal_colors(root: Path):
    ctx = Context(rules=RULES, source_root=root)
    det = RULE["detect"]["source"]
    result = DETECTORS[det["detector"]].fn(ctx, det, RULE, "source")
    return "\n".join(h.observed for h in result.hits), ctx.cache.get("source.skipped_links")


def test_a_source_file_that_is_a_link_out_of_the_tree_is_not_read(project, tmp_path):
    (project / "src" / "secret.css").symlink_to(tmp_path / "elsewhere" / "secret.css")
    (project / "package.json").symlink_to(tmp_path / "elsewhere" / "package.json")
    seen, skipped = literal_colors(project)
    assert "#1f2937" in seen and "#ab12cd" not in seen
    assert sorted(skipped) == ["package.json", "src/secret.css"]


def test_a_link_that_stays_inside_the_tree_is_still_read(project):
    (project / "src" / "alias.css").symlink_to(project / "src" / "card.css")
    seen, skipped = literal_colors(project)
    assert "#1f2937" in seen and skipped == []


def test_the_run_warns_on_stderr_and_the_report_holds_nothing_from_outside(project, tmp_path, capsys):
    (project / "src" / "secret.css").symlink_to(tmp_path / "elsewhere" / "secret.css")
    report = lint_cli.run(source=project)
    assert "#ab12cd" not in json.dumps(report).lower()
    warning = capsys.readouterr().err
    assert "1 source file(s)" in warning and "src/secret.css" in warning and "not read" in warning


def test_a_corpus_entry_that_is_a_link_out_of_the_folder_is_not_read(tmp_path):
    example = shared_dir() / "render" / "example.extract.json"
    corpus = tmp_path / "corpus"
    (corpus / "defaults").mkdir(parents=True)
    (corpus / "defaults" / "c.json").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "x.json").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    (corpus / "defaults" / "x.json").symlink_to(outside / "x.json")
    skipped: list[str] = []
    entries = lint_cli._corpus(corpus, skipped)
    assert [e["_corpus"] for e in entries] == ["defaults"] and skipped == ["defaults/x.json"]
    # a file the user names themselves is read, whatever it links to
    assert [e["_corpus"] for e in lint_cli._corpus(corpus / "defaults" / "x.json", [])] == ["defaults"]
