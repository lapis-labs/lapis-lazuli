"""Optional plan fields added for the lps-system, lps-ux, and color work: shape, surface, and icon tokens,
color-role theme and value source class, and physical standard ids."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

SHARED = Path(__file__).resolve().parents[1] / "src" / "shared"
SCHEMA = Draft202012Validator(yaml.safe_load((SHARED / "plan" / "schema.yaml").read_text(encoding="utf-8")))
EXAMPLE = yaml.safe_load((SHARED / "plan" / "example.plan.yaml").read_text(encoding="utf-8"))


def errors(plan: dict) -> list[str]:
    return [e.message for e in SCHEMA.iter_errors(plan)]


def with_tokens(**tokens) -> dict:
    plan = copy.deepcopy(EXAMPLE)
    plan["tokens"].update(tokens)
    return plan


def test_example_plan_uses_every_new_field_and_validates():
    tokens = EXAMPLE["tokens"]
    roles = tokens["color"]["roles"]
    assert errors(EXAMPLE) == []
    assert {"shape", "surface", "icons"} <= set(tokens)
    assert any(t.get("job") for t in tokens["surface"]["treatments"])
    assert any(r.get("theme") == "dark" for r in roles)
    assert any("source_class" in r for r in roles)


def test_unknown_source_class_is_refused():
    plan = copy.deepcopy(EXAMPLE)
    plan["tokens"]["color"]["roles"][0]["source_class"] = "eyedropper"
    assert errors(plan)


def test_a_surface_treatment_needs_a_job():
    assert errors(with_tokens(surface={"treatments": [{"name": "paper grain"}]}))
    assert not errors(with_tokens(surface={"treatments": [{"name": "paper grain", "job": "marks printed matter"}]}))


@pytest.mark.parametrize("radius", [{"scale": [-2, 4]}, {"by_role": {"control": -6}}])
def test_negative_corners_are_refused(radius):
    assert errors(with_tokens(shape={"radius": radius}))


def test_older_plans_keep_the_ral_system_id():
    plan = copy.deepcopy(EXAMPLE)
    plan["tokens"]["color"]["roles"][0]["system_code"] = {"system": "ral", "code": "RAL 270 30 40"}
    assert errors(plan) == []
    plan["tokens"]["color"]["roles"][0]["system_code"]["system"] = "ral-design-plus"
    assert errors(plan) == []
