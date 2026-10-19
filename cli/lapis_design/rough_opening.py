"""What a rough's opening is, read from its own render: the composition every generated page opens with.

The pair distance of `diverge check` counts where text, media, and controls sit and how the color is spread, so two roughs
that open as the same hero (a headline and a button on one side, an app window on the other) can still count as different.
These checks read each rough's render extract with rules the lint of built pages already has, so the default is named at the
rough stage, before the owner picks between two copies of it:

- **The rules** (`rough_opening.rules` in `diverge/pools.yaml`): `layout.split-hero`, `layout.crowded-hero`, and
  `component.fake-app-window`, run through the lint engine on the rough's extract with their detectors, as at a build. A hit
  counts when its box starts in the first view.
- **A set** whose every rough trips the same rule is refused, naming the rule and the roughs. A set where only some do passes,
  and the owner block and the pick question say which rough opens that way.
- **What lifts it** is only the brief: `opening.keeps` quotes the owner's `[declared]` line about the opening that asks for
  what the rule flags (a two-column opening, a window in the first view). A keep condition the rule lists for a built page
  (a won comparison, a labeled illustration) does not lift it here: no owner has compared the roughs yet.
- **The brief** (`diverge contract`): an opening that carries all four of identity, claim, decisive-object, and
  primary-action is refused unless `opening.carries_by` quotes the owner's `[declared]` line about the opening. The first
  view's job is three things; an owner's answer about the order of work is a plan of work and is no such line.

The quotes and the term lists are lexical and a lead for the gate (`rough_opening` in the pools file): the owner judges the
opening.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from lapis_design import diverge, owner_text, rough_carries

ALL_CARRIES = frozenset({"identity", "claim", "decisive-object", "primary-action"})
ASKS = {"layout.split-hero": "a two-column opening", "layout.crowded-hero": "that proof or copy in the first view",
        "component.fake-app-window": "an app window in the first view"}      # what a `keeps` quote asks for, by rule


def rules() -> dict[str, Any]:
    return diverge.pools()["rough_opening"]


def _first_view(extract: Mapping[str, Any], location: Mapping[str, Any]) -> bool:
    """Whether the box a finding names starts in the first view of the capture it was found in; a finding that names no
    box counts."""
    box_id = location.get("box")
    if box_id is None:
        return True
    for view in extract.get("viewports") or ():
        if view.get("width") != location.get("viewport"):
            continue
        for box in view.get("boxes") or ():
            if box.get("id") == box_id:
                return (box.get("rect") or {}).get("y", 0) < (view.get("height") or diverge.VIEWS[1440][1])
    return True


def opens(root: Path, task: str, candidate: str) -> dict[str, str]:
    """The opening rules the render of `candidate` trips, as `{rule id: what the detector observed}`, in the pools' order.
    Empty when there is no render to read or no rule hits."""
    from lapis_design.lint import engine
    from lapis_design.lint.types import Context

    extract = diverge._json(diverge.extract_path(root, task, candidate))
    if not isinstance(extract, dict):
        return {}
    ctx = Context(rules=diverge.shared_yaml("slop/rules.yaml"), extract=extract)
    wanted = rules()["rules"]
    found: dict[str, str] = {}
    for finding in engine.lint(ctx, ["render"], wanted):
        if finding["status"] == "open" and finding["rule_id"] not in found and _first_view(extract, finding["location"]):
            found[finding["rule_id"]] = finding["observed"]
    return {rule: found[rule] for rule in wanted if rule in found}


def lifted(root: Path, task: str) -> set[str]:
    """The rules the shared brief keeps (`opening.keeps`); `diverge contract` has read each quote against the record."""
    found = diverge.brief(root, task)
    opening = found.get("opening") if isinstance(found, dict) else None
    keeps = opening.get("keeps") if isinstance(opening, dict) else None
    return {row["rule"] for row in keeps or () if isinstance(row, dict) and isinstance(row.get("rule"), str)}


def says(lang: str, rule: str) -> str:
    return owner_text.say(lang, f"rough.opens.{rule}")


# ---------------------------------------------------------------- the set

def set_problems(root: Path, task: str, candidates: list[str]) -> list[str]:
    """One problem for each rule that every rough of the set trips (two roughs or more) and the brief does not keep."""
    if len(candidates) < 2:
        return []
    found = {c: opens(root, task, c) for c in candidates}
    kept = lifted(root, task)
    problems = []
    for rule in rules()["rules"]:
        if rule in kept or not all(rule in found[c] for c in candidates):
            continue
        problems.append(
            f"every rough ({', '.join(candidates)}) {says('en', rule)} ({rule}; {found[candidates[0]][rule]}): a set whose every "
            "rough opens on the default composition differs in finish only, and the owner would pick between copies of it. Open at "
            "least one rough on the relation between its claim and its object (where the object stands, what is drawn of it, or what "
            "the first view holds instead), and render it again. Only the brief lifts this: `opening.keeps` with "
            f"`rule: {rule}` and `by`, the owner's `[declared]` line about the opening that asks for {ASKS[rule]}, quoted")
    return problems


# ---------------------------------------------------------------- the brief

def quote_problem(root: Path, task: str, quote: str, terms: list[str] | None) -> str | None:
    """Why `quote` does not stand as the owner's `[declared]` line about the opening (that asks for one of `terms`, when
    given), or None when it does."""
    wanted = rough_carries._squash(quote)
    lines = [rough_carries._squash(words) for _, words in rough_carries.declared_words(root, task)]
    standing = [line for line in lines if wanted in line]
    if not standing:
        return "is in no `[declared]` line of the brief record"
    if not any(rough_carries._find(line, rules()["opening_words"]) for line in standing):
        return "is in a `[declared]` line that does not speak of the opening (the first view, the first screen, the hero)"
    if terms is not None and not any(rough_carries._find(line, terms) for line in standing):
        return "is in a `[declared]` line that asks for none of what the rule flags (it has no term of `rough_opening.asks`)"
    return None


def contract_problems(root: Path, task: str, found: Mapping[str, Any]) -> list[str]:
    """What is wrong with the opening of the shared brief: all four carries with no owner `[declared]` line about the
    opening quoted in `carries_by`, and a `keeps` row whose quote is not such a line that asks for what its rule flags."""
    where = f".lapis/diverge/{task}/brief.yaml"
    opening = found["opening"]
    problems = []
    if set(opening["carries"]) == ALL_CARRIES:
        quote = opening.get("carries_by")
        if quote is None:
            problems.append(
                f"{where}: the opening carries identity, claim, decisive-object, and primary-action. The first view's job is three "
                "things: who and what (`identity`, with the claim in it), one decisive object, and the primary action; with all "
                "four the claim, the object, and the action share the screen with the headline, and every rough opens as the same "
                "hero around the object. List `identity`, `decisive-object`, and `primary-action`; keep all four only with "
                "`opening.carries_by`, the owner's `[declared]` line about the opening that asks for them, quoted. An answer about "
                "the order of work (\"build the library window first\") is a plan of work, not that line, and `resolved` may not "
                "turn it into one")
        elif why := quote_problem(root, task, quote, None):
            problems.append(f"{where}: opening.carries_by quotes \"{quote[:60]}\", which {why}")
    for row in opening.get("keeps") or ():
        if why := quote_problem(root, task, row["by"], rules()["asks"].get(row["rule"], [])):
            problems.append(f"{where}: opening.keeps {row['rule']} quotes \"{row['by'][:60]}\", which {why}")
    return problems


# ---------------------------------------------------------------- what the owner is shown

def owner_lines(root: Path, task: str, candidates: list[str], lang: str = "en") -> list[str]:
    """Per rough that trips an opening rule the brief does not keep, one line for the owner block and the pick question:
    how it opens (\"opens as a split hero\"). A rough that trips none gets no line."""
    kept = lifted(root, task)
    lines = []
    for candidate in candidates:
        if tripped := [rule for rule in opens(root, task, candidate) if rule not in kept]:
            lines.append(owner_text.say(lang, "rough.opening", candidate=candidate,
                                        says="; ".join(says(lang, rule) for rule in tripped)))
    return lines
