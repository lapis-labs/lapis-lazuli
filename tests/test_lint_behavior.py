"""Behavior-layer detectors of slop_lint, run with the shipped rules on small hand-built sessions.

Every session here validates against behavior/session.schema.yaml and carries no derived values,
so the detectors fill them the way behavior_check does (lapis_design.behavior.derive_session)."""
from __future__ import annotations

import copy

import jsonschema
import pytest
import yaml

import lapis_design.lint.detectors.behavior  # noqa: F401  (registers the detectors)
from lapis_design import shared_dir
from lapis_design.lint.types import DETECTORS, Context

RULES = yaml.safe_load((shared_dir() / "slop" / "rules.yaml").read_text())
BY_ID = {r["id"]: r for r in RULES["rules"]}
VALIDATOR = jsonschema.Draft202012Validator(
    yaml.safe_load((shared_dir() / "behavior" / "session.schema.yaml").read_text()))

BEHAVIOR = ["control-has-effect", "console-errors", "focus-visible", "state-coverage", "reduced-motion-respected",
            "dialog-usage", "keyboard-traversal", "keyboard-bypass", "context-change", "choice-analysis",
            "flow-analysis", "form-behavior", "commit-safety", "status-announcement", "urgency-integrity",
            "time-limit", "history-behavior", "pointer-alternatives", "scroll-behavior", "permission-requests",
            "media-autoplay", "primary-action-reach"]


def box(n: int) -> str:
    return f"b{n:012x}"


A, B, C, D, E, F = (box(n) for n in range(1, 7))
CLICKABLE_DIV = box(99)


def session(probes: dict | None = None, *, flows=None, console=None) -> dict:
    ctx = {"height": 844, "theme": "light", "network": "normal", "dir": "ltr", "clock": "controlled"}
    doc = {
        "version": 0,
        "meta": {"driver": {"name": "behavior_check", "version": "0.1.0"},
                 "generated_at": "2026-09-26T10:00:00Z", "backend": "stub"},
        "source": {"kind": "render", "url": "http://127.0.0.1:4173/", "task": "demo"},
        "contexts": [{"id": "m", "width": 390, "pointer": "coarse", "reduced_motion": False, **ctx},
                     {"id": "d", "width": 1440, "pointer": "fine", "reduced_motion": False, **ctx, "height": 900},
                     {"id": "m-rm", "width": 390, "pointer": "coarse", "reduced_motion": True, **ctx}],
        "nodes": {**{box(n): {"role": "button", "name": f"Control {n}"} for n in range(1, 7)},
                  CLICKABLE_DIV: {"role": "other", "name": "Clickable card"}},
        "probes": probes or {},
        "coverage": [],
    }
    if flows is not None:
        doc["flows"] = flows
    if console is not None:
        doc["console"] = console
    return doc


def run(rule_id: str, doc: dict | None, *, plan: dict | None = None):
    rule = BY_ID[rule_id]
    det = copy.deepcopy(rule["detect"]["behavior"])
    if doc is not None:
        assert [e.message for e in VALIDATOR.iter_errors(doc)] == []
    ctx = Context(rules=RULES, session=doc, plan=plan, session_path=".lapis/behavior/demo.json")
    return DETECTORS[det["detector"]].fn(ctx, det, rule, "behavior")


def hit_boxes(result) -> list:
    return [h.location.get("box") for h in result.hits]


def test_every_behavior_detector_skips_without_a_session():
    rules = {r["detect"]["behavior"]["detector"]: r["id"] for r in RULES["rules"]
             if "behavior" in (r.get("detect") or {})}
    for name in BEHAVIOR:
        result = run(rules[name], None)
        assert result.hits == [] and result.skipped, name


# ---------------------------------------------------------------- controls and console

def control(b, promise, effect, context="m", keyboard=None):
    probe = {"box": b, "context": context, "promise": promise, "action": {"kind": "tap", "target": b},
             "effect": {"navigation": "none", **effect}}
    if keyboard:
        probe["keyboard"] = keyboard
    return probe


def primary_run(status, target, kind="primary"):
    return {"id": "reserve", "context": "m", "kind": kind, "status": status,
            "steps": [{"index": 0, "path": "/", "actions": [{"kind": "tap", "target": target}]}],
            "effort": {"steps": 1, "interactions": 1}}


@pytest.mark.parametrize("gap,fires", [(421.9, False), (422, False), (422.1, True)])
def test_primary_action_reach_uses_the_same_screen_boundary_not_initial_depth(gap, fires):
    flow = primary_run("completed", A)
    flow["steps"][0]["action_reach"] = {
        "box": A, "initial": {"action_y": 3000, "below_first_view_px": 2156},
        "after_selections": {"action_y": 1000 + gap, "selection_bottom_y": 1000, "gap_px": gap,
                             "visible": False, "pinned": False}}
    result = run("layout.primary-action-reach", session(flows=[flow]))
    assert hit_boxes(result) == ([A] if fires else [])


def test_dead_control_hits_no_effect_mismatch_and_console_errors():
    doc = session({"controls": [
        control(A, "submit", {"outcome": "no-effect"}),
        control(B, "toggle", {"outcome": "navigated", "navigation": "document", "path": "/x"}),
        control(C, "expand", {"outcome": "state-changed", "console_errors": 2,
                              "aria_changes": [{"box": C, "attr": "aria-expanded", "from": "false", "to": "true"}]}),
        control(D, "expand", {"outcome": "state-changed",
                              "aria_changes": [{"box": D, "attr": "aria-expanded", "from": "false", "to": "true"}]}),
        control(E, "navigate", {"outcome": "navigated", "navigation": "document", "external": True}),
    ]})
    result = run("ux.dead-control", doc)
    assert hit_boxes(result) == [A, B, C]
    assert all(h.evidence == "runtime" and h.location["context"] == "m" for h in result.hits)
    assert result.skipped is None


def test_dead_control_on_an_unfinished_primary_flow_blocks_the_primary_task():
    probes = {"controls": [control(A, "submit", {"outcome": "no-effect"})]}
    blocked = run("ux.dead-control", session(probes, flows=[primary_run("blocked", A)]))
    finished = run("ux.dead-control", session(probes, flows=[primary_run("completed", A)]))
    assert blocked.hits[0].conditions == {"the primary task is blocked"}
    assert finished.hits[0].conditions == frozenset()


