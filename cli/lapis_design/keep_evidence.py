"""keep evidence: what a `defaults` keep has to show for the `keep_when` case it names.

A keep that names one of the rule's cases waives its hits (plan_check.default_verdict). A case can also
list the evidence a plan is able to carry for its premise (`evidence` in slop/rules.yaml): a list of
alternatives, any one of which backs the keep. `evidence: none` marks a case whose premise nothing in a
plan, a design contract, or the asset ledger can show; it waives as before and the critic reads the
reason. Without the evidence the finding keeps its severity and says which evidence is missing.

Alternatives a case may list:

  design       the keep's `evidence.design` names a token of the design contract (`DESIGN.md#colors.accent`);
               holds when `context.design` is declared, the named file is the declared one, and the last
               segment of the token appears in its text (the test `plan check` applies to a color `ref`)
  brief        `evidence.brief` quotes a line of `brief` (subject, one_job, audience, or a constraint)
  material     `evidence.material` is an entry of `world_materials`
  source       `evidence.source` is the `ref` of an entry of `sources`
  exploration  `evidence.exploration` is the chosen face of a complete type comparison in `explorations`
               that a type role covered by that comparison uses
  {asset: {kind, origin, role}}   `evidence.asset` is the id of a ledger asset recorded as used by this
               plan's task, whose kind, origin, and role are among the listed values
  {plan: PATH, has | lacks | present | min}   no citation: the plan itself says it. `has` holds when any
               listed value is among the values at PATH, `lacks` when none is (and PATH has a value),
               `present` when PATH has a value, `min` when a number at PATH is at least that

It judges that the evidence exists where the plan says it does, never that it supports the case; the
critic reads the reason against the page.
"""
from __future__ import annotations

import posixpath
import unicodedata
from dataclasses import dataclass
from typing import Any

from lapis_design.plan_check import resolve

CITED = {
    "design": "a token of the declared design contract, such as DESIGN.md#colors.accent",
    "brief": "a line of brief, quoted",
    "material": "an entry of world_materials",
    "source": "the ref of an entry of sources",
    "exploration": "the chosen face of a type comparison in explorations",
    "asset": "the id of an asset in the asset ledger",
}


@dataclass(frozen=True)
class Sources:
    """Where a keep's evidence is looked up: the plan, the asset ledger, and the text of the design contract."""
    plan: dict
    ledger: dict | None = None
    design_text: str | None = None


def gap(case: dict, entry: dict, sources: Sources) -> str | None:
    """Why `entry` (a defaults keep) does not back `case`, or None when it does or the case lists no evidence."""
    alternatives = case.get("evidence")
    if not isinstance(alternatives, list):
        return None
    cited = entry.get("evidence") if isinstance(entry.get("evidence"), dict) else {}
    reasons = []
    for alternative in alternatives:
        reason = _holds(alternative, cited, sources)
        if reason is None:
            return None
        reasons.append(reason)
    return f"keep_when {case.get('id')!r} needs evidence the keep does not have: " + "; or ".join(reasons)


def _holds(alternative: Any, cited: dict, sources: Sources) -> str | None:
    if isinstance(alternative, str):
        return _CHECKS[alternative](cited.get(alternative), sources)
    if "asset" in alternative:
        return _asset(alternative["asset"], cited.get("asset"), sources)
    return _plan_value(alternative, sources.plan)


def _norm(text: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split()) if isinstance(text, str) else ""


def _missing(kind: str) -> str:
    return f"evidence.{kind} ({CITED[kind]}) is missing"


def _design(cite: Any, sources: Sources) -> str | None:
    design = (sources.plan.get("context") or {}).get("design")
    if not design:
        return "design: context.design is null, so no design contract was read"
    if not cite:
        return "design: " + _missing("design")
    path, _, anchor = str(cite).partition("#")
    if path.strip() and posixpath.normpath(path.strip()) != posixpath.normpath(design["path"]):
        return f"design: evidence.design names {path!r}, not the declared {design['path']}"
    if sources.design_text is None:
        return f"design: {design['path']} could not be read"
    leaf = anchor.rsplit(".", 1)[-1].strip()
    if not leaf or leaf not in sources.design_text:
        return f"design: {anchor!r} does not appear in {design['path']}"
    return None


