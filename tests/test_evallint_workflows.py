"""CI workflows: they parse, and every action is pinned to a full commit SHA with its version tag beside it,
so a moved tag cannot change what runs in CI."""
import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))
PINNED = re.compile(r"^\s*(?:- )?uses:\s*[\w.-]+/[\w./-]+@[0-9a-f]{40}\s+#\s*v\d+(?:\.\d+)*\b", re.M)


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit_with_its_version_beside_it(workflow):
    text = workflow.read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    uses = [step["uses"] for job in document["jobs"].values() for step in job["steps"] if "uses" in step]
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref) for ref in uses), uses
    assert len(PINNED.findall(text)) == len(uses)           # each pin has a version comment on its own line
