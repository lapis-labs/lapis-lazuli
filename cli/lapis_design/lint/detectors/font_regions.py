"""Font feature regions: plan-font-region, and the measured-face lookup and region meanings it
shares with rendered-family-region (render_type.py).

Font feature regions are named in rules.yaml `lists`; vocab/type.yaml `font_feature_regions` gives
each name its meaning in lazuli measurements (vocab/type.yaml classes as measured by
cli/lazuli/measure.py), and `judge` reads that definition. List scopes map to scripts: `latin`
applies to Latin text, `all` to any. Reports name the family and its measured classes, never a local
font's file or PostScript name.

This module imports no render code, so a plan-layer run (the exit-plan hook) loads it without the
render detector modules.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml

from lapis_design import shared_dir
from lapis_design.lint.types import Context, Hit, Result, detector
from lapis_design.plan_check import resolve
from lazuli.scan import norm as family_norm


def definitions() -> dict[str, dict]:
    """Region name -> its definition in vocab/type.yaml `font_feature_regions`."""
    return _load_regions(shared_dir() / "vocab" / "type.yaml")


@lru_cache(maxsize=None)
def _load_regions(path: Path) -> dict[str, dict]:
    vocab = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {region["id"]: region for region in vocab.get("font_feature_regions") or ()}


def _matches(value, expected) -> bool:
    return value in expected if isinstance(expected, list) else value == expected


def judge(definition: dict, features: dict) -> bool | None:
    """Whether a face's features are in the region (`when`, `unless`, and `when_any` as the vocabulary
    defines them), or None when a feature the definition needs is not measured."""
    when, unless, when_any = ((definition.get(key) or {}) for key in ("when", "unless", "when_any"))
    if any(features.get(key) is None for key in when):
        return None
    measured_any = {key: value for key, value in when_any.items() if features.get(key) is not None}
    if when_any and not measured_any:
        return None
    return (all(_matches(features[key], value) for key, value in when.items())
            and not any(features.get(key) is not None and _matches(features[key], value)
                        for key, value in unless.items())
            and (not when_any or any(_matches(features[key], value) for key, value in measured_any.items())))


SCOPE_SCRIPTS = {"latin": {"latn"}, "cyrl": {"cyrl"}, "grek": {"grek"}, "ko": {"hang"}, "ja": {"kana", "hani"},
                 "zh": {"hani"}, "arab": {"arab"}, "hebr": {"hebr"}, "thai": {"thai"}}
LANG_SCRIPTS = {"ko": {"hang"}, "ja": {"kana", "hani"}, "zh": {"hani"}, "el": {"grek"}, "he": {"hebr"},
                "yi": {"hebr"}, "th": {"thai"}, "ar": {"arab"}, "fa": {"arab"}, "ur": {"arab"},
                **{lang: {"cyrl"} for lang in ("ru", "uk", "be", "bg", "sr", "mk", "kk", "ky", "mn", "tg")}}
FACE_SQL = """SELECT lf.id, lf.subfamily, m.family_kind, m.panose_json, m.metrics_json, m.cjk_json
              FROM local_font lf JOIN measurement m ON m.local_font_id = lf.id
              WHERE lf.family_norm = ? ORDER BY lf.id, m.measured_at DESC"""


@dataclass(frozen=True)
class Face:
    weight: float | None
    italic: bool
    features: dict


def region_list(ctx: Context, det: dict) -> tuple[list[tuple[str, set[str] | None]], str | None]:
    """(region name, scripts it applies to or None for any) from the rule's list."""
    key = det.get("list")
    if not key:
        return [], "the rule names no list of feature regions"
    values = ((ctx.rules.get("lists") or {}).get(key) or {}).get("values") or {}
    regions = [(name, SCOPE_SCRIPTS.get(scope)) for scope, names in values.items() for name in names]
    if not regions:
        return [], f"list {key!r} has no feature regions"
    defined = definitions()
    undefined = [name for name, _ in regions if name not in defined]
    if len(undefined) == len(regions):
        return [], f"feature regions {undefined} have no measured definition"
    return regions, None


def family_keys(name: str) -> list[str]:
    """Normalized lookup keys: the name, the family inside a font loader's hashed name
    (`__Inter_d65c78`), and the name without a trailing Variable or VF."""
    candidates = [name]
    if (match := re.fullmatch(r"_+(.+?)_[0-9a-f]{5,}", name)) and not match.group(1).endswith("_Fallback"):
        candidates.append(match.group(1).replace("_", " "))
    candidates.append(re.sub(r"\s+(?:variable|vf)$", "", candidates[-1], flags=re.I))
    return list(dict.fromkeys(key for c in candidates if (key := family_norm(c))))


