"""The derived values in behavior/DERIVED.md, pinned with small cases."""
import numpy as np

from lapis_design.behavior import (bypass, choice_derived, flow_derived, focus_visible, matches_promise,
                                   order_inversions, outcome, reasks_after_decline, repeated_stops, scroll_ratio,
                                   skip_link_broken, urgency_derived)


def test_outcome_order():
    assert outcome({"navigation": "document", "dialog_opened": "b000000000001"}) == "navigated"
    assert outcome({"dialog_opened": "b000000000001", "requests": [{}]}) == "dialog"
    assert outcome({"dom_mutations": 40}) == "no-effect"                 # cosmetic mutations alone
    assert outcome({"dom_mutations": 40, "console_errors": 2}) == "error"
    assert outcome({"text_changed": ["b000000000001"], "console_errors": 2}) == "state-changed"
    assert outcome({"requests": [{}]}) == "data-requested"
    assert outcome({"scroll_y_delta": -900}) == "moved"                  # back to top
    assert outcome({"focus_to": "b000000000002"}, "b000000000001") == "moved"
    assert outcome({"focus_to": "b000000000001"}, "b000000000001") == "no-effect"
    assert outcome({"requests": [{"kind": "beacon"}, {"kind": "fetch", "blocked": True}]}) == "no-effect"
    # another box visibly grew or moved: the control did something, even without text or ARIA changes
    assert outcome({"layout_animated": ["b000000000002"]}, "b000000000001") == "state-changed"
    assert outcome({"shift_sources": ["b000000000002"], "layout_shift": 0.02}, "b000000000001") == "state-changed"
    assert outcome({"shift_sources": ["b000000000001"], "layout_shift": 0.02}, "b000000000001") == "no-effect"
    # another box changed size with no animation at all (an instant or sub-50 ms expansion)
    assert outcome({"resized": ["b000000000002"]}, "b000000000001") == "state-changed"
    assert outcome({"resized": ["b000000000001"]}, "b000000000001") == "no-effect"   # only the control itself


def test_promises():
    assert matches_promise("toggle", "state-changed")
    assert not matches_promise("toggle", "navigated")
    assert not matches_promise("other", "no-effect")
    assert matches_promise("other", "dialog")
    assert matches_promise("destructive", "navigated")                  # a cancel link to its page
    assert matches_promise("navigate", "moved")                         # an in-page anchor


def test_focus_visible_needs_a_line_of_contrasting_pixels():
    rect = {"x": 0, "y": 0, "w": 100, "h": 40}                          # a 2 px line along the width: 200
    assert focus_visible({"area_px": 200, "contrast": 3.0, "contrast_area_px": 200}, rect)   # a 2 px underline
    assert not focus_visible({"area_px": 100, "contrast": 5.0, "contrast_area_px": 100}, rect)   # 1 px underline
    assert not focus_visible({"area_px": 900, "contrast": 2.9, "contrast_area_px": 199}, rect)
    # a two-tone ring: its light half lowers the median, its dark half still draws the line
    assert focus_visible({"area_px": 400, "contrast": 1.7, "contrast_area_px": 200}, rect)
    assert focus_visible(None, rect) is None                            # not measured: no verdict


def test_indicator_counts_the_pixels_that_reach_three_to_one():
    from lapis_design.behavior_check.probes.keyboard import _indicator
    before = np.full((56, 116, 3), 255, np.uint8)                       # a 100 x 40 box inflated by 8 px, white
    after = before.copy()
    after[4:6, 4:112] = after[50:52, 4:112] = 16                        # dark outer ring, 2 px
    after[6:8, 6:110] = after[48:50, 6:110] = 200                       # light inner ring, wider share
    after[6:50, 4:6] = 200
    region = {"inside": True, "x": 0, "y": 0, "w": 116, "h": 56, "vw": 116}
    measured = _indicator(before, after, region)
    assert measured["contrast"] < 3 and measured["contrast_area_px"] == 432     # 2 x 108 px x 2 dark rows
    assert focus_visible(measured, {"x": 8, "y": 8, "w": 100, "h": 40})