def test_dead_control_skips_focused_entry_fields_and_reports_each_control_once():
    doc = session({"controls": [
        control(A, "other", {"outcome": "no-effect", "focus_to": A}),           # text field took focus
        control(A, "other", {"outcome": "no-effect", "focus_to": A}, context="d"),
        control(B, "other", {"outcome": "no-effect", "focus_to": B}),           # a button that only focuses
        control(C, "submit", {"outcome": "no-effect"}),
        control(C, "submit", {"outcome": "no-effect"}, context="d"),
    ]})
    doc["nodes"][A] = {"role": "input", "name": "Email"}
    result = run("ux.dead-control", doc)
    assert hit_boxes(result) == [B, C]
    assert "tap (m), tap (d)" in result.hits[1].observed and len(result.hits[1].refs) == 2


def test_console_errors_group_listed_kinds_only():
    entries = [{"context": "m", "level": "error", "kind": "hydration-mismatch", "message": "text differs"},
               {"context": "d", "level": "error", "kind": "hydration-mismatch", "message": "text differs"},
               {"context": "m", "level": "error", "kind": "exception", "message": "boom"}]
    result = run("code.locale-time-rendering", session(console=entries))
    assert len(result.hits) == 1 and "2 time" in result.hits[0].observed
    assert run("code.locale-time-rendering", session(console=entries[2:])).hits == []


# ---------------------------------------------------------------- keyboard

def stop(i, b, *, rect=(0, 0, 100, 30), **kw):
    x, y, w, h = rect
    return {"box": b, "index": i, "rect": {"x": x, "y": y, "w": w, "h": h}, **kw}


def walk(stops, path="/", context="d", **kw):
    return {"context": context, "path": path, "stops": stops, "completed": True, **kw}


def test_focus_visible_hits_stops_below_the_indicator_policy():
    doc = session({"keyboard": [walk([
        stop(0, A, indicator={"area_px": 199, "contrast": 5, "contrast_area_px": 199}),   # needs 2 x 100 px
        stop(1, B, indicator={"area_px": 400, "contrast": 1.7, "contrast_area_px": 200}),  # the allowed edge
        stop(2, C, indicator={"area_px": 400, "contrast": 2.9, "contrast_area_px": 0}),
    ])]})
    result = run("code.focus-outline-removed", doc)
    assert hit_boxes(result) == [A, C] and result.skipped is None


def test_focus_visible_names_unmeasured_stops_instead_of_passing_them():
    result = run("code.focus-outline-removed", session({"keyboard": [walk([stop(0, A)])]}))
    assert result.hits == [] and "indicator" in result.skipped


def test_keyboard_trap_hits_cycles_escape_does_not_leave():
    trapped = walk([stop(0, A)], traps=[{"boxes": [A, B], "escape_leaves": False}])
    left = walk([stop(0, A)], path="/b", traps=[{"boxes": [C], "escape_leaves": True}])
    assert hit_boxes(run("ux.keyboard-trap", session({"keyboard": [trapped, left]}))) == [A]


def test_operable_splits_semantic_controls_from_clickable_elements():
    doc = session({
        "keyboard": [walk([stop(0, A)], unreachable=[{"box": B, "semantic": True},
                                                     {"box": CLICKABLE_DIV, "semantic": False}])],
        "controls": [control(C, "submit", {"outcome": "data-requested", "requests": [
                        {"method": "POST", "host": "127.0.0.1:4173", "path": "/api/orders"}]},
                             keyboard={"focusable": True, "activation": "none"}),
                     control(D, "expand", {"outcome": "state-changed", "text_changed": [D]},
                             keyboard={"focusable": True, "activation": "same"})],
    })
    assert hit_boxes(run("ux.keyboard-inoperable", doc)) == [B, C]
    assert hit_boxes(run("code.clickable-non-interactive", doc)) == [CLICKABLE_DIV]


def test_inoperable_control_on_the_primary_flow_blocks_the_primary_task():
    doc = session({"keyboard": [walk([stop(0, A)], unreachable=[{"box": B, "semantic": True}])]},
                  flows=[primary_run("completed", B)])
    assert run("ux.keyboard-inoperable", doc).hits[0].conditions == {"the primary task is blocked"}


def test_focus_order_hits_a_backward_jump():
    backward = walk([stop(0, A, rect=(0, 400, 100, 30)), stop(1, B, rect=(0, 0, 100, 30))])
    forward = walk([stop(0, A, rect=(0, 0, 100, 30)), stop(1, B, rect=(0, 400, 100, 30))], path="/b")
    result = run("ux.focus-order", session({"keyboard": [backward, forward]}))
    assert [h.location["path"] for h in result.hits] == ["/"]


def test_focus_obscured_fires_only_above_the_bound():
    doc = session({"keyboard": [walk([stop(0, A, obscured_share=0.99), stop(1, B, obscured_share=1.0, obscured_by=C)])]})
    assert hit_boxes(run("ux.focus-obscured", doc)) == [B]


NAV = [(A, "Home"), (B, "Shop"), (C, "About")]


def route(path, *, main=False, skip=None, own=(), headings=None, nav=NAV):
    stops = [stop(i, b, name=n, landmark="navigation", in_main=False) for i, (b, n) in enumerate(nav)]
    stops += [stop(len(stops) + i, b, name=n, landmark="main", in_main=True) for i, (b, n) in enumerate(own)]
    w = walk(stops, path=path, landmarks={"main": main}, headings=headings or [])
    if skip is not None:
        w["skip_link"] = skip
    return w


def test_no_bypass_hits_repeated_navigation_without_a_way_past():
    doc = session({"keyboard": [route("/"), route("/shop")]})
    result = run("ux.no-bypass", doc)
    assert len(result.hits) == 1 and "3 repeated" in result.hits[0].observed


