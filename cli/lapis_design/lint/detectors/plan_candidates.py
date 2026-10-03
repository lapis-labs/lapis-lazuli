"""plan-candidates: whether each open decision in a plan was made between candidates, not taken as the
first answer (plan.uncompared-decision).

The plan's `explorations` hold one entry per decision: the candidates with their sources, what they
were compared on, the chosen one, and why the runner-up lost. A decision is open when the plan makes
it: each role of `tokens.type.roles`, the palette (`tokens.color.roles`), the layout structure
(`layout`), the motion level (`direction.dials.motion`), the direction (`direction.concept` or
`levers`), and each key copy slot the rule lists (`copy_slots`). An entry covers a type role or a copy
slot through its `covers`; every other decision has one entry. The detector reports an open decision
that no entry covers, and an entry that covers one without holding up:

- fewer distinct candidates than `min_candidates`, a `chosen` that is not one of them, no basis in
  `compared_on`, or no `runner_up_lost`
- type: every candidate is a generic family (fonts/system-fonts.yaml, or source `generic`), so no named
  face was considered; or the comparison was never seen (`compared_on` has neither `specimen` nor
  `render`)
- `fixed_by`: the entry says the contract or the brief fixes the decision, which exempts it from the
  comparison. `contract` holds only when the plan reads a DESIGN.md (`context.design`), and either
  value needs its `reason`. A type role whose `source` is `contract` is fixed the same way, and
  only when `context.design` is set.

It judges what the plan records, never whether the candidates were fairly compared; the critic reads
the specimens. Runs only in the plan modes the rule lists.
"""
from __future__ import annotations

from dataclasses import dataclass

from lapis_design import system_fonts
from lapis_design.lint.types import Context, Hit, Result, detector
from lapis_design.plan_check import resolve

SEEN = {"specimen", "render"}          # a face is judged on the page's own copy, not on facts or a sketch


@dataclass(frozen=True)
class Need:
    kind: str
    item: str | None = None             # a type role or a copy slot
    note: str = ""


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _needs(plan: dict, params: dict, design: object) -> list[Need]:
    needs: list[Need] = []
    seen_roles: set[str] = set()
    for role in resolve(plan, "tokens.type.roles[*]"):
        if not isinstance(role, dict):
            continue
        name = _text(role.get("role"))
        if not name or name in seen_roles:
            continue
        if role.get("source") == "contract":
            if design:
                continue                                # the contract names this face
            needs.append(Need("type", name, "contract"))
        else:
            needs.append(Need("type", name))
        seen_roles.add(name)
    if resolve(plan, "tokens.color.roles[*]"):
        needs.append(Need("palette"))
    if resolve(plan, "layout.sections[*]") or _text(next(iter(resolve(plan, "layout.procedure.archetype")), "")):
        needs.append(Need("layout"))
    if any(isinstance(v, int) and not isinstance(v, bool) for v in resolve(plan, "direction.dials.motion")):
        needs.append(Need("motion"))
    if _text(next(iter(resolve(plan, "direction.concept")), "")) or resolve(plan, "direction.levers[*]"):
        needs.append(Need("direction"))
    slots = params.get("copy_slots") or ()
    seen_slots: set[str] = set()
    for key in resolve(plan, "content.key_copy[*]"):
        slot = _text(key.get("slot")) if isinstance(key, dict) else ""
        if slot in slots and slot not in seen_slots:
            seen_slots.add(slot)
            needs.append(Need("copy", slot))
    return needs


def _names(entry: dict) -> list[str]:
    return list(dict.fromkeys(_text(c.get("name")).casefold() for c in entry.get("candidates") or ()
                              if isinstance(c, dict) and _text(c.get("name"))))


