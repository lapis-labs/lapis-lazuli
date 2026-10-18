"""A small iOS-like web prototype through the real render and the lint: the plan names Apple's HIG (declared by an owner row) and
WCAG 2.2, the requirement record holds the guidelines' rows apart from the owner's, and a close button of 30 CSS px is a
finding that names `apple-hig/target-size` and says how a point stands for a CSS px."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from lapis_design import plan_check, requirements, shared_dir
from procedure_support import BRIEF_RECORD, record

pytestmark = pytest.mark.browser

TASK = "kiln-notes"
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Firing notes</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
body{margin:0;font:17px/1.4 system-ui,sans-serif;background:#f2f2f7;color:#111}
header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:#fff}
h1{font-size:17px;margin:0} button{font:inherit;border:0;background:#e5e5ea;border-radius:8px}
.close{width:30px;height:30px} .add{width:44px;height:44px;background:#007aff;color:#fff}
main{padding:16px} li{list-style:none;background:#fff;margin:8px 0;padding:12px;border-radius:10px}
</style></head><body>
<header><button class="close" aria-label="Close">x</button><h1>Firing notes</h1><button class="add" aria-label="Add note">+</button></header>
<main><ul><li>Cone 6 oxidation, 14 hours</li><li>Shino glaze test tiles</li></ul></main>
</body></html>
"""
OWNER = "It has to follow Apple's Human Interface Guidelines, like an iPhone app\nA cook can add a note from the first screen\n"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    plan = yaml.safe_load((shared_dir() / "plan" / "example.plan.yaml").read_text(encoding="utf-8"))
    plan["task"] = {"id": TASK, "title": "Kiln notes, an iPhone-style web prototype"}
    plan["brief"].update(platform=["ios", "web"], locales=["en"], product_frame="consumer-mobile-app", guidelines=[
        {"id": "apple-hig", "platforms": ["ios"], "basis": "declared", "visual": "consult",
         "route": {"kind": "context7", "ref": "/websites/developer_apple_design_human-interface-guidelines"}},
        {"id": "wcag-2.2", "platforms": ["web"], "basis": "suggested", "visual": "none",
         "route": {"kind": "official-docs", "ref": "https://www.w3.org/TR/2024/REC-WCAG22-20241212/"}}])
    (tmp_path / ".lapis" / "plans").mkdir(parents=True)
    (tmp_path / ".lapis" / "plans" / f"{TASK}.yaml").write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "index.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "owner-brief.md").write_text("".join(f"- {line}\n" for line in OWNER.splitlines()), encoding="utf-8")
    record(tmp_path, "answers", BRIEF_RECORD, 50, task=TASK)
    return tmp_path


def test_the_rows_sit_apart_from_the_owners_and_a_small_close_button_is_a_finding_that_names_its_item(project):
    requirements.seal(project, TASK, ["owner-brief.md"])
    doc = json.loads(requirements.record_path(project, TASK).read_text(encoding="utf-8"))
    assert len(doc["rows"]) == 2 and any("Human Interface Guidelines" in r["text"] for r in doc["rows"])
    assert len(doc["guideline_rows"]) == 19 + 20 and doc["guideline_rows"][0]["id"] == "G:apple-hig/target-size"
    plan = yaml.safe_load((project / ".lapis" / "plans" / f"{TASK}.yaml").read_text(encoding="utf-8"))
    assert [f for f in plan_check.check_guidelines(plan, project, "plan.yaml")] == []          # the owner named HIG; the plan says declared

    script = "import sys\nfrom lapis_design.render import main\nraise SystemExit(main(sys.argv[1:]))"
    shot = subprocess.run([sys.executable, "-c", script, "site/index.html", "--task", TASK, "--width", "390"], capture_output=True, text=True,
                          cwd=project, timeout=600, env={**os.environ, "LAPIS_SIG_KEY_FILE": str(project / "sig.key")})
    assert shot.returncode == 0, shot.stdout + shot.stderr
    lint = subprocess.run([sys.executable, "-c", "import sys\nfrom lapis_design.cli import main\nraise SystemExit(main(sys.argv[1:]))",
                           "slop", "lint", "--plan", f".lapis/plans/{TASK}.yaml", "--extract", f".lapis/renders/{TASK}.narrow.json",
                           "--layer", "render", "-o", ".lapis/lint/t.json"], capture_output=True, text=True, cwd=project, timeout=600)
    assert lint.returncode in (0, 1), lint.stdout + lint.stderr
    found = json.loads((project / ".lapis" / "lint" / "t.json").read_text(encoding="utf-8"))["findings"]
    sizes = [f for f in found if f["rule_id"] == "guideline.target-size"]
    assert len(sizes) == 1, [f["observed"] for f in sizes]
    assert sizes[0]["guideline_items"] == ["apple-hig/target-size"]
    assert sizes[0]["observed"].startswith("apple-hig/target-size: button 'Close' is 30 x 30 CSS px; the item asks at least 44 pt = 44 CSS px")
    assert "1 pt : 1 CSS px for a web prototype" in sizes[0]["observed"] and sizes[0]["blocking"] is False