def test_no_bypass_accepts_a_main_landmark_after_the_repeated_block():
    doc = session({"keyboard": [route("/", main=True, own=[(D, "Buy")]), route("/shop", main=True, own=[(E, "Filter")])]})
    assert run("ux.no-bypass", doc).hits == []


def test_bypass_with_one_walked_route_is_not_verified():
    result = run("ux.no-bypass", session({"keyboard": [route("/")]}))
    assert result.hits == [] and "one walked route" in result.skipped


def test_skip_link_reports_a_broken_link_even_on_one_route():
    doc = session({"keyboard": [route("/", skip={"present": True, "box": A, "index": 0, "lands_at": None})]})
    result = run("ux.skip-link-missing", doc)
    assert hit_boxes(result) == [A]


def test_skip_link_bound_counts_repeated_stops_without_a_skip_link():
    def header(n):
        nav = [(box(10 + i), f"Nav {i}") for i in range(n)]
        return session({"keyboard": [route("/", main=True, nav=nav), route("/b", main=True, nav=nav)]})
    assert run("ux.skip-link-missing", header(5)).hits == []
    assert len(run("ux.skip-link-missing", header(6)).hits) == 1    # a main landmark is not a skip link


def test_context_change_on_focus_and_on_input():
    doc = session({
        "keyboard": [walk([stop(0, A, context_change="navigated"), stop(1, B, context_change="none")])],
        "forms": [{"box": E, "context": "m", "purpose": "settings", "fields": [
            {"box": C, "kind": "select", "on_change": "submitted"}, {"box": D, "kind": "checkbox", "on_change": "none"}]}],
    })
    assert hit_boxes(run("ux.unexpected-context-change", doc)) == [A, C]


def test_context_change_names_stops_without_a_recorded_change():
    result = run("ux.unexpected-context-change", session({"keyboard": [walk([stop(0, A)])]}))
    assert result.hits == [] and "no context change recorded" in result.skipped


# ---------------------------------------------------------------- states and motion

def state(st, shown=True, **kw):
    return {"context": "m", "surface": A, "state": st, "induced_by": kw.pop("induced_by", "fixture"), "shown": shown, **kw}


def test_missing_states_hits_unshown_blank_and_indistinguishable_states():
    doc = session({"states": [
        state("loading", shown=False, induced_by="delay"),
        state("error", induced_by="fail-5xx", same_as=["empty"]),
        state("empty", blank=True),
        state("success", induced_by="action"),
        state("timeout", shown=False, induced_by="hang"),              # not among the rule's states
    ]})
    result = run("ux.missing-states", doc)
    assert [h.observed.split()[0] for h in result.hits] == ["loading", "error", "empty"]


def test_generic_spinner_fires_only_above_the_bound_for_regions_and_pages():
    def spinner(ms, scope="region"):
        return state("loading", induced_by="delay", indicator="spinner", indicator_shown_ms=ms, scope=scope)
    assert run("component.generic-spinner", session({"states": [spinner(1000), spinner(5000, "object")]})).hits == []
    assert len(run("component.generic-spinner", session({"states": [spinner(1001)]})).hits) == 1
    unmeasured = state("loading", induced_by="delay", indicator="spinner", scope="page")
    result = run("component.generic-spinner", session({"states": [unmeasured]}))
    assert result.hits == [] and "not measured" in result.skipped


def test_error_without_recovery_needs_problem_text_and_a_working_recovery():
    good = state("error", induced_by="fail-5xx", problem_text=True, recovery_action=True, recovery_works=True)
    broken = state("error", induced_by="fail-5xx", problem_text=True, recovery_action=True, recovery_works=False)
    offline = state("offline", induced_by="offline", problem_text=False, recovery_action=False)
    result = run("copy.error-without-recovery", session({"states": [good, broken, offline]}))
    assert len(result.hits) == 1 and "does not recover" in result.hits[0].observed


def test_reduced_motion_hits_spatial_motion_that_is_not_essential():
    doc = session({"motion": [
        {"context": "m-rm", "compare_to": "m", "window_ms": 5000, "moving": [
            {"box": A, "kind": "transform", "travel_px": 40},
            {"box": B, "kind": "opacity"},
            {"box": C, "kind": "video", "essential": True},
            {"box": D, "kind": "scroll-linked"}]},
        {"context": "m", "window_ms": 5000, "moving": [{"box": A, "kind": "transform", "travel_px": 40}]},
    ]})
    assert hit_boxes(run("motion.reduced-motion-missing", doc)) == [A, D]


def test_reduced_motion_without_a_reduced_context_is_skipped():
    doc = session({"motion": [{"context": "m", "window_ms": 5000, "moving": [{"box": A, "kind": "transform"}]}]})
    result = run("motion.reduced-motion-missing", doc)
    assert result.hits == [] and "reduced motion" in result.skipped
    assert result.cause == "probe"


# ---------------------------------------------------------------- dialogs

def dialog(b, trigger, purpose, *, kind="modal", responses=("decline",), **kw):
    appearances = [{"preceded_by": p, "response": r} for p, r in
                   ([("none", responses[0])] + [(pre, "decline") for pre in responses[1:]])]
    return {"box": b, "context": "m", "kind": kind, "trigger": trigger, "purpose": purpose,
            "appearances": appearances, **kw}


def test_routine_modal_hits_route_modals_link_modals_and_multi_step_tasks():
    link = box(50)
    doc = session(
        {"dialogs": [
            dialog(A, "navigation", "other", blocks_content=True),
            dialog(B, "control", "other", blocks_content=True, trigger_box=link),
            dialog(C, "control", "task", blocks_content=True),
            dialog(D, "control", "task", blocks_content=True),
            dialog(E, "control", "confirm", blocks_content=True),
            dialog(F, "navigation", "task", kind="sheet", blocks_content=True)],
         "controls": [control(link, "navigate", {"outcome": "dialog", "dialog_opened": B})]},
        flows=[flow("buy", "purchase", step_list=[{"index": 0, "path": "/"}, {"index": 1, "path": "/", "dialog": C},
                                                  {"index": 2, "path": "/", "dialog": C}])])
    result = run("ux.routine-modal", doc)
    assert hit_boxes(result) == [A, B, C]
    assert D in result.skipped                                    # a one-step task dialog is left to review


