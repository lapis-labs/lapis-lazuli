"""Builders for render-extract fixtures of the layout and type detectors: small extracts that validate against
the extract schema, and a `lint` that runs one shipped rule's detector through the registry."""
from __future__ import annotations

import copy

import yaml
from jsonschema import Draft202012Validator

from lapis_design import shared_dir
from lapis_design.lint.detectors import load
from lapis_design.lint.types import DETECTORS, Context

load("render")
SHARED = shared_dir()
RULES = yaml.safe_load((SHARED / "slop" / "rules.yaml").read_text(encoding="utf-8"))
EXTRACT = Draft202012Validator(yaml.safe_load((SHARED / "render" / "extract.schema.yaml").read_text(encoding="utf-8")))
HEIGHT = {320: 568, 390: 844, 768: 1024, 1440: 900}


def bid(n: int) -> str:
    return f"b{n:012x}"


def box(n, role, x, y, w, h, parent=None, **extra):
    return {"id": bid(n), "parent": None if parent is None else bid(parent), "role": role,
            "role_confidence": 0.9, "rect": {"x": x, "y": y, "w": w, "h": h}, **extra}


def run(n, box_n, text, type_role="body", size=16, **extra):
    return {"id": f"t{n}", "box": bid(box_n), "text": text, "chars": sum(not c.isspace() for c in text),
            "script": "latn", "type_role": type_role, "font": {"requested": "Inter", "rendered": "Inter"},
            "size_px": size, **extra}


def viewport(width, boxes=(), text=(), derived=None, **extra):
    vp = {"width": width, "height": HEIGHT[width], "theme": "light", "boxes": list(boxes), "text": list(text),
          **extra}
    if derived is not None:
        vp["derived"] = derived
    return vp


def extract(*viewports):
    doc = {"version": 1,
           "meta": {"extractor": {"name": "render_check", "version": "test"}, "generated_at": "2026-10-05T00:00:00Z"},
           "source": {"kind": "render", "task": "demo"}, "viewports": list(viewports)}
    errors = list(EXTRACT.iter_errors(doc))
    assert not errors, errors[0].message
    return doc


def lint(rule_id, layer="render", *, threshold=None, params=None, **inputs):
    rule = copy.deepcopy(next(r for r in RULES["rules"] if r["id"] == rule_id))
    det = rule["detect"][layer]
    if threshold:
        det.setdefault("threshold", {}).update(threshold)
    if params:
        det.setdefault("params", {}).update(params)
    return DETECTORS[det["detector"]].fn(Context(rules=RULES, **inputs), det, rule, layer)


def observed(result):
    assert result.skipped is None, result.skipped
    return [hit.observed for hit in result.hits]
