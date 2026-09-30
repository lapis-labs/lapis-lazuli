"""Reference implementation of the derived values in behavior/DERIVED.md (session log v0).

behavior_check stores these values in the session (the `derived` blocks, `effect.outcome`, and
`stop.focus_visible`); detectors only compare them with rule thresholds. Every function here is pure
and works on the JSON objects of a session.

    outcome(effect)                       -> control outcome class
    matches_promise(promise, outcome)     -> whether the outcome is what the control promised
    focus_visible(indicator, rect)        -> whether a focus change is visible (project policy), or None
    order_inversions(stops, containers)   -> (count, pairs) of backward jumps in the Tab order
    reasks_after_decline(appearances)     -> times a request came back after the user declined it
    choice_derived(choice_set)            -> prominence and decline-effort comparison, or None
    urgency_derived(probe)                -> whether a countdown resets or a claim drifts
    scroll_ratio(probe)                   -> actual / expected scroll distance
    flow_derived(run, pair, flow)         -> drip-priced components, sneaked lines, hidden terms, exit effort
    required_terms(run)                   -> disclosure kinds a recurring flow must make readable
    derive_session(session, plan_flows)   -> a copy of the session with every derived value recomputed
"""
from __future__ import annotations

import copy
from typing import Any

# ---------------------------------------------------------------- controls

PROMISES = {
    "navigate": {"navigated", "moved", "download"},
    "submit": {"data-requested", "navigated", "state-changed", "dialog"},
    "toggle": {"state-changed"},
    "expand": {"state-changed"},
    "select": {"state-changed", "navigated"},
    "open": {"dialog", "state-changed", "navigated"},
    "play": {"state-changed"},
    "download": {"download", "navigated"},
    "destructive": {"dialog", "state-changed", "data-requested", "navigated"},
}


def _counted_requests(effect: dict) -> list[dict]:
    """Beacons and blocked (non-local) requests say nothing about what a control did."""
    return [r for r in effect.get("requests", []) if r.get("kind") != "beacon" and not r.get("blocked")]


def outcome(effect: dict, control: str | None = None) -> str:
    """Classify what an action did. Classes and their order: DERIVED.md, Controls."""
    nav = effect.get("navigation", "none")
    if nav in ("document", "same-document", "new-window"):
        return "navigated"
    if nav == "download":
        return "download"
    if effect.get("dialog_opened"):
        return "dialog"
    if effect.get("aria_changes") or effect.get("text_changed"):
        return "state-changed"
    if any(box != control for box in [*effect.get("layout_animated", ()), *effect.get("shift_sources", ()),
                                      *effect.get("resized", ())]):
        return "state-changed"                    # another box visibly grew, shrank, or moved
    if effect.get("scroll_y_delta") or ("focus_to" in effect and effect["focus_to"] not in (None, control)):
        return "moved"
    if _counted_requests(effect):
        return "data-requested"
    if effect.get("console_errors", 0) > 0:
        return "error"
    return "no-effect"


def matches_promise(promise: str | None, result: str) -> bool:
    if result in ("no-effect", "error"):
        return False
    allowed = PROMISES.get(promise or "other")
    return True if allowed is None else result in allowed


# ---------------------------------------------------------------- keyboard

FOCUS_CONTRAST_MIN = 3.0


def focus_visible(indicator: dict | None, rect: dict | None) -> bool | None:
    """Project policy: changed pixels that reach 3:1 against their unfocused state cover at least a
    2 CSS px line along the box's longer side. None when it cannot be judged."""
    if not indicator or not rect:
        return None
    return indicator["contrast_area_px"] >= 2 * max(rect["w"], rect["h"])


def _flip(rect: dict) -> dict:
    return {**rect, "x": -(rect["x"] + rect["w"])}


def _is_backward(cur: dict, nxt: dict) -> bool:
    top = cur["y"]
    overlap = min(cur["y"] + cur["h"], nxt["y"] + nxt["h"]) - max(cur["y"], nxt["y"])
    low = min(cur["h"], nxt["h"])
    if low > 0 and overlap >= 0.5 * low:                          # same row
        return nxt["x"] + nxt["w"] / 2 < cur["x"]
    return nxt["y"] + nxt["h"] / 2 < top