def test_entry_interruption_hits_blocking_dialogs_before_any_input():
    doc = session({"dialogs": [
        dialog(A, "load", "marketing", blocks_content=True),
        dialog(B, "control", "marketing", blocks_content=True),
        dialog(C, "load", "marketing", kind="banner", blocks_content=False),
        dialog(D, "timer", "consent", blocks_content=True),            # consent is not among the rule's purposes
    ]})
    assert hit_boxes(run("ux.entry-interruption", doc)) == [A]


def test_dialog_focus_management():
    ok = {"moved_in": True, "contained": True, "escape_closes": True, "close_control": True, "returns_to": "invoker"}
    doc = session({
        "dialogs": [
            dialog(A, "control", "task", blocks_content=True, focus={**ok, "moved_in": False}),
            dialog(B, "control", "task", blocks_content=True, focus={**ok, "returns_to": "body"}),
            dialog(C, "control", "task", blocks_content=True, focus={**ok, "escape_closes": False, "close_control": False}),
            dialog(D, "control", "task", blocks_content=True, focus=ok),
            dialog(E, "timer", "marketing", blocks_content=True, focus={**ok, "returns_to": "body"}),
        ],
        "commits": [{"box": F, "context": "m", "kind": "delete", "destructive": True,
                     "confirm": {"shown": True, "names_object": True, "initial_focus": "destructive"}}],
    })
    result = run("ux.dialog-focus", doc)
    assert hit_boxes(result) == [A, B, C, F] and result.skipped is None


def test_dialog_focus_names_dialogs_whose_focus_was_not_recorded():
    result = run("ux.dialog-focus", session({"dialogs": [dialog(A, "control", "task", blocks_content=True)]}))
    assert result.hits == [] and A in result.skipped


def test_nagging_counts_reasks_the_user_did_not_open():
    doc = session({
        "dialogs": [dialog(A, "timer", "marketing", responses=("decline", "navigation")),
                    dialog(B, "timer", "marketing", responses=("decline", "control"))],
        "permissions": [{"context": "m", "api": "notifications", "user_gesture": True, "after_denial": True}],
    })
    result = run("ux.nagging", doc)
    assert hit_boxes(result) == [A, None]
    assert "notifications" in result.hits[1].observed


# ---------------------------------------------------------------- choices

def option(kind, *, interactions=1, area=400, filled=True, contrast=7.0, control="button", **kw):
    o = {"kind": kind, "control": control, "layer": kw.pop("layer", 1), "interactions": interactions, **kw}
    if interactions:
        o["visual"] = {"area_px": area, "filled": filled, "contrast": contrast}
    return o


def choices(*sets):
    return [{"id": f"c{i}", "context": "m", "purpose": purpose, "options": opts, "container": box(20 + i)}
            for i, (purpose, opts) in enumerate(sets, 1)]


def test_preselection_hits_accept_options_and_optional_fields_checked_on_load():
    doc = session({
        "choices": choices(
            ("marketing", [option("accept", interactions=0, preselected=True, box=A), option("decline", box=B)]),
            ("add-on", [option("accept", interactions=0, preselected=True, price=4.5, currency="USD", box=C),
                        option("decline", interactions=0)]),
            ("marketing", [option("accept", box=D), option("decline", box=E)])),
        "forms": [{"box": F, "context": "m", "purpose": "checkout", "fields": [
            {"box": box(30), "kind": "checkbox", "purpose": "marketing", "checked_on_load": True},
            {"box": box(31), "kind": "checkbox", "purpose": "add-on", "checked_on_load": True},
            {"box": box(32), "kind": "checkbox", "purpose": "terms", "checked_on_load": True, "required": True}]}],
    })
    result = run("ux.preselected-option", doc)
    assert hit_boxes(result) == [A, C, box(30), box(31)]
    assert [bool(h.conditions) for h in result.hits] == [False, True, False, True]


def test_preselection_compares_plans_by_annualized_price():
    monthly = option("neutral", preselected=True, price=10, currency="USD", cadence="month", box=A)
    yearly = option("neutral", price=100, currency="USD", cadence="year", box=B)
    result = run("ux.preselected-option", session({"choices": choices(("plan", [monthly, yearly]))}))
    assert hit_boxes(result) == [A] and result.hits[0].conditions == {"the preselected option adds a charge"}
    cheap = option("neutral", preselected=True, price=100, currency="USD", cadence="year", box=B)
    dear = option("neutral", price=10, currency="USD", cadence="month", box=A)
    assert run("ux.preselected-option", session({"choices": choices(("plan", [dear, cheap]))})).hits == []


def test_false_hierarchy_fires_only_above_the_ratio_bound():
    def pair(accept_area):                                        # filled 2x style against unstyled text
        return ("marketing", [option("accept", area=accept_area), option("decline", area=200, filled=False)])
    assert run("ux.false-hierarchy", session({"choices": choices(pair(400))})).hits == []      # ratio 4.0
    assert len(run("ux.false-hierarchy", session({"choices": choices(pair(404))})).hits) == 1  # ratio 4.04


def test_asymmetric_decline_hits_extra_effort_and_missing_declines():
    doc = session({"choices": choices(
        ("consent", [option("accept"), option("decline", interactions=3, layer=2)]),
        ("consent", [option("accept"), option("customize")]),
        ("consent", [option("accept"), option("decline")]),
        ("consent", [option("accept", interactions=0, preselected=True), option("decline", interactions=2)]))})
    result = run("ux.asymmetric-decline", doc)
    assert hit_boxes(result) == [box(21), box(22)]


def test_confirmshaming_reports_matching_decline_labels_as_review_leads():
    doc = session({"choices": choices(("marketing", [
        option("accept", label="Get the deal", lang="en"),
        option("decline", label="No thanks, I don’t want to save", lang="en", box=A),
        option("dismiss", label="Not now", lang="en", box=B),
        option("decline", label="할인은 필요 없어요", lang="ko-KR", box=C)]))})
    result = run("ux.confirmshaming", doc)
    assert hit_boxes(result) == [A, C] and {h.evidence for h in result.hits} == {"review"}


