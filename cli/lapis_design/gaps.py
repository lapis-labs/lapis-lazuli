"""The gap list: the decisions the owner block shows that the owner did not make, and the owner's word on them.

The agent fills in what nobody told it: the style's jobs, how a core object is represented, the signature, the color
roles and where they sit, the layout, the motion, the type roles, the copy's register. Which of those were the owner's is
a fact the records hold, so the CLI computes it (`compute`), and the owner block lists the rest under `## Decisions you
have not made` with what the agent filled in. Nothing is sealed or approved until the owner's reply acknowledges that
block by its digest (`- Gaps seen (lapis-owner-block <sha8>): "<their words>"`, an untagged line), or decides the items.

An area is decided by the owner when the answers file holds a `[declared]` item for it, or when the plan's `explorations`
fixes it by the brief with a reason that quotes a live requirement-row id (`fixed_by: brief` and, in `reason`, an `R...` id
of `.lapis/requirements/<task>.json`; a `fixed_by: brief` that quotes none stays a gap, marked so). Direction areas (style,
objects, signature) are decided by the direction answers (`direction.items`): by the owner, never `[assumed]`.

| Area | Decided when | "Filled in" comes from |
|---|---|---|
| style | each `S`/`K` item `decided` by the owner | the default taken |
| objects | each `O` item `decided`, or `narrowed` and picked by the owner | the picked card's representation |
| signature | each `G` item of the proposal and the pick `decided` | `layout.signature`, `direction.levers` |
| color | `[declared] color: ...`, or a palette exploration fixed by the brief | `tokens.color.roles`: role, value, `area` |
| layout | `[declared] layout: ...`, or a layout exploration fixed by the brief | `layout.procedure.archetype`, the section ids |
| motion | `[declared] motion: ...`, or a motion exploration fixed by the brief | `direction.dials.motion`, a motion principle |
| type | per role: `[declared] type <role>: ...`, or a type exploration fixed by the brief that covers the role | `tokens.type.roles` |
| copy | per locale: `[declared] copy <locale> <role>: ...`, or a copy exploration fixed by the brief | `content.voice.locales`, the headline |

`owner.write` records the ids of the gaps each block listed in `.lapis/state/<task>.gaps.json` (a record only the CLI
writes), so `unacknowledged` can say which gaps the block an approval question carried listed, whatever changed after.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from lapis_design import direction, requirements, waiting

AREAS = ("style", "objects", "signature", "color", "layout", "motion", "type", "copy")
KEEP_BLOCKS = 20                       # blocks whose gap ids the record keeps
SEEN = re.compile(r"^[ \t]*[-*+][ \t]+Gaps seen[ \t]*\(lapis-owner-block ([0-9a-f]{8})\)[ \t]*:[ \t]*(\S.*)$",
                  re.IGNORECASE | re.MULTILINE)
_TYPE = re.compile(r"^type\s+(\S+?)\s*:", re.IGNORECASE)
_COPY = re.compile(r"^copy\s+(\S+)\s+\S+\s*:", re.IGNORECASE)
_HEAD = {area: re.compile(rf"^{area}\s*:", re.IGNORECASE) for area in ("signature", "color", "layout", "motion")}


def state_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "state" / f"{task}.gaps.json"


def _cut(text: Any, limit: int = 100) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _plan(root: Path, task: str) -> dict:
    from lapis_design.plan_check import read_plan

    try:
        plan = read_plan(root / ".lapis" / "plans" / f"{task}.yaml")
    except Exception:                                      # a plan that cannot be read has no gaps to list
        return {}
    return plan if isinstance(plan, dict) else {}


def _declared(root: Path, task: str) -> list[str]:
    """The words after the tag of each `[declared]` top-level item of the answers file."""
    try:
        text = (root / ".lapis" / "answers" / f"{task}.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [body for _, _, body in requirements._declared_items(text)]


def _fixed(plan: Mapping[str, Any], rows: set[str], decision: str) -> list[dict] | None:
    """The explorations of `decision` fixed by the brief with a reason that quotes a live row id, or None when there is
    a `fixed_by: brief` entry that quotes none (a gap, marked so), or [] when there is none."""
    found: list[dict] = []
    unquoted = False
    for entry in plan.get("explorations") or ():
        if isinstance(entry, Mapping) and entry.get("decision") == decision and entry.get("fixed_by") == "brief":
            if rows & set(requirements._ID.findall(str(entry.get("reason") or ""))):
                found.append(entry)
            else:
                unquoted = True
    return None if unquoted and not found else found


def _fixed_note(plan: Mapping[str, Any], rows: set[str], decision: str) -> str:
    return " (plan says fixed by the brief; no row quoted)" if _fixed(plan, rows, decision) is None else ""


def _num(value: Any) -> str:
    text = f"{value:.3g}" if isinstance(value, (int, float)) else str(value)
    return text[1:] if text.startswith("0.") else text


def _color(plan: Mapping[str, Any]) -> str:
    roles = [r for r in ((plan.get("tokens") or {}).get("color") or {}).get("roles") or ()
             if isinstance(r, Mapping) and r.get("role") in ("field", "identity")]
    parts = []
    for role in roles:
        value = (f"oklch({' '.join(_num(n) for n in role['oklch'])})" if isinstance(role.get("oklch"), list)
                 else str(role.get("ref") or role.get("name") or ""))
        theme = f" [{role['theme']}]" if role.get("theme") else ""
        parts.append(f"{role['role']}{theme} {value} — {_cut(role['area'], 120) if role.get('area') else 'no area said'}")
    return "; ".join(parts) or "no field or identity color in the plan"


def _layout(plan: Mapping[str, Any]) -> str:
    layout = plan.get("layout") or {}
    archetype = (layout.get("procedure") or {}).get("archetype")
    sections = [s["id"] for s in layout.get("sections") or () if isinstance(s, Mapping) and s.get("id")]
    return "; ".join(part for part in (str(archetype) if archetype else "",
                                       f"sections {', '.join(sections)}" if sections else "") if part) \
        or "no archetype or sections in the plan"


def _motion(plan: Mapping[str, Any]) -> str:
    dial = ((plan.get("direction") or {}).get("dials") or {}).get("motion")
    principles = ((plan.get("tokens") or {}).get("motion") or {}).get("principles") or ()
    parts = [f"dial {dial} of 10"] if dial is not None else []
    if principles:
        parts.append(f"\"{_cut(principles[0])}\"")
    return "; ".join(parts) or "no motion dial or principle in the plan"


def _roles(by_role: Any) -> str:
    """`headline/label/action compact; error haeyo`: the roles that share a register, in order of first appearance."""
    if not isinstance(by_role, Mapping):
        return _cut(by_role) if by_role else ""
    grouped: dict[str, list[str]] = {}
    for role, register in by_role.items():
        grouped.setdefault(str(register), []).append(str(role))
    return "; ".join(f"{'/'.join(roles)} {register}" for register, roles in grouped.items())


def _copy(plan: Mapping[str, Any], locale: str) -> str:
    voice = ((plan.get("content") or {}).get("voice") or {}).get("locales", {}).get(locale) or {}
    head = next((c["text"] for c in (plan.get("content") or {}).get("key_copy") or ()
                 if isinstance(c, Mapping) and c.get("slot") == "headline"
                 and str(c.get("locale") or locale).split("-")[0] == locale.split("-")[0]), None)
    parts = [part for part in (f"prose {voice['prose']}" if voice.get("prose") else "", _roles(voice.get("by_role")),
                               f"headline \"{_cut(head)}\"" if head else "") if part]
    return "; ".join(parts) or "no voice or headline in the plan"


def _direction(root: Path, task: str, env: Mapping[str, str]) -> tuple[list[dict], dict | None]:
    return direction.items(root, task, env), direction.pick(root, task, env)


def _picked_card(root: Path, task: str, pick: Mapping[str, Any] | None) -> dict:
    """The card of the picked candidate, as the agent wrote it, or {}."""
    import yaml

    if not pick:
        return {}
    try:
        doc = yaml.safe_load((root / ".lapis" / "diverge" / task / pick["candidate"] / "card.yaml")
                             .read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _option(item: Mapping[str, Any], choice: str) -> str:
    text = next((o.get("text") for o in item.get("options") or () if o.get("id") == choice), None)
    return f"{choice} \"{_cut(text, 60)}\"" if text and item["kind"] != "K" else choice


def _style(items: Iterable[Mapping[str, Any]]) -> list[dict]:
    out = []
    for item in items:
        if item["kind"] in ("S", "K") and not (item["state"] == "decided" and item["by"] == "owner"):
            taken = "defaults accepted" if item["state"] == "delegated" else "default"
            out.append({"id": f"style:{item['id']}", "area": "style",
                        "text": f"style: {item['id']} {_cut(item['label'], 60)} → "
                                f"{_option(item, str(item['default']))} ({taken})"})
    return out


def _objects(items: Iterable[Mapping[str, Any]], pick: Mapping[str, Any] | None, card: Mapping[str, Any]) -> list[dict]:
    out = []
    represented = {o.get("id"): o.get("representation") for o in card.get("objects") or () if isinstance(o, Mapping)}
    for item in items:
        if item["kind"] != "O":
            continue
        owner_decided = item["state"] == "decided" and item["by"] == "owner"
        picked = item["state"] == "narrowed" and pick is not None and pick["by"] == "owner"
        if owner_decided or picked:
            continue
        filled = represented.get(item["id"]) or f"default {item['default']}"
        out.append({"id": f"objects:{item['id']}", "area": "objects",
                    "text": f"objects: {item['id']} {_cut(item['label'], 60)} → {_cut(filled, 100)}"})
    return out


def _signature(plan: Mapping[str, Any], items: Iterable[Mapping[str, Any]], pick: Mapping[str, Any] | None) -> list[dict]:
    wanted = [i for i in items if i["kind"] == "G" and i.get("candidate") in (None, pick["candidate"] if pick else None)]
    undecided = [i["id"] for i in wanted if not (i["state"] == "decided" and i["by"] == "owner")]
    if wanted and not undecided:
        return []
    sign = (plan.get("layout") or {}).get("signature")
    levers = (plan.get("direction") or {}).get("levers") or ()
    parts = [f"layout.signature \"{_cut(sign)}\"" if sign else "", f"lever \"{_cut(levers[0])}\"" if levers else "",
             f"items {', '.join(undecided)} not decided" if undecided else ""]
    summary = "; ".join(part for part in parts if part)
    return [{"id": "signature", "area": "signature", "text": f"signature: {summary}"}] if summary else []


def compute(root: Path, task: str, env: Mapping[str, str] = os.environ) -> list[dict]:
    """The gaps of `task` under `root`, in the order of `AREAS`: `{"id", "area", "text"}`, `text` the line the owner
    block shows. Nothing here reads a time, so the same files give the same list."""
    root = Path(root)
    plan = _plan(root, task)
    if not plan:
        return []
    declared = _declared(root, task)
    record = requirements.rows(root, task) or []
    rows = {r["id"] for r in record}
    items, pick = _direction(root, task, env)
    card = _picked_card(root, task, pick)
    out = _style(items) + _objects(items, pick, card)
    if not any(_HEAD["signature"].match(body) for body in declared):
        out += _signature(plan, items, pick)
    for area, summary in (("color", _color), ("layout", _layout), ("motion", _motion)):
        if not any(_HEAD[area].match(body) for body in declared) and not _fixed(plan, rows, "palette" if area == "color" else area):
            note = _fixed_note(plan, rows, "palette" if area == "color" else area)
            out.append({"id": area, "area": area, "text": f"{area}: {summary(plan)}{note}"})
    roles = ((plan.get("tokens") or {}).get("type") or {}).get("roles") or ()
    typed = _fixed(plan, rows, "type") or []
    for role in roles:
        if not isinstance(role, Mapping) or not role.get("role"):
            continue
        said = any((m := _TYPE.match(body)) and m.group(1).lower() == role["role"] for body in declared)
        if said or any(role["role"] in (e.get("covers") or ()) for e in typed):
            continue
        scripts = f" ({', '.join(role['scripts'])})" if role.get("scripts") else ""
        out.append({"id": f"type:{role['role']}", "area": "type",
                    "text": f"type: {role['role']}{scripts} {role.get('family', '')}".rstrip()
                            + _fixed_note(plan, rows, "type")})
    locales = (((plan.get("content") or {}).get("voice") or {}).get("locales") or {})
    for locale in locales if isinstance(locales, Mapping) else ():
        said = any((m := _COPY.match(body)) and m.group(1).lower() == str(locale).lower() for body in declared)
        if not said and not _fixed(plan, rows, "copy"):
            out.append({"id": f"copy:{locale}", "area": "copy",
                        "text": f"copy: {locale}: {_copy(plan, str(locale))}{_fixed_note(plan, rows, 'copy')}"})
    return out


def _record(root: Path, task: str) -> dict[str, list[str]]:
    try:
        doc = json.loads(state_path(root, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    blocks = doc.get("blocks") if isinstance(doc, dict) else None
    return {k: v for k, v in (blocks or {}).items() if isinstance(v, list)} if isinstance(blocks, dict) else {}


def record(root: Path, task: str, sha8: str, ids: list[str]) -> None:
    """Remember that the owner block with digest `sha8` listed the gaps `ids`. A record that cannot be written is left
    as it was: `unacknowledged` then reads the gaps as they are now."""
    blocks = _record(root, task)
    if blocks.get(sha8) == ids:
        return
    blocks.pop(sha8, None)
    blocks[sha8] = ids
    blocks = dict(list(blocks.items())[-KEEP_BLOCKS:])
    try:
        requirements.write_atomic(state_path(root, task), json.dumps(
            {"version": 0, "task": task, "blocks": blocks}, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        pass


def seen(root: Path, task: str) -> set[str]:
    """The block digests the answers file acknowledges: each `- Gaps seen (lapis-owner-block <sha8>): "<words>"` line."""
    try:
        text = (root / ".lapis" / "answers" / f"{task}.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {m.group(1) for m in SEEN.finditer(text)}


def unacknowledged(root: Path, task: str, sha8: str | None, env: Mapping[str, str] = os.environ) -> list[dict]:
    """The gaps of the owner block with digest `sha8` that the owner has neither acknowledged nor decided: none when a
    `Gaps seen` line names `sha8`; otherwise each gap that block listed and that is still a gap now (an area the owner
    decided since is no longer one). A block the record does not know (`sha8` is None, or not one `owner.write` wrote)
    stands for every gap there is now."""
    current = {g["id"]: g for g in compute(root, task, env)}
    if sha8 is not None and sha8 in seen(root, task):
        return []
    listed = _record(root, task).get(sha8) if sha8 is not None else None
    return [current[i] for i in (listed if listed is not None else current) if i in current]


def problem(missing: list[dict], sha8: str | None, *, approval: str) -> str:
    """What `next` says while `missing` gaps are unacknowledged. `approval` names what is not approved yet."""
    shown = "; ".join(g["text"] for g in missing[:3]) + (f"; and {len(missing) - 3} more" if len(missing) > 3 else "")
    where = f"(lapis-owner-block {sha8})" if sha8 else "(lapis-owner-block <sha8>)"
    return (f"The owner block you showed lists {len(missing)} decisions the owner did not make ({shown}). Record the "
            f"owner's acknowledgment as `- Gaps seen {where}: <their words>` in the answers file, or their decision on "
            f"each (`- [declared] color: <what they decided>`, `- [declared] layout: ...`), then run `next`. {approval} is "
            "not approved while they are unacknowledged.")


def approval_problem(root: Path, task: str, plan: Any, env: Mapping[str, str] = os.environ) -> str | None:
    """What the step `approval-gaps` says, or None: a redesign or repair plan says `approval: {state: approved}` and an
    approval question was asked and answered, but the owner block it carried lists decisions the owner did not make and
    has not acknowledged. An unattended run needs no acknowledgment: the block's section is the record."""
    if (not isinstance(plan, Mapping) or plan.get("mode") == "create" or env.get(waiting.ENV) == "1"
            or (plan.get("approval") or {}).get("state") != "approved"):
        return None
    current = waiting.current(root, task)
    if current is None or current["kind"] != "approval" or not current["answered"]:
        return None
    carried = waiting.carried(current["text"])
    if missing := unacknowledged(root, task, carried, env):
        return problem(missing, carried, approval="The plan")
    return None