def entry_problems(entry: dict, params: dict, design: object) -> list[str]:
    """Why an entry does not hold up; empty when it is a complete comparison or a valid exemption."""
    fixed = entry.get("fixed_by")
    if fixed:
        problems = []
        if fixed == "contract" and not design:
            problems.append("fixed_by is contract, but context.design is null")
        if len(_text(entry.get("reason"))) < 8:
            problems.append(f"fixed_by is {fixed} without a reason that says what fixes it")
        return problems
    problems = []
    names = _names(entry)
    minimum = int(params.get("min_candidates") or 2)
    if len(names) < minimum:
        problems.append(f"{len(names)} distinct candidate{'s' * (len(names) != 1)} recorded, {minimum} needed")
    chosen = _text(entry.get("chosen")).casefold()
    if not chosen:
        problems.append("no chosen candidate")
    elif chosen not in names:
        problems.append(f"chosen {entry.get('chosen')!r} is not one of the candidates")
    on = {v for v in entry.get("compared_on") or () if isinstance(v, str)}
    if not on:
        problems.append("compared_on is empty")
    elif entry.get("decision") == "type" and not on & SEEN:
        problems.append("compared_on has neither a specimen nor a render of the page's own copy")
    if len(_text(entry.get("runner_up_lost"))) < 8:
        problems.append("no runner_up_lost: why the closest alternative lost")
    if entry.get("decision") == "type":
        named = [c for c in entry.get("candidates") or ()
                 if isinstance(c, dict) and _text(c.get("source")) != "generic"
                 and not system_fonts.is_generic(_text(c.get("name")))]
        if not named:
            problems.append("every candidate is a generic family, so no named face was considered; compare an "
                            "installed, catalog, Adobe, or commercial face")
    return problems


def _label(entry: dict) -> str:
    covers = entry.get("covers") or ()
    return f"{entry.get('decision')} {', '.join(covers)}" if covers else str(entry.get("decision"))


def _covered(need: Need, entry: dict) -> bool:
    if entry.get("decision") != need.kind:
        return False
    return need.item in (entry.get("covers") or ()) if need.item is not None else True


@detector("plan-candidates", layers=("plan",))
def plan_candidates(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    if ctx.plan is None:
        return Result(skipped="no plan given")
    params = det.get("params") or {}
    plan = ctx.plan
    if params.get("modes") and plan.get("mode") not in params["modes"]:
        return Result()
    design = (plan.get("context") or {}).get("design")
    entries = [(i, e) for i, e in enumerate(plan.get("explorations") or ()) if isinstance(e, dict)]
    here = {"file": ctx.plan_path} if ctx.plan_path else {}
    path = det.get("path") or "explorations"
    problems = {i: entry_problems(e, params, design) for i, e in entries}
    missing: list[Need] = []
    unsound: dict[int, None] = {}
    for need in _needs(plan, params, design):
        covering = [(i, e) for i, e in entries if _covered(need, e)]
        if not covering:
            missing.append(need)
        elif all(problems[i] for i, _ in covering):
            unsound[covering[0][0]] = None
    hits = []
    if missing:
        parts: dict[str, list[str]] = {}
        for need in missing:
            parts.setdefault(need.kind, []).append(need.item or "")
        said = [f"{ {'type': 'type roles', 'copy': 'copy slots'}[kind] } {', '.join(items)}" if kind in ("type", "copy")
                else kind for kind, items in parts.items()]
        claimed = [n.item for n in missing if n.note]
        if claimed:
            said.append(f"type roles {', '.join(claimed)} say source contract, but context.design is null, so no "
                        "contract fixes them")
        total = len(missing)
        hits.append(Hit(observed=f"{total} open decision{'s' * (total != 1)} with no comparison recorded in "
                                 f"explorations: {'; '.join(said)}",
                        location={**here, "path": path}, evidence="plan"))
    for i in unsound:
        hits.append(Hit(observed=f"explorations[{i}] ({_label(dict(entries)[i])}): {'; '.join(problems[i])}",
                        location={**here, "path": f"{path}[{i}]"}, evidence="plan"))
    return Result(hits=hits)