def test_confirmshaming_names_options_without_a_recorded_label():
    doc = session({"choices": choices(("marketing", [option("accept"), option("decline", box=A)]))})
    result = run("ux.confirmshaming", doc)
    assert result.hits == [] and "no recorded label" in result.skipped


# ---------------------------------------------------------------- flows

PLAN = {"flows": [
    {"id": "join", "kind": "subscribe", "goal": "Join the monthly box", "start": "/", "done": {"route": "/welcome"},
     "max_steps": 3},
    {"id": "leave", "kind": "cancel-subscription", "goal": "Cancel the monthly box", "start": "/account",
     "done": {"text": "Cancelled"}, "pair": "join"},
    {"id": "buy", "kind": "purchase", "goal": "Buy a mug", "start": "/", "done": {"route": "/thanks"},
     "requires": ["address"], "max_steps": 3},
]}


def flow(fid, kind, *, status="completed", steps=3, interactions=3, context="m", **kw):
    effort = {"steps": steps, "interactions": interactions, **kw.pop("effort", {})}
    return {"id": fid, "context": context, "kind": kind, "status": status,
            "steps": kw.pop("step_list", [{"index": i, "path": f"/s{i}"} for i in range(steps)]), "effort": effort, **kw}


def comp(key, kind, amount, **kw):
    return {"key": key, "kind": kind, "state": "known", "amount": amount, "mandatory": True, **kw}


def test_drip_pricing_hits_a_fee_that_first_appears_late():
    prices = [{"step": 0, "currency": "USD", "components": [comp("mug", "item", 20, placement="primary")]},
              {"step": 2, "currency": "USD", "components": [comp("mug", "item", 20), comp("service", "fee", 3)]}]
    honest = [{"step": 0, "currency": "USD", "components": [comp("mug", "item", 20, placement="primary"),
                                                            comp("service", "fee", 3, placement="primary")]},
              {"step": 2, "currency": "USD", "components": [comp("mug", "item", 20), comp("service", "fee", 3)]}]
    result = run("ux.drip-pricing", session(flows=[flow("buy", "purchase", prices=prices)]))
    assert len(result.hits) == 1 and result.hits[0].location == {"flow": "buy", "step": 2, "context": "m", "viewport": 390}
    assert run("ux.drip-pricing", session(flows=[flow("buy", "purchase", prices=honest)])).hits == []


def test_sneak_into_basket_hits_system_lines_with_a_price():
    cart = [{"step": 1, "lines": [{"key": "mug", "added_by": "user", "amount": 20},
                                  {"key": "insurance", "added_by": "system", "amount": 2}]}]
    assert len(run("ux.sneak-into-basket", session(flows=[flow("buy", "purchase", cart=cart)])).hits) == 1
    cart[0]["lines"].pop()
    assert run("ux.sneak-into-basket", session(flows=[flow("buy", "purchase", cart=cart)])).hits == []


def test_hidden_subscription_marks_trials_that_convert():
    prices = [{"step": 2, "currency": "USD", "components": [comp("box", "recurring", 12, cadence="month")]}]
    shown = [{"kind": k, "placement": "near-commit", "step": 2, "at_commit": True}
             for k in ("renewal-price", "cadence", "cancellation-method", "trial-end", "trial-conversion")]
    hidden = flow("join", "subscribe", prices=prices, trial=True, commit_step=2,
                  disclosures=[{"kind": "renewal-price", "placement": "collapsed", "step": 2}])
    result = run("ux.hidden-subscription", session(flows=[hidden]))
    assert result.hits[0].conditions == {"a free or discounted trial converts to a paid plan"}
    clear = flow("join", "subscribe", prices=prices, trial=True, commit_step=2, disclosures=shown)
    assert run("ux.hidden-subscription", session(flows=[clear])).hits == []


def test_hidden_subscription_needs_a_commit_to_judge_terms_at():
    # A preview on a page that lists monthly plans never commits, so no term can be hidden at a commit.
    prices = [{"step": 0, "currency": "USD", "components": [comp("personal", "recurring", 8, cadence="month")]}]
    preview = run("ux.hidden-subscription", session(flows=[flow("preview", "primary", prices=prices)]))
    assert preview.hits == [] and preview.skipped is None
    # A flow declared as a subscription that reached no commit is not verified rather than passed.
    join = run("ux.hidden-subscription", session(flows=[flow("join", "subscribe", prices=prices)]))
    assert join.hits == [] and "join" in join.skipped and "reached no commit" in join.skipped
    # Pins existing behavior: the note is kept for purchase and subscribe runs whatever their status, never for other kinds.
    for kind in ("purchase", "subscribe"):
        for status in ("completed", "blocked", "abandoned", "dead-end"):
            ended = run("ux.hidden-subscription", session(flows=[flow("join", kind, status=status, prices=prices)]))
            assert ended.hits == [] and "recurring terms not verified" in ended.skipped
    for status in ("completed", "blocked", "abandoned", "dead-end"):
        other = run("ux.hidden-subscription", session(flows=[flow("join", "primary", status=status, prices=prices)]))
        assert other.hits == [] and other.skipped is None


def test_obstructed_exit_compares_effort_with_the_join_flow_at_the_bound():
    join = flow("join", "subscribe", steps=2, interactions=3)
    at_bound = run("ux.obstructed-exit", session(flows=[join, flow("leave", "cancel-subscription", steps=4, interactions=6)]),
                   plan=PLAN)
    over = run("ux.obstructed-exit", session(flows=[join, flow("leave", "cancel-subscription", steps=5, interactions=6)]),
               plan=PLAN)
    assert at_bound.hits == [] and at_bound.skipped is None
    assert len(over.hits) == 1 and over.hits[0].location["flow"] == "leave"


def test_obstructed_exit_marks_exits_that_need_contact_with_the_business():
    phone = flow("leave", "cancel-subscription", effort={"channel": "phone"})
    blocked = flow("leave", "cancel-subscription", status="blocked", context="d")
    result = run("ux.obstructed-exit", session(flows=[phone, blocked]))
    assert [h.conditions for h in result.hits] == [
        {"leaving cannot be finished without contacting the business"}, frozenset()]


