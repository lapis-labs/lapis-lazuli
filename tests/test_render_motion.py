"""`lapis-design render motion` records what the owner judges on a page that moves: the scripted-scroll playback, settled and
reduced-motion captures at 390 and 1440, the pinned scenes with their content and runway, and the build's identity, which
`render check` records in its extract from the same document."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml

from lapis_design import motion, shared_dir

pytestmark = pytest.mark.browser

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Firing</title>
<style>body,h1,h2,p{margin:0}body{font:20px sans-serif}.intro,.end{height:100vh}.track{height:300vh}
.pin{position:sticky;top:0;height:100vh}@keyframes spin{to{transform:rotate(360deg)}}h2{animation:spin 2s linear infinite}</style>
</head><body><section class="intro"><h1>The kiln</h1></section>
<section class="track"><div class="pin"><h2>Three steps of one firing</h2></div></section>
<section class="end"><p>Book a piece</p></section></body></html>
"""


def run(module: str, cwd: Path, *argv: str) -> subprocess.CompletedProcess:
    script = f"import sys\nfrom {module} import main\nraise SystemExit(main(sys.argv[1:]))"
    return subprocess.run([sys.executable, "-c", script, *argv], cwd=cwd, capture_output=True, text=True, timeout=240)


@pytest.fixture(scope="module")
def recorded(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("motion")
    (root / "site").mkdir()
    (root / "site" / "index.html").write_text(PAGE, encoding="utf-8")
    result = run("lapis_design.motion", root, str(root / "site" / "index.html"), "--task", "firing")
    assert result.returncode == 0, result.stderr
    result = run("lapis_design.render", root, str(root / "site" / "index.html"), "--task", "firing", "--width", "390")
    assert result.returncode == 0, result.stderr
    return root


def test_the_manifest_matches_its_schema_and_names_files_that_exist_with_their_digests(recorded):
    document = json.loads(motion.manifest_path(recorded, "firing").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(yaml.safe_load((shared_dir() / "render" / "motion.schema.yaml").read_text())).validate(document)
    assert [e["lang"] for e in document["locales"]] == ["en"]
    for block in document["locales"][0]["widths"]:
        assert {r["kind"] for r in block["recordings"]} == {"playback", "settled", "reduced"}
        for row in block["recordings"]:
            file = recorded / row["path"]
            assert file.is_file() and file.stat().st_size > 0 and motion.sha256(file) == row["sha256"]
        playback = next(r for r in block["recordings"] if r["kind"] == "playback")
        assert playback["path"].endswith(".webm") and playback["seconds"] >= 6


def test_a_pinned_scene_is_measured_as_the_content_it_holds_and_the_empty_runway_around_it(recorded):
    blocks = {b["width"]: b for b in motion.read(recorded, "firing")["locales"][0]["widths"]}
    for width, height in ((1440, 900), (390, 844)):
        (scene,) = blocks[width]["scenes"]
        assert scene["content_px"] == height and scene["runway_px"] == 2 * height
        assert "Three steps" in scene["text"]
    assert motion.runway(recorded, "firing", blocks[1440]["document_sha256"]) == 1800
    assert motion.runway(recorded, "firing", "0" * 64) == 0


def test_the_still_captures_follow_the_scene_and_the_reduced_motion_set_repeats_them(recorded):
    block = motion.read(recorded, "firing")["locales"][0]["widths"][1]
    stills = {k: [r["scroll_y"] for r in block["recordings"] if r["kind"] == k] for k in ("settled", "reduced")}
    assert stills["settled"] == stills["reduced"] and stills["settled"][0] == 0 and len(stills["settled"]) >= 4
    assert 900 in stills["settled"] and 2700 in stills["settled"]                      # the scene's start and end


def test_render_check_records_the_build_the_motion_was_recorded_from(recorded):
    extract = json.loads((recorded / ".lapis" / "renders" / "firing.narrow.json").read_text(encoding="utf-8"))
    block = motion.read(recorded, "firing")["locales"][0]["widths"][0]
    assert extract["source"]["document_sha256"] == block["document_sha256"]


def test_a_second_locale_is_added_to_the_manifest_and_the_first_is_kept(recorded):
    result = run("lapis_design.motion", recorded, str(recorded / "site" / "index.html"), "--task", "firing", "--lang", "ko")
    assert result.returncode == 0, result.stderr
    assert [e["lang"] for e in motion.read(recorded, "firing")["locales"]] == ["en", "ko"]
