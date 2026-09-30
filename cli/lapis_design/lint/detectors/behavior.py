"""Behavior-layer detectors: they read the behavior session (behavior/session.schema.yaml) with the
derived values of behavior/DERIVED.md filled, and report what the driver observed.

Coverage: the engine adds one skipped finding for each probe of a detector (its `probes` in
slop/detectors.yaml) that ran partly, not at all, or left no coverage entry, so an empty probe list
here means nothing to report. A detector skips on its own only when the session is missing or when
observations it needs were not measured; those are named in `Result.skipped` next to the hits that
could be judged, so a missing measurement never reads as a pass.

Hints: a flow observation with `hint_mismatch` (a data-lapis-* hint the page reading does not
confirm) decides no verdict, pass or fail. flow-analysis names it in `Result.skipped`, which the
engine reports as a non-blocking finding with evidence `not-verified`, and judges the rest.
"""
from __future__ import annotations

from typing import Any, Iterable

from lapis_design.behavior import EXIT_KINDS, RECURRING_CADENCE, derive_session, matches_promise, required_terms
from lapis_design.lint.types import Context, Hit, Result, detector

RUNTIME = "runtime"
PRIMARY_BLOCKED = "the primary task is blocked"
CHARGE_ADDED = "the preselected option adds a charge"
TRIAL_CONVERTS = "a free or discounted trial converts to a paid plan"
CONTACT_REQUIRED = "leaving cannot be finished without contacting the business"
CONTACT_CHANNELS = {"phone", "chat", "email", "request-form"}
UNFINISHED = {"blocked", "dead-end", "abandoned"}
ANNUAL = {"day": 365, "week": 52, "month": 12, "year": 1}
PRICE_EPSILON = 0.005


# ---------------------------------------------------------------- session access

def _underived(session: dict, plan_flows: list[dict] | None) -> bool:
    """True when a derived value the detectors read is missing (DERIVED.md says where each exists)."""
    probes = session.get("probes") or {}
    nodes = session.get("nodes") or {}
    runs = session.get("flows") or []
    if (any("derived" not in item for name in ("controls", "keyboard", "dialogs", "urgency")
            for item in probes.get(name, []))
            or any("derived" not in run for run in runs)
            or any("derived" not in c and any(o["kind"] == "accept" for o in c["options"])
                   for c in probes.get("choices", []))
            or any("derived" not in p and p["expected_px"] > 0 for p in probes.get("scroll", []))
            or any("focus_visible" not in st and st.get("indicator")
                   and (st.get("rect") or (nodes.get(st["box"]) or {}).get("rect"))
                   for walk in probes.get("keyboard", []) for st in walk["stops"])):
        return True
    pairs = {f["id"]: f.get("pair") for f in plan_flows or []}
    by_key = {(r["id"], r["context"]): r for r in runs}
    return any(r["kind"] in EXIT_KINDS and "exit" not in r["derived"]
               and (by_key.get((pairs.get(r["id"]), r["context"])) or {}).get("status") == "completed"
               for r in runs)


def _session(ctx: Context) -> dict | None:
    """The session with derived values filled, computed once per run."""
    if ctx.session is None:
        return None
    key = "behavior:session"
    if key not in ctx.cache:
        flows = (ctx.plan or {}).get("flows")
        ctx.cache[key] = derive_session(ctx.session, flows) if _underived(ctx.session, flows) else ctx.session
    return ctx.cache[key]


def _no_session() -> Result:
    return Result(skipped="no behavior session given")


def _items(session: dict, probe: str) -> list[dict]:
    if probe == "flows":
        return session.get("flows") or []
    if probe == "console":
        return session.get("console") or []
    return (session.get("probes") or {}).get(probe) or []


def _params(det: dict) -> dict:
    return det.get("params") or {}


def _list(value: Any) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _bound(det: dict, key: str) -> float | None:
    value = (det.get("threshold") or {}).get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _result(hits: list[Hit], unjudged: Iterable[str] = ()) -> Result:
    notes = list(dict.fromkeys(unjudged))
    return Result(hits=hits, skipped="; ".join(notes) if notes else None)


def _unknown_check(check: Any) -> Result:
    return Result(skipped=f"unknown or missing check {check!r} for this detector")


def _no_bound(key: str) -> Result:
    return Result(skipped=f"the rule sets no threshold {key}")


def _ref(ctx: Context, *parts: Any) -> str:
    return f"{ctx.session_path or 'session'}#/" + "/".join(str(p) for p in parts)


def _label(session: dict, box: str | None) -> str:
    if not box:
        return "the page"
    node = (session.get("nodes") or {}).get(box) or {}
    role = node.get("role", "box")
    name = node.get("name")
    return f'{role} "{_clip(name)}"' if name else f"{role} {box}"