def test_obstructed_exit_without_a_pair_run_is_not_verified():
    result = run("ux.obstructed-exit", session(flows=[flow("leave", "cancel-subscription", steps=9)]), plan=PLAN)
    assert result.hits == [] and "pair" in result.skipped
    skipped = run("ux.obstructed-exit", session(flows=[flow("leave", "cancel-subscription", status="skipped")]))
    assert skipped.hits == [] and "skipped" in skipped.skipped


def test_forced_action_hits_listed_gates_that_are_neither_skippable_nor_declared():
    gates = [{"step": 1, "kind": "account", "skippable": False, "declared": False, "box": A},
             {"step": 1, "kind": "survey", "skippable": True, "declared": False, "box": B},
             {"step": 2, "kind": "address", "skippable": False, "declared": True, "box": C},
             {"step": 2, "kind": "install", "skippable": False, "declared": False, "box": D}]
    assert hit_boxes(run("ux.forced-action", session(flows=[flow("buy", "purchase", gates=gates)]))) == [A, D]


def test_forced_action_reads_declared_prerequisites_from_the_plan():
    gates = [{"step": 1, "kind": "account", "skippable": False, "declared": False, "box": A}]
    plan = copy.deepcopy(PLAN)
    plan["flows"][2].update(requires=["account"], requires_reason="orders are kept on the account page")
    assert run("ux.forced-action", session(flows=[flow("buy", "purchase", gates=gates)]), plan=plan).hits == []


def test_dead_end_hits_steps_with_no_way_on():
    steps = [{"index": 0, "path": "/"}, {"index": 1, "path": "/error", "dead_end": True, "main": A}]
    result = run("ux.dead-end", session(flows=[flow("buy", "purchase", status="dead-end", step_list=steps)]))
    assert [h.location["step"] for h in result.hits] == [1]


def test_excess_steps_against_the_plan_and_single_field_runs():
    at_bound = flow("buy", "purchase", steps=3, effort={"single_field_steps": 1})
    over = flow("join", "subscribe", steps=4, effort={"single_field_steps": 2})
    assert run("ux.excess-steps", session(flows=[at_bound]), plan=PLAN).hits == []
    assert len(run("ux.excess-steps", session(flows=[over]), plan=PLAN).hits) == 2
    no_plan = run("ux.excess-steps", session(flows=[at_bound]))
    assert no_plan.hits == [] and "no plan" in no_plan.skipped


def test_no_review_before_commit_unless_an_undo_restores():
    prices = [{"step": 1, "currency": "USD", "components": [comp("mug", "item", 20, placement="primary")]}]
    run_ = flow("buy", "purchase", prices=prices, commit_step=1, review_before_commit=False)
    assert len(run("ux.no-review-before-commit", session(flows=[run_])).hits) == 1
    undo = {"box": A, "context": "m", "flow": "buy", "kind": "purchase",
            "undo": {"offered": True, "restores": True, "survives_reload": True}}
    assert run("ux.no-review-before-commit", session({"commits": [undo]}, flows=[run_])).hits == []
    reviewed = flow("buy", "purchase", prices=prices, commit_step=1, review_before_commit=True)
    assert run("ux.no-review-before-commit", session(flows=[reviewed])).hits == []


def test_flow_observations_whose_hints_disagree_are_not_verified():
    # A hint the page reading does not confirm never decides a verdict, pass or fail: the detector
    # reports the observation as not verified and judges the others as usual.
    gates = [{"step": 1, "kind": "account", "skippable": False, "declared": False, "box": A,
              "hint_mismatch": ["skippable"]},
             {"step": 2, "kind": "install", "skippable": False, "declared": False, "box": D}]
    forced = run("ux.forced-action", session(flows=[flow("buy", "purchase", gates=gates)]))
    assert hit_boxes(forced) == [D] and "account" in forced.skipped and "not verified" in forced.skipped
    prices = [{"step": 0, "currency": "USD", "components": [comp("mug", "item", 20, placement="primary")]},
              {"step": 2, "currency": "USD", "components": [comp("mug", "item", 20), comp("service", "fee", 3),
                                                            comp("gift", "fee", 2, hint_mismatch=["kind"])]}]
    drip = run("ux.drip-pricing", session(flows=[flow("buy", "purchase", prices=prices)]))
    assert [h.observed for h in drip.hits] == ["purchase flow buy: charges service appear or rise after the first price"]
    assert "gift" in drip.skipped and "not verified" in drip.skipped
    cart = [{"step": 1, "lines": [{"key": "insurance", "added_by": "system", "amount": 2, "hint_mismatch": ["added_by"]}]}]
    sneak = run("ux.sneak-into-basket", session(flows=[flow("buy", "purchase", cart=cart)]))
    assert sneak.hits == [] and "insurance" in sneak.skipped
    recurring = [{"step": 2, "currency": "USD", "components": [comp("box", "recurring", 12, cadence="month")]}]
    shown = [{"kind": "renewal-price", "placement": "near-commit", "step": 2, "at_commit": True, "hint_mismatch": ["kind"]},
             {"kind": "cadence", "placement": "near-commit", "step": 2, "at_commit": True}]
    terms = run("ux.hidden-subscription", session(flows=[flow("join", "subscribe", prices=recurring, commit_step=2,
                                                             disclosures=shown)]))
    assert [h.observed for h in terms.hits] == [
        "subscribe flow join: recurring terms not readable at the commit: cancellation-method"]
    assert "renewal-price" in terms.skipped
    steps = [{"index": 0, "path": "/", "offers": [{"box": A, "kind": "retention", "blocks": False,
                                                   "hint_mismatch": ["blocks"]}]}]
    leave = flow("leave", "cancel-subscription", step_list=steps, effort={"offers": 1, "blocking_offers": 0})
    exit_ = run("ux.obstructed-exit", session(flows=[leave]))
    assert exit_.hits == [] and "blocking offers" in exit_.skipped


# ---------------------------------------------------------------- forms and commits

def form(fields=(), purpose="checkout", **kw):
    return {"box": F, "context": "m", "purpose": purpose, "fields": list(fields), **kw}