def _chain(box: str | None, containers: dict) -> list[str]:
    out = []
    while box is not None and box in containers and box not in out:
        out.append(box)
        box = containers[box].get("parent")
    return out


def order_inversions(stops: list[dict], containers: dict | None = None,
                     rtl: bool = False) -> tuple[int, list[list[str]]]:
    """Backward jumps between consecutive stops (DERIVED.md, Keyboard). Stops in different containers
    that are not nested are compared by the two branches under their closest common ancestor; all
    other pairs by the stops' own rects. Moves into or out of a dialog are not compared."""
    containers = containers or {}
    pairs = []
    ordered = sorted(stops, key=lambda s: s["index"])
    for cur, nxt in zip(ordered, ordered[1:]):
        if cur.get("in_dialog") != nxt.get("in_dialog"):
            continue
        ca = cur.get("container") if cur.get("container") in containers else None
        cb = nxt.get("container") if nxt.get("container") in containers else None
        a, b = cur.get("rect"), nxt.get("rect")
        if ca and cb and ca != cb:
            chain_a, chain_b = _chain(ca, containers), _chain(cb, containers)
            common = next((c for c in chain_a if c in chain_b), None)
            if common not in (ca, cb):                            # siblings: compare the two branches
                ia = chain_a.index(common) if common else len(chain_a)
                ib = chain_b.index(common) if common else len(chain_b)
                a, b = containers[chain_a[ia - 1]]["rect"], containers[chain_b[ib - 1]]["rect"]
        if not a or not b:
            continue
        if rtl:
            a, b = _flip(a), _flip(b)
        if _is_backward(a, b):
            pairs.append([cur["box"], nxt["box"]])
    return len(pairs), pairs


CHROME_LANDMARKS = {"banner", "navigation", "complementary", "contentinfo"}   # site furniture, not page content


def _content_start(walk: dict) -> int:
    """Index where the page's own content starts: the first stop inside main that is not in site
    furniture, or the next stop of the first level-1 heading outside site furniture that has a stop
    before it (DERIVED.md, Keyboard)."""
    ordered = sorted(walk["stops"], key=lambda s: s["index"])
    cut = next((i for i, s in enumerate(ordered)
                if s.get("in_main") and s.get("landmark") not in CHROME_LANDMARKS), len(ordered))

    def after_a_stop(h):
        return (h["next_stop"] is None and ordered) or (h["next_stop"] or 0) > 0
    h1 = next((h for h in walk.get("headings", [])
               if h["level"] == 1 and h.get("landmark") not in CHROME_LANDMARKS and after_a_stop(h)), None)
    if h1 is not None:
        cut = min(cut, len(ordered) if h1["next_stop"] is None else h1["next_stop"])
    return cut


def repeated_stops(walk: dict, walks: list[dict]) -> int | None:
    """Leading stops repeated on another route in the same context, cut where the page's own content
    starts. Stops match by box id and accessible name. None when no other route was walked."""
    def keys(w):
        return [(s["box"], s.get("name")) for s in sorted(w["stops"], key=lambda s: s["index"])]
    peers = [w for w in walks if w["context"] == walk["context"] and w["path"] != walk["path"]]
    if not peers:
        return None
    mine, best = keys(walk), 0
    for peer in peers:
        theirs, n = keys(peer), 0
        while n < min(len(mine), len(theirs)) and mine[n] == theirs[n]:
            n += 1
        best = max(best, n)
    return min(best, _content_start(walk))


def skip_link_broken(walk: dict) -> bool:
    skip = walk.get("skip_link") or {}
    return bool(skip.get("present")) and skip.get("lands_at") is None