def faces(ctx: Context, family: str) -> tuple[list[Face], str | None]:
    """Measured faces of a family in the lazuli database, or why there are none."""
    memo = ctx.cache.setdefault("font_regions.faces", {})
    if family in memo:
        return memo[family]
    found: list[Face] = []
    installed = False
    try:
        for key in family_keys(family):
            seen = set()
            for row in ctx.lazuli.execute(FACE_SQL, (key,)).fetchall():
                ident, subfamily, kind, panose, metrics, cjk = tuple(row)
                if ident in seen:
                    continue
                seen.add(ident)
                metrics = json.loads(metrics or "{}")
                if "unmeasurable" in metrics:
                    continue
                italic = metrics.get("italic")
                if italic is None:
                    italic = bool(re.search(r"italic|oblique", subfamily or "", re.I))
                found.append(Face(metrics.get("weight_class"), bool(italic),
                                  {**metrics, **json.loads(panose or "{}"), "italic": bool(italic),
                                   "family_kind": kind, "cjk": json.loads(cjk or "{}")}))
            if found:
                break
            installed = installed or ctx.lazuli.execute(
                "SELECT 1 FROM local_font WHERE family_norm = ? LIMIT 1", (key,)).fetchone() is not None
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        memo[family] = ([], f"the lazuli database cannot be read ({exc})")
        return memo[family]
    reason = None if found else (f"'{family}' is installed but not measured" if installed
                                 else f"'{family}' is not among the measured local fonts")
    memo[family] = (found, reason)
    return memo[family]


def pick(candidates: list[Face], weight: float | None, italic: bool) -> Face:
    target = weight or 400
    return min(candidates, key=lambda f: ((f.italic != italic) * 10_000 + abs((f.weight or 400) - target)))


def describe(f: dict) -> str:
    parts = []
    if f.get("serif") is not None:
        parts.append("serif" if f["serif"] else "sans")
    for key, label in (("weight", "weight"), ("contrast", "contrast"), ("proportion", "proportion"),
                       ("x_height_size", "x-height")):
        if f.get(key):
            parts.append(f"{label} {f[key]}")
    if f.get("italic"):
        parts.append("italic")
    return ", ".join(parts) or "measured"


def judge_face(face: Face, name: str) -> bool | None:
    definition = definitions().get(name)
    return judge(definition, face.features) if definition else None


def _finish(hits: list[Hit], unjudged: Iterable[str]) -> Result:
    """Hits when there are any; otherwise a skip when something could not be judged; else a pass."""
    if hits:
        return Result(hits=hits)
    reasons = list(dict.fromkeys(reason for reason in unjudged if reason))
    return Result(skipped="; ".join(reasons)) if reasons else Result()


def locale_scripts(locales: Iterable[str]) -> set[str]:
    scripts: set[str] = set()
    for locale in locales:
        scripts |= LANG_SCRIPTS.get(str(locale).split("-")[0].lower(), {"latn"})
    return scripts


@detector("plan-font-region", layers=("plan",))
def plan_font_region(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    if ctx.plan is None:
        return Result(skipped="no plan given")
    regions, problem = region_list(ctx, det)
    if problem:
        return Result(skipped=problem)
    if ctx.lazuli is None:
        return Result(skipped="no lazuli database given, so planned families have no measured features")
    path = det.get("path")
    if not path:
        return Result(skipped="the rule gives no plan path")
    families = [v for v in resolve(ctx.plan, path) if isinstance(v, str) and v.strip()]
    owners = resolve(ctx.plan, path.removesuffix(".family")) if path.endswith(".family") else []
    info: dict[str, dict] = {family: {"roles": [], "weights": [], "scripts": set()} for family in families}
    for owner in owners:
        if isinstance(owner, dict) and owner.get("family") in info:
            entry = info[owner["family"]]
            entry["roles"].append(owner.get("role", "role"))
            entry["weights"] += [w for w in owner.get("weights") or () if isinstance(w, (int, float))]
            entry["scripts"] |= set(owner.get("scripts") or ())
    planned = locale_scripts(((ctx.plan.get("brief") or {}).get("locales")) or ())
    hits: dict[tuple, Hit] = {}
    defined = definitions()
    unjudged = [f"feature region {name!r} has no measured definition" for name, _ in regions if name not in defined]
    for family, entry in info.items():
        measured, reason = faces(ctx, family)
        if not measured:
            unjudged.append(reason)
            continue
        scripts = entry["scripts"] or planned
        for name, scope in regions:
            if name not in defined or (scope is not None and scripts and not scope & scripts):
                continue
            for weight in entry["weights"] or [400]:
                face = pick(measured, weight, False)
                verdict = judge_face(face, name)
                if verdict is None:
                    unjudged.append(f"'{family}' lacks measurements the region {name!r} needs")
                elif verdict and (family, name) not in hits:
                    roles = ", ".join(dict.fromkeys(entry["roles"])) or path
                    hits[(family, name)] = Hit(
                        observed=f"'{family}' ({roles}) measures in the feature region {name}: "
                                 f"{describe(face.features)}",
                        location={"path": path})
    return _finish(list(hits.values()), unjudged)