def test_lost_input_hits_cleared_fields_and_unexplained_cleared_secrets():
    doc = session({"forms": [
        form(preservation=[{"after": "server-error", "kept": 1, "cleared": 2}]),
        form(preservation=[{"after": "invalid-submit", "kept": 3, "cleared": 0, "cleared_sensitive": 1, "explained": False}]),
        form(preservation=[{"after": "back", "kept": 3, "cleared": 0, "cleared_sensitive": 1, "explained": True}]),
    ]})
    assert len(run("ux.lost-input", doc).hits) == 2


def test_premature_validation():
    doc = session({"forms": [form(validation={"first_error": "keystroke"}), form(validation={"first_error": "blur"}),
                             form(validation={"first_error": "submit", "untouched_invalid_on_load": True})]})
    assert len(run("ux.premature-validation", doc).hits) == 2


def test_error_identification():
    fine = {"errors": 1, "described_in_text": True, "associated": True, "color_only": False,
            "focus_to": "first-error", "announced": True}
    doc = session({"forms": [form(invalid_submit={**fine, "color_only": True}),
                             form(invalid_submit={**fine, "associated": False}),
                             form(invalid_submit={**fine, "announced": False, "focus_to": "submit"}),
                             form(invalid_submit={**fine, "announced": False}),
                             form(invalid_submit=fine)]})
    assert len(run("ux.input-error-unidentified", doc).hits) == 3
    result = run("ux.input-error-unidentified", session({"forms": [form()]}))
    assert result.hits == [] and "invalid submit" in result.skipped


def test_disabled_submit_without_a_visible_reason():
    doc = session({"forms": [form(submit={"box": A, "disabled_until_valid": True, "reason_visible": False}),
                             form(submit={"box": B, "disabled_until_valid": True, "reason_visible": True})]})
    assert hit_boxes(run("ux.disabled-submit-unexplained", doc)) == [A]


def test_redundant_entry_spares_prefilled_offered_and_secret_repeats():
    doc = session({"forms": [form([
        {"box": A, "kind": "text"},
        {"box": B, "kind": "text", "repeats": A},
        {"box": C, "kind": "text", "repeats": A, "prefilled": True},
        {"box": D, "kind": "text", "repeats": A, "same_as_offered": True},
        {"box": E, "kind": "password", "repeats": box(40), "sensitive": True}])]})
    assert hit_boxes(run("ux.redundant-entry", doc)) == [B]


def test_inaccessible_auth():
    doc = session({"forms": [
        form([{"box": A, "kind": "password", "paste_blocked": True}, {"box": B, "kind": "email", "paste_blocked": True}],
             purpose="sign-in", auth={"cognitive_test": "puzzle", "alternative": False}),
        form(purpose="sign-in", auth={"cognitive_test": "memory", "alternative": True}),
        form(purpose="sign-in", auth={"cognitive_test": "object-recognition", "alternative": False}),
    ]})
    assert hit_boxes(run("ux.inaccessible-auth", doc)) == [F, A]


def commit(b, kind="purchase", **kw):
    return {"box": b, "context": "m", "kind": kind, **kw}


def outcome(injected, claimed, actual, **kw):
    return {"injected": injected, "claimed": claimed, "actual": actual, **kw}


def test_duplicate_submit_counts_effects_of_one_intended_commit():
    doc = session({
        "commits": [commit(A, double_activation={"requests": 2, "effects": 2}),
                    commit(B, double_activation={"requests": 1, "effects": 1},
                           outcomes=[outcome("none", "success", "applied")]),
                    commit(C, outcomes=[outcome("hang", "unknown", "applied", retry_offered=True, retry_effects=1)]),
                    commit(D, outcomes=[outcome("fail-5xx", "failure", "not-applied", auto_resent=True)])],
        "history": [{"context": "m", "action": "reload", "from": "/thanks", "resubmit_prompt": True}],
    })
    result = run("ux.duplicate-submit", doc)
    assert hit_boxes(result) == [A, C, None]
    assert result.hits[2].location["path"] == "/thanks"


def test_false_status_compares_the_claim_with_the_backend():
    doc = session({"commits": [
        commit(A, outcomes=[outcome("fail-5xx", "success", "not-applied")]),
        commit(B, outcomes=[outcome("hang", "failure", "applied")]),
        commit(C, outcomes=[outcome("none", "success", "applied"), outcome("hang", "unknown", "applied")]),
    ]})
    assert hit_boxes(run("ux.false-status", doc)) == [A, B]


def test_destructive_without_undo():
    doc = session({"commits": [
        commit(A, "delete", destructive=True, confirm={"shown": False}),
        commit(B, "delete", destructive=True, confirm={"shown": True, "names_object": True}),
        commit(C, "delete", destructive=True, undo={"offered": True, "restores": True, "survives_reload": False}),
        commit(D, "delete", destructive=True, undo={"offered": True, "restores": True, "survives_reload": True}),
        commit(E, "save", destructive=False),
    ]})
    assert hit_boxes(run("ux.destructive-without-undo", doc)) == [A, C]


def test_status_not_announced_from_controls_commits_and_states():
    doc = session({
        "controls": [control(A, "submit", {"outcome": "state-changed", "text_changed": [D], "status_changed": [D]}),
                     control(B, "submit", {"outcome": "state-changed", "text_changed": [D], "status_changed": [D],
                                           "announcements": [{"channel": "live-polite", "box": D}]})],
        "commits": [commit(C, outcomes=[outcome("none", "success", "applied", announced=False)]),
                    commit(E, outcomes=[outcome("none", "none", "applied", announced=False)])],
        "states": [state("success", on_action=True, announced=False, surface=F),
                   state("empty", on_action=False, announced=False)],
    })
    assert hit_boxes(run("ux.status-not-announced", doc)) == [A, C, F]


# ---------------------------------------------------------------- time, history, input, media

def reading(when, value, elapsed_ms, **kw):
    return {"when": when, "value": value, "elapsed_ms": elapsed_ms, **kw}


def urgency(b, kind, readings, **kw):
    return {"box": b, "context": "m", "kind": kind, "readings": readings, **kw}