def bypass(walk: dict, repeated: int) -> list[str]:
    """Mechanisms that let a user skip the repeated leading stops (DERIVED.md, Keyboard)."""
    out = []
    skip = walk.get("skip_link") or {}
    lands = skip.get("lands_at")
    if skip.get("present") and lands is not None and lands >= repeated and lands > skip.get("index", 0) + 1:
        out.append("skip-link")
    ordered = sorted(walk["stops"], key=lambda s: s["index"])
    if (walk.get("landmarks") or {}).get("main") and not any(s.get("in_main") for s in ordered[:repeated]):
        out.append("main-landmark")
    if any((h["next_stop"] is None or h["next_stop"] >= repeated) and h.get("landmark") not in CHROME_LANDMARKS
           for h in walk.get("headings", [])):
        out.append("heading")
    return out


# ---------------------------------------------------------------- dialogs and choices

def reasks_after_decline(appearances: list[dict]) -> int:
    """Appearances after the first decline, dismissal, or 'later' that the user did not open
    themselves."""
    declined, count = False, 0
    for a in appearances:
        if declined and a["preceded_by"] != "control":
            count += 1
        if a["response"] in ("decline", "dismiss", "later"):
            declined = True
    return count


RATIO_CAP = 1000.0


def prominence(option: dict) -> float:
    v = option["visual"]
    style = 2.0 if v["filled"] else (1.5 if v.get("bordered") else 1.0)
    return v["area_px"] * style * min(v["contrast"], 7.0) / 7.0


def choice_derived(choice_set: dict) -> dict | None:
    """None for a choice set with no accept route (nothing to steer toward)."""
    opts = choice_set["options"]
    accepts = [o for o in opts if o["kind"] == "accept"]
    if not accepts:
        return None
    declines = [o for o in opts if o["kind"] == "decline"]
    if not declines:
        return {"decline_found": False}
    out: dict[str, Any] = {"decline_found": True,
                           "decline_extra_interactions": min(o["interactions"] for o in declines)
                           - min(o["interactions"] for o in accepts)}
    shown = [o for o in opts if o["layer"] == 1 and o["interactions"] > 0 and "visual" in o
             and not (o["kind"] != "accept" and o["control"] == "icon")]     # an icon-only close is not compared
    acc = [o for o in shown if o["kind"] == "accept"]
    entry = ([o for o in shown if o["kind"] == "decline"] or [o for o in shown if o["kind"] == "customize"]
             or [o for o in shown if o["kind"] == "dismiss"])
    if acc and entry:
        a, d = max(prominence(o) for o in acc), max(prominence(o) for o in entry)
        ratio = RATIO_CAP if d == 0 and a > 0 else (0.0 if a == 0 else min(a / d, RATIO_CAP))
        out["prominence_ratio"] = round(ratio, 2)
    return out


# ---------------------------------------------------------------- urgency and scroll

RESET_TOLERANCE_S = 2.0


def urgency_derived(probe: dict) -> dict:
    readings = probe["readings"]
    load = next((r for r in readings if r["when"] == "load"), None)
    if probe["kind"] in ("countdown", "deadline"):
        resets = False
        if load is not None:
            for r in readings:
                if r["when"] in ("later", "reload", "fresh-profile"):
                    tolerance = max(RESET_TOLERANCE_S, r.get("resolution_s", 0), load.get("resolution_s", 0))
                    if r["value"] > load["value"] - r["elapsed_ms"] / 1000 + tolerance:
                        resets = True
        return {"resets": resets, "drifts": False}
    if probe["kind"] == "hold":
        return {"resets": False, "drifts": False}
    values = {r["value"] for r in readings if r["when"] in ("load", "later", "reload", "fresh-profile")}
    return {"resets": False, "drifts": len(values) > 1}


def scroll_ratio(probe: dict) -> float | None:
    if probe["expected_px"] <= 0:
        return None
    return round(probe["actual_px"] / probe["expected_px"], 2)


# ---------------------------------------------------------------- flows

CHARGE_KINDS = {"fee", "shipping", "tax", "deposit", "recurring"}
RECURRING_CADENCE = {"day", "week", "month", "year", "other"}
VISIBLE = {"primary", "secondary"}
PLACEMENT_ORDER = ["near-commit", "primary", "secondary", "collapsed", "tooltip", "after-commit", "absent"]
EXIT_KINDS = {"cancel-subscription", "delete-account", "withdraw-consent", "unsubscribe"}
AMOUNT_EPSILON = 0.005