def _brief(cite: Any, sources: Sources) -> str | None:
    if not _norm(cite):
        return "brief: " + _missing("brief")
    brief = sources.plan.get("brief") or {}
    lines = [brief.get("subject"), brief.get("one_job"), brief.get("audience"), *(brief.get("constraints") or ())]
    if any(_norm(cite) in _norm(line) for line in lines):
        return None
    return "brief: evidence.brief is not a line of brief"


def _listed(kind: str, cite: Any, listed: list[Any], where: str) -> str | None:
    if not _norm(cite):
        return f"{kind}: " + _missing(kind)
    if _norm(cite) in {_norm(item) for item in listed}:
        return None
    return f"{kind}: {str(cite)!r} is not in {where}"


def _material(cite: Any, sources: Sources) -> str | None:
    return _listed("material", cite, sources.plan.get("world_materials") or [], "world_materials")


def _source(cite: Any, sources: Sources) -> str | None:
    refs = [s.get("ref") for s in sources.plan.get("sources") or () if isinstance(s, dict)]
    return _listed("source", cite, refs, "sources")


def _exploration(cite: Any, sources: Sources) -> str | None:
    from lapis_design.lint.detectors.plan_candidates import entry_problems

    plan = sources.plan
    design = (plan.get("context") or {}).get("design")
    roles = [r for r in resolve(plan, "tokens.type.roles[*]") if isinstance(r, dict)]
    won = []
    for entry in plan.get("explorations") or ():
        if not isinstance(entry, dict) or entry.get("decision") != "type" or entry.get("fixed_by"):
            continue
        if entry_problems(entry, {}, design):
            continue
        covers = set(entry.get("covers") or ())
        if any(r.get("role") in covers and _norm(r.get("family")) == _norm(entry.get("chosen")) for r in roles):
            won.append(entry["chosen"])
    if not won:
        return "exploration: no complete type comparison in explorations was won by a face that a type role uses"
    if not _norm(cite):
        return f"exploration: {_missing('exploration')}; won: {', '.join(dict.fromkeys(won))}"
    if _norm(cite) in {_norm(name) for name in won}:
        return None
    return f"exploration: {str(cite)!r} won no comparison that a type role uses; won: {', '.join(dict.fromkeys(won))}"


def _asset(spec: dict, cite: Any, sources: Sources) -> str | None:
    needs = "; ".join(f"{field} {' or '.join(spec[field])}" for field in ("kind", "origin", "role") if spec.get(field))
    if sources.ledger is None:
        return "asset: no asset ledger was given"
    if not cite:
        return f"asset: {_missing('asset')}, with {needs}"
    asset = next((a for a in sources.ledger.get("assets") or () if isinstance(a, dict) and a.get("id") == cite), None)
    if asset is None:
        return f"asset: {str(cite)!r} is not in the asset ledger"
    task = (sources.plan.get("task") or {}).get("id")
    if task not in (asset.get("used_by") or ()):
        return f"asset: {cite!r} is not recorded as used by task {task!r}"
    for field in ("kind", "origin", "role"):
        if spec.get(field) and asset.get(field) not in spec[field]:
            return f"asset: {cite!r} has {field} {asset.get(field)!r}; the case needs {' or '.join(spec[field])}"
    return None


def _values(plan: dict, path: str) -> list[Any]:
    out: list[Any] = []
    for value in resolve(plan, path):
        out.extend(value if isinstance(value, list) else [value])
    return [v for v in out if v not in (None, "", [], {})]


def _plan_value(condition: dict, plan: dict) -> str | None:
    path = condition["plan"]
    values = _values(plan, path)
    seen = ", ".join(str(v) for v in values) if values else "no value"
    if "has" in condition:
        return None if any(v in condition["has"] for v in values) else \
            f"{path} must include {' or '.join(map(str, condition['has']))}; it has {seen}"
    if "lacks" in condition:
        return None if values and not any(v in condition["lacks"] for v in values) else \
            f"{path} must not include {' or '.join(map(str, condition['lacks']))}; it has {seen}"
    if "min" in condition:
        numbers = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return None if any(v >= condition["min"] for v in numbers) else \
            f"{path} must be at least {condition['min']}; it has {seen}"
    return None if values else f"{path} must be present in the plan"


_CHECKS = {"design": _design, "brief": _brief, "material": _material, "source": _source,
           "exploration": _exploration}
