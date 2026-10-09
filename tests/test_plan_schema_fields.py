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


def with_voice(voice: dict) -> dict:
    plan = copy.deepcopy(EXAMPLE)
    plan["content"]["voice"] = voice
    return plan


def test_example_plan_sets_a_voice_per_locale_and_role():
    ko = EXAMPLE["content"]["voice"]["locales"]["ko"]
    assert ko["prose"] == "haeyo" and ko["by_role"]["headline"] == "compact" and ko["speaker"] == "brand"


@pytest.mark.parametrize("voice", [
    {"locales": {"ko": {"prose": "hapnida", "by_role": {"status": "haeyo", "legal": "hapnida", "label": "compact"}}}},
    {"locales": {"ko": {"prose": "haera", "speaker": "editorial"}, "en": {"prose": "en-formal"}}},
    {"locales": {"ja": {"prose": "desu-masu", "by_role": {"headline": "compact", "action": "compact"}}, "fr": {"prose": "other"}}},
    {"notes": "Product explains screen planning to developers.", "locales": {"zh": {"prose": "zh-casual"}}},
])
def test_a_voice_policy_per_locale_validates(voice):
    assert errors(with_voice(voice)) == []


@pytest.mark.parametrize("voice", [
    {"locales": {"ko": {"prose": "en-casual"}}},                                   # another language's register
    {"locales": {"ja": {"prose": "haeyo"}}},
    {"locales": {"ko": {"prose": "compact"}}},                                     # a form, not a sentence register
    {"locales": {"ko": {"prose": "haeyo", "by_role": {"headline": "desu-masu"}}}},  # a role of another language
    {"locales": {"ko": {"prose": "haeyo", "by_role": {"tooltip": "compact"}}}},    # no such role
    {"locales": {"ko": {"prose": "haeyo", "speaker": "robot"}}},
    {"locales": {"ko-KR": {"prose": "haeyo"}}},                                    # the language, not the region
    {"locales": {"ko": {"by_role": {"headline": "compact"}}}},                     # no prose register
    {"locales": {}},
])
def test_a_voice_policy_that_contradicts_itself_is_refused(voice):
    assert errors(with_voice(voice))


def test_the_page_wide_register_is_refused_and_explained():
    from lapis_design import plan_check
    plan = with_voice({"register": "haeyo", "notes": "ko sentences in haeyo"})
    schema = yaml.safe_load((SHARED / "plan" / "schema.yaml").read_text(encoding="utf-8"))
    found = plan_check.check_schema(plan, schema, "plan.yaml")
    assert len(found) == 1 and found[0]["location"]["path"] == "content/voice"
    assert "content.voice.locales.<language>.prose" in found[0]["observed"]