def _drip(run: dict) -> list[str]:
    """Charges that appear, rise, settle without the input they waited for, stay pending at the
    commit, or lose a discount after the first price step, without user input. DERIVED.md, Flows."""
    obs = sorted(run.get("prices", []), key=lambda o: o["step"])
    first = next((o["step"] for o in obs for c in o["components"]
                  if c["kind"] == "item" and c["state"] == "known"), None)
    if first is None:
        return []
    state: dict[str, dict] = {}
    drip: list[str] = []
    currency = None

    def hit(key: str) -> None:
        if key not in drip:
            drip.append(key)

    for o in obs:
        after = o["step"] > first
        if currency is not None and o["currency"] != currency:
            for st in state.values():                             # amounts in another currency do not compare
                st["amount"] = None
        currency = o["currency"]
        present = {c["key"] for c in o["components"]}
        for c in o["components"]:
            key, prev = c["key"], state.get(c["key"])
            amount = c.get("amount") if c["state"] in ("known", "estimated") else None
            charge = c["mandatory"] and c["kind"] in CHARGE_KINDS
            if after and not c.get("user_caused"):
                if charge and (prev is None or not prev["disclosed"]):
                    hit(key)                                      # a new or previously hidden charge
                elif prev is not None and (charge or c["kind"] in ("item", "total")):
                    if prev["amount"] is not None and amount is not None and amount > prev["amount"] + AMOUNT_EPSILON:
                        hit(key)                                  # the amount rose
                    elif prev["pending"] and prev["amount"] is None and amount is not None:
                        hit(key)                                  # settled without the input it waited for
                if (c["kind"] == "discount" and prev is not None and prev["amount"] is not None
                        and amount is not None and abs(amount) + AMOUNT_EPSILON < abs(prev["amount"])):
                    hit(key)                                      # the discount shrank
            disclosed = after or c.get("placement", "primary") in VISIBLE
            state[key] = {"kind": c["kind"],
                          "disclosed": disclosed or (prev or {}).get("disclosed", False),
                          "amount": amount if amount is not None else (prev or {}).get("amount"),
                          "pending": c["state"] == "pending"}
        if after and any(c["kind"] == "total" for c in o["components"]):
            for key, st in state.items():
                if st["kind"] == "discount" and key not in present:
                    hit(key)                                      # a discount left the breakdown
    commit = run.get("commit_step")
    at_commit = [o for o in obs if commit is not None and o["step"] <= commit]
    if at_commit:
        for c in at_commit[-1]["components"]:
            if c["mandatory"] and c["kind"] in CHARGE_KINDS and c["state"] == "pending":
                hit(c["key"])                                     # still to be calculated when the user commits
    return drip


def _sneaked(run: dict) -> list[str]:
    keys: list[str] = []
    for o in sorted(run.get("cart", []), key=lambda o: o["step"]):
        for line in o["lines"]:
            if line["added_by"] == "system" and line["amount"] > 0 and line["key"] not in keys:
                keys.append(line["key"])
    return keys


def _recurring(run: dict) -> bool:
    return any(c["kind"] == "recurring" or c.get("cadence") in RECURRING_CADENCE
               for o in run.get("prices", []) for c in o["components"])


def required_terms(run: dict) -> list[str]:
    """Disclosure kinds a flow must make readable: none unless it charges on a recurring basis."""
    if not _recurring(run):
        return []
    required = ["cadence", "cancellation-method", "renewal-price"]
    if run.get("trial"):
        required += ["trial-conversion", "trial-end"]
    return sorted(required)


def _best(disclosures: list[dict], kind: str) -> dict | None:
    found = [d for d in disclosures if d["kind"] == kind]
    if not found:
        return None
    return {"placement": min((d["placement"] for d in found), key=PLACEMENT_ORDER.index),
            "at_commit": any(d.get("at_commit") for d in found),
            "step": min((d["step"] for d in found if "step" in d), default=None)}


