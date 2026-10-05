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
- palette claiming `render`: each candidate has an artifact and roles or a token file, and matched
  comparisons name the variable, viewport/theme, state, and a capture for every candidate
- `fixed_by`: the entry says the contract or the brief fixes the decision, which exempts it from the
  comparison. `contract` holds only when the plan reads a DESIGN.md (`context.design`), and either
  value needs its `reason`. A type role whose `source` is `contract` is fixed the same way, and
  only when `context.design` is set.

It checks recorded evidence and a bounded source-identity signal for rendered HTML alternatives.
It does not decide fairness or visual quality; the critic reads the actual specimens and playback.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from lapis_design import system_fonts
from lapis_design.lint.types import Context, Hit, Result, detector
from lapis_design.plan_check import resolve
from pathlib import Path

SEEN = {"specimen", "render"}          # a face is judged on the page's own copy, not on facts or a sketch


@dataclass(frozen=True)
class Need:
    kind: str
    item: str | None = None             # a type role or a copy slot
    note: str = ""
    family: str = ""
    scripts: tuple[str, ...] = ()


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _needs(plan: dict, params: dict, design: object) -> list[Need]:
    needs: list[Need] = []
    seen_roles: set[tuple] = set()
    for role in resolve(plan, "tokens.type.roles[*]"):
        if not isinstance(role, dict):
            continue
        name = _text(role.get("role"))
        key = (name, role.get("family"), tuple(role.get("scripts") or ()))
        if not name or key in seen_roles:
            continue
        if role.get("source") == "contract":
            if design:
                continue                                # the contract names this face
            needs.append(Need("type", name, "contract", _text(role.get("family")), tuple(role.get("scripts") or ())))
        else:
            needs.append(Need("type", name, family=_text(role.get("family")), scripts=tuple(role.get("scripts") or ())))
        seen_roles.add(key)
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


def palette_render_problems(entry: dict) -> list[str]:
    """Missing reproducibility or matched-view evidence, not proof that files were seen or are fair."""
    problems = []
    candidates = [c for c in entry.get("candidates") or () if isinstance(c, dict)]
    for candidate in candidates:
        name = candidate.get("name")
        if not _text(candidate.get("artifact")):
            problems.append(f"palette candidate {name!r} has no artifact")
        if not candidate.get("roles") and not _text(candidate.get("token_file")):
            problems.append(f"palette candidate {name!r} has no roles or token_file")
    comparisons = entry.get("comparisons") or ()
    if not comparisons:
        problems.append("palette render has no comparisons with matched captures")
    for index, comparison in enumerate(comparisons):
        if not isinstance(comparison, dict):
            problems.append(f"palette comparisons[{index}] is not a matched view")
            continue
        viewport = comparison.get("viewport") or {}
        width = viewport.get("width")
        if not isinstance(width, int) or isinstance(width, bool) or width <= 0 or not _text(viewport.get("theme")):
            problems.append(f"palette comparisons[{index}] has no viewport width/theme")
        for key in ("variable", "state"):
            if not _text(comparison.get(key)):
                problems.append(f"palette comparisons[{index}] has no {key}")
        captures = comparison.get("captures") or {}
        for candidate in candidates:
            if not _text(captures.get(candidate.get("name"))):
                problems.append(f"palette comparisons[{index}] has no capture for {candidate.get('name')!r}")
    return problems


def booking_phone_problems(entry: dict, plan: dict) -> list[str]:
    brief = plan.get("brief") or {}
    archetype = ((plan.get("layout") or {}).get("procedure") or {}).get("archetype")
    booking = (brief.get("product_frame") == "forms-onboarding-checkout" or archetype == "form") and re.search(
        r"\b(?:book|booking|appointment|reservation)\b|예약|진료|予約|预订", brief.get("one_job", ""), re.I)
    if not booking or entry.get("decision") != "layout" or entry.get("fixed_by"):
        return []
    problems = []
    modes = {c.get("form_mode") for c in entry.get("candidates") or []}
    if not {"staged", "continuous"} <= modes:
        problems.append("booking layout needs staged and continuous candidates with the same real fields")
    phone = [c for c in entry.get("comparisons") or []
             if isinstance((c.get("viewport") or {}).get("width"), int)
             and 0 < c["viewport"]["width"] <= 430]
    if "render" not in (entry.get("compared_on") or []) or not phone:
        problems.append("booking shortness is unobserved without a matched phone render")
    elif not any(c.get("state") and c.get("fields")
                 and all(_text(c["captures"].get(candidate.get("name"))) for candidate in entry.get("candidates") or [])
                 for c in phone if isinstance(c.get("captures"), dict)):
        problems.append("booking phone comparison needs real field labels, availability state and every candidate's capture")
    return problems


def entry_problems(entry: dict, params: dict, design: object, root: Path | None = None) -> list[str]:
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
    if entry.get("decision") == "palette" and "render" in on:
        problems.extend(palette_render_problems(entry))
    from lapis_design.alternatives import files_problem

    problems.extend(files_problem(entry, root))
    return problems


def _label(entry: dict) -> str:
    covers = entry.get("covers") or ()
    return f"{entry.get('decision')} {', '.join(covers)}" if covers else str(entry.get("decision"))


def _covered(need: Need, entry: dict) -> bool:
    if entry.get("decision") != need.kind:
        return False
    if need.item is None:
        return True
    if need.item not in (entry.get("covers") or ()):
        return False
    return need.kind != "type" or not entry.get("scripts") or set(need.scripts) <= set(entry["scripts"])


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
    problems = {i: entry_problems(e, params, design, ctx.project_root) + booking_phone_problems(e, plan)
                for i, e in entries}
    missing: list[Need] = []
    unsound: dict[int, None] = {}
    for need in _needs(plan, params, design):
        covering = [(i, e) for i, e in entries if _covered(need, e)]
        if not covering:
            missing.append(need)
        elif need.kind == "type" and not any(e.get("fixed_by") or _text(e.get("chosen")).casefold() == need.family.casefold()
                                             for _, e in covering):
            i = covering[0][0]
            problems[i].append(f"chosen face does not decide {need.item} / {list(need.scripts)} using {need.family}")
            unsound[i] = None
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
