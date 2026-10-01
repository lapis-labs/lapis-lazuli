"""tools/eval/score.py and review.py: parsing checker JSON, aggregation, and what a table says for a
checker that did not run. Synthetic reports only; no model, browser, or server."""
import csv
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "eval"))

import evalkit  # noqa: E402
from evallint_support import make_font_db  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(f"eval_{name}", ROOT / "tools" / "eval" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module          # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


score = load("score")
review = load("review")


def finding(rule, layer, *, blocking=False, status="open"):
    return {"rule_id": rule, "class": "quality", "severity": {}, "layer": layer, "observed": "x",
            "blocking": blocking, "evidence": {"type": "measurement"}, "status": status}


def run_record(task, arm, replicate=1, tokens=None):
    usage = {"input_tokens": tokens, "output_tokens": 0} if tokens else None
    return {"id": evalkit.run_id(task, replicate, arm), "task": task, "arm": arm, "replicate": replicate,
            "status": "completed", "exit_code": 0, "duration_s": 60.0, "usage": usage,
            "session": {"skills_read": ["lapis"] if arm == "with" else []}}


def score_record(*, plan=True, lint_layers=None, copy=None, render_ok=True, behavior=None):
    layers = lint_layers or {}
    return {"checkers": {
        "render_check": {"status": "ok"} if render_ok else {"status": "not scored", "code": "render check failed",
                                                             "reason": "boom"},
        "behavior_check": behavior or {"status": "not scored", "code": "n/a", "reason": "no behavior check"},
        "lint": {"status": "ok", "layers": layers}},
        "copy": copy or {"status": "not scored", "code": "no render", "reason": "x"}}


def ok(blocking, total):
    return {"status": "ok", "blocking": blocking, "total": total, "open": total, "skipped": 0}


def missing(code):
    return {"status": "not scored", "code": code, "reason": code}


def test_words_come_from_the_richest_viewport_and_skip_code_and_data():
    extract = {"viewports": [
        {"width": 390, "text": [{"text": "짧은 글"}]},
        {"width": 768, "text": [{"text": "가마 공방에서 물레를 돌려요"},          # 4 words
                                {"text": "— ·"},                                   # no letter or digit
                                {"text": "const a = 1", "type_role": "code"},
                                {"text": "9월 24점", "type_role": "data"},
                                {"text": "예약 3일 전까지 무료"}]},                # 4 words
    ]}
    assert score.rendered_words(extract) == (8, 768)
    assert score.rendered_words({"viewports": []}) == (0, None)


def test_the_widest_viewport_wins_a_tie_on_text():
    same = [{"text": "하나 둘"}]
    assert score.rendered_words({"viewports": [{"width": 390, "text": same}, {"width": 1440, "text": same}]})[1] == 1440


def test_layer_stats_split_blocking_open_and_skipped_by_layer():
    report = {"findings": [
        finding("type.a", "render", blocking=True), finding("copy.b", "render"),
        finding("copy.c", "render", status="skipped"), finding("contract.d", "plan", blocking=True),
        finding("flow.e", "behavior"), finding("review.f", "review")]}
    stats = score.layer_stats(report)
    assert stats["render"] == {"blocking": 1, "total": 3, "open": 2, "skipped": 1}
    assert stats["plan"]["blocking"] == 1 and stats["source"]["total"] == 0
    assert "review" not in stats


def test_copy_findings_count_open_render_hits_per_thousand_words():
    extract = {"viewports": [{"width": 390, "text": [{"text": " ".join(["말"] * 500)}]}]}
    report = {"scope": {"layers": ["plan", "render"]}, "findings": [
        finding("copy.buzzwords", "render"), finding("copy.ko.register-mix", "render", blocking=True),
        finding("copy.vague-cta", "render", status="skipped"),      # not judged: not counted
        finding("copy.buzzwords", "plan"),                          # plan text has another denominator
        finding("type.body-size", "render")]}
    result = score.copy_stats(report, extract)
    assert (result["findings"], result["words"], result["per_1000_words"]) == (2, 500, 4.0)
    assert result["blocking"] == 1 and result["plan_findings"] == 1
    assert result["rules"] == {"copy.buzzwords": 1, "copy.ko.register-mix": 1}


def test_copy_is_not_scored_without_a_render_layer_or_copy():
    extract = {"viewports": [{"width": 390, "text": []}]}
    assert score.copy_stats({"scope": {"layers": ["source"]}, "findings": []}, extract)["status"] == "not scored"
    assert score.copy_stats({"scope": {"layers": ["render"]}, "findings": []}, extract)["code"] == "no copy"
    assert score.copy_stats(None, extract)["status"] == "not scored"


def test_layers_say_why_a_layer_did_not_run():
    report = {"scope": {"layers": ["source", "render"]}, "findings": [finding("type.x", "render")]}
    layers = score.layers_record(report, {"status": "ok"}, plan=None, behavior_applicable=False,
                                 behavior=None, render={"status": "ok"})
    assert layers["plan"]["code"] == "no plan" and layers["behavior"]["code"] == "n/a"
    assert layers["render"]["status"] == "ok" and layers["render"]["total"] == 1
    rejected = score.layers_record(report, {"status": "ok", "plan_problem": "plan invalid"}, plan=Path("p.yaml"),
                                   behavior_applicable=True, behavior={"reason": "boom"}, render={"status": "ok"})
    assert rejected["plan"]["code"] == "plan rejected" and rejected["behavior"]["code"] == "no behavior"


def test_a_lint_that_did_not_run_scores_no_layer_as_zero():
    layers = score.layers_record(None, {"code": "lint failed", "reason": "exit 2"}, plan=None,
                                 behavior_applicable=True, behavior=None, render={"status": "ok"})
    assert {layer: entry["status"] for layer, entry in layers.items()} == {layer: "not scored" for layer in score.LAYERS}
    assert layers["plan"]["code"] == "no plan" and layers["source"]["code"] == "lint failed"


def test_row_sums_scored_layers_and_leaves_the_others_empty():
    layers = {"plan": missing("no plan"), "source": ok(1, 3), "render": ok(2, 5), "behavior": missing("n/a")}
    copy = {"status": "ok", "words": 400, "findings": 2, "per_1000_words": 5.0}
    row = score.row_from(run_record("kiln-landing-ko", "without", tokens=1000),
                         score_record(lint_layers=layers, copy=copy))
    assert (row["lint_blocking"], row["lint_total"]) == (3, 8)
    assert row["plan_blocking"] is None and row["plan_status"] == "no plan" and row["behavior_status"] == "n/a"
    assert score.pair(row, "plan") == "no plan" and score.pair(row, "source") == "1/3 (3 open)"
    assert row["tokens"] == 1000 and row["copy_per_1000"] == 5.0 and row["skills_read"] == ""


def test_unscored_run_has_no_numbers_and_render_failure_is_a_code_not_zero():
    unscored = score.row_from(run_record("t", "with"), None)
    assert unscored["scored"] is False and unscored["lint_total"] is None and unscored["copy_status"] == score.NA
    failed = score.row_from(run_record("t", "with"), score_record(render_ok=False, lint_layers={"source": ok(0, 0)}))
    assert failed["render_check"] == "render check failed" and failed["render_total"] is None


def test_arm_means_skip_unscored_runs_and_report_how_many_counted():
    def row(arm, replicate, blocking):
        layers = {"plan": missing("no plan"), "source": ok(blocking, blocking + 2) if blocking is not None else missing("lint failed"),
                  "render": missing("no render"), "behavior": missing("n/a")}
        return score.row_from(run_record("t", arm, replicate), score_record(lint_layers=layers))
    rows = [row("with", 1, 1), row("with", 2, 3), row("without", 1, 6), row("without", 2, None)]
    agg = score.aggregate(rows)["t"]
    assert agg["with"]["mean"]["source_blocking"] == 2 and agg["with"]["n"]["source_blocking"] == 2
    assert agg["without"]["mean"]["source_blocking"] == 6 and agg["without"]["n"]["source_blocking"] == 1
    assert agg["without"]["mean"]["plan_blocking"] is None
    change = score.delta(agg)
    assert change["source_blocking"] == -4 and change["plan_blocking"] is None


def test_delta_needs_both_arms():
    rows = [score.row_from(run_record("t", "with"), None)]
    assert score.delta(score.aggregate(rows)["t"]) == {}


def test_csv_leaves_unscored_cells_blank_and_markdown_names_the_reason(tmp_path):
    layers = {"plan": missing("no plan"), "source": ok(0, 2), "render": missing("no render"), "behavior": missing("n/a")}
    rows = [score.row_from(run_record("t", "with"), score_record(lint_layers=layers)),
            score.row_from(run_record("t", "without"), score_record(lint_layers=layers))]
    score.write_summary(tmp_path, rows)
    table = list(csv.DictReader((tmp_path / "summary.csv").open(encoding="utf-8")))
    runs = [r for r in table if r["scope"] == "run"]
    assert len(runs) == 2 and {r["scope"] for r in table} == {"run", "mean", "delta"}
    assert all(r["plan_blocking"] == "" and r["plan_status"] == "no plan" for r in runs)
    assert all(r["source_blocking"] == "0" for r in runs)
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "| no plan |" in text and "0/2" in text and "with − without" in text


def test_plan_is_used_only_when_the_agent_wrote_it_by_task_name(tmp_path):
    assert score.find_plan(tmp_path, "t") == (None, [])
    plans = tmp_path / ".lapis" / "plans"
    plans.mkdir(parents=True)
    (plans / "other.yaml").write_text("x: 1\n")
    assert score.find_plan(tmp_path, "t") == (None, ["other.yaml"])
    (plans / "t.yaml").write_text("x: 1\n")
    assert score.find_plan(tmp_path, "t") == (plans / "t.yaml", ["other.yaml"])


def test_site_root_prefers_the_project_then_conventional_output_folders(tmp_path):
    assert score.find_site_root(tmp_path) is None
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<p>x")
    assert score.find_site_root(tmp_path) == tmp_path / "dist"
    (tmp_path / "index.html").write_text("<p>y")
    assert score.find_site_root(tmp_path) == tmp_path


def test_behavior_coverage_counts_probes_by_status():
    session = {"coverage": [{"probe": "forms", "status": "ran"}, {"probe": "flows", "status": "partial"},
                            {"probe": "media", "status": "skipped"}, {"probe": "scroll", "status": "skipped"}]}
    assert score.coverage_counts(session) == {"ran": 1, "partial": 1, "skipped": 2,
                                              "skipped_probes": ["media", "scroll"]}


def test_review_screenshots_drop_variants_and_carry_no_run_name():
    extract = {"viewports": [
        {"width": 390, "theme": "light", "screenshot": "render.shots/01-390-light.png"},
        {"width": 390, "theme": "dark", "screenshot": "render.shots/02-390-dark.png"},
        {"width": 390, "theme": "light", "reduced_motion": True, "screenshot": "render.shots/03-390-light-reduced.png"},
        {"width": 390, "theme": "light", "browser_chrome": True, "screenshot": "render.shots/04-390-light-chrome.png"},
        {"width": 1440, "theme": "light", "screenshot": "render.shots/07-1440-light.png"}]}
    assert review.screenshot_plan(extract) == [("render.shots/01-390-light.png", "390-light.png"),
                                               ("render.shots/02-390-dark.png", "390-dark.png"),
                                               ("render.shots/07-1440-light.png", "1440-light.png")]
    assert review.screenshot_plan(None) == []


def test_review_sheet_hides_the_arm_and_the_key_maps_it_back(tmp_path):
    tasks = {"t": {"title": "A task", "acceptance": ["note one", "note two"]}}
    for arm in ("with", "without"):
        run_dir = tmp_path / "runs" / evalkit.run_id("t", 1, arm)
        (run_dir / "project").mkdir(parents=True)
        (run_dir / "project" / "index.html").write_text("<p>hi</p>")
        (run_dir / "project" / ".lapis").mkdir()
        (run_dir / "project" / ".lapis" / "secret-plan.yaml").write_text("x: 1\n")
        shots = run_dir / "score" / "render.shots"
        shots.mkdir(parents=True)
        (shots / "01-390-light.png").write_bytes(b"png")
        evalkit.write_json(run_dir / "run.json", {**run_record("t", arm), "project": "project", "order": 1})
        evalkit.write_json(run_dir / "score.json", {"site": {"root": "project"}})
        evalkit.write_json(run_dir / "score" / "render.json", {"viewports": [
            {"width": 390, "theme": "light", "screenshot": "render.shots/01-390-light.png"}]})
    key = review.build(tmp_path, 3, tasks)
    sheet = (tmp_path / "review" / "sheet.md").read_text(encoding="utf-8")
    assert "t.r1" not in sheet and "runs/" not in sheet and str(tmp_path) not in sheet
    assert sorted(key["candidates"]) == ["t/A", "t/B"]
    assert {v["arm"] for v in key["candidates"].values()} == {"with", "without"}
    candidate = tmp_path / "review" / "t" / "A"
    assert (candidate / "shots" / "390-light.png").is_file() and (candidate / "site" / "index.html").is_file()
    assert not (candidate / "site" / ".lapis").exists()
    header = (tmp_path / "review" / "scores.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == "task,label,rank,note_1,note_2,evidence"


def test_review_refuses_a_folder_without_scored_runs(tmp_path):
    with pytest.raises(evalkit.KitError):
        review.build(tmp_path, 1, {})


def test_a_run_that_built_nothing_is_not_scored_as_zero_findings(tmp_path):
    run_dir = tmp_path / "runs" / evalkit.run_id("signup-recovery-ko", 1, "without")
    (run_dir / "project").mkdir(parents=True)
    evalkit.write_json(run_dir / "run.json", {**run_record("signup-recovery-ko", "without"), "project": "project"})
    font_db = evalkit.evaluation_font_db(make_font_db(tmp_path / "eval-fonts.db"))
    result = score.score_run(run_dir, evalkit.load_tasks(), font_db=font_db, sig_key=tmp_path / "sig.key")
    checkers = result["checkers"]
    assert checkers["render_check"]["code"] == "no site" and checkers["behavior_check"]["code"] == "no site"
    assert checkers["lint"]["status"] == "not scored"
    assert {layer["status"] for layer in checkers["lint"]["layers"].values()} == {"not scored"}
    assert result["copy"]["status"] == "not scored"
    row = score.row_from(run_record("signup-recovery-ko", "without"), result)
    assert row["lint_total"] is None and row["source_blocking"] is None and row["source_status"] == "no site"