def _hidden_terms(run: dict) -> list[str]:
    commit = run.get("commit_step")
    disclosures = run.get("disclosures", [])
    hidden = []
    for kind in required_terms(run):
        d = _best(disclosures, kind)
        if kind == "cancellation-method":
            ok = (d is not None and d["placement"] in {"near-commit", "primary", "secondary"}
                  and d["step"] is not None and (commit is None or d["step"] <= commit))
        else:
            ok = d is not None and d["at_commit"]
        if not ok:
            hidden.append(kind)
    return hidden


def _exit(run: dict, pair: dict | None, flow: dict | None) -> dict | None:
    # the comparison needs a pair run that completed in the same context; otherwise it is skipped
    if run["kind"] not in EXIT_KINDS or pair is None or pair.get("status") != "completed":
        return None
    e, p = run["effort"], pair["effort"]
    declared = "reauth" in ((flow or {}).get("requires") or [])
    return {"pair": pair["id"],
            "extra_steps": e["steps"] - p["steps"],
            "extra_interactions": e["interactions"] - p["interactions"],
            "added_reauth": bool(e.get("reauth")) and not bool(p.get("reauth")) and not declared}


def flow_derived(run: dict, pair: dict | None = None, flow: dict | None = None) -> dict:
    out: dict[str, Any] = {"drip": _drip(run), "sneaked": _sneaked(run), "hidden_terms": _hidden_terms(run)}
    ex = _exit(run, pair, flow)
    if ex is not None:
        out["exit"] = ex
    return out


# ---------------------------------------------------------------- whole session

def derive_session(session: dict, plan_flows: list[dict] | None = None) -> dict:
    """Recompute every derived value. `plan_flows` is the plan's `flows`; exit runs are compared
    with the run of their `pair` in the same context."""
    s = copy.deepcopy(session)
    nodes = s.get("nodes", {})
    probes = s.get("probes", {})
    rtl = {c["id"]: c.get("dir") == "rtl" for c in s.get("contexts", [])}
    for c in probes.get("controls", []):
        c["effect"]["outcome"] = outcome(c["effect"], c["box"])
        c["derived"] = {"matches_promise": matches_promise(c.get("promise"), c["effect"]["outcome"])}
    walks = probes.get("keyboard", [])
    for k in walks:
        for stop in k["stops"]:
            rect = stop.get("rect") or (nodes.get(stop["box"]) or {}).get("rect")
            visible = focus_visible(stop.get("indicator"), rect)
            if visible is None:
                stop.pop("focus_visible", None)
            else:
                stop["focus_visible"] = visible
        n, pairs_ = order_inversions(k["stops"], k.get("containers"), rtl.get(k["context"], False))
        k["derived"] = {"order_inversions": n, "inversion_pairs": pairs_}
        rep = repeated_stops(k, walks)
        if rep is not None:
            k["derived"]["repeated_stops"] = rep
            k["derived"]["bypass"] = bypass(k, rep)
    for d in probes.get("dialogs", []):
        d["derived"] = {"reasks_after_decline": reasks_after_decline(d["appearances"])}
    for cs in probes.get("choices", []):
        der = choice_derived(cs)
        if der is None:
            cs.pop("derived", None)
        else:
            cs["derived"] = der
    for u in probes.get("urgency", []):
        u["derived"] = urgency_derived(u)
    for sc in probes.get("scroll", []):
        r = scroll_ratio(sc)
        if r is None:
            sc.pop("derived", None)
        else:
            sc["derived"] = {"ratio": r}
    flows = {f["id"]: f for f in (plan_flows or [])}
    runs = s.get("flows", [])
    by_key = {(r["id"], r["context"]): r for r in runs}
    for r in runs:
        flow = flows.get(r["id"])
        pair_id = (flow or {}).get("pair")
        r["derived"] = flow_derived(r, by_key.get((pair_id, r["context"])) if pair_id else None, flow)
    return s
