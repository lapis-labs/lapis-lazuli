"""The example release manifest is a valid model distribution contract."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
import yaml


MODELS = Path(__file__).resolve().parents[1] / "src" / "shared" / "models"


def test_example_manifest_matches_schema():
    schema = yaml.safe_load((MODELS / "manifest.schema.yaml").read_text(encoding="utf-8"))
    example = json.loads((MODELS / "example.manifest.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(example)) == []