def _stop(i, box, x, y, w=80, h=30, dialog=None):
    s = {"box": box, "index": i, "rect": {"x": x, "y": y, "w": w, "h": h}}
    if dialog:
        s["in_dialog"] = dialog
    return s


def test_order_inversions():
    a, b, c, d = "b00000000000a", "b00000000000b", "b00000000000c", "b00000000000d"
    forward = [_stop(0, a, 0, 0), _stop(1, b, 200, 0), _stop(2, c, 0, 100)]
    assert order_inversions(forward) == (0, [])
    left_in_row = [_stop(0, a, 200, 0), _stop(1, b, 0, 5)]
    assert order_inversions(left_in_row) == (1, [[a, b]])
    up = [_stop(0, a, 0, 300), _stop(1, b, 0, 100)]
    assert order_inversions(up)[0] == 1
    into_dialog = [_stop(0, a, 0, 300), _stop(1, d, 0, 100, dialog="b0000000000ff")]
    assert order_inversions(into_dialog)[0] == 0
    assert order_inversions(left_in_row, rtl=True)[0] == 0              # right to left reads the other way


def _rect(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def test_order_inversions_follow_containers():
    grid, c1, c2, c3 = "b0000000000g0", "b0000000000c1", "b0000000000c2", "b0000000000c3"
    containers = {grid: {"parent": None, "rect": _rect(0, 0, 900, 400)},
                  c1: {"parent": grid, "rect": _rect(0, 0, 280, 400)},
                  c2: {"parent": grid, "rect": _rect(300, 0, 280, 400)},
                  c3: {"parent": grid, "rect": _rect(600, 0, 280, 400)}}
    cards = []
    for n, card in enumerate([c1, c2, c3]):                           # title at the top, button at the bottom
        x = containers[card]["rect"]["x"]
        cards.append({"box": f"b00000000{n}t0", "index": 2 * n, "rect": _rect(x, 10, 200, 30), "container": card})
        cards.append({"box": f"b00000000{n}b0", "index": 2 * n + 1, "rect": _rect(x, 350, 200, 40), "container": card})
    assert order_inversions(cards, containers)[0] == 0                 # card by card is in order
    assert order_inversions(cards)[0] == 2                              # without containers every jump up counts
    main, side = "b0000000000m0", "b0000000000s0"
    page = {main: {"parent": None, "rect": _rect(0, 0, 900, 3000)}, side: {"parent": None, "rect": _rect(920, 0, 300, 800)}}
    walk = [{"box": "b0000000000m1", "index": 0, "rect": _rect(0, 2900, 200, 30), "container": main},
            {"box": "b0000000000s1", "index": 1, "rect": _rect(920, 10, 200, 30), "container": side}]
    assert order_inversions(walk, page)[0] == 0                         # main column, then the sidebar
    back = [walk[1] | {"index": 0}, walk[0] | {"index": 1}]
    assert order_inversions(back, page)[0] == 1                         # the sidebar first is out of order


def test_reasks_after_decline():
    seq = [{"preceded_by": "none", "response": "decline"}, {"preceded_by": "control", "response": "accept"},
           {"preceded_by": "reload", "response": "dismiss"}]
    assert reasks_after_decline(seq) == 1
    assert reasks_after_decline([{"preceded_by": "none", "response": "accept"},
                                 {"preceded_by": "reload", "response": "none"}]) == 0
    assert reasks_after_decline([{"preceded_by": "none", "response": "later"},
                                 {"preceded_by": "navigation", "response": "later"}]) == 1


def _opt(kind, area, filled, contrast, layer=1, interactions=1, bordered=False):
    return {"kind": kind, "control": "button", "layer": layer, "interactions": interactions,
            "visual": {"area_px": area, "filled": filled, "bordered": bordered, "contrast": contrast}}


def test_choice_prominence_and_decline_effort():
    link_vs_button = {"options": [_opt("accept", 16952, True, 8.1, interactions=2), _opt("decline", 1280, False, 3.2)]}
    assert choice_derived(link_vs_button) == {"decline_found": True, "prominence_ratio": 57.94,
                                              "decline_extra_interactions": -1}
    buried = {"options": [_opt("accept", 10000, True, 7), _opt("customize", 2000, False, 7),
                          _opt("decline", 4000, False, 7, layer=2, interactions=3)]}
    assert choice_derived(buried) == {"decline_found": True, "prominence_ratio": 10.0, "decline_extra_interactions": 2}
    outline = {"options": [_opt("accept", 10000, True, 7), _opt("decline", 10000, False, 7, bordered=True)]}
    assert choice_derived(outline)["prominence_ratio"] == 1.33          # filled against outlined is ordinary
    no_decline = {"options": [_opt("accept", 10000, True, 7), _opt("dismiss", 400, False, 7)]}
    assert choice_derived(no_decline) == {"decline_found": False}
    assert choice_derived({"options": [_opt("neutral", 1, False, 7), _opt("neutral", 1, False, 7)]}) is None
    invisible = {"options": [_opt("accept", 10000, True, 7), _opt("decline", 0, False, 7)]}
    assert choice_derived(invisible)["prominence_ratio"] == 1000.0
    close_only = {"options": [_opt("accept", 10000, True, 7), dict(_opt("decline", 576, False, 7), control="icon")]}
    assert "prominence_ratio" not in choice_derived(close_only)        # an icon close is not weighed against a button


def test_leaving_an_add_on_unchecked_is_a_decline():
    add_on = {"options": [_opt("accept", 900, False, 7), {"kind": "decline", "control": "checkbox", "layer": 1,
                                                          "interactions": 0}]}
    assert choice_derived(add_on) == {"decline_found": True, "decline_extra_interactions": -1}


def test_urgency():
    reset = {"kind": "countdown", "readings": [{"when": "load", "value": 600, "elapsed_ms": 0},
                                               {"when": "reload", "value": 600, "elapsed_ms": 60000}]}
    assert urgency_derived(reset) == {"resets": True, "drifts": False}
    honest = {"kind": "countdown", "readings": [{"when": "load", "value": 600, "elapsed_ms": 0},
                                                {"when": "reload", "value": 541, "elapsed_ms": 60000}]}
    assert urgency_derived(honest)["resets"] is False
    stock = {"kind": "stock", "readings": [{"when": "load", "value": 3, "elapsed_ms": 0},
                                           {"when": "reload", "value": 2, "elapsed_ms": 5000}]}
    assert urgency_derived(stock) == {"resets": False, "drifts": True}
    days = {"kind": "countdown", "readings": [{"when": "load", "value": 172800, "resolution_s": 86400, "elapsed_ms": 0},
                                              {"when": "later", "value": 172800, "resolution_s": 86400, "elapsed_ms": 60000}]}
    assert urgency_derived(days)["resets"] is False                     # "2 days left" a minute later
    hold = {"kind": "hold", "readings": [{"when": "load", "value": 600, "elapsed_ms": 0},
                                         {"when": "reload", "value": 600, "elapsed_ms": 60000}]}
    assert urgency_derived(hold)["resets"] is False


def test_scroll_ratio():
    assert scroll_ratio({"expected_px": 300, "actual_px": 900}) == 3.0
    assert scroll_ratio({"expected_px": 0, "actual_px": 0}) is None


def _c(key, kind, state="known", amount=None, mandatory=True, user_caused=False, cadence=None, placement=None):
    c = {"key": key, "kind": kind, "state": state, "mandatory": mandatory, "user_caused": user_caused}
    if amount is not None:
        c["amount"] = amount
    if cadence:
        c["cadence"] = cadence
    if placement:
        c["placement"] = placement
    return c


def _run(prices, **kw):
    return {"id": "f", "context": "m", "kind": kw.pop("kind", "purchase"), "status": "completed", "steps": [],
            "effort": kw.pop("effort", {"steps": 1, "interactions": 1}), "prices": prices, **kw}


def _p(step, *components):
    return {"step": step, "currency": "USD", "components": list(components)}


def test_drip_pricing():
    item = _c("item", "item", amount=100)
    disclosed = [_p(0, item, _c("ship", "shipping", state="pending")),
                 _p(2, item, _c("ship", "shipping", amount=9, user_caused=True)),
                 _p(3, item, _c("ship", "shipping", amount=9))]
    assert flow_derived(_run(disclosed))["drip"] == []
    never_settled = [_p(0, item, _c("svc", "fee", state="pending")), _p(3, item, _c("svc", "fee", amount=4))]
    assert flow_derived(_run(never_settled))["drip"] == ["svc"]         # "calculated at checkout" with no input
    tucked = [_p(0, item, _c("svc", "fee", amount=4, placement="tooltip")), _p(2, item, _c("svc", "fee", amount=4))]
    assert flow_derived(_run(tucked))["drip"] == ["svc"]
    estimate = [_p(0, item, _c("ship", "shipping", state="estimated", amount=5)), _p(2, item, _c("ship", "shipping", amount=50))]
    assert flow_derived(_run(estimate))["drip"] == ["ship"]
    later_rise = [_p(0, item, _c("ship", "shipping", state="pending")),
                  _p(1, item, _c("ship", "shipping", amount=5, user_caused=True)),
                  _p(3, item, _c("ship", "shipping", amount=25))]
    assert flow_derived(_run(later_rise))["drip"] == ["ship"]
    bait = [_p(0, item, _c("promo", "discount", amount=-20)), _p(2, _c("item", "item", amount=100), _c("total", "total", amount=100))]
    assert flow_derived(_run(bait))["drip"] == ["promo"]
    item_rise = [_p(0, item), _p(2, _c("item", "item", amount=120, mandatory=False))]
    assert flow_derived(_run(item_rise))["drip"] == ["item"]
    address_then_tax = [_p(0, item, _c("tax", "tax", state="pending")), _p(1, item, _c("tax", "tax", state="pending")),
                        _p(2, item, _c("tax", "tax", amount=8, user_caused=True))]  # entered on step 1, shown on step 2
    assert flow_derived(_run(address_then_tax))["drip"] == []
    back_to_known = [_p(0, item, _c("ship", "shipping", amount=5)), _p(1, item, _c("ship", "shipping", state="pending")),
                     _p(2, item, _c("ship", "shipping", amount=5))]
    assert flow_derived(_run(back_to_known))["drip"] == []
    total_only = [_p(0, item, _c("total", "total", amount=100)), _p(2, _c("total", "total", amount=112))]
    assert flow_derived(_run(total_only))["drip"] == ["total"]
    open_at_commit = [_p(0, item, _c("svc", "fee", state="pending")), _p(2, item, _c("svc", "fee", state="pending"))]
    assert flow_derived(_run(open_at_commit, commit_step=2))["drip"] == ["svc"]
    currency = [_p(0, item), {"step": 2, "currency": "KRW", "components": [_c("item", "item", amount=130000)]}]
    assert flow_derived(_run(currency))["drip"] == []
    late_fee = [{"step": 0, "currency": "USD", "components": [item]},
                {"step": 2, "currency": "USD", "components": [item, _c("svc", "fee", amount=4)]}]
    assert flow_derived(_run(late_fee))["drip"] == ["svc"]
    rising = [{"step": 0, "currency": "USD", "components": [item, _c("svc", "fee", amount=2)]},
              {"step": 2, "currency": "USD", "components": [item, _c("svc", "fee", amount=4)]}]
    assert flow_derived(_run(rising))["drip"] == ["svc"]
    chosen = [{"step": 0, "currency": "USD", "components": [item]},
              {"step": 1, "currency": "USD", "components": [item, _c("express", "shipping", amount=15, user_caused=True)]}]
    assert flow_derived(_run(chosen))["drip"] == []


def test_sneaked_lines():
    run = _run([], cart=[{"step": 1, "lines": [{"key": "mug", "added_by": "user", "amount": 30},
                                                {"key": "insurance", "added_by": "system", "amount": 4},
                                                {"key": "gift-note", "added_by": "system", "amount": 0}]}])
    assert flow_derived(run)["sneaked"] == ["insurance"]                # a free line is not a charge


def test_hidden_subscription_terms():
    monthly = [{"step": 0, "currency": "USD", "components": [_c("plan", "item", amount=0),
                                                            _c("renewal", "recurring", amount=24, cadence="month")]}]
    shown = [{"kind": "renewal-price", "step": 0, "placement": "near-commit", "at_commit": True},
             {"kind": "cadence", "step": 0, "placement": "near-commit", "at_commit": True},
             {"kind": "cancellation-method", "step": 0, "placement": "secondary", "at_commit": False}]
    assert flow_derived(_run(monthly, commit_step=0, disclosures=shown))["hidden_terms"] == []
    assert flow_derived(_run(monthly, commit_step=0, disclosures=shown, trial=True))["hidden_terms"] == \
        ["trial-conversion", "trial-end"]
    tucked = [dict(shown[0], placement="collapsed", at_commit=False)] + shown[1:]
    assert flow_derived(_run(monthly, commit_step=0, disclosures=tucked))["hidden_terms"] == ["renewal-price"]
    twice = shown + [dict(shown[0], placement="collapsed", at_commit=False)]      # entry order does not matter
    assert flow_derived(_run(monthly, commit_step=0, disclosures=twice))["hidden_terms"] == []
    optional = shown + [{"kind": "cancellation-terms", "step": 0, "placement": "collapsed", "at_commit": False}]
    assert flow_derived(_run(monthly, commit_step=0, disclosures=optional))["hidden_terms"] == []
    assert flow_derived(_run([{"step": 0, "currency": "USD", "components": [_c("mug", "item", amount=30)]}]))["hidden_terms"] == []


def test_exit_effort_against_the_pair():
    join = _run([], kind="subscribe", effort={"steps": 2, "interactions": 4, "reauth": False})
    join["id"] = "join"
    leave = _run([], kind="cancel-subscription", effort={"steps": 6, "interactions": 11, "reauth": True})
    assert flow_derived(leave, join)["exit"] == {"pair": "join", "extra_steps": 4, "extra_interactions": 7,
                                                 "added_reauth": True}
    assert flow_derived(leave, join, {"requires": ["reauth"]})["exit"]["added_reauth"] is False
    assert "exit" not in flow_derived(leave)
    for status in ("blocked", "dead-end", "abandoned", "skipped"):
        assert "exit" not in flow_derived(leave, dict(join, status=status))      # no completed pair: skipped


def test_rtl_contexts_mirror_reading_order():
    from lapis_design.behavior import derive_session
    a, b = "b00000000000a", "b00000000000b"
    session = {"contexts": [{"id": "r", "dir": "rtl"}], "nodes": {},
               "probes": {"keyboard": [{"context": "r", "path": "/", "completed": True,
                                        "stops": [_stop(0, a, 200, 0), _stop(1, b, 0, 5)]}]}}
    assert derive_session(session)["probes"]["keyboard"][0]["derived"]["order_inversions"] == 0


def _walk(path, boxes, context="d", names=None, nearest=None, in_main=None, **extra):
    stops = []
    for i, b in enumerate(boxes):
        stop = {"box": b, "index": i}
        if names:
            stop["name"] = names[i]
        if nearest:
            stop["landmark"] = nearest[i]
        if in_main:
            stop["in_main"] = in_main[i]
        stops.append(stop)
    return {"context": context, "path": path, "stops": stops, **extra}


HEADER = ["b1", "b2", "b3", "b4"]


def test_repeated_stops_compare_routes_in_one_context():
    home = _walk("/", HEADER + ["b5"])
    detail = _walk("/works/12", HEADER + ["b9"])
    other_ctx = _walk("/about", HEADER, context="m")
    walks = [home, detail, other_ctx]
    assert repeated_stops(home, walks) == 4
    assert repeated_stops(other_ctx, walks) is None                     # no second route in m
    assert repeated_stops(home, [home, _walk("/", ["b1"])]) is None       # same route twice


def test_a_shared_template_does_not_extend_the_block_into_content():
    names = ["skip", "works", "log", "guide", "reserve"]
    a = _walk("/works/12", HEADER + ["b5"], names=names, headings=[{"box": "h", "level": 1, "next_stop": 4}])
    b = _walk("/works/13", HEADER + ["b5"], names=names)
    assert repeated_stops(a, [a, b]) == 4                               # cut at the h1 after the header
    marked = _walk("/works/12", HEADER + ["b5"], names=names, nearest=["banner"] * 4 + ["main"],
                   in_main=[False] * 4 + [True])
    assert repeated_stops(marked, [marked, b]) == 4                     # cut at the first stop in main
    search = _walk("/works/12", HEADER + ["s1", "s2", "b5"], nearest=["banner"] * 4 + ["search"] * 2 + ["main"],
                   in_main=[False] * 4 + [True] * 3)
    peer = _walk("/works/13", HEADER + ["s1", "s2", "b9"])
    assert repeated_stops(search, [search, peer]) == 4                  # a search form opening main is content
    renamed = _walk("/works/13", HEADER + ["b5"], names=names[:4] + ["reserve 13"])
    plain = _walk("/works/12", HEADER + ["b5"], names=names)
    assert repeated_stops(plain, [plain, renamed]) == 4                 # names tell the cards apart


def test_bypass_mechanisms():
    walk = _walk("/", HEADER + ["b5"], skip_link={"present": True, "index": 0, "lands_at": None},
                 landmarks={"main": False}, headings=[{"box": "bh", "level": 2, "next_stop": 1}])
    assert bypass(walk, 4) == [] and skip_link_broken(walk)              # heading inside the block
    walk["headings"].append({"box": "bh1", "level": 1, "next_stop": 5})
    assert bypass(walk, 4) == ["heading"]                                 # after a per-route breadcrumb
    walk["landmarks"]["main"] = True
    walk["skip_link"]["lands_at"] = 4
    assert bypass(walk, 4) == ["skip-link", "main-landmark", "heading"]
    walk["skip_link"]["lands_at"] = 1
    assert "skip-link" not in bypass(walk, 4) and not skip_link_broken(walk)
    tail = _walk("/", ["b1", "b2"], headings=[{"box": "bh", "level": 2, "landmark": "none", "next_stop": None}])
    assert bypass(tail, 2) == ["heading"]                                 # the block is the whole walk
    footer = _walk("/", ["b1", "b2"], headings=[{"box": "bh", "level": 2, "landmark": "contentinfo", "next_stop": None}])
    assert bypass(footer, 2) == []                                        # a footer heading skips nothing


def test_a_site_title_in_the_banner_is_not_the_content_start():
    walk = _walk("/", ["logo"] + HEADER + ["b5"],
                 headings=[{"box": "t", "level": 1, "landmark": "banner", "next_stop": 1}])
    peer = _walk("/about", ["logo"] + HEADER + ["b9"])
    assert repeated_stops(walk, [walk, peer]) == 5


def test_a_main_that_wraps_the_navigation_skips_nothing():
    walk = _walk("/", HEADER + ["b5"], nearest=["navigation"] * 4 + ["main"], in_main=[True] * 5)
    peer = _walk("/about", HEADER + ["b7"])
    walk["landmarks"] = {"main": True}
    rep = repeated_stops(walk, [walk, peer])
    assert rep == 4 and "main-landmark" not in bypass(walk, rep)