def test_false_urgency():
    doc = session({"urgency": [
        urgency(A, "countdown", [reading("load", 600, 0, resolution_s=1), reading("reload", 600, 130000, resolution_s=1)],
                backed=True),
        urgency(B, "stock", [reading("load", 3, 0), reading("reload", 2, 130000)], backed=True),
        urgency(C, "hold", [reading("load", 600, 0)], at_expiry="restarts", backed=True),
        urgency(D, "countdown", [reading("load", 600, 0)], at_expiry="unchanged", backed=True),
        urgency(E, "demand", [reading("load", 12, 0), reading("later", 12, 60000)], backed=False),
        urgency(F, "demand", [reading("load", 12, 0), reading("later", 12, 60000)], backed=True),
    ]})
    assert hit_boxes(run("ux.false-urgency", doc)) == [A, B, D, E]


def limit(limit_s=900, warned=True, extendable=True, **kw):
    return {"context": "m", "kind": "session", "limit_s": limit_s, "warned": warned, "extendable": extendable, **kw}


@pytest.mark.parametrize("probe, fires", [
    (limit(warned=False, extendable=False), True),
    (limit(warn_lead_s=20, extensions=10), False),
    (limit(warn_lead_s=19, extensions=10), True),
    (limit(warn_lead_s=20, extensions=9), True),
    (limit(warned=False, extendable=False, turn_off=True), False),
    (limit(limit_s=72001, warned=False, extendable=False), False),
    (limit(limit_s=72000, warned=False, extendable=False), True),
])
def test_timeout_without_warning(probe, fires):
    assert bool(run("ux.timeout-without-warning", session({"time_limits": [probe]})).hits) is fires


def test_timeout_without_a_measured_warning_lead_is_not_verified():
    result = run("ux.timeout-without-warning", session({"time_limits": [limit(extensions=10)]}))
    assert result.hits == [] and "warning lead" in result.skipped


def back(**kw):
    return {"context": "m", "action": "back", "from": "/", **kw}


@pytest.mark.parametrize("probe, fires", [
    (back(presses=3, left_page=False, pushed_entries=4), True),
    (back(presses=1, left_page=True), False),
    (back(presses=2, left_page=True), True),
    (back(presses=2, left_page=True, overlay_closed_first=True, overlay_opened_by="user"), False),
    (back(presses=2, left_page=True, overlay_closed_first=True, overlay_opened_by="page"), True),
])
def test_back_trap(probe, fires):
    assert bool(run("ux.back-trap", session({"history": [probe]})).hits) is fires


def test_lost_context_on_return_and_deep_links():
    doc = session({"history": [
        {"context": "m", "action": "back", "from": "/works/:id", "to": "/works",
         "restored": {"filters": True, "scroll": False}},
        {"context": "m", "action": "back", "from": "/works/:id", "to": "/works", "restored": {"filters": True}},
        {"context": "m", "action": "deep-link-after-sign-in", "from": "/orders/:id", "landed": "home"},
        {"context": "m", "action": "deep-link-after-sign-in", "from": "/orders/:id", "landed": "target"},
    ]})
    result = run("ux.lost-context-on-return", doc)
    assert [h.location["path"] for h in result.hits] == ["/works/:id", "/orders/:id"]


def test_gesture_only_and_hover_content():
    doc = session({"pointer": [
        {"box": A, "context": "d", "kind": "drag", "alternative": "none"},
        {"box": B, "context": "d", "kind": "path-gesture", "alternative": "keyboard-only"},
        {"box": C, "context": "d", "kind": "drag", "alternative": "buttons"},
        {"box": D, "context": "d", "kind": "hover-reveal", "on_focus_too": False, "hoverable": True, "persistent": True},
        {"box": E, "context": "d", "kind": "hover-reveal", "on_focus_too": True, "hoverable": True, "persistent": True,
         "obscures": True, "dismissible": False},
        {"box": F, "context": "d", "kind": "hover-reveal", "on_focus_too": True, "hoverable": True, "persistent": True,
         "obscures": True, "dismissible": True},
    ]})
    assert hit_boxes(run("ux.gesture-only", doc)) == [A, B]
    assert hit_boxes(run("ux.hover-content", doc)) == [D, E]


@pytest.mark.parametrize("actual, extra, fires", [
    (150, {}, False), (147, {}, True), (600, {}, False), (603, {}, True),
    (300, {"snapped": True}, True), (0, {"blocked": True}, True),
])
def test_scroll_hijack_ratio_bounds(actual, extra, fires):
    probe = {"context": "d", "input": "wheel", "expected_px": 300, "actual_px": actual, **extra}
    assert bool(run("ux.scroll-hijack", session({"scroll": [probe]})).hits) is fires


def test_permission_on_load_hits_listed_apis_without_a_gesture():
    doc = session({"permissions": [
        {"context": "m", "api": "notifications", "user_gesture": False, "t_ms": 1200},
        {"context": "m", "api": "notifications", "user_gesture": False, "t_ms": 9000},
        {"context": "m", "api": "camera", "user_gesture": True},
        {"context": "m", "api": "clipboard-read", "user_gesture": False},
    ]})
    result = run("ux.permission-on-load", doc)
    assert len(result.hits) == 1 and "notifications" in result.hits[0].observed


@pytest.mark.parametrize("probe, fires", [
    ({"autoplay": True, "audible": True, "audible_s": 3, "controls": False}, False),
    ({"autoplay": True, "audible": True, "audible_s": 3.5, "controls": False}, True),
    ({"autoplay": True, "audible": True, "audible_s": 10, "controls": True}, False),
    ({"autoplay": True, "audible": False, "audible_s": 0}, False),
    ({"autoplay": False, "audible": True, "audible_s": 10, "controls": False}, False),
])
def test_autoplay_audio(probe, fires):
    doc = session({"media": [{"box": A, "context": "d", **probe}]})
    assert bool(run("ux.autoplay-audio", doc).hits) is fires


def test_autoplay_audio_without_a_duration_is_not_verified():
    result = run("ux.autoplay-audio", session({"media": [{"box": A, "context": "d", "autoplay": True, "audible": True}]}))
    assert result.hits == [] and "not recorded" in result.skipped