def _clip(text: str, limit: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _loc(session: dict, context: str | None = None, **keys: Any) -> dict:
    out = {k: v for k, v in keys.items() if v is not None}
    if context:
        out["context"] = context
        width = next((c.get("width") for c in session.get("contexts") or [] if c["id"] == context), None)
        if width is not None:
            out["viewport"] = width
    return out


def _fmt(value: float) -> str:
    return f"{value:g}"


def _primary_boxes(session: dict, unfinished_only: bool) -> set[str]:
    """Boxes the driver acted on during runs of the plan's primary flow."""
    boxes: set[str] = set()
    for run in session.get("flows") or []:
        if run["kind"] != "primary" or (unfinished_only and run["status"] not in UNFINISHED):
            continue
        for step in run.get("steps") or []:
            boxes.update(a["target"] for a in step.get("actions") or [] if a.get("target"))
    return boxes


# ---------------------------------------------------------------- controls and console

@detector("control-has-effect", layers=("behavior",))
def control_has_effect(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    console = "console-errors" in _list(_params(det).get("also"))
    blocked = _primary_boxes(s, unfinished_only=True)
    nodes = s.get("nodes") or {}
    groups: dict[tuple[str, str, str], list[tuple[int, dict]]] = {}
    for i, c in enumerate(_items(s, "controls")):
        effect, promise = c["effect"], c.get("promise") or "other"
        if effect.get("external"):                     # stopped at another host: it navigated
            result, matches = "navigated", matches_promise(promise, "navigated")
        else:
            result = effect["outcome"]
            matches = (c.get("derived") or {}).get("matches_promise", matches_promise(promise, result))
        if (result == "no-effect" and (nodes.get(c["box"]) or {}).get("role") == "input"
                and effect.get("focus_to") == c["box"]):
            continue                                   # an entry field took focus; the forms probe judges entry
        errors = effect.get("console_errors") or 0
        if result == "no-effect":
            what = "nothing visible or requested happened"
        elif result == "error":
            what = f"only {errors} console error(s) followed"
        elif not matches:
            what = f"the outcome was {result}"
        elif console and errors:
            what = f"the outcome was {result} with {errors} console error(s)"
        else:
            continue
        groups.setdefault((c["box"], promise, what), []).append((i, c))
    hits = []
    for (box, promise, what), probes in groups.items():   # one hit per control, naming every context
        actions = ", ".join(dict.fromkeys(f"{c['action']['kind']} ({c['context']})" for _, c in probes))
        hits.append(Hit(
            observed=f"{_label(s, box)} promises {promise}; on {actions} {what}",
            location=_loc(s, probes[0][1]["context"], box=box), evidence=RUNTIME,
            refs=[_ref(ctx, "probes", "controls", i) for i, _ in probes],
            conditions=frozenset({PRIMARY_BLOCKED}) if box in blocked else frozenset(),
            consequence="the control does not do what it shows"))
    return _result(hits)


@detector("console-errors", layers=("behavior",))
def console_errors(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    kinds = set(_list(_params(det).get("kinds")))
    groups: dict[tuple, list[tuple[int, dict]]] = {}
    for i, entry in enumerate(_items(s, "console")):
        if kinds and entry["kind"] not in kinds:
            continue
        groups.setdefault((entry["kind"], entry["level"], entry.get("message", "")), []).append((i, entry))
    hits = []
    for (kind, level, message), entries in groups.items():
        contexts = sorted({e["context"] for _, e in entries if e.get("context")})
        where = f" in context {', '.join(contexts)}" if contexts else ""
        text = f': "{_clip(message, 120)}"' if message else ""
        hits.append(Hit(
            observed=f"console {level} ({kind}) seen {len(entries)} time(s){where}{text}",
            location=_loc(s, contexts[0] if contexts else None), evidence=RUNTIME,
            refs=[_ref(ctx, "console", i) for i, _ in entries[:5]]))
    return _result(hits)


# ---------------------------------------------------------------- keyboard

@detector("focus-visible", layers=("behavior",))
def focus_visible(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    nodes = s.get("nodes") or {}
    hits, measured, unmeasured, reported = [], set(), set(), set()
    for wi, walk in enumerate(_items(s, "keyboard")):
        for si, stop in enumerate(walk["stops"]):
            key = (walk["context"], stop["box"])
            visible = stop.get("focus_visible")
            if visible is None:
                unmeasured.add(key)
                continue
            measured.add(key)
            if visible or key in reported:
                continue
            reported.add(key)
            ind = stop.get("indicator") or {}
            rect = stop.get("rect") or (nodes.get(stop["box"]) or {}).get("rect") or {}
            need = 2 * max(rect.get("w", 0), rect.get("h", 0))
            hits.append(Hit(
                observed=(f"focus on {_label(s, stop['box'])} shows {_fmt(ind.get('contrast_area_px', 0))} px² at "
                          f"3:1 or more ({_fmt(ind.get('area_px', 0))} px² changed); a visible indicator needs "
                          f"{_fmt(need)} px²"),
                location=_loc(s, walk["context"], box=stop["box"], path=walk["path"]), evidence=RUNTIME,
                refs=[_ref(ctx, "probes", "keyboard", wi, "stops", si)],
                consequence="keyboard users cannot see where focus is"))
    unmeasured -= measured
    notes = [f"{len(unmeasured)} focus stop(s) have no indicator measurement"] if unmeasured else []
    return _result(hits, notes)


def _operable(ctx: Context, s: dict, semantic: bool | None) -> list[Hit]:
    needed = _primary_boxes(s, unfinished_only=False)
    hits, seen = [], set()

    def conditions(box: str) -> frozenset[str]:
        return frozenset({PRIMARY_BLOCKED}) if box in needed else frozenset()

    for wi, walk in enumerate(_items(s, "keyboard")):
        for ui, item in enumerate(walk.get("unreachable") or []):
            key = (walk["context"], item["box"])
            if (semantic is not None and item["semantic"] != semantic) or key in seen:
                continue
            seen.add(key)
            kind = "control" if item["semantic"] else "clickable element without a control role"
            hits.append(Hit(
                observed=f"{_label(s, item['box'])} ({kind}) is never reached with Tab on {walk['path']}",
                location=_loc(s, walk["context"], box=item["box"], path=walk["path"]), evidence=RUNTIME,
                refs=[_ref(ctx, "probes", "keyboard", wi, "unreachable", ui)], conditions=conditions(item["box"]),
                consequence="keyboard users cannot use it"))
    nodes = s.get("nodes") or {}
    for ci, c in enumerate(_items(s, "controls")):
        activation = (c.get("keyboard") or {}).get("activation")
        key = (c["context"], c["box"])
        if activation not in ("none", "different") or key in seen:
            continue
        is_semantic = (nodes.get(c["box"]) or {}).get("role") in ("button", "link", "input")
        if semantic is not None and is_semantic != semantic:
            continue
        seen.add(key)
        what = "does nothing" if activation == "none" else "does something other than a click"
        hits.append(Hit(
            observed=f"{_label(s, c['box'])} is reachable, but Enter or Space {what}",
            location=_loc(s, c["context"], box=c["box"]), evidence=RUNTIME,
            refs=[_ref(ctx, "probes", "controls", ci, "keyboard")], conditions=conditions(c["box"]),
            consequence="keyboard users cannot use it"))
    return hits


@detector("keyboard-traversal", layers=("behavior",))
def keyboard_traversal(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    params = _params(det)
    check = params.get("check")
    if check not in ("trap", "operable", "order", "obscured"):
        return _unknown_check(check)
    walks = _items(s, "keyboard")
    hits: list[Hit] = []
    if check == "operable":
        return _result(_operable(ctx, s, params.get("semantic")))
    if check == "trap":
        seen = set()
        for wi, walk in enumerate(walks):
            for ti, trap in enumerate(walk.get("traps") or []):
                key = (walk["context"], tuple(trap["boxes"]))
                if trap["escape_leaves"] or key in seen:
                    continue
                seen.add(key)
                names = ", ".join(_label(s, b) for b in trap["boxes"][:4])
                hits.append(Hit(
                    observed=f"Tab cycles through {len(trap['boxes'])} stop(s) ({names}) on {walk['path']} and Escape does not leave",
                    location=_loc(s, walk["context"], box=trap["boxes"][0] if trap["boxes"] else None, path=walk["path"]),
                    evidence=RUNTIME, refs=[_ref(ctx, "probes", "keyboard", wi, "traps", ti)],
                    consequence="the rest of the page is out of keyboard reach"))
        return _result(hits)
    if check == "order":
        bound = _bound(det, "order_inversions_max")
        if bound is None:
            return _no_bound("order_inversions_max")
        for wi, walk in enumerate(walks):
            derived = walk.get("derived") or {}
            count = derived.get("order_inversions", 0)
            if count <= bound:
                continue
            pairs = "; ".join(f"{_label(s, a)} → {_label(s, b)}" for a, b in (derived.get("inversion_pairs") or [])[:3])
            hits.append(Hit(
                observed=f"Tab order jumps backward {count} time(s) on {walk['path']} (allowed {_fmt(bound)}): {pairs}",
                location=_loc(s, walk["context"], path=walk["path"]), evidence=RUNTIME,
                refs=[_ref(ctx, "probes", "keyboard", wi)]))
        return _result(hits)
    bound = _bound(det, "obscured_share_max")                     # check == "obscured"
    if bound is None:
        return _no_bound("obscured_share_max")
    seen, unmeasured = set(), 0
    for wi, walk in enumerate(walks):
        for si, stop in enumerate(walk["stops"]):
            share = stop.get("obscured_share")
            key = (walk["context"], stop["box"])
            if share is None:
                unmeasured += 1
                continue
            if share <= bound or key in seen:
                continue
            seen.add(key)
            cover = f" by {_label(s, stop['obscured_by'])}" if stop.get("obscured_by") else ""
            hits.append(Hit(
                observed=f"focused {_label(s, stop['box'])} is {share:.0%} covered{cover} on {walk['path']}",
                location=_loc(s, walk["context"], box=stop["box"], path=walk["path"]), evidence=RUNTIME,
                refs=[_ref(ctx, "probes", "keyboard", wi, "stops", si)],
                consequence="keyboard users cannot see the focused control"))
    return _result(hits, [f"{unmeasured} focus stop(s) have no obscured share"] if unmeasured else [])


@detector("keyboard-bypass", layers=("behavior",))
def keyboard_bypass(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    check = _params(det).get("check")
    if check not in ("bypass", "skip-link"):
        return _unknown_check(check)
    bound = _bound(det, "repeated_stops_max")
    if bound is None:
        return _no_bound("repeated_stops_max")
    walks = _items(s, "keyboard")
    hits, broken = [], set()
    if check == "skip-link":
        for wi, walk in enumerate(walks):
            skip = walk.get("skip_link") or {}
            key = (walk["context"], skip.get("box"))
            if skip.get("present") and skip.get("lands_at") is None and key not in broken:
                broken.add(key)
                hits.append(Hit(
                    observed=f"skip link {_label(s, skip.get('box'))} on {walk['path']} leaves focus where it was",
                    location=_loc(s, walk["context"], box=skip.get("box"), path=walk["path"]), evidence=RUNTIME,
                    refs=[_ref(ctx, "probes", "keyboard", wi, "skip_link")]))
    by_context: dict[str, list[tuple[int, dict]]] = {}
    for wi, walk in enumerate(walks):
        by_context.setdefault(walk["context"], []).append((wi, walk))
    single = []
    for context, entries in by_context.items():
        judged = [(wi, w) for wi, w in entries if "repeated_stops" in (w.get("derived") or {})]
        if not judged:
            single.append(context)
            continue
        failing = []
        for wi, walk in judged:
            derived = walk["derived"]
            mechanisms = derived.get("bypass") or []
            ok = "skip-link" in mechanisms if check == "skip-link" else bool(mechanisms)
            if derived["repeated_stops"] > bound and not ok:
                failing.append((wi, walk))
        if not failing:
            continue
        wi, walk = failing[0]
        repeated = walk["derived"]["repeated_stops"]
        stops = sorted(walk["stops"], key=lambda st: st["index"])[:repeated]
        names = ", ".join(f'"{_clip(st["name"], 30)}"' if st.get("name") else st["box"] for st in stops[:4])
        routes = ", ".join(w["path"] for _, w in failing)
        missing = "skip link" if check == "skip-link" else "skip link, main landmark, or heading"
        hits.append(Hit(
            observed=(f"{repeated} repeated leading stops ({names}{', …' if repeated > 4 else ''}) on {routes} "
                      f"with no {missing} past them (allowed {_fmt(bound)})"),
            location=_loc(s, context, path=walk["path"]), evidence=RUNTIME,
            refs=[_ref(ctx, "probes", "keyboard", i) for i, _ in failing[:5]],
            consequence="keyboard users walk the same block on every page"))
    notes = [f"one walked route in context {c}: repeated stops not verified" for c in single]
    return _result(hits, notes)


@detector("context-change", layers=("behavior",))
def context_change(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    events = set(_list(_params(det).get("events")) or ["focus", "input"])
    if not events & {"focus", "input"}:
        return Result(skipped=f"no known event in {sorted(events)}")
    hits, seen, unmeasured = [], set(), 0
    if "focus" in events:
        for wi, walk in enumerate(_items(s, "keyboard")):
            for si, stop in enumerate(walk["stops"]):
                change, key = stop.get("context_change"), ("focus", walk["context"], stop["box"])
                unmeasured += change is None
                if change in (None, "none") or key in seen:
                    continue
                seen.add(key)
                hits.append(Hit(
                    observed=f"focusing {_label(s, stop['box'])} on {walk['path']} {change.replace('-', ' ')} with no other input",
                    location=_loc(s, walk["context"], box=stop["box"], path=walk["path"]), evidence=RUNTIME,
                    refs=[_ref(ctx, "probes", "keyboard", wi, "stops", si)]))
    if "input" in events:
        for fi, form in enumerate(_items(s, "forms")):
            for di, field in enumerate(form["fields"]):
                change, key = field.get("on_change"), ("input", form["context"], field["box"])
                if change in (None, "none") or key in seen:
                    continue
                seen.add(key)
                hits.append(Hit(
                    observed=f"changing {_label(s, field['box'])} ({field['kind']}) {change.replace('-', ' ')} before any submit",
                    location=_loc(s, form["context"], box=field["box"], flow=form.get("flow")), evidence=RUNTIME,
                    refs=[_ref(ctx, "probes", "forms", fi, "fields", di)]))
    return _result(hits, [f"{unmeasured} focus stop(s) have no context change recorded"] if unmeasured else [])


# ---------------------------------------------------------------- states and motion

@detector("state-coverage", layers=("behavior",))
def state_coverage(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    params = _params(det)
    check = params.get("check")
    if check not in (None, "indicator-kind", "problem-and-recovery", "distinguishable"):
        return _unknown_check(check)
    default = {"indicator-kind": ["loading"], "problem-and-recovery": ["error", "offline"]}.get(check)
    wanted = set(_list(params.get("states")) + _list(params.get("state"))) or set(default or [])
    bound = None
    if check == "indicator-kind":
        bound = _bound(det, "spinner_shown_ms_max")
        if bound is None:
            return _no_bound("spinner_shown_ms_max")
    hits, notes = [], []
    for i, p in enumerate(_items(s, "states")):
        if wanted and p["state"] not in wanted:
            continue
        where = f"{p['state']} state of {_label(s, p.get('surface'))}" + (f" on {p['path']}" if p.get("path") else "")
        reasons: list[str] = []
        if check is None or check == "distinguishable":
            if check is None and not p["shown"]:
                reasons.append(f"attempted by {p['induced_by']} and not shown")
            elif p.get("blank"):
                reasons.append("shows only persistent chrome")
            elif p.get("same_as"):
                reasons.append(f"looks the same as {', '.join(p['same_as'])}")
        elif check == "indicator-kind":
            if p.get("indicator") != "spinner" or p.get("scope") not in ("region", "page"):
                continue
            shown = p.get("indicator_shown_ms")
            if shown is None:
                notes.append(f"{where}: spinner duration not measured")
            elif shown > bound:
                reasons.append(f"shows only a spinner for {_fmt(shown)} ms over a {p['scope']} (allowed {_fmt(bound)} ms)")
        else:                                                      # problem-and-recovery
            if not p["shown"]:
                continue
            judged = [k for k in ("problem_text", "recovery_action") if k in p]
            if not judged:
                notes.append(f"{where}: problem text and recovery not recorded")
                continue
            if p.get("problem_text") is False:
                reasons.append("does not say what went wrong")
            if p.get("recovery_action") is False:
                reasons.append("offers no recovery action")
            elif p.get("recovery_action") and p.get("recovery_works") is False:
                reasons.append("offers a recovery action that does not recover")
        if reasons:
            hits.append(Hit(observed=f"{where}: {'; '.join(reasons)}",
                            location=_loc(s, p["context"], box=p.get("surface"), path=p.get("path")),
                            evidence=RUNTIME, refs=[_ref(ctx, "probes", "states", i)]))
    return _result(hits, notes)


@detector("reduced-motion-respected", layers=("behavior",))
def reduced_motion_respected(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    motion = _items(s, "motion")
    reduced = {c["id"] for c in s.get("contexts") or [] if c.get("reduced_motion")}
    runs = [(i, m) for i, m in enumerate(motion) if m["context"] in reduced]
    if motion and not runs:
        return Result(skipped="no motion probe ran with reduced motion", cause="probe")
    hits, seen = [], set()
    for i, m in runs:
        twin = next((t for t in motion if t["context"] == m.get("compare_to")), None)
        full = {mv["box"]: mv for mv in (twin or {}).get("moving") or []}
        for mi, mv in enumerate(m["moving"]):
            key = (m["context"], mv["box"])
            if mv["kind"] not in ("transform", "scroll-linked", "video", "canvas") or mv.get("essential") or key in seen:
                continue
            seen.add(key)
            travel = f", {_fmt(mv['travel_px'])} px" if "travel_px" in mv else ""
            before = full.get(mv["box"])
            compare = (f"; without reduced motion {_fmt(before['travel_px'])} px" if before and "travel_px" in before
                       else "")
            hits.append(Hit(
                observed=f"{_label(s, mv['box'])} still moves by {mv['kind']} under reduced motion{travel}{compare}",
                location=_loc(s, m["context"], box=mv["box"]), evidence=RUNTIME,
                refs=[_ref(ctx, "probes", "motion", i, "moving", mi)],
                consequence="motion-sensitive users cannot avoid it"))
    return _result(hits)


# ---------------------------------------------------------------- dialogs and choices

def _blocking(d: dict) -> bool:
    return d.get("blocks_content", d["kind"] in ("modal", "interstitial"))


@detector("dialog-usage", layers=("behavior",))
def dialog_usage(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    params = _params(det)
    check = params.get("check")
    if check not in ("routine-navigation-or-long-task", "entry-interruption", "focus-management", "recurrence"):
        return _unknown_check(check)
    purposes = set(_list(params.get("purposes")))
    triggers = set(_list(params.get("triggers")))
    dialogs = [(i, d) for i, d in enumerate(_items(s, "dialogs")) if not purposes or d["purpose"] in purposes]
    hits, notes = [], []

    def hit(i: int, d: dict, text: str, **kw: Any) -> None:
        hits.append(Hit(observed=f"{d['kind']} {_label(s, d['box'])}{' on ' + d['path'] if d.get('path') else ''} {text}",
                        location=_loc(s, d["context"], box=d["box"], path=d.get("path"), flow=d.get("flow")),
                        evidence=RUNTIME, refs=[_ref(ctx, "probes", "dialogs", i)], **kw))

    if check == "routine-navigation-or-long-task":
        held: dict[str, int] = {}
        for run in s.get("flows") or []:
            for step in run.get("steps") or []:
                if step.get("dialog"):
                    held[step["dialog"]] = held.get(step["dialog"], 0) + 1
        links = {c["box"] for c in _items(s, "controls") if c.get("promise") == "navigate"}
        for i, d in dialogs:
            if d["kind"] not in ("modal", "interstitial") or not _blocking(d) or d["purpose"] not in ("task", "other"):
                continue
            steps = held.get(d["box"], 0)
            if d["trigger"] == "navigation":
                hit(i, d, f"opens on a route change and blocks the page for a {d['purpose']} dialog")
            elif d["trigger"] == "control" and d.get("trigger_box") in links:
                hit(i, d, f"opens from link {_label(s, d['trigger_box'])} instead of a page and blocks it")
            elif d["trigger"] == "control" and steps > 1:
                hit(i, d, f"blocks the page for a task that takes {steps} flow steps")
            elif d["trigger"] == "control" and d["purpose"] == "task":
                notes.append(f"task dialog {d['box']}: whether the task is short enough to block the page needs review")
    elif check == "entry-interruption":
        for i, d in dialogs:
            if (triggers and d["trigger"] not in triggers) or (params.get("blocking") and not _blocking(d)):
                continue
            when = {"timer": f"after {_fmt(d.get('trigger_after_ms', 0) / 1000)} s", "scroll": "on scroll",
                    "exit-intent": "on exit intent", "idle": "when idle", "navigation": "on a new route",
                    "load": "on load", "control": "from a control"}[d["trigger"]]
            cover = f", covering {d['area_share']:.0%} of the viewport" if "area_share" in d else ""
            hit(i, d, f"asks for {d['purpose']} {when} before any input{cover}",
                consequence="the user is interrupted before doing anything")
    elif check == "focus-management":
        for i, d in dialogs:
            focus = d.get("focus")
            if not focus:
                notes.append(f"focus handling of dialog {d['box']} not recorded")
                continue
            reasons = []
            if _blocking(d) and focus.get("moved_in") is False:
                reasons.append("does not take focus")
            if _blocking(d) and focus.get("contained") is False:
                reasons.append("lets Tab leave while it blocks the page")
            if focus.get("escape_closes") is False and focus.get("close_control") is False:
                reasons.append("closes with neither Escape nor a visible control")
            if d["trigger"] == "control" and focus.get("returns_to") in ("body", "other"):
                reasons.append(f"returns focus to {'the page body' if focus['returns_to'] == 'body' else 'another box'} on close")
            if reasons:
                hit(i, d, "; ".join(reasons))
        for ci, c in enumerate(_items(s, "commits")):
            if ((c.get("confirm") or {}).get("initial_focus")) == "destructive":
                hits.append(Hit(
                    observed=f"the confirmation for {_label(s, c['box'])} opens with focus on the destructive control",
                    location=_loc(s, c["context"], box=c["box"], flow=c.get("flow")), evidence=RUNTIME,
                    refs=[_ref(ctx, "probes", "commits", ci, "confirm")]))
    else:                                                          # recurrence
        bound = _bound(det, "reasks_after_decline_max")
        if bound is None:
            return _no_bound("reasks_after_decline_max")
        for i, d in dialogs:
            reasks = (d.get("derived") or {}).get("reasks_after_decline", 0)
            if reasks > bound:
                hit(i, d, f"asks for {d['purpose']} again {reasks} time(s) after it was declined (allowed {_fmt(bound)})",
                    consequence="the user is pressed to change the answer")
        if not purposes or "permission-preprompt" in purposes:
            seen = set()
            for pi, p in enumerate(_items(s, "permissions")):
                if p.get("after_denial") and (p["context"], p["api"]) not in seen:
                    seen.add((p["context"], p["api"]))
                    hits.append(Hit(observed=f"the page requests {p['api']} permission again after it was denied",
                                    location=_loc(s, p["context"]), evidence=RUNTIME,
                                    refs=[_ref(ctx, "probes", "permissions", pi)]))
    return _result(hits, notes)


def _annual(option: dict) -> tuple[tuple, float] | None:
    """Comparable group and annualized price (DERIVED.md, Prices)."""
    price = option.get("price")
    if price is None:
        return None
    cadence = option.get("cadence") or "once"
    if cadence in ANNUAL:
        return ("recurring", option.get("currency")), price * ANNUAL[cadence]
    return (cadence, option.get("currency")), price


def _norm(text: str) -> str:
    return " ".join(text.replace("’", "'").replace("‘", "'").casefold().split())


@detector("choice-analysis", layers=("behavior",))
def choice_analysis(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    params = _params(det)
    check = params.get("check")
    if check not in ("preselection", "prominence", "decline-effort", "copy"):
        return _unknown_check(check)
    purposes = set(_list(params.get("purposes")))
    sets = [(i, c) for i, c in enumerate(_items(s, "choices")) if not purposes or c["purpose"] in purposes]
    hits, notes = [], []

    def where(c: dict) -> str:
        return f"{c['purpose']} choice {c['id']}" + (f" on {c['path']}" if c.get("path") else "")

    def loc(c: dict, box: str | None = None) -> dict:
        return _loc(s, c["context"], box=box or c.get("container"), path=c.get("path"), flow=c.get("flow"))

    if check == "preselection":
        for i, c in sets:
            opts = c["options"]
            if c["purpose"] == "plan":
                priced = [(o, a) for o in opts if (a := _annual(o)) is not None]
                for oi, o in enumerate(opts):
                    mine = _annual(o)
                    if not o.get("preselected") or mine is None:
                        continue
                    cheapest = min(a[1] for _, a in priced if a[0] == mine[0])
                    if mine[1] > cheapest + PRICE_EPSILON:
                        hits.append(Hit(
                            observed=(f"{where(c)}: {_label(s, o.get('box'))} is preselected at {_fmt(mine[1])} a year "
                                      f"while a comparable option costs {_fmt(cheapest)}"),
                            location=loc(c, o.get("box")), evidence=RUNTIME,
                            refs=[_ref(ctx, "probes", "choices", i, "options", oi)],
                            conditions=frozenset({CHARGE_ADDED})))
                continue
            for oi, o in enumerate(opts):
                if o["kind"] == "accept" and o.get("preselected"):
                    charge = (o.get("price") or 0) > 0
                    price = f" (adds {_fmt(o['price'])} {o.get('currency', '')})".replace(" )", ")") if charge else ""
                    hits.append(Hit(
                        observed=f"{where(c)}: accept option {_label(s, o.get('box'))} is selected on load{price}",
                        location=loc(c, o.get("box")), evidence=RUNTIME,
                        refs=[_ref(ctx, "probes", "choices", i, "options", oi)],
                        conditions=frozenset({CHARGE_ADDED}) if charge else frozenset()))
        field_purposes = set(_list(params.get("field_purposes")))
        for fi, form in enumerate(_items(s, "forms")):
            for di, field in enumerate(form["fields"]):
                if (field.get("checked_on_load") and not field.get("required")
                        and (not field_purposes or field.get("purpose") in field_purposes)):
                    hits.append(Hit(
                        observed=f"optional {field.get('purpose', 'other')} field {_label(s, field['box'])} is checked on load",
                        location=_loc(s, form["context"], box=field["box"], flow=form.get("flow")), evidence=RUNTIME,
                        refs=[_ref(ctx, "probes", "forms", fi, "fields", di)],
                        conditions=frozenset({CHARGE_ADDED}) if field.get("purpose") == "add-on" else frozenset()))
    elif check == "prominence":
        bound = _bound(det, "prominence_ratio_max")
        if bound is None:
            return _no_bound("prominence_ratio_max")
        for i, c in sets:
            ratio = (c.get("derived") or {}).get("prominence_ratio")
            if ratio is not None and ratio > bound:
                hits.append(Hit(
                    observed=f"{where(c)}: accepting is {_fmt(ratio)}× as prominent as declining (allowed {_fmt(bound)}×)",
                    location=loc(c), evidence=RUNTIME, refs=[_ref(ctx, "probes", "choices", i)]))
    elif check == "decline-effort":
        bound = _bound(det, "decline_extra_interactions_max")
        if bound is None:
            return _no_bound("decline_extra_interactions_max")
        for i, c in sets:
            derived = c.get("derived")
            if derived is None or any(o["kind"] == "accept" and o.get("preselected") for o in c["options"]):
                continue                                          # no accept route, or preselection reports it
            if not derived["decline_found"]:
                text = "offers no way to decline"
            elif derived["decline_extra_interactions"] > bound:
                text = (f"declining takes {derived['decline_extra_interactions']} more interaction(s) than accepting "
                        f"(allowed {_fmt(bound)})")
            else:
                continue
            hits.append(Hit(observed=f"{where(c)} {text}", location=loc(c), evidence=RUNTIME,
                            refs=[_ref(ctx, "probes", "choices", i)]))
    else:                                                          # copy
        family = det.get("family") or det.get("list")
        if not family or family not in (ctx.rules.get("lists") or {}):
            return Result(skipped=f"the rule names no list of phrases (family {family!r})")
        kinds = set(_list(params.get("kinds")))
        locales = {c["id"]: c.get("locale") for c in s.get("contexts") or []}
        labelled = 0
        for i, c in sets:
            for oi, o in enumerate(c["options"]):
                if kinds and o["kind"] not in kinds:
                    continue
                if not o.get("label"):
                    notes.append(f"{where(c)}: a {o['kind']} option has no recorded label")
                    continue
                labelled += 1
                lang = o.get("lang") or locales.get(c["context"])
                phrases = ctx.list_values(family, lang.split("-")[0].lower()) if lang else ctx.list_values(family)
                label = _norm(o["label"])
                match = next((p for p in phrases if _norm(p) in label), None)
                if match:
                    hits.append(Hit(
                        observed=f'{where(c)}: {o["kind"]} option reads "{_clip(o["label"])}" (matches "{match}")',
                        location=loc(c, o.get("box")), evidence="review",
                        refs=[_ref(ctx, "probes", "choices", i, "options", oi)]))
    return _result(hits, notes)


# ---------------------------------------------------------------- flows

def _first_step(run: dict, key: str, field: str) -> int | None:
    rows = run.get("prices" if field == "components" else "cart") or []
    steps = [o["step"] for o in rows if any(item["key"] == key for item in o[field])]
    return min(steps) if steps else None


def _mismatched(items: Iterable[dict], label) -> dict[str, list[str]]:
    """Observations with `hint_mismatch`, by label, with the fields their hints dispute."""
    out: dict[str, list[str]] = {}
    for item in items:
        for field in item.get("hint_mismatch") or ():
            fields = out.setdefault(label(item), [])
            if field not in fields:
                fields.append(field)
    return out


def _unconfirmed(name: str, run: dict, what: str, items: dict[str, list[str]]) -> str:
    """The not-verified note that replaces a verdict resting on hints the page reading does not confirm."""
    listed = "; ".join(f"{label} ({', '.join(fields)})" for label, fields in items.items())
    return f"{name} in context {run['context']}: {what} not verified: hints the page does not confirm on {listed}"


def _components(run: dict) -> list[dict]:
    return [c for o in run.get("prices") or [] for c in o["components"]]


@detector("flow-analysis", layers=("behavior",))
def flow_analysis(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    params = _params(det)
    check = params.get("check")
    if check not in ("drip", "sneak", "terms", "exit", "gates", "dead-end", "steps", "review"):
        return _unknown_check(check)
    kinds = set(_list(params.get("kinds"))) or (EXIT_KINDS if check == "exit" else set())
    plan = {f["id"]: f for f in (ctx.plan or {}).get("flows") or []}
    hits, notes = [], []
    for ri, run in enumerate(s.get("flows") or []):
        if kinds and run["kind"] not in kinds:
            continue
        name = f"{run['kind']} flow {run['id']}"
        if run["status"] == "skipped":
            notes.append(f"{name} in context {run['context']} was skipped" + (f": {run['note']}" if run.get("note") else ""))
            continue
        derived = run.get("derived") or {}

        def add(text: str, step: int | None = None, box: str | None = None, conditions: Iterable[str] = (),
                ref: tuple = (), **kw: Any) -> None:
            hits.append(Hit(observed=f"{name}: {text}", location=_loc(s, run["context"], flow=run["id"], step=step, box=box),
                            evidence=RUNTIME, refs=[_ref(ctx, "flows", ri, *ref)], conditions=frozenset(conditions), **kw))

        if check == "drip":
            shaky = _mismatched(_components(run), lambda c: c["key"])
            drip = [k for k in derived.get("drip") or [] if k not in shaky]
            if drip:
                steps = [st for k in drip if (st := _first_step(run, k, "components")) is not None]
                add(f"charges {', '.join(drip)} appear or rise after the first price", min(steps, default=None),
                    ref=("prices",), consequence="the price shown is not the price paid")
            if shaky:
                notes.append(_unconfirmed(name, run, "drip pricing", shaky))
        elif check == "sneak":
            shaky = _mismatched((line for o in run.get("cart") or [] for line in o["lines"]), lambda line: line["key"])
            sneaked = [k for k in derived.get("sneaked") or [] if k not in shaky]
            if sneaked:
                steps = [st for k in sneaked if (st := _first_step(run, k, "lines")) is not None]
                add(f"cart lines {', '.join(sneaked)} were added without the user", min(steps, default=None),
                    ref=("cart",))
            if shaky:
                notes.append(_unconfirmed(name, run, "sneaked cart lines", shaky))
        elif check == "terms":
            _terms_hits(run, derived, add, notes, name)
        elif check == "exit":
            _exit_hits(det, params, run, derived, add, notes, name, bool(plan))
        elif check == "gates":
            allowed = set(_list(params.get("gates")))
            requires = set((plan.get(run["id"]) or {}).get("requires") or []) if run["id"] in plan else None
            for gi, gate in enumerate(run.get("gates") or []):
                declared = gate["kind"] in requires if requires is not None else gate["declared"]
                if allowed and gate["kind"] not in allowed:
                    continue
                if gate.get("hint_mismatch"):
                    notes.append(_unconfirmed(name, run, "gate", {f"{gate['kind']} at step {gate['step']}": gate["hint_mismatch"]}))
                    continue
                if gate["skippable"] or declared:
                    continue
                add(f"step {gate['step']} requires {gate['kind']} before continuing; it is neither skippable nor declared",
                    gate["step"], gate.get("box"), ref=("gates", gi))
        elif check == "dead-end":
            ends = [st for st in run["steps"] if st.get("dead_end")]
            if not ends and run["status"] == "dead-end" and run["steps"]:
                ends = [max(run["steps"], key=lambda st: st["index"])]
            for st in ends:
                add(f"step {st['index']} on {st['path']} offers no way forward or back", st["index"], st.get("main"),
                    ref=("steps", run["steps"].index(st)))
        elif check == "steps":
            _step_hits(det, run, plan, add, notes, name, ctx.plan is not None)
        elif check == "review":
            if run.get("commit_step") is None or not run.get("prices"):
                continue
            review = run.get("review_before_commit")
            if review is None:
                notes.append(f"{name}: whether a review step precedes the commit was not recorded")
                continue
            if review:
                continue
            undo = [c.get("undo") or {} for c in _items(s, "commits") if c.get("flow") == run["id"]]
            if any(u.get("offered") and u.get("restores") for u in undo):
                continue
            add(f"commits at step {run['commit_step']} with a price, no review step before it, and no undo that restores",
                run["commit_step"], ref=("review_before_commit",))
    return _result(hits, notes)


def _terms_hits(run: dict, derived: dict, add, notes: list[str], name: str) -> None:
    # Whether terms are required at all rests on the recurring components. When no recurring
    # component is confirmed and some component's hint disputes its kind or cadence, recurrence
    # itself is not verified.
    def disputed(c):
        return bool({"kind", "cadence"} & set(c.get("hint_mismatch") or ()))
    components = _components(run)
    doubtful = [c for c in components if disputed(c)]
    if doubtful and not any(not disputed(c) for c in components
                            if c["kind"] == "recurring" or c.get("cadence") in RECURRING_CADENCE):
        notes.append(_unconfirmed(name, run, "recurring terms (whether the flow recurs)",
                                  _mismatched(doubtful, lambda c: c["key"])))
        return
    required = set(required_terms(run))
    shaky = _mismatched((d for d in run.get("disclosures") or [] if d["kind"] in required), lambda d: d["kind"])
    hidden = [k for k in derived.get("hidden_terms") or [] if k not in shaky]
    if hidden:
        add(f"recurring terms not readable at the commit: {', '.join(hidden)}", run.get("commit_step"),
            conditions=[TRIAL_CONVERTS] if run.get("trial") else [], ref=("disclosures",))
    if shaky:
        notes.append(_unconfirmed(name, run, "recurring terms", shaky))


def _exit_hits(det: dict, params: dict, run: dict, derived: dict, add, notes: list[str], name: str,
               have_plan: bool) -> None:
    effort = run["effort"]
    reasons, conditions = [], set()
    if run["status"] in UNFINISHED:
        reasons.append(f"the run ended {run['status']}")
    channel = params.get("channel")
    if channel and effort.get("channel") and effort["channel"] != channel:
        reasons.append(f"it can be finished only by {effort['channel']}")
        if effort["channel"] in CONTACT_CHANNELS:
            conditions.add(CONTACT_REQUIRED)
    contact = [g for g in run.get("gates") or [] if g["kind"] == "contact" and not g["skippable"]]
    confirmed = [g for g in contact if not g.get("hint_mismatch")]
    if confirmed:
        reasons.append(f"step {confirmed[0]['step']} requires contacting support")
        conditions.add(CONTACT_REQUIRED)
    elif contact:
        notes.append(_unconfirmed(name, run, "contact requirement", _mismatched(contact, lambda g: f"step {g['step']} gate")))
    offers = [o for st in run["steps"] for o in st.get("offers") or []]
    disputed = {key for o in offers for field in o.get("hint_mismatch") or ()
                for key in (("offers", "blocking_offers") if field == "kind" else ("blocking_offers",))}
    for key, label in (("offers", "offers"), ("blocking_offers", "blocking offers")):
        bound = _bound(det, f"{key}_max")
        if bound is None:
            continue
        if key in disputed:
            notes.append(_unconfirmed(name, run, f"the count of {label}",
                                      _mismatched(offers, lambda o: f"{o['kind']} offer {o['box']}")))
        elif effort.get(key, 0) > bound:
            reasons.append(f"{effort[key]} {label} (allowed {_fmt(bound)})")
    exit_ = derived.get("exit")
    if exit_ is None:
        if run["status"] == "completed":
            notes.append(f"{name} in context {run['context']}: no completed pair run in the same context"
                         + ("" if have_plan else " (no plan given)") + "; effort against joining not verified")
    else:
        if exit_.get("added_reauth"):
            reasons.append(f"it asks for reauthentication that {exit_['pair']} did not")
        for key, label in (("extra_steps", "steps"), ("extra_interactions", "interactions")):
            bound = _bound(det, f"{key}_max")
            if bound is not None and exit_.get(key, 0) > bound:
                reasons.append(f"{exit_[key]} more {label} than {exit_['pair']} (allowed {_fmt(bound)})")
    if reasons:
        add("; ".join(reasons), conditions=conditions, ref=("effort",))


def _step_hits(det: dict, run: dict, plan: dict, add, notes: list[str], name: str, have_plan: bool) -> None:
    effort = run["effort"]
    over = _bound(det, "steps_over_plan_max")
    if over is not None:
        if not have_plan:
            notes.append(f"{name}: no plan given, steps against max_steps not verified")
        elif run["id"] not in plan:
            notes.append(f"{name}: the plan has no flow {run['id']}")
        elif plan[run["id"]].get("max_steps") is not None:
            limit = plan[run["id"]]["max_steps"]
            if effort["steps"] - limit > over:
                add(f"takes {effort['steps']} steps; the plan allows {limit}", ref=("effort", "steps"))
    single = _bound(det, "single_field_steps_max")
    if single is not None:
        if "single_field_steps" not in effort:
            notes.append(f"{name}: single-field steps not recorded")
        elif effort["single_field_steps"] > single:
            add(f"{effort['single_field_steps']} consecutive steps ask for one field each (allowed {_fmt(single)})",
                ref=("effort", "single_field_steps"))


# ---------------------------------------------------------------- forms and commits

@detector("form-behavior", layers=("behavior",))
def form_behavior(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    params = _params(det)
    check = params.get("check")
    if check not in ("lost-input", "premature-validation", "error-identification", "disabled-submit",
                     "redundant-entry", "auth"):
        return _unknown_check(check)
    after = set(_list(params.get("after")))
    hits, notes = [], []
    for fi, form in enumerate(_items(s, "forms")):
        name = f"{form['purpose']} form {_label(s, form['box'])}"

        def add(text: str, *ref: Any, box: str | None = None) -> None:
            hits.append(Hit(observed=f"{name}: {text}", evidence=RUNTIME,
                            location=_loc(s, form["context"], box=box or form["box"], flow=form.get("flow")),
                            refs=[_ref(ctx, "probes", "forms", fi, *ref)]))

        if check == "lost-input":
            for pi, p in enumerate(form.get("preservation") or []):
                if after and p["after"] not in after:
                    continue
                if p["cleared"] > 0:
                    add(f"after {p['after']} {p['cleared']} entered field(s) are empty, {p['kept']} kept",
                        "preservation", pi)
                elif p.get("cleared_sensitive") and p.get("explained") is False:
                    add(f"after {p['after']} {p['cleared_sensitive']} sensitive field(s) are empty with no reason given",
                        "preservation", pi)
        elif check == "premature-validation":
            v = form.get("validation") or {}
            if v.get("untouched_invalid_on_load"):
                add("fields show errors before any input", "validation")
            elif v.get("first_error") in ("load", "keystroke"):
                add(f"the first error appears on {v['first_error']}, while the user is still typing"
                    if v["first_error"] == "keystroke" else "the first error appears on load", "validation")
        elif check == "error-identification":
            e = form.get("invalid_submit")
            if not e:
                notes.append(f"{name}: no invalid submit recorded")
                continue
            reasons = []
            if e.get("color_only"):
                reasons.append("the error shows only as a color change")
            elif e.get("described_in_text") is False and e.get("errors", 0) > 0:
                reasons.append("the error is not described in text")
            if e.get("associated") is False and e.get("errors", 0) > 0:
                reasons.append("messages are not tied to their fields")
            if e.get("announced") is False and e.get("focus_to") not in ("first-error", "summary"):
                reasons.append(f"it is not announced and focus goes to {e.get('focus_to', 'nowhere recorded')}")
            if reasons:
                add("after an invalid submit " + "; ".join(reasons), "invalid_submit")
        elif check == "disabled-submit":
            sub = form.get("submit") or {}
            if sub.get("disabled_until_valid") and sub.get("reason_visible") is False:
                add("submit stays disabled until valid with no visible reason", "submit", box=sub.get("box"))
        elif check == "redundant-entry":
            for di, field in enumerate(form["fields"]):
                if (field.get("repeats") and not field.get("sensitive") and not field.get("prefilled")
                        and not field.get("same_as_offered")):
                    add(f"{_label(s, field['box'])} asks again for the value of {_label(s, field['repeats'])} "
                        "without prefilling it or offering to reuse it", "fields", di, box=field["box"])
        else:                                                      # auth
            auth = form.get("auth") or {}
            if auth.get("cognitive_test") in ("puzzle", "transcription", "memory") and auth.get("alternative") is False:
                add(f"signing in needs a {auth['cognitive_test']} test with no alternative", "auth")
            for di, field in enumerate(form["fields"]):
                secret = field["kind"] in ("password", "otp") or (
                    field.get("sensitive") and form["purpose"] in ("sign-in", "signup"))
                if secret and field.get("paste_blocked"):
                    add(f"pasting into {field['kind']} field {_label(s, field['box'])} is blocked", "fields", di,
                        box=field["box"])
    return _result(hits, notes)


def _under(outcome: dict) -> str:
    return "with no failure injected" if outcome["injected"] == "none" else f"with {outcome['injected']} injected"


def _intended_effects(outcome: dict) -> int:
    """Effects of one intended commit under one injection (DERIVED.md, Commits)."""
    return ((1 if outcome["actual"] == "applied" else 0) + (outcome.get("retry_effects") or 0)
            + (1 if outcome.get("auto_resent") else 0))


@detector("commit-safety", layers=("behavior",))
def commit_safety(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    check = _params(det).get("check")
    if check not in ("duplicate", "status", "undo"):
        return _unknown_check(check)
    bound = None
    if check == "duplicate":
        bound = _bound(det, "effects_max")
        if bound is None:
            return _no_bound("effects_max")
    hits = []
    for ci, c in enumerate(_items(s, "commits")):
        reasons = []
        if check == "duplicate":
            da = c.get("double_activation")
            if da and da["effects"] > bound:
                reasons.append(f"two quick activations applied {da['effects']} effects")
            for o in c.get("outcomes") or []:
                n = _intended_effects(o)
                if n > bound:
                    how = "an automatic resend" if o.get("auto_resent") else "the offered retry"
                    reasons.append(f"{_under(o)}, {how} brought the effects to {n}")
        elif check == "status":
            for o in c.get("outcomes") or []:
                if o["claimed"] == "success" and o["actual"] in ("not-applied", "unknown"):
                    reasons.append(f"{_under(o)} it claims success while the change is {o['actual']}")
                elif o["claimed"] == "failure" and o["actual"] == "applied":
                    reasons.append(f"{_under(o)} it claims failure while the change was applied")
        else:                                                      # undo
            if not c.get("destructive", c["kind"] in ("delete", "cancel")):
                continue
            confirm, undo = c.get("confirm") or {}, c.get("undo") or {}
            named = confirm.get("shown") and confirm.get("names_object")
            if not named and not undo.get("offered"):
                reasons.append("runs with neither a confirmation naming the object nor an undo")
            if undo.get("offered") and (undo.get("restores") is False or undo.get("survives_reload") is False):
                reasons.append("offers an undo that does not bring the object back after reload")
            if undo.get("dismissed_while_focused"):
                reasons.append("removes its undo while it has focus")
        if reasons:
            hits.append(Hit(observed=f"{c['kind']} commit {_label(s, c['box'])}: {'; '.join(reasons)}",
                            location=_loc(s, c["context"], box=c["box"], flow=c.get("flow")), evidence=RUNTIME,
                            refs=[_ref(ctx, "probes", "commits", ci)]))
    if check == "duplicate":
        for hi, h in enumerate(_items(s, "history")):
            if h.get("resubmit_prompt"):
                hits.append(Hit(observed=f"reloading {h.get('to') or h['from']} after a submit offers to send the form again",
                                location=_loc(s, h["context"], path=h.get("to") or h["from"]), evidence=RUNTIME,
                                refs=[_ref(ctx, "probes", "history", hi)]))
    return _result(hits)


@detector("status-announcement", layers=("behavior",))
def status_announcement(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    sources = [x for x in _list(_params(det).get("sources")) or ["controls", "commits", "states"]
               if x in ("controls", "commits", "states")]
    if not sources:
        return Result(skipped="no known source in sources")
    hits = []
    if "controls" in sources:
        for ci, c in enumerate(_items(s, "controls")):
            effect = c["effect"]
            changed = effect.get("status_changed") or []
            if not changed or effect.get("announcements") or effect.get("focus_to") in changed:
                continue
            hits.append(Hit(
                observed=f"after {c['action']['kind']} on {_label(s, c['box'])}, {_label(s, changed[0])} reports a result "
                         "that reaches neither a live region nor focus",
                location=_loc(s, c["context"], box=c["box"]), evidence=RUNTIME,
                refs=[_ref(ctx, "probes", "controls", ci, "effect")]))
    if "commits" in sources:
        for ci, c in enumerate(_items(s, "commits")):
            silent = [o for o in c.get("outcomes") or [] if o["claimed"] != "none" and o.get("announced") is False]
            if silent:
                cases = ", ".join(f"{o['claimed']} {_under(o)}" for o in silent)
                hits.append(Hit(observed=f"{c['kind']} commit {_label(s, c['box'])} shows its result unannounced ({cases})",
                                location=_loc(s, c["context"], box=c["box"], flow=c.get("flow")), evidence=RUNTIME,
                                refs=[_ref(ctx, "probes", "commits", ci, "outcomes")]))
    if "states" in sources:
        for pi, p in enumerate(_items(s, "states")):
            if p.get("on_action") and p["shown"] and p.get("announced") is False:
                hits.append(Hit(
                    observed=f"{p['state']} state of {_label(s, p.get('surface'))} appears after an action unannounced",
                    location=_loc(s, p["context"], box=p.get("surface"), path=p.get("path")), evidence=RUNTIME,
                    refs=[_ref(ctx, "probes", "states", pi)]))
    return _result(hits)


# ---------------------------------------------------------------- time, history, input, media

@detector("urgency-integrity", layers=("behavior",))
def urgency_integrity(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    params = _params(det)
    checks = set(_list(params.get("checks")) or ["resets", "drifts", "expiry", "unbacked"])
    unbacked = set(_list(params.get("unbacked_kinds")))
    hits, notes = [], []
    for i, u in enumerate(_items(s, "urgency")):
        derived, reasons = u.get("derived") or {}, []
        if "resets" in checks and derived.get("resets"):
            reasons.append("shows more time after reload or in a fresh profile than it had left")
        if "drifts" in checks and derived.get("drifts"):
            values = ", ".join(f"{r['when']} {_fmt(r['value'])}" for r in u["readings"])
            reasons.append(f"changes with no purchase in between ({values})")
        if "expiry" in checks and u["kind"] != "hold" and u.get("at_expiry") in ("restarts", "unchanged"):
            reasons.append(f"{'restarts' if u['at_expiry'] == 'restarts' else 'changes nothing'} when it runs out")
        if "unbacked" in checks and (not unbacked or u["kind"] in unbacked):
            if u.get("backed") is False:
                reasons.append("no backend data supplies it")
            elif "backed" not in u:
                notes.append(f"{u['kind']} claim {u['box']}: backing not checked")
        if reasons:
            hits.append(Hit(observed=f"{u['kind']} claim {_label(s, u['box'])}: {'; '.join(reasons)}",
                            location=_loc(s, u["context"], box=u["box"], path=u.get("path")), evidence=RUNTIME,
                            refs=[_ref(ctx, "probes", "urgency", i)], consequence="the pressure to decide is invented"))
    return _result(hits, notes)


@detector("time-limit", layers=("behavior",))
def time_limit(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    exempt = _params(det).get("exempt_over_s")
    lead_min, ext_min = _bound(det, "warn_lead_s_min"), _bound(det, "extensions_min")
    hits, notes = [], []
    for i, t in enumerate(_items(s, "time_limits")):
        if (exempt is not None and t["limit_s"] > exempt) or t.get("turn_off") or t.get("adjustable"):
            continue
        reasons, unknown = [], []
        if not t["warned"]:
            reasons.append("no warning")
        elif lead_min is not None and "warn_lead_s" not in t:
            unknown.append("warning lead")
        elif lead_min is not None and t["warn_lead_s"] < lead_min:
            reasons.append(f"a warning {_fmt(t['warn_lead_s'])} s ahead (needs {_fmt(lead_min)} s)")
        if not t["extendable"]:
            reasons.append("no simple way to extend")
        elif ext_min is not None and "extensions" not in t:
            unknown.append("extensions")
        elif ext_min is not None and t["extensions"] < ext_min:
            reasons.append(f"{t['extensions']} working extension(s) (needs {_fmt(ext_min)})")
        if not reasons:
            if unknown:
                notes.append(f"{t['kind']} limit of {_fmt(t['limit_s'])} s: {' and '.join(unknown)} not recorded")
            continue
        lost = t.get("input_after_expiry") == "lost"
        hits.append(Hit(
            observed=(f"{t['kind']} limit of {_fmt(t['limit_s'])} s that cannot be turned off or lengthened: "
                      f"{'; '.join(reasons)}{'; entered input is lost' if lost else ''}"),
            location=_loc(s, t["context"], flow=t.get("flow")), evidence=RUNTIME,
            refs=[_ref(ctx, "probes", "time_limits", i)],
            consequence="entered work is lost when the limit passes" if lost else None))
    return _result(hits, notes)


@detector("history-behavior", layers=("behavior",))
def history_behavior(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    params = _params(det)
    check = params.get("check")
    if check not in ("back-trap", "restore"):
        return _unknown_check(check)
    hits = []

    def add(i: int, h: dict, text: str) -> None:
        hits.append(Hit(observed=text, location=_loc(s, h["context"], path=h["from"]), evidence=RUNTIME,
                        refs=[_ref(ctx, "probes", "history", i)]))

    if check == "back-trap":
        bound = _bound(det, "presses_to_leave_max")
        if bound is None:
            return _no_bound("presses_to_leave_max")
        for i, h in enumerate(_items(s, "history")):
            if h["action"] != "back" or "left_page" not in h:
                continue
            pushed = f"; the page added {h['pushed_entries']} history entries" if h.get("pushed_entries") else ""
            if not h["left_page"]:
                add(i, h, f"Back from {h['from']} never leaves the page in {h.get('presses', 3)} presses{pushed}")
                continue
            presses = h.get("presses", 1)
            if h.get("overlay_closed_first") and h.get("overlay_opened_by") == "user":
                presses -= 1
            if presses > bound:
                add(i, h, f"Back from {h['from']} takes {presses} presses to leave (allowed {_fmt(bound)}){pushed}")
        return _result(hits)
    kinds = _list(params.get("restores")) or ["filters", "page", "scroll", "input", "selection"]
    deep = "deep-link" in _list(params.get("also"))
    for i, h in enumerate(_items(s, "history")):
        if h["action"] == "back" and h.get("restored"):
            lost = [k for k in kinds if h["restored"].get(k) is False]
            if lost:
                add(i, h, f"Back to {h.get('to') or h['from']} loses {', '.join(lost)}")
        elif deep and h["action"] == "deep-link-after-sign-in" and h.get("landed") in ("home", "other"):
            add(i, h, f"signing in from {h['from']} lands on {h['landed']}, not the linked page")
    return _result(hits)


@detector("pointer-alternatives", layers=("behavior",))
def pointer_alternatives(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    params = _params(det)
    check = params.get("check")
    if check not in ("gesture", "hover-content"):
        return _unknown_check(check)
    kinds = set(_list(params.get("kinds")))
    hits, notes = [], []
    for i, p in enumerate(_items(s, "pointer")):
        reasons = []
        if check == "gesture":
            if p["kind"] == "hover-reveal" or (kinds and p["kind"] not in kinds):
                continue
            alt = p.get("alternative")
            if alt is None:
                notes.append(f"{p['kind']} target {p['box']}: alternative not recorded")
            elif alt in ("none", "keyboard-only"):
                reasons.append(f"works only by {p['kind']}" + (" or keys" if alt == "keyboard-only" else "")
                               + ", with no single-pointer alternative")
        else:
            if p["kind"] != "hover-reveal":
                continue
            if p.get("on_focus_too") is False:
                reasons.append("keyboard focus does not reveal it")
            if p.get("hoverable") is False:
                reasons.append("it disappears when the pointer moves onto it")
            if p.get("persistent") is False:
                reasons.append("it disappears while hover remains")
            if p.get("obscures") and p.get("dismissible") is False:
                reasons.append("it covers other content and Escape does not hide it")
            if reasons:
                reasons = [f"content revealed on hover: {'; '.join(reasons)}"]
        if reasons:
            hits.append(Hit(observed=f"{_label(s, p['box'])}: {reasons[0]}", location=_loc(s, p["context"], box=p["box"]),
                            evidence=RUNTIME, refs=[_ref(ctx, "probes", "pointer", i)]))
    return _result(hits, notes)


@detector("scroll-behavior", layers=("behavior",))
def scroll_behavior(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    low, high = _bound(det, "ratio_min"), _bound(det, "ratio_max")
    hits = []
    for i, p in enumerate(_items(s, "scroll")):
        ratio = (p.get("derived") or {}).get("ratio")
        reasons = []
        if p.get("blocked"):
            reasons.append("the page did not move")
        elif ratio is not None and low is not None and ratio < low:
            reasons.append(f"it moved {_fmt(ratio)}× the expected distance (at least {_fmt(low)}×)")
        elif ratio is not None and high is not None and ratio > high:
            reasons.append(f"it moved {_fmt(ratio)}× the expected distance (at most {_fmt(high)}×)")
        if p.get("snapped"):
            reasons.append("the document snapped to section boundaries")
        if reasons:
            hits.append(Hit(observed=f"scrolling by {p['input']}: {'; '.join(reasons)}", location=_loc(s, p["context"]),
                            evidence=RUNTIME, refs=[_ref(ctx, "probes", "scroll", i)],
                            consequence="users lose control of their position"))
    return _result(hits)


@detector("permission-requests", layers=("behavior",))
def permission_requests(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    params = _params(det)
    check = params.get("check", "without-gesture")
    if check != "without-gesture":
        return _unknown_check(check)
    apis = set(_list(params.get("apis")))
    hits, seen = [], set()
    for i, p in enumerate(_items(s, "permissions")):
        key = (p["context"], p["api"])
        if p["user_gesture"] or (apis and p["api"] not in apis) or key in seen:
            continue
        seen.add(key)
        when = f" {_fmt(p['t_ms'] / 1000)} s after load" if "t_ms" in p else ""
        hits.append(Hit(observed=f"the page requests {p['api']} permission{when} without a user action",
                        location=_loc(s, p["context"]), evidence=RUNTIME, refs=[_ref(ctx, "probes", "permissions", i)],
                        consequence="the request has no context and a refusal sticks"))
    return _result(hits)


@detector("media-autoplay", layers=("behavior",))
def media_autoplay(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    s = _session(ctx)
    if s is None:
        return _no_session()
    bound = _bound(det, "audible_seconds_max")
    if bound is None:
        return _no_bound("audible_seconds_max")
    hits, notes = [], []
    for i, m in enumerate(_items(s, "media")):
        if not (m["autoplay"] and m["audible"]):
            continue
        seconds, controls = m.get("audible_s"), m.get("controls")
        if seconds is None or controls is None:
            notes.append(f"autoplaying audio {m['box']}: {'duration' if seconds is None else 'controls'} not recorded")
            continue
        if seconds > bound and not controls:
            hits.append(Hit(
                observed=(f"{_label(s, m['box'])} plays sound on its own for {_fmt(seconds)} s "
                          f"(allowed {_fmt(bound)} s) with no pause, stop, or volume control"),
                location=_loc(s, m["context"], box=m["box"]), evidence=RUNTIME, refs=[_ref(ctx, "probes", "media", i)],
                consequence="the sound drowns out screen readers"))
    return _result(hits, notes)
